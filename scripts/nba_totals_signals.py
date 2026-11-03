#!/usr/bin/env python3
"""NBA Totals: patches full-game UNDER picks onto the day's NBA slate
(data/nba/<date>.json), like nba_stats_signals.py does for sides. Rules in
lib/nba_totals_rules.py:

  1. the spread is 3 points or less;
  2. the road team's previous regular-season game (within 10 days) went to OT.

Fields written on a game: totalsLine (the line the pick is graded against),
totalsFavors ("Under"), totalsRules ([{rule, name, backtest, detail}]) and
totalsCheck (plain-text why). Until tip-off every run refreshes the line from
ESPN's pickcenter (DraftKings), so grading uses a near-closing total, and the
rules are re-evaluated on it; once a game has started nothing changes.
Regular-season games only (the backtest's scope). Graded in score_slate.py
(totalsCorrect / totalsReturn).

Usage: python scripts/nba_totals_signals.py [YYYY-MM-DD ...]   (default: today ET)
       python scripts/nba_totals_signals.py --backfill [YYYY-MM-DD ...]

--backfill applies the rules to finished games on past slates that have no
NBA Totals fields yet, using the DraftKings closing spread and total archived
in data/raw/nba_lines.csv (the same lines the backtest graded against). Those
picks are marked totalsBackfill: true. Default: every past slate this season.
"""
import csv
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(__file__))
from lib import espn, store  # noqa: E402
from lib.dates import et_date_of_iso, today_et_str  # noqa: E402
from lib.nba_totals_rules import CLOSE_SPREAD, OT_LOOKBACK_DAYS, RULE_BACKTEST, RULE_NAMES  # noqa: E402
from score_slate import _same_team  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCORES_CSV = os.path.join(REPO_ROOT, "data", "raw", "master_nba_scores.csv")
LINES_CSV = os.path.join(REPO_ROOT, "data", "raw", "nba_lines.csv")
FIELDS = ("totalsLine", "totalsFavors", "totalsRules", "totalsCheck")


def season_start(date_str):
    """First NBA slate date of date_str's season (the slates start with the
    regular season), so a preseason OT never counts as a 'last game'."""
    y = int(date_str[:4]) - (0 if date_str[5:7] >= "08" else 1)
    first = [d for d, _ in store.list_docs("nba") if f"{y}-08-01" <= d <= date_str]
    return min(first) if first else f"{y}-10-15"


def last_game(rows, team, before, since):
    """The team's latest finished game in the scores archive before `before`."""
    best = None
    for r in rows:
        if not (since <= r["Date"] < before) or not str(r["Status"]).lower().startswith("final"):
            continue
        if _same_team(team, r["Away_Team"]) or _same_team(team, r["Home_Team"]):
            if best is None or r["Date"] > best["Date"]:
                best = r
    return best


def evaluate(g, rows, date_str, since, spread):
    rules = []
    if spread is not None and abs(spread) <= CLOSE_SPREAD:
        rules.append({"rule": 1, "detail": f"Spread {g['home']} {spread:+g} (3 points or less)."})
    last = last_game(rows, g["away"], date_str, since)
    if last and "ot" in str(last["Status"]).lower():
        gap = (date.fromisoformat(date_str) - date.fromisoformat(last["Date"])).days
        if gap <= OT_LOOKBACK_DAYS:
            opp = last["Home_Team"] if _same_team(g["away"], last["Away_Team"]) else last["Away_Team"]
            rules.append({"rule": 2, "detail": f"{g['away']} (road) went to {last['Status'].split('/')[-1]} vs {opp} on {last['Date']} "
                                               f"({last['Away_Team']} {last['Away_Score']}, {last['Home_Team']} {last['Home_Score']})."})
    for r in rules:
        r["name"], r["backtest"] = RULE_NAMES[r["rule"]], RULE_BACKTEST[r["rule"]]
    return rules


def run_for_date(session, rows, date_str):
    doc = store.read_doc("nba", date_str)
    if doc is None:
        print(f"{date_str}: no NBA slate yet, nothing to patch.")
        return
    try:
        events = espn.fetch_scoreboard(session, "basketball", "nba", date_str.replace("-", ""))
    except Exception as exc:
        print(f"{date_str}: ESPN scoreboard unavailable ({exc}); leaving NBA Totals as they are.")
        return
    evs = []
    for ev in events:
        if et_date_of_iso(ev["date"]) != date_str:
            continue
        comp = ev["competitions"][0]
        teams = {c["homeAway"]: c["team"]["displayName"] for c in comp["competitors"]}
        evs.append({"id": ev["id"], "away": teams.get("away"), "home": teams.get("home"),
                    "state": (comp.get("status") or {}).get("type", {}).get("state"),
                    "regular": (ev.get("season") or {}).get("type") == 2})
    since = season_start(date_str)
    changed = picks = 0
    for g in doc.get("games", []):
        ev = next((e for e in evs if _same_team(g.get("away"), e["away"]) and _same_team(g.get("home"), e["home"])), None)
        if ev is None or ev["state"] != "pre":
            picks += bool(g.get("totalsFavors"))
            continue  # not found, or already started: keep whatever it has
        before = {k: g.get(k) for k in FIELDS}
        if not ev["regular"]:
            for k in FIELDS:
                g.pop(k, None)
        else:
            lines = espn.pickcenter_lines(session, "basketball", "nba", ev["id"])
            if lines.get("total") is not None:
                g["totalsLine"] = lines["total"]
            spread = lines.get("homeSpread", g.get("homeSpread"))
            rules = evaluate(g, rows, date_str, since, spread)
            if rules and g.get("totalsLine") is not None:
                g["totalsFavors"] = "Under"
                g["totalsRules"] = rules
                g["totalsCheck"] = " ".join(f"Rule {r['rule']}: {r['detail']}" for r in rules)
                picks += 1
                print(f"  {date_str} {g['away']} @ {g['home']}: Under {g['totalsLine']:g} -- rules {[r['rule'] for r in rules]}")
            else:
                for k in ("totalsFavors", "totalsRules", "totalsCheck"):
                    g.pop(k, None)
        if {k: g.get(k) for k in FIELDS} != before:
            changed += 1
    if changed:
        store.write_doc("nba", date_str, doc)
    print(f"{date_str}: {picks} NBA Totals pick(s).")


def backfill(rows, dates):
    with open(LINES_CSV, encoding="utf-8") as f:
        lines = list(csv.DictReader(f))
    today = today_et_str()
    total_picks = 0
    for date_str in dates:
        if date_str >= today:
            continue
        doc = store.read_doc("nba", date_str)
        if doc is None:
            continue
        since = season_start(date_str)
        changed = 0
        for g in doc.get("games", []):
            if g.get("totalsFavors") or "totalsBackfill" in g:
                continue  # already has a live or backfilled verdict
            if not isinstance(g.get("awayScore"), (int, float)) or not isinstance(g.get("homeScore"), (int, float)):
                continue  # not final
            ln = next((r for r in lines if r["date"] == date_str and _same_team(g.get("away"), r["away"])
                       and _same_team(g.get("home"), r["home"])), None)
            try:
                total, spread = float(ln["total_close"]), float(ln["spread_close"])
            except (TypeError, ValueError):
                continue  # no archived closing line
            rules = evaluate(g, rows, date_str, since, spread)
            g["totalsBackfill"] = True  # checked, even when no rule fired, so it's never re-done
            if rules:
                g["totalsLine"], g["totalsFavors"], g["totalsRules"] = total, "Under", rules
                g["totalsCheck"] = " ".join(f"Rule {r['rule']}: {r['detail']}" for r in rules) + " (backfilled from the DraftKings closing line)"
                total_picks += 1
                print(f"  {date_str} {g['away']} @ {g['home']}: Under {total:g} -- rules {[r['rule'] for r in rules]}")
            changed += 1
        if changed:
            store.write_doc("nba", date_str, doc)
    print(f"backfilled {total_picks} NBA Totals pick(s).")


def main():
    if sys.argv[1:2] == ["--backfill"]:
        with open(SCORES_CSV, encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        start = season_start(today_et_str())
        backfill(rows, sys.argv[2:] or [d for d, _ in store.list_docs("nba") if d >= start])
        return
    dates = sys.argv[1:] or [today_et_str()]
    with open(SCORES_CSV, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    session = espn.make_session()
    for d in dates:
        run_for_date(session, rows, d)


if __name__ == "__main__":
    main()
