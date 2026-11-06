"""Save Sports Reference's men's college basketball school ratings to
data/raw/ncaab/ratings/, for the Basketball Routine's NCAAB Ledger.

The Ledger needs each team's PD/g and adjusted offensive and defensive
efficiency with national ranks. The sites the Routine used to look these up
on don't serve it: KenPom is paywalled, BartTorvik's robots.txt bars
ClaudeBot (and all *.json), and TeamRankings answers with client errors, so
on 2026-11-06 every NCAAB game was skipped "no-data". Sports Reference's
ratings page (allowed by its robots.txt) has all of it for every Division I
team: points per game, points allowed, MOV (= PD/g), SOS, SRS and adjusted
ORtg/DRtg/NRtg per 100 possessions (the same scale as KenPom's). The Routine
reads the saved copy through raw.githubusercontent.com.

Files:
- <YYYY-MM-DD>.json: this season's table, as of that US Eastern date.
  Fetched at most once a day: once a file fetched after 8 AM ET exists for
  today (last night's late games are in by then), later runs leave it alone.
- final-<season>.json: last season's final table, for the Ledger's
  "blend with last season's final" rule. Saved once.

A season is named by the year it ends (2026-27 is 2027), as on the site.
Ranks are among teams that have played (adjusted ORtg: higher is better;
adjusted DRtg: lower is better), with "n" the number of ranked teams, so the
Ledger's offense percentile is (n - rank) / (n - 1) x 100.

The daily file also applies the Ledger's own early-season rule, so every run
uses it the same way: a team with 0 games uses last season's final; through
its first 10 games, a 50/50 blend of this season and last season's final;
after that, this season only. That gives "ledgerMov" (PD/g), "ledgerORtg"
and "ledgerDRtg" with "ledgerBasis", and "ledgerORtgRank"/"ledgerDRtgRank"
ranked among the "ledgerN" teams that have a value.
"""
import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timezone
from html import unescape
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import store  # noqa: E402

OUT_DIR = os.path.join(store.REPO_ROOT, "data", "raw", "ncaab", "ratings")
URL = "https://www.sports-reference.com/cbb/seasons/men/{season}-ratings.html"
UA = "diamond-ledger/1.0 (+https://github.com/danreed001-droid/sport)"
ET = ZoneInfo("America/New_York")
FRESH_AFTER_HOUR_ET = 8

NUM = {"ap_rank": "apRank", "wins": "wins", "losses": "losses", "pts_per_g": "ppg",
       "opp_pts_per_g": "oppPpg", "mov": "mov", "sos": "sos", "srs_off": "srsOff",
       "srs_def": "srsDef", "srs": "srs", "off_rtg": "adjORtg", "def_rtg": "adjDRtg",
       "net_rtg": "adjNRtg"}


def fetch(season):
    req = urllib.request.Request(URL.format(season=season), headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _num(s):
    s = s.strip().lstrip("+")
    try:
        return float(s) if s else None
    except ValueError:
        return None


def parse(html):
    """The ratings table's rows as dicts. The adjusted ORtg/DRtg/NRtg are the
    page's off_rtg/def_rtg/net_rtg columns (under its "Adjusted" header)."""
    teams = []
    for row in re.findall(r'<tr\s*>\s*<th scope="row".*?</tr>', html, re.S):
        cells = dict(re.findall(r'data-stat="([a-z_]+)"[^>]*>(.*?)</t[dh]>', row, re.S))
        name = unescape(re.sub(r"<[^>]+>", "", cells.get("school_name", ""))).replace("\xa0", " ").strip()
        if not name:
            continue
        t = {"school": name, "conf": unescape(re.sub(r"<[^>]+>", "", cells.get("conf_abbr", ""))).strip()}
        for stat, key in NUM.items():
            t[key] = _num(unescape(re.sub(r"<[^>]+>", "", cells.get(stat, ""))))
        if t["apRank"] is not None:
            t["apRank"] = int(t["apRank"])
        t["games"] = int((t["wins"] or 0) + (t["losses"] or 0))
        teams.append(t)
    return teams


def rank(teams):
    played = [t for t in teams if t["games"] > 0 and t["adjORtg"] is not None and t["adjDRtg"] is not None]
    for key, rkey, best_high in (("adjORtg", "adjORtgRank", True), ("adjDRtg", "adjDRtgRank", False)):
        order = sorted(played, key=lambda t: t[key], reverse=best_high)
        prev, r = None, 0
        for i, t in enumerate(order, 1):
            if t[key] != prev:
                r, prev = i, t[key]
            t[rkey] = r
    for t in teams:
        t.setdefault("adjORtgRank", None)
        t.setdefault("adjDRtgRank", None)
    return len(played)


def ledger_inputs(teams, last):
    """The Ledger's blend of this season and last season's final (see the
    module docstring), ranked across every team that has a value."""
    prev = {t["school"]: t for t in last}
    for t in teams:
        p = prev.get(t["school"])
        cur_ok = t["games"] > 0 and None not in (t["mov"], t["adjORtg"], t["adjDRtg"])
        prev_ok = p is not None and None not in (p["mov"], p["adjORtg"], p["adjDRtg"])
        if cur_ok and (t["games"] > 10 or not prev_ok):
            basis, w = ("this season" if t["games"] > 10 else "this season only (no final last season)"), 1.0
        elif cur_ok:
            basis, w = f"50/50 blend: {t['games']} game(s) this season + last season's final", 0.5
        elif prev_ok:
            basis, w = "last season's final (0 games this season)", 0.0
        else:
            t.update(ledgerBasis=None, ledgerMov=None, ledgerORtg=None, ledgerDRtg=None)
            continue
        for key, out in (("mov", "ledgerMov"), ("adjORtg", "ledgerORtg"), ("adjDRtg", "ledgerDRtg")):
            t[out] = t[key] if w == 1 else p[key] if w == 0 else round(w * t[key] + (1 - w) * p[key], 2)
        t["ledgerBasis"] = basis
    have = [t for t in teams if t.get("ledgerORtg") is not None]
    for key, rkey, best_high in (("ledgerORtg", "ledgerORtgRank", True), ("ledgerDRtg", "ledgerDRtgRank", False)):
        prev_v, r = None, 0
        for i, t in enumerate(sorted(have, key=lambda t: t[key], reverse=best_high), 1):
            if t[key] != prev_v:
                r, prev_v = i, t[key]
            t[rkey] = r
    for t in teams:
        t.setdefault("ledgerORtgRank", None)
        t.setdefault("ledgerDRtgRank", None)
    return len(have)


def save(path, season, label, teams, n, ledger_n=None):
    doc = {"season": season, "label": label, "source": URL.format(season=season),
           "fetchedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "n": n, "note": "mov = PD/g. adjORtg/adjDRtg: adjusted points scored/allowed per 100 "
                           "possessions; ranks among the n teams that have played.",
           "teams": teams}
    if ledger_n is not None:
        doc["ledgerN"] = ledger_n
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=1)
        f.write("\n")
    os.replace(tmp, path)


def fresh(path, today):
    try:
        with open(path, encoding="utf-8") as f:
            at = datetime.fromisoformat(json.load(f)["fetchedAt"]).astimezone(ET)
    except (OSError, ValueError, KeyError):
        return False
    return at.date() == today and at.hour >= FRESH_AFTER_HOUR_ET


def main():
    now = datetime.now(ET)
    today = now.date()
    season = today.year + 1 if today.month >= 8 else today.year
    os.makedirs(OUT_DIR, exist_ok=True)

    final = os.path.join(OUT_DIR, f"final-{season - 1}.json")
    if not os.path.exists(final):
        teams = parse(fetch(season - 1))
        if len(teams) < 300:
            sys.exit(f"{season - 1} final: only {len(teams)} teams parsed -- page layout changed? Not saved.")
        n = rank(teams)
        save(final, season - 1, f"{season - 2}-{str(season - 1)[2:]} final", teams, n)
        print(f"Saved {season - 2}-{str(season - 1)[2:]} final ratings: {len(teams)} teams.")

    path = os.path.join(OUT_DIR, f"{today.isoformat()}.json")
    if fresh(path, today):
        print(f"{today}: ratings already saved after {FRESH_AFTER_HOUR_ET} AM ET -- left as is.")
        return
    teams = parse(fetch(season))
    if len(teams) < 300:
        sys.exit(f"{today}: only {len(teams)} teams parsed -- page layout changed? Not saved.")
    n = rank(teams)
    with open(final, encoding="utf-8") as f:
        ledger_n = ledger_inputs(teams, json.load(f)["teams"])
    save(path, season, f"{season - 1}-{str(season)[2:]} as of {today.isoformat()}", teams, n, ledger_n)
    print(f"{today}: saved {season - 1}-{str(season)[2:]} ratings, {len(teams)} teams ({n} have played; "
          f"Ledger inputs for {ledger_n}).")


if __name__ == "__main__":
    main()
