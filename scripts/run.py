#!/usr/bin/env python3
"""Run STEP 1 (fetch scores, grade past slates) for one or more sports and
print a results report. This is the fully-deterministic half of Diamond
Ledger — no LLM involved — meant to run unattended on a schedule (see
.github/workflows/diamond-ledger.yml).

STEP 2 (generating each day's slate) is not run from here at all: the live
"Diamond Ledger" scheduled Routines (NFL, CFB, MLB, Basketball) do their own
research in claude.ai and mirror the slate they generate straight into
data/<collection>/<date>.json. This script only grades what's already there.

Usage: python scripts/run.py [sport ...]   (default: nfl cfb mlb nba ncaab epl)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

import fetch_scores  # noqa: E402
import score_slate  # noqa: E402
from lib import sports, store, report  # noqa: E402
from lib.dates import today_et_str  # noqa: E402

DEFAULT_SPORTS = ["nfl", "cfb", "mlb", "nba", "ncaab", "epl"]


def _fmt(totals):
    extra = f", n={totals['n']}" if "n" in totals else ""
    return f"SU {totals['straightUp']}, ML ${totals['moneylineProfit']}, ATS {totals['ats']}, ATS $ {totals['atsProfit']}{extra}"


def run_sport(sport_key, summary_lines):
    cfg = sports.get(sport_key)
    print(f"\n{'=' * 10} {cfg['label']} {'=' * 10}")

    print(f"--- Fetching {cfg['label']} scores from ESPN ---")
    fetch_scores.main(sport_key)

    print(f"--- STEP 1: scoring past {cfg['label']} slates ---")
    score_slate.main(sport_key)

    print(f"--- {cfg['label']} results ---")
    docs = store.list_docs(cfg["collection"])
    today = today_et_str()
    r = report.report_for(docs, slate_date=today)

    summary_lines.append(f"\n## {cfg['label']}")
    rows = [("Ledger", "ledger"), ("Second Opinion", "secondOpinion")]
    if cfg["kind"] == "two_way":
        rows += [("Trend-check signal", "trendSignal"), ("Blowout-check signal", "blowoutSignal")]
    for label, key in rows:
        slate_line = _fmt(r["slate"][key])
        season_line = _fmt(r["seasonToDate"][key])
        print(f"{label}: today's slate - {slate_line}")
        print(f"{label}: season-to-date - {season_line}")
        summary_lines.append(f"- **{label}** — slate: {slate_line} | season: {season_line}")


def main():
    requested = sys.argv[1:] or DEFAULT_SPORTS
    summary_lines = ["# Diamond Ledger results (scoring only)"]
    for sport_key in requested:
        run_sport(sport_key, summary_lines)

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as f:
            f.write("\n".join(summary_lines) + "\n")


if __name__ == "__main__":
    main()
