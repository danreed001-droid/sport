---
name: diamond-ledger-generate
description: Generate today's Diamond Ledger slate (NFL, CFB, MLB, NBA, or EPL) for this repo by researching the matchups yourself (WebSearch/WebFetch) and pushing the result to GitHub. Use when asked to "generate today's picks", "run Diamond Ledger", or similar for this repo. Grading past slates is a separate, fully automated GitHub Action (.github/workflows/diamond-ledger.yml) and does not need this skill.
---

# Diamond Ledger — generate today's slate

This repo's Diamond Ledger pipeline deliberately does NOT call the Claude/Anthropic
API from GitHub Actions. Scoring past slates (STEP 1) is fully deterministic and
runs unattended via `.github/workflows/diamond-ledger.yml`. Generating a new slate
(STEP 2) needs real research and judgment, so it's done by you, a live Claude Code
session, using your own WebSearch/WebFetch tools — then you commit and push the
result yourself. That's this skill.

## Steps

For each sport you're asked to generate (`nfl`, `cfb`, `mlb`, `nba`, `epl`):

1. **Prep** — fetch today's ESPN matchups and known stats:
   ```
   python scripts/generate_slate.py <sport> prep /tmp/dl_prep_<sport>.json
   ```
   If it prints "doc already exists" or "no games found today", stop here for that
   sport — there's nothing to generate. Otherwise it writes a JSON file containing:
   - `espnGames`: the matchups with their ESPN-sourced known facts (schedule,
     moneylines, PD/g or run-diff, records) — do NOT re-derive or override these.
   - `systemPrompt` / `userPrompt`: the exact research brief and JSON schema for
     this sport, ported from that sport's own Diamond Ledger rules (or, for NBA/EPL,
     a user-approved analogous design — see the corresponding `lib/<sport>_model.py`
     docstring for what's tentative/experimental about it).

2. **Research** — read the `userPrompt` (and `systemPrompt`) from that file and do
   the actual research it asks for, using WebSearch/WebFetch, exactly as if you were
   Claude answering that prompt yourself (you are). Follow every rule stated in it:
   null instead of fabricating, cbssports.com as the tiebreaker source, fact
   discipline (double-check a claim names the right team before writing it down),
   etc. Write your findings as a single JSON object matching the schema shown in
   `userPrompt`, saved to its own file, e.g. `/tmp/dl_research_<sport>.json`.

3. **Apply** — run the deterministic tiering/screening/category-vote logic against
   your research:
   ```
   python scripts/generate_slate.py <sport> apply /tmp/dl_prep_<sport>.json /tmp/dl_research_<sport>.json
   ```
   This writes `data/<collection>/<date>.json` (collection per `lib/sports.py`,
   e.g. `data/nfl/2026-09-26.json`). It refuses to overwrite an existing doc for
   that date, so it's safe to re-run.

4. **Push** — after generating every sport you were asked for, commit and push:
   ```
   git add data/
   git commit -m "Diamond Ledger: generate <date> slate(s)"
   git push
   ```
   Only commit real generated docs — never hand-edit a `pick`/`altPick`/reasoning
   field after the fact once a day's doc exists; a rule change applies starting
   with the next date, per the same policy the MLB/CFB skills state explicitly.

## Notes

- Each sport's exact rules (screens, tiers, category list, veto thresholds) live in
  `scripts/lib/<sport>_model.py` as plain, auditable Python — read the relevant one
  if you need to know precisely how a pick or confidence tier is computed, rather
  than re-deriving it from memory of the original skills.
- NFL and CFB additionally track a prior-game trend check and a blowout-win
  regression check (`altTrendFavors`/`altBlowoutFavors`); MLB has neither; NBA has
  a simplified back-to-back/blowout check (`altRestBlowoutFavors`); EPL has none.
- EPL's `pick`/`altPick` can be `"Home"`, `"Away"`, or `"Draw"` — a real 3-way
  market. There's no spread/ATS for EPL, only moneyline.
- If a required stat genuinely can't be found after searching, use `null` in your
  research JSON — the deterministic code treats missing inputs as a skip/pass,
  never a guess.
