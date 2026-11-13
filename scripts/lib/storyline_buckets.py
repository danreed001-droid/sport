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


# Computed 2026-11-13 from each sport's storyline research data, replaying the
# selected storylines with the card's weights (each storyline reproduced its
# STORIES record). NBA: 2018-19 and 2021-22 to 2025-26, both teams 8+ games
# (pushes not kept). NFL 2010-2025, CFB FBS vs FBS 2015-2025, MLB 2015-2025
# (2020 out in all three); soccer the research's leagues and seasons. MLB and
# soccer are judged against the odds' implied win %, not 50%.
BACKTEST = {
    "nba": {"1": [1549, 1320, 0], "1.5-2": [496, 367, 0], "2.5-3": [81, 54, 0], "3.5+": [22, 9, 0]},
    "ncaab": {"1": [1331, 1198, 32], "1.5-2": [677, 549, 13], "2.5-3": [358, 300, 8], "3.5+": [250, 182, 9]},
    "nfl": {"1": [634, 541, 42], "1.5-2": [166, 117, 6], "2.5-3": [32, 16, 0], "3.5+": [5, 1, 1]},
    "cfb": {"1": [1043, 882, 24], "1.5-2": [174, 136, 5], "2.5-3": [24, 23, 1], "3.5+": [4, 1, 0]},
    "mlb": {"1": [361, 338, 0], "1.5-2": [527, 423, 0], "2.5-3": [18, 12, 0], "3.5+": [0, 0, 0]},
    "soccer": {"1": [407, 569, 0], "1.5-2": [0, 0, 0], "2.5-3": [0, 0, 0], "3.5+": [0, 0, 0]},
}
NOTES = {
    "nba": "NBA 2018-19 and 2021-22 to 2025-26",
    "ncaab": "games with an AP Top 25 team, 2015-16 to 2025-26 without 2020-21; bigger leans are almost all toward the home team (home teams covered 52.4%), so part of the climb is home court counted several times",
    "nfl": "NFL regular seasons 2010-2025 without 2020",
    "cfb": "FBS vs FBS regular seasons 2015-2025 without 2020",
    "mlb": "MLB 2015-2025 without 2020; the odds priced the leaned team at about 50% (so 50% is break-even-ish, before the vig)",
    "soccer": "big five leagues, MLS and Liga MX, 2018-19 to 2025-26; only 1-point leans happen (no two soccer storylines pointed the same way), and the leaned team was priced to win 37.6%, so 41.7% beat the odds",
}
