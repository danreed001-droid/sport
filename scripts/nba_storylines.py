#!/usr/bin/env python3
"""NBA storylines: context for the pick sheet, never a pick.

Each storyline is a situation a story could be told about (a team on a 5-game
win streak "fat and happy", a team flying home east "jet lagged"), tested on
every regular-season game from 2018-19 and 2021-22 to 2025-26 (the 2019-20
bubble and 2020-21 empty-arena seasons left out; both teams 8+ games played,
closing spread) on 2026-11-13. Of the ~70 tested, these are the ones where
history leaned 53%+ one way on 50+ games, or was unlikely by chance (p<0.05) --
which side that is can be the opposite of what the story says (a team that
lost the last meeting by 25+ didn't bounce back: it covered 47.0%).
None of them cleared the NBA Stats bar (61%+, 55%+ on unseen seasons), most
are within luck of 50%, and several can apply to one game. They're shown on
the game card with their record and aren't graded or counted anywhere.

Writes `storylines` onto each game of today's NBA slate (or the dates given)
that hasn't started: [{key, name, team, says, fact, record, pct, leans,
leanPct, against}], where `team` is who the story is about, `says` is the
story's bet ("back"/"fade" that team), `record`/`pct` are that bet's history
ATS, and `leans`/`leanPct` the side history favors. Once a game has a score
the entry is kept as it was before tip-off.
"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import nba_stats_signals as ns  # noqa: E402
from lib import storyline_live  # noqa: E402
from lib import espn, store  # noqa: E402
from lib.dates import today_et_str  # noqa: E402
from lib.nba_arenas import time_zone  # noqa: E402
from score_slate import _same_team  # noqa: E402

EAST = {"Boston Celtics", "Brooklyn Nets", "New York Knicks", "Philadelphia 76ers", "Toronto Raptors", "Chicago Bulls",
        "Cleveland Cavaliers", "Detroit Pistons", "Indiana Pacers", "Milwaukee Bucks", "Atlanta Hawks", "Charlotte Hornets",
        "Miami Heat", "Orlando Magic", "Washington Wizards"}
WEST_FAR = {"Golden State Warriors", "Los Angeles Clippers", "LA Clippers", "Los Angeles Lakers", "LA Lakers", "Phoenix Suns",
            "Sacramento Kings", "Portland Trail Blazers", "Utah Jazz", "Denver Nuggets"}

# key: (name, story's bet, wins-losses for that bet, games where it applies)
STORIES = {
    "fat_happy": ("Fat and happy", "fade", (152, 133), "on a 5+ game win streak and favored by 7+"),
    "quiet_giant": ("The quiet giant vs the hype machine", "back", (103, 80),
                    "its record undersells its point differential while the opponent's record flatters its own"),
    "second_battle": ("Second battle", "back", (217, 181), "lost the last meeting within 10 days, now at home"),
    "running_fumes": ("Running on fumes", "fade", (97, 75), "on a 5+ game win streak with 3+ wins by 5 or fewer in its last 10"),
    "sleeping_giant": ("The sleeping giant", "back", (154, 135),
                       "a winning team that lost 3 of its last 5, vs a team that won 4 of its last 5"),
    "body_clock": ("Body clock", "fade", (35, 19), "a Western team on the road in the East, tipping before 5 PM ET"),
    "holiday": ("Holiday hangover", "fade", (80, 64), "favored in the days right after Christmas (Dec 26-28)"),
    "dog_days": ("Dog days of February", "back", (41, 50), "home team, February, both teams .450-.550"),
    "escape": ("Escape artists", "fade", (74, 60), "trailed by 10+ after three quarters and won its last game, rested"),
    "jet_lag": ("Jet lag homecoming", "fade", (102, 68),
                "first home game after a 3+ game road trip that ended 2+ time zones west"),
    "schedule_loss": ("The schedule loss", "fade", (862, 760), "on the road, its 4th game in 6 nights, vs a rested team"),
    "friday": ("Friday night lights", "fade", (193, 232), "a road favorite on a Friday"),
    "payback": ("Payback with interest", "back", (233, 263), "lost the last meeting this season by 25+"),
    "champions": ("Champions don't lose three", "back", (63, 50), "a .650+ team that lost its last two"),
    "shell_shocked": ("Shell-shocked", "back", (76, 86), "led by 10+ after three quarters last game and lost"),
    "ghost_town": ("Ghost town", "fade", (820, 740), "an underdog whose top scorer has missed its last two games"),
    "prodigal": ("The prodigal star", "back", (171, 207), "an underdog whose top scorer just returned after missing 2+"),
    "emperor": ("The emperor's new clothes", "fade", (176, 152), "favored by 5+ while covering under 40% this season"),
    "steady": ("Steady Eddie", "back", (93, 81), "favored, after three straight wins by 5-15"),
    "leaky": ("Leaky defense meets leaky defense", "back", (117, 136), "home team, and both teams allowed 125+ last game"),
    # Letdown storylines (2026-11-14): a 5+ favorite vs a .450-or-worse team.
    # National TV = ESPN, ABC, TNT, NBC, Prime Video, Peacock (ESPN scoreboard
    # broadcasts). After a non-national win the underdog covered 47.9%.
    "spotlight": ("Spotlight letdown", "fade", (147, 114),
                  "won its last game on national TV, now a 5+ favorite vs a weaker team and not on national TV"),
    "letdown": ("Letdown spot", "fade", (355, 299),
                "a 5+ favorite vs a weaker team right after a big game: a national-TV win over a .550+ team "
                "(tonight not national), a win over a classic rival, a 15+ point win over a .600+ team, or its "
                "3rd game in 4 nights vs a rested team"),
}


def pos(name):
    """Possessive: "Bucks'" / "Heat's"."""
    return name + ("'" if name.endswith("s") else "'s")


# Storylines the user chose to count double in the card's "history leans"
# tally (2026-11-13): the comeback-win fade (NFL/NBA escape artists, CFB held
# on for dear life -- the same pattern in three sports), NBA jet lag (climbs
# with time zones crossed) and MLB rust (climbs with the layoff).
STRONG = {'escape', 'jet_lag'}


# Storylines counted as half a point (2026-11-13): their record doesn't hold
# up in both halves of the seasons, or the same idea went the other way in
# another sport.
WEAK = {'body_clock'}


def entry(key, team, opp, fact):
    name, says, (w, l), _ = STORIES[key]
    lw, ll = storyline_live.live("nba", key)  # graded since it went live
    w, l = w + lw, l + ll
    pct = 100 * w / (w + l)
    lean, lean_pct = (team, pct) if (pct > 50) == (says == "back") else (opp, 100 - pct)
    if pct == 50:
        lean = None
    return {"weight": 2 if key in STRONG else (0.5 if key in WEAK else 1), "live": f"{lw}-{ll}", "key": key, "name": name, "team": team, "says": says, "fact": fact, "record": f"{w}-{l}", "pct": round(pct, 1),
            "leans": lean, "leanPct": round(max(pct, 100 - pct), 1), "against": pct < 50}


def form(games):
    """Season-to-date facts from a team's prior games (oldest first)."""
    n = len(games)
    margins = [g["team_score"] - g["opp_score"] for g in games]
    wins = sum(1 for m in margins if m > 0)
    pd = sum(margins) / n
    streak = 0
    for m in reversed(margins):
        if (m > 0) == (margins[-1] > 0):
            streak += 1
        else:
            break
    return {"gp": n, "wp": wins / n, "pd": pd, "luck": wins / n - (0.5 + 0.033 * pd), "margins": margins,
            "streak": streak if margins[-1] > 0 else -streak, "w5": sum(1 for m in margins[-5:] if m > 0),
            "close_w10": sum(1 for m in margins[-10:] if 0 < m <= 5)}


def star_facts(points, games, team):
    """The team's top scorer (best per game, 5+ games): whether he missed the
    last two games, or played the last one after missing the one before."""
    tot = {}
    played = []
    for g in games:
        box = points.get(g["event_id"], team)
        if box is None:
            return None
        played.append(set(box))
        for pid, (pts, name) in box.items():
            t = tot.setdefault(pid, [0, 0, name])
            t[0] += 1
            t[1] += pts
    best = max(((v[1] / v[0], pid, v[2]) for pid, v in tot.items() if v[0] >= 5), default=None)
    if not best or len(played) < 2:
        return None
    sid = best[1]
    l1, l2 = sid in played[-1], sid in played[-2]
    return {"name": best[2], "ppg": best[0], "missed2": not l1 and not l2, "returned": l1 and not l2}


def tip_hour(time_str):
    """'7:30 PM ET' -> 19.5, or None."""
    try:
        t, ampm = time_str.replace("ET", "").split()[:2]
        h, m = (t.split(":") + ["0"])[:2]
        h = int(h) % 12 + (12 if ampm.upper() == "PM" else 0)
        return h + int(m) / 60
    except (AttributeError, ValueError):
        return None


NATIONAL_NETS = {"ESPN", "ABC", "TNT", "NBC", "Prime Video", "Peacock", "truTV", "HBO Max", "ESPN2", "TBS"}
RIVALS = {frozenset(p) for p in [
    ("Boston Celtics", "Los Angeles Lakers"), ("Boston Celtics", "Philadelphia 76ers"), ("Boston Celtics", "New York Knicks"),
    ("New York Knicks", "Brooklyn Nets"), ("Los Angeles Lakers", "LA Clippers"), ("Los Angeles Lakers", "Los Angeles Clippers"),
    ("Chicago Bulls", "Detroit Pistons"), ("New York Knicks", "Miami Heat"), ("Golden State Warriors", "Cleveland Cavaliers"),
    ("Dallas Mavericks", "San Antonio Spurs"), ("Houston Rockets", "San Antonio Spurs"), ("Dallas Mavericks", "Houston Rockets"),
    ("Los Angeles Lakers", "Golden State Warriors"), ("Phoenix Suns", "Los Angeles Lakers"), ("Miami Heat", "Boston Celtics"),
    ("Indiana Pacers", "New York Knicks"), ("Utah Jazz", "Denver Nuggets"), ("Milwaukee Bucks", "Chicago Bulls"),
    ("Philadelphia 76ers", "Brooklyn Nets"), ("Memphis Grizzlies", "Golden State Warriors")]}
_TV = {}


def national(session, date_str, a, b):
    """True when ESPN lists a national broadcast for a vs b on date_str, False
    when it lists the game without one, None when unknown."""
    if date_str not in _TV:
        try:
            evs = espn.fetch_scoreboard(session, "basketball", "nba", date_str.replace("-", ""))
        except Exception:
            return None  # not cached: retried on the next use
        day = []
        for ev in evs:
            comp = ev["competitions"][0]
            names = [c["team"]["displayName"] for c in comp["competitors"]]
            nets = set()
            for bc in comp.get("broadcasts") or []:
                if (bc.get("market") or "").lower() == "national":
                    nets.update(bc.get("names") or [])
            for gb in comp.get("geoBroadcasts") or []:
                if ((gb.get("market") or {}).get("type") or "").lower() == "national":
                    nets.add((gb.get("media") or {}).get("shortName"))
            day.append((names, bool(nets & NATIONAL_NETS)))
        _TV[date_str] = day
    for names, nat in _TV[date_str]:
        if any(_same_team(a, x) for x in names) and any(_same_team(b, x) for x in names):
            return nat
    return None


def record_before(games, before):
    """Win pct from a team's games before a date (None with no games)."""
    gs = [g for g in games if g["date"] < before]
    return sum(g["won"] for g in gs) / len(gs) if gs else None


def team_side(session, points, q_cache, date_str, team, opp, is_home, prior, opp_prior, my_spread, tip, by_team=None):
    """Storylines about `team` tonight."""
    out = []
    D = date.fromisoformat(date_str)
    t, o = form(prior), form(opp_prior)
    last = prior[-1]
    rest = (D - date.fromisoformat(last["date"])).days
    orest = (D - date.fromisoformat(opp_prior[-1]["date"])).days
    sp = my_spread
    rec = f"{round(t['wp'] * t['gp'])}-{t['gp'] - round(t['wp'] * t['gp'])}"

    if t["streak"] >= 5 and sp is not None and sp <= -7:
        out.append(entry("fat_happy", team, opp, f"{team} has won {t['streak']} straight and is a {sp:+g} favorite."))
    if t["luck"] <= -0.05 and o["luck"] >= 0.10:
        out.append(entry("quiet_giant", team, opp, f"{pos(team)} point differential ({t['pd']:+.1f} a game) is better than "
                                                   f"its {rec} record, and {pos(opp)} record is better than its {o['pd']:+.1f}."))
    meets = [g for g in prior if g["opp"] == opp or _same_team(g["opp"], opp)]
    if meets:
        m = meets[-1]
        margin = m["team_score"] - m["opp_score"]
        days = (D - date.fromisoformat(m["date"])).days
        if days <= 10 and margin < 0 and is_home:
            out.append(entry("second_battle", team, opp, f"{team} lost to {opp} {m['team_score']:g}-{m['opp_score']:g} "
                                                         f"{days} days ago and is at home tonight."))
        if margin <= -25:
            out.append(entry("payback", team, opp, f"{team} lost the last meeting {m['team_score']:g}-{m['opp_score']:g} "
                                                   f"({m['date']})."))
    if t["streak"] >= 5 and t["close_w10"] >= 3:
        out.append(entry("running_fumes", team, opp, f"{team} has won {t['streak']} straight, {t['close_w10']} of its last 10 "
                                                     f"by 5 or fewer."))
    if t["wp"] >= 0.55 and t["w5"] <= 2 and o["w5"] >= 4:
        out.append(entry("sleeping_giant", team, opp, f"{team} ({rec}) is {t['w5']}-{min(5, t['gp']) - t['w5']} in its last "
                                                      f"five; {opp} is {o['w5']}-{min(5, o['gp']) - o['w5']}."))
    if not is_home and team in WEST_FAR and opp in EAST and tip is not None and tip < 17:
        out.append(entry("body_clock", team, opp, f"{team} plays at {opp} with an early tip."))
    if (D.month, D.day) in ((12, 26), (12, 27), (12, 28)) and sp is not None and sp < 0:
        out.append(entry("holiday", team, opp, f"{team} is a {sp:+g} favorite right after Christmas."))
    if is_home and D.month == 2 and 0.45 <= t["wp"] <= 0.55 and 0.45 <= o["wp"] <= 0.55:
        out.append(entry("dog_days", team, opp, f"February, {team} and {opp} both near .500."))
    q = ns.quarter_data(session, q_cache, last["date"])
    qe = next((v for v in q.values() if team in v["teams"] and last["opp"] in v["teams"]), None)
    trailed = ns.trailed_after_three(qe, team, last["opp"]) if qe else None
    if trailed is not None:
        if trailed >= 10 and last["won"] and rest >= 2:
            out.append(entry("escape", team, opp, f"{team} trailed {last['opp']} by {trailed:g} after three quarters and won "
                                                  f"{last['team_score']:g}-{last['opp_score']:g}."))
        if trailed <= -10 and not last["won"]:
            out.append(entry("shell_shocked", team, opp, f"{team} led {last['opp']} by {-trailed:g} after three quarters and lost "
                                                         f"{last['team_score']:g}-{last['opp_score']:g}."))
    if is_home and not last["is_home"]:
        trip = 0
        for g in reversed(prior):
            if g["is_home"]:
                break
            trip += 1
        zh, zl = time_zone(team), time_zone(last["opp"])
        if trip >= 3 and zh is not None and zl is not None and zh - zl >= 2:
            out.append(entry("jet_lag", team, opp, f"{pos(team)} first home game after a {trip}-game road trip that ended at "
                                                   f"{last['opp']}, {zh - zl} time zones west."))
    in6 = 1 + sum(1 for g in prior if (D - date.fromisoformat(g["date"])).days <= 5)
    if not is_home and in6 >= 4 and orest >= 2:
        out.append(entry("schedule_loss", team, opp, f"{pos(team)} {in6}th game in 6 nights, on the road; {opp} has had "
                                                     f"{orest - 1} day{'s' if orest != 2 else ''} off."))
    if not is_home and D.weekday() == 4 and sp is not None and sp < 0:
        out.append(entry("friday", team, opp, f"{team} is a {sp:+g} road favorite on a Friday."))
    if t["wp"] >= 0.65 and t["streak"] == -2:
        out.append(entry("champions", team, opp, f"{team} ({rec}) lost its last two."))
    if sp is not None and sp > 0:
        st = star_facts(points, prior, team)
        if st and st["missed2"]:
            out.append(entry("ghost_town", team, opp, f"{pos(team)} top scorer {st['name']} ({st['ppg']:.1f} a game) missed its "
                                                       f"last two games; {team} is a {sp:+g} underdog."))
        if st and st["returned"]:
            out.append(entry("prodigal", team, opp, f"{pos(team)} top scorer {st['name']} ({st['ppg']:.1f} a game) returned last "
                                                     f"game after missing the one before; {team} is a {sp:+g} underdog."))
    if sp is not None and sp <= -5 and t["gp"] >= 10:
        covers = []
        for g in prior:
            hs = ns.home_spread_of(g["event_id"])
            if hs is None:
                continue
            cm = g["team_score"] - g["opp_score"] + (hs if g["is_home"] else -hs)
            if cm != 0:
                covers.append(cm > 0)
        if len(covers) >= 8 and sum(covers) / len(covers) < 0.4:
            out.append(entry("emperor", team, opp, f"{team} is a {sp:+g} favorite but has covered {sum(covers)} of "
                                                   f"{len(covers)} this season."))
    if sp is not None and sp < 0 and len(t["margins"]) >= 3 and all(5 <= m <= 15 for m in t["margins"][-3:]):
        out.append(entry("steady", team, opp, f"{team} won its last three by "
                                              f"{', '.join(f'{m:g}' for m in reversed(t['margins'][-3:]))}."))
    # Letdown storylines: a 5+ favorite vs a .450-or-worse team.
    if sp is not None and sp <= -5 and o["wp"] <= 0.45:
        won_by = last["team_score"] - last["opp_score"]
        prev_opp_games = (by_team or {}).get(next((k for k in (by_team or {}) if _same_team(last["opp"], k)), ""), [])
        pwp = record_before([g for g in prev_opp_games if g["date"] >= ns.season_start(date_str)], last["date"])
        prev_nat = national(session, last["date"], team, last["opp"]) if won_by > 0 else None
        now_nat = national(session, date_str, team, opp)
        spot = won_by > 0 and prev_nat is True and now_nat is False
        if spot:
            out.append(entry("spotlight", team, opp, f"{team} beat {last['opp']} {last['team_score']:g}-{last['opp_score']:g} "
                                                     f"on national TV and is a {sp:+g} favorite tonight off national TV."))
        reasons = []
        if spot and pwp is not None and pwp >= 0.55:
            reasons.append(f"it just beat {last['opp']} on national TV")
        if won_by > 0 and frozenset((team, last["opp"])) in RIVALS:
            reasons.append(f"it just beat rival {last['opp']}")
        if won_by >= 15 and pwp is not None and pwp >= 0.60:
            reasons.append(f"it just beat {last['opp']} ({pwp:.3f}) by {won_by:g}")
        if 1 + sum(1 for g in prior if (D - date.fromisoformat(g["date"])).days <= 3) >= 3 and orest >= 2:
            reasons.append(f"it's playing its 3rd game in 4 nights and {opp} is rested")
        if reasons and not spot:  # the spotlight storyline already covers that game
            out.append(entry("letdown", team, opp, f"{team} is a {sp:+g} favorite vs {opp} ({round(o['wp'] * o['gp'])}-"
                                                   f"{o['gp'] - round(o['wp'] * o['gp'])}): " + "; ".join(reasons) + "."))
    if is_home and last["opp_score"] >= 125 and opp_prior[-1]["opp_score"] >= 125:
        out.append(entry("leaky", team, opp, f"{team} allowed {last['opp_score']:g} last game and {opp} allowed "
                                             f"{opp_prior[-1]['opp_score']:g}."))
    return out


def storylines_for(session, points, by_team, q_cache, date_str, home, away, home_spread, tip):
    s0 = ns.season_start(date_str)

    def resolve(name):
        if name in by_team:
            return name
        return next((k for k in by_team if _same_team(name, k)), None)

    h, a = resolve(home), resolve(away)
    if not h or not a:
        return []
    hp = [g for g in by_team[h] if s0 <= g["date"] < date_str]
    ap = [g for g in by_team[a] if s0 <= g["date"] < date_str]
    if len(hp) < 8 or len(ap) < 8:  # as backtested: both teams 8+ games
        return []
    out = team_side(session, points, q_cache, date_str, h, a, True, hp, ap, home_spread, tip, by_team)
    out += team_side(session, points, q_cache, date_str, a, h, False, ap, hp,
                     None if home_spread is None else -home_spread, tip, by_team)
    # Name teams as the slate does.
    names = {h: home, a: away}
    for e in out:
        e["team"] = names.get(e["team"], e["team"])
        if e["leans"]:
            e["leans"] = names.get(e["leans"], e["leans"])
    return out


def main():
    # --backfill: also finished games (this season's games before storylines
    # went live, from the games before each one); run storyline_records.py after.
    backfill = "--backfill" in sys.argv
    dates = [a for a in sys.argv[1:] if not a.startswith("--")] or [today_et_str()]
    session = espn.make_session()
    points = ns.BoxCache(session)

    def regular(g, team):
        if str(g["event_id"]).startswith("manual-"):
            return True
        t = points.season_type(g["event_id"])
        if t is None:
            return ns.manual.team_game("nba", g["date"], team) is not None
        return t == 2

    by_team = {team: [g for g in games if regular(g, team)] for team, games in ns.load_team_logs().items()}
    q_cache = {}
    try:
        for date_str in dates:
            doc = store.read_doc("nba", date_str)
            if doc is None:
                print(f"{date_str}: no NBA slate.")
                continue
            regular_today = ns.regular_season_games(session, date_str)
            changed = 0
            for g in doc.get("games", []):
                if not g.get("away") or not g.get("home") or (isinstance(g.get("awayScore"), (int, float)) and not backfill):
                    continue  # started or final: keep what was there before tip-off
                if not regular_today.get((g["away"], g["home"]), True):
                    new = []
                else:
                    new = storylines_for(session, points, by_team, q_cache, date_str, g["home"], g["away"],
                                         g.get("statsSpread", g.get("homeSpread")), tip_hour(g.get("time")))
                if new != (g.get("storylines") or []):
                    if new:
                        g["storylines"] = new
                    else:
                        g.pop("storylines", None)
                    changed += 1
                for e in new:
                    print(f"  {g['away']} @ {g['home']}: {e['name']} ({e['team']}) -> leans {e['leans']} {e['leanPct']}%")
            if changed:
                store.write_doc("nba", date_str, doc)
            print(f"{date_str}: storylines on {sum(1 for g in doc.get('games', []) if g.get('storylines'))} game(s).")
    finally:
        points.save()


if __name__ == "__main__":
    main()
