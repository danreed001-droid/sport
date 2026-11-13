"""How a game's storylines did by the size of their weighted net lean (the
card's tally: weight 2 for STRONG, 0.5 for WEAK, else 1): the backtest
record per sport. The pick sheet adds this season's finished games
(build_site.storyline_strength) for an all-in record that keeps updating.

Buckets of |net lean|: "1" (0-1), "1.5-2", "2.5-3", "3.5+". Values are
[wins, losses, pushes] for the side the storylines leaned to: ATS at the
closing spread (NBA, NFL, CFB), the moneyline winner (MLB), the leaned-to
team winning (soccer; a draw is a miss).
"""

BUCKETS = ("1", "1.5-2", "2.5-3", "3.5+")


def bucket(net):
    a = abs(net)
    return "1" if a <= 1 else "1.5-2" if a <= 2 else "2.5-3" if a <= 3 else "3.5+"


def net_toward_home(game):
    """The card's weighted tally as one number: + leans home, - leans away."""
    toward = {}
    for e in game.get("storylines") or []:
        lean = e.get("leans")
        if not lean:
            continue
        w = float(e.get("weight") or 1)
        toward[lean] = toward.get(lean, 0) + (-w if e.get("unit") == "not to win" else w)
    return toward.get(game.get("home"), 0) - toward.get(game.get("away"), 0)


# NBA: 2018-19 and 2021-22 to 2025-26, both teams 8+ games (pushes not kept).
BACKTEST = {
    "nba": {"1": [1549, 1320, 0], "1.5-2": [496, 367, 0], "2.5-3": [81, 54, 0], "3.5+": [22, 9, 0]},
}
NOTES = {
    "nba": "NBA backtest 2018-19 and 2021-22 to 2025-26",
}
