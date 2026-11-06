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


def board(date_str, tries=3):
    """Every game on Action Network's NBA board for date_str, with the
    consensus line now, the opener, and the public splits for the spread and
    the total: [{away, home, start, state, spread: {home, open, tix_home,
    money_home}, total: {now, open, tix_over, money_over}, moneyline: {home,
    away}}]. [] on any failure."""
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
    out = []
    for g in (data or {}).get("games", []):
        try:
            teams = {t["id"]: t["full_name"] for t in g.get("teams", [])}
            mk = g.get("markets") or {}
            cons = (mk.get(CONSENSUS) or {}).get("event") or {}
            opn = (mk.get(OPEN) or {}).get("event") or {}
            def pct(o, k):
                v = ((o or {}).get("bet_info") or {}).get(k, {}).get("percent")
                return v if v else None
            sh, oh = _side(cons.get("spread"), "home"), _side(opn.get("spread"), "home")
            ov, oo = _side(cons.get("total"), "over"), _side(opn.get("total"), "over")
            mh, ma = _side(cons.get("moneyline"), "home"), _side(cons.get("moneyline"), "away")
            out.append({"away": teams.get(g.get("away_team_id")), "home": teams.get(g.get("home_team_id")),
                        "start": g.get("start_time"), "state": g.get("status"),
                        "spread": {"home": (sh or {}).get("value"), "open": (oh or {}).get("value"),
                                   "tix_home": pct(sh, "tickets"), "money_home": pct(sh, "money")},
                        "total": {"now": (ov or {}).get("value"), "open": (oo or {}).get("value"),
                                  "tix_over": pct(ov, "tickets"), "money_over": pct(ov, "money")},
                        "moneyline": {"home": (mh or {}).get("odds"), "away": (ma or {}).get("odds")}})
        except (TypeError, KeyError, AttributeError):
            continue
    return out


def rlm_favorite(game):
    """The team NBA Stats rule 50 (and the Second Opinion's Market category)
    backs in a board() game, or None: 60%+ of spread bets on a 7+ point
    underdog while the line moved 1-4.5 points toward the favorite since the
    open."""
    sp = game.get("spread") or {}
    if None in (sp.get("home"), sp.get("open"), sp.get("tix_home")):
        return None
    for is_home in (True, False):
        s = sp["home"] if is_home else -sp["home"]
        o = sp["open"] if is_home else -sp["open"]
        t = sp["tix_home"] if is_home else 100 - sp["tix_home"]
        if s >= 7 and t >= 60 and 1 <= s - o < 5:
            return game["away"] if is_home else game["home"]
    return None
