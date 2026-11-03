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
    4: "Under when a team lost by 1-9 at home to a worse-record team and now faces a better-record team",
    5: "Rule 4, and the team is rested",
    6: "Under when a team lost at home to a worse-record team and now plays on the road vs. a better-record team (on trial)",
    7: "Rule 6, and the team is rested (on trial)",
    8: "Rule 6, after losing that home game by 10+ (on trial)",
    9: "Under when the home team is back from a 20+ road win, now vs. a weaker team and rested, and wasn't a 7+ pt favorite in that win (on trial)",
    10: "Under when the home team is back from a 20+ road win, now vs. a weaker team, and wasn't a 7+ pt favorite in that win (on trial)",
    11: "Under when the home team is back from a 20-29 point road win, now vs. a weaker team, and wasn't a 7+ pt favorite in that win (on trial)",
    12: "Under when the home team is back from a 20-29 point road win and wasn't a 7+ pt favorite in it (on trial)",
    13: "Under when the home team is back from a 20-29 point road win (on trial)",
    14: "Under when the home team is back from a 20+ road win, now vs. a weaker team (on trial)",
    15: "Under when the home team is back from a 20-29 point road win, now vs. a weaker team (on trial)",
    16: "Over when a team lost by 30+ on the road last game and now faces a weaker team (on trial)",
}
RULE_BACKTEST = {
    3: "65.2% overs, 43-23 (2022-23 to now); over in 3 of 4 seasons, small sample",
    4: "63.6% unders, 89-51 (2022-23 to now); found on 2022-24 (52-32), held on 2024-26 (37-19); every season",
    5: "63.8% unders, 74-42 (2022-23 to 2025-26); found on 2022-24 (45-27), held on 2024-26 (29-15); every season",
    6: "66.3% unders, 69-35 (2022-23 to 2025-26); under every season",
    7: "65.2% unders, 58-31 (2022-23 to 2025-26); under every season",
    8: "71.4% unders, 30-12 (2022-23 to 2025-26); under every season, small sample",
    9: "67.4% unders, 29-14 (2022-23 to now); under every season",
    10: "66.0% unders, 35-18 (2022-23 to now); under every season",
    11: "64.3% unders, 27-15 (2022-23 to now); under every season",
    12: "63.5% unders, 40-23 (2022-23 to now); under every season",
    13: "63.4% unders, 59-34 (2022-23 to now); under every season",
    14: "63.3% unders, 57-33 (2022-23 to now); under every season",
    15: "62.5% unders, 40-24 (2022-23 to now); under every season",
    16: "71.4% overs, 30-12 (2022-23 to 2025-26); over every season",
}
OVER_RULES = {3, 16}
OT_LOOKBACK_DAYS = 10


# Rules 4-8 are overlapping slices of one situation (a home loss to a
# worse-record team): several on one game count as one family, not "stacked".
FAMILY = {**{n: "home-upset-loss" for n in range(4, 9)}, **{n: "home-after-road-blowout" for n in range(9, 16)}}


def families(nums):
    return len({FAMILY.get(n, n) for n in nums})
