"""High score persistence (JSON file, shared by all games)."""
from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict, List

# Anchor to the repository root (one level up from this package)
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCORES_FILE = os.path.join(_REPO_ROOT, '.highscores.json')
MAX_SCORES_PER_GAME = 20


def load_high_scores(game_name: str) -> List[Dict[str, Any]]:
    """Return list of {'name': str, 'score': int} sorted descending by score."""
    try:
        with open(SCORES_FILE) as f:
            data = json.load(f)
        return sorted(data.get(game_name, []), key=lambda e: e['score'], reverse=True)[:MAX_SCORES_PER_GAME]
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        return []


def save_high_score(game_name: str, name: str, score: int) -> None:
    """Add a score entry and persist. Only saves if score > 0."""
    if score <= 0:
        return
    try:
        with open(SCORES_FILE) as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        data = {}
    entries = data.get(game_name, [])
    entries.append({'name': name, 'score': score})
    entries.sort(key=lambda e: e['score'], reverse=True)
    data[game_name] = entries[:MAX_SCORES_PER_GAME]
    try:
        with open(SCORES_FILE, 'w') as f:
            json.dump(data, f)
    except OSError as e:
        print(f"[scores] save error: {e}", file=sys.stderr)
