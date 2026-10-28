"""NBA Stats rule names and backtest rates, shared by the signal engine
(scripts/nba_stats_signals.py) and the site build (scripts/build_site.py),
which has no network dependencies."""

RULE_NAMES = {
    1: "Fade a 5+ game win streak at home vs. a weaker team",
    2: "Fade an OT winner vs. a stronger team",
    3: "Fade a blown 10+ point lead at home vs. a weaker team",
    4: "Back a home team after its top scorer's cold night",
    5: "Back a home team vs. a weaker team after a 22+ turnover loss",
    6: "Fade a team after an 18+ assist edge",
    7: "Back a road team after being out-assisted by 18+",
    8: "Fade a close win built on 6+ more steals",
    9: "Fade a late comeback on the back-to-back",
}
RULE_BACKTEST = {
    1: "57.2% ATS, n=208", 2: "63.6% ATS, n=77", 3: "60.8% ATS, n=79", 4: "57.9% ATS, n=537",
    5: "62.1% ATS, n=29", 6: "64.2% ATS, n=53", 7: "69.2% ATS, n=26", 8: "61.0% ATS, n=141",
    9: "68.1% ATS, n=91",
}
