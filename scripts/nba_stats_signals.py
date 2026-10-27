#!/usr/bin/env python3
"""NBA Stats: a deterministic, backtested signal engine (no LLM research,
unlike the other Diamond Ledger sports). It fades a team coming off one of
three specific situations, each one backtested across every NBA regular
season game from 2020-21 through 2026-27 (7,293 games):

  1. 5+ game win streak, playing at home, next opponent has a worse
     record  -> faded 57.2% of the time ATS (n=208)
  2. Won its last game in OT, next opponent has a better record
     -> faded 63.6% of the time ATS (n=77)
  3. Blew a 10+ point lead and lost its last game, playing at home next,
     next opponent has a worse record -> faded 60.8% of the time ATS (n=79)

"Opponent has a worse/better record" compares each team's win% in this
season to date, entering the game being picked. Every pick is a fade: the
play is the FLAGGED team's opponent to cover, not the flagged team itself.

This is sparse by design -- most days have zero qualifying games. A game
only gets a pick when a rule fires; otherwise it's left out of the slate
entirely (there is no "no signal" entry to skip, unlike the researched
sports' slates).

Usage: python scripts/nba_stats_signals.py [YYYY-MM-DD]   (default: today ET)
"""
import csv
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(__file__))
from lib import espn, store  # noqa: E402
from lib.dates import today_et_str, et_date_of_iso  # noqa: E402

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
CONFIDENCE = {"streak": "lean", "ot_win": "solid", "blown_lead": "lean"}


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


def fetch_spread(session, comp, event_id):
    away_ml, home_ml = espn.fetch_event_odds_from_scoreboard(comp)
    home_spread = away_spread = None
    odds_list = comp.get("odds") or []
    if odds_list and isinstance(odds_list[0], dict):
        sp = odds_list[0].get("spread")
        if isinstance(sp, (int, float)):
            home_spread, away_spread = sp, -sp
    if home_spread is None:
        try:
            r = session.get(
                f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event={event_id}",
                timeout=12,
            )
            for o in (r.json().get("pickcenter") or []):
                if isinstance(o, dict) and isinstance(o.get("spread"), (int, float)):
                    home_spread, away_spread = o["spread"], -o["spread"]
                    break
        except Exception:
            pass
    return away_ml, home_ml, away_spread, home_spread


def main():
    date_str = sys.argv[1] if len(sys.argv) > 1 else today_et_str()
    session = espn.make_session()
    by_team = load_team_logs()

    # ESPN's scoreboard ?dates= query buckets by its own (roughly UTC) day,
    # which doesn't always match the US-Eastern day fetch_scores.py stores
    # games under -- query the surrounding days too and keep only events
    # whose true ET date is the one we're generating a slate for.
    query_date = datetime.strptime(date_str, "%Y-%m-%d")
    events, seen_ids = [], set()
    for delta in (-1, 0, 1):
        probe = (query_date + timedelta(days=delta)).strftime("%Y%m%d")
        try:
            for ev in espn.fetch_scoreboard(session, "basketball", "nba", probe):
                if ev["id"] not in seen_ids and et_date_of_iso(ev["date"]) == date_str:
                    seen_ids.add(ev["id"])
                    events.append(ev)
        except Exception as exc:
            print(f"scoreboard fetch failed for {probe}: {exc}", file=sys.stderr)
    q_cache = {}
    games_out = []

    for ev in events:
        comp = ev["competitions"][0]
        competitors = comp["competitors"]
        home = next(c for c in competitors if c["homeAway"] == "home")["team"]["displayName"]
        away = next(c for c in competitors if c["homeAway"] == "away")["team"]["displayName"]

        fired = None  # (flagged_team, opponent, rule_key)
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
                fired = (team, opp, "streak")
                break

            q = quarter_data(session, q_cache, last["date"])
            q_entry = next((v for v in q.values() if team in v.get("teams", {}) and last["opp"] in v.get("teams", {})), None)
            if q_entry and q_entry.get("period") and q_entry["period"] > 4 and last["won"] and opp_stronger:
                fired = (team, opp, "ot_win")
                break
            if q_entry and not last["won"] and is_home and opp_weaker:
                lead = blown_lead(q_entry, team, last["opp"])
                if lead >= MIN_BLOWN_LEAD:
                    fired = (team, opp, "blown_lead")
                    break

        if not fired:
            continue
        flagged_team, pick_team, rule_key = fired
        away_ml, home_ml, away_sp, home_sp = fetch_spread(session, comp, ev["id"])
        games_out.append({
            "away": away, "home": home, "time": ev["date"],
            "awayMoneyline": away_ml, "homeMoneyline": home_ml,
            "awaySpread": away_sp, "homeSpread": home_sp,
            "awaySpreadOdds": None, "homeSpreadOdds": None,
            "pick": pick_team, "confidence": CONFIDENCE[rule_key],
            "signalRule": rule_key, "signalAgainst": flagged_team,
            "skipped": home_sp is None, "skipReason": "no-spread-yet" if home_sp is None else None,
            "statLines": [f"Fading {flagged_team}: {RULES[rule_key]}."],
        })

    doc = {"date": date_str, "sport": "nba_stats", "scored": False,
           "generatedAt": datetime.utcnow().isoformat(timespec="seconds") + "Z", "games": games_out}
    store.write_doc("nba_stats", date_str, doc)
    print(f"Wrote {len(games_out)} signal pick(s) for {date_str}.")
    for g in games_out:
        print(f"  {g['away']} @ {g['home']}: fade {g['signalAgainst']} -> pick {g['pick']} "
              f"[{g['signalRule']}]{' (no spread yet)' if g['skipped'] else ''}")


if __name__ == "__main__":
    main()
