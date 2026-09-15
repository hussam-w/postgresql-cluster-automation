# VM discovery and secure access

> Portable configuration: start with [the external deployment setup](environment-portability.md). Addresses in this guide are documentation-only ranges, names are examples, and `/home/OPERATOR` means your controller account. Read measured results as anonymized historical evidence; obtain real values from your own inventory and discovery.

This workflow was completed for pg1 (192.0.2.21), pg2 (192.0.2.22), and pg3 (192.0.2.23), using administrative user dbadmin and verified SSH identities. The user confirmed all three as Type A core nodes. The current deployment and measured results are in [the deployment record](deployment-record.md). The instructions below remain the admission procedure for new environments; a responding SSH port alone never proves host identity.

## Password handling without Vault

Vault is not required for an initial secure interactive run. The Linux/WSL helper
`tools/run_discovery.py` invokes Ansible's standard hidden password prompts and
native in-memory/sshpass descriptor handling. The credential is not a command
argument, environment variable or disk file. The helper suppresses persistent
Ansible logging and uses memory-only fact caching. Remote observation output is
allowlisted; no process argument, full configuration or environment dumps are used.

Provision a verified known-hosts file first. Validate public fingerprints against
the VM consoles or another authenticated source. The console command
`ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub` prints the server's ED25519
fingerprint without revealing a private key. `known_hosts.candidate` contains
**untrusted observations** until that verification is complete. Do not add it to
trust automatically or disable `StrictHostKeyChecking`.

From the repository root in Linux/WSL, after host identities are verified:

```bash
python3 tools/run_discovery.py --inventory inventories/local/discovery.yml --port 22 --privileged \
  --known-hosts /absolute/path/to/verified_known_hosts
```

Enter the SSH and sudo passwords only at the hidden prompts. The helper does not
assume the two credentials or sudo policies are identical. If sudo denies access,
the run records incomplete coverage; it does not modify sudoers or SSH
configuration. The equivalent standard interface is:

```bash
ansible-playbook -i inventories/discovery/hosts.yml playbooks/discover.yml \
  -e '{"discovery_ssh_port":22,"discovery_privileged":true}' \
  --ask-pass --ask-become-pass
```

Keep strict host-key checking enabled for both paths. Do not paste credentials
into extra-vars, shell history, inventory, tickets or generated reports. Move to
Vault/secret management and reviewed SSH key authentication before ongoing
production automation. Never disable password authentication until key access,
sudo and an out-of-band recovery path have been tested.

## Observation scope

`playbooks/discover.yml` needs no VIP, deployment versions, data path, TLS material,
backup policy or component topology. It records:

- Authenticated module access; observed management address/hostname/OS/kernel;
  CPU, RAM, swap, block devices, mounts and available bytes/inodes.
- Interfaces, route tables/default routes, resolver entries, listeners, and
  node-to-node TCP probes of the observed SSH port.
- Sudo observation, synchronized-time state, selected SSH base policy settings,
  AppArmor/SELinux observation and firewall inspection fingerprints.
- Installed component packages, systemd states/unit paths, existing configuration
  paths and metadata; bounded PostgreSQL/etcd/Patroni state-marker searches.
- PostgreSQL control metadata when a matching installed `pg_controldata` binary
  can inspect a discovered data directory, without starting PostgreSQL.

No packages or services are installed, modified, stopped, restarted or removed.
No SQL writes, etcd mutations, bootstrap, SSH hardening or filesystem cleanup run.
SSH authentication/audit records and normal Ansible transport temporary files may
be created. Controller reports are stored under ignored `artifacts/discovery`.

Missing privileges, unavailable observation tools, unreachable peers and bounded
scan limits are reported as gaps. Ansible attempts all three targets and writes
the report even when some targets fail. Failed/unreachable hosts never count as
fresh. `coverage_complete` concerns the listed observation checks only; it never
means absence of all data or production approval.

The scanner deliberately does not traverse symlinks or inspect all file contents.
Custom PGDATA paths can require `discovery_additional_data_roots`. A bounded scan
cannot prove a machine contains no data. Encrypted/offline volumes, containers,
nonstandard binaries, authenticated runtime cluster membership, SSH `Match`
blocks, external firewall rules and application-port reachability may need
additional targeted checks. Peer SSH reachability does not prove the PostgreSQL,
etcd or VRRP network paths work.

## Preservation and the next gate

Discovery grants no mutation or rebuild authorization. Treat every target as
potentially containing production data. This repository provides no generic wipe,
cluster deletion or reinitialization flag. Preserve unexpected state and select
the documented existing-instance workflow; never delete state to pass admission.

After reviewing the private report, identify the intended node/component topology,
version policy, VIP/service network, storage/WAL layout, replication durability,
fencing, PKI, secrets, backup/restore policy, monitoring and exclusive change lock.
Only then select a separately admitted deployment or maintenance operation. No discovery result
automatically authorizes a PostgreSQL primary choice or a new etcd cluster.
