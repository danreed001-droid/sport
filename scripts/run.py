#!/usr/bin/env python3
"""Run the full Diamond Ledger cycle for one or more sports: fetch scores,
grade past slates, generate today's slate if needed, print a results report.

Usage: python scripts/run.py [sport ...]   (default: nfl cfb)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

import fetch_scores  # noqa: E402
import score_slate  # noqa: E402
import generate_slate  # noqa: E402
from lib import sports, store, report  # noqa: E402
from lib.dates import today_et_str  # noqa: E402

DEFAULT_SPORTS = ["nfl", "cfb", "mlb", "nba", "epl"]


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

    print(f"--- STEP 2: generating today's {cfg['label']} slate ---")
    generate_slate.main(sport_key)

    print(f"--- {cfg['label']} results ---")
    docs = store.list_docs(cfg["collection"])
    today = today_et_str()
    r = report.report_for(docs, slate_date=today)

    summary_lines.append(f"\n## {cfg['label']}")
    for label, key in (("Ledger", "ledger"), ("Second Opinion", "secondOpinion"),
                       ("Trend-check signal", "trendSignal"), ("Blowout-check signal", "blowoutSignal")):
        slate_line = _fmt(r["slate"][key])
        season_line = _fmt(r["seasonToDate"][key])
        print(f"{label}: today's slate - {slate_line}")
        print(f"{label}: season-to-date - {season_line}")
        summary_lines.append(f"- **{label}** — slate: {slate_line} | season: {season_line}")


def main():
    requested = sys.argv[1:] or DEFAULT_SPORTS
    summary_lines = ["# Diamond Ledger results"]
    for sport_key in requested:
        run_sport(sport_key, summary_lines)

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as f:
            f.write("\n".join(summary_lines) + "\n")


if __name__ == "__main__":
    main()
