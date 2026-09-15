# Select a PostgreSQL version

The deployment model accepts quoted integer majors **14 and above**, including
14, 15, 16, 17 and 18. There is no upper-bound allowlist. Selection drives server
and client package names, binary paths, extension packages, standalone services,
Patroni `bin_dir`, initialization and isolated recovery commands. It never invokes
`pg_upgrade`, changes an existing database's major, or reinitializes existing data.

## Configure the major once

The supplied model examples expose one selection:

```yaml
postgresql_version: '16'
postgresql_deployment:
  mode: standalone
  major: '{{ postgresql_version }}'
  topology: {primary: pg01, replicas: [], standby: []}
  extensions: [pgcrypto]
postgresql_operation: plan
```

Keep your own topology and storage policy when changing the example. The model's
`major` remains the canonical resolved version. Existing configurations with a
literal `major: '17'` still work; convert it to the expression above if using the
runner's version override. A conflicting literal is refused, never silently ignored.

Choose a version with **one** of these mechanisms:

```bash
# Model file includes postgresql_version and major as above.
python3 tools/run_playbook.py playbooks/postgresql.yml \
  --extra-vars @inventories/local/model.yml --postgres-version 14

# The same interface accepts 15, 16, 17, 18, or a future available major.
POSTGRES_VERSION=18 python3 tools/run_playbook.py playbooks/postgresql.yml \
  --extra-vars @inventories/local/model.yml
```

Alternatively put `POSTGRES_VERSION=16` in the ignored `.env`. CLI
`--postgres-version` overrides the process environment and `.env`; the chosen
value overrides the example default in model files. Without a runner selection,
the model file's `postgresql_version` applies. The runner forwards a string, so
YAML coercion cannot turn it into an unintended numeric type. `latest`, minor
versions, prerelease strings, leading zeros and majors below 14 are rejected.

For direct Ansible usage, put the version override **after** model files:

```bash
ansible-playbook -i inventories/local/hosts.yml playbooks/postgresql.yml \
  -e @inventories/local/model.yml -e '{"postgresql_version":"15"}'
```

Use the controller/SSH-trust configuration in [installation](installation.md).
`POSTGRES_VERSION` is a runner setting, not automatically read by direct Ansible.

## Select matching, reproducible packages

Each environment must provide exact apt package pins from its approved repository
snapshot. Changing the major cannot invent available packages or compatible
extension builds. The [official PGDG Ubuntu repository](https://www.postgresql.org/download/linux/ubuntu/)
provides versioned PostgreSQL packages; this project retains its Ubuntu 22.04
amd64 OS boundary. The separately approved repository playbook queries the
selected major instead of a fixed version. Ordinary runs do not replace repositories.

Package resolution follows this mapping:

| Component | Selected-major package/path |
| --- | --- |
| Server / bundled extensions | `postgresql-<major>` |
| Client tools | `postgresql-client-<major>` |
| Shared packaging | `postgresql-common` |
| pg_stat_kcache | `postgresql-<major>-pg-stat-kcache` |
| pgAudit | `postgresql-<major>-pgaudit` |
| Binaries | `/usr/lib/postgresql/<major>/bin` |
| Extension control files | `/usr/share/postgresql/<major>/extension` |

For standalone, set `postgresql_package_versions` with the selected server/client,
`postgresql-common` and selected extension package pins. For HA, the complete
`cluster.packages` mapping must contain matching server/client major keys; optional
extension pins go in `postgresql_package_versions`. Multiple or mismatching
server/client majors are refused. The shared package and dependencies can have
different release numbering from the PostgreSQL server.

To switch among preapproved release sets without renaming keys each time, define
an environment-owned matrix and derive names in a Jinja dictionary expression:

```yaml
# Values below are required repository pins, not installation defaults.
postgresql_release_pins:
  '14': {server: null, client: null, common: null}
  '15': {server: null, client: null, common: null}
  '16': {server: null, client: null, common: null}
  '17': {server: null, client: null, common: null}
  '18': {server: null, client: null, common: null}
postgresql_package_versions: >-
  {{ {'postgresql-' ~ postgresql_version: postgresql_release_pins[postgresql_version].server,
      'postgresql-client-' ~ postgresql_version: postgresql_release_pins[postgresql_version].client,
      'postgresql-common': postgresql_release_pins[postgresql_version].common} }}
```

Populate pins before provisioning. For HA, combine this generated mapping with
the other required service pins when constructing `cluster.packages`; preserve
the complete `cluster` mapping. Do not put Jinja expressions directly in YAML
dictionary keys and assume Ansible will template them. Add a future release to
your pin matrix once its packages and dependencies are available.

Existing exact-pin disagreements require controlled package maintenance; the
missing-package installer simulates transactions and refuses dependency upgrades,
removals or downgrades. There is no fallback to another PostgreSQL major or an
unpinned metapackage when resolution fails.

## Compatibility and data safeguards

Before initialization, the automation checks the selected `postgres`, `initdb`,
`pg_ctl` and `pg_basebackup` executables report the requested major and verifies
required initdb options. Existing `PG_VERSION` markers must match the selection.
Standalone native configuration parsing and Patroni validation still run before
service activation. SQL extension inspection checks the actual server major,
available extension versions and preload state; unavailable extensions stop work.

The shared templates use the PostgreSQL 14+ baseline rather than enabling
new-major-only tuning features. Checksums and SCRAM are explicitly requested on
every major. PostgreSQL 18 enables checksums by default, but the explicit setting
keeps the same policy across versions. See [PostgreSQL 18 initdb](https://www.postgresql.org/docs/18/app-initdb.html).
Reload reconciliation uses the running server's `pg_settings` metadata for setting
existence, type, units, bounds and reload context, in addition to its narrow
allowlist; it does not assume new releases have identical metadata.

PGDATA, WAL, backup roots, sockets and cluster names remain explicit environment
configuration. They are **not automatically renamed** when the selected major
changes. This prevents a version edit from quietly creating another database at a
new path. For a separate fresh cluster, explicitly select a new inventory,
identity, directories and ports. Physical streaming replicas must use the same
major; this is not a rolling-major-upgrade implementation.

Patroni, pgBackRest and third-party extensions have their own compatibility and
release schedules. Choose appropriate pinned releases and run representative
backup/restore and failover qualification. [Patroni documents PostgreSQL support](https://patroni.readthedocs.io/en/latest/),
and [pgBackRest release notes](https://pgbackrest.org/release.html) record added
server-version support. A selectable future major is not proof that those
components already support it.

## Deploy and validate

1. Select the major, matching package pins, topology and approved storage.
2. Run `postgresql_operation: plan` with the selected model. Review detected
   versions, existing data, ownership, missing packages and extension availability.
3. On an admitted fresh environment, follow the explicit provisioning controls in
   [installation](installation.md). Provisioning handles packages, configuration
   and initialization; no manual editing of versioned code paths is required.
4. Verify `SHOW server_version`, replication, TLS, extension behavior, backups and
   restore using the operation-specific verification workflows.
5. Re-run the plan. A mismatch with an existing cluster is a migration requirement,
   not authorization to stop, replace or initialize it.

Automated model/package/template tests cover majors 14–18 and future selection.
The repository's previous live HA evidence remains PostgreSQL 17. Full fresh
deployment, failover and restore have **not** been executed here on every new
major. Future upstream changes cannot be guaranteed compatible in advance;
unavailable or incompatible components must fail safely rather than be bypassed.
