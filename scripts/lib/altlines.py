"""Estimated prices for alternate lines (your own picks on the pick sheet).

Sportsbooks price alternate spreads and totals off the main line. This
estimates that price: the posted line and its odds fix where the result is
centered; the result is modeled as a whole-number distribution (normal, with
extra weight on football's key margins 3, 7, 10, 14...); the probability of
winning at the alternate line is converted back to American odds with a
typical sportsbook hold (~4.5%). site/index.html has the same math in
JavaScript (altPrice) so the sheet shows the price this module stores.

alt_price(sport, kind, posted, posted_odds, alt) -> American odds or None
  kind "spread": posted/alt are the picked team's spread (+7.5 = getting 7.5)
  kind "over"/"under": posted/alt are the total
"""
import math

# Standard deviation of the final margin and of the total, by sport.
MARGIN_SD = {"nfl": 13.5, "cfb": 16.0, "nba": 12.0, "ncaab": 11.0, "mlb": 4.2}
TOTAL_SD = {"nfl": 10.0, "cfb": 14.0, "nba": 17.0, "ncaab": 15.0, "mlb": 4.4}
# Relative weight of football's common final margins (|margin| -> multiplier).
KEY = {"nfl": {3: 2.3, 7: 1.7, 10: 1.35, 6: 1.25, 4: 1.25, 14: 1.3, 1: 1.1, 17: 1.15},
       "cfb": {3: 1.8, 7: 1.6, 10: 1.3, 14: 1.3, 17: 1.2, 4: 1.15, 6: 1.1, 21: 1.15}}
HOLD = 1.045
MAX_STEP = 10.0   # alternate lines offered up to 10 points either way


def _pdf(x, mu, sd):
    return math.exp(-0.5 * ((x - mu) / sd) ** 2)


def _pmf(mu, sd, keys, lo, hi):
    w = {k: _pdf(k, mu, sd) * keys.get(abs(k), 1.0) for k in range(lo, hi + 1)}
    t = sum(w.values()) or 1.0
    return {k: v / t for k, v in w.items()}


def _implied(odds):
    return 100.0 / (odds + 100.0) if odds > 0 else -odds / (-odds + 100.0)


def _american(p):
    if p <= 0.0:
        return None
    # floor(x + 0.5): rounds halves up, the same as JavaScript's Math.round
    if p >= 0.5:
        return math.floor(-100.0 * p / (1.0 - p) + 0.5) if p < 1 else None
    return math.floor(100.0 * (1.0 - p) / p + 0.5)


def _win_push(pmf, threshold, above):
    """P(value > threshold) or P(value < threshold), and P(value == threshold)."""
    win = sum(v for k, v in pmf.items() if (k > threshold if above else k < threshold))
    push = pmf.get(threshold, 0.0) if float(threshold).is_integer() else 0.0
    return win, push


def _fair_prob(odds):
    """No-vig chance from one side's price (assumes the usual two-way hold)."""
    return min(0.97, max(0.03, _implied(odds if odds is not None else -110) / HOLD))


def alt_price(sport, kind, posted, posted_odds, alt):
    if sport not in MARGIN_SD or posted is None or alt is None:
        return None
    if abs(alt - posted) > MAX_STEP + 1e-9:
        return None
    if alt == posted:
        return posted_odds if posted_odds is not None else -110
    q = _fair_prob(posted_odds)
    if kind == "spread":
        sd, keys, rng = MARGIN_SD[sport], KEY.get(sport, {}), 90
        # team margin M; cover at spread s when M > -s
        def probs(mu, s):
            pmf = _pmf(mu, sd, keys, -rng, rng)
            return _win_push(pmf, -s, True)
        center = -posted
    else:
        sd, keys, rng = TOTAL_SD[sport], {}, None
        def probs(mu, line):
            lo, hi = max(0, int(mu - 8 * sd)), int(mu + 8 * sd) + 1
            pmf = _pmf(mu, sd, {}, lo, hi)
            return _win_push(pmf, line, kind == "over")
        center = posted
    # find the center that reproduces the posted line's fair chance (excluding pushes)
    lo, hi = center - 4 * sd, center + 4 * sd
    for _ in range(60):
        mid = (lo + hi) / 2
        w, p = probs(mid, posted)
        val = w / (1 - p) if p < 1 else 0.5
        increasing = kind in ("spread", "over")
        if (val < q) == increasing:
            lo = mid
        else:
            hi = mid
    mu = (lo + hi) / 2
    w, p = probs(mu, alt)
    if p >= 1:
        return None
    pw = min(0.995, (w / (1 - p)) * HOLD)
    odds = _american(pw)
    if odds is None:
        return None
    return max(-2000, min(2000, odds))
