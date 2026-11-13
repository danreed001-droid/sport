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

def load_mypicks():
    out = {}
    for path in sorted(glob.glob(os.path.join(store.REPO_ROOT, "data", "mypicks", "*.json"))):
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
        out[doc["date"]] = doc
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
                        play["ag"] = [k for k, s in model_sides if s == side]
                        play["op"] = [k for k, s in model_sides if s and s != side]
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
                    if not final:
                        play.update({"a": None, "ap": None, "m": None, "mp": None, "x": 0, "pd": 1})
                        plays.append(play)
                        continue
                    r = grade(sport, gv, side)
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
            if not g.get("statsFavors") or not is_final(doc, g):
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
            if not g.get("nflStatsFavors") or not is_final(doc, g):
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
            if not g.get("ncaabStatsFavors") or not is_final(doc, g):
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
                        who: grade(sport, stats_view(g) if who == "stats" else g, side)
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
        "myScores": mypicks.get(slate_date, {}).get("scores", {}),
        "scoreboard": totals,
        "plays": sorted(plays, key=lambda p: p["d"]),
        "sportLabels": {k: cfg["label"] for k, cfg in sports.SPORTS.items()},
        "bySport": {k: {"label": sports.SPORTS[k]["label"], **v} for k, v in by_sport.items()},
        "statsRules": stats_rules,
        "storyStrength": storyline_strength(all_docs),
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
    for _, doc in docs:
        for g in doc.get("games", []):
            nums = [r.get("rule") for r in g.get(rules) or []]
            if not g.get(favors) or families(nums) < 2 or not is_final(doc, g):
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
