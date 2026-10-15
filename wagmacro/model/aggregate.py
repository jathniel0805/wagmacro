"""Combine component scores into a board.

Deliberately thin. The judgement lives in the scorers and the bands
live in config; this module only assembles and applies the banding, so
there is exactly one place where "what is the total" is answered.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from ..core.config import BANDS, METHODOLOGY_VERSION
from ..core.types import (Board, ComponentScore, Currency, CurrencyReading,
                          SourceStamp)


def build_reading(currency: Currency,
                  components: list[ComponentScore],
                  *,
                  derived: bool = False,
                  note: str = "") -> CurrencyReading:
    """One currency's reading.

    `note` is the judgement layer — central-bank tone, live risk events.
    It is carried for display and NEVER added to the total. Keeping the
    number purely mechanical is what makes it reproducible; mixing an
    opinion into it would make the whole board an opinion.
    """
    total = sum(c.value for c in components)
    return CurrencyReading(
        currency=currency,
        components=tuple(components),
        total=total,
        band=BANDS.band_for(total),
        derived=derived,
        note=note,
    )


def build_board(as_of: date,
                readings: list[CurrencyReading],
                sources: dict[str, SourceStamp]) -> Board:
    return Board(
        as_of=as_of,
        generated_at=datetime.now(timezone.utc),
        methodology_version=METHODOLOGY_VERSION,
        readings=tuple(readings),
        sources=sources,
    )


def pair_bias(board: Board, base: Currency, quote: Currency) -> int | None:
    """Fundamental bias for a pair: base total minus quote total.

    The bridge to the technical side. J-SCORING produces a pair score
    from currency strength; this produces the same shape from macro, so
    the two can be read side by side — agreement is confluence,
    disagreement is a reason to stand down.

    Deliberately NOT banded here. The pair-level thresholds are a
    separate calibration from the single-currency ones and should be
    fitted to observed pair spreads, not inherited.
    """
    b = board.reading(base)
    q = board.reading(quote)
    if b is None or q is None:
        return None
    return b.total - q.total
