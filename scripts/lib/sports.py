"""Per-sport configuration registry. NFL and CFB mirror the same Ledger +
Second Opinion rules (per the existing Diamond Ledger skills for each),
differing only in the constants below. Adding a new sport that follows the
same shape means adding one entry here.
"""

SPORTS = {
    "nfl": {
        "label": "NFL",
        "collection": "nfl",
        "espn_sport": "football",
        "espn_league": "nfl",
        "qb_veto_threshold": 5.0,
        "qb_rating_note": "NFL passer rating (0-158.3 scale)",
        "offense_pool_fixed_n": 32,
        "spread_kind": "spread",
    },
    "cfb": {
        "label": "College Football (FBS)",
        "collection": "cfb",
        "espn_sport": "football",
        "espn_league": "college-football",
        # TENTATIVE per the Diamond Ledger CFB skill — carried over from the
        # NFL number, scaled for the wider NCAA passer-efficiency range.
        # Flag to the user for confirmation once real CFB slates run.
        "qb_veto_threshold": 8.0,
        "qb_rating_note": "NCAA passer efficiency rating (wider scale, often 130-170+ for good starters)",
        "offense_pool_fixed_n": None,  # dynamic: rank among however many FBS teams have played
        "spread_kind": "spread",
    },
}


def get(sport_key):
    if sport_key not in SPORTS:
        raise ValueError(f"Unknown sport '{sport_key}'. Configured: {list(SPORTS)}")
    return SPORTS[sport_key]
