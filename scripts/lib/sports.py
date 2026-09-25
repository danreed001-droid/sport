"""Per-sport configuration registry, used by the deterministic scoring
pipeline (score_slate.py/fetch_scores.py/run.py) and the report builder.

Picks themselves are generated entirely by the live "Diamond Ledger"
scheduled Routines (NFL, CFB, MLB, Basketball) in claude.ai, each running its
own real research and mirroring the slate it generates into
data/<collection>/<date>.json in this repo. Nothing in this repo generates
picks — "model" below is only set for a sport whose *scoring* needs
sport-specific grading logic (currently just the three-way soccer market);
two-way sports all grade through the shared logic in score_slate.py.
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
