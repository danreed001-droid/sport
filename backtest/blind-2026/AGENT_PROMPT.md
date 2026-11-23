# Blind test — instructions for a research agent

You are making **Third Opinion** picks against the spread for games in the 2026
season, as if it were the morning of each game. This is a blind test: the games
have been played, but you must not learn or use their results. Your picks are
locked (committed to git) before anyone grades them.

## What you may read

- Your input slate file(s) under `backtest/blind-2026/week<N>/slates/` (named in
  your task). Each game has teams, start time and the line you are picking
  against. Use that line; don't hunt for a different one (you may mention line
  movement you find in pre-game sources).
- `backtest/blind-2026/LESSONS.md`, if it exists: lessons from earlier graded
  weeks. Apply them.
- The web, under the blindness rules below.

Do **not** open anything else in the repository (especially `data/`, `site/`,
`_site/`, other weeks' folders or any `graded.json`), and do not run git.

## Blindness rules (the point of the test)

- The simulated "now" is the morning of each game's date (ET). Use only
  information published **before that game started**: previews, injury
  reports, odds pages, stats through the previous game.
- Write searches as a pre-game researcher would: "<team> vs <team> preview",
  "<team> injury report <date>", "<team> ATS record 2026", "<team> odds week 5".
  Never search for "score", "final", "recap", "result", "highlights", "who won",
  or the game's outcome, and don't open pages dated after the game.
- Search-result summaries leak results easily (in Week 5 a plain "<team>
  injury report" search summarized the final score). Every query should name
  the game's date or week AND a pre-game word: "preview", "prediction",
  "odds", "picks", "betting", "injury report ahead of". Don't search a player's
  status on its own; get injuries from preview articles. When a result page
  looks like a recap, don't open it. Prefer fetching pre-game preview/odds
  articles directly over reading search summaries. What worked in Week 5:
  narrow preview queries limited to one site (e.g. nbcsports.com, si.com,
  cbssports.com, covers.com), then WebFetch of the preview article with a
  prompt that asks for pre-game content only. Also: pass WebSearch
  `allowed_domains` limited to betting-preview sites (covers.com,
  wagertalk.com, predictem.com, dimers.com, sportsgambler.com,
  actionnetwork.com, oddsshark.com, pickswise.com) or block
  wikipedia.org / espn.com with `blocked_domains`; Wikipedia season pages and
  post-game headlines were the main leaks. Don't include cbssports.com,
  nbcsports.com or espn.com in injury searches: their result headlines leaked
  in Weeks 5-6.
- Stats pages update after every game. Prefer sources dated before the game
  (previews quote the stats). If a page clearly includes this game, don't use
  its numbers.
- If you see this game's result anyway (a snippet, a headline, a later page),
  you still lock a pick, but set `"contaminated": true` and say in
  `contaminationNote` exactly what you saw and whether you'd seen it before you
  decided. Be honest. A contaminated pick is graded separately; hiding one
  ruins the test. Seeing results of *earlier* games (before this game's date)
  is fine: that was knowable at the time.

- **Hard rule from Weeks 5-6: every WebSearch call must pass
  `allowed_domains` set to betting-preview sites only** (covers.com,
  wagertalk.com, predictem.com, dimers.com, sportsgambler.com,
  actionnetwork.com, oddsshark.com, pickswise.com, sportsbookreview.com,
  oddstrader.com, rotowire.com betting pages). Searches limited to those stayed
  clean; searches of team sites, newspapers, si.com, cbssports.com or with no
  domain limit leaked results. Only WebFetch pages from those sites (or a
  preview URL they link to that is clearly dated before the game).

## The method (Third Opinion)

The question is not "who wins?" but **"who covers the spread?"** For every game,
dig into the news around that specific game and write **at least 10 bullet
points** of concrete, checkable findings, then make your own call.

Be a creative reporter, not a checklist. Find the story of this game: injuries
and who's questionable (and how the team has played without them), QB or
starter changes, rest and schedule (short week, bye, back-to-back, end of a road
trip, travel, altitude), coaching changes, a player facing his former team,
rivalry or revenge, motivation and stakes (rankings, conference race, playoff or
NBA Cup stakes, tanking), weather for outdoor football, locker-room news, and
matchup problems the stats hide.

- Each bullet is one specific fact with its source (outlet + date), says which
  side of the spread it helps, and the bullets cover BOTH teams.
- At least 3 bullets are game-specific or unusual findings a stats model would
  miss, tagged `[angle]`.
- At least 3 bullets are spread-specific: ATS records this season (overall,
  home/road, as favorite/underdog), line movement since the open, betting
  splits / sharp vs public money, point differential or efficiency, margin
  tendencies (blowouts vs close games, backdoor covers).
- Never fabricate. If fewer than 10 solid bullets exist, say so and lower
  confidence. Keep quotes short.

Weighing the evidence (from graded picks in this project):
- This season's repeated performance data and the market beat narratives and
  old history. Angles decide close calls; they don't override the numbers.
- This season's matchup stats beat head-to-head history.
- A line move on injury or rest news is information, not an overreaction.
- A big underdog covers only if it can score with this lineup; check its recent
  offense.
- Check betting splits to tell sharp from public money; don't fade sharp money
  without a strong, data-backed reason.
- A team's own repeated ATS situation this season outweighs a one-off injury
  storyline about the opponent.
- Research both sides of the key matchup, not just one.
- Plus everything in `LESSONS.md`.

Then decide. Estimate the final margin as `projectedMargin` = home score minus
away score (+4.5 = home wins by 4.5, -4.5 = away wins by 4.5). The home team
covers if `projectedMargin + homeSpread > 0`. Compare and pick the side that
covers. `pick` = exact team name (as in the slate) expected to COVER, or null for
a pass. `confidence` = "strong" | "lean" | "pass": pass when the projection is
within about 2 points of the spread, the evidence is balanced, or a key player's
late status decides it; "strong" only when the projection clears the spread by
roughly 5+ and several independent findings agree.

Also record `forcedSide` for every game, passes included: the team you'd take
if you had to bet this game. It is graded as a separate record (it never
replaces `pick`). For a contaminated game, give the side your pre-leak
reasoning pointed to.

Also, some betting sites leak results too (Weeks 5-6): Covers picks shown
with ✅/❌ or "went 0-1", Dimers scoreboards and /predictions/ matchup pages,
Pickswise game pages showing finals, Predictem results lists. Ignore any
graded pick, scoreboard or results list; don't open those pages.

Budget: aim for about 4-8 searches per game. Depth on the deciding questions
beats breadth.

## Output (this is the lock)

Write **one JSON file per input slate file**, same file name, into the week's
`picks/` folder (e.g. `slates/nfl-2026-10-11-1.json` -> `picks/nfl-2026-10-11-1.json`),
with the Write tool:

```json
{
  "sport": "nfl", "date": "2026-10-11", "chunk": "nfl-2026-10-11-1",
  "games": [
    {
      "away": "...", "home": "...",           // exactly as in the slate
      "pick": "Team Name" or null,
      "confidence": "strong" | "lean" | "pass",
      "projectedMargin": 3.5,                  // home minus away
      "research": ["...10+ bullets..."],
      "reasoning": "2-4 sentences: what decided it, the most surprising [angle], what would have changed it",
      "forcedSide": "Team Name",               // ALWAYS a team, even on a pass: the side you'd take if you had to bet
      "contaminated": false,
      "contaminationNote": null
    }
  ]
}
```

Every game in the slate file must be in your output. Then reply with only a
short table: game, line, pick, confidence, projected margin, contaminated.
Don't paste the research into your reply.
