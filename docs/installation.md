# Installation, first execution and repeat execution

For the opt-in automated package/preload/restart workflow, see [on-premise extension lifecycle](onprem-extension-lifecycle.md). The older `configure` operation retains its manual preload-maintenance boundary.

> Portable configuration: start with [the external deployment setup](environment-portability.md). Addresses in this guide are documentation-only ranges, names are examples, and `/home/OPERATOR` means your controller account. Read measured results as anonymized historical evidence; obtain real values from your own inventory and discovery.

This is the current command-oriented installation guide. Read [feature controls](features.md) and [environment settings](environment-settings.md) before selecting an operation. Examples use Bash on the controller and illustrative environment names. Replace example addresses, paths and names; none grants permission to alter the reference deployment.

## 1. Understand the supported scope

Select the server major using [PostgreSQL version setup](postgresql-versions.md)
before supplying package pins. The example models support `--postgres-version`
and `POSTGRES_VERSION` through their `postgresql_version` variable.

The implementation targets Ubuntu 22.04 amd64 and configurable PostgreSQL 14+. The controller qualification used ansible-core 2.16.3. PostgreSQL majors 14 and above are selectable; see [version selection](postgresql-versions.md) for qualification limits; a different OS/architecture requires implementation qualification. Existing servers can be inspected without installing missing tools; incomplete observation blocks changes.

For configurable node counts, optional routing/backups and custom extensions, follow [modular deployment](modular-deployment.md) alongside the admission steps here. Choose `standalone` for one PostgreSQL instance, or `cluster` for Type A with at least three database nodes and exactly three etcd/router core nodes. A five-node initial topology is expressible; live scale-out/conversion is a separate migration. The new standalone and five-node paths have not been deployed end-to-end in a clean staging environment. Review the [qualification record](validation.md) before admitting workloads.

## 2. Prepare the controller

Use Linux or a WSL Linux session, not Windows Python for the runners. Required controller capabilities are Python 3, ansible-core, OpenSSH client, PyYAML, and an interactive terminal for password authentication. Password transport also needs `sshpass`. `tools/provision_credentials.py` needs Python cryptography and Ansible Vault libraries. Optional client acceptance tools need their PostgreSQL Python client dependencies. Install these through an approved, pinned controller image/package environment; this repository does not supply a complete controller lockfile or installation script.

From the repository root:

```bash
python3 --version
ansible-playbook --version
ssh -V
python3 -c 'import yaml, ansible, cryptography'
ansible-galaxy collection install -r requirements.yml \
  -p "$HOME/.local/share/pg-ha/collections"
```

Collection pins are `community.postgresql: 4.2.0`, `community.general: 8.3.0`, and `ansible.posix: 1.5.4`. `ansible.cfg` selects the repository's roles, custom modules, module utilities and filters, strict SSH host-key checking and memory fact caching. The runner explicitly points Ansible at this configuration and the collection path above. Run from the repository root so relative file examples resolve correctly.

Prepare target access: an existing SSH account with approved sudo privileges, Python 3 and required observation tools. The project does not create your initial SSH access or change sudoers to complete discovery. Local database inspection requires the database OS owner/administrative visibility and installed `psql`; it does not bypass database authentication.

Verify SSH fingerprints against a console or trusted provisioning record. A network keyscan alone is not authentication. Store verified entries in a protected environment-specific known-hosts file; for a nonstandard SSH port use OpenSSH's `[host]:port` form. Never reuse an old host's key after replacement without independently verifying identity.

Define path-only shell variables and a helper:

```bash
PGHA_INVENTORY=inventories/customer-a/hosts.yml
PGHA_KNOWN_HOSTS=/secure/customer-a/known_hosts
PGHA_MODEL=/secure/customer-a/model.yml
PGHA_PRIVATE=/secure/customer-a/private
pgha() {
  python3 tools/run_playbook.py "$@" \
    --inventory "$PGHA_INVENTORY" --known-hosts "$PGHA_KNOWN_HOSTS"
}
```

Create/review those directories and files through your normal controller provisioning process before use. These are examples, not existing repository files. The runner uses existing SSH keys by default and prompts for sudo; use `--ssh-auth password` for a hidden SSH password prompt. `--ssh-auth key` selects existing SSH key/agent access; `--become-auth passwordless` is only for already-approved passwordless sudo. For an explicit key path use Ansible's standard `ansible_ssh_private_key_file` in inventory; private key contents remain outside it.

The runner holds a local advisory change lock. Another controller or manual tool must honor the organization's external change coordination. Never put passwords in shell variables, command-line extra-vars or inventory.

## 3. Create inventory and inspect first

If selecting unified mounted data/WAL/backups, read [storage layout](storage-layout.md)
before first provisioning and add the same storage overlay to each model/component
invocation. It resolves paths without formatting/moving data. The legacy paths
below remain defaults when no storage profile is selected.

For standalone, create this minimal inventory without copying the HA `group_vars/all.yml` skeleton:

```yaml
all:
  vars:
    ansible_user: dbadmin
    ansible_port: 22
  children:
    postgres_cluster:
      hosts:
        pg01:
          ansible_host: 192.0.2.21
```

`192.0.2.21` is an illustrative address; replace it with the actual reserved VM address. No `etcd_cluster` or `routers` members may exist in standalone inventory. Standard Ansible `group_vars/all.yml` and `host_vars/pg01/*.yml` beneath this inventory directory hold shared and node-specific configuration respectively.

```bash
pgha playbooks/site.yml
```

Without a model this discovers packages, services, storage and database state and reports SQL observations where access is available. It creates no PostgreSQL cluster and changes no infrastructure configuration. Review unreachable hosts, coverage gaps, offline data directories and ownership before proceeding. A bounded scan cannot establish that every possible application resource is absent.

## 4. Standalone: configure and validate

Copy the contents of `examples/standalone.yml` into the environment model file and set `topology.primary` to your sole inventory hostname. Key values:

```yaml
postgresql_deployment:
  mode: standalone
  major: '17'
  topology:
    primary: pg01
    replicas: []
    standby: []
    total_nodes: 1
  extensions: [pgcrypto]
  extension_databases: [postgres]
postgresql_operation: plan
standalone:
  name: main
  storage_mount: /srv/postgresql
  data_dir: /srv/postgresql/data
  port: 5432
  listen_address: ''
  client_cidrs: []
```

Supply an existing writable ext4/XFS mount with adequate capacity. The default headroom check is 10 GiB; size it for your workload. The target data directory must be new, canonical and inside that reviewed mount. No filesystem formatting or mount creation occurs in the standalone role. Existing PostgreSQL/etcd markers anywhere in the complete fresh scan block new initialization. For an existing database skip to section 8; never remove it to make fresh provisioning pass.

Configure signed Ubuntu/PGDG repositories through your package-management process. Review `apt-cache policy postgresql-common postgresql-17 postgresql-client-17` on the target, then put exact available versions in `postgresql_package_versions`. Values such as `latest`, wildcards and documentation placeholders are invalid. Add pins for separately packaged selected extensions. Package simulation refuses changes to installed requested versions or upgrades/removals of existing dependencies.

Local-only access is the default. To accept TCP, set `standalone.listen_address` to an IPv4 address already present on the VM, add canonical `standalone.client_cidrs`, and supply existing `standalone.tls.cert`, `.key`, `.ca` node paths. Certificates must validate to the CA, cover that IP, have at least 30 days remaining, and match a private postgres-owned key. The role does not assign an IP, publish DNS, install a firewall policy or create application logins. Those are prerequisites for the selected exposure.

```bash
ansible-playbook -i "$PGHA_INVENTORY" playbooks/model-validate.yml \
  -e "@$PGHA_MODEL"
pgha playbooks/postgresql.yml --extra-vars "@$PGHA_MODEL"
```

The first validates membership/model locally; the second observes the target. An absent socket is expected on an admitted fresh host. Resolve all unrelated coverage/state conditions before creating anything.

## 5. Standalone: provision and verify

Create a short-lived operation file, for example `/secure/customer-a/standalone-provision.yml`:

```yaml
postgresql_operation: provision
postgresql_provision_confirmation: PROVISION pg01
postgresql_allow_package_install: true
postgresql_allow_extension_create: true
```

The extension flag is necessary only for missing selected extensions. Exact package pins remain in the model/environment policy. Execute:

```bash
pgha playbooks/postgresql.yml --extra-vars "@$PGHA_MODEL" \
  --extra-vars @/secure/customer-a/standalone-provision.yml
```

The role detects ownership; admits only a new target; installs missing pinned packages; checks extension control files; initializes PostgreSQL with checksums and SCRAM/peer authentication; backs up initial configuration; validates the configuration/service; and starts only the newly created service. It then validates SQL/HBA and records root-owned identity/policy/file fingerprints. No HA components are installed.

On the standalone VM, with the example name and port:

```bash
sudo systemctl status pg-standalone-main --no-pager
sudo -u postgres psql -X -h /run/pg-standalone-main -p 5432 -d postgres \
  -c 'SELECT version(), pg_is_in_recovery();'
sudo -u postgres psql -X -h /run/pg-standalone-main -p 5432 -d postgres \
  -c 'SELECT extname, extversion FROM pg_extension ORDER BY extname;'
sudo -u postgres psql -X -h /run/pg-standalone-main -p 5432 -d postgres \
  -c 'SELECT * FROM pg_hba_file_rules WHERE error IS NOT NULL;'
```

Re-run the model plan. Repeating the completed provisioning operation with identical policy verifies ownership, SQL and fingerprints; it does not rewrite configuration or restart/start an existing service. Drift or partial initialization stops. Preserve the failed instance and investigate its journal rather than removing its directory.

Before business traffic, separately implement least-privilege application roles, backup/restore, monitoring, capacity alerts and recovery procedures. Standalone currently uses minimal WAL without integrated archiving/replication; it is not a PITR or HA deployment.

## 6. Cluster: inventory, policy and preparation

Start from `inventories/example/` in a separate environment directory. Replace all required nulls; it is a contract skeleton, not a runnable inventory. Add `ansible_user`, actual addresses and full `node` metadata. For five nodes:

```yaml
all:
  vars:
    ansible_user: dbadmin
    ansible_port: 22
  children:
    postgres_cluster:
      hosts:
        pg01:
          ansible_host: 192.0.2.21
          node: {address: 192.0.2.21, dns_name: pg01.example.internal, interface: eth0, priority: 150, failure_domain: rack-a}
        pg02:
          ansible_host: 192.0.2.22
          node: {address: 192.0.2.22, dns_name: pg02.example.internal}
        pg03:
          ansible_host: 192.0.2.23
          node: {address: 192.0.2.23, dns_name: pg03.example.internal}
        pg04:
          ansible_host: 192.0.2.24
          node: {address: 192.0.2.24, dns_name: pg04.example.internal, interface: eth0, priority: 140, failure_domain: rack-b}
        pg05:
          ansible_host: 192.0.2.25
          node: {address: 192.0.2.25, dns_name: pg05.example.internal, interface: eth0, priority: 130, failure_domain: rack-c}
    etcd_cluster:
      hosts: {pg01: {}, pg04: {}, pg05: {}}
    routers:
      hosts: {pg01: {}, pg04: {}, pg05: {}}
```

This illustrates membership, not the complete contract. Add reviewed firewall fingerprints and all required group policy. If using the platform helpers on additional database nodes, supply their required interface/platform inputs too; helper and monitor assumptions require staging qualification for extra nodes. The current HA monitor assumes a local etcd endpoint and is not qualified on database-only nodes.

Use `examples/topology-five-nodes.yml` as the global model. Set `cluster.bootstrap_host: pg01`, the initial primary, and choose strict synchronous count no greater than the eligible standby count. Count fields assert membership; they do not create VMs. Read replicas `pg02/pg03` are excluded from automatic promotion and synchronous selection. Eligible `pg04/pg05` may become primary after failover.

Complete the contract's IP/DNS/VIP/VRID, mounts, resources, package pins, etcd artifact digest, replication/timeouts, backup helper paths/objectives and evidence references. Set `backup_repository_host`, `backup_repository_path`, `backup_port`, `backup_package_version`, `application_databases`, and `tls_sources` if using managed backups. Actual service credentials are required in Vault. Their reference values and selection impacts are in the [environment settings](environment-settings.md).

For the supplied internal PKI helper, from Linux:

```bash
python3 tools/provision_credentials.py --inventory "$PGHA_INVENTORY" \
  --private-dir "$PGHA_PRIVATE" --vip 192.0.2.50 \
  --vip-dns postgres.example.internal
```

It reads direct node definitions from hosts.yml, writes host TLS pointer files, and creates protected CA/leaf material plus `secrets.vault.yml` and `vault-password`. Existing leaves/secrets are retained, not renewed or rotated. Use approved organizational PKI instead where required. Keep recovery keys separately protected and do not use this HA helper as a standalone TLS deployment tool.

Add Vault arguments to calls requiring service credentials:

```bash
pgha playbooks/validate-inputs.yml \
  --extra-vars "@$PGHA_PRIVATE/secrets.vault.yml" \
  --vault-password-file "$PGHA_PRIVATE/vault-password"
```

Validate the model separately as in section 4. Controller validation cannot establish actual network reachability, free storage, backup readiness or working fencing.

Provision approved repositories, mounts, DNS, firewall and watchdog/time synchronization before HA bootstrap. Existing compliant infrastructure may be prepared externally and reused. All `platform_manage_*` flags default false. Selecting a flag grants management of that subsystem; leaving it false skips management and does not make the prerequisite optional.

The optional repository/platform/backup helpers are **mutating maintenance operations**, not ordinary plans. For each invocation, use a reviewed operation file containing `maintenance_intent` and only that helper's exact `maintenance_approved_operations` name. `platform.yml` additionally needs `platform_change_confirmation: PROVISION PLATFORM` and individually selected flags. `backup-platform.yml` installs the supplied pgBackRest transport/configuration before PostgreSQL bootstrap. On previously prepared hosts use `maintenance_intent: maintenance`; do not call them fresh if existing configuration/services are present. This does not authorize adoption or destruction of PostgreSQL data.

Example for an already-reviewed prepared-host backup integration:

```yaml
maintenance_intent: maintenance
maintenance_approved_operations: [backup-platform]
```

Pass this file to `pgha playbooks/backup-platform.yml` with the Vault arguments above. This helper can replace its managed configuration/start its service; it is not the new missing-only package reconciler. Review target ownership and existing backup history before invocation. If using external archive integration instead, install/test the exact executable contract beforehand and omit managed repository selection.

## 7. Cluster: bootstrap and verify

### Establish the approved firewall fingerprint

HA admission requires the normalized effective nftables fingerprint in each
`node.firewall_sha256`. After reviewing the actual ingress policy, an operator can
run the existing read-only module through Ansible:

```bash
ANSIBLE_CONFIG="$PWD/ansible.cfg" ansible postgres_cluster \
  -i "$PGHA_INVENTORY" -m firewall_policy_info --become \
  --ask-pass --ask-become-pass \
  --ssh-common-args "-o StrictHostKeyChecking=yes -o UserKnownHostsFile=$PGHA_KNOWN_HOSTS"
```

For existing key authentication omit `--ask-pass`; omit `--ask-become-pass` only
with approved passwordless sudo. Store each returned `sha256` with that host's
reviewed node policy. Missing ingress rules are refused. Never manufacture a hash
or replace a recorded baseline merely to hide unexpected drift. The legacy
`deploy.yml` records this automatically after its approved platform phase; the
model workflow expects that prerequisite policy to be supplied.

Once prerequisites are prepared, use a new short-lived operation file:

```yaml
postgresql_operation: provision
deployment_mode: bootstrap
bootstrap_confirmation: CREATE customer_a
maintenance_intent: maintenance
maintenance_approved_operations: [provision-cluster]
postgresql_allow_package_install: true
postgresql_allow_extension_create: true
```

`customer_a` must exactly match `cluster.name`. `maintenance` here reflects the already prepared platform/backup services; PostgreSQL/etcd bootstrap still enforces its own empty-data, identity and exact-plan rules. It is not permission to reuse foreign data. If no prerequisite state exists and using the legacy combined deployment, its separately documented fresh gate applies. Never change intent simply to hide an unexplained blocker.

```bash
pgha playbooks/postgresql.yml --extra-vars "@$PGHA_MODEL" \
  --extra-vars @/secure/customer-a/cluster-provision.yml \
  --extra-vars "@$PGHA_PRIVATE/secrets.vault.yml" \
  --vault-password-file "$PGHA_PRIVATE/vault-password"
```

The model workflow validates roles/versions and discovery, then delegates fresh HA to `provision-cluster.yml`: full preflight, preparation, etcd consensus, initial Patroni primary/replicas, database identities/poolers, serial routing activation and verification. Selected preloads enter fresh Patroni configuration. Extensions are created on the actual writer and verified across members. No live role reassignment occurs.

On a core VM:

```bash
sudo -u postgres patronictl -c /etc/pg-ha/patroni/patroni.yml list
```

From the controller, run `pgha playbooks/verify.yml` with Vault arguments. Require one writer, matching system identity, streaming replicas, strict-sync policy where selected, healthy etcd/routing and one reachable VIP owner. Validate application TLS/SQL through both frontends as described in the operator guide. A healthy process is insufficient.

Backup/restore and fault acceptance are deliberate writes/disruptions, not routine verification. Use the runbook's specific confirmation controls and exact maintenance scopes. `backup-schedule.yml` and `monitoring.yml` require individual maintenance approvals and enable their timers; deleting an approval variable later does not disable an installed timer. Do not enable the current HA monitor on database-only additional nodes without qualification/adaptation.

## 8. Existing instances and routine re-execution

### Exact legacy helper scopes

The following are examples of operation scopes, not a batch to run. Keep each in
its own short-lived file and supply other operation-specific confirmations too:

| Selected playbook | `maintenance_approved_operations` | Additional behavior |
| --- | --- | --- |
| `platform-repositories.yml` | `[platform-repositories]` | Can install utilities/update package metadata/repository; review existing sources |
| `platform.yml` | `[platform]` | Exact platform confirmation plus selected subsystem flags |
| `backup-platform.yml` | `[backup-platform]` | Installs/configures managed backup transport |
| `provision-cluster.yml` | `[provision-cluster]` | Exact bootstrap/resume identity admission |
| Legacy `deploy.yml` | `[deploy, platform, backup-platform, provision-cluster]` | Combined prepared workflow; not a completed-cluster update command |
| `data-acceptance.yml` | `[data-acceptance, endpoints-verify, backup-verify]` | Writes application markers and performs backup acceptance |
| `pitr-acceptance.yml` | `[pitr-acceptance, restore-verify]` | Writes/restores markers, unique test paths and confirmations |
| `backup-schedule.yml` | `[backup-schedule]` | Enables installed backup timer |
| `monitoring.yml` | `[monitoring]` | Installs/enables monitor and executes its initial check |
| `final-acceptance.yml` | `[final-acceptance]` | Repeated verification/monitor evidence; requires installed operational prerequisites |

Use `maintenance_intent: fresh` only when its relevant-state conditions are
actually true; otherwise use separately reviewed maintenance scope. Neither choice
permits deleting existing PostgreSQL data. Plain `verify.yml` and routine plan
need no legacy mutation scope. The model's completed-HA provisioning branch uses
verification; the legacy direct bootstrap helpers refuse completed ownership.

Use `site.yml` without a model, or `postgresql.yml` with `postgresql_operation: plan`, for routine observation. Existing offline/foreign data is reported and preserved. Existing managed HA `provision` selects verification rather than replaying completed bootstrap; partially owned topology stops. It never creates a new system identity to resolve a mismatch.

For reloadable parameters, use [safe re-execution](safe-reexecution.md): explicit local endpoints, discovered system identifiers, reviewed plan hashes and `allow_reload`. Use `reconcile.yml` directly when a model is present, because `site.yml` dispatches to the model first. A matching plan changes only the supported differing parameters, backs up protected configuration and reloads through the appropriate existing manager. Already-correct settings cause no backup/write/reload. Restart parameters are refused.

For extensions, use [deployment models](deployment-models.md#5-extension-registry-and-prerequisites): plan; missing pinned packages if approved; separately managed preload restart if required; fresh plan; `configure` with expected identity/hash and creation permission. Existing versions and unselected extensions are preserved. Disabling the creation flag prevents new DDL; it does not uninstall anything.

Do not keep fresh/bootstrap/maintenance approvals in permanent defaults. A retry after partial initialization is an investigation first. The legacy HA `resume` path requires the original exact incomplete plan and `RESUME <name>`; it is not a general repair or destructive retry. Standalone partial ownership is deliberately refused.

## 9. Troubleshooting

| Symptom | Meaning and next safe action |
| --- | --- |
| Undefined/null required value | Complete the environment contract; example inventories are intentionally incomplete |
| Invalid topology or count | Match every host exactly once; keep core etcd/router membership identical; do not change live roles merely to satisfy YAML |
| SSH host-key mismatch | Verify the target via trusted console; investigate replacement or routing error before updating trust |
| Missing package pin/version conflict | Check installed versions and approved repository candidates; arrange separate upgrades instead of weakening pins |
| Missing extension/preload | Install only approved compatible packages; preload activation needs a separate restart plan on existing servers |
| Unsafe extension schema | Preserve ACLs/owner; choose an approved secure schema rather than granting installer rights broadly |
| Existing directory/ownership mismatch | Preserve data, determine identity and use existing-instance scope; do not delete markers |
| Coverage gap | Resolve observation privilege/tools or define a reviewed existing-instance scope; never treat failed inspection as empty |
| Stale plan hash | State changed since review; obtain and review a fresh plan |
| `@` YAML error in `/etc/patroni/config.yml.in` | That file is a vendor template; use the actual managed `/etc/pg-ha/patroni/patroni.yml` path |
| Standalone startup failure | Inspect `journalctl -u pg-standalone-<name>` and retained server configuration; preserve partial initialization |
| HA verification drift | Compare approved files/policy/runtime; do not edit fingerprints to silence the failure |

No instruction in this guide authorizes wiping disks, replacing an existing cluster, disabling fencing/TLS to restore apparent health, or starting a second manager for the same data directory.
