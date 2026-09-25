#!/usr/bin/env python3
"""Fetch scores/status/moneylines from ESPN's public API for a given sport
and archive them in this repo (data/raw/master_<sport>_scores.csv,
data/raw/active_slate_<sport>.txt).

This is the direct replacement for the Google Drive feed: same idea (a
continuously-refreshed CSV of recent games), but written by this script
straight into the git repo instead of a Colab notebook writing to Drive.
"""
import csv
import os
import sys
import time
from datetime import timedelta

sys.path.insert(0, os.path.dirname(__file__))
from lib import espn, sports  # noqa: E402
from lib.dates import now_et  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(REPO_ROOT, "data", "raw")

FIELDNAMES = [
    "Game_ID", "Date", "Status", "Away_Team", "Away_Score", "Away_Diff",
    "Home_Team", "Home_Score", "Home_Diff", "Away_ML", "Home_ML",
]


def _csv_path(sport_key):
    return os.path.join(OUTPUT_DIR, f"master_{sport_key}_scores.csv")


def _slate_path(sport_key):
    return os.path.join(OUTPUT_DIR, f"active_slate_{sport_key}.txt")


def load_history(sport_key):
    history = {}
    path = _csv_path(sport_key)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row.get("Game_ID"):
                    history[row["Game_ID"]] = row
    return history


def _existing_ml(existing, key):
    val = existing.get(key)
    if val in (None, "", "-"):
        return None
    try:
        return int(float(val))
    except ValueError:
        return None


def main(sport_key):
    cfg = sports.get(sport_key)
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    session = espn.make_session()
    history = load_history(sport_key)
    print(f"[{cfg['label']}] loaded {len(history)} historical games from repo archive.")

    differentials = espn.fetch_standings(session, cfg["espn_sport"], cfg["espn_league"])

    now = now_et()
    dates_to_crawl = [(now - timedelta(days=1)).strftime("%Y%m%d"), now.strftime("%Y%m%d")]

    for date_str in dates_to_crawl:
        try:
            events = espn.fetch_scoreboard(session, cfg["espn_sport"], cfg["espn_league"], date_str)
        except Exception as exc:
            print(f"[{cfg['label']}] scoreboard fetch failed for {date_str}: {exc}")
            continue

        for ev in events:
            try:
                game_id = str(ev.get("id"))
                existing = history.get(game_id, {})
                game_date = ev.get("date", "")[:10]
                status_type = ev.get("status", {}).get("type", {})
                detail = status_type.get("shortDetail") or status_type.get("description", "Scheduled")
                is_completed = bool(status_type.get("completed"))

                comp = ev.get("competitions", [{}])[0]
                competitors = comp.get("competitors", [])

                away_ml, home_ml = espn.fetch_event_odds_from_scoreboard(comp)
                if away_ml is None:
                    away_ml = _existing_ml(existing, "Away_ML")
                if home_ml is None:
                    home_ml = _existing_ml(existing, "Home_ML")

                if (away_ml is None or home_ml is None) and (is_completed or "final" in str(detail).lower()):
                    s_aml, s_hml = espn.fetch_summary_odds(session, cfg["espn_sport"], cfg["espn_league"], game_id)
                    away_ml = away_ml if away_ml is not None else s_aml
                    home_ml = home_ml if home_ml is not None else s_hml
                    time.sleep(0.1)

                home_team = away_team = None
                home_score = away_score = None
                for c in competitors:
                    name = c.get("team", {}).get("displayName", "Unknown")
                    score = c.get("score")
                    if c.get("homeAway") == "home":
                        home_team, home_score = name, score
                    else:
                        away_team, away_score = name, score

                away_diff = espn.pd_per_game(differentials.get(away_team))
                home_diff = espn.pd_per_game(differentials.get(home_team))

                history[game_id] = {
                    "Game_ID": game_id,
                    "Date": game_date,
                    "Status": detail,
                    "Away_Team": away_team,
                    "Away_Score": away_score if away_score not in (None, "") else "-",
                    "Away_Diff": away_diff if away_diff is not None else existing.get("Away_Diff", "-"),
                    "Home_Team": home_team,
                    "Home_Score": home_score if home_score not in (None, "") else "-",
                    "Home_Diff": home_diff if home_diff is not None else existing.get("Home_Diff", "-"),
                    "Away_ML": away_ml if away_ml is not None else "-",
                    "Home_ML": home_ml if home_ml is not None else "-",
                }
            except Exception as exc:
                print(f"[{cfg['label']}] skipping event due to error: {exc}")
                continue

    all_records = list(history.values())
    all_records.sort(key=lambda x: x.get("Date", ""), reverse=True)

    with open(_csv_path(sport_key), "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(all_records)

    yesterday_str = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    today_str = now.strftime("%Y-%m-%d")
    recent = [r for r in all_records if r.get("Date") in (yesterday_str, today_str)]

    with open(_slate_path(sport_key), "w", encoding="utf-8") as f:
        f.write(f"{cfg['label']} Slate (Yesterday & Today) as of {now.strftime('%Y-%m-%d %H:%M:%S %Z')}\n")
        current_date = ""
        for g in recent:
            if g["Date"] != current_date:
                current_date = g["Date"]
                f.write(f"\n==== DATE: {current_date} ====\n")
            f.write(f"{g['Away_Team']} (Diff: {g['Away_Diff']}) at {g['Home_Team']} (Diff: {g['Home_Diff']}) | {g['Status']}\n")
            f.write(f"Score: {g['Away_Team']} {g['Away_Score']} - {g['Home_Team']} {g['Home_Score']}\n")
            f.write(f"ML: Away {g['Away_ML']} / Home {g['Home_ML']}\n")
            f.write("-" * 35 + "\n")

    print(f"[{cfg['label']}] archive updated: {len(all_records)} total games tracked.")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "nfl")
