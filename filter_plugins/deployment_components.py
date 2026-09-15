from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from module_utils.deployment_components import cluster_components


class FilterModule:
    def filters(self):
        return {'cluster_components': cluster_components}
