#!/usr/bin/env python3
"""Is there a game the scoring run should have graded by now but hasn't?

Used by .github/workflows/score-chaser.yml, the backup for GitHub's hourly
schedule (which runs late and sometimes skips for hours: no run between
10:31 PM ET on 2026-11-18 and the next morning left that night's games
ungraded). A game counts as pending when it started 2 to 14 hours ago and its
slate doesn't have it graded yet (`is_final`). The 14-hour cap keeps a
postponed or never-finished game from chasing forever; the health check and
hand entry cover anything older.

Prints what's pending and writes `pending=true|false` to $GITHUB_OUTPUT.
"""
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import sports, store  # noqa: E402
from lib.picks import is_final  # noqa: E402

ET = ZoneInfo("America/New_York")
ZONES = {"ET": "America/New_York", "EST": "America/New_York", "EDT": "America/New_York",
         "CT": "America/Chicago", "CST": "America/Chicago", "CDT": "America/Chicago",
         "MT": "America/Denver", "PT": "America/Los_Angeles", "AST": "America/Halifax",
         "GMT": "Europe/London", "BST": "Europe/London", "UTC": "UTC", "WET": "Europe/Lisbon",
         "WEST": "Europe/Lisbon", "CET": "Europe/Paris", "CEST": "Europe/Paris",
         "TRT": "Europe/Istanbul", "BRT": "America/Sao_Paulo"}
TIME = re.compile(r"(\d{1,2}):(\d{2})\s*([AP]M)\s*([A-Z]{2,4})?", re.I)

MIN_AGE = timedelta(hours=2)    # a game needs about this long to finish
MAX_AGE = timedelta(hours=14)   # stop chasing after this


def start_of(date_str, time_str):
    """The game's start as an aware datetime, or None when the time can't be read."""
    m = TIME.search(time_str or "")
    if not m:
        return None
    h, mi, ap, zone = int(m.group(1)) % 12, int(m.group(2)), m.group(3).upper(), (m.group(4) or "ET").upper()
    if ap == "PM":
        h += 12
    tz = ZoneInfo(ZONES.get(zone, "America/New_York"))
    y, mo, d = (int(x) for x in date_str.split("-"))
    return datetime(y, mo, d, h, mi, tzinfo=tz)


def pending(now=None):
    now = now or datetime.now(timezone.utc)
    today = now.astimezone(ET).date()
    days = {(today - timedelta(days=k)).isoformat() for k in (0, 1)}
    out = []
    for sport, cfg in sports.SPORTS.items():
        for date_str, doc in store.list_docs(cfg["collection"]):
            if date_str not in days:
                continue
            for g in doc.get("games", []):
                start = start_of(date_str, g.get("time"))
                if start is None or is_final(doc, g):
                    continue
                age = now - start
                if MIN_AGE <= age <= MAX_AGE:
                    out.append(f"{sport} {date_str} {g.get('away')} @ {g.get('home')} (started {age.total_seconds() / 3600:.1f}h ago)")
    return out


def main():
    items = pending()
    print("\n".join(items) if items else "Nothing waiting to be graded.")
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as f:
            f.write(f"pending={'true' if items else 'false'}\n")


if __name__ == "__main__":
    main()
