"""NBA Ledger + Second Opinion model — NEW, no prior Diamond Ledger skill
to port. Built by direct analogy to the NFL model, approved by the user:
PD/g stays the non-overridable pick-direction determinant; offensive rating
takes YPP's role (an efficiency stat used for the off-gap screen and one
softening step); net rating plus a starred-player-out flag takes QB rating's
role (a second softening step and a veto screen). All thresholds below are
TENTATIVE, carried over from the NFL version's numbers as a starting point
since NBA has no backtested calibration yet — flag to the user for
confirmation once real slates run, same as the CFB skill's own tentative
constants.
"""
from datetime import datetime

from lib import espn
from lib.dates import ET

TIER_SOFTEN = {"solid": "solid", "lean": "toss-up", "toss-up": "toss-up"}

CATEGORY_LABELS = {
    "rest": "Rest/Back-to-back", "travel": "Travel", "injuries": "Injuries/Lineup", "form": "Form",
    "motivation": "Motivation/Spot", "venue": "Venue/Crowd", "market": "Market",
    "matchup": "Matchup splits",
}

# TENTATIVE: net-rating veto threshold, carried over unscaled from the NFL
# QB-rating threshold (5.0) as a starting point pending real calibration.
NET_RATING_VETO_THRESHOLD = 5.0

SYSTEM_PROMPT = """You are a research assistant for an NBA prediction pipeline called Diamond Ledger.
For each matchup you are given, research and return ONLY the fields requested. You are not asked to \
decide who to bet on or how confident to be — a separate deterministic program applies all scoring \
and threshold logic afterwards using the facts you provide.

Rules:
- Use web search to find current, real information. Never fabricate a stat, injury, or odds number.
- If you cannot find a number after searching, use null for it — do not estimate or guess.
- Season point differential per game and moneylines are already known (given to you below as
  "known") — do not re-derive or override them; only fill in a moneyline yourself if it says null.
- Team offensive rating (points scored per 100 possessions) and net rating (offensive minus defensive
  rating) are season stats for both teams. Report each team's single best/most impactful player and
  whether that player is confirmed OUT tonight (injury report, not just questionable).
- The point spread (awaySpread/homeSpread, signed from each side) and each side's spread odds must be
  a real two-sided sportsbook line captured now, pregame — not a favorite-plus-price summary.
- The 8 Second-Opinion categories (rest/back-to-back, travel, injuries, form, motivation, venue/crowd,
  market, matchup) each need a verdict: which team a single concrete, checkable fact favors ("away",
  "home", or "neutral" if you can't verify one). Do not use offensive/net rating in these 8 categories
  — those are reserved for a separate model. "Rest" should specifically check whether either team is
  on the second night of a back-to-back or has a schedule/rest advantage.
- For each team's most recent completed game: report the final margin (positive if it won, negative if
  it lost), whether that team was playing the second night of a back-to-back, and if it was a win by
  20+ points, whether that team is now favored by 5+ points tonight (a sign the market may be
  overreacting to a blowout).

Return your findings as a single JSON object and nothing else — no prose, no markdown code fences,
just the raw JSON, matching the shape given in the user message."""

_SCHEMA_HINT = """Return JSON shaped exactly like this (one entry per game in "games", using the exact
away/home team names given to you):
{
  "leagueOffRating": {"Boston Celtics": 118.5, "...": 0.0},
  "games": [
    {
      "away": "...", "home": "...",
      "awayNetRating": 0.0, "homeNetRating": null,
      "awayStarPlayer": "...", "homeStarPlayer": "...",
      "awayStarOut": false, "homeStarOut": false,
      "awayMoneyline": null, "homeMoneyline": null,
      "awaySpread": -3.5, "homeSpread": 3.5,
      "awaySpreadOdds": -110, "homeSpreadOdds": -110,
      "categoryVotes": {
        "rest": {"favors": "away|home|neutral", "reason": "..."},
        "travel": {"favors": "...", "reason": "..."},
        "injuries": {"favors": "...", "reason": "..."},
        "form": {"favors": "...", "reason": "..."},
        "motivation": {"favors": "...", "reason": "..."},
        "venue": {"favors": "...", "reason": "..."},
        "market": {"favors": "...", "reason": "..."},
        "matchup": {"favors": "...", "reason": "..."}
      },
      "recentGame": {
        "away": {"margin": 0, "backToBack": false, "blowoutWin20Plus": false, "favoredBy5PlusTonight": false},
        "home": {"margin": 0, "backToBack": false, "blowoutWin20Plus": false, "favoredBy5PlusTonight": false}
      }
    }
  ]
}"""


def build_system_prompt(cfg):
    return SYSTEM_PROMPT


def build_user_prompt(date_str, weekday, matchups, cfg):
    lines = [f"Today is {weekday}, {date_str} (US Eastern). Research these NBA games:", ""]
    for m in matchups:
        lines.append(
            f"- {m['away']} @ {m['home']} ({m['time']}) — known PD/g: away "
            f"{m.get('awayPDpg')}, home {m.get('homePDpg')}; known moneyline: away "
            f"{m.get('awayMoneyline')}, home {m.get('homeMoneyline')}; season record: away "
            f"{m.get('awayRecord')}, home {m.get('homeRecord')}"
        )
    lines.append("")
    lines.append("Also research offensive rating this season for every NBA team that has played a game.")
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

        away_ml, home_ml = espn.fetch_event_odds_from_scoreboard(comp)
        tip = ev.get("date")
        tip_et = "TBD"
        if tip:
            dt = datetime.fromisoformat(tip.replace("Z", "+00:00")).astimezone(ET)
            tip_et = dt.strftime("%-I:%M %p ET")

        away_std, home_std = standings.get(away_team), standings.get(home_team)
        games.append({
            "away": away_team, "home": home_team, "time": tip_et,
            "espnGameId": str(ev.get("id")),
            "awayPDpg": espn.pd_per_game(away_std), "homePDpg": espn.pd_per_game(home_std),
            "awayMoneyline": away_ml, "homeMoneyline": home_ml,
            "awayRecord": f"{away_std.get('wins')}-{away_std.get('losses')}" if away_std else None,
            "homeRecord": f"{home_std.get('wins')}-{home_std.get('losses')}" if home_std else None,
        })
    return games


def tier_from_gap(gap):
    if gap < 3:
        return "toss-up"
    if gap <= 7:
        return "lean"
    return "solid"


def offense_percentiles(league_off_rating):
    teams = [(t, v) for t, v in league_off_rating.items() if isinstance(v, (int, float))]
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


def apply_rest_blowout_check(recent, away, home):
    """Simplified NBA analogue of the NFL trend/blowout checks: back-to-back
    fatigue (-2 to the tired team, i.e. +2 to its opponent) and blowout-win
    regression (+2 to the opponent when the market has already bought in).
    TENTATIVE — unlike the NFL/CFB checks, this has no backtesting yet."""
    away_swing = home_swing = 0
    notes = []
    for team_name, opp_name, side in ((away, home, "away"), (home, away, "home")):
        r = (recent or {}).get(side) or {}
        if not r:
            notes.append(f"{team_name}: no recent-game data")
            continue
        if r.get("backToBack"):
            if opp_name == away:
                away_swing += 2
            else:
                home_swing += 2
            notes.append(f"{team_name} on a back-to-back → +2 {opp_name}")
        if r.get("blowoutWin20Plus") and r.get("favoredBy5PlusTonight"):
            if opp_name == away:
                away_swing += 2
            else:
                home_swing += 2
            notes.append(f"{team_name} off a 20+ pt win, now favored by 5+ → regression flag, +2 {opp_name}")
        if not r.get("backToBack") and not (r.get("blowoutWin20Plus") and r.get("favoredBy5PlusTonight")):
            notes.append(f"{team_name}: no flag")
    return away_swing, home_swing, "; ".join(notes) if notes else "no data"


def build_game(espn_game, research_game, pct, league_off_rating):
    away, home = espn_game["away"], espn_game["home"]
    away_pdpg, home_pdpg = espn_game["awayPDpg"], espn_game["homePDpg"]
    away_off, home_off = league_off_rating.get(away), league_off_rating.get(home)
    away_pct, home_pct = pct.get(away), pct.get(home)
    away_net = research_game.get("awayNetRating")
    home_net = research_game.get("homeNetRating")
    away_star_out = bool(research_game.get("awayStarOut"))
    home_star_out = bool(research_game.get("homeStarOut"))
    away_ml = espn_game.get("awayMoneyline") or research_game.get("awayMoneyline")
    home_ml = espn_game.get("homeMoneyline") or research_game.get("homeMoneyline")

    game = {
        "away": away, "home": home, "time": espn_game["time"], "espnGameId": espn_game.get("espnGameId"),
        "awayStarPlayer": research_game.get("awayStarPlayer"), "homeStarPlayer": research_game.get("homeStarPlayer"),
        "awayStarOut": away_star_out, "homeStarOut": home_star_out,
        "awayPDpg": away_pdpg, "homePDpg": home_pdpg,
        "awayOffRating": away_off, "homeOffRating": home_off, "offGap": None,
        "awayNetRating": away_net, "homeNetRating": home_net,
        "awayMoneyline": away_ml, "homeMoneyline": home_ml,
        "awaySpread": research_game.get("awaySpread"), "homeSpread": research_game.get("homeSpread"),
        "awaySpreadOdds": research_game.get("awaySpreadOdds"), "homeSpreadOdds": research_game.get("homeSpreadOdds"),
        "statLines": [], "pick": None, "confidence": None, "skipped": False,
        "altPick": None, "altConfidence": None, "altCategoryTally": None, "altReasons": [],
        "altRestBlowoutCheck": None, "altRestBlowoutFavors": None,
        "awayScore": None, "homeScore": None, "correct": None, "pickReturn": None,
        "altCorrect": None, "altReturn": None, "pickCover": None, "pickSpreadReturn": None,
        "altCover": None, "altSpreadReturn": None,
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

            pick_off = away_off if pick == away else home_off
            opp_off = home_off if pick == away else away_off
            if pick_off is not None and opp_off is not None and opp_off > pick_off:
                tier = TIER_SOFTEN[tier]

            pick_net = away_net if pick == away else home_net
            opp_net = home_net if pick == away else away_net
            if pick_net is not None and opp_net is not None and pick_net < opp_net:
                tier = TIER_SOFTEN[tier]

            game["pick"], game["confidence"] = pick, tier

            veto_reason = None
            pick_star_out = away_star_out if pick == away else home_star_out
            opp_star_out = home_star_out if pick == away else away_star_out
            if pick_net is not None and opp_net is not None:
                diff = away_net - home_net
                if abs(diff) <= NET_RATING_VETO_THRESHOLD:
                    veto_reason = "rating-close"
                elif (pick == away and diff < 0) or (pick == home and diff > 0):
                    veto_reason = "rating-veto"
            if not veto_reason and pick_star_out and not opp_star_out:
                veto_reason = "star-out"

            if veto_reason:
                game["pick"], game["confidence"] = None, "skip"
                game["skipped"], game["skipReason"] = True, veto_reason

    stat_lines = []
    if away_pdpg is not None and home_pdpg is not None:
        stat_lines.append(f"PD/g {away_pdpg:+.2f} vs {home_pdpg:+.2f}")
    if away_off is not None and home_off is not None and game["offGap"] is not None:
        stat_lines.append(f"Off rtg {away_off:.1f} vs {home_off:.1f} · {game['offGap']:.0f}-pt gap")
    if away_net is not None and home_net is not None:
        stat_lines.append(f"Net rtg {away_net:+.1f} vs {home_net:+.1f}")
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

    r_away, r_home, rest_note = apply_rest_blowout_check(research_game.get("recentGame", {}) or {}, away, home)
    away_total += r_away
    home_total += r_home
    rest_favors = away if r_away > r_home else home if r_home > r_away else None

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
    game["altRestBlowoutCheck"] = rest_note
    game["altRestBlowoutFavors"] = rest_favors

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

    league_off = research.get("leagueOffRating", {}) or {}
    pct = offense_percentiles(league_off)
    research_games = research.get("games", []) or []

    return [
        build_game(eg, match_research_game(research_games, eg["away"], eg["home"]), pct, league_off)
        for eg in espn_games
    ]
