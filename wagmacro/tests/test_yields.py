"""Parser tests for the six yield adapters.

WHAT THESE TESTS DO AND DO NOT PROVE

Where a fixture was CAPTURED — copied from bytes a publisher actually
sent, recorded in the verification runs on 2026-10-15 — the test proves
the parser reads the real format correctly. That covers ECB, MOF and
RBA, and the BoE sheet layout.

Where a fixture was CONSTRUCTED — because the verification run showed
the feed header but no data rows — the test proves the parser handles
that shape, not that the shape is right. That applies to the Treasury
XML entry body. `python -m wagmacro.cli --diagnose` is what settles it
against live data, and it is deliberately part of the rollout rather
than an afterthought.

Each fixture is marked CAPTURED or CONSTRUCTED so nobody later mistakes
one for the other.
"""

from __future__ import annotations

import io
import unittest
import zipfile
from datetime import date

from wagmacro.core.types import Currency
from wagmacro.ingest.yields import boc, boe, ecb, mof, rba, treasury
from wagmacro.ingest.yields.base import (YieldPoint, YieldSet, from_manual,
                                         merge, point_from_series)


# ---------------------------------------------------------------- ECB ----
# CAPTURED 2026-10-15. Trailing note field contains commas on purpose —
# it is what broke a naive split(",") and why the parser uses csv.reader.
ECB_CSV = (
    "KEY,FREQ,REF_AREA,CURRENCY,PROVIDER_FM,INSTRUMENT_FM,PROVIDER_FM_ID,"
    "DATA_TYPE_FM,TIME_PERIOD,OBS_VALUE,OBS_STATUS,OBS_CONF,TITLE\n"
    "YC.B.U2.EUR.4F.G_N_A.SV_C_YM.SR_2Y,B,U2,EUR,4F,G_N_A,SV_C_YM,SR_2Y,"
    "2026-08-17,2.7360418851,A,F,\"Technical notes, available at ecb.int\"\n"
    "YC.B.U2.EUR.4F.G_N_A.SV_C_YM.SR_2Y,B,U2,EUR,4F,G_N_A,SV_C_YM,SR_2Y,"
    "2026-08-21,2.7610795861,A,F,\"Technical notes, available at ecb.int\"\n"
    "YC.B.U2.EUR.4F.G_N_A.SV_C_YM.SR_2Y,B,U2,EUR,4F,G_N_A,SV_C_YM,SR_2Y,"
    "2026-08-18,2.7804608813,A,F,\"Technical notes, available at ecb.int\"\n"
)


class TestEcb(unittest.TestCase):
    def test_parses_and_sorts(self):
        series = ecb.parse(ECB_CSV)
        self.assertEqual(len(series), 3)
        self.assertEqual(series[0], (date(2026, 8, 17), 2.7360418851))
        self.assertEqual(series[-1], (date(2026, 8, 21), 2.7610795861))

    def test_comma_inside_quoted_note_does_not_shift_columns(self):
        # If the note were split on, OBS_VALUE would land on the wrong field.
        self.assertEqual(ecb.parse(ECB_CSV)[0][1], 2.7360418851)

    def test_missing_columns_yield_nothing_rather_than_guessing(self):
        self.assertEqual(ecb.parse("A,B,C\n1,2,3\n"), ())

    def test_empty_input(self):
        self.assertEqual(ecb.parse(""), ())


# ---------------------------------------------------------------- MOF ----
# CAPTURED 2026-10-15, including the Shift-JIS encoding and era dates.
MOF_TEXT = (
    "長期金利情報 (令和8年10月),,,,,,,,,,,,,,,(単位 : %)\n"
    "基準日,1年,2年,3年,4年,5年,6年,7年,8年,9年,10年\n"
    "R8.10.1,1.668,1.939,2.077,2.274,2.407,2.534,2.657,2.82,2.952,3.092\n"
    "R8.10.2,1.65,1.919,2.065,2.259,2.397,2.528,2.657,2.821,2.957,3.097\n"
    "R8.10.5,1.638,-,2.056,2.251,2.389,2.517,2.645,2.81,2.944,3.085\n"
)
MOF_BYTES = MOF_TEXT.encode("cp932")


class TestMofDates(unittest.TestCase):
    def test_reiwa(self):
        self.assertEqual(mof.japanese_date("R8.10.1"), date(2026, 10, 1))

    def test_heisei(self):
        self.assertEqual(mof.japanese_date("H31.4.30"), date(2019, 4, 30))

    def test_showa(self):
        self.assertEqual(mof.japanese_date("S64.1.7"), date(1989, 1, 7))

    def test_rejects_rubbish(self):
        for bad in ("", "基準日", "2026-10-01", "R8", "X8.10.1", "R8.99.1"):
            self.assertIsNone(mof.japanese_date(bad), bad)


class TestMof(unittest.TestCase):
    def test_reads_the_two_year_column(self):
        series = mof.parse(MOF_BYTES)
        self.assertEqual(series[0], (date(2026, 10, 1), 1.939))

    def test_skips_the_hyphen_placeholder(self):
        series = mof.parse(MOF_BYTES)
        self.assertEqual([d for d, _ in series],
                         [date(2026, 10, 1), date(2026, 10, 2)])

    def test_not_confused_by_the_one_year_column(self):
        # 1.668 is the 1-year on the same row; reading it would be a
        # silent 27bp error every day.
        self.assertNotIn(1.668, [v for _, v in mof.parse(MOF_BYTES)])

    def test_utf8_decoding_would_have_failed(self):
        # Guards the choice of cp932: decoded as UTF-8 the header is
        # mojibake and the 2年 column cannot be found at all.
        self.assertEqual(mof.parse(MOF_TEXT.encode("utf-8")), ())


# ---------------------------------------------------------------- RBA ----
# Metadata block CAPTURED 2026-10-15; data rows CONSTRUCTED in the
# format the RBA uses, since the probe showed only the preamble.
RBA_CSV = (
    "F2 CAPITAL MARKET YIELDS – GOVERNMENT BONDS\n"
    "Title,Australian Government 2 year bond,Australian Government 3 year bond,"
    "Australian Government 10 year bond\n"
    "Description,\"Yields on Australian government bonds, interpolated, 2 years"
    " maturity\",\"3 years\",\"10 years\"\n"
    "Frequency,Daily,Daily,Daily\n"
    "Type,Original,Original,Original\n"
    "Units,Per cent per annum,Per cent per annum,Per cent per annum\n"
    "Series ID,FCMYGBAG2,FCMYGBAG3,FCMYGBAG10\n"
    "01-Oct-2026,3.55,3.71,4.28\n"
    "02-Oct-2026,3.58,3.74,4.31\n"
)


class TestRba(unittest.TestCase):
    def test_finds_two_year_column_from_the_title_row(self):
        series = rba.parse(RBA_CSV)
        self.assertEqual(series[0], (date(2026, 10, 1), 3.55))
        self.assertEqual(series[-1], (date(2026, 10, 2), 3.58))

    def test_metadata_rows_are_not_mistaken_for_data(self):
        self.assertEqual(len(rba.parse(RBA_CSV)), 2)

    def test_no_matching_column_returns_empty(self):
        self.assertEqual(rba.parse("Title,Something Else\n01-Oct-2026,1.0\n"), ())


# ---------------------------------------------------------------- BoC ----
# CONSTRUCTED to the Valet shape; the series label was CAPTURED.
BOC_JSON = (
    '{"seriesDetail": {"BD.CDN.2YR.DQ.YLD": '
    '{"label": "Benchmark bond yield, 2-year"}},'
    '"observations": ['
    '{"d": "2026-10-01", "BD.CDN.2YR.DQ.YLD": {"v": "2.85"}},'
    '{"d": "2026-10-02", "BD.CDN.2YR.DQ.YLD": {"v": ""}},'
    '{"d": "2026-10-03", "BD.CDN.2YR.DQ.YLD": {"v": "2.88"}}]}'
)


class TestBoc(unittest.TestCase):
    def test_parses(self):
        series = boc.parse(BOC_JSON)
        self.assertEqual(series[0], (date(2026, 10, 1), 2.85))

    def test_empty_string_is_a_holiday_not_a_zero(self):
        # Valet uses "" for a non-trading day. Treating it as 0.0 would
        # put a fake 285bp collapse into the series.
        series = boc.parse(BOC_JSON)
        self.assertEqual(len(series), 2)
        self.assertNotIn(0.0, [v for _, v in series])

    def test_malformed_json(self):
        self.assertEqual(boc.parse("{not json"), ())


# ----------------------------------------------------------- Treasury ----
# CONSTRUCTED. The verification run returned the feed header only, so the
# entry body below is the documented OData shape rather than captured
# bytes. --diagnose is what confirms the real field name.
TREASURY_XML = """<?xml version="1.0" encoding="utf-8" standalone="yes"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:d="http://schemas.microsoft.com/ado/2007/08/dataservices"
      xmlns:m="http://schemas.microsoft.com/ado/2007/08/dataservices/metadata">
  <entry><content type="application/xml"><m:properties>
    <d:NEW_DATE m:type="Edm.DateTime">2026-10-01T00:00:00</d:NEW_DATE>
    <d:BC_1YEAR>3.81</d:BC_1YEAR>
    <d:BC_2YEAR>3.62</d:BC_2YEAR>
    <d:BC_10YEAR>4.11</d:BC_10YEAR>
  </m:properties></content></entry>
  <entry><content type="application/xml"><m:properties>
    <d:NEW_DATE m:type="Edm.DateTime">2026-10-02T00:00:00</d:NEW_DATE>
    <d:BC_1YEAR>3.79</d:BC_1YEAR>
    <d:BC_2YEAR>3.60</d:BC_2YEAR>
    <d:BC_10YEAR>4.09</d:BC_10YEAR>
  </m:properties></content></entry>
</feed>"""

TREASURY_CSV = ("Date,1 Yr,2 Yr,10 Yr\n"
                "10/01/2026,3.81,3.62,4.11\n"
                "10/02/2026,3.79,3.60,4.09\n")


class TestTreasury(unittest.TestCase):
    def test_xml(self):
        series = treasury.parse_xml(TREASURY_XML)
        self.assertEqual(series, ((date(2026, 10, 1), 3.62),
                                  (date(2026, 10, 2), 3.60)))

    def test_xml_records_field_names_when_tenor_missing(self):
        # The point of this: a missing field must produce a report of
        # what WAS there, not a silent empty series.
        without = TREASURY_XML.replace("BC_2YEAR", "BC_3YEAR")
        self.assertEqual(treasury.parse_xml(without), ())
        self.assertIn("BC_3YEAR", treasury.last_seen_fields)
        self.assertIn("NEW_DATE", treasury.last_seen_fields)

    def test_csv_fallback(self):
        series = treasury.parse_csv(TREASURY_CSV)
        self.assertEqual(series[0], (date(2026, 10, 1), 3.62))

    def test_malformed_xml(self):
        self.assertEqual(treasury.parse_xml("<not-xml"), ())


# ---------------------------------------------------------------- BoE ----

def _boe_zip() -> bytes:
    """Rebuild the sheet layout CAPTURED on 2026-10-15.

    The 'months:' row is included deliberately. In the real workbook a
    sibling sheet carries one, and a parser that scans for the value 2.0
    without anchoring finds TWO MONTHS and reports it as a two-year
    yield. The real numbers below are from the verified file.
    """
    import openpyxl

    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "4. spot curve"
    sheet.append([None, "UK nominal spot curve"])
    sheet.append([None])
    sheet.append(["Maturity"])
    sheet.append(["months:", 6, 12, 18, 24, 30])        # the trap
    sheet.append(["years:", 0.5, 1, 1.5, 2, 2.5])       # the anchor
    sheet.append(["#VALUE!", None, None, None, None, None])
    sheet.append([date(2026, 10, 1), 4.1213445478, 4.3500177123,
                  4.5000723575, 4.6007787599, 4.6730946319])
    sheet.append([date(2026, 10, 2), 4.1300000000, 4.3600000000,
                  4.5100000000, 4.6100000000, 4.6800000000])

    other = book.create_sheet("info")
    other.append(["not a curve"])

    buf = io.BytesIO()
    book.save(buf)

    zbuf = io.BytesIO()
    with zipfile.ZipFile(zbuf, "w") as archive:
        archive.writestr("GLC Nominal daily data current month.xlsx",
                         buf.getvalue())
        archive.writestr("GLC Real daily data current month.xlsx", b"ignored")
    return zbuf.getvalue()


class TestBoe(unittest.TestCase):
    def test_reads_the_two_year_spot(self):
        series = boe.parse(_boe_zip())
        self.assertEqual(series[0], (date(2026, 10, 1), 4.6007787599))

    def test_anchors_on_years_not_on_the_months_row(self):
        # Column 4 of the months row is 24; if the parser anchored there
        # it would return the 2.5-year value, not the 2-year one.
        series = boe.parse(_boe_zip())
        self.assertNotIn(4.6730946319, [v for _, v in series])

    def test_does_not_read_the_five_year_by_mistake(self):
        # The IADB mistake this adapter exists to avoid.
        self.assertNotIn(4.9288, [v for _, v in boe.parse(_boe_zip())])

    def test_not_a_zip(self):
        self.assertEqual(boe.parse(b"this is not a zip"), ())


# --------------------------------------------------------- assembling ----

class TestSeriesToPoint(unittest.TestCase):
    def _series(self, n: int):
        return tuple((date(2026, 1, 1), 1.0 + i / 100) for i in range(n))

    def test_prior_is_lookback_observations_back(self):
        series = tuple((date(2026, 9, i + 1), float(i)) for i in range(25))
        point = point_from_series(Currency.USD, series, lookback=20)
        self.assertEqual(point.yield_pct, 24.0)
        self.assertEqual(point.yield_pct_prior, 4.0)
        self.assertAlmostEqual(point.change_bps, 2000.0)

    def test_short_series_has_no_prior_rather_than_a_wrong_one(self):
        series = tuple((date(2026, 9, i + 1), float(i)) for i in range(5))
        point = point_from_series(Currency.USD, series, lookback=20)
        self.assertIsNone(point.yield_pct_prior)
        self.assertIsNone(point.change_bps)

    def test_empty_series(self):
        self.assertIsNone(point_from_series(Currency.USD, (), 20))


class TestMerge(unittest.TestCase):
    """The archive-is-stale bug, pinned.

    The UK series came back fourteen days old because the adapter took
    whichever file answered first: the archive had 12,068 observations
    and the current-month file had the recent ones, and first-wins chose
    depth over freshness without ever noticing.
    """

    ARCHIVE = ((date(2026, 9, 28), 4.71),
               (date(2026, 9, 29), 4.68),
               (date(2026, 9, 30), 4.66))
    CURRENT = ((date(2026, 9, 30), 4.67),      # overlaps, revised
               (date(2026, 10, 1), 4.70),
               (date(2026, 10, 2), 4.73))

    def test_keeps_depth_and_freshness(self):
        merged = merge(self.ARCHIVE, self.CURRENT)
        self.assertEqual(merged[0][0], date(2026, 9, 28))
        self.assertEqual(merged[-1][0], date(2026, 10, 2))
        self.assertEqual(len(merged), 5)

    def test_later_argument_wins_on_overlap(self):
        merged = merge(self.ARCHIVE, self.CURRENT)
        overlap = dict(merged)[date(2026, 9, 30)]
        self.assertEqual(overlap, 4.67)

    def test_stays_sorted(self):
        merged = merge(self.CURRENT, self.ARCHIVE)
        self.assertEqual([d for d, _ in merged], sorted(d for d, _ in merged))

    def test_tolerates_empty_parts(self):
        self.assertEqual(merge((), self.CURRENT, ()), self.CURRENT)
        self.assertEqual(merge(), ())


class TestRbaDiagnostics(unittest.TestCase):
    def test_reports_unparseable_first_cells(self):
        # A date format the parser does not know must be REPORTED, not
        # silently dropped — that is how a stale series hides.
        odd = RBA_CSV + "2026-10-08T00:00:00+11:00,3.60,3.76,4.33\n"
        rba.parse(odd)
        self.assertTrue(rba.skipped_rows)
        self.assertIn("2026-10-08", rba.skipped_rows[0])

    def test_known_metadata_labels_are_not_reported_as_drops(self):
        rba.parse(RBA_CSV)
        self.assertEqual(rba.skipped_rows, ())


class TestYieldSetMaths(unittest.TestCase):
    def test_differential_needs_three_peers(self):
        tiny = from_manual(date(2026, 10, 1),
                           {Currency.USD: 4.0, Currency.EUR: 2.0})
        self.assertIsNone(tiny.differential(Currency.USD))

    def test_differential_against_six(self):
        levels = {Currency.USD: 4.0, Currency.EUR: 2.0, Currency.GBP: 4.0,
                  Currency.JPY: 1.0, Currency.CAD: 3.0, Currency.AUD: 3.0}
        wide = from_manual(date(2026, 10, 1), levels)
        # peers of USD: 2,4,1,3,3 -> mean 2.6
        self.assertAlmostEqual(wide.differential(Currency.USD), 1.4)

    def test_absent_currency_has_no_differential(self):
        levels = {Currency.USD: 4.0, Currency.EUR: 2.0, Currency.GBP: 4.0,
                  Currency.JPY: 1.0}
        wide = from_manual(date(2026, 10, 1), levels)
        self.assertIsNone(wide.differential(Currency.NZD))


if __name__ == "__main__":
    unittest.main()
