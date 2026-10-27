#!/usr/bin/env python3
"""NBA Stats: a deterministic, backtested model patched directly onto each
day's NBA slate (data/nba/<date>.json), alongside the Ledger and Second
Opinion -- the same way Trend check/Blowout check ride along on NFL/CFB
games. No LLM research involved. Four rules, each backtested on every NBA
regular season game from 2020-21 through 2026-27 (ATS rates use the games
ESPN has archived lines for: 2020-21 to 2022-23 and 2025-26 on):

  Fades (pick the flagged team's opponent):
  1. 5+ game win streak, playing at home, opponent has a worse record
     -> faded 57.2% of the time ATS (n=208)
  2. Won its last game in OT, opponent has a better record
     -> faded 63.6% of the time ATS (n=77)
  3. Blew a 10+ point lead and lost its last game, playing at home,
     opponent has a worse record -> faded 60.8% of the time ATS (n=79)

  Back (pick the flagged team):
  4. Its top scorer (18+ ppg, 5+ games) was held under 70% of his season
     average last game, and it's playing at home -> covered 57.9% ATS
     (n=537); 60.8% (n=273) when the opponent has a better record
  5. Lost its last game with 22+ team turnovers, playing at home, opponent
     has a worse record -> covered 62.1% ATS (n=29 -- small; the broader
     "lost with 22+ turnovers, any next game" version is 58.6%, n=191)

"Better/worse record" compares each team's season-to-date win% entering the
game. A game gets "statsFavors" (team name) and "statsCheck" (the reasoning,
with the backtested rate) when rules fire and agree on a side; if they point
at opposite sides, the game gets no pick. Most days no game qualifies.

Needs data/nba/<date>.json to already exist for the target date (the live
Routine's own slate). Per-player points and team turnovers for completed
games are cached in data/raw/nba_player_points.json so each run only
fetches games it hasn't seen.

Usage: python scripts/nba_stats_signals.py [YYYY-MM-DD ...]   (default: today ET)
"""
import csv
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from lib import espn, store  # noqa: E402
from lib.dates import today_et_str  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCORES_CSV = os.path.join(REPO_ROOT, "data", "raw", "master_nba_scores.csv")
POINTS_CACHE = os.path.join(REPO_ROOT, "data", "raw", "nba_player_points.json")
MIN_STREAK = 5
MIN_BLOWN_LEAD = 10
STAR_MIN_PPG = 18
STAR_MIN_GP = 5
COLD_CUTOFF = 0.7
SLOPPY_LOSS_TO = 22

RULES = {
    "streak": "5+ game win streak, home, vs. a worse-record opponent -- "
              "faded 57.2% of the time ATS (n=208)",
    "ot_win": "won last game in OT, now facing a better-record opponent -- "
              "faded 63.6% of the time ATS (n=77)",
    "blown_lead": "blew a 10+ point lead and lost last game, home, vs. a "
                  "worse-record opponent -- faded 60.8% of the time ATS (n=79)",
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
        if not isinstance(e, dict) or "pts" not in e:  # missing, failed, or pre-turnover format
            e = self.data[event_id] = self._fetch(event_id)
            self.dirty = True
        return e or {}

    def get(self, event_id, team):
        return self._entry(event_id).get("pts", {}).get(team)

    def turnovers(self, event_id, team):
        return self._entry(event_id).get("to", {}).get(team)

    def _fetch(self, event_id):
        try:
            d = self.session.get(
                f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event={event_id}",
                timeout=15,
            ).json()
        except Exception:
            return None
        box = d.get("boxscore", {})
        pts_by_team, to_by_team = {}, {}
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
            try:
                to_by_team[t["team"]["displayName"]] = int(stats["totalTurnovers"])
            except (KeyError, TypeError, ValueError):
                continue
        if not pts_by_team:
            return None
        return {"pts": pts_by_team, "to": to_by_team}

    def save(self):
        if self.dirty:
            with open(POINTS_CACHE, "w", encoding="utf-8") as f:
                json.dump(self.data, f, separators=(",", ":"))


def cold_star(points, prior, team):
    """If `team`'s top scorer entering its last game (18+ ppg over 5+ games)
    played that game and scored under 70% of his average, returns
    (name, ppg, pts_last); otherwise None."""
    if len(prior) < STAR_MIN_GP + 1:
        return None
    totals, gp, names = {}, {}, {}
    for g in prior[:-1]:
        for pid, (pts, name) in (points.get(g["event_id"], team) or {}).items():
            totals[pid] = totals.get(pid, 0) + pts
            gp[pid] = gp.get(pid, 0) + 1
            names[pid] = name
    cands = [(totals[p] / gp[p], p) for p in gp if gp[p] >= STAR_MIN_GP]
    if not cands:
        return None
    ppg, star = max(cands)
    if ppg < STAR_MIN_PPG:
        return None
    last = points.get(prior[-1]["event_id"], team) or {}
    if star not in last:
        return None
    pts_last = last[star][0]
    if pts_last >= COLD_CUTOFF * ppg:
        return None
    return names[star], ppg, pts_last


def evaluate_game(session, points, by_team, q_cache, date_str, home, away):
    """Returns (pick_team, check_text) or None. Collects every rule that
    fires for either team; skips the game if they disagree on a side."""
    picks = []  # (pick_team, text)
    for team, is_home, opp in ((home, True, away), (away, False, home)):
        games = by_team.get(team, [])
        prior = [g for g in games if g["date"] < date_str]
        if not prior:
            continue
        last = prior[-1]
        team_w, team_l = season_record(games, date_str)
        opp_w, opp_l = season_record(by_team.get(opp, []), date_str)
        if not (team_w + team_l) or not (opp_w + opp_l):
            continue
        team_pct, opp_pct = team_w / (team_w + team_l), opp_w / (opp_w + opp_l)
        opp_weaker, opp_stronger = opp_pct < team_pct, opp_pct > team_pct

        if win_streak(prior) >= MIN_STREAK and is_home and opp_weaker:
            picks.append((opp, f"Fading {team}: {RULES['streak']}."))

        q = quarter_data(session, q_cache, last["date"])
        q_entry = next((v for v in q.values()
                        if team in v["teams"] and last["opp"] in v["teams"]), None)
        if q_entry:
            if q_entry.get("period") and q_entry["period"] > 4 and last["won"] and opp_stronger:
                picks.append((opp, f"Fading {team}: {RULES['ot_win']}."))
            if not last["won"] and is_home and opp_weaker and blown_lead(q_entry, team, last["opp"]) >= MIN_BLOWN_LEAD:
                picks.append((opp, f"Fading {team}: {RULES['blown_lead']}."))

        if is_home and opp_weaker and not last["won"]:
            to = points.turnovers(last["event_id"], team)
            if to is not None and to >= SLOPPY_LOSS_TO:
                picks.append((team, f"Backing {team}: lost last game with {to} turnovers ({SLOPPY_LOSS_TO}+), "
                                    f"now home vs. a worse-record opponent -- teams in this spot covered "
                                    f"62.1% ATS (n=29, small sample)."))

        if is_home:
            cold = cold_star(points, prior, team)
            if cold:
                name, ppg, pts_last = cold
                rate = ("covered 60.8% ATS when the opponent has a better record (n=273)" if opp_stronger
                        else "covered 57.9% ATS at home (n=537)")
                picks.append((team, f"Backing {team}: top scorer {name} ({ppg:.1f} ppg) was held to "
                                    f"{pts_last} last game, under 70% of his average, and {team} is home "
                                    f"-- teams in this spot {rate}."))
    sides = {p for p, _ in picks}
    if len(sides) != 1:
        return None
    return picks[0][0], " ".join(text for _, text in picks)


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
        before = (g.get("statsFavors"), g.get("statsCheck"))
        if result:
            if result != before:
                for k in ("statsCorrect", "statsReturn", "statsCover", "statsSpreadReturn"):
                    g.pop(k, None)
            g["statsFavors"], g["statsCheck"] = result
            print(f"  {date_str} {away} @ {home}: pick {result[0]} -- {result[1]}")
        else:
            for k in ("statsFavors", "statsCheck", "statsCorrect", "statsReturn", "statsCover", "statsSpreadReturn"):
                g.pop(k, None)
        if (g.get("statsFavors"), g.get("statsCheck")) != before:
            changed += 1
    if changed:
        store.write_doc("nba", date_str, doc)
    picks = sum(1 for g in doc.get("games", []) if g.get("statsFavors"))
    print(f"{date_str}: {picks} NBA Stats pick(s).")


def main():
    dates = sys.argv[1:] or [today_et_str()]
    session = espn.make_session()
    points = BoxCache(session)
    by_team = load_team_logs()
    q_cache = {}
    try:
        for date_str in dates:
            run_for_date(session, points, by_team, q_cache, date_str)
    finally:
        points.save()


if __name__ == "__main__":
    main()
