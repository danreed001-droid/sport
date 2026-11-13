#!/usr/bin/env python3
"""CFB storylines: context for the pick sheet, never a pick. (DRAFT: data layer.)"""
import os
import re
import sys
from collections import Counter
from datetime import date, datetime
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ET = ZoneInfo("America/New_York")
SITE = "https://site.api.espn.com/apis/site/v2/sports/football/college-football"
CORE = "https://sports.core.api.espn.com/v2/sports/football/leagues/college-football"

FBS_CONF = {"1", "4", "5", "8", "9", "12", "15", "17", "18", "37", "151"}
NOTRE_DAME = "87"


# Traditional rivalries (ESPN's school names). Hard-coded: ESPN doesn't flag them.
RIVALRY_PAIRS = """Alabama|Auburn; Ohio State|Michigan; Texas|Oklahoma; Georgia|Florida; Georgia|Georgia Tech;
Clemson|South Carolina; Florida|Florida State; Florida State|Miami; USC|UCLA; USC|Notre Dame; Oregon|Oregon State;
Washington|Washington State; Stanford|California; LSU|Alabama; Ole Miss|Mississippi State; Texas|Texas A&M;
Tennessee|Alabama; Kentucky|Louisville; Tennessee|Vanderbilt; Iowa|Iowa State; Minnesota|Wisconsin;
Michigan|Michigan State; Pittsburgh|West Virginia; Penn State|Pittsburgh; Virginia|Virginia Tech; North Carolina|NC State;
North Carolina|Duke; Kansas|Kansas State; Kansas|Missouri; Oklahoma|Oklahoma State; Arizona|Arizona State; Utah|BYU;
Colorado|Colorado State; Army|Navy; Air Force|Army; Air Force|Navy; Indiana|Purdue; Illinois|Northwestern; Nebraska|Iowa;
Minnesota|Iowa; Wisconsin|Iowa; TCU|SMU; TCU|Baylor; Miami (OH)|Ohio; Toledo|Bowling Green; Oregon|Washington;
Arkansas|LSU; Auburn|Georgia; Notre Dame|Navy; Florida|Tennessee; Texas A&M|Arkansas; Missouri|Arkansas;
New Mexico|New Mexico State; Wyoming|Colorado State; Nevada|UNLV; Houston|Rice; Boise State|Fresno State; Texas|Texas Tech;
Michigan|Notre Dame; Louisiana|UL Monroe; Louisiana|Louisiana Monroe; Utah|Utah State; Cincinnati|Miami (OH);
Memphis|Ole Miss; Tulane|Southern Miss; Boston College|Syracuse; Duke|Wake Forest; Clemson|Georgia Tech"""
RIVALS = {frozenset(p.strip().split("|")) for p in RIVALRY_PAIRS.split(";")}


def is_power(conf, team_id, season):
    """ACC, Big Ten, Big 12, SEC (and the Pac-12 before 2024), plus Notre Dame."""
    return team_id == NOTRE_DAME or conf in {"1", "4", "5", "8"} or (conf == "9" and season < 2024)


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


def zone_of(city, state):
    return CITY_TZ.get((city, state)) or STATE_TZ.get(state)


def season_of(date_str):
    d = date.fromisoformat(date_str)
    return d.year if d.month >= 7 else d.year - 1


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
    """UTC ISO -> aware ET datetime, or None when ESPN's time is a placeholder."""
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return None
    return dt.astimezone(ET)


def known_time(iso, state):
    return bool(iso) and (state == "HI" or iso[11:16] not in ("03:59", "04:00", "04:59", "05:00"))


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
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


def record(rows):
    w = sum(1 for r in rows if r["ts"] > r["os"])
    return w, sum(1 for r in rows if r["ts"] < r["os"])


def game_context(rows_by_team, prev_rows_by_team, homes, ap_by_week, row, spread, rivals, kick_iso=None):
    """What a storyline may read about `row` (one team's side of a game), all
    known before kickoff: the season so far for both teams, the rest of the
    team's schedule (opponents and sites, not results), AP ranks this week, last
    week and in the preseason, and last season's meeting."""
    tid, oid = row["tid"], row["oid"]
    kick_iso = kick_iso or row["kick"]
    mine, theirs = rows_by_team.get(tid, []), rows_by_team.get(oid, [])
    prior = [r for r in mine if r["kick"] < kick_iso and r["ts"] is not None]
    oprior = [r for r in theirs if r["kick"] < kick_iso and r["ts"] is not None]
    later = [r for r in mine if r["kick"] > kick_iso and not r["title"]]
    wk = row["week"]
    now, prev, pre = ap_by_week.get(wk) or {}, ap_by_week.get(wk - 1) if wk > 1 else None, ap_by_week.get(1) or {}
    k = kickoff(kick_iso)
    vz = zone_of(row["city"], row["state"]) if row["site"] != "neutral" or row["state"] else None
    local_hour = None
    if k is not None and row["kick_known"] and vz:
        lk = k.astimezone(ZoneInfo(vz))
        local_hour = lk.hour + lk.minute / 60
    home = homes.get(tid) or (None, None, None)
    ohome = homes.get(oid) or (None, None, None)
    return {
        "season": row["season"], "week": wk, "date": row["date"], "D": date.fromisoformat(row["date"]), "kick": k,
        "et_hour": (k.hour + k.minute / 60) if (k is not None and row["kick_known"]) else None, "local_hour": local_hour,
        "tid": tid, "team": row["team"], "oid": oid, "opp": row["opp"], "site": row["site"], "city": row["city"],
        "state": row["state"], "venue_zone": vz, "sp": spread, "prior": prior, "oprior": oprior, "later": later,
        "rank": now.get(tid), "orank": now.get(oid), "now_ranks": now,
        "prev_rank": None if prev is None else prev.get(tid), "has_prev": prev is not None,
        "pre_rank": pre.get(tid), "opre_rank": pre.get(oid),
        "meets": [r for r in prev_rows_by_team.get(tid, []) if r["oid"] == oid and r["ts"] is not None],
        "home": home, "ohome": ohome, "conf": row["conf"], "oconf": row["oconf"],
        "power": is_power(row["conf"], tid, row["season"]), "opower": is_power(row["oconf"], oid, row["season"]),
        "rivalry": frozenset((row["team"], row["opp"])) in rivals, "row_confgame": bool(row["confgame"]),
        "prev_conf": (Counter(r["conf"] for r in prev_rows_by_team.get(tid, [])).most_common(1) or [(None, 0)])[0][0],
    }


# ---------------------------------------------------------------- live data

def _scoreboard_week(session, season, week, limits):
    evs = {}
    errors = 0
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


def fetch_season(session, season, limits=(1000, 500)):
    """Every FBS regular-season event of a season (played and scheduled),
    week by week, as the backtest read them."""
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
    """{team_id: AP rank} for the poll that applies to `week`'s games (week 1 =
    preseason). Raises if ESPN can't be reached, so a missing poll never reads
    as "unranked"."""
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
