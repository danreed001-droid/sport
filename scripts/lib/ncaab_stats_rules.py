"""NCAAB Stats rule names and backtest rates, shared by the signal engine
(scripts/ncaab_stats_signals.py) and the site build (scripts/build_site.py),
which has no network dependencies. Backtested on every game involving an AP
Top 25 team with an ESPN closing spread, 2018-19 through 2025-26 (5,134
games); the rest of the 74 ideas tested didn't clear the bar (60%+, 60+
games, no losing season, 57%+ in both halves)."""

# No active rules. Retired 2026-11-03: rule 1, back a team after a loss where
# the opponent out-shot it from three by 25+ points of 3P% -- replayed on AP
# Top 25 games with ESPN core-odds closing lines, 2018-19 to 2025-26 (2020-21
# left out), it went 108-76 (58.7%), under the 61% bar used for NBA Stats.
# The NBA rules translated to college and 2,100 college combinations were
# also tested that day; none cleared the bar. Numbers aren't reused.
RULE_NAMES = {}
RULE_BACKTEST = {}
RETIRED = {1}
# With one rule there are no stacked picks yet.
STACKED_BACKTEST = None
