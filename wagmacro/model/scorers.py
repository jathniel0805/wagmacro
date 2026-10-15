"""The three component scorers.

Every function here is PURE: typed data in, a ComponentScore out, no
I/O, no clock, no globals. That is what makes them testable, and it is
what will let the same scoring code run behind a web request later
without dragging a fetch layer along.

Each scorer must do three things:

  1. Clamp to [-3, +3].
  2. Say WHY, in a sentence a trader would accept.
  3. Report its own confidence honestly. A scorer with no data returns
     0 with Confidence.UNAVAILABLE — never 0 with Confidence.OK, which
     would be indistinguishable from a genuinely neutral reading.
"""

from __future__ import annotations

from datetime import date
from statistics import median

from ..core.config import (CALENDAR_BANDS, POSITIONING_BANDS,
                           POSITIONING_MIN_HISTORY_WEEKS, RATES_CHANGE_BANDS,
                           RATES_CHANGE_LOOKBACK_DAYS, RATES_CHANGE_WEIGHT,
                           RATES_LEVEL_BANDS, RATES_LEVEL_WEIGHT,
                           STALENESS_DAYS)
from ..core.types import (ComponentKind, ComponentScore, Confidence, Currency)
from ..ingest.calendar import EventReading
from ..ingest.cot import CotReading
from ..ingest.yields import YieldSet


def _band(value: float, bands: tuple[tuple[float, int], ...]) -> int:
    """Map a value through descending (threshold, score) pairs.

    Bands are written high-to-low; anything under the final threshold
    takes the bottom score. Kept as one helper so every component bands
    identically and a reader only has to understand it once.
    """
    for threshold, score in bands:
        if value >= threshold:
            return score
    return bands[-1][1] - 1 if bands[-1][1] > -3 else -3


def _clamp(value: int) -> int:
    return max(-3, min(3, value))


def _staleness(data_date: date | None, as_of: date, key: str) -> Confidence:
    if data_date is None:
        return Confidence.PARTIAL
    age = (as_of - data_date).days
    return Confidence.OK if age <= STALENESS_DAYS[key] else Confidence.STALE


# --------------------------------------------------------------------------
# Positioning
# --------------------------------------------------------------------------

def score_positioning(currency: Currency,
                      reading: CotReading | None,
                      as_of: date,
                      history: list[float] | None = None,
                      derived_net_share: float | None = None) -> ComponentScore:
    """Speculative positioning from the CFTC COT report.

    Scored on net leveraged-fund position as a share of open interest.
    Normalising by open interest is what makes a 40,000 net long in EUR
    comparable with one in NZD.

    When enough history exists the scorer switches to PERCENTILE ranking
    against the contract's own past, which is the better measure —
    crowding is relative to a contract's own norms, not to an absolute
    ratio that means different things in different futures.

    USD arrives via `derived_net_share` because it has no contract of
    its own; see cot.derive_usd.
    """
    if reading is None and derived_net_share is None:
        return ComponentScore(
            kind=ComponentKind.POSITIONING, value=0,
            reason="No COT data for this contract.",
            confidence=Confidence.UNAVAILABLE,
        )

    if reading is not None:
        share = reading.net_share_of_oi
        data_date: date | None = reading.report_date
        net_desc = f"net {reading.net:+,} of {reading.open_interest:,} OI"
    else:
        share = float(derived_net_share)   # type: ignore[arg-type]
        data_date = None
        net_desc = "derived from the other six contracts"

    confidence = _staleness(data_date, as_of, "positioning")

    if history and len(history) >= POSITIONING_MIN_HISTORY_WEEKS:
        below = sum(1 for h in history if h < share)
        pct = below / len(history)
        if pct >= 0.90:
            value, how = 3, f"{pct:.0%} percentile — crowded long"
        elif pct >= 0.75:
            value, how = 2, f"{pct:.0%} percentile"
        elif pct >= 0.60:
            value, how = 1, f"{pct:.0%} percentile"
        elif pct > 0.40:
            value, how = 0, f"{pct:.0%} percentile — mid-range"
        elif pct > 0.25:
            value, how = -1, f"{pct:.0%} percentile"
        elif pct > 0.10:
            value, how = -2, f"{pct:.0%} percentile"
        else:
            value, how = -3, f"{pct:.0%} percentile — crowded short"
    else:
        value = _band(share, POSITIONING_BANDS)
        weeks = len(history) if history else 0
        how = (f"{share:+.1%} of open interest "
               f"(level bands — {weeks}w history, "
               f"{POSITIONING_MIN_HISTORY_WEEKS}w needed for percentile)")

    return ComponentScore(
        kind=ComponentKind.POSITIONING,
        value=_clamp(value),
        reason=f"Leveraged funds {net_desc}; {how}.",
        confidence=confidence,
        inputs={"net_share_of_oi": round(share, 4),
                "report_date": data_date.isoformat() if data_date else None},
    )


# --------------------------------------------------------------------------
# Rates
# --------------------------------------------------------------------------

def score_rates(currency: Currency,
                yields: YieldSet | None,
                as_of: date) -> ComponentScore:
    """Two-year yield differential, and more importantly its repricing.

    The change is weighted above the level because spot responds to
    repricing — carry that is already in the price has already been
    traded.
    """
    if yields is None or currency not in yields.points:
        return ComponentScore(
            kind=ComponentKind.RATES, value=0,
            reason="No 2-year yield available for this currency.",
            confidence=Confidence.UNAVAILABLE,
        )

    level = yields.differential(currency)
    change = yields.differential_change_bps(currency)

    if level is None:
        return ComponentScore(
            kind=ComponentKind.RATES, value=0,
            reason="Too few peer yields to form a differential.",
            confidence=Confidence.PARTIAL,
        )

    level_score = _band(level, RATES_LEVEL_BANDS)

    if change is None:
        value = level_score
        confidence = Confidence.PARTIAL
        reason = (f"2y differential {level:+.2f}pp vs peers "
                  f"(level only — no {RATES_CHANGE_LOOKBACK_DAYS}-day history "
                  f"to measure repricing).")
    else:
        change_score = _band(change, RATES_CHANGE_BANDS)
        blended = (level_score * RATES_LEVEL_WEIGHT
                   + change_score * RATES_CHANGE_WEIGHT)
        value = round(blended)
        confidence = _staleness(yields.as_of, as_of, "rates")
        direction = "widening" if change > 0 else "narrowing"
        reason = (f"2y differential {level:+.2f}pp vs peers, "
                  f"{direction} {abs(change):.0f}bp over "
                  f"{RATES_CHANGE_LOOKBACK_DAYS} days.")

    if not yields.verified_source:
        confidence = Confidence.PARTIAL
        reason += " Source not verified."

    return ComponentScore(
        kind=ComponentKind.RATES,
        value=_clamp(int(value)),
        reason=reason,
        confidence=confidence,
        inputs={"differential_pp": round(level, 3),
                "change_bps": round(change, 1) if change is not None else None},
    )


# --------------------------------------------------------------------------
# Calendar
# --------------------------------------------------------------------------

def score_calendar(currency: Currency,
                   events: list[EventReading],
                   as_of: date,
                   feed_has_actuals: bool = False) -> ComponentScore:
    """Scheduled releases, weighted by impact.

    Reads actual-vs-forecast when the feed carries actuals and
    forecast-vs-previous when it does not. The reason text names which,
    because they are not the same signal and the weaker one should not
    be mistaken for the stronger.
    """
    mine = [e for e in events if e.currency is currency]
    if not mine:
        return ComponentScore(
            kind=ComponentKind.CALENDAR, value=0,
            reason="No High or Medium impact events in the window.",
            confidence=Confidence.OK,   # genuinely nothing on, not a failure
            inputs={"events": 0},
        )

    contributions: list[float] = []
    skipped = 0
    for event in mine:
        surprise = event.surprise
        if surprise is None:
            skipped += 1
            continue
        contributions.append(surprise * event.weight)

    if not contributions:
        return ComponentScore(
            kind=ComponentKind.CALENDAR, value=0,
            reason=(f"{len(mine)} event(s) scheduled but none scoreable "
                    "— missing figures or an unrecognised indicator."),
            confidence=Confidence.PARTIAL,
            inputs={"events": len(mine), "skipped": skipped},
        )

    total = sum(contributions)
    value = _band(total, CALENDAR_BANDS)

    basis = ("actual vs forecast" if feed_has_actuals
             else "forecast vs previous — expectations, not surprises")
    confidence = Confidence.OK if feed_has_actuals else Confidence.PARTIAL

    return ComponentScore(
        kind=ComponentKind.CALENDAR,
        value=_clamp(value),
        reason=(f"{len(contributions)} of {len(mine)} event(s) scored, "
                f"weighted sum {total:+.2f} ({basis})."),
        confidence=confidence,
        inputs={"events": len(mine), "scored": len(contributions),
                "weighted_sum": round(total, 3)},
    )
