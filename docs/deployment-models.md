# Deployment modes, topology and extension management

For the opt-in automated package/preload/restart workflow, see [on-premise extension lifecycle](onprem-extension-lifecycle.md). The older `configure` operation retains its manual preload-maintenance boundary.

> Portable configuration: start with [the external deployment setup](environment-portability.md). Addresses in this guide are documentation-only ranges, names are examples, and `/home/OPERATOR` means your controller account. Read measured results as anonymized historical evidence; obtain real values from your own inventory and discovery.

For complete controller preparation and runnable phase-by-phase instructions, use
[installation](installation.md). [Environment settings](environment-settings.md)
distinguishes defaults from examples; [feature controls](features.md) explains what
omission/disablement actually does. This chapter is the detailed model contract.

This guide describes the configuration-driven entry point `playbooks/postgresql.yml`, also selected by `site.yml` when `postgresql_deployment` is defined. It complements the [operator guide](operator-guide.md) and [safe re-execution guide](safe-reexecution.md). The implementation targets Ubuntu 22.04 with configurable PostgreSQL 14+. Majors below 14 and unsupported architectures fail explicitly; changing a version string never performs an upgrade.

## 1. Choose an operation before choosing a target

| `postgresql_operation` | Purpose | Changes permitted |
| --- | --- | --- |
| `plan` (default) | Discover resources, validate topology, report extensions and eligibility | None to target configuration or database data |
| `provision` | Create an explicitly admitted new standalone or Type A deployment; verify completed owned deployments | Guarded installation and initialization of new resources only; selected extension creation requires its own opt-in |
| `packages` | Install missing packages for a detected matching PostgreSQL instance | Exact pinned missing packages, only with installation opt-in; installed-version conflicts stop |
| `configure` | Enable selected extensions on an existing matching instance | Additive extension DDL after identity and plan approval; no preload changes, restart, role reassignment or promotion |

For reloadable PostgreSQL parameters, continue using `playbooks/reconcile.yml` and its separate reviewed parameter plan. `configure` does not replace that workflow. Historical `deployment_mode: bootstrap/resume/...` is the legacy HA lifecycle variable; it is deliberately distinct from `postgresql_deployment.mode`.

Global model values belong in an extra-vars YAML file, visible to both localhost validation and managed hosts. Do not distribute contradictory model copies in host variables. Inventory contains connectivity and per-node infrastructure values. Secrets belong in the existing protected secret workflow, never in examples or command-line passwords.

```bash
# Validate topology locally before any SSH connection.
ansible-playbook -i inventories/my-environment/hosts.yml \
  playbooks/model-validate.yml -e @my-environment.yml

# Verified SSH identities are required by the runner.
python3 tools/run_playbook.py playbooks/postgresql.yml \
  --inventory inventories/my-environment/hosts.yml \
  --known-hosts /protected/path/known_hosts \
  --extra-vars @my-environment.yml
```

The runner prompts for SSH/sudo credentials when configured for password authentication. Use its `--ssh-auth key` option for an appropriately provisioned SSH agent/key. Discovery executes tools and SQL observations and can produce normal host audit logs; it does not promise zero filesystem activity from Ansible itself.

## 2. Define exact membership

```yaml
postgresql_deployment:
  mode: cluster
  architecture: type_a
  major: '17'
  topology:
    primary: pg01
    replicas: [pg02, pg03]
    standby: [pg04, pg05]
    total_nodes: 5
    replica_count: 2
    standby_count: 2
  extensions: [pg_stat_statements, pg_stat_kcache, pgaudit, pgcrypto]
  extension_databases: [postgres]
postgresql_operation: plan
```

| Field | Meaning and selection | Impact of changing it |
| --- | --- | --- |
| `mode` | Explicit `standalone` or `cluster` | Selects implementation; switching an existing server does not convert/adopt it |
| `major` | Quoted integer PostgreSQL major of 14 or above | Must match the detected server; version mismatch stops before extension changes |
| `architecture` | Cluster-only, currently `type_a` | Future architectures need their own validated implementation |
| `topology.primary` | One inventory hostname; initial HA bootstrap primary | Must match `cluster.bootstrap_host`; never forces a running leader back after failover |
| `topology.replicas` | Named read replicas excluded from automatic promotion and synchronous selection | Patroni `nofailover: true`, `nosync: true` on fresh provisioning; existing policy differences require controlled maintenance |
| `topology.standby` | Named eligible HA/synchronous candidates | Patroni `nofailover: false`, `nosync: false`; eligibility is not a promise that every standby is currently synchronous |
| Optional count fields | Assertions against the declared host lists | Omit to derive counts; mismatches, duplicates and booleans fail validation |
| `extensions` | Explicit optional names from the registry | Adds desired dependencies; removal from this list never drops an existing extension |
| `extension_databases` | Existing databases in which extensions should exist; default `[postgres]` | Installation is per database, not per server; databases are never created implicitly |

All hosts in `postgres_cluster` must appear exactly once. Unknown keys, unknown hosts, multiple/conflicting role assignments and unsupported extensions fail controller validation. Do not use `--limit` for a partial cluster deployment; discovery requires the full selected inventory.

The opt-in [modular architecture](modular-deployment.md) supports other node counts and optional routing. Legacy Type A requires at least three PostgreSQL nodes and exactly three colocated etcd/router core nodes. For the five-node example, use `pg01`, `pg04`, `pg05` as the core and `pg02`, `pg03` as additional database nodes. Each database node runs Patroni and PgBouncer; only core nodes run etcd and routing. Declare independent failure domains in the existing environment contract. Five VMs on one hypervisor do not provide five independent failure domains.

Both replica and standby nodes use physical streaming replication. Here, “standby” means HA eligibility; it does not mean a separate cascading DR/Patroni standby cluster. Read replicas remain read-only. An eligible standby may become the runtime primary. Runtime validation requires one writer, common system identity, and a writer that is not designated a read replica.

Select `cluster.replication.synchronous_node_count` according to the required durability/availability tradeoff and available eligible standbys. The model rejects a strict synchronous count larger than the declared standby count. Size WAL senders, slots, connection pools, disk retention and backup capacity for the full node count using the existing environment contract.

## 3. Standalone workflow

An optional [storage layout](storage-layout.md) resolves a target-home or absolute
root and derives data/WAL/backup paths with mount admission. It takes precedence
over the legacy path defaults below and requires the documented prepared volumes.
Existing relocation is not automatic; external-WAL restore drills need separate
qualification.

Use one host in `postgres_cluster` with no members in `etcd_cluster` or `routers`. Start with [the standalone example](../examples/standalone.yml).

```yaml
postgresql_deployment:
  mode: standalone
  major: '17'
  topology:
    primary: pg01
    replicas: []
    standby: []
  extensions: [pgcrypto]
standalone:
  name: main
  storage_mount: /srv/postgresql
  data_dir: /srv/postgresql/data
  port: 5432
  listen_address: ''
  client_cidrs: []
```

The standalone role installs PostgreSQL and selected extension packages, creates its own `pg-standalone-<name>.service`, and does not invoke Patroni, etcd, PgBouncer, HAProxy or Keepalived. Its default connection is a local peer-authenticated Unix socket, `/run/pg-standalone-<name>`. It does not create application users or databases automatically.

| Standalone value | Default / requirement | How to select it and consequences |
| --- | --- | --- |
| `name` | `main` | Unique service/socket identity; changing it does not rename an existing deployment |
| `storage_mount` | Required existing ext4/XFS writable mount | Use a reviewed capacity/performance/failure domain; automation never partitions or formats it |
| `data_dir` | `/srv/postgresql/data` | New canonical path inside that mount; existing unowned directories and symlink traversal are refused |
| `port` | `5432` | Free local port; changing it affects clients and requires controlled maintenance |
| `listen_address` | Empty: local sockets only | For TCP, choose an IPv4 address already assigned to the host; no networking changes are made |
| `client_cidrs` | Empty | Canonical approved client networks; TCP requires a nonempty list, TLS and SCRAM |
| `tls.cert`, `tls.key`, `tls.ca` | Required existing paths for TCP | Certificate must validate to CA, cover the selected IP and have at least 30 days remaining; key must match and be private/readable by postgres |
| `shared_buffers_mb` | `128` | Size using measured RAM/workload budget, leaving room for OS cache and concurrent queries; restart-sensitive, never auto changed on rerun |
| `max_connections` | `100` | Match connection budget; use application pooling as needed; each connection consumes resources |
| `min_free_bytes` | `10737418240` (10 GiB) | Minimum admission headroom, not a capacity guarantee; raise for expected data growth and maintenance |
| `locale` | `C.UTF-8` | Installed locale controlling initial database collation; changing collation later requires a separate migration plan |

Before provisioning, approve exact package versions in `postgresql_package_versions`; configure and validate repositories separately. Run a plan, review discovery coverage and resources, then set:

```yaml
postgresql_operation: provision
postgresql_provision_confirmation: PROVISION pg01
postgresql_allow_package_install: true
postgresql_allow_extension_create: true  # only when selecting missing extensions
postgresql_package_versions:
  postgresql-common: '<reviewed exact repository version>'
  postgresql-17: '<reviewed exact repository version>'
  postgresql-client-17: '<reviewed exact repository version>'
```

The placeholders intentionally fail package validation. Obtain versions with `apt-cache policy` after repository administration; do not copy another environment's pins blindly. Optional separately packaged extensions require their own exact pins.

Fresh provisioning requires complete standard-root/mounted-filesystem discovery and no detected PostgreSQL/etcd data. Narrowing `discovery_scan_roots` cannot authorize fresh standalone initialization. An existing foreign installation should use an explicit endpoint and the existing-instance workflows below; this role never adopts it by writing an ownership marker.

After successful native SQL and configuration validation, a root-owned record stores system identity, declared policy and configuration fingerprints. Repeating the same completed provisioning verifies these; it does not rewrite configuration or restart/start an existing service. Policy drift, file drift, partial initialization or a stopped owned server stops for investigation. Failed new initialization is preserved; do not delete its data or ownership evidence simply to bypass admission.

Standalone has no HA, streaming replication or archive configuration. An optional logical backup schedule is now available through the [modular component controls](modular-deployment.md). Its minimal WAL configuration is not a PITR design. Before admitting production workloads, implement and restore-test a separately reviewed backup design, monitoring, application roles, retention and recovery objectives. Do not interpret successful provisioning as recovery readiness.

## 4. Fresh HA workflow and existing HA preservation

Start with a complete copy of the existing example inventory/environment contract and the [five-node model overlay](../examples/topology-five-nodes.yml). Fill node addresses, DNS, PKI, storage mounts, pinned packages, watchdog/fencing, pool limits, backup destination and recovery policy as described in the operator guide. The model overlay is not a replacement for that infrastructure contract.

Run local model validation and plan. Prepare repositories/storage/PKI through their separately authorized workflows. The model's `provision` operation delegates fresh HA work to `provision-cluster.yml`; it does not silently invoke networking or format storage. Its legacy fresh/bootstrap confirmation and `maintenance_approved_operations: [provision-cluster]` gate still apply. See [safe re-execution](safe-reexecution.md) for the exact maintenance contract.

All selected extension package transactions are prevalidated before fresh deployment. Native extension control/catalog availability is then checked against installed packages. Fresh Patroni configuration includes the selected preload libraries before first PostgreSQL startup; existing servers never receive an automatic preload restart.

If all HA ownership records already exist, `provision` selects verification rather than replaying bootstrap. Partial ownership stops. Existing role-policy mismatches stop before extension DDL. Adding hosts to an existing inventory is not an automatic scale-out migration: establish an explicit join/backup/fencing plan, then use the appropriate controlled provisioning procedure. The topology model supports larger fresh deployments without pretending that arbitrary live topology transitions are nondisruptive.

## 5. Extension registry and prerequisites

| Extension | Baseline or optional | Package example for major 17 | Preload / dependency |
| --- | --- | --- | --- |
| `plpgsql` | Mandatory baseline, normally already installed | `postgresql-17` | None |
| `pgcrypto` | Optional | `postgresql-17` | None |
| `pg_stat_statements` | Optional | `postgresql-17` | `pg_stat_statements` preload |
| `pg_stat_kcache` | Optional | `postgresql-17-pg-stat-kcache` | Automatically selects `pg_stat_statements`; preload statements first, then kcache |
| `pgaudit` | Optional | `postgresql-17-pgaudit` | `pgaudit` preload |

The project's existing baseline does not require any of the four optional extensions. Audit logging policy and query-statistics privacy/retention are environment decisions; enabling an extension is not a complete audit/monitoring policy. Installed packages alone do not create database extensions.

Package names derive from the selected qualified major. Package resolution is simulated before installation; unavailable pins, removals, upgrades of installed dependencies and repair transactions stop. Existing requested package versions must match pins. No unattended extension upgrade, `DROP EXTENSION`, `CASCADE`, database creation or preload rewrite occurs.

For an existing server, follow this sequence:

1. Declare the model, optional extensions, database list and an explicit `postgresql_instance` endpoint if it differs from the managed defaults.
2. Run `plan`. Review detected major, system identifier, current versions, missing control files, required preloads and schema safety.
3. If packages are missing, select `packages`, provide exact pins and set `postgresql_allow_package_install: true`. Re-run plan afterward.
4. If preloads are missing, arrange separately reviewed configuration and a controlled restart through the server's existing manager. Preserve existing preload entries and validate compatibility; this extension workflow stops until they are active. Re-run plan after any restart.
5. Review the writer's `plan_sha256`. Set `configure`, the expected system identifier, the writer's exact plan hash and `postgresql_allow_extension_create: true`.
6. Apply. The actual writer creates missing extensions in dependency order. Verify all selected databases and replicas. Repeat: satisfied extensions report unchanged, preserving their versions.

```yaml
postgresql_operation: configure
postgresql_instance:
  socket_dir: /run/postgresql  # discover the real local socket first
  port: 5432
  owner: postgres
  expected_system_id: '<observed system identifier>'
postgresql_extension_plan_sha256: '<writer plan_sha256 from the latest plan>'
postgresql_allow_extension_create: true
postgresql_extension_schema: postgres_extensions
```

For Type A use `/run/pg-ha-patroni`, and optionally `postgresql_instance.patroni_config` if its real path differs. Endpoint overrides select a target; they do not move files or change ports. A major or identity mismatch stops. The fingerprint includes observations, so a changed plan or restarted server requires review again when DDL is needed.

The default extension schema is `postgres_extensions`; installed extensions retain their existing schemas and versions. New extensions require a schema owned by a superuser and without CREATE rights for untrusted principals. This prevents extension installation scripts from resolving hostile objects in an attacker-controlled schema. The guard checks ownership even if an owner revoked its own CREATE privilege, and rechecks inside the transaction. The automation does not rewrite ACLs to make an unsafe schema acceptable. Fixed extension schemas are accepted only when compatible with the selected schema or `pg_catalog`.

Changes are transactional **per database**, not across all databases. A later failure reports previously completed databases. On an uncertain connection/commit outcome, inspect and replan; never drop successfully installed extensions as an automatic rollback. Physical replicas receive extension DDL through WAL, but must have compatible packages available locally.

## 6. Safe changes and extensibility

Use plan output to distinguish compliant resources, missing resources and intervention conditions. Fresh initialization, package installation and extension DDL have separate admission gates. Unknown infrastructure stays untouched. No network address, filesystem, replication policy or existing service is changed merely because the model differs.

Configuration rollback means restoring a reviewed prior file/policy through the existing manager and validating it. Package downgrade, topology changes, extension upgrades and major-version migration require separate tested procedures. A file backup is not a database backup.

To add a future capability, extend `module_utils/deployment_model.py` with explicit supported combinations, implement a separate reusable role/adapter, add negative admission tests and native acceptance tests, and document migration/rollback limits. Adding a major to `SUPPORTED_MAJORS` alone is insufficient: qualify OS repositories, binary paths, package dependencies, SQL behavior, Patroni compatibility, native templates and restore/failover behavior. Unknown roles/architectures remain rejected until implemented.

## 7. Validation and limits

Run `python -m unittest discover -s tests` and, from the supported Linux controller, `python3 tests/ansible_validation.py`. The isolated `tests/extensions_acceptance.yml` fixture refuses an existing test directory, tests additive creation and no-op repetition, checks preload and unsafe-schema refusal, compares server start identity, and shuts down its private socket-only server while retaining evidence.

Read the dated validation record for what was actually exercised. Model/unit/syntax tests do not establish fresh-OS standalone deployment, five-node failover, backup readiness or arbitrary version compatibility. Qualify those in a representative staging environment before production adoption.

## References

- [PostgreSQL 17 CREATE EXTENSION: privileges, schemas and installation security](https://www.postgresql.org/docs/17/sql-createextension.html)
- [PostgreSQL 17 supplied modules](https://www.postgresql.org/docs/17/contrib.html)
- [pg_stat_kcache prerequisites and configuration](https://github.com/powa-team/pg_stat_kcache)
- [pgAudit installation and version compatibility](https://github.com/pgaudit/pgaudit)
