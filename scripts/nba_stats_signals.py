#!/usr/bin/env python3
"""NBA Stats: a deterministic, backtested model patched directly onto each
day's NBA slate (data/nba/<date>.json), alongside the Ledger and Second
Opinion -- the same way Trend check/Blowout check ride along on NFL/CFB
games. No LLM research involved: it fades a team coming off one of three
specific situations, each backtested across every NBA regular season game
from 2020-21 through 2026-27 (7,293 games):

  1. 5+ game win streak, playing at home, next opponent has a worse
     record  -> faded 57.2% of the time ATS (n=208)
  2. Won its last game in OT, next opponent has a better record
     -> faded 63.6% of the time ATS (n=77)
  3. Blew a 10+ point lead and lost its last game, playing at home next,
     next opponent has a worse record -> faded 60.8% of the time ATS (n=79)

"Opponent has a worse/better record" compares each team's win% in this
season to date, entering the game being picked. Every pick is a fade: the
play is the FLAGGED team's opponent to cover, not the flagged team itself.
It sets "statsFavors" (team name) and "statsCheck" (the reasoning, with the
backtested rate) on whichever games in that day's NBA slate qualify --
most days, none do, and those two fields are simply left unset.

Needs data/nba/<date>.json to already exist for the target date (the live
Routine's own slate) since that's where today's matchups and spreads come
from; this script only adds its own two fields to games already there.

Usage: python scripts/nba_stats_signals.py [YYYY-MM-DD ...]   (default: today ET)
"""
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from lib import espn, store  # noqa: E402
from lib.dates import today_et_str  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCORES_CSV = os.path.join(REPO_ROOT, "data", "raw", "master_nba_scores.csv")
MIN_STREAK = 5
MIN_BLOWN_LEAD = 10

RULES = {
    "streak": "5+ game win streak, home, vs. a worse-record opponent -- "
              "faded 57.2% of the time ATS (n=208, 2020-21–2026-27)",
    "ot_win": "won last game in OT, now facing a better-record opponent -- "
              "faded 63.6% of the time ATS (n=77, 2020-21–2026-27)",
    "blown_lead": "blew a 10+ point lead and lost last game, home, vs. a "
                  "worse-record opponent -- faded 60.8% of the time ATS "
                  "(n=79, 2020-21–2026-27)",
}


def load_team_logs():
    """Returns {team: [{date, opp, team_score, opp_score, won, is_home}, ...]}
    in chronological order, from the continuously-archived season CSV."""
    by_team = {}
    if not os.path.exists(SCORES_CSV):
        return by_team
    with open(SCORES_CSV, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if not (row.get("Status") or "").startswith("Final"):
                continue
            try:
                away_score, home_score = float(row["Away_Score"]), float(row["Home_Score"])
            except (TypeError, ValueError):
                continue
            away, home, date_str = row["Away_Team"], row["Home_Team"], row["Date"]
            for team, opp, mine, theirs, is_home in (
                (away, home, away_score, home_score, False),
                (home, away, home_score, away_score, True),
            ):
                by_team.setdefault(team, []).append({
                    "date": date_str, "opp": opp, "team_score": mine,
                    "opp_score": theirs, "won": mine > theirs, "is_home": is_home,
                })
    for team in by_team:
        by_team[team].sort(key=lambda g: g["date"])
    return by_team


def season_record(games, before_date):
    w = l = 0
    for g in games:
        if g["date"] >= before_date:
            continue
        w += 1 if g["won"] else 0
        l += 0 if g["won"] else 1
    return w, l


def win_streak_ending_at(games, idx):
    streak = 0
    for g in reversed(games[:idx + 1]):
        if g["won"]:
            streak += 1
        else:
            break
    return streak


def quarter_data(session, cache, date_str):
    """{event_id: {period, teams: {team_name: [q1,q2,q3,q4,...]}}}, cached
    per calendar date so a date shared by several teams' last games is only
    fetched once."""
    if date_str in cache:
        return cache[date_str]
    out = {}
    yyyymmdd = date_str.replace("-", "")
    try:
        events = espn.fetch_scoreboard(session, "basketball", "nba", yyyymmdd)
    except Exception:
        events = []
    for ev in events:
        comp = ev["competitions"][0]
        period = comp.get("status", {}).get("period")
        teams = {}
        for c in comp["competitors"]:
            teams[c["team"]["displayName"]] = [p.get("value") for p in (c.get("linescores") or [])]
        out[ev["id"]] = {"period": period, "teams": teams}
    cache[date_str] = out
    return out


def blown_lead(q_entry, team, opp):
    """Max lead `team` held over `opp` at any quarter boundary, or 0."""
    teams = q_entry.get("teams", {})
    t_q, o_q = teams.get(team), teams.get(opp)
    if not t_q or not o_q:
        return 0
    t_cum = o_cum = 0
    worst_for_opp = 0
    for t, o in zip(t_q, o_q):
        t_cum += t or 0
        o_cum += o or 0
        worst_for_opp = max(worst_for_opp, t_cum - o_cum)
    return worst_for_opp


def evaluate_game(session, by_team, q_cache, date_str, home, away):
    """Returns (flagged_team, pick_team, rule_key) or None."""
    for team, is_home, opp in ((home, True, away), (away, False, home)):
        games = by_team.get(team, [])
        prior = [g for g in games if g["date"] < date_str]
        if not prior:
            continue
        last = prior[-1]
        opp_games = by_team.get(opp, [])
        team_w, team_l = season_record(games, date_str)
        opp_w, opp_l = season_record(opp_games, date_str)
        if not (team_w + team_l) or not (opp_w + opp_l):
            continue
        team_pct, opp_pct = team_w / (team_w + team_l), opp_w / (opp_w + opp_l)
        opp_weaker, opp_stronger = opp_pct < team_pct, opp_pct > team_pct

        streak = win_streak_ending_at(prior, len(prior) - 1)
        if streak >= MIN_STREAK and is_home and opp_weaker:
            return team, opp, "streak"

        q = quarter_data(session, q_cache, last["date"])
        q_entry = next((v for v in q.values() if team in v.get("teams", {}) and last["opp"] in v.get("teams", {})), None)
        if q_entry and q_entry.get("period") and q_entry["period"] > 4 and last["won"] and opp_stronger:
            return team, opp, "ot_win"
        if q_entry and not last["won"] and is_home and opp_weaker:
            lead = blown_lead(q_entry, team, last["opp"])
            if lead >= MIN_BLOWN_LEAD:
                return team, opp, "blown_lead"
    return None


def run_for_date(session, by_team, q_cache, date_str):
    doc = store.read_doc("nba", date_str)
    if doc is None:
        print(f"{date_str}: no NBA slate yet, nothing to patch.")
        return
    changed = 0
    for g in doc.get("games", []):
        away, home = g.get("away"), g.get("home")
        if not away or not home:
            continue
        fired = evaluate_game(session, by_team, q_cache, date_str, home, away)
        if fired:
            flagged_team, pick_team, rule_key = fired
            g["statsFavors"] = pick_team
            g["statsCheck"] = f"Fading {flagged_team}: {RULES[rule_key]}."
            changed += 1
            print(f"  {date_str} {away} @ {home}: fade {flagged_team} -> pick {pick_team} [{rule_key}]")
        else:
            g.pop("statsFavors", None)
            g.pop("statsCheck", None)
    if changed and doc.get("scored"):
        # This slate was already graded before statsFavors existed on it --
        # force a regrade so score_slate.py's next pass fills in the new
        # statsCorrect/statsCover/etc fields too (idempotent: everything
        # else it recomputes comes out the same).
        doc["scored"] = False
    store.write_doc("nba", date_str, doc)
    print(f"{date_str}: patched {changed} signal pick(s) onto the NBA slate.")


def main():
    dates = sys.argv[1:] or [today_et_str()]
    session = espn.make_session()
    by_team = load_team_logs()
    q_cache = {}
    for date_str in dates:
        run_for_date(session, by_team, q_cache, date_str)


if __name__ == "__main__":
    main()
