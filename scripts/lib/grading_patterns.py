"""Your category grading vs results, for the pick sheet's "My grading" page
(site/grading.html).

On the pick sheet you score each Second Opinion reason A (away), a (half
away), N (neutral), h (half home) or H (home); those letters are stored per
game in data/mypicks/<date>.json under "scores". This joins every graded
game with its final score and lines and emits compact records the page
aggregates itself (so it can filter by sport and date range):

  cats:  one per non-neutral grade -- did the side you graded toward win
         straight up and cover the spread?
  games: one per graded game -- your overall lean (the A/a/h/H tally),
         whether your grades pointed both ways, and how the leaned side did.

Only finished, graded games count. Nothing here is a pick: it's a record of
how your grading has held up.
"""
import re

from . import sports, store
from .picks import game_id, grade, is_final

LETTER = {"A": ("away", 1.0), "a": ("away", 0.5), "h": ("home", 0.5), "H": ("home", 1.0)}

# The sports' Second Opinions name some categories differently; fold them
# together so one row covers the same idea.
CATEGORY_ALIASES = {
    "injuries": "Injuries/Lineup",
    "injuries/lineup": "Injuries/Lineup",
    "matchup": "Matchup splits",
    "matchup splits": "Matchup splits",
    "venue/crowd": "Venue",
    "weather/venue": "Venue",
    "venue": "Venue",
}


def category_name(reason):
    """'Market: Bills -3 ... favors Bills' -> 'Market'."""
    name = re.sub(r"\s*\(.*?\)", "", str(reason).split(":", 1)[0]).strip()
    return CATEGORY_ALIASES.get(name.lower(), name) or "?"


def _outcome(sport, g, side):
    r = grade(sport, g, side)
    ats = {"cover": "W", "miss": "L", "push": "P"}.get(r["ats"]["result"])
    return r["ml"]["result"], ats


def _is_fav(g, side):
    other = "home" if side == "away" else "away"
    a, b = g.get(f"{side}Moneyline"), g.get(f"{other}Moneyline")
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and a != b:
        return a < b
    a, b = g.get(f"{side}Spread"), g.get(f"{other}Spread")
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and a != b:
        return a < b
    return None


def build(mypicks):
    """mypicks: {date: data/mypicks doc}. Returns {"cats": [...], "games": [...]}."""
    slates = {}
    for sport, cfg in sports.SPORTS.items():
        slates[sport] = dict(store.list_docs(cfg["collection"]))

    cats, games = [], []
    for date_str, mp in sorted(mypicks.items()):
        for gid, letters in (mp.get("scores") or {}).items():
            sport = gid.split("-", 1)[0]
            doc = slates.get(sport, {}).get(date_str)
            if not doc:
                continue
            g = next((x for x in doc.get("games", []) if game_id(sport, date_str, x) == gid), None)
            if g is None or not is_final(doc, g) or g.get("drawMoneyline") is not None:
                continue  # unfinished, or a 3-way soccer match (no two-way spread to grade)
            reasons = g.get("altReasons") or []
            lean = 0.0
            sides = set()
            for i, letter in enumerate(str(letters)):
                if letter not in LETTER or i >= len(reasons):
                    continue
                side, weight = LETTER[letter]
                lean += weight if side == "home" else -weight
                sides.add(side)
                su, ats = _outcome(sport, g, side)
                cats.append({"d": date_str, "s": sport, "c": category_name(reasons[i]),
                             "f": weight == 1.0, "su": su, "ats": ats, "fav": _is_fav(g, side)})
            entry = {"d": date_str, "s": sport, "lean": lean, "mixed": len(sides) > 1,
                     "k": sum(1 for x in str(letters) if x in LETTER), "su": None, "ats": None, "fav": None}
            if lean:
                side = "home" if lean > 0 else "away"
                entry["su"], entry["ats"] = _outcome(sport, g, side)
                entry["fav"] = _is_fav(g, side)
            games.append(entry)
    return {"cats": cats, "games": games}
