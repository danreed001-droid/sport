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


def cumulative_series(games, return_key):
    """Running total of `return_key` by date, for a bankroll-growth chart.
    Expects each game dict to carry its own "date" (the caller flattens docs
    into games and stamps the doc's date onto each one first)."""
    by_date = {}
    for g in games:
        date = g.get("date")
        if date is None:
            continue
        by_date.setdefault(date, 0.0)
        r = g.get(return_key)
        if r is not None:
            by_date[date] += r
    running = 0.0
    series = []
    for date in sorted(by_date):
        running += by_date[date]
        series.append({"date": date, "value": round(running, 2)})
    return series


def html_payload(label, kind, games):
    """Shape consumed by the report template (scripts/report/template.html),
    for one league. `games` must already have "date" stamped on each item.

    Trend/blowout/rest-blowout "extra signal" blocks are included only when
    this league's own games actually carry that field — checked by key
    presence, not by whether it ever fired, so a real 0-0-0 record still
    shows up for a sport that tracks the check."""
    if kind == "three_way":
        ledger = _totals(games, "pick", "correct", "pickReturn", "pickCover", "pickSpreadReturn")
        alt = _totals(games, "altPick", "altCorrect", "altReturn", "altCover", "altSpreadReturn")
    else:
        ledger = ledger_totals(games)
        alt = second_opinion_totals(games)

    payload = {
        "label": label, "kind": kind,
        "ledger": ledger, "secondOpinion": alt,
        "ledgerSeries": cumulative_series(games, "pickReturn"),
        "altSeries": cumulative_series(games, "altReturn"),
        "games": sorted(games, key=lambda g: g.get("date", ""), reverse=True),
    }
    if any("altTrendFavors" in g for g in games):
        payload["trendSignal"] = trend_signal_totals(games)
    if any("altBlowoutFavors" in g for g in games):
        payload["blowoutSignal"] = blowout_signal_totals(games)
    if any("altRestBlowoutFavors" in g for g in games):
        payload["restBlowoutSignal"] = _signal_totals(
            games, "altRestBlowoutFavors", "altRestBlowoutCorrect",
            "altRestBlowoutReturn", "altRestBlowoutCover", "altRestBlowoutSpreadReturn",
        )
    return payload


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
