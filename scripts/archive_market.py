"""Save Action Network's NBA board (consensus line, opener, public betting
splits) for today and tomorrow (US Eastern) to data/raw/market/nba/<date>.json.

The Basketball Routine runs where Action Network can't be reached, but it can
read this repo through raw.githubusercontent.com, so this file is how the
Second Opinion's Market category gets the splits. Each game also carries
"rlmFavorite": the team rule 50's reverse-line-movement test backs (or null).
Rewritten every scoring run while a date's games haven't all finished; once
they have, the file is left as it was (the last pre-game snapshot)."""
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import action_network, store  # noqa: E402

OUT_DIR = os.path.join(store.REPO_ROOT, "data", "raw", "market", "nba")


def main():
    today = datetime.now(ZoneInfo("America/New_York")).date()
    os.makedirs(OUT_DIR, exist_ok=True)
    for d in (today, today + timedelta(days=1)):
        ds = d.isoformat()
        path = os.path.join(OUT_DIR, f"{ds}.json")
        games = action_network.board(ds)
        if not games:
            print(f"{ds}: Action Network returned no NBA games (feed unreachable, or none scheduled) -- left as is.")
            continue
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                old = json.load(f)
            if old.get("games") and all(g.get("state") == "complete" for g in old["games"]):
                print(f"{ds}: all games final -- kept the saved snapshot.")
                continue
            # A game that has started keeps its last pre-game snapshot.
            prev = {(g["away"], g["home"]): g for g in old.get("games", [])}
            games = [prev[(g["away"], g["home"])] if g.get("state") != "scheduled" and (g["away"], g["home"]) in prev else g
                     for g in games]
        for g in games:
            g["rlmFavorite"] = action_network.rlm_favorite(g)
        doc = {"date": ds, "source": "Action Network public feed (consensus = book 15, opener = book 30)",
               "fetchedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"), "games": games}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(doc, f, indent=1)
        flagged = [g["rlmFavorite"] for g in games if g.get("rlmFavorite")]
        print(f"{ds}: saved {len(games)} game(s); reverse line movement backs: {', '.join(flagged) or 'none'}.")


if __name__ == "__main__":
    main()
