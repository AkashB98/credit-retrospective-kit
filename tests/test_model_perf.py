"""Model performance: AUC / PSI / calibration, hand-computed + pinned."""

import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from generator import generate_loans
from helpers import book, loan
from model_perf import (PSI_EPSILON, auc, band_shares, calibration_by_band,
                        early_late_windows, max_calibration_error, model_report,
                        psi, psi_band, psi_verdict, score_band)


class TestAucHandComputed(unittest.TestCase):
    def test_perfect_ranking_is_one(self):
        loans = book([(0.9, True), (0.8, True), (0.2, False), (0.1, False)])
        self.assertEqual(auc(loans), 1.0)

    def test_reversed_ranking_is_zero(self):
        loans = book([(0.1, True), (0.2, True), (0.8, False), (0.9, False)])
        self.assertEqual(auc(loans), 0.0)

    def test_all_tied_scores_is_half(self):
        loans = book([(0.5, True), (0.5, True), (0.5, False), (0.5, False)])
        self.assertEqual(auc(loans), 0.5)

    def test_partial_credit(self):
        # Positives 0.9, 0.4; negatives 0.5, 0.1: pairs won 3 of 4.
        loans = book([(0.9, True), (0.4, True), (0.5, False), (0.1, False)])
        self.assertEqual(auc(loans), 0.75)

    def test_tie_between_classes_gets_half_credit(self):
        loans = book([(0.5, True), (0.5, False), (0.1, False)])
        self.assertEqual(auc(loans), 0.75)

    def test_single_class_raises(self):
        with self.assertRaises(ValueError):
            auc(book([(0.5, True), (0.6, True)]))
        with self.assertRaises(ValueError):
            auc(book([(0.5, False)]))
        with self.assertRaises(ValueError):
            auc([])


def _brute_force_auc(loans):
    """AUC by definition: over every (defaulter, non-defaulter) pair,
    score 1 if the defaulter was scored riskier, 0.5 on a tie, else 0."""
    pos = [ln["risk_score"] for ln in loans if ln["defaulted"]]
    neg = [ln["risk_score"] for ln in loans if not ln["defaulted"]]
    wins = 0.0
    for p in pos:
        for n in neg:
            if p > n:
                wins += 1.0
            elif p == n:
                wins += 0.5
    return round(wins / (len(pos) * len(neg)), 6)


class TestAucBruteForce(unittest.TestCase):
    """The Mann-Whitney implementation in model_perf.auc — tie-averaged
    ranks and all — must agree with a brute-force pairwise count."""

    def test_matches_brute_force_no_ties(self):
        loans = book([(0.9, True), (0.4, True), (0.7, False),
                      (0.5, False), (0.1, False), (0.3, True)])
        self.assertEqual(auc(loans), _brute_force_auc(loans))

    def test_matches_brute_force_with_ties(self):
        loans = book([(0.5, True), (0.5, True), (0.5, False),
                      (0.2, True), (0.2, False), (0.8, False),
                      (0.8, True), (0.1, False)])
        self.assertEqual(auc(loans), _brute_force_auc(loans))

    def test_matches_brute_force_on_seeded_slice(self):
        loans = generate_loans()[:300]
        self.assertEqual(auc(loans), _brute_force_auc(loans))


class TestPlantedKnownAnswers(unittest.TestCase):
    """Golden known-answer cases: a planted drift shift must be flagged
    by PSI and a planted miscalibrated band must be caught by calibration."""

    def test_planted_drift_shift_flagged_by_psi(self):
        early = [loan(vintage="2024-Q1", risk_score=0.05 + 0.01 * (i % 5))
                 for i in range(100)]
        late = [loan(vintage="2025-Q4", risk_score=0.45 + 0.01 * (i % 5))
                for i in range(100)]
        value = psi(early, late)
        self.assertGreater(value, 0.25)
        self.assertEqual(psi_verdict(value), "material_shift")

    def test_planted_miscalibrated_band_caught(self):
        # Band S3 claims ~37% risk; plant an 85% realised default rate
        # on seasoned loans — calibration must catch the bad band.
        loans = []
        for i in range(100):
            defaulted = i < 85
            loans.append(loan(risk_score=0.37, defaulted=defaulted,
                              default_mob=4 if defaulted else None,
                              months_on_book=18))
        rows = calibration_by_band(loans, min_mob=12)
        s3 = next(r for r in rows if r["band"] == "S3")
        self.assertEqual(s3["observed"], 0.85)
        self.assertGreater(s3["abs_error"], 0.20)
        self.assertGreater(max_calibration_error(loans, min_mob=12), 0.20)


class TestScoreBands(unittest.TestCase):
    def test_band_edges(self):
        self.assertEqual(score_band(0.0), "S1")
        self.assertEqual(score_band(0.1499), "S1")
        self.assertEqual(score_band(0.15), "S2")
        self.assertEqual(score_band(0.30), "S3")
        self.assertEqual(score_band(0.45), "S4")
        self.assertEqual(score_band(0.60), "S5")
        self.assertEqual(score_band(1.0), "S5")

    def test_psi_band_edges(self):
        self.assertEqual(psi_band(0.05), "P1")
        self.assertEqual(psi_band(0.10), "P2")
        self.assertEqual(psi_band(0.95), "P10")


class TestPsi(unittest.TestCase):
    def test_identical_distributions_zero(self):
        loans = book([(0.05, False), (0.25, True), (0.55, False), (0.85, True)])
        self.assertEqual(psi(loans, loans), 0.0)

    def test_psi_formula_hand_computed(self):
        early = [loan(risk_score=0.05), loan(risk_score=0.05),
                 loan(risk_score=0.25), loan(risk_score=0.25)]
        late = [loan(risk_score=0.05), loan(risk_score=0.25),
                loan(risk_score=0.25), loan(risk_score=0.25)]
        # P1: 0.5 -> 0.25, P3 (0.25 in [0.2,0.3)): 0.5 -> 0.75, rest equal
        expected = ((0.25 - 0.5) * math.log(0.25 / 0.5)
                    + (0.75 - 0.5) * math.log(0.75 / 0.5))
        self.assertAlmostEqual(psi(early, late), round(expected, 6), places=6)

    def test_psi_symmetric(self):
        a = book([(0.05, False), (0.15, False), (0.25, True)])
        b = book([(0.35, False), (0.45, True), (0.55, False)])
        self.assertAlmostEqual(psi(a, b), psi(b, a), places=6)

    def test_psi_empty_bands_do_not_crash(self):
        a = [loan(risk_score=0.05)]
        b = [loan(risk_score=0.95)]
        self.assertGreater(psi(a, b), 0.25)

    def test_band_shares_sum_to_one(self):
        loans = generate_loans()
        self.assertAlmostEqual(sum(band_shares(loans).values()), 1.0, places=6)

    def test_verdict_bands(self):
        self.assertEqual(psi_verdict(0.05), "stable")
        self.assertEqual(psi_verdict(0.10), "moderate_shift")
        self.assertEqual(psi_verdict(0.25), "moderate_shift")
        self.assertEqual(psi_verdict(0.250001), "material_shift")

    def test_epsilon_floor_is_small(self):
        self.assertLess(PSI_EPSILON, 0.001)


class TestCalibration(unittest.TestCase):
    def test_hand_computed_band(self):
        loans = [loan(risk_score=0.10, defaulted=True, default_mob=2),
                 loan(risk_score=0.10), loan(risk_score=0.10),
                 loan(risk_score=0.10)]
        rows = calibration_by_band(loans)
        s1 = rows[0]
        self.assertEqual((s1["count"], s1["predicted"], s1["observed"]),
                         (4, 0.10, 0.25))
        self.assertEqual(s1["abs_error"], 0.15)

    def test_min_mob_filters_unseasoned(self):
        loans = [loan(risk_score=0.10, months_on_book=6),
                 loan(risk_score=0.10, months_on_book=18)]
        rows = calibration_by_band(loans, min_mob=12)
        self.assertEqual(rows[0]["count"], 1)
        rows_all = calibration_by_band(loans)
        self.assertEqual(rows_all[0]["count"], 2)

    def test_empty_book_rows_zero(self):
        rows = calibration_by_band([])
        self.assertTrue(all(r["count"] == 0 for r in rows))
        self.assertEqual(max_calibration_error([]), 0.0)


class TestSeededModel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = model_report(generate_loans())

    def test_auc_pinned(self):
        self.assertEqual(self.report["auc"], 0.735782)

    def test_psi_pinned(self):
        self.assertEqual(self.report["psi"], 0.009436)
        self.assertEqual(self.report["psi_verdict"], "stable")

    def test_calibration_pinned(self):
        cal = {r["band"]: r for r in self.report["calibration"]}
        self.assertEqual(cal["S1"]["count"], 519)
        self.assertEqual(cal["S1"]["observed"], 0.078998)
        self.assertEqual(cal["S5"]["observed"], 0.674419)
        self.assertEqual(self.report["max_calibration_error"], 0.032428)

    def test_rank_ordered(self):
        self.assertTrue(self.report["rank_ordered"])

    def test_calibration_population_is_seasoned_subset(self):
        self.assertEqual(self.report["calibration_loans"], 1436)
        self.assertLess(self.report["calibration_loans"], 2400)

    def test_windows_are_first_and_last_two_vintages(self):
        early, late = early_late_windows(generate_loans())
        self.assertEqual(len(early), 600)
        self.assertEqual(len(late), 600)
        self.assertTrue(all(ln["vintage"] in ("2024-Q1", "2024-Q2") for ln in early))
        self.assertTrue(all(ln["vintage"] in ("2025-Q3", "2025-Q4") for ln in late))


if __name__ == "__main__":
    unittest.main()
