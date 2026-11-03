"""Cash-flow signal deep-dive: do deposit-behaviour signals separate
defaulters from non-defaulters, beyond what the score already knows?

Two synthetic signals per loan:

* ``income_volatility_cv`` — how uneven monthly deposit income is
  (coefficient of variation: standard deviation / mean — 0 is perfectly
  steady pay, higher is lumpier income).
* ``balance_trend_pct`` — the average monthly % change in the deposit
  balance (negative = balances bleeding down month after month).

Each signal is cut into plain groups and the default rate is reported
per group, with *lift* — the group's default rate divided by the whole
book's default rate, so 2.0 means "defaults at twice the book rate".
"""

from __future__ import annotations

from typing import Dict, List

VOLATILITY_GROUPS = ["low_lt_0.15", "mid_0.15_0.30", "high_ge_0.30"]
TREND_GROUPS = ["falling_lt_-0.01", "stable_-0.01_0.01", "rising_gt_0.01"]


def volatility_group(value: float) -> str:
    if value < 0.15:
        return VOLATILITY_GROUPS[0]
    if value < 0.30:
        return VOLATILITY_GROUPS[1]
    return VOLATILITY_GROUPS[2]


def trend_group(value: float) -> str:
    if value < -0.01:
        return TREND_GROUPS[0]
    if value <= 0.01:
        return TREND_GROUPS[1]
    return TREND_GROUPS[2]


def _group_rows(loans: List[Dict], key_fn, groups: List[str]) -> List[Dict]:
    overall = (sum(1 for ln in loans if ln.get("defaulted")) / len(loans)
               if loans else 0.0)
    rows = []
    for group in groups:
        members = [ln for ln in loans if key_fn(ln) == group]
        count = len(members)
        rate = (sum(1 for ln in members if ln.get("defaulted")) / count
                if count else 0.0)
        rows.append({
            "group": group,
            "count": count,
            "default_rate": round(rate, 6),
            "lift": round(rate / overall, 6) if overall > 0 else 0.0,
        })
    return rows


def signal_report(loans: List[Dict]) -> Dict:
    overall = (sum(1 for ln in loans if ln.get("defaulted")) / len(loans)
               if loans else 0.0)
    defaulted = [ln for ln in loans if ln.get("defaulted")]
    clean = [ln for ln in loans if not ln.get("defaulted")]

    def _mean(rows, field):
        return round(sum(r[field] for r in rows) / len(rows), 6) if rows else 0.0

    vol_rows = _group_rows(loans, lambda ln: volatility_group(ln["income_volatility_cv"]),
                           VOLATILITY_GROUPS)
    trend_rows = _group_rows(loans, lambda ln: trend_group(ln["balance_trend_pct"]),
                             TREND_GROUPS)
    vol_rates = [r["default_rate"] for r in vol_rows if r["count"] > 0]
    trend_falling = next((r for r in trend_rows if r["group"] == TREND_GROUPS[0]), None)
    trend_rising = next((r for r in trend_rows if r["group"] == TREND_GROUPS[2]), None)
    return {
        "overall_default_rate": round(overall, 6),
        "volatility_groups": vol_rows,
        "trend_groups": trend_rows,
        "volatility_monotonic": vol_rates == sorted(vol_rates),
        "mean_volatility_defaulted": _mean(defaulted, "income_volatility_cv"),
        "mean_volatility_non_defaulted": _mean(clean, "income_volatility_cv"),
        "mean_trend_defaulted": _mean(defaulted, "balance_trend_pct"),
        "mean_trend_non_defaulted": _mean(clean, "balance_trend_pct"),
        "falling_vs_rising_lift_gap": round(
            (trend_falling["lift"] - trend_rising["lift"])
            if trend_falling and trend_rising else 0.0, 6),
    }
