#!/usr/bin/env python3
"""Builds a realistic DEMO dataset for previewing the Diamond Ledger report,
using the same grading/report math as production (lib/grading.py,
lib/report.py, lib/soccer_model.grade_game) so the numbers shown are
internally consistent. This data is hand-crafted for the preview only and
is never written into data/<sport>/ — it must never be mistaken for real
season history.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from lib.grading import grade_pick  # noqa: E402
from lib import report as report_lib  # noqa: E402
from lib.soccer_model import grade_game as soccer_grade_game  # noqa: E402

OUT_PATH = os.path.join(os.path.dirname(__file__), "demo_data.json")

# Each row: date, away, home, awayScore, homeScore, pick, confidence, altPick,
# altConfidence, awayMoneyline, homeMoneyline, awaySpread, homeSpread,
# awaySpreadOdds, homeSpreadOdds
NFL_GAMES = [
    ("2026-09-07", "Kansas City Chiefs", "Baltimore Ravens", 20, 24, "Baltimore Ravens", "lean", "Baltimore Ravens", "lean", 145, -170, 3.5, -3.5, -110, -110),
    ("2026-09-07", "Philadelphia Eagles", "Dallas Cowboys", 27, 20, "Philadelphia Eagles", "solid", "Philadelphia Eagles", "strong", -210, 175, -5.5, 5.5, -110, -110),
    ("2026-09-14", "Buffalo Bills", "New York Jets", 30, 10, "Buffalo Bills", "solid", "Buffalo Bills", "strong", -280, 230, -7.5, 7.5, -110, -110),
    ("2026-09-14", "San Francisco 49ers", "Minnesota Vikings", 17, 24, "San Francisco 49ers", "lean", None, "pass", -160, 135, -3.0, 3.0, -110, -110),
    ("2026-09-20", "Philadelphia Eagles", "Tennessee Titans", 24, 20, "Philadelphia Eagles", "solid", None, "pass", -350, 280, -7.0, 7.0, -110, -110),
    ("2026-09-20", "New Orleans Saints", "Baltimore Ravens", 24, 17, "Baltimore Ravens", "solid", None, "pass", 340, -430, 8.5, -8.5, -115, -105),
    ("2026-09-20", "Jacksonville Jaguars", "Denver Broncos", 13, 20, "Jacksonville Jaguars", "solid", None, "pass", 126, -148, 2.5, -2.5, -102, -120),
    ("2026-09-21", "New York Giants", "Los Angeles Rams", 6, 28, "New York Giants", "solid", None, "pass", 250, -310, 6.5, -6.5, -102, -120),
    ("2026-09-24", "Atlanta Falcons", "Green Bay Packers", 35, 14, None, "skip", None, "pass", 205, -250, 5.5, -5.5, -115, -105),
    ("2026-09-28", "Buffalo Bills", "New Orleans Saints", 31, 19, "Buffalo Bills", "solid", "Buffalo Bills", "strong", -650, 450, -13.5, 13.5, -110, -110),
    ("2026-09-28", "Detroit Lions", "Cleveland Browns", 34, 10, "Detroit Lions", "solid", "Detroit Lions", "lean", -400, 320, -9.5, 9.5, -110, -110),
]

CFB_GAMES = [
    ("2026-09-06", "Alabama Crimson Tide", "Wisconsin Badgers", 34, 10, "Alabama Crimson Tide", "solid", "Alabama Crimson Tide", "strong", -320, 260, -8.5, 8.5, -110, -110),
    ("2026-09-13", "Ohio State Buckeyes", "Texas Longhorns", 17, 21, "Ohio State Buckeyes", "lean", None, "pass", -140, 120, -2.5, 2.5, -110, -110),
    ("2026-09-13", "Oregon Ducks", "Northwestern Wildcats", 40, 13, "Oregon Ducks", "solid", "Oregon Ducks", "strong", -900, 550, -20.5, 20.5, -110, -110),
    ("2026-09-20", "Georgia Bulldogs", "Kentucky Wildcats", 31, 14, "Georgia Bulldogs", "solid", None, "pass", -400, 320, -10.5, 10.5, -110, -110),
    ("2026-09-20", "Miami Hurricanes", "Florida Gators", 26, 20, "Miami Hurricanes", "lean", "Miami Hurricanes", "lean", -155, 130, -3.0, 3.0, -110, -110),
    ("2026-09-27", "Penn State Nittany Lions", "Iowa Hawkeyes", 27, 24, "Penn State Nittany Lions", "toss-up", None, "pass", -190, 158, -3.5, 3.5, -110, -110),
    ("2026-09-27", "Texas A&M Aggies", "Arkansas Razorbacks", 21, 17, "Texas A&M Aggies", "toss-up", "Arkansas Razorbacks", "lean", -175, 148, -3.5, 3.5, -108, -112),
]

MLB_GAMES = [
    ("2026-09-10", "Los Angeles Dodgers", "San Diego Padres", 6, 2, "Los Angeles Dodgers", "solid", "Los Angeles Dodgers", "strong", -175, 144, -1.5, 1.5, -130, 110),
    ("2026-09-11", "New York Yankees", "Boston Red Sox", 3, 4, "New York Yankees", "lean", None, "pass", -140, 120, -1.5, 1.5, 150, -175),
    ("2026-09-12", "Atlanta Braves", "Philadelphia Phillies", 5, 3, "Atlanta Braves", "lean", "Atlanta Braves", "lean", 110, -130, 1.5, -1.5, -110, -110),
    ("2026-09-15", "Houston Astros", "Seattle Mariners", 2, 6, "Houston Astros", "solid", None, "pass", -160, 138, -1.5, 1.5, 105, -125),
    ("2026-09-16", "Milwaukee Brewers", "Chicago Cubs", 7, 1, "Milwaukee Brewers", "solid", "Milwaukee Brewers", "strong", -145, 124, -1.5, 1.5, -115, -105),
    ("2026-09-18", "Detroit Tigers", "Cleveland Guardians", 4, 3, "Detroit Tigers", "toss-up", None, "pass", -120, 100, -1.5, 1.5, 145, -165),
    ("2026-09-19", "Los Angeles Dodgers", "Arizona Diamondbacks", 8, 2, "Los Angeles Dodgers", "solid", "Los Angeles Dodgers", "strong", -240, 195, -1.5, 1.5, -145, 122),
    ("2026-09-22", "New York Mets", "Washington Nationals", 3, 5, "New York Mets", "lean", "New York Mets", "lean", -165, 140, -1.5, 1.5, -120, 102),
    ("2026-09-23", "San Diego Padres", "Colorado Rockies", 6, 4, "San Diego Padres", "solid", None, "pass", -220, 182, -1.5, 1.5, -160, 138),
]

NBA_GAMES = [
    ("2026-10-22", "Boston Celtics", "New York Knicks", 118, 109, "Boston Celtics", "solid", "Boston Celtics", "strong", -195, 165, -4.5, 4.5, -110, -110),
    ("2026-10-23", "Denver Nuggets", "Oklahoma City Thunder", 112, 120, None, "skip", "Oklahoma City Thunder", "lean", 130, -155, 3.0, -3.0, -110, -110),
    ("2026-10-24", "Minnesota Timberwolves", "Los Angeles Lakers", 108, 101, "Minnesota Timberwolves", "lean", None, "pass", -130, 110, -2.0, 2.0, -110, -110),
    ("2026-10-25", "Milwaukee Bucks", "Miami Heat", 115, 104, "Milwaukee Bucks", "solid", "Milwaukee Bucks", "lean", -220, 182, -5.5, 5.5, -110, -110),
    ("2026-10-27", "Phoenix Suns", "Golden State Warriors", 99, 112, "Phoenix Suns", "toss-up", "Golden State Warriors", "lean", 145, -170, 4.0, -4.0, -110, -110),
    ("2026-10-28", "Dallas Mavericks", "San Antonio Spurs", 121, 118, "Dallas Mavericks", "lean", None, "pass", -150, 128, -3.5, 3.5, -110, -110),
]

# 3-way: away, home, awayScore, homeScore, pick, altPick, awayMoneyline, drawMoneyline, homeMoneyline
EPL_GAMES = [
    ("2026-08-16", "Arsenal", "Nottingham Forest", 3, 0, "Arsenal", "Arsenal", -175, 320, 420),
    ("2026-08-23", "Liverpool", "Everton", 2, 2, "Liverpool", "Draw", -140, 260, 350),
    ("2026-08-30", "Manchester City", "Brighton", 3, 1, "Manchester City", "Manchester City", -260, 380, 650),
    ("2026-09-13", "Chelsea", "Tottenham", 1, 1, "Draw", "Draw", 210, 230, 130),
    ("2026-09-20", "Newcastle", "Aston Villa", 1, 2, "Newcastle", None, 155, 230, 165),
    ("2026-09-27", "Manchester United", "West Ham", 1, 1, "Manchester United", "Draw", -155, 250, 400),
]


def build_two_way(games):
    rows = []
    for (date, away, home, away_score, home_score, pick, conf, alt_pick, alt_conf,
         away_ml, home_ml, away_spread, home_spread, away_sp_odds, home_sp_odds) in games:
        g = {
            "date": date, "away": away, "home": home,
            "awayScore": away_score, "homeScore": home_score,
            "pick": pick, "confidence": conf, "altPick": alt_pick, "altConfidence": alt_conf,
            "awayMoneyline": away_ml, "homeMoneyline": home_ml,
            "awaySpread": away_spread, "homeSpread": home_spread,
            "awaySpreadOdds": away_sp_odds, "homeSpreadOdds": home_sp_odds,
        }
        ledger = grade_pick(
            pick, away_score if pick == away else home_score if pick == home else None,
            home_score if pick == away else away_score if pick == home else None,
            away_ml if pick == away else home_ml, away_spread if pick == away else home_spread,
            away_sp_odds if pick == away else home_sp_odds,
        )
        g.update(ledger)
        alt = grade_pick(
            alt_pick, away_score if alt_pick == away else home_score if alt_pick == home else None,
            home_score if alt_pick == away else away_score if alt_pick == home else None,
            away_ml if alt_pick == away else home_ml, away_spread if alt_pick == away else home_spread,
            away_sp_odds if alt_pick == away else home_sp_odds,
        )
        g["altCorrect"], g["altReturn"] = alt["correct"], alt["pickReturn"]
        g["altCover"], g["altSpreadReturn"] = alt["pickCover"], alt["pickSpreadReturn"]
        rows.append(g)
    return rows


def grade_named(g, team):
    if team == g["away"]:
        return grade_pick(team, g["awayScore"], g["homeScore"], g["awayMoneyline"], g["awaySpread"], g["awaySpreadOdds"])
    if team == g["home"]:
        return grade_pick(team, g["homeScore"], g["awayScore"], g["homeMoneyline"], g["homeSpread"], g["homeSpreadOdds"])
    return {"correct": None, "pickReturn": None, "pickCover": None, "pickSpreadReturn": None}


def add_signal(games, favors_by_index, favors_field, correct_field, return_field, cover_field, spread_field):
    """Stamps a "3rd/4th model" signal (trend check, blowout check, ...) onto
    a subset of games by index, graded the same way score_slate.py grades
    any named pick — always sets the field (to None where no signal fired)
    so the report can tell "tracked, didn't fire" from "not tracked"."""
    for g in games:
        g[favors_field] = None
        g[correct_field] = None
        g[return_field] = None
        g[cover_field] = None
        g[spread_field] = None
    for idx, team in favors_by_index.items():
        g = games[idx]
        g[favors_field] = team
        graded = grade_named(g, team)
        g[correct_field] = graded["correct"]
        g[return_field] = graded["pickReturn"]
        g[cover_field] = graded["pickCover"]
        g[spread_field] = graded["pickSpreadReturn"]


def build_epl(games):
    rows = []
    for date, away, home, away_score, home_score, pick, alt_pick, away_ml, draw_ml, home_ml in games:
        g = {
            "date": date, "away": away, "home": home,
            "awayScore": away_score, "homeScore": home_score,
            "pick": pick, "confidence": "lean" if pick else "pass",
            "altPick": alt_pick, "altConfidence": "lean" if alt_pick else "pass",
            "awayMoneyline": away_ml, "drawMoneyline": draw_ml, "homeMoneyline": home_ml,
        }
        g.update(soccer_grade_game(g, away_score, home_score))
        rows.append(g)
    return rows


def main():
    nfl_games = build_two_way(NFL_GAMES)
    add_signal(nfl_games, {0: "Baltimore Ravens", 2: "Buffalo Bills", 7: "Los Angeles Rams", 10: "Cleveland Browns"},
               "altTrendFavors", "altTrendCorrect", "altTrendReturn", "altTrendCover", "altTrendSpreadReturn")
    add_signal(nfl_games, {4: "Tennessee Titans", 9: "New Orleans Saints"},
               "altBlowoutFavors", "altBlowoutCorrect", "altBlowoutReturn", "altBlowoutCover", "altBlowoutSpreadReturn")

    cfb_games = build_two_way(CFB_GAMES)
    add_signal(cfb_games, {0: "Alabama Crimson Tide", 3: "Georgia Bulldogs", 5: "Iowa Hawkeyes"},
               "altTrendFavors", "altTrendCorrect", "altTrendReturn", "altTrendCover", "altTrendSpreadReturn")
    add_signal(cfb_games, {2: "Northwestern Wildcats", 4: "Florida Gators"},
               "altBlowoutFavors", "altBlowoutCorrect", "altBlowoutReturn", "altBlowoutCover", "altBlowoutSpreadReturn")

    nba_games = build_two_way(NBA_GAMES)
    add_signal(nba_games, {1: "Oklahoma City Thunder", 3: "Miami Heat", 4: "Golden State Warriors"},
               "altRestBlowoutFavors", "altRestBlowoutCorrect", "altRestBlowoutReturn",
               "altRestBlowoutCover", "altRestBlowoutSpreadReturn")

    data = {
        "generatedAt": "DEMO",
        "leagues": {
            "nfl": report_lib.html_payload("NFL", "two_way", nfl_games),
            "cfb": report_lib.html_payload("College Football", "two_way", cfb_games),
            "mlb": report_lib.html_payload("MLB", "two_way", build_two_way(MLB_GAMES)),
            "nba": report_lib.html_payload("NBA", "two_way", nba_games),
            "epl": report_lib.html_payload("Premier League", "three_way", build_epl(EPL_GAMES)),
        },
    }
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    print(f"Wrote {OUT_PATH}")
    for key, payload in data["leagues"].items():
        print(f"  {key}: ledger {payload['ledger']['straightUp']} ML ${payload['ledger']['moneylineProfit']} | "
              f"alt {payload['secondOpinion']['straightUp']} ML ${payload['secondOpinion']['moneylineProfit']}")


if __name__ == "__main__":
    main()
