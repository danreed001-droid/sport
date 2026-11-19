#!/usr/bin/env python3
"""Line-move check (the user's ask, 2026-11-19): for every game that hasn't
started, the spread, total and moneyline as they opened and as they are now
(ESPN pickcenter, DraftKings), so the card can show how far the market has
moved. NBA games also get the public betting split and the reverse-line-move
side from data/raw/market/nba/<date>.json (archive_market.py, Action Network).

Writes `lineMove` on each game (repo-owned in sync_ledger.py):
  {"checked": ISO time, "spread": [open, now] (home team's), "total": [open, now],
   "ml": {"home": [open, now], "away": [open, now], "draw": [open, now] (soccer)},
   "public": {"betsHome": %, "moneyHome": %, "rlm": team or None} (NBA)}
Left as it was once the game starts, so a finished game keeps its last
pre-game numbers (about the close). Context only, never a pick.
Usage: line_moves.py [sport ...]   (default all)
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import espn, props, store  # noqa: E402
from lib.picks import is_final  # noqa: E402
from score_slate import _same_team  # noqa: E402

ET = ZoneInfo("America/New_York")
AHEAD = {"nba": 1, "ncaab": 1, "mlb": 1, "soccer": 2, "nfl": 4, "cfb": 4}


def _num(v):
    try:
        return float(str(v).lstrip("ou").replace("+", ""))
    except (TypeError, ValueError):
        return None


def _pair(o):
    o = o or {}
    a = _num((o.get("open") or {}).get("line", (o.get("open") or {}).get("odds")))
    b = _num((o.get("close") or {}).get("line", (o.get("close") or {}).get("odds")))
    return [a, b] if a is not None or b is not None else None


def market_row(date_str, g):
    try:
        with open(os.path.join(store.REPO_ROOT, "data", "raw", "market", "nba", f"{date_str}.json"), encoding="utf-8") as f:
            m = json.load(f)
    except (OSError, ValueError):
        return None
    for r in m.get("games") or []:
        if _same_team(r.get("away", ""), g.get("away", "")) and _same_team(r.get("home", ""), g.get("home", "")):
            sp = r.get("spread") or {}
            if sp.get("tix_home") is None and sp.get("money_home") is None:
                return None
            return {"betsHome": sp.get("tix_home"), "moneyHome": sp.get("money_home"), "rlm": r.get("rlmFavorite")}
    return None


def run(sport, session):
    today = datetime.now(ET).date()
    path = props.espn_path(sport)
    changed = 0
    for i in range(AHEAD[sport] + 1):
        date_str = (today + timedelta(days=i)).isoformat()
        doc = store.read_doc(sport, date_str)
        if not doc or not doc.get("games"):
            continue
        try:
            evs = session.get(f"https://site.api.espn.com/apis/site/v2/sports/{path}/scoreboard?dates={date_str.replace('-', '')}&limit=1000"
                              + ("&groups=50" if sport == "ncaab" else "&groups=80" if sport == "cfb" else ""), timeout=25).json().get("events", [])
        except Exception as exc:  # noqa: BLE001
            print(f"{sport} {date_str}: {exc.__class__.__name__}")
            continue
        dirty = False
        for g in doc["games"]:
            if is_final(doc, g):
                continue
            ev = None
            for e in evs:
                t = {c["homeAway"]: c["team"]["displayName"] for c in e["competitions"][0]["competitors"]}
                if _same_team(t.get("away", ""), g.get("away", "")) and _same_team(t.get("home", ""), g.get("home", "")):
                    ev = e
                    break
            if not ev or (((ev.get("status") or {}).get("type") or {}).get("state") not in (None, "pre")):
                continue          # not found, or started: keep the last pre-game numbers
            spath = path
            if sport == "soccer":
                lg = props.league_slug(session, "soccer", ev["id"])
                spath = f"soccer/{lg}" if lg else path
            try:
                d = session.get(f"https://site.api.espn.com/apis/site/v2/sports/{spath}/summary?event={ev['id']}", timeout=25).json()
            except Exception:  # noqa: BLE001
                continue
            pc = (d.get("pickcenter") or [{}])[0]
            ml = {k: _pair((pc.get("moneyline") or {}).get(k)) for k in ("home", "away", "draw")}
            new = {"spread": _pair((pc.get("pointSpread") or {}).get("home")),
                   "total": _pair((pc.get("total") or {}).get("over")),
                   "ml": {k: v for k, v in ml.items() if v}}
            if sport == "nba":
                pub = market_row(date_str, g)
                if pub:
                    new["public"] = pub
            if not new["spread"] and not new["total"] and not new["ml"]:
                continue
            old = {k: v for k, v in (g.get("lineMove") or {}).items() if k != "checked"}
            if old != new:
                g["lineMove"] = dict(new, checked=datetime.now(timezone.utc).isoformat(timespec="seconds"))
                dirty = True
                changed += 1
        if dirty:
            store.write_doc(sport, date_str, doc)
    print(f"{sport}: line moves updated on {changed} game(s)")


def main():
    session = espn.make_session()
    for sport in [a for a in sys.argv[1:] if a in AHEAD] or list(AHEAD):
        run(sport, session)


if __name__ == "__main__":
    main()
