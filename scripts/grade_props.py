#!/usr/bin/env python3
"""Grade your player and team prop bets (data/mypicks/<date>.json "props").

Team props ("kind": "team") read the team's number from the game's score, its
periods or the team box score (lib/props.py TEAM_STATS, `team_value`).

Each prop entry carries the ESPN event id, the player's ESPN athlete id (or
just the name, matched in the box score), the stat (lib/props.py STATS, per
sport), the line, the side
("over"/"under") and the odds taken (-110 if none). Once ESPN marks the game
final, this reads the player's line from the box score and stores `actual`,
`result` ("W"/"L"/"P"; "void" if he didn't play) and `profit` ($100 a bet).
Graded props aren't fetched again. Run after scoring each hour.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import espn, props  # noqa: E402
from lib.picks import payout  # noqa: E402

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "mypicks")


def player_row(session, sport, eid, pid, name):
    """(final?, the player's box-score row or None if he didn't play)."""
    d = session.get(f"https://site.api.espn.com/apis/site/v2/sports/{props.espn_path(sport)}/summary?event={eid}",
                    timeout=25).json()
    st = ((d.get("header") or {}).get("competitions") or [{}])[0].get("status", {}).get("type", {})
    if not st.get("completed"):
        return False, None
    box = props.flatten_box(d)
    if pid and str(pid) in box:
        return True, box[str(pid)]
    want = props.norm(name)
    hit = [r for r in box.values() if props.norm(r.get("_name")) == want]
    return True, (hit[0] if len(hit) == 1 else None)


def grade(p, act):
    """Fill actual/result/profit; "void" when the number isn't there (didn't play)."""
    if act is None:
        p.update(result="void", profit=0.0, actual=None)
        return
    won = (act > p["line"]) if p["side"] == "over" else (act < p["line"])
    odds = p.get("odds") if isinstance(p.get("odds"), (int, float)) else -110
    p.update(actual=act, result="P" if act == p["line"] else ("W" if won else "L"),
             profit=0.0 if act == p["line"] else round(payout(odds, won), 2))


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
            if p.get("kind") == "team":
                try:
                    final, act = props.team_value(session, p.get("sport", "nba"), p["eventId"], p.get("teamSide"), p["stat"])
                except Exception as exc:  # noqa: BLE001
                    print(f"{name} {key}: ESPN unreachable ({exc.__class__.__name__}); try next run")
                    continue
                if not final:
                    continue
                grade(p, act)
                changed = True
                print(f"{name}: {p['player']} {p['side']} {p['line']:g} {p['stat']} -> {p.get('actual')} {p['result']}")
                continue
            try:
                final, row = player_row(session, p.get("sport", "nba"), p["eventId"], p.get("playerId"), p.get("player"))
            except Exception as exc:  # noqa: BLE001
                print(f"{name} {key}: ESPN unreachable ({exc.__class__.__name__}); try next run")
                continue
            if not final:
                continue
            act = props.stat_value(row, p.get("sport", "nba"), p["stat"]) if row is not None else None
            grade(p, act)
            changed = True
            print(f"{name}: {p['player']} {p['side']} {p['line']:g} {p['stat']} -> {p.get('actual')} {p['result']}")
        if changed:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(doc, f, indent=2, ensure_ascii=False)
                f.write("\n")


if __name__ == "__main__":
    main()
