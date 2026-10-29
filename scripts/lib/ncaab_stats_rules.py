"""NCAAB Stats rule names and backtest rates, shared by the signal engine
(scripts/ncaab_stats_signals.py) and the site build (scripts/build_site.py),
which has no network dependencies. Backtested on every game involving an AP
Top 25 team with an ESPN closing spread, 2018-19 through 2025-26 (5,134
games); the rest of the 74 ideas tested didn't clear the bar (60%+, 60+
games, no losing season, 57%+ in both halves)."""

RULE_NAMES = {
    1: "Back a team after a loss where the opponent out-shot it from three by 25+ points of 3P%",
}
RULE_BACKTEST = {
    1: "60.5% ATS, 141-92 (2018-19 to 2025-26); 2018-21 64.0%, 2022-25 57.1%; no losing season",
}
# With one rule there are no stacked picks yet.
STACKED_BACKTEST = None
