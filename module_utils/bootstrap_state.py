"""Recognize only empty Ansible transport directories, never database contents."""
from pathlib import Path


def empty_transport_home(path):
    root = Path(path)
    expected = [root / '.ansible', root / '.ansible' / 'tmp']
    if root.is_symlink() or not root.is_dir():
        return False
    if set(root.iterdir()) != {expected[0]}:
        return False
    if any(p.is_symlink() or not p.is_dir() for p in expected):
        return False
    return set(expected[0].iterdir()) == {expected[1]} and not any(expected[1].iterdir())
