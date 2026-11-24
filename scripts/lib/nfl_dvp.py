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
from .nba_dvp import team_points, offense_pct  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BOX = os.path.join(ROOT, "data", "raw", "nfl_player_box.json")
# College football (archive_college_player_box.py): only games of teams on our
# CFB slates are saved, so a defense needs 3+ saved games to be ranked; box
# scores have no targets, so WR/TE usage is catches and targets aren't shown.
BOXES = {"nfl": BOX, "cfb": os.path.join(ROOT, "data", "raw", "cfb_player_box.json")}
MIN_TEAM_GAMES = 3
OUTISH = {"out", "injured reserve", "suspension", "suspended"}   # see lib/nba_dvp.py
POS = ("QB", "RB", "WR", "TE")
# per position: (key, label, value from a box row)
STATS = {
    "QB": [("pyd", "Pass yds", lambda r: r[5]), ("ptd", "Pass TD", lambda r: r[6]), ("int", "INT", lambda r: r[7]), ("ryd", "Rush yds", lambda r: r[9])],
    "RB": [("ryd", "Rush yds", lambda r: r[9]), ("rec", "Rec", lambda r: r[11]), ("cyd", "Rec yds", lambda r: r[12]), ("td", "TD", lambda r: r[10] + r[13])],
    "WR": [("rec", "Rec", lambda r: r[11]), ("cyd", "Rec yds", lambda r: r[12]), ("td", "TD", lambda r: r[13]), ("tgt", "Targets", lambda r: r[14])],
}
STATS["TE"] = STATS["WR"]
SPEC = {P: [[k, lab] for k, lab, _f in STATS[P]] for P in POS}
# Matchup score (2026-11-19): how soft tonight's defense is to this offense, the
# NFL version of lib/nba_dvp.py's. Per position, the defense's allowed numbers vs
# the league (QB pass yds .6 / pass TD .3 / INT -.1; RB rush yds .6 / rec yds .2
# / TD .2; WR and TE rec yds .6 / TD .3 / rec .1), each position weighted by how
# this offense gains its yards: its passing share split QB .45 / WR .40 / TE .15,
# its rushing share to RB. Not backtested (one season of box scores so far).
SCORE_W = {"QB": {"pyd": .6, "ptd": .3, "int": -.1}, "RB": {"ryd": .6, "cyd": .2, "td": .2},
           "WR": {"cyd": .6, "td": .3, "rec": .1}, "TE": {"cyd": .6, "td": .3, "rec": .1}}
PASS_SPLIT = {"QB": .45, "WR": .40, "TE": .15}
# Injured offense (see lib/nba_dvp.py OUT_KEEP): an out player's share of the
# team's yards (rush + receiving + half the QB's passing, half of a QB's own
# total) times its points a game, taken off at OUT_KEEP. This season (228 NFL
# team-games) the fit was 0.76 (missing 4.4 pts: 3.7 under; 7.9: 7.2 under) and
# CFB 0.36 (870, 9.6 missing: 3.8 under); 0.5, since the NFL sample is small.
OUT_KEEP = 0.5
MIN_GAMES = 3
_CACHE = {}


def _pos(p):
    return "RB" if p == "FB" else p if p in POS else None


def _load(sport="nfl"):
    path = BOX if sport == "nfl" else BOXES[sport]
    if ("box", path) not in _CACHE:
        try:
            with open(path, encoding="utf-8") as f:
                box = json.load(f)
        except (OSError, ValueError):
            box = {}
        _CACHE[("box", path)] = sorted((e["date"], eid, e) for eid, e in box.items() if e.get("players"))
    return _CACHE[("box", path)]


def _same(a, b):
    from score_slate import _same_team
    return a == b or _same_team(a, b)


def _usage(P, r):
    return r[4] if P == "QB" else (r[8] + r[11]) if P == "RB" else (r[14] or r[11])


def for_slate(slate_date, games_today, sport="nfl", injuries=None):
    """{"_league": {pos: {stat: per game}}, "_spec": SPEC,
        game id: {"away": side, "home": side}}; a side is
       {"allows": {pos: {stat: [per game, rank 1 = most allowed]}}, "teams": n,
        "players": [[name, pos, games, {stat: per game}], ...]}."""
    games = [g for g in _load(sport) if g[0] < slate_date]
    stats = STATS if sport == "nfl" else {P: [x for x in v if x[0] != "tgt"] for P, v in STATS.items()}
    if not games or not games_today:
        return {}
    allowed = defaultdict(lambda: defaultdict(list))
    players = defaultdict(dict)   # team -> pid -> [name, pos, g, usage, {stat: total}]
    yds = defaultdict(lambda: [0.0, 0.0, 0])   # offense team -> [pass yds, rush yds, games]
    last_team = {}
    pf = defaultdict(list)                     # offense team -> [points a game] (overall grade, see lib/nba_dvp.py)
    pa = defaultdict(list)                     # defense team -> [points allowed a game]
    final = team_points(sport)
    for _d, _eid, e in games:
        teams = list(e["players"])
        if len(teams) != 2:
            continue
        for i, team in enumerate(teams):
            opp = teams[1 - i]
            sums = {P: {k: 0.0 for k, _l, _f in stats[P]} for P in POS}
            for r in e["players"][team]:
                P = _pos(r[2])
                if not P:
                    continue
                for k, _l, f in stats[P]:
                    sums[P][k] += f(r)
                x = players[team].setdefault(r[0], [r[1], P, 0, 0.0, {k: 0.0 for k, _l, _f in stats[P]}])
                x[2] += 1
                x[3] += _usage(P, r)
                for k, _l, f in stats[P]:
                    x[4][k] = x[4].get(k, 0.0) + f(r)
                last_team[r[0]] = team
            for P in POS:
                allowed[opp][P].append(sums[P])
            y = yds[team]
            y[0] += sums["QB"]["pyd"]
            y[1] += sum(r[9] for r in e["players"][team])
            y[2] += 1
            sc = (final.get(str(_eid)) or {}).get(team)
            if sc is not None:
                pf[team].append(sc)
                pa[opp].append(sc)
    ranked = [t for t in allowed if len(allowed[t]["QB"]) >= MIN_TEAM_GAMES]
    league = {P: {k: round(sum(g[k] for t in ranked for g in allowed[t][P]) / max(1, sum(len(allowed[t][P]) for t in ranked)), 1)
                  for k, _l, _f in stats[P]} for P in POS}
    avg = {t: {P: {k: sum(g[k] for g in allowed[t][P]) / len(allowed[t][P]) for k, _l, _f in stats[P]} for P in POS if allowed[t][P]}
           for t in ranked}
    ranks = {}
    for P in POS:
        for k, _l, _f in stats[P]:
            for i, t in enumerate(sorted((t for t in avg if P in avg[t]), key=lambda t: -avg[t][P][k])):
                ranks[(t, P, k)] = i + 1
    offq, lg_pts = offense_pct(pf, ranked)
    defq, _ = offense_pct(pa, ranked)
    cap = {"QB": 1, "RB": 2, "WR": 3, "TE": 1}

    def pick(keys, name):
        hits = [t for t in keys if t == name] or [t for t in keys if _same(t, name)]
        return max(hits, key=lambda t: len(allowed[t]["QB"])) if hits else None

    def side(name, inj=None):
        inj = inj or {}
        team = pick(avg, name)
        roster = pick(players, name)
        out = {"allows": {}, "players": [], "teams": len(avg)}
        if team:
            out["allows"] = {P: {k: [round(v, 1), ranks.get((team, P, k))] for k, v in avg[team][P].items()} for P in POS if P in avg[team]}
        if roster:
            rows = []
            for P in POS:
                cand = [(pid, x) for pid, x in players[roster].items() if x[1] == P and last_team.get(pid) == roster and x[2] >= 2]
                cand.sort(key=lambda px: -px[1][3] / px[1][2])
                n_ok = 0
                for pid, (pname, _P, g, use, tot) in cand:
                    if n_ok >= cap[P]:
                        break
                    if use / g < (10 if P == "QB" else 3):
                        continue
                    st = inj.get(pid)
                    rows.append([pname, P, g, {k: round(v / g, 1) for k, v in tot.items()}, st])
                    n_ok += st not in OUTISH        # an out starter is shown marked, and the next man up too
            out["players"] = rows
        return out

    def score(off, dfn, inj=None):
        """As in lib/nba_dvp.py; an out player's rushing yards come off the
        offense's run share (a missing QB or receiver doesn't change how much
        it throws), and he's listed in "out" with "base" the score with everyone."""
        o = pick(yds, off)
        d = pick(avg, dfn)
        if not o or not d or yds[o][2] < MIN_GAMES or len(allowed[d]["QB"]) < MIN_GAMES:
            return None
        tg = yds[o][2] or 1
        gone, rush_off, out_share = [], 0.0, 0.0
        team_y = yds[o][1] + 1.5 * yds[o][0]
        for pid, st in (inj or {}).items():
            x = players[o].get(pid) if o in players else None
            if st in OUTISH and x and last_team.get(pid) == o and x[2] >= 2:
                rush_off += x[4].get("ryd", 0.0) / tg
                mine = x[4].get("ryd", 0.0) + x[4].get("cyd", 0.0) + x[4].get("pyd", 0.0)
                sh = (0.5 if x[1] == "QB" else 1.0) * mine / max(1.0, team_y)
                if sh >= 0.08:
                    out_share += sh
                main = {"QB": "pyd", "RB": "ryd", "WR": "cyd", "TE": "cyd"}[x[1]]
                gone.append([x[0], x[1], round(x[4].get(main, 0.0) / tg, 1)])
        base_ps = yds[o][0] / max(1.0, yds[o][0] + yds[o][1])
        ps = yds[o][0] / max(1.0, yds[o][0] + max(0.0, yds[o][1] - rush_off * tg))
        def total_at(p_s):
            t = 0.0
            for P in POS:
                if P in avg[d]:
                    c = sum(w * (avg[d][P][k] / league[P][k] - 1) for k, w in SCORE_W[P].items() if league[P][k] > 0)
                    t += (p_s * PASS_SPLIT[P] if P in PASS_SPLIT else 1 - p_s) * c
            return t
        out, total = {}, 0.0
        for P in POS:
            if P not in avg[d]:
                continue
            comp = sum(w * (avg[d][P][k] / league[P][k] - 1) for k, w in SCORE_W[P].items() if league[P][k] > 0)
            share = ps * PASS_SPLIT[P] if P in PASS_SPLIT else 1 - ps
            total += share * comp
            out[P] = [round(100 * comp, 1), round(100 * share)]
        r_ = {"score": round(100 * total, 1), "pos": out}
        if o in offq:
            r_["off"] = round(offq[o], 1)
            r_["ppg"] = round(sum(pf[o]) / len(pf[o]), 1)
            lost = OUT_KEEP * min(out_share, 1.0) * r_["ppg"]
            if lost >= 0.05 and lg_pts:
                r_["offBase"] = r_["off"]
                r_["offLost"] = round(lost, 1)
                r_["off"] = round(offq[o] - 100 * lost / lg_pts, 1)
            if d in defq:
                r_["dfn"] = round(defq[d], 1)
                r_["papg"] = round(sum(pa[d]) / len(pa[d]), 1)
                r_["overall"] = round(r_["off"] + r_["dfn"], 1)
        if gone:
            r_["base"] = round(100 * total_at(base_ps), 1)
            r_["out"] = gone
        return r_

    res = {"_league": league, "_ppg": round(lg_pts, 1), "_spec": {P: [[k, lab] for k, lab, _f in stats[P]] for P in POS}}
    for gid, away, home in games_today:
        inj = (injuries or {}).get(gid) or {}
        ia, ih = inj.get("away") or {}, inj.get("home") or {}
        res[gid] = {"away": side(away, ia), "home": side(home, ih),
                    "score": {"away": score(away, home, ia), "home": score(home, away, ih)}, "lg": round(lg_pts, 1)}
    return res
