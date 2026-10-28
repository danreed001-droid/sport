"""NBA Stats rule names and backtest rates, shared by the signal engine
(scripts/nba_stats_signals.py) and the site build (scripts/build_site.py),
which has no network dependencies. Each rule only fires on the rest days
where it backtested at 62%+ ATS; the rates below are for those days.
Retired: rule 4 (no rest situation cleared 62%), and rules 1, 3, 6, 7, 8,
10, 11, 12 and 15, which went under 60% ATS when replayed on 2023-24 and
2024-25 -- seasons none of the rules were found on."""

RULE_NAMES = {
    2: "Fade an OT winner vs. a stronger team (any rest)",
    5: "Back a home team vs. a weaker team after a 22+ turnover loss (back-to-back)",
    9: "Fade a late comeback on the back-to-back",
    13: "Fade a team vs. a weaker team after its top scorer's 1.5x+ night in a loss (back-to-back or 2+ days)",
    14: "Fade a team on a back-to-back vs. a weaker team after all 5 starters scored 10+ in a win",
    16: "Back a home team on a back-to-back after losing to a team that shot 50%+ from three",
    17: "Fade a home team after a win where it allowed 130+ (any rest)",
}
# Backtest rate, then the record when replayed on 2023-24 and 2024-25 (unseen).
RULE_BACKTEST = {
    2: "63.6% ATS, n=77; unseen 2023-25: 31-13", 5: "77.8% ATS, n=9; unseen 2023-25: 3-1",
    9: "68.1% ATS, n=91; unseen 2023-25: 24-15", 13: "75.8% ATS, n=33; unseen 2023-25: 6-3",
    14: "62.3% ATS, n=122; unseen 2023-25: 49-29", 16: "68.5% ATS, n=54; unseen 2023-25: 15-10",
    17: "65.5% ATS, n=58; unseen 2023-25: 21-13",
}
