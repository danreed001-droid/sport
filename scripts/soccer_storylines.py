#!/usr/bin/env python3
"""Soccer storylines: context for the pick sheet, never a pick.

(docstring filled in after the research run)
"""
import math
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib import espn, store  # noqa: E402
from lib.dates import ET, today_et_str  # noqa: E402
from score_slate import _same_team, find_match_loose  # noqa: E402

EURO = {"uefa.champions", "uefa.europa", "uefa.europa.conf"}
EUROPE_LG = {"eng.1", "esp.1", "ger.1", "ita.1", "fra.1"}
DOMESTIC_CUPS = {"eng.fa", "eng.league_cup", "esp.copa_del_rey", "ger.dfb_pokal", "ita.coppa_italia",
                 "fra.coupe_de_france", "usa.open", "mex.copa_mx"}
# Other competitions whose matches count for rest, congestion and "last match".
OTHER_COMPS = {
    "eng.1": ["uefa.champions", "uefa.europa", "uefa.europa.conf", "eng.fa", "eng.league_cup"],
    "esp.1": ["uefa.champions", "uefa.europa", "uefa.europa.conf", "esp.copa_del_rey", "esp.super_cup"],
    "ger.1": ["uefa.champions", "uefa.europa", "uefa.europa.conf", "ger.dfb_pokal"],
    "ita.1": ["uefa.champions", "uefa.europa", "uefa.europa.conf", "ita.coppa_italia", "ita.super_cup"],
    "fra.1": ["uefa.champions", "uefa.europa", "uefa.europa.conf", "fra.coupe_de_france"],
    "usa.1": ["concacaf.champions", "concacaf.leagues.cup", "usa.open"],
    "mex.1": ["concacaf.champions", "concacaf.leagues.cup"],
}
LEAGUE_SIZE = {"eng.1": 20, "esp.1": 20, "ger.1": 18, "ita.1": 20, "fra.1": 18}
DONE = {"STATUS_FULL_TIME", "STATUS_FINAL_AET", "STATUS_FINAL_PEN", "STATUS_FINAL"}

# Slate competition names (lower case, ", Matchday N" and "(...)" removed) -> ESPN league.
COMPETITIONS = {
    "eng.1": {"premier league", "english premier league", "england's premier league", "epl", "england premier league"},
    "esp.1": {"la liga", "laliga", "spain's la liga", "spanish la liga", "laliga ea sports", "la liga ea sports"},
    "ger.1": {"bundesliga", "germany's bundesliga", "german bundesliga", "1. bundesliga"},
    "ita.1": {"serie a", "italy's serie a", "italian serie a", "serie a enilive"},
    "fra.1": {"ligue 1", "france's ligue 1", "french ligue 1", "ligue 1 mcdonald's"},
    "usa.1": {"mls", "major league soccer"},
    "mex.1": {"liga mx", "mexico's liga mx", "liga bbva mx"},
}


def league_of(competition):
    s = (competition or "").split(",")[0].split("(")[0].strip().lower().replace("’", "'")
    for lg, names in COMPETITIONS.items():
        if s in names:
            return lg
    if s.startswith("liga mx"):
        return "mex.1"
    return None
