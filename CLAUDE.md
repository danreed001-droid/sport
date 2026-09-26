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
  that haven't started, marks each change with `auditNote`/`auditChanges`, and
  commits its report to `data/audits/<date>.md` plus the mirrored slates.
  Nothing else changes a pick after it's generated.
- **Grading:** `.github/workflows/diamond-ledger.yml` grades NFL, CFB, MLB,
  NBA and NCAAB every morning from ESPN (`fetch_scores.py` then
  `score_slate.py`). The sport Routines no longer grade. Soccer is the
  exception: its Routine still grades in the database and the sync brings
  those results over.

## The user's own picks come from the pick sheet, not from Claude

The GitHub Pages pick sheet (`site/index.html`, built by `scripts/build_site.py`,
deployed by `.github/workflows/pages.yml`) is where the user makes picks. They
pick a side and score each Second Opinion reason (A away, a half away, N
neutral, h half home, H home); a tally margin of 2.5+ sets the pick. Submitting
opens a `picks YYYY-MM-DD` issue, and `.github/workflows/pick-intake.yml` runs
`scripts/intake_picks.py` to commit them to `data/mypicks/<date>.json`.

Don't write picks into game objects in `data/<sport>/` (no `userPick`,
`yourPick`, `myPick` fields) and don't ask the user to tell you their picks.
Grading of their picks happens in `scripts/lib/picks.py` from the game's final
score and stored lines: ATS and moneyline at $100 flat, with NFL/CFB picks on a
team getting more than 7 points counted ATS only.
