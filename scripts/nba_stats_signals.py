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
  three, now home on a back-to-back.
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
"""
import csv
import json
import os
import sys
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(__file__))
from lib import espn, manual, store  # noqa: E402
from lib.nba_stats_rules import RULE_BACKTEST, RULE_NAMES  # noqa: E402
from lib.dates import et_date_of_iso, today_et_str, weekday_et  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCORES_CSV = os.path.join(REPO_ROOT, "data", "raw", "master_nba_scores.csv")
POINTS_CACHE = os.path.join(REPO_ROOT, "data", "raw", "nba_player_points.json")
# Rest days (for the team the rule is about) on which each rule backtested
# at 62%+ ATS: "b2b" = played yesterday, "1" = one day off, "2+" = two or more.
ALLOWED_REST = {
    2: {"b2b", "1", "2+"}, 9: {"b2b"}, 14: {"b2b"}, 16: {"b2b"}, 17: {"b2b", "1", "2+"},
}
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
        events = []
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
        ast_p_by_team, tp_by_team = {}, {}
        for t in box.get("players", []):
            if not t.get("statistics"):
                continue
            cat = t["statistics"][0]
            labels = cat.get("labels", [])
            if "PTS" not in labels:
                continue
            i = labels.index("PTS")
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
                    # Player rebounds, summed -- the backtest's definition (the
                    # team total can also include uncredited "team rebounds").
                    reb += int(st[r]) if r is not None and r < len(st) else 0
                except (TypeError, ValueError, KeyError):
                    continue
            pts_by_team[t["team"]["displayName"]] = pts
            starters_by_team[t["team"]["displayName"]] = starters
            ast_p_by_team[t["team"]["displayName"]] = ast_p
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
                "starters": starters_by_team, "ast_p": ast_p_by_team, "tp": tp_by_team, "type": d.get("header", {}).get("season", {}).get("type")}

    def save(self):
        if self.dirty:
            with open(POINTS_CACHE, "w", encoding="utf-8") as f:
                json.dump(self.data, f, separators=(",", ":"))


def evaluate_game(session, points, by_team, q_cache, date_str, home, away):
    """Returns (pick_team, check_text) or None. Collects every rule that
    fires for either team; skips the game if they disagree on a side."""
    picks = []  # (pick_team, rule number, text)
    season0 = season_start(date_str)
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


def run_for_date(session, points, by_team, q_cache, date_str):
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
    for g in doc.get("games", []):
        away, home = g.get("away"), g.get("home")
        if not away or not home:
            continue
        if regular.get((away, home), True):
            result = evaluate_game(session, points, by_team, q_cache, date_str, home, away)
        else:
            result = None  # preseason / play-in / playoffs: not what the rules were tested on
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
        for date_str in dates:
            run_for_date(session, points, by_team, q_cache, date_str)
    finally:
        points.save()


if __name__ == "__main__":
    main()
