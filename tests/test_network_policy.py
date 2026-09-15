import copy
import sys
import unittest
from fixture import ROOT

sys.path.insert(0, str(ROOT))
from module_utils.network_policy import DEFAULT_PORTS, resolve_ports, nft_fingerprint, nft_has_filter_rules


class NetworkPolicyTests(unittest.TestCase):
    def test_partial_overrides_preserve_other_architecture_ports(self):
        ports = resolve_ports({'postgres': 15432})
        self.assertEqual(ports['postgres'], 15432)
        self.assertEqual(ports['write'], 5000)
        self.assertEqual(DEFAULT_PORTS['postgres'], 5432)

    def test_collisions_unknown_keys_and_unsafe_values_fail(self):
        for value in [{'postgres': 5000}, {'postgres': True}, {'postgres': '5432'},
                      {'postgres': 22}, {'postgres': 65536}, {'typo': 9000}]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                resolve_ports(value)

    @staticmethod
    def rules():
        return {'nftables': [
            {'metainfo': {'version': 'test'}},
            {'chain': {'family': 'inet', 'table': 'filter', 'name': 'input', 'hook': 'input', 'policy': 'drop', 'handle': 1}},
            {'rule': {'family': 'inet', 'table': 'filter', 'chain': 'input', 'handle': 2,
                      'expr': [{'counter': {'packets': 1, 'bytes': 100}}, {'accept': None}]}},
        ]}

    def test_runtime_counters_handles_and_metadata_do_not_cause_drift(self):
        original = self.rules()
        updated = copy.deepcopy(original)
        updated['nftables'][0]['metainfo']['version'] = 'changed'
        updated['nftables'][1]['chain']['handle'] = 20
        updated['nftables'][2]['rule']['expr'][0]['counter']['bytes'] = 999
        self.assertEqual(nft_fingerprint(original), nft_fingerprint(updated))

    def test_security_policy_changes_still_cause_drift(self):
        original = self.rules()
        updated = copy.deepcopy(original)
        updated['nftables'][1]['chain']['policy'] = 'accept'
        self.assertNotEqual(nft_fingerprint(original), nft_fingerprint(updated))

    def test_metadata_or_unrelated_chain_is_not_ingress_protection(self):
        self.assertTrue(nft_has_filter_rules(self.rules()))
        self.assertFalse(nft_has_filter_rules({'nftables': [{'metainfo': {}}]}))
        updated = self.rules()
        updated['nftables'][1]['chain']['hook'] = 'output'
        self.assertFalse(nft_has_filter_rules(updated))


if __name__ == '__main__':
    unittest.main()
