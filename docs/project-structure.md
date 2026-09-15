# Repository structure and documentation map

For the opt-in automated package/preload/restart workflow, see [on-premise extension lifecycle](onprem-extension-lifecycle.md). The older `configure` operation retains its manual preload-maintenance boundary.

See [modular deployment](modular-deployment.md) for the optional topology/component profile, its example files, configuration controls and qualification limits.

> Portable configuration: start with [the external deployment setup](environment-portability.md). Addresses in this guide are documentation-only ranges, names are examples, and `/home/OPERATOR` means your controller account. Read measured results as anonymized historical evidence; obtain real values from your own inventory and discovery.

This describes the actual repository layout. Environment operators normally edit inventory/model/operation files, not roles or modules. Relative paths below are relative to the repository root.

| Directory/file | Purpose and ownership |
| --- | --- |
| `README.md` | Entry point, supported scope, examples and guide links |
| `ansible.cfg` | Repository roles/modules/filter paths, strict SSH host verification, memory facts and sudo settings; keep consistent with the controller runner |
| `requirements.yml` | Exact three Ansible collection pins; changing them requires qualification |
| `inventories/example/hosts.yml` | HA inventory skeleton with intentional nulls; never deploy unchanged |
| `inventories/example/group_vars/all.yml` | Required HA contract, optional port defaults and secret/TLS guidance |
| `inventories/production/` | Ignored local reference environment; not a distributable default or guaranteed present in a fresh checkout |
| `inventories/discovery/` | Local inventory used by `run_discovery.py`; review before using the helper |
| `inventories/<env>/group_vars/`, `host_vars/` | Standard inventory-relative shared/per-node overrides; created for each environment |
| `examples/standalone.yml` | Standalone model/defaults example; deliberately empty package pins prevent installation |
| `examples/topology-five-nodes.yml` | Five-node role/extension overlay; requires the full HA contract |
| `examples/production-model-plan.yml` | Generic read-only three-node model; replace inventory role labels |
| `playbooks/` | Public orchestration entry points, guarded maintenance and acceptance workflows |
| `playbooks/tasks/` | Included migration/fault orchestration pieces; not standalone routine entry points |
| `roles/` | Component implementation; `tasks/`, `defaults/`, `templates/`, `files/` live beneath relevant roles, not generic top-level folders |
| `examples/storage-layout.yml`, `playbooks/storage-resolve.yml` | Commented opt-in unified layout and read-only target path resolution |
| `library/` | Custom Ansible modules for infrastructure, database, identity, extension and safety observations/actions |
| `module_utils/` | Shared pure contracts and module helpers: deployment_model, cluster_contract, reconcile_policy, network_policy, bootstrap_state and local PostgreSQL transport |
| `filter_plugins/` | Controller-side model/contract/report filters; consumed before host changes |
| `tools/` | POSIX runner, discovery, credential generation and specialized reference-environment utilities |
| `tests/` | Policy/unit/template tests, synthetic native parsers and explicit isolated/live acceptance fixtures |
| `docs/` | Current guides plus clearly labeled historical evidence |
| `artifacts/` | Ignored rendered fixtures, discovery reports and test evidence; sensitive metadata still needs access control |

There is no generic top-level `scripts/`, `templates/`, `defaults/` or `handlers/` tree. Do not create configuration in an imagined location and expect Ansible to consume it. Role activation is controlled by the playbooks and tasks; there is no universal restart-handler or feature-uninstall mechanism.

## Roles

| Role | Responsibility |
| --- | --- |
| `common` | HA default paths/derived ports and contract context |
| `preflight` | HA identity, inventory, policy, secret/application and node admission checks |
| `prepare` | HA packages/accounts/directories, TLS material and protected bootstrap preparation |
| `etcd` | Initial three-member DCS configuration and managed service |
| `patroni` | PostgreSQL authority, initial primary/replica orchestration, policy and eligible-role tags |
| `pgbouncer` | Initial application identities/verifiers and local pooling |
| `routing` | HAProxy/Keepalived configuration and VIP eligibility checks |
| `health` | Read-only HA membership, SQL/replication, DCS, routing and VIP checks |
| `platform` | Separately opted-in owned storage/network/hosts/firewall/watchdog work |
| `backup` | Managed pgBackRest configuration, encryption and TLS transport |
| `monitoring` | Protected HA functional health policy, implementation and timer |
| `standalone` | Admitted new single-instance provisioning and completed-ownership verification |
| `packages_safe` | Exact pinned missing-only package simulation/installation, installed-version preservation |
| `storage_layout`, `storage_guard` | Target-home/absolute path resolution and read-only mount/data-layout admission; no volume formatting or migration |

## Select the right playbook

| Category | Entry points and implications |
| --- | --- |
| Routine observation | `site.yml`, `inspect.yml`; model `postgresql.yml` defaults to plan |
| Local validation | `model-validate.yml`, `validate-inputs.yml`; respectively model and full HA contract |
| Bounded existing changes | `reconcile.yml` for reload settings; `postgresql.yml` configure/packages modes for extensions/missing packages |
| Managed HA verification | `verify.yml`, `preflight.yml`; preflight is declaration/host admission, not full application acceptance |
| Fresh model | `postgresql.yml` selects standalone or delegates admitted fresh HA to `provision-cluster.yml` |
| Legacy bootstrap | `deploy.yml` imports platform, backup-platform and provision-cluster; `bootstrap.yml`/`continue-bootstrap.yml` remain guarded incomplete-bootstrap helpers, not routine repeat commands |
| Infrastructure/package maintenance | `platform.yml`, `platform-repositories.yml`, `package-maintenance.yml`; explicit scopes and subsystem/operation conditions |
| Backup and monitoring installation | `backup-platform.yml`, `backup-schedule.yml`, `monitoring.yml`; separately gated, may write configuration/start services |
| Backup/application acceptance | `data-acceptance.yml`, `endpoints-verify.yml`, `backup-verify.yml`, `restore-verify.yml`, `pitr-acceptance.yml`, `backup-export.yml`, `export-verify.yml`; read each procedure, some write data, run backups or pause jobs |
| Disruptive qualification | `fault-suite.yml`, `service-failure*.yml`, `watchdog-acceptance.yml`, recovery acceptance; never routine health checks |
| Historical migrations/repairs | `ip-migration*.yml`, `repair-*.yml`; reference-state-specific guarded procedures, not a general drift-fixing API |
| Gate | `maintenance-gate.yml`; imported by legacy mutations, not a standalone authorization to change everything |

`site.yml` selects the model first if `postgresql_deployment` exists. Otherwise `execution_mode` selects plan/reconcile/fresh. Do not conflate this with `postgresql_operation` or legacy `deployment_mode`.

## Controller tools and fixed assumptions

`tools/run_playbook.py` is the general runner: explicit inventory/known-host paths, hidden credentials, collection path, local lock and supported check mode. `run_discovery.py` is specialized and uses the discovery inventory. `provision_credentials.py` creates retained HA PKI/Vault material and host pointer files, not SSH accounts or automatic renewals.

`probe_ssh_identity.py` collects candidate identities; independent verification is still required. `link_controller_collections.py` links an existing supported local collection layout rather than downloading arbitrary dependencies. `acceptance_client.py` requires an explicit policy file. Migration helpers require explicit site mappings and separate qualification; the VMware helper only writes a reviewable candidate. See [portable helper inputs](environment-portability.md#6-explicit-inputs-for-operational-helpers).

## Documentation ownership

Read `installation.md`, `deployment-models.md`, `environment-settings.md`, `features.md` and `environment-migration.md` for current setup. `operator-guide.md`, `operations.md`, `safe-reexecution.md`, `architecture.md`, `environment.md` and `discovery.md` explain operation and contracts. `validation.md` separates tested scopes from limitations. `deployment-record.md` and `ip-migration.md` preserve dated facts; `failure-tests.md` classifies acceptance scenarios.

When adding a variable, update the model/defaults, actual consumers, admission checks, environment reference, feature impact, applicable commands and validation evidence together. Never document a capability merely because an upstream product supports it.


## On-premise extension lifecycle components

| Path | Responsibility |
| --- | --- |
| `examples/onprem.yml` | Declarative topology, component and existing-instance maintenance interface |
| `playbooks/extensions.yml` | Discovery, admission, package installation, preload staging, ordered restart and SQL verification |
| `module_utils/deployment_model.py` | Version-aware extension catalog, custom descriptors and topology constraints |
| `module_utils/extension_lifecycle.py` | Pure preload merging, native dependency order and cluster health policy |
| `library/extension_package_versions.py` | Read-only exact installed/candidate package resolution |
| `library/postgres_preload.py` | Identity/ownership validation, private backups and additive DCS/ALTER SYSTEM changes |
| `roles/extension_repositories` | Explicitly trusted apt sources and preserved repository configuration |
| `roles/extension_lifecycle/tasks/health.yml` | mTLS membership and lag checks around managed restarts |
| `tests/test_extension_lifecycle.py`, `tests/test_preload_module.py` | Pure policy tests and filesystem-backed DCS simulations |
