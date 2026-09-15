# Production operations and recovery runbook

> Portable configuration: start with [the external deployment setup](environment-portability.md). Addresses in this guide are documentation-only ranges, names are examples, and `/home/OPERATOR` means your controller account. Read measured results as anonymized historical evidence; obtain real values from your own inventory and discovery.

The service, failover and recovery procedures here apply to Type A HA. For standalone
service paths and verification use the [installation guide](installation.md).
Routine `site.yml` defaults to observation; model-selected operations and extension
management are described in [deployment models](deployment-models.md).

## Safe automated operations

`preflight.yml` audits the declared environment. `verify.yml` is a repeatable
read-only whole-cluster check after a successful bootstrap. It checks the recorded
policy/configuration fingerprints and refuses drift. It does not repair drift,
upgrade packages or change dynamic Patroni policy. Always use verified SSH host
keys, the real inventory and an exclusive change ticket/lock.

First deployment is an authorized mutation with a name-bound confirmation.
It installs pinned packages, masks vendor startup units, provisions configuration
and starts services in dependency order. No existing data is replaced. A bootstrap
retry in bootstrap mode is deliberately rejected after state has appeared. An
explicit `deployment_mode=resume` with `bootstrap_confirmation="RESUME <name>"`
requires the exact recorded bootstrap plan, unchanged node policy, and no completed
cluster identity marker. It retains PostgreSQL and etcd data and skips the initial
empty-DCS requirement. Inspect the failed stage first; it does not authorize a
different topology, credential rotation, or recovery of unrelated data. Rerunning `verify.yml` is the supported no-change
idempotency check, not rerunning a cluster-creation authorization.

## Daily operations and observability

Monitor and alert from outside the database failure domain:

- Authenticated application SQL through VIP:5000 and VIP:5001; verify recovery
  role, latency, connection errors and application transaction outcomes.
- Patroni leader count, member state, timeline, pause state, pending restarts,
  watchdog failure, DCS write/lease latency and promotion events.
- `pg_stat_replication` sender state, write/flush/replay LSN and lag; replication
  slot retained bytes and invalidation; checkpoint activity and WAL growth rate.
- etcd quorum and all endpoint health, leader changes, alarms, backend quota,
  fsync latency, member identity and clock/network problems.
- HAProxy frontend/backend stats, role-check failures, PgBouncer waiting clients,
  pool saturation, authentication failures and server connection churn.
- Keepalived state and VIP advertisements from multiple network observation
  points. An inventory snapshot cannot see a hidden partitioned claimant.
- Filesystem free bytes/inodes, growth rate, disk latency, memory pressure/OOM,
  CPU starvation, NTP health, DNS, packet loss, certificate expiry and reboot age.
- Base-backup age, WAL archive failures, retention enforcement, restore drills
  and measured RPO/RTO. Alert before WAL/archive queues can exhaust storage.

The verify playbook is an on-demand acceptance gate. A separate pg-ha-monitor timer runs functional checks every minute and writes protected local status plus journald output. External alert delivery remains an operational integration.
Do not expose SQL superuser credentials to a monitoring frontend. Create dedicated
least-privilege monitoring roles with your access-control process.

Managed units are `pg-ha-etcd`, `pg-ha-patroni`, `pg-ha-pgbouncer`,
`pg-ha-haproxy` and `pg-ha-keepalived`. Inspect their journals on the affected
host and correlate timestamps across nodes. Use the local PostgreSQL Unix socket
`/run/pg-ha-patroni` as the postgres OS account for privileged local inspection.
Use `/etc/pg-ha/patroni/patroni.yml` with `patronictl`; it contains credentials and
must not be copied into tickets or command output.

## Controlled changes requiring an approved maintenance plan

`reconcile.yml` supports a bounded allowlist of reloadable PostgreSQL settings,
and `postgresql.yml` supports guarded additive extension creation. Neither is a
general OS, service, topology or restart reconciler. For other changes, capture
the current configuration, checksums, runtime DCS
policy, package versions, member/system IDs, primary, timeline and backup status.
Protect copies with the same access restrictions as the originals. Candidate
configuration must pass the service's native parser (Patroni, HAProxy,
Keepalived), plus the custom schema checks and live health probes where no native
dry-run exists (etcd/PgBouncer). Never confuse custom schema validation with proof
that a daemon can start.

| Change | Minimum sequence and impact |
| --- | --- |
| HAProxy routing | Validate candidate; update one non-VIP router; graceful master-worker reload; check backends and authenticated SQL; proceed one at a time. Existing sessions can still fail when their backend is marked down. Restore previous config and reload if compatible. |
| Keepalived | Validate candidate; change one backup router first; verify advertisements and no duplicate VIP; move to remaining backups and then VIP holder. VIP movement can interrupt sessions. Restore previous config only after confirming uniqueness. |
| PgBouncer | Stage credential/cert overlap; reload supported settings; authenticate every application/database. For restart-only settings, drain the node through routing/maintenance policy, wait for or explicitly terminate sessions, then restart. Restore old config only while old credentials remain valid. |
| Patroni local YAML | Validate; reload only reloadable fields on one replica; verify runtime values and replication. Preserve watchdog requirements. Do not independently start PostgreSQL. |
| Patroni DCS policy | Review actual `/config`; use authenticated Patroni API or `patronictl edit-config` under a single writer/change lock. Bootstrap YAML changes do not update DCS. Preserve/compare the prior config and reject stale concurrent updates. Verify durability semantics before and after. |
| PostgreSQL restart parameter or patch | Ensure all voters/replicas healthy; drain and restart one replica through Patroni; verify catch-up; repeat; perform an explicitly reviewed switchover to a ready replica; restart former primary last. Expect connection interruption at switchover. Never restart all nodes. |
| etcd config or patch | All three members healthy and a verified snapshot first; one member at a time, verify quorum/member IDs after each. Stop immediately if any other member is unhealthy. Never change initial membership strings as a replacement for membership operations. |

After an approved change, a human-reviewed policy/fingerprint migration is needed
before `verify.yml` will accept the new baseline. Do not edit the recorded files
merely to silence an alarm. The versioned review must describe the authorized
diff and include runtime/functional verification. This explicit boundary prevents
an incomplete reconciler from taking unsafe production actions.

## Switchover and unplanned leader failure

Planned: acquire lock; verify healthy quorum, one primary, required synchronous
replicas, caught-up candidate, common timeline, functioning fencing and backups.
Drain or coordinate clients. Use Patroni's controlled switchover with the current
leader and explicit candidate; inspect its confirmation. Verify the old primary
is demoted and the new primary holds the lock before resuming traffic. Confirm
role-specific HAProxy backends, exactly one reachable VIP owner, read/write SQL,
replication and retry behavior. Measure interruption against the approved budget.

Unplanned: Patroni/etcd elect an eligible replica after loss of the former leader's
lease; the watchdog must fence the former primary before it can overlap. HAProxy
removes the failed path and disconnects marked-down sessions. Keepalived moves
the VIP only if the router path itself fails. Operators must not force promotion
merely because clients time out. Determine whether quorum, synchronization,
network reachability or fencing intentionally blocked availability.

If a recovered former primary is divergent, **retain its data and keep it out of
traffic**. Automatic rewind and directory removal are disabled. Evaluate timeline,
WAL continuity and possible lost transactions before approving recovery. A healthy
nondivergent restart may rejoin under Patroni without recreation; verify it
explicitly. Never infer safety from a green process-status indicator.

## Partial bootstrap

Stop further changes and preserve the inventory, exact packages, configuration,
etcd member IDs/cluster ID, Patroni namespace, PostgreSQL system IDs, directory
contents and journals. Do not delete state to make bootstrap pass. Distinguish:

1. Packages/config only, no database or DCS state: review what started and verify
   every node before approving a narrowly scoped continuation.
2. etcd initialized, PostgreSQL absent: confirm original membership/quorum and an
   empty Patroni namespace. Continue the original identity; never generate a new
   token against existing member storage.
3. PostgreSQL primary exists, some replicas or routers missing: preserve that
   system identifier and DCS namespace. Validate the primary and any replicas,
   then explicitly provision only verified empty missing nodes. Strict sync may
   intentionally block writes until replicas join.
4. State ambiguous or multiple system IDs: isolate traffic and investigate as a
   recovery incident. No automatic continuation is appropriate.

This release provides only an exact-plan incomplete-bootstrap resume, as described
above. Other states need a reviewed state-specific continuation or recovery
procedure. A missing final identity marker does not imply the node is unused or
disposable. See the [administrator guide](operator-guide.md) for detailed
configuration ownership, parameter selection and operating examples.

## Node replacement, scale-out and replica recreation

These are separate approved operations. Record the failed member identity and
fence it. Verify backups, surviving quorum, primary identity/timeline and capacity.
Retain old storage or a recoverable snapshot. Do not reuse its IP while it may
still advertise the VIP or serve writes.

For a database-only replica: allocate a unique identity/address, update reviewed
access/PKI/routing capacity, explicitly authorize an initial base backup into a
verified empty directory, verify streaming and lag, then admit it to read traffic
and the selected eligibility policy. Model-designated read replicas remain excluded
from automatic promotion and synchronous selection. Do not add an etcd voter just because a replica exists.

For a core voter replacement: perform the etcd documented member replacement
procedure, one member at a time with surviving quorum and original cluster ID.
Only then provision the replacement PostgreSQL replica/pooler/router. Do not use
`initial-cluster-state: new` or `force-new-cluster` to repair membership. A loss of
quorum needs the disaster recovery plan; minority members cannot vote themselves
into a new authoritative cluster safely.

Recreating a replica destroys the contents of the destination. Any future
automation for it must require a node/system-ID-bound explicit destructive
opt-in, recovery confirmation, fencing, backup retention and a verified source.
This repository deliberately provides no removal/reinit task or deletion flag.

## Disaster recovery and rollback

Backups must contain a base backup plus the required WAL and configuration/PKI
recovery material. Test restoration into isolated hosts and a separate network/
DCS namespace first; verify application consistency at the chosen recovery point
and measure RPO/RTO. A backup command succeeding is not restore evidence.

Before production cutover, fence the old cluster, stop competing VIP ownership,
record the selected recovery timeline and obtain the incident/change approval.
Rebuild authoritative cluster membership using the backup product and etcd
recovery procedures qualified for your versions. Never connect restored stale
etcd state to an unfenced live cluster.

Configuration rollback may restore the protected previous file and reload only
when binaries, credentials and runtime policy are still compatible. Recheck the
cluster after each node. Database rollback is a separate restore decision with
potential data loss. Binary downgrade, stale snapshot restoration, forced primary
selection and WAL/slot deletion are not automatic rollback mechanisms.

## Troubleshooting order

1. Establish whether data safety has intentionally stopped service: quorum,
   fencing, strict synchronization, conflicting identities or disk exhaustion.
2. Trace client -> VIP -> HAProxy role/pool checks -> PgBouncer authentication/TLS
   -> local PostgreSQL. Inspect each stage independently; do not weaken TLS or
   substitute a TCP-only primary check.
3. Check node DNS from every node, firewall fingerprints, actual routes, VRRP
   protocol 112, MTU/packet loss, time synchronization and certificate expiry.
4. Check WAL availability, sender/receiver state, replay lag, timeline, slots and
   archiving. Do not remove WAL or slots as a quick disk-space fix.
5. Preserve evidence and stop on ambiguous state. Restore service through the
   appropriate reviewed operation, then run both server and application checks.

## Deployed backup and acceptance commands

Every gated command also needs `maintenance_intent: maintenance` and its exact
`maintenance_approved_operations` list, in addition to the confirmations below.
For `data-acceptance.yml`, include `[data-acceptance, endpoints-verify, backup-verify]`;
for PITR include `[pitr-acceptance, restore-verify]`; for the other commands below
use their individual basename without `.yml`. Do not store these approvals as
permanently enabled defaults. The operator guide's recovery examples include them.

Pass the protected Vault file and vault-password file through `tools/run_playbook.py` as shown in the README. No command below embeds a credential.

- `data-acceptance.yml`: endpoint semantics, archive check and encrypted full backup.
- `restore-verify.yml`: use `restore_test_confirmation="TEST ISOLATED RESTORE"` and a fresh `/srv/postgres/restore-acceptance-...` directory. Existing targets are refused and retained for inspection.
- `pitr-acceptance.yml`: supply a unique `pitr_table` with the `pg_ha_pitr_acceptance_` prefix and a fresh restore directory. The test proves an earlier commit is present and a later commit absent.
- `backup-export.yml`: explicit `backup_export_confirmation="EXPORT ENCRYPTED REPOSITORY"`, unique `export_id` and protected native `export_controller_dir`. It briefly pauses new pgBackRest work with automatic admission recovery; PostgreSQL retains WAL during the pause.
- `export-verify.yml`: verify the actual exported archive on `export_verify_host`, which must differ from the repository node. This validates encrypted backup/WAL contents without contacting the original repository.
- `final-acceptance.yml`: two independent verification passes, stable service process/start identities, current functional monitoring and nonsecret audit artifacts.

The tested repository export is outside the VMs on the controller, but is one-time and not off-site. Protect Vault and CA recovery material separately; an encrypted repository without its cipher key cannot be recovered. External/immutable repository replication and alert routing remain production operational requirements.

The explicit fault-suite and watchdog-acceptance playbooks are disruptive qualification tools. Do not schedule them as routine health checks. Their measured results are in the deployment record. In-flight transactions can have uncertain outcomes; applications must reconcile by an idempotency key before retrying writes.

Boot order now requires pg-ha-watchdog before Patroni, and waits for confirmed time synchronization. If a node stays stopped after reboot, inspect these readiness checks before changing durability or fencing policy. Do not bypass them to restore apparent availability.
