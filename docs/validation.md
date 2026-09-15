# Validation and production qualification

See [modular deployment](modular-deployment.md) for the optional topology/component profile, its example files, configuration controls and qualification limits.

## PostgreSQL version selection validation

The version refactor passed 74 unit tests. Matrix tests cover 14, 15, 16, 17,
18 and prospective future majors for model admission, versioned packages,
legacy package contracts, rendered service paths and WAL settings. Conflicting
pins, malformed versions and existing-data major mismatches are refused.
Documentation checks cover 20 files and 147 local links/anchors.

These are automated logic/template checks, not fresh live installations of
every PostgreSQL major. Prior native/live PostgreSQL 17 evidence below remains
unchanged. No production VM packages, data or services were changed for this
refactor. See [version compatibility and qualification](postgresql-versions.md).

## Environment portability validation

The portability refactor passed 70 unit tests, including controller configuration
precedence, missing-target refusal, shell-expression rejection and quoted SSH
known-host paths. Public documentation uses anonymized identities; private local
inventories and evidence remain untouched. No VM deployment, network migration,
certificate replacement or service restart was performed for this refactor.
The configuration changes do not expand the qualified OS/PostgreSQL/platform
matrix. Requalify maintenance migrations in the destination environment.

> Portable configuration: start with [the external deployment setup](environment-portability.md). Addresses in this guide are documentation-only ranges, names are examples, and `/home/OPERATOR` means your controller account. Read measured results as anonymized historical evidence; obtain real values from your own inventory and discovery.

## Portable storage profile qualification

The opt-in [storage profile](storage-layout.md) adds target-account/absolute root
resolution, explicit mounted data/backup admission and fresh external WAL.
63 unit/policy/template tests passed, including canonical/ambiguous path rejection,
repeatable resolution and preservation of Patroni checkpoint/WAL options. Rendered
YAML now rejects duplicate keys. Ansible syntax and existing refusal-gate checks
passed during development.

On pg3, `tests/storage_wal_acceptance.yml` used the new private directory
`/srv/postgres/storage-wal-qa-20260913` and Unix-only port 55494. Missing-mount
admission was refused with no change; native PostgreSQL 17 initdb and pg_basebackup
created the expected separate WAL links. The private test server was stopped and
both test data copies retained. No production data was moved or rewritten.

Final Ansible syntax/refusal checks passed. Read-only HA verification finished
with `changed=0` and `failed=0` on pg1, pg2 and pg3, including replication,
etcd, routing and single reachable VIP ownership checks.

This does not qualify a fresh mounted-volume deployment, cloud-volume provisioning,
home ACL configuration, mount failure recovery or external-WAL disaster restore.
The legacy restore fixture refuses the new profile until its isolated mapping is
qualified. Existing reference deployment paths remain unchanged without opt-in.

Documentation review, 13 September 2026: current installation, settings, feature
controls and portability guides describe the implemented scope. Documentation
checks validate local links/anchors and YAML examples; they do not deploy services
or expand the runtime qualification recorded below.

The documentation-only audit passed across 17 files: 103 local links/anchors,
17 YAML examples with duplicate-key rejection, and five complete model examples
checked against the implementation's topology/extension validator. No VM or
deployment-automation changes were made during this documentation revision.

## 13 September 2026: deployment-model and extension qualification

The model-aware implementation is documented in [deployment models and extensions](deployment-models.md). Validation performed for this change:

| Check | Result |
| --- | --- |
| Unit/policy/template tests | 58 passed, including exact topology membership, conflicting roles/counts, unsupported versions/extensions, dependency expansion, rendered Patroni eligibility/preloads and standalone service isolation |
| Ansible validation | All `playbooks/*.yml` syntax checks passed; duplicate YAML keys rejected; invalid model/topology/version fixtures refused before SSH with no changes; legacy maintenance gates remain enforced |
| Native synthetic parsers | HAProxy and Keepalived passed; etcd and PgBouncer project configuration validators passed. The temporary Keepalived fixture uses its actual script owner; production root-script policy is unchanged |
| Isolated PostgreSQL 17 extension test | `pgcrypto` created once, repeat unchanged, installed version retained, server start identity unchanged; missing preload and unsafe schema-owner conditions detected |
| Reference three-node model plan | pg1/pg2/pg3 completed with `changed=0`, `failed=0`; major 17, common identity `SYSTEM_IDENTIFIER_FROM_DISCOVERY`, expected primary/standby eligibility and baseline extension detected |
| Existing-cluster configure and health | Extension creation disabled; all three nodes completed with `changed=0`, `failed=0`. Streaming replication with zero observed byte lag, synchronous standby, etcd health, routing and exactly one reachable VIP owner passed |

The isolated extension fixture is retained, stopped, at `/srv/postgres/extensions-qa-20260913` on pg3; it used Unix sockets only and port 55493. The fixture refuses an existing path and never deletes prior evidence. No production PostgreSQL data, configuration, networking, package or service changes were applied for this implementation.

The initial broad discovery reported bounded-scan coverage limits, without mutating anything. The existing-instance configuration test explicitly scoped discovery to `/srv/postgres/data`, `/srv/etcd/data`, `/var/lib/postgresql`, and `/var/lib/etcd`. Those scoped observations do not establish that the whole host is empty and cannot authorize fresh standalone initialization.

Fresh-OS standalone provisioning, new five-node HA deployment/failover, optional package installation, preload maintenance/restarts, multi-database failure recovery and future PostgreSQL majors have **not** been exercised end-to-end for this change. Standalone integrated backup/restore scheduling is not implemented. These remain explicit staging/operational qualification requirements; syntax and model tests do not substitute for them.

## Earlier safe-reexecution and deployment qualification

**13 September update:** the [safe re-execution qualification](safe-reexecution.md#validation-and-qualification) covers the new default plan, controlled reconciliation, 45 policy tests, legacy-operation refusal tests, native standalone/Patroni apply-and-repeat tests and zero-change production verification. The results below describe the earlier deployment qualification.

Date: 2026-09-12. The target is the actual three-node Ubuntu 22.04.5 / PostgreSQL 17.11 deployment, not the local WSL controller.

## Measured results

| Check | Result and evidence |
| --- | --- |
| Authenticated discovery | All three management hosts and directed peer probes passed; `artifacts/discovery/` contains sanitized reports and pinned SSH identities. |
| Storage and networking | Dedicated ext4 LVs, stable service IPs, source routes, firewall validation and fresh SSH reconnect passed on all nodes. |
| Deployment | Exact packages, certificate chains/key pairs, native service configuration, startup, PostgreSQL identity and etcd consensus passed. |
| Replication | One primary, two streaming replicas, a synchronous standby, equal timeline/system ID and bounded replay lag passed. |
| Application endpoints | Committed marker through VIP:5000, replicated reads through VIP:5001, verified TLS and rejection of writes on replica endpoint passed; `artifacts/endpoints-evidence.json`. |
| Encrypted backup | pgBackRest stanza check and complete AES-256-CBC full backup passed; `artifacts/backup-info.json`. |
| Isolated recovery | Restored to a fresh directory with no TCP listener, verified system lineage and recovered the committed application marker, then stopped only the recovered instance; `artifacts/restore-evidence.json`. |
| Continuous monitoring | All three initial functional monitors passed after installation. Daily backup timer is enabled on the repository node. |
| Application-side baseline | Controller workload: 38 acknowledged commits, zero failed attempts and zero missing acknowledged commits; `artifacts/client-baseline.json`. |
| Failure tests | HAProxy, Keepalived, one etcd member, primary PgBouncer and primary Patroni outage/recovery passed. Actual watchdog reboot and rejoin passed after startup repair. All acknowledged commits survived; see the deployment record and client artifacts. |

## Local verification

28 Python safety tests passed. Ansible syntax checking covers every top-level playbook and rejects the incomplete example before SSH. Native HAProxy and Keepalived parser checks pass using disposable Linux paths/certificates; etcd and PgBouncer schema checks pass. Isolated HAProxy integration covers authenticated role selection, pool failure/recovery, duplicate-primary rejection and role changes.

The controller uses ansible-core 2.16.3 and pinned collections: community.postgresql 4.2.0, community.general 8.3.0 and ansible.posix 1.5.4. Controller native parser versions differ from target versions; target startup and functional checks supply the live evidence.

## Defects found and corrected during live acceptance

- Restricted parent directory permissions prevented PostgreSQL from executing WAL integration helpers. Corrected traversal permissions while retaining private service configuration.
- A collection's SQL array conversion returned no matching application roles. Credential lookup now uses one parameterized scalar query per role and exports PostgreSQL's exact SCRAM verifier.
- Patroni's local replication probe used `localhost` against a node-name TLS certificate. Local replication probes now use the Unix socket with SCRAM; inter-node replication retains verified TLS.
- Native Patroni validation must allow ports already owned by the running service during a reviewed resume/reload. Fresh bootstrap still checks free ports.
- pgBackRest requires a recognizable archive command. The managed integration now uses its native archive-push command and updates only that reloadable dynamic setting.
- Isolated restore directories need explicit postgres ownership. Restore startup explicitly overrides data/HBA/identity paths and disables TCP and archiving.
- PgBouncer rejects the libpq startup `options` used by the monitor. Timeouts now use SQL SET after authentication.
- The watchdog reboot exposed a missing boot-time device. An explicit watchdog service dependency and bounded time-synchronization readiness check fixed it; the repeated reboot passed.
- Added a cross-play failure guard so dependent common-role workflows cannot proceed with a reduced set of surviving hosts.

This is engineering validation within this task, not an independent security certification.

## Qualifications that software cannot establish here

VM-level separation is known; independent physical hosts, storage, power and network failure domains are not established. The 1 GiB repository on pg3 is colocated. Its encrypted controller export has a matching SHA-256 digest; neither location establishes off-site or immutable storage. External DNS publication and actionable external alert delivery are not configured. Small initial volumes and 2-vCPU/3.8-GiB nodes are not workload sizing certification. Broad network-partition, resource-exhaustion and correlated-hypervisor tests require separate representative qualification.

Keep these limits visible when deciding whether to admit business-critical traffic. A passing backup restore proves recoverability of the measured data set, not a one-hour recovery guarantee for an unknown production workload. The [failure matrix](failure-tests.md) distinguishes expected behavior from executed evidence.

## Modular component validation — 2026-09-13

Local validation passed: 86 Linux unit tests; all playbook syntax checks; PostgreSQL selection 14–19; six Ansible modular model cases covering 1/2/3/5 database hosts with backup/routing combinations; invalid-input and unapproved-operation rejection. Native `systemd-analyze verify` accepted the rendered standalone and cluster logical-backup service/timer units. Documentation checks passed for 21 Markdown files, 165 local links/anchors, 24 YAML examples and six complete model examples.

Backup tests use simulated PostgreSQL commands with actual Linux temporary directories, locking, checksums and atomic publication. They cover repeated runs, primary/replica selection, failed dumps and identity changes. No native PostgreSQL dump/restore, new VM deployment, live topology migration or new-topology failover was performed for this change. Existing production VMs were not modified. The [modular guide](modular-deployment.md) identifies the required staging and recovery qualification.

## Existing three-node runtime acceptance — 2026-09-13

A real Ubuntu 22.04 / PostgreSQL 17.11 three-node deployment passed the new model/component workflow on an existing Type A cluster. Existing storage, addresses, synchronous policy, WAL archiving and running PostgreSQL services were preserved. Selected `pgcrypto` was created on the leader and verified on replicas; logical-backup configuration and timers were installed on all nodes.

Live TLS write routing, replicated-marker reads from all three nodes, read-endpoint write rejection, primary-only native logical dumping, manifest checksums, globals restoration and restoration of both databases passed. The restored test marker and pgcrypto were verified in a separate Unix-socket-only PostgreSQL instance, which was stopped after validation. Identical deployment re-execution returned zero changes, zero failures and zero unreachable hosts on every node.

This qualifies that existing-cluster compatibility path and native logical backup workflow on PostgreSQL 17; it does not qualify fresh modular installations, disabled-router deployments, alternate majors, failure injection or live topology conversion. Private per-host logs, full recaps and the deployment report are retained under the ignored local `artifacts/live-*` files; environment-specific models remain in the private production inventory.

## Declarative on-premise extension workflow — 2026-09-13

97 Linux unit tests pass, including native control-file dependency ordering, version-derived pgvector/TimescaleDB packages, custom package descriptors, environment parsing, additive preload preservation, cluster health rejection and filesystem-backed preload/DCS simulations. The latter verify protected backups, exact identity/plan guards, preservation of unrelated settings, and compare-and-swap refusal.

All playbook syntax checks and the existing version/topology validation matrix passed. The new on-premise template additionally resolved empty, built-in (pgcrypto/pgvector/TimescaleDB), and unregistered preinstalled extension selections through actual Ansible controller-only model evaluation. Documentation validation passed for 22 Markdown files, 180 local links/anchors, 26 YAML examples and six complete embedded model examples.

No VM changes were performed for this implementation. The new automated preload/rolling-restart workflow is not yet qualified on native staging machines. Previous three-VM pgcrypto and backup acceptance does not qualify this new path or TimescaleDB/pgvector runtime behavior. Fresh topology conversion, multi-primary replication and arbitrary third-party installation/restore hooks remain outside this workflow's guarantees.
