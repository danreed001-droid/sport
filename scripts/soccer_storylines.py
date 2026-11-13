#!/usr/bin/env python3
"""Soccer storylines: context for the pick sheet, never a pick.

Each storyline is a situation a pundit would tell a story about (a Champions
League hangover, a derby-day underdog, a relegation dogfight at home, a team
"deflated" by a late equaliser). On 2026-11-13, 55 of them (45, then 10 more
on request) were tested on the 3-way moneyline for the Premier League, La
Liga, Bundesliga, Serie A, Ligue 1, MLS and Liga MX, regular season only:
2018-19 to 2025-26 in Europe, MLS 2019 and 2021-2026, Liga MX 2019-20 (to Feb
2020) and 2021-22 to Clausura 2026 (2019-20 after the restart, 2020-21's empty
stadiums, MLS 2020 and Liga MX 2020-21 left out). Results, goal minutes, red
cards, shots and every cup/European fixture come from ESPN's scoreboards;
prices are the pre-match 1X2 ESPN stored for each match (Bet365, else a US
book). "back" a team = it wins; "fade" = draw or loss, priced as the double
chance 1/(1/draw + 1/other) at the same book. The implied % is the no-vig
probability by the power method (proportional removal under-rated favourites
by ~3 points at 60-70% on this data). football-data.co.uk wasn't used: its
robots.txt bars Claude's crawlers.

It's noise: 1 of 55 reached p<0.05 against the price, where chance alone gives
2.2 (a game-level simulation of every match from its price). The four kept
here are the ones with 100+ matches whose hit % was 3+ points off the implied
% with a positive ROI on the favoured side, or p<0.05 -- and every one of them
points AGAINST its story (`against: true`): the favourite after an
international break, the MLS midweek road team, the side with nothing to play
for, and the team that played 120 minutes in a midweek cup all won MORE often
than priced. They're shown on the game card with their record and aren't
graded or counted anywhere. The research write-up (every storyline, per
season, split-half) was a scratch report, not kept in the repo.

Writes `storylines` onto each match of today's soccer slate (or the dates
given) in a covered league that hasn't started: [{key, name, team, says,
fact, record, pct, implied, roi, leans, leanPct, against, unit}], where `team`
is who the story is about, `says` the story's bet ("back" = to win, "fade" =
not to win), `record`/`pct`/`implied`/`roi` that bet's history (hits-misses,
hit %, average no-vig implied %, ROI % at the stored price), and `leans` +
`unit` + `leanPct` the bet history favours ("Arsenal" "to win" 75.2%). Once
a match has a score the entry is kept as it was before kick-off.
Usage: soccer_storylines.py [YYYY-MM-DD ...] [--dry-run [--include-final]]
(--dry-run prints without writing; --include-final also runs finished matches,
for testing on past slates.)
"""
import os
import sys
import time
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib import storyline_live  # noqa: E402
from lib import espn, store  # noqa: E402
from lib.dates import ET, today_et_str  # noqa: E402
from score_slate import _same_team, find_match_loose  # noqa: E402

EUROPE_LG = {"eng.1", "esp.1", "ger.1", "ita.1", "fra.1"}
DOMESTIC_CUPS = {"eng.fa", "eng.league_cup", "esp.copa_del_rey", "ger.dfb_pokal", "ita.coppa_italia",
                 "fra.coupe_de_france", "usa.open", "mex.copa_mx"}
# Other competitions whose matches count for rest and "last match" (as researched).
OTHER_COMPS = {
    "eng.1": ["uefa.champions", "uefa.europa", "uefa.europa.conf", "eng.fa", "eng.league_cup"],
    "esp.1": ["uefa.champions", "uefa.europa", "uefa.europa.conf", "esp.copa_del_rey", "esp.super_cup"],
    "ger.1": ["uefa.champions", "uefa.europa", "uefa.europa.conf", "ger.dfb_pokal", "ger.super_cup"],
    "ita.1": ["uefa.champions", "uefa.europa", "uefa.europa.conf", "ita.coppa_italia", "ita.super_cup"],
    "fra.1": ["uefa.champions", "uefa.europa", "uefa.europa.conf", "fra.coupe_de_france", "fra.super_cup"],
    "usa.1": ["concacaf.champions", "concacaf.leagues.cup", "usa.open"],
    "mex.1": ["concacaf.champions", "concacaf.leagues.cup"],
}
LEAGUE_NAME = {"eng.1": "Premier League", "esp.1": "La Liga", "ger.1": "Bundesliga", "ita.1": "Serie A",
               "fra.1": "Ligue 1", "usa.1": "MLS", "mex.1": "Liga MX"}
CUP_NAME = {"eng.fa": "FA Cup", "eng.league_cup": "League Cup", "esp.copa_del_rey": "Copa del Rey",
            "ger.dfb_pokal": "DFB-Pokal", "ita.coppa_italia": "Coppa Italia", "fra.coupe_de_france": "Coupe de France",
            "usa.open": "U.S. Open Cup", "mex.copa_mx": "Copa MX"}
DONE = {"STATUS_FULL_TIME", "STATUS_FINAL_AET", "STATUS_FINAL_PEN", "STATUS_FINAL"}

# Slate competition names (lower case, ", Matchday N" and "(...)" dropped) -> ESPN league.
COMPETITIONS = {
    "eng.1": {"premier league", "english premier league", "england's premier league", "epl", "england premier league"},
    "esp.1": {"la liga", "laliga", "spain's la liga", "spanish la liga", "laliga ea sports", "la liga ea sports"},
    "ger.1": {"bundesliga", "germany's bundesliga", "german bundesliga", "1. bundesliga"},
    "ita.1": {"serie a", "italy's serie a", "italian serie a", "serie a enilive"},
    "fra.1": {"ligue 1", "france's ligue 1", "french ligue 1", "ligue 1 mcdonald's"},
    "usa.1": {"mls", "major league soccer"},
    "mex.1": {"liga mx", "mexico's liga mx", "liga bbva mx"},
}

# key: (name, story's bet, (hits, misses) for that bet, implied %, ROI %, where it applies)
STORIES = {
    "intl_break_fav": ("International-break rust", "fade", (29, 88), 28.7, -20.6,
                       "first league match after a 12-20 day league break in Sep-Nov or March, favoured at 60%+"),
    "mls_midweek_road": ("Midweek road trip", "fade", (335, 142), 73.6, -10.2,
                         "MLS road team in a Tue-Thu (ET) match, 4.5 days or fewer after its last match"),
    "beach_vs_desperate": ("Beach mode vs desperation", "fade", (65, 59), 55.9, -11.8,
                           "safe (10+ pts above the drop) and 8+ pts off 6th with 6 or fewer games left, "
                           "vs a side within 3 pts of the drop (European leagues)"),
    "cup_120_midweek": ("120 minutes in midweek", "fade", (166, 140), 60.6, -13.7,
                        "played extra time / penalties in a domestic cup tie on a Tue-Thu, 4.5 days or fewer ago"),
}


def league_of(competition):
    s = (competition or "").split(",")[0].split("(")[0].strip().lower().replace("’", "'")
    for lg, names in COMPETITIONS.items():
        if s in names:
            return lg
    return "mex.1" if s.startswith("liga mx") else None


def regular(lg, e):
    slug = e.get("slug") or ""
    if lg == "usa.1":
        return slug == "regular-season"
    if lg == "mex.1":
        return slug.startswith("torneo")
    return not any(k in slug for k in ("playoff", "promotion", "relegation"))


STRONG = set()
WEAK = set()


def entry(key, team, fact):
    name, says, (w, n), implied, roi, _ = STORIES[key]
    lw, ln = storyline_live.live("soccer", key)  # graded since it went live
    w, n = w + lw, n + ln
    pct = 100 * w / (w + n)
    against = pct < implied
    favoured_back = (says == "back") != against
    return {"weight": 2 if key in STRONG else (0.5 if key in WEAK else 1), "live": f"{lw}-{ln}", "key": key, "name": name, "team": team, "says": says, "fact": fact, "record": f"{w}-{n}",
            "pct": round(pct, 1), "implied": implied, "roi": roi,
            "leans": team if pct != implied else None, "leanPct": round(100 - pct if against else pct, 1),
            "against": against, "unit": "to win" if favoured_back else "not to win"}


def decimal(ml):
    try:
        ml = float(ml)
    except (TypeError, ValueError):
        return None
    if ml == 0:
        return None
    return 1 + (ml / 100 if ml > 0 else 100 / -ml)


def power_probs(odds):
    """No-vig probabilities, power method (as researched)."""
    inv = [1 / o for o in odds]
    lo, hi = 1.0, 3.0
    for _ in range(60):
        k = (lo + hi) / 2
        if sum(x ** k for x in inv) > 1:
            lo = k
        else:
            hi = k
    return [x ** k for x in inv]


class Feed:
    """ESPN scoreboards by month, cached for the run. A failed fetch marks the
    run's data incomplete (`failed`) so existing storylines are left alone."""

    def __init__(self):
        self.session = espn.make_session()
        self.cache = {}
        self.failed = set()

    def month(self, slug, yyyymm):
        key = (slug, yyyymm)
        if key in self.cache:
            return self.cache[key]
        url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/scoreboard?dates={yyyymm}&limit=1000"
        events = None
        try:
            r = self.session.get(url, timeout=30)
            if r.status_code == 200:
                events = [c for c in (compact(e) for e in r.json().get("events", [])) if c]
            elif r.status_code in (400, 404):
                events = []  # competition not running that month
        except Exception as exc:  # noqa: BLE001
            print(f"  ESPN {slug} {yyyymm}: {exc}")
        if events is None:
            self.failed.add(slug)
            events = []
        self.cache[key] = events
        time.sleep(0.2)
        return events

    def events(self, slug, months):
        seen, out = set(), []
        for m in months:
            for e in self.month(slug, m):
                if e["id"] not in seen:
                    seen.add(e["id"])
                    out.append(e)
        return out


def compact(e):
    try:
        c = e["competitions"][0]
        side = {x["homeAway"]: x for x in c["competitors"]}
        st = e.get("status", {}).get("type", {})
        return {"id": str(e["id"]), "dt": datetime.fromisoformat(e["date"].replace("Z", "+00:00")),
                "slug": (e.get("season") or {}).get("slug", ""), "year": (e.get("season") or {}).get("year"),
                "status": st.get("name"), "home": side["home"]["team"]["displayName"], "hid": side["home"]["team"]["id"],
                "away": side["away"]["team"]["displayName"], "aid": side["away"]["team"]["id"],
                "hs": side["home"].get("score"), "as": side["away"].get("score")}
    except (KeyError, IndexError, TypeError, ValueError):
        return None


def months_between(d0, d1):
    out, y, m = [], d0.year, d0.month
    while (y, m) <= (d1.year, d1.month):
        out.append(f"{y}{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def score(e, tid):
    hs, as_ = int(e["hs"]), int(e["as"])
    return (hs, as_) if e["hid"] == tid else (as_, hs)


def table_facts(lg, ev, league_events, tid, oid):
    """The league table before the match's (UTC) day, as researched: points of
    the team and opponent above the top of the drop zone, points off 6th, and
    games left."""
    day = ev["dt"].date()
    season = [e for e in league_events if e["year"] == ev["year"] and regular(lg, e)]
    teams = {e["hid"] for e in season} | {e["aid"] for e in season}
    tb = {t: [0, 0, 0, 0] for t in teams}  # pts, gd, gf, gp
    for e in season:
        if e["status"] not in DONE or e["dt"].date() >= day:
            continue
        for t in (e["hid"], e["aid"]):
            gf, ga = score(e, t)
            x = tb[t]
            x[0] += 3 if gf > ga else (1 if gf == ga else 0)
            x[1] += gf - ga
            x[2] += gf
            x[3] += 1
    n = len(teams)
    if n < 16 or tid not in tb or oid not in tb:
        return None
    srt = sorted((x[0] for x in tb.values()), reverse=True)
    drop_n = 3 if n in (18, 20) else 2
    line = srt[n - drop_n]
    return {"n": n, "left": 2 * (n - 1) - tb[tid][3], "above": tb[tid][0] - line, "oabove": tb[oid][0] - line,
            "to6": srt[5] - tb[tid][0], "pts": tb[tid][0]}


def team_stories(lg, ev, tid, team, opp_name, is_home, timeline, league_events, p_win):
    out = []
    kick = ev["dt"]
    prior = [x for x in timeline if x[1]["dt"] < kick and x[1]["status"] in DONE]
    prev = prior[-1] if prior else None
    rest = (kick - prev[1]["dt"]).total_seconds() / 86400 if prev else None

    # International-break rust: favoured at 60%+ in the first league match after a 12-20 day league break.
    before = [e["dt"].date() for e in league_events if e["status"] in DONE and e["dt"].date() < kick.date()]
    gap = (kick.date() - max(before)).days if before else None
    if gap is not None and 12 <= gap <= 20 and kick.month in (9, 10, 11, 3) and p_win is not None and p_win >= 0.6:
        out.append(entry("intl_break_fav", team,
                         f"{team} is a {100 * p_win:.0f}% favourite in the {LEAGUE_NAME[lg]}'s first round after "
                         f"a {gap}-day break."))

    # Midweek road trip (MLS).
    if lg == "usa.1" and not is_home and rest is not None and rest <= 4.5 and kick.astimezone(ET).weekday() in (1, 2, 3):
        out.append(entry("mls_midweek_road", team,
                         f"{team} is on the road on a {kick.astimezone(ET).strftime('%A')}, "
                         f"{rest:.0f} days after its last match ({prev[1]['away'] if prev[1]['hid'] == tid else prev[1]['home']})."))

    # 120 minutes in midweek: extra time / penalties in a domestic cup tie, Tue-Thu, 4.5 days or fewer ago.
    if (prev and prev[0] in DOMESTIC_CUPS and prev[1]["status"] in ("STATUS_FINAL_AET", "STATUS_FINAL_PEN")
            and rest is not None and rest <= 4.5 and prev[1]["dt"].astimezone(ET).weekday() in (1, 2, 3)):
        p = prev[1]
        gf, ga = score(p, tid)
        other = p["away"] if p["hid"] == tid else p["home"]
        how = "on penalties" if p["status"] == "STATUS_FINAL_PEN" else "after extra time"
        out.append(entry("cup_120_midweek", team,
                         f"{team} played 120 minutes against {other} in the {CUP_NAME.get(prev[0], 'cup')} "
                         f"{rest:.0f} days ago ({gf}-{ga}, decided {how})."))
    return out


def storylines_for(feed, lg, date_str, g):
    """Entries for one slate match, or None when the data couldn't be read."""
    d = date.fromisoformat(date_str)
    months = months_between(d - timedelta(days=35), d + timedelta(days=1))
    league_events = feed.events(lg, months)
    if lg in feed.failed:
        return None
    rows = [{"Away_Team": e["away"], "Home_Team": e["home"], "ev": e} for e in league_events
            if e["dt"].astimezone(ET).date() == d]
    row, swapped = find_match_loose(rows, g)
    if row is None:
        # One side named alike and that team's only league match that day ("Stade Brestois 29" is ESPN's "Brest").
        hits = [(r, False) for r in rows if _same_team(g["home"], r["Home_Team"]) or _same_team(g["away"], r["Away_Team"])]
        hits += [(r, True) for r in rows if _same_team(g["home"], r["Away_Team"]) or _same_team(g["away"], r["Home_Team"])]
        if len({id(r) for r, _ in hits}) == 1 and len(hits) == 1:
            row, swapped = hits[0]
    if row is None:
        print(f"  {g['away']} @ {g['home']}: no ESPN {lg} match found")
        return []
    ev = row["ev"]
    if not regular(lg, ev):
        return []
    others = {c: feed.events(c, months) for c in OTHER_COMPS[lg]}
    if any(c in feed.failed for c in OTHER_COMPS[lg]):
        return None
    if lg in EUROPE_LG and ev["dt"].month in (3, 4, 5, 6):  # the table matters only late in the season
        y = ev["year"] or ev["dt"].year
        season_events = feed.events(lg, months_between(date(y, 7, 1), d))
        if lg in feed.failed:
            return None
    else:
        season_events = None

    def timeline(tid):
        out = [(lg, e) for e in league_events if tid in (e["hid"], e["aid"])]
        for c, evs in others.items():
            out += [(c, e) for e in evs if tid in (e["hid"], e["aid"])]
        return sorted(out, key=lambda x: x[1]["dt"])

    # Prices from the slate, mapped onto ESPN's home/away (the slate may list them reversed).
    o = [decimal(g.get(k)) for k in ("homeMoneyline", "drawMoneyline", "awayMoneyline")]
    ph = pa = None
    if all(o):
        ph, _, pa = power_probs(o)
        if swapped:
            ph, pa = pa, ph
    # Slate names for ESPN's home/away.
    name = {ev["hid"]: g["away"] if swapped else g["home"], ev["aid"]: g["home"] if swapped else g["away"]}
    out = []
    for tid, oid, is_home, p in ((ev["hid"], ev["aid"], True, ph), (ev["aid"], ev["hid"], False, pa)):
        out += team_stories(lg, ev, tid, name[tid], name[oid], is_home, timeline(tid), league_events, p)
        if season_events is not None:
            t = table_facts(lg, ev, season_events, tid, oid)
            if t and t["left"] <= 6 and t["above"] >= 10 and t["to6"] >= 8 and t["oabove"] <= 3:
                where = ("in the drop zone" if t["oabove"] < 0 else "level on points with it" if t["oabove"] == 0
                         else f"{t['oabove']} point{'s' if t['oabove'] != 1 else ''} above it")
                out.append(entry("beach_vs_desperate", name[tid],
                                 f"{name[tid]} is {t['above']} points clear of the drop zone and {t['to6']} off 6th with "
                                 f"{t['left']} games left; {name[oid]} is {where}."))
    return out


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    dry = "--dry-run" in sys.argv
    # Testing only: also run on matches that already have a score (needs --dry-run).
    redo = (dry or "--backfill" in sys.argv) and "--include-final" in sys.argv
    dates = args or [today_et_str()]
    feed = Feed()
    for date_str in dates:
        doc = store.read_doc("soccer", date_str)
        if doc is None:
            print(f"{date_str}: no soccer slate.")
            continue
        changed = 0
        for g in doc.get("games", []):
            lg = league_of(g.get("competition"))
            if not lg or not g.get("home") or not g.get("away"):
                continue
            if not redo and (isinstance(g.get("homeScore"), (int, float)) or isinstance(g.get("awayScore"), (int, float))):
                continue  # started or final: keep what was there before kick-off
            try:
                new = storylines_for(feed, lg, date_str, g)
            except Exception as exc:  # noqa: BLE001 -- one bad match must not cost the slate
                print(f"  {g['away']} @ {g['home']}: skipped ({exc})")
                new = None
            if new is None:
                print(f"  {g['away']} @ {g['home']}: ESPN unavailable, storylines left as they were")
                continue
            for e in new:
                print(f"  {g['away']} @ {g['home']}: {e['name']} ({e['team']}, story {e['says']}) -> history: "
                      f"{e['leans']} {e['unit']} {e['leanPct']}% -- {e['fact']}")
            if new != (g.get("storylines") or []):
                if new:
                    g["storylines"] = new
                else:
                    g.pop("storylines", None)
                changed += 1
        if changed and not dry:
            store.write_doc("soccer", date_str, doc)
        n = sum(1 for g in doc.get("games", []) if g.get("storylines"))
        print(f"{date_str}: storylines on {n} match(es){' (dry run, not written)' if dry else ''}.")


if __name__ == "__main__":
    main()
