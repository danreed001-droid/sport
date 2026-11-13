"""Live records for the storylines (scripts/<sport>_storylines.py).

scripts/storyline_records.py grades every storyline shown on a finished game
and writes data/storylines_record.json: {sport: {key: {"w": hits, "l": misses,
"p": pushes}}}. Each storyline script adds those to the backtest record, so a
storyline's record, %, and the side history leans to keep updating as games
are played.
"""
import json
import os

PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "storylines_record.json")
_DATA = None


def live(sport, key):
    """(hits, misses) since the storyline went live, (0, 0) if none."""
    global _DATA
    if _DATA is None:
        try:
            with open(PATH, encoding="utf-8") as f:
                _DATA = json.load(f)
        except (OSError, ValueError):
            _DATA = {}
    r = (_DATA.get(sport) or {}).get(key) or {}
    return int(r.get("w", 0)), int(r.get("l", 0))
