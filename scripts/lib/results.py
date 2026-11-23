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
  moved from), note (a hand correction, kept visible), voided / uncounted (a pick
  voided at the user's request, or one meant but added after kickoff: listed, never counted),
  close (the closing line from the pick's side: spread, or the total) and clv
  (points better (+) or worse (-) than the close: the posted line for an
  alternate, since buying points isn't beating the market).
Closing lines: data/raw/<sport>_lines.csv (nba, nfl, ncaab, cfb; date +/- a
day, teams by name); NBA spreads prefer the slate's statsSpread (DraftKings
frozen at tip-off); otherwise none (MLB, soccer).
"""
import os
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


_CLOSE = {}
LINES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "raw")


def _key(name):
    n = (name or "").lower().replace("la clippers", "los angeles clippers").replace("la lakers", "los angeles lakers")
    return " ".join(n.split())


def _close_row(sport, date_str, away, home):
    """(home closing spread, closing total) from the lines archive, or (None, None)."""
    if sport not in _CLOSE:
        by = {}
        path = os.path.join(LINES_DIR, f"{sport}_lines.csv")
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                for r in csv.DictReader(f):
                    def fl(v):
                        try:
                            return float(v)
                        except (TypeError, ValueError):
                            return None
                    by.setdefault(r["date"], []).append((_key(r["away"]), _key(r["home"]), fl(r.get("spread_close")), fl(r.get("total_close"))))
        _CLOSE[sport] = by
    from datetime import date as _d, timedelta as _td
    a, h = _key(away), _key(home)
    for off in (0, 1, -1):
        d = (_d.fromisoformat(date_str) + _td(days=off)).isoformat()
        for ra, rh, sp, tot in _CLOSE[sport].get(d, []):
            if (ra == a or ra in a or a in ra) and (rh == h or rh in h or h in rh):
                return sp, tot
    return None, None


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
                   "alt": bool(p.get("alt")), "posted": p.get("posted"), "note": p.get("correction"),
                   "reason": p.get("reason")}
            # vs the close: the line taken (the posted one for an alternate) against the closing spread.
            if g is not None and p.get("side") in ("home", "away"):
                c_sp, _ = _close_row(sport, date_str, g.get("away"), g.get("home"))
                if sport == "nba" and _num(g.get("statsSpread")):
                    c_sp = g["statsSpread"]
                taken = (p.get("posted") or {}).get("spread") if p.get("alt") else p.get("spread")
                if _num(c_sp) and _num(taken):
                    mine_close = c_sp if p["side"] == "home" else -c_sp
                    row["close"], row["clv"] = mine_close, round(taken - mine_close, 1)
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
                   "alt": bool(t.get("alt")), "posted": t.get("posted"), "note": t.get("correction"),
                   "reason": t.get("reason")}
            if g is not None and t.get("side") in ("over", "under"):
                _, c_tot = _close_row(sport, date_str, g.get("away"), g.get("home"))
                if c_tot is None and sport == "nba" and _num(g.get("totalsLine")):
                    c_tot = g["totalsLine"]
                taken = (t.get("posted") or {}).get("line") if t.get("alt") else line
                if _num(c_tot) and _num(taken):
                    row["close"], row["clv"] = c_tot, round((c_tot - taken) if t["side"] == "over" else (taken - c_tot), 1)
            if g is None:
                row["result"] = "void"
            elif is_final(doc, g) and _num(line):
                r = grade_total(g, t["side"], line, t.get("odds"))
                row["result"], row["units"] = r["result"], round(r["profit"] / 100, 2)
            rows.append(row)
        # Picks voided at the user's request (entered by mistake) stay listed,
        # marked void with the reason, and never count; "uncounted" holds a pick
        # the user meant to make, added after kickoff, listed but never graded.
        for key, flag in (("voided", "voided"), ("uncounted", "uncounted")):
            for gid, p in sorted((mp.get(key) or {}).items()):
                rows.append({"d": date_str, "sport": p.get("sport"), "game": f"{p.get('away')} @ {p.get('home')}", "kind": "side",
                             "pick": f"{p.get('team')} {_fmt(p.get('spread'))}".strip(), "line": p.get("spread"),
                             "odds": p.get("spreadOdds"), "ml": p.get("moneyline"), "submitted": p.get("submittedAt") or p.get("addedAt"),
                             "lead": lead_minutes(date_str, p.get("time"), p.get("submittedAt") or p.get("addedAt")),
                             "result": "void", "units": None, "mlResult": None, "mlUnits": None, "mlCounted": None,
                             "alt": False, "posted": None, "note": p.get("voidNote") or p.get("note"), flag: True})
        # Player props (graded by scripts/grade_props.py from the box score).
        for key, p in sorted((mp.get("props") or {}).items()):
            from lib.props import any_stat_def as stat_def
            sd = stat_def(p.get("sport", "nba"), p.get("stat"))
            STAT = {p.get("stat"): sd[2] if sd else p.get("stat")}
            res = p.get("result")
            rows.append({"d": date_str, "sport": p.get("sport", "nba"), "game": f"{p.get('away')} @ {p.get('home')}", "kind": "prop",
                         "pick": f"{p.get('player')} {str(p.get('side')).title()} {p.get('line'):g} {STAT.get(p.get('stat'), p.get('stat'))}",
                         "line": p.get("line"), "odds": p.get("odds"), "ml": None, "submitted": p.get("submittedAt"),
                         "lead": lead_minutes(date_str, p.get("time"), p.get("submittedAt")),
                         "result": None if not res else ("void" if res == "void" else res),
                         "units": round(p["profit"] / 100, 2) if res in ("W", "L", "P") and _num(p.get("profit")) else None,
                         "actual": p.get("actual"), "mlResult": None, "mlUnits": None, "mlCounted": None,
                         "alt": False, "posted": None, "note": p.get("note"), "reason": p.get("reason")})
    rows.sort(key=lambda r: (r["d"], r["submitted"] or "", r["kind"]))
    return rows


def results_csv(rows):
    buf = io.StringIO()
    cols = ["date", "sport", "game", "type", "pick", "line", "odds",
            "result", "units", "moneyline", "moneyline_result", "moneyline_units", "alternate_line", "posted_line", "note",
            "closing_line", "vs_close"]
    w = csv.writer(buf)
    w.writerow(cols)
    for r in rows:
        posted = r.get("posted") or {}
        w.writerow([r["d"], r["sport"], r["game"], {"total": "over/under", "prop": "player prop"}.get(r["kind"], "spread"), r["pick"],
                    r["line"], r["odds"], r["result"] or "pending", r["units"], r["ml"],
                    r["mlResult"], r["mlUnits"], "yes" if r["alt"] else "",
                    posted.get("spread", posted.get("line", "")), r["note"] or "", r.get("close", ""), r.get("clv", "")])
    return buf.getvalue()
