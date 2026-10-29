"""Hand-entered data: the last-resort input for when ESPN (or a Routine)
doesn't deliver. One file per sport and date, data/manual/<sport>/<date>.json:

    {"date": "2026-11-01", "sport": "nfl", "games": {
        "Denver Broncos @ Arizona Cardinals": {
            "away": "Denver Broncos", "home": "Arizona Cardinals", "time": "4:05 PM ET",
            "awayScore": 30, "homeScore": 16, "ot": false,
            "awaySpread": -4.5, "homeSpread": 4.5, "awayMoneyline": -225, "homeMoneyline": 185,
            "box": {"Denver Broncos": {"turnovers": 1, "totalYards": 402, "passYards": 288,
                                       "topRusherYards": 96, "topPasserYards": 301}}}}}

Every field is optional except away/home; whatever is entered wins over the
automatic source. Entries arrive from the pick sheet's "Enter data by hand"
page (a "data <sport> <date>" issue, merged by scripts/intake_manual.py) or by
editing the file directly on GitHub. Used by:
  - scripts/apply_manual.py: puts games and lines on the slates (creating a
    slate when none exists) and has edited games re-graded;
  - scripts/fetch_scores.py: final scores into the scores archive, so every
    model grades from them and NBA Stats sees them as played games;
  - scripts/nba_stats_signals.py / nfl_stats_signals.py / ncaab_stats_signals.py: the box-score
    facts their rules read (quarters, starters' points, threes, turnovers,
    yards, top rusher and passer).
"""
import json
import os
import re

from . import store

SPORTS = ("nfl", "cfb", "mlb", "nba", "ncaab", "soccer", "epl")
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# field: (min, max, integer?)
GAME_FIELDS = {
    "awayScore": (0, 300, True), "homeScore": (0, 300, True),
    "awaySpread": (-80, 80, False), "homeSpread": (-80, 80, False),
    "awaySpreadOdds": (-10000, 10000, True), "homeSpreadOdds": (-10000, 10000, True),
    "awayMoneyline": (-100000, 100000, True), "homeMoneyline": (-100000, 100000, True),
    "drawMoneyline": (-100000, 100000, True), "total": (0, 400, False),
}
GAME_FLAGS = ("ot", "decidedAfter90")
LINE_FIELDS = ("awaySpread", "homeSpread", "awaySpreadOdds", "homeSpreadOdds",
               "awayMoneyline", "homeMoneyline", "drawMoneyline", "total")
BOX_FIELDS = {
    "nba": {"threesMade": (0, 60, True), "threesAttempted": (0, 100, True)},
    "ncaab": {"threesMade": (0, 60, True), "threesAttempted": (0, 100, True)},
    "nfl": {"turnovers": (0, 15, True), "totalYards": (-100, 1200, True), "passYards": (-100, 900, True),
            "topRusherYards": (-50, 400, True), "topPasserYards": (-50, 700, True)},
}
BOX_NAMES = {"nfl": ("topRusherName", "topPasserName")}
BOX_LISTS = {"nba": {"quarters": (4, 8, 0, 100), "starterPoints": (5, 5, 0, 100)}}  # (min len, max len, min, max)


def path(sport, date_str):
    return os.path.join(store.REPO_ROOT, "data", "manual", sport, f"{date_str}.json")


def key(away, home):
    return f"{away} @ {home}"


_CACHE = {}


def load(sport, date_str):
    """{game key: entry} for a sport and date ({} when nothing was entered)."""
    if (sport, date_str) not in _CACHE:
        try:
            with open(path(sport, date_str), encoding="utf-8") as f:
                _CACHE[(sport, date_str)] = (json.load(f).get("games") or {})
        except (OSError, ValueError):
            _CACHE[(sport, date_str)] = {}
    return _CACHE[(sport, date_str)]


def dates(sport):
    d = os.path.join(store.REPO_ROOT, "data", "manual", sport)
    if not os.path.isdir(d):
        return []
    return sorted(f[:-5] for f in os.listdir(d) if f.endswith(".json") and DATE.match(f[:-5]))


def game(sport, date_str, away, home):
    return load(sport, date_str).get(key(away, home))


def team_game(sport, date_str, team):
    """The entry for `team`'s game on date_str, or None."""
    return next((g for g in load(sport, date_str).values() if team in (g.get("away"), g.get("home"))), None)


def team_box(sport, date_str, team):
    g = team_game(sport, date_str, team)
    return ((g or {}).get("box") or {}).get(team) or {}


def has_final(g):
    return g is not None and isinstance(g.get("awayScore"), (int, float)) and isinstance(g.get("homeScore"), (int, float))


def validate(sport, entry):
    """(clean entry, [problems]) -- only known fields, numbers in range."""
    problems, out = [], {}
    for side in ("away", "home"):
        v = entry.get(side)
        if not isinstance(v, str) or not v.strip():
            problems.append(f"missing the {side} team")
        else:
            out[side] = v.strip()
    if isinstance(entry.get("time"), str) and entry["time"].strip():
        out["time"] = entry["time"].strip()[:20]
    for f, (lo, hi, integer) in GAME_FIELDS.items():
        if entry.get(f) in (None, ""):
            continue
        v = _number(entry[f], lo, hi, integer)
        if v is None:
            problems.append(f"{f} must be a number from {lo} to {hi}")
        else:
            out[f] = v
    for f in GAME_FLAGS:
        if entry.get(f) is True:
            out[f] = True
    if "awaySpread" in out and "homeSpread" not in out:
        out["homeSpread"] = -out["awaySpread"]
    if "homeSpread" in out and "awaySpread" not in out:
        out["awaySpread"] = -out["homeSpread"]
    box_in = entry.get("box") or {}
    if isinstance(box_in, dict):
        box = {}
        for team, stats in box_in.items():
            if team not in (out.get("away"), out.get("home")) or not isinstance(stats, dict):
                problems.append(f"box score for `{team}`, who isn't in this game")
                continue
            clean = {}
            for f, (lo, hi, integer) in BOX_FIELDS.get(sport, {}).items():
                if stats.get(f) in (None, ""):
                    continue
                v = _number(stats[f], lo, hi, integer)
                if v is None:
                    problems.append(f"{team} {f} must be a number from {lo} to {hi}")
                else:
                    clean[f] = v
            for f in BOX_NAMES.get(sport, ()):
                if isinstance(stats.get(f), str) and stats[f].strip():
                    clean[f] = stats[f].strip()[:60]
            for f, (nmin, nmax, lo, hi) in BOX_LISTS.get(sport, {}).items():
                v = stats.get(f)
                if v in (None, "", []):
                    continue
                nums = [_number(x, lo, hi, True) for x in v] if isinstance(v, list) else [None]
                if not (nmin <= len(nums) <= nmax) or None in nums:
                    problems.append(f"{team} {f} needs {nmin}{'' if nmin == nmax else '-' + str(nmax)} whole numbers from {lo} to {hi}")
                else:
                    clean[f] = nums
            if clean:
                box[team] = clean
        if box:
            out["box"] = box
    return out, problems


def _number(v, lo, hi, integer):
    try:
        f = float(str(v).replace("+", "").strip())
    except (TypeError, ValueError):
        return None
    if not (lo <= f <= hi) or (integer and f != int(f)):
        return None
    return int(f) if integer else f


def merge(sport, date_str, entries, meta):
    """Merge validated entries into the file (field by field: a resubmitted
    game keeps what it doesn't change). Returns the number of games changed."""
    p = path(sport, date_str)
    try:
        with open(p, encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, ValueError):
        doc = {"date": date_str, "sport": sport, "games": {}}
    changed = 0
    for e in entries:
        k = key(e["away"], e["home"])
        cur = dict(doc["games"].get(k) or {})
        new = {**cur, **{f: v for f, v in e.items() if f != "box"}}
        if "box" in e:
            box = dict(cur.get("box") or {})
            for team, stats in e["box"].items():
                box[team] = {**(box.get(team) or {}), **stats}
            new["box"] = box
        if new != cur:
            new.update(meta)
            doc["games"][k] = new
            changed += 1
    if changed:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(doc, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, p)
        _CACHE.pop((sport, date_str), None)
    return changed
