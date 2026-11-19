"""NFL defense vs position: what each team allows a game to opposing
quarterbacks, running backs, wide receivers and tight ends, and how tonight's
players line up with it. Box scores from data/raw/nfl_player_box.json
(archive_nfl_player_box.py); positions from ESPN rosters (FB counts as RB).
Only games before the slate's date count.

Row layout in the box file: [id, name, pos, cmp, att, pass yds, pass td, int,
rush att, rush yds, rush td, rec, rec yds, rec td, targets].
"""
import json
import os
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BOX = os.path.join(ROOT, "data", "raw", "nfl_player_box.json")
POS = ("QB", "RB", "WR", "TE")
# per position: (key, label, value from a box row)
STATS = {
    "QB": [("pyd", "Pass yds", lambda r: r[5]), ("ptd", "Pass TD", lambda r: r[6]), ("int", "INT", lambda r: r[7]), ("ryd", "Rush yds", lambda r: r[9])],
    "RB": [("ryd", "Rush yds", lambda r: r[9]), ("rec", "Rec", lambda r: r[11]), ("cyd", "Rec yds", lambda r: r[12]), ("td", "TD", lambda r: r[10] + r[13])],
    "WR": [("rec", "Rec", lambda r: r[11]), ("cyd", "Rec yds", lambda r: r[12]), ("td", "TD", lambda r: r[13]), ("tgt", "Targets", lambda r: r[14])],
}
STATS["TE"] = STATS["WR"]
SPEC = {P: [[k, lab] for k, lab, _f in STATS[P]] for P in POS}
_CACHE = {}


def _pos(p):
    return "RB" if p == "FB" else p if p in POS else None


def _load():
    if "box" not in _CACHE:
        try:
            with open(BOX, encoding="utf-8") as f:
                box = json.load(f)
        except (OSError, ValueError):
            box = {}
        _CACHE["box"] = sorted((e["date"], eid, e) for eid, e in box.items() if e.get("players"))
    return _CACHE["box"]


def _same(a, b):
    from score_slate import _same_team
    return a == b or _same_team(a, b)


def _usage(P, r):
    return r[4] if P == "QB" else (r[8] + r[11]) if P == "RB" else r[14]


def for_slate(slate_date, games_today):
    """{"_league": {pos: {stat: per game}}, "_spec": SPEC,
        game id: {"away": side, "home": side}}; a side is
       {"allows": {pos: {stat: [per game, rank 1 = most allowed]}}, "teams": n,
        "players": [[name, pos, games, {stat: per game}], ...]}."""
    games = [g for g in _load() if g[0] < slate_date]
    if not games or not games_today:
        return {}
    allowed = defaultdict(lambda: defaultdict(list))
    players = defaultdict(dict)   # team -> pid -> [name, pos, g, usage, {stat: total}]
    last_team = {}
    for _d, _eid, e in games:
        teams = list(e["players"])
        if len(teams) != 2:
            continue
        for i, team in enumerate(teams):
            opp = teams[1 - i]
            sums = {P: {k: 0.0 for k, _l, _f in STATS[P]} for P in POS}
            for r in e["players"][team]:
                P = _pos(r[2])
                if not P:
                    continue
                for k, _l, f in STATS[P]:
                    sums[P][k] += f(r)
                x = players[team].setdefault(r[0], [r[1], P, 0, 0.0, {k: 0.0 for k, _l, _f in STATS[P]}])
                x[2] += 1
                x[3] += _usage(P, r)
                for k, _l, f in STATS[P]:
                    x[4][k] = x[4].get(k, 0.0) + f(r)
                last_team[r[0]] = team
            for P in POS:
                allowed[opp][P].append(sums[P])
    league = {P: {k: round(sum(g[k] for t in allowed for g in allowed[t][P]) / max(1, sum(len(allowed[t][P]) for t in allowed)), 1)
                  for k, _l, _f in STATS[P]} for P in POS}
    avg = {t: {P: {k: sum(g[k] for g in allowed[t][P]) / len(allowed[t][P]) for k, _l, _f in STATS[P]} for P in POS if allowed[t][P]}
           for t in allowed}
    ranks = {}
    for P in POS:
        for k, _l, _f in STATS[P]:
            for i, t in enumerate(sorted((t for t in avg if P in avg[t]), key=lambda t: -avg[t][P][k])):
                ranks[(t, P, k)] = i + 1
    cap = {"QB": 1, "RB": 2, "WR": 3, "TE": 1}

    def side(name):
        team = next((t for t in avg if _same(t, name)), None)
        roster = next((t for t in players if _same(t, name)), None)
        out = {"allows": {}, "players": [], "teams": len(avg)}
        if team:
            out["allows"] = {P: {k: [round(v, 1), ranks.get((team, P, k))] for k, v in avg[team][P].items()} for P in POS if P in avg[team]}
        if roster:
            rows = []
            for P in POS:
                cand = [(pid, x) for pid, x in players[roster].items() if x[1] == P and last_team.get(pid) == roster and x[2] >= 2]
                cand.sort(key=lambda px: -px[1][3] / px[1][2])
                for pid, (pname, _P, g, use, tot) in cand[:cap[P]]:
                    if use / g < (10 if P == "QB" else 3):
                        continue
                    rows.append([pname, P, g, {k: round(v / g, 1) for k, v in tot.items()}])
            out["players"] = rows
        return out

    res = {"_league": league, "_spec": SPEC}
    for gid, away, home in games_today:
        res[gid] = {"away": side(away), "home": side(home)}
    return res
