# Diamond Ledger — repo notes for Claude

`main` is the default branch and the only long-lived one. Work on a branch and
merge into `main`; the scoring, pick-intake and Pages workflows all run from it.

## Always push after generating or scoring a daily slate

For every daily Diamond Ledger routine (NFL, CFB, MLB, NBA, NCAAB, EPL): after
generating today's picks (STEP 2) or scoring a past slate (STEP 1), commit the
resulting `data/<collection>/<date>.json` file(s) and push before ending the
run, whether it was triggered live or on a schedule. The repo is the source of
truth the pick sheet reads from. Mirror the slate exactly as it was written to
the ledger database; don't generate a second, different slate for a date that
already has one.

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
