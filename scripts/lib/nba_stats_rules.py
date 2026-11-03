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
    35: "Back a team on a back-to-back after a 20+ point road loss where it wasn't a 7+ pt dog (on trial)",
    36: "Back a team on the road after a 30+ point home loss (on trial)",
    37: "Back a team on the road, rested, after a 30+ point home loss (on trial)",
    39: "Back a road team vs. a stronger team after a 20-29 point road loss where it wasn't a 7+ pt dog (on trial)",
    41: "Both teams on a back-to-back: back the home team when it's favored and the road team has the better record (on trial)",
    43: "Both teams on a back-to-back: back a home team favored by 5+ that played on the road last night (on trial)",
}
RULE_BACKTEST = {
    2: "66.0% ATS, 97-50 (2018-19 and 2021-22 to now; 2019-20 and 2020-21 left out)",
    9: "69.9% ATS, 65-28 (2018-19 and 2021-22 to now; 2019-20 and 2020-21 left out)",
    16: "73.9% ATS, 34-12 (2018-19 and 2021-22 to now; 2019-20 and 2020-21 left out)",
    17: "62.6% ATS, 62-37 (2018-19 and 2021-22 to now; 2019-20 and 2020-21 left out)",
    20: "68.3% ATS, 41-19 (2018-19 and 2021-22 to now; 2019-20 and 2020-21 left out); unseen when found, 2018-19 + 2021-22: 12-7",
    21: "65.8% ATS, 50-26 (2018-19 and 2021-22 to now; 2019-20 and 2020-21 left out); unseen when found, 2018-19 + 2021-22: 14-8",
    24: "62.8% ATS, 76-45 (2018-19 and 2021-22 to now; 2019-20 and 2020-21 left out); unseen when found, 2018-19 + 2021-22: 24-14",
    28: "61.5% ATS, 88-55 (2018-19 and 2021-22 to now; 2019-20 and 2020-21 left out); unseen when found, 2018-19 + 2021-22: 26-17",
    35: "62.3% ATS, 38-23 (2018-19 and 2021-22 to now; 2019-20 and 2020-21 left out); unseen when found, 2018-19 + 2021-22: 11-10",
    36: "64.9% ATS, 48-26 (2018-19 and 2021-22 to now; 2019-20 and 2020-21 left out); unseen when found, 2018-19 + 2021-22: 14-8",
    37: "65.6% ATS, 42-22 (2018-19 and 2021-22 to now; 2019-20 and 2020-21 left out); unseen when found, 2018-19 + 2021-22: 12-6",
    39: "61.4% ATS, 43-27 (2018-19 and 2021-22 to now; 2019-20 and 2020-21 left out); unseen when found, 2018-19 + 2021-22: 14-9",
    41: "64.2% ATS, 34-19 (2018-19 and 2021-22 to now; 2019-20 and 2020-21 left out); unseen when found, 2018-19 + 2021-22: 6-4",
    43: "62.3% ATS, 43-26 (2018-19 and 2021-22 to now; 2019-20 and 2020-21 left out); unseen when found, 2018-19 + 2021-22: 13-8",
}

# Retired 2026-11-03 (under 61% ATS on 2018-19 and 2021-22 to now, with the
# 2019-20 bubble and 2020-21 empty-arena seasons left out): 14, 18, 19, 22, 23, 25, 26, 27, 29, 33, 34, 38, 40, 42.
# Their code paths stay in nba_stats_signals.py but never pick; numbers aren't reused.
RETIRED = {14, 18, 19, 22, 23, 25, 26, 27, 29, 33, 34, 38, 40, 42}

# A pick two or more rules agree on ("stacked"), replayed on the same six
# unseen seasons: one-rule picks went 57.4% (269-200).
STACKED_BACKTEST = "67.5% ATS, 27-13 (replay on 6 unseen seasons); one-rule picks 57.4%"


# Rules 20-29 (a road-upset win) and 35-40 (a 20+ point loss) are overlapping
# slices of one situation each, so
# several firing on one game is not independent agreement: "stacked" counts
# distinct families, not rules.
FAMILY = {**{n: "road-upset" for n in range(20, 30)}, **{n: "blowout-loss" for n in range(35, 41)},
          **{n: "both-b2b" for n in range(41, 44)}}


def families(nums):
    return len({FAMILY.get(n, n) for n in nums})
