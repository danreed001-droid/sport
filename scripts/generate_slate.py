#!/usr/bin/env python3
"""STEP 2: build today's Diamond Ledger slate for a given sport.

No Claude API calls here — the research step is done by a live Claude Code
session doing its own WebSearch, not a billed API request. This script has
two modes that bracket that step:

  prep   fetches today's ESPN matchups + known stats and writes them, plus
         the sport's research prompt/schema, to a JSON file. A Claude Code
         session reads that file, does the actual research, and writes a
         second JSON file matching the schema.

  apply  reads the prep file (for the matchups) and the research file (for
         what was found), applies the sport's deterministic tiering/screening
         logic, and writes the final data/<sport>/<date>.json doc.

Usage:
  python scripts/generate_slate.py <sport> prep <prep_out.json>
  python scripts/generate_slate.py <sport> apply <prep_out.json> <research.json>
"""
import importlib
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))
from lib import espn, sports, store  # noqa: E402
from lib.dates import today_et_str, weekday_et  # noqa: E402


def load_model(cfg):
    return importlib.import_module(f"lib.{cfg['model']}")


def cmd_prep(sport_key, out_path):
    cfg = sports.get(sport_key)
    date_str = today_et_str()
    if store.read_doc(cfg["collection"], date_str) is not None:
        print(f"[{cfg['label']}] doc already exists for {date_str}; nothing to generate.")
        return False

    model = load_model(cfg)
    session = espn.make_session()
    espn_games = model.fetch_games(session, cfg)
    if not espn_games:
        print(f"[{cfg['label']}] no games found today ({date_str}); writing nothing.")
        return False

    system_prompt = model.build_system_prompt(cfg)
    user_prompt = model.build_user_prompt(date_str, weekday_et(date_str), espn_games, cfg)

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "sport": sport_key, "date": date_str,
            "espnGames": espn_games,
            "systemPrompt": system_prompt,
            "userPrompt": user_prompt,
        }, f, indent=2)

    print(f"[{cfg['label']}] {len(espn_games)} game(s) today. Prep written to {out_path}.")
    print("Now research each game per userPrompt's schema, and write the result as its own JSON file.")
    print(f"Then run: python scripts/generate_slate.py {sport_key} apply {out_path} <research.json>")
    return True


def cmd_apply(sport_key, prep_path, research_path):
    cfg = sports.get(sport_key)
    model = load_model(cfg)

    with open(prep_path, "r", encoding="utf-8") as f:
        prep = json.load(f)
    with open(research_path, "r", encoding="utf-8") as f:
        research = json.load(f)

    date_str = prep["date"]
    if store.read_doc(cfg["collection"], date_str) is not None:
        print(f"[{cfg['label']}] doc already exists for {date_str}; refusing to overwrite.")
        return

    games = model.assemble(prep["espnGames"], research, cfg)

    doc = {
        "date": date_str,
        "weekday": weekday_et(date_str),
        "sport": sport_key,
        "scored": False,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "games": games,
    }
    store.write_doc(cfg["collection"], date_str, doc)
    print(f"[{cfg['label']}] wrote data/{cfg['collection']}/{date_str}.json with {len(games)} game(s).")


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    sport_key, mode = sys.argv[1], sys.argv[2]
    if mode == "prep":
        cmd_prep(sport_key, sys.argv[3])
    elif mode == "apply":
        cmd_apply(sport_key, sys.argv[3], sys.argv[4])
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
