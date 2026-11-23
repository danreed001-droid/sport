#!/usr/bin/env python3
"""Blind test of Third Opinion-style picks on the 2026 season, one week at a time.

Weeks follow the NFL calendar (Tue-Mon). For each week:

  prep  WEEK   write blinded slates (teams, time and lines only -- no scores,
               no model picks) to backtest/blind-2026/week<N>/slates/, split
               into chunks of up to CHUNK games for the research agents.
  check WEEK   confirm every chunk has a locked picks file covering its games.
  grade WEEK   (only after the picks are committed) join the picks with the
               final scores in data/<sport>/<date>.json and write graded.json.
  report       season record so far -> backtest/blind-2026/RESULTS.md.

Grading follows the Third Opinion rules: ATS at the slate's stored spread and
odds (-110 if none), $100 flat; straight-up at the stored moneyline, none when
the pick gets more than 10 points. A pick whose agent reported seeing the
game's result is "contaminated": graded, but kept out of the clean record.
"""
import glob
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "backtest", "blind-2026")
SPORTS = ["nfl", "cfb", "nba", "ncaab"]
WEEKS = {
    5: ("2026-10-06", "2026-10-12"),
    6: ("2026-10-13", "2026-10-19"),
    7: ("2026-10-20", "2026-10-26"),
    8: ("2026-10-27", "2026-11-02"),
    9: ("2026-11-03", "2026-11-09"),
    10: ("2026-11-10", "2026-11-16"),
}
CHUNK = 6
KEEP = ["away", "home", "time", "neutral", "awayRank", "homeRank",
        "awaySpread", "homeSpread", "awaySpreadOdds", "homeSpreadOdds",
        "awayMoneyline", "homeMoneyline", "total"]


def week_dir(w):
    return os.path.join(OUT, f"week{w}")


def slates_for(w):
    a, b = WEEKS[w]
    for sport in SPORTS:
        for f in sorted(glob.glob(os.path.join(ROOT, "data", sport, "2026-*.json"))):
            d = os.path.basename(f)[:10]
            if a <= d <= b:
                yield sport, d, f


def prep(w):
    os.makedirs(os.path.join(week_dir(w), "slates"), exist_ok=True)
    os.makedirs(os.path.join(week_dir(w), "picks"), exist_ok=True)
    made = []
    for sport, d, f in slates_for(w):
        games = []
        for g in json.load(open(f))["games"]:
            if g.get("awaySpread") is None or g.get("homeSpread") is None:
                continue  # no line: nothing to pick against the spread
            games.append({k: g[k] for k in KEEP if g.get(k) is not None})
        for i in range(0, len(games), CHUNK):
            part = games[i:i + CHUNK]
            name = f"{sport}-{d}-{i // CHUNK + 1}"
            path = os.path.join(week_dir(w), "slates", name + ".json")
            json.dump({"sport": sport, "date": d, "chunk": name, "games": part},
                      open(path, "w"), indent=1)
            made.append((name, len(part)))
    for name, n in made:
        print(name, n)
    print("chunks", len(made), "games", sum(n for _, n in made))


def chunks(w):
    for f in sorted(glob.glob(os.path.join(week_dir(w), "slates", "*.json"))):
        yield json.load(open(f))


def check(w):
    bad = 0
    for c in chunks(w):
        p = os.path.join(week_dir(w), "picks", c["chunk"] + ".json")
        if not os.path.exists(p):
            print("MISSING", c["chunk"]); bad += 1; continue
        try:
            picks = json.load(open(p))["games"]
        except Exception as e:  # noqa: BLE001
            print("BAD JSON", c["chunk"], e); bad += 1; continue
        want = {(g["away"], g["home"]) for g in c["games"]}
        have = {(g.get("away"), g.get("home")) for g in picks}
        if want - have:
            print("GAMES MISSING", c["chunk"], sorted(want - have)); bad += 1
        for g in picks:
            if g.get("pick") not in (None, g.get("away"), g.get("home")):
                print("PICK NOT A TEAM", c["chunk"], g.get("away"), g.get("home"), g.get("pick")); bad += 1
    print("ok" if not bad else f"{bad} problem(s)")
    return bad == 0


def win_amt(odds):
    if odds is None:
        odds = -110
    return odds if odds > 0 else 10000.0 / abs(odds)


def from_projection(p, line):
    """The side the locked projection covers with (for passes locked before forcedSide existed)."""
    pm = p.get("projectedMargin")
    if pm is None or pm + line["homeSpread"] == 0:
        return None
    return line["home"] if pm + line["homeSpread"] > 0 else line["away"]


def grade(w):
    rows = []
    for c in chunks(w):
        slate = json.load(open(os.path.join(ROOT, "data", c["sport"], c["date"] + ".json")))["games"]
        picks = {(g["away"], g["home"]): g for g in
                 json.load(open(os.path.join(week_dir(w), "picks", c["chunk"] + ".json")))["games"]}
        for line in c["games"]:
            key = (line["away"], line["home"])
            p = picks.get(key, {})
            fin = [g for g in slate if g.get("away") == key[0] and g.get("home") == key[1]]
            fin = fin[0] if fin else {}
            r = {"week": w, "sport": c["sport"], "date": c["date"], "away": key[0], "home": key[1],
                 "homeSpread": line["homeSpread"], "pick": p.get("pick"),
                 "confidence": p.get("confidence"), "projectedMargin": p.get("projectedMargin"),
                 "forcedSide": p.get("forcedSide") or p.get("pick") or from_projection(p, line), "forcedCover": None,
                 "reasoning": p.get("reasoning"), "contaminated": bool(p.get("contaminated")),
                 "awayScore": fin.get("awayScore"), "homeScore": fin.get("homeScore"),
                 "cover": None, "spreadReturn": None, "won": None, "mlReturn": None}
            if r["pick"] and r["awayScore"] is not None and r["homeScore"] is not None:
                side = "home" if r["pick"] == key[1] else "away"
                other = "away" if side == "home" else "home"
                spread = line[side + "Spread"]
                margin = fin[side + "Score"] - fin[other + "Score"]
                ats = margin + spread
                r["cover"] = None if ats == 0 else ats > 0
                r["spreadReturn"] = 0.0 if ats == 0 else (
                    round(win_amt(line.get(side + "SpreadOdds")), 2) if ats > 0 else -100.0)
                r["won"] = margin > 0
                ml = line.get(side + "Moneyline")
                if spread <= 10 and ml is not None and margin != 0:
                    r["mlReturn"] = round(win_amt(ml), 2) if margin > 0 else -100.0
            fs = r["forcedSide"]
            if fs in key and r["awayScore"] is not None and r["homeScore"] is not None:
                sd = "home" if fs == key[1] else "away"
                ot = "away" if sd == "home" else "home"
                ats = fin[sd + "Score"] - fin[ot + "Score"] + line[sd + "Spread"]
                r["forcedCover"] = None if ats == 0 else ats > 0
            rows.append(r)
    json.dump(rows, open(os.path.join(week_dir(w), "graded.json"), "w"), indent=1)
    print(summary_line(rows, f"Week {w}"))


def tally(rows):
    g = [r for r in rows if r["pick"] and r["awayScore"] is not None]
    w = sum(1 for r in g if r["cover"] is True)
    l = sum(1 for r in g if r["cover"] is False)
    p = sum(1 for r in g if r["cover"] is None)
    prof = sum(r["spreadReturn"] or 0 for r in g)
    su_w = sum(1 for r in g if r["won"])
    ml = sum(r["mlReturn"] or 0 for r in g)
    return w, l, p, prof, su_w, len(g) - su_w, ml


def fmt(rows):
    w, l, p, prof, sw, sl, ml = tally(rows)
    pct = f"{100 * w / (w + l):.1f}%" if w + l else "-"
    return f"{w}-{l}-{p} ({pct}), ATS ${prof:+.0f}; straight up {sw}-{sl}, ML ${ml:+.0f}"


def summary_line(rows, label):
    clean = [r for r in rows if not r["contaminated"]]
    passes = sum(1 for r in rows if not r["pick"])
    return f"{label}: clean {fmt(clean)} | all {fmt(rows)} | passes {passes} | contaminated {len(rows) - len(clean)}"


def report():
    rows = []
    for w in WEEKS:
        f = os.path.join(week_dir(w), "graded.json")
        if os.path.exists(f):
            rows += json.load(open(f))
    clean = [r for r in rows if not r["contaminated"]]
    out = ["# Blind test, 2026 — results", "",
           "Third Opinion-style picks made week by week, each locked (committed) before its scores were read.",
           "Graded ATS at the slate's stored line, $100 flat. \"Clean\" leaves out picks whose agent reported seeing the game's result.",
           "", "| | Clean ATS | All ATS | Passes | Contaminated |", "|---|---|---|---|---|"]
    def line(label, rs):
        cl = [r for r in rs if not r["contaminated"]]
        return f"| {label} | {fmt(cl)} | {fmt(rs)} | {sum(1 for r in rs if not r['pick'])} | {len(rs) - len(cl)} |"
    out.append(line("**Total**", rows))
    for s in SPORTS:
        rs = [r for r in rows if r["sport"] == s]
        if rs:
            out.append(line(s.upper(), rs))
    for w in WEEKS:
        rs = [r for r in rows if r["week"] == w]
        if rs:
            out.append(line(f"Week {w}", rs))
    def forced(rs):
        rs = [r for r in rs if r.get("forcedCover") is not None or (r.get("forcedSide") and r.get("awayScore") is not None)]
        w = sum(1 for r in rs if r.get("forcedCover") is True)
        l = sum(1 for r in rs if r.get("forcedCover") is False)
        return f"{w}-{l}-{len(rs) - w - l}" + (f" ({100 * w / (w + l):.1f}%)" if w + l else "")
    out += ["", "Forced side (every game, passes included; Weeks 5-6 passes use the side the locked projected margin covers with):", "",
            "| | Clean | All |", "|---|---|---|"]
    for label, rs in [("Total", rows)] + [(s.upper(), [r for r in rows if r["sport"] == s]) for s in SPORTS] + \
            [(f"Week {w}", [r for r in rows if r["week"] == w]) for w in WEEKS]:
        if rs:
            out.append(f"| {label} | {forced([r for r in rs if not r['contaminated']])} | {forced(rs)} |")
    out.append("")
    for conf in ["strong", "lean"]:
        rs = [r for r in rows if r["confidence"] == conf]
        if rs:
            out.append(line(f"Confidence: {conf}", rs))
    open(os.path.join(OUT, "RESULTS.md"), "w").write("\n".join(out) + "\n")
    print("\n".join(out))


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "report":
        report()
    else:
        {"prep": prep, "check": check, "grade": grade}[cmd](int(sys.argv[2]))
