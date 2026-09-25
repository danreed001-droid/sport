"""Season-to-date / slate results aggregation for both predictors."""


def _totals(games, pick_key, correct_key, return_key, cover_key, spread_return_key):
    wins = losses = 0
    ml_profit = 0.0
    ats_w = ats_l = ats_p = 0
    ats_profit = 0.0
    for g in games:
        if g.get(pick_key) is None:
            continue
        correct = g.get(correct_key)
        if correct is True:
            wins += 1
        elif correct is False:
            losses += 1
        ret = g.get(return_key)
        if ret is not None:
            ml_profit += ret
        sret = g.get(spread_return_key)
        if sret is not None:
            ats_profit += sret
            cover = g.get(cover_key)
            if cover is True:
                ats_w += 1
            elif cover is False:
                ats_l += 1
            else:
                ats_p += 1
    return {
        "straightUp": f"{wins}-{losses}",
        "moneylineProfit": round(ml_profit, 2),
        "ats": f"{ats_w}-{ats_l}-{ats_p}",
        "atsProfit": round(ats_profit, 2),
    }


def ledger_totals(games):
    return _totals(games, "pick", "correct", "pickReturn", "pickCover", "pickSpreadReturn")


def second_opinion_totals(games):
    return _totals(games, "altPick", "altCorrect", "altReturn", "altCover", "altSpreadReturn")


def _signal_totals(games, favors_key, correct_key, return_key, cover_key, spread_return_key):
    t = _totals(games, favors_key, correct_key, return_key, cover_key, spread_return_key)
    t["n"] = sum(1 for g in games if g.get(favors_key) is not None)
    return t


def trend_signal_totals(games):
    return _signal_totals(games, "altTrendFavors", "altTrendCorrect", "altTrendReturn", "altTrendCover", "altTrendSpreadReturn")


def blowout_signal_totals(games):
    return _signal_totals(games, "altBlowoutFavors", "altBlowoutCorrect", "altBlowoutReturn", "altBlowoutCover", "altBlowoutSpreadReturn")


def report_for(all_docs, slate_date=None):
    all_games = []
    slate_games = []
    for date_str, doc in all_docs:
        if not doc.get("scored"):
            continue
        games = doc.get("games", [])
        all_games.extend(games)
        if date_str == slate_date:
            slate_games = games
    return {
        "slate": {
            "ledger": ledger_totals(slate_games),
            "secondOpinion": second_opinion_totals(slate_games),
            "trendSignal": trend_signal_totals(slate_games),
            "blowoutSignal": blowout_signal_totals(slate_games),
        },
        "seasonToDate": {
            "ledger": ledger_totals(all_games),
            "secondOpinion": second_opinion_totals(all_games),
            "trendSignal": trend_signal_totals(all_games),
            "blowoutSignal": blowout_signal_totals(all_games),
        },
    }
