#!/usr/bin/env python3
"""Builds the GitHub Pages pick sheet: copies site/index.html and writes
data.json with the latest slate, the season scoreboard for the Ledger, the
Second Opinion, the NFL/CFB-only Trend check and Blowout check, and your own
picks (data/mypicks/, each tagged with the models that agreed or disagreed),
and your picks on the latest slate, plus how your category grading has
held up (lib/grading_patterns.py, shown on site/grading.html).

Usage: python scripts/build_site.py [--out _site]
"""
import glob
import hashlib
import csv
import json
import re
import os
import shutil
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))
from lib import grading_patterns, manual, sports, store  # noqa: E402
from lib.nba_stats_rules import RULE_BACKTEST, RULE_NAMES, STACKED_BACKTEST  # noqa: E402
from lib.nba_stats_rules import families as nba_families  # noqa: E402
from lib import nba_totals_rules, ncaab_stats_rules, nfl_stats_rules, storyline_buckets  # noqa: E402
from lib.results import build_results, lead_minutes, results_csv  # noqa: E402
from lib import props as props_lib  # noqa: E402
from lib.picks import game_id, grade, grade_total, is_final, line_for, mine_view, ml_skip, side_of, stats_view, team_for  # noqa: E402

REPO = os.environ.get("GITHUB_REPOSITORY", "danreed001-droid/sport")
SLATE_FIELDS = [
    "away", "home", "time", "awayPitcher", "homePitcher", "statLines",
    "pick", "confidence", "skipped", "skipReason",
    "altPick", "altConfidence", "altCategoryTally", "altReasons",
    "altTrendCheck", "altBlowoutCheck", "altTrendFavors", "altBlowoutFavors",
    "statsFavors", "statsCheck", "statsRules", "nflStatsFavors", "nflStatsCheck", "nflStatsRules",
    "ncaabStatsFavors", "ncaabStatsCheck", "ncaabStatsRules",
    "competition", "awayMoneyline", "homeMoneyline", "drawMoneyline", "awaySpread", "homeSpread", "awaySpreadOdds", "homeSpreadOdds",
    "awayScore", "homeScore", "manualFields",
    "totalsLine", "totalsFavors", "totalsCheck", "totalsRules", "statsWatch", "statsLine", "totalsWatch",
    "gameTotal", "gameTotalOverOdds", "gameTotalUnderOdds", "storylines",
]





# How a game's storylines did by the size of their weighted net lean (the
# card's tally), this season's finished games; lib/storyline_buckets.py has
# the backtest per sport, and the page shows both and the two together.
def storyline_strength(all_docs):
    out = {}
    for sport in ("nba", "nfl", "cfb", "ncaab", "mlb", "soccer"):
        rec = {b: [0, 0, 0] for b in storyline_buckets.BUCKETS}
        for _, doc in all_docs.get(sport, []):
            for g in doc.get("games", []):
                if not g.get("storylines") or not is_final(doc, g):
                    continue
                net = storyline_buckets.net_toward_home(g)
                if net == 0:
                    continue
                margin = g["homeScore"] - g["awayScore"]
                if sport in ("mlb", "soccer"):
                    res = margin
                else:
                    hs = g.get("statsSpread") if sport == "nba" and isinstance(g.get("statsSpread"), (int, float)) else g.get("homeSpread")
                    if not isinstance(hs, (int, float)):
                        continue
                    res = margin + hs
                b = storyline_buckets.bucket(net)
                if res == 0:
                    rec[b][1 if sport == "soccer" else 2] += 1  # soccer: a draw means the leaned team didn't win
                else:
                    rec[b][0 if (res > 0) == (net > 0) else 1] += 1
        if any(sum(v) for v in rec.values()):
            out[sport] = rec
    return out



# ATS trend on the game cards: each slate team's last N graded games (football
# 7, basketball 14) from the sport's slate files -- the cover margin (margin +
# the team's spread; NBA at statsSpread when it has one) per game. College
# slates don't hold every game a team plays, so those trends also read the lines file.
TREND_GAMES = {"nfl": 7, "cfb": 7, "nba": 14, "ncaab": 14, "mlb": 14, "soccer": 7}
# Sports whose trend games may have no spread (MLB's run line is on about half
# the slate games; soccer has none): those games still give a win margin.
NO_LINE_OK = ("mlb", "soccer")


def _team_key(name):
    n = (name or "").lower().replace("la clippers", "los angeles clippers").replace("la lakers", "los angeles lakers")
    return " ".join(n.split())


_LINES = {}


def closing_total(sport, date_str, g):
    """A finished game's closing total: data/raw/<sport>_lines.csv (date +/- a
    day, teams by name), else the slate's own total fields."""
    if sport not in _LINES:
        by = {}
        path = os.path.join(store.REPO_ROOT, "data", "raw", f"{sport}_lines.csv")
        if os.path.exists(path):
            import csv as _csv
            from datetime import date as _date
            with open(path, encoding="utf-8") as f:
                for r in _csv.DictReader(f):
                    try:
                        t = float(r.get("total_close") or "")
                    except ValueError:
                        continue
                    by.setdefault(r["date"], []).append((_team_key(r["away"]), _team_key(r["home"]), t))
        _LINES[sport] = by
    from datetime import date as _date, timedelta as _td
    a, h = _team_key(g.get("away")), _team_key(g.get("home"))
    for off in (0, 1, -1):
        d = (_date.fromisoformat(date_str) + _td(days=off)).isoformat()
        for ra, rh, t in _LINES[sport].get(d, []):
            if (ra == a or ra in a or a in ra) and (rh == h or rh in h or h in rh):
                return t
    for k in ("totalsLine", "gameTotal", "total"):
        if isinstance(g.get(k), (int, float)):
            return g[k]
    return None


_LINE_ROWS = {}


def _line_rows(sport):
    """Every finished game in data/raw/<sport>_lines.csv (not only the ones on our
    slates): (date, away, home, away_score, home_score, home_spread, total)."""
    if sport not in _LINE_ROWS:
        rows = []
        path = os.path.join(store.REPO_ROOT, "data", "raw", f"{sport}_lines.csv")
        if os.path.exists(path):
            import csv as _csv
            with open(path, encoding="utf-8") as f:
                for r in _csv.DictReader(f):
                    def num(k):
                        try:
                            return float(r.get(k) or "")
                        except ValueError:
                            return None
                    a, h = num("away_score"), num("home_score")
                    if a is None or h is None:
                        continue
                    rows.append((r["date"], r["away"], r["home"], a, h, num("spread_close"), num("total_close")))
        _LINE_ROWS[sport] = rows
    return _LINE_ROWS[sport]


def _full_name(sport, name, slate_date):
    """A slate's short school name ("Duke") -> the lines file's full name ("Duke Blue
    Devils"), or None when it's missing or ambiguous (Miami / Miami (OH))."""
    n = _team_key(name)
    names = {}
    for d, a, h, *_ in _line_rows(sport):
        for t in (a, h):
            names.setdefault(_team_key(t), t)
    if n in names:
        return names[n]
    cands = {k: v for k, v in names.items() if k.startswith(n + " ")}
    return next(iter(cands.values())) if len(cands) == 1 else None


def _fill_from_lines(sport, wanted, hist, slate_date, totals):
    """College slates don't hold every game a team plays, so a team whose opponent
    wasn't on earlier slates had no trend line. Add its games from the lines file."""
    if sport not in ("cfb", "ncaab"):
        return
    rows = _line_rows(sport)
    for k, name in wanted.items():
        full = _full_name(sport, name, slate_date)
        if not full:
            continue
        have = {e[0] for e in hist[k]}
        for d, a, h, asc, hsc, hs, tot in rows:
            if (slate_date and d >= slate_date) or d in have or full not in (a, h):
                continue
            home = full == h
            opp = a if home else h
            if totals:
                if tot is None:
                    continue
                hist[k].append([d, opp, round(asc + hsc - tot, 1), tot, int(home)])
            else:
                if hs is None:
                    continue
                my_sp = hs if home else -hs
                m = (hsc - asc) if home else (asc - hsc)
                hist[k].append([d, opp, round(m + my_sp, 1), my_sp, int(home)])


def _fill_from_scores(sport, wanted, hist, slate_date):
    """Soccer slates hold only a few matches a team plays, so its other finished
    matches come from the scores archive (data/raw/master_soccer_scores.csv):
    win margin only, no line."""
    path = os.path.join(store.REPO_ROOT, "data", "raw", f"master_{sport}_scores.csv")
    try:
        with open(path, encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
    except OSError:
        return
    for r in rows:
        d = r.get("Date") or ""
        if (slate_date and d >= slate_date) or r.get("Status") not in ("FT", "AET", "FT-Pens", "AGT", "Final"):
            continue
        try:
            a_sc, h_sc = float(r["Away_Score"]), float(r["Home_Score"])
        except (TypeError, ValueError, KeyError):
            continue
        for side, team, opp, m in (("home", r.get("Home_Team"), r.get("Away_Team"), h_sc - a_sc), ("away", r.get("Away_Team"), r.get("Home_Team"), a_sc - h_sc)):
            k = _team_key(team)
            if k in hist and d not in {e[0] for e in hist[k]}:
                hist[k].append([d, opp, None, None, int(side == "home"), None, round(m, 1)])


_QLINES = {}


def quarters(sport, date_str, g, side, totals):
    """The game's periods from data/raw/linescores/<sport>.json: the team's
    margin per quarter (half in NCAAB; overtime periods after), or with
    totals=True the points both teams scored per period. None if not saved."""
    if sport not in _QLINES:
        try:
            with open(os.path.join(store.REPO_ROOT, "data", "raw", "linescores", f"{sport}.json"), encoding="utf-8") as f:
                _QLINES[sport] = json.load(f)
        except (OSError, ValueError):
            _QLINES[sport] = {}
    ls = (_QLINES[sport].get(date_str) or {}).get(f"{g.get('away')}@{g.get('home')}")
    if not ls or len(ls[0]) != len(ls[1]):
        return None
    a, h = ls
    if totals:
        return [round(x + y) for x, y in zip(a, h)]
    return [round(y - x) if side == "home" else round(x - y) for x, y in zip(a, h)]


_RECS = {}


def record_at(sport, date_str, team):
    """The team's overall record going into its game on that date, from
    data/raw/records/<sport>.json (archive_linescores.py), or None."""
    if sport not in _RECS:
        try:
            with open(os.path.join(store.REPO_ROOT, "data", "raw", "records", f"{sport}.json"), encoding="utf-8") as f:
                _RECS[sport] = json.load(f)
        except (OSError, ValueError):
            _RECS[sport] = {}
    day = _RECS[sport].get(date_str) or {}
    if team in day:
        return day[team]
    from score_slate import _same_team
    hits = [v for k, v in day.items() if k != "_done" and _same_team(k, team)]
    return hits[0] if len(hits) == 1 else None


def ats_trends(all_docs, slate_date, slate_sports, totals=False):
    """totals=False: cover margin per game; True: points over (+) or under (-)
    the closing total."""
    out = {}
    for sport, n in TREND_GAMES.items():
        today = (slate_sports.get(sport) or {}).get("games") or []
        if not today:
            continue
        wanted = {_team_key(t): t for g in today for t in (g.get("away"), g.get("home")) if t}
        hist = {k: [] for k in wanted}
        for date_str, doc in all_docs.get(sport, []):
            if slate_date and date_str >= slate_date:
                continue
            for g in doc.get("games", []):
                if not is_final(doc, g):
                    continue
                sides = [s_ for s_ in ("home", "away") if _team_key(g.get(s_)) in hist]
                if not sides:
                    continue
                if totals:
                    tot = closing_total(sport, date_str, g)
                    if tot is None:
                        continue
                    over = g["homeScore"] + g["awayScore"] - tot
                    for side in sides:
                        hist[_team_key(g.get(side))].append([date_str, g.get("away" if side == "home" else "home"), round(over, 1), tot, int(side == "home"),
                                                             quarters(sport, date_str, g, side, True)])
                    continue
                hs = g.get("statsSpread") if sport == "nba" and isinstance(g.get("statsSpread"), (int, float)) else g.get("homeSpread")
                margin = g["homeScore"] - g["awayScore"]
                if not isinstance(hs, (int, float)):
                    if sport in NO_LINE_OK:
                        for side in sides:
                            hist[_team_key(g.get(side))].append([date_str, g.get("away" if side == "home" else "home"), None, None,
                                                                 int(side == "home"), None, round(margin if side == "home" else -margin, 1)])
                    continue
                for side in sides:
                    k = _team_key(g.get(side))
                    my_sp = hs if side == "home" else -hs
                    m = margin if side == "home" else -margin
                    hist[k].append([date_str, g.get("away" if side == "home" else "home"), round(m + my_sp, 1), my_sp, int(side == "home"),
                                    quarters(sport, date_str, g, side, False)])
        _fill_from_lines(sport, wanted, hist, slate_date, totals)
        # (Soccer isn't filled from data/raw/master_soccer_scores.csv: ESPN's combined
        # feed has women's and youth sides under the same club names and no league
        # column, so only our slates' matches are used. `_fill_from_scores` is kept.)
        out[sport] = {}
        for k, v in hist.items():
            if not v:
                continue
            rows = sorted(v, key=lambda r: (r[0], str(r[1])))[-n:]
            # row[6]: the opponent's record going into the game; row[7]: the team's
            # final margin (also for games with no spread)
            out[sport][wanted[k]] = [r[:5] + [r[5] if len(r) > 5 else None, record_at(sport, r[0], r[1]),
                                              round(r[2] - r[3], 1) if isinstance(r[2], (int, float)) and isinstance(r[3], (int, float))
                                              else (r[6] if len(r) > 6 else None)] for r in rows]
    return out

def backtest_wl(text):
    """(wins, losses) from a rule's backtest text ("66.0% ATS, 97-50 (...)" or
    "60.0% ATS, n=100 (...)"), or (None, None) when it can't be read."""
    m = re.search(r"(?:ATS|overs|unders),\s*(\d+)-(\d+)", text or "")
    if m:
        return int(m.group(1)), int(m.group(2))
    m = re.search(r"^([\d.]+)% ATS, n=(\d+)", text or "")
    if m:
        w = round(float(m.group(1)) / 100 * int(m.group(2)))
        return w, int(m.group(2)) - w
    return None, None

def nba_rosters(slate):
    """{slate team name: [[ESPN athlete id, name, points a game], ...]} for the
    NBA teams on today's slate, from the box scores NBA Stats caches
    (data/raw/nba_player_points.json): everyone who played in the team's last
    10 games, best scorers first. Feeds the pick sheet's player-prop picker."""
    from score_slate import _same_team
    games = (slate.get("sports") or {}).get("nba", {}).get("games") or []
    teams = {t for g in games for t in (g.get("away"), g.get("home")) if t}
    if not teams:
        return {}
    try:
        with open(os.path.join(store.REPO_ROOT, "data", "raw", "nba_player_points.json"), encoding="utf-8") as f:
            cache = json.load(f)
    except (OSError, ValueError):
        return {}
    seen = {}  # cache team name -> [box, ...] newest last (event ids grow with time)
    for eid in sorted(cache, key=lambda k: int(k) if str(k).isdigit() else 0):
        for team, box in ((cache[eid] or {}).get("pts") or {}).items():
            seen.setdefault(team, []).append(box)
    out = {}
    for t in teams:
        k = next((x for x in seen if x == t or _same_team(x, t)), None)
        if not k:
            continue
        tot = {}
        for box in seen[k][-10:]:
            for pid, v in box.items():
                if not v:
                    continue
                r = tot.setdefault(pid, [0, 0, v[1]])
                r[0] += 1
                r[1] += v[0] or 0
        out[t] = sorted(([pid, r[2], round(r[1] / r[0], 1)] for pid, r in tot.items()), key=lambda x: -x[2])
    return out


POS_ORDER = {"nfl": ["QB", "RB", "WR", "TE", "FB", "K"], "cfb": ["QB", "RB", "WR", "TE", "FB", "K"],
             "mlb": ["C", "1B", "2B", "3B", "SS", "LF", "CF", "RF", "DH", "OF", "IF", "SP", "RP", "P"],
             "soccer": ["F", "M", "D", "G"]}


def prop_rosters(slate):
    """{sport: {slate team name: [[athlete id, name, tag], ...]}} for the player-
    prop picker: ESPN rosters saved by archive_rosters.py for the slate date
    (tag = position), NBA sorted by points a game from the box-score cache
    (tag = "25.4 ppg"); players who don't play these props' positions last."""
    out = {}
    date_str = slate.get("date")
    nba_ppg = {pid: (name, ppg) for team in nba_rosters(slate).values() for pid, name, ppg in team}
    for sport, block in (slate.get("sports") or {}).items():
        try:
            with open(os.path.join(store.REPO_ROOT, "data", "raw", "rosters", f"{sport}.json"), encoding="utf-8") as f:
                teams = (json.load(f).get(date_str) or {}).get("teams") or {}
        except (OSError, ValueError):
            teams = {}
        res = {}
        for g in block.get("games") or []:
            for t in (g.get("away"), g.get("home")):
                if not t or t in res:
                    continue
                rows = [list(r) for r in teams.get(t) or []]
                if sport == "nba":
                    known = {r[0] for r in rows}
                    rows = [[r[0], r[1], f"{nba_ppg[r[0]][1]} ppg" if r[0] in nba_ppg else r[2]] for r in rows]
                    for team_rows in nba_rosters(slate).get(t, []):
                        if team_rows[0] not in known:
                            rows.append([team_rows[0], team_rows[1], f"{team_rows[2]} ppg"])
                    rows.sort(key=lambda r: -float(r[2].split()[0]) if r[2].endswith("ppg") else 1)
                else:
                    order = POS_ORDER.get(sport, [])
                    rows.sort(key=lambda r: (order.index(r[2]) if r[2] in order else len(order), r[1]))
                if rows:
                    res[t] = rows
        if res:
            out[sport] = res
    return out


def load_mypicks():
    out = {}
    for path in sorted(glob.glob(os.path.join(store.REPO_ROOT, "data", "mypicks", "*.json"))):
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
        out[doc["date"]] = doc
    return out


def prop_log(mypicks):
    """Every prop of yours (player and team) as plays ("w": "myprop"): they count
    in your record like your over/unders (tl line, tr result, tp profit; a void
    prop has no result)."""
    out = []
    for date_str, doc in sorted(mypicks.items()):
        for p in (doc.get("props") or {}).values():
            sd = props_lib.any_stat_def(p.get("sport", "nba"), p.get("stat"))
            res = p.get("result")
            play = {"d": date_str, "s": p.get("sport", "nba"), "w": "myprop", "g": f"{p.get('away')} @ {p.get('home')}",
                    "k": f"{p.get('player')} {str(p.get('side')).title()} {p.get('line'):g} {sd[2] if sd else p.get('stat')}",
                    "tl": p.get("line"), "o": p.get("odds"), "r": res, "act": p.get("actual"), "why": p.get("reason"),
                    "team": 1 if p.get("kind") == "team" else 0}
            if res in ("W", "L", "P"):
                play.update({"tr": res, "tp": p.get("profit")})
            elif not res:
                play["pd"] = 1
            out.append(play)
    return out


def blank():
    return {"atsW": 0, "atsL": 0, "atsP": 0, "atsProfit": 0.0, "atsPriced": 0,
            "mlW": 0, "mlL": 0, "mlProfit": 0.0, "mlPriced": 0, "mlSkipped": 0}


def tally(acc, g_result):
    ats, ml = g_result["ats"], g_result["ml"]
    if ats["result"] == "cover":
        acc["atsW"] += 1
    elif ats["result"] == "miss":
        acc["atsL"] += 1
    elif ats["result"] == "push":
        acc["atsP"] += 1
    if ats["profit"] is not None:
        acc["atsProfit"] += ats["profit"]
        acc["atsPriced"] += 1
    if not ml["counted"]:
        acc["mlSkipped"] += 1
    elif ml["result"] == "W":
        acc["mlW"] += 1
    elif ml["result"] == "L":
        acc["mlL"] += 1
    # A moneyline pick the grading rules skip (priced -400 or shorter, or an
    # NFL/CFB/NCAAB dog of 7+) is left out of the profit too, as on the page.
    if ml["counted"] and ml["profit"] is not None:
        acc["mlProfit"] += ml["profit"]
        acc["mlPriced"] += 1


def ledger_side(g):
    if g.get("pick") and g.get("confidence") != "skip" and not g.get("skipped"):
        return side_of(g, g["pick"])
    return None


def alt_side(g):
    if g.get("altPick") and g.get("altConfidence") != "pass":
        return side_of(g, g["altPick"])
    return None


def trend_side(g):
    return side_of(g, g["altTrendFavors"]) if g.get("altTrendFavors") else None


def blowout_side(g):
    return side_of(g, g["altBlowoutFavors"]) if g.get("altBlowoutFavors") else None


def stats_side(g):
    return side_of(g, g["statsFavors"]) if g.get("statsFavors") else None


def nflstats_side(g):
    return side_of(g, g["nflStatsFavors"]) if g.get("nflStatsFavors") else None


def ncaabstats_side(g):
    return side_of(g, g["ncaabStatsFavors"]) if g.get("ncaabStatsFavors") else None


# Storyline veto (the user's call, 2026-11-13): from this date on, a model's
# pick on a game whose storylines lean the other way (the card's weighted
# tally, frozen at the start) sits out -- it counts neither for nor against
# the model anywhere on the page. Your own picks always count. The pick log
# keeps what the pick would have done ("sx"/"sxa"), so the change can be judged.
# The storyline veto ran 2026-11-13 to 2026-11-15 and was removed on
# 2026-11-16 at the user's request (storylines didn't do much better than the
# models): every model pick counts again, those days included. Set a date
# here to turn it back on from that date.
STORY_VETO_FROM = None
STORY_VETO_REMOVED = "2026-11-16"


def story_vetoed(date_str, g, side):
    if not STORY_VETO_FROM or date_str < STORY_VETO_FROM or side not in ("home", "away") or not g.get("storylines"):
        return False
    net = storyline_buckets.net_toward_home(g)
    return (net < 0) if side == "home" else (net > 0)


# Trend/blowout are only populated on NFL and CFB games, stats only on NBA
# games and nflstats only on NFL games; every other sport's games lack these
# keys entirely so these "models" contribute nothing outside their sport.
MODEL_SIDES = (("ledger", ledger_side), ("alt", alt_side), ("trend", trend_side),
               ("blowout", blowout_side), ("stats", stats_side), ("nflstats", nflstats_side), ("ncaabstats", ncaabstats_side))


def build():
    mypicks = load_mypicks()
    all_docs = {k: store.list_docs(cfg["collection"]) for k, cfg in sports.SPORTS.items()}

    totals = {k: blank() for k in ("ledger", "alt", "trend", "blowout", "stats", "nflstats", "ncaabstats", "mine")}
    by_sport = {}
    plays = []
    for sport, docs in all_docs.items():
        for date_str, doc in docs:
            picks_today = mypicks.get(date_str, {}).get("picks", {})
            for g in doc.get("games", []):
                final = is_final(doc, g)
                mine = picks_today.get(game_id(sport, date_str, g), {}).get("side")
                model_sides = [(k, f(g)) for k, f in MODEL_SIDES]
                for who, side in model_sides + [("mine", mine)]:
                    if side not in ("away", "home", "draw"):
                        continue
                    tier = g.get("confidence") if who == "ledger" else g.get("altConfidence") if who == "alt" else None
                    rule_src = {"stats": ("statsRules", RULE_NAMES, RULE_BACKTEST),
                                "nflstats": ("nflStatsRules", nfl_stats_rules.RULE_NAMES, nfl_stats_rules.RULE_BACKTEST),
                                "ncaabstats": ("ncaabStatsRules", ncaab_stats_rules.RULE_NAMES, ncaab_stats_rules.RULE_BACKTEST)}.get(who)
                    play_rules = None
                    if rule_src and g.get(rule_src[0]):
                        nums = [str(r.get("rule")) for r in g[rule_src[0]]]
                        stacked = (nba_families([r.get("rule") for r in g[rule_src[0]]]) if who == "stats" else len(nums)) > 1
                        tier = ("Rules " if len(nums) > 1 else "Rule ") + " + ".join(nums) + (" · stacked" if stacked else "")
                        play_rules = [{"n": r.get("rule"), "name": rule_src[1].get(r.get("rule"), r.get("name", "")),
                                       "bt": rule_src[2].get(r.get("rule"), r.get("backtest", ""))} for r in g[rule_src[0]]]
                    # NBA Stats: graded at its live line; your picks: at the line you took.
                    gv = (stats_view(g) if who == "stats"
                          else mine_view(g, picks_today.get(game_id(sport, date_str, g))) if who == "mine" else g)
                    ln = line_for(gv, side)
                    play = {"d": date_str, "s": sport, "w": who, "t": tier,
                            "g": f"{g.get('away')} @ {g.get('home')}", "k": team_for(g, side),
                            "sp": ln["spread"], "mo": ln["moneyline"]}
                    if play_rules:
                        play["rr"] = play_rules
                    if who == "mine":
                        pk = picks_today.get(game_id(sport, date_str, g)) or {}
                        lead = lead_minutes(date_str, pk.get("time"), pk.get("submittedAt"))
                        if lead is not None and lead < 0:
                            play["lt"] = 1   # submitted after the game started (the public Results page leaves it out)
                        # Which models were on your side ("ag") or the other
                        # side ("op") of this game, for the agreement table.
                        live_sides = [(k, s) for k, s in model_sides if s and not story_vetoed(date_str, g, s)]  # sat-out picks don't count
                        play["ag"] = [k for k, s in live_sides if s == side]
                        play["op"] = [k for k, s in live_sides if s != side]
                        # Storylines' net lean toward your side (each storyline's
                        # tally weight; + with you, - against), when the game had any.
                        if g.get("storylines"):
                            mine_team, net = team_for(g, side), 0.0
                            for e in g["storylines"]:
                                lean, wt = e.get("leans"), float(e.get("weight") or 1)
                                if not lean:
                                    continue
                                if e.get("unit") == "not to win":
                                    net -= wt if lean == mine_team else 0
                                else:
                                    net += wt if lean == mine_team else -wt
                            play["sl"] = net
                    vetoed = who != "mine" and story_vetoed(date_str, g, side)
                    if vetoed:
                        play["sx"] = 1   # sits out: the storylines leaned the other way
                    if not final:
                        play.update({"a": None, "ap": None, "m": None, "mp": None, "x": 0, "pd": 1})
                        plays.append(play)
                        continue
                    r = grade(sport, gv, side)
                    if vetoed:
                        # Not counted anywhere; "sxa"/"sxm" keep what it would have done.
                        play.update({"a": None, "ap": None, "m": None, "mp": None, "x": 0,
                                     "sxa": {"cover": "W", "miss": "L", "push": "P"}.get(r["ats"]["result"]),
                                     "sxm": r["ml"]["result"], "sc": f"{g['awayScore']:g}–{g['homeScore']:g}"})
                        plays.append(play)
                        continue
                    tally(totals[who], r)
                    ats_code = {"cover": "W", "miss": "L", "push": "P"}.get(r["ats"]["result"])
                    # "m"/"mp" carry the moneyline result/profit even for a skipped
                    # pick (a -400-or-shorter fav, or a 7+ point NFL/college dog) —
                    # "x" flags why, so the site can include or exclude those via
                    # its own filter instead of the build baking in one answer.
                    play.update({"a": ats_code, "ap": r["ats"]["profit"],
                                 "m": r["ml"]["result"], "mp": r["ml"]["profit"],
                                 "x": {"dog": 1, "fav": 2}.get(r["ml"]["skip"], 0), "sc": f"{g['awayScore']:g}–{g['homeScore']:g}"})
                    plays.append(play)
                    bucket = by_sport.setdefault(sport, {k: blank() for k in ("ledger", "alt", "trend", "blowout", "stats", "nflstats", "ncaabstats", "mine")})
                    tally(bucket[who], r)
                # Your own over/under picks (data/mypicks totals), graded at the
                # line they were submitted at; kept apart from sides like NBA Totals.
                mt = mypicks.get(date_str, {}).get("totals", {}).get(game_id(sport, date_str, g))
                if mt and isinstance(mt.get("line"), (int, float)):
                    play = {"d": date_str, "s": sport, "w": "mytotal", "g": f"{g.get('away')} @ {g.get('home')}",
                            "k": f"{mt['side'].title()} {mt['line']:g}", "tl": mt["line"]}
                    lead = lead_minutes(date_str, mt.get("time"), mt.get("submittedAt"))
                    if lead is not None and lead < 0:
                        play["lt"] = 1
                    if final:
                        r = grade_total(g, mt["side"], mt["line"], mt.get("odds"))
                        play.update({"tr": r["result"], "tp": r["profit"], "sc": f"{g['awayScore']:g}–{g['homeScore']:g}"})
                    else:
                        play["pd"] = 1
                    plays.append(play)
                # NBA Totals picks go in the pick log too, under their own keys
                # (tl line, tr result, tp profit) so the spread/moneyline
                # dashboard figures never count them.
                if sport == "nba" and g.get("totalsFavors") and isinstance(g.get("totalsLine"), (int, float)):
                    play = {"d": date_str, "s": sport, "w": "totals", "g": f"{g.get('away')} @ {g.get('home')}",
                            "k": f"{g['totalsFavors']} {g['totalsLine']:g}", "tl": g["totalsLine"],
                            "rr": [{"n": x.get("rule"), "name": nba_totals_rules.RULE_NAMES.get(x.get("rule"), x.get("name", "")),
                                    "bt": nba_totals_rules.RULE_BACKTEST.get(x.get("rule"), x.get("backtest", ""))}
                                   for x in g.get("totalsRules") or []]}
                    if final:
                        play.update({"tr": totals_result(g), "tp": g.get("totalsReturn"),
                                     "sc": f"{g['awayScore']:g}–{g['homeScore']:g}"})
                    else:
                        play["pd"] = 1
                    plays.append(play)

    # NBA Stats record per rule this season: a pick counts toward every rule
    # that triggered it.
    rule_records = {n: {"w": 0, "l": 0, "p": 0} for n in RULE_NAMES}
    for date_str, doc in all_docs.get("nba", []):
        for g in doc.get("games", []):
            if not g.get("statsFavors") or not is_final(doc, g) or story_vetoed(date_str, g, side_of(g, g["statsFavors"])):
                continue
            r = grade("nba", stats_view(g), side_of(g, g["statsFavors"]))["ats"]["result"]
            key = {"cover": "w", "miss": "l", "push": "p"}.get(r)
            for rule in g.get("statsRules") or []:
                if key and rule.get("rule") in rule_records:
                    rule_records[rule["rule"]][key] += 1
    stats_stacked = {**stacked_record(all_docs.get("nba", []), "nba", "statsFavors", "statsRules", nba_families, stats_view),
                     "backtest": STACKED_BACKTEST}
    stats_rules = [{"rule": n, "name": RULE_NAMES[n], "backtest": RULE_BACKTEST[n], **rule_records[n],
                    **dict(zip(("btW", "btL"), backtest_wl(RULE_BACKTEST[n])))}
                   for n in sorted(RULE_NAMES)]
    # NBA Stats picks (or rules on a pick) added after the fact by
    # `nba_stats_signals.py --backfill`, so the page can say so.
    stats_backfilled = sum(1 for _, doc in all_docs.get("nba", []) for g in doc.get("games", [])
                           if g.get("statsFavors") and any(r.get("backfill") for r in g.get("statsRules") or []))
    nfl_records = {n: {"w": 0, "l": 0, "p": 0} for n in nfl_stats_rules.RULE_NAMES}
    for date_str, doc in all_docs.get("nfl", []):
        for g in doc.get("games", []):
            if not g.get("nflStatsFavors") or not is_final(doc, g) or story_vetoed(date_str, g, side_of(g, g["nflStatsFavors"])):
                continue
            key = {"cover": "w", "miss": "l", "push": "p"}.get(grade("nfl", g, side_of(g, g["nflStatsFavors"]))["ats"]["result"])
            for rule in g.get("nflStatsRules") or []:
                if key and rule.get("rule") in nfl_records:
                    nfl_records[rule["rule"]][key] += 1
    nfl_stacked = {**stacked_record(all_docs.get("nfl", []), "nfl", "nflStatsFavors", "nflStatsRules"),
                   "backtest": nfl_stats_rules.STACKED_BACKTEST}
    nfl_rules = [{"rule": n, "name": nfl_stats_rules.RULE_NAMES[n], "backtest": nfl_stats_rules.RULE_BACKTEST[n], **nfl_records[n],
                  **dict(zip(("btW", "btL"), backtest_wl(nfl_stats_rules.RULE_BACKTEST[n])))}
                 for n in sorted(nfl_stats_rules.RULE_NAMES)]
    ncaab_records = {n: {"w": 0, "l": 0, "p": 0} for n in ncaab_stats_rules.RULE_NAMES}
    for date_str, doc in all_docs.get("ncaab", []):
        for g in doc.get("games", []):
            if not g.get("ncaabStatsFavors") or not is_final(doc, g) or story_vetoed(date_str, g, side_of(g, g["ncaabStatsFavors"])):
                continue
            key = {"cover": "w", "miss": "l", "push": "p"}.get(grade("ncaab", g, side_of(g, g["ncaabStatsFavors"]))["ats"]["result"])
            for rule in g.get("ncaabStatsRules") or []:
                if key and rule.get("rule") in ncaab_records:
                    ncaab_records[rule["rule"]][key] += 1
    ncaab_rules = [{"rule": n, "name": ncaab_stats_rules.RULE_NAMES[n], "backtest": ncaab_stats_rules.RULE_BACKTEST[n], **ncaab_records[n],
                    **dict(zip(("btW", "btL"), backtest_wl(ncaab_stats_rules.RULE_BACKTEST[n])))}
                   for n in sorted(ncaab_stats_rules.RULE_NAMES)]

    nba_totals = nba_totals_record(all_docs.get("nba", []))

    slate_date = max((d for docs in all_docs.values() for d, _ in docs), default=None)
    slate = {"date": slate_date, "weekday": None, "sports": {}}
    for sport, docs in all_docs.items():
        for date_str, doc in docs:
            if date_str != slate_date:
                continue
            slate["weekday"] = doc.get("weekday") or slate["weekday"]
            games = []
            for g in doc.get("games", []):
                row = {k: g.get(k) for k in SLATE_FIELDS}
                row["id"] = game_id(sport, date_str, g)
                row["final"] = is_final(doc, g)
                if row["final"]:
                    row["results"] = {
                        who: ({"sx": 1} if story_vetoed(date_str, g, side) else grade(sport, stats_view(g) if who == "stats" else g, side))
                        for who, side in [(k, f(g)) for k, f in MODEL_SIDES]
                        if side
                    }
                    t = totals_result(g)
                    if t:
                        row["results"]["totals"] = {"result": t}
                games.append(row)
            slate["sports"][sport] = {"label": sports.SPORTS[sport]["label"], "games": games}

    committed = {}
    for gid, p in mypicks.get(slate_date, {}).get("picks", {}).items():
        entry = dict(p)
        sport = p.get("sport")
        game = next((g for g in slate["sports"].get(sport, {}).get("games", []) if g["id"] == gid), None)
        if game:
            game = mine_view(game, p)   # graded at the line you took
            skip = ml_skip(sport, line_for(game, p["side"]))
            entry["bigDog"] = skip == "dog"
            entry["heavyFav"] = skip == "fav"
            if game["final"]:
                entry["result"] = grade(sport, game, p["side"])
        committed[gid] = entry

    my_totals = {}
    for gid, t in mypicks.get(slate_date, {}).get("totals", {}).items():
        entry = dict(t)
        game = next((g for g in slate["sports"].get(t.get("sport"), {}).get("games", []) if g["id"] == gid), None)
        if game and game["final"] and isinstance(t.get("line"), (int, float)):
            entry["result"] = grade_total(game, t["side"], t["line"], t.get("odds"))
        my_totals[gid] = entry

    for block in [totals, *by_sport.values()]:
        for acc in block.values():
            acc["atsProfit"] = round(acc["atsProfit"], 2)
            acc["mlProfit"] = round(acc["mlProfit"], 2)

    return {
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "repo": REPO,
        "slate": slate,
        "myPicks": committed,
        "myTotals": my_totals,
        "myProps": mypicks.get(slate_date, {}).get("props", {}),
        "rosters": prop_rosters(slate),
        "propStats": {k: [[x[0], x[1], x[2]] for x in v] for k, v in props_lib.STATS.items()},
        "teamPropStats": {k: [[x[0], x[1], x[2]] for x in v] for k, v in props_lib.TEAM_STATS.items()},
        "myScores": mypicks.get(slate_date, {}).get("scores", {}),
        "scoreboard": totals,
        "plays": sorted(plays + prop_log(mypicks), key=lambda p: p["d"]),
        "sportLabels": {k: cfg["label"] for k, cfg in sports.SPORTS.items()},
        "bySport": {k: {"label": sports.SPORTS[k]["label"], **v} for k, v in by_sport.items()},
        "statsRules": stats_rules,
        "storyStrength": storyline_strength(all_docs),
        "atsTrend": ats_trends(all_docs, slate.get("date"), slate.get("sports") or {}),
        "ouTrend": ats_trends(all_docs, slate.get("date"), slate.get("sports") or {}, totals=True),
        "storyVetoFrom": STORY_VETO_FROM,
        "storyVetoRemoved": STORY_VETO_REMOVED,
        "storyBacktest": storyline_buckets.BACKTEST,
        "storyBacktestNotes": storyline_buckets.NOTES,
        "statsBackfilled": stats_backfilled,
        "nflStatsRules": nfl_rules,
        "ncaabStatsRules": ncaab_rules,
        "health": read_health(),
        "manual": read_manual(),
        "grading": grading_patterns.build(mypicks),
        "statsStacked": stats_stacked,
        "nbaTotalsRules": nba_totals["rules"],
        "nbaTotals": nba_totals["all"],
        "nbaTotalsPlays": nba_totals["plays"],
        "nflStatsStacked": nfl_stacked,
    }


def read_manual():
    """{sport: {date: {game key: entry}}} -- every hand-entered game, so the
    "Enter data by hand" page can show and correct what's already there."""
    out = {}
    for sport in manual.SPORTS:
        for d in manual.dates(sport):
            out.setdefault(sport, {})[d] = manual.load(sport, d)
    return out


def read_health():
    """data/health.json (each scoring step's last status), or {} if absent."""
    try:
        with open(os.path.join(store.REPO_ROOT, "data", "health.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def totals_result(g):
    """'W', 'L' or 'P' for a graded NBA Totals pick, else None."""
    if not g.get("totalsFavors") or "totalsCorrect" not in g:
        return None
    if g["totalsCorrect"] is None:
        return "P" if g.get("totalsReturn") == 0 else None
    return "W" if g["totalsCorrect"] else "L"


def nba_totals_record(docs):
    """This season's NBA Totals record: per rule (a pick counts for every rule
    that flagged it), picks both rules agreed on, and all picks with $100
    profit at -110, plus how many were backfilled (totalsBackfill: graded
    after the fact on the archived closing line, see nba_totals_signals.py)."""
    rules = {n: {"w": 0, "l": 0, "p": 0} for n in nba_totals_rules.RULE_NAMES}
    both = {"w": 0, "l": 0, "p": 0}
    allp = {"w": 0, "l": 0, "p": 0, "profit": 0.0, "backfilled": 0, "backfilledThrough": None}
    plays = []  # every graded pick {d, r, v}, so the dashboard can filter by date
    for date_str, doc in docs:
        for g in doc.get("games", []):
            r = totals_result(g)
            if not r or not is_final(doc, g):
                continue
            key = r.lower()
            nums = [x.get("rule") for x in g.get("totalsRules") or []]
            for n in nums:
                if n in rules:
                    rules[n][key] += 1
            if nba_totals_rules.families(nums) > 1:
                both[key] += 1
            allp[key] += 1
            allp["profit"] += g.get("totalsReturn") or 0
            plays.append({"d": date_str, "r": r, "v": g.get("totalsReturn") or 0})
            if g.get("totalsBackfill"):
                allp["backfilled"] += 1
                allp["backfilledThrough"] = max(allp["backfilledThrough"] or date_str, date_str)
    allp["profit"] = round(allp["profit"], 2)
    return {"rules": [{"rule": n, "name": nba_totals_rules.RULE_NAMES[n], "backtest": nba_totals_rules.RULE_BACKTEST[n], **rules[n],
                       **dict(zip(("btW", "btL"), backtest_wl(nba_totals_rules.RULE_BACKTEST[n])))}
                      for n in sorted(rules)],
            "all": {**allp, "both": both}, "plays": plays}


def stacked_record(docs, sport, favors, rules, families=len, view=lambda g: g):
    """This season's record on picks two or more rules agreed on (rule
    families for NBA Stats: overlapping slices of one situation count once)."""
    rec = {"w": 0, "l": 0, "p": 0}
    for date_str, doc in docs:
        for g in doc.get("games", []):
            nums = [r.get("rule") for r in g.get(rules) or []]
            if not g.get(favors) or families(nums) < 2 or not is_final(doc, g) or story_vetoed(date_str, g, side_of(g, g[favors])):
                continue
            key = {"cover": "w", "miss": "l", "push": "p"}.get(grade(sport, view(g), side_of(g, g[favors]))["ats"]["result"])
            if key:
                rec[key] += 1
    return rec


def main():
    out_dir = os.path.join(store.REPO_ROOT, "_site")
    if "--out" in sys.argv:
        out_dir = sys.argv[sys.argv.index("--out") + 1]
    os.makedirs(out_dir, exist_ok=True)
    # The page's code version goes into both the HTML and data.json. data.json
    # is always fetched fresh, so a browser holding an older cached copy of
    # the page sees the mismatch and reloads itself (site/index.html).
    with open(os.path.join(store.REPO_ROOT, "site", "index.html"), encoding="utf-8") as f:
        page = f.read()
    version = hashlib.sha1(page.encode("utf-8")).hexdigest()[:12]
    with open(os.path.join(out_dir, "index.html"), "w", encoding="utf-8") as f:
        f.write(page.replace("__PAGE_VERSION__", version))
    for extra in ("manual.html", "grading.html", "results.html", "manifest.webmanifest", "sw.js"):
        shutil.copy(os.path.join(store.REPO_ROOT, "site", extra), os.path.join(out_dir, extra))
    # App icons (installable app: manifest.webmanifest + sw.js).
    shutil.copytree(os.path.join(store.REPO_ROOT, "site", "icons"), os.path.join(out_dir, "icons"), dirs_exist_ok=True)
    payload = build()
    payload["pageVersion"] = version
    with open(os.path.join(out_dir, "data.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
    # Public results: every pick of yours, graded at the line you took (site/results.html).
    rows = build_results(load_mypicks(), {k: store.list_docs(cfg["collection"]) for k, cfg in sports.SPORTS.items()})
    with open(os.path.join(out_dir, "results.json"), "w", encoding="utf-8") as f:
        json.dump({"generatedAt": payload["generatedAt"], "repo": REPO, "rows": rows}, f, ensure_ascii=False, separators=(",", ":"))
    with open(os.path.join(out_dir, "results.csv"), "w", encoding="utf-8", newline="") as f:
        f.write(results_csv(rows))
    n = sum(len(s["games"]) for s in payload["slate"]["sports"].values())
    print(f"Wrote {out_dir}: slate {payload['slate']['date']} ({n} games), {len(payload['myPicks'])} of your picks on it.")


if __name__ == "__main__":
    main()
