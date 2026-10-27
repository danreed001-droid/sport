"""Per-sport configuration registry, used by the deterministic scoring
pipeline (score_slate.py/fetch_scores.py/run.py) and the report builder.

Picks for every sport but nba_stats are generated entirely by the live
"Diamond Ledger" scheduled Routines (NFL, CFB, MLB, Basketball) in
claude.ai, each running its own real research and mirroring the slate it
generates into data/<collection>/<date>.json in this repo. nba_stats is the
one exception: its slate is generated in this repo too, deterministically,
by scripts/nba_stats_signals.py -- no LLM research needed since it's just a
fixed set of backtested trigger conditions. "model" below is only set for a
sport whose *scoring* needs sport-specific grading logic (currently just
the three-way soccer market); two-way sports all grade through the shared
logic in score_slate.py.
"""

SPORTS = {
    "nfl": {
        "label": "NFL",
        "collection": "nfl",
        "kind": "two_way",
        "espn_sport": "football",
        "espn_league": "nfl",
    },
    "cfb": {
        "label": "College Football (FBS)",
        "collection": "cfb",
        "kind": "two_way",
        "espn_sport": "football",
        "espn_league": "college-football",
    },
    "mlb": {
        "label": "MLB",
        "collection": "mlb",
        "kind": "two_way",
        "espn_sport": "baseball",
        "espn_league": "mlb",
    },
    "nba": {
        "label": "NBA",
        "collection": "nba",
        "kind": "two_way",
        "espn_sport": "basketball",
        "espn_league": "nba",
    },
    "ncaab": {
        # Men's college basketball, AP Top 25-involving games only, per the
        # live "Diamond Ledger — Basketball" Routine's scope.
        "label": "NCAA Basketball",
        "collection": "ncaab",
        "kind": "two_way",
        "espn_sport": "basketball",
        "espn_league": "mens-college-basketball",
    },
    "soccer": {
        # The live "Diamond Ledger — Soccer" Routine's collection: matches from
        # several competitions (MLS, Liga MX, UEFA, CONMEBOL...) in one daily
        # doc. Graded here like every other sport, from ESPN's combined
        # "all" soccer scoreboard, which spans every competition at once.
        "label": "Soccer",
        "collection": "soccer",
        "model": "soccer_model",
        "kind": "three_way",
        "espn_sport": "soccer",
        "espn_league": "all",
        # Slates carry their own prices; skip the per-match odds lookups the
        # combined feed would otherwise need (hundreds of matches a day).
        "summary_odds": False,
    },
    "nba_stats": {
        # Rule-based NBA signal engine (scripts/nba_stats_signals.py), not a
        # live research Routine like the others: deterministic, backtested
        # trigger conditions fade a team coming off one of three specific
        # situations (5+ win streak, an OT win, a blown 10+ point lead) when
        # the matchup/opponent context from the backtest also holds. Sparse
        # by design -- most slates have no qualifying game at all.
        "label": "NBA Stats",
        "collection": "nba_stats",
        "kind": "two_way",
        "espn_sport": "basketball",
        "espn_league": "nba",
    },
    "epl": {
        # No live scheduled Routine generates this one yet, so it stays
        # empty in the real report until one exists. English Premier League
        # by default; point espn_league at a different soccer league to
        # cover another one instead.
        "label": "Premier League",
        "collection": "epl",
        "model": "soccer_model",
        "kind": "three_way",
        "espn_sport": "soccer",
        "espn_league": "eng.1",
    },
}


def get(sport_key):
    if sport_key not in SPORTS:
        raise ValueError(f"Unknown sport '{sport_key}'. Configured: {list(SPORTS)}")
    return SPORTS[sport_key]
