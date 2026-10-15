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
from .base import ProviderResult, Series, merge

#: Fetched and merged, later winning on a shared date. The first is the
#: verified file; on 2026-10-15 it returned 3,292 observations but the
#: newest was 2026-10-07, a week behind the other publishers. Whether
#: that is an RBA publication lag or rows this parser is dropping is an
#: open question — `skipped_rows` below is what answers it, rather than
#: another round of guessing.
URLS = (
    "https://www.rba.gov.au/statistics/tables/csv/f2-data.csv",
    "https://www.rba.gov.au/statistics/tables/csv/f2.1-data.csv",
)

TITLE_ROW_KEY = "title"
TENOR_MATCH = "2 year"

#: The RBA has used more than one of these over the years.
_DATE_FORMATS = ("%d-%b-%Y", "%d/%m/%Y", "%Y-%m-%d", "%d %b %Y")

#: Rows whose first cell looked like it wanted to be a date but did not
#: parse. If the file is fresher than the series, the dropped rows are
#: in here and their format is the bug.
skipped_rows: tuple[str, ...] = ()

#: Metadata labels that legitimately sit in column 0 and are not dates.
_KNOWN_LABELS = {"title", "description", "frequency", "type", "units",
                 "source", "publication date", "series id", "collection",
                 "mnemonic", ""}


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

    global skipped_rows
    dropped: list[str] = []
    out: list[tuple[date, float]] = []

    for row in rows:
        if len(row) <= column or not row:
            continue
        first = row[0].strip()
        when = _as_date(first)
        if when is None:
            if first.lower() not in _KNOWN_LABELS and len(dropped) < 5:
                dropped.append(first[:40])
            continue
        cell = row[column].strip()
        if not cell:
            continue
        try:
            out.append((when, float(cell)))
        except ValueError:
            continue

    skipped_rows = tuple(dropped)
    out.sort()
    return tuple(out)


def fetch(get) -> ProviderResult:
    parts: list[Series] = []
    notes: list[str] = []

    for target in URLS:
        label = target.rsplit("/", 1)[-1]
        status, body = get(target)
        if status != 200:
            notes.append(f"{label}: HTTP {status}")
            continue
        # The RBA serves this as application/octet-stream with a BOM.
        series = parse(body.decode("utf-8-sig", errors="replace"))
        if not series:
            notes.append(f"{label}: 200 but no observations parsed")
            continue
        parts.append(series)
        note = f"{label}: {len(series)} obs to {series[-1][0]}"
        if skipped_rows:
            note += f" (unparsed first cells: {', '.join(skipped_rows)})"
        notes.append(note)

    merged = merge(*parts)
    if not merged:
        return ProviderResult(Currency.AUD, URLS[0],
                              detail="; ".join(notes) or "no attempt made")
    return ProviderResult(
        Currency.AUD, URLS[0], series=merged, ok=True,
        detail=f"{len(merged)} obs merged, latest {merged[-1][0]} "
               f"[{'; '.join(notes)}]")
