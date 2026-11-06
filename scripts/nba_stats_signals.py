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

  Fades (pick the flagged team's opponent): 2 OT win, 9 late comeback,
  14 all 5 starters scored 10+ in a win, now on a back-to-back vs. a
  worse-record team, 17 won while allowing 130+, now at home.
  Backs (pick the flagged team): 16 lost to an opponent that shot 50%+ from
  three, now home on a back-to-back; 18 (on trial) home vs. a better-record
  team while the player who scored 30+ in its last game is out tonight
  (ESPN's injury report says "Out"; checked until tip-off, then frozen);
  19 (on trial) on the road on a back-to-back after losing at home to a
  worse-record team.
  Fades, on trial: 20-29 a team coming off a ROAD UPSET WIN (it had the worse
  record, the home team 5+ games played), sliced by home/road now, the next
  opponent's record, rest, the win's margin and whether it was a 7+ point
  underdog in that win (spread from data/raw/nba_lines.csv) -- see ROAD_UPSET.
  Backs, on trial: 33 home vs. a better-record team after a 30+ point win;
  34 after a 30+ point ROAD win where it wasn't a 7+ point favorite.
  (30-32 were tried and removed; numbers aren't reused.)
  35-40 (on trial), after a 20+ point loss -- see BLOWOUT_LOSS (38 is a fade).
  41-43 (on trial), both teams on a back-to-back: back the home team -- BOTH_B2B.
  44-48 (on trial), revenge: the team that lost the last meeting
  (lib/nba_revenge.py) -- 44-47 back it after an upset loss / a 10-19 loss,
  48 fades it as a home favorite after a home loss it was expected to take.
  Retired: rule 4 (never cleared 62%); rules 1, 3, 6, 7, 8, 10, 11, 12 and
  15, which went under 60% ATS when replayed on 2023-24 and 2024-25 --
  seasons none of the rules were found on (ESPN's core odds feed has their
  lines); and rules 5 and 13, which then went under 60% on 2018-19 and
  2019-20 too.

"Better/worse record" compares each team's season-to-date win% entering the
game. A game gets "statsFavors" (team name), "statsRules" (every rule that
fired, with its reason) and "statsCheck" (the same reasons as one string)
when rules fire and agree on a side; if they point at opposite sides, the
game gets no pick. Most days no game qualifies.

When data/nba/<date>.json doesn't exist yet (the live Routine writes it
later in the day), builds a bare slate from ESPN -- teams, tip times, lines
-- marked autoSlate, so NBA Stats never waits on the Routine; the Routine's
slate replaces it when it syncs in, keeping the NBA Stats fields. Per-player points and team turnovers/assists/steals/
free throws/rebounds/starters/player assists/threes for completed games are cached in data/raw/nba_player_points.json
so each run only fetches games it hasn't seen.

Usage: python scripts/nba_stats_signals.py [YYYY-MM-DD ...]   (default: today ET)
       python scripts/nba_stats_signals.py --backfill RULE [RULE ...] [-- YYYY-MM-DD ...]
         applies only those rules to finished past games (default: this season);
         see backfill().
"""
import csv
import json
import os
import sys
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(__file__))
from lib import action_network, espn, manual, store  # noqa: E402
from lib.nba_absence import big_scorers, injury_status, watch_entries  # noqa: E402
from lib.nba_revenge import revenge_facts  # noqa: E402
from score_slate import _same_team  # noqa: E402
from lib.nba_stats_rules import RULE_BACKTEST, RULE_NAMES  # noqa: E402
from lib.dates import et_date_of_iso, today_et_str, weekday_et  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCORES_CSV = os.path.join(REPO_ROOT, "data", "raw", "master_nba_scores.csv")
POINTS_CACHE = os.path.join(REPO_ROOT, "data", "raw", "nba_player_points.json")
LINES_CSV = os.path.join(REPO_ROOT, "data", "raw", "nba_lines.csv")

# Rules 20-29: fade a team after a road upset win. Each is a set of conditions
# on (now home?, next opponent stronger?, rested?, won by 1-9?, not a 7+ point
# underdog in that win?); None = either. Backtested 2022-23 to 2025-26.
ROAD_UPSET = {
    20: {"home": True, "stronger": True, "rested": True, "close": True, "notbig": True},
    21: {"home": True, "stronger": True, "close": True, "notbig": True},
    22: {"home": False, "stronger": False, "rested": True, "close": True},
    23: {"home": True, "stronger": False, "close": False},
    24: {"home": True, "rested": True, "close": True, "notbig": True},
    25: {"stronger": False, "close": False, "notbig": True},
    26: {"home": False, "stronger": False, "rested": True},
    27: {"stronger": False, "rested": True, "close": False, "notbig": True},
    28: {"home": True, "close": True, "notbig": True},
    29: {"home": False, "stronger": False, "close": True},
}
# Rules 35-40: after a 20+ point loss -> (rule, back the team? (else fade), conditions on
# now home?, next opponent stronger?, back-to-back?, that loss on the road?,
# lost by 30+?, not a 7+ point underdog in it?). Backtested 2022-23 to 2025-26.
BLOWOUT_LOSS = [
    (35, True, {"b2b": True, "road_loss": True, "notbigdog": True}),
    (36, True, {"home": False, "road_loss": False, "big": True}),
    (37, True, {"home": False, "b2b": False, "road_loss": False, "big": True}),
    (38, False, {"home": True, "stronger": False, "b2b": False, "road_loss": True, "big": False}),
    (39, True, {"home": False, "stronger": True, "road_loss": True, "big": False, "notbigdog": True}),
    (40, True, {"home": True, "stronger": False, "b2b": False, "road_loss": False, "big": False}),
]
# Rules 41-43: both teams on a back-to-back -> back the home team, when:
BOTH_B2B = {
    41: {"home_fav": True, "road_better": True},
    42: {"home_fav": True, "home_was_home": False, "road_won": False},
    43: {"home_fav": True, "home_was_home": False, "big_spread": True},
}


def both_b2b_facts(by_team, season0, date_str, home, away, home_spread):
    """Facts for rules 41-43 when both teams played yesterday (regular season,
    this season) and the records differ, else None. home_spread: tonight's
    home spread (negative = home favored); a pick'em or no line -> None."""
    if home_spread is None or home_spread == 0:
        return None
    prev = date.fromordinal(date.fromisoformat(date_str).toordinal() - 1).isoformat()
    lg = {}
    for t in (home, away):
        gs = [g for g in by_team.get(t, []) if season0 <= g["date"] < date_str]
        if not gs or gs[-1]["date"] != prev:
            return None
        lg[t] = gs
    rec = {t: season_record(lg[t], date_str) for t in (home, away)}
    if not all(w + l for w, l in rec.values()):
        return None
    hp, ap = (rec[t][0] / (rec[t][0] + rec[t][1]) for t in (home, away))
    if hp == ap:
        return None
    return {"home_fav": home_spread < 0, "road_better": ap > hp, "home_was_home": lg[home][-1]["is_home"],
            "road_won": lg[away][-1]["won"], "big_spread": abs(home_spread) >= 5}


_HOME_SPREAD = None


def home_spread_of(event_id):
    """The home team's closing spread for a finished game (data/raw/nba_lines.csv), or None."""
    global _HOME_SPREAD
    if _HOME_SPREAD is None:
        _HOME_SPREAD = {}
        if os.path.exists(LINES_CSV):
            with open(LINES_CSV, encoding="utf-8") as f:
                for r in csv.DictReader(f):
                    try:
                        _HOME_SPREAD[r["game_id"]] = float(r["spread_close"])
                    except (TypeError, ValueError):
                        pass
    return _HOME_SPREAD.get(str(event_id))
# Rest days (for the team the rule is about) on which each rule backtested
# at 62%+ ATS: "b2b" = played yesterday, "1" = one day off, "2+" = two or more.
ALLOWED_REST = {
    2: {"b2b", "1", "2+"}, 9: {"b2b"}, 14: {"b2b"}, 16: {"b2b"}, 17: {"b2b", "1", "2+"},
    18: {"b2b", "1", "2+"},
    19: {"b2b"},
    **{n: ({"1", "2+"} if c.get("rested") else {"b2b", "1", "2+"}) for n, c in {
        20: {"rested": True}, 21: {}, 22: {"rested": True}, 23: {}, 24: {"rested": True},
        25: {}, 26: {"rested": True}, 27: {"rested": True}, 28: {}, 29: {},
        33: {}, 34: {}, 35: {}, 36: {}, 37: {"rested": True}, 38: {"rested": True},
        39: {}, 40: {"rested": True}, 41: {}, 42: {}, 43: {}, 44: {}, 45: {}, 46: {}, 47: {}, 48: {}}.items()},
    49: {"b2b"},
    50: {"b2b", "1", "2+"},
}
STATS_LINE_KEYS = ("homeSpread", "awaySpread", "homeSpreadOdds", "awaySpreadOdds", "homeMoneyline", "awayMoneyline")
LATE_COMEBACK = 5
STARTER_PTS = 10      # rule 14: points every starter scored
HOT_OPP_THREES = 0.5  # rule 16: opponent's 3-point % last game (on HOT_OPP_3PA+ attempts)
HOT_OPP_3PA = 25
SHOOTOUT_ALLOWED = 130  # rule 17: points allowed in last game's win

RULES = {
    "ot_win": "won last game in OT, now facing a better-record opponent -- "
              "faded 63.6% of the time ATS (n=77)",
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


def season_start(date_str):
    """First day of the NBA season date_str falls in (Aug 1 of its start
    year). The scores archive keeps growing across seasons, so every rule
    looks only at games on or after this day: last season's games never
    count toward a record or a "last game"."""
    d = date.fromisoformat(date_str)
    return f"{d.year if d.month >= 8 else d.year - 1}-08-01"


def regular_season_games(session, date_str):
    """{(away, home): True/False} -- whether each of ESPN's games on date_str
    is a regular-season game (season type 2). The rules were only backtested
    on the regular season, so preseason, play-in and playoff games get no
    pick. Empty when ESPN can't be reached (then every game is evaluated)."""
    try:
        events = espn.fetch_scoreboard(session, "basketball", "nba", date_str.replace("-", ""))
    except Exception:
        return {}
    out = {}
    for ev in events:
        teams = {c["homeAway"]: c["team"]["displayName"] for c in ev["competitions"][0]["competitors"]}
        out[(teams.get("away"), teams.get("home"))] = (ev.get("season") or {}).get("type") == 2
    return out


def tonight_games(session, date_str):
    """{(away, home): {"state", "out", "status"}} for ESPN's games on date_str;
    "out" is a function team -> set of player ids ESPN's injury report lists
    as Out, "status" team -> {player_id: (name, status)} (both fetched lazily,
    only for games that haven't started; None if unknown)."""
    try:
        events = espn.fetch_scoreboard(session, "basketball", "nba", date_str.replace("-", ""))
    except Exception:
        return {}
    out = {}
    for ev in events:
        comp = ev["competitions"][0]
        teams = {c["homeAway"]: c["team"]["displayName"] for c in comp["competitors"]}
        cache = {}
        def status_fn(team, eid=ev["id"], cache=cache):
            if "inj" not in cache:
                cache["inj"] = injury_status(session, eid)
            inj = cache["inj"]
            if inj is None:
                return None
            merged = {}
            for k, v in inj.items():
                if _same_team(team, k):
                    merged.update(v)
            return merged
        def out_fn(team, status_fn=status_fn):
            st = status_fn(team)
            return None if st is None else {pid for pid, v in st.items() if v[1] == "out"}
        out[(teams.get("away"), teams.get("home"))] = {"state": (comp.get("status") or {}).get("type", {}).get("state"),
                                                       "out": out_fn, "status": status_fn, "id": ev["id"]}
    return out


def season_record(games, before_date):
    w = l = 0
    for g in games:
        if g["date"] >= before_date:
            continue
        w += 1 if g["won"] else 0
        l += 0 if g["won"] else 1
    return w, l



def quarter_data(session, cache, date_str):
    """{event_id: {period, teams: {team_name: [q1,q2,q3,q4,...]}}}, cached
    per calendar date."""
    if date_str in cache:
        return cache[date_str]
    out = {}
    try:
        events = espn.fetch_scoreboard(session, "basketball", "nba", date_str.replace("-", ""))
    except Exception:
        FAILS[0] += 1
        return {}  # not cached: retried at the next use
    for ev in events:
        comp = ev["competitions"][0]
        teams = {c["team"]["displayName"]: [p.get("value") for p in (c.get("linescores") or [])]
                 for c in comp["competitors"]}
        out[ev["id"]] = {"period": comp.get("status", {}).get("period"), "teams": teams}
    cache[date_str] = out
    return out



def trailed_after_three(q_entry, team, opp):
    """How many points `team` trailed `opp` by after 3 quarters (negative or
    zero if it led or was tied), or None without three quarters of data."""
    t_q, o_q = q_entry["teams"].get(team), q_entry["teams"].get(opp)
    if not t_q or not o_q or len(t_q) < 3 or len(o_q) < 3 or None in t_q[:3] + o_q[:3]:
        return None
    return sum(o_q[:3]) - sum(t_q[:3])




# ESPN lookups that failed this run (box scores, scoreboards). A game whose
# evaluation hit one keeps the pick it already had: a missing number would
# otherwise drop a rule -- and with it a pick and its grade.
FAILS = [0]


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
        if not isinstance(e, dict) or "ast_p" not in e:  # missing, failed, or an older format
            e = self.data[event_id] = self._fetch(event_id)
            self.dirty = True
        if e is None:
            FAILS[0] += 1
        return e or {}

    def get(self, event_id, team):
        return self._entry(event_id).get("pts", {}).get(team)

    def turnovers(self, event_id, team):
        return self._entry(event_id).get("to", {}).get(team)

    def assists(self, event_id, team):
        return self._entry(event_id).get("ast", {}).get(team)

    def steals(self, event_id, team):
        return self._entry(event_id).get("stl", {}).get(team)

    def rebounds(self, event_id, team):
        return self._entry(event_id).get("reb", {}).get(team)

    def free_throws_made(self, event_id, team):
        return self._entry(event_id).get("ftm", {}).get(team)

    def player_assists(self, event_id, team):
        return self._entry(event_id).get("ast_p", {}).get(team)

    def threes(self, event_id, team):
        """(made, attempted) threes for `team`, or None."""
        v = self._entry(event_id).get("tp", {}).get(team)
        return tuple(v) if v else None

    def starters(self, event_id, team):
        return self._entry(event_id).get("starters", {}).get(team)

    def rotation(self, event_id, team):
        """How many of `team`'s players played 10+ minutes (rule 49). Entries
        cached before this was added are fetched again once, when needed."""
        e = self._entry(event_id)
        if e and "rot" not in e:
            new = self._fetch(event_id)
            if new:
                e = self.data[event_id] = new
                self.dirty = True
        return (e or {}).get("rot", {}).get(team)

    def is_regular_season(self, event_id):
        return self._entry(event_id).get("type") == 2

    def season_type(self, event_id):
        """ESPN's season type (2 = regular season), None if unknown."""
        return self._entry(event_id).get("type")

    def _fetch(self, event_id):
        try:
            d = self.session.get(
                f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event={event_id}",
                timeout=15,
            ).json()
        except Exception:
            return None
        box = d.get("boxscore", {})
        pts_by_team, to_by_team, ast_by_team, stl_by_team, ftm_by_team, reb_by_team, starters_by_team = {}, {}, {}, {}, {}, {}, {}
        ast_p_by_team, tp_by_team, rot_by_team = {}, {}, {}
        for t in box.get("players", []):
            if not t.get("statistics"):
                continue
            cat = t["statistics"][0]
            labels = cat.get("labels", [])
            if "PTS" not in labels:
                continue
            i = labels.index("PTS")
            mi = labels.index("MIN") if "MIN" in labels else None
            rot = 0
            r = labels.index("REB") if "REB" in labels else None
            a = labels.index("AST") if "AST" in labels else None
            pts, reb, starters, ast_p = {}, 0, [], {}
            for ath in cat.get("athletes", []):
                st = ath.get("stats") or []
                if ath.get("didNotPlay") or len(st) <= i:
                    continue
                try:
                    pts[ath["athlete"]["id"]] = [int(st[i]), ath["athlete"].get("displayName")]
                    if ath.get("starter"):
                        starters.append(ath["athlete"]["id"])
                    if a is not None and a < len(st):
                        ast_p[ath["athlete"]["id"]] = int(st[a])
                    if mi is not None and mi < len(st):
                        try:
                            rot += float(str(st[mi]).split(":")[0]) >= 10
                        except ValueError:
                            pass
                    # Player rebounds, summed -- the backtest's definition (the
                    # team total can also include uncredited "team rebounds").
                    reb += int(st[r]) if r is not None and r < len(st) else 0
                except (TypeError, ValueError, KeyError):
                    continue
            pts_by_team[t["team"]["displayName"]] = pts
            starters_by_team[t["team"]["displayName"]] = starters
            ast_p_by_team[t["team"]["displayName"]] = ast_p
            if mi is not None:
                rot_by_team[t["team"]["displayName"]] = rot
            if r is not None:
                reb_by_team[t["team"]["displayName"]] = reb
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
            try:
                tp_by_team[name] = [int(v) for v in str(stats["threePointFieldGoalsMade-threePointFieldGoalsAttempted"]).split("-")]
            except (KeyError, TypeError, ValueError):
                pass
        if not pts_by_team:
            return None
        return {"pts": pts_by_team, "to": to_by_team, "ast": ast_by_team, "stl": stl_by_team, "ftm": ftm_by_team, "reb": reb_by_team,
                "starters": starters_by_team, "ast_p": ast_p_by_team, "tp": tp_by_team, "rot": rot_by_team, "type": d.get("header", {}).get("season", {}).get("type")}

    def save(self):
        if self.dirty:
            with open(POINTS_CACHE, "w", encoding="utf-8") as f:
                json.dump(self.data, f, separators=(",", ":"))


def evaluate_game(session, points, by_team, q_cache, date_str, home, away, tonight=None, only_rules=None, home_spread=None,
                  market=None):
    """Returns (pick_team, check_text) or None. Collects every rule that
    fires for either team; skips the game if they disagree on a side.
    tonight: {"state": ESPN game state, "out": team -> set of player ids out
    (None if unknown), "prior": the game's current statsRules} for rule 18."""
    picks = []  # (pick_team, rule number, text)
    season0 = season_start(date_str)
    # Slates sometimes spell a team differently from ESPN's archive ("LA
    # Lakers" vs "Los Angeles Lakers"): look teams up by the archive's name,
    # and hand the pick back under the slate's.
    def resolve(name):
        return name if name in by_team else next((k for k in by_team if _same_team(name, k)), name)
    H, A = resolve(home), resolve(away)
    slate_name = {H: home, A: away}
    home, away = H, A
    for team, is_home, opp in ((home, True, away), (away, False, home)):
        games = [g for g in by_team.get(team, []) if g["date"] >= season0]
        prior = [g for g in games if g["date"] < date_str]
        if not prior:
            continue
        last = prior[-1]
        start = len(picks)
        team_w, team_l = season_record(games, date_str)
        opp_w, opp_l = season_record([g for g in by_team.get(opp, []) if g["date"] >= season0], date_str)
        if not (team_w + team_l) or not (opp_w + opp_l):
            continue
        team_pct, opp_pct = team_w / (team_w + team_l), opp_w / (opp_w + opp_l)
        opp_weaker, opp_stronger = opp_pct < team_pct, opp_pct > team_pct

        q = quarter_data(session, q_cache, last["date"])
        q_entry = next((v for v in q.values()
                        if team in v["teams"] and last["opp"] in v["teams"]), None)
        # Hand-entered data for that game (lib/manual.py) wins over ESPN's.
        m_game = manual.team_game("nba", last["date"], team) or {}
        m_box, m_opp = manual.team_box("nba", last["date"], team), manual.team_box("nba", last["date"], last["opp"])
        if m_box.get("quarters") and m_opp.get("quarters"):
            q_entry = {"period": max(len(m_box["quarters"]), len(m_opp["quarters"])),
                       "teams": {team: m_box["quarters"], last["opp"]: m_opp["quarters"]}}
        if m_game.get("ot"):
            q_entry = dict(q_entry or {"teams": {}}, period=max((q_entry or {}).get("period") or 0, 5))
        if q_entry:
            if q_entry.get("period") and q_entry["period"] > 4 and last["won"] and opp_stronger:
                picks.append((opp, 2, f"Fading {team}: {RULES['ot_win']}."))
            back_to_back = (date.fromisoformat(date_str) - date.fromisoformat(last["date"])).days == 1
            trail = trailed_after_three(q_entry, team, last["opp"]) if last["won"] and back_to_back else None
            if trail is not None and trail >= LATE_COMEBACK:
                picks.append((opp, 9, f"Fading {team}: came back to win last night after trailing by {trail:g} "
                                   f"through 3 quarters ({LATE_COMEBACK}+), now on the second night of a back-to-back "
                                   f"-- teams in this spot were faded 68.1% of the time ATS (n=91)."))

        if last["won"] and is_home and last["opp_score"] >= SHOOTOUT_ALLOWED:
            picks.append((opp, 17, f"Fading {team}: won last game but allowed {last['opp_score']:g} points ({SHOOTOUT_ALLOWED}+), "
                                f"now at home -- teams in this spot were faded 65.5% of the time ATS (n=58)."))

        if not last["won"] and is_home:
            three = ((m_opp["threesMade"], m_opp["threesAttempted"]) if "threesMade" in m_opp and "threesAttempted" in m_opp
                     else points.threes(last["event_id"], last["opp"]))
            if three and three[1] >= HOT_OPP_3PA and three[0] / three[1] >= HOT_OPP_THREES:
                picks.append((team, 16, f"Backing {team}: lost last game while its opponent shot {three[0]}-of-{three[1]} "
                                     f"({three[0] / three[1]:.0%}) from three, now home on a back-to-back -- teams in this "
                                     f"spot covered 68.5% ATS (n=54)."))

        if last["won"] and opp_weaker:
            if m_box.get("starterPoints"):
                box = {i: [p, f"starter {i + 1}"] for i, p in enumerate(m_box["starterPoints"])}
                five = list(box)
            else:
                box, five = points.get(last["event_id"], team) or {}, points.starters(last["event_id"], team) or []
            if len(five) == 5 and all(box.get(pid, [0])[0] >= STARTER_PTS for pid in five):
                who = ", ".join(f"{box[pid][1]} {box[pid][0]}" for pid in five)
                picks.append((opp, 14, f"Fading {team}: all 5 starters scored {STARTER_PTS}+ in last game's win ({who}), "
                                    f"now on a back-to-back vs. a worse-record opponent -- teams in this spot were faded "
                                    f"62.3% of the time ATS (n=122)."))

        if is_home and opp_stronger and tonight is not None:
            big = big_scorers(points, last["event_id"], team, 30)
            if big and tonight.get("state") == "pre":
                out = tonight["out"](team)
                hit = [b for b in big if out is not None and b[0] in out]
                if hit:
                    who = ", ".join(f"{n} ({p} pts)" for _, p, n in hit)
                    picks.append((team, 18, f"Backing {team}: {who} scored 30+ in its last game and is out tonight; "
                                         f"now home vs. a better-record team -- teams in this spot covered 61.7% ATS "
                                         f"(29-18, 2022-23 to 2025-26)."))
                elif "watch" in tonight and 18 in RULE_NAMES:
                    tonight["watch"] += watch_entries(big, tonight["status"](team), 18,
                                                      f"NBA Stats rule 18 would back {slate_name.get(team, team)}")
            elif big:  # started or final: keep whatever was decided before tip-off
                prev = next((r for r in tonight.get("prior") or [] if r.get("rule") == 18), None)
                if prev:
                    picks.append((team, 18, prev.get("detail", "")))

        if not last["is_home"] and last["won"] and team_pct != opp_pct:
            tw, tl = season_record(games, last["date"])
            ow, ol = season_record([g for g in by_team.get(last["opp"], []) if g["date"] >= season0], last["date"])
            if tw + tl and ow + ol >= 5 and tw / (tw + tl) < ow / (ow + ol):
                hs = home_spread_of(last["event_id"])
                my_spread = -hs if hs is not None else None  # it was the road team
                margin = last["team_score"] - last["opp_score"]
                facts = {"home": is_home, "stronger": opp_stronger,
                         "rested": (date.fromisoformat(date_str) - date.fromisoformat(last["date"])).days > 1,
                         "close": margin <= 9, "notbig": my_spread is None or my_spread < 7}
                where = "home" if is_home else "on the road"
                dog = f"as a {my_spread:+g} underdog" if my_spread is not None and my_spread > 0 else (
                      f"as a {my_spread:+g} favorite" if my_spread is not None else "")
                for n, cond in ROAD_UPSET.items():
                    if all(facts[k] == v for k, v in cond.items()):
                        picks.append((opp, n, f"Fading {team}: won at better-record {last['opp']} "
                                              f"{last['team_score']:g}-{last['opp_score']:g} {dog} last game; now {where} vs. "
                                              f"{'a better' if opp_stronger else 'a worse'}-record team"
                                              f"{', rested' if facts['rested'] else ', on a back-to-back'} -- {RULE_BACKTEST.get(n, '')}."))

        lost_by = last["opp_score"] - last["team_score"]
        if lost_by >= 20 and team_pct != opp_pct:  # rules 35-40: after a 20+ point loss
            hs = home_spread_of(last["event_id"])
            my_spread = (hs if last["is_home"] else -hs) if hs is not None else None
            f = {"home": is_home, "stronger": opp_stronger,
                 "b2b": (date.fromisoformat(date_str) - date.fromisoformat(last["date"])).days == 1,
                 "road_loss": not last["is_home"], "big": lost_by >= 30,
                 "notbigdog": my_spread is None or my_spread < 7}
            where = "on the road" if f["road_loss"] else "at home"
            lost = (f"lost by {lost_by:g} {where} last game ({last['team_score']:g}-{last['opp_score']:g} vs {last['opp']})"
                    f"{f' as a {my_spread:+g}' if my_spread is not None else ''}")
            for n, back, cond in BLOWOUT_LOSS:
                if all(f[k] == v for k, v in cond.items()):
                    pick = team if back else opp
                    verb = "Backing" if back else "Fading"
                    picks.append((pick, n, f"{verb} {team}: {lost}; now {'home' if is_home else 'on the road'} vs. "
                                           f"{'a better' if opp_stronger else 'a worse'}-record team"
                                           f"{', on a back-to-back' if f['b2b'] else ', rested'} -- {RULE_BACKTEST.get(n, '')}."))

        big_margin = last["team_score"] - last["opp_score"]
        if big_margin >= 30 and team_pct != opp_pct:  # rules 33-34: back a team after a 30+ point win
            hs = home_spread_of(last["event_id"])
            my_spread = (hs if last["is_home"] else -hs) if hs is not None else None
            score = f"{last['team_score']:g}-{last['opp_score']:g}"
            if is_home and opp_stronger:
                picks.append((team, 33, f"Backing {team}: won by {big_margin:g} last game ({score} vs {last['opp']}), now home "
                                     f"vs. a better-record team -- {RULE_BACKTEST.get(33, '')}."))
            if not last["is_home"] and (my_spread is None or my_spread > -7):
                picks.append((team, 34, f"Backing {team}: won by {big_margin:g} on the road last game ({score} at {last['opp']})"
                                     f"{f' as a {my_spread:+g}' if my_spread is not None else ''} -- {RULE_BACKTEST.get(34, '')}."))

        if not is_home and last["is_home"] and not last["won"] and team_pct != opp_pct:  # as backtested: equal records excluded
            tw, tl = season_record(games, last["date"])
            ow, ol = season_record([g for g in by_team.get(last["opp"], []) if g["date"] >= season0], last["date"])
            if tw + tl >= 5 and ow + ol and tw / (tw + tl) > ow / (ow + ol):
                picks.append((team, 19, f"Backing {team}: lost at home to worse-record {last['opp']} "
                                     f"({last['team_score']:g}-{last['opp_score']:g}) last night, now on the road on a "
                                     f"back-to-back -- teams in this spot covered 65.9% ATS (29-15, 2022-23 to 2025-26)."))

        # Rule 49: fade a 7+ point underdog on a back-to-back whose last game
        # used 8 or fewer players for 10+ minutes (as backtested: 6+ games
        # played this season by both teams).
        my_spread = None if home_spread is None else (home_spread if is_home else -home_spread)
        opp_prior = [g for g in by_team.get(opp, []) if season0 <= g["date"] < date_str]
        if (my_spread is not None and my_spread >= 7 and len(prior) >= 6 and len(opp_prior) >= 6
                and (date.fromisoformat(date_str) - date.fromisoformat(last["date"])).days == 1):
            rot = points.rotation(last["event_id"], team)
            if rot is not None and rot <= 8:
                picks.append((opp, 49, f"Fading {team}: only {rot} players played 10+ minutes in last night's game "
                                    f"(vs {last['opp']}), now a {my_spread:+g} underdog on the second night of a back-to-back "
                                    f"-- {RULE_BACKTEST.get(49, '')}."))

        # Keep only the rules whose backtest cleared 62% for this team's rest
        # (days off since its last game).
        gap = (date.fromisoformat(date_str) - date.fromisoformat(last["date"])).days - 1
        rest = "b2b" if gap <= 0 else ("1" if gap == 1 else "2+")
        picks[start:] = [pk for pk in picks[start:] if rest in ALLOWED_REST[pk[1]]]
    # Rules 41-43: both teams on the second night of a back-to-back; back the home team.
    bb = both_b2b_facts(by_team, season0, date_str, home, away, home_spread)
    if bb:
        for n, cond in BOTH_B2B.items():
            if all(bb[k] == v for k, v in cond.items()):
                picks.append((home, n, f"Backing {home}: both teams played last night ({home} "
                                       f"{'at home' if bb['home_was_home'] else 'on the road'}, {away} "
                                       f"{'won' if bb['road_won'] else 'lost'}); {home} favored by {-home_spread:g}"
                                       f"{', and ' + away + ' has the better record' if bb['road_better'] else ''} -- {RULE_BACKTEST.get(n, '')}."))

    # Rules 44-48: revenge -- the team that lost the last meeting (lib/nba_revenge.py).
    rv = revenge_facts(home, away, date_str, home_spread, _same_team)
    if rv:
        rt = home if rv["rev"] == "home" else away
        ot = away if rt == home else home
        mid = 10 <= rv["margin"] <= 19
        fire = {44: mid and rv["was_fav"] and rv["home_now"] and rv["worse_now"],
                45: mid and rv["was_fav"] and rv["worse_now"] and rv["streak"] >= 2,
                46: rv["was_fav"] and rv["fav_now"] and rv["worse_now"] and rv["streak"] >= 2,
                47: mid and rv["recent"] == "last season" and rv["worse_now"] and rv["streak"] == 1,
                48: rv["lost_at_home"] and not rv["was_fav"] and rv["home_now"] and rv["fav_now"]}
        why = (f"{rt} lost the last meeting by {rv['margin']:g} ({rv['last_score']}, {rv['last_date']})"
               f"{' as the favorite' if rv['was_fav'] else ' as the underdog'}"
               f"{', its ' + str(rv['streak']) + ' straight loss to them' if rv['streak'] >= 2 else ''}; tonight "
               f"{'home' if rv['home_now'] else 'on the road'}, {'favored' if rv['fav_now'] else 'the underdog'}, "
               f"with the {'worse' if rv['worse_now'] else 'better'} record")
        for n, ok in fire.items():
            if ok:
                pick = ot if n == 48 else rt
                picks.append((pick, n, f"{'Fading' if n == 48 else 'Backing'} {rt}: {why} -- {RULE_BACKTEST.get(n, '')}."))

    # Rule 50: 60%+ of spread bets on a 7+ point underdog, yet the line moved 1+
    # (but under 5) point further toward the favorite since it opened -> back the favorite.
    # market: this game's Action Network entry (lib/action_network.py). Checked
    # until tip-off, then frozen: a game that has started keeps what it had.
    if tonight is not None and tonight.get("state") not in (None, "pre"):
        prev = next((r for r in tonight.get("prior") or [] if r.get("rule") == 50), None)
        if prev:
            faded = home if str(prev.get("detail", "")).startswith(f"Fading {home}:") else away
            picks.append((away if faded == home else home, 50, prev.get("detail", "")))
    elif market and market.get("tix_home") is not None and market.get("spread_home") is not None \
            and market.get("open_home") is not None:
        for dog, is_home in ((home, True), (away, False)):
            sp = market["spread_home"] if is_home else -market["spread_home"]
            op = market["open_home"] if is_home else -market["open_home"]
            tix = market["tix_home"] if is_home else 100 - market["tix_home"]
            if sp >= 7 and tix >= 60 and 1 <= sp - op < 5:  # 5+ point moves: injury news or a bad opener
                fav = away if is_home else home
                picks.append((fav, 50, f"Fading {dog}: {tix:g}% of spread bets are on {dog} at {sp:+g}, but the line has "
                                       f"moved from {op:+g} toward {fav} since it opened (Action Network consensus) -- "
                                       f"{RULE_BACKTEST.get(50, '')}."))

    picks = [p for p in picks if p[1] in RULE_NAMES]  # retired rules (lib/nba_stats_rules.RETIRED) never pick
    if only_rules is not None:  # backfill: just these rules, as if no other rule existed
        picks = [p for p in picks if p[1] in only_rules]
    sides = {p for p, _, _ in picks}
    if len(sides) != 1:
        return None
    rules = [{"rule": n, "name": RULE_NAMES[n], "backtest": RULE_BACKTEST.get(n, ''), "detail": text}
             for _, n, text in sorted(picks, key=lambda x: x[1])]
    return slate_name.get(picks[0][0], picks[0][0]), rules


def _num(v):
    try:
        return float(str(v).replace("+", ""))
    except (TypeError, ValueError):
        return None


def espn_lines(session, event_id):
    """Current spread (home side), spread odds and moneylines from ESPN's
    pickcenter, or {} when the game has no line posted yet."""
    try:
        d = session.get(f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event={event_id}",
                        timeout=20).json()
    except Exception:
        return {}
    pc = (d.get("pickcenter") or [{}])[0]
    home, away = pc.get("homeTeamOdds") or {}, pc.get("awayTeamOdds") or {}
    close = ((pc.get("pointSpread") or {}).get("home") or {}).get("close") or {}
    spread = _num(close.get("line"))
    if spread is None:
        spread = _num(pc.get("spread"))
    out = {}
    if spread is not None:
        out.update(homeSpread=spread, awaySpread=-spread)
    for key, side in (("homeSpreadOdds", home), ("awaySpreadOdds", away)):
        if _num(side.get("spreadOdds")) is not None:
            out[key] = _num(side.get("spreadOdds"))
    for key, side in (("homeMoneyline", home), ("awayMoneyline", away)):
        if _num(side.get("moneyLine")) is not None:
            out[key] = _num(side.get("moneyLine"))
    return out


def build_espn_slate(session, date_str):
    """A bare NBA slate (teams, tip time, lines) straight from ESPN, for days
    the Claude routine hasn't written one yet, so NBA Stats never waits on it.
    Marked autoSlate: the routine's own slate replaces it when it syncs in
    (sync_ledger.py keeps the NBA Stats fields). None if ESPN lists no games."""
    try:
        events = espn.fetch_scoreboard(session, "basketball", "nba", date_str.replace("-", ""))
    except Exception:
        return None
    games = []
    for ev in events:
        if et_date_of_iso(ev["date"]) != date_str:
            continue
        comp = ev["competitions"][0]
        teams = {c["homeAway"]: c["team"]["displayName"] for c in comp["competitors"]}
        tip = datetime.fromisoformat(ev["date"].replace("Z", "+00:00")).astimezone(ZoneInfo("America/New_York"))
        games.append({"espnId": ev["id"], "away": teams.get("away"), "home": teams.get("home"),
                      "time": tip.strftime("%I:%M %p").lstrip("0") + " ET", **espn_lines(session, ev["id"])})
    if not games:
        return None
    return {"date": date_str, "weekday": weekday_et(date_str), "sport": "nba", "scored": False, "autoSlate": True,
            "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "games": games}


def run_for_date(session, points, by_team, q_cache, date_str, setup_failed=False):
    doc = store.read_doc("nba", date_str)
    if doc is None:
        doc = build_espn_slate(session, date_str)
        if doc is None:
            print(f"{date_str}: no NBA games on ESPN, nothing to patch.")
            return
        store.write_doc("nba", date_str, doc)
        print(f"{date_str}: no slate from the routine yet -- built one from ESPN ({len(doc['games'])} games).")
    elif doc.get("autoSlate") and not doc.get("scored"):
        # Fill in lines ESPN hadn't posted yet when the slate was built.
        filled = 0
        for g in doc.get("games", []):
            if g.get("homeSpread") is None and g.get("espnId"):
                lines = espn_lines(session, g["espnId"])
                g.update(lines)
                filled += bool(lines)
        if filled:
            store.write_doc("nba", date_str, doc)
    changed = 0
    regular = regular_season_games(session, date_str)
    tonight = tonight_games(session, date_str)
    mk = action_network.market(date_str)
    for g in doc.get("games", []):
        away, home = g.get("away"), g.get("home")
        if not away or not home:
            continue
        fails = FAILS[0]
        watch_before, spread_before = g.get("statsWatch"), (g.get("statsSpread"), g.get("statsLine"))
        if regular.get((away, home), True):
            ev = next((v for (a, h), v in tonight.items() if _same_team(away, a) and _same_team(home, h)), None)
            ctx = None if ev is None else {"state": ev["state"], "out": ev["out"], "status": ev["status"],
                                           "prior": g.get("statsRules") or [], "watch": []}
            # Rules that read tonight's spread (43-49) use the market's current line
            # (ESPN pickcenter / DraftKings), refreshed until tip-off and then kept
            # as statsSpread: a slate's line can be stale.
            # statsLine keeps the whole live line (spread, its odds, moneylines): NBA
            # Stats picks are graded at it (lib/picks.stats_view), not the slate's.
            if ctx and ctx["state"] == "pre" and ev.get("id"):
                live = espn.pickcenter_lines(session, "basketball", "nba", ev["id"])
                if live.get("homeSpread") is not None:
                    g["statsSpread"] = live["homeSpread"]
                    g["statsLine"] = {k: live[k] for k in STATS_LINE_KEYS if live.get(k) is not None}
            result = evaluate_game(session, points, by_team, q_cache, date_str, home, away, ctx,
                                   home_spread=g.get("statsSpread", g.get("homeSpread")),
                                   market=action_network.lookup(mk, away, home, _same_team))
            if ctx and ctx["state"] == "pre":  # injury watch: refreshed until tip-off, then kept as it was
                if ctx["watch"]:
                    g["statsWatch"] = ctx["watch"]
                else:
                    g.pop("statsWatch", None)
        else:
            result = None  # preseason / play-in / playoffs: not what the rules were tested on
        before = (g.get("statsFavors"), g.get("statsCheck"), g.get("statsRules"))
        if (FAILS[0] > fails or setup_failed) and before[0] and (result is None or result[0] != before[0] or result[1] != before[2]):
            print(f"  {date_str} {away} @ {home}: an ESPN lookup failed -- keeping the existing pick ({before[0]}); next run re-checks")
            continue
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
        if (g.get("statsFavors"), g.get("statsCheck"), g.get("statsRules")) != before or g.get("statsWatch") != watch_before \
                or (g.get("statsSpread"), g.get("statsLine")) != spread_before:
            changed += 1
    if changed:
        store.write_doc("nba", date_str, doc)
    picks = sum(1 for g in doc.get("games", []) if g.get("statsFavors"))
    print(f"{date_str}: {picks} NBA Stats pick(s).")


def backfill(session, points, by_team, q_cache, rules, dates):
    """Apply only `rules` to finished games on past slates (this season by
    default), from the games before each one -- what the rules would have
    picked live. A game with no NBA Stats pick gets one; a game whose pick
    already agrees gets the rule added; a game picked the other way is left
    alone (live, the disagreement would have meant no pick). Backfilled rules
    carry "backfill": true, and a pick that came only from backfill gets
    statsBackfill: true. Graded by score_slate.py like any other pick."""
    today = today_et_str()
    added = 0
    for date_str in dates:
        if date_str >= today:
            continue
        doc = store.read_doc("nba", date_str)
        if doc is None:
            continue
        changed = False
        for g in doc.get("games", []):
            if not isinstance(g.get("awayScore"), (int, float)):
                continue
            mk = action_network.lookup(action_network.market(date_str), g["away"], g["home"], _same_team) if 50 in rules else None
            r = evaluate_game(session, points, by_team, q_cache, date_str, g["home"], g["away"], None, set(rules),
                              home_spread=g.get("homeSpread"), market=mk)
            if not r:
                continue
            pick, new = r
            have = {x.get("rule") for x in g.get("statsRules") or []}
            new = [dict(x, backfill=True) for x in new if x["rule"] not in have]
            if not new:
                continue
            if g.get("statsFavors") and g["statsFavors"] != pick:
                print(f"  {date_str} {g['away']} @ {g['home']}: rules {[x['rule'] for x in new]} pick {pick}, "
                      f"but the existing pick is {g['statsFavors']} -- left alone")
                continue
            if not g.get("statsFavors"):
                g["statsFavors"], g["statsRules"], g["statsBackfill"] = pick, [], True
            g["statsRules"] = sorted(g["statsRules"] + new, key=lambda x: x["rule"])
            g["statsCheck"] = " ".join(f"Rule {x['rule']}: {x['detail']}" for x in g["statsRules"])
            for k in ("statsCorrect", "statsReturn", "statsCover", "statsSpreadReturn"):
                g.pop(k, None)  # regraded by score_slate.py
            changed = True
            added += 1
            print(f"  {date_str} {g['away']} @ {g['home']}: {pick} -- backfilled rules {[x['rule'] for x in new]}")
        if changed:
            store.write_doc("nba", date_str, doc)
    print(f"backfilled {added} game(s) with rules {sorted(rules)}.")


def main():
    backfill_rules = None
    args = sys.argv[1:]
    if args[:1] == ["--backfill"]:
        # python scripts/nba_stats_signals.py --backfill 38 39 [-- YYYY-MM-DD ...]
        rest = args[1:]
        dates = rest[rest.index("--") + 1:] if "--" in rest else []
        backfill_rules = [int(x) for x in (rest[:rest.index("--")] if "--" in rest else rest)]
        args = dates
    dates = args or [today_et_str()]
    session = espn.make_session()
    points = BoxCache(session)
    # The backtests are regular-season only, and the scores archive also
    # holds preseason games -- drop those so streaks, records and "last game"
    # mean what they meant in the backtest.
    def regular(g, team):
        if str(g["event_id"]).startswith("manual-"):
            return True  # entered by hand (ESPN never listed it)
        t = points.season_type(g["event_id"])
        if t is None:  # ESPN couldn't say: a hand-entered box score vouches for it
            return manual.team_game("nba", g["date"], team) is not None
        return t == 2
    by_team = {team: [g for g in games if regular(g, team)] for team, games in load_team_logs().items()}
    q_cache = {}
    try:
        # A failed lookup while sorting regular-season games could drop a
        # team's last game, so it protects every existing pick this run.
        setup_failed = FAILS[0] > 0
        if backfill_rules is not None:
            if not args:
                s0 = season_start(today_et_str())
                dates = [d for d, _ in store.list_docs("nba") if d >= s0]
            backfill(session, points, by_team, q_cache, backfill_rules, dates)
            return
        for date_str in dates:
            run_for_date(session, points, by_team, q_cache, date_str, setup_failed)
    finally:
        points.save()


if __name__ == "__main__":
    main()
