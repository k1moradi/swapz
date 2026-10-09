#!/usr/bin/env python3
"""Rootless source and diagnostic checks for streaming-benchmark.sh.

Runs ONLY read-only reporting and the source's embedded JSON conversion with
fabricated fio/stat JSON. Does not invoke the actual benchmark script, device
setup, DM, NBD, fio, modules, swap or a process worker.
"""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
REPORTER_PATH = HERE / "streaming-benchmark-report.py"
BENCHMARK_PATH = HERE / "streaming-benchmark.sh"
spec = importlib.util.spec_from_file_location("swapz_streaming_report_test", REPORTER_PATH)
assert spec and spec.loader
reporter = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = reporter
spec.loader.exec_module(reporter)

MIB = 1024 * 1024


def row(*, batch=128, strategy="staged", backend="size-aware-nbd-20MiBps-500000ns-serialized"):
    return {
        "backend": backend,
        "strategy": strategy,
        "batch_kib": batch,
        "logical_write_bytes": 16 * MIB,
        "upper_write_mib_s": 123.0,
        "logical_flush_window_mib_s": 8.0,
        "lower_counter_window_mib_s": 1.0,
        "drain_window_s": 2.0,
        "lower_write_ios": 10,
        "lower_write_sectors": 4096,
        "read_count": 200,
        "read_p99_ms": 2.5,
        "read_max_ms": 3.0,
        "staged_early": 0,
        "status": {"failed": "0", "staged_hits": "10"},
    }


class StreamingReportingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="swapz-report-only-")
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.jsonl = self.directory / "fabricated.jsonl"
        self.script = BENCHMARK_PATH.read_text(encoding="utf-8")

    def write(self, rows):
        self.jsonl.write_text(
            "".join(json.dumps(item, sort_keys=True) + "\n" for item in rows),
            encoding="utf-8",
        )
        return self.jsonl

    def read(self, rows):
        return reporter.read_rows(self.write(rows))

    def test_lower_counter_rate_is_distinct_from_logical_flush_and_upper(self):
        text = reporter.report(self.read([row()]))
        self.assertIn("NO QUALIFIED WINNER", text)
        self.assertIn("PLATEAU NOT REACHED", text)
        self.assertIn("lower_counter_window=1.000MiB/s", text)
        self.assertIn("logical_flush_window=8.000MiB/s", text)
        self.assertIn("upper=123.000MiB/s", text)
        self.assertIn("read_count=200", text)

    def test_reporter_cannot_nominate_winner_even_with_three_strategies(self):
        observations = [row(strategy="immediate", batch=4),
                        row(strategy="staged", batch=128),
                        row(strategy="opportunistic", batch=128)]
        report = reporter.report(self.read(observations))
        self.assertEqual(report.count("unqualified; only one observation per batch"), 3)
        self.assertNotIn("latency_guarded=", report)
        self.assertNotIn("first_97pct=", report)

    def test_invalid_read_and_write_measurements_are_rejected(self):
        bad = [
            ("read_count", 0), ("read_count", True),
            ("read_p99_ms", -1), ("read_max_ms", -3),
            ("logical_write_bytes", 0), ("lower_write_sectors", -1),
            ("lower_write_ios", -1), ("drain_window_s", 0),
            ("drain_window_s", -1), ("upper_write_mib_s", float("inf")),
            ("batch_kib", 3), ("strategy", "unknown"),
        ]
        for key, value in bad:
            with self.subTest(key=key, value=value):
                item = row()
                item[key] = value
                with self.assertRaises(ValueError):
                    self.read([item])

    def test_underlying_sector_and_logical_rate_arithmetic_is_enforced(self):
        for key, changed in (
            ("lower_counter_window_mib_s", 8.0),
            ("logical_flush_window_mib_s", 1.0),
            ("drain_window_s", 10.0),
        ):
            with self.subTest(key=key):
                item = row()
                item[key] = changed
                with self.assertRaisesRegex(ValueError, "inconsistent"):
                    self.read([item])

    def test_failed_status_and_unsupported_immediate_batch_are_rejected(self):
        for item in (
            {**row(), "status": {"failed": "1"}},
            {**row(), "status": {}},
            {**row(), "strategy": "immediate", "batch_kib": 64},
            {**row(), "backend": "/dev/sda"},
            {**row(), "read_p99_ms": 5.0},
        ):
            with self.assertRaises(ValueError):
                self.read([item])

    def test_duplicate_batch_and_mixed_backend_rejected(self):
        first = row()
        with self.assertRaisesRegex(ValueError, "duplicate strategy/batch"):
            self.read([first, copy.deepcopy(first)])
        with self.assertRaisesRegex(ValueError, "different backend"):
            self.read([first, row(batch=256, backend="other-backend")])

    def test_missing_or_nonfinite_or_invalid_json_is_rejected(self):
        for value in (
            {k:v for k,v in row().items() if k != "lower_write_sectors"},
            {**row(), "logical_flush_window_mib_s": float("nan")},
            {**row(), "read_count": "200"},
        ):
            with self.assertRaises(ValueError):
                self.read([value])
        for value in ("", "not json\n", "\n", '{"backend":Infinity}\n'):
            with self.subTest(value=value):
                self.jsonl.write_text(value, encoding="utf-8")
                with self.assertRaises(ValueError):
                    reporter.read_rows(self.jsonl)

    def test_duplicate_json_keys_are_not_silently_accepted(self):
        payload = json.dumps(row())
        self.jsonl.write_text(payload[:-1] + ', "batch_kib": 4}\n', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "duplicate JSON"):
            reporter.read_rows(self.jsonl)

    def test_oversized_input_and_too_many_rows_rejected(self):
        self.jsonl.write_bytes(b"x" * (reporter.MAX_BYTES + 1))
        with self.assertRaisesRegex(ValueError, "oversized"):
            reporter.read_rows(self.jsonl)
        self.jsonl.write_text("{}\n" * (reporter.MAX_ROWS + 1), encoding="utf-8")
        with self.assertRaises(ValueError):
            reporter.read_rows(self.jsonl)

    def test_command_line_runs_readonly_and_returns_diagnostics(self):
        self.write([row()])
        result = subprocess.run(
            [sys.executable, "-B", str(REPORTER_PATH), "--results", str(self.jsonl)],
            capture_output=True, text=True, timeout=5, check=True
        )
        self.assertIn("NO QUALIFIED WINNER", result.stdout)
        self.assertIn("PLATEAU NOT REACHED", result.stdout)

    def test_embedded_collector_produces_counters_not_logical_drain(self):
        source = self.script
        marker = '"$start_ns" "$end_ns" "$BACKEND" >>"$RESULTS" <<\'PY\'\n'
        self.assertIn(marker, source)
        embedded = source.split(marker, 1)[1].split("\nPY\n", 1)[0]
        self.assertIn('lower_counter_window_mib_s', embedded)
        fio = self.directory / "fabricated-fio.json"
        fio.write_text(json.dumps({"jobs": [
            {"jobname": "writer", "job options": {"iodepth": "64"},
             "write": {"io_bytes": 16 * MIB, "bw_bytes": 123 * MIB,
                       "clat_ns": {"mean": 1_000_000, "max": 3_000_000,
                                   "percentile": {"99.000000": 2_000_000}}},
             "usr_cpu": 3, "sys_cpu": 5},
            {"jobname": "reader",
             "read": {"total_ios": 200,
                      "clat_ns": {"mean": 1_000_000, "max": 3_000_000,
                                  "percentile": {"95.000000": 2_000_000,
                                                 "99.000000": 2_500_000}}},
             "usr_cpu": 1, "sys_cpu": 2},
        ]}), encoding="utf-8")
        cmd = [
            sys.executable, "-c", embedded, str(fio),
            "10 1000 20 2000", "12 1016 30 6096",
            "failed=0 staged_hits=10", "staged", "128",
            "1000000000", "3000000000",
            "size-aware-nbd-20MiBps-500000ns-serialized",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5, check=True)
        parsed = json.loads(result.stdout)
        self.assertNotIn("drained_write_mib_s", parsed)
        self.assertEqual(parsed["lower_write_sectors"], 4096)
        self.assertEqual(parsed["read_count"], 200)
        self.assertAlmostEqual(parsed["logical_flush_window_mib_s"], 8)
        self.assertAlmostEqual(parsed["lower_counter_window_mib_s"], 1)
        self.assertIn("NO QUALIFIED WINNER", reporter.report(reporter.read_rows(self.write([parsed]))))

    def test_embedded_collector_rejects_counter_regression(self):
        source = self.script
        marker = '"$start_ns" "$end_ns" "$BACKEND" >>"$RESULTS" <<\'PY\'\n'
        embedded = source.split(marker, 1)[1].split("\nPY\n", 1)[0]
        fio = self.directory / "fio.json"
        fio.write_text(json.dumps({"jobs":[
            {"jobname":"writer","job options":{"iodepth":"1"},
             "write":{"io_bytes":MIB,"bw_bytes":MIB}},
            {"jobname":"reader","read":{"total_ios":20}}
        ]}), encoding="utf-8")
        args=[sys.executable,"-c",embedded,str(fio),"10 1000 20 2000",
              "10 1000 19 1900","failed=0","staged","128",
              "1000000000","3000000000","backend"]
        result=subprocess.run(args,capture_output=True,text=True,timeout=5)
        self.assertNotEqual(result.returncode,0)
        self.assertIn("counters decreased",result.stderr)

    def test_benchmark_shell_only_reports_and_does_not_nominate_from_single_run(self):
        self.assertNotIn('"drained_write_mib_s"', self.script)
        self.assertNotIn("latency_guarded", self.script)
        self.assertNotIn("first_97pct", self.script)
        self.assertNotIn("best_drain", self.script)
        self.assertIn('streaming-benchmark-report.py" --results "$RESULTS"', self.script)
        self.assertIn("time.monotonic_ns()", self.script)

    def test_unsafe_nbd_mode_fails_closed_before_any_backing_creation(self):
        source = self.script
        gate = 'if [[ "$BACKEND_KIND" == nbd ]]; then\n  echo "ERROR: NBD backend disabled:'
        self.assertIn(gate, source)
        self.assertLess(source.index(gate), source.index('TMP=$(mktemp -d'))
        self.assertNotIn('NBD_PID=$!', source)
        self.assertNotIn('kill -0 "$NBD_PID"', source)
        self.assertNotIn('kill -TERM "$NBD_PID"', source)
        teardown = (HERE / "streaming-benchmark-teardown.sh").read_text(
            encoding="utf-8")
        self.assertNotIn('kill -TERM "$NBD_PID"', teardown)
        self.assertNotIn('kill -0 "$NBD_PID"', teardown)
        self.assertIn('NBD backend teardown requires a verified pidfd-owned server',
                      teardown)

    def test_reporter_source_has_no_live_device_commands(self):
        content = REPORTER_PATH.read_text(encoding="utf-8")
        self.assertNotIn("subprocess.", content)
        self.assertNotIn('"/dev/', content)
        self.assertNotIn("os.system", content)


if __name__ == "__main__":
    unittest.main()
