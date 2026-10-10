#!/usr/bin/env python3
"""Real fio CLAT-log integration against an ordinary temporary file.

No root, device nodes, DM, swap, loop, NBD, or kernel module operations.
Unlike synthetic converter fixtures, this verifies fio's generated filename,
reader JSON count, log field semantics and the production V3 converter.
"""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
CONVERTER = HERE / "streaming-benchmark-read-latency.py"
SPEC = importlib.util.spec_from_file_location("swapz_real_fio_clat", CONVERTER)
assert SPEC is not None and SPEC.loader is not None
collector = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(collector)


class RealFioReaderLogIntegration(unittest.TestCase):
    def test_unprivileged_regular_file_fio_logs_match_exact_v3_converter(self):
        fio = os.environ.get("SWAPZ_FIO_BIN", "/usr/bin/fio")
        version = subprocess.run([fio, "--version"], capture_output=True, text=True,
                                 timeout=10, check=True).stdout.strip()
        self.assertRegex(version, r"^fio-[0-9]", "not the Flexible I/O Tester")

        with tempfile.TemporaryDirectory(prefix="swapz-fio-clat-") as directory:
            root = Path(directory)
            data = root / "reader-data"
            with data.open("wb") as stream:
                stream.truncate(64 * 1024)
            prefix = root / "reader"
            output = root / "fio.json"
            result = subprocess.run([
                fio, "--name=reader", f"--filename={data}", "--ioengine=sync",
                "--direct=0", "--rw=randread", "--bs=4k", "--size=64k",
                "--time_based=1", "--runtime=2", "--rate_iops=100",
                "--log_avg_msec=0", "--per_job_logs=0", "--log_entries=4096",
                f"--write_lat_log={prefix}", "--output-format=json",
                f"--output={output}",
            ], capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            log = root / "reader_clat.log"
            self.assertTrue(log.is_file(), "fio CLAT filename differs from expected")
            self.assertFalse((root / "reader_clat.1.log").exists())
            sidecar = root / "reader.latbin"
            summary = collector.collect(output, log, sidecar)
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(report["jobs"][0]["jobname"], "reader")
            self.assertEqual(summary["read_count"], report["jobs"][0]["read"]["total_ios"])
            self.assertGreater(summary["read_count"], 10)
            self.assertGreater(summary["read_p99_ns"], 0)
            payload = sidecar.read_bytes()
            self.assertEqual(len(payload), summary["read_latency_bytes"])
            self.assertEqual(len(payload) % 16, 0)
            histogram = [struct.unpack("!QQ", payload[i:i + 16])
                         for i in range(0, len(payload), 16)]
            self.assertEqual(sum(count for _, count in histogram),
                             summary["read_count"])
            self.assertIn("NOT-independent-attestation", summary["read_latency_source"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
