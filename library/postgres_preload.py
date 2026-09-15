#!/usr/bin/python3
"""Plan/add required preloads with exact identity, backups and DCS CAS; never restart."""
import copy, fcntl, hashlib, json, os, tempfile, re
from pathlib import Path
from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils.local_postgres import LocalPostgres, literal
from ansible.module_utils.extension_lifecycle import merge_preloads


def main():
    m = AnsibleModule(argument_spec={
        'socket_dir': {'type':'path','required':True}, 'port':{'type':'int','default':5432},
        'major':{'type':'str','required':True}, 'expected_system_id':{'type':'str','required':True},
        'required':{'type':'list','elements':'str','default':[]},
        'manager':{'choices':['patroni','standalone'],'required':True},
        'patroni_config':{'type':'path','default':'/etc/pg-ha/patroni/patroni.yml'},
        'standalone_name':{'type':'str','default':'main'},
        'operation':{'choices':['plan','apply'],'default':'plan'},
        'expected_plan_sha256':{'type':'str','default':''},
        'allow_restart':{'type':'bool','default':False},
    }, supports_check_mode=True)
    p=m.params; changed=False; backup=None
    try:
        if os.geteuid()!=0: raise ValueError('Root discovery required; SQL runs as postgres')
        db=LocalPostgres(p['socket_dir'],p['port'])
        identity=db.query("SELECT json_build_object('id',system_identifier::text,'major',current_setting('server_version_num')::int/10000,'data',current_setting('data_directory'),'started',pg_postmaster_start_time(),'recovery',pg_is_in_recovery(),'active',current_setting('shared_preload_libraries')) FROM pg_control_system()")
        if identity['id']!=p['expected_system_id'] or str(identity['major'])!=p['major']: raise ValueError('Server identity/major mismatch')
        errors=db.query("SELECT count(*) FROM pg_file_settings WHERE error IS NOT NULL AND (name IS DISTINCT FROM 'shared_preload_libraries' OR error <> 'setting could not be applied')")
        pending=db.query("SELECT count(*) FROM pg_settings WHERE pending_restart AND name <> 'shared_preload_libraries'")
        if errors or pending: raise ValueError('Unrelated configuration errors or pending restarts require separate maintenance')
        data=Path(identity['data']); auto=data/'postgresql.auto.conf'
        if data.resolve()!=data or auto.is_symlink(): raise ValueError('Aliased data/configuration path requires manual review')
        if not re.fullmatch(r'[a-zA-Z0-9_-]+',p['standalone_name']): raise ValueError('Invalid standalone service name')
        marker=Path('/var/lib/pg-ha/files.json') if p['manager']=='patroni' else Path('/var/lib/pg-standalone-'+p['standalone_name']+'.json')
        if not marker.is_file() or marker.is_symlink() or marker.stat().st_uid!=0 or marker.stat().st_mode & 0o077: raise ValueError('Protected managed file manifest required')
        owned=json.loads(marker.read_text())
        if p['manager']=='standalone':
            if owned['system_id']!=identity['id'] or owned['policy']['data_dir']!=identity['data']: raise ValueError('Standalone service ownership does not match runtime')
            owned=owned['files']
        for filename,metadata in owned.items():
            path=Path(filename)
            if not path.is_file() or path.is_symlink(): raise ValueError('Managed file missing or aliased')
            expected=metadata['sha256'] if isinstance(metadata,dict) else metadata
            if hashlib.sha256(path.read_bytes()).hexdigest()!=expected: raise ValueError('Managed configuration drift requires separate review')
            if isinstance(metadata,dict) and (path.stat().st_uid!=metadata['uid'] or path.stat().st_gid!=metadata['gid'] or format(path.stat().st_mode & 0o7777,'04o')!=metadata['mode']): raise ValueError('Managed file permission drift')
        before=auto.read_bytes() if auto.exists() else b''
        desired=merge_preloads(identity['active'],p['required'])
        dcs=None; dynamic=None
        configured=identity['active']
        if p['manager']=='patroni':
            from patroni.config import Config
            from patroni.dcs import get_dcs
            local=Config(p['patroni_config'],validator=None).copy()
            if Path(local['postgresql']['data_dir']).resolve()!=data: raise ValueError('Patroni does not own the selected data directory')
            if 'shared_preload_libraries' in local.get('postgresql',{}).get('parameters',{}): raise ValueError('Local Patroni preload override requires separate maintenance')
            if db.query("SELECT count(*) FROM pg_file_settings WHERE name='shared_preload_libraries' AND sourcefile="+literal(str(auto))): raise ValueError('ALTER SYSTEM override would mask DCS configuration')
            dcs=get_dcs(local); dynamic=dcs.get_cluster().config
            if not dynamic: raise ValueError('Existing DCS config required')
            configured=dynamic.data.get('postgresql',{}).get('parameters',{}).get('shared_preload_libraries',identity['active'])
            desired=merge_preloads(configured,desired)
        else:
            if (data/'patroni.dynamic.json').exists() or identity['recovery']: raise ValueError('Standalone ownership conflicts with replication manager')
            file_values=db.query("SELECT coalesce(json_agg(setting ORDER BY seqno),'[]') FROM pg_file_settings WHERE name='shared_preload_libraries' AND applied")
            configured=file_values[-1] if file_values else identity['active']
            desired=merge_preloads(configured,desired)
        target=','.join(desired)
        needs_config=merge_preloads(configured,[])!=desired
        needs_restart=merge_preloads(identity['active'],[])!=desired
        # Refuse unknown libraries before writing settings that could prevent startup.
        for name in desired:
            if not (Path('/usr/lib/postgresql')/p['major']/'lib'/(name+'.so')).is_file(): raise ValueError('Preload library unavailable: '+name)
        signature=hashlib.sha256(json.dumps({'identity':identity,'desired':desired,'dynamic':dynamic.data if dynamic else None,'auto':hashlib.sha256(before).hexdigest()},sort_keys=True).encode()).hexdigest()
        report={'identity':identity,'desired':desired,'needs_config':needs_config,'needs_restart':needs_restart,'plan_sha256':signature}
        if p['operation']=='plan' or m.check_mode: m.exit_json(changed=False,report=report)
        if not needs_config: m.exit_json(changed=False,report=report)
        if not p['allow_restart'] or signature!=p['expected_plan_sha256']: raise ValueError('Preload changes require restart opt-in and current plan hash')
        root=Path('/var/lib/pg-ha-extension-maintenance')
        if root.exists() and (root.is_symlink() or root.stat().st_uid!=0 or root.stat().st_mode & 0o077): raise ValueError('Unsafe maintenance backup directory')
        root.mkdir(mode=0o700,exist_ok=True)
        fd=os.open(root/'change.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
        fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        backup=tempfile.mkdtemp(prefix=identity['id']+'-',dir=root)
        saved=Path(backup)/'before.json'
        with saved.open('x') as stream: os.chmod(saved,0o600); json.dump(dynamic.data if dynamic else {'auto':before.decode()},stream)
        if dcs:
            candidate=copy.deepcopy(dynamic.data)
            candidate.setdefault('postgresql',{}).setdefault('parameters',{})['shared_preload_libraries']=target
            changed=True
            if not dcs.set_config_value(json.dumps(candidate),dynamic.version):
                changed=False; raise ValueError('Concurrent DCS update refused; replan')
        else:
            if (auto.read_bytes() if auto.exists() else b'')!=before: raise ValueError('Concurrent auto.conf change refused')
            changed=True; db.sql('ALTER SYSTEM SET shared_preload_libraries = '+literal(target))
        db.sql('SELECT pg_reload_conf()')
        m.exit_json(changed=changed,report=report,backup_directory=backup)
    except Exception as e:
        m.fail_json(changed=changed,backup_directory=backup,msg=str(e) if type(e) is ValueError else type(e).__name__+': inspect protected diagnostics; preserve state before retrying')

if __name__=='__main__': main()
