#!/usr/bin/env python3
"""NFL storylines: context for the pick sheet, never a pick.

Each storyline is a situation a sportswriter could tell a story about (a team
"on a short week after an overtime war", a "trap game" between two division
games, a West Coast team "body clock" kickoff at 1 PM ET). 52 of them were
tested on 2026-11-13 on every regular-season game from 2010 to 2025, with the
2020 empty-stadium season reported separately and left out of the numbers
below (nflverse games file: closing spread, rest, kickoff time, roof, weather,
starting QBs and head coaches; ESPN scoreboards for the quarter scores;
nflverse team stats for turnovers). The story's bet was graded against the
closing spread, pushes left out; neutral-site games (London, Germany, Mexico,
...) were left out, and a story that pointed at both teams in one game was
skipped for that game. Only one of the 52 was at p<0.05 (about 2.6 would be
expected by chance), so as a group they're no better than luck. These are
the ones where history leaned 53%+ one way on 50+ games, or p<0.05 -- which
side that is can be the opposite of what the story says (the West Coast team
at a 1 PM ET kickoff covered 56.3%; the story says fade it, so it's marked
`against`). None is a model: they're shown on the game card with their record
and aren't graded or counted anywhere.

Selected but not computed here: "The wind is the great equalizer" (back an
underdog in 15+ mph wind; the underdog covered only 45.5%, 136-163). The
backtest used the game's measured wind, and there's no allowed live forecast
source for it (ESPN's game weather has temperature but no wind;
api.weather.gov's robots.txt disallows everything; Open-Meteo's API isn't
reachable from the runner's network), so it's left out.

"QB vs his old team" reads QB_STARTS, starts by franchise through the 2025
season taken from the nflverse games file, so it only runs for the 2026
season (QB_SEASON); refresh the table each offseason to keep it. Tonight's
starter is the slate's homeQB/awayQB (the Routine's research), else the
passer with the most attempts in the team's last game (ESPN box score).

Writes `storylines` onto each game of today's NFL slate (or the dates given)
that hasn't started: [{key, name, team, says, fact, record, pct, leans,
leanPct, against, unit}], where `team` is who the story is about, `says` is
the story's bet ("back"/"fade" that team), `record`/`pct` are that bet's
history ATS (`unit`), and `leans`/`leanPct` the side history favors. Once a
game has a score the entry is kept as it was before kickoff. Each team's
games come from ESPN's weekly regular-season scoreboards (quarter scores,
overtime, neutral site, next week's opponent), with hand-entered finals
(data/manual/nfl) on top. If ESPN can't be reached, nothing is changed.

Usage: python scripts/nfl_storylines.py [--dry-run] [--include-final] [YYYY-MM-DD ...]
  --dry-run        print what fires, write nothing
  --include-final  (with --dry-run only) also evaluate games that have a score
"""
import math
import os
import re
import sys
from datetime import date, datetime
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib import espn, manual, store  # noqa: E402
from lib.dates import today_et_str  # noqa: E402
from score_slate import _same_team  # noqa: E402

ET = ZoneInfo("America/New_York")

# key: (name, story's bet, wins-losses for that bet 2010-2025 without 2020, games where it applies)
STORIES = {
    "ot_short": ("Short week after an overtime war", "fade", (36, 24),
                 "its last game went to overtime and this one comes 6 or fewer days later"),
    "bye_rust": ("Bye-week rust", "fade", (64, 54), "a home favorite of 3+ coming off a bye (13+ days rest)"),
    "west_early": ("Body clock: West Coast team at 1 PM ET", "fade", (69, 89),
                   "a Pacific-time team on the road in the Eastern time zone, kicking off before 2 PM ET"),
    "west_night": ("West Coast night owls", "back", (40, 30),
                   "a Pacific-time team vs an Eastern-time team kicking off at 8 PM ET or later, either venue"),
    "cross_country": ("Cross-country trip", "fade", (173, 200), "a road team traveling 2,000+ miles"),
    "frozen_tundra": ("December at a cold-weather stadium", "back", (102, 88),
                      "a cold-weather outdoor home team in December or January vs a dome or warm-weather visitor"),
    "sandwich": ("Trap game", "fade", (114, 100),
                 "favored by 3+ vs a non-division opponent, between two division games"),
    "qb_former": ("QB vs his old team", "back", (41, 50),
                  "its starting QB made 8+ starts for tonight's opponent in earlier seasons"),
    "escape": ("Escape artists", "fade", (58, 37), "trailed by 10+ after three quarters last game and won"),
    "unbeaten": ("Target on their back", "fade", (57, 48), "unbeaten after 4+ games"),
    "hidden_gem": ("Better than its record", "back", (60, 48),
                   "its record is .200+ worse than its points scored and allowed suggest (Pythagorean, 6+ games)"),
}

CODE = {"Arizona Cardinals": "ARI", "Atlanta Falcons": "ATL", "Baltimore Ravens": "BAL", "Buffalo Bills": "BUF",
        "Carolina Panthers": "CAR", "Chicago Bears": "CHI", "Cincinnati Bengals": "CIN", "Cleveland Browns": "CLE",
        "Dallas Cowboys": "DAL", "Denver Broncos": "DEN", "Detroit Lions": "DET", "Green Bay Packers": "GB",
        "Houston Texans": "HOU", "Indianapolis Colts": "IND", "Jacksonville Jaguars": "JAX", "Kansas City Chiefs": "KC",
        "Las Vegas Raiders": "LV", "Los Angeles Chargers": "LAC", "Los Angeles Rams": "LA", "Miami Dolphins": "MIA",
        "Minnesota Vikings": "MIN", "New England Patriots": "NE", "New Orleans Saints": "NO", "New York Giants": "NYG",
        "New York Jets": "NYJ", "Philadelphia Eagles": "PHI", "Pittsburgh Steelers": "PIT", "San Francisco 49ers": "SF",
        "Seattle Seahawks": "SEA", "Tampa Bay Buccaneers": "TB", "Tennessee Titans": "TEN", "Washington Commanders": "WAS"}
DIVISION = {t: d for d, ts in (("AE", "BUF MIA NE NYJ"), ("AN", "BAL CIN CLE PIT"), ("AS", "HOU IND JAX TEN"),
                               ("AW", "DEN KC LV LAC"), ("NE", "DAL NYG PHI WAS"), ("NN", "CHI DET GB MIN"),
                               ("NS", "ATL CAR NO TB"), ("NW", "ARI LA SF SEA")) for t in ts.split()}
# Hours from Eastern time (Arizona counted as Mountain, as in the backtest).
TZ = {**{t: 0 for t in "ATL BAL BUF CAR CIN CLE DET IND JAX MIA NE NYG NYJ PHI PIT TB WAS".split()},
      **{t: -1 for t in "CHI DAL GB HOU KC MIN NO TEN".split()},
      **{t: -2 for t in "DEN ARI".split()},
      **{t: -3 for t in "LA LAC LV SEA SF".split()}}
COORD = {"ARI": (33.53, -112.26), "ATL": (33.76, -84.40), "BAL": (39.28, -76.62), "BUF": (42.77, -78.79),
         "CAR": (35.23, -80.85), "CHI": (41.86, -87.62), "CIN": (39.10, -84.52), "CLE": (41.51, -81.70),
         "DAL": (32.75, -97.09), "DEN": (39.74, -105.02), "DET": (42.34, -83.05), "GB": (44.50, -88.06),
         "HOU": (29.68, -95.41), "IND": (39.76, -86.16), "JAX": (30.32, -81.64), "KC": (39.05, -94.48),
         "LA": (33.95, -118.34), "LAC": (33.95, -118.34), "LV": (36.09, -115.18), "MIA": (25.96, -80.24),
         "MIN": (44.97, -93.26), "NE": (42.09, -71.26), "NO": (29.95, -90.08), "NYG": (40.81, -74.07),
         "NYJ": (40.81, -74.07), "PHI": (39.90, -75.17), "PIT": (40.45, -80.02), "SEA": (47.60, -122.33),
         "SF": (37.40, -121.97), "TB": (27.98, -82.50), "TEN": (36.17, -86.77), "WAS": (38.91, -76.86)}
# Home games under a roof (dome or retractable), as in the nflverse games file for 2025.
DOME = {"ARI", "ATL", "DAL", "DET", "HOU", "IND", "LA", "LAC", "LV", "MIN", "NO"}
WARM_OUTDOOR = {"MIA", "TB", "JAX"}
COLD_OUTDOOR = {"BUF", "GB", "CHI", "NE", "PIT", "CLE", "KC", "DEN", "NYJ", "NYG", "PHI", "BAL", "CIN", "WAS"}

# Regular-season starts by franchise through the 2025 season (nflverse games
# file), franchises with 8+ only, for QBs who started a game in 2024 or 2025.
QB_SEASON = 2026
QB_STARTS = {
    "Aaron Rodgers": {"GB": 222, "NYJ": 18, "PIT": 16}, "Aidan O'Connell": {"LV": 17},
    "Andy Dalton": {"CIN": 133, "DAL": 9, "NO": 13, "CAR": 10}, "Anthony Richardson": {"IND": 10},
    "Bailey Zappe": {"NE": 8}, "Baker Mayfield": {"CLE": 59, "TB": 51}, "Bo Nix": {"DEN": 34},
    "Brock Purdy": {"SF": 45}, "Bryce Young": {"CAR": 41}, "C.J. Stroud": {"HOU": 45}, "Caleb Williams": {"CHI": 34},
    "Cam Ward": {"TEN": 17}, "Carson Wentz": {"PHI": 68, "IND": 17}, "Cooper Rush": {"DAL": 14},
    "Dak Prescott": {"DAL": 138}, "Daniel Jones": {"NYG": 69, "IND": 13}, "Davis Mills": {"HOU": 30},
    "Derek Carr": {"LV": 142, "NO": 27}, "Deshaun Watson": {"HOU": 53, "CLE": 19}, "Drake Maye": {"NE": 28},
    "Drew Lock": {"DEN": 21}, "Gardner Minshew": {"JAX": 20, "IND": 13, "LV": 10},
    "Geno Smith": {"NYJ": 30, "SEA": 52, "LV": 15}, "J.J. McCarthy": {"MIN": 10},
    "Jacoby Brissett": {"IND": 30, "CLE": 11, "ARI": 12}, "Jake Browning": {"CIN": 10}, "Jalen Hurts": {"PHI": 83},
    "Jameis Winston": {"TB": 70, "NO": 11, "CLE": 9}, "Jared Goff": {"LA": 69, "DET": 82}, "Jaxson Dart": {"NYG": 12},
    "Jayden Daniels": {"WAS": 20}, "Jimmy Garoppolo": {"SF": 55}, "Joe Burrow": {"CIN": 77},
    "Joe Flacco": {"BAL": 162, "DEN": 8, "NYJ": 9, "CLE": 9, "IND": 11}, "Jordan Love": {"GB": 48},
    "Josh Allen": {"BUF": 124}, "Joshua Dobbs": {"ARI": 8}, "Justin Fields": {"CHI": 38},
    "Justin Herbert": {"LAC": 95}, "Kenny Pickett": {"PIT": 25}, "Kirk Cousins": {"WAS": 57, "MIN": 88, "ATL": 22},
    "Kyler Murray": {"ARI": 86}, "Lamar Jackson": {"BAL": 107}, "Mac Jones": {"NE": 42, "SF": 8},
    "Marcus Mariota": {"TEN": 61, "ATL": 13, "WAS": 12}, "Mason Rudolph": {"PIT": 14, "TEN": 11},
    "Matthew Stafford": {"DET": 165, "LA": 74}, "Michael Penix": {"ATL": 12}, "Mitchell Trubisky": {"CHI": 50},
    "Patrick Mahomes": {"KC": 126}, "Philip Rivers": {"LAC": 224, "IND": 19},
    "Russell Wilson": {"SEA": 158, "DEN": 30, "PIT": 11}, "Sam Darnold": {"NYJ": 38, "CAR": 18, "MIN": 17, "SEA": 17},
    "Spencer Rattler": {"NO": 12}, "Tommy DeVito": {"NYG": 11}, "Trevor Lawrence": {"JAX": 77},
    "Tua Tagovailoa": {"MIA": 76}, "Tyler Huntley": {"BAL": 11}, "Tyler Shough": {"NO": 9},
    "Tyrod Taylor": {"BUF": 43, "NYJ": 8}, "Will Levis": {"TEN": 15},
}


def _qb_key(name):
    s = re.sub(r"[^a-z ]", "", (name or "").lower().replace("-", " "))
    return " ".join(t for t in s.split() if t not in ("jr", "sr", "ii", "iii", "iv", "v"))


QB_BY_KEY = {_qb_key(k): (k, v) for k, v in QB_STARTS.items()}


def _num(v):
    try:
        return float(str(v).replace("+", ""))
    except (TypeError, ValueError):
        return None


def pos(name):
    """Possessive: "Bills'" / "Lions'"."""
    return name + ("'" if name.endswith("s") else "'s")


def nick_of(name):
    """"Detroit Lions" -> "Lions"."""
    return name.split()[-1]


def miles(a, b):
    (la1, lo1), (la2, lo2) = a, b
    p = math.pi / 180
    h = math.sin((la2 - la1) * p / 2) ** 2 + math.cos(la1 * p) * math.cos(la2 * p) * math.sin((lo2 - lo1) * p / 2) ** 2
    return 3959 * 2 * math.asin(math.sqrt(h))


def entry(key, team, opp, fact):
    name, says, (w, l), _ = STORIES[key]
    pct = 100 * w / (w + l)
    lean, lean_pct = (team, pct) if (pct > 50) == (says == "back") else (opp, 100 - pct)
    if pct == 50:
        lean = None
    return {"key": key, "name": name, "team": team, "says": says, "fact": fact, "record": f"{w}-{l}", "pct": round(pct, 1),
            "leans": lean, "leanPct": round(max(pct, 100 - pct), 1), "against": pct < 50, "unit": "ATS"}


def kick_hour(time_str):
    """'1:00 PM ET' -> 13.0, or None."""
    try:
        t, ampm = time_str.replace("ET", "").split()[:2]
        h, m = (t.split(":") + ["0"])[:2]
        return int(h) % 12 + (12 if ampm.upper() == "PM" else 0) + int(m) / 60
    except (AttributeError, ValueError):
        return None


def season_of(date_str):
    d = date.fromisoformat(date_str)
    return d.year if d.month >= 3 else d.year - 1


_SEASONS = {}


def season_games(session, season):
    """Every regular-season game of `season` from ESPN's weekly scoreboards,
    hand-entered finals on top: [{eid, date (ET), kick (ET hour), neutral,
    final, ot, home, away, hs, as, hq, aq}]. Raises if a week can't be read:
    a missing week would make a team's record (and so its storylines) wrong."""
    if season in _SEASONS:
        return _SEASONS[season]
    out = []
    for week in range(1, 19):
        r = session.get(f"https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
                        f"?dates={season}&seasontype=2&week={week}&limit=100", timeout=20)
        r.raise_for_status()
        for ev in r.json().get("events", []):
            if (ev.get("season") or {}).get("type") not in (None, 2):
                continue
            comp = ev["competitions"][0]
            t = {c["homeAway"]: c for c in comp["competitors"]}
            kick = datetime.fromisoformat(ev["date"].replace("Z", "+00:00")).astimezone(ET)
            st = comp.get("status") or {}
            g = {"eid": ev["id"], "date": kick.strftime("%Y-%m-%d"), "kick": kick.hour + kick.minute / 60,
                 "neutral": bool(comp.get("neutralSite")), "final": bool((st.get("type") or {}).get("completed")),
                 "ot": (st.get("period") or 0) > 4, "home": t["home"]["team"]["displayName"],
                 "away": t["away"]["team"]["displayName"], "hs": _num(t["home"].get("score")),
                 "as": _num(t["away"].get("score")),
                 "hq": [_num(x.get("value")) for x in t["home"].get("linescores") or []],
                 "aq": [_num(x.get("value")) for x in t["away"].get("linescores") or []]}
            m = manual.game("nfl", g["date"], g["away"], g["home"])
            if manual.has_final(m):  # hand-entered final wins over ESPN
                if (m["homeScore"], m["awayScore"]) != (g["hs"], g["as"]):
                    g["hq"] = g["aq"] = []
                g.update(hs=float(m["homeScore"]), **{"as": float(m["awayScore"])}, final=True)
                if "ot" in m:
                    g["ot"] = bool(m["ot"])
            out.append(g)
    # Finals entered by hand for games ESPN doesn't list at all.
    listed = {(g["date"], g["away"], g["home"]) for g in out}
    for d in manual.dates("nfl"):
        if season_of(d) != season or not (date(season, 8, 25) <= date.fromisoformat(d) <= date(season + 1, 1, 20)):
            continue
        for m in manual.load("nfl", d).values():
            if manual.has_final(m) and (d, m.get("away"), m.get("home")) not in listed:
                out.append({"eid": f"manual:{d}", "date": d, "kick": kick_hour(m.get("time")), "neutral": False,
                            "final": True, "ot": bool(m.get("ot")), "home": m["home"], "away": m["away"],
                            "hs": float(m["homeScore"]), "as": float(m["awayScore"]), "hq": [], "aq": []})
    out.sort(key=lambda g: (g["date"], g["kick"] or 0))
    _SEASONS[season] = out
    return out


def team_log(games, team):
    """The team's games in date order, from its side: {date, opp, venue
    ('H'/'A'/'N'), final, pf, pa, m, ot, q3 (its lead after three quarters,
    None when unknown), eid}."""
    out = []
    for g in games:
        if team not in (g["home"], g["away"]):
            continue
        h = g["home"] == team
        pf, pa = (g["hs"], g["as"]) if h else (g["as"], g["hs"])
        mq, oq = (g["hq"], g["aq"]) if h else (g["aq"], g["hq"])
        q3 = sum(mq[:3]) - sum(oq[:3]) if len(mq) >= 3 and len(oq) >= 3 and None not in mq[:3] + oq[:3] else None
        out.append({"date": g["date"], "opp": g["away"] if h else g["home"], "venue": "N" if g["neutral"] else ("H" if h else "A"),
                    "final": g["final"] and pf is not None and pa is not None, "pf": pf, "pa": pa,
                    "m": None if pf is None or pa is None else pf - pa, "ot": g["ot"], "q3": q3, "eid": g["eid"]})
    return out


def win_pct(prior):
    return sum(1 if p["m"] > 0 else 0.5 if p["m"] == 0 else 0 for p in prior) / len(prior)


def pyth(prior):
    pf, pa = sum(p["pf"] for p in prior), sum(p["pa"] for p in prior)
    return pf ** 2.37 / (pf ** 2.37 + pa ** 2.37) if pf + pa else 0.5


def record(prior):
    w = sum(1 for p in prior if p["m"] > 0)
    l_ = sum(1 for p in prior if p["m"] < 0)
    t = len(prior) - w - l_
    return f"{w}-{l_}" + (f"-{t}" if t else "")


def starting_qb(session, slate_qb, last):
    """(name, how we know) for tonight's starter: the slate's, else the
    passer with the most attempts in the team's last game."""
    if slate_qb:
        return slate_qb, ""
    if last and not str(last["eid"]).startswith("manual"):
        import nfl_stats_signals as nfs  # noqa: E402  (only when needed)
        p = nfs.top_passer(session, last["eid"], last["team"])
        if p:
            return p[0], " (he started its last game)"
    return None, ""


def team_side(session, date_str, team, opp, is_home, prior, nxt, line, kick, slate_qb):
    """Storylines about `team` today. `prior` is its finished games before
    today, `nxt` its next game after today (or None), `line` its own spread
    (+ = underdog)."""
    out = []
    D = date.fromisoformat(date_str)
    tc, oc = CODE.get(team), CODE.get(opp)
    last = prior[-1] if prior else None
    rest = (D - date.fromisoformat(last["date"])).days if last else None

    if last and last["ot"] and rest <= 6:
        out.append(entry("ot_short", team, opp, f"{team} went to overtime against {last['opp']} on {last['date']} "
                                                f"({last['pf']:g}-{last['pa']:g}) and plays again {rest} days later."))
    if last and rest >= 13 and is_home and line is not None and line <= -3:
        out.append(entry("bye_rust", team, opp, f"{team} is coming off a bye ({rest} days since its last game) and is a "
                                                f"{line:+g} home favorite."))
    if tc and oc:
        if not is_home and TZ[tc] == -3 and TZ[oc] == 0 and kick is not None and kick < 14:
            hh, mm = int(kick), round(kick % 1 * 60)
            out.append(entry("west_early", team, opp, f"{team} (Pacific time) plays at the {opp} at {hh % 12 or 12}:{mm:02d} "
                                                      f"{'PM' if hh >= 12 else 'AM'} ET, {(hh - 3) % 12 or 12}:{mm:02d} "
                                                      f"{'PM' if hh - 3 >= 12 else 'AM'} on its body clock."))
        if TZ[tc] == -3 and TZ[oc] == 0 and kick is not None and kick >= 20:
            out.append(entry("west_night", team, opp, f"{team} (Pacific time) {'hosts' if is_home else 'visits'} {opp} "
                                                      f"(Eastern time) in a night game."))
        if not is_home:
            mi = miles(COORD[tc], COORD[oc])
            if mi >= 2000:
                out.append(entry("cross_country", team, opp, f"{team} travels about {round(mi, -1):,.0f} miles to play the {opp}."))
        if is_home and tc in COLD_OUTDOOR and D.month in (12, 1) and (oc in DOME or oc in WARM_OUTDOOR):
            why = "plays its home games under a roof" if oc in DOME else "comes from a warm-weather city"
            out.append(entry("frozen_tundra", team, opp, f"{team} hosts the {opp} outdoors in {D.strftime('%B')}; the {nick_of(opp)} {why}."))
        if (line is not None and line <= -3 and DIVISION[tc] != DIVISION[oc] and last and nxt
                and DIVISION.get(CODE.get(last["opp"])) == DIVISION[tc] and DIVISION.get(CODE.get(nxt["opp"])) == DIVISION[tc]):
            out.append(entry("sandwich", team, opp, f"{team} is a {line:+g} favorite against the {opp}, a non-division game between "
                                                    f"division games with {last['opp']} and {nxt['opp']}."))
        if season_of(date_str) == QB_SEASON:
            qb, how = starting_qb(session, slate_qb, dict(last, team=team) if last else None)
            hit = QB_BY_KEY.get(_qb_key(qb)) if qb else None
            if hit and hit[1].get(oc, 0) >= 8 and oc != tc:
                out.append(entry("qb_former", team, opp, f"{team} QB {qb}{how} made {hit[1][oc]} regular-season starts for "
                                                         f"{opp}."))
    if last and last["q3"] is not None and last["q3"] <= -10 and last["m"] > 0:
        out.append(entry("escape", team, opp, f"{team} trailed {last['opp']} by {-last['q3']:g} after three quarters last "
                                              f"game and won {last['pf']:g}-{last['pa']:g}."))
    if len(prior) >= 4 and all(p["m"] > 0 for p in prior):
        out.append(entry("unbeaten", team, opp, f"{team} is {len(prior)}-0."))
    if len(prior) >= 6:
        wp, py = win_pct(prior), pyth(prior)
        if py - wp >= 0.2:
            n = len(prior)
            out.append(entry("hidden_gem", team, opp, f"{team} is {record(prior)} but has scored "
                                                      f"{sum(p['pf'] for p in prior):g} and allowed "
                                                      f"{sum(p['pa'] for p in prior):g}, which usually goes with about "
                                                      f"{py * n:.1f} wins in {n} games."))
    return out


def storylines_for(session, games, date_str, g):
    """Storylines for one slate game (a list, possibly empty), or None when
    the game isn't a regular-season game on ESPN's board for that date."""
    def same(a, b):
        return a == b or _same_team(a, b)

    today = next((e for e in games if e["date"] == date_str and same(g["home"], e["home"]) and same(g["away"], e["away"])), None)
    if today is None:
        return None
    if today["neutral"]:
        return []  # as backtested: neutral-site games left out
    home, away = today["home"], today["away"]
    hs = _num(g.get("homeSpread"))
    kick = kick_hour(g.get("time"))
    if kick is None:
        kick = today["kick"]
    out = []
    for team, opp, is_home in ((home, away, True), (away, home, False)):
        log = team_log(games, team)
        prior = [p for p in log if p["date"] < date_str and p["final"]]
        nxt = next((p for p in log if p["date"] > date_str), None)
        line = None if hs is None else (hs if is_home else -hs)
        out += team_side(session, date_str, team, opp, is_home, prior, nxt, line, kick,
                         g.get("homeQB" if is_home else "awayQB"))
    # A story that points at both teams in one game says nothing: drop it
    # (the backtest skipped those games).
    sides = {}
    for e in out:
        sides.setdefault(e["key"], set()).add(e["team"] if e["says"] == "back" else (away if e["team"] == home else home))
    out = [e for e in out if len(sides[e["key"]]) == 1]
    names = {home: g["home"], away: g["away"]}  # name teams as the slate does
    for e in out:
        e["team"] = names.get(e["team"], e["team"])
        if e["leans"]:
            e["leans"] = names.get(e["leans"], e["leans"])
    return out


def main():
    args = sys.argv[1:]
    dry = "--dry-run" in args
    include_final = "--include-final" in args
    if include_final and not dry:
        sys.exit("--include-final only works with --dry-run (finished games keep their pre-kickoff storylines).")
    dates = [a for a in args if not a.startswith("--")] or [today_et_str()]
    session = espn.make_session()
    for date_str in dates:
        doc = store.read_doc("nfl", date_str)
        if doc is None:
            print(f"{date_str}: no NFL slate.")
            continue
        try:
            games = season_games(session, season_of(date_str))
        except Exception as exc:  # noqa: BLE001
            print(f"{date_str}: ESPN unreachable ({exc.__class__.__name__}) -- storylines left as they were.")
            continue
        changed = 0
        for g in doc.get("games", []):
            if not g.get("away") or not g.get("home"):
                continue
            if isinstance(g.get("awayScore"), (int, float)) and not include_final:
                continue  # started or final: keep what was there before kickoff
            try:
                new = storylines_for(session, games, date_str, g)
            except Exception as exc:  # noqa: BLE001
                print(f"  {g['away']} @ {g['home']}: skipped ({exc.__class__.__name__}: {exc})")
                continue
            new = new or []
            if new != (g.get("storylines") or []):
                if new:
                    g["storylines"] = new
                else:
                    g.pop("storylines", None)
                changed += 1
            for e in new:
                print(f"  {g['away']} @ {g['home']}: {e['name']} ({e['team']}, {e['says']}) -> leans {e['leans']} "
                      f"{e['leanPct']}% | {e['fact']}")
        if changed and not dry:
            store.write_doc("nfl", date_str, doc)
        print(f"{date_str}: storylines on {sum(1 for g in doc.get('games', []) if g.get('storylines'))} game(s)"
              f"{' (dry run, nothing written)' if dry else ''}.")


if __name__ == "__main__":
    main()
