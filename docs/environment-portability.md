# Configure this project for your environment

See [modular deployment](modular-deployment.md) for the optional topology/component profile, its example files, configuration controls and qualification limits.

The distributable configuration has no implicit production destination. Use a Linux or WSL controller and the supported Ubuntu 22.04 amd64 target platform with selectable PostgreSQL 14+. Portability here means configurable infrastructure identities and policy; it does not imply support for every operating system, PostgreSQL major, cloud networking model, or storage backend.

## 1. Separate controller settings from target policy

| Location | Purpose | Examples |
| --- | --- | --- |
| `.env` or `--env-file` | Nonsecret settings for the Python runners | Inventory, verified SSH keys, controller collection and lock directories |
| `inventories/local/hosts.yml` | Target connections and membership | IPs, account, SSH port, per-node DNS/interface, HA groups |
| `inventories/local/group_vars/all.yml` | Complete shared environment policy | Cluster name, VIP, capacity, package pins, replication, backup policy |
| `inventories/local/host_vars/<host>/` | Per-server overrides | Interface, filesystem locations, TLS source paths |
| External model / operation YAML | Explicit desired topology and permitted operation | Standalone/HA, roles, extension selection, plan/provision |
| Protected external Vault / PKI directory | Credentials and certificates | Database passwords, CA keys, TLS leaves |

`.env` is read only by `run_playbook.py`, `run_discovery.py`, and the collection-link helper. Ansible, shells and other helpers do not automatically load it. It is not a target environment file or a secret store. Structured PostgreSQL/network policy belongs in YAML; there is no hidden translation from environment variables into arbitrary Ansible settings.

## 2. Create a local configuration without overwriting an existing one

Run from the repository root in Linux/WSL:

```bash
test -e .env || cp .env.example .env
mkdir -p inventories/local
test -e inventories/local/hosts.yml || cp inventories/example/hosts.yml inventories/local/hosts.yml
mkdir -p inventories/local/group_vars
test -e inventories/local/group_vars/all.yml || cp inventories/example/group_vars/all.yml inventories/local/group_vars/all.yml
```

These inventory copies are for **HA**. For standalone, use the minimal one-host inventory and standalone model in [installation](installation.md#3-create-inventory-and-inspect-first); do not include the HA policy or etcd/router groups.

Edit `.env` with your paths. Values are literal `KEY=value`; matching single/double quotes around the whole value are accepted. Blank lines and whole-line comments are supported. No shell sourcing, `$HOME`, `${VAR}`, commands, multiline values or inline comments are supported. Use `~/` for the controller's home. Unknown/duplicate file keys are errors. Never `source .env` as part of this workflow.

Precedence is **explicit CLI option → process environment → selected `.env` file → safe default**. CLI inventory, known-hosts and authentication options override their matching settings. `--env-file` selects a different file; an explicitly missing file fails. If omitted, the runner reads the repository `.env` when present. Relative controller paths resolve from the repository root. Changing environment files does not change the target machines by itself.

| Setting | Default if absent | When to override / impact |
| --- | --- | --- |
| `PGHA_INVENTORY` | None; required | Select the exact target environment. Wrong selection can target the wrong servers; always inspect before applying |
| `PGHA_KNOWN_HOSTS` | None; required | Existing independently verified SSH host keys for that environment; replacement hosts require trusted re-verification |
| `PGHA_COLLECTIONS_PATH` | `~/.local/share/pg-ha/collections` | Approved native Linux collection installation directory; install pinned requirements at the same path |
| `PGHA_STATE_DIR` | `~/.local/share/pg-ha` | Controller lock directory; all operators on one controller must use the same directory to coordinate changes. It is not a distributed lock |
| `PGHA_SSH_AUTH` | `key` | `key` uses existing keys/agent; `password` prompts privately and requires sshpass |
| `PGHA_BECOME_AUTH` | `password` | `password` prompts for sudo; `passwordless` uses already-approved sudo policy |
| `POSTGRES_VERSION` | None | General-runner major override for models referencing `postgresql_version`; see [version setup](postgresql-versions.md). Never upgrades existing data |

Keep the lock and collections on native Linux storage. `.env`, `.env.*` (except `.env.example`), `inventories/local`, existing private production/discovery inventories and runtime artifacts are ignored. Other environment directory names require your own ignore rule or a deliberately reviewed nonsecret inventory repository. Do not commit Vault decryption keys, SSH passwords, CA keys or unrestricted inventory dumps.

## 3. Set host identities and connection parameters

Replace every required `null` in the HA templates. The example host labels `pg1`, `pg2`, `pg3` are arbitrary Ansible identifiers; renaming them requires updating all group membership and topology references. An illustrative host entry is:

```yaml
pg1:
  ansible_host: 192.0.2.21
  ansible_user: dbadmin
  ansible_port: 22
  node:
    address: 192.0.2.21
    dns_name: pg1.db.example.com
    interface: eth0
    priority: 150
    failure_domain: rack-a
```

**These addresses and names are documentation examples, not deployable defaults.** Set `ansible_host` to the controller-reachable address. Set `node.address` to the stable address used for database and peer communication. They can differ only where routing/firewall/TLS policy supports it. Determine `node.interface` on each server using `ip -br address` and `ip route`; do not assume `eth0`. Obtain the actual failure domain from infrastructure placement, not the hostname.

Use DNS you control and provision records through your DNS/IPAM workflow. Node DNS must resolve consistently from every peer and match certificate identities. `cluster.vip_dns_name` names the client endpoint, not a server. `cluster.vip` is a separately reserved, unused address for Keepalived; it remains necessary for this Type A routing design even when node addresses are DHCP reservations. The network must support the documented VIP/VRRP behavior. Cloud networks that prohibit address movement need a separately qualified routing architecture.

Normal planning/reconciliation does not change DNS, interfaces, static addresses or DHCP. Platform network/hosts management remains a separate opt-in. A new IP/domain value for an existing deployment is a migration requirement, not permission to overwrite infrastructure or automatically reissue certificates.

## 4. Complete the shared policy and model

Use [environment settings](environment-settings.md) for the full configuration reference. In particular:

1. Set a unique cluster name, initial bootstrap member, etcd token and topology. The primary in the model must agree with the bootstrap member; runtime leadership can move.
2. Reserve VIP, prefix and VRRP ID, and specify narrow client/admin CIDRs. Avoid a shared VRRP ID collision on the router network.
3. Set exact package versions and artifact checksums from your approved repositories. Do not copy historical version observations as permanent package locks.
4. Size PostgreSQL connections, memory, pooling, WAL retention and etcd limits against workload measurements and recovery requirements.
5. Set storage paths/mounts, minimum capacity and a backup repository host/path. Use [storage layout](storage-layout.md) for the unified `data`, `wal`, `backups` profile. Target `home_user` is resolved from that server's account database; controller `~/` is unrelated. Existing data is never automatically relocated.
6. Provide backup destination, retention policy and measured RPO/RTO. A colocated repository does not establish off-site recovery.
7. Populate evidence references and TLS source files for the selected workflows. They document completed checks rather than automatically proving production readiness.

Copy `examples/production-model-plan.yml` for a generic three-node HA model (the filename is retained for compatibility), or use the standalone/five-node examples. Put the model under your environment directory or pass it explicitly with `--extra-vars @/absolute/path/model.yml`. The runner does not silently load a model from `.env`.

Ansible merges inventory precedence according to its normal rules; nested dictionaries are not universally deep-merged. Do not pass a partial `cluster` mapping in extra-vars and assume the rest survives. Keep the complete shared mapping in one reviewed file and use dedicated operation controls separately.

## 5. Verify SSH trust and perform observation first

Install the pinned collections into the path configured above:

```bash
ansible-galaxy collection install -r requirements.yml -p "$HOME/.local/share/pg-ha/collections"
python3 tools/run_playbook.py playbooks/site.yml
```

Before that run, create the configured known-hosts file from independently verified server fingerprints. Missing configuration fails before SSH. The command defaults to observation when no deployment model/operation is supplied; review the report and coverage gaps.

For the specialized infrastructure-discovery workflow, copy `examples/discovery-inventory.yml` to `inventories/local/discovery.yml`, fill its account/addresses/expected target list, and add hosts as needed. It uses the `target_vms` group, not the deployment group:

```bash
python3 tools/probe_ssh_identity.py --inventory inventories/local/discovery.yml --port 22
# Compare the candidate fingerprints with trusted console/provisioning records.
python3 tools/run_discovery.py --inventory inventories/local/discovery.yml --port 22 --privileged
```

The discovery runner uses hidden password prompts; its `--port` is required. `PGHA_SSH_AUTH` and `PGHA_BECOME_AUTH` are general-runner settings and do not change this specialized password workflow. For key-based observation, use the general runner with `site.yml` and a deployment inventory.

For another environment, keep its configuration separate and select it explicitly:

```bash
python3 tools/run_playbook.py playbooks/site.yml --env-file /secure/staging/controller.env
python3 tools/run_playbook.py playbooks/postgresql.yml --extra-vars @inventories/local/model.yml
```

Keep `postgresql_operation: plan` until reviewed. Then follow the exact [fresh or existing installation workflow](installation.md). Check mode predicts supported changes; it is not a substitute for observation, backups or validation. Existing data/unknown ownership stops destructive provisioning. No environment file can implicitly authorize reinitialization.

## 6. Explicit inputs for operational helpers

| Helper | Environment inputs / limits |
| --- | --- |
| `provision_credentials.py` | Required `--inventory`, `--private-dir`, `--vip`, `--vip-dns`; existing PKI retained. Inventory must use the documented direct host mapping |
| `acceptance_client.py` | Required `--policy`, `--private-dir`, `--output`; policy includes complete `cluster` and `application_databases`. Writes a dedicated acceptance table using the first configured application database; use an approved test workload |
| `issue_migrated_dcs_certificates.py` | Required `--mapping`, `--private-dir`, `--destination`; JSON `nodes` structure shown in `examples/ip-migration.json`. Preserve CAs/keys, inspect SANs before installation |
| `ip-migration*.yml` | Explicit maintenance admission plus `migration_nodes`, `migration_state_dir`, `migration_certificate_dir`, `migration_expected_system_id`; main migration also requires `migration_site_qualified: true` and confirmation containing the actual cluster name. Three-core legacy Netplan workflow and standard ports only; qualify separately before use |
| `reserve_vmware_addresses.ps1` | Required `-Source`, `-Output`, `-Settings`. Generates a candidate only; never installs DHCP configuration or restarts a service |
| Isolated live test playbooks | Explicit `qa_host`; identity-sensitive tests require `qa_protected_system_id`; model acceptance additionally requires `qa_primary` and `qa_standby`. Review socket/ports, fixture paths and scan roots before use |

Migration JSON uses actual host OS short names as keys and `{old, new}` addresses as values. Ansible `migration_nodes` uses that same inner mapping. Migration tooling is maintenance-specific, not a general multi-cloud address migration engine. The established service locations and native protocol behavior remain implementation contracts. Set `migration_state_dir` (JSON `state_dir`) to a dedicated `/var/lib/pg-ha-migrations/<change-id>` directory. An existing journal requires inspection before a new migration; never discard old recovery material.

Migration health checks obtain their initial endpoint from inventory and use
`etcdctl endpoint health --cluster` to check member endpoints, preserving the
whole-cluster health requirement without a fixed DNS list. See the
[etcd 3.5 cluster-status documentation](https://etcd.io/docs/v3.5/tutorials/how-to-check-cluster-status/).

VMware candidate settings contain `expected_source_sha256`, `old_range_statement`, `replacement_range_statements`, and `reservations` (a list of `{name, ip, mac}`). Obtain all values from your hypervisor's current configuration and IPAM. Manually validate subnet placement, existing reservations, exclusion of reserved addresses from every dynamic range, and DHCP syntax. Installation and any service restart require a separate approved maintenance procedure.

## 7. Re-run and change environments safely

Inspect the selected inventory and operation before every change. Re-run plans after edits; examine differences and apply only the supported, approved operation. Back up affected configuration and verify service/SQL/replication/backup health afterward. Never delete state markers or data to bypass a safety refusal.

Changing `.env` affects controller selection only. Changing inventory desired state does not migrate data, rotate certificates, move a VIP to another subnet, alter DNS or convert topology automatically. Those changes require coordinated maintenance. Historical guides use anonymized examples; raw local deployment evidence and private inventories are preserved separately and must not be distributed as defaults.
