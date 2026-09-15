# Deployment record

> Portable configuration: start with [the external deployment setup](environment-portability.md). Addresses in this guide are documentation-only ranges, names are examples, and `/home/OPERATOR` means your controller account. Read measured results as anonymized historical evidence; obtain real values from your own inventory and discovery.

This is historical evidence, not the current installation procedure. Use
[installation](installation.md), [environment settings](environment-settings.md)
and [validation](validation.md) for current interfaces, defaults and scope.

> Historical deployment record: node service addresses were migrated on 13 September 2026. See [the migration record](ip-migration.md) for current addresses and subsequent validation.

Validated on 2026-09-12. This record separates selected policy, measured behavior and infrastructure limits.

## Deployed topology

| Node | Management IP | Service IP | Final PostgreSQL role | VIP owner |
| --- | --- | --- | --- | --- |
| pg1 | 192.0.2.21 | 198.51.100.21 | Replica | Yes |
| pg2 | 192.0.2.22 | 198.51.100.22 | Primary | No |
| pg3 | 192.0.2.23 | 198.51.100.23 | Replica / backup repository | No |

Roles and VIP ownership are runtime observations and can move. Final system ID: `SYSTEM_IDENTIFIER_FROM_DISCOVERY`; timeline: 5. All three etcd voters are healthy. Both replicas stream with bounded lag and one is synchronous. All functional monitors report healthy.

Application endpoint: `postgres.db.example.com`, VIP `192.0.2.50`, write port 5000, replica read port 5001, database `appdb`, role `app_owner`. External clients need DNS/hosts publication or libpq host plus hostaddr. Client certificates are not required; clients verify the database CA and authenticate using SCRAM.

Ubuntu 22.04.5, PostgreSQL 17.11, Patroni 4.1.5, etcd 3.5.33, HAProxy 2.4.30, PgBouncer 1.25.2, Keepalived 2.2.4 and pgBackRest 2.59.1 are installed. Exact package versions and full installed manifests are retained in inventory and artifacts.

Each VM has two vCPUs, approximately 3.8 GiB RAM, a 6 GiB PostgreSQL LV, a 512 MiB etcd LV and a 1 GiB backup LV. These are explicit initial capacity limits, not workload sizing certification. No root filesystem was shrunk or reformatted. No existing database data was deleted.

## Network and VRRP

Stable service addresses and VIP are outside the observed VMware DHCP pool (192.0.2.128–254). Original management DHCP remains intact. ARP duplicate checks, stable source routes, authenticated peer connectivity, exactly one reachable VIP owner and actual client SQL passed. HAProxy and Keepalived outages on the current VIP owner recovered successfully.

An ARP probe is not an external IPAM reservation. Managed hosts entries are not authoritative DNS. Arbitrary asymmetric partitions and hidden VIP claimants have not been exhaustively tested.

## Firewall policy

A dedicated inet pg_ha table permits established traffic, ICMP, DHCP, restricted management SSH, exact-peer control-plane traffic, VRRP and declared application ports. Other firewall tables are preserved. Native validation and fresh SSH reconnect passed before timed rollback cancellation. Its normalized fingerprint remains unchanged after reboot and failure tests.

## Fencing test

Actual primary Patroni suspension triggered watchdog reboots, followed by leader election and rejoin without recreating data. The first reboot exposed missing watchdog provisioning at startup. The repair adds an explicit watchdog service dependency, udev readiness and a bounded clock-synchronization check before Patroni starts. The repeated test passed all post-reboot checks.

| Workload window | Acknowledged commits | Missing acknowledged commits | Largest observed interruption |
| --- | ---: | ---: | ---: |
| Five single-service failures | 2,075 | 0 | 35.537 s |
| First watchdog test | 952 | 0 | 46.441 s |
| Corrected watchdog retest | 880 | 0 | 61.816 s |

Service tests deliberately held one component stopped for 20 seconds, restored it, and verified complete health before the next test. The Patroni service test moved primary ownership from pg2 to pg3; watchdog tests subsequently exercised further elections. These measurements are bounded canary results, not an availability SLA or throughput benchmark. Failed/in-flight transactions require application reconciliation and retry discipline.

Strict synchronous replication protects acknowledged writes against one eligible-node failure. Loss of every eligible synchronous standby blocks commits. Software watchdog testing does not prove fencing under hypervisor freeze or shared hardware failure. Physical host, storage, power and network independence has not been established.

## Backup restore test

pgBackRest stanza checks, complete encrypted full backup and WAL archiving passed. An isolated restore recovered the committed application marker and matching database identity. A separate point-in-time restore to `2026-09-12 17:56:17.994310+00` included the earlier committed marker and excluded the later marker. Recovered instances used isolated directories and Unix sockets with no TCP listener or archiving, and were stopped after verification.

Daily full backups are scheduled at 02:15 UTC with randomized delay and catch-up. Retention is two full backups. The selected archival interval is 60 seconds; the one-hour recovery objective is a target for workload qualification, not a measured guarantee for an unknown production data size.

An encrypted repository export is stored outside the VMs at `/home/OPERATOR/.local/share/pg-ha/exports/pg-ha-20260912.tar` on the WSL controller. Source and destination SHA-256 match: `c4d3fb98a992bf823f6c5fcbfd972873a4fea2a40a60d78125200114a02d9120`. Export size: 8,243,200 bytes. Archiving resumed and passed its check after the bounded export pause. The actual exported archive was then verified on pg1 with pgBackRest 2.59.1, including backup and WAL checksums, without contacting pg3. The export is not an off-site or immutable backup, and it is not a continuously replicated second repository.

## Repository provenance

Target nodes use scoped signed PGDG metadata and the verified signing-key fingerprint `B97B0AFCAA1A47F044F244A07FCC7D46ACCC4CF8`. etcd uses the upstream 3.5.33 archive pinned to SHA-256 `5025b5b24d81a9616b6e284ccd439b9a3df055ef8fdcdc142af3ec8f6a3b3c95`. Exact component pins do not constitute an immutable mirror of every transitive dependency.

The pre-existing WSL controller has unrelated repositories configured with `trusted=yes`. A broad metadata refresh for an optional verifier was stopped; repository verification uses the target's already validated installation. Production controller qualification should use a dedicated controller with signed repositories. Target repository security was not weakened.

References: [PGDG installation](https://www.postgresql.org/download/linux/ubuntu/), [etcd release](https://github.com/etcd-io/etcd/releases/tag/v3.5.33), [pgBackRest commands](https://pgbackrest.org/command.html), and [Patroni configuration](https://patroni.readthedocs.io/en/latest/yaml_configuration.html).

## Monitoring and alerts

Minute-by-minute SQL role, replication, etcd, disk-capacity, certificate-expiry and backup-age checks are enabled on all nodes. All final checks report healthy. Status is in `/var/lib/pg-ha-monitor/status.json` and journald. No external alert receiver or delivery test is configured; local status alone is insufficient for unattended business-critical operations.

## Exclusive change lock

The controller runner holds an inherited Linux advisory lock. It prevents concurrent project playbooks on that controller, not manual changes or another controller. Destructive recovery and membership changes remain deliberate operational workflows.

## Final validation

Two independent verification passes succeeded with unchanged service PIDs and activation timestamps. No services restarted during repeat verification. All three final monitors passed. See `artifacts/final-deployment.json`, per-scenario evidence, full package manifests and [validation](validation.md). Local safety tests, syntax checks, native parsers and isolated routing integration supplement the real deployment evidence.
