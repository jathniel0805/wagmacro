"""The yield contract the scorer consumes, and the shape adapters return.

`YieldSet` is unchanged from the original module — the scorer and its
tests depend on it, and swapping the data sources underneath is exactly
what this package exists to make possible.

Each adapter contributes a plain series of (date, yield_pct) and knows
nothing about scoring, differentials or any other currency. Assembling
those into a YieldSet happens in one place, in `__init__.py`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from ...core.types import Currency

#: Series are returned oldest-first.
Series = tuple[tuple[date, float], ...]


@dataclass(frozen=True, slots=True)
class ProviderResult:
    """What one publisher gave us, successful or not."""

    currency: Currency
    url: str
    series: Series = ()
    ok: bool = False
    detail: str = ""

    @property
    def latest(self) -> tuple[date, float] | None:
        return self.series[-1] if self.series else None


@dataclass(frozen=True, slots=True)
class YieldPoint:
    currency: Currency
    as_of: date
    yield_pct: float
    yield_pct_prior: float | None = None   # same series, lookback window ago

    @property
    def change_bps(self) -> float | None:
        if self.yield_pct_prior is None:
            return None
        return (self.yield_pct - self.yield_pct_prior) * 100.0


@dataclass(frozen=True, slots=True)
class YieldSet:
    """Yields for every currency available on a given day."""

    as_of: date
    points: dict[Currency, YieldPoint]
    verified_source: bool
    notes: tuple[str, ...] = field(default=())

    def differential(self, currency: Currency) -> float | None:
        """This currency's 2y yield minus the mean of the others.

        A simple mean rather than trade weights. Trade weighting is the
        better measure and is the obvious next refinement, but it needs
        a weights table that is itself a sourcing decision — doing it
        badly would be worse than doing it plainly.
        """
        point = self.points.get(currency)
        if point is None:
            return None
        others = [p.yield_pct for c, p in self.points.items() if c is not currency]
        if len(others) < 3:
            return None
        return point.yield_pct - (sum(others) / len(others))

    def differential_change_bps(self, currency: Currency) -> float | None:
        """Change in that differential over the lookback window."""
        point = self.points.get(currency)
        if point is None or point.change_bps is None:
            return None
        other_changes = [
            p.change_bps for c, p in self.points.items()
            if c is not currency and p.change_bps is not None
        ]
        if len(other_changes) < 3:
            return None
        return point.change_bps - (sum(other_changes) / len(other_changes))


def from_manual(as_of: date,
                levels: dict[Currency, float],
                priors: dict[Currency, float] | None = None) -> YieldSet:
    """Build a YieldSet from hand-entered numbers.

    Kept as the override for when a provider breaks, and as what the
    sample dataset and the model tests run on.
    """
    priors = priors or {}
    points = {
        currency: YieldPoint(
            currency=currency,
            as_of=as_of,
            yield_pct=level,
            yield_pct_prior=priors.get(currency),
        )
        for currency, level in levels.items()
    }
    return YieldSet(as_of=as_of, points=points, verified_source=True)


#: Dates where two merged sources disagreed, with both values. Read by
#: the adapters and surfaced in the diagnostic — see merge() below.
last_merge_conflicts: tuple[str, ...] = ()

#: Below this, a disagreement is rounding between publishers' own
#: precision. Above it, the two files are probably different series.
MERGE_CONFLICT_TOLERANCE = 0.005


def merge(*parts: Series) -> Series:
    """Combine several series, later arguments winning on a shared date.

    Several publishers split their data across a long archive and a
    small current-period file. Taking whichever one answers first gets
    you either deep history or a fresh reading, never both — the UK
    series came back fourteen days stale for exactly that reason. Merging
    keeps the archive's depth and the current file's freshness, and the
    argument order decides who wins where they overlap.

    It also records where the sources DISAGREED. Two files from the same
    publisher that give different numbers for the same day are usually
    not the same series, and silently letting one overwrite the other is
    how a wrong number enters without anybody noticing. An RBA file
    added speculatively did exactly that — it moved a verified reading
    by 2bp — which is why this reporting exists.
    """
    global last_merge_conflicts
    combined: dict[date, float] = {}
    conflicts: list[str] = []

    for part in parts:
        for when, value in part:
            previous = combined.get(when)
            if previous is not None and \
                    abs(previous - value) > MERGE_CONFLICT_TOLERANCE:
                if len(conflicts) < 5:
                    conflicts.append(f"{when}: {previous} vs {value}")
            combined[when] = value

    last_merge_conflicts = tuple(conflicts)
    return tuple(sorted(combined.items()))


def point_from_series(currency: Currency, series: Series,
                      lookback: int) -> YieldPoint | None:
    """Latest observation, plus the one `lookback` observations earlier.

    Counting observations rather than calendar days is deliberate: the
    series are already business-daily, and counting rows avoids landing
    the comparison on a weekend or a national holiday that differs by
    country.
    """
    if not series:
        return None
    as_of, latest = series[-1]
    prior = series[-(lookback + 1)][1] if len(series) > lookback else None
    return YieldPoint(currency=currency, as_of=as_of,
                      yield_pct=latest, yield_pct_prior=prior)
