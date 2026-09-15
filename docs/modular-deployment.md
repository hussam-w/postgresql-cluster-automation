# Modular topology, components and deployment scenarios

For the opt-in automated package/preload/restart workflow, see [on-premise extension lifecycle](onprem-extension-lifecycle.md). The older `configure` operation retains its manual preload-maintenance boundary.

This guide describes the opt-in modular profile. Existing Type A inventories retain their original component requirements. Ubuntu 22.04 amd64 remains the supported target platform; selecting PostgreSQL 14+ does not establish compatibility with every future server or extension release. New topology paths require staging deployment and failover qualification. A PostgreSQL 17 existing three-node Type A cluster has now passed native logical backup/restore acceptance; this does not qualify fresh modular topologies.

## 1. Select a model and inventory

Copy [modular-single.yml](../examples/modular-single.yml) or [modular-ha.yml](../examples/modular-ha.yml) into your ignored local inventory directory as `model.yml`. Start with the [controller and inventory setup](environment-portability.md), including verified SSH host keys. The HA model is an overlay onto the complete HA policy inventory; it does not replace storage, TLS, package pins, firewall, fencing or credentials configuration.

Set `postgresql_version` once and supply compatible exact package pins. List every database machine in `postgres_cluster`. In a cluster, choose 1, 3 or 5 colocated consensus voters in `etcd_cluster`; the initial primary must be one of them. Use independently failing machines for quorum. Put the selected routers in `routers`; routers must be a subset of consensus voters. With routing disabled, keep `routers` empty. Standalone has exactly one database host and empty consensus/router groups.

These playbooks configure existing inventory machines; counts do not create VMs. Give every database host exactly one role: initial primary, read replica, or eligible standby. Read replicas are excluded from automatic promotion and synchronous selection. The initial-primary setting does not move leadership after failover.

## 2. Configure the controls

| Setting | Default in modular examples | Meaning and change impact |
| --- | --- | --- |
| `postgresql_deployment.mode` | `standalone` or `cluster` by example | One independent server or Patroni-managed cluster; changing this is a migration |
| `postgresql_deployment.architecture` | `modular` in cluster example | Enables flexible quorum and routing topology; omitted cluster architecture retains Type A |
| `primary_node` | `pg1` in HA example | Inventory name of the initial leader |
| `replica_nodes` / `replica_count` | `[]` / `0` | Read-only, non-promotable hosts and exact count assertion |
| `standby_nodes` / `standby_count` | `[pg2, pg3]` / `2` | Eligible streaming standbys and exact count assertion |
| `allow_degraded_topology` | `false` | Explicitly acknowledges fewer than three consensus voters or no eligible standby; these configurations are not HA |
| `enable_backup` | `false` | Install primary-only logical backup scheduling when enabled |
| `backup_target_path` | unset | Required absolute, protected per-host destination when enabling backups |
| `backup_schedule` | `*-*-* 02:15:00 UTC` | systemd calendar expression; timer adds up to five minutes of random delay and catches missed runs |
| `enable_haproxy` | cluster `true`, standalone `false` | Deploy HAProxy and Keepalived/VIP together, or use direct database endpoints |
| `postgresql_extensions` | `[]` | Optional extensions; mandatory `plpgsql` remains |
| `postgresql_extension_registry` | `{}` | Approved custom dependency/package/preload descriptors |
| `postgresql_operation` | `plan` | Observe first; `provision` creates an admitted fresh deployment; `components` maintains backup scheduling on an identified existing instance |

The example models bind these variables to `postgresql_deployment`. Custom models must retain those bindings to consume environment overrides. The runner accepts literal `ENABLE_BACKUP=true/false`, `ENABLE_HAPROXY=true/false`, and `BACKUP_TARGET_PATH` in `.env` or process environment. CLI `--enable-backup`, `--enable-haproxy`, and `--backup-target-path` take precedence. Boolean spellings such as `yes` or `1` are rejected. YAML uses unquoted `true`/`false`.

For different destinations on different servers, omit the global backup destination override and set `backup_target_path` in each host's variables. Explicit global extra-vars override host settings. Paths are target-server absolute paths, never controller `$HOME`; use the existing [storage path resolution](environment-settings.md) for target-home-based layouts and supply the resulting absolute backup destination.

## 3. Example scenarios

| Scenario | Database roles | Consensus voters | Routing | Required policy |
| --- | --- | --- | --- | --- |
| Single server | One primary | None | Off | Standalone model |
| Normal HA | One primary, two eligible standbys | Three | On or off | Independent failure domains and reviewed synchronous policy |
| HA with read scaling | One primary, two eligible standbys, two read replicas | Three or five | On or off | Set both role lists and matching counts; pre-provision five machines |
| Two database servers | One primary, one standby | One | On or off | `allow_degraded_topology: true`; consensus has a single failure point |
| No eligible standbys | Primary plus zero or more read replicas | One, three or five, limited by available hosts | On or off | Degraded opt-in, async replication, synchronous count zero, explicit async data-loss acknowledgment |
| One Patroni database | Primary only | One | On or off | Same degraded/async acknowledgment; standalone is usually simpler |

For zero eligible standbys, set `cluster.replication.mode: async`, `synchronous_node_count: 0`, and `acknowledge_async_data_loss: true` in the existing replication policy. For synchronous mode, size the count within the eligible standby list: strict synchronous replication can block writes when that many standbys are unavailable. A single router is also a routing failure point even if database failover is available.

Plan first:

```bash
python3 tools/run_playbook.py playbooks/postgresql.yml \
  --extra-vars @inventories/local/model.yml
```

Review discovery, selected packages, topology and proposed extension changes. Follow the existing [installation admission steps](installation.md) for exact package pins, credentials, mounted storage, TLS, bootstrap confirmation and extension creation approval; then run the same model with `--extra-vars postgresql_operation=provision`. The model does not bypass those safeguards. Existing clusters with different roles, data or architecture stop for controlled maintenance. Editing host counts is not an online membership migration.

## 4. HAProxy enabled or direct connections

With HAProxy enabled, reserve an appropriate VIP, configure its certificate identity and use the existing write/read ports (defaults 5000/5001). HAProxy selects role-appropriate PgBouncer backends using Patroni health. It does not examine SQL to split statements. A one-database topology exposes only the write frontend because there is no replica backend.

With HAProxy disabled, HAProxy/Keepalived packages, routing configuration and VIP management are skipped. No VIP or VIP DNS is required by this profile. Patroni, PgBouncer, TLS, consensus and fencing remain cluster requirements. The certificate helper accepts `--direct` to omit VIP arguments and VIP certificate SANs.

Use direct PostgreSQL endpoints on the configured database port (default 5432), approved client CIDRs, and a separately reviewed firewall allowing those connections. Configure clients with a list of actual node certificate names, CA validation and `target_session_attrs=read-write` for writes; use `read-only` only when a standby is available. For example, the libpq connection parameters are `host=pg1.example.net,pg2.example.net,pg3.example.net port=5432 sslmode=verify-full sslrootcert=/secure/ca.crt target_session_attrs=read-write`. Supply database, user and credentials through protected client configuration. Multi-host selection applies when connecting; applications must reconnect after failure and handle uncertain transaction outcomes. See [PostgreSQL multi-host connections](https://www.postgresql.org/docs/14/libpq-connect.html).

Turning this switch off on an existing routed cluster does not dismantle routers or migrate clients. Plan that transition separately; preservation gates can refuse changed owned configuration.

## 5. Backup destination, operation and recovery

The new toggle schedules custom-format `pg_dump` for each connectable non-template database plus `pg_dumpall --globals-only`. It is a logical backup, not a physical replica seed or WAL/PITR service. Each database has its own snapshot; the set is not an atomic cross-database snapshot. Avoid concurrent database/role/DDL changes during the backup window. The runner checks cluster identity, primary status, server start time and database membership before/after dumping, but those checks cannot detect every concurrent metadata change.

Prepare an encrypted, capacity-monitored dedicated backup volume outside PGDATA, WAL and etcd directories. Follow the existing [storage instructions](installation.md) to mount it persistently using a stable device identity; do not format an existing volume. The role does not create mounts or require the destination itself to be a mountpoint. Confirm the intended filesystem using `findmnt -T /srv/pg-storage/backups/repository` before enabling it. A missing mount must not silently send production backups to a small root filesystem: add and verify the appropriate site mount dependency before deployment.

Supported destination roots are `/srv`, `/data`, `/mnt`, `/var/backups`, or `/home/USER`. Use a canonical absolute path with no symlink aliases or traversal. An existing destination must already be a dedicated postgres-owned directory with mode 0700; incompatible ownership is refused rather than changed. Parent directories must permit postgres traversal. The role creates a missing leaf directory, never wipes its contents. For example, select `backup_target_path: /srv/pg-storage/backups/repository`.

Enable the timer during admitted provisioning, or on an existing instance select `postgresql_operation: components` and provide `postgresql_instance.expected_system_id` from the observed plan. Retain the matching socket directory/port and model. This operation changes backup scheduling, not database contents, extension DDL or routing topology. Schedule/path updates preserve prior configuration copies and backup files.

The units are `pg-ha-logical-backup-NAME.timer` and `.service`, where NAME is `cluster.name` or `standalone.name` (default `main`). Run an initial backup explicitly and inspect it before relying on the schedule:

```bash
sudo systemctl start pg-ha-logical-backup-main.service
sudo systemctl status pg-ha-logical-backup-main.timer
sudo journalctl -u pg-ha-logical-backup-main.service
```

Replace `main` with your configured name. Cluster timers run on each node; only the current primary dumps locally. After failover, backup history can be distributed across different node volumes. Arrange independent offsite copies and an inventory of those locations. No automatic retention deletion or offsite upload is implemented. Monitor disk capacity, timer failures and the age of the last complete backup externally.

Completed timestamped directories contain dumps, globals and a SHA-256 manifest. Failures retain a `.partial` directory for inspection, never publish it as complete, and do not delete older backups. Globals contain sensitive role information, including password hashes; protect copies and restore environments accordingly. `pg_restore --list` checks readability, not recoverability. See [pg_dumpall behavior](https://www.postgresql.org/docs/17/app-pg-dumpall.html).

Restore qualification must use an isolated target of a compatible PostgreSQL version with required extension binaries. Verify manifest checksums, review globals for role/tablespace conflicts and environment-specific paths, restore approved globals, then restore each custom dump with `pg_restore --create` against a maintenance database. Resolve ownership and existing-database conflicts deliberately; do not add `--clean` against a live environment. Validate application queries, permissions and measured recovery time. Dumps do not include operating-system settings, certificates or deployment secrets; preserve those separately. Choose schedule, offsite copy frequency and retention from your RPO/RTO rather than assuming the daily default satisfies them.

To stop future scheduled backups, set `enable_backup: false` and explicitly run the identity-gated `components` operation. It disables only the managed timer; running jobs, backup data and configuration remain. A disabled fresh deployment installs no backup service. Merely planning or omitting backup settings never removes existing backups.

Modular clusters disable the legacy WAL archiver independently of this logical backup toggle. Legacy Type A pgBackRest/PITR workflows remain separate. Do not apply their archive-dependent recovery, monitoring or qualification commands to a modular deployment without adapting and testing them.

## 6. Extension selection and dependencies

Set `postgresql_extensions` to registered names, or leave it empty for no optional extensions. Built-ins include `pgcrypto`, `pg_stat_statements`, `pg_stat_kcache` and `pgaudit`. Packages derive from the selected major; dependencies are ordered and preloads deduplicated. Required exact package pins and extension creation gates still apply.

To add a reviewed distribution-provided extension, put a descriptor in the custom registry:

```yaml
postgresql_extensions: [hstore]
postgresql_extension_registry:
  hstore:
    package: 'postgresql-{major}'
    preload: []
    requires: []
```

Verify the actual package/control files for your repository before choosing this mapping. A descriptor has exactly `package`, `preload` and `requires`; dependency names must be registered and acyclic. Built-ins cannot be overridden. Custom packages must be available from approved repositories and compatible with the chosen server major. The automation cannot infer safe arbitrary third-party packages from an extension name.

Set `postgresql_deployment.extension_databases` to existing intended databases. Plan reports installed and missing extensions. Extra installed extensions are preserved. Removing a requested name does not drop it, uninstall its package or remove an active preload. Existing-server preload changes require a separately planned restart; automatic major/extension upgrades and arbitrary SQL installation scripts are outside this workflow.

## 7. Re-execution and qualification

Discovery, admission, configuration and verification remain separate. Correct resources are reused, existing database identities are checked, and unrelated resources are preserved or cause a safe stop. Backups are intentionally new outputs on each scheduled run; rerunning configuration does not run an extra backup or restart PostgreSQL.

The modular matrix has local model/syntax coverage for one, two, three and five database nodes, plus unit coverage through seven nodes. Backup tests simulate PostgreSQL tools while exercising real Linux locking and filesystem publication. These local tests alone do not establish runtime qualification. A subsequent real three-node PostgreSQL 17 Type A acceptance run passed model application, TLS routing, replication, logical dumping and isolated restore. Fresh modular provisioning, new-topology failover, mount-loss behavior and application recovery still require representative staging qualification.
