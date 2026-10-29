#!/usr/bin/env python3
"""NCAAB Stats: a deterministic, backtested model patched onto each NCAA
basketball slate (data/ncaab/<date>.json), alongside the Ledger and Second
Opinion. No LLM research involved. Rules and rates are in
scripts/lib/ncaab_stats_rules.py.

  Rule 1: back a team after a loss in which the opponent's three-point
  percentage beat its own by 25+ points (both teams 15+ attempts) -- a loss
  that was mostly shooting luck. Backtest: 60.5% ATS, 2018-19 to 2025-26.

Each team's previous game comes from ESPN's team schedule (regular season and
postseason), its threes from that game's box score; hand-entered box scores
(data/manual/ncaab/, lib/manual.py) win over ESPN's. A game gets
"ncaabStatsFavors" (team name), "ncaabStatsRules" (every rule that fired,
with its reason) and "ncaabStatsCheck". If an ESPN lookup fails while a game
is evaluated, the pick it already had is kept for the next run to re-check.

Usage: python scripts/ncaab_stats_signals.py [YYYY-MM-DD ...]   (default: today ET)
"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(__file__))
from lib import espn, manual, store  # noqa: E402
from lib.dates import et_date_of_iso, today_et_str  # noqa: E402
from lib.ncaab_stats_rules import RULE_BACKTEST, RULE_NAMES  # noqa: E402

BASE = "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball"
THREE_GAP = 0.25     # rule 1: opponent's 3P% minus the team's, in the loss
THREE_MIN_ATT = 15   # ...with this many three-point attempts or more for each team
LOOKBACK_DAYS = 30   # how far back a "previous game" can be (holiday breaks)
FIELDS = ("ncaabStatsFavors", "ncaabStatsCheck", "ncaabStatsRules")
GRADE_FIELDS = ("ncaabStatsCorrect", "ncaabStatsReturn", "ncaabStatsCover", "ncaabStatsSpreadReturn")
FAILS = [0]  # failed ESPN lookups this run (see the module docstring)


def season_of(date_str):
    """ESPN's season label: 2026 for the 2025-26 season."""
    d = date.fromisoformat(date_str)
    return d.year + 1 if d.month >= 8 else d.year


_IDS, _SCHED, _BOX = {}, {}, {}


def team_ids(session, date_str):
    """{team display name: ESPN team id} for every D-I game on date_str."""
    if date_str not in _IDS:
        try:
            events = session.get(f"{BASE}/scoreboard?dates={date_str.replace('-', '')}&groups=50&limit=1000", timeout=30).json().get("events", [])
            _IDS[date_str] = {c["team"]["displayName"]: c["team"]["id"] for ev in events for c in ev["competitions"][0]["competitors"]}
        except Exception:
            FAILS[0] += 1
            return {}
    return _IDS[date_str]


def schedule(session, team_id, season):
    """The team's completed games this season, oldest first:
    [{eid, date, opp, mine, theirs}]."""
    key = (team_id, season)
    if key not in _SCHED:
        games = []
        try:
            for st in ("", "&seasontype=3"):
                for ev in session.get(f"{BASE}/teams/{team_id}/schedule?season={season}{st}", timeout=30).json().get("events", []):
                    comp = ev["competitions"][0]
                    if not comp.get("status", {}).get("type", {}).get("completed"):
                        continue
                    t = {c["team"]["id"]: c for c in comp["competitors"]}
                    if team_id not in t or len(t) != 2:
                        continue
                    other = next(c for k, c in t.items() if k != team_id)
                    sc = lambda c: (c.get("score") or {}).get("value") if isinstance(c.get("score"), dict) else c.get("score")
                    games.append({"eid": ev["id"], "date": et_date_of_iso(ev["date"]), "opp": other["team"]["displayName"],
                                  "mine": float(sc(t[team_id])), "theirs": float(sc(other))})
        except Exception:
            FAILS[0] += 1
            return None  # not cached: retried at the next use
        _SCHED[key] = sorted(games, key=lambda g: (g["date"], g["eid"]))
    return _SCHED[key]


def threes(session, event_id):
    """{team display name: (made, attempted)} from an ESPN box score."""
    if event_id not in _BOX:
        try:
            d = session.get(f"{BASE}/summary?event={event_id}", timeout=30).json()
            out = {}
            for t in d.get("boxscore", {}).get("teams", []):
                st = {s.get("name"): s.get("displayValue") for s in t.get("statistics", [])}
                m, _, a = str(st.get("threePointFieldGoalsMade-threePointFieldGoalsAttempted", "")).partition("-")
                if m.isdigit() and a.isdigit():
                    out[t["team"]["displayName"]] = (int(m), int(a))
            _BOX[event_id] = out
        except Exception:
            FAILS[0] += 1
            return {}
    return _BOX[event_id]


def last_game(session, team, date_str):
    """The team's previous game before date_str: {date, opp, mine, theirs,
    eid}, from ESPN's schedule, or from a hand-entered final when ESPN has
    nothing; None if there's none within LOOKBACK_DAYS."""
    d0 = date.fromisoformat(date_str)
    tid = team_ids(session, date_str).get(team)
    games = schedule(session, tid, season_of(date_str)) if tid else None
    prev = [g for g in games or [] if g["date"] < date_str]
    if prev and (d0 - date.fromisoformat(prev[-1]["date"])).days <= LOOKBACK_DAYS:
        g = dict(prev[-1])
        m = manual.team_game("ncaab", g["date"], team)
        if manual.has_final(m):  # a hand-entered score wins
            g["mine"], g["theirs"] = (m["homeScore"], m["awayScore"]) if m["home"] == team else (m["awayScore"], m["homeScore"])
        return g
    for k in range(1, LOOKBACK_DAYS + 1):  # ESPN had nothing: hand-entered finals
        ds = date.fromordinal(d0.toordinal() - k).isoformat()
        m = manual.team_game("ncaab", ds, team)
        if manual.has_final(m):
            home = m["home"] == team
            return {"date": ds, "opp": m["away"] if home else m["home"], "eid": None,
                    "mine": m["homeScore"] if home else m["awayScore"], "theirs": m["awayScore"] if home else m["homeScore"]}
    return None


def last_threes(session, last, team):
    """(team's, opponent's) (made, attempted) threes in its last game; hand-
    entered numbers win."""
    box = threes(session, last["eid"]) if last.get("eid") else {}
    out = []
    for who in (team, last["opp"]):
        mb = manual.team_box("ncaab", last["date"], who)
        if mb.get("threesMade") is not None and mb.get("threesAttempted") is not None:
            out.append((mb["threesMade"], mb["threesAttempted"]))
        else:
            out.append(box.get(who))
    return tuple(out)


def evaluate(session, date_str, g):
    """(pick team, [rule dicts]) or None; no pick if the rules disagree."""
    picks = []
    for team in (g["home"], g["away"]):
        last = last_game(session, team, date_str)
        if not last or last["mine"] >= last["theirs"]:
            continue
        mine, theirs = last_threes(session, last, team)
        if not mine or not theirs or mine[1] < THREE_MIN_ATT or theirs[1] < THREE_MIN_ATT:
            continue
        gap = theirs[0] / theirs[1] - mine[0] / mine[1]
        if gap >= THREE_GAP:
            picks.append((team, 1, f"Backing {team}: lost its last game {last['mine']:g}-{last['theirs']:g} to {last['opp']} ({last['date']}) "
                                   f"while {last['opp']} shot {theirs[0]}-of-{theirs[1]} from three ({theirs[0] / theirs[1]:.0%}) to its "
                                   f"{mine[0]}-of-{mine[1]} ({mine[0] / mine[1]:.0%}) -- a {gap * 100:.0f}-point gap, a loss mostly down to "
                                   f"shooting luck; teams in this spot covered 60.5% ATS, 2018-19 to 2025-26 (n=233), no losing season."))
    if len({p for p, _, _ in picks}) != 1:
        return None
    merged = {}
    for _, n, t in sorted(picks, key=lambda x: x[1]):
        merged[n] = merged[n] + " Also: " + t if n in merged else t
    return picks[0][0], [{"rule": n, "name": RULE_NAMES[n], "backtest": RULE_BACKTEST[n], "detail": t} for n, t in merged.items()]


def run_for_date(session, date_str):
    doc = store.read_doc("ncaab", date_str)
    if doc is None:
        print(f"{date_str}: no NCAA basketball slate.")
        return
    changed = False
    for g in doc.get("games", []):
        if not g.get("away") or not g.get("home"):
            continue
        fails = FAILS[0]
        result = evaluate(session, date_str, g)
        before = tuple(g.get(k) for k in FIELDS)
        if FAILS[0] > fails and before[0] and (result is None or result[0] != before[0] or result[1] != before[2]):
            print(f"  {date_str} {g['away']} @ {g['home']}: an ESPN lookup failed -- keeping the existing pick ({before[0]}); next run re-checks")
            continue
        if result:
            if result[0] != before[0]:
                for k in GRADE_FIELDS:
                    g.pop(k, None)
            g["ncaabStatsFavors"], g["ncaabStatsRules"] = result
            g["ncaabStatsCheck"] = " ".join(f"Rule {r['rule']}: {r['detail']}" for r in result[1])
            print(f"  {date_str} {g['away']} @ {g['home']}: pick {result[0]}")
        else:
            for k in FIELDS + GRADE_FIELDS:
                g.pop(k, None)
        if tuple(g.get(k) for k in FIELDS) != before:
            changed = True
    # A slate graded before its pick existed gets that pick graded from its own final score.
    if doc.get("scored"):
        from score_slate import TWO_WAY_SIGNAL_FIELDS, grade_named  # noqa: E402
        fields = next(f for f in TWO_WAY_SIGNAL_FIELDS if f[0] == "ncaabStatsFavors")
        for g in doc.get("games", []):
            a, h = g.get("awayScore"), g.get("homeScore")
            if g.get("ncaabStatsFavors") and "ncaabStatsCorrect" not in g and isinstance(a, (int, float)) and isinstance(h, (int, float)):
                graded = grade_named(g, g["ncaabStatsFavors"], float(a), float(h))
                for key, out in zip(("correct", "pickReturn", "pickCover", "pickSpreadReturn"), fields[1:]):
                    g[out] = graded[key]
                changed = True
    if changed:
        store.write_doc("ncaab", date_str, doc)
    print(f"{date_str}: {sum(1 for g in doc.get('games', []) if g.get('ncaabStatsFavors'))} NCAAB Stats pick(s).")


def main():
    dates = sys.argv[1:] or [today_et_str()]
    session = espn.make_session()
    for d in dates:
        run_for_date(session, d)


if __name__ == "__main__":
    main()
