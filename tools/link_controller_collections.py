#!/usr/bin/env python3
"""Select already-installed exact collection releases without changing global installs."""
import json
from pathlib import Path
import yaml
from controller_config import load

ROOT = Path(__file__).resolve().parents[1]
destination = (ROOT / Path(load().get('PGHA_COLLECTIONS_PATH', '~/.local/share/pg-ha/collections')).expanduser()).resolve() / 'ansible_collections'
sources = [Path.home() / '.ansible/collections/ansible_collections',
           Path('/usr/lib/python3/dist-packages/ansible_collections')]
for item in yaml.safe_load((ROOT / 'requirements.yml').read_text())['collections']:
    namespace, name = item['name'].split('.')
    matches = []
    for base in sources:
        candidate = base / namespace / name
        manifest = candidate / 'MANIFEST.json'
        if manifest.is_file() and json.loads(manifest.read_text())['collection_info']['version'] == item['version']:
            matches.append(candidate)
    if not matches:
        raise RuntimeError('Install required collection on native Linux storage: ' + item['name'] + ':' + item['version'])
    target = destination / namespace / name
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_symlink():
        if target.resolve() != matches[0].resolve():
            raise RuntimeError('Existing collection link points to a different release.')
    elif target.exists():
        raise RuntimeError('Existing collection directory requires manual reconciliation.')
    else:
        target.symlink_to(matches[0], target_is_directory=True)
    print(item['name'] + ':' + item['version'])
