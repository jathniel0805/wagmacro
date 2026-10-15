"""ForexFactory economic calendar.

Source: https://nfs.faireconomy.media/ff_calendar_thisweek.json

VERIFIED LIMITATION — read this before trusting the component.

The feed carries `forecast` and `previous` but NOT `actual`. Confirmed
by inspection on 2026-10-15, including for events that had already
released earlier the same week.

That means this component scores EXPECTATIONS (is the next print
expected to run hotter or cooler than the last one?) and not SURPRISES
(did it beat?). Expectations are the weaker signal — the market has
largely priced them — and the component's reason text says so, so a
reader is never misled about which of the two they are looking at.

Wiring in a true surprise index needs a feed that publishes actuals.
When one is added, `EventReading.surprise` is the hook: fill `actual`
and the scorer uses it in preference to the forecast-vs-previous path
with no other change.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from ..core.config import (CALENDAR_DIRECTION, CALENDAR_IMPACT_WEIGHT,
                           CALENDAR_LOOKAHEAD_DAYS, CALENDAR_LOOKBACK_DAYS)
from ..core.types import Currency, RawPayload

IMPACT_LEVELS = {"high": 3, "medium": 2, "low": 1}

#: Strips %, commas, currency marks and unit suffixes so "3.6%" and
#: "-12.4B" both become floats. Keeps the sign.
_NUMERIC = re.compile(r"-?\d+(?:\.\d+)?")


@dataclass(frozen=True, slots=True)
class EventReading:
    currency: Currency
    title: str
    when: datetime
    impact: int
    forecast: float | None
    previous: float | None
    actual: float | None = None      # hook for a future feed that has it

    @property
    def higher_is_bullish(self) -> bool | None:
        """Look the indicator up in the direction table.

        First match wins, so the table is ordered specific-before-general.
        An unrecognised indicator returns None and is skipped rather than
        guessed at — a wrong sign is worse than a missing data point.
        """
        lowered = self.title.lower()
        for needle, bullish in CALENDAR_DIRECTION:
            if needle in lowered:
                return bullish
        return None

    @property
    def surprise(self) -> float | None:
        """Signed, scale-free move, already direction-adjusted.

        Uses actual-vs-forecast when an actual exists, otherwise
        forecast-vs-previous. Normalised by the magnitude of the
        baseline so a 0.2pp move in CPI is not swamped by a 20k move
        in payrolls.
        """
        direction = self.higher_is_bullish
        if direction is None:
            return None

        if self.actual is not None and self.forecast is not None:
            new, base = self.actual, self.forecast
        elif self.forecast is not None and self.previous is not None:
            new, base = self.forecast, self.previous
        else:
            return None

        denominator = max(abs(base), 0.1)   # floor: many series sit near zero
        raw = (new - base) / denominator
        raw = max(-1.0, min(1.0, raw))      # clamp: one print cannot dominate
        return raw if direction else -raw

    @property
    def weight(self) -> float:
        return CALENDAR_IMPACT_WEIGHT.get(self.impact, 0.0)


def _parse_number(raw: str | None) -> float | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text or text in {"", "-", "N/A"}:
        return None
    match = _NUMERIC.search(text.replace(",", ""))
    if not match:
        return None
    value = float(match.group())
    # Suffixes change magnitude but the comparison is like-for-like
    # within an indicator, so scaling is unnecessary — and applying it
    # inconsistently would be worse than leaving it alone.
    return value


def parse(payload: RawPayload,
          tracked: tuple[Currency, ...] | None = None) -> list[EventReading]:
    """Parse the feed into typed events for the tracked currencies."""
    if not payload.ok:
        return []

    try:
        raw_events = json.loads(payload.body)
    except json.JSONDecodeError:
        return []
    if not isinstance(raw_events, list):
        return []

    names = {c.value for c in (tracked or Currency.all())}
    out: list[EventReading] = []

    for item in raw_events:
        if not isinstance(item, dict):
            continue
        country = str(item.get("country", "")).strip().upper()
        if country not in names:
            continue

        impact = IMPACT_LEVELS.get(str(item.get("impact", "")).strip().lower(), 0)
        if impact < 2:                      # Low and unrecognised discarded
            continue

        raw_date = str(item.get("date", "")).strip()
        try:
            when = datetime.fromisoformat(raw_date)
        except ValueError:
            continue

        title = str(item.get("title", "")).strip()
        if not title:
            continue

        out.append(EventReading(
            currency=Currency(country),
            title=title,
            when=when,
            impact=impact,
            forecast=_parse_number(item.get("forecast")),
            previous=_parse_number(item.get("previous")),
            actual=_parse_number(item.get("actual")),
        ))

    return out


def in_window(events: list[EventReading], as_of: date) -> list[EventReading]:
    """Trim to the scoring window around `as_of`."""
    start = as_of - timedelta(days=CALENDAR_LOOKBACK_DAYS)
    end = as_of + timedelta(days=CALENDAR_LOOKAHEAD_DAYS)
    return [e for e in events if start <= e.when.date() <= end]


def feed_has_actuals(events: list[EventReading]) -> bool:
    """Whether this payload carried any actuals.

    Drives the wording of the component's reason, so the dashboard can
    say whether it is reading surprises or merely expectations.
    """
    return any(e.actual is not None for e in events)
