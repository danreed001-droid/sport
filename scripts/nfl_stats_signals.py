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
from lib import espn, store  # noqa: E402
from lib.dates import et_date_of_iso, today_et_str, weekday_et  # noqa: E402
from lib.nfl_stats_rules import RULE_BACKTEST, RULE_NAMES  # noqa: E402

BIG_HOME_DOG = 7
UPSET_DOG = 7        # rule 2: won its last game as an underdog of this many points or more
TO_LOSS_MARGIN = 10  # rule 5: lost last game by this many or more...
TO_LOSS_TURNOVERS = 3  # ...with this many turnovers or more...
TO_LOSS_YARDS = 75   # ...and total yards within this many of the opponent's
BIG_PASS = 300       # rule 4: QB passing yards in last game's win
BIG_YARDS = 500      # rule 6: team total yards last game...
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


def _board(session, date_str):
    """ESPN's NFL scoreboard events for one date, cached for the run."""
    if date_str not in _BOARDS:
        try:
            _BOARDS[date_str] = espn.fetch_scoreboard(session, "football", "nfl", date_str.replace("-", ""))
        except Exception:
            _BOARDS[date_str] = []
    return _BOARDS[date_str]


def last_game(session, team, date_str):
    """The team's previous regular-season game before date_str: {won, spread
    (the team's own line, + = underdog), neutral, date, opp}, or None. The game
    is found on ESPN's scoreboard; its spread comes from our own slate for that
    date when there is one, else ESPN's core odds feed (closing line)."""
    d0 = date.fromisoformat(date_str)
    for k in range(1, LOOKBACK_DAYS + 1):
        d = (d0 - timedelta(days=k)).isoformat()
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
            pass
        _BOX[event_id] = out
    return _BOX[event_id]


def season_pct(session, team, date_str):
    """The team's regular-season win share before date_str (ties count as
    non-wins, as in the backtest), from ESPN's scoreboards; None before its
    first game."""
    d0 = date.fromisoformat(date_str)
    d = date(d0.year if d0.month >= 8 else d0.year - 1, 8, 25)
    w = n = 0
    while d < d0:
        for ev in _board(session, d.isoformat()):
            if (ev.get("season") or {}).get("type") != 2 or et_date_of_iso(ev["date"]) != d.isoformat():
                continue
            comp = ev["competitions"][0]
            if not comp.get("status", {}).get("type", {}).get("completed"):
                continue
            t = {c["team"]["displayName"]: float(c["score"]) for c in comp["competitors"]}
            if team in t:
                other = next(v for k, v in t.items() if k != team)
                n += 1
                w += t[team] > other
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
            pass
        _PASS[event_id] = out
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
            pass
        _RUSH[event_id] = out
    return _RUSH[event_id].get(team)


def espn_games(session, date_str):
    """{(away, home): {espnId, neutral, time}} for ESPN's NFL games on date_str (ET)."""
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
                                                      "time": kick.strftime("%I:%M %p").lstrip("0") + " ET"}
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
        last = last_game(session, team, date_str)
        line = None if spread is None else (spread if team == g["home"] else -spread)
        if last and line is not None and line > 0:
            rusher = top_rusher(session, last["eid"], team)
            if rusher and rusher[1] >= BIG_RUSH:
                picks.append((team, 3, f"Backing {team}: {rusher[0]} ran for {rusher[1]:g} yards last game ({BIG_RUSH}+), and {team} "
                                       f"is a {line:g}-point underdog now -- teams in this spot covered 66.7% ATS, 2017-2025 (n=39, small sample)."))
        if last and team == g["away"] and last["margin"] <= -TO_LOSS_MARGIN:
            box = team_box(session, last["eid"])
            me, them = box.get(team) or {}, box.get(last["opp"]) or {}
            if None not in (me.get("to"), me.get("yds"), them.get("yds")) and me["to"] >= TO_LOSS_TURNOVERS and abs(me["yds"] - them["yds"]) <= TO_LOSS_YARDS:
                picks.append((team, 5, f"Backing {team}: lost last game by {-last['margin']:g} with {me['to']:g} turnovers while gaining "
                                       f"{me['yds']:g} yards to {them['yds']:g} -- a turnover-driven loss, not a beating -- and is on the road now; "
                                       f"teams in this spot covered 65.3% ATS, 2017-2025 (n=75), no losing season."))
        if last and last["won"] and team == g["home"]:
            passer = top_passer(session, last["eid"], team)
            if passer and passer[1] >= BIG_PASS:
                mine, theirs = season_pct(session, team, date_str), season_pct(session, opp, date_str)
                if mine is not None and theirs is not None and theirs < mine:
                    picks.append((opp, 4, f"Fading {team}: {passer[0]} threw for {passer[1]:g} yards in last game's win ({BIG_PASS}+), and "
                                          f"{team} is home vs. a worse-record opponent -- teams in this spot were faded 60.3% of the time ATS, "
                                          f"2017-2025 (n=121), every season 55%+."))
        if last:
            me = team_box(session, last["eid"]).get(team) or {}
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
    return picks[0][0], [{"rule": n, "name": RULE_NAMES[n], "backtest": RULE_BACKTEST[n], "detail": t} for _, n, t in sorted(picks, key=lambda x: x[1])]


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
        neutral = (games.get((away, home)) or {}).get("neutral", False)
        result = evaluate(session, date_str, g, neutral)
        before = tuple(g.get(k) for k in FIELDS)
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
