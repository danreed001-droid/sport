#!/usr/bin/env python3
"""STEP 1: grade any unscored past slates for a given sport using the
ESPN-derived archive in data/raw/master_<sport>_scores.csv (see
fetch_scores.py). Grades the Ledger pick, the Second Opinion pick, and —
independently — the prior-game trend check and blowout-win regression
check's own named favorites, so each signal's real hit rate is measurable
on its own (mirrors the Diamond Ledger CFB skill's SIGNAL GRADING rule,
which the live NFL data already follows too).
"""
import csv
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))
from lib import sports, store  # noqa: E402
from lib.grading import grade_pick  # noqa: E402
from lib.dates import today_et_str  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _csv_path(sport_key):
    return os.path.join(REPO_ROOT, "data", "raw", f"master_{sport_key}_scores.csv")


def load_scores_by_date(sport_key):
    by_date = {}
    path = _csv_path(sport_key)
    if not os.path.exists(path):
        return by_date
    with open(path, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            by_date.setdefault(row["Date"], []).append(row)
    return by_date


def _num(v):
    if v in (None, "", "-"):
        return None
    try:
        return float(v)
    except ValueError:
        return None


def find_match(scores_for_date, away, home):
    for row in scores_for_date:
        if row["Away_Team"] == away and row["Home_Team"] == home:
            return row
    for row in scores_for_date:
        if (away in row["Away_Team"] or row["Away_Team"] in away) and (home in row["Home_Team"] or row["Home_Team"] in home):
            return row
    return None


def is_resolved(status):
    s = (status or "").strip().lower()
    return s.startswith("final") or "postponed" in s or "cancel" in s


def grade_named(g, team, away_score, home_score):
    """Grade any named team (pick, altPick, altTrendFavors, altBlowoutFavors)
    against a finished game, using that team's own stored odds/spread."""
    if team == g["away"]:
        return grade_pick(team, away_score, home_score, g.get("awayMoneyline"), g.get("awaySpread"), g.get("awaySpreadOdds"))
    if team == g["home"]:
        return grade_pick(team, home_score, away_score, g.get("homeMoneyline"), g.get("homeSpread"), g.get("homeSpreadOdds"))
    return {"correct": None, "pickReturn": None, "pickCover": None, "pickSpreadReturn": None}


def main(sport_key):
    cfg = sports.get(sport_key)
    today = today_et_str()
    scores_by_date = load_scores_by_date(sport_key)
    docs = store.list_docs(cfg["collection"])
    pending = sorted(
        [(d, doc) for d, doc in docs if not doc.get("scored") and d < today],
        key=lambda x: x[0],
    )

    if not pending:
        print(f"[{cfg['label']}] no unscored past slates to grade.")
        return

    for date_str, doc in pending:
        games = doc.get("games", [])
        scores_for_date = scores_by_date.get(date_str, [])
        all_resolved = True
        missing = []
        matches = {}

        for g in games:
            row = find_match(scores_for_date, g["away"], g["home"])
            if row is None or not is_resolved(row.get("Status")):
                all_resolved = False
                missing.append(f"{g['away']} @ {g['home']}")
                continue
            matches[(g["away"], g["home"])] = row

        if not all_resolved:
            print(f"[{cfg['label']}] {date_str}: leaving unscored, missing/incomplete: {missing}")
            continue

        for g in games:
            row = matches[(g["away"], g["home"])]
            away_score = _num(row.get("Away_Score"))
            home_score = _num(row.get("Home_Score"))
            g["awayScore"], g["homeScore"] = away_score, home_score

            ledger = grade_named(g, g.get("pick"), away_score, home_score)
            g["correct"], g["pickReturn"] = ledger["correct"], ledger["pickReturn"]
            g["pickCover"], g["pickSpreadReturn"] = ledger["pickCover"], ledger["pickSpreadReturn"]

            alt = grade_named(g, g.get("altPick"), away_score, home_score)
            g["altCorrect"], g["altReturn"] = alt["correct"], alt["pickReturn"]
            g["altCover"], g["altSpreadReturn"] = alt["pickCover"], alt["pickSpreadReturn"]

            trend = grade_named(g, g.get("altTrendFavors"), away_score, home_score)
            g["altTrendCorrect"], g["altTrendReturn"] = trend["correct"], trend["pickReturn"]
            g["altTrendCover"], g["altTrendSpreadReturn"] = trend["pickCover"], trend["pickSpreadReturn"]

            blowout = grade_named(g, g.get("altBlowoutFavors"), away_score, home_score)
            g["altBlowoutCorrect"], g["altBlowoutReturn"] = blowout["correct"], blowout["pickReturn"]
            g["altBlowoutCover"], g["altBlowoutSpreadReturn"] = blowout["pickCover"], blowout["pickSpreadReturn"]

        doc["scored"] = True
        doc["scoredAt"] = datetime.now(timezone.utc).isoformat()
        store.write_doc(cfg["collection"], date_str, doc)
        print(f"[{cfg['label']}] {date_str}: scored {len(games)} game(s).")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "nfl")
