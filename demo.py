"""End-to-end demo: generate -> vintages -> model -> signals -> report
-> check -> serve.

SYNTHETIC DATA ONLY (fictional Northstar Lending). Runs fully offline;
the serve round-trip is loopback-only on an ephemeral port. Every
stage asserts.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from cli import main as cli_main, make_server, reset_state  # noqa: E402
from generator import generate_loans  # noqa: E402
from model_perf import model_report  # noqa: E402
from report import build_report, format_text_report  # noqa: E402
from signals import signal_report  # noqa: E402
from validation import validate_book  # noqa: E402
from vintage import rank_vintages  # noqa: E402


def _request(port: int, path: str, payload=None, method: str = "GET"):
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"Content-Type": "application/json"} if data else {}
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}",
                                 data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.status, json.loads(resp.read())


def main() -> None:
    print("== 1. generate synthetic Northstar Lending book (seed=42) ==")
    loans = generate_loans()
    assert loans == generate_loans(), "generator must be deterministic"
    assert validate_book(loans) == [], validate_book(loans)[:3]
    vintages = sorted({ln["vintage"] for ln in loans})
    print(f"   {len(loans)} loans across {len(vintages)} vintages, clean")

    print("\n== 2. vintage retrospective ==")
    ranking = rank_vintages(loans, mob=6)
    worst, best = ranking[0], ranking[-1]
    print(f"   worst at MOB 6: {worst['vintage']} "
          f"({worst['cum_default_rate_at_mob']:.2%}); best: {best['vintage']} "
          f"({best['cum_default_rate_at_mob']:.2%})")
    assert worst["cum_default_rate_at_mob"] > best["cum_default_rate_at_mob"]
    for summary_v in build_report(loans)["vintages"]:
        curve = summary_v["curve"]
        assert curve == sorted(curve), "cumulative curves never fall"

    print("\n== 3. model retrospective ==")
    model = model_report(loans)
    print(f"   AUC {model['auc']}, max calibration error "
          f"{model['max_calibration_error']}, PSI {model['psi']} "
          f"({model['psi_verdict']})")
    assert model["auc"] > 0.65, model["auc"]
    assert model["rank_ordered"], "band default rates must rise with risk band"

    print("\n== 4. cash-flow signals ==")
    sig = signal_report(loans)
    vol = {r["group"]: r["default_rate"] for r in sig["volatility_groups"]}
    print(f"   default rate by income volatility: {vol}")
    assert sig["mean_volatility_defaulted"] > sig["mean_volatility_non_defaulted"]
    assert sig["mean_trend_defaulted"] < sig["mean_trend_non_defaulted"]

    print("\n== 5. report + check gate ==")
    report = build_report(loans)
    text = format_text_report(report)
    assert report["verdict"] == "pass" and report["breaches"] == []
    assert "Verdict: PASS" in text
    code = cli_main(["check"])
    code_err = cli_main(["check", "--input", "/tmp/no-such-retro-xyz.json"])
    print(f"   seeded check={code}, missing-file={code_err}")
    assert code == 0 and code_err == 2

    print("\n== 6. live localhost serve round-trip ==")
    reset_state(loans)
    server = make_server(0)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, health = _request(port, "/health")
        assert status == 200 and health == {"status": "ok"}
        status, served = _request(port, "/report", payload={}, method="POST")
        assert status == 200 and served == report, "empty body -> seeded book"
        status, served2 = _request(port, "/report", payload={"loans": loans},
                                   method="POST")
        assert status == 200 and served2 == report
        print("   POST /report (seeded + explicit loans) matches local report")
    finally:
        server.shutdown()
        server.server_close()
        reset_state()

    print("\nDemo OK: generate, vintages, model, signals, report, check "
          "and serve verified.")


if __name__ == "__main__":
    main()
