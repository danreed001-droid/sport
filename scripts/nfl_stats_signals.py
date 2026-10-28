#!/usr/bin/env python3
"""NFL Stats: a deterministic, backtested model patched onto each NFL slate
(data/nfl/<date>.json), alongside the Ledger, Second Opinion, Trend check and
Blowout check. No LLM research involved. Rules and rates are in
scripts/lib/nfl_stats_rules.py.

  Rule 1: back a home underdog of 7+ points (fade a road favorite of 7+).
  Rule 2: fade a team that won its last game as an underdog of 7+ points.
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
            return {"won": won, "spread": spread, "neutral": bool(comp.get("neutralSite")), "date": d, "opp": names[other]}
    return None


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
