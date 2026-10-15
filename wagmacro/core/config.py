"""Tunable parameters, in one place, versioned.

Everything a human might reasonably want to change lives here rather
than being buried in a scorer. Two reasons:

  1. Jath will recalibrate the bands once a few weeks of real readings
     exist. That must be a config edit, not a code change.
  2. METHODOLOGY_VERSION is stamped onto every stored Board. When the
     bands move, old boards keep the version that produced them, so a
     recalibration never silently rewrites history.

Bump METHODOLOGY_VERSION whenever a change would alter a score for
unchanged inputs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .types import Band, Currency

METHODOLOGY_VERSION = "1.0.0"


# --------------------------------------------------------------------------
# Banding
# --------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class BandThresholds:
    """Total score -> display band.

    STARTING POINT, NOT A SETTLED ANSWER.

    With three components each spanning -3..+3, a total of +-5 flags
    roughly 20% of readings if the components spread evenly, so about
    1-2 of 7 currencies at a time. That is the property worth keeping:
    a board where five cells are green tells you nothing.

    Real components will NOT spread evenly — COT percentiles cluster
    mid-range and rate differentials move slowly — so the live
    distribution will be tighter and +-5 may flag almost nothing. Log a
    few weeks of readings, look at the actual spread, and move these so
    that 1-2 currencies qualify. Fit the rule to the data, the same way
    the pair-score tiers were fitted.
    """

    strong: int = 5
    lean: int = 3

    def band_for(self, total: int) -> Band:
        if total >= self.strong:
            return Band.STRONG_BULL
        if total >= self.lean:
            return Band.BULL
        if total <= -self.strong:
            return Band.STRONG_BEAR
        if total <= -self.lean:
            return Band.BEAR
        return Band.NEUTRAL


BANDS = BandThresholds()


# --------------------------------------------------------------------------
# Component refresh windows
# --------------------------------------------------------------------------

#: How old a component's data may be before it is marked STALE.
#: COT is published Friday for Tuesday's positions, so a week plus a
#: few days of slack. Yields and calendar should be same-day.
STALENESS_DAYS: Mapping[str, int] = {
    "positioning": 10,
    "rates": 4,
    "calendar": 1,
}


# --------------------------------------------------------------------------
# Positioning (CFTC COT)
# --------------------------------------------------------------------------

#: CFTC contract market codes for the six currencies with their own
#: futures. Verified against the Financial Futures weekly report.
COT_CONTRACT_CODES: Mapping[Currency, str] = {
    Currency.AUD: "232741",
    Currency.CAD: "090741",
    Currency.GBP: "096742",
    Currency.JPY: "097741",
    Currency.EUR: "099741",
    Currency.NZD: "112741",
}

#: Net leveraged-fund position as a share of open interest, mapped to a
#: score. Leveraged funds are the speculative cohort; asset managers are
#: slower and dealers are largely hedging flow.
#:
#: These are LEVEL bands, used until enough history exists to score by
#: percentile against a currency's own 3-year range. Percentile is the
#: better measure — crowding is relative to a contract's own norms — and
#: the scorer switches to it automatically once history is available.
POSITIONING_BANDS: tuple[tuple[float, int], ...] = (
    (0.30, 3),
    (0.18, 2),
    (0.07, 1),
    (-0.07, 0),
    (-0.18, -1),
    (-0.30, -2),
)
#: Anything below the last threshold scores -3.

#: Minimum weeks of history before the scorer prefers percentile ranking
#: over the fixed level bands above.
POSITIONING_MIN_HISTORY_WEEKS = 52


# --------------------------------------------------------------------------
# Rates (2-year government yields)
# --------------------------------------------------------------------------

#: The 2y yield is the market's pricing of the policy path over the
#: horizon FX actually trades. The LEVEL of a differential matters less
#: than its CHANGE — spot moves on repricing, not on carry that is
#: already in the price — so the scorer weights the 20-day change more
#: heavily than the level.
RATES_LEVEL_WEIGHT = 0.4
RATES_CHANGE_WEIGHT = 0.6

#: Differential vs the average of the other six, in percentage points.
RATES_LEVEL_BANDS: tuple[tuple[float, int], ...] = (
    (1.50, 3),
    (0.75, 2),
    (0.25, 1),
    (-0.25, 0),
    (-0.75, -1),
    (-1.50, -2),
)

#: 20-day change in that differential, in basis points.
RATES_CHANGE_BANDS: tuple[tuple[float, int], ...] = (
    (30.0, 3),
    (15.0, 2),
    (5.0, 1),
    (-5.0, 0),
    (-15.0, -1),
    (-30.0, -2),
)

RATES_CHANGE_LOOKBACK_DAYS = 20


# --------------------------------------------------------------------------
# Calendar
# --------------------------------------------------------------------------

#: Does a HIGHER reading support the currency?
#:
#: This table is the crux of the calendar component and the part most
#: worth arguing with. Keep it explicit and reviewable rather than
#: hidden inside a model. Matching is substring, case-insensitive, and
#: FIRST MATCH WINS — so order matters: put the specific before the
#: general ("unemployment claims" before "employment").
#:
#: True  = higher reading is bullish for the currency
#: False = higher reading is bearish (inverted indicators)
CALENDAR_DIRECTION: tuple[tuple[str, bool], ...] = (
    # Inverted — put these first, they contain words that appear below
    ("unemployment rate", False),
    ("unemployment claims", False),
    ("jobless claims", False),
    ("continuing claims", False),

    # Policy
    ("rate decision", True),
    ("cash rate", True),
    ("official bank rate", True),
    ("federal funds rate", True),
    ("main refinancing rate", True),
    ("policy rate", True),

    # Inflation — hotter supports rate expectations
    ("core cpi", True),
    ("cpi", True),
    ("core pce", True),
    ("pce", True),
    ("ppi", True),
    ("inflation", True),

    # Activity
    ("gdp", True),
    ("pmi", True),
    ("ism", True),
    ("retail sales", True),
    ("industrial production", True),
    ("durable goods", True),
    ("building permits", True),
    ("housing starts", True),

    # Labour
    ("non-farm employment", True),
    ("employment change", True),
    ("payrolls", True),
    ("average earnings", True),
    ("average hourly earnings", True),
    ("labor cost", True),

    # External
    ("trade balance", True),
    ("current account", True),
)

#: Weight by ForexFactory impact level. 3 = High, 2 = Medium.
#: Low impact is discarded upstream.
CALENDAR_IMPACT_WEIGHT: Mapping[int, float] = {3: 1.0, 2: 0.4}

#: How many days of events to consider, either side of today.
CALENDAR_LOOKBACK_DAYS = 7
CALENDAR_LOOKAHEAD_DAYS = 7

#: Weighted surprise sum -> score.
CALENDAR_BANDS: tuple[tuple[float, int], ...] = (
    (2.0, 3),
    (1.0, 2),
    (0.3, 1),
    (-0.3, 0),
    (-1.0, -1),
    (-2.0, -2),
)


# --------------------------------------------------------------------------
# Sources
# --------------------------------------------------------------------------

SOURCE_URLS: Mapping[str, str] = {
    "cot": "https://www.cftc.gov/dea/newcot/FinFutWk.txt",
    "calendar": "https://nfs.faireconomy.media/ff_calendar_thisweek.json",
    "yields_us": "https://home.treasury.gov/resource-center/data-chart-center"
                 "/interest-rates/daily-treasury-rates.csv/2026/all",
    "yields_intl": "https://fred.stlouisfed.org/graph/fredgraph.csv",
}

#: Hosts that must be reachable for live fetching. If these are not on
#: the account's network allowlist the transport layer falls back to
#: cached payloads and every affected reading is marked STALE rather
#: than quietly scoring zero.
REQUIRED_HOSTS: tuple[str, ...] = (
    "www.cftc.gov",
    "nfs.faireconomy.media",
    "fred.stlouisfed.org",
    "home.treasury.gov",
)
