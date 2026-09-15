# Environment and variable contract

> Portable configuration: start with [the external deployment setup](environment-portability.md). Addresses in this guide are documentation-only ranges, names are examples, and `/home/OPERATOR` means your controller account. Read measured results as anonymized historical evidence; obtain real values from your own inventory and discovery.

For the cross-mode default/required/source reference start with
[environment settings](environment-settings.md). Follow [installation](installation.md)
for commands and [feature controls](features.md) for supported switches. The
inventory/storage/network contract below is specifically the Type A HA contract;
standalone uses the separate `standalone` mapping and has no etcd/router groups.

The original deployment targeted **Ubuntu 22.04** and **PostgreSQL 17** on fresh nodes. Routine execution now treats every target as potentially containing production data. See [safe re-execution](safe-reexecution.md) for the discovery/reconciliation contract. The strict contract below applies to fresh HA provisioning and managed-cluster verification, not to generic existing-instance inspection. Every other
environment value is explicit. The bootstrap example inventory is deliberately unusable.
`module_utils/cluster_contract.py` is the executable validation contract.

Current reference addresses are pg1 `192.0.2.21`, pg2 `192.0.2.22`, and pg3 `192.0.2.23`, used for both management and services. VMware MAC reservations exclude them from the dynamic pool; the shared VIP remains `192.0.2.50`. See [migration record](ip-migration.md).

## Inventory and storage

`postgres_cluster` contains every database node. Exactly three of those nodes
belong to both `etcd_cluster` and `routers`. Extra replicas can be included at
first deployment; later additions require the membership runbook. Node names
must be safe identifiers. Every `node` needs a unique IPv4 `address`, resolvable
`dns_name` matching the system hostname, and the core nodes require `interface`, unique `priority` (1..254),
distinct `failure_domain` and a reviewed `firewall_sha256`.

Component ports are configurable through cluster.ports. Validation requires distinct unprivileged TCP ports; the network table shows the deployed defaults. IPv4 on one common router/VIP subnet is the supported profile. IPv6, routed VIPs,
cloud anti-spoofing exceptions and managed load balancers require another qualified
network profile. A declared failure domain is evidence supplied by the operator;
Ansible cannot prove independent power, storage or hypervisors.

`cluster.data_dir` and `cluster.etcd_data_dir` must be separate dedicated
subdirectories under the explicitly mounted `postgres_mount` and `etcd_mount`.
Only operator-approved ext4/xfs are accepted. Provision storage capacity,
persistent mounts, ownership, latency and IOPS before deployment. Set
`min_free_bytes`, `min_ram_mb`, `min_vcpus` from your workload/resource plan. These
minimums are admission thresholds, not an automatic PostgreSQL sizing algorithm.

Do not use symlinks or overlapping mount/data paths. Vendor data directories and
active vendor services must be empty/inactive. Fresh machines may already have a
`postgres` account to support permanent watchdog device ownership, but must not
contain a database cluster.

## Network policy

| Source | Destination | Required traffic |
| --- | --- | --- |
| Controller | All hosts | Configured SSH port; verified host keys and sudo |
| Core etcd nodes | Core etcd nodes | TCP 2380, peer mTLS |
| Patroni nodes | All etcd nodes | TCP 2379, DCS mTLS |
| Patroni peers, routers, approved operators | All Patroni nodes | TCP 8008, management mTLS; mutation additionally requires Basic auth |
| PostgreSQL nodes | PostgreSQL nodes | TCP 5432, verified TLS/SCRAM for replication |
| Each local pooler | Its own PostgreSQL address | TCP 5432, verified TLS/SCRAM |
| All routers | Every pooler | TCP 6432, PostgreSQL protocol with client TLS passthrough |
| Clients/approved operators | VIP and permitted router listeners | TCP 5000 and 5001 |
| Core routers | Core routers | IP protocol 112 (VRRP), unicast; **not UDP port 112** |
| Nodes | Approved DNS/time/backup/repository services | Explicit organizational egress policy |

HAProxy binds IPv4 wildcard listeners so non-VIP nodes can start without enabling
nonlocal binding. Frontend source ACLs permit only `client_cidrs`/`admin_cidrs`.
The host/network firewall must additionally restrict traffic and DCS/management
exposure. The platform role provisions a dedicated table, preserves unrelated tables, and records the normalized effective policy fingerprint. Include source addresses actually visible after NAT in the reviewed ACL.
There is no PROXY protocol; PostgreSQL sees the pooler identity/address.

Preflight compares the normalized nftables ruleset SHA-256 with node.firewall_sha256. Use the supplied firewall_policy_info module; volatile handles, counters and metadata are excluded without ignoring policy. A policy change requires review. Preflight also checks time synchronization, addresses, DNS, routes, storage, listeners and existing state. Runtime TLS/SQL and consensus checks establish actual service connectivity.

## PKI and secrets

Supply per-host `tls_sources` entries, each with `ca`, `cert`, `key` paths on the
controller. These paths may point to protected files or Vault-encrypted files
supported by the copy action. HAProxy bundle assembly uses the file lookup, so
its source key must be securely decrypted in the controller's temporary workspace
for that step. Do not commit it. A secret manager/ephemeral runner can supply files.

| Entry | Owner | Issuing trust domain | Required identity/use |
| --- | --- | --- | --- |
| postgres | postgres | Database | Node DNS SAN; server authentication |
| pgbouncer | pgbouncer | Database | Node and VIP DNS SANs; server authentication |
| patroni | postgres | Management | Node DNS SAN; server and client authentication |
| haproxy (core only) | root | Management | Node DNS SAN; client authentication |
| etcd (core only) | etcd | DCS | Node DNS SAN; server and client authentication |
| dcs | postgres | DCS | Node DNS SAN; client authentication |
| backup | postgres | Backup | Node DNS/IP SAN and node-name CN; client/server authentication |

Use one distinct root CA per domain; intermediate chains go into `cert.pem`,
with the leaf first. Do not share roots across these four domains. CA equality
checks use DER fingerprints. Each leaf must have at least 30 days remaining at
installation. OpenSSL checks chain, names, purpose and key pairing; service health
checks verify that hosts trust each other. DCS has a dedicated cluster and uses
mTLS admission, not etcd per-key RBAC. Possession of a DCS client key grants broad
DCS authority; issue it only to cluster services and authorized operators.

Vault variables: `vault_pg_superuser_password`, `vault_pg_replication_password`,
`vault_patroni_api_password`, `vault_backup_cipher_pass`, and `vault_app_users` (list of name/password mappings).
Passwords must be at least 24 characters. `application_databases` supplies explicit
name/owner mappings. Application roles have no cluster administration privileges.
Database owners can change their own database schema; use migrations and grant
policies appropriate to the application. Initial SQL roles/databases are created
only once by this bootstrap workflow. Production rotation is staged separately.

Secret tasks suppress output and diffs; configuration/key files are private.
Do not enable Ansible callback plugins or persistent fact logging that capture
module arguments/results. Treat root-readable configuration backups, archived
controller workspaces and etcd snapshots as sensitive. No passwords are passed
in shell arguments. Never use `--diff` for the secret deployment path.

## Policy, binaries, fencing and backup

Provide every numeric field in the example, including replication lag, timing,
WAL retention, slots, memory, pool and connection budgets. `strict_sync` requires
1..N-1 synchronous nodes; loss of all eligible synchronous replicas blocks writes.
`async` requires zero synchronous nodes and explicit data-loss acknowledgement.
Watchdog timing must satisfy `loop_wait + retry_timeout < ttl/2` as well as
Patroni's `loop_wait + 2*retry_timeout <= ttl` constraint. Select values from measured
latency and scheduling behavior. The software does not measure worst-case latency.

Pool caps apply to each database on each node. Aggregate all per-database caps,
reserved connections, replication and maintenance capacity against PostgreSQL's
per-node limit. Transaction pooling requires an application compatibility review;
session-affine features may require session pooling.

The platform provisions softdog, device ownership and a dedicated watchdog startup unit. Patroni requires it and waits for time synchronization before startup. Preflight never opens or arms the device. The explicit watchdog-acceptance playbook suspends only the current primary authority, provides a timed fallback, and proves reboot and complete rejoin. Hardware/hypervisor fencing still needs platform-specific qualification.

Package paths are `/usr/bin/patroni`, `/usr/sbin/{haproxy,pgbouncer,keepalived}`, `/usr/lib/postgresql/<major>/bin` and checksum-pinned `/opt/pg-ha/etcd/<version>/{etcd,etcdctl}`. The etcd account is explicitly provisioned. Vendor database units are masked; do not independently start PostgreSQL. Plan patching as rolling maintenance and qualify transitive dependencies. General OS unattended updates were not globally disabled.

The managed pgBackRest integration uses its native archive-push command, protected cipher credentials, a separate TLS trust domain and explicit backup_repository_host/path/port. The generic archive/restore executable contract remains available for externally provisioned integrations. Daily full-backup scheduling is enabled only after backup acceptance; isolated restore and point-in-time tests preserve the live cluster. A one-time encrypted controller export supplements the colocated repository but is neither off-site nor continuous disaster recovery.
Every `cluster.evidence` field records an actual change ticket/test artifact:
network/VRRP, firewall, fencing, backup restore, repository provenance, monitoring
and an externally held exclusive deployment lock. A nonempty reference is only an
audit link; it is not a machine-verifiable proof that the test passed.
