# VM address migration — 13 September 2026

> Portable configuration: start with [the external deployment setup](environment-portability.md). Addresses in this guide are documentation-only ranges, names are examples, and `/home/OPERATOR` means your controller account. Read measured results as anonymized historical evidence; obtain real values from your own inventory and discovery.

This records a completed, reference-cluster-specific migration. Do not replay its
helpers for another environment or infer routine network-management permission.
Use [deploying in another environment](environment-migration.md) for preparation
and the [feature matrix](features.md) for current opt-in networking behavior.

## Result and current addresses

The database cluster now uses each VM's requested address for both management and cluster services:

| Node | Current management/service IP | Retired service alias | MAC |
| --- | --- | --- | --- |
| pg1 | `192.0.2.21` | `198.51.100.21` | `02:00:00:00:00:01` |
| pg2 | `192.0.2.22` | `198.51.100.22` | `02:00:00:00:00:02` |
| pg3 | `192.0.2.23` | `198.51.100.23` | `02:00:00:00:00:03` |

The application VIP remains `192.0.2.50`, with write port 5000 and replica-read port 5001. It is intentionally separate from node identity. The final network inspection found only the requested node address on each eth0, plus the VIP on its current owner. No retired alias was present in runtime interfaces, listeners or the combined persistent Netplan configuration.

PostgreSQL system identifier remains `SYSTEM_IDENTIFIER_FROM_DISCOVERY`; no database directory was removed, initialized, rewound or recloned. At the recorded acceptance point, pg2 was primary and VIP owner, pg1/pg3 were replicas, and all members were on timeline 13. Roles can change after this observation.

## Address persistence and network ownership

The requested addresses were inside VMware's previous dynamic range. The host's DHCP configuration now excludes precisely those three addresses from dynamic allocation and reserves each by its verified VM MAC. Other VMware networks and the remaining dynamic addresses were retained.

Dynamic ranges for this subnet are now `.128–.148`, `.150–.154`, `.156–.160`, and `.162–.254`. Configuration is `C:\ProgramData\VMware\vmnetdhcp.conf`; the protected original recovery copy is `vmnetdhcp.conf.pg-ha-before-ip-migration` in the same directory. Applying the reservation required Windows administrator elevation and a brief VMware DHCP service restart.

Each VM's managed Netplan fragment declares its actual address and peer source routes. DHCP remains enabled for the established network profile, with MAC-bound allocation rather than an unreserved lease. A `dynamic` flag in `ip a` may therefore remain; it does not mean the server is free to assign another address to that VM under the reservation. Preserve the reservations if VMware network settings are regenerated or a VM MAC is changed.

All service DNS names now resolve to the requested addresses in the managed hosts files. The DNS names themselves are unchanged. Authoritative external DNS remains an external integration; this migration does not provision a DNS server.

## What changed

- PostgreSQL, Patroni API, etcd, PgBouncer and pgBackRest listeners moved to the actual VM addresses.
- Peer source routes, PostgreSQL HBA, HAProxy backends, Keepalived sources/peers, hosts mappings and the dedicated firewall policy were updated.
- Temporary dual-address listener/HBA/firewall/VRRP overlap was retired after the rolling move.
- All seven leaf-certificate service identities per node now include the actual node IP. Pooler certificates retain both application VIP IP and DNS identities. CA trust domains, private keys, subjects and application passwords were retained; original leaves remain protected for history/recovery.
- Inventory host declarations and per-host policy/TLS source paths were synchronized with deployed state.
- Only reviewed address/certificate changes were advanced in the managed baseline. Unrelated managed file drift remained a failure condition.

New certificate sources are under `/home/OPERATOR/.local/share/pg-ha/production/ip-migration-20260913`. These paths contain public leaf certificates but are kept inside protected controller storage. Private keys and CA files remain at their original protected paths.

## Execution and service interruption

The existing cluster first passed a read-only whole-cluster verification. Preparation saved protected configuration copies, a fresh encrypted PostgreSQL backup and a live etcd snapshot. The migration then admitted both old/new peer address sets, rolled services with quorum/catch-up checks, moved name resolution and routes, applied final listeners, and retired the old aliases with timed network fallback.

There was an **extended write-endpoint interruption during cutover**. This was not a zero-downtime migration. The first final-pass switchover was refused before final configuration changes; candidate selection was corrected to use the currently synchronous, caught-up standby rather than a fixed member.

After alias retirement, native etcd gRPC health succeeded while its HTTP gateway requests timed out. Patroni could not use that gateway, all databases were observed as replicas, and Keepalived withdrew the VIP because no writable backend passed the routing checks. The original 600-second application test could not complete its final query and did not produce a complete acknowledgement-verification report. It must not be cited as evidence of zero lost acknowledged commits across the entire migration.

Recovery retained membership and data. DCS-domain leaves were reissued with correct actual-IP SANs; key pairing, trust and IP identities passed. Refreshing a replica Patroni process alone did not resolve the gateway problem. Restarting each etcd voter individually, while checking quorum, changed each HTTP member-list probe from timeout to HTTP 200. Patroni subsequently resumed leadership and the VIP returned. No forced promotion, DCS reinitialization, unsafe asynchronous fallback or TLS bypass was used.

The evidence establishes the gateway failure and successful refresh; it does not isolate every internal cached connection involved. The migration now includes explicit new-IP certificate checks and a separate HTTP-gateway gate. For any future migration, provision overlapping peer certificate SANs **before** moving source addresses, qualify gateway behavior on the new endpoints, and retain old connectivity until those checks pass. Native gRPC health alone is insufficient for a Patroni installation using the HTTP gateway.

etcd's documented peer authentication checks the source IP against IP SANs when present, and its TLS reload behavior must be considered separately from long-lived connections and gateway state. See the [etcd transport security reference](https://etcd.io/docs/v3.5/op-guide/security/).

The remaining application/management/backup certificates were migrated with graceful PostgreSQL/Patroni/PgBouncer/HAProxy reloads and local backup-server refreshes. Direct node-IP HTTPS and PostgreSQL/PgBouncer `verify-full` SQL tests passed on all nodes; this final certificate step did not require PostgreSQL restarts.

## Validation evidence

Ignored `artifacts/` contains the detailed nonsecret results:

| Evidence | What it establishes |
| --- | --- |
| `ip-migration-final-pg1.json`, `...pg2.json`, `...pg3.json` | Actual interfaces, listeners, persistent Netplan and unchanged PostgreSQL lineage |
| `ip-migration-gateway-pg*.json` | HTTP gateway timeout before refresh and successful authenticated membership afterward |
| `endpoints-evidence.json` | Real write endpoint commit, replicated reads and read-port write rejection |
| `backup-info.json` | Successful post-migration full backup `20260913-070738F` |
| `restore-evidence.json` | Isolated recovery with matching lineage and durable marker; TCP disabled and recovered server stopped |
| `final-deployment.json` | Repeated whole-cluster verification, stable core service identities and healthy local monitors |
| `client-ip-migration-final.json` | Recovery-period 60-second test: 209 acknowledged commits, one failed attempt, no missing acknowledged commits; observed interruption 3.264 seconds within that window |
| `client-ip-migration-stable.json` | Subsequent 30-second test: 111 acknowledged commits, zero failed attempts, no missing acknowledged commits |

These short successful windows are separate from the incomplete full-migration workload. They do not measure the total cutover interruption or prove every transaction outcome during it.

After the remaining service certificates were installed, `ip-migration-closeout.yml` passed repeated whole-cluster verification, backup certificate IP checks on all nodes and `pgbackrest check`. The final monitor observations at approximately 07:19:49 UTC on 13 September 2026 reported all three nodes healthy, with pg2 primary and owning the VIP on timeline 13.

The isolated restore is retained at `/srv/postgres/restore-acceptance-ipmigration20260913` on pg3. It was not connected to the live Patroni namespace and is not running. Retention of test directories requires capacity management; do not confuse them with the live `/srv/postgres/data` directory.

Local validation included 31 unit tests, including HBA ordering, overlapping VRRP identity and firewall-preservation cases. YAML duplicate-key checking, playbook syntax and incomplete-inventory rejection passed. Native daemon validators ran for affected configurations during deployment. Existing off-site backup, external-alert, physical-failure-domain and workload-sizing qualifications remain unchanged.

## Recovery material and maintenance boundaries

Each node retains root-only original configuration under `/var/lib/pg-ha-ip-migration-20260913`, including a phase manifest. Deep1 also retains the etcd snapshot there. These files contain secrets and are not general-purpose public artifacts. Original controller host inventory is in ignored `artifacts/ip-migration-original-hosts.yml`.

The `ip-migration*` playbooks and helper scripts are **scoped historical operations for this exact cluster**, not a reusable general reconciliation interface. Do not replay preparation, intermediate phases or broad original configuration copies against the completed migration. The migration manifest intentionally rejects subsequent unrecorded changes, including the later certificate baseline updates.

Rollback after completion would itself require a coordinated reverse migration of reservations, addresses, certificates, routing and policy. An etcd snapshot is not a routine configuration rollback, and must never be restored into an unfenced live cluster. Continue routine operation with `verify.yml` and the [administrator guide](operator-guide.md).
