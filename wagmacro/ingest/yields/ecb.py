"""EUR — European Central Bank, euro area yield curve, 2-year spot.

Series key B.U2.EUR.4F.G_N_A.SV_C_YM.SR_2Y.

AAA-only (`G_N_A`) rather than all-government (`G_N_C`). The gap between
them is peripheral credit spread, and this component is meant to measure
the expected policy path, not Italy's risk premium. The all-government
key is kept below so the choice is visible and reversible rather than
buried.

Verified reachable and correct on 2026-10-15:
    YC.B.U2.EUR.4F.G_N_A.SV_C_YM.SR_2Y,...,2026-08-21,2.7610795861,A,F,...
"""

from __future__ import annotations

import csv
import io
from datetime import date, timedelta

from ...core.types import Currency
from .base import ProviderResult, Series

_BASE = "https://data-api.ecb.europa.eu/service/data/YC/"
KEY_AAA = "B.U2.EUR.4F.G_N_A.SV_C_YM.SR_2Y"
KEY_ALL_GOVT = "B.U2.EUR.4F.G_N_C.SV_C_YM.SR_2Y"


def url(days: int = 120, key: str = KEY_AAA) -> str:
    start = (date.today() - timedelta(days=days)).isoformat()
    return f"{_BASE}{key}?startPeriod={start}&format=csvdata"


def parse(text: str) -> Series:
    """Read TIME_PERIOD / OBS_VALUE by column NAME, not position.

    The response carries ~30 columns and a free-text note containing
    commas, so this goes through csv.reader and looks the two columns up
    in the header rather than counting fields.
    """
    reader = csv.reader(io.StringIO(text))
    try:
        header = next(reader)
    except StopIteration:
        return ()

    try:
        i_date = header.index("TIME_PERIOD")
        i_value = header.index("OBS_VALUE")
    except ValueError:
        return ()

    out: list[tuple[date, float]] = []
    for row in reader:
        if len(row) <= max(i_date, i_value):
            continue
        raw_date, raw_value = row[i_date].strip(), row[i_value].strip()
        if not raw_date or not raw_value:
            continue
        try:
            out.append((date.fromisoformat(raw_date), float(raw_value)))
        except ValueError:
            continue
    out.sort()
    return tuple(out)


def fetch(get) -> ProviderResult:
    target = url()
    status, body = get(target)
    if status != 200:
        return ProviderResult(Currency.EUR, target,
                              detail=f"HTTP {status}")
    series = parse(body.decode("utf-8", errors="replace"))
    if not series:
        return ProviderResult(Currency.EUR, target,
                              detail="fetched but no observations parsed")
    return ProviderResult(Currency.EUR, target, series=series, ok=True,
                          detail=f"{len(series)} obs, latest {series[-1][0]}")
