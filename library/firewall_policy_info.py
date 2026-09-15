#!/usr/bin/python
"""Read the complete effective nftables policy, excluding volatile counters."""
import json
from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils.network_policy import nft_fingerprint, nft_has_filter_rules

module = AnsibleModule(argument_spec={}, supports_check_mode=True)
rc, stdout, stderr = module.run_command(['nft', '-j', 'list', 'ruleset'])
if rc:
    module.fail_json(msg='Cannot inspect effective nftables policy')
policy = json.loads(stdout)
if not nft_has_filter_rules(policy):
    module.fail_json(msg='Effective ingress policy is missing')
module.exit_json(changed=False, sha256=nft_fingerprint(policy))
