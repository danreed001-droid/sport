"""Who scored 30+ in a team's last game, and is he out tonight? Shared by NBA
Stats rule 18 (scripts/nba_stats_signals.py) and NBA Totals rule 3
(scripts/nba_totals_signals.py).

"Out" before tip-off means ESPN's injury report (the game summary's
`injuries`) lists the player with status "Out"; the backtest used who actually
didn't play, so a late scratch the report misses is a known gap. A player
listed with a WATCH status (questionable, doubtful, day-to-day...) isn't out
yet, but the pick would fire if he sits: the scripts write him to the game's
statsWatch / totalsWatch so the pick sheet can show an injury watch. After a
game is final (backfill), "out" means he isn't in that game's box score."""

WATCH = {"day-to-day", "questionable", "doubtful", "game time decision", "gtd"}


def big_scorers(points, event_id, team, lo=30, hi=None):
    """[(player_id, pts, name)] for players on `team` who scored lo+ (and at
    most hi) in that game, from the NBA Stats BoxCache."""
    box = points.get(event_id, team) or {}
    return [(pid, v[0], v[1]) for pid, v in box.items()
            if v and v[0] >= lo and (hi is None or v[0] <= hi)]


def injury_status(session, event_id):
    """{team displayName: {player_id: (name, status lowercased)}} from ESPN's
    injury report for this game; None if the summary can't be read."""
    try:
        d = session.get(f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event={event_id}",
                        timeout=20).json()
    except Exception:
        return None
    out = {}
    for t in d.get("injuries") or []:
        name = (t.get("team") or {}).get("displayName")
        for i in t.get("injuries") or []:
            a = i.get("athlete") or {}
            out.setdefault(name, {})[str(a.get("id"))] = (a.get("displayName"), str(i.get("status", "")).lower())
    return out


def injury_out(session, event_id):
    """{team displayName: {player_id: name}} of players ESPN lists as Out for
    this game; None if the summary can't be read."""
    st = injury_status(session, event_id)
    if st is None:
        return None
    return {team: {pid: v[0] for pid, v in players.items() if v[1] == "out"} for team, players in st.items()}


def watch_entries(big, statuses, rule, if_out):
    """Injury-watch rows for big scorers listed with a WATCH status:
    [{player, pts, status, rule, ifOut}]."""
    rows = []
    for pid, pts, name in big:
        st = (statuses or {}).get(pid)
        if st and st[1] in WATCH:
            rows.append({"player": name, "pts": pts, "status": st[1].title(), "rule": rule, "ifOut": if_out})
    return rows
