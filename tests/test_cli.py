"""CLI: commands, exit codes 0/1/2, JSON round-trips, serve round-trips."""

import io
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from contextlib import redirect_stderr, redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cli import (EXIT_ERROR, EXIT_FAIL, EXIT_OK, load_book, main as cli_main,
                 make_server, reset_state)  # noqa: E402
from generator import generate_loans, loans_to_csv, loans_to_jsonl  # noqa: E402
from helpers import loan  # noqa: E402
from report import build_report  # noqa: E402


def run_cli(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = cli_main(argv)
    return code, out.getvalue(), err.getvalue()


class CliBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="retro-test-")
        self.seeded = os.path.join(self.tmp, "book.jsonl")
        with open(self.seeded, "w", encoding="utf-8") as fh:
            fh.write(loans_to_jsonl(generate_loans()))


class TestCommands(CliBase):
    def test_generate_to_file(self):
        out_path = os.path.join(self.tmp, "gen.jsonl")
        code, out, _ = run_cli(["generate", "--out", out_path])
        self.assertEqual(code, EXIT_OK)
        with open(out_path, encoding="utf-8") as fh:
            self.assertEqual(len(fh.read().strip().splitlines()), 2400)

    def test_generate_count_and_seed(self):
        out_path = os.path.join(self.tmp, "gen16.jsonl")
        code, _, _ = run_cli(["generate", "--count", "16", "--seed", "7",
                              "--out", out_path])
        self.assertEqual(code, EXIT_OK)
        self.assertEqual(len(load_book(out_path)), 16)

    def test_vintages_command(self):
        code, out, _ = run_cli(["vintages", "--input", self.seeded])
        self.assertEqual(code, EXIT_OK)
        payload = json.loads(out)
        self.assertEqual(payload["ranking_at_mob"][0]["vintage"], "2024-Q3")
        self.assertEqual(len(payload["vintages"]), 8)

    def test_vintages_seeded_default_no_input(self):
        code, out, _ = run_cli(["vintages"])
        self.assertEqual(code, EXIT_OK)
        self.assertEqual(json.loads(out)["mob"], 6)

    def test_model_command(self):
        code, out, _ = run_cli(["model", "--input", self.seeded])
        self.assertEqual(code, EXIT_OK)
        self.assertEqual(json.loads(out)["auc"], 0.735782)

    def test_signals_command(self):
        code, out, _ = run_cli(["signals", "--input", self.seeded])
        self.assertEqual(code, EXIT_OK)
        self.assertTrue(json.loads(out)["volatility_monotonic"])

    def test_report_json_matches_build_report(self):
        code, out, _ = run_cli(["report", "--input", self.seeded])
        self.assertEqual(code, EXIT_OK)
        self.assertEqual(json.loads(out), build_report(generate_loans()))

    def test_report_text(self):
        code, out, _ = run_cli(["report", "--input", self.seeded, "--text"])
        self.assertEqual(code, EXIT_OK)
        self.assertIn("Verdict: PASS", out)

    def test_report_out_file(self):
        out_path = os.path.join(self.tmp, "rep.json")
        code, _, _ = run_cli(["report", "--out", out_path])
        self.assertEqual(code, EXIT_OK)
        with open(out_path, encoding="utf-8") as fh:
            self.assertEqual(json.load(fh)["total_loans"], 2400)

    def test_csv_input_round_trip(self):
        csv_path = os.path.join(self.tmp, "book.csv")
        with open(csv_path, "w", encoding="utf-8") as fh:
            fh.write(loans_to_csv(generate_loans()))
        code, out, _ = run_cli(["report", "--input", csv_path])
        self.assertEqual(code, EXIT_OK)
        self.assertEqual(json.loads(out)["total_defaults"], 499)


class TestCheckExitCodes(CliBase):
    def test_check_seeded_passes(self):
        code, out, _ = run_cli(["check", "--input", self.seeded])
        self.assertEqual(code, EXIT_OK)
        self.assertIn("check PASS", out)

    def test_check_missing_file_is_error(self):
        code, _, _ = run_cli(["check", "--input", "/tmp/no-such-retro-xyz.json"])
        self.assertEqual(code, EXIT_ERROR)

    def test_check_invalid_data_is_error(self):
        path = os.path.join(self.tmp, "junk.jsonl")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write('{"loan_id": 1}\n')
        code, _, _ = run_cli(["check", "--input", path])
        self.assertEqual(code, EXIT_ERROR)

    def test_check_breach_fails(self):
        loans = ([loan(vintage="2024-Q1", risk_score=0.05) for _ in range(25)]
                 + [loan(vintage="2024-Q2", risk_score=0.05) for _ in range(25)]
                 + [loan(vintage="2025-Q3", risk_score=0.55, defaulted=True,
                         default_mob=4) for _ in range(25)]
                 + [loan(vintage="2025-Q4", risk_score=0.55, defaulted=True,
                         default_mob=4) for _ in range(25)])
        for i, ln in enumerate(loans):
            ln["loan_id"] = f"NL-B{i:04d}"
        path = os.path.join(self.tmp, "breach.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(loans, fh)
        code, out, _ = run_cli(["check", "--input", path])
        self.assertEqual(code, EXIT_FAIL)
        self.assertIn("check FAIL", out)

    def test_report_missing_file_is_error(self):
        code, _, _ = run_cli(["report", "--input", "/tmp/no-such-retro-xyz.json"])
        self.assertEqual(code, EXIT_ERROR)


class TestServe(CliBase):
    def setUp(self):
        super().setUp()
        self.loans = generate_loans()
        reset_state(self.loans)
        self.server = make_server(0)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        reset_state()

    def _req(self, path, payload=None, method="GET"):
        data = json.dumps(payload).encode() if payload is not None else None
        headers = {"Content-Type": "application/json"} if data else {}
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}", data=data,
            headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read())

    def test_health(self):
        status, body = self._req("/health")
        self.assertEqual((status, body), (200, {"status": "ok"}))

    def test_report_empty_body_is_seeded(self):
        status, body = self._req("/report", payload={}, method="POST")
        self.assertEqual(status, 200)
        self.assertEqual(body, build_report(self.loans))

    def test_report_explicit_loans(self):
        status, body = self._req("/report", payload={"loans": self.loans},
                                 method="POST")
        self.assertEqual(status, 200)
        self.assertEqual(body["total_loans"], 2400)

    def test_report_bad_loans_is_400(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._req("/report", payload={"loans": [{"loan_id": 1}]},
                      method="POST")
        self.assertEqual(ctx.exception.code, 400)

    def test_unknown_path_is_404(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._req("/nope")
        self.assertEqual(ctx.exception.code, 404)


if __name__ == "__main__":
    unittest.main()
