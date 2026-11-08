"""Public results: every pick of the user's (sides and over/unders), graded at
the line they took, with when it was submitted relative to the game's start.
Feeds site/results.html via results.json and results.csv (build_site.py).

A row:
  d, sport, game, kind ("side"|"total"), pick (text), line, odds, ml (the
  moneyline taken, sides only), submitted (UTC ISO), lead (minutes before the
  game's start when submitted; negative = after it started; None if unknown),
  result ("W"|"L"|"P"|None for pending|"NS" no spread saved|"void" game left the slate),
  units (profit / 100), mlResult / mlUnits / mlCounted (sides only),
  alt (an alternate line, price estimated), posted (the posted line it was
  moved from), note (a hand correction, kept visible).
"""
import csv
import io
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from .picks import game_id, grade, grade_total, is_final, mine_view

ET = ZoneInfo("America/New_York")
TIME = re.compile(r"(\d{1,2}):(\d{2})\s*([AP]M)", re.I)
RESULT = {"cover": "W", "miss": "L", "push": "P"}


def start_et(date_str, time_str):
    m = TIME.search(time_str or "")
    if not m:
        return None
    hour = int(m.group(1)) % 12 + (12 if m.group(3).upper() == "PM" else 0)
    y, mo, d = (int(x) for x in date_str.split("-"))
    return datetime(y, mo, d, hour, int(m.group(2)), tzinfo=ET)


def lead_minutes(date_str, time_str, submitted):
    start = start_et(date_str, time_str)
    if start is None or not submitted:
        return None
    try:
        sub = datetime.fromisoformat(submitted)
    except ValueError:
        return None
    if sub.tzinfo is None:
        sub = sub.replace(tzinfo=timezone.utc)
    return round((start - sub).total_seconds() / 60)


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _fmt(v):
    return f"{v:+g}" if _num(v) else ""


def build_results(mypicks, all_docs):
    docs = {sport: {d: doc for d, doc in lst} for sport, lst in all_docs.items()}
    rows = []
    for date_str, mp in sorted(mypicks.items()):
        def find(sport, gid):
            doc = docs.get(sport, {}).get(date_str)
            g = next((x for x in (doc or {}).get("games", []) if game_id(sport, date_str, x) == gid), None)
            return doc, g

        for gid, p in sorted((mp.get("picks") or {}).items()):
            sport = p.get("sport")
            doc, g = find(sport, gid)
            row = {"d": date_str, "sport": sport, "game": f"{p.get('away')} @ {p.get('home')}", "kind": "side",
                   "pick": f"{p.get('team')} {_fmt(p.get('spread'))}".strip(), "line": p.get("spread"),
                   "odds": p.get("spreadOdds"), "ml": p.get("moneyline"), "submitted": p.get("submittedAt"),
                   "lead": lead_minutes(date_str, p.get("time"), p.get("submittedAt")),
                   "result": None, "units": None, "mlResult": None, "mlUnits": None, "mlCounted": None,
                   "alt": bool(p.get("alt")), "posted": p.get("posted"), "note": p.get("correction")}
            if g is None:
                row["result"] = "void"
            elif is_final(doc, g):
                r = grade(sport, mine_view(g, p), p["side"])
                ats = (r.get("ats") or {}).get("result")
                # "NS": no spread was saved with the pick, so only its moneyline can be graded.
                row["result"] = RESULT.get(ats) or ("NS" if (r.get("ml") or {}).get("result") else "void")
                if ats:
                    row["units"] = round((r["ats"].get("profit") or 0) / 100, 2)
                ml = r.get("ml") or {}
                row["mlResult"], row["mlCounted"] = ml.get("result"), bool(ml.get("counted"))
                if ml.get("profit") is not None:
                    row["mlUnits"] = round(ml["profit"] / 100, 2)
            rows.append(row)

        for gid, t in sorted((mp.get("totals") or {}).items()):
            sport = t.get("sport")
            doc, g = find(sport, gid)
            line = t.get("line")
            row = {"d": date_str, "sport": sport, "game": f"{t.get('away')} @ {t.get('home')}", "kind": "total",
                   "pick": f"{str(t.get('side')).title()} {line:g}" if _num(line) else str(t.get("side")).title(),
                   "line": line, "odds": t.get("odds"), "ml": None, "submitted": t.get("submittedAt"),
                   "lead": lead_minutes(date_str, t.get("time"), t.get("submittedAt")),
                   "result": None, "units": None, "mlResult": None, "mlUnits": None, "mlCounted": None,
                   "alt": bool(t.get("alt")), "posted": t.get("posted"), "note": t.get("correction")}
            if g is None:
                row["result"] = "void"
            elif is_final(doc, g) and _num(line):
                r = grade_total(g, t["side"], line, t.get("odds"))
                row["result"], row["units"] = r["result"], round(r["profit"] / 100, 2)
            rows.append(row)
    rows.sort(key=lambda r: (r["d"], r["submitted"] or "", r["kind"]))
    return rows


def results_csv(rows):
    buf = io.StringIO()
    cols = ["date", "sport", "game", "type", "pick", "line", "odds", "submitted_utc", "minutes_before_start",
            "result", "units", "moneyline", "moneyline_result", "moneyline_units", "alternate_line", "posted_line", "note"]
    w = csv.writer(buf)
    w.writerow(cols)
    for r in rows:
        posted = r.get("posted") or {}
        w.writerow([r["d"], r["sport"], r["game"], "over/under" if r["kind"] == "total" else "spread", r["pick"],
                    r["line"], r["odds"], r["submitted"], r["lead"], r["result"] or "pending", r["units"], r["ml"],
                    r["mlResult"], r["mlUnits"], "yes" if r["alt"] else "",
                    posted.get("spread", posted.get("line", "")), r["note"] or ""])
    return buf.getvalue()
