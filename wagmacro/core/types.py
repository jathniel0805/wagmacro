"""Domain types for the macro bias model.

Everything here is immutable and transport-agnostic. Nothing in this
module knows where data came from or how it will be displayed — that
separation is what lets the same model back a daily script today and a
subscription web service later without rewriting the part that thinks.

Design rules enforced here:

  * Frozen dataclasses, never bare dicts. A typo in a dict key is a
    silent wrong number; a typo in a field name is an error at import.
  * Every score carries its REASON and its INPUTS. A dashboard cell that
    cannot explain itself is not auditable, and an unauditable number in
    a trading tool is worse than no number.
  * Every reading records the methodology version that produced it, so
    recalibrating the model never silently rewrites history.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Mapping, Sequence


# --------------------------------------------------------------------------
# Currencies
# --------------------------------------------------------------------------

class Currency(str, Enum):
    """The seven majors this model covers."""

    AUD = "AUD"
    CAD = "CAD"
    EUR = "EUR"
    GBP = "GBP"
    JPY = "JPY"
    NZD = "NZD"
    USD = "USD"

    @classmethod
    def all(cls) -> tuple["Currency", ...]:
        return tuple(cls)

    @classmethod
    def non_usd(cls) -> tuple["Currency", ...]:
        """Every currency with its own futures contract.

        USD is deliberately excluded: the CFTC publishes currency futures
        quoted AGAINST the dollar, so there is no USD contract to read.
        The USD reading is derived from the aggregate of the others, and
        that difference is surfaced in the UI rather than hidden.
        """
        return tuple(c for c in cls if c is not cls.USD)


# --------------------------------------------------------------------------
# Scoring
# --------------------------------------------------------------------------

class ComponentKind(str, Enum):
    RATES = "rates"          # 2y yield differential and its repricing
    POSITIONING = "positioning"   # CFTC Commitment of Traders
    CALENDAR = "calendar"    # forecast vs previous on scheduled releases


class Confidence(str, Enum):
    """How much the component's own inputs can be trusted today.

    A component that could not get fresh data still returns a score of
    zero rather than vanishing, but it says so. Silent degradation is
    how a dashboard starts lying.
    """

    OK = "ok"
    STALE = "stale"          # data older than the component's refresh window
    PARTIAL = "partial"      # some inputs missing
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class ComponentScore:
    """One component's contribution for one currency.

    `value` is clamped to [-3, +3] by the scorer. `reason` is written for
    a human reading the dashboard, not for a log file.
    """

    kind: ComponentKind
    value: int
    reason: str
    confidence: Confidence = Confidence.OK
    inputs: Mapping[str, float | str | None] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not -3 <= self.value <= 3:
            raise ValueError(
                f"{self.kind.value} score {self.value} outside [-3, +3]; "
                "scorers must clamp before constructing a ComponentScore"
            )


class Band(str, Enum):
    """Display band. Thresholds live in config, not here."""

    STRONG_BULL = "strong_bull"
    BULL = "bull"
    NEUTRAL = "neutral"
    BEAR = "bear"
    STRONG_BEAR = "strong_bear"

    @property
    def is_actionable(self) -> bool:
        return self in (Band.STRONG_BULL, Band.STRONG_BEAR)


@dataclass(frozen=True, slots=True)
class CurrencyReading:
    """The full picture for one currency on one day."""

    currency: Currency
    components: tuple[ComponentScore, ...]
    total: int
    band: Band
    derived: bool = False     # True for USD, which has no futures contract
    note: str = ""            # the judgement layer; never feeds `total`

    def component(self, kind: ComponentKind) -> ComponentScore | None:
        for c in self.components:
            if c.kind is kind:
                return c
        return None

    @property
    def weakest_link(self) -> Confidence:
        """The worst confidence among the components.

        Surfaced so a reading built on two stale inputs cannot look as
        solid as one built on three fresh ones.
        """
        order = [Confidence.OK, Confidence.STALE,
                 Confidence.PARTIAL, Confidence.UNAVAILABLE]
        return max((c.confidence for c in self.components),
                   key=order.index, default=Confidence.UNAVAILABLE)


@dataclass(frozen=True, slots=True)
class Board:
    """A full day's board — what gets stored and what gets rendered."""

    as_of: date
    generated_at: datetime
    methodology_version: str
    readings: tuple[CurrencyReading, ...]
    sources: Mapping[str, "SourceStamp"] = field(default_factory=dict)

    def reading(self, currency: Currency) -> CurrencyReading | None:
        for r in self.readings:
            if r.currency is currency:
                return r
        return None

    def ranked(self) -> Sequence[CurrencyReading]:
        """Strongest to weakest. The order a trader actually scans in."""
        return sorted(self.readings, key=lambda r: (-r.total, r.currency.value))


# --------------------------------------------------------------------------
# Provenance
# --------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class SourceStamp:
    """Where a number came from and how old it is.

    Carried all the way to the UI. If a user ever asks "why is CAD red",
    the answer has to be reachable from the screen, not from a logfile
    on someone's laptop.
    """

    name: str
    url: str
    retrieved_at: datetime | None
    data_dated: date | None
    transport: str            # "http" | "cache" | "manual" | "unavailable"
    ok: bool
    detail: str = ""


@dataclass(frozen=True, slots=True)
class RawPayload:
    """Bytes as fetched, plus where they came from.

    Kept deliberately dumb. Parsers take this; fetchers return it. Storing
    the raw payload beside the parsed output is what makes a disputed
    number reproducible months later.
    """

    stamp: SourceStamp
    body: str

    @property
    def ok(self) -> bool:
        return self.stamp.ok and bool(self.body)
