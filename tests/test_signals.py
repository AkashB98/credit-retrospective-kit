"""Cash-flow signals: grouping edges, lift math, seeded pins."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from generator import generate_loans
from helpers import loan
from signals import signal_report, trend_group, volatility_group


class TestGrouping(unittest.TestCase):
    def test_volatility_edges(self):
        self.assertEqual(volatility_group(0.0), "low_lt_0.15")
        self.assertEqual(volatility_group(0.1499), "low_lt_0.15")
        self.assertEqual(volatility_group(0.15), "mid_0.15_0.30")
        self.assertEqual(volatility_group(0.2999), "mid_0.15_0.30")
        self.assertEqual(volatility_group(0.30), "high_ge_0.30")

    def test_trend_edges(self):
        self.assertEqual(trend_group(-0.02), "falling_lt_-0.01")
        self.assertEqual(trend_group(-0.01), "stable_-0.01_0.01")
        self.assertEqual(trend_group(0.01), "stable_-0.01_0.01")
        self.assertEqual(trend_group(0.02), "rising_gt_0.01")


class TestLiftHandComputed(unittest.TestCase):
    def test_lift_math(self):
        loans = [loan(income_volatility_cv=0.40, defaulted=True, default_mob=2),
                 loan(income_volatility_cv=0.40),
                 loan(income_volatility_cv=0.05),
                 loan(income_volatility_cv=0.05)]
        rep = signal_report(loans)
        self.assertEqual(rep["overall_default_rate"], 0.25)
        high = rep["volatility_groups"][2]
        self.assertEqual(high["default_rate"], 0.5)
        self.assertEqual(high["lift"], 2.0)
        low = rep["volatility_groups"][0]
        self.assertEqual(low["lift"], 0.0)

    def test_empty_book(self):
        rep = signal_report([])
        self.assertEqual(rep["overall_default_rate"], 0.0)
        self.assertTrue(all(r["count"] == 0 for r in rep["volatility_groups"]))


class TestSeededSignals(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rep = signal_report(generate_loans())

    def test_volatility_monotonic_and_pinned(self):
        self.assertTrue(self.rep["volatility_monotonic"])
        rates = [r["default_rate"] for r in self.rep["volatility_groups"]]
        self.assertEqual(rates, [0.144951, 0.205622, 0.284658])

    def test_trend_groups_pinned(self):
        rows = {r["group"]: r for r in self.rep["trend_groups"]}
        self.assertEqual(rows["falling_lt_-0.01"]["default_rate"], 0.27451)
        self.assertEqual(rows["rising_gt_0.01"]["default_rate"], 0.147644)
        self.assertEqual(self.rep["falling_vs_rising_lift_gap"], 0.610177)

    def test_group_counts_partition_book(self):
        total = sum(r["count"] for r in self.rep["volatility_groups"])
        self.assertEqual(total, 2400)
        total_t = sum(r["count"] for r in self.rep["trend_groups"])
        self.assertEqual(total_t, 2400)

    def test_defaulters_have_worse_signals_on_average(self):
        self.assertGreater(self.rep["mean_volatility_defaulted"],
                           self.rep["mean_volatility_non_defaulted"])
        self.assertLess(self.rep["mean_trend_defaulted"],
                        self.rep["mean_trend_non_defaulted"])

    def test_mean_values_pinned(self):
        self.assertEqual(self.rep["mean_volatility_defaulted"], 0.248063)
        self.assertEqual(self.rep["mean_trend_defaulted"], -0.006076)


if __name__ == "__main__":
    unittest.main()
