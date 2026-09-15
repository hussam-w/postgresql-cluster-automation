# PostgreSQL deployment and safe operations with Ansible

Configuration-driven PostgreSQL automation for **Ubuntu 22.04 amd64 and configurable PostgreSQL 14+**. Deploy standalone PostgreSQL, modular clusters or Type A HA, inspect existing environments, reconcile a bounded set of reloadable settings, and manage selected extensions while preserving existing databases.

**Routine execution defaults to observation.** Existing data, configuration and services are presumed valuable. Upgrades, restarts, live topology conversion, storage/network changes and recovery are not automatic consequences of configuration differences.

## Documentation

| Guide | Contents |
| --- | --- |
| **[On-premise extension lifecycle](docs/onprem-extension-lifecycle.md)** | Declarative native/third-party extensions, package sources, guarded preload/restart automation and reapplication |
| **[Modular deployment](docs/modular-deployment.md)** | Node counts, optional backups and HAProxy, custom extensions, examples and safe changes |
| **[PostgreSQL versions](docs/postgresql-versions.md)** | Select 14–18 or future majors, matching package pins, compatibility checks and upgrade boundaries |
| **[Installation and usage](docs/installation.md)** | Prerequisites, exact standalone/HA workflows, validation, verification and troubleshooting |
| **[Environment settings](docs/environment-settings.md)** | Actual defaults, required values, sources, examples, sizing and change consequences |
| **[Feature controls](docs/features.md)** | Supported switches, dependencies, enable/disable behavior and unsupported options |
| **[Another environment](docs/environment-migration.md)** | Practical inventory, network, storage, secrets and recovery checklist |
| [Models and extensions](docs/deployment-models.md) | Exact topology and extension lifecycle contracts |
| [Safe re-execution](docs/safe-reexecution.md) | Discovery, approved reload plans, preservation and maintenance gates |
| [Administrator guide](docs/operator-guide.md) / [runbook](docs/operations.md) | Detailed HA configuration, operation and recovery |
| [Repository structure](docs/project-structure.md) | Actual files, entry points and ownership |
| [Validation](docs/validation.md) | Measured evidence and qualification limits |

## Supported modes and capabilities

| Mode | Components and topology |
| --- | --- |
| Standalone | One PostgreSQL service; local socket by default, TLS required for TCP; no replication, Patroni, etcd, pooler or VIP |
| Modular cluster | Explicit primary/read-replica/standby lists; 1, 3 or 5 consensus voters; optional HAProxy/VIP; reduced topologies require acknowledgment and are not HA |
| Type A HA | At least three PostgreSQL/Patroni/PgBouncer nodes; exactly three colocated etcd/HAProxy/Keepalived core nodes; explicit initial primary, read replicas and eligible HA standbys |

Every inventory host must have exactly one role; optional counts must agree before SSH. Initial primary selection does not undo failover. Designated read replicas are excluded from promotion and synchronous selection. Existing role differences stop for controlled maintenance.

The mandatory extension baseline is `plpgsql`. The catalog includes native extensions, statistics/audit extensions, pgvector and TimescaleDB, and accepts custom package descriptors or preinstalled control files. Existing extension versions remain. The dedicated extension lifecycle can automate additive preloads and sequential restarts with explicit maintenance opt-ins. No automatic DROP or extension upgrade occurs.

The reference three-node HA deployment is tested. Fresh standalone and five-node deployment/failover still need staging qualification. Optional scheduled logical backups are available for standalone and modular clusters; native logical backup/restore passed on an existing PostgreSQL 17 three-node Type A cluster; fresh modular topology and failover qualification remain outstanding. S3 configuration, Prometheus installation, arbitrary adoption and major upgrades are not implemented.

## Declarative extensions on existing on-premise clusters

Use [examples/onprem.yml](examples/onprem.yml) as your configuration interface. Append extension names, bind the model to `postgresql_extensions`, and run:

```bash
python3 tools/run_playbook.py playbooks/extensions.yml \
  --extra-vars @inventories/local/model.yml --extensions pgcrypto,pgvector
```

This defaults to observation. After reviewing the plan and setting the identity confirmation, package permissions and any required maintenance-window flags, add `--extra-vars extension_operation=apply`. The workflow resolves registered packages and native SQL dependencies, installs missing packages on all nodes, preserves existing preloads, performs explicitly permitted managed restarts sequentially, and creates/verifies missing extensions. Unknown third-party names require installed control files or an explicit trusted package descriptor; no vendor install scripts are guessed or executed.

Read the [full workflow](docs/onprem-extension-lifecycle.md) before enabling restarts. One physical replication cluster has one writable primary. Existing databases, network configuration and mounts are preserved; live membership conversion is a separate operation. The new restart path needs native staging qualification.

## Modular deployment options

Start with [modular-single.yml](examples/modular-single.yml) or [modular-ha.yml](examples/modular-ha.yml), and follow the [complete setup and operations guide](docs/modular-deployment.md).

| Option | Default | Configuration |
| --- | --- | --- |
| Topology | Explicit selection | `standalone` or `cluster` with `architecture: modular` |
| Replica/standby counts | HA example: 0 / 2 | Edit actual host lists and matching count assertions; zero is supported with appropriate durability/degraded policy |
| Automated backups | Disabled | `ENABLE_BACKUP=true`; set `BACKUP_TARGET_PATH` to protected storage |
| HAProxy and VIP | Enabled for cluster, disabled standalone | `ENABLE_HAPROXY=false` selects direct node connections and requires an empty router group |
| Extra extensions | None | `postgresql_extensions: []`; built-in and custom dependency registries supported |

```bash
python3 tools/run_playbook.py playbooks/postgresql.yml \
  --extra-vars @inventories/local/model.yml \
  --enable-backup true --backup-target-path /srv/pg-storage/backups/repository
```

This runs the default observation plan. Provisioning retains explicit storage, package, TLS and bootstrap admission. Backups are scheduled logical dumps, not PITR; disabled backups skip service creation. The identity-gated `components` operation can enable or disable an existing managed backup timer while retaining data. Counts do not create VMs, and topology/routing changes do not automatically convert live clusters.

## Architecture

```text
Standalone: application -> PostgreSQL local socket or approved TLS endpoint

Type A: application -> VIP:5000 -> HAProxy -> primary PgBouncer -> PostgreSQL
                   -> VIP:5001 -> HAProxy -> replica PgBouncer -> PostgreSQL
        Patroni <-> three-member etcd; primary WAL -> streaming replicas
        separately installed pgBackRest integration -> encrypted repository
```

VIP ownership and leadership are independent. HAProxy does not split SQL statements. Failover interrupts connections and can leave transaction outcomes uncertain; applications need bounded retries and transaction idempotency. Strict synchronous policy may block writes when eligible standbys are unavailable. See [architecture](docs/architecture.md).

## Prerequisites and first safe run

Start with [the portable environment setup](docs/environment-portability.md). Copy
[.env.example](.env.example) to `.env`, copy the HA inventory template to
`inventories/local/` (or use the standalone inventory below), and fill in your own
addresses, account, DNS names, topology and policy. Local files are ignored by Git.
No reference VM or production inventory is selected implicitly.

`.env` configures controller paths/authentication and optional version/component
overrides; the complete target policy stays in Ansible YAML. CLI options override process environment, which overrides `.env`.
Use `~/` for controller home; shell expansion is not supported. The linked guide
covers all settings, per-server overrides, SSH trust and switching environments.

Use a Linux/WSL controller, Python 3, Ansible (tested core 2.16.3), OpenSSH and the pinned collections. Password transport needs `sshpass`; the PKI helper needs cryptography. Verify host keys independently, provide approved sudo access and keep private credentials outside the repository. [Full preparation](docs/installation.md#2-prepare-the-controller).

```bash
ansible-galaxy collection install -r requirements.yml \
  -p "$HOME/.local/share/pg-ha/collections"
python3 tools/run_playbook.py playbooks/site.yml \
  --inventory inventories/my-environment/hosts.yml \
  --known-hosts /secure/my-environment/known_hosts
```

Create/review these environment files first. The runner uses existing SSH keys by default, prompts privately for sudo, selects `ansible.cfg` and holds a local change lock. `--ssh-auth password` enables a hidden SSH password prompt; it does not create access.

## Inventory and model examples

The supplied model files expose `postgresql_version` and reference it in
`postgresql_deployment.major`. Select a version before the first plan:

```bash
python3 tools/run_playbook.py playbooks/postgresql.yml \
  --extra-vars @inventories/local/model.yml --postgres-version 16
```

Alternatively set `POSTGRES_VERSION=16` in `.env`. Provide matching exact package
pins from your approved repositories. Versions below 14 and conflicting
model/package selections are refused. Future majors have no selection ceiling,
but require compatible upstream components and destination qualification.
Changing this value never upgrades an existing cluster. See the
[complete version setup](docs/postgresql-versions.md).

Standalone inventory (replace the illustrative address):

```yaml
all:
  vars: {ansible_user: dbadmin, ansible_port: 22}
  children:
    postgres_cluster:
      hosts:
        pg01: {ansible_host: 192.0.2.21}
```

Standalone model:

```yaml
postgresql_deployment:
  mode: standalone
  major: '17'
  topology: {primary: pg01, replicas: [], standby: []}
  extensions: [pgcrypto]
postgresql_operation: plan
```

Five-node cluster model:

```yaml
postgresql_deployment:
  mode: cluster
  major: '17'
  topology:
    primary: pg01
    replicas: [pg02, pg03]
    standby: [pg04, pg05]
    total_nodes: 5
    replica_count: 2
    standby_count: 2
  extensions: [pg_stat_statements]
postgresql_operation: plan
```

The HA inventory must contain all five hosts, with `pg01/pg04/pg05` in both `etcd_cluster` and `routers`. These are model fragments, not complete provisioning contracts. Complete [standalone settings](examples/standalone.yml), or the [HA overlay](examples/topology-five-nodes.yml) plus `inventories/example/` requirements using the installation guide. Count fields do not create VMs.

```bash
ansible-playbook -i inventories/my-environment/hosts.yml \
  playbooks/model-validate.yml -e @/secure/my-environment/model.yml
python3 tools/run_playbook.py playbooks/postgresql.yml \
  --inventory inventories/my-environment/hosts.yml \
  --known-hosts /secure/my-environment/known_hosts \
  --extra-vars @/secure/my-environment/model.yml
```

These validate locally and observe remotely. Follow the separate [standalone](docs/installation.md#5-standalone-provision-and-verify) or [HA deployment](docs/installation.md#7-cluster-bootstrap-and-verify) steps for pins, prerequisites and explicit initialization permissions. A plan does not install PostgreSQL.

## Portable data, WAL and backup paths

Opt in with `storage_layout: {root: /srv/pg-storage}` or, for standalone,
`storage_layout: {home_user: dbadmin}`. The latter resolves the named account's
home **on the target**, then appends `/data`; it never uses the controller's HOME.
The resulting `data/pgdata`, `wal/pg_wal` and `backups/repository` share one root.
Data and repository mount points are verified; fresh initdb/replica copies receive
the external WAL path. Existing clusters are never relocated automatically.

See [storage layout and volume mounting](docs/storage-layout.md) for per-environment
overrides, exact mount instructions, home-directory restrictions and recovery
qualification limits, plus the [commented configuration](examples/storage-layout.yml).

## Verify and re-run

For standalone, inspect `pg-standalone-<name>` and SQL through `/run/pg-standalone-<name>` using the installation guide. For HA, run `playbooks/verify.yml` with reviewed inventory/Vault arguments and `sudo -u postgres patronictl -c /etc/pg-ha/patroni/patroni.yml list` on a node.

Re-run plan routinely. Completed provisioning verifies ownership rather than recreating data. `reconcile.yml` handles approved reloadable parameters; model `configure` handles approved missing extensions. Correct resources are unchanged; drift, missing dependencies and ambiguous state require intervention. Never erase data/ownership markers to pass a gate.

## Security, backup and monitoring

Use environment-specific addresses/DNS, verified TLS, restricted administration, SCRAM and protected Vault/CA keys. The PKI helper retains material; it does not rotate/renew it. Platform storage/network/hosts/firewall/watchdog management is independently opt-in. Skipping management preserves existing state and does not remove an installed component.

HA's separately admitted pgBackRest integration supports an encrypted filesystem repository over TLS, scheduling and isolated restore tests. Retention/encryption settings have fixed implementation limits; descriptive text does not change them. The reference repository is colocated and its controller export is one-time, not continuous off-site DR. The HA monitor writes local status/journald; external alerts and Prometheus are separate. [Feature details](docs/features.md).

## Repository, troubleshooting and qualification

Administrators configure `inventories/` and external model/operation files. `playbooks/` orchestrates; `roles/` implements components; `library/`, `module_utils/` and `filter_plugins/` provide detection/admission; `tools/` holds controller helpers; `tests/` holds validation; `docs/` and `examples/` teach use; ignored `artifacts/` contains runtime reports. [Complete structure](docs/project-structure.md).

Check topology/null values, trusted SSH identity, discovery coverage, package versions, actual config paths and current plan hashes when execution stops. Preserve unexplained state; never weaken TLS/fencing or alter fingerprints to hide failure. [Troubleshooting](docs/installation.md#9-troubleshooting).

All public addresses and names are illustrative. [Deployment record](docs/deployment-record.md), [IP migration](docs/ip-migration.md) and [failure matrix](docs/failure-tests.md) preserve anonymized dated evidence, not replay instructions. Private local inventories are retained separately.

Development checks: `python -m unittest discover -s tests` and Linux `python3 tests/ansible_validation.py`. Production readiness additionally requires representative workload, fencing, backup/restore and failure evidence in the actual environment.
