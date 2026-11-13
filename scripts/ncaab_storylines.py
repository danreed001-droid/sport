#!/usr/bin/env python3
"""NCAA men's basketball storylines: context for the pick sheet, never a pick.

DOCSTRING_PLACEHOLDER
"""
import os
import statistics
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

STORIES_PLACEHOLDER


def pos(name):
    """Possessive: "Texas'" / "Duke's"."""
    return name + ("'" if name.endswith("s") else "'s")


STRONG_WEAK_PLACEHOLDER


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


def game_context(rows, polls, homes, row, spread, last_rows=None):
    """What a storyline may read about `row` (one team's side of a game), all
    known before tip-off: both teams' season so far, the team's remaining
    schedule (opponents, sites, dates -- not results), this week's and last
    week's AP poll and the preseason one, and last season's meetings."""
    w = row["week"]
    now = polls.get(w, {}) if w else {}
    prevw = w - 1 if w else None
    while prevw and prevw > 0 and prevw not in polls:
        prevw -= 1
    prev = polls.get(prevw) if prevw and prevw >= 1 else None
    mine, theirs = rows.get(row["tid"], []), rows.get(row["oid"], [])
    done = lambda r: r["kick"] < row["kick"] and r["done"] and r["stype"] == 2 and r["ts"] is not None  # noqa: E731
    prior = [r for r in mine if done(r)]
    return {"D": row["D"], "team": row["team"], "opp": row["opp"], "tid": row["tid"], "oid": row["oid"],
            "rank": now.get(row["tid"]), "orank": now.get(row["oid"]), "week": w,
            "prev_known": prev is not None, "prev_rank": (prev or {}).get(row["tid"]), "pre_rank": polls.get(1, {}).get(row["tid"]),
            "site": row["site"], "city": row["city"], "state": row["state"], "confgame": row["confgame"],
            "conf": row["conf"], "oconf": row["oconf"], "sp": spread, "prior": prior, "oprior": [r for r in theirs if done(r)],
            "later": [dict(r, orank_now=now.get(r["oid"])) for r in mine if r["kick"] > row["kick"] and r["stype"] == 2],
            "streak": streak_of(prior), "home": homes.get(row["tid"], (None, None, None)), "tv": row["tv"],
            "et_hour": row["et_hour"],
            "last_meets": [r for r in (last_rows or {}).get(row["tid"], [])
                           if r["oid"] == row["oid"] and r["done"] and r["ts"] is not None and r["stype"] == 2]}


TEAM_SIDE_PLACEHOLDER


def game_stories(rows, polls, homes, home_row, away_row, home_spread, last_rows=None):
    """[(key, team row, fact)] for one game; a story that points at both teams
    is dropped (the backtest skipped those)."""
    fired = []
    for row, sp in ((home_row, home_spread), (away_row, None if home_spread is None else -home_spread)):
        c = game_context(rows, polls, homes, row, sp, last_rows)
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
        with ThreadPoolExecutor(4) as ex:
            self.by_date = dict(zip(days, ex.map(fetch_day, days)))
        self.polls, dated = fetch_polls(session, season)
        self.weeks = map_weeks(self.by_date, self.polls, dated)
        self.rows = season_rows(self.by_date, self.polls, self.weeks)
        self.homes = {tid: home_info(rs) for tid, rs in self.rows.items()}
        self.last_rows = None

    def need_last_season(self):
        if self.last_rows is None:
            s0 = self.season - 1
            start, end = date(s0 - 1, 11, 1), date(s0, 3, 20)
            days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
            with ThreadPoolExecutor(4) as ex:
                by_date = dict(zip(days, ex.map(fetch_day, days)))
            self.last_rows = season_rows(by_date, {}, {})
            # a team with no home game yet this season: last season's floor
            for tid, rs in self.last_rows.items():
                if self.homes.get(tid, (None,))[0] is None:
                    self.homes[tid] = home_info(rs)
        return self.last_rows


def _match(g, comps):
    """The slate's home and away teams among an ESPN event's competitors."""
    def hit(name, c):
        return any(_same_team(name, x) for x in (c["name"], c["loc"]) if x)
    h = [c for c in comps if hit(g["home"], c)]
    a = [c for c in comps if hit(g["away"], c)]
    if len(h) == 1 and len(a) == 1 and h[0] is not a[0]:
        return h[0], a[0]
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
    last_rows = live.need_last_season() if NEEDS_LAST_SEASON else None
    fired = game_stories(live.rows, live.polls, live.homes, hrow, arow, hs, last_rows)
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
            if live is None or max(live.by_date) < D:
                live = seasons[season] = Season(session, season, max(D, date.fromisoformat(max(dates))))
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
