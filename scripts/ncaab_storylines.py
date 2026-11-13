#!/usr/bin/env python3
"""NCAA men's basketball storylines: context for the pick sheet, never a pick.

Each storyline is a situation a writer could tell a story about (a ranked
team "on a school night" in a road gym, an unranked team "hung over" after
beating a top-10 team, a top-5 team "laying 25"). 79 were tested on
2026-11-13, in two rounds (48, then 31 more), on every regular-season game
involving an AP Top 25 team from 2015-16 to 2025-26 with a closing spread
(6,693 games; conference tournaments and the postseason left out; the
2020-21 COVID season, 497 games in mostly empty arenas, reported separately
and left out of the numbers below). Data: ESPN's daily D-I scoreboards
(groups=50: scores, overtime, site, venue, conference game, TV, team three-
point/field-goal/free-throw/rebound totals), ESPN's weekly AP polls (each
date's poll from the Monday it was released; week 1 = preseason) and ESPN's
closing spreads (core odds API: ESPN BET's line when listed, else the median
of the sportsbooks). The story's bet was graded against the closing spread,
pushes left out, and a story that pointed at both teams in one game was
skipped for that game. 5 of the 79 were at p<0.05 where about 4 would be
expected by chance, and 26 met the display bar where about 19 would by
chance, so as a group they're no better than luck. These are the 26 where
history leaned 53%+ one way on 50+ games, or p<0.05 (last year's grudge,
52.4% on 2,679 games) -- which side that can be the opposite of the story
(an AP top-5 team favored by 25+ covered 55.2%; the story says fade it, so
it's marked `against`). Several are one pattern sliced different ways: in
these games AP-ranked teams on a true road floor covered 47.3% and home
teams 52.4%, which is most of what school night on the road, snake pit,
disrespected on the road, non-conference road trip and leaving home show.
Small samples: upset hangover (75 games), November hype (66), home cooking
(80). Leaning opposite ways in even and odd seasons: nail-biters, home skid
(counted half in the tally, WEAK). They're shown on the game card with their
record and aren't graded or counted anywhere except their own live record.

Not tested, because these feeds don't carry them: senior night as such (the
last home game was tested: 48.7%), buzzer-beaters (won by 1-2: 51.7%),
coaching changes, injuries, and player stats. Rivalries were tested from a
hard-coded list of 62 pairs: underdogs covered 51.9%, so they aren't shown.

Writes `storylines` onto each game of today's NCAAB slate (or the dates
given) that hasn't started: [{key, name, team, says, fact, record, pct,
leans, leanPct, against, unit, weight, live}], where `team` is who the story
is about, `says` is the story's bet ("back"/"fade" that team), `record`/`pct`
are that bet's history ATS (`unit`) plus its live record since going live
(`live`, lib/storyline_live.py), and `leans`/`leanPct` the side history
favors. Once a game has a score the entry is kept as it was before tip-off.
Live, each team's games come from ESPN's daily D-I scoreboards from Nov 1
(as in the backtest; through five days ahead, for the sandwich game), the AP
ranks from ESPN's weekly polls, tonight's spread from the slate's homeSpread
(the backtest used the closing line), last season's meetings and the games a
team has left from ESPN's team schedules. Only games with an AP Top 25 team,
a spread, in the regular season and not in a conference tournament get any
(as backtested). If ESPN can't be reached, nothing is changed.

Usage: python scripts/ncaab_storylines.py [--dry-run] [--include-final] [--backfill] [YYYY-MM-DD ...]
  --dry-run        print what fires, write nothing
  --include-final  (with --dry-run) also evaluate games that have a score
  --backfill       also write finished games (this season's games before
                   storylines went live, from the games before each one);
                   run storyline_records.py after
"""
import os
import sys
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib import storyline_live  # noqa: E402
from lib import espn, store  # noqa: E402
from lib.dates import today_et_str  # noqa: E402
from score_slate import _same_team  # noqa: E402

ET = ZoneInfo("America/New_York")
SITE = "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball"
CORE = "https://sports.core.api.espn.com/v2/sports/basketball/leagues/mens-college-basketball"

# key: (name, story's bet, wins-losses for that bet 2015-16 to 2025-26 without 2020-21, games where it applies)
STORIES = {
    "midweek_road": ("School night on the road", "fade", (631, 539),
                     "an AP-ranked team on the road (not a neutral floor) on a Tuesday, Wednesday or Thursday"),
    "hostile_gym": ("Big Ten / Big 12 snake pit", "fade", (449, 385),
                    "an AP-ranked team on the road in a Big Ten or Big 12 conference game"),
    "ranked_road_dog": ("Disrespected on the road", "back", (446, 515), "AP-ranked, on the road, and an underdog"),
    "nonconf_road": ("Non-conference road trip", "fade", (200, 166), "an AP-ranked team in a true road non-conference game"),
    "first_road": ("Leaving home", "fade", (130, 112), "an AP-ranked team in its first true road game of the season"),
    "last_season_grudge": ("Last year's grudge", "back", (1405, 1274),
                           "lost its last meeting with this opponent last season; first meeting this season"),
    "revenge": ("The rematch", "back", (723, 642), "lost to this opponent earlier this season"),
    "payback": ("Payback", "back", (230, 203), "lost to this opponent by 15+ earlier this season"),
    "big_stage": ("Down from the big stage", "fade", (272, 234), "played an AP top-5 team in its last game"),
    "rolling_dog": ("Rolling underdog", "back", (264, 302), "an underdog on a 5+ game winning streak"),
    "top5_huge": ("Top-5 laying 25", "fade", (95, 117), "an AP top-5 team favored by 25+"),
    "ot_loser": ("Overtime heartbreak", "back", (151, 126), "lost its last game in overtime"),
    "steamroller": ("Steamroller", "fade", (115, 138), "won each of its last three games by 20+"),
    "home_skid": ("Home skid", "back", (179, 154), "unranked, at home, on a 3+ game losing streak"),
    "poll_riser": ("Poll riser", "fade", (235, 265), "AP-ranked and up 5+ spots in this week's poll"),
    "conf_opener_dog": ("Conference-opener underdog", "back", (100, 119), "an underdog in its first conference game"),
    "rust": ("Holiday rust", "fade", (143, 165), "8+ days since its last game, in December or January"),
    "upset_hangover": ("Upset hangover", "fade", (43, 32), "unranked, and beat an AP top-10 team in its last game"),
    "sandwich": ("Sandwich game", "fade", (144, 125),
                 "AP-ranked vs an unranked team, after a game vs a ranked team and before another within 5 days"),
    "bracket_lock": ("Bracket lock", "fade", (79, 65), "an AP top-5 team in its last three regular-season games, February on"),
    "home_cooking": ("Home cooking", "back", (35, 45), "its first home game after 3+ straight true road games"),
    "holiday_fav": ("Holiday hangover", "fade", (119, 136), "favored, December 26 to January 1"),
    "mte_hangover": ("Tournament-trip hangover", "fade", (124, 109),
                     "first game off a November/December neutral-site event (its last two games on neutral floors)"),
    "nail_biters": ("Nail-biters", "fade", (95, 108), "each of its last three games decided by 5 or fewer"),
    "after_dark": ("After dark out West", "fade", (73, 83),
                   "an Eastern/Central-time team away from home in the Pacific time zone, tipping 9 PM ET or later"),
    "november_hype": ("November hype", "fade", (31, 35), "an AP top-10 team favored over a ranked team on a neutral floor in November"),
}

B1G_B12 = {"7", "8"}
STATE_TZ = {}
for _z, _states in ((0, "CT DE DC FL GA IN KY ME MD MA MI NH NJ NY NC OH PA RI SC VT VA WV"),
                    (1, "AL AR IL IA KS LA MN MS MO NE ND OK SD TN TX WI"),
                    (2, "CO MT NM UT WY ID AZ"), (3, "CA NV OR WA"), (4, "AK"), (5, "HI")):
    for _s in _states.split():
        STATE_TZ[_s] = _z  # hours behind Eastern (standard time)
CITY_TZ = {("El Paso", "TX"): 2, ("Knoxville", "TN"): 0, ("Chattanooga", "TN"): 0, ("Johnson City", "TN"): 0,
           ("Bowling Green", "KY"): 1, ("Murray", "KY"): 1, ("Moscow", "ID"): 3, ("Pensacola", "FL"): 1,
           ("Evansville", "IN"): 1, ("Valparaiso", "IN"): 1, ("Hammond", "IN"): 1, ("Cookeville", "TN"): 1,
           ("Grand Forks", "ND"): 1, ("Fargo", "ND"): 1}


def pos(name):
    """Possessive: "Texas'" / "Duke's"."""
    return name + ("'" if name.endswith("s") else "'s")


# Storylines counted double in the card's "history leans" tally. None for
# college basketball: 5 of the 79 tested were at p<0.05 where about 4 would be
# by chance, and the strongest (school night on the road, snake pit,
# disrespected on the road) are slices of one base pattern -- AP-ranked teams
# on a true road floor covered 47.3% in these games -- so none stands out as
# the most robust.
STRONG = set()


# Storylines counted as half a point: their lean flips between even and odd
# seasons (nail-biters 41-68 in even seasons, 54-40 in odd; home skid 117-82
# even, 62-72 odd).
WEAK = {"nail_biters", "home_skid"}


def entry(key, team, opp, fact):
    name, says, (w, l), _ = STORIES[key]
    lw, ll = storyline_live.live("ncaab", key)  # graded since it went live
    w, l = w + lw, l + ll
    pct = 100 * w / (w + l)
    lean, lean_pct = (team, pct) if (pct > 50) == (says == "back") else (opp, 100 - pct)
    if pct == 50:
        lean = None
    return {"weight": 2 if key in STRONG else (0.5 if key in WEAK else 1), "live": f"{lw}-{ll}", "key": key, "name": name,
            "team": team, "says": says, "fact": fact, "record": f"{w}-{l}", "pct": round(pct, 1),
            "leans": lean, "leanPct": round(max(pct, 100 - pct), 1), "against": pct < 50, "unit": "ATS"}


# ---------------------------------------------------------------- game data

def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _stat(t, name):
    for s in t.get("statistics", []):
        if s.get("name") == name:
            return s.get("displayValue")
    return None


def trim_event(e):
    """The parts of an ESPN scoreboard event the storylines use."""
    c = e["competitions"][0]
    comps = []
    for t in c["competitors"]:
        tm = t.get("team") or {}
        comps.append({"id": tm.get("id"), "loc": tm.get("location"), "name": tm.get("displayName"), "abbr": tm.get("abbreviation"),
                      "conf": tm.get("conferenceId"), "ha": t.get("homeAway"), "score": t.get("score"),
                      "rank": (t.get("curatedRank") or {}).get("current"),
                      "3pm": _stat(t, "threePointFieldGoalsMade"), "3pa": _stat(t, "threePointFieldGoalsAttempted"),
                      "fgm": _stat(t, "fieldGoalsMade"), "fga": _stat(t, "fieldGoalsAttempted"), "reb": _stat(t, "rebounds"),
                      "ftm": _stat(t, "freeThrowsMade"), "fta": _stat(t, "freeThrowsAttempted")})
    v = c.get("venue") or {}
    st = c.get("status", {})
    return {"id": str(e["id"]), "date": c.get("date") or e.get("date"), "stype": (e.get("season") or {}).get("type"),
            "neutral": c.get("neutralSite"), "confgame": c.get("conferenceCompetition"),
            "city": (v.get("address") or {}).get("city"), "state": (v.get("address") or {}).get("state"),
            "notes": [n.get("headline") for n in c.get("notes", [])],
            "tv": [{"m": b.get("market"), "n": b.get("names")} for b in c.get("broadcasts", [])],
            "completed": st.get("type", {}).get("completed"), "period": st.get("period"), "comps": comps}


def season_of(d):
    """ESPN's season year (2026-27 -> 2027)."""
    return d.year + 1 if d.month >= 8 else d.year


def kickoff(iso):
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(ET)
    except (AttributeError, ValueError):
        return None


def conf_tourney(e, d):
    """A conference tournament game (left out, as backtested)."""
    txt = " ".join(n or "" for n in e.get("notes") or []).lower()
    return ("tournament" in txt or "championship" in txt) and (bool(e.get("confgame")) or d.month == 3)


def map_weeks(events_by_date, polls, dated):
    """{date: AP poll week}. Weeks run Monday to Sunday from the week-2 poll's
    Monday: from ESPN's poll dates (`dated`, {week: ET date}) where it has
    them, else the Monday of the first date whose games' curatedRank matches
    the week-2 poll better than the preseason one."""
    if not polls:
        return {}
    w2 = None
    for w, dd in sorted(dated.items()):
        if w >= 3:
            w2 = dd - timedelta(days=7 * (w - 2))
            break
    if w2 is None and 2 in polls and 1 in polls:
        for d in sorted(events_by_date):
            pairs = [(c["id"], c["rank"]) for e in events_by_date[d] for c in e["comps"] if c.get("rank") and c["rank"] <= 25]
            if sum(1 for t, r in pairs if polls[2].get(t) == r) > sum(1 for t, r in pairs if polls[1].get(t) == r):
                w2 = d - timedelta(days=d.weekday())
                break
    out = {}
    for d in events_by_date:
        if w2 is None or d < w2:
            out[d] = 1 if 1 in polls else None
            continue
        w = 2 + (d - w2).days // 7
        while w > 1 and w not in polls:
            w -= 1
        out[d] = w if w in polls else None
    return out


def season_rows(events_by_date, polls, weeks):
    """{team_id: [row, ...]} oldest first: every game of the season from each
    team's side, with the AP ranks of the poll that applied that day."""
    rows, seen = {}, set()
    for d, evs in sorted(events_by_date.items()):
        for e in evs:
            if e["id"] in seen or len(e["comps"]) != 2:
                continue
            seen.add(e["id"])
            k = kickoff(e["date"])
            if k is None:
                continue
            gd = k.date()
            w = weeks.get(d)
            poll = polls.get(w, {}) if w else {}
            home = next((c for c in e["comps"] if c["ha"] == "home"), e["comps"][0])
            away = next((c for c in e["comps"] if c is not home), e["comps"][1])
            done = bool(e.get("completed"))
            tv = [n for b in e.get("tv") or [] if b.get("m") == "national" for n in (b.get("n") or [])]
            for me, op in ((home, away), (away, home)):
                rows.setdefault(me["id"], []).append({
                    "eid": e["id"], "date": gd.isoformat(), "D": gd, "kick": e["date"], "et_hour": k.hour + k.minute / 60,
                    "week": w, "site": "neutral" if e.get("neutral") else ("home" if me is home else "away"),
                    "listed_home": me is home, "tid": me["id"], "team": me["loc"], "tname": me["name"], "abbr": me["abbr"],
                    "conf": me["conf"], "oid": op["id"], "opp": op["loc"], "oconf": op["conf"],
                    "ts": _num(me["score"]) if done else None, "os": _num(op["score"]) if done else None,
                    "ot": done and (e.get("period") or 2) > 2,
                    "rank": poll.get(me["id"]), "orank": poll.get(op["id"]),
                    "t3m": _num(me["3pm"]), "t3a": _num(me["3pa"]), "o3m": _num(op["3pm"]), "o3a": _num(op["3pa"]),
                    "tfgm": _num(me["fgm"]), "tfga": _num(me["fga"]), "treb": _num(me["reb"]), "oreb": _num(op["reb"]),
                    "tftm": _num(me["ftm"]), "tfta": _num(me["fta"]),
                    "city": e.get("city"), "state": e.get("state"), "confgame": bool(e.get("confgame")),
                    "ctourney": conf_tourney(e, gd), "stype": e.get("stype"), "notes": e.get("notes") or [], "tv": tv,
                    "done": done,
                })
    for r in rows.values():
        r.sort(key=lambda x: x["kick"])
    return rows


def zone_of(city, state):
    return CITY_TZ.get((city, state), STATE_TZ.get(state))


def home_info(rows):
    """(hours behind Eastern, city, state) of a team's usual home floor."""
    c = Counter((r["city"], r["state"]) for r in rows if r["site"] == "home" and r["state"])
    if not c:
        return (None, None, None)
    city, state = c.most_common(1)[0][0]
    return (zone_of(city, state), city, state)


def streak_of(prior):
    s = 0
    for r in reversed(prior):
        mm = r["ts"] - r["os"]
        if mm == 0:
            break
        if s == 0:
            s = 1 if mm > 0 else -1
        elif (mm > 0) == (s > 0):
            s += 1 if s > 0 else -1
        else:
            break
    return s


def game_context(rows, polls, homes, row, spread, extra=None):
    """What a storyline may read about `row` (one team's side of a game), all
    known before tip-off: both teams' season so far, the team's remaining
    schedule (opponents, sites, dates -- not results), this week's and last
    week's AP poll and the preseason one, and last season's meetings.
    `extra` (live) supplies last season's meetings and the count of
    regular-season games left from ESPN's team schedules; without it both come
    from `rows` (the backtest's full-season data)."""
    w = row["week"]
    now = polls.get(w, {}) if w else {}
    prevw = w - 1 if w else None
    while prevw and prevw > 0 and prevw not in polls:
        prevw -= 1
    prev = polls.get(prevw) if prevw and prevw >= 1 else None
    mine, theirs = rows.get(row["tid"], []), rows.get(row["oid"], [])
    done = lambda r: r["kick"] < row["kick"] and r["done"] and r["stype"] == 2 and r["ts"] is not None  # noqa: E731
    prior = [r for r in mine if done(r)]
    later = [dict(r, orank_now=now.get(r["oid"])) for r in mine if r["kick"] > row["kick"] and r["stype"] == 2]
    if extra is not None:
        last_meets = extra.last_meets(row["tid"], row["oid"])
        remaining = lambda: extra.remaining(row["tid"], row["kick"])  # noqa: E731
    else:
        last_meets = []
        remaining = lambda: sum(1 for r in later if not r["ctourney"])  # noqa: E731
    return {"D": row["D"], "team": row["team"], "opp": row["opp"], "tid": row["tid"], "oid": row["oid"],
            "rank": now.get(row["tid"]), "orank": now.get(row["oid"]), "week": w,
            "prev_known": prev is not None, "prev_rank": (prev or {}).get(row["tid"]), "pre_rank": polls.get(1, {}).get(row["tid"]),
            "site": row["site"], "city": row["city"], "state": row["state"], "confgame": row["confgame"],
            "conf": row["conf"], "oconf": row["oconf"], "sp": spread, "prior": prior, "oprior": [r for r in theirs if done(r)],
            "later": later, "remaining": remaining, "last_meets": last_meets,
            "streak": streak_of(prior), "home": homes.get(row["tid"], (None, None, None)), "tv": row["tv"],
            "et_hour": row["et_hour"]}


def _m(r):
    return r["ts"] - r["os"]


def _score(r):
    return f"{r['ts']:g}-{r['os']:g}"


def team_side(c):
    """[(key, fact)] for the team in context `c` (game_context)."""
    out = []
    P, sp, D = c["prior"], c["sp"], c["D"]
    last = P[-1] if P else None
    T, O = c["team"], c["opp"]
    rk, ork = c["rank"], c["orank"]
    site = c["site"]
    later = c["later"]
    nxt = later[0] if later else None
    hz = c["home"][0]
    vz = zone_of(c["city"], c["state"])
    rT = f"#{rk} {T}" if rk else T
    meets = [r for r in P if r["oid"] == c["oid"]]
    add = lambda k, fact: out.append((k, fact))  # noqa: E731

    if rk and site == "away" and D.weekday() in (1, 2, 3):
        add("midweek_road", f"{rT} plays at {O} on a {D.strftime('%A')}.")
    if rk and site == "away" and c["confgame"] and c["oconf"] in B1G_B12:
        add("hostile_gym", f"{rT} plays at {O} in a {'Big Ten' if c['oconf'] == '7' else 'Big 12'} game.")
    if rk and site == "away" and sp is not None and sp > 0:
        add("ranked_road_dog", f"{rT} is a {sp:+g} underdog at {O}.")
    if rk and site == "away" and not c["confgame"]:
        add("nonconf_road", f"{rT} plays a non-conference game at {O}.")
    if rk and site == "away" and P and not any(r["site"] == "away" for r in P):
        add("first_road", f"{pos(rT)} first true road game of the season.")
    lm = c.get("last_meets") or []
    if lm and _m(lm[-1]) < 0 and not meets:
        add("last_season_grudge", f"{T} lost to {O} {_score(lm[-1])} last season ({lm[-1]['date']}).")
    if meets and _m(meets[-1]) < 0:
        add("revenge", f"{T} lost to {O} {_score(meets[-1])} on {meets[-1]['date']}.")
    if meets and _m(meets[-1]) <= -15:
        add("payback", f"{T} lost to {O} by {-_m(meets[-1]):g} on {meets[-1]['date']}.")
    if last and last["orank"] and last["orank"] <= 5:
        add("big_stage", f"{T} played #{last['orank']} {last['opp']} last time out ({'won' if _m(last) > 0 else 'lost'} "
                         f"{_score(last)}).")
    if c["streak"] >= 5 and sp is not None and sp > 0:
        add("rolling_dog", f"{T} has won {c['streak']} straight and is a {sp:+g} underdog.")
    if rk and rk <= 5 and sp is not None and sp <= -25:
        add("top5_huge", f"#{rk} {T} is a {sp:+g} favorite.")
    if last and last["ot"] and _m(last) < 0:
        add("ot_loser", f"{T} lost to {last['opp']} {_score(last)} in overtime last time out.")
    if len(P) >= 3 and all(_m(r) >= 20 for r in P[-3:]):
        add("steamroller", f"{T} won its last three by {', '.join(f'{_m(r):g}' for r in reversed(P[-3:]))}.")
    if not rk and site == "home" and c["streak"] <= -3:
        add("home_skid", f"{T} has lost {-c['streak']} straight and is at home.")
    if rk and c["prev_rank"] and c["prev_rank"] - rk >= 5:
        add("poll_riser", f"{T} moved up from #{c['prev_rank']} to #{rk} in this week's AP poll.")
    if c["confgame"] and not any(r["confgame"] for r in P) and sp is not None and sp > 0:
        add("conf_opener_dog", f"{pos(T)} first conference game; it's a {sp:+g} underdog.")
    if last and D.month in (12, 1) and (D - last["D"]).days >= 8:
        add("rust", f"{T} hasn't played since {last['date']} ({(D - last['D']).days} days).")
    if not rk and last and _m(last) > 0 and last["orank"] and last["orank"] <= 10 and not last["rank"]:
        add("upset_hangover", f"Unranked {T} beat #{last['orank']} {last['opp']} {_score(last)} last time out.")
    if rk and not ork and last and last["orank"] and nxt and nxt["orank_now"] and (nxt["D"] - D).days <= 5:
        add("sandwich", f"{rT} is between #{last['orank']} {last['opp']} and #{nxt['orank_now']} {nxt['opp']} "
                        f"({nxt['date']}).")
    if rk and rk <= 5 and D.month >= 2:
        left = c["remaining"]()
        if left is not None and left <= 2:
            add("bracket_lock", f"#{rk} {T} has {left} regular-season game{'s' if left != 1 else ''} left after this one.")
    if site == "home" and len(P) >= 3 and all(r["site"] == "away" for r in P[-3:]):
        trip = 0
        for r in reversed(P):
            if r["site"] != "away":
                break
            trip += 1
        add("home_cooking", f"{pos(T)} first home game after {trip} straight on the road.")
    if ((D.month == 12 and D.day >= 26) or (D.month == 1 and D.day == 1)) and sp is not None and sp < 0:
        add("holiday_fav", f"{T} is a {sp:+g} favorite in the holiday week.")
    if site != "neutral" and len(P) >= 2 and P[-1]["site"] == "neutral" and P[-2]["site"] == "neutral" \
            and P[-1]["D"].month in (11, 12) and not P[-1]["confgame"]:
        ev = next((n for n in P[-1]["notes"] if n), None)
        add("mte_hangover", f"{pos(T)} first game back from neutral-site games"
                            f"{f' ({ev})' if ev else ''}.")
    if len(P) >= 3 and all(abs(_m(r)) <= 5 for r in P[-3:]):
        add("nail_biters", f"{pos(T)} last three were decided by {', '.join(f'{abs(_m(r)):g}' for r in reversed(P[-3:]))}.")
    if site != "home" and hz is not None and hz <= 1 and vz is not None and vz >= 3 and c["et_hour"] is not None \
            and c["et_hour"] >= 21:
        h = int(c["et_hour"])
        add("after_dark", f"{T} tips at {h - 12 if h > 12 else h}:{int(round((c['et_hour'] - h) * 60)):02d} PM ET in "
                          f"{c['city']}, {c['state']}.")
    if D.month == 11 and site == "neutral" and rk and rk <= 10 and ork and sp is not None and sp < 0:
        add("november_hype", f"#{rk} {T} is a {sp:+g} favorite over #{ork} {O} on a neutral floor.")
    return out


def game_stories(rows, polls, homes, home_row, away_row, home_spread, extra=None):
    """[(key, team row, fact)] for one game; a story that points at both teams
    is dropped (the backtest skipped those)."""
    fired = []
    for row, sp in ((home_row, home_spread), (away_row, None if home_spread is None else -home_spread)):
        c = game_context(rows, polls, homes, row, sp, extra)
        fired += [(k, row, fact) for k, fact in team_side(c)]
    keys = Counter(k for k, _, _ in fired)
    return [f for f in fired if keys[f[0]] == 1]


# ---------------------------------------------------------------- live

_local = threading.local()


def _session():
    if not hasattr(_local, "s"):
        _local.s = espn.make_session()
    return _local.s


def fetch_day(d):
    """Every D-I event on a date (ESPN scoreboard, groups=50), trimmed."""
    evs, errors = {}, 0
    for limit in espn.SCOREBOARD_LIMITS:
        try:
            r = _session().get(f"{SITE}/scoreboard?dates={d.strftime('%Y%m%d')}&groups=50&limit={limit}", timeout=30)
            r.raise_for_status()
            for e in r.json().get("events", []):
                if e.get("id") and e.get("competitions"):
                    evs.setdefault(str(e["id"]), trim_event(e))
        except Exception:  # noqa: BLE001
            errors += 1
    if errors == len(espn.SCOREBOARD_LIMITS):
        raise RuntimeError(f"ESPN scoreboard {d} unreachable")
    return list(evs.values())


def fetch_polls(session, season):
    """({week: {team_id: rank}}, {week: ET release date}) for a season's AP
    polls; the post-tournament final poll left out."""
    polls, dated = {}, {}
    misses = 0
    for w in range(1, 23):
        r = session.get(f"{CORE}/seasons/{season}/types/2/weeks/{w}/rankings/1", timeout=20)
        if r.status_code == 404:
            misses += 1
            if misses >= 2:
                break
            continue
        r.raise_for_status()
        misses = 0
        d = r.json()
        dd = kickoff(d["date"]).date() if d.get("date") else None
        if dd and 4 <= dd.month <= 9:
            continue  # the final poll (ESPN numbers one 2025-26 final as week 2)
        ranks = {rk["team"]["$ref"].split("/teams/")[1].split("?")[0]: rk["current"] for rk in d.get("ranks") or []}
        if ranks:
            polls[w] = ranks
            if dd:
                dated[w] = dd
    if 1 not in polls:
        raise RuntimeError(f"no AP preseason poll for {season}")
    return polls, dated


class Season:
    """One season's games (Nov 1 through `through`), fetched once per run."""

    def __init__(self, session, season, through):
        self.session, self.season = session, season
        start = date(season - 1, 11, 1)
        days = [start + timedelta(days=i) for i in range((through - start).days + 1)]
        self.polls, dated = fetch_polls(session, season)  # fails fast when ESPN can't be reached
        with ThreadPoolExecutor(4) as ex:
            self.by_date = dict(zip(days, ex.map(fetch_day, days)))
        self.weeks = map_weeks(self.by_date, self.polls, dated)
        self.rows = season_rows(self.by_date, self.polls, self.weeks)
        self.homes = {tid: home_info(rs) for tid, rs in self.rows.items()}
        self.schedules = Schedules(session, season)



class Schedules:
    """Teams' ESPN schedules (regular season, conference tournaments included),
    fetched only when a storyline asks and kept for the run: last season's
    meetings with tonight's opponent, the regular-season games a team has
    left, and a home floor for a team with no home game on the boards yet."""

    def __init__(self, session, season):
        self.session, self.season, self.cache = session, season, {}

    def rows(self, tid, season):
        key = (tid, season)
        if key not in self.cache:
            r = self.session.get(f"{SITE}/teams/{tid}/schedule?season={season}&seasontype=2", timeout=20)
            r.raise_for_status()
            out = []
            for e in r.json().get("events", []):
                c = (e.get("competitions") or [{}])[0]
                comps = c.get("competitors") or []
                me = next((x for x in comps if str(x.get("id")) == str(tid)), None)
                op = next((x for x in comps if x is not me), None)
                if me is None or op is None:
                    continue
                done = bool(((c.get("status") or {}).get("type") or {}).get("completed"))
                k = kickoff(e.get("date"))
                addr = (c.get("venue") or {}).get("address") or {}
                sc = lambda x: _num((x.get("score") or {}).get("value") if isinstance(x.get("score"), dict) else x.get("score"))  # noqa: E731
                out.append({"oid": str(op.get("id")), "date": k.date().isoformat() if k else None, "kick": e.get("date"),
                            "done": done, "ts": sc(me) if done else None, "os": sc(op) if done else None,
                            "stype": (e.get("seasonType") or {}).get("type"),
                            "site": "neutral" if c.get("neutralSite") else me.get("homeAway"),
                            "city": addr.get("city"), "state": addr.get("state"),
                            "ctourney": conf_tourney({"notes": [n.get("headline") for n in c.get("notes") or []],
                                                      "confgame": False}, k.date() if k else date(season, 1, 1))})
            self.cache[key] = out
        return self.cache[key]

    def last_meets(self, tid, oid):
        return [r for r in self.rows(tid, self.season - 1)
                if r["oid"] == oid and r["done"] and r["ts"] is not None and r["stype"] == 2]

    def remaining(self, tid, kick):
        return sum(1 for r in self.rows(tid, self.season)
                   if (r["kick"] or "") > kick and r["stype"] == 2 and not r["ctourney"])

    def home(self, tid):
        return home_info(self.rows(tid, self.season))


def _match(g, comps):
    """The slate's home and away teams among an ESPN event's competitors."""
    def hit(name, c):
        return any(_same_team(name, x) for x in (c["name"], c["loc"]) if x)
    for test in (lambda name, c: name == c["name"], hit):  # exact display name first ("Tennessee" vs "Tennessee State")
        h = [c for c in comps if test(g["home"], c)]
        a = [c for c in comps if test(g["away"], c)]
        if len(h) == 1 and len(a) == 1 and h[0] is not a[0]:
            return h[0], a[0]
        if len(h) == 1 and len(a) == 2 and h[0] in a:
            return h[0], next(c for c in a if c is not h[0])
        if len(a) == 1 and len(h) == 2 and a[0] in h:
            return next(c for c in h if c is not a[0]), a[0]
    # one side by name, the other by nickname ("Penn Quakers" = "Pennsylvania Quakers")
    nick = lambda name, c: name.split()[-1:] == (c["name"] or "").split()[-1:]  # noqa: E731
    for x, y in ((comps[0], comps[1]), (comps[1], comps[0])):
        if hit(g["home"], x) and nick(g["away"], y) and not hit(g["away"], x):
            return x, y
        if hit(g["away"], y) and nick(g["home"], x) and not hit(g["home"], y):
            return x, y
    return None


def storylines_for(live, date_str, g):
    """Storylines for one slate game (a list, possibly empty), or None when it
    can't be found on ESPN's D-I board for that date."""
    D = date.fromisoformat(date_str)
    evs = live.by_date.get(D, [])
    e = next((x for x in evs if str(g.get("espnId") or "") == x["id"]), None)
    if e is None:
        cands = [x for x in evs if len(x["comps"]) == 2 and _match(g, x["comps"])]
        if len(cands) != 1:
            return None
        e = cands[0]
    if len(e["comps"]) != 2 or _match(g, e["comps"]) is None:
        return None
    if e.get("stype") != 2 or conf_tourney(e, D):
        return []  # as backtested: regular season, no conference tournaments
    hc, ac = _match(g, e["comps"])
    hrow = next((r for r in live.rows.get(hc["id"], []) if r["eid"] == e["id"]), None)
    arow = next((r for r in live.rows.get(ac["id"], []) if r["eid"] == e["id"]), None)
    if hrow is None or arow is None:
        return None
    if not (hrow["rank"] or arow["rank"]):
        return []  # as backtested: games with an AP Top 25 team
    hs = _num(g.get("homeSpread"))
    if hs is None:
        return []  # graded at the closing spread; no line, no storyline
    # the slate's "home" is ESPN's listed home team; for a neutral site that's who ESPN lists first
    if not hrow["listed_home"]:
        hrow, arow, hs = arow, hrow, -hs
        names = {hrow["team"]: g["away"], arow["team"]: g["home"]}
    else:
        names = {hrow["team"]: g["home"], arow["team"]: g["away"]}
    for row in (hrow, arow):
        if live.homes.get(row["tid"], (None,))[0] is None:
            live.homes[row["tid"]] = live.schedules.home(row["tid"])  # no home game on the boards yet
    fired = game_stories(live.rows, live.polls, live.homes, hrow, arow, hs, live.schedules)
    out = []
    for key, row, fact in fired:
        me = names[row["team"]]
        opp = names[(arow if row is hrow else hrow)["team"]]
        out.append(entry(key, me, opp, fact))
    return out


def main():
    args = sys.argv[1:]
    dry = "--dry-run" in args
    backfill = "--backfill" in args
    include_final = "--include-final" in args or backfill
    if "--include-final" in args and not dry and not backfill:
        sys.exit("--include-final only works with --dry-run or --backfill (finished games keep their pre-tip storylines).")
    dates = [a for a in args if not a.startswith("--")] or [today_et_str()]
    session = espn.make_session()
    seasons = {}
    for date_str in dates:
        doc = store.read_doc("ncaab", date_str)
        if doc is None:
            print(f"{date_str}: no NCAAB slate.")
            continue
        todo = [g for g in doc.get("games", []) if g.get("away") and g.get("home")
                and (include_final or not isinstance(g.get("awayScore"), (int, float)))]
        if not todo:
            print(f"{date_str}: every game has started -- storylines left as they were.")
            continue
        D = date.fromisoformat(date_str)
        season = season_of(D)
        try:
            live = seasons.get(season)
            if live is None or max(live.by_date) < D + timedelta(days=5):
                live = seasons[season] = Season(session, season, max(D, date.fromisoformat(max(dates))) + timedelta(days=5))
        except Exception as exc:  # noqa: BLE001
            print(f"{date_str}: ESPN unreachable ({exc.__class__.__name__}: {exc}) -- storylines left as they were.")
            continue
        changed = 0
        for g in todo:
            try:
                new = storylines_for(live, date_str, g)
            except Exception as exc:  # noqa: BLE001
                print(f"  {g['away']} @ {g['home']}: skipped ({exc.__class__.__name__}: {exc})")
                continue
            if new is None:
                print(f"  {g['away']} @ {g['home']}: not found on ESPN's D-I board -- left as it was.")
                continue
            if new != (g.get("storylines") or []):
                if new:
                    g["storylines"] = new
                else:
                    g.pop("storylines", None)
                changed += 1
            for ent in new:
                print(f"  {g['away']} @ {g['home']}: {ent['name']} ({ent['team']}, {ent['says']}) -> leans {ent['leans']} "
                      f"{ent['leanPct']}% | {ent['fact']}")
        if changed and not dry:
            store.write_doc("ncaab", date_str, doc)
        print(f"{date_str}: storylines on {sum(1 for g in doc.get('games', []) if g.get('storylines'))} game(s)"
              f"{' (dry run, nothing written)' if dry else ''}.")


if __name__ == "__main__":
    main()
