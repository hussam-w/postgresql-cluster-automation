import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from module_utils.deployment_model import validate_model, extension_plan


class FilterModule:
    def filters(self):
        return {'validate_deployment_model': validate_model, 'deployment_extension_plan': extension_plan}
