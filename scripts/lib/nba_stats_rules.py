"""NBA Stats rule names and backtest rates, shared by the signal engine
(scripts/nba_stats_signals.py) and the site build (scripts/build_site.py),
which has no network dependencies. Each rule only fires on the rest days
where it backtested at 62%+ ATS; the rates below are for those days.
Rule 4 (back a home team after its top scorer's cold night) was retired:
no rest situation cleared 62%."""

RULE_NAMES = {
    1: "Fade a 5+ game win streak at home vs. a weaker team (back-to-back)",
    2: "Fade an OT winner vs. a stronger team (any rest)",
    3: "Fade a blown 10+ point lead at home vs. a weaker team (back-to-back)",
    5: "Back a home team vs. a weaker team after a 22+ turnover loss (back-to-back)",
    6: "Fade a team after an 18+ assist edge (1 day of rest)",
    7: "Back a road team after being out-assisted by 18+ (back-to-back or 1 day)",
    8: "Fade a close win built on 6+ more steals (back-to-back or 2+ days)",
    9: "Fade a late comeback on the back-to-back",
    10: "Fade a team out-rebounded by 18+ (2+ days of rest)",
}
RULE_BACKTEST = {
    1: "65.3% ATS, n=49", 2: "63.6% ATS, n=77", 3: "79.2% ATS, n=24", 5: "77.8% ATS, n=9",
    6: "79.2% ATS, n=24", 7: "72.7% ATS, n=22", 8: "64.5% ATS, n=62", 9: "68.1% ATS, n=91",
    10: "72.4% ATS, n=58",
}
