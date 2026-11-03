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
    14: "Fade a team on a back-to-back vs. a weaker team after all 5 starters scored 10+ in a win",
    16: "Back a home team on a back-to-back after losing to a team that shot 50%+ from three",
    17: "Fade a home team after a win where it allowed 130+ (any rest)",
    18: "Back a home team vs. a stronger team when last game's 30+ point scorer is out (on trial)",
    19: "Back a road team on a back-to-back after a home loss to a worse-record team (on trial)",
    20: "Fade a road-upset winner now home vs. a stronger team, rested, after winning by 1-9 as less than a 7-pt dog (on trial)",
    21: "Fade a road-upset winner now home vs. a stronger team, after winning by 1-9 as less than a 7-pt dog (on trial)",
    22: "Fade a road-upset winner now on the road vs. a weaker team, rested, after winning by 1-9 (on trial)",
    23: "Fade a road-upset winner now home vs. a weaker team after winning by 10+ (on trial)",
    24: "Fade a road-upset winner now home, rested, after winning by 1-9 as less than a 7-pt dog (on trial)",
    25: "Fade a road-upset winner vs. a weaker team after winning by 10+ as less than a 7-pt dog (on trial)",
    26: "Fade a road-upset winner now on the road vs. a weaker team, rested (on trial)",
    27: "Fade a road-upset winner vs. a weaker team, rested, after winning by 10+ as less than a 7-pt dog (on trial)",
    28: "Fade a road-upset winner now home after winning by 1-9 as less than a 7-pt dog (on trial)",
    29: "Fade a road-upset winner now on the road vs. a weaker team after winning by 1-9 (on trial)",
    33: "Back a team after a 30+ point win, now home vs. a stronger team (on trial)",
    34: "Back a team after a 30+ point road win where it wasn't a 7+ pt favorite (on trial)",
}
# Backtest rate, then the record replayed on six seasons none of the rules
# were found on: 2016-17 through 2019-20, 2023-24 and 2024-25.
RULE_BACKTEST = {
    2: "63.6% ATS, n=77; 6 unseen seasons: 95-62", 9: "68.1% ATS, n=91; 6 unseen seasons: 62-49",
    14: "62.3% ATS, n=122; 6 unseen seasons: 91-67", 16: "68.5% ATS, n=54; 6 unseen seasons: 37-24",
    17: "65.5% ATS, n=58; 6 unseen seasons: 39-24",
    18: "61.7% ATS, n=47 (2022-23 to 2025-26), covered every season; on trial",
    19: "65.9% ATS, n=44 (2022-23 to 2025-26), covered every season; on trial",
    20: "71.4% ATS, n=42 (30-12) (2022-23 to 2025-26); on trial",
    21: "67.3% ATS, n=55 (37-18) (2022-23 to 2025-26); on trial",
    22: "65.5% ATS, n=58 (38-20) (2022-23 to 2025-26); on trial",
    23: "64.3% ATS, n=42 (27-15) (2022-23 to 2025-26); on trial",
    24: "63.1% ATS, n=84 (53-31) (2022-23 to 2025-26); on trial",
    25: "63.1% ATS, n=84 (53-31) (2022-23 to 2025-26); on trial",
    26: "62.9% ATS, n=105 (66-39) (2022-23 to 2025-26); on trial",
    27: "62.5% ATS, n=64 (40-24) (2022-23 to 2025-26); on trial",
    28: "62.4% ATS, n=101 (63-38) (2022-23 to 2025-26); on trial",
    29: "62.3% ATS, n=69 (43-26) (2022-23 to 2025-26); on trial",
    33: "66.0% ATS, n=47 (31-16, 2022-23 to 2025-26), covered every season; on trial",
    34: "63.2% ATS, n=57 (36-21, 2022-23 to 2025-26), covered every season; on trial",
}
# A pick two or more rules agree on ("stacked"), replayed on the same six
# unseen seasons: one-rule picks went 57.4% (269-200).
STACKED_BACKTEST = "67.5% ATS, 27-13 (replay on 6 unseen seasons); one-rule picks 57.4%"


# Rules 20-29 are overlapping slices of one situation (a road-upset win), so
# several firing on one game is not independent agreement: "stacked" counts
# distinct families, not rules.
FAMILY = {n: "road-upset" for n in range(20, 30)}


def families(nums):
    return len({FAMILY.get(n, n) for n in nums})
