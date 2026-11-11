"""NBA arena coordinates and the flight distance between them, for NBA Stats
rule 55 (first road game after a home stand, 1,000+ miles away)."""
import math

ARENA = {
    "Atlanta Hawks": (33.757, -84.396), "Boston Celtics": (42.366, -71.062), "Brooklyn Nets": (40.683, -73.975),
    "Charlotte Hornets": (35.225, -80.839), "Chicago Bulls": (41.881, -87.674), "Cleveland Cavaliers": (41.497, -81.688),
    "Dallas Mavericks": (32.790, -96.810), "Denver Nuggets": (39.749, -105.008), "Detroit Pistons": (42.341, -83.055),
    "Golden State Warriors": (37.768, -122.388), "Houston Rockets": (29.751, -95.362), "Indiana Pacers": (39.764, -86.156),
    "Los Angeles Clippers": (33.99, -118.30), "Los Angeles Lakers": (34.043, -118.267), "Memphis Grizzlies": (35.138, -90.051),
    "Miami Heat": (25.781, -80.188), "Milwaukee Bucks": (43.045, -87.917), "Minnesota Timberwolves": (44.979, -93.276),
    "New Orleans Pelicans": (29.949, -90.082), "New York Knicks": (40.751, -73.994), "Oklahoma City Thunder": (35.463, -97.515),
    "Orlando Magic": (28.539, -81.384), "Philadelphia 76ers": (39.901, -75.172), "Phoenix Suns": (33.446, -112.071),
    "Portland Trail Blazers": (45.532, -122.667), "Sacramento Kings": (38.580, -121.500), "San Antonio Spurs": (29.427, -98.438),
    "Toronto Raptors": (43.643, -79.379), "Utah Jazz": (40.768, -111.901), "Washington Wizards": (38.898, -77.021),
}
ALIASES = {"LA Clippers": "Los Angeles Clippers", "LA Lakers": "Los Angeles Lakers"}


def miles_between(team_a, team_b):
    """Great-circle miles between two teams' home arenas, or None if a name isn't known."""
    a, b = ARENA.get(ALIASES.get(team_a, team_a)), ARENA.get(ALIASES.get(team_b, team_b))
    if a is None or b is None:
        return None
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 3959 * 2 * math.asin(math.sqrt(h))
