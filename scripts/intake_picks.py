#!/usr/bin/env python3
"""Reads a "picks YYYY-MM-DD" GitHub issue (opened from the Pages pick sheet)
and merges its picks into data/mypicks/<date>.json. Run by
.github/workflows/pick-intake.yml; everything about each game (teams, lines)
is taken from data/<sport>/<date>.json, never from the issue text.

Writes a markdown summary to --summary and changed=true|false to $GITHUB_OUTPUT.
"""
import json
import os
import re
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))
from lib import sports, store  # noqa: E402
from lib.picks import game_id, is_final, line_for, team_for  # noqa: E402

BLOCK = re.compile(r"```json\s*(\{.*?\})\s*```", re.S)
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# One letter per Second Opinion reason: A away, a half away, N neutral, h half home, H home.
SCORE = re.compile(r"^[AaNhH]*$")
POINTS = {"A": (1, 0), "a": (0.5, 0), "N": (0, 0), "h": (0, 0.5), "H": (0, 1)}


def tally_text(g, code):
    away = sum(POINTS[c][0] for c in code)
    home = sum(POINTS[c][1] for c in code)
    fmt = lambda v: f"{v:g}"
    return f"{g['away']} {fmt(away)} – {fmt(home)} {g['home']}"


def games_for(date_str):
    found = {}
    for sport, cfg in sports.SPORTS.items():
        doc = store.read_doc(cfg["collection"], date_str)
        if not doc:
            continue
        for g in doc.get("games", []):
            found[game_id(sport, date_str, g)] = (sport, doc, g)
    return found


def process(issue):
    m = BLOCK.search(issue.get("body") or "")
    if not m:
        return False, "No picks block found in this issue. Submit picks from the pick sheet's **Submit** button."
    try:
        payload = json.loads(m.group(1))
    except json.JSONDecodeError as e:
        return False, f"Couldn't read the picks block ({e}). Submit again from the pick sheet."

    date_str = payload.get("date")
    picks = payload.get("picks") or {}
    scores = payload.get("scores") or {}
    if not isinstance(date_str, str) or not DATE.match(date_str) or not isinstance(picks, dict) or not isinstance(scores, dict):
        return False, "The picks block is missing a valid date or picks list."

    games = games_for(date_str)
    if not games:
        return False, f"There's no slate in the repo for {date_str}."

    path = os.path.join(store.REPO_ROOT, "data", "mypicks", f"{date_str}.json")
    current = {"date": date_str, "picks": {}, "scores": {}}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            current = json.load(f)
    current.setdefault("picks", {})
    current.setdefault("scores", {})

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    saved, cleared, rejected, scored = [], [], [], []

    for gid, code in scores.items():
        if gid not in games:
            rejected.append(f"`{gid}` — not on the {date_str} slate")
            continue
        sport, doc, g = games[gid]
        label = f"{g['away']} @ {g['home']}"
        n = len(g.get("altReasons") or [])
        if not isinstance(code, str) or not SCORE.match(code) or len(code) != n:
            rejected.append(f"{label} — reason scores don't match its {n} Second Opinion reasons")
            continue
        if is_final(doc, g):
            rejected.append(f"{label} — already final, reason scores are locked")
            continue
        current["scores"][gid] = code
        scored.append(f"{label}: {tally_text(g, code)}")

    for gid, side in picks.items():
        if gid not in games:
            rejected.append(f"`{gid}` — not on the {date_str} slate")
            continue
        sport, doc, g = games[gid]
        label = f"{g['away']} @ {g['home']}"
        allowed = ("away", "home", "none", "draw") if g.get("drawMoneyline") is not None else ("away", "home", "none")
        if side not in allowed:
            rejected.append(f"{label} — unknown side `{side}`")
            continue
        if is_final(doc, g):
            rejected.append(f"{label} — already final, picks are locked")
            continue
        if side == "none":
            if current["picks"].pop(gid, None):
                cleared.append(label)
            continue
        ln = line_for(g, side)
        current["picks"][gid] = {
            "sport": sport, "away": g["away"], "home": g["home"], "time": g.get("time"),
            "side": side, "team": team_for(g, side), "spread": ln["spread"], "spreadOdds": ln["spreadOdds"],
            "moneyline": ln["moneyline"], "submittedAt": now, "issue": issue.get("number"),
        }
        spread = ln["spread"]
        saved.append(f"{team_for(g, side)} {'' if spread is None else ('+' if spread > 0 else '') + str(spread)} ({label})".replace("  ", " "))

    changed = bool(saved or cleared or scored)
    if changed:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        current["picks"] = dict(sorted(current["picks"].items()))
        current["scores"] = dict(sorted(current["scores"].items()))
        with open(path, "w", encoding="utf-8") as f:
            json.dump(current, f, indent=2, ensure_ascii=False)
            f.write("\n")

    lines = [f"**Picks for {date_str}**", ""]
    if saved:
        lines += ["Saved:"] + [f"- {s}" for s in saved] + [""]
    if cleared:
        lines += ["Cleared:"] + [f"- {s}" for s in cleared] + [""]
    if scored:
        lines += ["Reason scores (your tally):"] + [f"- {s}" for s in scored] + [""]
    if rejected:
        lines += ["Not saved:"] + [f"- {s}" for s in rejected] + [""]
    if changed:
        lines.append(f"Committed to `data/mypicks/{date_str}.json`. The pick sheet updates in a minute or two.")
    elif not rejected:
        lines.append("Nothing changed.")
    return changed, "\n".join(lines)


def main():
    summary_path = sys.argv[sys.argv.index("--summary") + 1] if "--summary" in sys.argv else None
    with open(os.environ["GITHUB_EVENT_PATH"], encoding="utf-8") as f:
        issue = json.load(f)["issue"]
    changed, summary = process(issue)
    print(summary)
    if summary_path:
        with open(summary_path, "w", encoding="utf-8") as f:
            f.write(summary + "\n")
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as f:
            f.write(f"changed={'true' if changed else 'false'}\n")


if __name__ == "__main__":
    main()
