import importlib.util
import sys
from pathlib import Path

_path = Path(__file__).resolve().parents[1] / 'module_utils' / 'cluster_contract.py'
if str(_path.parent.parent) not in sys.path:
    sys.path.insert(0, str(_path.parent.parent))
_spec = importlib.util.spec_from_file_location('cluster_contract', _path)
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)


class FilterModule:
    def filters(self):
        return {'validate_cluster_contract': _module.validate_contract}
