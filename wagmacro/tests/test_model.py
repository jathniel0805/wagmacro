"""Tests for the scoring model.

Plain unittest so this runs anywhere with no install step. The emphasis
is on the things that would be expensive to get wrong and invisible if
they were: band boundaries, the direction map's sign, the derived USD
path, and the rule that a missing input never looks like a neutral one.
"""

from __future__ import annotations

import sys
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from wagmacro.core.config import BANDS
from wagmacro.core.types import (Band, ComponentKind, ComponentScore,
                                 Confidence, Currency)
from wagmacro.ingest.calendar import EventReading
from wagmacro.ingest.cot import CotReading, derive_usd
from wagmacro.ingest.yields import from_manual
from wagmacro.model.aggregate import build_reading, pair_bias, build_board
from wagmacro.model.scorers import (score_calendar, score_positioning,
                                    score_rates)

TODAY = date(2026, 10, 15)


class TestComponentScoreGuards(unittest.TestCase):
    def test_rejects_out_of_range(self):
        for bad in (4, -4, 99):
            with self.assertRaises(ValueError):
                ComponentScore(kind=ComponentKind.RATES, value=bad, reason="x")

    def test_accepts_boundaries(self):
        for ok in (-3, 0, 3):
            ComponentScore(kind=ComponentKind.RATES, value=ok, reason="x")


class TestBanding(unittest.TestCase):
    def test_thresholds(self):
        cases = {
            9: Band.STRONG_BULL, 5: Band.STRONG_BULL,
            4: Band.BULL, 3: Band.BULL,
            2: Band.NEUTRAL, 0: Band.NEUTRAL, -2: Band.NEUTRAL,
            -3: Band.BEAR, -4: Band.BEAR,
            -5: Band.STRONG_BEAR, -9: Band.STRONG_BEAR,
        }
        for total, expected in cases.items():
            self.assertIs(BANDS.band_for(total), expected, f"total {total}")

    def test_only_strong_is_actionable(self):
        self.assertTrue(Band.STRONG_BULL.is_actionable)
        self.assertTrue(Band.STRONG_BEAR.is_actionable)
        self.assertFalse(Band.BULL.is_actionable)
        self.assertFalse(Band.NEUTRAL.is_actionable)


class TestPositioning(unittest.TestCase):
    def _reading(self, net: int, oi: int = 100_000) -> CotReading:
        longs = max(net, 0) + 10_000
        return CotReading(currency=Currency.EUR, report_date=TODAY,
                          open_interest=oi, leveraged_long=longs,
                          leveraged_short=longs - net)

    def test_crowded_long_scores_high(self):
        s = score_positioning(Currency.EUR, self._reading(40_000), TODAY)
        self.assertEqual(s.value, 3)

    def test_crowded_short_scores_low(self):
        s = score_positioning(Currency.EUR, self._reading(-40_000), TODAY)
        self.assertEqual(s.value, -3)

    def test_flat_scores_zero(self):
        s = score_positioning(Currency.EUR, self._reading(0), TODAY)
        self.assertEqual(s.value, 0)

    def test_missing_data_is_unavailable_not_neutral(self):
        """The failure that matters: a gap must not read as a neutral market."""
        s = score_positioning(Currency.EUR, None, TODAY)
        self.assertEqual(s.value, 0)
        self.assertIs(s.confidence, Confidence.UNAVAILABLE)

    def test_stale_report_is_flagged(self):
        old = CotReading(Currency.EUR, TODAY - timedelta(days=30),
                         100_000, 50_000, 50_000)
        self.assertIs(score_positioning(Currency.EUR, old, TODAY).confidence,
                      Confidence.STALE)

    def test_percentile_used_once_history_is_long_enough(self):
        history = [i / 1000.0 for i in range(-60, 60)]   # 120 weeks
        s = score_positioning(Currency.EUR, self._reading(5_000), TODAY,
                              history=history)
        self.assertIn("percentile", s.reason)

    def test_zero_open_interest_does_not_divide_by_zero(self):
        r = CotReading(Currency.EUR, TODAY, 0, 10, 5)
        self.assertEqual(score_positioning(Currency.EUR, r, TODAY).value, 0)


class TestDerivedUsd(unittest.TestCase):
    def test_usd_is_opposite_of_the_complex(self):
        readings = {
            c: CotReading(c, TODAY, 100_000, 60_000, 40_000)   # all net long
            for c in (Currency.EUR, Currency.GBP, Currency.JPY, Currency.AUD)
        }
        usd = derive_usd(readings)
        self.assertIsNotNone(usd)
        self.assertLess(usd, 0, "everyone long the majors means short USD")

    def test_too_few_contracts_returns_none(self):
        readings = {Currency.EUR: CotReading(Currency.EUR, TODAY,
                                             100_000, 60_000, 40_000)}
        self.assertIsNone(derive_usd(readings))


class TestRates(unittest.TestCase):
    def _set(self, levels, priors=None):
        return from_manual(TODAY, levels, priors)

    def test_highest_yield_scores_positive(self):
        ys = self._set({Currency.USD: 4.5, Currency.EUR: 2.0,
                        Currency.JPY: 0.5, Currency.GBP: 4.0,
                        Currency.AUD: 3.8})
        self.assertGreater(score_rates(Currency.USD, ys, TODAY).value, 0)

    def test_lowest_yield_scores_negative(self):
        ys = self._set({Currency.USD: 4.5, Currency.EUR: 2.0,
                        Currency.JPY: 0.5, Currency.GBP: 4.0,
                        Currency.AUD: 3.8})
        self.assertLess(score_rates(Currency.JPY, ys, TODAY).value, 0)

    def test_repricing_outweighs_level(self):
        """A widening differential should beat a static higher one.

        Both currencies sit above peers on level. Only one is repricing.
        """
        levels = {Currency.USD: 4.0, Currency.GBP: 4.0, Currency.EUR: 2.0,
                  Currency.JPY: 0.5, Currency.AUD: 2.0}
        priors = {Currency.USD: 3.5, Currency.GBP: 4.3, Currency.EUR: 2.0,
                  Currency.JPY: 0.5, Currency.AUD: 2.0}
        ys = self._set(levels, priors)
        self.assertGreater(score_rates(Currency.USD, ys, TODAY).value,
                           score_rates(Currency.GBP, ys, TODAY).value)

    def test_missing_currency_is_unavailable(self):
        ys = self._set({Currency.USD: 4.0, Currency.EUR: 2.0,
                        Currency.JPY: 0.5, Currency.GBP: 4.0})
        s = score_rates(Currency.NZD, ys, TODAY)
        self.assertIs(s.confidence, Confidence.UNAVAILABLE)

    def test_too_few_peers_is_partial(self):
        ys = self._set({Currency.USD: 4.0, Currency.EUR: 2.0})
        self.assertIs(score_rates(Currency.USD, ys, TODAY).confidence,
                      Confidence.PARTIAL)


class TestCalendarDirection(unittest.TestCase):
    def _event(self, title, forecast, previous, impact=3):
        return EventReading(currency=Currency.USD, title=title,
                            when=datetime(2026, 10, 15, 12, 0),
                            impact=impact, forecast=forecast,
                            previous=previous)

    def test_hotter_cpi_is_bullish(self):
        self.assertGreater(self._event("CPI y/y", 3.6, 3.4).surprise, 0)

    def test_rising_unemployment_is_bearish(self):
        """The inversion that a naive table gets wrong."""
        self.assertLess(self._event("Unemployment Rate", 4.5, 4.1).surprise, 0)

    def test_rising_claims_is_bearish(self):
        self.assertLess(self._event("Unemployment Claims", 260, 230).surprise, 0)

    def test_specific_beats_general_in_the_table(self):
        """'unemployment rate' must not be caught by a later 'employment'."""
        self.assertFalse(self._event("Unemployment Rate", 4.5, 4.1).higher_is_bullish)
        self.assertTrue(self._event("Employment Change", 50, 20).higher_is_bullish)

    def test_unknown_indicator_is_skipped_not_guessed(self):
        e = self._event("Mystery Index", 10, 5)
        self.assertIsNone(e.higher_is_bullish)
        self.assertIsNone(e.surprise)

    def test_actual_preferred_over_forecast_when_present(self):
        e = EventReading(currency=Currency.USD, title="CPI y/y",
                         when=datetime(2026, 10, 15), impact=3,
                         forecast=3.6, previous=3.4, actual=4.0)
        # actual(4.0) vs forecast(3.6) is a beat, even though forecast
        # vs previous would also be positive — check it used the actual
        self.assertAlmostEqual(e.surprise, (4.0 - 3.6) / 3.6, places=6)

    def test_surprise_is_clamped(self):
        huge = self._event("CPI y/y", 100.0, 0.1)
        self.assertLessEqual(abs(huge.surprise), 1.0)

    def test_high_impact_outweighs_medium(self):
        high = self._event("CPI y/y", 3.6, 3.4, impact=3)
        med = self._event("CPI y/y", 3.6, 3.4, impact=2)
        self.assertGreater(high.weight, med.weight)


class TestCalendarScorer(unittest.TestCase):
    def _e(self, cur, title, f, p, impact=3):
        return EventReading(currency=cur, title=title,
                            when=datetime(2026, 10, 15), impact=impact,
                            forecast=f, previous=p)

    def test_no_events_is_ok_not_a_failure(self):
        s = score_calendar(Currency.USD, [], TODAY)
        self.assertEqual(s.value, 0)
        self.assertIs(s.confidence, Confidence.OK)

    def test_unscoreable_events_are_partial(self):
        s = score_calendar(Currency.USD,
                           [self._e(Currency.USD, "Mystery Index", 1, 2)],
                           TODAY)
        self.assertIs(s.confidence, Confidence.PARTIAL)

    def test_expectations_basis_is_named(self):
        s = score_calendar(Currency.USD,
                           [self._e(Currency.USD, "CPI y/y", 3.6, 3.4)],
                           TODAY, feed_has_actuals=False)
        self.assertIn("expectations", s.reason)

    def test_only_this_currency_counts(self):
        events = [self._e(Currency.EUR, "CPI y/y", 9.0, 1.0)]
        self.assertEqual(score_calendar(Currency.USD, events, TODAY).value, 0)


class TestAggregate(unittest.TestCase):
    def _c(self, kind, value):
        return ComponentScore(kind=kind, value=value, reason="test")

    def test_total_and_band(self):
        r = build_reading(Currency.USD, [
            self._c(ComponentKind.RATES, 3),
            self._c(ComponentKind.POSITIONING, 2),
            self._c(ComponentKind.CALENDAR, 1),
        ])
        self.assertEqual(r.total, 6)
        self.assertIs(r.band, Band.STRONG_BULL)

    def test_note_never_moves_the_total(self):
        """The judgement layer must stay out of the number."""
        a = build_reading(Currency.USD, [self._c(ComponentKind.RATES, 1)])
        b = build_reading(Currency.USD, [self._c(ComponentKind.RATES, 1)],
                          note="Very hawkish Fed, huge upside risk")
        self.assertEqual(a.total, b.total)

    def test_weakest_link_surfaces_worst_confidence(self):
        r = build_reading(Currency.USD, [
            ComponentScore(ComponentKind.RATES, 1, "x", Confidence.OK),
            ComponentScore(ComponentKind.CALENDAR, 0, "x", Confidence.UNAVAILABLE),
        ])
        self.assertIs(r.weakest_link, Confidence.UNAVAILABLE)

    def test_pair_bias_is_the_difference(self):
        board = build_board(TODAY, [
            build_reading(Currency.GBP, [self._c(ComponentKind.RATES, 3)]),
            build_reading(Currency.JPY, [self._c(ComponentKind.RATES, -3)]),
        ], {})
        self.assertEqual(pair_bias(board, Currency.GBP, Currency.JPY), 6)
        self.assertEqual(pair_bias(board, Currency.JPY, Currency.GBP), -6)

    def test_pair_bias_none_when_missing(self):
        board = build_board(TODAY, [
            build_reading(Currency.GBP, [self._c(ComponentKind.RATES, 3)])], {})
        self.assertIsNone(pair_bias(board, Currency.GBP, Currency.JPY))

    def test_ranked_is_strongest_first(self):
        board = build_board(TODAY, [
            build_reading(Currency.JPY, [self._c(ComponentKind.RATES, -2)]),
            build_reading(Currency.USD, [self._c(ComponentKind.RATES, 3)]),
            build_reading(Currency.EUR, [self._c(ComponentKind.RATES, 0)]),
        ], {})
        self.assertEqual([r.currency for r in board.ranked()],
                         [Currency.USD, Currency.EUR, Currency.JPY])


class TestCurrencySet(unittest.TestCase):
    def test_seven_tracked(self):
        self.assertEqual(len(Currency.all()), 7)

    def test_usd_excluded_from_futures_set(self):
        self.assertNotIn(Currency.USD, Currency.non_usd())
        self.assertEqual(len(Currency.non_usd()), 6)


if __name__ == "__main__":
    unittest.main(verbosity=2)
