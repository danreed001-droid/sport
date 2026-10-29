#!/usr/bin/env python3
"""NFL Stats: a deterministic, backtested model patched onto each NFL slate
(data/nfl/<date>.json), alongside the Ledger, Second Opinion, Trend check and
Blowout check. No LLM research involved. Rules and rates are in
scripts/lib/nfl_stats_rules.py.

  Rule 1: back a home underdog of 7+ points (fade a road favorite of 7+).
  Rule 2: fade a team that won its last game as an underdog of 7+ points.
  Rule 3: back an underdog whose top rusher ran for 150+ yards last game.
  Rule 4: fade a home team vs. a worse-record opponent after its QB threw
  for 300+ yards in a win.
  Rule 5: back a road team after a 10+ point loss with 3+ turnovers in which
  it gained about as many yards as its opponent (within 75).
  Rule 6: fade a team that gained 500+ yards, 300+ of them passing, last game.
  Rule 9: fade a team after a game with both a 100-yard rusher and a
  350-yard passer (only the pair works: either one alone is a coin flip).
  Rule 10: bet on a team's ATS record catching up with its record -- back a
  winning team that has covered under 40%, fade a losing team that has
  covered 60%+ (5+ games with a line). When the two records agree, there's
  no edge; it's their disagreement that reverts.
  A pick two or more rules agree on is "stacked" (69.4% ATS in the replay).
  Neutral-site games (London, Germany, etc.) are left out, as in the backtests;
  if the rules point at opposite sides, the game gets no pick.

The rule reads the slate's own homeSpread, so the line it checks is the line
the pick is graded at. A game gets "nflStatsFavors" (team name),
"nflStatsRules" (every rule that fired, with its reason) and "nflStatsCheck"
(the same reasons as one string).

When data/nfl/<date>.json doesn't exist yet, builds a bare slate from ESPN
(teams, kickoff time, current lines) marked autoSlate, so NFL Stats never
waits on the live Routine; the Routine's slate replaces it when it syncs in,
keeping the NFL Stats fields (scripts/sync_ledger.py).

Usage: python scripts/nfl_stats_signals.py [YYYY-MM-DD ...]   (default: today ET)
"""
import os
import sys
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(__file__))
from lib import espn, manual, store  # noqa: E402
from lib.dates import et_date_of_iso, today_et_str, weekday_et  # noqa: E402
from lib.nfl_stats_rules import RULE_BACKTEST, RULE_NAMES  # noqa: E402

BIG_HOME_DOG = 7
UPSET_DOG = 7        # rule 2: won its last game as an underdog of this many points or more
TO_LOSS_MARGIN = 10  # rule 5: lost last game by this many or more...
TO_LOSS_TURNOVERS = 3  # ...with this many turnovers or more...
TO_LOSS_YARDS = 75   # ...and total yards within this many of the opponent's
BIG_PASS = 300       # rule 4: QB passing yards in last game's win
BIG_YARDS = 500      # rule 6: team total yards last game...
BOTH_RUSH, BOTH_PASS = 100, 350  # rule 9: top rusher and top passer, same game
ATS_MIN_GAMES = 5             # rule 10: games with a line needed...
ATS_LOW, ATS_HIGH = 0.4, 0.6  # ...a winning team covering under 40%, a losing team covering 60%+
BIG_YARDS_PASS = 300  # ...with this many net passing yards or more
BIG_RUSH = 150       # rule 3: top rusher's yards in the team's last game
LOOKBACK_DAYS = 16   # how far back to look for a team's last regular-season game
FIELDS = ("nflStatsFavors", "nflStatsCheck", "nflStatsRules")
GRADE_FIELDS = ("nflStatsCorrect", "nflStatsReturn", "nflStatsCover", "nflStatsSpreadReturn")


def _num(v):
    try:
        return float(str(v).replace("+", ""))
    except (TypeError, ValueError):
        return None


_BOARDS = {}
# ESPN lookups that failed this run (scoreboards, box scores, odds). A game
# whose evaluation hit one keeps the pick it already had: a missing number
# would otherwise drop a rule -- and with it a pick and its grade.
FAILS = [0]


def _board(session, date_str):
    """ESPN's NFL scoreboard events for one date, cached for the run."""
    if date_str not in _BOARDS:
        try:
            _BOARDS[date_str] = espn.fetch_scoreboard(session, "football", "nfl", date_str.replace("-", ""))
        except Exception:
            _BOARDS[date_str] = None
    if _BOARDS[date_str] is None:
        FAILS[0] += 1
        return []
    return _BOARDS[date_str]


def last_game(session, team, date_str):
    """The team's previous regular-season game before date_str: {won, spread
    (the team's own line, + = underdog), neutral, date, opp}, or None. The game
    is found on ESPN's scoreboard; its spread comes from our own slate for that
    date when there is one, else ESPN's core odds feed (closing line)."""
    d0 = date.fromisoformat(date_str)
    for k in range(1, LOOKBACK_DAYS + 1):
        d = (d0 - timedelta(days=k)).isoformat()
        m = manual.team_game("nfl", d, team)
        if manual.has_final(m):  # entered by hand (lib/manual.py): wins over ESPN
            side = "home" if m["home"] == team else "away"
            mine, theirs = (m["homeScore"], m["awayScore"]) if side == "home" else (m["awayScore"], m["homeScore"])
            doc_g = next((g for g in (store.read_doc("nfl", d) or {}).get("games", [])
                          if g.get("home") == m["home"] and g.get("away") == m["away"]), {})
            home_spread = _num(doc_g.get("homeSpread", m.get("homeSpread")))
            spread = None if home_spread is None else (home_spread if side == "home" else -home_spread)
            return {"won": mine > theirs, "spread": spread, "neutral": False, "date": d,
                    "opp": m["away"] if side == "home" else m["home"], "eid": f"manual:{d}", "margin": mine - theirs}
        for ev in _board(session, d):
            if (ev.get("season") or {}).get("type") != 2 or et_date_of_iso(ev["date"]) != d:
                continue
            comp = ev["competitions"][0]
            if not comp.get("status", {}).get("type", {}).get("completed"):
                continue
            t = {c["homeAway"]: c for c in comp["competitors"]}
            names = {s_: t[s_]["team"]["displayName"] for s_ in ("home", "away")}
            if team not in names.values():
                continue
            side = "home" if names["home"] == team else "away"
            other = "away" if side == "home" else "home"
            won = float(t[side]["score"]) > float(t[other]["score"])
            margin = float(t[side]["score"]) - float(t[other]["score"])
            home_spread = None
            doc = store.read_doc("nfl", d)
            for g in (doc or {}).get("games", []):
                if g.get("home") == names["home"] and g.get("away") == names["away"]:
                    home_spread = _num(g.get("homeSpread"))
            if home_spread is None:
                try:
                    items = session.get(f"https://sports.core.api.espn.com/v2/sports/football/leagues/nfl/events/{ev['id']}/competitions/{ev['id']}/odds",
                                        timeout=20).json().get("items", [])
                    home_spread = _num(next((i.get("spread") for i in items if i.get("spread") is not None), None))
                except Exception:
                    FAILS[0] += 1
                    home_spread = None
            spread = None if home_spread is None else (home_spread if side == "home" else -home_spread)
            return {"won": won, "spread": spread, "neutral": bool(comp.get("neutralSite")), "date": d, "opp": names[other], "eid": ev["id"], "margin": margin}
    return None


_RUSH = {}
_PASS = {}
_BOX = {}


def team_box(session, event_id):
    """{team name: {"to": turnovers, "yds": total yards, "pass": net passing yards}} from an ESPN game's box score."""
    if event_id not in _BOX:
        out = {}
        try:
            d = session.get(f"https://site.api.espn.com/apis/site/v2/sports/football/nfl/summary?event={event_id}", timeout=20).json()
            for t in d.get("boxscore", {}).get("teams", []):
                st = {x.get("name"): x.get("displayValue") for x in t.get("statistics", [])}
                out[t["team"]["displayName"]] = {"to": _num(st.get("turnovers")), "yds": _num(st.get("totalYards")),
                                                 "pass": _num(st.get("netPassingYards"))}
        except Exception:
            out = None
        _BOX[event_id] = out
    if _BOX[event_id] is None:
        FAILS[0] += 1
        return {}
    return _BOX[event_id]


_ODDS = {}


def _home_spread(session, d, home, away, event_id):
    """A game's closing home spread: our own slate for that date (which
    carries any hand-entered line), else ESPN's core odds feed; None if
    neither has one."""
    for g in (store.read_doc("nfl", d) or {}).get("games", []):
        if g.get("home") == home and g.get("away") == away and _num(g.get("homeSpread")) is not None:
            return _num(g.get("homeSpread"))
    if event_id not in _ODDS:
        try:
            items = session.get(f"https://sports.core.api.espn.com/v2/sports/football/leagues/nfl/events/{event_id}/competitions/{event_id}/odds",
                                timeout=20).json().get("items", [])
            _ODDS[event_id] = _num(next((i.get("spread") for i in items if i.get("spread") is not None), None))
        except Exception:
            FAILS[0] += 1
            return None  # not cached: retried next time
    return _ODDS[event_id]


def season_ats(session, team, date_str):
    """The team's regular-season record before date_str, straight up and
    against the spread: {w, n, cov, miss} (ties are non-wins, pushes and
    games without a line are left out of the ATS count, as in the backtest).
    Games come from ESPN's scoreboards since Aug 25, plus hand-entered finals."""
    d0 = date.fromisoformat(date_str)
    d = date(d0.year if d0.month >= 8 else d0.year - 1, 8, 25)
    out = {"w": 0, "n": 0, "cov": 0, "miss": 0}

    def add(mine, theirs, my_spread):
        out["n"] += 1
        out["w"] += mine > theirs
        if my_spread is not None and mine - theirs + my_spread != 0:
            out["cov" if mine - theirs + my_spread > 0 else "miss"] += 1

    while d < d0:
        ds, listed = d.isoformat(), set()
        m = manual.team_game("nfl", ds, team)
        for ev in _board(session, ds):
            if (ev.get("season") or {}).get("type") != 2 or et_date_of_iso(ev["date"]) != ds:
                continue
            comp = ev["competitions"][0]
            if not comp.get("status", {}).get("type", {}).get("completed"):
                continue
            t = {c["homeAway"]: c for c in comp["competitors"]}
            names = {s_: t[s_]["team"]["displayName"] for s_ in ("home", "away")}
            listed.add(frozenset(names.values()))
            if team not in names.values():
                continue
            score = {s_: float(t[s_]["score"]) for s_ in ("home", "away")}
            if manual.has_final(m) and frozenset((m["away"], m["home"])) == frozenset(names.values()):
                score = {"home": m["homeScore"], "away": m["awayScore"]}  # hand-entered score wins
            side = "home" if names["home"] == team else "away"
            other = "away" if side == "home" else "home"
            hs = _home_spread(session, ds, names["home"], names["away"], ev["id"])
            add(score[side], score[other], None if hs is None else (hs if side == "home" else -hs))
        if manual.has_final(m) and frozenset((m["away"], m["home"])) not in listed:
            side = "home" if m["home"] == team else "away"
            hs = _num(m.get("homeSpread"))
            mine, theirs = (m["homeScore"], m["awayScore"]) if side == "home" else (m["awayScore"], m["homeScore"])
            add(mine, theirs, None if hs is None else (hs if side == "home" else -hs))
        d += timedelta(days=1)
    return out


def season_pct(session, team, date_str):
    """The team's regular-season win share before date_str (ties count as
    non-wins, as in the backtest), from ESPN's scoreboards; None before its
    first game."""
    d0 = date.fromisoformat(date_str)
    d = date(d0.year if d0.month >= 8 else d0.year - 1, 8, 25)
    w = n = 0
    while d < d0:
        listed = set()
        for ev in _board(session, d.isoformat()):
            if (ev.get("season") or {}).get("type") != 2 or et_date_of_iso(ev["date"]) != d.isoformat():
                continue
            comp = ev["competitions"][0]
            if not comp.get("status", {}).get("type", {}).get("completed"):
                continue
            t = {c["team"]["displayName"]: float(c["score"]) for c in comp["competitors"]}
            listed.add(frozenset(t))
            m = manual.team_game("nfl", d.isoformat(), team) if team in t else None
            if manual.has_final(m) and frozenset((m["away"], m["home"])) == frozenset(t):
                t = {m["away"]: m["awayScore"], m["home"]: m["homeScore"]}  # hand-entered score wins
            if team in t:
                other = next(v for k, v in t.items() if k != team)
                n += 1
                w += t[team] > other
        m = manual.team_game("nfl", d.isoformat(), team)
        if manual.has_final(m) and frozenset((m["away"], m["home"])) not in listed:
            mine, theirs = (m["homeScore"], m["awayScore"]) if m["home"] == team else (m["awayScore"], m["homeScore"])
            n += 1
            w += mine > theirs
        d += timedelta(days=1)
    return w / n if n else None


def top_passer(session, event_id, team):
    """(name, passing yards) for the team's QB with the most attempts in an ESPN game, or None."""
    if event_id not in _PASS:
        out = {}
        try:
            d = session.get(f"https://site.api.espn.com/apis/site/v2/sports/football/nfl/summary?event={event_id}", timeout=20).json()
            for t in d.get("boxscore", {}).get("players", []):
                for cat in t.get("statistics", []):
                    if cat.get("name") != "passing":
                        continue
                    labels = cat.get("labels", [])
                    ia = labels.index("C/ATT") if "C/ATT" in labels else None
                    iy = labels.index("YDS") if "YDS" in labels else None
                    best = None
                    for a in cat.get("athletes", []):
                        st = a.get("stats") or []
                        att = _num(str(st[ia]).split("/")[-1]) if ia is not None and ia < len(st) else None
                        yds = _num(st[iy]) if iy is not None and iy < len(st) else None
                        if att is not None and yds is not None and (best is None or att > best[2]):
                            best = (a["athlete"].get("displayName"), yds, att)
                    if best:
                        out[t["team"]["displayName"]] = best[:2]
        except Exception:
            out = None
        _PASS[event_id] = out
    if _PASS[event_id] is None:
        FAILS[0] += 1
        return None
    return _PASS[event_id].get(team)


def top_rusher(session, event_id, team):
    """(name, yards) for the team's leading rusher in an ESPN game, or None."""
    if event_id not in _RUSH:
        out = {}
        try:
            d = session.get(f"https://site.api.espn.com/apis/site/v2/sports/football/nfl/summary?event={event_id}", timeout=20).json()
            for t in d.get("boxscore", {}).get("players", []):
                for cat in t.get("statistics", []):
                    if cat.get("name") != "rushing":
                        continue
                    labels = cat.get("labels", [])
                    i = labels.index("YDS") if "YDS" in labels else None
                    best = None
                    for a in cat.get("athletes", []):
                        st = a.get("stats") or []
                        yds = _num(st[i]) if i is not None and i < len(st) else None
                        if yds is not None and (best is None or yds > best[1]):
                            best = (a["athlete"].get("displayName"), yds)
                    if best:
                        out[t["team"]["displayName"]] = best
        except Exception:
            out = None
        _RUSH[event_id] = out
    if _RUSH[event_id] is None:
        FAILS[0] += 1
        return None
    return _RUSH[event_id].get(team)


def espn_games(session, date_str):
    """{(away, home): {espnId, neutral, time, regular}} for ESPN's NFL games on date_str (ET)."""
    try:
        events = espn.fetch_scoreboard(session, "football", "nfl", date_str.replace("-", ""))
    except Exception:
        return {}
    out = {}
    for ev in events:
        if et_date_of_iso(ev["date"]) != date_str:
            continue
        comp = ev["competitions"][0]
        teams = {c["homeAway"]: c["team"]["displayName"] for c in comp["competitors"]}
        kick = datetime.fromisoformat(ev["date"].replace("Z", "+00:00")).astimezone(ZoneInfo("America/New_York"))
        out[(teams.get("away"), teams.get("home"))] = {"espnId": ev["id"], "neutral": bool(comp.get("neutralSite")),
                                                      "time": kick.strftime("%I:%M %p").lstrip("0") + " ET",
                                                      "regular": (ev.get("season") or {}).get("type") == 2}
    return out


def espn_lines(session, event_id):
    """Current spread (home side), spread odds and moneylines from ESPN's
    pickcenter, or {} when no line is posted yet."""
    try:
        d = session.get(f"https://site.api.espn.com/apis/site/v2/sports/football/nfl/summary?event={event_id}",
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
    for key, side, field in (("homeSpreadOdds", home, "spreadOdds"), ("awaySpreadOdds", away, "spreadOdds"),
                             ("homeMoneyline", home, "moneyLine"), ("awayMoneyline", away, "moneyLine")):
        if _num(side.get(field)) is not None:
            out[key] = _num(side.get(field))
    return out


def build_espn_slate(session, date_str, games):
    if not games:
        return None
    rows = [{"espnId": v["espnId"], "away": away, "home": home, "time": v["time"], **espn_lines(session, v["espnId"])}
            for (away, home), v in games.items()]
    return {"date": date_str, "weekday": weekday_et(date_str), "sport": "nfl", "scored": False, "autoSlate": True,
            "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "games": rows}


def _rusher(session, last, team):
    mb = manual.team_box("nfl", last["date"], team)
    if mb.get("topRusherYards") is not None:
        return (mb.get("topRusherName") or "Their top rusher", mb["topRusherYards"])
    return None if str(last["eid"]).startswith("manual") else top_rusher(session, last["eid"], team)


def _passer(session, last, team):
    mb = manual.team_box("nfl", last["date"], team)
    if mb.get("topPasserYards") is not None:
        return (mb.get("topPasserName") or "Their QB", mb["topPasserYards"])
    return None if str(last["eid"]).startswith("manual") else top_passer(session, last["eid"], team)


def _box(session, last, team):
    """{to, yds, pass} for `team` in its last game: ESPN's, with any
    hand-entered numbers on top."""
    espn_box = {} if str(last["eid"]).startswith("manual") else (team_box(session, last["eid"]).get(team) or {})
    mb = manual.team_box("nfl", last["date"], team)
    out = dict(espn_box)
    for k, mk in (("to", "turnovers"), ("yds", "totalYards"), ("pass", "passYards")):
        if mb.get(mk) is not None:
            out[k] = mb[mk]
    return out


def evaluate(session, date_str, g, neutral):
    """(pick team, [rule dicts]) or None. Collects every rule that fires;
    skips the game if they point at opposite sides."""
    if neutral:
        return None
    picks = []
    spread = _num(g.get("homeSpread"))
    if spread is not None and spread >= BIG_HOME_DOG:
        picks.append((g["home"], 1, f"Backing {g['home']}: a {spread:g}-point home underdog ({BIG_HOME_DOG}+) -- home dogs this big "
                                    f"covered 64.7% ATS from 2020-2025 (n=116), 70.3% on the held-out 2024-25 seasons."))
    for team, opp in ((g["home"], g["away"]), (g["away"], g["home"])):
        rec = season_ats(session, team, date_str)
        graded = rec["cov"] + rec["miss"]
        if graded >= ATS_MIN_GAMES and rec["n"]:
            pct, win = rec["cov"] / graded, rec["w"] / rec["n"]
            su = f"{rec['w']}-{rec['n'] - rec['w']}"
            ats = f"{rec['cov']}-{rec['miss']}"
            if pct < ATS_LOW and win > 0.5:
                picks.append((team, 10, f"Backing {team}: {su} straight up but only {ats} against the spread ({pct:.0%}) -- a winning team "
                                        f"that hasn't been covering covered 66.7% ATS in its next game, 2017-2025 (n=78), no losing season."))
            elif pct >= ATS_HIGH and win < 0.5:
                picks.append((opp, 10, f"Fading {team}: {su} straight up but {ats} against the spread ({pct:.0%}) -- a losing team that "
                                       f"keeps covering was faded 61.9% of the time ATS in its next game, 2017-2025 (n=147), no losing season."))
        last = last_game(session, team, date_str)
        line = None if spread is None else (spread if team == g["home"] else -spread)
        if last and line is not None and line > 0:
            rusher = _rusher(session, last, team)
            if rusher and rusher[1] >= BIG_RUSH:
                picks.append((team, 3, f"Backing {team}: {rusher[0]} ran for {rusher[1]:g} yards last game ({BIG_RUSH}+), and {team} "
                                       f"is a {line:g}-point underdog now -- teams in this spot covered 66.7% ATS, 2017-2025 (n=39, small sample)."))
        if last and team == g["away"] and last["margin"] <= -TO_LOSS_MARGIN:
            me, them = _box(session, last, team), _box(session, last, last["opp"])
            if None not in (me.get("to"), me.get("yds"), them.get("yds")) and me["to"] >= TO_LOSS_TURNOVERS and abs(me["yds"] - them["yds"]) <= TO_LOSS_YARDS:
                picks.append((team, 5, f"Backing {team}: lost last game by {-last['margin']:g} with {me['to']:g} turnovers while gaining "
                                       f"{me['yds']:g} yards to {them['yds']:g} -- a turnover-driven loss, not a beating -- and is on the road now; "
                                       f"teams in this spot covered 65.3% ATS, 2017-2025 (n=75), no losing season."))
        if last and last["won"] and team == g["home"]:
            passer = _passer(session, last, team)
            if passer and passer[1] >= BIG_PASS:
                mine, theirs = season_pct(session, team, date_str), season_pct(session, opp, date_str)
                if mine is not None and theirs is not None and theirs < mine:
                    picks.append((opp, 4, f"Fading {team}: {passer[0]} threw for {passer[1]:g} yards in last game's win ({BIG_PASS}+), and "
                                          f"{team} is home vs. a worse-record opponent -- teams in this spot were faded 60.3% of the time ATS, "
                                          f"2017-2025 (n=121), every season 55%+."))
        if last:
            rusher, passer = _rusher(session, last, team), _passer(session, last, team)
            if rusher and passer and rusher[1] >= BOTH_RUSH and passer[1] >= BOTH_PASS:
                picks.append((opp, 9, f"Fading {team}: {rusher[0]} ran for {rusher[1]:g} and {passer[0]} threw for {passer[1]:g} "
                                      f"in its last game ({BOTH_RUSH}+ rushing and {BOTH_PASS}+ passing, same game) -- teams in this "
                                      f"spot were faded 83.3% of the time ATS next game, 2017-2025 (n=24, small sample), no losing season."))
            me = _box(session, last, team)
            if None not in (me.get("yds"), me.get("pass")) and me["yds"] >= BIG_YARDS and me["pass"] >= BIG_YARDS_PASS:
                picks.append((opp, 6, f"Fading {team}: gained {me['yds']:g} yards last game, {me['pass']:g} of them passing "
                                      f"({BIG_YARDS}+ with {BIG_YARDS_PASS}+ through the air) -- teams in this spot were faded 60.0% of the time "
                                      f"ATS next game, 2017-2025 (n=115)."))
        if last and last["won"] and not last["neutral"] and last["spread"] is not None and last["spread"] >= UPSET_DOG:
            picks.append((opp, 2, f"Fading {team}: won last game ({last['date']}, vs. {last['opp']}) as a {last['spread']:g}-point "
                                  f"underdog ({UPSET_DOG}+) -- teams coming off an upset that big were faded 60.0% of the time ATS "
                                  f"in their next game, 2017-2025 (n=100)."))
    if len({p for p, _, _ in picks}) != 1:
        return None
    # One entry per rule: Rule 10 can fire from both teams' records at once
    # (backing one, fading the other) -- that's still one rule, not a stack.
    merged = {}
    for _, n, t in sorted(picks, key=lambda x: x[1]):
        merged[n] = merged[n] + " Also: " + t if n in merged else t
    return picks[0][0], [{"rule": n, "name": RULE_NAMES[n], "backtest": RULE_BACKTEST[n], "detail": t} for n, t in merged.items()]


def run_for_date(session, date_str):
    games = espn_games(session, date_str)
    doc = store.read_doc("nfl", date_str)
    if doc is None:
        doc = build_espn_slate(session, date_str, games)
        if doc is None:
            print(f"{date_str}: no NFL games, nothing to patch.")
            return
        store.write_doc("nfl", date_str, doc)
        print(f"{date_str}: no slate from the routine yet -- built one from ESPN ({len(doc['games'])} games).")
    changed = False
    if doc.get("autoSlate") and not doc.get("scored"):
        for g in doc.get("games", []):
            if g.get("homeSpread") is None and g.get("espnId"):
                lines = espn_lines(session, g["espnId"])
                if lines:
                    g.update(lines)
                    changed = True
    for g in doc.get("games", []):
        away, home = g.get("away"), g.get("home")
        if not away or not home:
            continue
        info = games.get((away, home)) or {}
        # The rules were only backtested on regular-season games: preseason
        # and playoff games get no pick (unknown -- ESPN down -- is evaluated).
        fails = FAILS[0]
        result = evaluate(session, date_str, g, info.get("neutral", False)) if info.get("regular", True) else None
        before = tuple(g.get(k) for k in FIELDS)
        if FAILS[0] > fails and before[0] and (result is None or result[0] != before[0] or result[1] != before[2]):
            print(f"  {date_str} {away} @ {home}: an ESPN lookup failed -- keeping the existing pick ({before[0]}); next run re-checks")
            continue
        if result:
            if result[0] != before[0]:
                for k in GRADE_FIELDS:
                    g.pop(k, None)
            g["nflStatsFavors"], g["nflStatsRules"] = result
            g["nflStatsCheck"] = " ".join(f"Rule {r['rule']}: {r['detail']}" for r in result[1])
            print(f"  {date_str} {away} @ {home}: pick {result[0]}")
        else:
            for k in FIELDS + GRADE_FIELDS:
                g.pop(k, None)
        if tuple(g.get(k) for k in FIELDS) != before:
            changed = True
    # A slate already graded before its NFL Stats pick existed (or older than
    # the scores archive reaches) gets that pick graded from its own final score.
    if doc.get("scored"):
        from score_slate import TWO_WAY_SIGNAL_FIELDS, grade_named  # noqa: E402
        fields = next(f for f in TWO_WAY_SIGNAL_FIELDS if f[0] == "nflStatsFavors")
        for g in doc.get("games", []):
            if g.get("nflStatsFavors") and "nflStatsCorrect" not in g and _num(g.get("awayScore")) is not None and _num(g.get("homeScore")) is not None:
                graded = grade_named(g, g["nflStatsFavors"], _num(g["awayScore"]), _num(g["homeScore"]))
                for key, out in zip(("correct", "pickReturn", "pickCover", "pickSpreadReturn"), fields[1:]):
                    g[out] = graded[key]
                changed = True
    if changed:
        store.write_doc("nfl", date_str, doc)
    print(f"{date_str}: {sum(1 for g in doc.get('games', []) if g.get('nflStatsFavors'))} NFL Stats pick(s).")


def main():
    session = espn.make_session()
    for date_str in sys.argv[1:] or [today_et_str()]:
        run_for_date(session, date_str)


if __name__ == "__main__":
    main()
