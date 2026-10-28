#!/usr/bin/env python3
"""Archives each finished NBA game's opening and closing lines (spread, total,
moneyline, DraftKings via ESPN's pickcenter) to data/raw/nba_lines.csv, so
line-movement ideas can be backtested later. ESPN only exposes opening lines
for recent seasons, so this keeps our own copy.

Reads finished games from data/raw/master_nba_scores.csv and only fetches
games not archived yet. A game whose summary has no opening line yet is
retried on later runs for RETRY_DAYS days, then written with blank lines so
it isn't fetched forever. Spreads are from the home team's side. The scores
archive also holds preseason games, so they're archived too; the file was
seeded with all of 2025-26 (whose opening lines ESPN still had).

Usage: python scripts/archive_nba_lines.py
"""
import csv
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(__file__))
from lib import espn  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCORES_CSV = os.path.join(REPO_ROOT, "data", "raw", "master_nba_scores.csv")
LINES_CSV = os.path.join(REPO_ROOT, "data", "raw", "nba_lines.csv")
RETRY_DAYS = 3
FIELDS = ["game_id", "date", "away", "home", "away_score", "home_score", "provider",
          "spread_open", "spread_close", "spread_odds_open", "spread_odds_close",
          "total_open", "total_close", "home_ml_open", "home_ml_close", "away_ml_open", "away_ml_close"]


def num(v):
    try:
        return float(str(v).lstrip("ou").replace("+", ""))
    except (TypeError, ValueError):
        return None


def fmt(v):
    return "" if v is None else f"{v:g}"


def fetch_lines(session, event_id):
    """{field: value} from the summary's first pickcenter entry, or None when
    it has no opening spread yet."""
    try:
        d = session.get(
            f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event={event_id}",
            timeout=20,
        ).json()
    except Exception:
        return None
    pc = (d.get("pickcenter") or [{}])[0]
    sp = (pc.get("pointSpread") or {}).get("home") or {}
    tot = (pc.get("total") or {}).get("over") or {}
    ml = pc.get("moneyline") or {}
    if not (sp.get("open") or {}).get("line"):
        return None
    pick = lambda node, when, key: num(((node or {}).get(when) or {}).get(key))
    return {
        "provider": (pc.get("provider") or {}).get("name", ""),
        "spread_open": pick(sp, "open", "line"), "spread_close": pick(sp, "close", "line"),
        "spread_odds_open": pick(sp, "open", "odds"), "spread_odds_close": pick(sp, "close", "odds"),
        "total_open": pick(tot, "open", "line"), "total_close": pick(tot, "close", "line"),
        "home_ml_open": pick(ml.get("home"), "open", "odds"), "home_ml_close": pick(ml.get("home"), "close", "odds"),
        "away_ml_open": pick(ml.get("away"), "open", "odds"), "away_ml_close": pick(ml.get("away"), "close", "odds"),
    }


def main():
    if not os.path.exists(SCORES_CSV):
        print("No NBA scores archive yet.")
        return
    done = set()
    if os.path.exists(LINES_CSV):
        with open(LINES_CSV, encoding="utf-8") as f:
            done = {row["game_id"] for row in csv.DictReader(f)}
    with open(SCORES_CSV, encoding="utf-8") as f:
        finals = [r for r in csv.DictReader(f)
                  if (r.get("Status") or "").startswith("Final") and r["Game_ID"] not in done]
    if not finals:
        print("NBA lines: nothing new to archive.")
        return
    session = espn.make_session()
    today = date.today()
    rows, waiting = [], 0
    for r in sorted(finals, key=lambda r: (r["Date"], r["Game_ID"])):
        lines = fetch_lines(session, r["Game_ID"])
        if lines is None and (today - date.fromisoformat(r["Date"])).days <= RETRY_DAYS:
            waiting += 1
            continue
        lines = lines or {}
        rows.append({"game_id": r["Game_ID"], "date": r["Date"], "away": r["Away_Team"], "home": r["Home_Team"],
                     "away_score": r["Away_Score"], "home_score": r["Home_Score"], "provider": lines.get("provider", ""),
                     **{k: fmt(lines.get(k)) for k in FIELDS[7:]}})
    if rows:
        new_file = not os.path.exists(LINES_CSV)
        with open(LINES_CSV, "a", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            if new_file:
                w.writeheader()
            w.writerows(rows)
    print(f"NBA lines: archived {len(rows)} game(s)"
          f"{f', {waiting} waiting on an opening line' if waiting else ''}.")


if __name__ == "__main__":
    main()
