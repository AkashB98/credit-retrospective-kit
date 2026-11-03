"""CLI: generate | vintages | model | signals | report | check | demo | serve.

SYNTHETIC DATA ONLY — Northstar Lending is a fictional lender and every
book handled here is fabricated sample data.

Exit codes:
  check : 0 = pass, 1 = drift / calibration threshold breach,
          2 = usage / IO / data-quality error
  others: 0 = success, 2 = usage / IO error
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from generator import generate_loans, loans_to_csv, loans_to_jsonl  # noqa: E402
from model_perf import model_report  # noqa: E402
from report import build_report, format_text_report  # noqa: E402
from signals import signal_report  # noqa: E402
from validation import validate_book  # noqa: E402
from vintage import all_vintages, rank_vintages  # noqa: E402

EXIT_OK, EXIT_FAIL, EXIT_ERROR = 0, 1, 2


def canonical(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True)


def _coerce(loan: Dict) -> Dict:
    out = dict(loan)
    for field in ("loan_amount", "apr", "dti_ratio", "risk_score",
                  "income_volatility_cv", "balance_trend_pct", "avg_balance"):
        if field in out and isinstance(out[field], str):
            try:
                out[field] = float(out[field])
            except ValueError:
                pass
    for field in ("term_months", "months_on_book", "default_mob"):
        if field in out and isinstance(out[field], str):
            if out[field] in ("", "None"):
                out[field] = None
            else:
                try:
                    out[field] = int(float(out[field]))
                except ValueError:
                    pass
        if isinstance(out.get(field), float) and out[field] is not None \
                and out[field].is_integer():
            out[field] = int(out[field])
    for field in ("defaulted", "ever_delinquent"):
        if isinstance(out.get(field), str):
            if out[field].lower() == "true":
                out[field] = True
            elif out[field].lower() == "false":
                out[field] = False
    return out


def load_book(path: str) -> List[Dict]:
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    stripped = text.strip()
    if not stripped:
        return []
    if path.endswith(".csv"):
        reader = csv.DictReader(io.StringIO(text))
        return [_coerce(dict(row)) for row in reader]
    if stripped.startswith("["):
        return [_coerce(dict(x)) for x in json.loads(stripped)]
    return [_coerce(json.loads(line)) for line in stripped.splitlines() if line.strip()]


def _load_or_error(path: Optional[str]) -> Optional[List[Dict]]:
    if path is None:
        return generate_loans()
    try:
        return load_book(path)
    except FileNotFoundError:
        print(f"error: file not found: {path}", file=sys.stderr)
    except (ValueError, OSError) as exc:
        print(f"error: cannot read {path}: {exc}", file=sys.stderr)
    return None


def cmd_generate(args) -> int:
    loans = generate_loans(count=args.count, seed=args.seed)
    fmt = args.format or ("csv" if (args.out and args.out.endswith(".csv")) else "jsonl")
    text = loans_to_csv(loans) if fmt == "csv" else loans_to_jsonl(loans)
    if args.out:
        try:
            with open(args.out, "w", encoding="utf-8") as fh:
                fh.write(text)
        except OSError as exc:
            print(f"error: cannot write {args.out}: {exc}", file=sys.stderr)
            return EXIT_ERROR
        print(f"generated {len(loans)} synthetic loans (seed={args.seed}) -> {args.out}")
    else:
        print(text, end="")
    return EXIT_OK


def cmd_vintages(args) -> int:
    loans = _load_or_error(args.input)
    if loans is None:
        return EXIT_ERROR
    print(canonical({"vintages": all_vintages(loans),
                     "ranking_at_mob": rank_vintages(loans, mob=args.mob),
                     "mob": args.mob}))
    return EXIT_OK


def cmd_model(args) -> int:
    loans = _load_or_error(args.input)
    if loans is None:
        return EXIT_ERROR
    print(canonical(model_report(loans)))
    return EXIT_OK


def cmd_signals(args) -> int:
    loans = _load_or_error(args.input)
    if loans is None:
        return EXIT_ERROR
    print(canonical(signal_report(loans)))
    return EXIT_OK


def cmd_report(args) -> int:
    loans = _load_or_error(args.input)
    if loans is None:
        return EXIT_ERROR
    report = build_report(loans)
    text = format_text_report(report) if args.text else canonical(report) + "\n"
    if args.out:
        try:
            with open(args.out, "w", encoding="utf-8") as fh:
                fh.write(text)
        except OSError as exc:
            print(f"error: cannot write {args.out}: {exc}", file=sys.stderr)
            return EXIT_ERROR
        print(f"report for {len(loans)} loans -> {args.out}")
    else:
        print(text, end="")
    return EXIT_OK


def cmd_check(args) -> int:
    loans = _load_or_error(args.input)
    if loans is None:
        return EXIT_ERROR
    issues = validate_book(loans)
    if issues:
        for issue in issues[:20]:
            print(f"data-quality: {issue}")
        print(f"check FAIL (data quality): {len(issues)} issue(s)")
        return EXIT_ERROR
    report = build_report(loans)
    print(f"loans={report['total_loans']} auc={report['model']['auc']} "
          f"psi={report['model']['psi']} "
          f"max_calibration_error={report['model']['max_calibration_error']}")
    if report["breaches"]:
        for breach in report["breaches"]:
            print(f"check FAIL: {breach}")
        return EXIT_FAIL
    print("check PASS")
    return EXIT_OK


def cmd_demo(args) -> int:
    import demo as demo_mod
    try:
        demo_mod.main()
    except AssertionError as exc:
        print(f"demo FAILED: {exc}", file=sys.stderr)
        return EXIT_FAIL
    return EXIT_OK


# ------------------------------------------------------------------- serve

class _State:
    def __init__(self):
        self.loans: List[Dict] = generate_loans()


_STATE = _State()


def get_state() -> _State:
    return _STATE


def reset_state(loans: Optional[List[Dict]] = None) -> None:
    _STATE.loans = list(loans) if loans is not None else generate_loans()


class _Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, code: int, payload: Any) -> None:
        self._send(code, (canonical(payload) + "\n").encode(), "application/json")

    def do_GET(self):  # noqa: N802
        if self.path == "/health":
            return self._send_json(200, {"status": "ok"})
        return self._send_json(404, {"error": "unknown endpoint"})

    def do_POST(self):  # noqa: N802
        if self.path != "/report":
            return self._send_json(404, {"error": "unknown endpoint"})
        length = int(self.headers.get("Content-Length", 0) or 0)
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
            if isinstance(body, dict) and "loans" in body:
                loans = [_coerce(dict(x)) for x in body["loans"]]
                issues = validate_book(loans)
                if issues:
                    return self._send_json(400, {"error": "invalid loans",
                                                 "issues": issues[:5]})
                _STATE.loans = loans
                return self._send_json(200, build_report(loans))
            if isinstance(body, dict) and not body:
                return self._send_json(200, build_report(_STATE.loans))
            raise ValueError("expected {} or {'loans': [...]}")
        except (ValueError, TypeError, KeyError) as exc:
            return self._send_json(400, {"error": f"bad request: {exc}"})

    def log_message(self, *a: Any) -> None:
        pass


def make_server(port: int) -> HTTPServer:
    return HTTPServer(("127.0.0.1", port), _Handler)


def cmd_serve(args) -> int:
    server = make_server(args.port)
    print(f"serving on http://127.0.0.1:{args.port}  (POST /report, GET /health)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="credit-retrospective-kit",
        description="Synthetic credit portfolio retrospectives (Northstar Lending).")
    sub = p.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("generate", help="generate a synthetic loan book")
    g.add_argument("--count", type=int, default=2400)
    g.add_argument("--seed", type=int, default=42)
    g.add_argument("--out", default=None)
    g.add_argument("--format", choices=["csv", "jsonl"], default=None)
    g.set_defaults(func=cmd_generate)

    for name, func, helptext in (
            ("vintages", cmd_vintages, "vintage curves + ranking"),
            ("model", cmd_model, "AUC, calibration, PSI drift"),
            ("signals", cmd_signals, "cash-flow signal deep-dive")):
        s = sub.add_parser(name, help=helptext)
        s.add_argument("--input", default=None)
        if name == "vintages":
            s.add_argument("--mob", type=int, default=6)
        s.set_defaults(func=func)

    r = sub.add_parser("report", help="full retrospective report (JSON or text)")
    r.add_argument("--input", default=None)
    r.add_argument("--out", default=None)
    r.add_argument("--text", action="store_true")
    r.set_defaults(func=cmd_report)

    c = sub.add_parser("check", help="CI gate: exit 0 pass / 1 breach / 2 error")
    c.add_argument("--input", default=None)
    c.set_defaults(func=cmd_check)

    sub.add_parser("demo", help="run the end-to-end demo").set_defaults(func=cmd_demo)

    s = sub.add_parser("serve", help="localhost JSON API: POST /report, GET /health")
    s.add_argument("--port", type=int, default=8765)
    s.set_defaults(func=cmd_serve)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
