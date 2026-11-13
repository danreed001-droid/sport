#!/usr/bin/env python3
"""MLB storylines: context for the pick sheet, never a pick.

Each storyline is a situation a baseball writer could tell a story about (a
starter "shaking off the rust" after a month out, a team "running on fumes"
after a 14-inning game last night, "split the doubleheader"). 46 of them were
tested on 2026-11-13 on every regular-season game from 2015 to 2025, with the
2020 60-game empty-stadium season reported separately and left out of the
numbers below. The bet is the moneyline at the closing price ("back" a team =
it wins; "fade" = its opponent wins); the story's record is compared with the
average no-vig implied probability of the closing odds, and ROI is the return
per $1 at those odds. Neutral-site games (London, Mexico City, Tokyo, Seoul,
Field of Dreams, Williamsport, Rickwood, ...) were left out, and a story that
pointed at both teams in one game was skipped for that game.

Data: Retrosheet's per-season CSV files (game info, line scores, team and
pitcher lines; pitch counts summed from its play-by-play) for the game
context, closing moneylines from SportsbookReviewsOnline's MLB archive
(2015-2021) and ESPN's core odds API (2022-2025; ESPN BET's close where it
has one). "The information used here was obtained free of charge from and is
copyrighted by Retrosheet."

Only 1 of the 46 was at p<0.05 against the implied odds; about 2.3 would be
expected by chance (simulating every season from its own closing odds), so as
a group they're no better than luck, and the market already prices nearly
every classic angle (getaway day, Coors hangover, bullpen burned, sweep
attempts, walk-offs, the stopper, revenge vs an old team, ...). These four
are the ones with 100+ games whose win rate beat the implied odds by 3+
points (with a positive return), or p<0.05 -- by chance about 6 of the 46
would pass that filter, so even these are probably mostly noise. None is a
model: they're shown on the game card with their record and aren't graded or
counted anywhere.

  rust            fade a team whose starter last pitched 21+ days ago (and has
                  pitched this season): 559-443, 55.8% vs 52.4% implied, ROI
                  +3.3%, p=0.029; even years 55.9/52.6, odd 55.7/52.3; it
                  climbs with the layoff (14+ days 53.5/51.7, 30+ 56.3/52.2,
                  60+ 58.4/52.9). The only one at p<0.05, and the steadiest.
  dh_split        back the team that lost game 1 in game 2 of a doubleheader:
                  189-165, 53.4% vs 48.9%, ROI +5.2%, p=0.086.
  ace_vs_ace      back the underdog when both starters have a 3.00-or-better
                  ERA on 60+ innings: 111-126, 46.8% vs 42.7%, ROI +5.0%,
                  p=0.19; even years 50.5/41.9 but odd years 43.8/43.3, and
                  not steady across thresholds (2.50/30 IP: 45.7/42.7; 3.50/60
                  IP: 43.4/42.4).
  extra_hangover  fade a team that played 12+ innings yesterday (and its
                  opponent didn't): 77-69, 52.7% vs 48.9%, ROI +1.2%, p=0.35;
                  10+ innings 54.4/50.5 but 13+ 50.0/49.2, so no steady trend.

Live, from ESPN before first pitch: today's scoreboard (regular season,
neutral site, probable starters), each team's season schedule (results and
doubleheaders), yesterday's scoreboard (innings) and each probable starter's
game log (appearances, innings and earned runs this season). The backtest
used the actual starter; live uses ESPN's probable, so a late switch changes
what fires until the next run. Game 2 of a doubleheader only gets "split the
doubleheader" once game 1 is final, which can be after the last run before
game 2. The underdog for "ace vs ace" is from the slate's moneylines. Run
over the 2024 and 2025 seasons from ESPN's data (each game's starters and
closing odds standing in for the probables and the slate), this script fired
on the same games as the backtest: 165 of 165 in 2024, 155 of 156 in 2025
(the one miss: ESPN's probable wasn't the pitcher who started).

Writes `storylines` onto each game of today's MLB slate (or the dates given)
that hasn't started: [{key, name, team, says, fact, record, pct, implied,
roi, leans, leanPct, against, unit}], where `team` is who the story is about,
`says` is the story's bet ("back"/"fade" that team), `record`/`pct` that
bet's history to win (`unit`), `implied` the average no-vig implied % of its
closing odds, `roi` its return at those odds, and `leans`/`leanPct` the side
history favors and how often that side won. Once a game has a score the
entry is kept as it was before first pitch. If ESPN can't be reached,
nothing is changed.

Usage: python scripts/mlb_storylines.py [--dry-run] [--include-final] [YYYY-MM-DD ...]
  --dry-run        print what fires, write nothing
  --include-final  (with --dry-run only) also evaluate games that have a score
"""
import os
import sys
from datetime import date, datetime
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib import espn, store  # noqa: E402
from lib.dates import today_et_str  # noqa: E402
from score_slate import _same_team  # noqa: E402

ET = ZoneInfo("America/New_York")
SITE = "https://site.api.espn.com/apis/site/v2/sports/baseball/mlb"
GAMELOG = "https://site.web.api.espn.com/apis/common/v3/sports/baseball/mlb/athletes/{}/gamelog?season={}"

# key: (name, story's bet, (wins, losses) for that bet, avg no-vig implied %, ROI % at closing odds, games where it
# applies) -- 2015-2025 regular season without 2020, closing moneyline.
STORIES = {
    "rust": ("Rust", "fade", (559, 443), 52.4, 3.3,
             "today's starter hasn't pitched in 21+ days (and has pitched this season)"),
    "dh_split": ("Split the doubleheader", "back", (189, 165), 48.9, 5.2, "lost game 1 of a doubleheader, now game 2"),
    "ace_vs_ace": ("Ace vs ace: take the dog", "back", (111, 126), 42.7, 5.0,
                   "the underdog when both starters have a 3.00-or-better ERA on 60+ innings"),
    "extra_hangover": ("Extra-innings hangover", "fade", (77, 69), 48.9, 1.2, "played 12+ innings yesterday"),
}
RUST_DAYS = 21
ACE_ERA, ACE_OUTS = 3.00, 180
EXTRA_INNINGS = 12


def _num(v):
    try:
        return float(str(v).replace("+", ""))
    except (TypeError, ValueError):
        return None


def pos(name):
    """Possessive: "Twins'" / "Phillies'"."""
    return name + ("'" if name.endswith("s") else "'s")


def ip_text(outs):
    return f"{outs // 3}.{outs % 3}"


def entry(key, team, opp, fact):
    name, says, (w, l_), imp, roi, _ = STORIES[key]
    pct = 100 * w / (w + l_)
    beat = pct > imp  # the story's bet beat the odds
    lean = (team if says == "back" else opp) if beat else (opp if says == "back" else team)
    if pct == imp:
        lean = None
    return {"key": key, "name": name, "team": team, "says": says, "fact": fact, "record": f"{w}-{l_}",
            "pct": round(pct, 1), "implied": imp, "roi": roi, "leans": lean,
            "leanPct": round(pct if beat else 100 - pct, 1), "against": not beat, "unit": "to win"}


# ---------------------------------------------------------------- ESPN data

class Feed:
    """ESPN reads for one run, each cached: date scoreboards, team schedules,
    pitcher game logs. Each raises on a failed read."""

    def __init__(self, session):
        self.s = session
        self._board, self._sched, self._log = {}, {}, {}

    def _get(self, url):
        r = self.s.get(url, timeout=20)
        r.raise_for_status()
        return r.json()

    def board(self, date_str):
        if date_str not in self._board:
            j = self._get(f"{SITE}/scoreboard?dates={date_str.replace('-', '')}&limit=100")
            self._board[date_str] = [e for e in (parse_event(ev) for ev in j.get("events", [])) if e]
        return self._board[date_str]

    def schedule(self, team_id, season):
        k = (team_id, season)
        if k not in self._sched:
            j = self._get(f"{SITE}/teams/{team_id}/schedule?season={season}&seasontype=2")
            self._sched[k] = sorted((e for e in (parse_event(ev) for ev in j.get("events", [])) if e),
                                    key=lambda e: e["start"])
        return self._sched[k]

    def gamelog(self, athlete_id, season):
        k = (athlete_id, season)
        if k not in self._log:
            self._log[k] = parse_gamelog(self._get(GAMELOG.format(athlete_id, season)))
        return self._log[k]


def parse_event(ev):
    """A scoreboard or team-schedule event -> {eid, start (ET), date, home,
    away (ESPN ids), names, neutral, state, completed, hs, as, season_type,
    innings, probables {home/away: (id, name)}}."""
    try:
        comp = ev["competitions"][0]
        t = {c["homeAway"]: c for c in comp["competitors"]}
        start = datetime.fromisoformat(ev["date"].replace("Z", "+00:00")).astimezone(ET)
    except (KeyError, IndexError, TypeError, ValueError):
        return None
    status = comp.get("status") or ev.get("status") or {}
    st = status.get("type") or {}

    def score(c):
        s = c.get("score")
        if isinstance(s, dict):
            s = s.get("value", s.get("displayValue"))
        return _num(s)

    def probable(c):
        a = ((c.get("probables") or [{}])[0] or {}).get("athlete") or {}
        return (str(a["id"]), a.get("displayName") or a.get("fullName")) if a.get("id") else None

    lines = [len(c.get("linescores") or []) for c in t.values()]
    return {"eid": str(ev["id"]), "start": start, "date": start.strftime("%Y-%m-%d"),
            "home": str(t["home"]["team"].get("id")), "away": str(t["away"]["team"].get("id")),
            "home_name": t["home"]["team"].get("displayName"), "away_name": t["away"]["team"].get("displayName"),
            "neutral": bool(comp.get("neutralSite")), "state": st.get("name"), "completed": bool(st.get("completed")),
            "hs": score(t["home"]), "as": score(t["away"]),
            "season_type": (ev.get("seasonType") or {}).get("type") or (ev.get("season") or {}).get("type"),
            "innings": max(lines + [int(status.get("period") or 0)]),
            "probables": {"home": probable(t["home"]), "away": probable(t["away"])}}


def parse_gamelog(j):
    """Regular-season appearances: [(start ET, outs, earned runs)], oldest
    first. ESPN files the All-Star Game under the regular season: left out."""
    labels = j.get("labels") or []
    events = j.get("events") or {}
    out = []
    for stype in j.get("seasonTypes") or []:
        if "regular" not in (stype.get("displayName") or "").lower():
            continue
        for cat in stype.get("categories") or []:
            for e in cat.get("events") or []:
                v = dict(zip(labels, e.get("stats") or []))
                info = events.get(str(e.get("eventId"))) or {}
                when = info.get("gameDate")
                if (not when or (info.get("team") or {}).get("isAllStar") or (info.get("opponent") or {}).get("isAllStar")
                        or "all-star" in (info.get("eventNote") or "").lower()):
                    continue
                whole, _, frac = str(v.get("IP", "0")).partition(".")
                out.append((datetime.fromisoformat(when.replace("Z", "+00:00")).astimezone(ET),
                            int(_num(whole) or 0) * 3 + int(_num(frac) or 0), _num(v.get("ER")) or 0))
    return sorted(out)


def season_of(date_str):
    return int(date_str[:4])


def prior_games(feed, team_id, ev):
    """The team's completed regular-season games before this one, oldest first."""
    return [e for e in feed.schedule(team_id, season_of(ev["date"]))
            if e["completed"] and e["eid"] != ev["eid"] and e["start"] < ev["start"]
            and e["hs"] is not None and e["as"] is not None]


def pitcher_form(feed, athlete_id, ev):
    """(appearances before this game this season, outs, earned runs) for a starter."""
    apps = [a for a in feed.gamelog(athlete_id, season_of(ev["date"])) if a[0] < ev["start"]]
    return apps, sum(a[1] for a in apps), sum(a[2] for a in apps)


def storylines_for(feed, ev, g):
    """Storylines for one slate game, from its ESPN event."""
    if ev["neutral"]:
        return []  # as backtested: neutral-site games left out
    D = date.fromisoformat(ev["date"])
    out = []
    names = {ev["home"]: g["home"], ev["away"]: g["away"]}
    form = {}
    for side in ("home", "away"):
        p = ev["probables"][side]
        if p:  # a failed read raises: the caller leaves the game as it was
            form[side] = (p[1], pitcher_form(feed, p[0], ev))
    for side, other in (("home", "away"), ("away", "home")):
        tid, oid = ev[side], ev[other]
        team, opp = names[tid], names[oid]
        prior = prior_games(feed, tid, ev)
        last = prior[-1] if prior else None
        if last:
            lh = last["home"] == tid
            rf, ra = (last["hs"], last["as"]) if lh else (last["as"], last["hs"])
            lopp = last["away_name"] if lh else last["home_name"]
            if last["date"] == ev["date"] and rf < ra:
                out.append(entry("dh_split", team, opp, f"{team} lost game 1 of today's doubleheader to {lopp} "
                                                        f"{rf:g}-{ra:g}."))
            if (D - date.fromisoformat(last["date"])).days == 1:
                yb = next((e for e in feed.board(last["date"]) if e["eid"] == last["eid"]), None)
                inn = yb["innings"] if yb else last["innings"]
                if inn >= EXTRA_INNINGS:
                    out.append(entry("extra_hangover", team, opp, f"{team} played {inn} innings against {lopp} yesterday "
                                                                  f"({'won' if rf > ra else 'lost'} {rf:g}-{ra:g})."))
        if side in form:
            pname, (apps, _, _) = form[side]
            if apps:
                gap = (D - apps[-1][0].date()).days
                if gap >= RUST_DAYS:
                    out.append(entry("rust", team, opp, f"{pos(team)} starter {pname} last pitched in a big-league game "
                                                        f"on {apps[-1][0].strftime('%Y-%m-%d')}, {gap} days ago."))
    hml, aml = _num(g.get("homeMoneyline")), _num(g.get("awayMoneyline"))
    if len(form) == 2 and hml is not None and aml is not None and hml != aml:
        aces = []
        for side in ("away", "home"):
            pname, (_, outs, er) = form[side]
            if outs >= ACE_OUTS and 27 * er / outs <= ACE_ERA:
                aces.append(f"{pname} ({27 * er / outs:.2f} ERA in {ip_text(outs)} innings)")
        if len(aces) == 2:
            dog, fav, ml = (g["home"], g["away"], hml) if hml > aml else (g["away"], g["home"], aml)
            out.append(entry("ace_vs_ace", dog, fav, f"{aces[0]} vs {aces[1]}; {dog} is the underdog at {ml:+g}."))
    # A story that points at both teams in one game says nothing: drop it
    # (the backtest skipped those games).
    sides = {}
    for e in out:
        sides.setdefault(e["key"], set()).add(e["team"] if e["says"] == "back" else
                                              (g["away"] if e["team"] == g["home"] else g["home"]))
    return [e for e in out if len(sides[e["key"]]) == 1]


def find_event(events, g):
    """The ESPN event for a slate game (a doubleheader by the slate's time)."""
    hits = [e for e in events if _same_team(g["home"], e["home_name"]) and _same_team(g["away"], e["away_name"])]
    if len(hits) <= 1:
        return hits[0] if hits else None
    try:
        t, ampm = str(g.get("time")).replace("ET", "").split()[:2]
        h, m = (t.split(":") + ["0"])[:2]
        mins = (int(h) % 12 + (12 if ampm.upper() == "PM" else 0)) * 60 + int(m)
        return min(hits, key=lambda e: abs(e["start"].hour * 60 + e["start"].minute - mins))
    except (ValueError, AttributeError):
        return next((e for e in hits if not e["completed"]), hits[0])


def main():
    args = sys.argv[1:]
    dry = "--dry-run" in args
    include_final = "--include-final" in args
    if include_final and not dry:
        sys.exit("--include-final only works with --dry-run (finished games keep their pre-game storylines).")
    dates = [a for a in args if not a.startswith("--")] or [today_et_str()]
    feed = Feed(espn.make_session())
    for date_str in dates:
        doc = store.read_doc("mlb", date_str)
        if doc is None:
            print(f"{date_str}: no MLB slate.")
            continue
        try:
            events = feed.board(date_str)
        except Exception as exc:  # noqa: BLE001
            print(f"{date_str}: ESPN unreachable ({exc.__class__.__name__}) -- storylines left as they were.")
            continue
        changed = 0
        for g in doc.get("games", []):
            if not g.get("away") or not g.get("home"):
                continue
            if isinstance(g.get("awayScore"), (int, float)) and not include_final:
                continue  # started or final: keep what was there before first pitch
            ev = find_event(events, g)
            if ev is None:
                print(f"  {g['away']} @ {g['home']}: not on ESPN's board for {date_str} -- left as it was.")
                continue
            if ev["season_type"] != 2:
                new = []  # regular season only
            else:
                try:
                    new = storylines_for(feed, ev, g)
                except Exception as exc:  # noqa: BLE001
                    print(f"  {g['away']} @ {g['home']}: skipped ({exc.__class__.__name__}: {exc})")
                    continue
            if new != (g.get("storylines") or []):
                if new:
                    g["storylines"] = new
                else:
                    g.pop("storylines", None)
                changed += 1
            for e in new:
                print(f"  {g['away']} @ {g['home']}: {e['name']} ({e['team']}, {e['says']}) -> leans {e['leans']} "
                      f"{e['leanPct']}% (implied {e['implied']}%) | {e['fact']}")
        if changed and not dry:
            store.write_doc("mlb", date_str, doc)
        print(f"{date_str}: storylines on {sum(1 for g in doc.get('games', []) if g.get('storylines'))} game(s)"
              f"{' (dry run, nothing written)' if dry else ''}.")


if __name__ == "__main__":
    main()
