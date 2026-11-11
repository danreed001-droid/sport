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
- **Rule bar (2026-11-03):** NBA Stats and NBA Totals keep only rules at 61%+
  when every current rule is replayed on 2018-19 and 2021-22 to now (the
  2019-20 bubble and 2020-21 empty-arena seasons left out; 2018-19 and
  2021-22 were never seen by the rules found on 2022-26), and 55%+ on those two
  unseen seasons alone. Active: NBA Stats 2, 9, 16, 17, 20, 21, 24, 28, 36,
  37, 39, 43, 44, 45, 46, 47, 48, 49, 50, 51, 52, 53, 54, 55, 56, 57, 58, 59, 60, 61, 62, 63, 64; NBA Totals 3, 6, 9, 10, 14, 16, 20, 21, 22. Retired rules are listed in `RETIRED` in each rules file;
  their code stays but the scripts drop them, and numbers aren't reused.
  `data/raw/nba_lines.csv` dates for 2025-26 are the UTC date (a day late for
  evening games; 2026-27 rows are Eastern): backtests date games by ESPN's
  start time in Eastern. Re-dating them on 2026-11-05 retired NBA Stats 41
  (60.0%).
  Older seasons' odds (kyleskom, 2018-19 to 2021-22) store the spread
  unsigned, so the favorite comes from the moneylines, and call Charlotte
  "Bobcats".
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
  rules 17-19 UNDER (on trial) when both teams are on a back-to-back (`BOTH_B2B`);
  rules 20-21 UNDER (on trial, revenge family) when the team that lost the last
  meeting at home is now the underdog with the better record (20 that meeting
  earlier this season, 21 lost it by 10-19). An over and an under rule on
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
  Rules 44-48 (on trial, one "revenge" family) play the team that lost the
  last regular-season meeting with tonight's opponent (this season or last,
  within 400 days; `lib/nba_revenge.py`, meetings from `data/raw/nba_lines.csv`,
  equal records excluded): 44 lost it by 10-19 as the favorite, now home with
  the worse record; 45 same margin as the favorite, worse record, 2+ straight
  losses to them; 46 favored then and now, worse record, 2+ straight; 47 lost by
  10-19 last season, worse record, only that meeting; 48 FADES a team that lost
  at home as the underdog and is now a home favorite. Revenge with both teams in
  good form, and adding turnover trends, were tested and didn't clear the bar.
  Rule 49 (on trial) fades a 7+ point underdog on a back-to-back whose last
  game used 8 or fewer players for 10+ minutes (`BoxCache.rotation`, from the
  box score's MIN; both teams 6+ games played). It came from a 2026-11-05
  search of player box-score facts (last game / last 3, both teams) where a
  game-level shuffle passed 36-91 combinations vs 79 real, so it's on trial;
  last-game team stats and 3/5-game stat trends were also searched and were
  no better than luck.
  Rule 50 (on trial) backs the favorite when 60%+ of spread bets are on a 7+
  point underdog but the line moved 1-4.5 points toward the favorite since
  the open (reverse line movement), from Action Network's public feed
  (`lib/action_network.py`: consensus line, opener, ticket %); 89-55 replayed
  on 2024-25 and 2025-26 (no openers in the 2023-24 feed). Moves of 5+ are
  left out: some are injury news, some a bad opener (a few have home/away
  swapped). Checked until
  tip-off, then frozen; no feed means it just doesn't fire. Public %, money %
  and plain line moves on their own tested at 49-54% (2023-24 to now).
  Rule 51 (on trial) backs a team with a losing record that won its last two
  games by 10+ each, with at least a day off (5+ games played): 101-45 rested,
  114-62 any rest (13-17 on a back-to-back, so those are left out); every
  season positive. It came from a 2026-11-11 search of schedule, travel,
  home-stand, vs-the-spread and streak facts (8,300 side and 6,600 total
  combinations) that was otherwise no better than luck (39 passes vs 32 by
  chance); the losing-record cut was chosen after looking, so treat the
  backtest as optimistic. Backfilled for 2026-27 (1 game). It can point the
  other way from rules 20-29 (a disagreement means no pick).
  Rule 52 (on trial, one "momentum" family with 51) backs a home team that
  beat the closing spread by 15+ in each of its last two games
  (`data/raw/nba_lines.csv`), with at least a day off: 58-30 rested, 68-40 any
  rest (10-10 on a back-to-back); 2022-23 was 5-8. Beating the spread twice
  running climbs steadily (5+ 53.6%, 10+ 56.3%, 15+ 58.5%; at home 63.0%), but
  on the road it's 54%. Found on 2026-11-11 from seven scenario families (270
  variants; this family passes by luck ~2% of the time). 2026-11-02 Pelicans
  @ Grizzlies had 51 on New Orleans and 52 on Memphis: no pick, as live.
  Rule 53 (on trial, one "tired-underdog" family with 49) backs a home
  favorite of 10+ (tonight's `statsSpread`) vs. a team at .300 or worse (8+
  games played) on the second night of a back-to-back: 76-38, unseen 23-14,
  every counted season positive; it climbs with the spread (7+ 63.6%, 12+
  74.7%), and the same bad teams with a day off covered 50% (194-193), so the
  back-to-back is the signal. Found on 2026-11-11 by drilling into a lean
  from the Knicks-Bucks game (which itself was NOT a back-to-back for
  Milwaukee and isn't a rule-53 game); no 2026-27 games qualified at backfill.
  Rule 54 (on trial, "momentum" family with 51-52) backs a home team that
  covered its last two games with a line (`data/raw/nba_lines.csv`, pushes
  skipped), in games 6-20 of its season, with at least a day off: 172-105
  rested, 202-126 any rest (30-21 on a back-to-back); flat 50% from game 21
  on and 46% on the road; 2024-now only 52-38 and 2020-21 was 24-28. Found
  on 2026-11-11 from a split-season search of 243,000 three-way side
  combinations (162 held in both halves vs 89 by chance); its own family
  passes by luck 0.3% of the time. Backfilled for 2026-27: 10-8
  (2026-11-02 Pelicans @ Grizzlies left with no pick: 51 was on New Orleans).
  Rule 55 (on trial) backs a road team in its first road game after 3+
  straight at home, 1,000+ miles from home (`lib/nba_arenas.py`, arena to
  arena), after losing its last game, with at least a day off: 97-50, unseen
  33-16, 2024-now 30-19. The weakest of 51-55: the same spot after a win is
  47.5% and it isn't steady as the miles go up; its family passes by luck
  about 1% of the time. Backfilled for 2026-27: 2 games.
  Rule 56 (on trial, one "hard-win" family with 2 and 9) fades a team on the
  second night of a back-to-back that won last night with a player logging
  40+ minutes (`BoxCache.max_minutes`, the box score's MIN; both teams 5+
  games): 120-73, unseen 41-21, 2024-now 38-22, no losing season. It needs
  all three parts: after a loss it's 102-103, with rest 51%; 38+ min is 57.5%
  and 42+ is 64.0%. From a 2026-11-11 split-season search of 206,000 side
  combinations with a player box-score fact (137 held vs 85 by chance); its
  family passes by luck 0.7% of the time. Rebounding facts (50+ team
  rebounds vs. a team on a back-to-back: 56.6%) and totals with player facts
  didn't clear the bar. Backfilled for 2026-27: 1 game (already a pick).
  Rules 57-61 (on trial) came from a 2026-11-11 two-condition search of 203
  facts (player box score, streaks, rest, travel, spread results; 22 pairs
  held at 58%+ in both halves of the seasons vs 8 by chance), each then
  checked for a steady dose-response and its own family shuffle:
  57 ("momentum" family) backs a team beating the closing spread by 6+ a game
  over its last five (4+ with a line) vs. an opponent with no double-digit
  rebounder in either of its last two games (`BoxCache.top_rebounds`), rested:
  144-79, unseen 38-22, 2024-now 65-35; vs. an opponent that had one in each
  it's 49.2%. 58 fades a team that won its last game by 1-5 when tonight's
  opponent scored 130+ in its last game: 119-68, unseen 30-18, 2024-now 58-22;
  climbs 115+ 54.8% / 120+ 58.0% / 125+ 60.8% / 135+ 70.2%. 59 fades a home
  team in its first game back from 4+ straight road games that's being
  outscored by 5+ a game, rested: 69-37, unseen 21-7 (road trip alone 50.1%;
  good teams 47.8%; smallest sample). 60 ("momentum") backs a team that won
  its last two by 10+ vs. an opponent whose last game went over its closing
  total by 20+ (`total_close_of`): 111-61, unseen 45-15; climbs with the size
  of the over; 2023-24 was 11-10. 61 ("tired-underdog" family with 49, 53)
  fades a team at .250 or worse (8+ games) that used 8 or fewer players for
  10+ minutes last game: 118-75, unseen 33-21; only just clears 61% (.300
  teams 59.5%). Backfilled for 2026-27: 57 2-1, 58 1-1, 59 1-1, 60 1-1, 61
  0-2 (several on games that already had a pick; four left alone because an
  existing pick was on the other side).
  Rules 62-64 (on trial) came from a 2026-11-11 search adding star-player
  (top scorer by points per game, 5+ games: missed / big night), pace,
  schedule-density and home/road-record facts; those new facts alone were
  weak (7 pairs vs 3.6 by chance). 62 ("momentum") backs a team that covered
  its last 3+ games with a line vs. an opponent whose top scorer scored 10+
  over his average last game, rested: 71-33 (83-42 any rest), unseen 38-11,
  2024-now 23-16; climbs 8+ 58.6% / 10+ 66.4% / 12+ 71.8%. 63 ("hard-win"
  with 2, 9, 56) fades a team on a back-to-back that won last night shooting
  45%+ from three on 25+ attempts (`BoxCache.threes`): 152-96, unseen 54-25,
  but 2024-now 39-33 and 2025-26 14-16; rested it's 48-51%, after a loss
  28-33. 64 backs a home team covering 60%+ this season (8+ games with a
  line) vs. a team .250 or worse on the road (3+ road games), rested:
  106-61, unseen 30-24 (just over 55%), 2024-now 44-15; it doesn't strengthen
  with a higher bar (65%+ ATS: 54.7%). An OT winner with a 30+ scorer
  (146-88) was left out: rule 2 already covers most of it and the rest is
  57.9%. Backfilled for 2026-27: 62 0-1, 63 0-2, 64 4-0 (one new pick; the
  rest on games that already had one).
  NBA Totals rule 22 (on trial) bets the UNDER in a near pick'em (spread 2 or
  less) when the total is 3+ above the two teams' season scoring averages
  (`inflated_total` in `nba_totals_signals.py`: (home PF + away PA)/2 + (away
  PF + home PA)/2, both 5+ games) and a team's last five went over their
  closing totals by 6+ a game: 108-66, unseen 46-32, 2024-now 18-11. Tighter
  spreads and bigger gaps do better (spread 3-/5+ 61.0%, 4.5- 54%). From a
  2026-11-11 split-season totals search (5,240 combinations, about chance
  overall); its family passes by luck under 0.1% of the time. No 2026-27 games yet.
  Shuffle checks must permute only games that have a result (2% of games
  are pushes or have no line): an early version of the 2026-11-11 checks
  shuffled the blanks in too, which overstated chance for side searches; the
  figures for 51-55 and Totals 22 above are from the corrected check.
  `scripts/archive_market.py` (each scoring and game-time run) saves Action
  Network's NBA board for today and tomorrow to `data/raw/market/nba/<date>.json`
  (consensus line, opener, bet/money splits, and `rlmFavorite`, the team rule
  50's test backs). The Basketball Routine can't reach Action Network (the
  scheduled-task network blocks it, and its robots.txt bars WebFetch) but can
  read raw.githubusercontent.com, so its Market category reads this file.
  NBA Stats rules that read tonight's spread use `statsSpread`: ESPN
  pickcenter's (DraftKings) line, refreshed until tip-off and then kept,
  because a slate's line can be stale (2026-11-05 Heat @ Warriors: slate
  -7.5, market -3.5). The whole live line (spread, its odds, moneylines) is
  kept as `statsLine`, and NBA Stats picks are graded at it everywhere
  (`lib/picks.stats_view`: score_slate.py, the dashboard, pick log, rule
  records); every other model is still graded at the slate's line. Games
  from before 2026-11-05 have no statsLine and stay graded at the slate's.
  Overlapping slices of one situation (NBA Stats 2+9+56+63, 20-29, 35-40, 41-43, 44-48, 49+53+61, 51-52+54+57+60+62; NBA Totals 4-8,
  9-15, 17-19, 20-21) are one "family": several firing
  on a game don't make it "stacked" (`families()` in the rules files, `famCount`
  in `site/index.html`).
- **Refresh button** (pick sheet's top bar): re-fetches `data.json` in place (pending picks kept) and offers a link that opens a `refresh` issue; `.github/workflows/refresh-intake.yml` (owner's issues only) starts `diamond-ledger.yml` and `nba-gametime.yml` and closes it, and `pages.yml` rebuilds when they finish. A static page can't start a workflow without a token, hence the issue, as for picks and hand-entered data.
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
  After deploying, pages.yml also force-pushes the built `data.json` to the
  `site-data` branch (one commit, data.json only; the reason the workflow has
  `contents: write`), so a Routine that can read raw.githubusercontent.com but
  not the Pages site can fetch it. The Basketball Routine reads it: today's
  NCAAB stand-in slate as its starting game list and spread check, and the
  season records and NBA Stats/Totals rule flags for its closing summary
  (context only, never an input to the Ledger or Second Opinion).
- The pick sheet is an installable app (PWA): `site/manifest.webmanifest`,
  `site/sw.js` and `site/icons/` (copied into `_site` by `build_site.py`), with
  the manifest/icon tags and the service-worker registration in each page's
  head/body. The service worker is network-first for this site's own files, so
  pages and data.json are always fresh online and the last copy opens offline;
  bump `CACHE` in sw.js only to clear old caches.
- Totals models for other sports were tested on 2026-11-08 with the NBA
  Totals bars (61%+ counted, 55%+ unseen, found on 2022-24) and a game-level
  shuffle: NCAAB (AP Top 25 games 2018-19 to 2025-26, 3,819 with a total; 22
  passes vs 18.9 by chance, p=0.34), NFL (2017-2025, 1,780 games; 1 pass vs 3.9,
  and 12 vs 11.6 with 2021-22 as the finding seasons since ESPN has few 2023
  totals) and CFB (ranked-team games 2018-2025, 1,313; 10 vs 3.3, p=0.13).
  None is better than luck, so there are no NFL/NCAA totals models.
  `TOTALS_OF` in `site/index.html` would fold one into its tile if one is added.
- NBA and NFL Stats only pick regular-season games, and NBA Stats only reads
  the current season's games from the growing scores archive.
- `curl_cffi` is pinned in `requirements.txt`; bump it deliberately.
- NCAA basketball: when no Routine has written the day's slate,
  `scripts/auto_slate.py ncaab` (every scoring run) builds it from ESPN's
  default scoreboard -- the games involving an AP Top 25 team, the Basketball
  Routine's scope and the feed the grader reads -- with lines from ESPN's
  pickcenter, marked autoSlate so a Routine's slate still replaces it.
  `archive_lines.py` keeps NCAAB opening/closing lines too.
- NCAAB Ledger inputs: KenPom is paywalled, BartTorvik's robots.txt bars
  ClaudeBot and TeamRankings errors, so the Basketball Routine skipped every
  NCAAB game "no-data" on 2026-11-06. `scripts/archive_ncaab_ratings.py`
  (each scoring run; fetches at most once a day after 8 AM ET, plain request,
  allowed by robots.txt) saves Sports Reference's ratings page to
  `data/raw/ncaab/ratings/<date>.json`, plus last season's final once
  (`final-<season>.json`): MOV (= PD/g) and adjusted ORtg/DRtg per 100
  possessions with ranks, and the Ledger's inputs with its early-season rule
  already applied (`ledgerMov`, `ledgerORtg`/`ledgerDRtg` and their ranks
  among `ledgerN` teams; 0 games = last final, first 10 = 50/50 blend). The
  Routine and the research check read it through raw.githubusercontent.com.
  Sports Reference names schools its own way (Connecticut, Mississippi,
  Louisiana State, Miami (FL)). Don't fetch sites that block bots.
- NCAAB Stats (`scripts/ncaab_stats_signals.py`, rules in `scripts/lib/ncaab_stats_rules.py`)
  patches picks onto the NCAAB slate each run, like NBA/NFL Stats, but has no
  active rules: Rule 1 (back a team after a loss where the opponent out-shot it
  from three by 25+ points of 3P%) replayed at 58.7% on 2018-19 to 2025-26 and
  was retired on 2026-11-03 under the same 61% bar; the NBA rules translated
  to college and 2,100 college combinations didn't clear it either (AP Top 25
  games, ESPN core-odds closing lines). The step still runs and can take new
  rules. Each team's previous game comes from ESPN's team schedule and its box score.
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

A **Models** filter (multi-select chips, like Leagues; `DASH.models`, empty = all,
saved in localStorage) sits in the scorecard's filters and the pick log: it limits
the tiles, charts, legends, by-sport bars, chart tables, the pick log rows and the
game cards' model badges to the chosen models (`shownWho`, `playModelOn`,
`BADGE_OF`). NBA Totals follow NBA Stats and your O/U follows You; the
agreement table hides when You isn't selected. Your pick row on each card always shows.

Dashboard numbers all come from one calculation: `belongs` / `outcome` / `summarize` /
`seriesFor` in `site/index.html` count over/unders (NBA Totals in NBA Stats, your O/U
in You; `TOTALS_OF`) in the tiles, sparklines, running-profit and win-rate lines,
by-sport bars and every table, so they can't disagree (2026-11-08: tiles had them,
charts didn't). The agreement table is side picks only. Plays you made after the
game started carry `lt`; only the public Results page uses it (it leaves them out
unless its box is ticked). The pick page's You tile doesn't mention them.

Over/under picks: each game's pick row also has Over / Under buttons at the
game's total. `scripts/slate_totals.py` (every scoring run, and NBA in the
game-time run) puts ESPN pickcenter's line on today's and tomorrow's slates as
`gameTotal`, `gameTotalOverOdds`, `gameTotalUnderOdds`, refreshed until the game
starts (repo-owned in `sync_ledger.py`). The submitted payload's `totals` map
(game id -> over/under/none) is saved by `intake_picks.py` under `totals` in
`data/mypicks/<date>.json`, locked at the slate's line and odds at submission
(NBA falls back to `totalsLine`). They're graded in `lib/picks.grade_total`
($100 at the locked odds, -110 if none; landing on the line is a push) and
shown in the pick log ("Your O/U") and as a row on the dashboard's You card,
kept out of the ATS/moneyline figures.

Your picks are graded at the line you took, never the slate's current one:
`lib/picks.mine_view` puts the spread, its odds and the moneyline saved with
the pick in place of the slate's (the dashboard, pick log and the card).
Alternate lines: a picked side or total gets a − / + stepper (half points, up
to 10 either way, not soccer) with an estimated price. `lib/altlines.alt_price`
estimates it from the posted line and price (normal margin/total model with
football key numbers, 4.5% hold); `site/index.html`'s `altPrice` is the same
math in JavaScript (2,000 random cases match exactly) and `intake_picks.py`
recomputes the price itself from the payload's `alts` / `totalAlts`, saving
`alt: true` and the `posted` line with the pick. The user's picks may be
corrected by hand only when they ask (2026-11-07 Miami was taken at +7.5,
slate said +7; the entry keeps `posted` and a `correction` note).

Public results page (`site/results.html`, linked from the pick sheet): every one of
the user's picks, sides and over/unders, graded at the line taken. `lib/results.py`
builds `results.json` / `results.csv` in `build_site.py`. Each row has when it was
submitted and how many minutes before the game's start (the slate's `time`);
picks submitted after the start (2026-09-26 Texas @ Tennessee, 2026-10-10
Stanford @ Notre Dame) are flagged and left out of the page's numbers unless the
box is ticked, because a pick logged during a game can't be verified. Intake
doesn't reject them (it only blocks final games). Corrections and alternate
lines are labelled. The repo and Pages site are public, so the picks files and
their commit timestamps are the verification trail. It's the user's record, not
advice, and has a sample-size note (95% range).

Don't write picks into game objects in `data/<sport>/` (no `userPick`,
`yourPick`, `myPick` fields) and don't ask the user to tell you their picks.
Grading of their picks happens in `scripts/lib/picks.py` from the game's final
score and stored lines: ATS and moneyline at $100 flat, with NFL, CFB and NCAAB picks on a
team getting more than 7 points counted ATS only. In any sport, a pick priced
-400 or shorter is left out of the moneyline record and profit (win or lose);
this applies to the Ledger and Second Opinion too (`scripts/lib/grading.py`).
