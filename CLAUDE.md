# Diamond Ledger — repo notes for Claude

`main` is the default branch and the only long-lived one. Work on a branch and
merge into `main`; the scoring, pick-intake and Pages workflows all run from it.

## How data flows

- **Picks:** the daily Diamond Ledger Routines (NFL, CFB, MLB, NBA/NCAAB,
  soccer) research each day's games and write the slate to the ledger
  database only. They don't push to git.
- **Into the repo:** the hourly "Diamond Ledger — sync to GitHub" Routine runs
  `scripts/sync_ledger.py` on an export of the database and commits new or
  changed slates in `data/<sport>/` to `main`. Mirror the database exactly;
  never generate a second, different slate for a date that already has one.
- **Research check (final say):** the "Diamond Ledger — research check"
  Routine runs at 11:40 AM ET. It fact-checks that day's slates in the database,
  fixes a wrong fact that changes a pick (or removes a moved game) for games
  that haven't started, and marks each change with `auditNote`/`auditChanges`.
  Its findings for a sport go in that doc's `auditReport` field (a Markdown
  section); `sync_ledger.py` keeps the field out of the slate file and joins
  the sections into `data/audits/<date>.md`.
  Nothing else changes a pick after it's generated.
- **Grading:** `.github/workflows/diamond-ledger.yml` grades NFL, CFB, MLB,
  NBA, NCAAB and soccer every hour from ESPN (`fetch_scores.py` then
  `score_slate.py`), after patching on the NBA Stats and NFL Stats picks. The
  sport Routines no longer grade. Soccer uses ESPN's combined soccer feed and
  grades the 3-way moneyline; matches decided in extra time or on penalties
  get no result.

## Keeping it running unattended

- The scoring workflow runs hourly (GitHub starts scheduled runs late and
  sometimes skips them; every run is idempotent). Its steps fail
  independently, whatever succeeded is still committed, and the run is then
  marked failed. ESPN requests retry transient errors (`lib/espn.py`).
- Score redundancy, so one bad feed can't hold a slate ungraded: each
  scoreboard date is read at two page sizes and merged (ESPN's CFB board
  dropped to 25 games at `limit=1000` on 2026-10-31); then any game on an
  unscored past slate whose archived row still isn't final is looked up on its
  own ESPN game page (`refresh_unfinished_slate_games` in `fetch_scores.py`).
  If a slate is still ungraded at noon ET the next day, the health check
  starts a scoring run and opens its issue naming the games, for entry by hand.
- `data/health.json` holds each step's last status (dates only, so it changes
  about once a day: that daily bot commit keeps GitHub from switching off the
  scheduled workflows after 60 days without repo activity in the off-season).
  The pick sheet shows a warning banner when the page is 6+ hours old or a
  step is failing.
- `.github/workflows/health.yml` (every 4 hours) re-enables the scoring and
  Pages workflows, re-runs scoring if nothing has succeeded in 3+ hours,
  rebuilds the site if the live data.json is 6+ hours old, and opens a
  "Health check" issue (closed automatically on recovery) when it can't fix
  things itself.
- NBA Totals (`scripts/nba_totals_signals.py`, rules in `scripts/lib/nba_totals_rules.py`)
  runs right after NBA Stats each scoring run and flags full-game UNDERs on the
  NBA slate: rule 1, spread 3 points or less; rule 2, the road team's last
  game (within 10 days) went to OT. It writes `totalsLine` (refreshed from
  ESPN's pickcenter every run until tip-off, then frozen), `totalsFavors`,
  `totalsRules` and `totalsCheck`; `score_slate.py` grades them
  (`totalsCorrect`/`totalsReturn`, $100 at -110). Regular season only. Both
  are thin backtested edges (~54-55% unders, 2022-23 on), tracked to see if
  they hold; the pick sheet shows them as "NBA Totals".
- NBA and NFL Stats only pick regular-season games, and NBA Stats only reads
  the current season's games from the growing scores archive.
- `curl_cffi` is pinned in `requirements.txt`; bump it deliberately.
- NCAA basketball: when no Routine has written the day's slate,
  `scripts/auto_slate.py ncaab` (every scoring run) builds it from ESPN's
  default scoreboard -- the games involving an AP Top 25 team, the Basketball
  Routine's scope and the feed the grader reads -- with lines from ESPN's
  pickcenter, marked autoSlate so a Routine's slate still replaces it.
  `archive_lines.py` keeps NCAAB opening/closing lines too.
- NCAAB Stats (`scripts/ncaab_stats_signals.py`, rules in `scripts/lib/ncaab_stats_rules.py`)
  patches picks onto the NCAAB slate each run, like NBA/NFL Stats: Rule 1 backs a
  team after a loss where the opponent out-shot it from three by 25+ points of
  3P%. Each team's previous game comes from ESPN's team schedule and its box score.
- **Hand-entered data is the last resort** when a feed doesn't deliver: the
  pick sheet's "Enter data by hand" page (`site/manual.html`) opens a
  `data <sport> YYYY-MM-DD` issue; `.github/workflows/data-intake.yml` runs
  `scripts/intake_manual.py` to merge it into `data/manual/<sport>/<date>.json`
  (format in `scripts/lib/manual.py`) and starts a scoring run. Those values
  win over ESPN everywhere: `apply_manual.py` (first step of every scoring
  run) puts games and lines on the slates, building a slate when none exists,
  and re-grades edited ones; `fetch_scores.py` writes the finals into the
  scores archive; NBA/NFL Stats read the box-score facts for their rules.
  Don't edit `data/manual/` on the user's behalf unless they ask.

## The user's own picks come from the pick sheet, not from Claude

The GitHub Pages pick sheet (`site/index.html`, built by `scripts/build_site.py`,
deployed by `.github/workflows/pages.yml`) is where the user makes picks. They
pick a side and score each Second Opinion reason (A away, a half away, N
neutral, h half home, H home); a tally margin of 2.5+ sets the pick. Submitting
opens a `picks YYYY-MM-DD` issue, and `.github/workflows/pick-intake.yml` runs
`scripts/intake_picks.py` to commit them to `data/mypicks/<date>.json`.
The "My grading" page (`site/grading.html`, data from
`scripts/lib/grading_patterns.py` via `build_site.py`) shows how those
category grades have held up: for each non-neutral grade, did the graded side
win and cover, by category, full vs half grade, sport, lean size, and
favorite vs underdog. It's a record of their grading, never a pick.

Don't write picks into game objects in `data/<sport>/` (no `userPick`,
`yourPick`, `myPick` fields) and don't ask the user to tell you their picks.
Grading of their picks happens in `scripts/lib/picks.py` from the game's final
score and stored lines: ATS and moneyline at $100 flat, with NFL, CFB and NCAAB picks on a
team getting more than 7 points counted ATS only. In any sport, a pick priced
-400 or shorter is left out of the moneyline record and profit (win or lose);
this applies to the Ledger and Second Opinion too (`scripts/lib/grading.py`).
