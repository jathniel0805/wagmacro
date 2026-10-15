"""CFTC Commitments of Traders — Financial Futures, weekly.

Source: https://www.cftc.gov/dea/newcot/FinFutWk.txt

The file is a headerless CSV, one row per contract, published Friday
afternoon for the previous Tuesday's positions. Columns are positional
and defined by the CFTC's Traders in Financial Futures layout:

    0  market and exchange name, quoted
    1  report date, YYMMDD
    2  report date, ISO
    3  CFTC contract market code      <- what we match on
    ...
    7  open interest (all)
    8  dealer long          9  dealer short        10 dealer spread
    11 asset manager long   12 asset manager short 13 asset manager spread
    14 leveraged long       15 leveraged short     16 leveraged spread

We read the LEVERAGED FUNDS cohort. Dealers are mostly hedging bank
flow and asset managers turn over slowly; leveraged funds are the
speculative money whose crowding actually unwinds.

Matching is by contract code, never by name. Exchange names in this
file change wording between releases ("CHICAGO MERCANTILE EXCHANGE"
versus abbreviations); the numeric codes do not.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import date

from ..core.config import COT_CONTRACT_CODES
from ..core.types import Currency, RawPayload

#: Positional column indices, per the CFTC TFF layout.
COL_CONTRACT_CODE = 3
COL_OPEN_INTEREST = 7
COL_LEVERAGED_LONG = 14
COL_LEVERAGED_SHORT = 15
COL_REPORT_DATE_ISO = 2

MIN_COLUMNS = 17


@dataclass(frozen=True, slots=True)
class CotReading:
    currency: Currency
    report_date: date
    open_interest: int
    leveraged_long: int
    leveraged_short: int

    @property
    def net(self) -> int:
        return self.leveraged_long - self.leveraged_short

    @property
    def net_share_of_oi(self) -> float:
        """Net speculative position as a share of total open interest.

        Normalising by open interest makes contracts comparable: a
        40,000 net long means something very different in EUR futures
        than in NZD futures.
        """
        if self.open_interest <= 0:
            return 0.0
        return self.net / self.open_interest


class CotParseError(ValueError):
    """Raised only for a payload that is structurally not a COT file."""


def _to_int(raw: str) -> int:
    cleaned = raw.strip().replace(",", "")
    if not cleaned or cleaned in {".", "-"}:
        return 0
    return int(float(cleaned))


def parse(payload: RawPayload) -> dict[Currency, CotReading]:
    """Extract one reading per tracked currency.

    Returns only what was found. A missing contract is a gap for the
    scorer to report, not a reason to fail the whole run.
    """
    if not payload.ok:
        return {}

    wanted = {code: cur for cur, code in COT_CONTRACT_CODES.items()}
    found: dict[Currency, CotReading] = {}
    rows_seen = 0

    for row in csv.reader(io.StringIO(payload.body)):
        if len(row) < MIN_COLUMNS:
            continue
        rows_seen += 1

        code = row[COL_CONTRACT_CODE].strip()
        currency = wanted.get(code)
        if currency is None:
            continue

        try:
            report_date = date.fromisoformat(row[COL_REPORT_DATE_ISO].strip())
        except ValueError:
            continue

        try:
            reading = CotReading(
                currency=currency,
                report_date=report_date,
                open_interest=_to_int(row[COL_OPEN_INTEREST]),
                leveraged_long=_to_int(row[COL_LEVERAGED_LONG]),
                leveraged_short=_to_int(row[COL_LEVERAGED_SHORT]),
            )
        except ValueError:
            continue

        # Keep the most recent row if a file ever carries several weeks.
        existing = found.get(currency)
        if existing is None or reading.report_date > existing.report_date:
            found[currency] = reading

    if rows_seen == 0:
        raise CotParseError(
            "no rows with the expected column count; this does not look "
            "like a CFTC Financial Futures file"
        )
    return found


def derive_usd(readings: dict[Currency, CotReading]) -> float | None:
    """USD positioning, inferred from the other six.

    There is no USD contract in this file. Every currency future is
    quoted against the dollar, so being net long EUR futures IS being
    net short dollars. Aggregating the opposite side of all six gives a
    dollar proxy.

    This is the standard construction and it is defensible, but it is a
    CONSTRUCTION, not a reading. The dashboard marks the USD cell as
    derived so that difference stays visible.

    Returns a net-share-of-open-interest figure comparable with the
    other currencies, or None when there is too little to build on.
    """
    usable = [r for r in readings.values() if r.open_interest > 0]
    if len(usable) < 3:
        return None

    total_oi = sum(r.open_interest for r in usable)
    if total_oi <= 0:
        return None

    # Open-interest weighted: EUR and JPY futures dominate the complex,
    # and an unweighted mean would let NZD move the dollar as much as EUR.
    weighted_net = sum(r.net for r in usable)
    return -(weighted_net / total_oi)
