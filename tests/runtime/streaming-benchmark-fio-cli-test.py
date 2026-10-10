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
VERIFY_PATH = HERE / "streaming-benchmark-writer-verify.py"
VERIFY_SPEC = importlib.util.spec_from_file_location("swapz_full_writer_verify", VERIFY_PATH)
assert VERIFY_SPEC is not None and VERIFY_SPEC.loader is not None
writer_verify = importlib.util.module_from_spec(VERIFY_SPEC)
VERIFY_SPEC.loader.exec_module(writer_verify)


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
            reference = root / "sentinel-reference"
            reference.write_bytes(sentinel)
            # Exercise the live runner's exact direct-write command shape on
            # an ORDINARY FILE only; no block devices or elevated privileges.
            subprocess.run(
                ["dd", f"if={reference}", f"of={data}", "bs=4096", "count=1",
                 "seek=31", "oflag=direct", "conv=notrunc", "status=none"],
                check=True, capture_output=True, text=True, timeout=10,
            )
            # Preseed the whole writer region with checksummed 4 KiB pages
            # before the concurrent workload, mirroring the live benchmark.
            prefill = subprocess.run(
                [fio, "--name=writer-prefill", f"--filename={data}",
                 "--ioengine=libaio", "--iodepth=4", "--direct=1",
                 "--bs=4k", "--rw=write", "--offset=64k", "--size=60k",
                 "--verify=crc32c", "--do_verify=0",
                 "--refill_buffers=1", "--buffer_compress_percentage=50",
                 "--buffer_compress_chunk=512", "--output-format=json",
                 f"--output={root / 'writer-prefill.json'}"],
                capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(prefill.returncode, 0,
                             prefill.stderr + prefill.stdout)
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
                "verify=crc32c\n"
                "do_verify=0\n"
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
            # Fio must not reach the last 4 KiB; exercise the same direct
            # read and byte-for-byte comparison used by the live runner.
            readback = root / "sentinel-readback"
            subprocess.run(
                ["dd", f"if={data}", f"of={readback}", "bs=4096", "count=1",
                 "skip=31", "iflag=direct", "status=none"],
                check=True, capture_output=True, text=True, timeout=10,
            )
            self.assertEqual(readback.read_bytes(), sentinel)
            # Both fio jobs shared the same ordinary file and timing window;
            # now verify CRC/offset metadata for every writer page separately.
            verify_output = root / "paired-post-writer-verify.json"
            checked = subprocess.run(
                [fio, "--name=writer-verify", f"--filename={data}",
                 "--ioengine=libaio", "--iodepth=1", "--direct=1",
                 "--bs=4k", "--rw=read", "--offset=64k", "--size=60k",
                 "--verify=crc32c", "--output-format=json",
                 f"--output={verify_output}"],
                capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(checked.returncode, 0,
                             checked.stderr + checked.stdout)
            readback_result = writer_verify.validate(verify_output, 60 * 1024)
            self.assertEqual(readback_result["writer_verified_pages"], 15)


    def test_full_writer_range_crc32c_after_time_based_random_overwrites(self):
        """Real fio: preseed every 4K, random overwrite, sequential verify.

        Exercise ordinary files only. Also corrupt one page and prove the
        verification subprocess and JSON fail closed; never touch /dev.
        """
        fio = os.environ.get("SWAPZ_FIO_BIN", "/usr/bin/fio")
        with tempfile.TemporaryDirectory(prefix="swapz-fio-full-verify-") as directory:
            root = Path(directory)
            data = root / "writer-data"
            with data.open("wb") as stream:
                stream.truncate(128 * 1024)
            offset = 64 * 1024
            size = 60 * 1024  # 15 pages, excludes final sentinel
            def run(name, *args, expect_success=True):
                output = root / f"{name}.json"
                proc = subprocess.run(
                    [fio, f"--name={name}", f"--filename={data}", "--bs=4k",
                     "--ioengine=libaio", "--iodepth=4", "--direct=1",
                     f"--offset={offset}", f"--size={size}",
                     "--verify=crc32c", *args,
                     "--output-format=json", f"--output={output}"],
                    capture_output=True, text=True, timeout=30,
                )
                if expect_success:
                    self.assertEqual(proc.returncode, 0,
                                     proc.stdout + proc.stderr)
                else:
                    self.assertNotEqual(proc.returncode, 0,
                                        "corrupted record accepted")
                report = json.loads(output.read_text(encoding="utf-8"))
                self.assertEqual(len(report["jobs"]), 1)
                job = report["jobs"][0]
                if expect_success:
                    self.assertEqual(job["error"], 0, report)
                else:
                    self.assertNotEqual(job["error"], 0, report)
                return job

            prefill = run("prefill", "--rw=write", "--do_verify=0",
                          "--refill_buffers=1",
                          "--buffer_compress_percentage=50")
            self.assertEqual(prefill["write"]["io_bytes"], size)
            # An actual time_based random writer with checksummed payloads.
            writer = run("timed", "--rw=randwrite", "--time_based=1",
                         "--runtime=2", "--randseed=1517953062",
                         "--do_verify=0", "--refill_buffers=1",
                         "--buffer_compress_percentage=50")
            self.assertGreater(writer["write"]["total_ios"], 15)

            verify = run("writer-verify", "--rw=read")
            self.assertEqual(verify["read"]["io_bytes"], size)
            self.assertEqual(verify["read"]["total_ios"], size // 4096)
            passed = writer_verify.validate(root / "writer-verify.json", size)
            self.assertIs(passed["full_writer_readback_ok"], True)
            self.assertEqual(passed["writer_verified_bytes"], size)
            self.assertEqual(passed["writer_verified_pages"], 15)

            # One changed payload byte anywhere in the writer extent must fail.
            with data.open("r+b", buffering=0) as stream:
                stream.seek(offset + 4096 + 256)
                byte = stream.read(1)
                self.assertEqual(len(byte), 1)
                stream.seek(offset + 4096 + 256)
                stream.write(bytes([byte[0] ^ 0x01]))
            run("verify-bad", "--rw=read", expect_success=False)
            with self.assertRaisesRegex(ValueError, "job identity"):
                writer_verify.validate(root / "verify-bad.json", size)


if __name__ == "__main__":
    unittest.main(verbosity=2)
