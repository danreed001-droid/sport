"""NBA Totals rule names and backtests, shared by scripts/nba_totals_signals.py
(which flags the games), score_slate.py (grading) and build_site.py (the pick
sheet). Rules 1-2 bet the full-game UNDER, rule 3 the OVER, against the
closing total.

Backtested on 2022-23 through 2026-27 (5,001 regular-season games; lines from
DraftKings closing totals since 2025-11-25 and a pre-game snapshot before
that). Rule 1 was the only situation out of ~1,000 tested that was found on
2022-24 and held on 2024-27; rule 2 won every season but on a small sample,
so it's tracked to see whether it holds."""

RULE_NAMES = {
    1: "Under when the spread is 3 points or less",
    2: "Under when the road team is coming off an overtime game",
    3: "Over when the home team won its last game and that game's 30-39 point scorer is out (on trial)",
}
RULE_BACKTEST = {
    1: "54.2% unders, 637-539 (2022-23 to 2026-27); under won every season",
    2: "55.3% unders, 131-106 (2022-23 to 2025-26); under won every season",
    3: "65.2% overs, 43-23 (2022-23 to 2025-26); over in 3 of 4 seasons, small sample",
}
OVER_RULES = {3}
# Break-even at the usual -110 is 52.4%, so both edges are thin: bet only at
# -110 or better.
CLOSE_SPREAD = 3.0
OT_LOOKBACK_DAYS = 10
