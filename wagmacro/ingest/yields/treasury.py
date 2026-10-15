"""USD — US Treasury daily par yield curve, 2-year.

The XML feed is the confirmed-reachable route (verified 2026-10-15:
`DailyTreasuryYieldCurveRateData`, updated that morning). It is an OData
Atom feed, so every field sits in a namespaced element and the parser
matches on the LOCAL name rather than assuming a namespace URI that
Treasury could change.

What the probe did NOT show is an entry body — only the feed header —
so the exact field name for the 2-year is the one unverified assumption
left in this package. It is handled rather than hoped: if the expected
field is missing, `parse_xml` reports the field names it actually found,
and `--diagnose` surfaces that in one run instead of silently scoring
zero forever.
"""

from __future__ import annotations

import csv
import io
import re
from datetime import date, datetime
from xml.etree import ElementTree

from ...core.types import Currency
from .base import ProviderResult, Series

_XML = ("https://home.treasury.gov/resource-center/data-chart-center/"
        "interest-rates/pages/xml?data=daily_treasury_yield_curve"
        "&field_tdr_date_value={year}")

_CSV = ("https://home.treasury.gov/resource-center/data-chart-center/"
        "interest-rates/daily-treasury-rates.csv/{year}/all"
        "?type=daily_treasury_yield_curve&field_tdr_date_value={year}"
        "&page&_format=csv")

DATE_FIELD = "NEW_DATE"
TENOR_FIELD = "BC_2YEAR"

#: What the CSV calls the same column.
CSV_DATE = "Date"
CSV_TENOR = "2 Yr"

#: Set by parse_xml when the tenor field is absent, so the failure says
#: what the feed DOES contain rather than just "nothing parsed".
last_seen_fields: tuple[str, ...] = ()


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_xml(text: str) -> Series:
    global last_seen_fields
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError:
        return ()

    seen: set[str] = set()
    out: list[tuple[date, float]] = []

    for props in root.iter():
        if _local(props.tag) != "properties":
            continue
        when: date | None = None
        value: float | None = None
        for field in props:
            name = _local(field.tag)
            seen.add(name)
            raw = (field.text or "").strip()
            if not raw:
                continue
            if name == DATE_FIELD:
                try:
                    when = datetime.fromisoformat(raw.replace("Z", "")).date()
                except ValueError:
                    when = None
            elif name == TENOR_FIELD:
                try:
                    value = float(raw)
                except ValueError:
                    value = None
        if when is not None and value is not None:
            out.append((when, value))

    last_seen_fields = tuple(sorted(seen))
    out.sort()
    return tuple(out)


def parse_csv(text: str) -> Series:
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        return ()

    def find(target: str) -> str | None:
        flat = re.sub(r"\s+", "", target).lower()
        for name in reader.fieldnames or ():
            if re.sub(r"\s+", "", name).lower() == flat:
                return name
        return None

    date_col, tenor_col = find(CSV_DATE), find(CSV_TENOR)
    if not date_col or not tenor_col:
        return ()

    out: list[tuple[date, float]] = []
    for row in reader:
        raw_date = (row.get(date_col) or "").strip()
        raw_value = (row.get(tenor_col) or "").strip()
        if not raw_date or not raw_value:
            continue
        when = None
        for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y"):
            try:
                when = datetime.strptime(raw_date, fmt).date()
                break
            except ValueError:
                continue
        if when is None:
            continue
        try:
            out.append((when, float(raw_value)))
        except ValueError:
            continue
    out.sort()
    return tuple(out)


def fetch(get) -> ProviderResult:
    year = date.today().year
    attempts: list[str] = []

    target = _XML.format(year=year)
    status, body = get(target)
    if status == 200:
        series = parse_xml(body.decode("utf-8", errors="replace"))
        if series:
            return ProviderResult(
                Currency.USD, target, series=series, ok=True,
                detail=f"{len(series)} obs from XML, latest {series[-1][0]}")
        attempts.append(
            f"XML 200 but no '{TENOR_FIELD}' field; fields present: "
            + (", ".join(last_seen_fields[:18]) or "none"))
    else:
        attempts.append(f"XML: HTTP {status}")

    target = _CSV.format(year=year)
    status, body = get(target)
    if status == 200:
        series = parse_csv(body.decode("utf-8-sig", errors="replace"))
        if series:
            return ProviderResult(
                Currency.USD, target, series=series, ok=True,
                detail=f"{len(series)} obs from CSV, latest {series[-1][0]}")
        attempts.append("CSV 200 but no '2 Yr' column")
    else:
        attempts.append(f"CSV: HTTP {status}")

    return ProviderResult(Currency.USD, _XML.format(year=year),
                          detail="; ".join(attempts))
