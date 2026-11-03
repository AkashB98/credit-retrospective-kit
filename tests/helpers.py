"""Shared loan builders for the test suite (not a test module)."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_counter = [0]


def loan(vintage="2024-Q1", risk_score=0.20, defaulted=False, default_mob=None,
         months_on_book=18, income_volatility_cv=0.20, balance_trend_pct=0.0,
         credit_score_band="good", income_band="mid", dti_ratio=0.30,
         ever_delinquent=None):
    _counter[0] += 1
    if ever_delinquent is None:
        ever_delinquent = bool(defaulted)
    return {
        "loan_id": f"NL-T{_counter[0]:04d}",
        "vintage": vintage,
        "loan_amount": 8000.0,
        "term_months": 36,
        "apr": 11.0,
        "credit_score_band": credit_score_band,
        "income_band": income_band,
        "dti_ratio": dti_ratio,
        "months_on_book": months_on_book,
        "risk_score": risk_score,
        "defaulted": defaulted,
        "default_mob": default_mob,
        "ever_delinquent": ever_delinquent,
        "income_volatility_cv": income_volatility_cv,
        "balance_trend_pct": balance_trend_pct,
        "avg_balance": 2000.0,
    }


def book(specs, vintage="2024-Q1"):
    """Build loans from (risk_score, defaulted) pairs."""
    out = []
    for score, defaulted in specs:
        out.append(loan(vintage=vintage, risk_score=score, defaulted=defaulted,
                        default_mob=3 if defaulted else None))
    return out
