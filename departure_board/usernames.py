"""Username persistence (JSON file, list of strings)."""
from __future__ import annotations

import json
import os
import sys
from typing import List

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
USERNAMES_FILE = os.path.join(_REPO_ROOT, '.usernames.json')


def load_usernames() -> List[str]:
    """Return list of username strings from file, or [] on missing/corrupt file."""
    try:
        with open(USERNAMES_FILE) as f:
            data = json.load(f)
        return [str(u) for u in data if u] if isinstance(data, list) else []
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def save_username(name: str) -> None:
    """Append name to file if not already present. No-op for empty strings."""
    name = name.strip()
    if not name:
        return
    existing = load_usernames()
    if name in existing:
        return
    existing.append(name)
    try:
        with open(USERNAMES_FILE, 'w') as f:
            json.dump(existing, f)
    except OSError as e:
        print(f"[usernames] save error: {e}", file=sys.stderr)
