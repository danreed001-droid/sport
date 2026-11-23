# Blind test — instructions for the weekly lessons review

A week of Third Opinion picks has been locked and graded. Your job: find what
the research got wrong (or right) and update `backtest/blind-2026/LESSONS.md`,
which the next week's research agents read before picking.

Read only:
- `backtest/blind-2026/week<N>/graded.json` (each game: line, pick, confidence,
  projected margin, reasoning, final score, cover) and the same week's
  `picks/*.json` (the full research bullets);
- the current `LESSONS.md`, if any;
- web recaps of **this week's** games if you need to know what decided a game
  (one or two searches per game at most, only for the misses worth explaining).

Do not open other weeks' slates or anything under `data/`, and don't search for
games after this week: the next week hasn't been picked yet.

Write `backtest/blind-2026/week<N>/REVIEW.md`:
- the week's record by sport and confidence (from graded.json);
- for each miss by 7+ points against the line, and each strong pick that lost,
  one line: which research bullet misled, what decided the game;
- patterns: where the projected margins were biased (favorites vs underdogs,
  home vs road, totals of the projection vs the line), what kinds of [angle]
  helped or hurt.

Then rewrite `LESSONS.md` (cumulative, keep it under ~25 bullets, grouped by
sport where it matters). A lesson goes in only if it shows up in 2+ games
(across all weeks so far) or is a clear process error (e.g. used a stale line,
misread an injury status). Each lesson: one line, what to do differently, and
the evidence count (e.g. "3 of 4 big road favorites failed to cover, Wk5-6").
Drop or soften earlier lessons the new week contradicts. Lessons are about how
to research and weigh evidence; never name a future game.

Reply with only: the week's record line and the lessons you added or changed.
