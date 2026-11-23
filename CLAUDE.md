# Diamond Ledger — repo notes for Claude

`main` is the default branch and the only long-lived one. Work on a branch and
merge into `main`; the scoring, pick-intake and Pages workflows all run from it.

## How data flows

- **Picks:** the daily Diamond Ledger Routines (NFL, CFB, MLB, NBA/NCAAB,
  soccer) research each day's games and write the slate to the ledger
  database only. They don't push to git.
- **Into the repo:** the hourly "Diamond Ledger — sync to GitHub" Routine runs
  `scripts/sync_ledger.py` on an export of the database and commits new or
  changed slates in `data/<sport>/` to `main`. Repo-owned fields (picks the
  repo patches on, storylines, live lines) are carried over from the repo copy
  by matching games on away/home, then start time, then order -- a doubleheader
  has the same teams twice (matching on teams alone gave both MLB games game 2's
  fields until 2026-11-14). Mirror the database exactly;
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
- **Scoring chaser** (`.github/workflows/score-chaser.yml`, 2026-11-19, the
  user's call): GitHub's hourly schedule skipped every run from 10:31 PM ET on
  2026-11-18 to the next morning (and the 4-hourly health check ran twice a
  day), so that night's games stayed ungraded. After every scoring run the
  chaser runs `scripts/scoring_pending.py` (a game that started 2-14 hours ago
  whose slate doesn't have it graded, `is_final`; start from the slate's
  `time` and its zone); if any, it waits 40 minutes, looks again on the latest
  main, and starts a scoring run unless one is queued or running. Each run
  finishing starts the chaser again (a newer one cancels a waiting one), so it
  stops once everything is graded; the 14-hour cap stops it on postponed games.
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
  37, 39, 43, 44, 45, 46, 47, 48, 49, 50, 51, 52, 53, 54, 55, 56, 57, 58, 59, 60, 61, 62, 63, 64, 65, 66, 68, 69, 70; NBA Totals 3, 6, 9, 10, 14, 16, 20, 21, 22, 23, 24. Retired rules are listed in `RETIRED` in each rules file;
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
  Rule 65 (on trial) backs a team in a near pick'em (tonight's spread within
  3.5) whose opponent has been giving 60+ more minutes a game to players 6'4"
  and under over its last five games (`small_guard_minutes`: per-player minutes
  from `BoxCache.minutes`, heights from `lib/nba_heights.py` /
  `data/raw/nba_heights.json`, ESPN athlete pages, new players looked up once;
  a game counts with 7+ known heights, 3+ such games): 114-66, unseen 54-32,
  2024-now 36-16; climbs 20+ 53.2% / 40+ 58.5% / 60+ 63.3%. From a 2026-11-12
  look at player size: minutes-weighted height edge alone tilts ATS 47.5% ->
  52.5% across fifths; weight predicts wins, not covers; a shorter (1+ in) or
  guard-heavy team on a back-to-back covers ~40-43% (watch list, under the
  bar); size x rest/travel/strength grids (1,478 side, 1,157 total
  combinations) were luck overall and size does nothing for totals.
  Rule 66 (on trial, "hard-win" family with 2, 9, 56, 63) backs a team that has
  missed the closing spread by 6+ a game over its last five (4+ with a line)
  when tonight's opponent's last game went to overtime, won or lost
  (`went_to_ot`: ESPN scoreboard period > 4, hand-entered data first): 84-45,
  unseen 31-18, 2024-now 23-12, every counted season positive; climbs with
  the slump (0+ 53.2%, 4+ 60.3%, 8+ 68.4%, 10+ 79.5%); its family passes by
  luck 0.1% of the time. From a 2026-11-13 search of what precedes an 8+ point
  cover (base rate 26.8%; single factors reach ~31%, pairs were at chance, 4
  vs 2.5). No 2026-27 game had both conditions at backfill.
  Rule 67 (retired 2026-11-13, the day it was added, because 2022-23 was a
  losing season; code kept, in `RETIRED`; "jet lag homecoming") faded an Eastern home team in its
  first game back from a road game on the Pacific coast, 3 time zones west
  (`time_zone` in `lib/nba_arenas.py`; both teams 8+ games, any rest): 38-18,
  unseen 12-3, 2024-now 16-7, but 2022-23 was 4-7 and it's a small sample.
  Flying home east climbs with the zones crossed (0: 47.7%, 1: 47.1%, 2:
  56.9%, 3: 66.7% after 3+ game trips) and flying home west is 49.7%. From a
  2026-11-13 test of 49 "storyline" situations (4 at p<0.05 vs ~2.5 by
  chance). No 2026-27 game had qualified, so no picks to remove.
  NBA Totals rules 23-24 (on trial, OVER; 2026-11-12): no single factor of 128
  moved totals 5+ points in both halves and all-pairs searches were at chance,
  but two pairs had steady patterns of their own. 23: the home team's last
  game went over its closing total by 10+ and the road team allowed 130+ in
  its last game (141-85, unseen 27-17, 2024-now 60-38; 125+ 58.5%, 135+ 59.1%;
  the mirror, road over / home allowed, is 51.6%). 24: late season (home team
  66+ games played) and both teams lost their last game (205-130, unseen
  64-50, 2024-now 75-45; climbs 50+ 55.9% / 60+ 58.7% / 74+ 63.4%, nothing
  before game 50; fires from about March). Backfilled 2026-27: 23 on 3 games.
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
  Overlapping slices of one situation (NBA Stats 2+9+56+63+66, 20-29, 35-40, 41-43, 44-48, 49+53+61, 51-52+54+57+60+62; NBA Totals 4-8,
  9-15, 17-19, 20-21) are one "family": several firing
  on a game don't make it "stacked" (`families()` in the rules files, `famCount`
  in `site/index.html`).
- **Refresh button** (pick sheet's top bar): re-fetches `data.json` in place (pending picks kept) and offers a link that opens a `refresh` issue; `.github/workflows/refresh-intake.yml` (owner's issues only) starts `diamond-ledger.yml` and closes it, and `pages.yml` rebuilds when it finishes. It used to start `nba-gametime.yml` too; the two then collided pushing today's NBA slate and the scoring run failed (2026-11-12), so now both workflows' push steps retry a conflicted rebase with `-X theirs` (this run's lines win) and push only if the touched JSON still parses. Since 2026-11-14 the data JSON files merge field by field instead (`scripts/json_merge.py`, a git merge driver: `.gitattributes` `data/**/*.json merge=jsonmerge`, enabled by `git config merge.jsonmerge.driver ...` in the scoring, game-time, pick-intake and data-intake push steps): a field only one side changed keeps that change, a field both changed takes the run's value, games/entries are matched by identity, and each file keeps its layout. A line merge had let a scoring run's push undo a same-hour hand fix to two MLB slates (a whole game sits on one line); `-X theirs` now only applies to non-JSON files. Run the same `git config` in a local clone before rebasing data changes. A static page can't start a workflow without a token, hence the issue, as for picks and hand-entered data.
- `.github/workflows/nba-gametime.yml` re-runs only `nba_stats_signals.py` and
  `nba_totals_signals.py` every 15 minutes, 4 PM-midnight ET, so injury-based
  rules (NBA Stats 18, NBA Totals 3) and totals lines are checked near
  tip-off; it commits `data/nba/` and pages.yml rebuilds after it. When a
  pick would fire if a listed-but-not-Out player sits (questionable,
  doubtful, day-to-day), the scripts write `statsWatch` / `totalsWatch` and
  the card shows an "Injury watch" until the game is final.
- Game cards (2026-11-14 redesign, the user approved screenshots first):
  `matchupHeader` (team rows with a colored badge, Away/Home, spread chip and
  moneyline, a time/Final pill; final scores replace the lines and the loser is
  dimmed), a two-team color stripe on top (`--ca`/`--ch`), `leanMeter` (since
  2026-11-15 the same win-% blend as the mix donut, `mixData`: each team's
  blended %, soccer's draw in gray), accented model
  badges (`.badge` left border in the model's color; sat-out dashed). Team
  colors/abbreviations: `TEAM_COLORS`/`TEAM_ABBR` (NBA, NFL), `TEAM_COLORS2`
  second colors used when a color is near-black or the two teams look alike
  (`gameColors`); other teams get a hashed color and initials.
  Model + storyline mix donut (2026-11-15, `modelPie`/`pieRow` in
  site/index.html, the user approved screenshots): a slice per model with a
  pick (sat-out ones included, marked *) and per storyline (STY, sized by its
  tally weight); each slice is split by the model's season win % in that
  sport (`modelRec`; no record = 50%) or the storyline's leanPct -- that
  share in the pick's team color, the rest lighter to the other side (soccer:
  split between the other two results). The middle is the weighted blend.
  The lean meter shows the same blend (`mixData` feeds both). Display only:
  records and the veto are unchanged.
  Trend charts (2026-11-14): "ATS trend" and "Totals trend" on NBA/NFL/CFB/
  NCAAB cards (`trendChart` in site/index.html; data `atsTrend`/`ouTrend`
  from `ats_trends` in build_site.py): each team's running cover margin, and
  running points over/under the closing total, over its last 14 (basketball)
  or 7 (football) graded games on the sport's slates; college slates don't
  hold every game, so CFB/NCAAB teams are filled from `data/raw/<sport>_lines.csv`
  (`_fill_from_lines`; full-name match, ambiguous names like Miami/Michigan stay slate-only). Closing totals come from `data/raw/<sport>_lines.csv`
  (`closing_total`, date +/- a day, teams by name), else the slate's own total;
  `archive_lines.py` now also archives CFB (seeded with 2026's 434 games).
  By quarter (2026-11-18): each trend game also carries its periods (row[5],
  `quarters` in build_site.py from `data/raw/linescores/<sport>.json`, saved by
  `scripts/archive_linescores.py` each scoring run): the team's margin per
  quarter (NCAAB halves) on the ATS chart, both teams' points per period on the
  totals chart. On the chart itself each game's step is split into its
  quarters (NCAAB: halves; the user asked for the quarter trend inside the game
  trend, not separate charts): small dots after each quarter, at the running
  total plus the quarter's margin and a quarter of the spread (totals: points
  minus a quarter of the total), so the last step lands on the game's big dot
  (overtime folded into it); games without quarter scores go straight. Each game
  dot is labelled with the opponent (`@` = away; `oppLabels` nudges a label out
  a row when it would overlap another; the higher line's labels go above) and
  the opponent's record going into the game (row[6], `record_at` in
  build_site.py from `data/raw/records/<sport>.json`, which
  `archive_linescores.py` saves from the same scoreboards: ESPN's record on a
  finished game is the one after it, so the result is taken back off; college
  dates come from the lines files too). Hovers show it as well. The label's color
  is the opponent's win % going in, not the team color (the user's call):
  blue winning, red losing, deeper further from .500 (full at .750/.250),
  gray at .500 or 0-0 (`recColor`, `--recw`/`--recl`/`--recn`, with a key). Then a
  table of each team's average per period (`quarterTable`). The game dots'
  hovers list the quarters. Books' covers stay full-game.
  ATS bars (2026-11-19, the user's call, from a Basketball-Reference "Game
  Results" screenshot): the ATS trend is no longer a line -- `atsBars` draws
  one panel per team, a bar per game for how much it beat (green, up) or
  missed (red, down) the closing spread, oldest to newest, on a labelled scale,
  then tonight's game as a gray dashed bar; under each bar the opponent (@ =
  away; phone puts @/vs on its own line) and its record going in, colored by
  it (`recShade`). Hovers give the spread and the quarters; `quarterTable`
  (bars=true) keeps the per-quarter averages. The totals trend is still the
  running line with quarter steps.
  Bars sit on a calendar, one slot per day (the user asked for the spacing,
  as on that page): a back-to-back is the next slot, every day not played is
  an empty slot with a dash on the zero line (no cap: an NFL bye is a wide gap); each bar's
  label starts with its rest (orange "B2B" or "Nd off"; tonight's from the
  slate date), and a label that would overlap drops a level with a thin
  connector. An "ATS | Win margin" switch (top right; phone, above) flips every
  card's bars between the cover margin and the final score margin (r[2] -
  r[3]): `atsBars` draws both via `abBuild(..., WIN)` and `html.abwin` picks
  one, remembered in localStorage `dl-abmode`.
  MLB and soccer have the bars too (2026-11-19, the user's call: "all
  sports"; `TREND_GAMES` mlb 14, soccer 7, `NO_LINE_OK`): MLB's ATS is the run
  line where the slate has one (about half its games; the rest show "no line",
  and Win margin covers every game), soccer is Win margin only (no spread; W-D-L
  record). Each row carries row[7], the final margin, for games with no line.
  Soccer uses only our slates' matches: ESPN's combined soccer archive mixes
  women's/youth sides under the same club names with no league column, so
  `_fill_from_scores` is kept but unused. MLB records come from the same
  archive script (`archive_linescores.py`, records only: NO_LINESCORES); in the
  postseason ESPN shows the final regular-season record, kept as is.
  MLB abbreviations: `MLB_ABBR` in site/index.html. Bar numbers are left off
  where bars are packed (MLB's daily games on a phone); the hover has them.
  Next 3 games (2026-11-19, the user's ask): after tonight's gray bar, each
  team's next 3 games sit on the same calendar as dashed empty outlines (white
  dashes at home) with rest, opponent and its record (`atsNext`, `next_games`
  in build_site.py; soccer without records, ESPN's are per competition). From
  `scripts/archive_schedule.py` (each scoring run): `data/raw/schedule/<sport>.json`,
  every game back to the season's start (past dates saved once, so a past slate
  shows the games that followed it) and ahead (looked at again every 4 hours);
  NBA/NFL/MLB a month per request, college a day at a time, soccer per league
  (`SOCCER_LEAGUES`; a club in an unlisted competition shows fewer). Edge labels
  are kept inside the chart (`lx`).
  Point-differential candles (2026-11-21, the user's ask from a stock chart of
  daily candles with each week as a hollow candle): `pdCandles` in site/index.html
  (`cdBuild`), after the ATS bars on every trend card. Each team's running point
  differential this season (from `H2H_START`) as one candle per game on a calendar
  (open = the running total before it, close = after; the wick is the high and low
  through its quarters, halves or innings, saved in the schedule rows; soccer's
  scoreboards have no periods, so no wick), each
  Mon-Sun week (NFL/CFB: month) a hollow candle around its games, tonight a dashed
  outline. A "Point diff | ATS" switch (`dl-cdmode`, `html.cdats`) shows the running
  cover margin instead (margin + closing spread from `data/raw/<sport>_lines.csv`;
  no line = a flat gray candle; no switch where no line is saved, MLB and soccer).
  A 1M | 2M | 3M | Season range (2026-11-21, the user's ask; `CD_RANGES`,
  `dl-cdrange`, every card at once: `cdInner` redraws each `.cdwrap`) shows only
  the last 30/61/91 days, the running total still counted from the season's start
  (the header adds the change "in this range" when games were cut).
  Data: `pd_candles` in build_site.py from `data/raw/schedule/<sport>.json`, the
  whole current season (`CANDLE_DAYS` None; a number would keep only that many
  days as rows, the earlier games summed into `c0`/`a0`). For it,
  archive_schedule.py saves each finished game's points per period (row[7] away,
  row[8] home; MLB pads the home team's unplayed 9th with 0) and reads every
  scoreboard at limit=1000 and 300 and merges them: ESPN's CFB board gave 25
  games at 1000 (52 at 300), so the CFB schedule had missed most Saturday games
  until 2026-11-21.
  Home games' bars have a white border (`.hm`, every sport, both views and
  tonight's bar; the user's call), with a thin dark ring on the light theme so
  it shows on a light background; a key in the chart's note.
- Slate date picker (2026-11-19, the user's call): the slate bar's "Date" select
  and ‹ › show any past slate as it stood -- games, results, model and your
  picks, props, storylines, trend charts going into that day -- view only
  (`.pastview`: pick buttons off, prop forms and the submit bar hidden; a note
  with "Back to today"). `slate_payload` in build_site.py makes the slate part
  of data.json for the latest date and `slates/<date>.json` (same keys, no
  rosters) for every earlier date with games (`past_slate_dates`,
  `SLATE_HISTORY_DAYS` None = all season; ~70 files, 3.8 MB, built in ~2 s,
  each fetched only when picked; `_site` isn't committed). `data.json`'s
  `slateDates` lists them. The page swaps `SLATE_KEYS` into DATA and redraws
  only the slate (`rerenderSlate`); the dashboard and pick log don't change.
  A "Slate results" box tops each slate once any of its games are graded
  (`slateResultsHtml`, today's too): per model and You, that day's ATS and ML
  record with $, over/unders and props (NBA Totals with NBA Stats, yours with
  You), and pending, from DATA.plays for that date with the scorecard's
  `belongs`; follows the league and model filters (`applySlateFilter`).
  Each finished game's card is scored right under its header (`resultStrip`,
  the user's ask: "each game scored in its section"): who won and by how much,
  who covered the spread (MLB run line; NBA at statsSpread when set), the total
  against its line, then every pick on that game graded as chips -- models
  from `g.results` (ATS and counted ML), NBA Totals, your pick (ATS with $,
  ML), your O/U and your props (with the player's number). Shown as three tiles
  (2026-11-19, the user wanted better visuals than a text line): Winner (team
  badge, margin, score), Spread (who covered, by how much) and Total
  (OVER orange / UNDER blue, by how much), each topped in the team's or
  over/under color, the spread and total with a gauge (`gauge`: the line in
  the middle, a dot where the game finished); the pick chips below.
- **Matchup by position** (2026-11-19, the user's ask from an article on
  Indiana allowing 3s to point guards): a "Matchup by position" bar on NBA and
  NFL cards, above the trend charts, opens what each defense allows a game to
  each position (rank, green above / red below the league average) and each
  player's averages with ▲/▼ when tonight's defense gives his position 12%+
  more or less. NBA: `scripts/archive_nba_player_box.py` saves every player's
  line (`data/raw/nba_player_box.json`); `lib/nba_dvp.py` derives PG/SG/SF/PF/C
  (ESPN only lists G/F/C: guards 5+ assists per 36 = PG, forwards 6'9"+ = PF,
  `nba_heights.json`), pts/reb/ast/3PM, plus each player's average +/- (row[9]
  in the box file, the user's ask; games saved before it are re-fetched). NFL: `scripts/archive_nfl_player_box.py`
  (`data/raw/nfl_player_box.json`, positions from ESPN rosters in
  `data/raw/nfl_positions.json`), `lib/nfl_dvp.py`: QB pass yds/TD/INT/rush yds,
  RB rush yds/rec/rec yds/TD, WR and TE rec/rec yds/TD/targets. Both count only
  games before the slate's date (`dvp`/`dvpNfl` in slate payloads). Tested on
  2025-26 NBA (14,000 player-games, before-the-game data only): softest vs
  toughest fifth of defenses, players beat their own average 59% vs 54% (points),
  58% vs 50% (rebounds), 52.5% vs 49% (assists), 49% vs 45% (3PM); PGs vs a top-5
  "3s to PGs" defense 47%. Small, and books already price matchups: context,
  not a pick.
  Matchup score (2026-11-19, the user's ask for "a rubric to show mismatches"):
  each offense vs tonight's defense graded A-F (`score` in `lib/nba_dvp.py` /
  `lib/nfl_dvp.py`, `mmBlock`/`mmChips` in site/index.html; the grades also sit
  on the closed "Matchup by position" bar). Per position, what the defense
  allows vs the league (NBA pts .5 / reb .2 / ast .2 / 3PM .1; NFL per
  position, INT counted against), each position weighted by its share of the
  offense's points (NFL: passing share split QB .45 / WR .40 / TE .15, rushing
  to RB). Cuts (`MM_CUT`): NBA A +8% / B +4% / D -4% / F -8%, NFL +-10/+-20
  (its scores swing wider). 2025-26 NBA replay (979 games, 10+ games in): about
  0.77 points vs the team's own last-10 average per 1% (A +8.2, beat it 71%;
  B +5.9, 67%; D -4.9, 37%), but the gap between the two offenses' scores did
  nothing ATS (50.6%); both high over 53% (104-92), both low under 57% (111-85,
  p=0.07). NFL not backtested. Context, not a pick.
  College (2026-11-19, the user's ask): NCAAB and CFB cards have the same
  matchup view and score (`dvpNcaab`/`dvpCfb`; `for_slate(..., sport)` in
  `lib/nba_dvp.py` / `lib/nfl_dvp.py`). `scripts/archive_college_player_box.py`
  (scoring run, after `archive_schedule.py`, whose event ids it uses; at most 250
  fetches a sport a run) saves every finished game of a team that has been on
  our slates for that sport (`data/raw/ncaab_player_box.json`, NBA rows with no
  +/-; `data/raw/cfb_player_box.json`, NFL rows with no targets, positions from
  ESPN rosters in `data/raw/cfb_positions.json`). So a defense needs 3+ saved
  games to be ranked (`MIN_TEAM_GAMES`; NBA/NFL too) and the league average is
  over the ranked defenses, which in college are mostly ranked teams. NCAAB
  positions: no heights, so forwards split by rebounds; guards PG at 4+ assists
  per 36 or the team's top-assist guard (college plays three guards, so SG is
  the big bucket). A slate name matching two schools ("Miami") takes the one with
  more saved games. Cuts: NCAAB +-12/+-25, CFB +-15/+-30 (scores swing much
  more: few games, cupcake opponents). Not backtested.
- **Starter-out alert** (2026-11-19, the user's ask for an edge outside stats:
  injury news the line may not have caught up to): `scripts/starter_out.py`
  (scoring run for NBA and NFL; NBA also in the game-time run every 15 min)
  writes `starterOut` on each game that hasn't started (repo-owned in
  `sync_ledger.py`, passed through in build_site.py's game fields; frozen once
  ESPN's summary state isn't "pre"): regular starters on ESPN's injury report
  (Out/IR/suspended = out; questionable, doubtful, day-to-day = watch), NEW when
  he played the team's last game, else "out Ng" (missed N straight: likely
  priced); the line's move since it opened (ESPN pickcenter `pointSpread`
  open/close, DraftKings); and up to 3 teammates at his position with their
  averages with him and in this season's games without him (NBA min/pts/reb/
  ast/3PM; NFL by position). Starters: NBA started half the last 10 games or
  60%+ of his games with 20+ min (positions from `lib/nba_dvp.py`); NFL the
  top QB1/RB1/WR1-2/TE1 by usage a game (2+ games). The card's
  `starterAlert` (under the lean meter) adds the opponent defense's number vs
  that position from the matchup data. Context, not a pick.
  Injuries in the matchup view (2026-11-20, the user's ask): starter_out.py also
  writes `injuries` on every NBA/NFL game before it starts ({side: {athlete id:
  status}} for out / questionable / doubtful / day-to-day; repo-owned, passed
  through build_site.py's game fields). `for_slate(..., injuries)` in
  lib/nba_dvp.py / nfl_dvp.py marks those players in the matchup tables (OUT
  struck through, Q/D tags; an out player stays listed and the next man up is
  added) and adjusts the matchup score: NBA takes an out player's points a team
  game off his position and re-weights the rest (`out`, and `base` = the score
  with everyone, shown as "Adjusted for ... out"); NFL only moves an out
  player's rushing yards off the run share (a missing QB or receiver doesn't
  change how much a team throws). The defense side isn't adjusted for missing
  defenders. College isn't covered (no injury feed in starter_out.py).
- **Line-move check** (2026-11-19, the user's ask): `scripts/line_moves.py`
  (scoring run, every sport; NBA also in the game-time run) writes `lineMove` on
  each game that hasn't started (repo-owned; frozen at the last pre-game look,
  about the close): spread (home), total and moneyline as they opened and now
  from ESPN pickcenter (DraftKings `pointSpread`/`total`/`moneyline` open/close;
  soccer adds the draw), and for NBA the public split and rule 50's
  `rlmFavorite` from `data/raw/market/nba/<date>.json`. The card's `lineMoveRow`
  (under the lean meter) flags a big move (2+ basketball, 1.5+ football),
  football crossing 3 or 7, and a spread move against a 60%+ public side.
  The starter-out box drops its own line text when this row is there.
- **Earlier this season** (2026-11-19, the user's ask: "a record of in-season
  games already played between the teams in the slate"): `head_to_head` in
  build_site.py (`h2h` in slate payloads, so past slates too) lists this
  season's earlier meetings of each game's two teams from
  `data/raw/schedule/<sport>.json` (archive_schedule.py now keeps final scores,
  row[5]/row[6]; older rows were re-fetched once), regular season on
  (`H2H_START`: NBA 10-20, NFL 09-09, MLB 03-25; postseason included), with
  the closing spread and total from `data/raw/<sport>_lines.csv` by ESPN id,
  else our slate's. The card's `h2hBlock` (under the line-move row): series
  record, ATS record, each game's score, who covered, total over/under; more
  than 4 meetings fold the earlier ones. Team names: `resolve_teams` finds
  ESPN's full names from the schedule game that night (`_name_fit`: exact, or
  the slate name plus a one-word or known two-word mascot), so "Texas" no
  longer matches Texas A&M or "Missouri" Missouri State; `next_games` uses it too.
  build_site.py runs in pages.yml without `curl_cffi` installed: it must not
  import a script that imports `lib.espn` (the first h2h push failed the Pages
  build on `from archive_schedule import CFG`; the live site stayed up).
- **Jump bar** (2026-11-22, the user's ask for a way to move between sections):
  a sticky strip under the top bar (`.jumpstrip`, `renderJump`/`jumpSync` in
  site/index.html; on a phone only the strip sticks, the top bar scrolls away)
  with chips for Scorecard, Pick log, Today (the slate bar, `#slatetop`) and each
  league on the slate with its game count, in page order; the chip for the
  section in view is lit, leagues hidden by the Leagues filter drop out. A
  "Game..." select jumps to any card (`id="g-<game id>"`), and a round back-to-top
  button shows after scrolling. Jumps are instant (a smooth window scroll was cut
  short when the strip scrolled itself); `--tbh` is the sticky height, used as
  `scroll-margin-top`.
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
- **Storylines** (`scripts/nba_storylines.py`, each scoring and game-time run;
  `storylines` on each NBA game, repo-owned in `sync_ledger.py`): situations a
  story could be told about (fat and happy, jet lag homecoming, the schedule
  loss, ghost town...), 20 of ~70 tested on 2026-11-13 -- the ones where
  history leaned 53%+ one way on 50+ games or p<0.05, sometimes the opposite
  of the story (`against`). Each entry has the story's bet, its ATS record from
  2018-19 and 2021-22 to 2025-26 (both teams 8+ games) and the side history
  leans to. The card shows them in a collapsed "Storylines" box with a tally.
  Context only: never a pick, not graded, not an input to any model; frozen
  once the game has a score. NFL: `scripts/nfl_storylines.py` (2010-2025,
  2020 left out; 62 tested in two rounds, 1 at p<0.05 vs 3.1 by chance, 16 shown; the wind
  story has no allowed live forecast source, and the QB-vs-old-team table runs
  through 2025 and needs a refresh each offseason). Penalty storylines (2026-11-16, nflverse
  play-by-play 2016-2025, 2020 out): "Beat the refs too" backs a team that
  won its last game while penalized 40+ more yards than the opponent (134-102,
  56.8%, halves 59/55; home favorite 63.3%), "Help from the flags" fades one
  that won with the opponent penalized 40+ more (156-119); after a loss the gap
  means nothing; split cells beat luck (13 vs 6.3, p=0.01). Live from ESPN's box
  score `totalPenaltiesYards` (`penalty_yards`). `nfl_storylines.py --only=KEY
  DATE...` adds just those storylines to finished games (others stay frozen);
  backfilled 2026: beat_refs 7-6-1, flag_help 8-4 (fade). CFB:
  `scripts/cfb_storylines.py` (FBS vs FBS, 2015-2025, 2020 left out; 53
  tested, none at p<0.05 vs 2.7 by chance, 14 shown; AP poll from ESPN's
  weekly rankings, the date is skipped until that week's poll exists; bowls,
  conference title games and FCS opponents left out). Soccer:
  `scripts/soccer_storylines.py` (big five leagues 2018-19 to 2025-26, MLS,
  Liga MX; ESPN's stored pre-match 1X2, no-vig by the power method; 55
  tested, 1 at p<0.05 vs 2.2 by chance, 4 shown, all the opposite of their
  story). NBA letdown storylines (2026-11-14, from ~85 letdown variants, none
  near the rule bar): "Spotlight letdown" fades a 5+ favorite vs a .450-or-worse
  team that won its last game on national TV and isn't on national TV tonight
  (`national()`: ESPN scoreboard broadcasts, ESPN/ABC/TNT/NBC/Prime/Peacock;
  147-114, 56.3%, p=0.047; after a non-national win 47.9%; 2025-26 was 34-34),
  and "Letdown spot" fades that favorite after any of: that national-TV win over
  a .550+ team, a win over a classic rival (`RIVALS`), a 15+ point win over a
  .600+ team, or its 3rd game in 4 nights vs a rested team (355-299, 54.3%,
  chosen after looking; skipped when Spotlight fires). Backfilled to 2026-11-12
  only (the veto started 11-13); not in the NBA lean-size backtest. "Fresh legs"
  (2026-11-14, from Hawks @ Bulls) backs a team with 4+ days since its last
  game vs an opponent on 2, at home or as an underdog: 112-71 (61.2%), every
  counted season positive, unseen 2018-19 + 2021-22 41-32 -- it would clear the
  NBA Stats rule bar, but it was found after looking at one game; 4 vs 2 as a
  road favorite went 10-12 and is left out. Backfilled to 2026-11-12: 2-1.
  Promoted the same day, at the user's request, to NBA Stats rule 68 (on
  trial; same conditions, both teams 8+ games, tonight's statsSpread for
  "underdog"); the storyline no longer fires (the past entries stay).
  `--backfill 68`: 2 games (2026-11-08 Bulls, Pistons); Clippers left alone,
  NBA Stats already had the Pelicans.
  Rules 69-70 (on trial, 2026-11-14, from the Nets 145 @ Pelicans 111 game):
  the team's last game had a closing spread within 3 (`home_spread_of`) and it
  beat or missed the spread by 20+. 69 fades it when it beat the spread by 20+
  and now faces a better-record team (by .050+): 47-25, unseen 12-8, 2024-now
  16-10; climbs 15+ 56.9% / 20+ 65.3% / 25+ 68.8%. 70 backs a home team that
  missed by 20+ when it now faces a worse-record team: 31-17, unseen 14-9, but
  2018-19 7-8 and 2025-26 3-4 (the weaker of the two). Overall a big miss or
  cover in a close game predicts nothing (48-52%); it's who's next. From ~60
  cells (2-3 at p<0.05, about luck), kept for the dose-response and both
  halves. Backfill: none (2026-11-12 76ers left alone, NBA Stats had Toronto).
  Rest grid storylines (2026-11-14; home/away rest grid: a 1-day edge does
  nothing, 2+ days helps mostly at home): "Fresh legs at home" backs a home team
  on 3 days vs a visitor on a back-to-back (117-82, 58.8%, p=0.02, halves
  54%/64%); "Tired hosts" fades a home team on a back-to-back vs a visitor
  on 2+ days (389-318, 55.0%) -- retired the same day (no longer fires) when its
  two strong slices became "Rested road favorite" (road favorite on 3 days vs a
  home team on a back-to-back, 47-32, 59.5%) and "Fresh underdog on the road"
  (road underdog on 2 days vs a home team on a back-to-back, 162-119, 57.7%,
  p=0.01, halves 55%/60%); the rest of it was 180-167. Rest does nothing for totals (16 cells, none at
  p<0.05; a 2+ day gap either way leans over 53.8%). The same rest, letdown and
  big-underdog tests on NFL, CFB, NCAAB, MLB and soccer were at chance
  (scratchpad TESTS3.md per sport): these are NBA-only effects. "Gutted home underdog"
  (2026-11-15, from Mavericks @ Cavaliers): a home underdog missing 3+ of its
  top 5 scorers (season points a game, 5+ games; players out 30+ days not
  counted; `top_scorers`) -- the story backs it, history fades it: 100-152
  (fade 60.3%, p=0.001, every counted season, unseen 48-24; road 50%,
  4+ out 49.5%, "home underdog" chosen after looking). Live, "out" is ESPN's
  injury report Out (checked until tip-off); on finished games, not in the box
  score. `nba_storylines.py --only=KEY DATE...` adds just that storyline to
  finished games, leaving their other entries as frozen; backfilled for
  2026-27: 2 games (Hornets 11-09, Cavaliers 11-14), both covered. Moneyline entries carry `implied` and `roi`, and `unit` is the
  favored bet ("to win" / "not to win"). football-data.co.uk's robots.txt
  bars ClaudeBot: don't fetch it. MLB: `scripts/mlb_storylines.py`
  (2015-2025, 2020 left out; Retrosheet event files for game context, closing
  moneylines from SportsbookReviewsOnline to 2021 and ESPN core odds after;
  46 tested, 1 at p<0.05 vs 2.2 by chance, 4 shown: Rust, Split the
  doubleheader, Ace vs ace dog, Extra-innings hangover). Live it reads ESPN's
  probable starters, so a late pitching change can change what fires. NCAAB:
  `scripts/ncaab_storylines.py` (games with an AP Top 25 team, 2015-16 to
  2025-26, 2020-21 left out; 79 tested, 5 at p<0.05 vs ~4 by chance, 26
  shown -- the user asked for 20+ at the same bar; several are slices of one
  effect, ranked teams covering 47.3% in the other team's gym; Nail-biters
  and Home skid are WEAK).
  "Lockdown at home" (2026-11-23, from Magic @ Wizards): backs a home team whose
  last two opponents averaged 7+ under the league's points a game, season to date
  (`league_ppg`; both teams 8+ games): 791-671 (54.1%, p=0.002), every counted
  season positive, halves 55.5%/53.0%; on the road 52-53%. Checked apart from
  the momentum rules (51-54/57/60/62) before adding, at the user's request: ~54%
  whether or not the team covered or won its last two (no momentum at all 53.5%),
  and a logistic fit with streaks, ATS form, margin, win %, spread and rest left
  it at p=0.003; vs what those opponents usually score it's weaker (p=0.04).
  Pairing it with a road team that won on hot threes added nothing. Backfilled
  for 2026-27 (`--only=lockdown`; Nov 22 added before that slate was graded):
  8-17 on the season's graded games at backfill.
  Live records: `scripts/storyline_records.py` (after scoring, each run)
  marks each storyline on a finished game `result` hit/miss/push for the
  story's bet (ATS at the slate's line, NBA at statsSpread; soccer/MLB the
  moneyline) and totals them in `data/storylines_record.json`; each script
  adds those to its backtest record (`lib/storyline_live.py`), so records,
  % and the side history leans keep updating (`live` shows the part since
  going live). This season's finished games were backfilled on 2026-11-13
  (`--include-final --backfill`, NBA `--backfill`). Tally weights (the
  user's choice, `weight`): 2 for `STRONG` (the comeback-win fade -- NBA/NFL
  escape artists, CFB held on -- NBA jet lag, MLB rust), 0.5 for `WEAK` (NBA
  body clock; NFL short week after OT, night owls, 1 PM body clock), else 1.
  The NBA/NFL/NCAAB Stats and NBA Totals rules tables add an "All in" column:
  backtest W-L (`backtest_wl` in build_site.py) plus this season.
  Each sport's section has "Storylines — does a bigger lean do better?"
  (backtest per sport in `lib/storyline_buckets.py`, this season's finished
  games from `storyline_strength` in build_site.py, and the two all in; buckets
  of the card's weighted net lean 1 / 1.5-2 / 2.5-3 / 3.5+; ATS, MLB and soccer
  by winner), and each card's Storylines summary shows the game's net lean and
  that bucket's all-in record (`storyNet`/`storyBucketRec` in site/index.html),
  and the agreement table has rows for storylines leaning with/against your
  pick (`sl` on your plays). NBA backtest by net lean: 54.0% / 57.5% / 60.0%
  (2.5-3) / 71.0% (3.5+, 31 games); 3+ all one way 60.7% -- optimistic, since
  each storyline was kept for leaning. Best NBA pairs (20+ games, in-sample):
  ghost town + quiet giant 19-6, payback + prodigal 18-6, schedule loss +
  second battle 56-37.
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

- **Storyline veto: REMOVED 2026-11-16 (the user's call: storylines weren't
  doing much better than the models).** `STORY_VETO_FROM = None` in
  `build_site.py`, so `story_vetoed` is always false and every model pick
  counts again, Nov 13-15 included (the 20 benched picks went 12-8); no
  note on the page (removed 2026-11-18 at the user's request). The code below is kept
  and comes back by setting a date. What it did while it ran:
- **Storyline veto (the user's call, 2026-11-13):** from `STORY_VETO_FROM`
  in `build_site.py` on, a model's side pick (Ledger, Second Opinion, Trend,
  Blowout, NBA/NFL/NCAAB Stats) on a game whose storylines' weighted net lean
  (`storyline_buckets.net_toward_home`, the frozen pre-game tally) points the
  other way sits out (`story_vetoed`): it's left out of every record on the
  page -- scoreboard, by-sport, plays/tiles/charts, rule records, stacked
  rows, the agreement table -- and the pick log shows "Sat out" with what it
  would have done (`sx`/`sxa`/`sxm`); on cards the model's badge shows "Sat
  out" instead of its pick (`satBadge`), it's left off the sides line, and a
  "Sitting out" note explains (`vetoLine`)
  and a "sat out" chip. Each card also lists the models on each side with
  their season win % in that sport (`sidesLine`: ATS, soccer moneyline, from
  `DATA.bySport`, so veto-aware). Your own picks always count; NBA Totals (not a side)
  are unaffected; picks before that date are unchanged. Reason: model picks
  with the storylines went 35-17 and against 31-40 that season to date. The
  slate files keep every pick and `score_slate.py` still grades it; only the
  page's records apply the veto, and the scorecard has a note saying so.

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
game started carry `lt`; nothing on the pages uses it now.

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
Voided picks (2026-11-21, the user's call, option 2 of 3 offered): picks entered
by mistake that the user asks to void after kickoff move from `picks` to
`voided` in `data/mypicks/<date>.json` (the original entry plus `voidedAt`,
`voidNote`), so no record counts them; `lib/results.py` still lists them, "Void"
with a "voided*" tag and the note in Corrections. A pick the user meant to make
but asked for only after kickoff goes in `uncounted` (listed "not counted*",
never graded). First use: 2026-11-21 CFB, Miami, Arizona, Louisville and Boise
State voided (two lost, one won, one at halftime), Utah -7.5 uncounted.

Public results page (`site/results.html`, linked from the pick sheet): every one of
the user's picks, sides and over/unders, graded at the line taken. `lib/results.py`
builds `results.json` / `results.csv` in `build_site.py`. The page and CSV don't
show when a pick was made (the user's call, 2026-11-15; the JSON keeps
`submitted`/`lead` for ordering). Every pick counts and none is labelled late (it
used to flag and leave out picks that reached the repo after the listed start,
but NBA tips ~10 minutes after it and the timestamp is the issue, not the bet).
Intake only blocks final games. Corrections and alternate
lines are labelled. "vs close" (2026-11-15, `close`/`clv` in `lib/results.py`):
points better or worse than the closing line (lines archives; NBA spreads
the slate's statsSpread; an alternate measured from its posted line), with a "Beat the closing line" tile. The pick
sheet warns under an alternate line priced -150 or worse with its break-even
win % (`altwarn`): the user's bought-point picks went 4-4, -$186, vs +$4 at
the posted lines. The repo and Pages site are public, so the picks files and
their commit timestamps are the verification trail. It's the user's record, not
advice, and has a sample-size note (95% range).

Player props (2026-11-17, every sport since 2026-11-18): each game card's pick
row has "Your player props" (`propsInner` in site/index.html): pick a player
(from `DATA.rosters`, saved daily by `scripts/archive_rosters.py` from ESPN team
rosters into `data/raw/rosters/<sport>.json`, NBA sorted by points a game from
the box-score cache; a typed name + team when there's no roster), a stat
(`lib/props.py` STATS per sport: basketball pts/reb/ast/3PM/combos, football
passing/rushing/receiving yards, receptions, TDs..., MLB hits/HR/RBI/runs/H+R+RBI/
batter and pitcher Ks/outs..., soccer goals/assists/shots/SOT), Over/Under, line,
odds (blank = -110) and an optional reason. They go out in the picks issue as
`props`; `intake_picks.py` finds the ESPN event (saved rosters file, else the
scoreboard) and the athlete id (a typed name is matched on the roster, else
graded by name) and saves them under `props` in `data/mypicks/<date>.json`,
keyed `<sport>-espn-<event id>|<athlete id or n:name>|<stat>`, with the reason.
`scripts/grade_props.py` (scoring run) fills `actual`/`result`/`profit` from the
box score once final (`lib/props.flatten_box`/`stat_value`; "void" if he didn't
play). `lib/results.py` lists them (kind "prop", with the reason) and the
results page has a Player props tile and type filter, kept out of the
spread/over-under units. Since 2026-11-19 props count in your record like your
over/unders (the user's call): `prop_log` in build_site.py adds them to
`DATA.plays` as `w: "myprop"` (tl/tr/tp; a void prop has no result), `belongs`
puts them in You, the You card notes how many, and the pick log shows them
(`propLogRow`, "Your prop" / "Your team prop"). Team props (2026-11-19): one
team's number over/under a line -- points, 1st/2nd half, 1st quarter, 3PM,
rebounds..., football yards/first downs/turnovers/sacks, MLB runs/first 5/hits/
HR/pitcher Ks, soccer goals/1H goals/corners/shots/SOT/cards (`TEAM_STATS` and
`team_value` in lib/props.py: the score, its periods, or the team box score;
soccer's box comes from the league's own summary). The card's "Add a team
prop" form sends `playerId: "t:home"/"t:away"`; intake saves `kind: "team"`,
`teamSide`, keyed `<sport>-espn-<eid>|t:<side>|<stat>`; grade_props.py grades
them. A prop entered by hand is tagged "entered by hand*" on
the results page (not "corrected*"); the CSV type is "player prop". First prop (entered by hand before the form existed):
Daniss Jenkins under 17 points +100, 2026-11-17 Pistons @ Spurs.

Don't write picks into game objects in `data/<sport>/` (no `userPick`,
`yourPick`, `myPick` fields) and don't ask the user to tell you their picks.
Grading of their picks happens in `scripts/lib/picks.py` from the game's final
score and stored lines: ATS and moneyline at $100 flat, with NFL, CFB and NCAAB picks on a
team getting more than 7 points counted ATS only. In any sport, a pick priced
-400 or shorter is left out of the moneyline record and profit (win or lose);
this applies to the Ledger and Second Opinion too (`scripts/lib/grading.py`).
