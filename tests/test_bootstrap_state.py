import tempfile
import unittest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from module_utils.bootstrap_state import empty_transport_home


class TransportTests(unittest.TestCase):
    def test_only_empty_transport_tree_is_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / '.ansible/tmp').mkdir(parents=True)
            self.assertTrue(empty_transport_home(root))
            (root / '17').mkdir()
            self.assertFalse(empty_transport_home(root))

    def test_nonempty_transport_directory_is_not_ignored(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / '.ansible/tmp').mkdir(parents=True)
            (root / '.ansible/tmp/PG_VERSION').write_text('17')
            self.assertFalse(empty_transport_home(root))
