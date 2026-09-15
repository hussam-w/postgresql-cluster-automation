# Failure acceptance matrix

> Portable configuration: start with [the external deployment setup](environment-portability.md). Addresses in this guide are documentation-only ranges, names are examples, and `/home/OPERATOR` means your controller account. Read measured results as anonymized historical evidence; obtain real values from your own inventory and discovery.

Scope: the measured results here concern the reference three-node Type A cluster.
They do not qualify fresh standalone or five-node operation. These are separately
authorized disruptive acceptance procedures, not routine `plan`/health commands.
Use [installation](installation.md) for setup and [safe re-execution](safe-reexecution.md)
for exact maintenance gates; retain each test's own additional confirmation.

Live SQL, encrypted backup and isolated restore acceptance have passed. Five bounded single-service failure tests, primary watchdog reboot/rejoin, repeat verification, and point-in-time recovery passed with verified-TLS canary workloads. See [validation](validation.md), [deployment record](deployment-record.md), and the nonsecret artifacts for measured results. Rows below define expected behavior; a row is not itself evidence of execution. Explicitly selected fault playbooks restore the tested service and verify the whole cluster before continuing.

For every experiment, record: ticket and operators, versions/config hashes,
initial leader/system ID/timeline, etcd cluster/member IDs and health, VIP owner,
replication mode/lag, backup/restore evidence, workload/connection count, monotonic
timestamps, committed transaction IDs, client errors, RPO/RTO and post-recovery
evidence. Client probes must originate from the actual application network and
validate TLS hostnames. A successful SELECT on the server is insufficient.

Run a canary writer with unique idempotency keys and an independent commit log;
verify acknowledged outcomes after recovery. Classify unknown commit outcomes
separately from confirmed aborts. Read probes on 5001 must report recovery=true;
write probes on 5000 must report recovery=false and successfully commit a canary
transaction. Never use business data as the fault-test scratch area.

| Scenario / detector | Decision and protection | Client / replication impact | Recovery, rejoin and acceptance |
| --- | --- | --- | --- |
| First deployment; preflight and health gates | Controller admits only fresh nodes; etcd reaches quorum before Patroni; only selected bootstrap host initializes | No application traffic until replicas/pools/routing pass | One system ID/timeline, one leader, expected voters, streaming replicas, valid SQL via both VIP ports, archive/base backup and restore evidence |
| Repeated verify; Ansible/fingerprint checks | Read-only checks; no service mutation | No expected session interruption | Run twice; zero changed tasks, stable PIDs/uptime and no config/package drift |
| Partial deployment; preflight state inspection | Stop bootstrap on any existing state; no destructive retry | Incomplete service may be unavailable; strict sync can block writes | Follow state-specific continuation; preserve original IDs and verify all roles before traffic |
| PostgreSQL replica process failure; Patroni/HAProxy | Exclude unhealthy replica; primary authority unchanged | Read connections to failed replica drop; sync policy may block writes if no other eligible sync node | Patroni restarts intact data; verify WAL receiver, streaming state, timeline and replay lag before re-admission |
| PostgreSQL primary process failure; Patroni and DCS | Patroni may restart locally or eligible replica takes lease; fencing protects old primary | In-flight transactions/primary sessions can fail; replication source may change | Confirm at most one writable primary throughout; reconcile commit log and rejoin old node only on safe timeline |
| Patroni killed or suspended; watchdog/DCS/HAProxy | Required watchdog must fence before a successor can overlap | Primary connections drop; replicas await/elect eligible primary | Prove watchdog expiration under real CPU starvation/VM pause; no concurrent acknowledged writes on two nodes |
| One etcd member fails; etcd quorum/metrics | Two voters retain quorum; no membership mutation | Database remains available subject to other policy | Restart original member with intact identity; verify cluster ID, healthy endpoint and caught-up Raft state |
| Two etcd voters fail; Patroni lease expiry/watchdog | No quorum; no safe election; fail closed, failsafe mode off | Writes stop even if SQL process/network initially appears healthy | Recover original quorum; never force-new-cluster; verify no divergent primary before clients resume |
| Core node loss; peers, DCS, HAProxy, VRRP | Simultaneously lose one voter/database/router; remaining two must suffice | Sessions on failed path drop; VIP and/or primary may move independently | Confirm surviving quorum, eligible sync failover, bounded retry, safe original-state rejoin |
| HAProxy process failure; Keepalived script | Fault VIP candidate with unusable local routing | VIP moves; established sessions do not migrate | Restore HAProxy, validate role/pool checks, permit eligibility after rise threshold; no VIP oscillation |
| PgBouncer failure with healthy PostgreSQL/API; multi-step HAProxy check | Reject that backend despite green Patroni role | Relevant pooled sessions fail; another router cannot repair an unavailable primary's only local pooler | Restart/reload pooler safely; authenticated SQL and matching SCRAM/TLS before admission; do not trigger database failover merely to hide pooler failure |
| PgBouncer auth/TLS failure with open listener; authenticated probes | TCP check alone does not detect bad credentials; external SQL monitoring must detect | Authentication failures; listener-only HAProxy check may remain UP | Restore correct verifier/overlapping cert chain; verify each user/database; document this health-check limit |
| Keepalived process failure; peer VRRP timeout | Another healthy router acquires VIP | Reconnect required; PostgreSQL leadership normally unchanged | Verify stale VIP removed on failure/restart, exactly one advertiser from multiple vantage points |
| Replica WAL lag or paused replay; Patroni lag check/SQL metrics | Remove lagged replica from read pool and unsafe promotion eligibility | Less read capacity; session shutdown on mark-down; strict sync behavior depends on eligible set | Restore replay, verify timeline and measured byte lag; never bypass lag checks to regain capacity |
| Temporary packet loss or DNS outage; health checks/DNS/etcd metrics | Debounce transient failures; no stale manual routing overrides | Intermittent timeouts, possible session loss or failover if timers exceed bounds | Validate bounded retry and timer selection against measured RTT; verify role/quorum and DNS on all nodes |
| Primary isolated from DCS but reachable by clients; watchdog/lease | Primary demotes/fences; majority may elect eligible replica | Clients may reach old IP but must never commit there after successor activation | Independently probe old/new primary over the boundary; prove non-overlap and inspect both timelines before rejoin |
| Core 1-versus-2 network partition; etcd majority and fencing | Minority cannot elect; majority must still satisfy replication/fencing policy | Availability depends on sync placement and client reachability | Test all placements of primary/sync replica/client subnet; observe no split brain or forced quorum repair |
| VRRP-only partition; external duplicate-VIP detector | VRRP alone can produce dual VIP ownership; database fencing remains separate | ARP instability or traffic blackhole possible even with one SQL primary | Network profile must prevent/contain this failure; capture advertisements from both partitions; block readiness if duplicate VIP cannot be controlled |
| Application-to-router network interruption; external application probes | Service health on nodes may remain green; network incident owns response | Clients unavailable despite healthy replication | Restore route/ACL; verify SQL from every required client zone; no unnecessary DB promotion |
| Disk pressure/exhaustion or inode exhaustion; OS/Postgres/etcd/backup metrics | Alert before failure; preserve WAL/data; stop unsafe work | Commits/archiving/consensus may fail; eligible replica/fencing policy controls failover | Add/reclaim only reviewed nonessential storage; never delete WAL/slots blindly; verify integrity, archive continuity and replication |
| Unexpected reboot; watchdog/systemd/peers | Persistent identities/data; only managed units start; vendor units masked | Sessions drop; quorum/roles recover under Patroni | Verify mounts precede daemons, device permissions survive reboot, no accidental initdb, safe timeline and bounded recovery |
| Configuration change or rollback; validators/rolling health gates | One component/node at a time; stop on failure; restore only compatible prior config | Reload may be seamless; restart/switchover can interrupt sessions | Measure effect with workload; verify current DCS policy rather than bootstrap YAML; confirm authorized fingerprint migration |
| WAL-starved or divergent former primary; Patroni/operator inspection | No automatic rewind/removal/reinit | Failed node remains unavailable; healthy cluster may continue | Retain evidence; approve new base backup/rewind only after data-loss assessment and verified source; rejoin only after catch-up |
| Backup restore/PITR; backup tool and application consistency checks | Restore isolated, never overwrite active cluster by default | Production unaffected during drill; real cutover requires fencing and approval | Recover to requested point, validate application invariants and WAL chain, measure RPO/RTO; backup existence alone fails acceptance |
| Concurrent controller runs; external change lock | Second writer must be refused before mutations | No interleaved bootstrap/change activity | Demonstrate lock acquisition/expiry behavior in CI/operator system; `serial` alone is not a lock |

Stop any experiment on unexpected leader overlap, ambiguous commit outcomes,
loss of required recovery material or uncontrolled network effects. Restore the
approved baseline, gather complete evidence and revise the design before the next
experiment. A failed safety test must not be converted into a pass by disabling
TLS, fencing, synchronization, lag checks or bootstrap guards.
