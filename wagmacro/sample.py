"""An illustrative dataset for exercising the pipeline with no network.

EVERY NUMBER IN THIS FILE IS INVENTED.

It exists so the layout, the scoring path and the renderer can be
reviewed before the data sources are wired up. It is not market data,
it is not a forecast, and the board renders a permanent banner saying
so whenever it is used. `cli.py` also refuses to archive a sample board
into the history store, so it can never contaminate the record that
calibration will later be based on.

The shapes are realistic — a high-yielding dollar, a low-yielding yen,
commodity currencies in the middle — purely so the dashboard shows a
spread of bands rather than seven identical cells.
"""

from __future__ import annotations

from datetime import date, datetime

from .core.types import Currency
from .ingest.calendar import EventReading
from .ingest.cot import CotReading
from .ingest.yields import from_manual

_AS_OF = date(2026, 10, 13)

_COT = {
    Currency.EUR: CotReading(Currency.EUR, _AS_OF, 742_000, 198_000, 151_000),
    Currency.GBP: CotReading(Currency.GBP, _AS_OF, 281_000, 94_000, 61_000),
    Currency.JPY: CotReading(Currency.JPY, _AS_OF, 316_000, 52_000, 148_000),
    Currency.AUD: CotReading(Currency.AUD, _AS_OF, 198_000, 61_000, 74_000),
    Currency.CAD: CotReading(Currency.CAD, _AS_OF, 371_000, 72_000, 118_000),
    Currency.NZD: CotReading(Currency.NZD, _AS_OF, 64_000, 17_000, 26_000),
}

_YIELDS = from_manual(
    _AS_OF,
    levels={
        Currency.USD: 4.05, Currency.GBP: 3.92, Currency.AUD: 3.55,
        Currency.NZD: 3.20, Currency.CAD: 2.85, Currency.EUR: 2.05,
        Currency.JPY: 0.72,
    },
    priors={
        Currency.USD: 3.74, Currency.GBP: 3.95, Currency.AUD: 3.58,
        Currency.NZD: 3.34, Currency.CAD: 2.88, Currency.EUR: 2.11,
        Currency.JPY: 0.55,
    },
)

_EVENTS = [
    EventReading(Currency.USD, "CPI y/y", datetime(2026, 10, 14, 12, 30), 3, 3.6, 3.4),
    EventReading(Currency.USD, "Core CPI m/m", datetime(2026, 10, 14, 12, 30), 3, 0.3, 0.2),
    EventReading(Currency.USD, "Unemployment Claims", datetime(2026, 10, 16, 12, 30), 2, 228.0, 241.0),
    EventReading(Currency.EUR, "Final CPI y/y", datetime(2026, 10, 17, 9, 0), 3, 1.9, 2.2),
    EventReading(Currency.EUR, "Flash Manufacturing PMI", datetime(2026, 10, 19, 8, 0), 3, 47.1, 48.0),
    EventReading(Currency.GBP, "CPI y/y", datetime(2026, 10, 15, 6, 0), 3, 3.1, 3.0),
    EventReading(Currency.GBP, "Retail Sales m/m", datetime(2026, 10, 17, 6, 0), 3, 0.4, 0.1),
    EventReading(Currency.JPY, "National Core CPI y/y", datetime(2026, 10, 17, 23, 30), 3, 2.9, 2.7),
    EventReading(Currency.AUD, "Employment Change", datetime(2026, 10, 16, 0, 30), 3, 18.5, 42.6),
    EventReading(Currency.AUD, "Unemployment Rate", datetime(2026, 10, 16, 0, 30), 3, 4.4, 4.2),
    EventReading(Currency.NZD, "CPI q/q", datetime(2026, 10, 16, 21, 45), 3, 0.6, 0.9),
    EventReading(Currency.CAD, "Core Retail Sales m/m", datetime(2026, 10, 17, 12, 30), 3, 0.5, 0.2),
]

SAMPLE = {
    "cot": _COT,
    "events": _EVENTS,
    "yields": _YIELDS,
    "has_actuals": False,
}
