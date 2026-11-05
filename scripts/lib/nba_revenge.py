"""Revenge facts for NBA Stats rules 44-48 and NBA Totals rules 20-21: the
"revenge team" is the one that LOST the last regular-season meeting between
tonight's two teams (this season or last, within 400 days).

Meetings come from data/raw/nba_lines.csv (every finished game since the start
of 2025-26, with its closing spread), kept to each season's regular-season
window so preseason, play-in and playoff games don't count -- as in the
backtest, which used regular-season games only. Records ("better/worse record
now") are this season's win % going into tonight, from the same games;
equal records give no facts, as backtested. A replay can pass its own game
list to revenge_facts() instead of the CSV."""
import csv
import os
from datetime import date

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LINES_CSV = os.path.join(REPO_ROOT, "data", "raw", "nba_lines.csv")
# Regular-season windows (first and last day). A season missing here runs from
# Oct 15 to Apr 15.
REGULAR = {"2025-26": ("2025-10-21", "2026-04-12"), "2026-27": ("2026-10-20", "2027-04-11")}
_CACHE = None


def season_of(d):
    y = int(d[:4])
    return f"{y}-{str(y + 1)[2:]}" if d[5:7] >= "08" else f"{y - 1}-{str(y)[2:]}"


def _regular(d):
    s = season_of(d)
    lo, hi = REGULAR.get(s, (f"{int(s[:4])}-10-15", f"{int(s[:4]) + 1}-04-15"))
    return lo <= d <= hi


def archive_games():
    """[{date, season, home, away, hs, as, hsp}] from nba_lines.csv, regular season only."""
    global _CACHE
    if _CACHE is None:
        _CACHE = []
        if os.path.exists(LINES_CSV):
            with open(LINES_CSV, encoding="utf-8") as f:
                for r in csv.DictReader(f):
                    try:
                        hs, a = float(r["home_score"]), float(r["away_score"])
                    except (TypeError, ValueError):
                        continue
                    if not _regular(r["date"]):
                        continue
                    try:
                        hsp = float(r["spread_close"])
                    except (TypeError, ValueError):
                        hsp = None
                    _CACHE.append({"date": r["date"], "season": season_of(r["date"]), "home": r["home"], "away": r["away"],
                                   "hs": hs, "as": a, "hsp": hsp})
        _CACHE.sort(key=lambda g: g["date"])
    return _CACHE


def revenge_facts(home, away, date_str, home_spread, same=lambda a, b: a == b, games=None):
    """Facts about tonight's revenge spot, or None: {"rev": "home"|"away",
    "margin", "lost_at_home", "was_fav", "recent" ("within 30 days"|"earlier
    this season"|"last season"), "home_now", "fav_now", "worse_now", "streak",
    "last_date", "last_score"}. home_spread: tonight's home spread (negative =
    home favored); no line or a pick'em gives None."""
    if home_spread is None or home_spread == 0:
        return None
    games = archive_games() if games is None else games
    season = season_of(date_str)
    d0 = date.fromisoformat(date_str)
    meets, rec = [], {"home": [0, 0], "away": [0, 0]}
    for g in games:
        if g["date"] >= date_str:
            break
        gh, ga = g["home"], g["away"]
        sides = {}
        for side, team in (("home", home), ("away", away)):
            if same(team, gh): sides[side] = "home"
            elif same(team, ga): sides[side] = "away"
        if g["season"] == season and g["hs"] != g["as"]:
            for side, where in sides.items():
                won = (g["hs"] > g["as"]) == (where == "home")
                rec[side][0 if won else 1] += 1
        if len(sides) == 2 and sides["home"] != sides["away"] and g["hs"] != g["as"]:
            meets.append((g, sides))
    if not meets:
        return None
    g, sides = meets[-1]
    gap = (d0 - date.fromisoformat(g["date"])).days
    if gap > 400:
        return None
    home_won_last = (g["hs"] > g["as"]) == (sides["home"] == "home")
    rev = "away" if home_won_last else "home"
    tp = rec[rev][0] / sum(rec[rev]) if sum(rec[rev]) else None
    other = "home" if rev == "away" else "away"
    op = rec[other][0] / sum(rec[other]) if sum(rec[other]) else None
    if tp is None or op is None or tp == op:
        return None
    rev_where = sides[rev]  # "home"/"away" in that meeting
    fav_side = None if g["hsp"] in (None, 0) else ("home" if g["hsp"] < 0 else "away")
    streak = 0
    for mg, ms in reversed(meets):
        rev_won = (mg["hs"] > mg["as"]) == (ms[rev] == "home")
        if rev_won:
            break
        streak += 1
    my_sp = home_spread if rev == "home" else -home_spread
    recent = ("within 30 days" if gap <= 30 else "earlier this season") if g["season"] == season else "last season"
    return {"rev": rev, "margin": abs(g["hs"] - g["as"]), "lost_at_home": rev_where == "home",
            "was_fav": fav_side == rev_where, "recent": recent, "home_now": rev == "home", "fav_now": my_sp < 0,
            "worse_now": tp < op, "streak": streak, "last_date": g["date"],
            "last_score": f"{g['away']} {g['as']:g} @ {g['home']} {g['hs']:g}"}
