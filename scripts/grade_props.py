#!/usr/bin/env python3
"""Grade your player prop bets (data/mypicks/<date>.json "props").

Each prop entry carries the ESPN event id, the player's ESPN athlete id, the
stat ("points", "rebounds", "assists", "threes", "pra"), the line, the side
("over"/"under") and the odds taken (-110 if none). Once ESPN marks the game
final, this reads the player's line from the box score and stores `actual`,
`result` ("W"/"L"/"P"; "void" if he didn't play) and `profit` ($100 a bet).
Graded props aren't fetched again. Run after scoring each hour.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import espn  # noqa: E402
from lib.picks import payout  # noqa: E402

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "mypicks")
PATHS = {"nba": "basketball/nba", "ncaab": "basketball/mens-college-basketball"}
KEYS = {"points": ("PTS",), "rebounds": ("REB",), "assists": ("AST",), "threes": ("3PT",),
        "pra": ("PTS", "REB", "AST"), "pr": ("PTS", "REB"), "pa": ("PTS", "AST"), "ra": ("REB", "AST")}


def stat_line(session, sport, eid, pid):
    """(final?, {label: value} for the player or None if he didn't play)."""
    d = session.get(f"https://site.api.espn.com/apis/site/v2/sports/{PATHS[sport]}/summary?event={eid}", timeout=25).json()
    st = ((d.get("header") or {}).get("competitions") or [{}])[0].get("status", {}).get("type", {})
    if not st.get("completed"):
        return False, None
    for team in (d.get("boxscore") or {}).get("players") or []:
        block = (team.get("statistics") or [{}])[0]
        labels = block.get("labels") or block.get("names") or []
        for a in block.get("athletes") or []:
            if str((a.get("athlete") or {}).get("id")) == str(pid):
                vals = a.get("stats") or []
                if not vals or a.get("didNotPlay"):
                    return True, None
                return True, dict(zip(labels, vals))
    return True, None


def value(stats, stat):
    total = 0.0
    for k in KEYS[stat]:
        v = str(stats.get(k, "")).split("-")[0]  # 3PT is "made-attempted"
        total += float(v)
    return total


def main():
    session = espn.make_session()
    for name in sorted(os.listdir(ROOT)):
        path = os.path.join(ROOT, name)
        if not name.endswith(".json"):
            continue
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
        changed = False
        for key, p in (doc.get("props") or {}).items():
            if p.get("result"):
                continue
            try:
                final, stats = stat_line(session, p.get("sport", "nba"), p["eventId"], p["playerId"])
            except Exception as exc:  # noqa: BLE001
                print(f"{name} {key}: ESPN unreachable ({exc.__class__.__name__}); try next run")
                continue
            if not final:
                continue
            if stats is None:
                p.update(result="void", profit=0.0, actual=None)
            else:
                act = value(stats, p["stat"])
                won = (act > p["line"]) if p["side"] == "over" else (act < p["line"])
                odds = p.get("odds") if isinstance(p.get("odds"), (int, float)) else -110
                p.update(actual=act, result="P" if act == p["line"] else ("W" if won else "L"),
                         profit=0.0 if act == p["line"] else round(payout(odds, won), 2))
            changed = True
            print(f"{name}: {p['player']} {p['side']} {p['line']:g} {p['stat']} -> {p.get('actual')} {p['result']}")
        if changed:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(doc, f, indent=2, ensure_ascii=False)
                f.write("\n")


if __name__ == "__main__":
    main()
