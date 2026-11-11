"""NBA Stats rule names and backtest rates, shared by the signal engine
(scripts/nba_stats_signals.py) and the site build (scripts/build_site.py),
which has no network dependencies. Each rule only fires on the rest days
where it backtested at 62%+ ATS; the rates below are for those days.
Retired: rule 4 (no rest situation cleared 62%); rules 1, 3, 6, 7, 8, 10,
11, 12 and 15, which went under 60% ATS when replayed on 2023-24 and 2024-25
-- seasons none of the rules were found on; and rules 5 and 13, which then
went under 60% on 2018-19 and 2019-20 too. Rules 18-29 are newer and on
trial: found on 2022-23 to 2025-26 and not yet replayed on unseen seasons.
A "road-upset winner" (20-29) won its last game on the road at a team with a
better record; "less than a 7-pt dog" includes being favored in that game."""

RULE_NAMES = {
    2: "Fade an OT winner vs. a stronger team (any rest)",
    9: "Fade a late comeback on the back-to-back",
    16: "Back a home team on a back-to-back after losing to a team that shot 50%+ from three",
    17: "Fade a home team after a win where it allowed 130+ (any rest)",
    20: "Fade a road-upset winner now home vs. a stronger team, rested, after winning by 1-9 as less than a 7-pt dog (on trial)",
    21: "Fade a road-upset winner now home vs. a stronger team, after winning by 1-9 as less than a 7-pt dog (on trial)",
    24: "Fade a road-upset winner now home, rested, after winning by 1-9 as less than a 7-pt dog (on trial)",
    28: "Fade a road-upset winner now home after winning by 1-9 as less than a 7-pt dog (on trial)",
    36: "Back a team on the road after a 30+ point home loss (on trial)",
    37: "Back a team on the road, rested, after a 30+ point home loss (on trial)",
    39: "Back a road team vs. a stronger team after a 20-29 point road loss where it wasn't a 7+ pt dog (on trial)",
    43: "Both teams on a back-to-back: back a home team favored by 5+ that played on the road last night (on trial)",
    44: "Revenge: back a team at home with the worse record after losing the last meeting by 10-19 as the favorite (on trial)",
    45: "Revenge: back a team with the worse record after losing the last meeting by 10-19 as the favorite, its 2nd+ straight loss to them (on trial)",
    46: "Revenge: back a favored team with the worse record after losing the last meeting as the favorite, its 2nd+ straight loss to them (on trial)",
    47: "Revenge: back a team with the worse record whose last meeting, last season, was a 10-19 point loss (its only straight loss to them) (on trial)",
    48: "Revenge: fade a home favorite that lost the last meeting at home as the underdog (on trial)",
    49: "Fade a 7+ point underdog on a back-to-back that used 8 or fewer players (10+ min) last game (on trial)",
    50: "Back the favorite when 60%+ of spread bets are on a 7+ point underdog but the line moved 1-4.5 pts toward the favorite (on trial)",
    51: "Back a losing-record team that won its last two games by 10+ each, with at least a day off (on trial)",
    52: "Back a home team that beat the spread by 15+ in each of its last two games, with at least a day off (on trial)",
    53: "Back a home favorite of 10+ vs. a team at .300 or worse on the second night of a back-to-back (on trial)",
    54: "Back a home team that covered its last two games, in its first 20 games of the season, with at least a day off (on trial)",
    55: "Back a road team in its first road game after 3+ straight at home, 1,000+ miles away, after a loss, with at least a day off (on trial)",
}
RULE_BACKTEST = {
    2: "66.0% ATS, 97-50 (2018-19 and 2021-22 to now; 2019-20 and 2020-21 left out)",
    9: "68.9% ATS, 62-28 (2018-19 and 2021-22 to now; 2019-20 and 2020-21 left out)",
    16: "69.0% ATS, 29-13 (2018-19 and 2021-22 to now; 2019-20 and 2020-21 left out)",
    17: "62.0% ATS, 62-38 (2018-19 and 2021-22 to now; 2019-20 and 2020-21 left out)",
    20: "68.9% ATS, 42-19 (2018-19 and 2021-22 to now; 2019-20 and 2020-21 left out); unseen when found, 2018-19 + 2021-22: 12-7",
    21: "66.2% ATS, 51-26 (2018-19 and 2021-22 to now; 2019-20 and 2020-21 left out); unseen when found, 2018-19 + 2021-22: 14-8",
    24: "63.1% ATS, 77-45 (2018-19 and 2021-22 to now; 2019-20 and 2020-21 left out); unseen when found, 2018-19 + 2021-22: 24-14",
    28: "61.8% ATS, 89-55 (2018-19 and 2021-22 to now; 2019-20 and 2020-21 left out); unseen when found, 2018-19 + 2021-22: 26-17",
    36: "64.9% ATS, 48-26 (2018-19 and 2021-22 to now; 2019-20 and 2020-21 left out); unseen when found, 2018-19 + 2021-22: 14-8",
    37: "64.6% ATS, 42-23 (2018-19 and 2021-22 to now; 2019-20 and 2020-21 left out); unseen when found, 2018-19 + 2021-22: 12-6",
    39: "62.0% ATS, 44-27 (2018-19 and 2021-22 to now; 2019-20 and 2020-21 left out); unseen when found, 2018-19 + 2021-22: 14-9",
    43: "64.9% ATS, 37-20 (2018-19 and 2021-22 to now; 2019-20 and 2020-21 left out); unseen when found, 2018-19 + 2021-22: 13-8",
    44: "67.8% ATS, 59-28 (2018-19 and 2021-22 to now); unseen 2018-19 + 2021-22: 15-6; 2024-now 22-15",
    45: "64.8% ATS, 70-38 (2018-19 and 2021-22 to now); unseen 14-9; 2024-now 27-16",
    46: "62.5% ATS, 70-42 (2018-19 and 2021-22 to now); unseen 12-7; 2024-now 22-16",
    47: "61.3% ATS, 84-53 (2018-19 and 2021-22 to now); unseen 17-13; 2024-now 36-22",
    48: "63.4% ATS, 83-48 (2018-19 and 2021-22 to now); unseen 12-7; 2024-now 37-26",
    50: "61.8% ATS, 89-55 (Action Network consensus lines, openers and bet splits; 2024-25: 43-30, 2025-26: 46-24)",
    49: "69.5% ATS, 82-36 (2018-19 and 2021-22 to now); unseen 2018-19 + 2021-22: 20-7; 2024-now 28-13",
    51: "69.2% ATS, 101-45 (2018-19 and 2021-22 to now); unseen 2018-19 + 2021-22: 35-13; 2024-now 43-18",
    52: "65.9% ATS, 58-30 (2018-19 and 2021-22 to now); unseen 2018-19 + 2021-22: 21-5; 2024-now 26-12",
    53: "66.7% ATS, 76-38 (2018-19 and 2021-22 to now); unseen 2018-19 + 2021-22: 23-14; 2024-now 31-10",
    54: "62.1% ATS, 172-105 (2018-19 and 2021-22 to now); unseen 2018-19 + 2021-22: 61-29; 2024-now 52-38",
    55: "66.0% ATS, 97-50 (2018-19 and 2021-22 to now); unseen 2018-19 + 2021-22: 33-16; 2024-now 30-19",
}

# Retired 2026-11-03 (under 61% ATS on 2018-19 and 2021-22 to now, with the
# 2019-20 bubble and 2020-21 empty-arena seasons left out): 14, 18, 19, 22, 23, 25, 26, 27, 29, 33, 34, 38, 40, 42.
# Also retired 2026-11-03 for going under 55% on the unseen seasons (2018-19 +
# 2021-22): 35.
# Their code paths stay in nba_stats_signals.py but never pick; numbers aren't reused.
# Retired 2026-11-05: 41 (60.0%, 27-18) once 2025-26 games were dated by their
# Eastern tip-off date -- the lines archive's 2025-26 dates are UTC, a day late
# for evening games, which had miscounted some back-to-backs in the replay.
RETIRED = {14, 18, 19, 22, 23, 25, 26, 27, 29, 33, 34, 35, 38, 40, 41, 42}

# A pick two or more rules agree on ("stacked"), replayed on the same six
# unseen seasons: one-rule picks went 57.4% (269-200).
STACKED_BACKTEST = "67.5% ATS, 27-13 (replay on 6 unseen seasons); one-rule picks 57.4%"


# Rules 20-29 (a road-upset win) and 35-40 (a 20+ point loss) are overlapping
# slices of one situation each, so
# several firing on one game is not independent agreement: "stacked" counts
# distinct families, not rules.
FAMILY = {**{n: "road-upset" for n in range(20, 30)}, **{n: "blowout-loss" for n in range(35, 41)},
          **{n: "both-b2b" for n in range(41, 44)}, **{n: "revenge" for n in range(44, 49)},
          51: "momentum", 52: "momentum", 54: "momentum", 49: "tired-underdog", 53: "tired-underdog"}


def families(nums):
    return len({FAMILY.get(n, n) for n in nums})
