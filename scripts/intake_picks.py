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
from lib.altlines import MAX_STEP, alt_price  # noqa: E402
from lib.picks import game_id, game_total_line, is_final, line_for, team_for  # noqa: E402

BLOCK = re.compile(r"```json\s*(\{.*?\})\s*```", re.S)
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# One letter per Second Opinion reason: A away, a half away, N neutral, h half home, H home.
SCORE = re.compile(r"^[AaNhH]*$")
POINTS = {"A": (1, 0), "a": (0.5, 0), "N": (0, 0), "h": (0, 0.5), "H": (0, 1)}


from lib import props as props_lib  # noqa: E402

PROP_STATS = {sp: {k: short for k, _label, short, _keys in v} for sp, v in props_lib.STATS.items()}


def _saved_rosters(sport, date_str):
    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "raw", "rosters", f"{sport}.json"),
                  encoding="utf-8") as f:
            return json.load(f).get(date_str) or {}
    except (OSError, ValueError):
        return {}


def prop_event_and_player(sport, date_str, g, pid, name, team):
    """(ESPN event id, athlete id, canonical name) for a prop; athlete id is
    looked up on the team's roster by name when the sheet didn't send one.
    (None, ...) when the game can't be found."""
    from lib import espn
    saved = _saved_rosters(sport, date_str)
    eid = (saved.get("events") or {}).get(f"{g['away']}@{g['home']}")
    session = espn.make_session()
    ids = {}
    if not eid or not pid:
        try:
            eid2, ids, _ = props_lib.event_for(session, sport, date_str, g["away"], g["home"])
            eid = eid or eid2
        except Exception:  # noqa: BLE001
            pass
    if not eid:
        return None, pid, name
    if pid:
        return eid, pid, name
    rows = (saved.get("teams") or {}).get(team) or []
    if not rows and ids:
        side = "away" if team == g["away"] else "home"
        try:
            rows = props_lib.team_roster(session, sport, ids.get(side), props_lib.league_slug(session, sport, eid))
        except Exception:  # noqa: BLE001
            rows = []
    want = props_lib.norm(name)
    hit = [r for r in rows if props_lib.norm(r[1]) == want] or [r for r in rows if want and want in props_lib.norm(r[1])]
    if len(hit) == 1:
        return eid, hit[0][0], hit[0][1]
    return eid, "", name   # graded by name from the box score


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
    totals = payload.get("totals") or {}
    alts = payload.get("alts") or {}            # game id -> your alternate spread
    total_alts = payload.get("totalAlts") or {}  # game id -> your alternate total
    if not isinstance(alts, dict): alts = {}
    if not isinstance(total_alts, dict): total_alts = {}
    if (not isinstance(date_str, str) or not DATE.match(date_str) or not isinstance(picks, dict) or not isinstance(scores, dict)
            or not isinstance(totals, dict)):
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
    current.setdefault("totals", {})

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
        entry = {
            "sport": sport, "away": g["away"], "home": g["home"], "time": g.get("time"),
            "side": side, "team": team_for(g, side), "spread": ln["spread"], "spreadOdds": ln["spreadOdds"],
            "moneyline": ln["moneyline"], "submittedAt": now, "issue": issue.get("number"),
        }
        alt = alts.get(gid)
        if alt is not None and side in ("away", "home"):
            ok = isinstance(alt, (int, float)) and ln["spread"] is not None and float(alt * 2).is_integer() \
                and abs(alt - ln["spread"]) <= MAX_STEP
            price = alt_price(sport, "spread", ln["spread"], ln["spreadOdds"], alt) if ok else None
            if price is None:
                rejected.append(f"{label} — alternate line {alt} isn't available (saved at the posted line)")
            elif alt != ln["spread"]:
                entry.update({"spread": alt, "spreadOdds": price, "alt": True,
                              "posted": {"spread": ln["spread"], "spreadOdds": ln["spreadOdds"]}})
        current["picks"][gid] = entry
        spread = entry["spread"]
        alt_note = f" (alternate line, est. {entry['spreadOdds']:+g})" if entry.get("alt") else ""
        saved.append(f"{team_for(g, side)} {'' if spread is None else ('+' if spread > 0 else '') + f'{spread:g}'}{alt_note} ({label})".replace("  ", " "))

    # Over/under picks: locked at the slate's line (and its odds) when submitted.
    for gid, ou in totals.items():
        if gid not in games:
            rejected.append(f"`{gid}` — not on the {date_str} slate")
            continue
        sport, doc, g = games[gid]
        label = f"{g['away']} @ {g['home']}"
        if ou not in ("over", "under", "none"):
            rejected.append(f"{label} — unknown total pick `{ou}`")
            continue
        if is_final(doc, g):
            rejected.append(f"{label} — already final, picks are locked")
            continue
        if ou == "none":
            if current["totals"].pop(gid, None):
                cleared.append(f"{label} total")
            continue
        line, over_odds, under_odds = game_total_line(g)
        if line is None:
            rejected.append(f"{label} — no over/under line on the slate yet")
            continue
        odds = over_odds if ou == "over" else under_odds
        tentry = {"sport": sport, "away": g["away"], "home": g["home"], "time": g.get("time"),
                  "side": ou, "line": line, "odds": odds, "submittedAt": now, "issue": issue.get("number")}
        talt = total_alts.get(gid)
        if talt is not None:
            ok = isinstance(talt, (int, float)) and float(talt * 2).is_integer() and abs(talt - line) <= MAX_STEP
            price = alt_price(sport, ou, line, odds, talt) if ok else None
            if price is None:
                rejected.append(f"{label} — alternate total {talt} isn't available (saved at the posted total)")
            elif talt != line:
                tentry.update({"line": talt, "odds": price, "alt": True, "posted": {"line": line, "odds": odds}})
        current["totals"][gid] = tentry
        line, odds = tentry["line"], tentry["odds"]
        saved.append(f"{ou.title()} {line:g}{'' if odds is None else f' ({odds:+g})'} ({label})")

    # Player props (NBA): {pending key: {gameId, playerId, player, team, stat, side, line, odds, reason} or "none"}
    current.setdefault("props", {})
    for pkey, pe in (payload.get("props") or {}).items():
        gid = (pe or {}).get("gameId") if isinstance(pe, dict) else str(pkey).split("|")[0]
        if gid not in games:
            rejected.append(f"prop {pkey} — game isn't on the {date_str} slate")
            continue
        sport, doc, g = games[gid]
        label = f"{g['away']} @ {g['home']}"
        parts = str(pkey).split("|")
        if pe == "none" or (isinstance(pe, dict) and pe.get("remove")):
            pid, stat = (parts + ["", "", ""])[1:3]
            hit = [k for k, v in current["props"].items() if v.get("gameId") == gid and v.get("stat") == stat
                   and (str(v.get("playerId")) == pid or "n:" + props_lib.norm(v.get("player")) == pid)]
            if hit and is_final(doc, g):
                rejected.append(f"{label} — prop already final, can't remove")
                continue
            for k in hit:
                cleared.append(f"{current['props'][k].get('player')} {current['props'][k].get('stat')} ({label})")
                current["props"].pop(k)
            continue
        if not isinstance(pe, dict) or sport not in PROP_STATS:
            rejected.append(f"{label} — no player props for this sport yet")
            continue
        if is_final(doc, g):
            rejected.append(f"{label} — already final, props are locked")
            continue
        stat, side, line, odds = pe.get("stat"), pe.get("side"), pe.get("line"), pe.get("odds")
        pid, player = str(pe.get("playerId") or ""), str(pe.get("player") or "").strip()[:60]
        if stat not in PROP_STATS[sport] or side not in ("over", "under") or not isinstance(line, (int, float)) \
                or not float(line * 2).is_integer() or not 0 < line < 1000 or (pid and not pid.isdigit()) or not player:
            rejected.append(f"{label} — prop {player or pkey} isn't complete (player, stat, over/under, a line in half points)")
            continue
        if not (isinstance(odds, (int, float)) and (odds <= -100 or odds >= 100) and abs(odds) <= 5000):
            odds = None
        team = str(pe.get("team") or "")[:60]
        eid, pid, player = prop_event_and_player(sport, date_str, g, pid, player, team)
        if eid is None:
            rejected.append(f"{label} — couldn't find the game on ESPN to grade the prop; try again")
            continue
        key = f"{sport}-espn-{eid}|{pid or 'n:' + props_lib.norm(player)}|{stat}"
        current["props"][key] = {"sport": sport, "eventId": eid, "gameId": gid, "away": g["away"], "home": g["home"],
                                 "time": g.get("time"), "player": player, "playerId": pid,
                                 "team": team, "stat": stat, "line": line, "side": side,
                                 "odds": odds, "reason": str(pe.get("reason") or "").strip()[:600] or None,
                                 "submittedAt": now, "issue": issue.get("number")}
        saved.append(f"{player} {side.title()} {line:g} {PROP_STATS[sport][stat]}{'' if pid else ' (matched by name at grading)'}{'' if odds is None else f' ({odds:+g})'} ({label})")

    changed = bool(saved or cleared or scored)
    if changed:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        current["picks"] = dict(sorted(current["picks"].items()))
        current["scores"] = dict(sorted(current["scores"].items()))
        current["totals"] = dict(sorted(current["totals"].items()))
        current["props"] = dict(sorted(current["props"].items()))
        if not current["props"]:
            current.pop("props")
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
