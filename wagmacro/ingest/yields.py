"""Two-year government bond yields.

The 2y yield is the market's pricing of the policy path over roughly
the horizon FX trades on. It is a better input than a policy-rate table
because it moves daily and because spot responds to REPRICING, not to
carry that is already in the price.

ARCHITECTURAL NOTE

This module is provider-agnostic on purpose. `YieldSet` is what the
scorer consumes; how it gets filled is a detail. Today there are two
fillers:

    from_manual(...)   — a small table a human maintains or pastes
    from_fred(...)     — the real adapter, once the host is allowlisted

The FRED series identifiers below are UNVERIFIED. They have not been
fetched and confirmed, because the host is not currently reachable from
this environment. They are written down as a starting point for
verification, not as established fact — `SERIES_VERIFIED` is False and
the adapter refuses to run until someone checks them and flips it.

That is deliberate. A plausible-looking wrong series ID would produce a
plausible-looking wrong yield, and a wrong yield differential would
quietly poison the most heavily weighted component in the model.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from ..core.types import Currency, RawPayload

#: Candidate FRED series for 2-year government yields, PENDING VERIFICATION.
#: Check each against https://fred.stlouisfed.org before use: confirm the
#: series is a 2-year constant-maturity GOVERNMENT yield, in percent,
#: daily, and still updating.
FRED_SERIES_CANDIDATES: dict[Currency, str] = {
    Currency.USD: "DGS2",            # most likely correct; still verify
    Currency.EUR: "IRLTLT01DEM156N",  # long-term rate, probably 10y — CHECK
    Currency.GBP: "IRLTLT01GBM156N",  # same caveat
    Currency.JPY: "IRLTLT01JPM156N",
    Currency.CAD: "IRLTLT01CAM156N",
    Currency.AUD: "IRLTLT01AUM156N",
    Currency.NZD: "IRLTLT01NZM156N",
}

#: Flip to True only after every series above has been fetched and
#: confirmed to be a 2-year government yield.
SERIES_VERIFIED = False


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

    Seven figures that move slowly. Entirely reasonable as the interim
    path while the allowlist is sorted, and useful forever as the
    override when a provider breaks.
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


def from_fred(payloads: dict[Currency, RawPayload], as_of: date) -> YieldSet:
    """Build a YieldSet from FRED CSV payloads.

    Refuses to run while SERIES_VERIFIED is False. See the module
    docstring — an unverified series ID is a silent correctness bug in
    the model's heaviest component.
    """
    if not SERIES_VERIFIED:
        raise RuntimeError(
            "FRED series identifiers have not been verified. Confirm each "
            "entry in FRED_SERIES_CANDIDATES is a 2-year government yield, "
            "then set SERIES_VERIFIED = True."
        )

    points: dict[Currency, YieldPoint] = {}
    for currency, payload in payloads.items():
        if not payload.ok:
            continue
        rows = [line.split(",") for line in payload.body.strip().splitlines()[1:]]
        series = [
            (r[0].strip(), float(r[1]))
            for r in rows
            if len(r) >= 2 and r[1].strip() not in {"", "."}
        ]
        if not series:
            continue
        latest = series[-1]
        prior = series[-21] if len(series) >= 21 else None
        points[currency] = YieldPoint(
            currency=currency,
            as_of=date.fromisoformat(latest[0]),
            yield_pct=latest[1],
            yield_pct_prior=prior[1] if prior else None,
        )
    return YieldSet(as_of=as_of, points=points, verified_source=True)
