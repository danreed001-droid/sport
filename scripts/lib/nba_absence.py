"""Who scored 30+ in a team's last game, and is he out tonight? Shared by NBA
Stats rule 18 (scripts/nba_stats_signals.py) and NBA Totals rule 3
(scripts/nba_totals_signals.py).

"Out" before tip-off means ESPN's injury report (the game summary's
`injuries`) lists the player with status "Out"; the backtest used who actually
didn't play, so a late scratch the report misses is a known gap. After a game
is final (backfill), "out" means he isn't in that game's box score."""


def big_scorers(points, event_id, team, lo=30, hi=None):
    """[(player_id, pts, name)] for players on `team` who scored lo+ (and at
    most hi) in that game, from the NBA Stats BoxCache."""
    box = points.get(event_id, team) or {}
    return [(pid, v[0], v[1]) for pid, v in box.items()
            if v and v[0] >= lo and (hi is None or v[0] <= hi)]


def injury_out(session, event_id):
    """{team displayName: {player_id: name}} of players ESPN lists as Out for
    this game; None if the summary can't be read."""
    try:
        d = session.get(f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event={event_id}",
                        timeout=20).json()
    except Exception:
        return None
    out = {}
    for t in d.get("injuries") or []:
        name = (t.get("team") or {}).get("displayName")
        for i in t.get("injuries") or []:
            if str(i.get("status", "")).lower() == "out":
                a = i.get("athlete") or {}
                out.setdefault(name, {})[str(a.get("id"))] = a.get("displayName")
    return out
