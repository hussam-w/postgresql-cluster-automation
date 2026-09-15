"""Validate the inventory-wide PostgreSQL reload plan and convergence."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from module_utils.reconcile_policy import plan_settings


def reconciliation_errors(scans, converged=False):
    records = [result for scan in scans for result in scan.get('results', [])]
    errors = []
    for record in records:
        if record.get('failed') or 'report' not in record:
            errors.append('A SQL observation failed; no further changes are admitted')
            continue
        report = record['report']
        desired = record['item'].get('parameters', {})
        peers = records if report['manager'] == 'patroni' else [record]
        for peer in peers:
            other = peer.get('report', {})
            if other.get('identity', {}).get('system_id') != report['identity']['system_id']:
                continue
            plan = plan_settings(desired, other['settings'], other['identity']['version']) if desired else {'changes': {}, 'blockers': []}
            if desired and report['manager'] == 'patroni':
                if other['manager'] != 'patroni':
                    errors.append('Every member must be inspected with manager=patroni before a cluster-wide change')
                for name in plan['changes']:
                    if name in other.get('local_overrides', []) or str(other['settings'][name].get('sourcefile', '')).endswith('/postgresql.auto.conf'):
                        errors.append(name + ': member has a local override; preserve it and review ownership')
            errors.extend(plan['blockers'])
            if converged and plan['changes']:
                errors.append('Desired reload settings have not converged on system ' + report['identity']['system_id'])
        errors.extend(report['plan']['blockers'])
    return sorted(set(errors))


class FilterModule:
    def filters(self):
        return {'reconciliation_errors': reconciliation_errors,
                'reconciliation_summary': lambda results: [
                    {key: result.get('report', {}).get(key) for key in
                     ['identity', 'manager', 'plan', 'plan_sha256']} if 'report' in result else
                    {'intervention': result.get('msg', 'SQL observation failed')} for result in results]}
