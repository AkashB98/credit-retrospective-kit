"""Golden evals for credit-retrospective-kit.

SYNTHETIC DATA ONLY (fictional Northstar Lending). Every eval is
deterministic: run_evals.py writes eval_report.json and the file must
be byte-identical across runs. No timestamps, ports, or temp paths
enter the report — only names, booleans, pinned counts and hashes.

E1-E4 pin the seeded book and the vintage retrospective. E5-E8 pin the
model retrospective (AUC, calibration, PSI, hand-computed formulas).
E9-E10 pin the cash-flow signals. E11-E14 pin validation, the CLI
check gate, the serve round-trip, and the bundled fixture. E15-E16 are
known-answer evals: a planted drift shift must be flagged by PSI and a
planted miscalibrated score band must be caught by calibration and
breach the report verdict.
"""

from __future__ import annotations

import hashlib
import io
import json
import math
import os
import sys
import threading
import urllib.request
from contextlib import redirect_stderr, redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cli import EXIT_ERROR, EXIT_FAIL, EXIT_OK, load_book, main as cli_main, make_server, reset_state  # noqa: E402
from generator import generate_loans, loans_to_jsonl  # noqa: E402
from model_perf import (auc, calibration_by_band, max_calibration_error,  # noqa: E402
                        psi, psi_verdict)
from report import build_report, format_text_report  # noqa: E402
from signals import signal_report  # noqa: E402
from validation import validate_book  # noqa: E402
from vintage import rank_vintages  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RESULTS = []


def check(name, passed, detail=""):
    RESULTS.append({"name": name, "passed": bool(passed), "detail": detail})
    print(f"  [{'PASS' if passed else 'FAIL'}] {name}" + (f" - {detail}" if detail else ""))
    return passed


def _run_cli(argv):
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        return cli_main(argv)


def _mk(**kw):
    base = {"loan_id": "eval_x", "vintage": "2024-Q1", "loan_amount": 8000.0,
            "term_months": 36, "apr": 11.0, "credit_score_band": "good",
            "income_band": "mid", "dti_ratio": 0.30, "months_on_book": 18,
            "risk_score": 0.20, "defaulted": False, "default_mob": None,
            "ever_delinquent": False, "income_volatility_cv": 0.20,
            "balance_trend_pct": 0.0, "avg_balance": 2000.0}
    base.update(kw)
    return base


def main():
    print("== golden evals: credit-retrospective-kit ==")
    loans = generate_loans()
    report = build_report(loans)
    model = report["model"]

    # E1: generator determinism (bytes pinned)
    text1 = loans_to_jsonl(generate_loans())
    md5 = hashlib.md5(text1.encode()).hexdigest()
    check("E1 generator determinism (seed=42, jsonl md5 pinned)",
          text1 == loans_to_jsonl(loans)
          and md5 == "90e073febbfc0c583207ccdbbcd7101f",
          f"jsonl_md5={md5}")

    # E2: headline counts pinned
    check("E2 headline counts (2400 loans, 300/vintage, 499 defaults)",
          report["total_loans"] == 2400
          and report["total_defaults"] == 499
          and report["overall_default_rate"] == 0.207917
          and all(v["count"] == 300 for v in report["vintages"])
          and validate_book(loans) == [])

    # E3: vintage ranking at MOB 6 pinned
    ranking = report["vintage_ranking_at_mob"]
    check("E3 vintage ranking at MOB 6 (worst 2024-Q3 21.0%, best 2025-Q4)",
          ranking[0]["vintage"] == "2024-Q3"
          and ranking[0]["cum_default_rate_at_mob"] == 0.21
          and ranking[-1]["vintage"] == "2025-Q4"
          and ranking[-1]["cum_default_rate_at_mob"] == 0.116667,
          f"worst={ranking[0]['vintage']}@{ranking[0]['cum_default_rate_at_mob']}")

    # E4: vintage curves pinned + monotonic everywhere
    q3 = next(v for v in report["vintages"] if v["vintage"] == "2024-Q3")
    check("E4 vintage curves (2024-Q3 ends 32.0%, all curves monotonic)",
          q3["curve"] == [0.04, 0.073333, 0.12, 0.156667, 0.186667, 0.21,
                          0.25, 0.273333, 0.29, 0.303333, 0.316667, 0.32]
          and all(v["curve"] == sorted(v["curve"]) for v in report["vintages"]))

    # E5: AUC pinned + hand-computed AUC cases
    hand = auc([_mk(risk_score=0.9, defaulted=True, default_mob=2,
                    ever_delinquent=True),
                _mk(risk_score=0.4, defaulted=True, default_mob=2,
                    ever_delinquent=True),
                _mk(risk_score=0.5), _mk(risk_score=0.1)])
    check("E5 AUC pinned (0.735782) + hand case 0.75",
          model["auc"] == 0.735782 and hand == 0.75,
          f"auc={model['auc']}")

    # E6: calibration pinned (seasoned population, max error 0.032428)
    cal = {r["band"]: r for r in model["calibration"]}
    check("E6 calibration pinned (S1 obs 7.90%, S5 obs 67.44%, max err 0.032428)",
          cal["S1"]["count"] == 519 and cal["S1"]["observed"] == 0.078998
          and cal["S5"]["observed"] == 0.674419
          and model["max_calibration_error"] == 0.032428
          and model["calibration_loans"] == 1436
          and model["rank_ordered"])

    # E7: PSI pinned + formula / symmetry properties
    early = [_mk(risk_score=0.05), _mk(risk_score=0.05),
             _mk(risk_score=0.25), _mk(risk_score=0.25)]
    late = [_mk(risk_score=0.05), _mk(risk_score=0.25),
            _mk(risk_score=0.25), _mk(risk_score=0.25)]
    expected = ((0.25 - 0.5) * math.log(0.5) + (0.75 - 0.5) * math.log(1.5))
    check("E7 PSI pinned (0.009436 stable) + formula hand case",
          model["psi"] == 0.009436 and model["psi_verdict"] == "stable"
          and psi(early, late) == round(expected, 6)
          and psi(loans, loans) == 0.0,
          f"psi={model['psi']}")

    # E8: calibration hand case (band math, seasoned filter)
    rows = calibration_by_band(
        [_mk(risk_score=0.10, defaulted=True, default_mob=2, ever_delinquent=True),
         _mk(risk_score=0.10), _mk(risk_score=0.10), _mk(risk_score=0.10),
         _mk(risk_score=0.10, months_on_book=6)], min_mob=12)
    check("E8 calibration hand case (S1: n=4 seasoned, pred 0.10, obs 0.25)",
          rows[0]["count"] == 4 and rows[0]["predicted"] == 0.10
          and rows[0]["observed"] == 0.25 and rows[0]["abs_error"] == 0.15)

    # E9: cash-flow signals pinned (volatility monotonic, trend gap)
    sig = report["signals"]
    check("E9 signals pinned (vol 14.50% -> 28.47%, trend lift gap 0.610177)",
          [r["default_rate"] for r in sig["volatility_groups"]]
          == [0.144951, 0.205622, 0.284658]
          and sig["volatility_monotonic"]
          and sig["falling_vs_rising_lift_gap"] == 0.610177,
          f"gap={sig['falling_vs_rising_lift_gap']}")

    # E10: signal means pinned (defaulters lumpier income, falling balances)
    check("E10 signal means pinned (vol 0.248063 vs 0.213141, trend -0.006076)",
          sig["mean_volatility_defaulted"] == 0.248063
          and sig["mean_volatility_non_defaulted"] == 0.213141
          and sig["mean_trend_defaulted"] == -0.006076
          and sig["mean_trend_non_defaulted"] == 0.004619)

    # E11: validation flags planted defects; generated book is clean
    bad = _mk(defaulted=True, default_mob=None)
    check("E11 validation (defect flagged, seeded book clean)",
          any("default_mob" in i for i in validate_book([bad]))
          and validate_book(loans) == [])

    # E12: CLI check exit codes 0 / 1 / 2
    import tempfile
    tmp = tempfile.mkdtemp(prefix="retro-evals-")
    breach_loans = (
        [_mk(loan_id=f"e{i}", vintage="2024-Q1", risk_score=0.05) for i in range(25)]
        + [_mk(loan_id=f"f{i}", vintage="2024-Q2", risk_score=0.05) for i in range(25)]
        + [_mk(loan_id=f"g{i}", vintage="2025-Q3", risk_score=0.55,
               defaulted=True, default_mob=4, ever_delinquent=True) for i in range(25)]
        + [_mk(loan_id=f"h{i}", vintage="2025-Q4", risk_score=0.55,
               defaulted=True, default_mob=4, ever_delinquent=True) for i in range(25)])
    breach_path = os.path.join(tmp, "breach.json")
    with open(breach_path, "w", encoding="utf-8") as fh:
        json.dump(breach_loans, fh)
    codes = (_run_cli(["check"]),
             _run_cli(["check", "--input", breach_path]),
             _run_cli(["check", "--input", "/tmp/no-such-retro-xyz.json"]))
    check("E12 CLI check exit codes 0/1/2",
          codes == (EXIT_OK, EXIT_FAIL, EXIT_ERROR), f"codes={codes}")

    # E13: serve round-trip matches local report (seeded + explicit)
    reset_state(loans)
    server = make_server(0)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        def _post(payload):
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/report",
                data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read())
        serve_ok = _post({}) == report and _post({"loans": loans}) == report
    finally:
        server.shutdown()
        server.server_close()
        reset_state()
    check("E13 serve round-trip matches local report", serve_ok)

    # E14: bundled fixture pinned + text report headlines
    fixture = load_book(os.path.join(ROOT, "fixtures", "sample_book.jsonl"))
    text = format_text_report(report)
    check("E14 fixture pinned (40 loans, 5/vintage, validates clean) + text",
          len(fixture) == 40 and validate_book(fixture) == []
          and len({ln["vintage"] for ln in fixture}) == 8
          and "AUC 0.735782" in text and "Verdict: PASS" in text)

    # E15: KNOWN-ANSWER planted drift — early window scores sit in the
    # lowest deciles, late window scores are shifted ~+0.40. PSI must
    # flag it as a material shift (this is the drift the gate exists for).
    planted_early = [_mk(loan_id=f"d{i}", vintage="2024-Q1",
                         risk_score=0.05 + 0.01 * (i % 5)) for i in range(100)]
    planted_late = [_mk(loan_id=f"e{i}", vintage="2025-Q4",
                        risk_score=0.45 + 0.01 * (i % 5)) for i in range(100)]
    planted_psi = psi(planted_early, planted_late)
    check("E15 planted drift flagged (PSI > 0.25, material_shift)",
          planted_psi > 0.25 and psi_verdict(planted_psi) == "material_shift",
          f"planted_psi={planted_psi}")

    # E16: KNOWN-ANSWER planted miscalibration — band S3 claims ~37%
    # risk but 85 of 100 seasoned loans in it defaulted. Calibration
    # must name the bad band and the full report must breach on it.
    planted_bad = []
    for i in range(100):
        vintage = ["2024-Q1", "2024-Q2", "2025-Q3", "2025-Q4"][i % 4]
        defaulted = i < 85
        planted_bad.append(_mk(
            loan_id=f"m{i}", vintage=vintage, risk_score=0.37,
            defaulted=defaulted, default_mob=4 if defaulted else None,
            ever_delinquent=defaulted, months_on_book=18))
    planted_rows = calibration_by_band(planted_bad, min_mob=12)
    planted_s3 = next(r for r in planted_rows if r["band"] == "S3")
    planted_report = build_report(planted_bad)
    check("E16 planted miscalibrated band caught (S3 obs 0.85, report breaches)",
          planted_s3["observed"] == 0.85
          and planted_s3["abs_error"] > 0.20
          and max_calibration_error(planted_bad, min_mob=12) > 0.20
          and planted_report["verdict"] == "breach"
          and any("calibration" in b for b in planted_report["breaches"]),
          f"s3_abs_error={planted_s3['abs_error']}")

    passed = sum(1 for r in RESULTS if r["passed"])
    total_n = len(RESULTS)
    summary_doc = {"passed": passed, "total": total_n,
                   "all_passed": passed == total_n, "evals": RESULTS}
    with open(os.path.join(HERE, "eval_report.json"), "w", encoding="utf-8") as fh:
        fh.write(json.dumps(summary_doc, sort_keys=True) + "\n")
    print(f"\n{passed}/{total_n} evals passed -> evals/eval_report.json")
    return 0 if passed == total_n else 1


if __name__ == "__main__":
    sys.exit(main())
