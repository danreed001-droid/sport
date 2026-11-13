#!/usr/bin/env python3
"""Grade the storylines shown on finished games and keep their live records.

For every finished game on every slate (NBA, NFL, CFB, MLB, soccer) that has
`storylines`, each entry gets `result` ("hit", "miss" or "push") for the
story's own bet, and the totals per storyline go to
data/storylines_record.json ({sport: {key: {"w", "l", "p"}}}). The storyline
scripts add those to the backtest record (lib/storyline_live.py), so records
keep updating as games are played.

  ATS sports (NBA, NFL, CFB): did the story's side cover the slate's line
  (NBA: statsSpread, the live line the storylines were computed with, when
  there is one). Moneyline sports: soccer "back" = the team won, "fade" = it
  didn't; MLB "back" = the team won, "fade" = it lost.

Run after scoring: python scripts/storyline_records.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import store  # noqa: E402
from lib.picks import is_final  # noqa: E402
from lib.storyline_live import PATH  # noqa: E402
from score_slate import _same_team  # noqa: E402

SPORTS = ("nba", "nfl", "cfb", "ncaab", "mlb", "soccer")
ATS = {"nba", "nfl", "cfb", "ncaab"}


def which(g, team):
    if team == g.get("home"):
        return "home"
    if team == g.get("away"):
        return "away"
    if _same_team(team, g.get("home", "")):
        return "home"
    if _same_team(team, g.get("away", "")):
        return "away"
    return None


def result(sport, g, e):
    side = which(g, e.get("team", ""))
    if side is None:
        return None
    h, a = float(g["homeScore"]), float(g["awayScore"])
    margin = (h - a) if side == "home" else (a - h)  # the story team's margin
    if sport in ATS:
        hs = g.get("statsSpread") if sport == "nba" and isinstance(g.get("statsSpread"), (int, float)) else g.get("homeSpread")
        if not isinstance(hs, (int, float)):
            return None
        cover = margin + (hs if side == "home" else -hs)
        if cover == 0:
            return "push"
        return "hit" if (cover > 0) == (e.get("says") == "back") else "miss"
    if sport == "soccer":
        won = margin > 0
        return "hit" if won == (e.get("says") == "back") else "miss"
    if margin == 0:
        return None
    return "hit" if (margin > 0) == (e.get("says") == "back") else "miss"


def main():
    totals = {}
    for sport in SPORTS:
        rec = {}
        for date_str, _ in store.list_docs(sport):
            doc = store.read_doc(sport, date_str)
            if not doc:
                continue
            changed = False
            for g in doc.get("games", []):
                if not g.get("storylines") or not is_final(doc, g):
                    continue
                for e in g["storylines"]:
                    r = result(sport, g, e)
                    if r and e.get("result") != r:
                        e["result"] = r
                        changed = True
                    if r:
                        t = rec.setdefault(e["key"], {"w": 0, "l": 0, "p": 0})
                        t[{"hit": "w", "miss": "l", "push": "p"}[r]] += 1
            if changed:
                store.write_doc(sport, date_str, doc)
        totals[sport] = dict(sorted(rec.items()))
        n = sum(v["w"] + v["l"] for v in rec.values())
        print(f"{sport}: {n} graded storyline bet(s) across {len(rec)} storyline(s).")
    old = None
    try:
        with open(PATH, encoding="utf-8") as f:
            old = json.load(f)
    except (OSError, ValueError):
        pass
    if old != totals:
        with open(PATH, "w", encoding="utf-8") as f:
            json.dump(totals, f, indent=1, sort_keys=True)
            f.write("\n")


if __name__ == "__main__":
    main()
