# Architecture and safety analysis

> Portable configuration: start with [the external deployment setup](environment-portability.md). Addresses in this guide are documentation-only ranges, names are examples, and `/home/OPERATOR` means your controller account. Read measured results as anonymized historical evidence; obtain real values from your own inventory and discovery.

## Deployment models

`postgresql_deployment.mode` selects standalone or Type A cluster operation;
without a model, `site.yml` remains generic read-only discovery. PostgreSQL 14+ selection on
Ubuntu 22.04 is implemented; live qualification remains strongest for major 17.
See [version selection and qualification](postgresql-versions.md).

Standalone provisions one PostgreSQL service and a local Unix socket by default.
It has no Patroni, etcd, pooler, routing, VIP, replication, integrated backup timer
or HA monitor. TCP requires an existing local address, approved CIDRs and TLS.
Existing standalone instances can use scoped parameter/extension workflows without
adoption. Backup and external monitoring readiness require separate work.

Cluster topology assigns every inventory host to exactly one initial-primary,
read-replica or eligible-standby role. Three hosts are etcd/router core nodes;
additional database nodes do not increase DCS quorum. Initial-primary selection
does not undo failover. Read replicas have `nofailover` and `nosync` set; eligible
standbys do not. See [deployment models](deployment-models.md) for exact variables.

The sections below analyze Type A specifically. Fresh standalone and five-node
deployment qualification remains distinct from the tested three-node environment.

## Scope and dependencies

The supplied Type A drawing defines three core machines, each running etcd,
Patroni/PostgreSQL, PgBouncer, HAProxy and Keepalived. Additional PostgreSQL
replicas need Patroni and PgBouncer but must not implicitly become etcd voters
or VIP candidates. Applications use the VIP on TCP 5000 for writes and 5001
for replica reads. HAProxy forwards PostgreSQL protocol to PgBouncer, which
connects only to its local PostgreSQL instance. Patroni owns PostgreSQL startup,
shutdown, replication and promotion. No distribution PostgreSQL service may
independently start the same data directory.

Dependency order: validated hosts/network/storage/PKI/fencing -> etcd quorum ->
one deliberately selected bootstrap Patroni node -> streaming replicas ->
database identities -> PgBouncer -> HAProxy -> VIP -> application-side probes.
etcd bootstrap needs all initial members configured before waiting for quorum;
serially starting and waiting for the first member would deadlock.

## Decisions made before implementation

| Problem | Selected design and trade-off |
| --- | --- |
| Co-located failures | Exactly three initial etcd voters on distinct failure domains. One core host failure consumes the entire single-failure budget. Shared storage, rack, switch, power, hypervisor or AZ failures can defeat this topology. No automation can infer physical independence. |
| Stale primary | Require a tested watchdog, `mode: required`, with half-TTL expiration. Hardware/hypervisor fencing must be proven to cover host/VM pauses. Software watchdog alone does not prove protection against hypervisor suspension. No automatic destructive rewind or data-directory removal. |
| DCS loss | Keep Patroni DCS failsafe mode disabled in this implementation. Losing quorum sacrifices write availability; never force a new etcd cluster to make a primary appear. |
| Durability | Replication mode, synchronous replica count, lag limits and all timing values are mandatory policy. Strict synchronous replication trades write availability for durability. Asynchronous operation requires an explicit acknowledgement of possible acknowledged-transaction loss. Neither mode replaces backups or prevents privileged clients changing session durability settings. |
| VIP vs leader | VIP holder is a router, not necessarily the primary host. Track functional HAProxy backends, never local PostgreSQL leadership. A routing host may forward to a remote primary. |
| Routing | Combine Patroni `/primary` or lag-bounded `/replica` HTTPS checks with a PgBouncer TCP check. Terminate existing backend sessions when a server is marked down. This detects listener availability; authenticated SQL probes additionally test pool/database functionality. Read routing never falls back to primary. |
| VRRP partitions | Keepalived cannot guarantee unique VIP ownership across every L2 partition. Require validated unicast VRRP, allowed IP protocol 112, peer reachability, gratuitous ARP support and a network design that prevents competing VIP advertisements. A managed network load balancer is required where the platform does not support this model. Duplicate VIP detection must alert operators. |
| Connection failover | Existing connections and in-flight transactions can fail. Clients need bounded reconnect backoff, transaction retry and application-level idempotency. No claim of transparent session migration or zero downtime. Read replicas are eventually consistent unless the application supplies additional consistency coordination. |
| TLS | Protected controller PKI or externally issued certificates; mandatory hostname/IP SAN verification and deliberate rotation. etcd peer and client mTLS, Patroni HTTPS/mTLS, PgBouncer client TLS and verified local PostgreSQL TLS. Pooler certificates must cover the application VIP DNS name as well as their node identity. Do not mint a production CA inside this repository. |
| Secrets | Vault-provided credentials; restrictive file ownership/modes; no diffs/logging for secret tasks. SCRAM verifiers in PgBouncer must be the exact PostgreSQL verifiers. Independent SCRAM generation with the same password does not work. Private configuration backups are secrets too. |
| Install policy | OS, versions, repositories and package artifact provenance require an explicit target profile. Do not install unpinned latest packages, modify repositories or enable distribution database services speculatively. |
| Bootstrap | Explicit new-cluster authorization; inventory-wide checks before changes. Nonempty database/etcd directories, foreign configuration or mismatched metadata block bootstrap. Partial bootstrap is a separate recovery decision, not an implicit retry with fresh identity. |
| Routine change | Validate candidates before activation; backup current configuration; serial orchestration with full cluster health gates. Restart-required changes are separate maintenance work. Bootstrap DCS settings are immutable inputs after initialization; changing local YAML is not a dynamic policy change. |
| Replica recovery | Existing divergent or WAL-starved replicas stop for operator review. Never delete directories, slots, WAL or etcd members. A reviewed replacement procedure must retain recoverable state. |
| Backups | Backup destination, encryption, retention, RPO, RTO and restore evidence are mandatory production inputs. Replication is not backup. Archive failure and slot retention can fill the primary disk. |
| Scale out | Adding a replica changes pool capacity and replication slots and may exhaust primary connections/WAL space. Treat as explicit membership/provisioning work, preserving three etcd voters. |

## Failure, race and rollback analysis

Concurrent controllers must be excluded by the deployment system; Ansible's
`serial` does not lock out a second operator. Bootstrap ownership must be chosen
once, with a unique cluster name/token, an empty DCS namespace and no existing
PostgreSQL system identifier. An offline node cannot be treated as empty.
All required hosts must be reachable before first deployment.

Pool sizing must budget all clients across all poolers and database/user pools,
including reserve pools, health probes, administrative sessions, replication and
failover reconnections. Defaults based on unknown RAM/CPU are unacceptable.
Finite slot WAL limits bound disk use but can invalidate a replica; recovery is
then an explicit operation. Monitor remaining bytes and growth rate, not only
percentage utilization. Time synchronization, low etcd disk latency and bounded
network RTT must be established before selecting election and Patroni timeouts.

Reloads can preserve active sessions, but certificate/authentication rotations
need overlap and staged verification. HAProxy down-session shutdown can interrupt
transactions. PgBouncer restart drains require application coordination. Patroni
and PostgreSQL restarts must operate replicas first, with a reviewed switchover
before restarting the former primary. etcd member restarts require a healthy
quorum and one member at a time. Keepalived changes can move the VIP.

Restore a previous configuration only when its binaries, keys and dynamic state
remain compatible. Do not automatically downgrade binaries, revert database
state, restore stale etcd snapshots or resume an unfenced former primary.
Configuration rollback is not a database rollback.

## Environment-specific qualification

The reference three-node environment has a deployment record and measured tests.
Its addresses, small resource allocations and backup placement are examples, not
defaults for other installations. Every new environment needs its own inventory,
package provenance, storage, network, PKI, recovery objectives and representative
failure/restore evidence. Consult [validation](validation.md) for tested scopes
and outstanding limitations.

## Primary references

- [Patroni watchdog](https://patroni.readthedocs.io/en/latest/watchdog.html)
- [Patroni replication modes](https://patroni.readthedocs.io/en/latest/replication_modes.html)
- [Patroni REST health semantics](https://patroni.readthedocs.io/en/latest/rest_api.html)
- [Patroni configuration and bootstrap DCS semantics](https://patroni.readthedocs.io/en/latest/yaml_configuration.html)
- [etcd clustering](https://etcd.io/docs/v3.5/op-guide/clustering/)
- [HAProxy multi-step health checks](https://www.haproxy.com/documentation/haproxy-configuration-tutorials/reliability/health-checks/)
- [PgBouncer TLS and SCRAM requirements](https://www.pgbouncer.org/config)
