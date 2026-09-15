# Portable data, WAL and backup storage

> Portable configuration: start with [the external deployment setup](environment-portability.md). Addresses in this guide are documentation-only ranges, names are examples, and `/home/OPERATOR` means your controller account. Read measured results as anonymized historical evidence; obtain real values from your own inventory and discovery.

The optional `storage_layout` profile derives three sibling directories from one
parent. It changes desired configuration only; it never formats a disk, mounts a
volume, moves an existing cluster or deletes old data. Without this profile, the
existing deployment paths and in-PGDATA WAL behavior remain unchanged.

```text
<storage root>/
  data/                 dedicated data-volume mount point
    pgdata/             PostgreSQL data directory
  wal/                  directory, or optional separately mounted WAL volume
    pg_wal/             external PostgreSQL WAL
  backups/              backup-volume mount point on the repository host
    repository/         pgBackRest repository, or reserved standalone backup directory
```

PGDATA is a child of the mount, so filesystem metadata such as `lost+found` does
not make the database directory nonempty. WAL is **not** backup: both PGDATA and
its WAL must remain durable and available. A sibling layout is a naming convention,
not proof of independent storage/failure domains or off-site recovery.

## Resolve paths explicitly

Copy [the commented example](../examples/storage-layout.yml) into the environment
policy or pass it as an extra-vars overlay:

```yaml
# Production-friendly service path, identical on all members of an HA cluster.
storage_layout:
  root: /srv/pg-storage
```

For a standalone development/staging server, resolve a named **target account**:

```yaml
# Remove root when selecting home_user. Do not supply both.
storage_layout:
  home_user: dbadmin
```

The read-only module queries that server's account database with `getpwnam` and
appends `/data`: `/home/dbadmin` becomes `/home/dbadmin/data`, and an account whose
home is `/var/lib/postgresql` becomes `/var/lib/postgresql/data`. It does not use
the SSH session's or sudo root's `$HOME`, and does not create the account.

Literal `$HOME`, `~`, relative paths, traversal, whitespace and symlinked root
paths are refused. If CI supplies a controller environment variable, expand it
explicitly in inventory, for example:

```yaml
# PGHA_STORAGE_ROOT is a controller/CI input, not a target-home lookup.
# Empty values fall back to the documented service path.
storage_layout:
  root: "{{ lookup('ansible.builtin.env', 'PGHA_STORAGE_ROOT') | default('/srv/pg-storage', true) }}"
```

An absolute value in `host_vars/<host>/storage.yml` can differ between standalone
environments. The current HA contract requires a common resolved service path on
all members. HA services retain `ProtectHome=true`: `/home/...` and `/root/...`
are therefore refused for HA. Mount site-specific volumes at the common `/srv/...`
path instead of weakening that sandbox. Standalone home paths require explicit
postgres directory-traversal access; do not make an entire private home public.

## Effective values and ownership

| Input/result | Meaning and behavior |
| --- | --- |
| `storage_layout` | Optional, absent by default; exactly `root` or `home_user` |
| `storage_paths` | Read-only resolved fact, not a user override; do not set it in inventory |
| Standalone `data_dir`, `storage_mount`, `wal_dir` | Derived as `data/pgdata`, `data`, `wal/pg_wal` |
| HA `cluster.data_dir`, `cluster.postgres_mount`, `cluster.wal_dir` | Same derived paths; other HA fields and separate etcd storage remain unchanged |
| `backup_repository_path` | HA derived `backups/repository`; only selected repository host stores the managed repository |
| Standalone backup directory | Created only if missing during admitted fresh provision; no backup product/schedule is installed |

Use one source of truth: conflicting higher-precedence explicit path overrides
are refused. Resolved facts last for the current Ansible run, so supply the same
profile on future runs. `postgresql.yml`, `verify.yml`, backup-platform and common
component workflows resolve it as needed. Direct legacy controller-only
`validate-inputs.yml` cannot discover a remote home: use the model workflow for
the resolved profile and keep other mandatory HA inputs complete.

Before new initialization, guards require mounted writable ext4/XFS at `data` on
every node, and at `backups` on the repository host (or standalone server). `wal`
must already exist on writable ext4/XFS; mounting a separate durable WAL device is
optional. Free-space admission uses standalone `min_free_bytes` (10 GiB default)
or HA `cluster.min_free_bytes`. These are floors, not workload sizing guarantees.
Review reported source/UUID against your volume inventory before approving creation.

New PGDATA/WAL leaves are private and postgres-owned. Parent mount directories
remain operator-managed; the automation does not recursively chmod a home or
change ownership of arbitrary existing backup contents. PostgreSQL must be able
to traverse the parents. Keep the actual data/WAL/repository inaccessible to
ordinary users.

## Prepare and mount data/backup volumes

Perform these steps on the target host only after the storage change is approved.
An attached EBS/local disk must already have the intended ext4/XFS filesystem, or
be initialized separately under an explicitly reviewed storage provisioning task.
This profile deliberately contains no `mkfs`, partitioning or cloud-volume API.
It is a systemd/VM deployment, not a Kubernetes PVC/operator implementation.

1. Inventory actual devices, mount points and filesystem UUIDs:

   ```bash
   lsblk -o NAME,SIZE,FSTYPE,UUID,MOUNTPOINTS
   findmnt
   sudo blkid
   ```

   Match volume IDs/serials to the cloud/hypervisor/storage record. Device names
   can change across reboot; never assume `/dev/sdb` identifies the intended disk.
   Do not format a volume just because it is currently unmounted.

2. Resolve and verify the chosen root. On this example target:

   ```bash
   PGHA_STORAGE_ROOT=/srv/pg-storage
   printf '%s\n' "$PGHA_STORAGE_ROOT"
   ```

   For the home-based option, inspect `getent passwd dbadmin` and use that home
   plus `/data`. This shell variable is only an operator convenience; it is not a
   substitute for the Ansible profile. Confirm all parent paths are canonical.

3. On **new, reviewed paths only**, prepare mount directories:

   ```bash
   sudo mkdir -p -- "$PGHA_STORAGE_ROOT/data" "$PGHA_STORAGE_ROOT/wal" "$PGHA_STORAGE_ROOT/backups"
   sudo find "$PGHA_STORAGE_ROOT/data" -mindepth 1 -maxdepth 1 -print
   sudo find "$PGHA_STORAGE_ROOT/backups" -mindepth 1 -maxdepth 1 -print
   ```

   If either target contains data or is already mounted, stop and identify it.
   Mounting over a directory hides its existing contents. Do not cover an existing
   PostgreSQL or backup directory with a new volume to make it appear empty.
   Ensure new parents are traversable by postgres; keep private home ACL changes
   restricted to search permission for that account on the required ancestors.

4. Preserve `/etc/fstab` to a unique protected backup and edit it through the
   normal configuration/change-management process. Example entries for this root:

   ```text
   UUID=<verified-data-filesystem-uuid> /srv/pg-storage/data ext4 defaults,nodev,nosuid 0 2
   UUID=<verified-backup-filesystem-uuid> /srv/pg-storage/backups ext4 defaults,nodev,nosuid 0 2
   ```

   Replace UUIDs and filesystem type with observed values. For XFS use its proper
   fstab/fsck policy (normally final field 0). Add an analogous `/wal` entry if a
   separate WAL volume is required. The backups entry is needed only on the HA
   repository host, but on each standalone host using this profile. Do not use
   `nofail` as a substitute for database mount admission.

5. Validate fstab, mount only the reviewed targets, and verify source identity:

   ```bash
   sudo findmnt --verify --verbose
   sudo systemctl daemon-reload
   sudo mount "$PGHA_STORAGE_ROOT/data"
   sudo mount "$PGHA_STORAGE_ROOT/backups"
   findmnt -M "$PGHA_STORAGE_ROOT/data" -o TARGET,SOURCE,UUID,FSTYPE,OPTIONS
   findmnt -M "$PGHA_STORAGE_ROOT/backups" -o TARGET,SOURCE,UUID,FSTYPE,OPTIONS
   df -h "$PGHA_STORAGE_ROOT/data" "$PGHA_STORAGE_ROOT/wal" "$PGHA_STORAGE_ROOT/backups"
   ```

   Mount a separately declared WAL volume before initialization too. Confirm
   writable permissions, capacity, persistence after a staging reboot and correct
   source UUID. The database unit uses mount dependencies and an actual data-mount
   assertion; the repository transport/scheduled job assert the backup mount.
   This avoids starting on a plain root-filesystem directory when expected mounts
   are absent. It does not detect every cloud-volume failure or provide fencing.

## Plan, override and provision

1. Put the profile in the appropriate environment group_vars/host_vars, or a
   separate `/secure/<environment>/storage.yml`. For HA use the same canonical
   service path across nodes, even when their underlying device IDs differ.
2. Retain the existing model, package pins, credentials and all other contract
   fields. Remove conflicting explicit path overrides from extra-vars.
3. Preview resolution without creating anything:

   ```bash
   python3 tools/run_playbook.py playbooks/storage-resolve.yml \
     --inventory inventories/my-environment/hosts.yml \
     --known-hosts /secure/my-environment/known_hosts \
     --extra-vars @/secure/my-environment/model.yml \
     --extra-vars @/secure/my-environment/storage.yml
   ```

4. Run `postgresql.yml` with the same overlays and default `plan`. Mount flags in
   resolution are observations, not authorization. New provisioning validates the
   mounts again before configuration/initialization. Fix missing infrastructure
   through the reviewed mount procedure, not by bypassing the guard.
5. Follow the [installation guide](installation.md) with the same storage overlay
   and explicit provision confirmations. Fresh standalone uses `initdb --waldir`;
   fresh HA uses Patroni initdb plus basebackup `waldir` configuration. PostgreSQL's
   native `PGDATA/pg_wal` symlink is intentional; arbitrary symlinked root paths
   remain refused.
6. Verify local runtime and native link location:

   ```bash
   sudo -u postgres readlink -f /srv/pg-storage/data/pgdata/pg_wal
   # Expect /srv/pg-storage/wal/pg_wal. Use your resolved root instead.
   ```

   Run the mode-specific SQL and service checks, inspect mounts, and re-run plan.
   Keep the profile with the environment configuration so later verification
   resolves the same paths.

## Existing databases and recovery

Changing root on an existing deployment is a data/storage migration, not a reload.
Owned policy differences, existing partial directories and an existing `pg_wal`
layout that does not match the requested external target stop safely. There is no
automatic move, symlink rewrite, reinitialization or restart of the live cluster.

A real migration requires verified backups, quiesced/stopped database authority,
copy/snapshot consistency, ownership and mount validation, coordinated service/
backup configuration, and an approved rollback plan. For HA it must be managed
through Patroni with replication/fencing considerations. Never move WAL while a
server or a replica-copy process is using it.

Restore tools must map WAL into an isolated **new** target; replaying a production
WAL link can affect live storage. The legacy `restore-verify.yml` fixture explicitly
refuses this new profile until an external-WAL restore mapping is qualified.
Standalone still has no integrated backup scheduler. Native initialization and
replica-copy placement tests are not end-to-end disaster-recovery qualification.

References: PostgreSQL documents [`initdb --waldir`](https://www.postgresql.org/docs/17/app-initdb.html)
and [`pg_basebackup --waldir`](https://www.postgresql.org/docs/17/app-pgbasebackup.html).
Patroni's [example configuration](https://github.com/patroni/patroni/blob/master/postgres1.yml)
shows external WAL options for replica creation. These mechanisms create the WAL
link during new initialization/copy; they do not migrate an existing running server.
