"""Public betting splits and lines from Action Network's public scoreboard feed
(the data behind https://www.actionnetwork.com/nba), for NBA Stats rule 50.

market(date_str) -> {(away, home): {"tix_home": % of spread bets on the home
team, "money_home": % of spread money on it, "spread_home": the consensus
home spread now (the close, once the game has started), "open_home": the
opening home spread, "state": "scheduled" | "inprogress" | "complete"}}.
Team names are Action Network's full names ("Los Angeles Clippers"); match
them with nba_stats_signals._same_team. Any failure returns {} -- a missing
feed only means rule 50 doesn't fire."""
import json
import time
import urllib.request

URL = "https://api.actionnetwork.com/web/v2/scoreboard/nba?period=game&date={}"
CONSENSUS, OPEN = "15", "30"   # Action Network book ids
_CACHE = {}


def _side(outs, side):
    return next((o for o in outs or [] if o.get("side") == side), None)


def market(date_str, tries=3):
    if date_str in _CACHE:
        return _CACHE[date_str]
    data = None
    for i in range(tries):
        try:
            req = urllib.request.Request(URL.format(date_str.replace("-", "")),
                                         headers={"User-Agent": "Mozilla/5.0 (Diamond Ledger)"})
            with urllib.request.urlopen(req, timeout=20) as r:
                data = json.load(r)
            break
        except Exception:
            time.sleep(2 ** i)
    out = {}
    for g in (data or {}).get("games", []):
        try:
            teams = {t["id"]: t["full_name"] for t in g.get("teams", [])}
            mk = g.get("markets") or {}
            cons = ((mk.get(CONSENSUS) or {}).get("event") or {}).get("spread")
            opn = ((mk.get(OPEN) or {}).get("event") or {}).get("spread")
            h = _side(cons, "home")
            if not h:
                continue
            bi = h.get("bet_info") or {}
            tix = (bi.get("tickets") or {}).get("percent")
            o = _side(opn, "home")
            out[(teams.get(g.get("away_team_id")), teams.get(g.get("home_team_id")))] = {
                "tix_home": tix if tix else None,
                "money_home": (bi.get("money") or {}).get("percent"),
                "spread_home": h.get("value"),
                "open_home": o.get("value") if o else None,
                "state": g.get("status"),
            }
        except (TypeError, KeyError, AttributeError):
            continue
    if data is not None:
        _CACHE[date_str] = out
    return out


def lookup(mk, away, home, same):
    """The entry for (away, home) in market(), matching names with `same`."""
    return next((v for (a, h), v in mk.items() if a and h and same(away, a) and same(home, h)), None)
