"""The one place this pipeline calls Claude.

Everything deterministic — schedule, final scores/status, season point
differential, moneylines — comes from ESPN (see espn.py) via plain code.
This module's only job is the part that genuinely needs research and
judgment: QB identities/ratings, team YPP, the betting spread, and the
Second Opinion's qualitative category verdicts plus the raw facts for the
prior-game trend check and blowout-win regression check. All scoring math,
tiering, and thresholds are applied afterwards by plain code in
generate_slate.py — Claude supplies facts and per-category leanings, not
picks or confidence labels.
"""
import json
import re

import anthropic

MODEL = "claude-opus-5"

SYSTEM_PROMPT = """You are a research assistant for a {sport_label} prediction pipeline called Diamond Ledger.
For each matchup you are given, research and return ONLY the fields requested. You are not asked to \
decide who to bet on or how confident to be — a separate deterministic program applies all scoring \
and threshold logic afterwards using the facts you provide.

Rules:
- Use web search to find current, real information. Never fabricate a stat, injury, or odds number.
- If you cannot find a number after searching, use null for it — do not estimate or guess.
- Prefer cbssports.com as the tiebreaker source when two mainstream sources disagree on a fact that
  would change a judgment call (who's starting, injury status, a stat crossing a threshold).
- QB passer rating: a QB with fewer than 2 starts this season blends 0.5 x this-season rating + 0.5 x
  last-season rating; a QB with 0 starts this season uses last season's rating alone (not a blend
  against nothing); a QB with no prior competitive history at all gets null. The rating scale for this
  sport is: {qb_rating_note}.
- Season point differential per game and moneylines are already known (given to you below as
  "known") — do not re-derive or override them; only fill in a moneyline yourself if it says null.
- The point spread (awaySpread/homeSpread, signed from each side, e.g. -3.5 / +3.5) and each side's
  spread odds must be a real two-sided sportsbook line captured now, pregame — not a
  favorite-plus-price summary.
- The 8 Second-Opinion categories (rest, travel, injuries, form, motivation, weather, market, matchup)
  each need a verdict: which team a single concrete, checkable fact favors ("away", "home", or
  "neutral" if you can't verify one). Do not use YPP or QB rating in these 8 categories — those are
  reserved for a separate model.
- Prior-game trend check: for EACH team's most recently completed game this season (its own prior
  game, not tonight's opponent's game), report from the CBS Sports Gametracker box score: total net
  yards, passing yards, passing attempts, rushing attempts, and that team's margin in that game
  (positive if it won, negative if it lost, by how many points). If it's a team's Week 1 game this
  season (no prior game), set trendAvailable to false for that team and skip the rest of its object.
- Blowout-win regression check: only for a team whose most recent game was a win by 17 or more points.
  Report the raw facts: takeaway margin in that win, whether the game was tied or within one score
  (<=8) at halftime before that team pulled away, that team's rushing attempts in the win, whether
  that team is now favored by 3+ points in tonight's game, whether tonight's OPPONENT ranks top-10 in
  takeaways forced OR top-5 in points allowed OR top-5 in pass defense, and whether that team's
  QB/primary ball-carriers have a turnover-trouble history this season (true/false + a one-line
  reason). If the team's last game was not a win of 17+ points, set blowoutApplicable to false and
  skip the rest of its object.

Return your findings as a single JSON object and nothing else — no prose, no markdown code fences,
just the raw JSON, matching the shape given in the user message."""

_SCHEMA_HINT = """Return JSON shaped exactly like this (one entry per game in "games", using the exact
away/home team names given to you):
{
  "leagueYPP": {"Buffalo Bills": 6.1, "...": 0.0},
  "games": [
    {
      "away": "...", "home": "...",
      "awayQB": "...", "homeQB": "...",
      "awayQBRating": 0.0, "homeQBRating": null,
      "awayMoneyline": null, "homeMoneyline": null,
      "awaySpread": -3.5, "homeSpread": 3.5,
      "awaySpreadOdds": -110, "homeSpreadOdds": -110,
      "categoryVotes": {
        "rest": {"favors": "away|home|neutral", "reason": "..."},
        "travel": {"favors": "...", "reason": "..."},
        "injuries": {"favors": "...", "reason": "..."},
        "form": {"favors": "...", "reason": "..."},
        "motivation": {"favors": "...", "reason": "..."},
        "weather": {"favors": "...", "reason": "..."},
        "market": {"favors": "...", "reason": "..."},
        "matchup": {"favors": "...", "reason": "..."}
      },
      "trendCheck": {
        "away": {"trendAvailable": true, "summary": "Wk3 vs X, W 24-17", "totalYards": 0, "passYards": 0, "passAttempts": 0, "rushAttempts": 0, "margin": 0},
        "home": {"trendAvailable": true, "summary": "...", "totalYards": 0, "passYards": 0, "passAttempts": 0, "rushAttempts": 0, "margin": 0}
      },
      "blowoutCheck": {
        "away": {"blowoutApplicable": false},
        "home": {
          "blowoutApplicable": true, "opponentLabel": "away",
          "takeawayMargin": 2, "closeAtHalf": false, "rushAttempts": 35,
          "favoredBy3Plus": true, "oppTopTakeaways": false, "oppTopPointsAllowed": true,
          "oppTopPassDefense": false, "turnoverProne": true, "turnoverProneReason": "..."
        }
      }
    }
  ]
}
"opponentLabel" names which side (away/home) is tonight's opponent — the one that would receive
the blowout-check point swing if it fires."""


def _build_user_prompt(date_str, weekday, matchups, sport_label):
    lines = [f"Today is {weekday}, {date_str} (US Eastern). Research these {sport_label} games:", ""]
    for m in matchups:
        lines.append(
            f"- {m['away']} @ {m['home']} ({m['time']}) — known PD/g: away "
            f"{m.get('awayPDpg')}, home {m.get('homePDpg')}; known moneyline: away "
            f"{m.get('awayMoneyline')}, home {m.get('homeMoneyline')}; season record: away "
            f"{m.get('awayRecord')}, home {m.get('homeRecord')}"
        )
    lines.append("")
    lines.append(
        f"Also research offensive yards per play (YPP) this season for every {sport_label} team "
        "that has played a game so far (needed to rank them all by offense)."
    )
    lines.append("")
    lines.append(_SCHEMA_HINT)
    return "\n".join(lines)


def _extract_json(text):
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n", "", text)
        text = re.sub(r"\n```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("No JSON object found in Claude's response:\n" + text[:2000])
    return json.loads(text[start:end + 1])


def research_slate(date_str, weekday, matchups, sport_cfg):
    """Call Claude once (with the web_search server tool) to research every
    game on today's slate. Returns the parsed JSON dict described above."""
    client = anthropic.Anthropic()
    system_prompt = SYSTEM_PROMPT.format(qb_rating_note=sport_cfg["qb_rating_note"], sport_label=sport_cfg["label"])
    user_prompt = _build_user_prompt(date_str, weekday, matchups, sport_cfg["label"])

    with client.beta.messages.stream(
        model=MODEL,
        max_tokens=32000,
        system=system_prompt,
        thinking={"type": "adaptive"},
        output_config={"effort": "high"},
        tools=[{"type": "web_search_20260209", "name": "web_search", "max_uses": 40}],
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        messages=[{"role": "user", "content": user_prompt}],
    ) as stream:
        response = stream.get_final_message()

    if getattr(response, "stop_reason", None) == "refusal":
        raise RuntimeError(f"Claude refused the research request: {response.stop_details}")

    text_parts = [block.text for block in response.content if getattr(block, "type", None) == "text"]
    full_text = "\n".join(text_parts)
    return _extract_json(full_text)
