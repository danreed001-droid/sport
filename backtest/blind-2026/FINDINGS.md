# Blind test, 2026 Weeks 5-10 — findings

Run 2026-11-23. 487 games with a line (NFL 86, CFB 108, NBA 204, NCAAB 89),
picked week by week, every week's picks committed before its scores were read.
Numbers: `RESULTS.md`; weekly reviews: `week*/REVIEW.md`; lessons: `LESSONS.md`.

## Record

- **Picks (official):** 16-18-1 ATS, -$348 at $100 flat (clean, no result
  seen: 11-14-1, -$416). Only 35 picks in 487 games; 452 passes.
- **Forced side** (the side the research leaned to on every game, passes
  included): **172-196-3 clean (46.7%)**, 211-234-3 all. Break-even at -110 is
  52.4%. Against 50% that's within chance (p ≈ 0.2); it is clearly not an edge.
  By sport, clean: NFL 34-30-2, CFB 35-44-1, NBA 75-82, NCAAB 28-40.
- Every weekly review looked for a split that beat 52.4% on a fair sample
  (favorite/underdog, home/road, line size, line moves, slate vs close, big
  college underdogs). Nothing held up across weeks; the few hot splits (NFL road
  teams 29-12 over Weeks 5-7) reversed the next week.

## What the test showed about the method

1. **Research-driven projections didn't beat the closing line.** Their average
   miss was about the same as the line's (10.6 vs 10.6 points, Weeks 5-7), and
   bigger projected edges did no better than small ones.
2. **The lessons loop converged on "pass".** Picks fell from 22 of 34 games in
   Week 5 to 0 of 125 in Week 10 as each review found the edges were noise.
   That is the honest result of the loop, not a bug.
3. **The one steady habit was a lean toward underdogs** (59% of forced sides),
   which didn't pay (forced underdogs 62-82 through Week 9).

## How blind it was

- 103 of 487 games are flagged "contaminated": the agent saw the result before
  locking. Almost all leaks came from WebSearch result summaries (later
  previews recapping the game, betting sites grading their own picks), even
  with searches limited to betting sites. Contaminated games are kept out of
  the clean record, and from Week 7 on they were locked as passes.
- Week 10 used no WebSearch at all (preview URLs built or taken from site
  sitemaps, every page fetched behind a "result on page?" guard): 2 leaks in
  125 games, both from an agent reading a later date's previews first.
  **For any future blind test, use that setup from the start.**
- Other limits: picks were graded at our slate's stored line; the archive's
  opening line was unreliable (sign flips, lookahead numbers) and its close was
  sometimes an early snapshot; Weeks 5-6 passes' forced side is derived from
  the locked projected margin. The orchestrator once saw three Week 8 scores
  while matching team names (README); it made no picks.
