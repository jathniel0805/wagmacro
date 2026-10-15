"""CAD — Bank of Canada Valet, benchmark 2-year government bond yield.

Series BD.CDN.2YR.DQ.YLD, confirmed on 2026-10-15 by the series detail
the API returns alongside the observations:

    "BD.CDN.2YR.DQ.YLD": {"label": "Benchmark bond yield, 2-year", ...}
"""

from __future__ import annotations

import json
from datetime import date

from ...core.types import Currency
from .base import ProviderResult, Series

SERIES = "BD.CDN.2YR.DQ.YLD"


def url(observations: int = 120) -> str:
    return ("https://www.bankofcanada.ca/valet/observations/"
            f"{SERIES}/json?recent={observations}")


def parse(text: str) -> Series:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return ()

    out: list[tuple[date, float]] = []
    for obs in payload.get("observations", []):
        raw_date = obs.get("d")
        cell = obs.get(SERIES) or {}
        raw_value = cell.get("v")
        # Valet uses an empty string for a non-trading day, not null.
        if not raw_date or raw_value in (None, ""):
            continue
        try:
            out.append((date.fromisoformat(raw_date), float(raw_value)))
        except (ValueError, TypeError):
            continue
    out.sort()
    return tuple(out)


def fetch(get) -> ProviderResult:
    target = url()
    status, body = get(target)
    if status != 200:
        return ProviderResult(Currency.CAD, target, detail=f"HTTP {status}")
    series = parse(body.decode("utf-8", errors="replace"))
    if not series:
        return ProviderResult(Currency.CAD, target,
                              detail="fetched but no observations parsed")
    return ProviderResult(Currency.CAD, target, series=series, ok=True,
                          detail=f"{len(series)} obs, latest {series[-1][0]}")
