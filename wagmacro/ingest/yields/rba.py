"""AUD — Reserve Bank of Australia, table F2, 2-year government bond.

Verified on 2026-10-15. The file opens with a metadata block before any
data appears:

    F2 CAPITAL MARKET YIELDS – GOVERNMENT BONDS
    Title,Australian Government 2 year bond,Australian Government 3 year...
    Description,"Yields on Australian government bonds, interpolated, 2 ...
    Frequency,Daily,Daily,Daily,Daily,Daily
    Type,Original,Original,...
    Units,Per cent per annum,...

so the column is found from the Title row by matching "2 year", and the
data is whatever rows below it start with a parseable date. Counting
preamble rows would break the first time the RBA adds a line to it.
"""

from __future__ import annotations

import csv
import io
from datetime import date, datetime

from ...core.types import Currency
from .base import ProviderResult, Series

URL = "https://www.rba.gov.au/statistics/tables/csv/f2-data.csv"

TITLE_ROW_KEY = "title"
TENOR_MATCH = "2 year"

#: The RBA has used more than one of these over the years.
_DATE_FORMATS = ("%d-%b-%Y", "%d/%m/%Y", "%Y-%m-%d", "%d %b %Y")


def _as_date(raw: str) -> date | None:
    raw = raw.strip()
    if not raw:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def parse(text: str) -> Series:
    rows = list(csv.reader(io.StringIO(text)))

    column = None
    for row in rows:
        if not row or row[0].strip().lower() != TITLE_ROW_KEY:
            continue
        for i, cell in enumerate(row):
            low = cell.lower()
            if TENOR_MATCH in low and "government" in low:
                column = i
                break
        if column is not None:
            break
    if column is None:
        return ()

    out: list[tuple[date, float]] = []
    for row in rows:
        if len(row) <= column:
            continue
        when = _as_date(row[0])
        if when is None:
            continue
        cell = row[column].strip()
        if not cell:
            continue
        try:
            out.append((when, float(cell)))
        except ValueError:
            continue
    out.sort()
    return tuple(out)


def fetch(get) -> ProviderResult:
    status, body = get(URL)
    if status != 200:
        return ProviderResult(Currency.AUD, URL, detail=f"HTTP {status}")
    # The RBA serves this as application/octet-stream with a BOM.
    series = parse(body.decode("utf-8-sig", errors="replace"))
    if not series:
        return ProviderResult(Currency.AUD, URL,
                              detail="fetched but no observations parsed")
    return ProviderResult(Currency.AUD, URL, series=series, ok=True,
                          detail=f"{len(series)} obs, latest {series[-1][0]}")
