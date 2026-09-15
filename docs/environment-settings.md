# Environment settings: defaults, ownership and change impact

For the opt-in automated package/preload/restart workflow, see [on-premise extension lifecycle](onprem-extension-lifecycle.md). The older `configure` operation retains its manual preload-maintenance boundary.

See [modular deployment](modular-deployment.md) for the optional topology/component profile, its example files, configuration controls and qualification limits.

> Portable configuration: start with [the external deployment setup](environment-portability.md). Addresses in this guide are documentation-only ranges, names are examples, and `/home/OPERATOR` means your controller account. Read measured results as anonymized historical evidence; obtain real values from your own inventory and discovery.

Use this reference with [installation](installation.md), [feature controls](features.md) and the detailed [HA operator reference](operator-guide.md#6-complete-environment-variable-reference). **Reference deployment values are examples, never universal defaults.** In `inventories/example/group_vars/all.yml`, `null` means required and deliberately unspecified, not zero or automatic detection. The current addresses and small lab allocations must not be copied as production sizing.

## Where to put values

`postgresql_version` is the single selector in the supplied examples;
`postgresql_deployment.major` references it. The runner accepts `POSTGRES_VERSION`
or `--postgres-version`. See [version selection](postgresql-versions.md) for exact
precedence, package matrices, extension compatibility and existing-data safeguards.

For unified data/WAL/backup mounts, the optional [storage profile](storage-layout.md)
is the path source of truth. Set either `storage_layout.root` (absolute target
service path, e.g. `/srv/pg-storage`) or `storage_layout.home_user` (existing target
account, standalone home-based setup). Both have no default and are mutually
exclusive. `storage_paths` is a resolved fact, not an override. Profile-derived
data/WAL/repository fields replace the legacy desired paths only in memory; an
existing differing cluster is not moved or reinitialized. Use the same profile on
subsequent runs and qualify mount/restore behavior before admitting workloads.

| Location | Administrator-owned content | Boundary |
| --- | --- | --- |
| `inventories/<environment>/hosts.yml` | Groups, names, SSH destinations, direct HA node metadata | Exact membership; keep complete node metadata here if using the PKI generator |
| `inventories/<environment>/group_vars/all.yml` | Shared HA contract and common policy | A complete `cluster` mapping is needed for HA; do not copy it into minimal standalone inventory |
| `inventories/<environment>/host_vars/<host>/*.yml` | Per-host node/TLS/instance settings | Ansible host variables can override inventory declarations; keep copies consistent |
| External model YAML passed with `--extra-vars @...` | `postgresql_deployment`, standalone configuration, model operation | Shared controller/host visibility; extra-vars override inventory, so review their effective values |
| Short-lived operation YAML | Confirmations, approved exact operation names, identity/hash and reload/create permission | Do not permanently enable mutation intent in defaults |
| Protected native Linux secret directory | Vault, Vault key, CA/private keys | Restrict directory 0700/private files 0600; separate recovery copies and authorization |
| Roles/templates/modules | Implementation, fixed behavior and validators | Do not edit code just to change a supported environment value |

## Cross-mode configuration

Each row states purpose, actual default, requiredness, source, an example/change reason and failure impact. Unless stated otherwise, set these in the external model YAML; the implementing source is shown for auditability.

| Variable | Default / required / source | Purpose, example and when to change | Incorrect-setting impact |
| --- | --- | --- | --- |
| `postgresql_deployment.mode` | Required; model validator | `standalone` for one instance, `cluster` for Type A | Unsupported membership/architecture stops; no live conversion |
| `postgresql_deployment.major` | Required quoted integer >=14; model registry | Declares expected running/package major | Older majors fail; package/runtime checks apply; not an upgrade switch |
| `postgresql_deployment.architecture` | Cluster default `type_a`; model registry | Qualified HA architecture; omit standalone | Other values/standalone use rejected |
| `postgresql_deployment.topology.primary` | Required; model validator | Initial primary inventory name, e.g. `pg01`; HA must match `cluster.bootstrap_host` | Does not force current leadership; wrong assignment blocks |
| `postgresql_deployment.topology.replicas` | Empty list; model validator | Read-only, excluded from automatic promotion/sync; `[pg02, pg03]` | Conflicts/missing membership fail; changing existing policy stops |
| `postgresql_deployment.topology.standby` | Empty list, HA requires candidates; model validator | Eligible HA nodes, e.g. `[pg04, pg05]` | Too few eligible candidates undermine strict-sync availability; contract stops inconsistent count |
| `topology.total_nodes`, `replica_count`, `standby_count` beneath the model | Optional, derived when absent; model validator | Assert counts, e.g. `5`, `2`, `2`; do not allocate hosts | Mismatch/noninteger/duplicate membership stops |
| `postgresql_deployment.extensions` | `[]`; extension registry | Optional names, e.g. `[pgcrypto]`; dependencies and baseline are automatic | Unknown names fail; list removal does not uninstall |
| `postgresql_deployment.extension_databases` | `[postgres]`; model validator/module | Existing database names receiving DDL | Missing/inaccessible database stops; not automatic database creation |
| `postgresql_operation` | `plan`; model playbook | Explicit plan/provision/packages/configure intent | Wrong intent can request mutation but still needs admission; return to plan after work |
| `postgresql_package_versions` | No complete default; required pins when installing | Exact apt map, e.g. key `postgresql-17`; source `roles/packages_safe` | Missing/unavailable pins or installed-version mismatch stop. HA extension pins overlay `cluster.packages` |
| `postgresql_allow_package_install` | `false`; packages_safe | Permit missing-only selected package install after simulation | Does not authorize installed-package upgrades |
| `postgresql_allow_extension_create` | `false`; model/module | Permit reviewed additive DDL | False leaves compliant instances unchanged and blocks missing DDL |
| `postgresql_extension_schema` | `postgres_extensions`; module | Secure schema for newly created extensions | Untrusted owner/CREATE grants block; existing extension schema preserved |
| `postgresql_extension_plan_sha256` | Empty; model playbook | Exact latest writer plan for existing DDL | Stale/incorrect plan stops; never fabricate it |
| `postgresql_instance.socket_dir` | HA `/run/pg-ha-patroni`; standalone `/run/pg-standalone-<name>` | Override for a discovered existing local endpoint | Wrong endpoint fails or observes wrong instance; identity admission protects apply |
| `postgresql_instance.port` | Standalone port, otherwise HA PostgreSQL port/default 5432 | Match actual local socket port | Wrong port prevents observation |
| `postgresql_instance.owner` | `postgres`; model/module | Existing OS/SQL administrator for peer connection | Wrong ownership/authentication blocks; no sudo/auth weakening |
| `postgresql_instance.expected_system_id` | Empty; configure requires observed identifier | Quote the actual cluster lineage identifier | Wrong identity stops even a no-op configure |
| `postgresql_instance.patroni_config` | `/etc/pg-ha/patroni/patroni.yml` | Read actual Patroni role metadata for an existing HA instance | Wrong/template path fails or lacks role evidence |
| `postgresql_provision_confirmation` | Empty; standalone role | Exact `PROVISION <inventory-host>` for new initialization | Missing/mismatched confirmation stops |

### Standalone settings

Defined by `roles/standalone/defaults/main.yml` and validated by its tasks; put overrides in `standalone`, not `standalone_defaults`. All policy changes on a completed owned instance are detected and stopped rather than reapplied destructively.

| Setting under `standalone` | Default / requirement | Purpose and example selection | Failure/change impact |
| --- | --- | --- | --- |
| `name` | `main`, optional | Service/socket name, e.g. `billing` | Not a rename operation; changes paths and ownership-record identity |
| `storage_mount` | No usable default, required | Existing writable ext4/XFS mount, e.g. `/srv/postgresql` | Not a block device; missing/readonly/wrong filesystem stops |
| `data_dir` | `/srv/postgresql/data` | New canonical path inside reviewed mount | Existing unowned/symlink/overlap state is refused; moving live data needs migration |
| `port` | 5432 | Unused chosen socket/TCP port | Collision prevents start; client endpoint changes need maintenance |
| `listen_address` | Empty, local sockets only | Existing assigned IPv4 for TCP | TLS/CIDRs become mandatory; no address assignment |
| `client_cidrs` | `[]` | Canonical smallest approved client networks, e.g. `[192.0.2.0/24]` | Noncanonical/invalid CIDR fails; overly broad CIDR expands exposure |
| `tls.cert`, `tls.key`, `tls.ca` | Required only for TCP, no defaults | Existing absolute node paths, e.g. `/etc/company-db/server.crt` | Pairing, CA, IP identity, readability, key mode and 30-day lifetime validated; no automatic renewal |
| `shared_buffers_mb` | 128 | RAM allocation; select from measured total service/query/OS budget | Too large risks memory pressure; restart-sensitive changes require maintenance |
| `max_connections` | 100 | Concurrent backend budget, including administration | Excess concurrency wastes memory/CPU; too low rejects connections |
| `min_free_bytes` | 10737418240 | Admission headroom, increase for growth/recovery space | Not a hard capacity guarantee; insufficient space stops |
| `locale` | `C.UTF-8` | Initial collation/locale compatible with application | Missing locale fails initdb; later collation changes need a migration |

## Inspection and reload controls

Set shared discovery options in inventory/model extra-vars and `reconcile_instances` in each host's variables. The source contracts are `inspect.yml`, `reconcile.yml`, `postgres_reconcile.py` and `reconcile_policy.py`.

| Setting | Default / requirement | Purpose/example | Failure/change impact |
| --- | --- | --- | --- |
| `execution_mode` | `plan`, optional, legacy site dispatch | `reconcile` selects bounded reload workflow only when no model is defined | A model takes dispatch precedence; use `reconcile.yml` directly when both are needed |
| `discovery_additional_data_roots` | `[]` | Add nonstandard known paths to standard scan | Missing paths/permissions can leave coverage gaps; never authorizes cleanup |
| `discovery_scan_roots` | `[]`, standard scan | Reviewed narrower existing-instance scope | Cannot authorize fresh initialization; scope may omit unrelated data |
| `reconcile_instances` | `[]`, auto-detected observations | Explicit endpoint/manager/desired-parameter list | Multiple/ambiguous identities or insufficient visibility block apply |
| Instance `socket_dir`, `port`, `owner`, `database` | Required socket; 5432 / postgres / postgres | Match actual local existing server and administrative connection | Wrong target/authentication stops; no auto install/start |
| Instance `manager` | Observation default; explicitly standalone/patroni for mutation | Route changes via existing manager | Cannot adopt a server or bypass Patroni |
| Instance `patroni_config` | `/etc/pg-ha/patroni/patroni.yml` | Existing manager configuration | Wrong path prevents authority checks |
| Instance `parameters` | `{}` | Desired allowlisted settings, e.g. `log_min_duration_statement: 500ms` | Unsupported/restart-only setting fails; do not include replication/security/path policy |
| Instance `expected_system_id` | Required for apply | Observed quoted lineage | Mismatch stops |
| Instance `expected_plan_sha256` | Empty until reviewed | Exact observation/change fingerprint | Changed source state stops differing apply |
| Instance `allow_reload` | `false` | Explicit permission for a differing admitted parameter plan | Does not authorize restart |
| `reconcile_confirmation` | Empty | Exact `APPLY RELOAD SETTINGS` | Missing confirmation prevents apply |
| `reconcile_backup_root` | `/var/lib/pg-ha-reconcile`, optional | Protected configuration backup root, consumed by `reconcile.yml` | Must be dedicated absolute root-owned/private and non-symlink; protect copies as secrets; does not back up database data |
| `maintenance_intent` | Empty | `fresh` or `maintenance` for legacy helpers | Fresh refuses existing relevant state; maintenance still does not authorize data adoption/deletion |
| `maintenance_approved_operations` | `[]` | Exact helper names, e.g. `[monitoring]` | Nested helper imports each need their own name; no wildcard authorization |
| `deployment_mode` | `audit` in common defaults | Legacy HA lifecycle bootstrap/resume/verify | Distinct from architecture; wrong mode does not safely convert live state |
| `bootstrap_confirmation` | Empty | `CREATE <cluster.name>` or `RESUME <cluster.name>` | Resume requires exact incomplete ownership, not completed/foreign data |

The reload allowlist is `log_checkpoints`, `log_lock_waits`, `log_min_duration_statement`, `log_temp_files`, `deadlock_timeout`, and `checkpoint_completion_target`. These have **no project desired defaults**; omission preserves live values. Logging controls affect volume/privacy, duration/size thresholds affect diagnostic detail and disk usage, deadlock timeout affects detection/check overhead, and checkpoint completion target affects I/O distribution. Choose values from measured workload and PostgreSQL's reported units/ranges. All require a reviewed plan and reload when changed; none authorizes restart. See [safe re-execution](safe-reexecution.md) for backup and concurrent-change behavior.

## HA environment reference and defaults

The detailed per-setting purposes, example reference values, sizing guidance and consequences are in the operator guide's sections 6.1–6.10. The tables below make their requiredness/default/source explicit. Unless otherwise specified, define HA values in inventory `group_vars/all.yml`; per-node items belong to inventory/host_vars. Keep values in the two documents consistent during future changes.

| Variable | Actual default / requiredness | Definition / override location | Reference example or purpose | Selection rationale and consequences |
| --- | --- | --- | --- | --- |
| `postgres_cluster` | Required HA membership; no automatic host allocation | `inventories/<env>/hosts.yml` | All database members | At least three. Include initial extra replicas only after qualifying platform and monitoring assumptions; live additions need a membership procedure |
| `etcd_cluster` | Required HA membership; no automatic host allocation | `inventories/<env>/hosts.yml` | Exactly three initial voters | Must be PostgreSQL members; distribute over independently verified failure domains |
| `routers` | Required HA membership; no automatic host allocation | `inventories/<env>/hosts.yml` | Same three hosts as etcd | Additional routers are a different profile requiring validation changes |
| `ansible_host` | Explicit host/user; SSH port fallback 22 | Inventory/host vars; Ansible connection and discovery | SSH and service IP; pg1 `192.0.2.21`, pg2 `192.0.2.22`, pg3 `192.0.2.23` | Reachable from controller, not necessarily service IP. Update verified host-key mapping on legitimate host replacement |
| `ansible_user` | Explicit host/user; SSH port fallback 22 | Inventory/host vars; Ansible connection and discovery | `dbadmin` | Sudo-capable operator account. Coordinate privileges and recovery access |
| `ansible_port` | Explicit host/user; SSH port fallback 22 | Inventory/host vars; Ansible connection and discovery | SSH port, normally 22 | Match actual sshd and firewall; discovery separately receives `--port` |
| `node.address` | Required per relevant host; reference priority examples are not a universal default | `inventories/<env>/hosts.yml` or `host_vars`; HA contract | Stable service IP; for example `192.0.2.21` | Unique reserved IPv4, excluded from dynamic DHCP allocation and bound to the intended MAC. Used for listeners, peers, TLS, firewall and replication; changing is a network/identity migration |
| `node.dns_name` | Required per relevant host; reference priority examples are not a universal default | `inventories/<env>/hosts.yml` or `host_vars`; HA contract | E.g. `pg1.db.example.com` | Unique, resolvable from all peers and matching expected node identity/SAN. DNS changes require certificate and connectivity coordination |
| `node.interface` | Required per relevant host; reference priority examples are not a universal default | `inventories/<env>/hosts.yml` or `host_vars`; HA contract | `eth0` | Determine with `ip -br address` and routes. Required by this platform workflow on targets; wrong interface can break VIP/network access |
| `node.priority` | Required per relevant host; reference priority examples are not a universal default | `inventories/<env>/hosts.yml` or `host_vars`; HA contract | Unique router priority, 1–254 | Relative VRRP preference, not PostgreSQL priority. `nopreempt` means a recovered preferred router does not immediately reclaim VIP |
| `node.failure_domain` | Required per relevant host; reference priority examples are not a universal default | `inventories/<env>/hosts.yml` or `host_vars`; HA contract | E.g. `vm-pg1` | Use real rack/AZ/hypervisor placement evidence. Distinct strings alone do not prove independence |
| `node.firewall_sha256` | Required per relevant host; reference priority examples are not a universal default | `inventories/<env>/hosts.yml` or `host_vars`; HA contract | Normalized effective nftables digest | Obtained from project firewall inspection after reviewed policy application. Never invent or replace it merely to hide drift |
| `cluster.name` | No implicit default; required for selected HA contract | `inventories/example/group_vars/all.yml`; inventory group vars | `pg_ha` | Safe, unique identifier used for Patroni scope and backup stanza. Treat as initial identity; renaming is a migration |
| `cluster.bootstrap_host` | No implicit default; required for selected HA contract | `inventories/example/group_vars/all.yml`; inventory group vars | `pg2` | One core member selected to create the first PostgreSQL cluster. It does not pin future leadership |
| `cluster.etcd_token` | No implicit default; required for selected HA contract | `inventories/example/group_vars/all.yml`; inventory group vars | Unique initial cluster token | Prevent accidental initial cluster mixing; not a password. Preserve for the recorded initial plan; do not change to repair a live DCS |
| `cluster.vip` | No implicit default; required for selected HA contract | `inventories/example/group_vars/all.yml`; inventory group vars | `192.0.2.50` | Reserved unused address in common router subnet; ARP checks supplement IPAM, not replace it |
| `cluster.vip_prefix` | No implicit default; required for selected HA contract | `inventories/example/group_vars/all.yml`; inventory group vars | `24` | Actual subnet prefix, 1–32 with usable distinct host address; coordinate platform prefix |
| `cluster.vip_dns_name` | No implicit default; required for selected HA contract | `inventories/example/group_vars/all.yml`; inventory group vars | `postgres.db.example.com` | Stable client-facing name, pooler SAN and client configuration. DNS publication is external |
| `cluster.vrid` | No implicit default; required for selected HA contract | `inventories/example/group_vars/all.yml`; inventory group vars | `51`, allowed 1–255 | Avoid conflicts with other VRRP instances on the same network; change all peers coherently |
| `cluster.client_cidrs` | No implicit default; required for selected HA contract | `inventories/example/group_vars/all.yml`; inventory group vars | `192.0.2.0/24` | Smallest approved application source networks as observed after NAT; HAProxy source ACL |
| `cluster.admin_cidrs` | No implicit default; required for selected HA contract | `inventories/example/group_vars/all.yml`; inventory group vars | `192.0.2.0/24` | Approved administrator source networks; affects routing ACL and PostgreSQL HBA. Does not independently open every host firewall path |
| `cluster.ports.postgres` | 5432; optional override | `module_utils/network_policy.py`; group vars | 5432 | PostgreSQL, poolers, replication, backup, local SQL checks |
| `cluster.ports.pgbouncer` | 6432; optional override | `module_utils/network_policy.py`; group vars | 6432 | Pooler listener, HAProxy backend, firewall |
| `cluster.ports.patroni` | 8008; optional override | `module_utils/network_policy.py`; group vars | 8008 | Patroni API, HAProxy health checks, monitor, peer firewall |
| `cluster.ports.etcd_client` | 2379; optional override | `module_utils/network_policy.py`; group vars | 2379 | Patroni DCS clients, etcd listener, checks/firewall |
| `cluster.ports.etcd_peer` | 2380; optional override | `module_utils/network_policy.py`; group vars | 2380 | etcd peer URLs/listener and peer firewall |
| `cluster.ports.write` | 5000; optional override | `module_utils/network_policy.py`; group vars | 5000 | HAProxy frontend, clients, monitor, firewall |
| `cluster.ports.read` | 5001; optional override | `module_utils/network_policy.py`; group vars | 5001 | Replica frontend, clients, monitor, firewall |
| `backup_port` | No default; required by managed backup selection | `roles/backup` and backup playbooks; group vars | Deployed 8432 | pgBackRest TLS servers and clients |
| `platform_ports.backup` | 8432; optional override | `roles/platform`; group or host vars | 8432 | Platform backup firewall port; keep aligned with `backup_port` |
| `cluster.postgres_mount` | No implicit default; required for selected HA contract | `inventories/example/group_vars/all.yml`; inventory group vars | `/srv/postgres` | Dedicated persistent database filesystem; account for data, indexes, WAL, temporary files and retained restore tests |
| `cluster.data_dir` | No implicit default; required for selected HA contract | `inventories/example/group_vars/all.yml`; inventory group vars | `/srv/postgres/data` | Dedicated subdirectory, not mount root or symlink; moving live data needs a storage migration |
| `cluster.etcd_mount` | No implicit default; required for selected HA contract | `inventories/example/group_vars/all.yml`; inventory group vars | `/srv/etcd` | Dedicated low-latency persistent filesystem |
| `cluster.etcd_data_dir` | No implicit default; required for selected HA contract | `inventories/example/group_vars/all.yml`; inventory group vars | `/srv/etcd/data` | Separate nonoverlapping etcd directory; never substitute an empty path during recovery |
| `cluster.allowed_filesystems` | No implicit default; required for selected HA contract | `inventories/example/group_vars/all.yml`; inventory group vars | `[ext4]` | Contract accepts ext4/xfs; supplied platform formatter creates ext4 only. Choosing xfs requires platform implementation work |
| `cluster.min_free_bytes` | No implicit default; required for selected HA contract | `inventories/example/group_vars/all.yml`; inventory group vars | 268435456 (256 MiB) | Admission floor, not a sufficient workload budget; set from outage/WAL growth and intervention time |
| `cluster.min_ram_mb` | No implicit default; required for selected HA contract | `inventories/example/group_vars/all.yml`; inventory group vars | 3500 | Minimum admitted host RAM, not allocated memory; leave room for all colocated services |
| `cluster.min_vcpus` | No implicit default; required for selected HA contract | `inventories/example/group_vars/all.yml`; inventory group vars | 2 | Minimum CPU admission; size from peak concurrency, latency and backup/replication overhead |
| `cluster.locale` | No implicit default; required for selected HA contract | `inventories/example/group_vars/all.yml`; inventory group vars | `C.UTF-8` | initdb locale: choose application collation requirements before creation. Changing later is a database migration/rebuild concern |
| `platform_volume_group` | Required when corresponding platform feature is selected | `roles/platform`; group or host vars | `data-vg` | Existing VG with enough unused extents; discover with `vgs`/`lvs` |
| `platform_volumes[].name` | Required when corresponding platform feature is selected | `roles/platform`; group or host vars | `pg_ha_postgres`, `pg_ha_etcd`, `pg_ha_backup` | Must match `pg_ha_[a-z0-9_]+`; existing LV must have project ownership tag |
| `platform_volumes[].size` | Required when corresponding platform feature is selected | `roles/platform`; group or host vars | `6G`, `512M`, `1G` | Positive integer M/G size. Initial allocator refuses shrinking; it is not a complete live filesystem growth workflow |
| `platform_volumes[].mount` | Required when corresponding platform feature is selected | `roles/platform`; group or host vars | `/srv/postgres`, `/srv/etcd`, `/srv/pgbackrest` | Supported `/srv/<safe-name>` path; synchronize with data/repository locations |
| `platform_service_prefix` | Required when corresponding platform feature is selected | `roles/platform`; group or host vars | Prefix of stable secondary node addresses; 24 deployed | Match the actual LAN, routing and VIP plan |
| `platform_vip` | Required when corresponding platform feature is selected | `roles/platform`; group or host vars | Platform's VIP declaration | Keep equal to `cluster.vip`; duplicate declarations are a current implementation limitation |
| `platform_vip_dns` | Required when corresponding platform feature is selected | `roles/platform`; group or host vars | Platform hosts-file name | Keep equal to `cluster.vip_dns_name` |
| `platform_ssh_cidrs` | Required when corresponding platform feature is selected | `roles/platform`; group or host vars | Host firewall SSH source networks | Include actual controller/NAT source and approved recovery access before applying |
| `platform_client_cidrs` | Required when corresponding platform feature is selected | `roles/platform`; group or host vars | Host firewall application endpoint networks | Coordinate with cluster client/admin ACLs; both firewall and HAProxy must allow a connection |
| `platform_change_confirmation` | Empty; exact confirmation required for platform helper | `roles/platform`; group or host vars | Exact `PROVISION PLATFORM` operation control | Initial platform mutation authorization, not a permanent setting to enable arbitrary updates |
| `cluster.replication` | No implicit default; required for selected HA contract | `inventories/example/group_vars/all.yml`; inventory group vars | Existing value / units | How to select and what changes |
| `cluster.replication.mode` | No implicit default; required for selected HA contract | `inventories/example/group_vars/all.yml`; inventory group vars | `strict_sync` | Durability/availability policy; only `strict_sync` and `async` supported. Async permits data loss on promotion |
| `cluster.replication.acknowledge_async_data_loss` | `false`; required true for async | `inventories/example/group_vars/all.yml`; inventory group vars | `false` | Must be true for async. It records explicit acceptance, not a mitigation |
| `cluster.replication.synchronous_node_count` | No implicit default; required for selected HA contract | `inventories/example/group_vars/all.yml`; inventory group vars | 1 standby | Strict mode requires 1..N−1, async requires 0. More required acknowledgements increase failure-domain coverage but may block writes with fewer available standbys |
| `cluster.replication.maximum_lag_on_failover` | No implicit default; required for selected HA contract | `inventories/example/group_vars/all.yml`; inventory group vars | 1048576 bytes | Candidate eligibility bound; use measured WAL rate and loss tolerance. A byte bound is not a precise time/RPO guarantee |
| `cluster.replication.read_lag_bytes` | No implicit default; required for selected HA contract | `inventories/example/group_vars/all.yml`; inventory group vars | 1048576 bytes | HAProxy replica health threshold. Lower values reduce stale-read exposure but can remove replicas during bursts |
| `cluster.replication.ttl` | No implicit default; required for selected HA contract | `inventories/example/group_vars/all.yml`; inventory group vars | 60 seconds, minimum 20 | Leadership lease timing. Larger values can increase failover time; too small can destabilize under pauses |
| `cluster.replication.loop_wait` | No implicit default; required for selected HA contract | `inventories/example/group_vars/all.yml`; inventory group vars | 5 seconds | Patroni control loop interval; shorter increases coordination frequency/load |
| `cluster.replication.retry_timeout` | No implicit default; required for selected HA contract | `inventories/example/group_vars/all.yml`; inventory group vars | 5 seconds | Retry timing for coordination/database operations; allow measured latency without violating watchdog constraints |
| `cluster.replication.max_slot_wal_keep_size_mb` | No implicit default; required for selected HA contract | `inventories/example/group_vars/all.yml`; inventory group vars | 512 MiB | Bound on WAL retained by slots; too small can require replica recovery, too large threatens disk capacity |
| `cluster.replication.max_wal_senders` | No implicit default; required for selected HA contract | `inventories/example/group_vars/all.yml`; inventory group vars | 8 | Sender capacity for replicas and base-backup/maintenance activity; budget beyond steady replica count |
| `cluster.replication.max_replication_slots` | No implicit default; required for selected HA contract | `inventories/example/group_vars/all.yml`; inventory group vars | 8 | Slot capacity with maintenance headroom; does not itself create or safely remove slots |
| `cluster.postgres` | No implicit default; required for selected HA contract | `inventories/example/group_vars/all.yml`; inventory group vars | Existing value | Selection and impact |
| `cluster.postgres.max_connections` | No implicit default; required for selected HA contract | `inventories/example/group_vars/all.yml`; inventory group vars | 100 | Per-server connection ceiling. Budget all database pools, direct clients and maintenance. More connections increase resource pressure; inspect parameter context and restart requirements |
| `cluster.postgres.superuser_reserved_connections` | No implicit default; required for selected HA contract | `inventories/example/group_vars/all.yml`; inventory group vars | 5 | Emergency superuser capacity. Preserve enough for diagnosis; it reduces ordinary connection capacity |
| `cluster.postgres.shared_buffers_mb` | No implicit default; required for selected HA contract | `inventories/example/group_vars/all.yml`; inventory group vars | 512 MiB | PostgreSQL shared buffer allocation; local Patroni YAML. Leave memory for OS cache, queries, backup and all colocated daemons; restart required |
| `cluster.postgres.max_wal_size_mb` | No implicit default; required for selected HA contract | `inventories/example/group_vars/all.yml`; inventory group vars | 512 MiB | Checkpoint/WAL sizing target; tune from write rate and checkpoint behavior. It is not a hard disk-usage cap |
| `cluster.pool.mode` | No implicit default; required for selected HA contract | `inventories/example/group_vars/all.yml`; inventory group vars | `session` | Compatibility versus reuse; transaction mode requires application qualification |
| `cluster.pool.max_client_conn` | No implicit default; required for selected HA contract | `inventories/example/group_vars/all.yml`; inventory group vars | 200 | PgBouncer client ceiling and HAProxy global `maxconn`; include file descriptors and client retry bursts |
| `cluster.pool.default_pool_size` | No implicit default; required for selected HA contract | `inventories/example/group_vars/all.yml`; inventory group vars | 10 | Server pool size per user/database pool; many users multiply demand |
| `cluster.pool.reserve_pool_size` | No implicit default; required for selected HA contract | `inventories/example/group_vars/all.yml`; inventory group vars | 5 | Additional burst connections; include them in database capacity planning |
| `cluster.pool.max_db_connections` | No implicit default; required for selected HA contract | `inventories/example/group_vars/all.yml`; inventory group vars | 50 | Pooler server cap per database per node; multiple databases add up |
| `cluster.timeouts.connect_seconds` | No implicit default; required for selected HA contract | `inventories/example/group_vars/all.yml`; inventory group vars | 5 seconds | HAProxy connection/check timeout and pooler server connect timeout; too low rejects slow-but-valid paths |
| `cluster.timeouts.client_seconds` | No implicit default; required for selected HA contract | `inventories/example/group_vars/all.yml`; inventory group vars | 300 seconds | HAProxy client-side inactivity timeout; not SQL statement timeout |
| `cluster.timeouts.server_seconds` | No implicit default; required for selected HA contract | `inventories/example/group_vars/all.yml`; inventory group vars | 300 seconds | HAProxy server-side inactivity timeout; long silent queries/sessions may be disconnected |
| `cluster.etcd.heartbeat_ms` | No implicit default; required for selected HA contract | `inventories/example/group_vars/all.yml`; inventory group vars | 100 ms | Choose from measured peer RTT and scheduling latency across all voters |
| `cluster.etcd.election_ms` | No implicit default; required for selected HA contract | `inventories/example/group_vars/all.yml`; inventory group vars | 1000 ms | Must be at least five heartbeat intervals under this contract; too short causes elections, too long delays recovery |
| `cluster.etcd.quota_bytes` | No implicit default; required for selected HA contract | `inventories/example/group_vars/all.yml`; inventory group vars | 134217728 (128 MiB) | Database backend quota; size and alert from actual growth. Quota exhaustion can block coordination writes |
| `cluster.packages` | No implicit default; required for selected HA contract | `inventories/example/group_vars/all.yml`; inventory group vars | Exact apt version map | Must contain precisely the nine package names in the example; no wildcards. Includes PostgreSQL/common/client, Patroni, HAProxy, PgBouncer, Keepalived, psycopg2 and etcd3gw |
| `cluster.expected_versions` | No implicit default; required for selected HA contract | `inventories/example/group_vars/all.yml`; inventory group vars | Numeric Patroni/etcd/HAProxy/PgBouncer/Keepalived releases | Match actual binary output as well as apt pins. Minimum feature families are validated; etcd is restricted to 3.5.x |
| `cluster.etcd_artifact.url` | No implicit default; required for selected HA contract | `inventories/example/group_vars/all.yml`; inventory group vars | HTTPS release tarball | Correct OS/architecture and approved provenance; current installer is amd64-specific |
| `cluster.etcd_artifact.sha256` | No implicit default; required for selected HA contract | `inventories/example/group_vars/all.yml`; inventory group vars | Exact 64-character lowercase digest | Independently verify release artifact. A digest proves identity only when its source is trusted |
| `backup_package_version` | No default; required by managed backup selection | `roles/backup` and backup playbooks; group vars | Exact pgBackRest apt version | Separate from `cluster.packages`; qualify server/repository compatibility and restore |
| `backup_repository_host` | No default; required by managed backup selection | `roles/backup` and backup playbooks; group vars | `pg3` | Managed inventory host storing repository; relocation requires copying/validating history and changing transport/archiving coherently |
| `backup_repository_path` | No default; required by managed backup selection | `roles/backup` and backup playbooks; group vars | `/srv/pgbackrest/repository` | Dedicated repository path; include capacity, ownership and systemd writable paths |
| `backup_schedule` | `*-*-* 02:15:00 UTC`; optional | `playbooks/backup-schedule.yml`; group vars | Default `*-*-* 02:15:00 UTC` | systemd calendar expression; choose quiet period and validate calendar. Random delay is up to 300 seconds |
| `cluster.backup.archive_executable` | No implicit default; required for selected HA contract | `inventories/example/group_vars/all.yml`; inventory group vars | Generic archive helper path | Generic integration contract; with managed backup, native pgBackRest archive-push is selected instead |
| `cluster.backup.restore_executable` | No implicit default; required for selected HA contract | `inventories/example/group_vars/all.yml`; inventory group vars | `/usr/local/libexec/pg-ha/restore-wal` | WAL retrieval helper; receives filename then destination. Must return real retrieval failure |
| `cluster.backup.destination_description` | No implicit default; required for selected HA contract | `inventories/example/group_vars/all.yml`; inventory group vars | Human-readable repository description | Documentation only; does not provision an external destination |
| `cluster.backup.retention_description` | No implicit default; required for selected HA contract | `inventories/example/group_vars/all.yml`; inventory group vars | Two daily full backups | Documentation only; actual retention is fixed in pgBackRest template |
| `cluster.backup.rpo_seconds` | No implicit default; required for selected HA contract | `inventories/example/group_vars/all.yml`; inventory group vars | 60 seconds | Recovery objective and source for initial `archive_timeout`; zero maps to 60 in template. Neither value guarantees archive RPO under failures |
| `cluster.backup.rto_seconds` | No implicit default; required for selected HA contract | `inventories/example/group_vars/all.yml`; inventory group vars | 3600 seconds | Recovery time objective recorded in policy; not an enforced restore timeout |
| `application_databases[].name` | Required explicit database/owner list for HA initial applications | `inventories/example/group_vars/all.yml`; inventory group vars | `appdb` | Initial SQL database and pooler mapping; adding live requires separate role/database/pool/HBA workflow |
| `application_databases[].owner` | Required explicit database/owner list for HA initial applications | `inventories/example/group_vars/all.yml`; inventory group vars | `app_owner` | Existing authorized application role; ownership permits schema control, so design narrower runtime roles if needed |
| `vault_app_users[].name/password` | No plaintext default; required by selected HA/backup/application operation | Protected Vault file; never ordinary inventory values | Application login and random secret | Initial SCRAM role and pooler verifier. Rotation must synchronize database, poolers, applications and monitor |
| `vault_pg_superuser_password` | No plaintext default; required by selected HA/backup/application operation | Protected Vault file; never ordinary inventory values | Database service superuser secret | Protected privileged credential; rotate without losing Patroni access |
| `vault_pg_replication_password` | No plaintext default; required by selected HA/backup/application operation | Protected Vault file; never ordinary inventory values | Replicator secret | Coordinate across primary and all reconnecting receivers |
| `vault_patroni_api_password` | No plaintext default; required by selected HA/backup/application operation | Protected Vault file; never ordinary inventory values | API mutation credential for `operator` | Combined with management client TLS; never expose to application users |
| `vault_backup_cipher_pass` | No plaintext default; required by selected HA/backup/application operation | Protected Vault file; never ordinary inventory values | Repository encryption passphrase | Required for old backup recovery; changing text is not re-encryption/rotation |
| `tls_sources.<service>.ca/cert/key` | Required service-specific source paths | `host_vars/<host>/tls.yml`; protected controller PKI files | Per-host controller paths | Correct CA domain, DNS/IP SAN, EKU and matching key; files are copied with restricted ownership |
| `cluster.evidence.network_and_vrrp` | Required; no default | Example group vars / contract validator | Real change-ticket or test-artifact reference | Records supporting evidence for network and vrrp; a nonempty string does not prove the control works |
| `cluster.evidence.firewall_policy` | Required; no default | Example group vars / contract validator | Real change-ticket or test-artifact reference | Records supporting evidence for firewall policy; a nonempty string does not prove the control works |
| `cluster.evidence.fencing_test` | Required; no default | Example group vars / contract validator | Real change-ticket or test-artifact reference | Records supporting evidence for fencing test; a nonempty string does not prove the control works |
| `cluster.evidence.backup_restore_test` | Required; no default | Example group vars / contract validator | Real change-ticket or test-artifact reference | Records supporting evidence for backup restore test; a nonempty string does not prove the control works |
| `cluster.evidence.repository_provenance` | Required; no default | Example group vars / contract validator | Real change-ticket or test-artifact reference | Records supporting evidence for repository provenance; a nonempty string does not prove the control works |
| `cluster.evidence.monitoring_and_alerts` | Required; no default | Example group vars / contract validator | Real change-ticket or test-artifact reference | Records supporting evidence for monitoring and alerts; a nonempty string does not prove the control works |
| `cluster.evidence.exclusive_change_lock` | Required; no default | Example group vars / contract validator | Real change-ticket or test-artifact reference | Records supporting evidence for exclusive change lock; a nonempty string does not prove the control works |

## Paths, backup objects and monitoring values that are not switches

### Exact software and acceptance selectors

The HA package map requires exact pins for `postgresql-common`, `postgresql-17`,
`postgresql-client-17`, `patroni`, `haproxy`, `pgbouncer`, `keepalived`,
`python3-psycopg2` and `python3-etcd3gw`. The validator's minimum feature versions
are Patroni 4.0, etcd 3.5, HAProxy 2.4, PgBouncer 1.24 and Keepalived 2.2; etcd is
restricted to 3.5.x. A minimum is not a recommendation to install an untested new
release. Match `cluster.expected_versions.<component>` to installed binary output
and the approved package/artifact release. Optional separately packaged extension
pins belong in `postgresql_package_versions`; pgBackRest uses
`backup_package_version`. No exact package release is universally defaulted.

Recovery/export selectors belong in temporary operation files, not baseline
environment defaults. See operator guide section 10 for runnable commands.

| Variable | Default / required / source | Purpose and example | Wrong-setting impact |
| --- | --- | --- | --- |
| `restore_test_confirmation` | Empty; required by restore-verify | Exact `TEST ISOLATED RESTORE` | Does not authorize restoring over live data |
| `restore_test_dir` | Required; restore-verify | Unique allowed `/srv/postgres/restore-acceptance-<suffix>` | Existing target refused; each drill consumes retained disk space |
| `restore_recovery_type` | `immediate`; restore-verify | `time` only for explicit PITR | Immediate is consistency recovery, not a guarantee of latest WAL replay |
| `restore_target_time` | Required for time recovery; restore-verify | UTC `YYYY-MM-DD HH:MM:SS[.fraction]+00`; PITR fixture generates its own target | Wrong format is refused; wrong time may recover the wrong business state; independent validation required |
| `pitr_table` | `pg_ha_pitr_acceptance`; pitr-acceptance | Use a fresh `pg_ha_pitr_acceptance_<lowercase/digits>` name | Existing table collision stops; this writes test data |
| `backup_export_confirmation` | Empty; backup-export | Exact `EXPORT ENCRYPTED REPOSITORY` | Export can temporarily pause new backup admission; capacity/time budget needed |
| `export_id` | Required; backup-export/export-verify | Unique lowercase/digit/hyphen archive identifier | Reuse/collision or mismatched verification selects wrong evidence |
| `export_controller_dir` | Required; export helpers | Protected native `/home/<user>/.local/share/pg-ha/exports` | Fixed allowed path shape; inadequate storage/permissions fail; no off-site durability implied |
| `export_verify_host` | Required; export-verify | Inventory host distinct from repository | Wrong node or capacity prevents independent verification |

These selectors supplement `maintenance_approved_operations`, never replace it.
Other historical fault/migration selectors are scoped to their dated procedures;
they are not portable deployment settings or generic recovery interfaces.

| Requested setting | Actual implementation / default | Where/how to change and risk |
| --- | --- | --- |
| Separate WAL directory | Opt-in `storage_layout` derives external `wal/pg_wal` for fresh initialization/replica copies; otherwise legacy in-PGDATA WAL | See [storage layout](storage-layout.md). Existing relocation is refused; native WAL links are supported, arbitrary root symlink shortcuts are not |
| Tablespaces | Existing tablespaces are observed; no tablespace provisioning mapping | Plan outside current reconciler; creation/relocation affects recovery and capacity |
| Archive directory | Managed pgBackRest stores archive history in its repository; no independent archive-directory variable | Change tested backup integration, not descriptive text |
| S3 bucket/region/endpoint/credentials | No S3/object-storage adapter variables | External/archive integration or new qualified implementation required; do not put S3 keys into unrelated backup fields |
| Retention/encryption/compression | Fixed full retention 2, AES-256-CBC, zst in backup template | Descriptive retention text does not change policy; changing ciphertext/history behavior requires restore-qualified repository migration |
| Monitoring bind address/Prometheus | No Prometheus server/exporter listener provisioned | Current monitor uses existing service endpoints, local protected JSON and journald; external collection/alerts are separate |
| Global config/state relocation | Some defaults use `/etc/pg-ha`, `/var/lib/pg-ha`, but many paths are literal | Normally leave `config_root`, `state_root`, binary/service/socket paths unchanged; not universal supported relocation flags |
| Firewall device selection | Existing `node.interface`, network/CIDR/port policy; optional platform management | Discover interface and NAT sources, coordinate all layers; never assume `eth0` in another environment |
| Extension version upgrades | Existing versions retained; new extension uses available default version in reviewed plan | Package pins constrain artifacts; no separate SQL extension-version upgrade variable or automatic ALTER EXTENSION UPDATE |

## Normally keep consistent

Preserve data integrity, TLS verification, SCRAM, required HA watchdog, no-auto-rewind/removal policy, identity checks and exact version pins. Paths/service names that are fixed in several consumers should normally remain unchanged. Cluster name, DCS initial token and system identifiers become identities after bootstrap, not routine tuning values. Change addresses, domain names, accounts, secrets, capacities and recovery/retention decisions for each environment, but coordinate their dependent certificates, routes, listeners, clients and backup access.
