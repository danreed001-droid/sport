#!/usr/bin/env python3
"""Builds the GitHub Pages pick sheet: copies site/index.html and writes
data.json with the latest slate, the season scoreboard for the Ledger, the
Second Opinion and your own picks (data/mypicks/), and your picks on the
latest slate.

Usage: python scripts/build_site.py [--out _site]
"""
import glob
import json
import os
import shutil
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))
from lib import sports, store  # noqa: E402
from lib.picks import game_id, grade, is_final, is_big_dog, line_for, side_of  # noqa: E402

REPO = os.environ.get("GITHUB_REPOSITORY", "danreed001-droid/sport")
SLATE_FIELDS = [
    "away", "home", "time", "awayPitcher", "homePitcher", "statLines",
    "pick", "confidence", "skipped", "skipReason",
    "altPick", "altConfidence", "altCategoryTally", "altReasons",
    "competition", "awayMoneyline", "homeMoneyline", "drawMoneyline", "awaySpread", "homeSpread", "awaySpreadOdds", "homeSpreadOdds",
    "awayScore", "homeScore",
]


def load_mypicks():
    out = {}
    for path in sorted(glob.glob(os.path.join(store.REPO_ROOT, "data", "mypicks", "*.json"))):
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
        out[doc["date"]] = doc
    return out


def blank():
    return {"atsW": 0, "atsL": 0, "atsP": 0, "atsProfit": 0.0, "atsPriced": 0,
            "mlW": 0, "mlL": 0, "mlProfit": 0.0, "mlPriced": 0, "mlSkippedDogs": 0}


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
        acc["mlSkippedDogs"] += 1
    elif ml["result"] == "W":
        acc["mlW"] += 1
    elif ml["result"] == "L":
        acc["mlL"] += 1
    if ml["profit"] is not None:
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


def build():
    mypicks = load_mypicks()
    all_docs = {k: store.list_docs(cfg["collection"]) for k, cfg in sports.SPORTS.items()}

    totals = {"ledger": blank(), "alt": blank(), "mine": blank()}
    by_sport = {}
    plays = []
    for sport, docs in all_docs.items():
        for date_str, doc in docs:
            picks_today = mypicks.get(date_str, {}).get("picks", {})
            for g in doc.get("games", []):
                if not is_final(doc, g):
                    continue
                mine = picks_today.get(game_id(sport, date_str, g), {}).get("side")
                for who, side in (("ledger", ledger_side(g)), ("alt", alt_side(g)), ("mine", mine)):
                    if side not in ("away", "home", "draw"):
                        continue
                    r = grade(sport, g, side)
                    tally(totals[who], r)
                    tier = g.get("confidence") if who == "ledger" else g.get("altConfidence") if who == "alt" else None
                    ats_code = {"cover": "W", "miss": "L", "push": "P"}.get(r["ats"]["result"])
                    plays.append({"d": date_str, "s": sport, "w": who, "t": tier,
                                  "a": ats_code, "ap": r["ats"]["profit"],
                                  "m": r["ml"]["result"] if r["ml"]["counted"] else None, "mp": r["ml"]["profit"],
                                  "x": 0 if r["ml"]["counted"] else 1})
                    bucket = by_sport.setdefault(sport, {"ledger": blank(), "alt": blank(), "mine": blank()})
                    tally(bucket[who], r)

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
                        who: grade(sport, g, side)
                        for who, side in (("ledger", ledger_side(g)), ("alt", alt_side(g)))
                        if side
                    }
                games.append(row)
            slate["sports"][sport] = {"label": sports.SPORTS[sport]["label"], "games": games}

    committed = {}
    for gid, p in mypicks.get(slate_date, {}).get("picks", {}).items():
        entry = dict(p)
        sport = p.get("sport")
        game = next((g for g in slate["sports"].get(sport, {}).get("games", []) if g["id"] == gid), None)
        if game:
            entry["bigDog"] = is_big_dog(sport, line_for(game, p["side"])["spread"])
            if game["final"]:
                entry["result"] = grade(sport, game, p["side"])
        committed[gid] = entry

    for block in [totals, *by_sport.values()]:
        for acc in block.values():
            acc["atsProfit"] = round(acc["atsProfit"], 2)
            acc["mlProfit"] = round(acc["mlProfit"], 2)

    return {
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "repo": REPO,
        "slate": slate,
        "myPicks": committed,
        "myScores": mypicks.get(slate_date, {}).get("scores", {}),
        "scoreboard": totals,
        "plays": sorted(plays, key=lambda p: p["d"]),
        "sportLabels": {k: cfg["label"] for k, cfg in sports.SPORTS.items()},
        "bySport": {k: {"label": sports.SPORTS[k]["label"], **v} for k, v in by_sport.items()},
    }


def main():
    out_dir = os.path.join(store.REPO_ROOT, "_site")
    if "--out" in sys.argv:
        out_dir = sys.argv[sys.argv.index("--out") + 1]
    os.makedirs(out_dir, exist_ok=True)
    shutil.copy(os.path.join(store.REPO_ROOT, "site", "index.html"), os.path.join(out_dir, "index.html"))
    payload = build()
    with open(os.path.join(out_dir, "data.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
    n = sum(len(s["games"]) for s in payload["slate"]["sports"].values())
    print(f"Wrote {out_dir}: slate {payload['slate']['date']} ({n} games), {len(payload['myPicks'])} of your picks on it.")


if __name__ == "__main__":
    main()
