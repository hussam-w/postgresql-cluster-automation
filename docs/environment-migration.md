# Deploying the project in a different environment

> Portable configuration: start with [the external deployment setup](environment-portability.md). Addresses in this guide are documentation-only ranges, names are examples, and `/home/OPERATOR` means your controller account. Read measured results as anonymized historical evidence; obtain real values from your own inventory and discovery.

This is a portability and preparation checklist, not a live data-migration tool. Creating a new deployment and moving an existing production database are different operations. The repository does not automatically move data, convert standalone to HA, replace DCS membership, rotate credentials or change network addresses in response to inventory edits.

Follow [installation](installation.md) after completing this review. Use [environment settings](environment-settings.md) for each variable's default, purpose and impact. The reference pg1/pg2/pg3 addresses, accounts, small storage allocations and backup placement are deployment examples only.

## 1. Establish the target and ownership

Create an isolated environment inventory and protected controller directory. A separate checkout/controller context avoids accidental use of reference utility paths and shared artifacts. Use one external change coordinator across controllers. Assign owners for infrastructure, database access, PKI renewal, backups, alerts and incident response.

Run observation first, even on allegedly new VMs. Record OS/architecture, installed PostgreSQL versions, active/offline clusters, data/config paths, tablespaces, services, listeners, certificates, package repositories and storage. Resolve incomplete coverage before changing anything. Existing resources remain authoritative until a specific ownership/migration decision is reviewed.

## 2. Review every environment-dependent category

| Review item | What to change or verify | What should remain consistent / acceptance evidence |
| --- | --- | --- |
| Inventory | Separate `inventories/<env>/hosts.yml`, group_vars and host_vars; remove reference hosts | All selected hosts reachable; complete exact membership; no hidden contradictory overrides |
| Actual IPs | `ansible_host`, `node.address`, or standalone TCP address; use reserved VM addresses | No routine network rewrites; verify IPAM/DHCP reservations and observed routes |
| Hostnames | Inventory name and actual hostname for HA/platform checks | Unique stable identity; never reuse a failed member name while it can still participate |
| DNS | Node names, VIP DNS, peer resolution, external application resolution | TLS SANs match names/IPs; hosts-file management does not publish external DNS |
| VIP/subnet | `cluster.vip`, prefix, VRID, router priorities; aligned platform fields | Supported common IPv4 subnet, unicast VRRP/IP protocol 112, no conflicting owner; validate network platform support |
| SSH | User, port, key/agent or hidden password, verified known-hosts file, sudo policy | Strict host-key checking, minimal approved access, working out-of-band recovery |
| Secrets | New service/application passwords and repository cipher key; protected Vault paths | Never copy another environment's live credentials; preserve old keys for recovery history |
| PKI | New node/VIP SANs, service EKUs, trusted CA domains, private-key paths and rotation ownership | Verified TLS/SCRAM remain enabled; existing generator leaves are not automatically renewed |
| OS/packages | Ubuntu 22.04 amd64, qualified major, exact package/artifact pins from approved repositories | No implicit major/version upgrades; transitive provenance and restore compatibility reviewed |
| Storage devices | Actual VG/LV or externally supplied mounts, ownership tags and unused capacity | Never repurpose an unknown disk/LV; no forced format/shrink; storage opt-in only when expressly required |
| Filesystem paths | HA data/etcd mounts and subdirectories, standalone data/mount, backup path | Canonical/nonoverlapping paths, permissions, capacity/IOPS and recovery space verified |
| WAL/tablespaces | Discover current layout; account for WAL, slots and existing tablespaces | The optional [storage layout](storage-layout.md) supports fresh external WAL; live relocation and tablespace provisioning need separate work |
| Network ranges | SSH, application/admin CIDRs, actual NAT sources, peer routes and interface names | Firewall and HAProxy/HBA policies all agree; preserve management reachability |
| Ports | Cluster ports and platform_ports, backup_port; standalone port | Distinct supported ports; update certificates/clients/probes/firewall dependencies where relevant |
| Topology | Initial primary, read replicas, eligible standbys, core group and count assertions | Runtime primary may differ after failover; three etcd voters, no automatic live role conversion |
| Resources | RAM/CPU/admission floors, buffers, connections/pools, WAL limits and timeout budgets | Size from workload and failure behavior; reference VM values are not production recommendations |
| Durability | Strict-sync count or explicitly acknowledged async, lag and watchdog timing | Qualified fencing and quorum; no promise of zero loss from labels alone |
| Extensions | Required optional names, compatible pinned packages, per-database list and preloads | Baseline/dependencies automatic; existing version retention; separately planned preload maintenance |
| Backup | Repository host/path/port/cipher, actual retention, restore helpers, scheduling, RPO/RTO | Test restoration independently; S3/immutability are not implemented inventory options |
| Monitoring | Application identity, service endpoints, backup assumptions, external alert destination | Current timer is HA-specific and assumes local etcd; qualify extra nodes separately; no Prometheus deployment |
| Feature controls | Each platform_manage flag, model operation and optional installation | False means skip management, not uninstall; remove one-time approvals after use |
| Evidence | Actual review tickets, fencing/restore/network/load test results | Nonempty evidence text is not machine proof; report unqualified scopes explicitly |

## 3. Change values in their owning layer

Update environment inventory/model files for supported settings. Do not search-and-replace reference IPs throughout the automation. Fixed service paths, watchdog/TLS/integrity safeguards, backup-template constants and unsupported adapters need reviewed implementation changes rather than invented inventory fields.

Use the actual model field `postgresql_deployment.major`, not `postgresql_version` or an imagined upgrade switch. Use `postgresql_deployment.extensions`, not an undocumented `postgresql_extensions` alias. Keep `cluster.bootstrap_host` equal to the initial-primary model field. Do not change it to chase every failover.

Set host TLS pointer paths after issuance. Updating a DNS name in inventory does not update an existing certificate. Review related PostgreSQL, PgBouncer, Patroni, etcd, HAProxy and backup trust/name consumers together. Do not carry old authorization hashes into a new environment: observe its identity and generate a new plan.

## 4. Validate before admitting workloads

1. Validate the controller/runtime and all YAML/model/HA contract inputs locally.
2. Verify SSH identities and observe every target. Resolve incompatible existing state rather than wiping it.
3. Confirm package candidates, mounted capacity, address/port availability, DNS, TLS, firewall and fencing prerequisites.
4. Select the correct standalone or HA first-run procedure with scoped operation files.
5. Verify runtime identity, configuration parsing, extension state and intended connection access.
6. For HA, verify one primary, streaming/sync behavior, DCS health, routing and single reachable VIP ownership.
7. Test application semantics, bounded retries, backup restoration and the required failure cases in staging.
8. Measure a repeat run: already-compliant state must remain unchanged; investigate any unexpected changes/restarts.
9. Enable and verify separately approved schedules/alerts, then preserve evidence and recovery material before cutover.

## 5. If production data must move

Select a separately reviewed replication/backup/restore/logical-migration method compatible with source and target versions, extensions and data size. Establish rollback criteria, application write coordination, consistency checks, outage budget and credentials/certificate cutover. Fence the old authority before exposing a replacement writer or VIP. Preserve the source until acceptance and retention requirements are satisfied.

The historical `ip-migration*` playbooks are bound to the reference cluster and recorded lineage; they are not generic migration commands. The retained source and recovery evidence must not be deleted merely because a new inventory is accepted. Configuration rollback is not database rollback, and restored stale DCS state must not join an unfenced live cluster.
