"""Player heights (inches) for NBA Stats rule 65, cached in
data/raw/nba_heights.json ({ESPN athlete id: inches}). A player not in the
file is looked up once on ESPN's athlete page and added (0 = ESPN has no
height, so it isn't asked again)."""
import json
import os

PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data", "raw", "nba_heights.json")
URL = "https://sports.core.api.espn.com/v2/sports/basketball/leagues/nba/athletes/{}"
_DATA = None
_DIRTY = False


def _load():
    global _DATA
    if _DATA is None:
        try:
            with open(PATH, encoding="utf-8") as f:
                _DATA = json.load(f)
        except (OSError, ValueError):
            _DATA = {}
    return _DATA


def height(session, pid):
    """Height in inches, or None when unknown."""
    global _DIRTY
    data, pid = _load(), str(pid)
    if pid not in data:
        try:
            h = session.get(URL.format(pid), timeout=15).json().get("height")
        except Exception:
            return None  # a failed lookup is tried again next run
        data[pid] = float(h) if isinstance(h, (int, float)) and h else 0
        _DIRTY = True
    return data[pid] or None


def save():
    global _DIRTY
    if _DIRTY and _DATA is not None:
        with open(PATH, "w", encoding="utf-8") as f:
            json.dump(_DATA, f, separators=(",", ":"), sort_keys=True)
        _DIRTY = False
