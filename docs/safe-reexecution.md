# Safe discovery, reconciliation and re-execution

> Portable configuration: start with [the external deployment setup](environment-portability.md). Addresses in this guide are documentation-only ranges, names are examples, and `/home/OPERATOR` means your controller account. Read measured results as anonymized historical evidence; obtain real values from your own inventory and discovery.

When `postgresql_deployment` is defined, `site.yml` dispatches to the model-aware workflow. Its default remains `postgresql_operation: plan`. Read [deployment models and extensions](deployment-models.md) for standalone provisioning, HA topology validation and additive extension management. The reloadable-parameter reconciliation and legacy maintenance gates described below remain separate operations.

This is the entry-point contract from 13 September 2026 onward. It supersedes older instructions that treated `site.yml` as the bootstrap command. An existing host is presumed to contain valuable configuration, data and workloads. Missing evidence is not evidence that it is empty.

## Choose the correct workflow

| Situation | Entry point | Default effect |
| --- | --- | --- |
| Unknown, fresh, standalone or managed environment | `playbooks/site.yml` or `inspect.yml`, with default observation intent | Observe and report; no managed configuration changes |
| Explicit architecture/extension model | `postgresql.yml`, or `site.yml` with `postgresql_deployment` defined | `postgresql_operation: plan` by default; explicit provision/packages/configure have separate scopes |
| Existing PostgreSQL with approved reload settings | `site.yml` with `execution_mode: reconcile`, or `reconcile.yml` | Inspect every host, validate the complete plan, apply only approved differences, inspect again |
| Already-compliant existing PostgreSQL | Same reconciliation entry point | No configuration write, backup, reload or restart |
| Existing project-managed HA cluster | `verify.yml` | Existing integrity, package, TLS, replication, DCS and routing checks |
| Fresh dedicated HA deployment | `deploy.yml`, with explicit provisioning approvals | Original protected Ubuntu 22.04/PostgreSQL 17 provisioning; never an adoption mechanism |
| Upgrade, replacement, networking, storage, failover, recovery or historical migration | Individually approved maintenance playbook | Separate reviewed procedure; never selected automatically by routine reconciliation |

The project does **not** automatically convert an arbitrary standalone database into Patroni, upgrade a PostgreSQL major version, adopt a foreign service unit, replace certificates or reconcile every possible operating-system setting. Those operations can disrupt workloads and require a specific migration procedure. Detecting such a condition produces a blocker or an observation, not a destructive attempt to make the host match a template.

## Routine execution

Use a Linux controller with the pinned Ansible collections. SSH identities must already have been verified. Target discovery uses existing tools and local database authentication; it does not install missing dependencies or weaken authentication to complete inspection.

```bash
python3 tools/run_playbook.py playbooks/site.yml \
  --inventory inventories/local/hosts.yml
```

The default mode is `plan`, independently of the legacy `deployment_mode` variable. No complete bootstrap architecture or Vault secret file is needed for this inspection. The inventory must contain `postgres_cluster`, `ansible_host` with an actual IPv4 address, and `ansible_user`. The group can contain a single standalone instance host or a complete HA cluster. Runtime connection details are detected where possible and can be supplied explicitly.

For a separate environment, supply its inventory and verified host-key file:

```bash
python3 tools/run_playbook.py playbooks/site.yml \
  --inventory inventories/customer-a/hosts.yml \
  --known-hosts /secure/customer-a/known_hosts \
  --ssh-auth key --become-auth passwordless
```

`--ssh-auth key` uses the configured SSH key/agent; it does not generate or copy keys. Password authentication remains available through hidden interactive prompts. `--become-auth passwordless` is appropriate only where the controller account already has the necessary approved sudo privileges. The runner still takes an exclusive controller lock. Other controllers and tools must observe the same maintenance coordination policy.

`--verbose` shows detailed metadata. Treat that output as operationally sensitive: it includes role/database names, paths and configuration hashes, although not password hashes, private key contents, connection secrets or full service configuration. Normal SSH/Ansible transport creates temporary files and authentication logs; “read-only” means no infrastructure/configuration mutation, not literally zero filesystem activity anywhere.

## What discovery examines

Infrastructure discovery collects OS/version, packages, unit state, addresses/routes, mounts/filesystems, capacity, firewall metadata, watchdog metadata and database/etcd state markers. It never opens the watchdog or changes networking. Systemd unit templates are reported as templates, not queried as running instances.

Running PostgreSQL instances are resolved from discovered data directories and local PID metadata, supplemented by `pg_lsclusters` and explicit socket definitions. A stale PID file or a denied SQL connection becomes an observation failure. Offline directories are retained and reported; the workflow never starts, initializes or repairs them automatically.

Authenticated local SQL checks read:

- PostgreSQL version, system identifier, start time, recovery state and effective configuration/HBA/ident paths.
- Existing databases and owners, roles and privilege flags, tablespaces and locations.
- Extensions in each connectable database, replication connections and replication slots.
- The approved parameter values, units, limits, source files, contexts and pending-restart flags.
- Configuration-file errors, included configuration file hashes and file ownership/modes.
- TLS enablement and certificate/key path metadata, without reading key contents into reports.

SQL runs as the declared database owner through a local Unix socket, using installed `psql`, without a password, startup file or shell. Inspection needs database administrator visibility. It does not run role/database/extension DDL. There is a 100-database extension-inspection bound; larger environments require a scoped audit. Unsupported pre-10 catalogs are refused. Parameter reconciliation accepts PostgreSQL 14+ and validates the running server metadata; older versions remain observation-only.

### Bounded filesystem scans

The default scan includes standard data locations and mounted data filesystems. PostgreSQL relation trees are pruned after detecting `PG_VERSION`. A depth, entry or time limit is reported explicitly and blocks applying changes. No filesystem scan proves that a whole server contains no unknown application data.

For a large **existing** environment, first review mounts, services and registered clusters. Then declare narrower `discovery_scan_roots` containing all database directories relevant to the proposed scope, and explicit local endpoints where necessary:

```yaml
discovery_scan_roots:
  - /srv/postgres/data
  - /srv/etcd/data
  - /var/lib/postgresql
  - /var/lib/etcd
```

This narrows an observation scope; it does not authorize deletion, adoption or bootstrap. `discovery_additional_data_roots` appends roots. Fresh-provisioning admission intentionally uses its own standard scan rather than accepting this narrowed scan as proof of emptiness. Missing inspection tools, permissions, unreachable hosts or unresolved SQL coverage block the apply phase.

## Configure an existing standalone instance

Put the following in that host's variables, replacing paths and values with discovered facts:

```yaml
reconcile_instances:
  - socket_dir: /var/run/postgresql
    port: 5432
    owner: postgres
    database: postgres
    manager: standalone
    expected_system_id: 'REPLACE_WITH_DISCOVERED_SYSTEM_IDENTIFIER'
    parameters:
      log_min_duration_statement: 500ms
    allow_reload: false
    expected_plan_sha256: ''
```

Run the plan. Review `identity`, `plan.changes`, `plan.compliant`, `plan.blockers` and `plan_sha256`. The hash covers the observed identity/start time, source-file hashes and permissions, current selected settings, requested values and configuration manager. For Patroni it also covers the current dynamic configuration.

Only after reviewing the proposal, copy the exact `plan_sha256` into `expected_plan_sha256` and set `allow_reload: true`. Keep the system identifier quoted: it is an identity, not a floating-point number. Apply with:

```bash
python3 tools/run_playbook.py playbooks/site.yml \
  --extra-vars '{"execution_mode":"reconcile","reconcile_confirmation":"APPLY RELOAD SETTINGS"}'
```

Every host is inspected and its requested changes are admitted before the first write. Each actual mutation rechecks the identity/files. A stale hash is refused. If the instance is already compliant, it is left untouched even when the previous plan hash is stale; the explicitly declared system identifier must still match.

Standalone reconciliation preserves the existing `postgresql.auto.conf` in a private backup, uses `ALTER SYSTEM` only for changed allowlisted parameters, inspects `pg_file_settings` before reload and verifies effective values through fresh SQL connections. Other settings remain present. It never rewrites the main PostgreSQL configuration template. Standalone standby changes and detected Patroni ownership are refused.

## Configure an existing Patroni cluster

Declare `manager: patroni` and the actual local Patroni configuration file on **every** member. Use the full inventory with host names matching DCS member names. Declare desired parameters on exactly one member; leave `parameters: {}` on the other members. Their runtime settings and local overrides are still inspected before and after a change.

```yaml
reconcile_instances:
  - socket_dir: /run/pg-ha-patroni
    port: 5432
    owner: postgres
    manager: patroni
    patroni_config: /etc/pg-ha/patroni/patroni.yml
    expected_system_id: 'SYSTEM_IDENTIFIER_FROM_DISCOVERY'
    parameters: {}  # Set the reviewed desired values on one member only.
    allow_reload: false
```

On the selected writer, use the same plan/hash/approval sequence as standalone PostgreSQL. The module checks that the Patroni file identifies the inspected data directory. It uses the installed Patroni DCS implementation and configured TLS credentials; it never creates the DCS namespace or uses an insecure HTTP fallback.

Only the requested keys under `postgresql.parameters` are merged into the existing dynamic configuration. The original dynamic configuration is preserved privately. A DCS compare-and-swap using the observed configuration version rejects an intervening writer. Patroni applies the dynamic settings through its normal mechanism. No REST restart, switchover, failover, reinitialization or PostgreSQL restart is issued.

A local Patroni override or `ALTER SYSTEM` override that would mask a proposed change is a blocker. Do not erase the override to make the automation succeed: determine who owns it and maintain that source explicitly. Post-change SQL checks cover the complete observed cluster. A failed member or convergence timeout prevents a success result and stops further work.

Role/database/session or command-line overrides visible in the inspection connection also block parameter reconciliation, even when their value happens to match the request. The workflow changes server defaults; it does not erase application role/database overrides or force values into existing sessions.

## Supported parameter changes and their impact

Reloadable does not mean impact-free. These settings require explicit desired values and reload approval; there are no new tuning defaults imposed on existing workloads.

| Parameter | Units / meaning | How to choose a value | Potential impact |
| --- | --- | --- | --- |
| `log_checkpoints` | Boolean; checkpoint activity logging | Enable when operational checkpoint visibility is required | Additional log volume |
| `log_lock_waits` | Boolean; logs waits exceeding `deadlock_timeout` | Enable for lock-wait investigation with log capacity reviewed | More logging under contention |
| `log_min_duration_statement` | Time; `-1` disables, `0` logs all completed statements | Choose a threshold from latency objectives and measured log volume | Query text can contain sensitive values; excessive logging increases I/O |
| `log_temp_files` | Size, base kB; `-1` disables, `0` logs all temporary files | Start with a threshold that identifies meaningful spills | Additional log volume; informs query/memory analysis |
| `deadlock_timeout` | Time, base ms | Change only after examining lock contention and detection cost | Lower values can increase deadlock-check overhead and lock-wait logging |
| `checkpoint_completion_target` | Fraction from 0 through 1 | Evaluate checkpoint duration and storage latency; retain the existing value unless measurements justify a change | Changes checkpoint write pacing and I/O behavior |

The running server supplies type, units, min/max values and context. The planner normalizes equivalent values, so `1s` and `1000ms` do not cause repeated writes. Invalid units, out-of-range numbers and fractional integer base units are refused rather than rounded silently.

The allowlist excludes connection limits, shared memory, ports, paths, authentication, archive commands, replication policy, durability switches and arbitrary SQL hooks. A request for any of those returns a manual-maintenance blocker. Adding a parameter requires extending the policy and adding native validation tests, not merely adding an inventory key.

## Backups, locking and rollback

`reconcile_backup_root` defaults to `/var/lib/pg-ha-reconcile`. It must be a dedicated root-owned private directory without symlink traversal. Nothing is created there for a no-op run. Each changed operation stores a protected plan and either the original `postgresql.auto.conf` or complete dynamic configuration. Retain these backups under your configuration-retention policy; they may contain secrets.

Standalone changes use a local lock and recheck file state. If candidate validation/reload fails and the file still matches the module's last write, the preserved file is restored and reloaded. If another writer changed it, automatic restoration is refused to avoid overwriting that writer. A convergence timeout or unexpected server restart is reported as a changed failure with the backup location; it does not trigger a restart or overwrite an unknown newer configuration.

Patroni changes use DCS compare-and-swap. There is no blind automatic replacement of the entire DCS configuration after a later failure. Inspect current state, compare the protected previous values, and submit a newly reviewed change to restore only the necessary parameters. Never restore an etcd snapshot as a routine configuration rollback.

The operation is **not a distributed transaction** across independent servers. All-host prechecks reduce partial application, but a later failure can leave earlier hosts updated. Stop, inspect the per-host results and backups, and plan the remaining or reverse changes. Do not automatically repeat disruptive maintenance. Prevent concurrent human `ALTER SYSTEM`, package managers and other automation during an approved change window; a local lock cannot serialize unrelated tools or all external controllers.

## Fresh provisioning and legacy maintenance

Fresh deployment still uses the established strict environment contract and guarded bootstrap implementation. Complete the required variables, reviewed storage, addresses, DNS, firewall, watchdog, package repository and TLS preparation. The project does not claim to install safely onto every Linux distribution or unknown storage design.

Legacy mutating entry points now begin with `maintenance-gate.yml`. They require:

```yaml
maintenance_intent: fresh  # Or maintenance for an existing, specifically reviewed operation.
maintenance_approved_operations:
  - deploy
  - platform
  - backup-platform
  - provision-cluster
deployment_mode: bootstrap
bootstrap_confirmation: 'CREATE your_cluster_name'
platform_change_confirmation: PROVISION PLATFORM
```

The list must include each invoked/imported operation. A separate repository-provisioning run also needs `platform-repositories` explicitly listed. These approvals are not required for routine plan/reconcile. Do not put broad maintenance approvals into shared defaults or habitual CI commands.

Fresh admission refuses discovered data markers, active component services, existing configuration directory entries or incomplete coverage. The original preflight further checks the exact requested data directories, ports and ownership. Bootstrap/deploy/resume helpers refuse a completed `/var/lib/pg-ha/identity.json` before their configuration helpers run. Partial bootstrap requires the existing exact recorded-plan resume protocol; it is not automatically retried as fresh.

Each of these platform variables defaults to **false**:

| Variable | Explicitly authorized effect |
| --- | --- |
| `platform_manage_storage` | Allocate reviewed project LVs from existing free extents, create a filesystem only where absent, mount specified volumes; never shrink or force-format |
| `platform_manage_network` | Apply the reviewed project Netplan fragment with timed rollback |
| `platform_manage_hosts` | Maintain the marked service-name block in `/etc/hosts` |
| `platform_manage_firewall` | Maintain the scoped project nftables policy with timed rollback |
| `platform_manage_watchdog` | Provision the selected watchdog integration and ownership |

Leave these false when equivalent resources already exist. Supply the observed paths/addresses and reviewed fingerprints to the environment contract. An incompatible resource is an intervention condition, not permission to recreate it. In particular, routine reconciliation does not change static IPs, DHCP, VMware reservations, VIPs, routes or DNS.

Configuration-copy/template/line-edit tasks preserve previous files with Ansible backups. These backups do not make arbitrary maintenance safe to replay: historical migration, restoration and fault-injection playbooks retain their specific conditions and are deliberately outside routine reconciliation.

## Validation and qualification

Validation combines policy tests, entry-point tests, YAML duplicate-key checking, Ansible syntax checks, live read-only observation and a separate native PostgreSQL instance test. The isolated acceptance creates a previously absent test directory, listens only on its private Unix socket, tests changed/no-op/refused outcomes, checks the server start identity, and stops the test server in an `always` block. It never points `initdb` or `pg_ctl` at the production data directory.

The native test instance and backups are retained as evidence; their capacity and eventual removal should follow an explicitly approved test-artifact retention procedure. Do not run the creation fixture again against the retained directory. For another test run, review a new isolated path.

A second fixture uses separate loopback-only etcd, Patroni and PostgreSQL processes to qualify an actual DCS parameter update, SQL convergence and a no-op repeat without a PostgreSQL restart. It never connects to the production DCS namespace. Its single-node test topology qualifies the write mechanism; production inventory-wide observation and convergence checks are tested separately on all three managed nodes. All test services are stopped afterward.

Results on 13 September 2026:

| Check | Result |
| --- | --- |
| Unit/policy tests | 45 passed |
| YAML and playbook syntax | Passed; duplicate keys rejected |
| Legacy-operation refusal | Unapproved platform, deployment, provisioning and historical IP migration refused before SSH/mutation |
| Production default plan | All three nodes reported zero changes |
| Production Patroni reconciliation | Two complete runs passed with zero changes and reload permission disabled |
| Isolated standalone PostgreSQL | Approved `250ms` change applied; equivalent `0.25s` repeat made no change; stale and forbidden requests refused; no restart |
| Isolated Patroni/etcd | Approved `500ms` change applied through DCS; equivalent `0.5s` repeat made no change; no PostgreSQL restart |
| Production health verification | Existing integrity, TLS, replication, DCS and VIP checks passed with zero changes |

The first Patroni test fixture lacked a required replication-authentication mapping and failed bootstrap. Its own new data was retained as `data.failed`, and its test processes stopped. The fixture was corrected and qualified in a different fresh directory. Retained test paths on pg3 are `/srv/postgres/reconcile-qa-20260913`, `/srv/postgres/reconcile-patroni-qa-20260913` and `/srv/postgres/reconcile-patroni-qa-20260913-v2`. These are test artifacts, not production database locations.

Final closeout passed production verification and confirmed all five test ports closed. Its one changed task cleared only the original stopped transient test unit's failed status after verifying its identity; it did not restart a service. The nonsecret result summary is retained in ignored `artifacts/reconciliation-validation.json`.

This qualification establishes the implemented bounded workflows. It does not establish safe unattended upgrades, automatic adoption, every possible file-layout variation or production workload tuning. Extend a scope with explicit ownership, version-specific validation, failure tests and a rollback procedure before enabling it.

References: PostgreSQL's [parameter contexts and pending restart state](https://www.postgresql.org/docs/17/view-pg-settings.html), [configuration-file validation view](https://www.postgresql.org/docs/17/view-pg-file-settings.html), and Patroni's [dynamic configuration](https://patroni.readthedocs.io/en/latest/patroni_configuration.html) describe the configuration mechanisms used here.
