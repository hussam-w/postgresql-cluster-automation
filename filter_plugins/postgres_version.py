from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from module_utils.postgres_version import resolve_major


class FilterModule:
    def filters(self):
        return {'postgres_major': resolve_major}
