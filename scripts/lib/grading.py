"""Pure grading math — no LLM, no network. Mirrors the Diamond Ledger
SCORING rules exactly (moneyline payout, big-underdog rule, ATS cover/return).
"""


def moneyline_payout(odds):
    """Profit on a flat $100 bet at American odds, if the bet wins."""
    if odds is None:
        return None
    if odds > 0:
        return float(odds)
    return round(10000 / abs(odds), 2)


def grade_pick(pick_team, pick_score, other_score, moneyline, spread_for_pick, spread_odds_for_pick):
    """Grade one predictor's pick against a finished game.

    Returns {correct, pickReturn, pickCover, pickSpreadReturn}. Ties,
    postponements/cancellations, and games with no pick all fall out of this
    naturally as None (missing scores or missing pick_team).
    """
    if pick_team is None or pick_score is None or other_score is None:
        return {"correct": None, "pickReturn": None, "pickCover": None, "pickSpreadReturn": None}

    if pick_score == other_score:
        return {"correct": None, "pickReturn": None, "pickCover": None, "pickSpreadReturn": None}

    correct = pick_score > other_score
    big_underdog = spread_for_pick is not None and spread_for_pick > 10

    if big_underdog or moneyline is None:
        pick_return = None
    else:
        pick_return = moneyline_payout(moneyline) if correct else -100.0

    if spread_for_pick is None:
        pick_cover = None
        pick_spread_return = None
    else:
        margin = (pick_score - other_score) + spread_for_pick
        if margin > 0:
            pick_cover = True
        elif margin < 0:
            pick_cover = False
        else:
            pick_cover = None  # push

        spread_odds = spread_odds_for_pick if spread_odds_for_pick is not None else -110
        if pick_cover is None:
            pick_spread_return = 0.0
        elif pick_cover:
            pick_spread_return = moneyline_payout(spread_odds)
        else:
            pick_spread_return = -100.0

    return {
        "correct": correct,
        "pickReturn": pick_return,
        "pickCover": pick_cover,
        "pickSpreadReturn": pick_spread_return,
    }
