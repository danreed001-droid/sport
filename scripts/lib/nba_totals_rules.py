"""NBA Totals rule names and backtests, shared by scripts/nba_totals_signals.py
(which flags the games), score_slate.py (grading) and build_site.py (the pick
sheet). Rules 4-8 bet the full-game UNDER, rule 3 the OVER, against the
closing total. Rules 5, 7 and 8 are narrower slices of 4 and 6, so they
usually fire together with them. Only rules that backtested at 61%+ are kept.

Backtested on 2022-23 through 2025-26 regular-season games (lines from
DraftKings closing totals since 2025-11-25 and a pre-game snapshot before
that). Rules 4 and 5 were found on 2022-24 and held on 2024-26; 3, 6, 7 and
8 are on trial."""

# Retired 2026-11-03 (only rules that backtested at 61%+ are kept): 1, under
# when the spread is 3 points or less (54.2%, 637-539); 2, under when the road
# team is coming off an OT game (55.3%, 131-106). Numbers aren't reused.
RULE_NAMES = {
    3: "Over when the home team won its last game and that game's 30-39 point scorer is out (on trial)",
    6: "Under when a team lost at home to a worse-record team and now plays on the road vs. a better-record team (on trial)",
    9: "Under when the home team is back from a 20+ road win, now vs. a weaker team and rested, and wasn't a 7+ pt favorite in that win (on trial)",
    10: "Under when the home team is back from a 20+ road win, now vs. a weaker team, and wasn't a 7+ pt favorite in that win (on trial)",
    14: "Under when the home team is back from a 20+ road win, now vs. a weaker team (on trial)",
    16: "Over when a team lost by 30+ on the road last game and now faces a weaker team (on trial)",
}
RULE_BACKTEST = {
    3: "65.1% overs, 56-30 (2018-19 and 2021-22 to now; 2019-20 and 2020-21 left out); unseen when found, 2018-19 + 2021-22: 13-8",
    6: "62.6% unders, 107-64 (2018-19 and 2021-22 to now; 2019-20 and 2020-21 left out); unseen when found, 2018-19 + 2021-22: 38-30",
    9: "63.5% unders, 47-27 (2018-19 and 2021-22 to now; 2019-20 and 2020-21 left out); unseen when found, 2018-19 + 2021-22: 18-13",
    10: "62.8% unders, 59-35 (2018-19 and 2021-22 to now; 2019-20 and 2020-21 left out); unseen when found, 2018-19 + 2021-22: 24-17",
    14: "61.2% unders, 90-57 (2018-19 and 2021-22 to now; 2019-20 and 2020-21 left out); unseen when found, 2018-19 + 2021-22: 33-24",
    16: "67.2% overs, 41-20 (2018-19 and 2021-22 to now; 2019-20 and 2020-21 left out); unseen when found, 2018-19 + 2021-22: 11-8",
}

# Retired 2026-11-03 (under 61% on 2018-19 and 2021-22 to now): 4, 5, 11, 12, 13, 15, 17, 18, 19. Earlier: 1, 2.
# Also retired 2026-11-03 for going under 55% on the unseen seasons (2018-19 +
# 2021-22): 7, 8.
# Their code paths stay in nba_totals_signals.py but never pick; numbers aren't reused.
RETIRED = {1, 2, 4, 5, 7, 8, 11, 12, 13, 15, 17, 18, 19}

OVER_RULES = {3, 16}
OT_LOOKBACK_DAYS = 10


# Rules 4-8 are overlapping slices of one situation (a home loss to a
# worse-record team): several on one game count as one family, not "stacked".
FAMILY = {**{n: "home-upset-loss" for n in range(4, 9)}, **{n: "home-after-road-blowout" for n in range(9, 16)},
          **{n: "both-b2b" for n in range(17, 20)}}


def families(nums):
    return len({FAMILY.get(n, n) for n in nums})
