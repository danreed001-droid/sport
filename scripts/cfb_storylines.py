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
    """{team_id: IANA zone of its usual home stadium} from its non-neutral home games."""
    seen = {}
    for rows_by_team in row_sets:
        for tid, rows in rows_by_team.items():
            for r in rows:
                if r["site"] == "home":
                    z = zone_of(r["city"], r["state"])
                    if z:
                        seen.setdefault(tid, Counter())[(z, r["city"])] += 1
    return {tid: c.most_common(1)[0][0] for tid, c in seen.items()}
