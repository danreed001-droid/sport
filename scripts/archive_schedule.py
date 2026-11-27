#!/usr/bin/env python3
"""Every team's games, played and coming up, for the trend charts' "next 3
games" (after tonight's game, on the same calendar as the bars).

Writes data/raw/schedule/<sport>.json:
  {"fetched": ISO time of the last look ahead,
   "done": [past dates saved for good],
   "dates": {Eastern date: [[away, home, away record, home record, ESPN event id,
                             away score, home score, away and home points per period
                             (quarters, halves, innings; finished games, else None)], ...]}}
with ESPN's team names. A record is the team's overall record going into
that game: for a game not yet played, its record when it was last looked at
(the look ahead refreshes every few hours, so the night before it's current);
for a finished one, ESPN's record after it with the result taken back off.

Past dates are fetched once (back to the season's start, so a past slate in the
date picker shows the games that followed it); dates from today on are looked
at again every LOOKAHEAD_HOURS. NBA, NFL and MLB scoreboards come a month at a
time; college ones (which cap a month at 25 or 1,000 games) a day at a time;
soccer a month at a time per league (the combined soccer feed caps a month at
1,000 and mixes women's and youth sides under the same club names).
Run in the scoring workflow.

Neutral sites (2026-11-24, the user's ask after UCLA-Saint Mary's was shown as
a UCLA home game): every game ESPN flags `neutralSite` goes in
data/raw/neutral_sites.json, {sport: {event id: venue}}, read by build_site.py
(the card shows "Neutral site" instead of Away/Home, and the trend charts give
neither team a home border). `--neutral-backfill` reads the whole season's
scoreboards again for that file only (the schedule files are left alone).
"""
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import espn, props, store  # noqa: E402
from archive_linescores import record_before  # noqa: E402

ET = ZoneInfo("America/New_York")
OUT = os.path.join(store.REPO_ROOT, "data", "raw", "schedule")
NEUTRAL = os.path.join(store.REPO_ROOT, "data", "raw", "neutral_sites.json")
LOOKAHEAD_HOURS = 4
BASE = "https://site.api.espn.com/apis/site/v2/sports"
# sport: (season start, days ahead, "month" or "day", extra query)
CFG = {
    "nba": ("2026-10-01", 14, "month", ""),
    "nfl": ("2026-09-01", 35, "month", ""),
    "mlb": ("2026-03-01", 10, "month", ""),
    "cfb": ("2026-08-20", 30, "day", "&groups=80"),
    "ncaab": ("2026-11-01", 14, "day", "&groups=50"),
    "soccer": ("2026-08-01", 35, "month", ""),
}
SOCCER_LEAGUES = ("eng.1", "esp.1", "ita.1", "ger.1", "fra.1", "usa.1", "mex.1", "uefa.champions", "uefa.europa",
                  "uefa.europa.conf", "eng.2", "eng.league_cup", "eng.fa", "ned.1", "por.1", "bel.1", "tur.1",
                  "sau.1", "bra.1", "den.1", "nor.1", "aut.1", "aus.1", "pol.1", "conmebol.libertadores",
                  "conmebol.sudamericana", "esp.copa_del_rey", "ger.dfb_pokal", "ita.coppa_italia", "fra.coupe_de_france")


def _load(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        f.write("\n")


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _rec(c, other, completed, post):
    if completed:
        return record_before(c, other, post)
    rec = next((r for r in c.get("records") or [] if r.get("type") == "total" or r.get("name") == "overall"), None)
    return (rec or {}).get("summary") or None


def _events(session, path, query):
    """A scoreboard read at two page sizes and merged: ESPN's college football
    board returns only 25 games at limit=1000 (52 at limit=300 on 2026-10-17)."""
    got, ok = {}, False
    for lim in (1000, 300):
        try:
            evs = session.get(f"{BASE}/{path}/scoreboard?{query}&limit={lim}", timeout=30).json().get("events", []) or []
        except Exception as exc:  # noqa: BLE001
            print(f"{path} {query} limit={lim}: {exc.__class__.__name__}")
            continue
        ok = True
        for ev in evs:
            got.setdefault(str(ev.get("id")), ev)
    return list(got.values()) if ok else None


def _rows(evs):
    """{Eastern date: {event id: row}}, {Eastern date: every game on it finished},
    {event id: venue name or "" when ESPN flags it a neutral site, None when not}."""
    by, fin, neu = {}, {}, {}
    for ev in evs:
        comp = (ev.get("competitions") or [{}])[0]
        t = {c.get("homeAway"): c for c in comp.get("competitors") or []}
        if "home" not in t or "away" not in t:
            continue
        try:
            d = datetime.fromisoformat(ev["date"].replace("Z", "+00:00")).astimezone(ET).date().isoformat()
        except (KeyError, ValueError):
            continue
        st = ((comp.get("status") or ev.get("status") or {}).get("type") or {})
        if st.get("name") in ("STATUS_CANCELED", "STATUS_POSTPONED"):
            continue
        done = bool(st.get("completed"))
        post = (ev.get("season") or {}).get("type") == 3
        a, h = t["away"], t["home"]
        score = lambda c: _num(c.get("score")) if done else None  # noqa: E731
        per = lambda c: [_num(x.get("value")) for x in c.get("linescores") or []] if done else None  # noqa: E731
        pa, ph = per(a), per(h)
        if pa and ph and len(pa) == len(ph) + 1:
            ph = ph + [0.0]          # baseball: the home team didn't bat in the last inning
        if not pa or not ph or len(pa) != len(ph) or None in pa + ph:
            pa = ph = None
        by.setdefault(d, {})[str(ev["id"])] = [a["team"]["displayName"], h["team"]["displayName"],
                                               _rec(a, h, done, post), _rec(h, a, done, post), str(ev["id"]),
                                               score(a), score(h), pa, ph]
        fin[d] = fin.get(d, True) and done
        neu[str(ev["id"])] = ((comp.get("venue") or {}).get("fullName") or "") if comp.get("neutralSite") else None
    return by, fin, neu


def _months(start, end):
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        yield f"{y}{m:02d}"
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def main():
    os.makedirs(OUT, exist_ok=True)
    session = espn.make_session()
    now = datetime.now(timezone.utc)
    today = now.astimezone(ET).date()
    backfill = "--neutral-backfill" in sys.argv
    only = [a for a in sys.argv[1:] if a in CFG]
    neutral = _load(NEUTRAL)
    for sport, (start, ahead, mode, extra) in CFG.items():
        if only and sport not in only:
            continue
        path = os.path.join(OUT, f"{sport}.json")
        data = _load(path)
        dates, done = data.setdefault("dates", {}), set(data.get("done") or [])
        if backfill:
            done = set()
        # rows saved before final scores (5 fields) or period scores (7) were kept are fetched again once
        done -= {d for d in done if any(len(r) < 9 for r in dates.get(d) or [])}
        try:
            fresh = now - datetime.fromisoformat(data.get("fetched")) < timedelta(hours=LOOKAHEAD_HOURS)
        except (TypeError, ValueError):
            fresh = False
        fresh = fresh and not backfill
        first, last = date.fromisoformat(start), today + timedelta(days=ahead)
        if first > last:
            continue
        # what to fetch: past days not saved for good, and (unless looked at lately) today on
        if mode == "month":
            queries = []
            for ym in _months(first, last):
                y, m = int(ym[:4]), int(ym[4:])
                mdays = [date(y, m, 1) + timedelta(days=i) for i in range(31) if (date(y, m, 1) + timedelta(days=i)).month == m]
                past_open = any(d < today and d >= first and d.isoformat() not in done for d in mdays)
                ahead_in = any(d >= today for d in mdays)
                if past_open or (ahead_in and not fresh):
                    queries.append(f"dates={ym}")
        else:
            queries = []
            d = first
            while d <= last:
                if (d < today and d.isoformat() not in done) or (d >= today and not fresh):
                    queries.append(f"dates={d.strftime('%Y%m%d')}{extra}")
                d += timedelta(days=1)
            if len(queries) > 120 and not backfill:     # first run: backfill in pieces
                queries = queries[:60] + [q for q in queries if q[6:14] >= today.strftime("%Y%m%d")]
        if not queries:
            print(f"{sport}: nothing to fetch ({len(dates)} dates saved)")
            continue
        paths = [f"soccer/{lg}" for lg in SOCCER_LEAGUES] if sport == "soccer" else [props.espn_path(sport)]
        got, fin, ok = {}, {}, set()
        for q in queries:
            for p in paths:
                evs = _events(session, p, q)
                if evs is None:
                    continue
                ok.add(q)
                by, f, nv = _rows(evs)
                nmap = neutral.setdefault(sport, {})
                for eid, venue in nv.items():
                    if venue is None:
                        nmap.pop(eid, None)
                    else:
                        nmap[eid] = venue
                for d, games in by.items():
                    got.setdefault(d, {}).update(games)
                    fin[d] = fin.get(d, True) and f[d]
        if backfill:
            print(f"{sport}: neutral sites {len(neutral.get(sport, {}))}")
            continue
        # Which dates did those queries cover in full? (Only replace a date we saw whole.)
        covered = set()
        for q in ok:
            v = q[6:].split("&")[0]
            if len(v) == 6:
                y, m = int(v[:4]), int(v[4:])
                d = date(y, m, 1)
                while d.month == m:
                    covered.add(d.isoformat())
                    d += timedelta(days=1)
            else:
                covered.add(f"{v[:4]}-{v[4:6]}-{v[6:8]}")
        changed = 0
        for d in sorted(covered):
            if d < start or d in done:
                continue
            rows = sorted(got.get(d, {}).values(), key=lambda r: (r[1], r[0]))
            if dates.get(d) != rows:
                if rows:
                    dates[d] = rows
                else:
                    dates.pop(d, None)
                changed += 1
            if d < today.isoformat() and (fin.get(d, True)):
                done.add(d)
        if any(q[6:].split("&")[0] >= today.strftime("%Y%m%d")[:len(q[6:].split("&")[0])] for q in ok):
            data["fetched"] = now.isoformat(timespec="seconds")
        data["done"] = sorted(done)
        _save(path, data)
        print(f"{sport}: {len(queries)} scoreboard(s), {changed} date(s) changed; {len(dates)} dates saved")
    _save(NEUTRAL, neutral)


if __name__ == "__main__":
    main()
