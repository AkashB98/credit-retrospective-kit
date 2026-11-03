"""Model-performance retrospective: did the origination score work?

Three questions, all computed from scratch in the standard library:

* Discrimination — does the score rank-order risk? Measured by AUC
  (area under the ROC curve): the probability that a randomly chosen
  defaulter was scored riskier than a randomly chosen non-defaulter.
  0.5 is a coin flip; 1.0 is perfect ranking. Computed with the
  Mann-Whitney rank formula, ties taking average ranks.
* Calibration — in each score band, does the average predicted score
  match the share that actually defaulted? A score can rank well and
  still be badly calibrated (always too optimistic, say).
* Drift — has the score distribution itself moved between an early
  window and a late window? Measured by PSI (population stability
  index): PSI = sum over bands of (late% - early%) * ln(late% / early%).
  Convention: < 0.10 stable, 0.10-0.25 moderate shift, > 0.25 material.
"""

from __future__ import annotations

import math
from typing import Dict, List, Tuple

SCORE_BANDS = ["S1", "S2", "S3", "S4", "S5"]
SCORE_BAND_EDGES = [0.15, 0.30, 0.45, 0.60]  # upper edges of S1..S4
PSI_EPSILON = 0.0001
PSI_THRESHOLD = 0.25
CALIBRATION_THRESHOLD = 0.20
# Calibration is judged only on loans observed for the score's full
# 12-month prediction horizon — a loan seen for 6 months cannot yet
# prove a 12-month prediction wrong.
CALIBRATION_MIN_MOB = 12


def score_band(score: float) -> str:
    for edge, band in zip(SCORE_BAND_EDGES, SCORE_BANDS):
        if score < edge:
            return band
    return SCORE_BANDS[-1]


def auc(loans: List[Dict]) -> float:
    """Mann-Whitney AUC of ``risk_score`` against ``defaulted``.

    Raises ValueError when either class is empty — an AUC over one
    class is undefined, and returning 0.5 would lie quietly.
    """
    scored = sorted(loans, key=lambda ln: ln["risk_score"])
    n_pos = sum(1 for ln in scored if ln.get("defaulted"))
    n_neg = len(scored) - n_pos
    if n_pos == 0 or n_neg == 0:
        raise ValueError("AUC undefined: need both defaulted and non-defaulted loans")
    rank_sum_pos = 0.0
    i = 0
    while i < len(scored):
        j = i
        while j + 1 < len(scored) and scored[j + 1]["risk_score"] == scored[i]["risk_score"]:
            j += 1
        avg_rank = (i + 1 + j + 1) / 2.0  # 1-based ranks i+1 .. j+1
        rank_sum_pos += avg_rank * sum(1 for ln in scored[i:j + 1] if ln.get("defaulted"))
        i = j + 1
    value = (rank_sum_pos - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg)
    return round(value, 6)


def calibration_by_band(loans: List[Dict], min_mob: int = 0) -> List[Dict]:
    """Per score band: count, mean predicted score, observed default rate.

    With ``min_mob`` > 0 only loans observed at least that many months
    are counted (the seasoned population calibration should be judged on).
    """
    pool = [ln for ln in loans if ln.get("months_on_book", 0) >= min_mob]
    rows = []
    for band in SCORE_BANDS:
        group = [ln for ln in pool if score_band(ln["risk_score"]) == band]
        count = len(group)
        predicted = (sum(ln["risk_score"] for ln in group) / count) if count else 0.0
        observed = (sum(1 for ln in group if ln.get("defaulted")) / count
                    if count else 0.0)
        rows.append({
            "band": band,
            "count": count,
            "share": round(count / len(pool), 6) if pool else 0.0,
            "predicted": round(predicted, 6),
            "observed": round(observed, 6),
            "abs_error": round(abs(observed - predicted), 6),
        })
    return rows


def max_calibration_error(loans: List[Dict], min_mob: int = 0) -> float:
    rows = [r for r in calibration_by_band(loans, min_mob=min_mob) if r["count"] > 0]
    return max((r["abs_error"] for r in rows), default=0.0)


PSI_BANDS = [f"P{i}" for i in range(1, 11)]
PSI_BAND_EDGES = [0.10 * i for i in range(1, 10)]  # decile-width bands


def psi_band(score: float) -> str:
    """Finer (0.10-wide) band used only for PSI: drift hides inside the
    broad calibration bands, so the stability index gets deciles."""
    for edge, band in zip(PSI_BAND_EDGES, PSI_BANDS):
        if score < edge:
            return band
    return PSI_BANDS[-1]


def band_shares(loans: List[Dict]) -> Dict[str, float]:
    """Share of loans per PSI band (decile-width), keys P1..P10."""
    counts = {band: 0 for band in PSI_BANDS}
    for ln in loans:
        counts[psi_band(ln["risk_score"])] += 1
    total = len(loans)
    return {band: (counts[band] / total if total else 0.0) for band in PSI_BANDS}


def psi(early: List[Dict], late: List[Dict]) -> float:
    """Population stability index between two loan windows.

    PSI = sum_bands (late_share - early_share) * ln(late_share / early_share),
    with each share floored at PSI_EPSILON so an empty band cannot divide
    by zero. Identical distributions give exactly 0.0 (before rounding).
    """
    e, l = band_shares(early), band_shares(late)
    total = 0.0
    for band in PSI_BANDS:
        es = max(e[band], PSI_EPSILON)
        ls = max(l[band], PSI_EPSILON)
        total += (ls - es) * math.log(ls / es)
    return round(total, 6)


def psi_verdict(value: float) -> str:
    if value > PSI_THRESHOLD:
        return "material_shift"
    if value >= 0.10:
        return "moderate_shift"
    return "stable"


def early_late_windows(loans: List[Dict]) -> Tuple[List[Dict], List[Dict]]:
    """Early = first two vintages present, late = last two vintages present."""
    from generator import VINTAGES
    present = [v for v in VINTAGES if any(ln.get("vintage") == v for ln in loans)]
    if len(present) < 2:
        return list(loans), list(loans)
    early_v, late_v = set(present[:2]), set(present[-2:])
    return ([ln for ln in loans if ln.get("vintage") in early_v],
            [ln for ln in loans if ln.get("vintage") in late_v])


def model_report(loans: List[Dict]) -> Dict:
    early, late = early_late_windows(loans)
    psi_value = psi(early, late)
    cal = calibration_by_band(loans, min_mob=CALIBRATION_MIN_MOB)
    seasoned = [ln for ln in loans if ln.get("months_on_book", 0) >= CALIBRATION_MIN_MOB]
    band_defaults = [r["observed"] for r in cal if r["count"] > 0]
    return {
        "auc": auc(loans) if loans else 0.0,
        "calibration": cal,
        "calibration_loans": len(seasoned),
        "calibration_min_mob": CALIBRATION_MIN_MOB,
        "max_calibration_error": max_calibration_error(
            loans, min_mob=CALIBRATION_MIN_MOB),
        "rank_ordered": band_defaults == sorted(band_defaults),
        "psi": psi_value,
        "psi_verdict": psi_verdict(psi_value),
        "psi_threshold": PSI_THRESHOLD,
        "calibration_threshold": CALIBRATION_THRESHOLD,
        "early_window_count": len(early),
        "late_window_count": len(late),
        "early_band_shares": {k: round(v, 6) for k, v in band_shares(early).items()},
        "late_band_shares": {k: round(v, 6) for k, v in band_shares(late).items()},
    }
