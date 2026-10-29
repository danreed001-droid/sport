"""NFL Stats rule names and backtest rates, shared by the signal engine
(scripts/nfl_stats_signals.py) and the site build (scripts/build_site.py),
which has no network dependencies. Backtested on every NFL regular-season
game 2020-2025 with ESPN closing spreads (core odds feed); it was one of 20
ideas set before looking, found on 2020-23 and confirmed on 2024-25.
Rule 2 came from a second batch of pre-set ideas and was checked on
2017-2025; the NFL bar is 60% (smaller samples than the NBA's 62%)."""

RULE_NAMES = {
    1: "Back a home underdog of 7+ points (fade a road favorite of 7+)",
    2: "Fade a team that won its last game as a 7+ point underdog",
    3: "Back an underdog whose top rusher ran for 150+ yards last game",
    4: "Fade a home team vs. a weaker team after its QB threw for 300+ yards in a win",
    5: "Back a road team after a 10+ point loss with 3+ turnovers and yards within 75 of the opponent",
    6: "Fade a team that gained 500+ yards, 300+ of them passing, last game",
    9: "Fade a team after a game with both a 100-yard rusher and a 350-yard passer",
    10: "Bet on the ATS record catching up: back a winning team covering under 40%, fade a losing team covering 60%+",
}
RULE_BACKTEST = {
    1: "64.7% ATS, n=116; held-out 2024-25: 26-11",
    2: "60.0% ATS, n=100 (2017-2025); 2017-21 59.1%, 2022-25 61.8%",
    3: "66.7% ATS, n=39 (2017-2025); 2017-21 61.9%, 2022-25 72.2%",
    4: "60.3% ATS, n=121 (2017-2025); every season 55%+",
    5: "65.3% ATS, n=75 (2017-2025); no losing season",
    6: "60.0% ATS, n=115 (2017-2025); 2017-21 59.8%, 2022-25 60.7%; only losing season 2021 (7-8)",
    9: "83.3% ATS, n=24 (2017-2025); 2017-21 14-4, 2022-25 6-0; no losing season (small sample)",
    10: "back side 66.7% ATS (n=78), fade side 61.9% (n=147), 2017-2025; no losing season either way",
}
# A pick two or more rules agree on ("stacked"), from replaying all the
# rules together on 2017-2025 (without 2023): one-rule picks went 60.0%.
STACKED_BACKTEST = "77.6% ATS, 52-15 (2017-2025 replay of all the rules)"
