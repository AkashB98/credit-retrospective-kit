"""Vintage analysis: how each origination cohort behaved over time.

A *vintage* is the set of loans originated in one quarter. Its
*cumulative default curve* is, for each month-on-book (MOB) m, the share
of the vintage that had defaulted on or before month m. Curves only
rise. Comparing vintages at one fixed MOB is the fair comparison — a
young vintage has simply had less time to go bad.
"""

from __future__ import annotations

from typing import Dict, List

from generator import VINTAGES

DEFAULT_MOB = 6
MAX_CURVE_MOB = 12


def vintage_loans(loans: List[Dict], vintage: str) -> List[Dict]:
    return [ln for ln in loans if ln.get("vintage") == vintage]


def cumulative_default_rate(loans: List[Dict], mob: int) -> float:
    """Share of ``loans`` that defaulted on or before ``mob`` (0.0 if empty)."""
    if not loans:
        return 0.0
    bad = sum(1 for ln in loans
              if ln.get("defaulted") and ln.get("default_mob") is not None
              and ln["default_mob"] <= mob)
    return round(bad / len(loans), 6)


def default_curve(loans: List[Dict], max_mob: int = MAX_CURVE_MOB) -> List[float]:
    """Cumulative default rate at MOB 1..``max_mob`` (index 0 = MOB 1)."""
    return [cumulative_default_rate(loans, m) for m in range(1, max_mob + 1)]


def vintage_summary(loans: List[Dict], vintage: str,
                    max_mob: int = MAX_CURVE_MOB) -> Dict:
    group = vintage_loans(loans, vintage)
    count = len(group)
    defaults = sum(1 for ln in group if ln.get("defaulted"))
    delinq = sum(1 for ln in group if ln.get("ever_delinquent"))
    return {
        "vintage": vintage,
        "count": count,
        "defaults": defaults,
        "default_rate": round(defaults / count, 6) if count else 0.0,
        "ever_delinquent_rate": round(delinq / count, 6) if count else 0.0,
        "avg_risk_score": round(sum(ln["risk_score"] for ln in group) / count, 6)
        if count else 0.0,
        "curve": default_curve(group, max_mob),
        "cum_default_at_mob": {str(m): cumulative_default_rate(group, m)
                               for m in (3, 6, 9, 12) if m <= max_mob},
    }


def all_vintages(loans: List[Dict], max_mob: int = MAX_CURVE_MOB) -> List[Dict]:
    present = [v for v in VINTAGES if any(ln.get("vintage") == v for ln in loans)]
    extra = sorted({ln.get("vintage") for ln in loans} - set(present))
    return [vintage_summary(loans, v, max_mob) for v in present + extra]


def rank_vintages(loans: List[Dict], mob: int = DEFAULT_MOB) -> List[Dict]:
    """Vintages ranked worst-first by cumulative default rate at ``mob``.

    Deterministic tie-break: higher rate, then earlier vintage name.
    """
    rows = []
    for summary in all_vintages(loans):
        rows.append({
            "vintage": summary["vintage"],
            "count": summary["count"],
            "cum_default_rate_at_mob": cumulative_default_rate(
                vintage_loans(loans, summary["vintage"]), mob),
            "mob": mob,
        })
    rows.sort(key=lambda r: (-r["cum_default_rate_at_mob"], r["vintage"]))
    for i, row in enumerate(rows, start=1):
        row["rank"] = i
    return rows
