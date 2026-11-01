#!/usr/bin/env python3
"""Health check for the pick sheet, run every few hours by
.github/workflows/health.yml. It repairs what it can and opens an issue
(GitHub emails the repo owner) for what it can't:

  1. Re-enables the scoring and Pages workflows if GitHub switched them off.
  2. Re-runs scoring if it hasn't succeeded in 3+ hours, and rebuilds the
     site if the live data.json is 6+ hours old.
  3. Opens (or updates) one "Health check" issue when something is still
     wrong: no successful scoring run in 12+ hours, 3+ failed runs in a row,
     a live site 12+ hours old, a step failing for 2+ days, or a past slate
     still ungraded at noon ET the day after (the issue names the games
     holding it up, so their finals can be entered by hand). Closes it once
     everything is healthy again.

Needs the gh CLI with GH_TOKEN, and GITHUB_REPOSITORY (both set in Actions).
"""
import json
import os
import subprocess
import sys
import urllib.request
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(__file__))
from lib import sports, store  # noqa: E402
from lib.dates import ET, now_et, today_et_str  # noqa: E402
import score_slate  # noqa: E402

# Every slate's games are over by early morning ET; one still ungraded at
# this hour the next day is stuck, not just waiting for the next run.
GRADE_BY_HOUR_ET = 12
OVERDUE_LOOKBACK_DAYS = 45

REPO = os.environ.get("GITHUB_REPOSITORY", "danreed001-droid/sport")
OWNER = REPO.split("/")[0]
SCORING, PAGES = "diamond-ledger.yml", "pages.yml"
ISSUE_TITLE = "Health check: the pick sheet needs attention"


def gh(*args):
    """stdout of a gh command, or None if it failed (logged, never fatal).
    `gh api` takes the repo in its path; every other command gets --repo."""
    cmd = ["gh", *args] if args[0] == "api" else ["gh", *args, "--repo", REPO]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"gh {' '.join(args)} failed: {r.stderr.strip()}")
        return None
    return r.stdout


def hours_since(iso):
    return (datetime.now(timezone.utc) - datetime.fromisoformat(iso.replace("Z", "+00:00"))).total_seconds() / 3600


def overdue_slates():
    """[(label, date, ["Away @ Home", ...])] for past slates still ungraded
    after GRADE_BY_HOUR_ET the next day, with the games that aren't final in
    the scores archive (empty if they all are and only grading is behind)."""
    now = now_et()
    out, seen = [], set()
    for key, cfg in sports.SPORTS.items():
        if cfg["collection"] in seen:
            continue
        seen.add(cfg["collection"])
        scores = None
        for d, doc in store.list_docs(cfg["collection"]):
            if doc.get("scored") or not doc.get("games"):
                continue
            day = date.fromisoformat(d)
            due = datetime(day.year, day.month, day.day, GRADE_BY_HOUR_ET, tzinfo=ET) + timedelta(days=1)
            age = (now.date() - day).days
            if now < due or age > OVERDUE_LOOKBACK_DAYS:
                continue
            if scores is None:
                scores = score_slate.load_scores_by_date(key)
            m = score_slate.match_slate(doc["games"], scores.get(d, []), age)
            out.append((cfg["label"], d, m["missing"]))
    return out


def main():
    problems, actions = [], []

    for wf in (SCORING, PAGES):
        if gh("workflow", "enable", wf) is not None:
            actions.append(f"made sure {wf} is enabled")

    runs = json.loads(gh("run", "list", "--workflow", SCORING, "--limit", "10",
                         "--json", "conclusion,status,createdAt,url") or "[]")
    busy = any(r["status"] in ("queued", "in_progress", "waiting", "pending") for r in runs)
    done = [r for r in runs if r["status"] == "completed"]
    ok = next((r for r in done if r["conclusion"] == "success"), None)
    ok_age = hours_since(ok["createdAt"]) if ok else None
    streak = 0
    for r in done:
        if r["conclusion"] != "failure":
            break
        streak += 1
    overdue = overdue_slates()
    if (ok_age is None or ok_age >= 3) and not busy:
        if gh("workflow", "run", SCORING) is not None:
            actions.append("started a scoring run (none had succeeded in 3+ hours)")
            busy = True
    if overdue and not busy:
        if gh("workflow", "run", SCORING) is not None:
            actions.append("started a scoring run (a past slate is still ungraded)")
    if ok_age is None or ok_age >= 12:
        problems.append(f"No successful scoring run in {'the last 10 runs' if ok_age is None else f'{ok_age:.0f} hours'}.")
    if streak >= 3:
        problems.append(f"The last {streak} scoring runs failed: {done[0]['url']}")

    site_age = None
    pages_url = (gh("api", f"repos/{REPO}/pages", "--jq", ".html_url") or "").strip()
    if pages_url:
        try:
            req = urllib.request.Request(pages_url.rstrip("/") + "/data.json", headers={"Cache-Control": "no-cache"})
            with urllib.request.urlopen(req, timeout=30) as f:
                site_age = hours_since(json.load(f)["generatedAt"])
        except Exception as e:  # noqa: BLE001
            problems.append(f"Couldn't read the live site's data.json ({pages_url}data.json): {e}")
    if site_age is not None and site_age >= 6:
        if gh("workflow", "run", PAGES) is not None:
            actions.append(f"rebuilt the site (live data was {site_age:.0f} hours old)")
    if site_age is not None and site_age >= 12:
        problems.append(f"The live pick sheet is {site_age:.0f} hours old.")

    manual_page = f"{pages_url.rstrip('/')}/manual.html" if pages_url else "the pick sheet's \"Enter data by hand\" page"
    for label, d, missing in overdue:
        if missing:
            problems.append(f"{label} {d} is still ungraded: ESPN has no final score for "
                            f"{', '.join(missing)}. Enter the final(s) by hand at {manual_page} "
                            f"and the next scoring run grades the slate.")
        else:
            problems.append(f"{label} {d} has every final score but hasn't been graded yet; check the latest scoring run.")

    try:
        with open(os.path.join(store.REPO_ROOT, "data", "health.json"), encoding="utf-8") as f:
            health = json.load(f)
    except (OSError, ValueError):
        health = {}
    today = date.fromisoformat(today_et_str())
    for step in (health.get("steps") or {}).values():
        since = step.get("failingSince")
        if since and (today - date.fromisoformat(since)).days >= 2:
            problems.append(f"{step['label']} has been failing since {since} (last OK: {step.get('okOn') or 'never'}).")

    print("actions:", "; ".join(actions) or "none")
    print("problems:", " | ".join(problems) or "none")

    issues = json.loads(gh("issue", "list", "--state", "open", "--search", f'in:title "{ISSUE_TITLE}"',
                           "--json", "number,title") or "[]")
    issue = next((i for i in issues if i["title"] == ISSUE_TITLE), None)
    if problems:
        body = (f"@{OWNER} the automatic health check found a problem it couldn't fix on its own.\n\n"
                + "\n".join(f"- {p}" for p in problems)
                + f"\n\nWhat it already tried: {'; '.join(actions) or 'nothing'}.\n\n"
                f"Run it by hand: Actions → Diamond Ledger (scoring) → Run workflow "
                f"(https://github.com/{REPO}/actions/workflows/{SCORING}). "
                f"This issue closes itself once everything is healthy again.\n\n"
                f"_Checked {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}._")
        if issue:
            gh("issue", "edit", str(issue["number"]), "--body", body)
        else:
            gh("issue", "create", "--title", ISSUE_TITLE, "--body", body)
    elif issue:
        gh("issue", "comment", str(issue["number"]), "--body", "Everything is healthy again: scoring is succeeding and the site is current. Closing.")
        gh("issue", "close", str(issue["number"]))


if __name__ == "__main__":
    main()
