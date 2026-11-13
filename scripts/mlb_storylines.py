#!/usr/bin/env python3
"""MLB storylines: context for the pick sheet, never a pick.

(docstring filled in below once the research is final)
"""
import os
import sys
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib import espn, store  # noqa: E402
from lib.dates import today_et_str  # noqa: E402
from score_slate import _same_team  # noqa: E402

ET = ZoneInfo("America/New_York")
SITE = "https://site.api.espn.com/apis/site/v2/sports/baseball/mlb"

# Hours behind Eastern during the season (Arizona doesn't observe daylight
# time, so it's on Pacific daylight time all season), by venue state/province.
_TZ_STATES = {
    0: "Maryland|Massachusetts|New York|Pennsylvania|Ohio|Michigan|Georgia|Florida|Ontario|District of Columbia|"
       "North Carolina|Tennessee|Puerto Rico|DC|MD|MA|NY|PA|OH|MI|GA|FL|ON|NC|TN|PR",
    1: "Illinois|Missouri|Wisconsin|Minnesota|Texas|Alabama|Iowa|Nebraska|IL|MO|WI|MN|TX|AL|IA|NE",
    2: "Colorado|CO",
    3: "Arizona|California|Washington|Oregon|Nevada|AZ|CA|WA|OR|NV",
}
STATE_TZ = {s: h for h, ss in _TZ_STATES.items() for s in ss.split("|")}
# ESPN abbreviation -> division (the Athletics are "OAK" before 2025, "ATH" after).
DIVISION = {t: d for d, ts in (("ALE", "BAL BOS NYY TB TOR"), ("ALC", "CHW CLE DET KC MIN"),
                               ("ALW", "LAA HOU OAK ATH SEA TEX"), ("NLE", "ATL MIA NYM PHI WSH"),
                               ("NLC", "CHC CIN MIL PIT STL"), ("NLW", "ARI COL LAD SD SF")) for t in ts.split()}


def _num(v):
    try:
        return float(str(v).replace("+", ""))
    except (TypeError, ValueError):
        return None


def pos(name):
    return name + ("'" if name.endswith("s") else "'s")


# ---------------------------------------------------------------- ESPN data

class Feed:
    """ESPN reads for one run, each cached: team schedules, game summaries,
    date scoreboards. Raises on a failed read (the caller skips the date)."""

    def __init__(self, session):
        self.s = session
        self._sched, self._sum, self._board = {}, {}, {}

    def _get(self, url):
        r = self.s.get(url, timeout=20)
        r.raise_for_status()
        return r.json()

    def board(self, date_str):
        if date_str not in self._board:
            self._board[date_str] = self._get(f"{SITE}/scoreboard?dates={date_str.replace('-', '')}&limit=100")
        return self._board[date_str]

    def schedule(self, team_id, season):
        k = (team_id, season)
        if k not in self._sched:
            j = self._get(f"{SITE}/teams/{team_id}/schedule?season={season}&seasontype=2")
            self._sched[k] = [e for e in (parse_event(ev) for ev in j.get("events", [])) if e]
        return self._sched[k]

    def summary(self, eid):
        if eid not in self._sum:
            self._sum[eid] = parse_summary(self._get(f"{SITE}/summary?event={eid}"))
        return self._sum[eid]


def parse_event(ev):
    """A scoreboard/schedule event -> {eid, start (ET), date, home, away
    (abbreviations), names, ids, venue, tz, neutral, state, hs, as}."""
    try:
        comp = ev["competitions"][0]
        t = {c["homeAway"]: c for c in comp["competitors"]}
        start = datetime.fromisoformat(ev["date"].replace("Z", "+00:00")).astimezone(ET)
    except (KeyError, IndexError, ValueError):
        return None
    venue = comp.get("venue") or {}
    addr = venue.get("address") or {}
    st = (comp.get("status") or ev.get("status") or {}).get("type") or {}

    def score(c):
        s = c.get("score")
        if isinstance(s, dict):
            s = s.get("value", s.get("displayValue"))
        return _num(s)

    return {"eid": str(ev["id"]), "start": start, "date": start.strftime("%Y-%m-%d"),
            "et_hour": start.hour + start.minute / 60,
            "home": t["home"]["team"].get("abbreviation"), "away": t["away"]["team"].get("abbreviation"),
            "home_name": t["home"]["team"].get("displayName"), "away_name": t["away"]["team"].get("displayName"),
            "home_id": str(t["home"]["team"].get("id")), "away_id": str(t["away"]["team"].get("id")),
            "venue": venue.get("fullName") or "",
            "tz": STATE_TZ.get(addr.get("state")), "neutral": bool(comp.get("neutralSite")),
            "state": st.get("name"), "completed": bool(st.get("completed")),
            "hs": score(t["home"]), "as": score(t["away"]),
            "season_type": (ev.get("seasonType") or {}).get("type") or (ev.get("season") or {}).get("type"),
            "probables": {side: ((t[side].get("probables") or [{}])[0].get("athlete") or {}) for side in ("home", "away")},
            "weather": ev.get("weather") or {}}


def parse_summary(j):
    """Line scores, hits and pitchers (in order: id, name, outs, er, r,
    pitches) per side ("home"/"away") from a game summary."""
    out = {"line": {}, "hits": {}, "pitchers": {}}
    comp = ((j.get("header") or {}).get("competitions") or [{}])[0]
    side_of = {}
    for c in comp.get("competitors") or []:
        side_of[str(c["team"]["id"])] = c["homeAway"]
        out["line"][c["homeAway"]] = [_num(x.get("displayValue", x.get("value"))) for x in c.get("linescores") or []]
        out["hits"][c["homeAway"]] = _num(c.get("hits"))
    for p in (j.get("boxscore") or {}).get("players") or []:
        side = side_of.get(str(p["team"]["id"]))
        for st in p.get("statistics") or []:
            if st.get("type") != "pitching":
                continue
            labels = st.get("labels") or []
            rows = []
            for a in st.get("athletes") or []:
                v = dict(zip(labels, a.get("stats") or []))
                ip = str(v.get("IP", "0"))
                whole, _, frac = ip.partition(".")
                outs = int(_num(whole) or 0) * 3 + int(_num(frac) or 0)
                rows.append({"id": str(a["athlete"]["id"]), "name": a["athlete"].get("displayName"), "outs": outs,
                             "er": _num(v.get("ER")) or 0, "r": _num(v.get("R")) or 0, "pitches": _num(v.get("PC")),
                             "starter": bool(a.get("starter"))})
            if side:
                out["pitchers"][side] = rows
    for side in ("home", "away"):  # hits from the batting box when the header lacks them
        if out["hits"].get(side) is None:
            for p in (j.get("boxscore") or {}).get("teams") or []:
                if side_of.get(str(p["team"]["id"])) == side:
                    for grp in p.get("statistics") or []:
                        for s in grp.get("stats") or []:
                            if s.get("name") == "hits" and out["hits"].get(side) is None:
                                out["hits"][side] = _num(s.get("value", s.get("displayValue")))
    return out
