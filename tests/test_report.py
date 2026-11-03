"""Report assembly: structure, breaches, text rendering."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from generator import generate_loans
from helpers import loan
from model_perf import CALIBRATION_THRESHOLD, PSI_THRESHOLD
from report import breaches, build_report, format_text_report


class TestSeededReport(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = build_report(generate_loans())

    def test_headline_counts(self):
        self.assertEqual(self.report["total_loans"], 2400)
        self.assertEqual(self.report["total_defaults"], 499)
        self.assertEqual(self.report["overall_default_rate"], 0.207917)

    def test_verdict_pass_no_breaches(self):
        self.assertEqual(self.report["verdict"], "pass")
        self.assertEqual(self.report["breaches"], [])

    def test_worst_vintage(self):
        worst = self.report["worst_vintage_at_mob"]
        self.assertEqual(worst["vintage"], "2024-Q3")
        self.assertEqual(worst["rank"], 1)

    def test_text_report_contains_headlines(self):
        text = format_text_report(self.report)
        self.assertIn("2024-Q3", text)
        self.assertIn("AUC 0.735782", text)
        self.assertIn("Verdict: PASS", text)
        self.assertIn("synthetic", text.lower())

    def test_report_is_deterministic(self):
        self.assertEqual(build_report(generate_loans()), self.report)


class TestBreaches(unittest.TestCase):
    def _fake_report(self, psi_value, cal_error):
        return {"model": {"psi": psi_value, "max_calibration_error": cal_error}}

    def test_no_breach_at_thresholds(self):
        self.assertEqual(breaches(self._fake_report(PSI_THRESHOLD,
                                                    CALIBRATION_THRESHOLD)), [])

    def test_psi_breach(self):
        out = breaches(self._fake_report(PSI_THRESHOLD + 0.01, 0.0))
        self.assertEqual(len(out), 1)
        self.assertIn("PSI", out[0])

    def test_calibration_breach(self):
        out = breaches(self._fake_report(0.0, CALIBRATION_THRESHOLD + 0.01))
        self.assertEqual(len(out), 1)
        self.assertIn("calibration", out[0])

    def test_drifted_book_breaches_via_build_report(self):
        # Early window all low scores, late window all high scores and
        # every loan defaulted despite middling scores -> PSI explodes.
        early = ([loan(vintage="2024-Q1", risk_score=0.05) for _ in range(25)]
                 + [loan(vintage="2024-Q2", risk_score=0.05) for _ in range(25)])
        late = ([loan(vintage="2025-Q3", risk_score=0.55, defaulted=True,
                      default_mob=4, months_on_book=18) for _ in range(25)]
                + [loan(vintage="2025-Q4", risk_score=0.55, defaulted=True,
                        default_mob=4, months_on_book=18) for _ in range(25)])
        rep = build_report(early + late)
        self.assertEqual(rep["verdict"], "breach")
        self.assertTrue(rep["breaches"])


if __name__ == "__main__":
    unittest.main()
