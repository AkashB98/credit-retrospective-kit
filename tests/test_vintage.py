"""Vintage analysis: curves, fixed-MOB ranking, hand-computed cases."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from generator import generate_loans
from helpers import loan
from vintage import (all_vintages, cumulative_default_rate, default_curve,
                     rank_vintages, vintage_summary)


def _vintage_book():
    # Vintage A: 4 loans, defaults at MOB 2 and 5. Vintage B: 4 loans,
    # one default at MOB 1 (early and bad), rest clean.
    a = [loan(vintage="2024-Q1", defaulted=True, default_mob=2),
         loan(vintage="2024-Q1", defaulted=True, default_mob=5),
         loan(vintage="2024-Q1"), loan(vintage="2024-Q1")]
    b = [loan(vintage="2024-Q2", defaulted=True, default_mob=1),
         loan(vintage="2024-Q2"), loan(vintage="2024-Q2"), loan(vintage="2024-Q2")]
    return a + b


class TestCurvesHandComputed(unittest.TestCase):
    def setUp(self):
        self.loans = _vintage_book()

    def test_rate_at_mob(self):
        a = [ln for ln in self.loans if ln["vintage"] == "2024-Q1"]
        self.assertEqual(cumulative_default_rate(a, 1), 0.0)
        self.assertEqual(cumulative_default_rate(a, 2), 0.25)
        self.assertEqual(cumulative_default_rate(a, 4), 0.25)
        self.assertEqual(cumulative_default_rate(a, 5), 0.5)

    def test_rate_empty_is_zero(self):
        self.assertEqual(cumulative_default_rate([], 6), 0.0)

    def test_curve_shape_and_monotonic(self):
        a = [ln for ln in self.loans if ln["vintage"] == "2024-Q1"]
        curve = default_curve(a, max_mob=6)
        self.assertEqual(curve, [0.0, 0.25, 0.25, 0.25, 0.5, 0.5])
        self.assertEqual(curve, sorted(curve))

    def test_curve_length(self):
        self.assertEqual(len(default_curve(self.loans)), 12)

    def test_non_defaulted_never_counts(self):
        loans = [loan(default_mob=None), loan(defaulted=False)]
        self.assertEqual(cumulative_default_rate(loans, 12), 0.0)


class TestRanking(unittest.TestCase):
    def test_ranking_uses_fixed_mob(self):
        # At MOB 1 vintage B is worst (0.25 vs 0.0); at MOB 6 A is worst.
        loans = _vintage_book()
        at1 = rank_vintages(loans, mob=1)
        at6 = rank_vintages(loans, mob=6)
        self.assertEqual(at1[0]["vintage"], "2024-Q2")
        self.assertEqual(at6[0]["vintage"], "2024-Q1")

    def test_ranks_are_1_to_n(self):
        rows = rank_vintages(_vintage_book(), mob=6)
        self.assertEqual([r["rank"] for r in rows], [1, 2])

    def test_summary_fields(self):
        s = vintage_summary(_vintage_book(), "2024-Q1")
        self.assertEqual(s["count"], 4)
        self.assertEqual(s["defaults"], 2)
        self.assertEqual(s["default_rate"], 0.5)
        self.assertEqual(s["cum_default_at_mob"]["6"], 0.5)


class TestSeededBook(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.loans = generate_loans()
        cls.summaries = all_vintages(cls.loans)

    def test_eight_summaries(self):
        self.assertEqual(len(self.summaries), 8)

    def test_all_curves_monotonic(self):
        for s in self.summaries:
            self.assertEqual(s["curve"], sorted(s["curve"]), s["vintage"])

    def test_worst_at_mob6_pinned(self):
        ranking = rank_vintages(self.loans, mob=6)
        self.assertEqual(ranking[0]["vintage"], "2024-Q3")
        self.assertEqual(ranking[0]["cum_default_rate_at_mob"], 0.21)
        self.assertEqual(ranking[-1]["vintage"], "2025-Q4")
        self.assertEqual(ranking[-1]["cum_default_rate_at_mob"], 0.116667)

    def test_q3_curve_pinned(self):
        q3 = next(s for s in self.summaries if s["vintage"] == "2024-Q3")
        self.assertEqual(q3["curve"][-1], 0.32)
        self.assertEqual(q3["defaults"], 96)


if __name__ == "__main__":
    unittest.main()
