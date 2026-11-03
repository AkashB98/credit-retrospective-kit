"""Generator: determinism, vintage split, planted structure."""

import hashlib
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from generator import (DEFAULT_COUNT, PER_VINTAGE, VINTAGES, generate_loans,
                       loans_to_csv, loans_to_jsonl)
from validation import validate_book


class TestGenerator(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.loans = generate_loans()

    def test_default_count(self):
        self.assertEqual(len(self.loans), DEFAULT_COUNT)
        self.assertEqual(DEFAULT_COUNT, 2400)

    def test_exactly_300_per_vintage(self):
        for v in VINTAGES:
            group = [ln for ln in self.loans if ln["vintage"] == v]
            self.assertEqual(len(group), PER_VINTAGE, v)

    def test_eight_vintages_in_order(self):
        self.assertEqual([ln["vintage"] for ln in self.loans],
                         sorted([ln["vintage"] for ln in self.loans],
                                key=VINTAGES.index))

    def test_deterministic_same_seed(self):
        self.assertEqual(generate_loans(), self.loans)

    def test_different_seed_differs(self):
        self.assertNotEqual(generate_loans(seed=7), self.loans)

    def test_jsonl_md5_pinned(self):
        md5 = hashlib.md5(loans_to_jsonl(self.loans).encode()).hexdigest()
        self.assertEqual(md5, "90e073febbfc0c583207ccdbbcd7101f")

    def test_loan_ids_unique_and_sequential(self):
        ids = [ln["loan_id"] for ln in self.loans]
        self.assertEqual(len(set(ids)), len(ids))
        self.assertEqual(ids[0], "NL-00001")
        self.assertEqual(ids[-1], "NL-02400")

    def test_generated_book_validates_clean(self):
        self.assertEqual(validate_book(self.loans), [])

    def test_default_mob_within_window(self):
        for ln in self.loans:
            if ln["defaulted"]:
                self.assertIsInstance(ln["default_mob"], int)
                self.assertGreaterEqual(ln["default_mob"], 1)
                self.assertLessEqual(ln["default_mob"], ln["months_on_book"])
                self.assertTrue(ln["ever_delinquent"])
            else:
                self.assertIsNone(ln["default_mob"])

    def test_months_on_book_at_least_six(self):
        self.assertTrue(all(ln["months_on_book"] >= 6 for ln in self.loans))

    def test_risk_scores_in_unit_interval(self):
        self.assertTrue(all(0.0 < ln["risk_score"] < 1.0 for ln in self.loans))

    def test_worse_credit_defaults_more(self):
        def rate(band):
            g = [ln for ln in self.loans if ln["credit_score_band"] == band]
            return sum(1 for ln in g if ln["defaulted"]) / len(g)
        self.assertGreater(rate("poor"), rate("good"))
        self.assertGreater(rate("good"), rate("excellent"))

    def test_planted_vintage_is_worst_overall(self):
        def rate(v):
            g = [ln for ln in self.loans if ln["vintage"] == v]
            return sum(1 for ln in g if ln["defaulted"]) / len(g)
        self.assertEqual(max(VINTAGES, key=rate), "2024-Q3")

    def test_small_count_split(self):
        loans = generate_loans(count=16)
        self.assertEqual(len(loans), 16)
        for v in VINTAGES:
            self.assertEqual(len([ln for ln in loans if ln["vintage"] == v]), 2)

    def test_per_vintage_override(self):
        loans = generate_loans(per_vintage=5)
        self.assertEqual(len(loans), 40)

    def test_negative_count_rejected(self):
        with self.assertRaises(ValueError):
            generate_loans(count=-1)

    def test_csv_round_trip_shape(self):
        text = loans_to_csv(self.loans[:3])
        lines = text.strip().splitlines()
        self.assertEqual(len(lines), 4)  # header + 3 rows
        self.assertTrue(lines[0].startswith("loan_id,vintage,"))


if __name__ == "__main__":
    unittest.main()
