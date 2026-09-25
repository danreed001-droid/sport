"""MLB Ledger + Second Opinion model, per the Diamond Ledger MLB skill.

Differs from the NFL/CFB model in real ways, not just constants: run
differential is a full-SEASON total (not a per-game rate), the starter
comparison falls back through two different stats (OPS-against, then WHIP)
instead of a single QB rating, there is no trend/blowout check, and the
Second Opinion's "scoring margin" category only counts when the run-diff gap
is at least 15 runs (otherwise it's noise, not signal).
"""
from datetime import datetime

from lib import espn
from lib.dates import ET

TIER_SOFTEN = {"solid": "solid", "lean": "toss-up", "toss-up": "toss-up"}

CATEGORY_LABELS = {
    "rest": "Rest", "travel": "Travel", "injuries": "Injuries/Lineup", "form": "Form",
    "motivation": "Motivation/Spot", "weather": "Weather/Venue", "market": "Market",
    "matchup": "Matchup splits",
}

SYSTEM_PROMPT = """You are a research assistant for an MLB prediction pipeline called Diamond Ledger.
For each matchup you are given, research and return ONLY the fields requested. You are not asked to \
decide who to bet on or how confident to be — a separate deterministic program applies all scoring \
and threshold logic afterwards using the facts you provide.

Rules:
- Use web search to find current, real information. Never fabricate a stat, injury, or odds number.
- If you cannot find a number after searching, use null for it — do not estimate or guess.
- Season run differential and moneylines are already known (given to you below as "known") — do
  not re-derive or override them; only fill in a moneyline yourself if it says null.
- Team OPS: season OPS for both teams. Starting pitcher ERA and WHIP should basically never come back
  null for an active MLB starter. OPS-against for each starter is frequently unavailable — null is
  common and acceptable there.
- The run line (awaySpread/homeSpread, standard is ±1.5, signed from each side) and each side's
  odds must be a real sportsbook line captured now, pregame.
- The 8 Second-Opinion categories (rest, travel, injuries, form, motivation, weather, market, matchup)
  each need a verdict: which team a single concrete, checkable fact favors ("away", "home", or
  "neutral" if you can't verify one). Do NOT pull ERA, WHIP, team OPS, or opponent OPS into these 8
  categories — those are reserved for the Ledger model. Categories may describe a starter's
  workload/role/availability (innings recently thrown, opener/bullpen game, TBD, injured) as a
  checkable fact, but must never slide into a performance-quality judgment about a pitcher (e.g.
  calling an arm "taxed" or a "downgrade") — that's the Ledger's job, not this one's.
- Fact discipline: every specific claim (who's on a short leash, who's out, which side a line move
  favors) must match the game's own actual away/home teams and pitchers given to you below. Double
  check before writing a reason down — never attribute a fact to the wrong team.
- A team playing a doubleheader appears as two separate matchups below with the same two teams but
  different times/pitchers; treat them as fully independent games.

Return your findings as a single JSON object and nothing else — no prose, no markdown code fences,
just the raw JSON, matching the shape given in the user message."""

_SCHEMA_HINT = """Return JSON shaped exactly like this (one entry per game in "games", using the exact
away/home team names given to you — if two entries share the same teams, they're a doubleheader;
match them back up by the time given):
{
  "leagueOPS": {"Los Angeles Dodgers": 0.780, "...": 0.0},
  "games": [
    {
      "away": "...", "home": "...", "time": "...",
      "awayPitcher": "...", "homePitcher": "...",
      "awayMoneyline": null, "homeMoneyline": null,
      "awaySpread": 1.5, "homeSpread": -1.5,
      "awaySpreadOdds": -110, "homeSpreadOdds": -110,
      "awayERA": 0.0, "homeERA": 0.0,
      "awayWHIP": 0.0, "homeWHIP": 0.0,
      "awayOppOPS": null, "homeOppOPS": null,
      "categoryVotes": {
        "rest": {"favors": "away|home|neutral", "reason": "..."},
        "travel": {"favors": "...", "reason": "..."},
        "injuries": {"favors": "...", "reason": "..."},
        "form": {"favors": "...", "reason": "..."},
        "motivation": {"favors": "...", "reason": "..."},
        "weather": {"favors": "...", "reason": "..."},
        "market": {"favors": "...", "reason": "..."},
        "matchup": {"favors": "...", "reason": "..."}
      }
    }
  ]
}"""


def build_system_prompt(cfg):
    return SYSTEM_PROMPT


def build_user_prompt(date_str, weekday, matchups, cfg):
    lines = [f"Today is {weekday}, {date_str} (US Eastern). Research these MLB games:", ""]
    for m in matchups:
        lines.append(
            f"- {m['away']} @ {m['home']} ({m['time']}) — known season run differential: away "
            f"{m.get('awayRD')}, home {m.get('homeRD')}; known moneyline: away "
            f"{m.get('awayMoneyline')}, home {m.get('homeMoneyline')}; season record: away "
            f"{m.get('awayRecord')}, home {m.get('homeRecord')}"
        )
    lines.append("")
    lines.append("Also research season OPS for every MLB team that has played this season.")
    lines.append("")
    lines.append(_SCHEMA_HINT)
    return "\n".join(lines)


def fetch_games(session, cfg):
    """ESPN-sourced pregame facts: schedule, moneylines, and season-total
    run differential (NOT per-game — MLB's Ledger uses season totals)."""
    from lib.dates import now_et

    today = now_et()
    events = espn.fetch_scoreboard(session, cfg["espn_sport"], cfg["espn_league"], today.strftime("%Y%m%d"))
    standings = espn.fetch_standings(session, cfg["espn_sport"], cfg["espn_league"])

    games = []
    for ev in events:
        status_type = ev.get("status", {}).get("type", {})
        if status_type.get("state") != "pre":
            continue
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
        start_et = "TBD"
        if kickoff:
            dt = datetime.fromisoformat(kickoff.replace("Z", "+00:00")).astimezone(ET)
            start_et = dt.strftime("%-I:%M %p ET")

        away_std, home_std = standings.get(away_team), standings.get(home_team)
        games.append({
            "away": away_team, "home": home_team, "time": start_et,
            "espnGameId": str(ev.get("id")),
            "awayRD": away_std.get("diff") if away_std else None,
            "homeRD": home_std.get("diff") if home_std else None,
            "awayMoneyline": away_ml, "homeMoneyline": home_ml,
            "awayRecord": f"{away_std.get('wins')}-{away_std.get('losses')}" if away_std else None,
            "homeRecord": f"{home_std.get('wins')}-{home_std.get('losses')}" if home_std else None,
        })
    return games


def tier_from_gap(gap):
    if gap < 40:
        return "toss-up"
    if gap <= 100:
        return "lean"
    return "solid"


def ops_percentiles(league_ops):
    teams = [(t, v) for t, v in league_ops.items() if isinstance(v, (int, float))]
    teams.sort(key=lambda kv: kv[1], reverse=True)
    n = len(teams)
    return {t: (n - rank) / (n - 1) * 100 if n > 1 else 50.0 for rank, (t, _) in enumerate(teams, start=1)}


def match_research_game(research_games, away, home, time_str):
    candidates = [g for g in research_games if g.get("away") == away and g.get("home") == home]
    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1:
        for g in candidates:  # doubleheader: prefer the matching kickoff time
            if g.get("time") == time_str:
                return g
        return candidates[0]
    for g in research_games:
        ga, gh = g.get("away", ""), g.get("home", "")
        if (away in ga or ga in away) and (home in gh or gh in home):
            return g
    return {}


def build_game(espn_game, research_game, pct, league_ops):
    away, home = espn_game["away"], espn_game["home"]
    away_rd, home_rd = espn_game["awayRD"], espn_game["homeRD"]
    away_ops, home_ops = league_ops.get(away), league_ops.get(home)
    away_pct, home_pct = pct.get(away), pct.get(home)
    away_era, home_era = research_game.get("awayERA"), research_game.get("homeERA")
    away_whip, home_whip = research_game.get("awayWHIP"), research_game.get("homeWHIP")
    away_oppops, home_oppops = research_game.get("awayOppOPS"), research_game.get("homeOppOPS")
    away_ml = espn_game.get("awayMoneyline") or research_game.get("awayMoneyline")
    home_ml = espn_game.get("homeMoneyline") or research_game.get("homeMoneyline")

    game = {
        "away": away, "home": home, "time": espn_game["time"], "espnGameId": espn_game.get("espnGameId"),
        "awayPitcher": research_game.get("awayPitcher"), "homePitcher": research_game.get("homePitcher"),
        "awayRD": away_rd, "homeRD": home_rd,
        "awayOPS": away_ops, "homeOPS": home_ops, "opsGap": None,
        "awayERA": away_era, "homeERA": home_era,
        "awayWHIP": away_whip, "homeWHIP": home_whip,
        "awayOppOPS": away_oppops, "homeOppOPS": home_oppops,
        "awayMoneyline": away_ml, "homeMoneyline": home_ml,
        "awaySpread": research_game.get("awaySpread"), "homeSpread": research_game.get("homeSpread"),
        "awaySpreadOdds": research_game.get("awaySpreadOdds"), "homeSpreadOdds": research_game.get("homeSpreadOdds"),
        "pick": None, "confidence": None, "skipped": False,
        "altPick": None, "altConfidence": None, "altCategoryTally": None, "altReasons": [],
        "awayScore": None, "homeScore": None, "correct": None, "pickReturn": None,
        "altCorrect": None, "altReturn": None, "pickCover": None, "pickSpreadReturn": None,
        "altCover": None, "altSpreadReturn": None,
    }

    # ---- Ledger ----
    if away_pct is None or home_pct is None or away_rd is None or home_rd is None:
        game["confidence"] = "skip"
        game["skipped"] = True
        game["skipReason"] = "insufficient-data"
    else:
        ops_gap = abs(away_pct - home_pct)
        game["opsGap"] = round(ops_gap, 1)
        if ops_gap < 30:
            game["confidence"] = "skip"
            game["skipped"] = True
            game["skipReason"] = "ops-gap"
        else:
            pick = away if away_rd >= home_rd else home
            gap = abs(away_rd - home_rd)
            tier = tier_from_gap(gap)

            pick_ops = away_ops if pick == away else home_ops
            opp_ops = home_ops if pick == away else away_ops
            if pick_ops is not None and opp_ops is not None and opp_ops > pick_ops:
                tier = TIER_SOFTEN[tier]

            pick_oppops = away_oppops if pick == away else home_oppops
            opp_oppops = home_oppops if pick == away else away_oppops
            pick_whip = away_whip if pick == away else home_whip
            opp_whip = home_whip if pick == away else away_whip

            if pick_oppops is not None and opp_oppops is not None:
                if pick_oppops > opp_oppops:  # higher OPS-against = worse pitcher
                    tier = TIER_SOFTEN[tier]
            elif pick_whip is not None and opp_whip is not None:
                if pick_whip > opp_whip:
                    tier = TIER_SOFTEN[tier]

            game["pick"], game["confidence"] = pick, tier

            veto_reason = None
            if away_oppops is not None and home_oppops is not None:
                if abs(away_oppops - home_oppops) <= 0.060:
                    veto_reason = "opsa-close"
                elif pick_oppops > opp_oppops:
                    veto_reason = "opsa-veto"
            elif away_whip is not None and home_whip is not None:
                if abs(away_whip - home_whip) <= 0.20:
                    veto_reason = "whip-close"
                elif pick_whip > opp_whip:
                    veto_reason = "whip-veto"

            if veto_reason:
                game["pick"], game["confidence"] = None, "skip"
                game["skipped"], game["skipReason"] = True, veto_reason

    # ---- Second Opinion ----
    away_total = home_total = 0
    reasons = []
    if away_rd is not None and home_rd is not None and abs(away_rd - home_rd) >= 15:
        favored = away if away_rd > home_rd else home
        away_total += 1 if favored == away else 0
        home_total += 1 if favored == home else 0
        reasons.append(f"Scoring margin: {away} {away_rd:+.0f} vs {home} {home_rd:+.0f} run diff favors {favored}")

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

    return game


def build_slate(session, cfg, research_slate_fn):
    espn_games = fetch_games(session, cfg)
    if not espn_games:
        return None

    from lib.dates import today_et_str, weekday_et
    date_str = today_et_str()
    system_prompt = build_system_prompt(cfg)
    user_prompt = build_user_prompt(date_str, weekday_et(date_str), espn_games, cfg)
    research = research_slate_fn(system_prompt, user_prompt)

    league_ops = research.get("leagueOPS", {}) or {}
    pct = ops_percentiles(league_ops)
    research_games = research.get("games", []) or []

    return [
        build_game(eg, match_research_game(research_games, eg["away"], eg["home"], eg["time"]), pct, league_ops)
        for eg in espn_games
    ]
