"""JPY — Japan Ministry of Finance, JGB interest rates, 2-year.

Two things about this feed are unlike any other source here.

ENCODING. It is Shift-JIS (cp932), not UTF-8. Decoded as UTF-8 it turns
to mojibake and the 2年 column header stops matching.

DATES. They are written in Japanese era years: `R8.10.1` is Reiwa 8,
October 1st — 2026-10-01. Reiwa year 1 is 1979+40 = 2019, so a Reiwa
year maps to 2018 + n. Heisei and Showa are handled too, because the
historical file reaches back that far.

Verified on 2026-10-15:
    基準日,1年,2年,3年,...
    R8.10.1,1.668,1.939,2.077,...
so the 2-year on that date was 1.939.

The monthly file holds only the current month. The historical file is
tried first for that reason — the 20-observation lookback needs about a
month of history, which the monthly file does not have on the 3rd.
"""

from __future__ import annotations

import csv
import io
from datetime import date

from ...core.types import Currency
from .base import ProviderResult, Series, merge

#: ALL of these are fetched and merged, later winning on a shared date.
#:
#: The monthly file is the only one verified to exist, and on 2026-10-15
#: it held nine rows — too few for the 20-observation lookback, so Japan
#: scored on level alone with no repricing measure. The historical files
#: below are candidates for the depth; `jgbcm_all.csv` at the top level
#: returned 404, so several plausible paths are tried and whichever
#: answer is reported in the result detail.
URLS = (
    "https://www.mof.go.jp/jgbs/reference/interest_rate/historical/"
    "jgbcm_all.csv",
    "https://www.mof.go.jp/jgbs/reference/interest_rate/data/jgbcm_all.csv",
    "https://www.mof.go.jp/english/jgbs/reference/interest_rate/jgbcm_all.csv",
    "https://www.mof.go.jp/jgbs/reference/interest_rate/jgbcm_all.csv",
    #: Verified. Fresh but shallow, so it goes last and wins on overlap.
    "https://www.mof.go.jp/jgbs/reference/interest_rate/jgbcm.csv",
)

#: Era letter -> the number added to the era year to get the Gregorian one.
_ERA_OFFSET = {"R": 2018, "H": 1988, "S": 1925}

TENOR_HEADER = "2年"


def japanese_date(raw: str) -> date | None:
    """`R8.10.1` -> date(2026, 10, 1). Returns None if unparseable."""
    raw = raw.strip()
    if len(raw) < 4:
        return None
    offset = _ERA_OFFSET.get(raw[0].upper())
    if offset is None:
        return None
    try:
        era_year, month, day = (int(p) for p in raw[1:].split("."))
    except ValueError:
        return None
    try:
        return date(offset + era_year, month, day)
    except ValueError:
        return None


def parse(raw: bytes) -> Series:
    text = raw.decode("cp932", errors="replace")
    rows = list(csv.reader(io.StringIO(text)))

    # Find the header row by looking for the tenor label itself. The
    # number of preamble rows differs between the monthly and historical
    # files, so counting rows would be fragile.
    column = None
    for row in rows:
        for i, cell in enumerate(row):
            if cell.strip() == TENOR_HEADER:
                column = i
                break
        if column is not None:
            break
    if column is None:
        return ()

    out: list[tuple[date, float]] = []
    for row in rows:
        if len(row) <= column or not row:
            continue
        when = japanese_date(row[0])
        if when is None:
            continue
        cell = row[column].strip()
        if not cell or cell == "-":          # MOF marks a non-quote with "-"
            continue
        try:
            out.append((when, float(cell)))
        except ValueError:
            continue
    out.sort()
    return tuple(out)


def fetch(get) -> ProviderResult:
    parts: list[Series] = []
    notes: list[str] = []

    for target in URLS:
        label = "/".join(target.split("/")[-2:])
        status, body = get(target)
        if status != 200:
            notes.append(f"{label}: HTTP {status}")
            continue
        series = parse(body)
        if not series:
            notes.append(f"{label}: 200 but unparsed")
            continue
        parts.append(series)
        notes.append(f"{label}: {len(series)} obs to {series[-1][0]}")

    merged = merge(*parts)
    if not merged:
        return ProviderResult(Currency.JPY, URLS[-1],
                              detail="; ".join(notes) or "no attempt made")
    return ProviderResult(
        Currency.JPY, URLS[-1], series=merged, ok=True,
        detail=f"{len(merged)} obs merged, latest {merged[-1][0]} "
               f"[{'; '.join(notes)}]")
