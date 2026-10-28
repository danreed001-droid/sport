#!/usr/bin/env python3
"""NBA Stats: a deterministic, backtested model patched directly onto each
day's NBA slate (data/nba/<date>.json), alongside the Ledger and Second
Opinion -- the same way Trend check/Blowout check ride along on NFL/CFB
games. No LLM research involved. Rules were backtested on every NBA regular
season game from 2020-21 through 2026-27 (ATS rates use the games ESPN has
archived lines for: 2020-21 to 2022-23 and 2025-26 on), and each one only
fires on the rest days -- the flagged team's days off since its last game --
where it backtested at 62%+ ATS. Names, rest days and rates are in
scripts/lib/nba_stats_rules.py and ALLOWED_REST below.

  Fades (pick the flagged team's opponent): 1 win streak, 2 OT win,
  3 blown lead, 6 assist edge, 8 close win built on steals, 9 late comeback.
  Backs (pick the flagged team): 5 sloppy turnover loss, 7 out-assisted.
  Rule 4 (cold top scorer) is retired.

"Better/worse record" compares each team's season-to-date win% entering the
game. A game gets "statsFavors" (team name), "statsRules" (every rule that
fired, with its reason) and "statsCheck" (the same reasons as one string)
when rules fire and agree on a side; if they point at opposite sides, the
game gets no pick. Most days no game qualifies.

Needs data/nba/<date>.json to already exist for the target date (the live
Routine's own slate). Per-player points and team turnovers/assists/steals/
free throws for completed games are cached in data/raw/nba_player_points.json
so each run only fetches games it hasn't seen.

Usage: python scripts/nba_stats_signals.py [YYYY-MM-DD ...]   (default: today ET)
"""
import csv
import json
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(__file__))
from lib import espn, store  # noqa: E402
from lib.nba_stats_rules import RULE_BACKTEST, RULE_NAMES  # noqa: E402
from lib.dates import today_et_str  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCORES_CSV = os.path.join(REPO_ROOT, "data", "raw", "master_nba_scores.csv")
POINTS_CACHE = os.path.join(REPO_ROOT, "data", "raw", "nba_player_points.json")
MIN_STREAK = 5
MIN_BLOWN_LEAD = 10
SLOPPY_LOSS_TO = 22
ASSIST_GAP = 18
STEAL_GAP = 6
CLOSE_WIN = 10
# Rest days (for the team the rule is about) on which each rule backtested
# at 62%+ ATS: "b2b" = played yesterday, "1" = one day off, "2+" = two or more.
ALLOWED_REST = {
    1: {"b2b"}, 2: {"b2b", "1", "2+"}, 3: {"b2b"}, 5: {"b2b"}, 6: {"1"},
    7: {"b2b", "1"}, 8: {"b2b", "2+"}, 9: {"b2b"},
}
LATE_COMEBACK = 5

RULES = {
    "streak": "5+ game win streak, home, vs. a worse-record opponent -- "
              "faded 65.3% of the time ATS on a back-to-back (n=49)",
    "ot_win": "won last game in OT, now facing a better-record opponent -- "
              "faded 63.6% of the time ATS (n=77)",
    "blown_lead": "blew a 10+ point lead and lost last game, home, vs. a "
                  "worse-record opponent -- faded 79.2% of the time ATS on a back-to-back (n=24)",
}


def load_team_logs():
    """{team: [{event_id, date, opp, team_score, opp_score, won, is_home}, ...]}
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
                    "event_id": row["Game_ID"], "date": date_str, "opp": opp,
                    "team_score": mine, "opp_score": theirs, "won": mine > theirs,
                    "is_home": is_home,
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


def win_streak(prior):
    streak = 0
    for g in reversed(prior):
        if not g["won"]:
            break
        streak += 1
    return streak


def quarter_data(session, cache, date_str):
    """{event_id: {period, teams: {team_name: [q1,q2,q3,q4,...]}}}, cached
    per calendar date."""
    if date_str in cache:
        return cache[date_str]
    out = {}
    try:
        events = espn.fetch_scoreboard(session, "basketball", "nba", date_str.replace("-", ""))
    except Exception:
        events = []
    for ev in events:
        comp = ev["competitions"][0]
        teams = {c["team"]["displayName"]: [p.get("value") for p in (c.get("linescores") or [])]
                 for c in comp["competitors"]}
        out[ev["id"]] = {"period": comp.get("status", {}).get("period"), "teams": teams}
    cache[date_str] = out
    return out


def blown_lead(q_entry, team, opp):
    """Max lead `team` held over `opp` at any quarter boundary, or 0."""
    t_q, o_q = q_entry["teams"].get(team), q_entry["teams"].get(opp)
    if not t_q or not o_q:
        return 0
    t_cum = o_cum = best = 0
    for t, o in zip(t_q, o_q):
        t_cum += t or 0
        o_cum += o or 0
        best = max(best, t_cum - o_cum)
    return best


def trailed_after_three(q_entry, team, opp):
    """How many points `team` trailed `opp` by after 3 quarters (negative or
    zero if it led or was tied), or None without three quarters of data."""
    t_q, o_q = q_entry["teams"].get(team), q_entry["teams"].get(opp)
    if not t_q or not o_q or len(t_q) < 3 or len(o_q) < 3 or None in t_q[:3] + o_q[:3]:
        return None
    return sum(o_q[:3]) - sum(t_q[:3])


class BoxCache:
    """Box-score bits for completed games, persisted so finished games are
    only ever fetched once:
    {event_id: {"pts": {team: {player_id: [pts, name]}}, "to": {team: turnovers}}}."""

    def __init__(self, session):
        self.session = session
        self.data = {}
        if os.path.exists(POINTS_CACHE):
            with open(POINTS_CACHE, encoding="utf-8") as f:
                self.data = json.load(f)
        self.dirty = False

    def _entry(self, event_id):
        e = self.data.get(event_id)
        if not isinstance(e, dict) or "ftm" not in e:  # missing, failed, or an older format
            e = self.data[event_id] = self._fetch(event_id)
            self.dirty = True
        return e or {}

    def get(self, event_id, team):
        return self._entry(event_id).get("pts", {}).get(team)

    def turnovers(self, event_id, team):
        return self._entry(event_id).get("to", {}).get(team)

    def assists(self, event_id, team):
        return self._entry(event_id).get("ast", {}).get(team)

    def steals(self, event_id, team):
        return self._entry(event_id).get("stl", {}).get(team)

    def free_throws_made(self, event_id, team):
        return self._entry(event_id).get("ftm", {}).get(team)

    def is_regular_season(self, event_id):
        return self._entry(event_id).get("type") == 2

    def _fetch(self, event_id):
        try:
            d = self.session.get(
                f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event={event_id}",
                timeout=15,
            ).json()
        except Exception:
            return None
        box = d.get("boxscore", {})
        pts_by_team, to_by_team, ast_by_team, stl_by_team, ftm_by_team = {}, {}, {}, {}, {}
        for t in box.get("players", []):
            if not t.get("statistics"):
                continue
            cat = t["statistics"][0]
            labels = cat.get("labels", [])
            if "PTS" not in labels:
                continue
            i = labels.index("PTS")
            pts = {}
            for ath in cat.get("athletes", []):
                st = ath.get("stats") or []
                if ath.get("didNotPlay") or len(st) <= i:
                    continue
                try:
                    pts[ath["athlete"]["id"]] = [int(st[i]), ath["athlete"].get("displayName")]
                except (TypeError, ValueError, KeyError):
                    continue
            pts_by_team[t["team"]["displayName"]] = pts
        for t in box.get("teams", []):
            stats = {s.get("name"): s.get("displayValue") for s in t.get("statistics", [])}
            name = t["team"]["displayName"]
            for key, out in (("totalTurnovers", to_by_team), ("assists", ast_by_team), ("steals", stl_by_team)):
                try:
                    out[name] = int(stats[key])
                except (KeyError, TypeError, ValueError):
                    pass
            try:
                ftm_by_team[name] = int(str(stats["freeThrowsMade-freeThrowsAttempted"]).split("-")[0])
            except (KeyError, TypeError, ValueError):
                pass
        if not pts_by_team:
            return None
        return {"pts": pts_by_team, "to": to_by_team, "ast": ast_by_team, "stl": stl_by_team, "ftm": ftm_by_team,
                "type": d.get("header", {}).get("season", {}).get("type")}

    def save(self):
        if self.dirty:
            with open(POINTS_CACHE, "w", encoding="utf-8") as f:
                json.dump(self.data, f, separators=(",", ":"))


def evaluate_game(session, points, by_team, q_cache, date_str, home, away):
    """Returns (pick_team, check_text) or None. Collects every rule that
    fires for either team; skips the game if they disagree on a side."""
    picks = []  # (pick_team, rule number, text)
    for team, is_home, opp in ((home, True, away), (away, False, home)):
        games = by_team.get(team, [])
        prior = [g for g in games if g["date"] < date_str]
        if not prior:
            continue
        last = prior[-1]
        start = len(picks)
        team_w, team_l = season_record(games, date_str)
        opp_w, opp_l = season_record(by_team.get(opp, []), date_str)
        if not (team_w + team_l) or not (opp_w + opp_l):
            continue
        team_pct, opp_pct = team_w / (team_w + team_l), opp_w / (opp_w + opp_l)
        opp_weaker, opp_stronger = opp_pct < team_pct, opp_pct > team_pct

        if win_streak(prior) >= MIN_STREAK and is_home and opp_weaker:
            picks.append((opp, 1, f"Fading {team}: {RULES['streak']}."))

        q = quarter_data(session, q_cache, last["date"])
        q_entry = next((v for v in q.values()
                        if team in v["teams"] and last["opp"] in v["teams"]), None)
        if q_entry:
            if q_entry.get("period") and q_entry["period"] > 4 and last["won"] and opp_stronger:
                picks.append((opp, 2, f"Fading {team}: {RULES['ot_win']}."))
            if not last["won"] and is_home and opp_weaker and blown_lead(q_entry, team, last["opp"]) >= MIN_BLOWN_LEAD:
                picks.append((opp, 3, f"Fading {team}: {RULES['blown_lead']}."))
            back_to_back = (date.fromisoformat(date_str) - date.fromisoformat(last["date"])).days == 1
            trail = trailed_after_three(q_entry, team, last["opp"]) if last["won"] and back_to_back else None
            if trail is not None and trail >= LATE_COMEBACK:
                picks.append((opp, 9, f"Fading {team}: came back to win last night after trailing by {trail:g} "
                                   f"through 3 quarters ({LATE_COMEBACK}+), now on the second night of a back-to-back "
                                   f"-- teams in this spot were faded 68.1% of the time ATS (n=91)."))

        mine, theirs = points.assists(last["event_id"], team), points.assists(last["event_id"], last["opp"])
        if mine is not None and theirs is not None:
            if mine - theirs >= ASSIST_GAP:
                picks.append((opp, 6, f"Fading {team}: had {mine - theirs} more assists than its opponent last game "
                                   f"({ASSIST_GAP}+) -- teams in this spot were faded 79.2% of the time ATS with 1 day of rest (n=24)."))
            if theirs - mine >= ASSIST_GAP and not is_home:
                picks.append((team, 7, f"Backing {team}: was out-assisted by {theirs - mine} last game ({ASSIST_GAP}+), "
                                    f"now on the road -- teams in this spot covered 72.7% ATS on a back-to-back or 1 day of rest (n=22, small sample)."))

        margin = last["team_score"] - last["opp_score"]
        if last["won"] and margin < CLOSE_WIN and not (is_home and opp_stronger):
            ms, ts = points.steals(last["event_id"], team), points.steals(last["event_id"], last["opp"])
            if ms is not None and ts is not None and ms - ts >= STEAL_GAP:
                picks.append((opp, 8, f"Fading {team}: won last game by {margin:g} with {ms - ts} more steals "
                                   f"({STEAL_GAP}+) -- teams in this spot were faded 64.5% of the time ATS on a back-to-back or 2+ days of rest (n=62)."))

        if is_home and opp_weaker and not last["won"]:
            to = points.turnovers(last["event_id"], team)
            if to is not None and to >= SLOPPY_LOSS_TO:
                picks.append((team, 5, f"Backing {team}: lost last game with {to} turnovers ({SLOPPY_LOSS_TO}+), "
                                    f"now home vs. a worse-record opponent -- teams in this spot covered "
                                    f"77.8% ATS on a back-to-back (n=9, small sample)."))

        # Keep only the rules whose backtest cleared 62% for this team's rest
        # (days off since its last game).
        gap = (date.fromisoformat(date_str) - date.fromisoformat(last["date"])).days - 1
        rest = "b2b" if gap <= 0 else ("1" if gap == 1 else "2+")
        picks[start:] = [pk for pk in picks[start:] if rest in ALLOWED_REST[pk[1]]]
    sides = {p for p, _, _ in picks}
    if len(sides) != 1:
        return None
    rules = [{"rule": n, "name": RULE_NAMES[n], "backtest": RULE_BACKTEST[n], "detail": text}
             for _, n, text in sorted(picks, key=lambda x: x[1])]
    return picks[0][0], rules


def run_for_date(session, points, by_team, q_cache, date_str):
    doc = store.read_doc("nba", date_str)
    if doc is None:
        print(f"{date_str}: no NBA slate yet, nothing to patch.")
        return
    changed = 0
    for g in doc.get("games", []):
        away, home = g.get("away"), g.get("home")
        if not away or not home:
            continue
        result = evaluate_game(session, points, by_team, q_cache, date_str, home, away)
        before = (g.get("statsFavors"), g.get("statsCheck"), g.get("statsRules"))
        if result:
            if result[0] != before[0]:
                for k in ("statsCorrect", "statsReturn", "statsCover", "statsSpreadReturn"):
                    g.pop(k, None)
            g["statsFavors"], g["statsRules"] = result
            g["statsCheck"] = " ".join(f"Rule {r['rule']}: {r['detail']}" for r in g["statsRules"])
            print(f"  {date_str} {away} @ {home}: pick {result[0]} -- rules {[r['rule'] for r in result[1]]}")
        else:
            for k in ("statsFavors", "statsCheck", "statsRules", "statsCorrect", "statsReturn", "statsCover", "statsSpreadReturn"):
                g.pop(k, None)
        if (g.get("statsFavors"), g.get("statsCheck"), g.get("statsRules")) != before:
            changed += 1
    if changed:
        store.write_doc("nba", date_str, doc)
    picks = sum(1 for g in doc.get("games", []) if g.get("statsFavors"))
    print(f"{date_str}: {picks} NBA Stats pick(s).")


def main():
    dates = sys.argv[1:] or [today_et_str()]
    session = espn.make_session()
    points = BoxCache(session)
    # The backtests are regular-season only, and the scores archive also
    # holds preseason games -- drop those so streaks, records and "last game"
    # mean what they meant in the backtest.
    by_team = {team: [g for g in games if points.is_regular_season(g["event_id"])]
               for team, games in load_team_logs().items()}
    q_cache = {}
    try:
        for date_str in dates:
            run_for_date(session, points, by_team, q_cache, date_str)
    finally:
        points.save()


if __name__ == "__main__":
    main()
