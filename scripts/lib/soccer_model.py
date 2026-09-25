"""Soccer (3-way home/draw/away market) scoring logic.

Only the grading half lives here — there is no live scheduled Routine that
generates EPL picks, so this repo never assembles a slate for it; if one
ever ran and mirrored data/epl/<date>.json here, score_slate.py would grade
it with grade_game below (moneyline-only — soccer has no standard point
spread the way NFL/MLB do)."""


def grade_game(g, away_score, home_score):
    """3-way moneyline-only grading — no spread/ATS for soccer.

    `pick`/`altPick` are the exact team name (matching `away`/`home`) or the
    literal "Draw" — same convention as every other sport's pick field, not
    a "home"/"away" side label — so results must be resolved against the
    game's own team names before comparing to the actual outcome."""
    result = {"correct": None, "pickReturn": None, "altCorrect": None, "altReturn": None}
    if away_score is None or home_score is None:
        return result

    if away_score > home_score:
        outcome = "away"
    elif home_score > away_score:
        outcome = "home"
    else:
        outcome = "draw"

    def resolve_side(pick):
        if pick is None:
            return None
        if pick == g["away"]:
            return "away"
        if pick == g["home"]:
            return "home"
        if pick.lower() == "draw":
            return "draw"
        return None

    price_for = {"away": g.get("awayMoneyline"), "draw": g.get("drawMoneyline"), "home": g.get("homeMoneyline")}

    for pick_field, correct_field, return_field in (("pick", "correct", "pickReturn"), ("altPick", "altCorrect", "altReturn")):
        side = resolve_side(g.get(pick_field))
        if side is None:
            continue
        correct = (side == outcome)
        price = price_for.get(side)
        if price is None:
            pick_return = None
        else:
            pick_return = _moneyline_payout(price) if correct else -100.0
        result[correct_field] = correct
        result[return_field] = pick_return

    return result


def _moneyline_payout(odds):
    if odds is None:
        return None
    if odds > 0:
        return float(odds)
    return round(10000 / abs(odds), 2)
