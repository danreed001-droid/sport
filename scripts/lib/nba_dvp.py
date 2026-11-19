"""NBA defense vs position: what each team allows a game to opposing point
guards, shooting guards, small forwards, power forwards and centers (points,
rebounds, assists, 3-pointers made), and how tonight's players line up with it.

Box scores come from data/raw/nba_player_box.json (archive_nba_player_box.py).
ESPN only lists G/F/C, so positions are derived from the season so far:
  C  = ESPN center
  PG = a guard averaging 5+ assists per 36 minutes, else SG (splits guard scoring
       about evenly: 27.6 vs 29.1 points a game to PGs and SGs on 2026-11-19)
  PF = a forward 6'9" or taller (data/raw/nba_heights.json), else SF; with no
       height, 8+ rebounds per 36 minutes makes a PF
Everything counts only games before the slate's date, so a past slate shows
what was known going in.
"""
import json
import os
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BOX = os.path.join(ROOT, "data", "raw", "nba_player_box.json")
HEIGHTS = os.path.join(ROOT, "data", "raw", "nba_heights.json")
POS = ("PG", "SG", "SF", "PF", "C")
STATS = ("pts", "reb", "ast", "tpm")
_CACHE = {}


def _load():
    if "box" not in _CACHE:
        try:
            with open(BOX, encoding="utf-8") as f:
                box = json.load(f)
        except (OSError, ValueError):
            box = {}
        try:
            with open(HEIGHTS, encoding="utf-8") as f:
                heights = json.load(f)
        except (OSError, ValueError):
            heights = {}
        _CACHE["box"] = sorted((e["date"], eid, e) for eid, e in box.items() if e.get("players"))
        _CACHE["h"] = heights
    return _CACHE["box"], _CACHE["h"]


def derive_positions(games, heights):
    """{athlete id: PG|SG|SF|PF|C} from season totals over `games`."""
    tot = defaultdict(lambda: [0.0, 0.0, 0.0, ""])   # min, reb, ast, ESPN pos
    for _d, _eid, e in games:
        for rows in e["players"].values():
            for row in rows:
                pid, pos, mi, r, a = row[0], row[2], row[4], row[6], row[7]
                x = tot[pid]
                x[0] += mi
                x[1] += r
                x[2] += a
                x[3] = pos or x[3]
    out = {}
    for pid, (mi, r, a, pos) in tot.items():
        m = max(mi, 1.0)
        if pos == "C":
            out[pid] = "C"
        elif pos == "G":
            out[pid] = "PG" if a / m * 36 >= 5.0 else "SG"
        elif pos == "F":
            h = heights.get(pid)
            out[pid] = ("PF" if h >= 81 else "SF") if h else ("PF" if r / m * 36 >= 8 else "SF")
    return out


def _same(a, b):
    from score_slate import _same_team
    return a == b or _same_team(a, b)


def for_slate(slate_date, games_today):
    """{game id: {"away": side, "home": side}} for tonight's NBA games, where a
    side is {"allows": {pos: {stat: [per game, rank 1 = most allowed]}},
             "players": [[name, pos, games, min, pts, reb, ast, tpm, +/- a game], ...]}
    plus "league": {pos: {stat: per game}} under the key "_league"."""
    box, heights = _load()
    games = [g for g in box if g[0] < slate_date]
    if not games or not games_today:
        return {}
    pos_of = derive_positions(games, heights)
    allowed = defaultdict(lambda: defaultdict(list))      # defense team -> pos -> [per-game dict]
    players = defaultdict(lambda: defaultdict(lambda: [None, 0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0]))  # team -> pid -> [name, g, min, pts, reb, ast, tpm, +/- total, games with +/-]
    last_team = {}
    for _d, _eid, e in games:
        teams = list(e["players"])
        if len(teams) != 2:
            continue
        for i, team in enumerate(teams):
            opp = teams[1 - i]
            sums = {p: dict.fromkeys(STATS, 0.0) for p in POS}
            for row in e["players"][team]:
                pid, name, mi, p, r, a, t = row[0], row[1], row[4], row[5], row[6], row[7], row[8]
                pm = row[9] if len(row) > 9 else None
                P = pos_of.get(pid)
                if P:
                    s = sums[P]
                    s["pts"] += p
                    s["reb"] += r
                    s["ast"] += a
                    s["tpm"] += t
                x = players[team][pid]
                x[0] = name
                x[1] += 1
                x[2] += mi
                x[3] += p
                x[4] += r
                x[5] += a
                x[6] += t
                if pm is not None:
                    x[7] += pm
                    x[8] += 1
                last_team[pid] = team
            for P in POS:
                allowed[opp][P].append(sums[P])
    league = {P: {k: round(sum(g[k] for t in allowed for g in allowed[t][P]) / max(1, sum(len(allowed[t][P]) for t in allowed)), 1)
                  for k in STATS} for P in POS}
    avg = {t: {P: {k: sum(g[k] for g in allowed[t][P]) / len(allowed[t][P]) for k in STATS} for P in POS if allowed[t][P]}
           for t in allowed}
    ranks = {}
    for P in POS:
        for k in STATS:
            order = sorted((t for t in avg if P in avg[t]), key=lambda t: -avg[t][P][k])
            for i, t in enumerate(order):
                ranks[(t, P, k)] = i + 1
    nteams = len(avg)

    def side(name):
        team = next((t for t in avg if _same(t, name)), None)
        roster = next((t for t in players if _same(t, name)), None)
        out = {"allows": {}, "players": [], "teams": nteams}
        if team:
            out["allows"] = {P: {k: [round(avg[team][P][k], 1), ranks.get((team, P, k))] for k in STATS} for P in POS if P in avg[team]}
        if roster:
            rows = []
            for pid, (pname, g, mi, p, r, a, t, pm, pmg) in players[roster].items():
                if g < 3 or mi / g < 15 or last_team.get(pid) != roster or pid not in pos_of:
                    continue
                rows.append([pname, pos_of[pid], g, round(mi / g, 1), round(p / g, 1), round(r / g, 1), round(a / g, 1), round(t / g, 1),
                             round(pm / pmg, 1) if pmg else None])
            out["players"] = sorted(rows, key=lambda x: -x[3])[:9]
        return out

    res = {"_league": league}
    for gid, away, home in games_today:
        res[gid] = {"away": side(away), "home": side(home)}
    return res
