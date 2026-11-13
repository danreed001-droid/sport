#!/usr/bin/env python3
"""College football storylines: context for the pick sheet, never a pick.

Each storyline is a situation a sportswriter could tell a story about (a
warm-weather team "freezing" on a November road trip, a team "hung over" after
upsetting a top-10 team, a top-5 team "laying 30"). 53 of them were tested on
2026-11-13, in two rounds (43, then 10 more), on every FBS-vs-FBS regular-season
game from 2015 to 2025 with a closing spread (7,169 games; conference
championship games left out; the 2020 COVID season reported separately and
left out of the numbers below). Data: ESPN's weekly FBS scoreboards (scores,
quarter scores, overtime, site, venue, conference game), ESPN's AP poll for
each week (the poll a week's games were played under; week 1 = preseason) and
ESPN's closing spreads (core odds API: ESPN BET's line for 2023-25, else the
median of the sportsbooks listed). The story's bet was graded against the
closing spread, pushes left out, and a story that pointed at both teams in one
game was skipped for that game. None of the 53 was at p<0.05 (about 2.7 would
be expected by chance), so as a group they're no better than luck. These are
the 14 where history leaned 53%+ one way on 50+ games -- which side that is can
be the opposite of what the story says (a team favored by 28+ the week after a
loss "angry giant" covered only 44.9%; the story says back it, so it's marked
`against`). Several are barely over the bar on small samples (altitude 85
games, angry giant 78). They're shown on the game card with their record and
aren't graded or counted anywhere.

Not tested, because these feeds don't carry them: coaching changes and coaches
facing former schools, homecoming, and turnovers (box scores only, too many
pages to fetch). Rivalries were tested from a hard-coded list of 68 pairs, and
underdogs in them covered 50.3%, so they aren't shown. A team's home stadium
(time zone, city, state) came from all seasons in the backtest and comes from
this season's home games live (last season's for a team with none yet).

Writes `storylines` onto each game of today's CFB slate (or the dates given)
that hasn't started: [{key, name, team, says, fact, record, pct, leans,
leanPct, against, unit}], where `team` is who the story is about, `says` is
the story's bet ("back"/"fade" that team), `record`/`pct` are that bet's
history ATS (`unit`), and `leans`/`leanPct` the side history favors. Once a
game has a score the entry is kept as it was before kickoff. Each team's games
come from ESPN's weekly FBS regular-season scoreboards (as in the backtest),
the AP poll from ESPN's rankings, tonight's spread from the slate's homeSpread,
and the closing spreads of a team's earlier games (for "can't buy a cover")
from ESPN's core odds API. Bowl games, conference championship games and
games involving an FCS team get none (as backtested). If ESPN can't be
reached, nothing is changed.

Usage: python scripts/cfb_storylines.py [--dry-run] [--include-final] [YYYY-MM-DD ...]
  --dry-run        print what fires, write nothing
  --include-final  (with --dry-run only) also evaluate games that have a score
"""
import os
import re
import statistics
import sys
from collections import Counter
from datetime import date, datetime
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib import espn, store  # noqa: E402
from lib.dates import today_et_str  # noqa: E402

ET = ZoneInfo("America/New_York")
SITE = "https://site.api.espn.com/apis/site/v2/sports/football/college-football"
CORE = "https://sports.core.api.espn.com/v2/sports/football/leagues/college-football"

# key: (name, story's bet, wins-losses for that bet 2015-2025 without 2020, games where it applies)
STORIES = {
    "first_road": ("Leaving the nest", "fade", (183, 211), "its first road game after 3+ straight at home"),
    "altitude": ("Thin air", "fade", (46, 39),
                 "an Eastern/Central-time team on the road at Air Force, Wyoming, Colorado, Colorado State, Utah State, "
                 "BYU, Utah, New Mexico or Nevada"),
    "cold_nov": ("Cold-weather trip", "fade", (53, 41),
                 "a team from a warm state (FL, TX, LA, AZ, CA, HI, GA, AL, MS, SC) on the road in a cold state, "
                 "November or later"),
    "upset_hangover": ("Upset hangover", "fade", (89, 69), "beat a top-10 team ranked above it in its last game"),
    "fell_out": ("Fell out of the poll", "back", (145, 122), "ranked in last week's AP poll, unranked this week"),
    "top5_huge": ("Top-5 laying 30", "fade", (65, 56), "an AP top-5 team favored by 30+"),
    "unranked_fav": ("Vegas knows", "back", (67, 58), "unranked but favored over an AP-ranked team"),
    "perfect_pressure": ("Weight of perfection", "fade", (49, 41), "undefeated with 7+ wins, November or later, favored by 14+"),
    "unlucky_close": ("Snakebit", "back", (171, 147), "3+ losses by 8 or fewer and no wins by 8 or fewer (5+ games)"),
    "ats_cold": ("Can't buy a cover", "back", (309, 271), "failed to cover its last four games with a closing line"),
    "fifty_win": ("Fifty-burger", "fade", (130, 156), "won its last game by 50+"),
    "angry_big_fav": ("Angry giant", "back", (35, 43), "favored by 28+ after losing its last game"),
    "held_on": ("Held on for dear life", "fade", (70, 57), "won its last game despite being outscored by 14+ in the 4th quarter"),
    "controls_destiny": ("Controls its destiny", "back", (106, 120),
                         "week 11 or later, unbeaten in conference play with 4+ conference wins, in a conference game"),
}

FBS_CONF = {"1", "4", "5", "8", "9", "12", "15", "17", "18", "37", "151"}  # ESPN conference ids
NOTRE_DAME = "87"
WARM = set("FL TX LA AZ CA HI GA AL MS SC".split())
COLD = set("MN WI MI IA NE OH PA IN IL NY MA CT NJ ND SD WY CO UT ID MT ME NH VT RI".split())
ALT_CITIES = {"Colorado Springs", "USAF Academy", "Air Force Academy", "Laramie", "Boulder", "Fort Collins", "Logan",
              "Provo", "Salt Lake City", "Albuquerque", "Reno"}

STATE_TZ = {}
for _z, _states in (("America/New_York", "CT DE DC FL GA IN KY ME MD MA MI NH NJ NY NC OH PA RI SC VT VA WV"),
                    ("America/Chicago", "AL AR IL IA KS LA MN MS MO NE ND OK SD TN TX WI"),
                    ("America/Denver", "CO MT NM UT WY ID"), ("America/Phoenix", "AZ"),
                    ("America/Los_Angeles", "CA NV OR WA"), ("America/Anchorage", "AK"), ("Pacific/Honolulu", "HI")):
    for _s in _states.split():
        STATE_TZ[_s] = _z
CITY_TZ = {("El Paso", "TX"): "America/Denver", ("Knoxville", "TN"): "America/New_York",
           ("Chattanooga", "TN"): "America/New_York", ("Johnson City", "TN"): "America/New_York",
           ("Bowling Green", "KY"): "America/Chicago", ("Moscow", "ID"): "America/Los_Angeles",
           ("Pensacola", "FL"): "America/Chicago"}
# Hours behind Eastern (standard time; Arizona counts as Mountain).
ZONE_BEHIND = {"America/New_York": 0, "America/Chicago": 1, "America/Denver": 2, "America/Phoenix": 2,
               "America/Los_Angeles": 3, "America/Anchorage": 4, "Pacific/Honolulu": 5}


def is_power(conf, team_id, season):
    """ACC, Big Ten, Big 12, SEC (and the Pac-12 before 2024), plus Notre Dame."""
    return team_id == NOTRE_DAME or conf in {"1", "4", "5", "8"} or (conf == "9" and season < 2024)


def zone_of(city, state):
    return CITY_TZ.get((city, state)) or STATE_TZ.get(state)


def season_of(date_str):
    d = date.fromisoformat(date_str)
    return d.year if d.month >= 7 else d.year - 1


def pos(name):
    """Possessive: "Texas'" / "Iowa's"."""
    return name + ("'" if name.endswith("s") else "'s")


def entry(key, team, opp, fact):
    name, says, (w, l), _ = STORIES[key]
    pct = 100 * w / (w + l)
    lean, lean_pct = (team, pct) if (pct > 50) == (says == "back") else (opp, 100 - pct)
    if pct == 50:
        lean = None
    return {"key": key, "name": name, "team": team, "says": says, "fact": fact, "record": f"{w}-{l}", "pct": round(pct, 1),
            "leans": lean, "leanPct": round(max(pct, 100 - pct), 1), "against": pct < 50, "unit": "ATS"}


# ---------------------------------------------------------------- game data

def trim_event(e, week):
    """The parts of an ESPN scoreboard event the storylines use."""
    c = e["competitions"][0]
    comps = []
    for t in c["competitors"]:
        tm = t.get("team") or {}
        comps.append({"id": tm.get("id"), "loc": tm.get("location"), "name": tm.get("displayName"),
                      "abbr": tm.get("abbreviation"), "conf": tm.get("conferenceId"), "ha": t.get("homeAway"),
                      "score": t.get("score"), "ls": [x.get("value", x.get("displayValue")) for x in t.get("linescores", [])],
                      "rank": (t.get("curatedRank") or {}).get("current")})
    v = c.get("venue") or {}
    return {"id": e["id"], "date": c.get("date") or e.get("date"), "week": week, "neutral": c.get("neutralSite"),
            "confgame": c.get("conferenceCompetition"), "venue": v.get("fullName"), "city": (v.get("address") or {}).get("city"),
            "state": (v.get("address") or {}).get("state"), "notes": [n.get("headline") for n in c.get("notes", [])],
            "completed": c.get("status", {}).get("type", {}).get("completed"), "comps": comps}


def kickoff(iso):
    """UTC ISO -> aware ET datetime, or None."""
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return None
    return dt.astimezone(ET)


def known_time(iso, state):
    """False when ESPN's time is a midnight-ET placeholder (time TBA)."""
    return bool(iso) and (state == "HI" or iso[11:16] not in ("03:59", "04:00", "04:59", "05:00"))


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


NON_BOOKS = {"opening", "consensus", "numberfire", "teamrankings", "accuscore"}


def closing_spread(items):
    """Home spread from ESPN core odds items [{p, spread}]: ESPN BET's line when
    listed (its `spread` is the close), else the median of the sportsbooks'
    (no openers, consensus, projections or live odds), else a projection."""
    for it in items:
        if it.get("p") == "ESPN BET" and it.get("spread") is not None:
            return it["spread"]
    books = [it["spread"] for it in items if it.get("spread") is not None
             and (it.get("p") or "").lower() not in NON_BOOKS and "live" not in (it.get("p") or "").lower()]
    if books:
        return round(statistics.median(books) * 2) / 2
    for fb in ("teamrankings", "numberfire", "accuscore", "consensus"):
        for it in items:
            if (it.get("p") or "").lower() == fb and it.get("spread") is not None:
                return it["spread"]
    return None


def season_rows(events, season, ap_by_week, spreads=None):
    """{team_id: [row, ...]} oldest first: every game (played or scheduled) of the
    season from the team's side. `ap_by_week[w]` is {team_id: AP rank} for the
    poll that applies to week w's games; `spreads` {event_id: home spread}."""
    spreads = spreads or {}
    out = {}
    for e in events:
        if len(e["comps"]) != 2:
            continue
        home = next((c for c in e["comps"] if c["ha"] == "home"), e["comps"][0])
        away = next((c for c in e["comps"] if c is not home), e["comps"][1])
        k = kickoff(e["date"])
        if k is None:
            continue
        ap = ap_by_week.get(e["week"]) or {}
        hs = spreads.get(e["id"])
        title = any("championship" in (n or "").lower() for n in e.get("notes") or []) and e["week"] >= 13
        done = bool(e.get("completed"))
        for me, op in ((home, away), (away, home)):
            site = "neutral" if e.get("neutral") else ("home" if me is home else "away")
            out.setdefault(me["id"], []).append({
                "eid": e["id"], "season": season, "week": e["week"], "date": k.strftime("%Y-%m-%d"), "kick": e["date"],
                "kick_known": known_time(e["date"], e.get("state")), "site": site, "is_home_listed": me is home,
                "team": me["loc"], "tid": me["id"], "conf": me["conf"], "oid": op["id"], "opp": op["loc"], "oconf": op["conf"],
                "ts": _num(me["score"]) if done else None, "os": _num(op["score"]) if done else None,
                "tls": [_num(x) for x in me["ls"]] if done else [], "ols": [_num(x) for x in op["ls"]] if done else [],
                "rank": ap.get(me["id"]), "orank": ap.get(op["id"]),
                "spread": None if hs is None else (hs if me is home else -hs),
                "state": e.get("state"), "city": e.get("city"), "confgame": e.get("confgame"), "title": title,
                "notes": e.get("notes") or [],
            })
    for rows in out.values():
        rows.sort(key=lambda r: r["kick"])
    return out


def home_zones(*row_sets):
    """{team_id: (IANA zone, city, state) of its usual home stadium}, from its
    non-neutral home games."""
    seen = {}
    for rows_by_team in row_sets:
        for tid, rows in rows_by_team.items():
            for r in rows:
                if r["site"] == "home":
                    z = zone_of(r["city"], r["state"])
                    if z:
                        seen.setdefault(tid, Counter())[(z, r["city"], r["state"])] += 1
    return {tid: c.most_common(1)[0][0] for tid, c in seen.items()}


def game_context(rows_by_team, prev_rows_by_team, homes, ap_by_week, row, spread, rivals=frozenset()):
    """What a storyline may read about `row` (one team's side of a game), all
    known before kickoff: the season so far for both teams, the rest of the
    team's schedule (opponents and sites, not results), AP ranks this week, last
    week and in the preseason, and last season's meetings."""
    tid, oid = row["tid"], row["oid"]
    kick_iso = row["kick"]
    mine, theirs = rows_by_team.get(tid, []), rows_by_team.get(oid, [])
    prior = [r for r in mine if r["kick"] < kick_iso and r["ts"] is not None]
    oprior = [r for r in theirs if r["kick"] < kick_iso and r["ts"] is not None]
    later = [r for r in mine if r["kick"] > kick_iso and not r["title"]]
    wk = row["week"]
    now, prev, pre = ap_by_week.get(wk) or {}, ap_by_week.get(wk - 1) if wk > 1 else None, ap_by_week.get(1) or {}
    k = kickoff(kick_iso)
    vz = zone_of(row["city"], row["state"])
    local_hour = None
    if k is not None and row["kick_known"] and vz:
        lk = k.astimezone(ZoneInfo(vz))
        local_hour = lk.hour + lk.minute / 60
    return {
        "season": row["season"], "week": wk, "date": row["date"], "D": date.fromisoformat(row["date"]), "kick": k,
        "et_hour": (k.hour + k.minute / 60) if (k is not None and row["kick_known"]) else None, "local_hour": local_hour,
        "tid": tid, "team": row["team"], "oid": oid, "opp": row["opp"], "site": row["site"], "city": row["city"],
        "state": row["state"], "venue_zone": vz, "sp": spread, "prior": prior, "oprior": oprior, "later": later,
        "rank": now.get(tid), "orank": now.get(oid), "now_ranks": now,
        "prev_rank": None if prev is None else prev.get(tid), "has_prev": prev is not None,
        "pre_rank": pre.get(tid), "opre_rank": pre.get(oid),
        "meets": [r for r in prev_rows_by_team.get(tid, []) if r["oid"] == oid and r["ts"] is not None],
        "home": homes.get(tid) or (None, None, None), "ohome": homes.get(oid) or (None, None, None),
        "conf": row["conf"], "oconf": row["oconf"],
        "power": is_power(row["conf"], tid, row["season"]), "opower": is_power(row["oconf"], oid, row["season"]),
        "rivalry": frozenset((row["team"], row["opp"])) in rivals, "row_confgame": bool(row["confgame"]),
        "prev_conf": (Counter(r["conf"] for r in prev_rows_by_team.get(tid, [])).most_common(1) or [(None, 0)])[0][0],
    }


# ---------------------------------------------------------------- the storylines

def _margin(r):
    return r["ts"] - r["os"]


def _rec(rows):
    return sum(1 for r in rows if r["ts"] > r["os"]), sum(1 for r in rows if r["ts"] < r["os"])


def team_side(c, spread_of=lambda r: r["spread"]):
    """[(key, fact)] for the team in context `c` (game_context). `spread_of(row)`
    gives an earlier game's closing spread from the team's side (or None)."""
    out = []
    P, sp, D = c["prior"], c["sp"], c["D"]
    last = P[-1] if P else None
    home_z, home_city, home_state = c["home"]
    T, Op = c["team"], c["opp"]
    vz = c["venue_zone"]

    if c["site"] == "away" and P:
        hs = 0
        for r in reversed(P):
            if r["site"] != "home":
                break
            hs += 1
        if hs >= 3:
            out.append(("first_road", f"{pos(T)} first road game after {hs} straight at home."))
    if c["site"] == "away" and home_z and vz:
        if c["city"] in ALT_CITIES and home_city not in ALT_CITIES and home_z in ("America/New_York", "America/Chicago"):
            out.append(("altitude", f"{T} plays at altitude in {c['city']}, {c['state']}."))
        if D.month >= 11 and home_state in WARM and c["state"] in COLD:
            out.append(("cold_nov", f"{T} ({home_state}) plays in {c['city']}, {c['state']} in {D.strftime('%B')}."))
    rk, ork = c["rank"], c["orank"]
    if last and _margin(last) > 0 and last["orank"] and last["orank"] <= 10 and (last["rank"] is None or last["rank"] > last["orank"]):
        who = f"#{last['rank']}" if last["rank"] else "unranked"
        out.append(("upset_hangover", f"{T} ({who} then) beat #{last['orank']} {last['opp']} {last['ts']:g}-{last['os']:g} "
                                      f"in its last game."))
    if c["has_prev"] and c["prev_rank"] and not rk:
        out.append(("fell_out", f"{T} was #{c['prev_rank']} in last week's AP poll and is unranked this week."))
    if rk and rk <= 5 and sp is not None and sp <= -30:
        out.append(("top5_huge", f"#{rk} {T} is a {sp:+g} favorite."))
    if not rk and ork and sp is not None and sp < 0:
        out.append(("unranked_fav", f"Unranked {T} is a {sp:+g} favorite over #{ork} {Op}."))
    w, l = _rec(P) if P else (0, 0)
    if l == 0 and w >= 7 and D.month >= 11 and sp is not None and sp <= -14:
        out.append(("perfect_pressure", f"{T} is {w}-0 and a {sp:+g} favorite."))
    if len(P) >= 5:
        cw = sum(1 for r in P if 0 < _margin(r) <= 8)
        cl = sum(1 for r in P if -8 <= _margin(r) < 0)
        if cl >= 3 and cw == 0:
            out.append(("unlucky_close", f"{T} ({w}-{l}) has lost {cl} games by 8 or fewer and won none that close."))
    lined = []
    for r in reversed(P):  # its last four games with a closing line (pushes skipped)
        s = spread_of(r)
        if s is not None and _margin(r) + s != 0:
            lined.append((r, s))
            if len(lined) == 4:
                break
    if len(lined) == 4 and not any(_margin(r) + s > 0 for r, s in lined):
        out.append(("ats_cold", f"{T} has failed to cover its last four "
                                f"({', '.join(f'{r['opp']} {s:+g}' for r, s in lined)})."))
    if last and _margin(last) >= 50:
        out.append(("fifty_win", f"{T} beat {last['opp']} {last['ts']:g}-{last['os']:g} in its last game."))
    if last and _margin(last) < 0 and sp is not None and sp <= -28:
        out.append(("angry_big_fav", f"{T} lost to {last['opp']} {last['ts']:g}-{last['os']:g} and is a {sp:+g} favorite."))
    if last and _margin(last) > 0 and len(last["tls"]) >= 4 and len(last["ols"]) >= 4 \
            and None not in (last["tls"][3], last["ols"][3]) and last["ols"][3] - last["tls"][3] >= 14:
        out.append(("held_on", f"{T} beat {last['opp']} {last['ts']:g}-{last['os']:g} after being outscored "
                               f"{last['ols'][3]:g}-{last['tls'][3]:g} in the 4th quarter."))
    if c["week"] >= 11 and c["row_confgame"]:
        cw = sum(1 for r in P if r["confgame"] and _margin(r) > 0)
        cl = sum(1 for r in P if r["confgame"] and _margin(r) < 0)
        if cw >= 4 and cl == 0:
            out.append(("controls_destiny", f"{T} is {cw}-0 in conference play."))
    return out


def game_stories(rows_by_team, prev_rows_by_team, homes, ap_by_week, home_row, away_row, home_spread,
                 spread_of=lambda r: r["spread"]):
    """[(key, team row, fact)] for one game, a story that points at both teams
    dropped (the backtest skipped those)."""
    fired = []
    for row, sp in ((home_row, home_spread), (away_row, None if home_spread is None else -home_spread)):
        ctx = game_context(rows_by_team, prev_rows_by_team, homes, ap_by_week, row, sp)
        fired += [(k, row, fact) for k, fact in team_side(ctx, spread_of)]
    keys = Counter(k for k, _, _ in fired)
    return [f for f in fired if keys[f[0]] == 1]


# ---------------------------------------------------------------- live

def _scoreboard_week(session, season, week, limits):
    evs, errors = {}, 0
    for limit in limits:
        url = f"{SITE}/scoreboard?dates={season}&seasontype=2&week={week}&groups=80&limit={limit}"
        try:
            r = session.get(url, timeout=20)
            r.raise_for_status()
            for e in r.json().get("events", []):
                if e.get("id") and e.get("competitions"):
                    evs.setdefault(str(e["id"]), trim_event(e, week))
        except Exception:  # noqa: BLE001
            errors += 1
    if errors == len(limits):
        raise RuntimeError(f"ESPN scoreboard {season} week {week} unreachable")
    return list(evs.values())


def fetch_season(session, season, limits=espn.SCOREBOARD_LIMITS):
    """Every FBS regular-season event of a season (played and scheduled), week by week."""
    events, empty = [], 0
    for wk in range(1, 18):
        evs = _scoreboard_week(session, season, wk, limits)
        if not evs:
            empty += 1
            if wk > 12 and empty >= 2:
                break
            continue
        empty = 0
        events += evs
    return events


def fetch_ap(session, season, week):
    """{team_id: AP rank} for the poll `week`'s games are played under (week 1
    = preseason). Raises when ESPN can't be reached or has no poll, so a
    missing poll never reads as "unranked"."""
    urls = [f"{CORE}/seasons/{season}/types/2/weeks/{week}/rankings/1"]
    if week == 1:
        urls.append(f"{CORE}/seasons/{season}/types/1/weeks/1/rankings/1")
    for url in urls:
        r = session.get(url, timeout=20)
        if r.status_code == 404:
            continue
        r.raise_for_status()
        ranks = r.json().get("ranks") or []
        if ranks:
            return {rk["team"]["$ref"].split("/teams/")[1].split("?")[0]: rk["current"] for rk in ranks}
    raise RuntimeError(f"no AP poll for {season} week {week}")


class LiveSpreads:
    """Closing spreads of earlier games from ESPN's core odds API, fetched only
    when a storyline asks (newest first) and kept for the run."""

    def __init__(self, session):
        self.session, self.home = session, {}

    def __call__(self, row):
        eid = row["eid"]
        if eid not in self.home:
            try:
                r = self.session.get(f"{CORE}/events/{eid}/competitions/{eid}/odds?limit=50", timeout=20)
                items = r.json().get("items", []) if r.status_code == 200 else []
                self.home[eid] = closing_spread([{"p": (it.get("provider") or {}).get("name"), "spread": it.get("spread")}
                                                 for it in items])
            except Exception:  # noqa: BLE001
                raise RuntimeError(f"ESPN odds for {eid} unreachable")
        hs = self.home[eid]
        return None if hs is None else (hs if row["is_home_listed"] else -hs)


def _norm(s):
    s = (s or "").lower().replace("'", "").replace("’", "").replace(".", "").replace("&", " and ")
    s = re.sub(r"[^a-z0-9() ]+", " ", s)
    return " ".join(s.split())


ALIASES = {"pitt": "pittsburgh", "umass": "massachusetts", "connecticut": "uconn", "miami (fl)": "miami",
           "miami fl": "miami", "mississippi": "ole miss", "louisiana monroe": "ul monroe", "ulm": "ul monroe",
           "appalachian state": "app state", "southern mississippi": "southern miss", "north carolina state": "nc state",
           "fiu": "florida international", "sam houston state": "sam houston"}


def same_school(slate_name, comp):
    """A slate's school name vs an ESPN competitor: exact on ESPN's location,
    abbreviation or full name (after aliases), so "Miami" never matches
    "Miami (OH)"."""
    n = _norm(slate_name)
    n = ALIASES.get(n, n)
    return n in {_norm(comp["loc"]), _norm(comp["abbr"]), _norm(comp["name"])}


class Season:
    """One season's live data, fetched once per run."""

    def __init__(self, session, season):
        self.session, self.season = session, season
        self.events = fetch_season(session, season)
        self.weeks = sorted({e["week"] for e in self.events})
        self.ap = {}
        self.rows = {}
        self.homes = {}
        self.last_homes = None  # last season's, fetched only for a team with no home game yet
        self.spreads = LiveSpreads(session)

    def prepare(self, through_week):
        """AP polls for weeks 1..through_week, then the team rows and homes."""
        for w in range(1, through_week + 1):
            if w not in self.ap and w in self.weeks:
                self.ap[w] = fetch_ap(self.session, self.season, w)
        self.rows = season_rows(self.events, self.season, self.ap)
        self._merge_homes()

    def _merge_homes(self):
        self.homes = dict(self.last_homes or {})
        self.homes.update(home_zones(self.rows))

    def add_last_season_homes(self):
        if self.last_homes is None:
            prev = season_rows(fetch_season(self.session, self.season - 1, limits=(500,)), self.season - 1, {})
            self.last_homes = home_zones(prev)
            self._merge_homes()


def storylines_for(live, date_str, g):
    """Storylines for one slate game (a list, possibly empty), or None when it
    isn't an FBS regular-season game on ESPN's board for that date."""
    today = [e for e in live.events if (kickoff(e["date"]) or datetime.min.replace(tzinfo=ET)).strftime("%Y-%m-%d") == date_str]
    match = [e for e in today if len(e["comps"]) == 2
             and any(same_school(g["home"], c) for c in e["comps"]) and any(same_school(g["away"], c) for c in e["comps"])]
    if len(match) != 1:
        return None
    e = match[0]
    if any(c["conf"] not in FBS_CONF for c in e["comps"]):
        return []  # as backtested: FBS vs FBS only
    if any("championship" in (n or "").lower() for n in e.get("notes") or []) and e["week"] >= 13:
        return []  # conference championship games were left out
    if any(w not in live.ap for w in range(1, e["week"] + 1) if w in live.weeks):
        live.prepare(e["week"])
    slate_home = next(c for c in e["comps"] if same_school(g["home"], c))
    slate_away = next(c for c in e["comps"] if c is not slate_home)
    if slate_home["id"] not in live.homes or slate_away["id"] not in live.homes:
        live.add_last_season_homes()
    hrow = next(r for r in live.rows[slate_home["id"]] if r["eid"] == e["id"])
    arow = next(r for r in live.rows[slate_away["id"]] if r["eid"] == e["id"])
    hs = _num(g.get("homeSpread"))
    fired = game_stories(live.rows, {}, live.homes, live.ap, hrow, arow, hs, live.spreads)
    names = {slate_home["loc"]: g["home"], slate_away["loc"]: g["away"]}  # name teams as the slate does
    out = []
    for key, row, fact in fired:
        opp = g["away"] if row is hrow else g["home"]
        ent = entry(key, names[row["team"]], opp, fact)
        out.append(ent)
    return out


def main():
    args = sys.argv[1:]
    dry = "--dry-run" in args
    include_final = "--include-final" in args
    if include_final and not dry:
        sys.exit("--include-final only works with --dry-run (finished games keep their pre-kickoff storylines).")
    dates = [a for a in args if not a.startswith("--")] or [today_et_str()]
    session = espn.make_session()
    seasons = {}
    for date_str in dates:
        doc = store.read_doc("cfb", date_str)
        if doc is None:
            print(f"{date_str}: no CFB slate.")
            continue
        todo = [g for g in doc.get("games", []) if g.get("away") and g.get("home")
                and (include_final or not isinstance(g.get("awayScore"), (int, float)))]
        if not todo:
            print(f"{date_str}: every game has started -- storylines left as they were.")
            continue
        season = season_of(date_str)
        try:
            if season not in seasons:
                seasons[season] = Season(session, season)
            live = seasons[season]
        except Exception as exc:  # noqa: BLE001
            print(f"{date_str}: ESPN unreachable ({exc.__class__.__name__}) -- storylines left as they were.")
            continue
        changed = 0
        for g in todo:
            try:
                new = storylines_for(live, date_str, g)
            except Exception as exc:  # noqa: BLE001
                print(f"  {g['away']} @ {g['home']}: skipped ({exc.__class__.__name__}: {exc})")
                continue
            if new is None:
                print(f"  {g['away']} @ {g['home']}: not an FBS regular-season game on ESPN's board -- left as it was.")
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
            store.write_doc("cfb", date_str, doc)
        print(f"{date_str}: storylines on {sum(1 for g in doc.get('games', []) if g.get('storylines'))} game(s)"
              f"{' (dry run, nothing written)' if dry else ''}.")


if __name__ == "__main__":
    main()
