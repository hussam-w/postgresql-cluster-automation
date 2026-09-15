# Declarative extensions and on-premise lifecycle

This project configures your existing machines over SSH. It does not create VMs or call cloud APIs. The workflow is inspired by Autobase's explicit inventory and declarative extension controls, while retaining this project's preservation rules. The supplied `github.gvt` link was unavailable; the reference reviewed was [Autobase's official configuration](https://github.com/autobase-tech/autobase/blob/main/automation/roles/common/defaults/main.yml).

## Choose your environment interface

Copy [onprem.yml](../examples/onprem.yml) to an ignored local inventory directory and replace its host names, identity, paths and pins. It is a model overlay, not a replacement for the full HA inventory policy. For one independent PostgreSQL server, start with [modular-single.yml](../examples/modular-single.yml) and add the maintenance controls from the on-premise example. Keep one authoritative model per environment.

| Control | Default | Meaning |
| --- | --- | --- |
| `postgresql_deployment.mode` | Explicit | `standalone` or `cluster` |
| `topology.primary_count` | Derived as 1 | Exactly one writable primary per cluster; multiple primaries require separate clusters or a different replication architecture |
| `primary_node`, `replica_nodes`, `standby_nodes` | Example host lists | Initial primary, non-promotable readers, promotion-eligible streaming standbys |
| `replica_count`, `standby_count` | Match lists | Exact assertions; actual nodes must exist in inventory |
| `enable_haproxy` | Cluster true; standalone false | HAProxy/Keepalived/VIP or direct node endpoints |
| `enable_backup` | false | Managed logical-backup scheduling |
| `backup_target_path` | Unset | Protected absolute destination on the target machine |
| `storage_layout.root` | Opt-in | Unified data/WAL/backup layout for guarded fresh provisioning; existing data is never moved |
| `postgresql_extensions` | Empty list | Desired optional extensions |
| `postgresql_deployment.extension_databases` | postgres | Explicit existing databases receiving every selected extension |
| `extension_operation` | plan | Read-only discovery or explicit apply |
| `extension_package_policy` | pinned | Exact supplied pins; optional `installed_or_candidate` preserves installed versions and selects missing packages from approved apt metadata |
| `postgresql_allow_package_install` | false | Permit missing-package installation after simulation |
| `extension_allow_repository_changes` | false | Permit declared signed apt repository configuration |
| `extension_allow_restart` | false | Permit preload configuration and managed PostgreSQL restarts |
| `extension_allow_write_interruption` | false | Acknowledge maintenance effects, including synchronous standby and primary restart interruption |
| `extension_change_confirmation` | Empty | Apply requires `APPLY EXTENSIONS <expected system identifier>` |

The existing [modular guide](modular-deployment.md) explains consensus voter counts, degraded topology admission, direct-client connections, backup scheduling and mounting. PgBouncer remains part of the managed cluster architecture; arbitrary proxy products are not deployed by these flags. Editing counts does not add or remove members from a live cluster. No disks are formatted, and no addresses are changed by extension maintenance.

Environment/CLI selection is available when your model binds `extensions: '{{ postgresql_extensions }}'`:

```text
POSTGRES_EXTENSIONS=pgcrypto,pgvector,timescaledb
ENABLE_HAPROXY=true
ENABLE_BACKUP=true
BACKUP_TARGET_PATH=/srv/pg-storage/backups/repository
```

An empty `POSTGRES_EXTENSIONS=` requests no optional extensions. It never drops installed ones. CLI `--extensions pgcrypto,pgvector` overrides that environment value. The full model stays in YAML; credentials never belong in `.env`.

## Select extensions without modifying project code

Built-in descriptors cover pgcrypto, statistics/audit extensions, hstore, pg_trgm, citext, uuid-ossp, btree_gin, btree_gist, vector and timescaledb. The input alias `pgvector` becomes the actual SQL extension name `vector`. TimescaleDB includes its version-specific loader package and preload requirement.

Append desired names to the model list. Native dependencies from installed extension control files are resolved in dependency order. An unregistered name is accepted for discovery, with no invented package or preload mapping. If its control file is absent, the plan explains that availability is blocked. No automation can safely infer an arbitrary vendor repository, signing key, package name and restart contract from an extension name alone.

For third-party packages, supply a descriptor in `postgresql_deployment.extension_registry`:

```yaml
# Fragment inside your existing postgresql_deployment mapping:
extensions: [pgcrypto, custom_ext]
extension_registry:
  custom_ext:
    packages: ['postgresql-{major}-custom', libexample1]
    preload: [custom_ext]
    requires: [pgcrypto]
extension_databases: [appdb]
```

The example package names are placeholders for your approved vendor's real packages. The legacy singular `package` field remains supported and can be combined with `packages`. Use `packages: []` for a preinstalled extension. Apt resolves transitive system dependencies; the project refuses dependency upgrades/removals or repairs of existing installed resources. Descriptor dependencies are checked for missing entries and cycles. Built-ins cannot be silently overridden; identical historical custom descriptors are accepted. Remove a redundant older custom TimescaleDB/vector descriptor when using the new built-in mapping; conflicting descriptors stop for review.

A selected package must provide extension binaries compatible with the chosen PostgreSQL major and patch release. Package version pins refer to apt package versions, not `pg_extension.extversion`. Installed SQL extension versions are retained; this is additive installation, not an extension upgrade engine. Some extensions use fixed schemas or have special install/restore rules and can require reviewed integration work.

## Trust and package resolution

Repositories already configured on the machines can be reused. To configure another repository declaratively, distribute its verified, root-owned mode-0644 public signing key to each host first and provide a descriptor:

```yaml
extension_allow_repository_changes: true
extension_repositories:
  - name: vendor
    uri: https://packages.example.org/postgresql
    suite: jammy
    components: main
    signed_by: /usr/share/keyrings/vendor-archive.gpg
    key_sha256: 'REPLACE_WITH_VERIFIED_64_CHARACTER_LOWERCASE_SHA256'
```

Use the real vendor URL and independently verified key checksum. This intentionally invalid example is not a runnable trust configuration. The role checks the root-owned key and checksum, refuses foreign/unprotected repository files, backs up managed definitions, and updates apt metadata only after a repository change. It never executes a downloaded installer. Removing a descriptor does not remove an existing repository or signing key.

For repeatable deployments, supply exact versions through `postgresql_package_versions`. Alternatively, explicitly select `extension_package_policy: installed_or_candidate` for existing-cluster maintenance. That mode resolves installed versions first and missing-package candidates from configured repository metadata, requires identical requested versions on every node, then simulates the entire transaction before installation. Repository snapshots remain preferable for reproducible builds. No downgrade, dependency replacement or extension upgrade is automatic.

## First deployment

Use `playbooks/postgresql.yml` with the normal model and fresh-deployment admission described in [installation](installation.md). Selected signed repository descriptors can be applied before package validation when explicitly enabled. Supply exact fresh-deployment pins. The initial PostgreSQL/Patroni configuration includes selected preload libraries before the first start. Native control-file availability and schema safety must pass before extension creation.

## Add extensions to an existing deployment

1. Edit the environment's model list and database targets. Provide `postgresql_instance.socket_dir`, port, and the existing `expected_system_id` from discovery. Keep role lists consistent with the actual deployment.
2. Run the dedicated observation workflow. It checks the full inventory, OS, data identity, current extension controls and schema safety. Use narrow known data scan roots if a broad scan hits its bounded discovery limit; that scopes maintenance and does not certify that the entire host is empty.

```bash
python3 tools/run_playbook.py playbooks/extensions.yml \
  --extra-vars @inventories/local/model.yml
```

The runner uses the explicit inventory, verified host keys and authentication configured in `.env`; see [environment setup](environment-portability.md). The default is read-only. No package installation, restart or extension creation happens in plan mode.

3. Review the plan. Select package pins or the explicit candidate policy; set `postgresql_allow_package_install: true` only if missing packages are required. If new preloads are needed, set both restart/interruption flags true for an approved maintenance window. These flags are not claims of zero downtime. Set the confirmation string to the observed cluster identifier.
4. Reapply through the same entry point:

```bash
python3 tools/run_playbook.py playbooks/extensions.yml \
  --extra-vars @inventories/local/model.yml \
  --extra-vars extension_operation=apply
```

The workflow installs missing packages on all selected nodes first. It preserves active preload entries, checks managed configuration fingerprints, refuses unrelated pending restarts and local Patroni/ALTER SYSTEM overrides, and saves protected configuration backups. Patroni changes use DCS compare-and-swap to refuse concurrent writes. Standalone changes use PostgreSQL's ALTER SYSTEM and require the project's owned service/data identity.

When needed, replicas are processed before the initially observed primary, one at a time, through Patroni's own restart API via patronictl. Live mTLS member identity, health and replication lag are checked before and after each restart. Local SQL must return with the same system identifier and active required preloads before advancing. Strict synchronous writes can pause during a standby restart; the primary restart interrupts connections and may trigger a leadership change. Standalone restarts interrupt its only endpoint. There is no automatic switchover choreography or zero-downtime guarantee. See [Patroni restart semantics](https://patroni.readthedocs.io/en/latest/rest_api.html).

After maintenance, the actual writer is rediscovered. Missing extensions are created with `IF NOT EXISTS`, dependency ordering and transactional per-database schema checks. Physical replicas receive SQL changes through WAL but must already have the corresponding local packages. All target databases/replicas are verified afterward. Reapplying a satisfied desired state installs nothing, writes no preload setting and restarts nothing.

Use `psql -d appdb -c '\dx'` through the correct local socket to inspect installed extensions. New extensions normally use the protected `postgres_extensions` schema; qualify functions or configure an appropriately reviewed application search_path. Existing schemas, ACLs, versions and unrelated extensions are preserved.

## Failure handling and backup implications

The run stops before advancing after a failed node, identity mismatch, unhealthy cluster or native validation failure. Package/configuration/DDL steps are not one distributed transaction: an interrupted run can leave installed packages or staged DCS settings on some nodes. Inspect and replan; successfully installed extensions are never dropped as rollback. Protected preload backups live under `/var/lib/pg-ha-extension-maintenance`. Review only the intended previous parameter when rolling back DCS configuration, preserving any later unrelated changes. Never blindly restore a whole old DCS document.

A restart requires adequate client retries and a maintenance window. If a new library prevents startup, recover the failed member using the saved setting and existing manager before proceeding. This workflow refuses complex manually specified preload paths/quoting and foreign/unmanaged services rather than assuming ownership.

Keep backup policy separate from extension selection. TimescaleDB logical recovery needs its pre/post-restore functions; a generic PostgreSQL restore test does not qualify TimescaleDB recovery. See [TimescaleDB restore APIs](https://docs.tigerdata.com/api/latest/administration). Third-party extensions can require additional procedures that cannot be inferred from their names.

The new extension lifecycle has unit and Ansible syntax/model coverage. Its automatic preload/restart path has not yet been exercised on a native staging cluster. The earlier successful three-VM pgcrypto/logical-backup test predates this workflow and is not evidence for TimescaleDB/vector installation or rolling restart safety. Qualify the selected extension versions, failover behavior, application reconnection and restore procedures before production use.
