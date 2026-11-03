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
  runs right after NBA Stats each scoring run and flags full-game totals on the
  NBA slate. Only rules that backtested at 61%+ are kept (the user's bar for
  NBA Stats and NBA Totals); rules 1-2 (54-55% unders) were retired on
  2026-11-03 and their numbers aren't reused. Rule 3 OVER (on trial), the
  home team won its last game and that game's 30-39 point scorer is out
  tonight (ESPN injury report "Out", `lib/nba_absence.py`); rules 4-8 UNDER
  after a team lost at home to a worse-record team and now faces a
  better-record one (4 lost by 1-9, 5 that and rested, 6 now on the road, 7
  that and rested, 8 road after losing by 10+); rules 9-15 UNDER (on trial)
  when the home team is back from a 20+ point road win (`ROAD_BLOWOUT`); rule
  16 OVER (on trial) after a 30+ point road loss, now vs. a worse-record team;
  rules 17-19 UNDER (on trial) when both teams are on a back-to-back (`BOTH_B2B`). An over and an under rule on
  the same game cancel out (no pick). Adding rules: bump BACKFILL_VERSION in
  `nba_totals_signals.py` and rerun `--backfill` so past games are rechecked. It writes `totalsLine` (refreshed from
  ESPN's pickcenter every run until tip-off, then frozen), `totalsFavors`,
  `totalsRules` and `totalsCheck`; `score_slate.py` grades them
  (`totalsCorrect`/`totalsReturn`, $100 at -110). Regular season only. The
  pick sheet shows them as "NBA Totals". The season's games
  before NBA Totals went live (2026-10-20 to 11-02) were backfilled with
  `nba_totals_signals.py --backfill` on the archived DraftKings closing lines
  and are marked `totalsBackfill: true`; the pick sheet says how many.
- NBA Stats rule 18 (on trial) backs a home team vs. a better-record team when
  the player who scored 30+ in its last game is listed Out tonight; it's
  checked until tip-off and then frozen (the game's existing statsRules). NBA
  Stats looks teams up by the scores archive's name, so a slate's "LA Lakers"
  still finds "Los Angeles Lakers". Rule 19 (on trial) backs a road team on a
  back-to-back after a home loss to a worse-record team (games between equal
  records excluded, as in the backtest). Rules 20-29 (on trial) fade a team
  coming off a road upset win (`ROAD_UPSET` in `nba_stats_signals.py`; the
  win's spread comes from `data/raw/nba_lines.csv`). Rules 33-34 (on trial)
  back a team after a 30+ point win (33 now home vs. a stronger team, 34 a
  road win where it wasn't a 7+ favorite); 30-32 were tried and removed.
  Rules 35-40 (on trial) play a team after a 20+ point loss (`BLOWOUT_LOSS`;
  38 fades, the rest back), one family. Rules 41-43 (on trial) back the home
  team when both teams are on a back-to-back (`BOTH_B2B`; they need tonight's
  spread, passed in as `home_spread`). `nba_stats_signals.py --backfill
  RULE ...` applies just those rules to this season's finished games (rules
  marked `"backfill": true`, a pick made only by backfill `statsBackfill:
  true`); a game already picked the other way is left alone. 38-39 were
  backfilled on 2026-11-03 (4 games).
  Overlapping slices of one situation (NBA Stats 20-29, NBA Totals 4-8 and
  9-15) are one "family": several firing
  on a game don't make it "stacked" (`families()` in the rules files, `famCount`
  in `site/index.html`).
- `.github/workflows/nba-gametime.yml` re-runs only `nba_stats_signals.py` and
  `nba_totals_signals.py` every 15 minutes, 4 PM-midnight ET, so injury-based
  rules (NBA Stats 18, NBA Totals 3) and totals lines are checked near
  tip-off; it commits `data/nba/` and pages.yml rebuilds after it. When a
  pick would fire if a listed-but-not-Out player sits (questionable,
  doubtful, day-to-day), the scripts write `statsWatch` / `totalsWatch` and
  the card shows an "Injury watch" until the game is final.
- `site/index.html` builds its text inside single-quoted JavaScript strings:
  escape apostrophes (`\'`). `scripts/check_site_js.py` syntax-checks every
  built page in pages.yml and stops the deploy on an error, so a broken page
  never replaces the live one.
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
