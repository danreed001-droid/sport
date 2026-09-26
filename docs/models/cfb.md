# College football model (Ledger + Second Opinion)

A copy of the rules written inline in the "Diamond Ledger — College Football"
Routine (trig_0114idHR9NqEyCDaeqi3nNQY), which generates the slate. The daily
research check reads this file, because its sessions can't read another
Routine's prompt. If the Routine's rules change, update this file too.

## Scope

Only FBS games that involve at least one team in the current AP Top 25. If the
opponent is an FCS team, the game is included, but the Ledger gets confidence
"skip", pick null, skipped true, skipReason "fcs" (the Second Opinion may
still pick or pass).

## Inputs

Kickoff times, expected starting QBs, both teams' season point differential
per game (PD/g), pregame moneylines, and the point spread with its odds for
both teams. Offensive yards per play (YPP) and its national FBS rank. Offense
percentile = (N - rank) / (N - 1) × 100, where N is the number of FBS teams in
that ranking (currently 134). A team with fewer than 2 FBS games still uses its
numbers, with a note in statLines. A genuinely unavailable stat → skipReason
"no-data".

## Ledger

For each game, in order:

- **Screen 1 (off-gap):** if |awayPct - homePct| < 30 → confidence "skip",
  pick null, skipped true, skipReason "off-gap"; stop for this game.
- **Model.** Point differential is the non-overridable determinant of pick
  direction; nothing flips it.
  - (a) pick = the team with the higher PD/g.
  - (b) tier from the PD/g gap: < 7 "toss-up"; 7–17 "lean"; > 17 "solid".
  - (c) if YPP favors the non-picked team, soften one notch ("solid" is
    immune, "lean" → "toss-up", "toss-up" stays).
  - (d) if both QB efficiency ratings exist and the picked team's is lower,
    soften one more notch by the same rule.
- **Screen 2 (QB veto,** no exemption for "solid"; only if both ratings
  exist): |diff| <= 10.0 → no pick, "qb-close"; else if the picked team's QB
  efficiency is lower → no pick, "qb-veto"; else keep.

## Second Opinion

A category vote that shares one input with the Ledger (PD/g). For each of the
9 categories, decide which team it favors on one concrete, checkable fact, or
mark it neutral:

1. Scoring margin: season PD/g; favors the better PD/g.
2. Rest: off a bye, short week for a weeknight game.
3. Travel: cross-country trip, time-zone change, early kickoff for a West
   Coast team, altitude.
4. Injuries/Lineup: QB or key starter out or returning, transfer eligibility,
   suspensions.
5. Form: last 3 games, including close escapes against lesser teams.
6. Motivation/Spot: rivalry, lookahead, letdown, revenge, night game or big
   home crowd.
7. Weather/Venue: wind, rain, heat, notable home-field environment.
8. Market: line movement since open, reverse line movement against public
   betting %.
9. Matchup splits: a specific unit-vs-unit mismatch.

No other Ledger stat (YPP, QB efficiency) may be used in categories 2–9.

**Rule:** tally the categories favoring each team (neutral counts for
neither). A lead of 4 or more picks that team: a 4-category lead is "lean",
5+ is "strong". A lead of 3 or fewer is a pass: altConfidence "pass",
altPick null. Unverifiable facts are neutral. Passing on most of the slate is
normal.

Stored per game: altPick (exact team name or null), altConfidence
("strong" | "lean" | "pass"), altCategoryTally (e.g. "5-1"), altReasons (one
string per non-neutral category, naming the category and the team it favors,
including categories favoring the non-picked team).

## Game fields

away, home (for neutral sites, the designated home team plus "Neutral site"
in statLines), awayRank, homeRank, time ("3:30 PM ET"), awayQB, homeQB,
awayPDpg, homePDpg, awayYPP, homeYPP, offGap, awayQBEff, homeQBEff,
awayMoneyline, homeMoneyline, awaySpread, homeSpread, awaySpreadOdds,
homeSpreadOdds, statLines (2–4 short "away vs home" strings), pick,
confidence, skipped, skipReason, altPick, altConfidence, altCategoryTally,
altReasons, plus null result fields. Moneylines are American odds; spreads are
signed from each team's side with American odds, from a mainstream book or
aggregator. Null only when genuinely not findable; never estimated.
