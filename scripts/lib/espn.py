"""ESPN public API helpers (schedule, scores, standings, odds), parameterized
by sport/league slug so the same functions serve NFL, CFB, and future sports.

Uses curl_cffi with a browser TLS fingerprint because ESPN's site API blocks
plain requests/urllib3 clients without one. This is the "own script" that
fetches scores directly instead of relying on the Google Drive feed.
"""
from curl_cffi import requests as curl_requests


def make_session():
    s = curl_requests.Session(impersonate="chrome120")
    s.headers.update({
        "Accept": "application/json",
        "Accept-Language": "en-US,en;q=0.9",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
    })
    return s


def fmt_ml(val):
    if val is None or val == "-":
        return None
    try:
        return int(float(val))
    except (TypeError, ValueError):
        return None


def fmt_num(val):
    if val is None or val == "-":
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def fetch_scoreboard(session, espn_sport, espn_league, yyyymmdd):
    url = f"https://site.api.espn.com/apis/site/v2/sports/{espn_sport}/{espn_league}/scoreboard?dates={yyyymmdd}"
    r = session.get(url, timeout=15)
    r.raise_for_status()
    return r.json().get("events", [])


def fetch_standings(session, espn_sport, espn_league):
    """Return {team displayName: {diff, games, wins, losses, ties}} using
    season-to-date point differential from ESPN standings. Falls back to
    pointsFor - pointsAgainst when a direct differential stat isn't present
    (seen on some non-NFL standings payloads)."""
    url = f"https://site.api.espn.com/apis/v2/sports/{espn_sport}/{espn_league}/standings"
    r = session.get(url, timeout=15)
    r.raise_for_status()
    data = r.json()
    out = {}

    def walk(node):
        if isinstance(node, dict):
            if "team" in node and "stats" in node:
                team = node["team"].get("displayName", "Unknown")
                stat_map = {s.get("name"): s for s in node["stats"] if isinstance(s, dict)}
                diff = stat_map.get("pointDifferential") or stat_map.get("differential")
                diff_val = fmt_num(diff.get("value")) if diff else None
                if diff_val is None:
                    pf = stat_map.get("pointsFor")
                    pa = stat_map.get("pointsAgainst")
                    if pf and pa:
                        pf_val, pa_val = fmt_num(pf.get("value")), fmt_num(pa.get("value"))
                        if pf_val is not None and pa_val is not None:
                            diff_val = pf_val - pa_val
                games = stat_map.get("gamesPlayed")
                wins = stat_map.get("wins")
                losses = stat_map.get("losses")
                ties = stat_map.get("ties")
                out[team] = {
                    "diff": diff_val,
                    "games": fmt_num(games.get("value")) if games else None,
                    "wins": fmt_num(wins.get("value")) if wins else None,
                    "losses": fmt_num(losses.get("value")) if losses else None,
                    "ties": fmt_num(ties.get("value")) if ties else None,
                }
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(data)
    return out


def pd_per_game(standings_entry):
    if not standings_entry:
        return None
    diff = standings_entry.get("diff")
    games = standings_entry.get("games")
    if diff is None or not games:
        return None
    return round(diff / games, 2)


def fetch_event_odds_from_scoreboard(comp):
    """Pull moneylines straight off a scoreboard competition block. The
    "details" string (e.g. "BUF -3.5") is a favorite-plus-price summary, not
    a real two-sided spread, so it is intentionally NOT parsed here —
    signed spreads always come from the Claude research step instead."""
    odds_list = comp.get("odds", [])
    home_ml = away_ml = None
    if odds_list:
        odds_data = odds_list[0]
        home_ml = fmt_ml((odds_data.get("homeTeamOdds") or {}).get("moneyLine"))
        away_ml = fmt_ml((odds_data.get("awayTeamOdds") or {}).get("moneyLine"))
    return away_ml, home_ml


def fetch_summary_odds(session, espn_sport, espn_league, event_id):
    """Fallback moneyline lookup via the game summary/pickcenter payload,
    used only for backfilling completed games that lacked scoreboard odds."""
    url = f"https://site.api.espn.com/apis/site/v2/sports/{espn_sport}/{espn_league}/summary?event={event_id}"
    try:
        r = session.get(url, timeout=12)
        if r.status_code != 200:
            return None, None
        data = r.json()
        odds_pool = data.get("pickcenter", []) or data.get("odds", [])
        if not odds_pool and "competitions" in data:
            odds_pool = data["competitions"][0].get("odds", [])
        for o in odds_pool:
            if not isinstance(o, dict):
                continue
            home_ml = fmt_ml((o.get("homeTeamOdds") or {}).get("moneyLine") or (o.get("homeTeamOdds") or {}).get("value"))
            away_ml = fmt_ml((o.get("awayTeamOdds") or {}).get("moneyLine") or (o.get("awayTeamOdds") or {}).get("value"))
            if home_ml or away_ml:
                return away_ml, home_ml
    except Exception:
        pass
    return None, None
