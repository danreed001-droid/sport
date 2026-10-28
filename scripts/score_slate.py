#!/usr/bin/env python3
"""STEP 1: grade any unscored past slates for a given sport using the
ESPN-derived archive in data/raw/master_<sport>_scores.csv (see
fetch_scores.py). For two-way sports (NFL/CFB/MLB/NBA) this independently
grades the Ledger pick, the Second Opinion pick, and — where the sport's
model tracks them — the trend/blowout checks' own named favorites, so each
signal's real hit rate is measurable on its own. Three-way sports (soccer)
dispatch to that sport's own 3-way grading function instead.
"""
import csv
import difflib
import importlib
import os
import re
import sys
import unicodedata
from datetime import date, datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))
from lib import sports, store  # noqa: E402
from lib.grading import grade_pick  # noqa: E402
from lib.picks import BIG_DOG_LIMIT, BIG_DOG_SPORTS  # noqa: E402
from lib.dates import today_et_str  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# A game with no score row at all on its slate date this many days later was
# moved or postponed: it's graded as void (no result) so the rest of its
# slate isn't held back forever.
VOID_AFTER_DAYS = 4


def _csv_path(sport_key):
    return os.path.join(REPO_ROOT, "data", "raw", f"master_{sport_key}_scores.csv")


def load_scores_by_date(sport_key):
    by_date = {}
    path = _csv_path(sport_key)
    if not os.path.exists(path):
        return by_date
    with open(path, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            by_date.setdefault(row["Date"], []).append(row)
    return by_date


def _num(v):
    if v in (None, "", "-"):
        return None
    try:
        return float(v)
    except ValueError:
        return None


def _clock(s):
    """'1:05 PM ET' / '01:05 PM' -> '1:05 PM'; anything unparseable -> ''."""
    s = (s or "").upper().replace("EDT", "").replace("EST", "").replace("ET", "").strip()
    parts = s.split()
    if len(parts) != 2 or ":" not in parts[0] or parts[1] not in ("AM", "PM"):
        return ""
    h, m = parts[0].split(":", 1)
    return f"{int(h)}:{m} {parts[1]}" if h.isdigit() and m.isdigit() else ""


def _minutes(s):
    c = _clock(s)
    if not c:
        return None
    hm, ap = c.split()
    h, m = (int(v) for v in hm.split(":"))
    return (h % 12 + (12 if ap == "PM" else 0)) * 60 + m


def find_match(scores_for_date, g, games=None):
    game_id = g.get("espnGameId")
    if game_id:
        for row in scores_for_date:
            if row.get("Game_ID") == game_id:
                return row
    away, home = g["away"], g["home"]
    matches = [r for r in scores_for_date if r["Away_Team"] == away and r["Home_Team"] == home]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:  # doubleheader: pair games by start order (game 2's time often moves)
        twins = sorted((x for x in (games or [g]) if x["away"] == away and x["home"] == home), key=lambda x: _minutes(x.get("time")))
        rows = sorted(matches, key=lambda r: _minutes(r.get("Start_ET")))
        if len(twins) != len(rows) or any(_minutes(r.get("Start_ET")) is None for r in rows) or any(_minutes(x.get("time")) is None for x in twins):
            return None
        return rows[twins.index(g)]
    for row in scores_for_date:
        if (away in row["Away_Team"] or row["Away_Team"] in away) and (home in row["Home_Team"] or row["Home_Team"] in home):
            return row
    return None


# Common short names a slate may use for a club ESPN lists differently.
TEAM_ALIASES = {
    "nycfc": "new york city", "chivas": "guadalajara", "psg": "paris saint germain",
    "lafc": "los angeles", "sporting kc": "sporting kansas city", "man city": "manchester city",
    "man united": "manchester united", "man utd": "manchester united", "spurs": "tottenham hotspur",
    "inter": "internazionale", "atletico madrid": "atletico de madrid", "bayern": "bayern munich",
    "inter milan": "internazionale", "olympique lyonnais": "lyon", "lyonnais": "lyon",
    "wolves": "wolverhampton wanderers", "forest": "nottingham forest",
    "west brom": "west bromwich albion", "sporting lisbon": "sporting cp",
    "bayern munchen": "bayern munich", "fc bayern munich": "bayern munich",
    "atletico mineiro": "atletico mg", "borussia monchengladbach": "monchengladbach",
}
_FILLER = {"fc", "cf", "sc", "afc", "cd", "club", "de", "the", "ac", "ssc", "as", "sv", "fk", "sk", "vfb", "bsc"}

# Geographic name variants (the German/local spelling vs. the English one
# ESPN commonly uses, or vice versa) — safe as a plain word swap, unlike a
# club nickname like "inter", which is also a fragment of unrelated clubs
# (Inter Miami, Deportivo Inter...) and must stay a whole-string alias only.
_CITY_WORDS = {"koln": "cologne", "munchen": "munich"}


def _norm_team(name):
    s = (name or "").replace("ø", "o").replace("Ø", "O").replace(".", "")
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = " ".join(_CITY_WORDS.get(t, t) for t in s.split())
    s = TEAM_ALIASES.get(s, s)
    return frozenset(t for t in s.split() if t not in _FILLER) or frozenset(s.split())


def _same_team(a, b):
    na, nb = _norm_team(a), _norm_team(b)
    return bool(na and nb) and (na == nb or na <= nb or nb <= na)


def _team_similarity(a, b):
    """0-1 string similarity on normalized, space-joined team names — a
    last-resort fallback for name variants token matching can't bridge
    (e.g. "Atlético Mineiro" vs "Atlético-MG", "Inter Milan" vs
    "Internazionale", "Hapoel Beer Sheva" vs "Hapoel Be'er")."""
    sa, sb = " ".join(sorted(_norm_team(a))), " ".join(sorted(_norm_team(b)))
    if not sa or not sb:
        return 0.0
    return difflib.SequenceMatcher(None, sa, sb).ratio()


FUZZY_THRESHOLD = 0.6
FUZZY_MARGIN = 0.08  # best match must clear the runner-up by this much


def find_match_loose(scores_for_date, g):
    """Fallback for slates whose names differ from ESPN's (accents, "FC",
    nicknames, abbreviations) or whose home/away is reversed. Returns (row,
    swapped) where swapped means the slate's away team is ESPN's home team,
    or (None, False). Tries an unambiguous token-subset match first, then an
    unambiguous fuzzy-string match (both sides must clear FUZZY_THRESHOLD,
    and the combined score must beat every other candidate by FUZZY_MARGIN,
    so a near-tie refuses rather than guesses)."""
    hits = []
    for row in scores_for_date:
        if _same_team(g["away"], row["Away_Team"]) and _same_team(g["home"], row["Home_Team"]):
            hits.append((row, False))
        elif _same_team(g["away"], row["Home_Team"]) and _same_team(g["home"], row["Away_Team"]):
            hits.append((row, True))
    if len(hits) == 1:
        return hits[0]
    if hits:
        return (None, False)  # ambiguous token match — don't fall through to fuzzy

    scored = []
    for row in scores_for_date:
        for swapped, (away_row, home_row) in (
            (False, (row["Away_Team"], row["Home_Team"])),
            (True, (row["Home_Team"], row["Away_Team"])),
        ):
            sa, sh = _team_similarity(g["away"], away_row), _team_similarity(g["home"], home_row)
            if sa >= FUZZY_THRESHOLD and sh >= FUZZY_THRESHOLD:
                scored.append((sa + sh, row, swapped))
    if not scored:
        return (None, False)
    scored.sort(key=lambda x: -x[0])
    if len(scored) > 1 and scored[0][0] - scored[1][0] < FUZZY_MARGIN:
        return (None, False)  # two candidates too close to trust either
    _, row, swapped = scored[0]
    return (row, swapped)


def is_resolved(status):
    s = (status or "").strip().lower()
    return (s.startswith("final") or s.startswith("ft") or s == "aet"
            or "postponed" in s or "cancel" in s)


def went_past_90(status):
    """Soccer matches decided in extra time or on penalties: a 3-way
    moneyline settles on the 90-minute score, which the final score doesn't
    give, so these are left ungraded."""
    s = (status or "").strip().lower()
    return s == "aet" or "pen" in s


def grade_named(g, team, away_score, home_score, big_dog_limit=10):
    """Two-way grading: any named team (pick, altPick, altTrendFavors,
    altBlowoutFavors, ...) against a finished game, using that team's own
    stored odds/spread."""
    if team == g["away"]:
        return grade_pick(team, away_score, home_score, g.get("awayMoneyline"), g.get("awaySpread"), g.get("awaySpreadOdds"), big_dog_limit)
    if team == g["home"]:
        return grade_pick(team, home_score, away_score, g.get("homeMoneyline"), g.get("homeSpread"), g.get("homeSpreadOdds"), big_dog_limit)
    return {"correct": None, "pickReturn": None, "pickCover": None, "pickSpreadReturn": None}


TWO_WAY_SIGNAL_FIELDS = [
    ("pick", "correct", "pickReturn", "pickCover", "pickSpreadReturn"),
    ("altPick", "altCorrect", "altReturn", "altCover", "altSpreadReturn"),
    ("altTrendFavors", "altTrendCorrect", "altTrendReturn", "altTrendCover", "altTrendSpreadReturn"),
    ("altBlowoutFavors", "altBlowoutCorrect", "altBlowoutReturn", "altBlowoutCover", "altBlowoutSpreadReturn"),
    ("altRestBlowoutFavors", "altRestBlowoutCorrect", "altRestBlowoutReturn", "altRestBlowoutCover", "altRestBlowoutSpreadReturn"),
    ("statsFavors", "statsCorrect", "statsReturn", "statsCover", "statsSpreadReturn"),
    ("nflStatsFavors", "nflStatsCorrect", "nflStatsReturn", "nflStatsCover", "nflStatsSpreadReturn"),
]


def grade_two_way_game(g, away_score, home_score, big_dog_limit=10):
    for pick_field, correct_field, return_field, cover_field, spread_return_field in TWO_WAY_SIGNAL_FIELDS:
        if pick_field not in g:
            continue  # this sport's model doesn't track this signal
        graded = grade_named(g, g.get(pick_field), away_score, home_score, big_dog_limit)
        g[correct_field] = graded["correct"]
        g[return_field] = graded["pickReturn"]
        g[cover_field] = graded["pickCover"]
        g[spread_return_field] = graded["pickSpreadReturn"]


def main(sport_key):
    cfg = sports.get(sport_key)
    today = today_et_str()
    scores_by_date = load_scores_by_date(sport_key)
    docs = store.list_docs(cfg["collection"])
    # A slate can arrive already graded from the ledger database but carry an
    # NBA/NFL Stats pick this repo added that nobody has graded yet; regrade it
    # (idempotent for everything else).
    def needs_stats_grade(doc):
        return any((g.get("statsFavors") and "statsCorrect" not in g)
                   or (g.get("nflStatsFavors") and "nflStatsCorrect" not in g) for g in doc.get("games", []))

    pending = sorted(
        [(d, doc) for d, doc in docs if (not doc.get("scored") or needs_stats_grade(doc)) and d < today],
        key=lambda x: x[0],
    )

    if not pending:
        print(f"[{cfg['label']}] no unscored past slates to grade.")
        return

    model = importlib.import_module(f"lib.{cfg['model']}") if cfg["kind"] == "three_way" else None

    for date_str, doc in pending:
        games = doc.get("games", [])
        scores_for_date = scores_by_date.get(date_str, [])
        all_resolved = True
        missing = []
        matches = {}

        swapped = {}
        voided = set()
        age_days = (date.fromisoformat(today) - date.fromisoformat(date_str)).days
        for i, g in enumerate(games):
            row = find_match(scores_for_date, g, games)
            if row is None:
                row, swapped[i] = find_match_loose(scores_for_date, g)
            if row is None and scores_for_date and age_days >= VOID_AFTER_DAYS:
                voided.add(i)
                matches[i] = {"Away_Score": None, "Home_Score": None, "Status": "Not played on this date"}
                continue
            if row is None or not is_resolved(row.get("Status")):
                all_resolved = False
                missing.append(f"{g['away']} @ {g['home']}")
                continue
            matches[i] = row

        if not all_resolved:
            print(f"[{cfg['label']}] {date_str}: leaving unscored, missing/incomplete: {missing}")
            continue

        for i, g in enumerate(games):
            row = matches[i]
            away_score = _num(row.get("Away_Score"))
            home_score = _num(row.get("Home_Score"))
            if swapped.get(i):  # slate lists this match the other way round
                away_score, home_score = home_score, away_score
            if cfg["kind"] == "three_way" and went_past_90(row.get("Status")):
                away_score = home_score = None
            if i in voided:
                g["gradeNote"] = "Not played on this date (moved or postponed); no result."
            g["awayScore"], g["homeScore"] = away_score, home_score

            if cfg["kind"] == "three_way":
                g.update(model.grade_game(g, away_score, home_score))
            else:
                grade_two_way_game(g, away_score, home_score, BIG_DOG_LIMIT if sport_key in BIG_DOG_SPORTS else 10)

        doc["scored"] = True
        doc["scoredAt"] = datetime.now(timezone.utc).isoformat()
        store.write_doc(cfg["collection"], date_str, doc)
        print(f"[{cfg['label']}] {date_str}: scored {len(games)} game(s).")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "nfl")
