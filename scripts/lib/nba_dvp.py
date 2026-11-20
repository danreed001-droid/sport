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
# College basketball uses the same rows (archive_college_player_box.py): only
# games of teams on our NCAAB slates are saved, so a defense needs 3+ saved
# games to be ranked, and forwards split by rebounds (no heights saved).
BOXES = {"nba": BOX, "ncaab": os.path.join(ROOT, "data", "raw", "ncaab_player_box.json")}
MIN_TEAM_GAMES = 3
# Players ESPN's injury report lists (the game's `injuries`, from starter_out.py):
# these statuses are out -- dropped from the offense's position mix in the
# matchup score -- the rest (questionable, doubtful, day-to-day) are only marked.
OUTISH = {"out", "injured reserve", "suspension", "suspended"}
HEIGHTS = os.path.join(ROOT, "data", "raw", "nba_heights.json")
POS = ("PG", "SG", "SF", "PF", "C")
STATS = ("pts", "reb", "ast", "tpm")
# Matchup score (the user's ask, 2026-11-19): how soft tonight's defense is to
# the positions this offense scores through. Per position, the defense's
# allowed numbers vs the league, weighted pts .5 / reb .2 / ast .2 / 3PM .1;
# then each position weighted by its share of this offense's points.
# +5 = the defense gives this offense's mix 5% more than an average defense.
# 2025-26 replay (979 games, 10+ games in, before-the-game data): points vs the
# team's own last-10 average = about 0.77 x score (+8 or more: +8.2, beat its
# average 71%; +4 to +8: +5.9, 67%; -8 to -4: -4.9, 37%); against the spread
# the gap between the two offenses' scores did nothing (50.6%), and for totals
# both scores high went over 53% (104-92), both low under 57% (111-85, p=0.07).
SCORE_W = {"pts": .5, "reb": .2, "ast": .2, "tpm": .1}
MIN_GAMES = 5
_CACHE = {}


def _load(sport="nba"):
    path = BOX if sport == "nba" else BOXES[sport]
    if ("box", path) not in _CACHE:
        try:
            with open(path, encoding="utf-8") as f:
                box = json.load(f)
        except (OSError, ValueError):
            box = {}
        heights = {}
        if sport == "nba":
            try:
                with open(HEIGHTS, encoding="utf-8") as f:
                    heights = json.load(f)
            except (OSError, ValueError):
                pass
        _CACHE[("box", path)] = (sorted((e["date"], eid, e) for eid, e in box.items() if e.get("players")), heights)
    return _CACHE[("box", path)]


def derive_positions(games, heights, college=False):
    """{athlete id: PG|SG|SF|PF|C} from season totals over `games`. College
    guards pass less, so there each team's top guard by assists per 36 (10+
    min a game) is a PG too, besides any guard at 4+ per 36."""
    tot = defaultdict(lambda: [0.0, 0.0, 0.0, ""])   # min, reb, ast, ESPN pos
    team_of, gp = {}, defaultdict(int)
    for _d, _eid, e in games:
        for team, rows in e["players"].items():
            for row in rows:
                team_of[row[0]] = team
                gp[row[0]] += 1
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
            out[pid] = "PG" if a / m * 36 >= (4.0 if college else 5.0) else "SG"
        elif pos == "F":
            h = heights.get(pid)
            out[pid] = ("PF" if h >= 81 else "SF") if h else ("PF" if r / m * 36 >= 8 else "SF")
    if college:
        best = {}
        for pid, (mi, r, a, pos) in tot.items():
            if pos == "G" and gp[pid] and mi / gp[pid] >= 10:
                t = team_of.get(pid)
                v = a / max(mi, 1.0)
                if t and v > best.get(t, (-1, None))[0]:
                    best[t] = (v, pid)
        for _v, pid in best.values():
            out[pid] = "PG"
    return out


def _same(a, b):
    from score_slate import _same_team
    return a == b or _same_team(a, b)


def for_slate(slate_date, games_today, sport="nba", injuries=None):
    """{game id: {"away": side, "home": side}} for tonight's NBA games, where a
    side is {"allows": {pos: {stat: [per game, rank 1 = most allowed]}},
             "players": [[name, pos, games, min, pts, reb, ast, tpm, +/- a game], ...]}
    plus "league": {pos: {stat: per game}} under the key "_league"."""
    box, heights = _load(sport)
    games = [g for g in box if g[0] < slate_date]
    if not games or not games_today:
        return {}
    pos_of = derive_positions(games, heights, college=sport != "nba")
    allowed = defaultdict(lambda: defaultdict(list))      # defense team -> pos -> [per-game dict]
    made = defaultdict(lambda: defaultdict(list))         # offense team -> pos -> [per-game dict]
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
                made[team][P].append(sums[P])
    # the league average is over the defenses that are ranked (3+ games): for
    # college, that's the teams on our slates, not their opponents
    ranked = [t for t in allowed if len(allowed[t]["PG"]) >= MIN_TEAM_GAMES]
    league = {P: {k: round(sum(g[k] for t in ranked for g in allowed[t][P]) / max(1, sum(len(allowed[t][P]) for t in ranked)), 1)
                  for k in STATS} for P in POS}
    avg = {t: {P: {k: sum(g[k] for g in allowed[t][P]) / len(allowed[t][P]) for k in STATS} for P in POS if allowed[t][P]}
           for t in ranked}
    ranks = {}
    for P in POS:
        for k in STATS:
            order = sorted((t for t in avg if P in avg[t]), key=lambda t: -avg[t][P][k])
            for i, t in enumerate(order):
                ranks[(t, P, k)] = i + 1
    nteams = len(avg)

    def pick(keys, name):
        hits = [t for t in keys if t == name] or [t for t in keys if _same(t, name)]
        return max(hits, key=lambda t: len(allowed[t]["PG"])) if hits else None

    def side(name, inj=None):
        inj = inj or {}
        team = pick(avg, name)
        roster = pick(players, name)
        out = {"allows": {}, "players": [], "teams": nteams}
        if team:
            out["allows"] = {P: {k: [round(avg[team][P][k], 1), ranks.get((team, P, k))] for k in STATS} for P in POS if P in avg[team]}
        if roster:
            rows = []
            for pid, (pname, g, mi, p, r, a, t, pm, pmg) in players[roster].items():
                if g < 3 or mi / g < 15 or last_team.get(pid) != roster or pid not in pos_of:
                    continue
                rows.append([pname, pos_of[pid], g, round(mi / g, 1), round(p / g, 1), round(r / g, 1), round(a / g, 1), round(t / g, 1),
                             round(pm / pmg, 1) if pmg else None, inj.get(pid)])
            rows.sort(key=lambda x: -x[3])
            # nine who can play, plus anyone above them who's out (shown marked)
            keep, healthy = [], 0
            for x in rows:
                if healthy >= 9:
                    break
                keep.append(x)
                healthy += x[9] not in OUTISH
            out["players"] = keep
        return out

    def score(off, dfn, inj=None):
        """{"score": %, "pos": {P: [defense vs league %, share of the offense's points %]},
        and when players are out: "base" (the score with everyone) and "out" ([name, pos, pts a team game])}
        -- an out player's points come off his position and the other positions' shares rise."""
        o = pick(made, off)
        d = pick(avg, dfn)
        need = MIN_GAMES if sport == "nba" else MIN_TEAM_GAMES
        if not o or not d or len(made[o]["PG"]) < need or len(allowed[d]["PG"]) < need:
            return None
        pts = {P: sum(g["pts"] for g in made[o][P]) / len(made[o][P]) for P in POS}
        comp = {P: sum(w * (avg[d][P][k] / league[P][k] - 1) for k, w in SCORE_W.items() if league[P][k] > 0) for P in POS if P in avg[d]}
        gone = []
        tg = len(made[o]["PG"]) or 1
        for pid, st in (inj or {}).items():
            x = players[o].get(pid) if o in players else None
            if st in OUTISH and x and pos_of.get(pid) and last_team.get(pid) == o:
                per = x[3] / tg
                gone.append([x[0], pos_of[pid], round(per, 1)])
        def mix(pp):
            tot = sum(pp.values()) or 1
            return sum(pp[P] / tot * comp[P] for P in comp), {P: [round(100 * comp[P], 1), round(100 * pp[P] / tot)] for P in comp}
        base, _ = mix(pts)
        adj = dict(pts)
        for _n, P, per in gone:
            adj[P] = max(0.0, adj[P] - per)
        total, out = mix(adj)
        res_ = {"score": round(100 * total, 1), "pos": out}
        if gone:
            res_["base"] = round(100 * base, 1)
            res_["out"] = sorted(gone, key=lambda g: -g[2])
        return res_

    res = {"_league": league}
    for gid, away, home in games_today:
        inj = (injuries or {}).get(gid) or {}
        ia, ih = inj.get("away") or {}, inj.get("home") or {}
        res[gid] = {"away": side(away, ia), "home": side(home, ih),
                    "score": {"away": score(away, home, ia), "home": score(home, away, ih)}}
    return res
