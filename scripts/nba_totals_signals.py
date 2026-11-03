#!/usr/bin/env python3
"""NBA Totals: patches full-game total picks onto the day's NBA slate
(data/nba/<date>.json), like nba_stats_signals.py does for sides. Rules in
lib/nba_totals_rules.py:

  1. UNDER: the spread is 3 points or less;
  2. UNDER: the road team's previous regular-season game (within 10 days) went to OT;
  3. OVER (on trial): the home team won its last game and a player who scored
     30-39 in it is out tonight (ESPN injury report: "Out").
  4-8. UNDER: a team lost its last game AT HOME to a worse-record team (it had
     the better season win % going in, 5+ games played) and now faces a
     better-record team: 4 lost by 1-9; 5 lost by 1-9 and rested; 6 now on the
     road; 7 on the road and rested; 8 on the road after losing by 10+.

If an over rule and an under rule both fire, the game gets no pick.

Fields written on a game: totalsLine (the line the pick is graded against),
totalsFavors ("Under" or "Over"), totalsRules ([{rule, name, backtest, detail}]) and
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
picks are marked totalsBackfill (= BACKFILL_VERSION once checked with every rule; for rule 3,
"out" means not in that game's box score). Default: every past slate this season.
"""
import csv
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(__file__))
from lib import espn, store  # noqa: E402
from lib.nba_absence import big_scorers, injury_out  # noqa: E402
from lib.dates import et_date_of_iso, today_et_str  # noqa: E402
from lib.nba_totals_rules import CLOSE_SPREAD, OT_LOOKBACK_DAYS, OVER_RULES, RULE_BACKTEST, RULE_NAMES  # noqa: E402
from score_slate import _same_team  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCORES_CSV = os.path.join(REPO_ROOT, "data", "raw", "master_nba_scores.csv")
LINES_CSV = os.path.join(REPO_ROOT, "data", "raw", "nba_lines.csv")
FIELDS = ("totalsLine", "totalsFavors", "totalsRules", "totalsCheck")
# Bumped whenever rules are added, so --backfill rechecks past games with them.
BACKFILL_VERSION = 3


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


def team_log(rows, team, since, before):
    """The team's finished games in [since, before), oldest first:
    [{date, home, opp, pf, pa}]."""
    out = []
    for r in rows:
        if not (since <= r["Date"] < before) or not str(r["Status"]).lower().startswith("final"):
            continue
        try:
            a, h = float(r["Away_Score"]), float(r["Home_Score"])
        except (TypeError, ValueError):
            continue
        if _same_team(team, r["Home_Team"]):
            out.append({"date": r["Date"], "home": True, "opp": r["Away_Team"], "pf": h, "pa": a})
        elif _same_team(team, r["Away_Team"]):
            out.append({"date": r["Date"], "home": False, "opp": r["Home_Team"], "pf": a, "pa": h})
    return sorted(out, key=lambda x: x["date"])


def win_pct(log):
    return sum(1 for x in log if x["pf"] > x["pa"]) / len(log) if log else None


def home_upset_loss(rows, team, opp_now, date_str, since):
    """If `team`'s last game (within 10 days) was a home loss to a worse-record
    team and tonight's opponent has the better record, the facts rules 4-8
    use; else None. Records are season win % going into each game."""
    log = team_log(rows, team, since, date_str)
    if not log:
        return None
    last = log[-1]
    gap = (date.fromisoformat(date_str) - date.fromisoformat(last["date"])).days
    if gap > OT_LOOKBACK_DAYS or not last["home"] or last["pf"] >= last["pa"]:
        return None
    before = log[:-1]
    them = team_log(rows, last["opp"], since, last["date"])
    if len(before) < 5 or not them or not win_pct(before) > win_pct(them):
        return None
    mine, theirs = win_pct(log), win_pct(team_log(rows, opp_now, since, date_str))
    if theirs is None or not theirs > mine:
        return None
    return {"last": last, "margin": last["pa"] - last["pf"], "rested": gap > 1, "record": (mine, theirs)}


def evaluate(g, rows, date_str, since, spread, points=None, absent=None):
    """Rules that fire for game g. absent(team_name) -> set of player ids out
    tonight (None if unknown); points is NBA Stats' BoxCache. Without them
    rule 3 isn't checked."""
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
    hl = last_game(rows, g["home"], date_str, since) if points is not None and absent is not None else None
    if hl and (date.fromisoformat(date_str) - date.fromisoformat(hl["Date"])).days <= OT_LOOKBACK_DAYS:
        was_home = _same_team(g["home"], hl["Home_Team"])
        team = hl["Home_Team"] if was_home else hl["Away_Team"]
        mine, theirs = (float(hl["Home_Score"]), float(hl["Away_Score"])) if was_home else (float(hl["Away_Score"]), float(hl["Home_Score"]))
        if mine > theirs:
            out_now = absent(g["home"])
            sitting = [b for b in big_scorers(points, hl["Game_ID"], team, 30, 39) if out_now is not None and b[0] in out_now]
            if sitting:
                who = ", ".join(f"{n} ({p})" for _, p, n in sitting)
                rules.append({"rule": 3, "detail": f"{g['home']} (home) won its last game on {hl['Date']} and {who} "
                                                   f"is out tonight."})
    for side, opp in (("home", "away"), ("away", "home")):
        u = home_upset_loss(rows, g[side], g[opp], date_str, since)
        if not u:
            continue
        lost = f"{g[side]} lost at home to {u['last']['opp']} by {u['margin']:g} on {u['last']['date']} (the worse-record team)"
        vs = f"now {'on the road' if side == 'away' else 'at home'} vs. better-record {g[opp]}"
        if u["margin"] <= 9:
            rules.append({"rule": 4, "detail": f"{lost}; {vs}."})
            if u["rested"]:
                rules.append({"rule": 5, "detail": f"{lost}; {vs}, rested."})
        if side == "away":
            rules.append({"rule": 6, "detail": f"{lost}; {vs}."})
            if u["rested"]:
                rules.append({"rule": 7, "detail": f"{lost}; {vs}, rested."})
            if u["margin"] >= 10:
                rules.append({"rule": 8, "detail": f"{lost} (10+); {vs}."})
    for r in rules:
        r["name"], r["backtest"] = RULE_NAMES[r["rule"]], RULE_BACKTEST[r["rule"]]
    return rules


def verdict(rules):
    """'Over', 'Under', or None when no rule fired or the rules disagree."""
    sides = {"Over" if r["rule"] in OVER_RULES else "Under" for r in rules}
    return sides.pop() if len(sides) == 1 else None


def run_for_date(session, points, rows, date_str):
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
            inj = injury_out(session, ev["id"])
            absent = (lambda team: None) if inj is None else (
                lambda team: set().union(*[set(v) for k, v in inj.items() if _same_team(team, k)]))
            rules = evaluate(g, rows, date_str, since, spread, points, absent)
            side = verdict(rules)
            if rules and not side:
                print(f"  {date_str} {g['away']} @ {g['home']}: rules {[r['rule'] for r in rules]} disagree -- no pick")
            if side and g.get("totalsLine") is not None:
                g["totalsFavors"] = side
                g["totalsRules"] = rules
                g["totalsCheck"] = " ".join(f"Rule {r['rule']}: {r['detail']}" for r in rules)
                picks += 1
                print(f"  {date_str} {g['away']} @ {g['home']}: {side} {g['totalsLine']:g} -- rules {[r['rule'] for r in rules]}")
            else:
                for k in ("totalsFavors", "totalsRules", "totalsCheck"):
                    g.pop(k, None)
        if {k: g.get(k) for k in FIELDS} != before:
            changed += 1
    if changed:
        store.write_doc("nba", date_str, doc)
    print(f"{date_str}: {picks} NBA Totals pick(s).")


def backfill(points, rows, dates):
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
            if g.get("totalsBackfill") == BACKFILL_VERSION or (g.get("totalsFavors") and not g.get("totalsBackfill")):
                continue  # already checked with every rule, or a live pick
            if not isinstance(g.get("awayScore"), (int, float)) or not isinstance(g.get("homeScore"), (int, float)):
                continue  # not final
            ln = next((r for r in lines if r["date"] == date_str and _same_team(g.get("away"), r["away"])
                       and _same_team(g.get("home"), r["home"])), None)
            try:
                total, spread = float(ln["total_close"]), float(ln["spread_close"])
            except (TypeError, ValueError):
                continue  # no archived closing line
            def absent(team, gid=ln["game_id"]):
                """Players out of this finished game: anyone not in its box score."""
                points.get(gid, team)  # makes sure the game's box is cached
                names = list(((points.data.get(gid) or {}).get("pts") or {}))
                key = next((k for k in names if _same_team(team, k)), None)
                box = points.get(gid, key) if key else None
                return None if box is None else _NotIn(box)
            rules = evaluate(g, rows, date_str, since, spread, points, absent)
            side = verdict(rules)
            before = (g.get("totalsFavors"), [r["rule"] for r in g.get("totalsRules") or []])
            g["totalsBackfill"] = BACKFILL_VERSION  # checked with every rule, even when none fired, so it's never re-done
            for k in ("totalsLine", "totalsFavors", "totalsRules", "totalsCheck", "totalsCorrect", "totalsReturn"):
                g.pop(k, None)
            if side:
                g["totalsLine"], g["totalsFavors"], g["totalsRules"] = total, side, rules
                g["totalsCheck"] = " ".join(f"Rule {r['rule']}: {r['detail']}" for r in rules) + " (backfilled from the DraftKings closing line)"
                total_picks += 1
                if before != (side, [r["rule"] for r in rules]):
                    print(f"  {date_str} {g['away']} @ {g['home']}: {side} {total:g} -- rules {[r['rule'] for r in rules]}")
            elif before[0]:
                print(f"  {date_str} {g['away']} @ {g['home']}: was {before[0]} {before[1]}, now no pick (rules {[r['rule'] for r in rules]})")
            changed += 1
        if changed:
            store.write_doc("nba", date_str, doc)
    print(f"backfilled {total_picks} NBA Totals pick(s).")


class _NotIn:
    """'Players out' for a finished game: anyone not in its box score."""
    def __init__(self, box):
        self.box = box

    def __contains__(self, pid):
        return pid not in self.box


def main():
    from nba_stats_signals import BoxCache
    session = espn.make_session()
    points = BoxCache(session)
    with open(SCORES_CSV, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    try:
        if sys.argv[1:2] == ["--backfill"]:
            start = season_start(today_et_str())
            backfill(points, rows, sys.argv[2:] or [d for d, _ in store.list_docs("nba") if d >= start])
            return
        for d in sys.argv[1:] or [today_et_str()]:
            run_for_date(session, points, rows, d)
    finally:
        points.save()


if __name__ == "__main__":
    main()
