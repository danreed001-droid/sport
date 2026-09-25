#!/usr/bin/env python3
"""STEP 2: build today's Diamond Ledger slate for a given sport (nfl or cfb).

Schedule, season PD/g, and moneylines come from ESPN (deterministic, see
lib/espn.py). QB identities/ratings, team YPP, the point spread, the 9
Second-Opinion categories, and the trend/blowout-check raw facts come from
one Claude Opus 5 web-search call (lib/claude_research.py) — Claude
supplies facts and per-category leanings; every tier/screen/threshold below
is plain, auditable code, driven by the per-sport constants in lib/sports.py.
"""
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))
from lib import espn, sports, store  # noqa: E402
from lib.claude_research import research_slate  # noqa: E402
from lib.dates import ET, now_et, today_et_str, weekday_et  # noqa: E402

TIER_SOFTEN = {"solid": "solid", "lean": "toss-up", "toss-up": "toss-up"}

CATEGORY_LABELS = {
    "rest": "Rest", "travel": "Travel", "injuries": "Injuries/Lineup", "form": "Form",
    "motivation": "Motivation/Spot", "weather": "Weather/Venue", "market": "Market",
    "matchup": "Matchup splits",
}


def tier_from_gap(gap):
    if gap < 3:
        return "toss-up"
    if gap <= 7:
        return "lean"
    return "solid"


def offense_percentiles(league_ypp):
    teams = [(t, v) for t, v in league_ypp.items() if isinstance(v, (int, float))]
    teams.sort(key=lambda kv: kv[1], reverse=True)
    n = len(teams)
    pct = {}
    for rank, (team, _) in enumerate(teams, start=1):
        pct[team] = (n - rank) / (n - 1) * 100 if n > 1 else 50.0
    return pct


def match_research_game(research_games, away, home):
    for g in research_games:
        if g.get("away") == away and g.get("home") == home:
            return g
    for g in research_games:
        ga, gh = g.get("away", ""), g.get("home", "")
        if (away in ga or ga in away) and (home in gh or gh in home):
            return g
    return {}


def apply_trend_check(trend, away, home):
    away_swing = home_swing = 0
    notes = []
    for team_name, opp_name, side in ((away, home, "away"), (home, away, "home")):
        t = trend.get(side) or {}
        if not t.get("trendAvailable", False):
            notes.append(f"{team_name}: no prior-game data")
            continue
        total_yards, pass_yards = t.get("totalYards"), t.get("passYards")
        pass_att, rush_att, margin = t.get("passAttempts"), t.get("rushAttempts"), t.get("margin")
        if None in (total_yards, pass_yards, pass_att, rush_att, margin) or not pass_att:
            notes.append(f"{team_name}: incomplete prior-game data")
            continue

        ypa = pass_yards / pass_att
        ypp = total_yards / (rush_att + pass_att) if (rush_att + pass_att) else 0
        fired = []
        if margin <= -11 and total_yards >= 426:
            fired.append(("A", team_name))
        if ypa >= 7.5 and ypp <= 5.15:
            fired.append(("B", team_name))
        if rush_att / pass_att <= 1.0 and rush_att >= 34:
            fired.append(("C", opp_name))
        if pass_att >= 41 and rush_att >= 34:
            fired.append(("D", opp_name))

        for pattern, beneficiary in fired:
            if beneficiary == away:
                away_swing += 2
            else:
                home_swing += 2
            notes.append(f"{team_name} prior game ({t.get('summary', '?')}): Pattern {pattern} → +2 {beneficiary}")
        if not fired:
            notes.append(f"{team_name} prior game ({t.get('summary', '?')}): no pattern matched")

    return away_swing, home_swing, "; ".join(notes) if notes else "no data"


def apply_blowout_check(blowout, away, home):
    away_swing = home_swing = 0
    notes = []
    for team_name, side in ((away, "away"), (home, "home")):
        b = (blowout or {}).get(side) or {}
        if not b.get("blowoutApplicable", False):
            continue
        conditions = [
            (b.get("takeawayMargin") is not None and b.get("takeawayMargin", 0) >= 2) or bool(b.get("closeAtHalf")),
            bool(b.get("favoredBy3Plus")),
            bool(b.get("oppTopTakeaways") or b.get("oppTopPointsAllowed") or b.get("oppTopPassDefense")),
            bool(b.get("rushAttempts") and b.get("rushAttempts", 0) >= 33),
            bool(b.get("turnoverProne")),
        ]
        hit_count = sum(1 for c in conditions if c)
        opponent_label = b.get("opponentLabel")
        opponent_name = home if opponent_label == "home" else away if opponent_label == "away" else None
        fired = hit_count >= 3 and opponent_name is not None
        notes.append(
            f"{team_name} blowout-win check: {hit_count}/5 conditions"
            + (f" → regression flag ON, +6 {opponent_name}" if fired else " → no flag")
        )
        if fired:
            if opponent_name == away:
                away_swing += 6
            else:
                home_swing += 6
    return away_swing, home_swing, "; ".join(notes) if notes else "not applicable"


def build_game(espn_game, research_game, pct, league_ypp, qb_veto_threshold):
    away, home = espn_game["away"], espn_game["home"]
    away_pdpg, home_pdpg = espn_game["awayPDpg"], espn_game["homePDpg"]
    away_ypp, home_ypp = league_ypp.get(away), league_ypp.get(home)
    away_pct, home_pct = pct.get(away), pct.get(home)
    away_qb_rating = research_game.get("awayQBRating")
    home_qb_rating = research_game.get("homeQBRating")
    away_ml = espn_game.get("awayMoneyline") or research_game.get("awayMoneyline")
    home_ml = espn_game.get("homeMoneyline") or research_game.get("homeMoneyline")

    game = {
        "away": away, "home": home, "time": espn_game["time"],
        "awayQB": research_game.get("awayQB"), "homeQB": research_game.get("homeQB"),
        "awayPDpg": away_pdpg, "homePDpg": home_pdpg,
        "awayYPP": away_ypp, "homeYPP": home_ypp,
        "offGap": None,
        "awayQBRating": away_qb_rating, "homeQBRating": home_qb_rating,
        "awayMoneyline": away_ml, "homeMoneyline": home_ml,
        "awaySpread": research_game.get("awaySpread"), "homeSpread": research_game.get("homeSpread"),
        "awaySpreadOdds": research_game.get("awaySpreadOdds"), "homeSpreadOdds": research_game.get("homeSpreadOdds"),
        "statLines": [], "pick": None, "confidence": None, "skipped": False,
        "altPick": None, "altConfidence": None, "altCategoryTally": None, "altReasons": [],
        "altTrendCheck": None, "altTrendFavors": None, "altBlowoutCheck": None, "altBlowoutFavors": None,
        "awayScore": None, "homeScore": None, "correct": None, "pickReturn": None,
        "altCorrect": None, "altReturn": None, "pickCover": None, "pickSpreadReturn": None,
        "altCover": None, "altSpreadReturn": None,
        "altTrendCorrect": None, "altTrendReturn": None, "altTrendCover": None, "altTrendSpreadReturn": None,
        "altBlowoutCorrect": None, "altBlowoutReturn": None, "altBlowoutCover": None, "altBlowoutSpreadReturn": None,
    }

    # ---- Ledger ----
    if away_pct is None or home_pct is None or away_pdpg is None or home_pdpg is None:
        game["confidence"] = "skip"
        game["skipped"] = True
        game["skipReason"] = "insufficient-data"
    else:
        off_gap = abs(away_pct - home_pct)
        game["offGap"] = round(off_gap, 1)
        if off_gap < 30:
            game["confidence"] = "skip"
            game["skipped"] = True
            game["skipReason"] = "off-gap"
        else:
            pick = away if away_pdpg >= home_pdpg else home
            gap = abs(away_pdpg - home_pdpg)
            tier = tier_from_gap(gap)

            pick_ypp = away_ypp if pick == away else home_ypp
            opp_ypp = home_ypp if pick == away else away_ypp
            if pick_ypp is not None and opp_ypp is not None and opp_ypp > pick_ypp:
                tier = TIER_SOFTEN[tier]

            pick_qb = away_qb_rating if pick == away else home_qb_rating
            opp_qb = home_qb_rating if pick == away else away_qb_rating
            if pick_qb is not None and opp_qb is not None and pick_qb < opp_qb:
                tier = TIER_SOFTEN[tier]

            game["pick"], game["confidence"] = pick, tier

            if away_qb_rating is not None and home_qb_rating is not None:
                diff = away_qb_rating - home_qb_rating
                veto_reason = None
                if abs(diff) <= qb_veto_threshold:
                    veto_reason = "qb-close"
                elif (pick == away and diff < 0) or (pick == home and diff > 0):
                    veto_reason = "qb-veto"
                if veto_reason:
                    game["pick"], game["confidence"] = None, "skip"
                    game["skipped"], game["skipReason"] = True, veto_reason

    stat_lines = []
    if away_pdpg is not None and home_pdpg is not None:
        stat_lines.append(f"PD/g {away_pdpg:+.2f} vs {home_pdpg:+.2f}")
    if away_ypp is not None and home_ypp is not None and game["offGap"] is not None:
        stat_lines.append(f"Yds/play {away_ypp:.2f} vs {home_ypp:.2f} · {game['offGap']:.0f}-pt gap")
    if away_qb_rating is not None and home_qb_rating is not None:
        stat_lines.append(f"QB rating {away_qb_rating:.1f} vs {home_qb_rating:.1f} ({game['awayQB']} vs {game['homeQB']})")
    game["statLines"] = stat_lines[:4]

    # ---- Second Opinion ----
    away_total = home_total = 0
    reasons = []
    if away_pdpg is not None and home_pdpg is not None and away_pdpg != home_pdpg:
        favored = away if away_pdpg > home_pdpg else home
        away_total += 1 if favored == away else 0
        home_total += 1 if favored == home else 0
        reasons.append(f"Scoring margin: {away} {away_pdpg:+.2f} vs {home} {home_pdpg:+.2f} PD/g favors {favored}")

    votes = research_game.get("categoryVotes", {}) or {}
    for key, label in CATEGORY_LABELS.items():
        v = votes.get(key) or {}
        favors = v.get("favors")
        if favors not in ("away", "home"):
            continue
        team = away if favors == "away" else home
        away_total += 1 if favors == "away" else 0
        home_total += 1 if favors == "home" else 0
        reason = (v.get("reason") or "").strip()
        reasons.append(f"{label}: {reason} favors {team}" if reason else f"{label} favors {team}")

    t_away, t_home, trend_note = apply_trend_check(research_game.get("trendCheck", {}) or {}, away, home)
    away_total += t_away
    home_total += t_home
    trend_favors = away if t_away > t_home else home if t_home > t_away else None

    b_away, b_home, blowout_note = apply_blowout_check(research_game.get("blowoutCheck", {}) or {}, away, home)
    away_total += b_away
    home_total += b_home
    blowout_favors = away if b_away > b_home else home if b_home > b_away else None

    lead = away_total - home_total
    if abs(lead) <= 3:
        alt_pick, alt_conf = None, "pass"
    elif lead >= 5:
        alt_pick, alt_conf = away, "strong"
    elif lead == 4:
        alt_pick, alt_conf = away, "lean"
    elif lead <= -5:
        alt_pick, alt_conf = home, "strong"
    else:
        alt_pick, alt_conf = home, "lean"

    game["altPick"] = alt_pick
    game["altConfidence"] = alt_conf
    game["altCategoryTally"] = f"{away_total}-{home_total}"
    game["altReasons"] = reasons
    game["altTrendCheck"] = trend_note
    game["altTrendFavors"] = trend_favors
    game["altBlowoutCheck"] = blowout_note
    game["altBlowoutFavors"] = blowout_favors

    return game


def fetch_todays_espn_games(session, cfg):
    today = now_et()
    events = espn.fetch_scoreboard(session, cfg["espn_sport"], cfg["espn_league"], today.strftime("%Y%m%d"))
    standings = espn.fetch_standings(session, cfg["espn_sport"], cfg["espn_league"])

    games = []
    for ev in events:
        status_type = ev.get("status", {}).get("type", {})
        if status_type.get("state") != "pre":
            continue  # pregame slate only; generation runs before kickoff
        comp = ev.get("competitions", [{}])[0]
        competitors = comp.get("competitors", [])
        home_team = away_team = None
        for c in competitors:
            name = c.get("team", {}).get("displayName", "Unknown")
            if c.get("homeAway") == "home":
                home_team = name
            else:
                away_team = name
        if not home_team or not away_team:
            continue

        away_ml, home_ml = espn.fetch_event_odds_from_scoreboard(comp)
        kickoff = ev.get("date")
        kickoff_et = "TBD"
        if kickoff:
            dt = datetime.fromisoformat(kickoff.replace("Z", "+00:00")).astimezone(ET)
            kickoff_et = dt.strftime("%-I:%M %p ET")

        away_std, home_std = standings.get(away_team), standings.get(home_team)
        games.append({
            "away": away_team, "home": home_team, "time": kickoff_et,
            "awayPDpg": espn.pd_per_game(away_std), "homePDpg": espn.pd_per_game(home_std),
            "awayMoneyline": away_ml, "homeMoneyline": home_ml,
            "awayRecord": f"{away_std.get('wins')}-{away_std.get('losses')}" if away_std else None,
            "homeRecord": f"{home_std.get('wins')}-{home_std.get('losses')}" if home_std else None,
        })
    return games


def main(sport_key):
    cfg = sports.get(sport_key)
    date_str = today_et_str()
    if store.read_doc(cfg["collection"], date_str) is not None:
        print(f"[{cfg['label']}] doc already exists for {date_str}; nothing to generate.")
        return

    session = espn.make_session()
    espn_games = fetch_todays_espn_games(session, cfg)
    if not espn_games:
        print(f"[{cfg['label']}] no games found today ({date_str}); writing nothing.")
        return

    print(f"[{cfg['label']}] found {len(espn_games)} game(s) today. Researching via Claude...")
    research = research_slate(date_str, weekday_et(date_str), espn_games, cfg)
    league_ypp = research.get("leagueYPP", {}) or {}
    pct = offense_percentiles(league_ypp)
    research_games = research.get("games", []) or []

    final_games = [
        build_game(
            eg,
            match_research_game(research_games, eg["away"], eg["home"]),
            pct, league_ypp, cfg["qb_veto_threshold"],
        )
        for eg in espn_games
    ]

    doc = {
        "date": date_str,
        "weekday": weekday_et(date_str),
        "sport": sport_key,
        "scored": False,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "games": final_games,
    }
    store.write_doc(cfg["collection"], date_str, doc)
    print(f"[{cfg['label']}] wrote data/{cfg['collection']}/{date_str}.json with {len(final_games)} game(s).")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "nfl")
