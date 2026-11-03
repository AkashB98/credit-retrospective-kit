"""Validation: clean books pass, planted defects are reported."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from generator import generate_loans
from helpers import loan
from validation import validate_book, validate_loan


class TestValidation(unittest.TestCase):
    def test_helper_loan_is_clean(self):
        self.assertEqual(validate_loan(loan()), [])

    def test_generated_book_is_clean(self):
        self.assertEqual(validate_book(generate_loans()), [])

    def test_empty_book_flagged(self):
        self.assertEqual(validate_book([]), ["book is empty"])

    def test_missing_field(self):
        bad = loan()
        del bad["apr"]
        self.assertTrue(any("missing field 'apr'" in i for i in validate_loan(bad)))

    def test_invalid_vintage(self):
        self.assertTrue(any("invalid vintage" in i
                            for i in validate_loan(loan(vintage="2030-Q9"))))

    def test_invalid_credit_band(self):
        self.assertTrue(any("credit_score_band" in i
                            for i in validate_loan(loan(credit_score_band="meh"))))

    def test_risk_score_bool_trap(self):
        bad = loan()
        bad["risk_score"] = True
        self.assertTrue(any("risk_score" in i for i in validate_loan(bad)))

    def test_risk_score_out_of_range(self):
        self.assertTrue(any("risk_score" in i
                            for i in validate_loan(loan(risk_score=1.5))))

    def test_defaulted_needs_default_mob(self):
        bad = loan(defaulted=True, default_mob=None)
        self.assertTrue(any("default_mob" in i for i in validate_loan(bad)))

    def test_default_mob_after_window(self):
        bad = loan(defaulted=True, default_mob=30, months_on_book=12)
        self.assertTrue(any("default_mob out of range" in i
                            for i in validate_loan(bad)))

    def test_non_defaulted_with_default_mob(self):
        bad = loan(defaulted=False, default_mob=3)
        self.assertTrue(any("default_mob None" in i for i in validate_loan(bad)))

    def test_defaulted_must_have_been_delinquent(self):
        bad = loan(defaulted=True, default_mob=3, ever_delinquent=False)
        self.assertTrue(any("delinquent" in i for i in validate_loan(bad)))

    def test_defaulted_not_bool(self):
        bad = loan(default_mob=3, ever_delinquent=True)
        bad["defaulted"] = "yes"
        self.assertTrue(any("defaulted must be a bool" in i
                            for i in validate_loan(bad)))

    def test_months_on_book_bool_trap(self):
        bad = loan()
        bad["months_on_book"] = True
        self.assertTrue(any("months_on_book" in i for i in validate_loan(bad)))

    def test_duplicate_loan_id(self):
        a, b = loan(), loan()
        b["loan_id"] = a["loan_id"]
        self.assertTrue(any("duplicate loan_id" in i
                            for i in validate_book([a, b])))

    def test_negative_balance_flagged(self):
        bad = loan()
        bad["avg_balance"] = -5
        self.assertTrue(any("avg_balance" in i for i in validate_loan(bad)))


if __name__ == "__main__":
    unittest.main()
