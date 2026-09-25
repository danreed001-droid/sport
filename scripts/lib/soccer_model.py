"""Soccer Ledger + Second Opinion model — EXPERIMENTAL, the most novel of
the five sports here since soccer's three-way market (home/draw/away) does
not fit the "pick one of two teams, grade vs. a spread" shape the other
sports share. Design choices made here (confirmed with the user):

- Both predictors output a genuine 3-way pick: "Home", "Away", or "Draw".
- Grading is moneyline-only against a real 3-way market (no spread/ATS —
  soccer doesn't have a standard point spread the way NFL/MLB do).
- Goal differential per game (GD/g) plays PD/g's role. Expected goals (xG)
  per match plays YPP's role. There is no clean single-position analogue to
  a starting QB, so the veto screen instead checks each team's single top
  scorer's availability, mirroring the NBA model's star-out screen.
- A near-even Second-Opinion category tally (a "pass" in every other sport)
  is read as a Draw lean here, since a genuine toss-up game is the closest
  on-field signal to a plausible draw — this is a real modeling bet, not a
  ported rule, and should be revisited once real results come in.

Defaults to the English Premier League (ESPN slug "eng.1"); swap
`espn_league` in lib/sports.py to point this at a different league.
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

# TENTATIVE thresholds — soccer goal differentials run much smaller than
# NFL point differentials, so these are scaled down, not backtested.
DRAW_GAP_THRESHOLD = 0.3
STAR_OUT_ONLY_VETO = True

SYSTEM_PROMPT = """You are a research assistant for a soccer prediction pipeline called Diamond Ledger.
For each match you are given, research and return ONLY the fields requested. You are not asked to \
decide who to bet on or how confident to be — a separate deterministic program applies all scoring \
and threshold logic afterwards using the facts you provide.

Rules:
- Use web search to find current, real information. Never fabricate a stat, injury, or odds number.
- If you cannot find a number after searching, use null for it — do not estimate or guess.
- Season goal differential per game and moneylines (3-way: home/draw/away) are already known (given
  below as "known") — do not re-derive or override them; only fill in a price yourself if it's null.
- Expected goals (xG) per match this season is a team stat. Report each team's single top scorer this
  season by name and whether they are confirmed OUT for this match (injury/suspension, not just a
  doubt).
- This is a genuine 3-way market: report awayMoneyline, drawMoneyline, and homeMoneyline (3-way odds),
  not a 2-way line.
- The 8 Second-Opinion categories (rest, travel, injuries, form, motivation, weather, market, matchup)
  each need a verdict: which side a single concrete, checkable fact favors ("away", "home", or
  "neutral"). Do not use xG or top-scorer availability in these 8 categories — those are reserved
  for a separate model.

Return your findings as a single JSON object and nothing else — no prose, no markdown code fences,
just the raw JSON, matching the shape given in the user message."""

_SCHEMA_HINT = """Return JSON shaped exactly like this (one entry per match in "matches", using the
exact away/home team names given to you):
{
  "leagueXG": {"Arsenal": 1.9, "...": 0.0},
  "matches": [
    {
      "away": "...", "home": "...",
      "awayTopScorer": "...", "homeTopScorer": "...",
      "awayTopScorerOut": false, "homeTopScorerOut": false,
      "awayMoneyline": null, "drawMoneyline": null, "homeMoneyline": null,
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
    lines = [f"Today is {weekday}, {date_str} (US Eastern). Research these {cfg['label']} matches:", ""]
    for m in matchups:
        lines.append(
            f"- {m['away']} @ {m['home']} ({m['time']}) — known GD/g: away "
            f"{m.get('awayGDpg')}, home {m.get('homeGDpg')}; known moneyline (3-way): away "
            f"{m.get('awayMoneyline')}, draw {m.get('drawMoneyline')}, home {m.get('homeMoneyline')}"
        )
    lines.append("")
    lines.append(f"Also research expected goals (xG) per match this season for every {cfg['label']} team.")
    lines.append("")
    lines.append(_SCHEMA_HINT)
    return "\n".join(lines)


def fetch_games(session, cfg):
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

        kickoff = ev.get("date")
        kickoff_et = "TBD"
        if kickoff:
            dt = datetime.fromisoformat(kickoff.replace("Z", "+00:00")).astimezone(ET)
            kickoff_et = dt.strftime("%-I:%M %p ET")

        away_std, home_std = standings.get(away_team), standings.get(home_team)
        games.append({
            "away": away_team, "home": home_team, "time": kickoff_et,
            "espnGameId": str(ev.get("id")),
            "awayGDpg": espn.pd_per_game(away_std), "homeGDpg": espn.pd_per_game(home_std),
            "awayMoneyline": None, "drawMoneyline": None, "homeMoneyline": None,
        })
    return games


def tier_from_gap(gap):
    if gap < 0.5:
        return "toss-up"
    if gap <= 1.0:
        return "lean"
    return "solid"


def xg_percentiles(league_xg):
    teams = [(t, v) for t, v in league_xg.items() if isinstance(v, (int, float))]
    teams.sort(key=lambda kv: kv[1], reverse=True)
    n = len(teams)
    return {t: (n - rank) / (n - 1) * 100 if n > 1 else 50.0 for rank, (t, _) in enumerate(teams, start=1)}


def match_research_game(research_games, away, home):
    for g in research_games:
        if g.get("away") == away and g.get("home") == home:
            return g
    for g in research_games:
        ga, gh = g.get("away", ""), g.get("home", "")
        if (away in ga or ga in away) and (home in gh or gh in home):
            return g
    return {}


def build_game(espn_game, research_game, pct, league_xg):
    away, home = espn_game["away"], espn_game["home"]
    away_gdpg, home_gdpg = espn_game["awayGDpg"], espn_game["homeGDpg"]
    away_xg, home_xg = league_xg.get(away), league_xg.get(home)
    away_pct, home_pct = pct.get(away), pct.get(home)
    away_star_out = bool(research_game.get("awayTopScorerOut"))
    home_star_out = bool(research_game.get("homeTopScorerOut"))
    away_ml = research_game.get("awayMoneyline")
    draw_ml = research_game.get("drawMoneyline")
    home_ml = research_game.get("homeMoneyline")

    game = {
        "away": away, "home": home, "time": espn_game["time"], "espnGameId": espn_game.get("espnGameId"),
        "awayTopScorer": research_game.get("awayTopScorer"), "homeTopScorer": research_game.get("homeTopScorer"),
        "awayTopScorerOut": away_star_out, "homeTopScorerOut": home_star_out,
        "awayGDpg": away_gdpg, "homeGDpg": home_gdpg,
        "awayXG": away_xg, "homeXG": home_xg, "offGap": None,
        "awayMoneyline": away_ml, "drawMoneyline": draw_ml, "homeMoneyline": home_ml,
        "statLines": [], "pick": None, "confidence": None, "skipped": False,
        "altPick": None, "altConfidence": None, "altCategoryTally": None, "altReasons": [],
        "awayScore": None, "homeScore": None, "correct": None, "pickReturn": None,
        "altCorrect": None, "altReturn": None,
    }

    # ---- Ledger ----
    if away_pct is None or home_pct is None or away_gdpg is None or home_gdpg is None:
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
            gap = abs(away_gdpg - home_gdpg)
            if gap < DRAW_GAP_THRESHOLD:
                game["pick"], game["confidence"] = "Draw", "toss-up"
            else:
                pick = away if away_gdpg >= home_gdpg else home
                tier = tier_from_gap(gap)

                pick_xg = away_xg if pick == away else home_xg
                opp_xg = home_xg if pick == away else away_xg
                if pick_xg is not None and opp_xg is not None and opp_xg > pick_xg:
                    tier = TIER_SOFTEN[tier]

                pick_star_out = away_star_out if pick == away else home_star_out
                opp_star_out = home_star_out if pick == away else away_star_out
                game["pick"], game["confidence"] = pick, tier
                if pick_star_out and not opp_star_out:
                    game["pick"], game["confidence"] = None, "skip"
                    game["skipped"], game["skipReason"] = True, "star-out"

    stat_lines = []
    if away_gdpg is not None and home_gdpg is not None:
        stat_lines.append(f"GD/g {away_gdpg:+.2f} vs {home_gdpg:+.2f}")
    if away_xg is not None and home_xg is not None and game["offGap"] is not None:
        stat_lines.append(f"xG/match {away_xg:.2f} vs {home_xg:.2f} · {game['offGap']:.0f}-pt gap")
    game["statLines"] = stat_lines[:4]

    # ---- Second Opinion ----
    away_total = home_total = 0
    reasons = []
    if away_gdpg is not None and home_gdpg is not None and away_gdpg != home_gdpg:
        favored = away if away_gdpg > home_gdpg else home
        away_total += 1 if favored == away else 0
        home_total += 1 if favored == home else 0
        reasons.append(f"Scoring margin: {away} {away_gdpg:+.2f} vs {home} {home_gdpg:+.2f} GD/g favors {favored}")

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
        alt_pick, alt_conf = "Draw", "draw-lean"
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


def assemble(espn_games, research, cfg):
    """Pure: turn ESPN's pregame facts plus a completed research JSON into
    the final graded-later game objects."""
    league_xg = research.get("leagueXG", {}) or {}
    pct = xg_percentiles(league_xg)
    research_games = research.get("matches", []) or []

    return [
        build_game(eg, match_research_game(research_games, eg["away"], eg["home"]), pct, league_xg)
        for eg in espn_games
    ]


def grade_game(g, away_score, home_score):
    """3-way moneyline-only grading — no spread/ATS for soccer."""
    result = {"correct": None, "pickReturn": None, "altCorrect": None, "altReturn": None}
    if away_score is None or home_score is None:
        return result

    if away_score > home_score:
        outcome = "away"
    elif home_score > away_score:
        outcome = "home"
    else:
        outcome = "draw"

    price_for = {"away": g.get("awayMoneyline"), "draw": g.get("drawMoneyline"), "home": g.get("homeMoneyline")}

    for pick_field, correct_field, return_field in (("pick", "correct", "pickReturn"), ("altPick", "altCorrect", "altReturn")):
        pick = g.get(pick_field)
        if pick is None:
            continue
        pick_key = pick.lower()
        correct = (pick_key == outcome)
        price = price_for.get(pick_key)
        if price is None:
            pick_return = None
        else:
            pick_return = _moneyline_payout(price) if correct else -100.0
        result[correct_field] = correct
        result[return_field] = pick_return

    return result


def _moneyline_payout(odds):
    if odds is None:
        return None
    if odds > 0:
        return float(odds)
    return round(10000 / abs(odds), 2)
