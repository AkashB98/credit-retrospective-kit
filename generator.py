"""Deterministic synthetic loan generator — Northstar Lending (fictional).

SYNTHETIC DATA ONLY. No real borrower data is ever used. Every loan is
fabricated from a seeded PRNG so the same seed always yields the same
book, byte-for-byte.

A loan book for retrospectives: 2,400 loans by default, exactly 300 in
each of 8 quarterly origination vintages (2024-Q1 .. 2025-Q4). Each loan
carries the risk score it was given at origination, whether it later
defaulted (and if so, at what month-on-book), and two synthetic
cash-flow signals — income volatility and average-balance trend — so a
retrospective can ask three different questions of the same book:
did the vintages behave, did the score work, and did the cash-flow
signals add anything?
"""

from __future__ import annotations

import random
from typing import Dict, List, Optional

VINTAGES = [f"{year}-Q{q}" for year in (2024, 2025) for q in (1, 2, 3, 4)]

# Risk multiplier per vintage: 2024-Q3 was a loose-underwriting quarter
# (the retrospective's villain), 2025-Q4 the tightest. This is a property
# of the fictional lender's history, planted so the vintage analysis has
# a real ranking to find.
VINTAGE_RISK_MULT = {
    "2024-Q1": 1.00, "2024-Q2": 1.05, "2024-Q3": 1.50, "2024-Q4": 1.15,
    "2025-Q1": 0.95, "2025-Q2": 0.90, "2025-Q3": 0.95, "2025-Q4": 0.85,
}

CREDIT_BANDS = ["poor", "fair", "good", "very_good", "excellent"]
CREDIT_WEIGHTS_EARLY = [0.13, 0.25, 0.31, 0.20, 0.11]
CREDIT_WEIGHTS_LATE = [0.26, 0.31, 0.26, 0.11, 0.06]
CREDIT_BASE_DEFAULT = {"poor": 0.38, "fair": 0.26, "good": 0.16,
                       "very_good": 0.09, "excellent": 0.04}

INCOME_BANDS = ["low", "lower_mid", "mid", "upper_mid", "high"]
INCOME_WEIGHTS = [0.18, 0.24, 0.28, 0.18, 0.12]

LOAN_FIELDS = ["loan_id", "vintage", "loan_amount", "term_months", "apr",
               "credit_score_band", "income_band", "dti_ratio",
               "months_on_book", "risk_score", "defaulted", "default_mob",
               "ever_delinquent", "income_volatility_cv", "balance_trend_pct",
               "avg_balance"]

DEFAULT_SEED = 42
DEFAULT_COUNT = 2400
PER_VINTAGE = 300


def _weighted(rng: random.Random, items, weights):
    return rng.choices(items, weights=weights, k=1)[0]


def _clamp(x: float, lo: float, hi: float) -> float:
    return min(hi, max(lo, x))


def _months_on_book(rng: random.Random, vintage_index: int) -> int:
    """Older vintages have been on the book longer; newest still >= 6."""
    hi = 22 - 2 * vintage_index
    lo = max(6, hi - 4)
    return rng.randint(lo, hi)


def generate_loans(count: int = DEFAULT_COUNT, seed: int = DEFAULT_SEED,
                   per_vintage: Optional[int] = None) -> List[Dict]:
    """Return synthetic loans, deterministic for ``seed``.

    With the default count the book is exactly ``PER_VINTAGE`` loans per
    vintage. Other counts are split as evenly as the count allows,
    filling vintages in order (the split is a pure function of count).
    """
    if count < 0:
        raise ValueError("count must be >= 0")
    if per_vintage is not None:
        if per_vintage < 0:
            raise ValueError("per_vintage must be >= 0")
        counts = [per_vintage] * len(VINTAGES)
    else:
        base, extra = divmod(count, len(VINTAGES))
        counts = [base + (1 if i < extra else 0) for i in range(len(VINTAGES))]

    rng = random.Random(seed)
    loans: List[Dict] = []
    seq = 0
    for v_idx, vintage in enumerate(VINTAGES):
        late = v_idx >= 6  # last two vintages: the "late window"
        credit_weights = CREDIT_WEIGHTS_LATE if late else CREDIT_WEIGHTS_EARLY
        mult = VINTAGE_RISK_MULT[vintage]
        for _ in range(counts[v_idx]):
            seq += 1
            credit = _weighted(rng, CREDIT_BANDS, credit_weights)
            income = _weighted(rng, INCOME_BANDS, INCOME_WEIGHTS)
            dti_base = {"poor": 0.44, "fair": 0.38, "good": 0.31,
                        "very_good": 0.25, "excellent": 0.19}[credit]
            dti = round(_clamp(rng.gauss(dti_base, 0.09), 0.05, 0.92), 4)
            apr = round(_clamp(rng.gauss(
                {"poor": 24.0, "fair": 17.5, "good": 11.5,
                 "very_good": 8.0, "excellent": 5.5}[credit], 1.8), 3.0, 36.0), 2)
            term = _weighted(rng, [12, 24, 36, 48, 60],
                             [0.12, 0.22, 0.32, 0.22, 0.12])
            loan_amount = round(max(500.0, rng.gauss(9000, 4200)), 2)

            # Cash-flow signals (synthetic): income volatility is the
            # coefficient of variation of monthly deposits; balance trend
            # is the average monthly % change in the deposit balance.
            vol_base = 0.26 if income == "low" else 0.21
            volatility = round(_clamp(rng.gauss(vol_base, 0.10), 0.02, 0.70), 4)
            trend = round(_clamp(rng.gauss(0.004 - max(0.0, dti - 0.35) * 0.05,
                                           0.030), -0.10, 0.10), 4)
            avg_balance = round(max(50.0, rng.gauss(2400, 1300)), 2)

            mob = _months_on_book(rng, v_idx)

            # Latent default propensity: credit + affordability +
            # cash-flow signals, scaled by the vintage's underwriting.
            propensity = CREDIT_BASE_DEFAULT[credit]
            propensity += max(0.0, dti - 0.35) * 0.45
            propensity += (volatility - 0.22) * 0.55
            propensity += (-trend) * 1.6
            propensity = _clamp(propensity * mult, 0.01, 0.92)

            # The origination score: the propensity the lender could see,
            # plus honest noise — a real score is never the truth itself.
            risk_score = round(_clamp(propensity + rng.gauss(0, 0.055),
                                      0.01, 0.99), 4)

            # The score is a 12-month default prediction. Default timing
            # is drawn over that fixed 12-month horizon, independent of
            # how long this loan happens to have been observed —
            # otherwise young vintages would look artificially bad at a
            # fixed MOB (their defaults would be squeezed into their
            # shorter windows). A loan only *shows* as defaulted if its
            # default month falls inside its observation window.
            would_default = rng.random() < propensity
            timing = rng.choices(range(1, 13),
                                 weights=[12 - i for i in range(12)], k=1)[0]
            defaulted = would_default and timing <= mob
            default_mob = timing if defaulted else None
            # Ever-delinquent (30+ days) is wider than default: every
            # default was delinquent first, plus some loans that cured.
            if defaulted:
                ever_delinquent = True
            else:
                ever_delinquent = rng.random() < propensity * 0.55

            loans.append({
                "loan_id": f"NL-{seq:05d}",
                "vintage": vintage,
                "loan_amount": loan_amount,
                "term_months": term,
                "apr": apr,
                "credit_score_band": credit,
                "income_band": income,
                "dti_ratio": dti,
                "months_on_book": mob,
                "risk_score": risk_score,
                "defaulted": defaulted,
                "default_mob": default_mob,
                "ever_delinquent": ever_delinquent,
                "income_volatility_cv": volatility,
                "balance_trend_pct": trend,
                "avg_balance": avg_balance,
            })
    return loans


def loans_to_csv(loans: List[Dict]) -> str:
    import csv
    import io
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=LOAN_FIELDS)
    writer.writeheader()
    for loan in loans:
        writer.writerow({k: loan[k] for k in LOAN_FIELDS})
    return buf.getvalue()


def loans_to_jsonl(loans: List[Dict]) -> str:
    import json
    return "".join(json.dumps(loan, sort_keys=True) + "\n" for loan in loans)
