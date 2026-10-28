"""NBA Stats rule names and backtest rates, shared by the signal engine
(scripts/nba_stats_signals.py) and the site build (scripts/build_site.py),
which has no network dependencies. Each rule only fires on the rest days
where it backtested at 62%+ ATS; the rates below are for those days.
Retired: rule 4 (no rest situation cleared 62%); rules 1, 3, 6, 7, 8, 10,
11, 12 and 15, which went under 60% ATS when replayed on 2023-24 and 2024-25
-- seasons none of the rules were found on; and rules 5 and 13, which then
went under 60% on 2018-19 and 2019-20 too."""

RULE_NAMES = {
    2: "Fade an OT winner vs. a stronger team (any rest)",
    9: "Fade a late comeback on the back-to-back",
    14: "Fade a team on a back-to-back vs. a weaker team after all 5 starters scored 10+ in a win",
    16: "Back a home team on a back-to-back after losing to a team that shot 50%+ from three",
    17: "Fade a home team after a win where it allowed 130+ (any rest)",
}
# Backtest rate, then the record replayed on four seasons none of the rules
# were found on: 2018-19, 2019-20, 2023-24 and 2024-25.
RULE_BACKTEST = {
    2: "63.6% ATS, n=77; unseen seasons: 65-43", 9: "68.1% ATS, n=91; unseen seasons: 44-26",
    14: "62.3% ATS, n=122; unseen seasons: 77-48", 16: "68.5% ATS, n=54; unseen seasons: 28-13",
    17: "65.5% ATS, n=58; unseen seasons: 35-22",
}
