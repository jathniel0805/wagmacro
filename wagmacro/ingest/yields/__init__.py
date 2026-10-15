"""Two-year government bond yields, one adapter per publisher.

The 2y yield is the market's pricing of the policy path over roughly the
horizon FX trades on. It beats a policy-rate table because it moves
daily, and because spot responds to REPRICING rather than to carry that
is already in the price.

WHY SIX ADAPTERS INSTEAD OF ONE FEED

FRED was the original plan and it does not work: it refuses datacenter
IP ranges, so every request from the build runner times out. Rather than
settle for an aggregator — Stooq was tried and serves HTML, not data —
each currency now comes from the institution that actually sets and
publishes it. Each source was verified by fetching it and reading what
came back, not by recognising the URL.

    USD  US Treasury par yield curve       treasury.py
    EUR  ECB euro area yield curve         ecb.py
    GBP  BoE government liability curve    boe.py
    JPY  MOF JGB interest rates            mof.py
    CAD  Bank of Canada Valet              boc.py
    AUD  RBA table F2                      rba.py

NZD IS ABSENT ON PURPOSE. The RBNZ and NZ Debt Management both return
403 to the build runner — a blanket block on the IP range, not a wrong
path. No proxy is substituted: a policy rate dressed up as a 2y yield
would corrupt every other currency's differential, since the differential
is measured against the mean of the peers. NZD's Rates component scores
zero and says so, which is the honest reading and the one the dashboard
already knows how to display.

This leaves NZD scoring on two components out of three, so its total
cannot reach the same extremes as the others. That is reported, never
scaled — rescaling would manufacture precision that the data has not
earned.
"""

from __future__ import annotations

import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date

from ...core.config import RATES_CHANGE_LOOKBACK_DAYS
from ...core.types import Currency
from . import boc, boe, ecb, mof, rba, treasury
from .base import (ProviderResult, Series, YieldPoint, YieldSet, from_manual,
                   point_from_series)

__all__ = [
    "YieldPoint", "YieldSet", "Series", "ProviderResult",
    "from_manual", "fetch_all", "PROVIDERS", "REQUIRED_HOSTS",
]

#: Order here is display order in the diagnostic, nothing more.
PROVIDERS = {
    Currency.USD: treasury,
    Currency.EUR: ecb,
    Currency.GBP: boe,
    Currency.JPY: mof,
    Currency.CAD: boc,
    Currency.AUD: rba,
}

#: The hosts this package needs. NZ is deliberately not here — see above.
REQUIRED_HOSTS = (
    "home.treasury.gov",
    "data-api.ecb.europa.eu",
    "www.bankofengland.co.uk",
    "www.mof.go.jp",
    "www.bankofcanada.ca",
    "www.rba.gov.au",
)

_UA = {"User-Agent": "Mozilla/5.0 (compatible; wagmacro/1.1; research)"}
_TIMEOUT = 30


def _get(url: str) -> tuple[int, bytes]:
    """Fetch raw BYTES, never raising.

    Deliberately not `ingest.transport.fetch`: that layer decodes to
    text and caches, which is right for the CSV and JSON feeds it was
    built for. Two sources here cannot survive that — the MOF file is
    Shift-JIS and the BoE file is a zip archive — so they need the bytes
    exactly as sent.
    """
    try:
        request = urllib.request.Request(url, headers=_UA)
        with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, b""
    except Exception:                        # noqa: BLE001 - never raise
        return 0, b""


def fetch_providers() -> dict[Currency, ProviderResult]:
    """Run every adapter in parallel. One slow publisher must not stall
    the build, and one broken publisher must not lose the other five."""

    def run(item):
        currency, module = item
        try:
            return currency, module.fetch(_get)
        except Exception as exc:             # noqa: BLE001 - isolate failures
            return currency, ProviderResult(
                currency, getattr(module, "URL", ""),
                detail=f"adapter raised {type(exc).__name__}: {exc}")

    with ThreadPoolExecutor(max_workers=len(PROVIDERS)) as pool:
        return dict(pool.map(run, PROVIDERS.items()))


def fetch_all(as_of: date | None = None,
              lookback: int = RATES_CHANGE_LOOKBACK_DAYS,
              ) -> tuple[YieldSet, dict[Currency, ProviderResult]]:
    """Build a YieldSet from the live publishers.

    Returns the set and the per-provider results, so the caller can
    report exactly which source produced which number instead of
    presenting an opaque total.
    """
    results = fetch_providers()

    points: dict[Currency, YieldPoint] = {}
    notes: list[str] = []
    for currency, result in results.items():
        if not result.ok:
            notes.append(f"{currency.value}: {result.detail}")
            continue
        point = point_from_series(currency, result.series, lookback)
        if point is None:
            notes.append(f"{currency.value}: empty series")
            continue
        if point.yield_pct_prior is None:
            notes.append(
                f"{currency.value}: only {len(result.series)} observations, "
                f"fewer than the {lookback} needed to measure repricing")
        points[currency] = point

    notes.append("NZD: no reachable publisher (RBNZ and NZDM block the "
                 "build runner); Rates scores 0 for NZD by design")

    latest = max((p.as_of for p in points.values()), default=as_of or date.today())
    return YieldSet(as_of=latest, points=points, verified_source=bool(points),
                    notes=tuple(notes)), results
