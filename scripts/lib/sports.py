"""Per-sport configuration registry. NFL and CFB mirror the same Ledger +
Second Opinion rules (per the existing Diamond Ledger skills for each),
differing only in the constants below. Adding a new sport that follows the
same shape means adding one entry here.
"""

SPORTS = {
    "nfl": {
        "label": "NFL",
        "collection": "nfl",
        "model": "nfl_model",
        "kind": "two_way",
        "espn_sport": "football",
        "espn_league": "nfl",
        "qb_veto_threshold": 5.0,
        "qb_rating_note": "NFL passer rating (0-158.3 scale)",
    },
    "cfb": {
        "label": "College Football (FBS)",
        "collection": "cfb",
        "model": "nfl_model",
        "kind": "two_way",
        "espn_sport": "football",
        "espn_league": "college-football",
        # TENTATIVE per the Diamond Ledger CFB skill — carried over from the
        # NFL number, scaled for the wider NCAA passer-efficiency range.
        # Flag to the user for confirmation once real CFB slates run.
        "qb_veto_threshold": 8.0,
        "qb_rating_note": "NCAA passer efficiency rating (wider scale, often 130-170+ for good starters)",
    },
    "mlb": {
        "label": "MLB",
        "collection": "mlb",
        "model": "mlb_model",
        "kind": "two_way",
        "espn_sport": "baseball",
        "espn_league": "mlb",
    },
    "nba": {
        # nba_model.py here is a standalone experimental model (offensive/net
        # rating + star-veto), NOT what generates the real "nba" collection
        # data — that comes from the live "Diamond Ledger — Basketball"
        # scheduled Routine, whose actual schema is ORtg/DRtg + defense-veto.
        # The report only needs the universal pick/correct/return fields,
        # which are consistent across both, so this entry is just for label/
        # collection/kind lookup in build_report.py.
        "label": "NBA",
        "collection": "nba",
        "model": "nba_model",
        "kind": "two_way",
        "espn_sport": "basketball",
        "espn_league": "nba",
    },
    "ncaab": {
        # Men's college basketball, AP Top 25-involving games only — mirrors
        # the real "Diamond Ledger — Basketball" scheduled Routine's schema
        # (awayORtg/homeORtg/awayDRtg/homeDRtg + defense-veto), not the
        # nba_model.py file (that model is NOT used to generate this data;
        # the report only reads the universal pick/correct/return fields).
        "label": "NCAA Basketball",
        "collection": "ncaab",
        "model": "nba_model",
        "kind": "two_way",
        "espn_sport": "basketball",
        "espn_league": "mens-college-basketball",
    },
    "epl": {
        # EXPERIMENTAL: 3-way (home/draw/away) market, no prior Diamond
        # Ledger skill. Defaults to the English Premier League; point
        # espn_league at a different soccer league to cover another one.
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
