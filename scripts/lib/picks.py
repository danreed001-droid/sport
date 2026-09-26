"""Shared game-id and flat-$100 grading logic for the GitHub Pages pick sheet:
used by build_site.py (scoreboard) and intake_picks.py (the issue-driven
workflow that commits your picks into data/mypicks/)."""
import re

BIG_DOG_LIMIT = 7
BIG_DOG_SPORTS = {"nfl", "cfb"}
DEFAULT_SPREAD_ODDS = -110


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", str(s or "").lower()).strip("-")


def game_id(sport, date_str, g):
    parts = [sport, date_str, slug(g.get("away")), slug(g.get("home")), slug(g.get("time"))]
    return "-".join(p for p in parts if p)


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def side_of(g, team):
    if team == g.get("away"):
        return "away"
    if team == g.get("home"):
        return "home"
    if isinstance(team, str) and team.lower() == "draw" and _num(g.get("drawMoneyline")):
        return "draw"
    return None


def team_for(g, side):
    return "Draw" if side == "draw" else g.get(side)


def line_for(g, side):
    return {
        "moneyline": g.get(f"{side}Moneyline"),
        "spread": g.get(f"{side}Spread"),
        "spreadOdds": g.get(f"{side}SpreadOdds"),
    }


def is_final(doc, g):
    return bool(doc.get("scored")) and _num(g.get("awayScore")) and _num(g.get("homeScore"))


def is_big_dog(sport, spread):
    return sport in BIG_DOG_SPORTS and _num(spread) and spread > BIG_DOG_LIMIT


def payout(odds, won):
    if not won:
        return -100.0
    return float(odds) if odds > 0 else 10000.0 / abs(odds)


def grade(sport, g, side):
    """Grade one side of a final game. Moneyline is skipped (counted=False)
    when the pick is an NFL/college dog of more than 7 points. A soccer draw
    pick is moneyline-only."""
    if side == "draw":
        won = g["awayScore"] == g["homeScore"]
        odds = g.get("drawMoneyline")
        return {"ml": {"result": "W" if won else "L", "profit": round(payout(odds, won), 2) if _num(odds) else None, "counted": True},
                "ats": {"result": None, "profit": None}}
    other = "home" if side == "away" else "away"
    mine, theirs = g[f"{side}Score"], g[f"{other}Score"]
    ln = line_for(g, side)

    ml = {"result": None, "profit": None, "counted": not is_big_dog(sport, ln["spread"])}
    three_way = _num(g.get("drawMoneyline"))
    if ml["counted"] and (mine != theirs or three_way):
        won = mine > theirs
        ml["result"] = "W" if won else "L"
        if _num(ln["moneyline"]):
            ml["profit"] = round(payout(ln["moneyline"], won), 2)

    ats = {"result": None, "profit": None}
    if _num(ln["spread"]):
        margin = mine - theirs + ln["spread"]
        odds = ln["spreadOdds"] if _num(ln["spreadOdds"]) else DEFAULT_SPREAD_ODDS
        if margin > 0:
            ats = {"result": "cover", "profit": round(payout(odds, True), 2)}
        elif margin < 0:
            ats = {"result": "miss", "profit": -100.0}
        else:
            ats = {"result": "push", "profit": 0.0}
    return {"ml": ml, "ats": ats}
