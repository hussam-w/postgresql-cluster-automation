import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from module_utils.extension_lifecycle import health_errors
class FilterModule:
    def filters(self):
        return {'extension_health_errors':health_errors}
