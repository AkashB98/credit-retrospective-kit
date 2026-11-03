"""Data-quality validation for retrospective loan books.

Returns a list of human-readable issue strings; an empty list means the
book is clean. Validation never raises on bad *data* — it reports — so
the CLI ``check`` gate can map issues to exit code 2.
"""

from __future__ import annotations

from typing import Dict, List

from generator import CREDIT_BANDS, INCOME_BANDS, LOAN_FIELDS, VINTAGES

REQUIRED_FIELDS = LOAN_FIELDS


def _is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def validate_loan(loan: Dict, index: int = 0) -> List[str]:
    issues: List[str] = []
    lid = loan.get("loan_id", f"<row {index}>")
    for field in REQUIRED_FIELDS:
        if field not in loan or loan[field] is None or loan[field] == "":
            # default_mob is legitimately None for non-defaulters.
            if field == "default_mob" and loan.get("defaulted") is False \
                    and "default_mob" in loan:
                continue
            issues.append(f"{lid}: missing field '{field}'")
    if issues:
        return issues

    if loan["vintage"] not in VINTAGES:
        issues.append(f"{lid}: invalid vintage '{loan['vintage']}'")
    if loan["credit_score_band"] not in CREDIT_BANDS:
        issues.append(f"{lid}: invalid credit_score_band '{loan['credit_score_band']}'")
    if loan["income_band"] not in INCOME_BANDS:
        issues.append(f"{lid}: invalid income_band '{loan['income_band']}'")
    if not _is_number(loan["loan_amount"]) or loan["loan_amount"] <= 0:
        issues.append(f"{lid}: loan_amount must be > 0")
    if not _is_number(loan["apr"]) or not (0 <= loan["apr"] <= 40):
        issues.append(f"{lid}: apr out of range [0, 40]")
    if not _is_number(loan["dti_ratio"]) or not (0 <= loan["dti_ratio"] <= 1.0):
        issues.append(f"{lid}: dti_ratio out of range [0, 1]")
    if not isinstance(loan["months_on_book"], int) \
            or isinstance(loan["months_on_book"], bool) \
            or not (1 <= loan["months_on_book"] <= 36):
        issues.append(f"{lid}: months_on_book must be int in [1, 36]")
    if not _is_number(loan["risk_score"]) or not (0 <= loan["risk_score"] <= 1):
        issues.append(f"{lid}: risk_score must be a number in [0, 1]")
    if not isinstance(loan["term_months"], int) \
            or isinstance(loan["term_months"], bool) or loan["term_months"] <= 0:
        issues.append(f"{lid}: term_months must be a positive int")
    if not isinstance(loan["defaulted"], bool):
        issues.append(f"{lid}: defaulted must be a bool")
    if not isinstance(loan["ever_delinquent"], bool):
        issues.append(f"{lid}: ever_delinquent must be a bool")
    if isinstance(loan.get("defaulted"), bool):
        if loan["defaulted"]:
            if not isinstance(loan["default_mob"], int) \
                    or isinstance(loan["default_mob"], bool):
                issues.append(f"{lid}: defaulted loan needs an int default_mob")
            elif _is_number(loan.get("months_on_book")) and not (
                    1 <= loan["default_mob"] <= loan["months_on_book"]):
                issues.append(f"{lid}: default_mob out of range [1, months_on_book]")
            if loan.get("ever_delinquent") is False:
                issues.append(f"{lid}: a defaulted loan must have been delinquent")
        elif loan["default_mob"] is not None:
            issues.append(f"{lid}: non-defaulted loan must have default_mob None")
    if not _is_number(loan["income_volatility_cv"]) \
            or not (0 <= loan["income_volatility_cv"] <= 1.5):
        issues.append(f"{lid}: income_volatility_cv out of range [0, 1.5]")
    if not _is_number(loan["balance_trend_pct"]) \
            or not (-0.5 <= loan["balance_trend_pct"] <= 0.5):
        issues.append(f"{lid}: balance_trend_pct out of range [-0.5, 0.5]")
    if not _is_number(loan["avg_balance"]) or loan["avg_balance"] < 0:
        issues.append(f"{lid}: avg_balance must be >= 0")
    return issues


def validate_book(loans: List[Dict]) -> List[str]:
    issues: List[str] = []
    if not loans:
        issues.append("book is empty")
        return issues
    seen = set()
    for i, loan in enumerate(loans):
        issues.extend(validate_loan(loan, index=i))
        lid = loan.get("loan_id")
        if lid in seen:
            issues.append(f"{lid}: duplicate loan_id")
        seen.add(lid)
    return issues
