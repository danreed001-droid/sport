"""Player props for every sport: which stats can be bet, where ESPN keeps
each sport's games, rosters and box scores, and how a box score is read.

STATS[sport] = [(key, label, short, [box keys summed])]. Box keys are
"<category>.<label>" from ESPN's summary box score (flatten_box): basketball
uses one block ("main"), football its categories (passing/rushing/receiving),
baseball "batting"/"pitching", soccer the roster stats ("soccer.totalGoals").
"""
import re
import unicodedata

from lib import sports

BASKETBALL = [("points", "Points", "pts", ["main.PTS"]), ("rebounds", "Rebounds", "reb", ["main.REB"]),
              ("assists", "Assists", "ast", ["main.AST"]), ("threes", "3-pointers made", "3PM", ["main.3PT"]),
              ("pra", "Pts + Reb + Ast", "PRA", ["main.PTS", "main.REB", "main.AST"]),
              ("pr", "Pts + Reb", "P+R", ["main.PTS", "main.REB"]), ("pa", "Pts + Ast", "P+A", ["main.PTS", "main.AST"]),
              ("ra", "Reb + Ast", "R+A", ["main.REB", "main.AST"])]
FOOTBALL = [("pass_yds", "Passing yards", "pass yds", ["passing.YDS"]), ("pass_tds", "Passing TDs", "pass TD", ["passing.TD"]),
            ("completions", "Completions", "comp", ["passing.C/ATT"]), ("ints", "Interceptions thrown", "INT", ["passing.INT"]),
            ("rush_yds", "Rushing yards", "rush yds", ["rushing.YDS"]), ("rush_att", "Rushing attempts", "rush att", ["rushing.CAR"]),
            ("rec_yds", "Receiving yards", "rec yds", ["receiving.YDS"]), ("receptions", "Receptions", "rec", ["receiving.REC"]),
            ("rush_rec_yds", "Rush + rec yards", "rush+rec yds", ["rushing.YDS", "receiving.YDS"]),
            ("tds", "Rush + rec TDs (anytime TD = over 0.5)", "TD", ["rushing.TD", "receiving.TD"])]
STATS = {
    "nba": BASKETBALL, "ncaab": BASKETBALL, "nfl": FOOTBALL, "cfb": FOOTBALL,
    "mlb": [("hits", "Hits", "H", ["batting.H"]), ("home_runs", "Home runs", "HR", ["batting.HR"]),
            ("rbis", "RBIs", "RBI", ["batting.RBI"]), ("runs", "Runs", "R", ["batting.R"]),
            ("hrr", "Hits + runs + RBIs", "H+R+RBI", ["batting.H", "batting.R", "batting.RBI"]),
            ("batter_ks", "Strikeouts (batter)", "K", ["batting.K"]),
            ("pitcher_ks", "Strikeouts (pitcher)", "K", ["pitching.K"]), ("hits_allowed", "Hits allowed", "H allowed", ["pitching.H"]),
            ("earned_runs", "Earned runs allowed", "ER", ["pitching.ER"]), ("outs", "Outs recorded", "outs", ["pitching.IP"])],
    "soccer": [("goals", "Goals (anytime = over 0.5)", "goals", ["soccer.totalGoals"]),
               ("assists", "Assists", "ast", ["soccer.goalAssists"]),
               ("goal_assist", "Goal or assist", "G+A", ["soccer.totalGoals", "soccer.goalAssists"]),
               ("shots", "Shots", "shots", ["soccer.totalShots"]), ("sot", "Shots on target", "SOT", ["soccer.shotsOnTarget"])],
}
STATS["epl"] = STATS["soccer"]


def stat_def(sport, key):
    return next((s for s in STATS.get(sport, []) if s[0] == key), None)


def espn_path(sport):
    cfg = sports.SPORTS.get(sport) or {}
    return f"{cfg.get('espn_sport')}/{cfg.get('espn_league') or sport}"


def norm(name):
    s = unicodedata.normalize("NFKD", str(name or "")).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\b(jr|sr|ii|iii|iv)\b\.?", "", s)
    return re.sub(r"[^a-z]", "", s)


def event_for(session, sport, date_str, away, home):
    """(ESPN event id, {"away": team id, "home": team id}, league slug or None) for a slate game."""
    from score_slate import _same_team
    r = session.get(f"https://site.api.espn.com/apis/site/v2/sports/{espn_path(sport)}/scoreboard"
                    f"?dates={date_str.replace('-', '')}&limit=1000", timeout=25)
    for ev in r.json().get("events", []):
        comps = ev["competitions"][0]["competitors"]
        t = {c["homeAway"]: c["team"] for c in comps}
        if _same_team(t.get("away", {}).get("displayName", ""), away) and _same_team(t.get("home", {}).get("displayName", ""), home):
            return str(ev["id"]), {k: str(v.get("id")) for k, v in t.items()}, None
    return None, {}, None


def league_slug(session, sport, eid):
    """Soccer's combined feed has no team rosters: the event's own league slug."""
    if sport not in ("soccer", "epl"):
        return None
    try:
        d = session.get(f"https://site.api.espn.com/apis/site/v2/sports/{espn_path(sport)}/summary?event={eid}", timeout=25).json()
        return ((d.get("header") or {}).get("league") or {}).get("slug")
    except Exception:  # noqa: BLE001
        return None


def team_roster(session, sport, team_id, slug=None):
    """[[athlete id, name, position abbreviation], ...] from ESPN's team roster."""
    path = espn_path(sport) if not slug else f"soccer/{slug}"
    d = session.get(f"https://site.api.espn.com/apis/site/v2/sports/{path}/teams/{team_id}/roster", timeout=25).json()
    out = []
    for grp in d.get("athletes") or []:
        for a in (grp.get("items") if isinstance(grp, dict) and "items" in grp else [grp]):
            if a.get("id") and a.get("displayName"):
                out.append([str(a["id"]), a["displayName"], ((a.get("position") or {}).get("abbreviation") or "")])
    return out


def flatten_box(summary):
    """{athlete id: {"<cat>.<LABEL>": raw value, "_name": display name}} from an ESPN summary."""
    out = {}
    for team in (summary.get("boxscore") or {}).get("players") or []:
        blocks = team.get("statistics") or []
        for st in blocks:
            labels = st.get("labels") or st.get("names") or []
            cat = st.get("name") or ("batting" if "H-AB" in labels else "pitching" if "IP" in labels else "main")
            for a in st.get("athletes") or []:
                ath = a.get("athlete") or {}
                vals = a.get("stats") or []
                if not ath.get("id") or not vals:
                    continue
                row = out.setdefault(str(ath["id"]), {"_name": ath.get("displayName")})
                for lab, v in zip(labels, vals):
                    row[f"{cat}.{lab}"] = v
    for team in summary.get("rosters") or []:   # soccer
        for p in team.get("roster") or []:
            ath = p.get("athlete") or {}
            if not ath.get("id") or not p.get("stats"):
                continue
            row = out.setdefault(str(ath["id"]), {"_name": ath.get("displayName")})
            for x in p["stats"]:
                row[f"soccer.{x.get('name')}"] = x.get("value")
    return out


def _num(v, key):
    s = str(v)
    if key.endswith(".IP"):          # innings "4.1" -> 13 outs
        w, _, f = s.partition(".")
        return int(w or 0) * 3 + int(f or 0)
    if "/" in s or "-" in s[1:]:     # "12/18", "3-7": the made part
        s = re.split(r"[/-]", s)[0]
    try:
        return float(s)
    except ValueError:
        return None


def stat_value(row, sport, key):
    """The player's number for the stat, or None if the box doesn't have it."""
    d = stat_def(sport, key)
    if not d or row is None:
        return None
    tot, found = 0.0, False
    for k in d[3]:
        if k in row:
            v = _num(row[k], k)
            if v is not None:
                tot += v
                found = True
    if not found and sport in ("nfl", "cfb", "soccer", "epl", "mlb") and row:
        return 0.0   # played, just no line in that table (e.g. a WR with no rushes)
    return tot if found else None
