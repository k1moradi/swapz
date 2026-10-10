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


    def test_two_job_fio_file_keeps_writer_out_of_exact_reader_log(self):
        """Exercise the production-like fio INI hierarchy and separate extents."""
        fio = os.environ.get("SWAPZ_FIO_BIN", "/usr/bin/fio")
        with tempfile.TemporaryDirectory(prefix="swapz-fio-paired-") as directory:
            root = Path(directory)
            data = root / "two-job-regular-file"
            sentinel = b"SWAPZ_V22_PROBE_" * 256
            with data.open("wb") as stream:
                stream.truncate(128 * 1024)
                stream.seek(128 * 1024 - 4096)
                stream.write(sentinel)
            prefix = root / "paired-reader"
            job = root / "paired.fio"
            output = root / "paired.json"
            job.write_text(
                "[global]\n"
                "ioengine=libaio\n"
                "direct=1\n"
                "bs=4k\n"
                "time_based=1\n"
                "runtime=2\n"
                "randrepeat=1\n"
                "randseed=1517953062\n"
                "percentile_list=50:90:95:99:99.9\n"
                "\n[writer]\n"
                f"filename={data}\n"
                "rw=randwrite\n"
                "offset=64k\n"
                "size=60k\n"
                "iodepth=4\n"
                "refill_buffers=1\n"
                "buffer_compress_percentage=50\n"
                "buffer_compress_chunk=512\n"
                "\n[reader]\n"
                f"filename={data}\n"
                "rw=randread\n"
                "offset=0\n"
                "size=64k\n"
                "iodepth=1\n"
                "rate_iops=100\n"
                f"write_lat_log={prefix}\n"
                "log_avg_msec=0\n"
                "per_job_logs=0\n"
                "log_entries=4096\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                [fio, str(job), "--output-format=json", f"--output={output}"],
                capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            report = json.loads(output.read_text(encoding="utf-8"))
            jobs = {j["jobname"]: j for j in report["jobs"]}
            self.assertEqual(set(jobs), {"writer", "reader"})
            self.assertEqual(jobs["writer"]["error"], 0)
            self.assertEqual(jobs["reader"]["error"], 0)
            self.assertGreater(jobs["writer"]["write"]["total_ios"], 0)
            self.assertGreater(jobs["reader"]["read"]["total_ios"], 10)
            self.assertEqual(jobs["writer"]["read"]["total_ios"], 0)
            log = root / "paired-reader_clat.log"
            self.assertTrue(log.is_file())
            self.assertFalse((root / "paired-reader_clat.2.log").exists())
            summary = collector.collect(output, log, root / "paired.latbin")
            self.assertEqual(summary["read_count"],
                             jobs["reader"]["read"]["total_ios"])
            self.assertGreater(summary["read_p99_ns"], 0)
            # Also verify that fio's actual offset/size semantics exclude the
            # reserved final 4 KiB sentinel under the concurrent writer.
            with data.open("rb") as stream:
                stream.seek(128 * 1024 - 4096)
                self.assertEqual(stream.read(4096), sentinel)


if __name__ == "__main__":
    unittest.main(verbosity=2)
