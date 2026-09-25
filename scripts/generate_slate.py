#!/usr/bin/env python3
"""STEP 2: build today's Diamond Ledger slate for a given sport.

Dispatches to that sport's model module (lib/nfl_model.py, lib/mlb_model.py,
lib/nba_model.py, lib/soccer_model.py) for the actual research prompt and
tiering/scoring logic — this file just wires ESPN + Claude + the doc store
together per lib/sports.py's per-sport configuration.
"""
import importlib
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))
from lib import espn, sports, store  # noqa: E402
from lib.claude_research import research_slate  # noqa: E402
from lib.dates import today_et_str, weekday_et  # noqa: E402


def load_model(cfg):
    return importlib.import_module(f"lib.{cfg['model']}")


def main(sport_key):
    cfg = sports.get(sport_key)
    date_str = today_et_str()
    if store.read_doc(cfg["collection"], date_str) is not None:
        print(f"[{cfg['label']}] doc already exists for {date_str}; nothing to generate.")
        return

    model = load_model(cfg)
    session = espn.make_session()

    def research_fn(system_prompt, user_prompt):
        return research_slate(system_prompt, user_prompt)

    games = model.build_slate(session, cfg, research_fn)
    if games is None:
        print(f"[{cfg['label']}] no games found today ({date_str}); writing nothing.")
        return

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


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "nfl")
