"""Retrospective report assembly: one pure function of the loan book.

The report answers, in order: how big is the book and how bad was it
overall; how did each vintage behave (and which was worst at a fair,
fixed month-on-book); did the origination score discriminate and stay
calibrated; has the score distribution drifted; and do the cash-flow
signals separate defaulters. A text rendering is included because a
retrospective is a document a person reads, not only JSON a pipe eats.
"""

from __future__ import annotations

from typing import Dict, List

from model_perf import CALIBRATION_THRESHOLD, PSI_THRESHOLD, model_report
from signals import signal_report
from vintage import DEFAULT_MOB, all_vintages, rank_vintages


def breaches(report: Dict) -> List[str]:
    """Stated-threshold breaches that fail the CI ``check`` gate."""
    out = []
    model = report["model"]
    if model["psi"] > PSI_THRESHOLD:
        out.append(f"PSI {model['psi']} > threshold {PSI_THRESHOLD} "
                   f"(score distribution drifted materially)")
    if model["max_calibration_error"] > CALIBRATION_THRESHOLD:
        out.append(f"max calibration error {model['max_calibration_error']} "
                   f"> threshold {CALIBRATION_THRESHOLD} "
                   f"(a score band's predicted risk misses its observed rate)")
    return out


def build_report(loans: List[Dict]) -> Dict:
    defaults = sum(1 for ln in loans if ln.get("defaulted"))
    report = {
        "lender": "Northstar Lending (fictional, synthetic data only)",
        "total_loans": len(loans),
        "total_defaults": defaults,
        "overall_default_rate": round(defaults / len(loans), 6) if loans else 0.0,
        "vintages": all_vintages(loans),
        "vintage_ranking_at_mob": rank_vintages(loans, mob=DEFAULT_MOB),
        "ranking_mob": DEFAULT_MOB,
        "model": model_report(loans) if loans else {
            "auc": 0.0, "calibration": [], "max_calibration_error": 0.0,
            "rank_ordered": True, "psi": 0.0, "psi_verdict": "stable",
            "psi_threshold": PSI_THRESHOLD,
            "calibration_threshold": CALIBRATION_THRESHOLD,
            "early_window_count": 0, "late_window_count": 0,
            "early_band_shares": {}, "late_band_shares": {}},
        "signals": signal_report(loans),
    }
    worst = report["vintage_ranking_at_mob"][0] if report["vintage_ranking_at_mob"] else None
    report["worst_vintage_at_mob"] = worst
    report["breaches"] = breaches(report)
    report["verdict"] = "breach" if report["breaches"] else "pass"
    return report


def format_text_report(report: Dict) -> str:
    lines = []
    lines.append("Northstar Lending — credit portfolio retrospective (synthetic data)")
    lines.append(f"Loans: {report['total_loans']}  Defaults: {report['total_defaults']} "
                 f"({report['overall_default_rate']:.2%})")
    lines.append("")
    lines.append(f"Vintage ranking at month-on-book {report['ranking_mob']} "
                 f"(worst first):")
    for row in report["vintage_ranking_at_mob"]:
        lines.append(f"  {row['rank']}. {row['vintage']}: "
                     f"{row['cum_default_rate_at_mob']:.2%} cumulative defaults "
                     f"(n={row['count']})")
    model = report["model"]
    lines.append("")
    lines.append(f"Model retrospective: AUC {model['auc']} "
                 f"(rank-ordering; 0.5 = coin flip), "
                 f"max calibration error {model['max_calibration_error']}, "
                 f"PSI {model['psi']} ({model['psi_verdict']}, "
                 f"threshold {model['psi_threshold']})")
    lines.append(f"Calibration by score band (predicted vs observed default rate; "
                 f"loans observed >= {model.get('calibration_min_mob', 12)} months, "
                 f"n={model.get('calibration_loans', 0)}):")
    for row in model["calibration"]:
        lines.append(f"  {row['band']}: n={row['count']} predicted "
                     f"{row['predicted']:.2%} observed {row['observed']:.2%}")
    sig = report["signals"]
    lines.append("")
    lines.append("Cash-flow signals (default rate by group):")
    for row in sig["volatility_groups"]:
        lines.append(f"  income volatility {row['group']}: {row['default_rate']:.2%} "
                     f"(lift {row['lift']})")
    for row in sig["trend_groups"]:
        lines.append(f"  balance trend {row['group']}: {row['default_rate']:.2%} "
                     f"(lift {row['lift']})")
    lines.append("")
    lines.append(f"Verdict: {report['verdict'].upper()}")
    for breach in report["breaches"]:
        lines.append(f"  BREACH: {breach}")
    return "\n".join(lines) + "\n"
