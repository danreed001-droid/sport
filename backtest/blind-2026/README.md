# Blind test, 2026 season (NFL Weeks 5-10 window)

A test of research-driven ("Third Opinion") picks without hindsight, run on
2026-11-23 in a fresh session that had no knowledge of the 2026 results (the
season is after the model's training data).

Scope: every game with a line on our NFL, CFB, NBA and NCAAB slates from
2026-10-06 to 2026-11-16, taken in NFL weeks (Tue-Mon), Week 5 to Week 10.

## Rules

1. **Date order.** One week at a time. A week's results aren't read until
   every pick for that week is locked.
2. **Blinded inputs.** `scripts/blind_test.py prep WEEK` writes each slate as
   teams, start time and lines only (`weekN/slates/`). The research agents read
   only those files, `LESSONS.md` and pre-game web sources
   (`AGENT_PROMPT.md`).
3. **Lock first.** Each agent writes its picks to `weekN/picks/`. The week's
   picks are committed and pushed before `blind_test.py grade WEEK` reads any
   score. The commit times are the record.
4. **Contamination is reported, not hidden.** If an agent's web research shows
   it a game's result, it still locks a pick but flags it; those picks are
   graded but kept out of the clean record.
5. **Lessons carry forward.** After each week is graded, the misses are
   reviewed and repeated lessons go into `LESSONS.md` for the next week, as
   they would in real time.

Grading: ATS at the slate's stored spread and odds (-110 if none), $100 flat;
straight up at the stored moneyline (none when the pick gets 10+ points).
Results: `RESULTS.md`.

Limits: the picks use the line stored on our slate, not a line the agent found
that morning; web search can still surface a result (that's what the
contamination flag is for); stats pages that update after games can leak
later numbers into "pre-game" research.
