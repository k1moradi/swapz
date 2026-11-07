#!/usr/bin/env python3
"""Owner policy: only five user-visible root Make commands."""
import importlib.util
import json
import os
import pathlib
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[3]
MAKE = (ROOT / "Makefile").read_text()

class PublicMakeContract(unittest.TestCase):
    def test_build_provenance_skips_report_only_commits(self):
        self.assertIn(
            "git log -1 --format=%H HEAD -- . "
            "':(exclude)test_results.json'",
            MAKE)

        runner_spec = importlib.util.spec_from_file_location(
            "swapz_provenance_runner", ROOT / "tests/tools/run-tests.py")
        runner_contract = importlib.util.module_from_spec(runner_spec)
        runner_spec.loader.exec_module(runner_contract)

        build_tests = ROOT / "build/tests"
        build_tests.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="report-source-sha-",
                                         dir=build_tests) as directory:
            repository = pathlib.Path(directory)
            runner_contract.ROOT = repository

            def git(*arguments):
                return subprocess.run(
                    ["git", *arguments], cwd=repository, check=True,
                    capture_output=True, text=True, timeout=5)

            git("init", "--initial-branch=main")
            git("config", "user.name", "swapz fixture")
            git("config", "user.email", "swapz-fixture@example.invalid")

            def check_make_provenance(expected_sha, expected_clean, phase):
                # Query the real Makefile without running install or sudo.
                queried = subprocess.run(
                    ["make", "-qp", "install"], cwd=repository,
                    capture_output=True, text=True, timeout=5)
                self.assertEqual(
                    queried.returncode, 1,
                    f"phase={phase} first_error=make query failed "
                    f"reason={queried.stderr.strip()}")
                for variable, expected in (
                        ("SWAPZ_BUILD_SOURCE_SHA", expected_sha),
                        ("SWAPZ_BUILD_SOURCE_CLEAN", expected_clean)):
                    self.assertRegex(
                        queried.stdout,
                        rf"(?m)^{variable} := {re.escape(expected)}$",
                        f"phase={phase} first_error={variable} mismatch "
                        "reason=unexpected generated-source contract")
                self.assertEqual(
                    runner_contract.git_sha(), expected_sha,
                    f"phase={phase} first_error=reporter source mismatch "
                    "reason=Makefile and official runner disagree")

            source = repository / "src/kernel/dm-target.c"
            source.parent.mkdir(parents=True)
            source.write_text("int source_revision = 1;\n")
            (repository / "Makefile").write_text(MAKE)
            git("add", "Makefile", "src/kernel/dm-target.c")
            git("commit", "-m", "source: synthetic candidate")
            source_sha = git("rev-parse", "HEAD").stdout.strip()
            check_make_provenance(source_sha, "1", "initial-source")

            report = repository / "test_results.json"
            report.write_text("{\"overall\":\"FAIL\"}\n")
            git("add", "test_results.json")
            git("commit", "-m",
                "test: latest run for 0123456789ab [skip ci]")
            report_head = git("rev-parse", "HEAD").stdout.strip()
            self.assertNotEqual(report_head, source_sha)

            resolved_sha = git(
                "log", "-1", "--format=%H", "HEAD", "--", ".",
                ":(exclude)test_results.json").stdout.strip()
            self.assertEqual(resolved_sha, source_sha)
            check_make_provenance(source_sha, "1", "report-only-descendant")

            source.write_text("int source_revision = 2;\n")
            check_make_provenance(source_sha, "0", "dirty-source")
            git("add", "src/kernel/dm-target.c")
            git("commit", "-m", "source: next synthetic candidate")
            next_source_sha = git("rev-parse", "HEAD").stdout.strip()
            self.assertNotEqual(next_source_sha, report_head)
            resolved_after_source_change = git(
                "log", "-1", "--format=%H", "HEAD", "--", ".",
                ":(exclude)test_results.json").stdout.strip()
            self.assertEqual(resolved_after_source_change, next_source_sha)
            check_make_provenance(next_source_sha, "1", "next-source")

    def test_exact_five_root_goals(self):
        targets = set()
        for line in MAKE.splitlines():
            if not line or line[0].isspace() or line.startswith("#") or line.startswith("."):
                continue
            m = re.match(r"^([A-Za-z][A-Za-z0-9_-]*):(?!=)", line)
            if m:
                targets.add(m.group(1))
        self.assertEqual(targets, {"all", "install", "uninstall", "test",
                                   "fast_test"})
        self.assertIn(".DEFAULT_GOAL := all", MAKE)
        self.assertIn("Only make, make install, make uninstall, make test, "
                      "make fast_test are supported", MAKE)
        self.assertNotIn("Only make -j2,", MAKE)
        self.assertNotIn("make test -j", MAKE)
        self.assertIn(".PHONY: all install uninstall test fast_test", MAKE)
        # make fast_test is a development decision loop: it never writes or
        # publishes the qualification report and never replaces make test.
        self.assertIn("@+python3 -B tests/tools/fast-test.py", MAKE)
        fast = (ROOT / "tests/tools/fast-test.py").read_text()
        for forbidden in ("test_results.json\")", "def publish", "git push",
                          "commit-tree", "SYNCED_GIT"):
            self.assertNotIn(forbidden, fast)
        self.assertIn("tests/tools/benchmark-owned-pair.sh", fast)
        self.assertIn("never replaces `make test`", fast)
        self.assertNotIn(".NOTPARALLEL: test", MAKE)
        self.assertIn(".PHONY: build/kernel/experimental/dm-swapz.ko", MAKE)
        self.assertIn("all: build/kernel/experimental/dm-swapz.ko "
                      "build/tests/device-roundtrip build/userspace/swapzctl", MAKE)
        self.assertIn("@+python3 -B tests/tools/run-tests.py --kdir", MAKE)
        reporter = (ROOT / "tests/tools/run-tests.py").read_text()
        for required in ("tests/tools/test-rootless.sh", "tests/tools/test-loaded.sh",
                         "W=1", "W=2", "test_results.json",
                         "tested_commit_sha", "commit-tree", "mktree",
                         "GIT_TERMINAL_PROMPT", "SYNCED_GIT"):
            self.assertIn(required, reporter)
        self.assertNotIn("code_commit_sha", reporter)
        self.assertNotIn('"ls-remote"', reporter)
        self.assertNotIn('env["GIT_ASKPASS"] = "false"', reporter)
        self.assertNotIn('REPORT = ROOT / "build/test_results.json"', reporter)
        self.assertIn("build/tests/device-roundtrip: tests/tools/device-roundtrip.c", MAKE)
        self.assertIn("build/tests/direct-write-probe: tests/tools/direct-write-probe.c", MAKE)
        self.assertIn("build/userspace/swapzctl: src/userspace/swapzctl.c "
                      "src/userspace/swapz-primary.c src/userspace/swapz-primary.h "
                      "src/kernel/VERSION src/kernel/authority.h src/kernel/codec.h",
                      MAKE)
        staged = (ROOT / "src/kernel/Makefile").read_text()
        self.assertIn('cmp -s "$$src" "$$dst"', staged)
        self.assertIn("build/kernel/w1", staged)
        self.assertIn("build/kernel/w2", staged)
        self.assertNotIn('@cp -f "$(CURDIR)/Makefile"', staged)
        self.assertIn("MAKECMDGOALS", MAKE)
        multi = subprocess.run(["make", "-n", "install", "uninstall"],
                               cwd=ROOT, capture_output=True, text=True, timeout=5)
        self.assertNotEqual(multi.returncode, 0)
        for forbidden in ("all", "verify", "run", "deploy", "clean", "swapz",
                          "check", "test-codec", "bench-pair-medium"):
            p = subprocess.run(["make", "-n", "--no-print-directory", forbidden],
                               cwd=ROOT, capture_output=True, text=True, timeout=5)
            self.assertNotEqual(p.returncode, 0, forbidden)


    def test_secure_boot_signing_hook_is_idempotent(self):
        helper = ROOT / "packaging/sign-module.sh"
        content = helper.read_text()
        for required in ("mokutil --sb-state", "kmodsign sha512",
                         "openssl cms -verify", "SWAPZ_MOK_PRIVATE_KEY",
                         "SWAPZ_MOK_CERT", "SWAPZ_SIGN_NONINTERACTIVE",
                         "sudo_command+=(-n)", "--verify",
                         "SWAPZ_SIGN_TEST_ROOT",
                         "kernel acceptance is not claimed",
                         "--ignore-keyring --test-key",
                         "is already enrolled"):
            self.assertIn(required, content)
        self.assertIn('bash packaging/sign-module.sh "$@"', MAKE)

        import os
        import tempfile
        build_tests = ROOT / "build/tests"
        build_tests.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="module-signing-",
                                         dir=build_tests) as directory:
            fixture = pathlib.Path(directory)
            fake_bin = fixture / "bin"
            fake_bin.mkdir()
            module = fixture / "dm-swapz.ko"
            key = fixture / "MOK.priv"
            cert = fixture / "MOK.der"
            module.write_bytes(b"module")
            key.write_text("private")
            cert.write_text("certificate")

            commands = {
                "mokutil": (
                    "#!/bin/sh\n"
                    "case \"$1\" in\n"
                    "  --sb-state) printf '%s\\n' 'SecureBoot enabled';;\n"
                    "  --ignore-keyring)\n"
                    "    [ \"$2\" = --test-key ] && [ \"$#\" = 3 ] || exit 2\n"
                    "    case \"${SWAPZ_FAKE_MOKUTIL_MODE:-enrolled-message}\" in\n"
                    "      status-zero-empty) exit 0;;\n"
                    "      status-zero-exact) printf '%s\\n' \"$3 is already enrolled\"; exit 0;;\n"
                    "      success-with-warning) printf '%s\\n' 'unrelated diagnostic'; exit 0;;\n"
                    "      enrolled-message) printf '%s\\n' \"$3 is already enrolled\"; exit 1;;\n"
                    "      enrolled-message-with-warning)\n"
                    "        printf '%s\\n' 'unrelated diagnostic' \"$3 is already enrolled\"; exit 1;;\n"
                    "      wrong-certificate) printf '%s\\n' '/other/MOK.der is already enrolled'; exit 1;;\n"
                    "      not-enrolled) printf '%s\\n' \"$3 is not enrolled\"; exit 1;;\n"
                    "      failed-with-positive-text) printf '%s\\n' \"$3 is already enrolled\"; exit 255;;\n"
                    "      *) exit 2;;\n"
                    "    esac;;\n"
                    "  *) exit 2;;\n"
                    "esac\n"
                ),
                "openssl": (
                    "#!/bin/sh\n"
                    "case \"$1\" in\n"
                    "  x509)\n"
                    "    output=''\n"
                    "    while [ \"$#\" -gt 0 ]; do\n"
                    "      if [ \"$1\" = -out ]; then output=$2; shift 2; "
                    "else shift; fi\n"
                    "    done\n"
                    "    if [ -n \"$output\" ]; then\n"
                    "      printf '%s\\n' fixture-certificate > \"$output\"\n"
                    "    else\n"
                    "      printf '%s\\n' fixture-certificate\n"
                    "    fi\n"
                    "    ;;\n"
                    "  cms)\n"
                    "    [ \"${2:-}\" = -cmsout ] &&\n"
                    "      printf '%s\\n' '    encapContentInfo:' "
                    "'      eContentType: pkcs7-data (1.2.840.113549.1.7.1)' "
                    "'      eContent: <ABSENT>'\n"
                    "    exit 0;;\n"
                    "  *) exit 2;;\n"
                    "esac\n"
                ),
                "kmodsign": (
                    "#!/bin/sh\n"
                    "module=$4\n"
                    "printf '%s\\n' call >> \"$module.calls\"\n"
                    "python3 - \"$module\" <<'PY'\n"
                    "import sys\n"
                    "from pathlib import Path\n"
                    "module = Path(sys.argv[1])\n"
                    "signature = b'fixture-signature'\n"
                    "header = bytes((0, 0, 2, 0, 0, 0, 0, 0))\n"
                    "header += len(signature).to_bytes(4, 'big')\n"
                    "with module.open('ab') as stream:\n"
                    "    stream.write(signature + header + "
                    "b'~Module signature appended~\\n')\n"
                    "PY\n"
                ),
                "sudo": "#!/bin/sh\n[ \"$1\" = -n ] && shift\nexec \"$@\"\n",
            }
            for name, script in commands.items():
                path = fake_bin / name
                path.write_text(script)
                path.chmod(0o755)

            env = os.environ.copy()
            env["PATH"] = f"{fake_bin}:{env.get('PATH', '')}"
            env["SWAPZ_MOK_PRIVATE_KEY"] = str(key)
            env["SWAPZ_MOK_CERT"] = str(cert)
            env["SWAPZ_SIGN_NONINTERACTIVE"] = "1"
            env["SWAPZ_SIGN_TEST_ROOT"] = str(fixture)
            for _ in range(2):
                proc = subprocess.run(
                    ["bash", str(helper), str(module)], env=env,
                    capture_output=True, text=True, timeout=5)
                self.assertEqual(proc.returncode, 0,
                                 proc.stdout + "\n" + proc.stderr)
            self.assertEqual((fixture / "dm-swapz.ko.calls").read_text(),
                             "call\n")

            env["SWAPZ_FAKE_MOKUTIL_MODE"] = "enrolled-message"
            verified_exact = subprocess.run(
                ["bash", str(helper), "--verify", str(module)], env=env,
                capture_output=True, text=True, timeout=5)
            self.assertEqual(verified_exact.returncode, 0,
                             verified_exact.stdout + "\n" +
                             verified_exact.stderr)

            # Supported mokutil 0.7.2 reports enrollment with status 1 and
            # this exact certificate-bound message.
            env["SWAPZ_FAKE_MOKUTIL_MODE"] = "enrolled-message"
            module.write_bytes(b"module")
            enrolled = subprocess.run(
                ["bash", str(helper), str(module)], env=env,
                capture_output=True, text=True, timeout=5)
            self.assertEqual(enrolled.returncode, 0,
                             enrolled.stdout + "\n" + enrolled.stderr)
            self.assertEqual((fixture / "dm-swapz.ko.calls").read_text(),
                             "call\ncall\n")
            verified_enrolled = subprocess.run(
                ["bash", str(helper), "--verify", str(module)], env=env,
                capture_output=True, text=True, timeout=5)
            self.assertEqual(verified_enrolled.returncode, 0,
                             verified_enrolled.stdout + "\n" +
                             verified_enrolled.stderr)

            # Newer mokutil versions use status 0 with the same exact,
            # certificate-bound positive enrollment response.
            env["SWAPZ_FAKE_MOKUTIL_MODE"] = "status-zero-exact"
            module.write_bytes(b"module")
            enrolled_status_zero = subprocess.run(
                ["bash", str(helper), str(module)], env=env,
                capture_output=True, text=True, timeout=5)
            self.assertEqual(enrolled_status_zero.returncode, 0,
                             enrolled_status_zero.stdout + "\n" +
                             enrolled_status_zero.stderr)
            self.assertEqual((fixture / "dm-swapz.ko.calls").read_text(),
                             "call\ncall\ncall\n")
            verified_status_zero = subprocess.run(
                ["bash", str(helper), "--verify", str(module)], env=env,
                capture_output=True, text=True, timeout=5)
            self.assertEqual(verified_status_zero.returncode, 0,
                             verified_status_zero.stdout + "\n" +
                             verified_status_zero.stderr)

            for mode in ("status-zero-empty",
                         "success-with-warning", "enrolled-message-with-warning",
                         "wrong-certificate", "not-enrolled",
                         "failed-with-positive-text"):
                with self.subTest(mokutil_mode=mode):
                    env["SWAPZ_FAKE_MOKUTIL_MODE"] = mode
                    module.write_bytes(b"module")
                    rejected = subprocess.run(
                        ["bash", str(helper), str(module)], env=env,
                        capture_output=True, text=True, timeout=5)
                    self.assertEqual(rejected.returncode, 2)
                    self.assertIn("not enrolled or enrollment could not be verified",
                                  rejected.stderr)
                    self.assertEqual(module.read_bytes(), b"module")
                    self.assertEqual(
                        (fixture / "dm-swapz.ko.calls").read_text(),
                        "call\ncall\ncall\n")

            env["SWAPZ_FAKE_MOKUTIL_MODE"] = "enrolled-message"
            module.write_bytes(b"module")
            unsigned = subprocess.run(
                ["bash", str(helper), "--verify", str(module)], env=env,
                capture_output=True, text=True, timeout=5)
            self.assertEqual(unsigned.returncode, 2)
            self.assertIn("qualified module is unsigned", unsigned.stderr)


    def test_secure_boot_requires_detached_real_cms(self):
        # OpenSSL can verify matching attached CMS, but the kernel rejects
        # encapsulated content in a module-signature trailer.
        if os.geteuid() == 0:
            self.skipTest("rootless signing regression requires nonroot")
        openssl = shutil.which("openssl")
        self.assertIsNotNone(openssl)
        build_tests = ROOT / "build/tests"
        build_tests.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="module-cms-detached-",
                                         dir=build_tests) as directory:
            fixture = pathlib.Path(directory)
            fake_bin = fixture / "bin"
            fake_bin.mkdir()
            mokutil = fake_bin / "mokutil"
            mokutil.write_text(
                "#!/bin/sh\n"
                "if [ \"$#\" -eq 1 ] && [ \"$1\" = --sb-state ]; then\n"
                "  printf '%s\\n' 'SecureBoot enabled'; exit 0\n"
                "fi\n"
                "if [ \"$#\" -eq 3 ] && [ \"$1\" = --ignore-keyring ] &&\n"
                "   [ \"$2\" = --test-key ]; then\n"
                "  printf '%s\\n' \"$3 is already enrolled\"; exit 1\n"
                "fi\n"
                "exit 92\n")
            mokutil.chmod(0o755)
            key = fixture / "MOK.priv"
            certificate = fixture / "MOK.pem"
            certificate_der = fixture / "MOK.der"
            payload = fixture / "module.payload"
            signature = fixture / "module.p7s"
            module = fixture / "dm-swapz.ko"
            payload_bytes = b"module bytes cryptographically covered by CMS\n"
            payload.write_bytes(payload_bytes)
            subprocess.run(
                [openssl, "req", "-x509", "-newkey", "rsa:2048", "-nodes",
                 "-keyout", str(key), "-out", str(certificate),
                 "-subj", "/CN=swapz-detached-test", "-days", "1"],
                check=True, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL)
            subprocess.run(
                [openssl, "x509", "-in", str(certificate), "-outform", "DER",
                 "-out", str(certificate_der)],
                check=True, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL)
            env = dict(
                os.environ,
                PATH=str(fake_bin) + os.pathsep + os.path.dirname(openssl) +
                     os.pathsep + "/usr/bin:/bin",
                SWAPZ_SIGN_TEST_ROOT=str(fixture),
                SWAPZ_MOK_CERT=str(certificate_der),
            )
            cases = (
                ("detached", (), True),
                ("attached", ("-nodetach",), False),
                ("wrong-content-type",
                 ("-econtent_type", "1.2.3.4.5"), False),
            )
            for case, extra_args, accepted in cases:
                with self.subTest(case=case):
                    args = [openssl, "cms", "-sign", "-binary", "-in",
                            str(payload), "-signer", str(certificate),
                            "-inkey", str(key), "-outform", "DER", "-out",
                            str(signature), "-nocerts", "-noattr", "-md",
                            "sha512"]
                    args.extend(extra_args)
                    subprocess.run(
                        args, check=True, stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL)
                    signature_bytes = signature.read_bytes()
                    header = bytes((0, 0, 2, 0, 0, 0, 0, 0))
                    header += len(signature_bytes).to_bytes(4, "big")
                    module.write_bytes(
                        payload_bytes + signature_bytes + header +
                        b"~Module signature appended~\n")
                    result = subprocess.run(
                        ["bash", str(ROOT / "packaging/sign-module.sh"),
                         "--verify", str(module)],
                        cwd=ROOT, env=env, capture_output=True,
                        text=True, timeout=10)
                    if accepted:
                        self.assertEqual(result.returncode, 0, result.stderr)
                        self.assertIn(
                            "kernel acceptance is not claimed", result.stdout)
                    else:
                        self.assertEqual(result.returncode, 2, result.stdout)
                        self.assertIn("phase=cms_verification", result.stderr)
                        self.assertIn(
                            "not a detached pkcs7-data signature",
                            result.stderr)
                        self.assertNotIn(str(key), result.stderr)
                        self.assertNotIn(str(certificate_der), result.stderr)

    def test_make_test_is_only_official_documented_test_command(self):
        canonical = ("docs/README.md", "docs/VISION.md",
                     "docs/coding_standards.md", "docs/testing_standards.md",
                     "docs/compile.md", "docs/benchmark.md")
        policy = "**Single official test command (read before every prompt):**"
        for document in canonical:
            with self.subTest(canonical=document):
                content = (ROOT / document).read_text()
                self.assertIn(policy, content)
                self.assertIn("Run `make test` at the repository root", content)
                self.assertIn("report BLOCKED (nonzero)", content)
                self.assertIn("Do not create, publish, recommend, or document "
                              "alternative test commands", content)

        readme = (ROOT / "docs/README.md").read_text()
        self.assertIn("[VISION.md](VISION.md)", readme)
        self.assertIn("[root Make API](compile.md#root-make-api)", readme)

        context = (ROOT / "docs/context.md").read_text()
        self.assertIn("**Current contracts (linked rather than restated):**",
                      context)
        self.assertIn("[VISION.md](VISION.md)", context)
        self.assertIn("sole official qualification\ninterface `make test`",
                      context)

        testing = (ROOT / "docs/testing_standards.md").read_text()
        self.assertIn("~~~sh\nmake test\n~~~", testing)
        operator_docs = ("docs/README.md", "docs/testing_standards.md")
        for document in operator_docs:
            with self.subTest(official=document):
                content = (ROOT / document).read_text()
                for forbidden in ("make test-codec", "make test-mapping",
                                  "make test-gc", "make test-lower-io",
                                  "make -C tests/suites test-all",
                                  "sudo bash tests/tools/deploy-nullblk.sh",
                                  "sudo bash tests/tools/benchmark-owned-pair.sh"):
                    self.assertNotIn(forbidden, content,
                                     f"Nonofficial test instruction in {document}")
        self.assertIn("tests/tools/test-rootless.sh", (ROOT / "tests/tools/run-tests.py").read_text())
        self.assertIn("tests/tools/test-loaded.sh", (ROOT / "tests/tools/run-tests.py").read_text())

    def test_primary_lifecycle_standards_match_no_vm_disposable_target_goal(self):
        testing = " ".join((ROOT / "docs/testing_standards.md").read_text().split())
        coding = (ROOT / "docs/coding_standards.md").read_text()
        self.assertIn("VM coverage is not required", testing)
        self.assertIn("deterministic fault injection on an owned RAM-backed `null_blk`",
                      testing)
        self.assertIn("safely bounded physical-host recovery and swap checks",
                      testing)
        self.assertIn("An original-header backup is optional", coding)
        self.assertNotIn("isolated VM coverage must", testing)
        self.assertNotIn("VM gates", testing)
        self.assertNotIn("must bind the exact partition identity, original-header backup",
                         testing)

    def test_parallel_build_is_incremental_and_test_stages_stay_ordered(self):
        """Run the REAL root/extent Makefiles using a fake, unprivileged Kbuild.

        No module is inserted, no system files are changed, and all fake
        outputs remain inside build/. Re-running the full public command
        must not recompile byte-identical inputs.
        """
        import os
        import tempfile
        import time

        build_tests = ROOT / "build/tests"
        build_tests.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="make-incremental-",
                                         dir=build_tests) as directory:
            fixture = pathlib.Path(directory)
            for part in ("src/kernel", "src/userspace", "tests/tools",
                         "packaging", "fake-headers"):
                (fixture / part).mkdir(parents=True, exist_ok=True)

            (fixture / "Makefile").write_text(MAKE)
            # The separate signing-hook regression exercises the real helper
            # with hermetic command mocks. Keep this Makefile fixture inert so
            # it cannot read the host MOK or invoke a privileged signer.
            (fixture / "packaging/sign-module.sh").write_text(
                "#!/bin/sh\n"
                "set -eu\n"
                "[ \"$#\" -eq 1 ] &&\n"
                "[ \"$1\" = build/kernel/experimental/dm-swapz.ko ] || exit 2\n"
                "printf 'call\\n' >> \"${SWAPZ_SIGNING_TEST_LOG:?}\"\n")
            (fixture / "src/kernel/Makefile").write_text(
                (ROOT / "src/kernel/Makefile").read_text())
            (fixture / "src/kernel/VERSION").write_text(
                (ROOT / "src/kernel/VERSION").read_text())
            (fixture / "src/kernel/superblock.h").write_text(
                (ROOT / "src/kernel/superblock.h").read_text())
            # swapz-primary.c shares the kernel authority integer-width
            # contract, so the isolated build must stage that exact header
            # and its codec type dependency rather than a test-side stub.
            (fixture / "src/kernel/authority.h").write_text(
                (ROOT / "src/kernel/authority.h").read_text())
            (fixture / "src/kernel/codec.h").write_text(
                (ROOT / "src/kernel/codec.h").read_text())
            (fixture / "src/kernel/swapz-build-info.h").write_text(
                (ROOT / "src/kernel/swapz-build-info.h").read_text())
            kernel_source = fixture / "src/kernel/dm-target.c"
            kernel_source.write_text("int fake_kernel_source = 1;\n")
            (fixture / "src/kernel/dummy.h").write_text(
                "#define FAKE_KERNEL_SOURCE 1\n")
            (fixture / "tests/tools/device-roundtrip.c").write_text(
                "int main(void) { return 0; }\n")
            (fixture / "tests/tools/direct-write-probe.c").write_text(
                "int main(void) { return 0; }\n")
            (fixture / "tests/tools/direct-read-probe.c").write_text(
                "int main(void) { return 0; }\n")
            cli = fixture / "src/userspace/swapzctl.c"
            cli.write_text("int main(void) { return 0; }\n")
            (fixture / "src/userspace/swapz-primary.c").write_text(
                (ROOT / "src/userspace/swapz-primary.c").read_text())
            (fixture / "src/userspace/swapz-primary.h").write_text(
                (ROOT / "src/userspace/swapz-primary.h").read_text())

            # This Kbuild substitute checks the staged source but
            # never compiles, loads, or inserts any kernel module.
            (fixture / "fake-headers/Makefile").write_text(
                ".PHONY: modules\n"
                "modules:\n"
                "\t@printf 'kbuild:%s\\n' '$(W)' >> '$(M)/../../order.log'\n"
                "\t@cat '$(M)/dm-target.c' '$(M)/authority.h' "
                "'$(M)/swapz-build-info.h' '$(M)/swapz-version.h' "
                "> '$(M)/.module-candidate'\n"
                "\t@if ! cmp -s '$(M)/.module-candidate' '$(M)/dm-swapz.ko'; "
                "then cp '$(M)/.module-candidate' '$(M)/dm-swapz.ko'; fi\n"
                "\t@rm -f '$(M)/.module-candidate'\n")
            (fixture / "tests/tools/run-tests.py").write_text(
                (ROOT / "tests/tools/run-tests.py").read_text())
            runner_path = fixture / "tests/tools/run-tests.py"
            runner_source = runner_path.read_text()
            runner_entrypoint = '\nif __name__ == "__main__":\n'
            self.assertEqual(runner_source.count(runner_entrypoint), 1)
            fixture_identity = (
                "\n# Deterministic identity for the isolated Make-interface fixture.\n"
                "def report_host_identity():\n"
                "    return {\"schema\": \"swapz-host-v1\", "
                "\"architecture\": \"fixture\", "
                "\"id_sha256\": \"a\" * 64}\n\n"
                "def refresh_history(host_identity):\n"
                "    return \"NOT UPDATED: isolated Make-interface fixture\"\n")
            runner_path.write_text(runner_source.replace(
                runner_entrypoint,
                fixture_identity + runner_entrypoint, 1))
            # The reporter imports the shared per-device-class goal module.
            (fixture / "tests/tools/product_goals.py").write_text(
                (ROOT / "tests/tools/product_goals.py").read_text())
            (fixture / "tests/tools/test-rootless.sh").write_text(
                "#!/bin/bash\n"
                "set -eu\n"
                "test -f build/kernel/experimental/dm-swapz.ko\n"
                "test -x build/tests/device-roundtrip\n"
                "test -x build/userspace/swapzctl\n"
                "printf '%s\\n' 'SWAPZ_PREDICTOR_EVIDENCE={\"scope\":\"OFFLINE_NATIVE_ONLY_NOT_KERNEL_POLICY\",\"negative_pages\":256,\"structured_pages\":320,\"classifier\":{\"candidate\":\"delta64\",\"backend\":\"scalar\",\"sample_pairs\":32,\"stage1_pairs\":8,\"stage1_min_score\":2,\"eligible_pages\":461,\"early_abort_pages\":120,\"benchmark_repeats\":256,\"benchmark_calls\":118016,\"ns_per_page\":55,\"scalar_ns_per_page\":55},\"lz4_acceleration_sweep\":[{\"acceleration\":1,\"wall_ns_per_page\":100,\"accepted_payload_bytes\":1000,\"raw_pages\":0,\"planner_blocks\":10,\"planner_extents\":8},{\"acceleration\":2,\"wall_ns_per_page\":90,\"accepted_payload_bytes\":1000,\"raw_pages\":0,\"planner_blocks\":10,\"planner_extents\":8},{\"acceleration\":3,\"wall_ns_per_page\":80,\"accepted_payload_bytes\":1000,\"raw_pages\":0,\"planner_blocks\":10,\"planner_extents\":8},{\"acceleration\":4,\"wall_ns_per_page\":70,\"accepted_payload_bytes\":1000,\"raw_pages\":0,\"planner_blocks\":10,\"planner_extents\":8}],\"sampling_controls\":[{\"name\":\"repeated_512b_headers\",\"score\":32,\"minimum_score\":24},{\"name\":\"lane1_only_signal\",\"score\":32,\"minimum_score\":16}],\"backend_benchmarks\":[{\"name\":\"scalar\",\"transform_ns_per_page\":700,\"inverse_ns_per_page\":650},{\"name\":\"sse2\",\"transform_ns_per_page\":430,\"inverse_ns_per_page\":550}],\"sse2_forward_ab\":{\"scope\":\"SAME_HOST_NATIVE_BASELINE_VS_PROMOTED_PRODUCTION\",\"pages\":576,\"repeats_per_arm\":64,\"pairs\":[{\"order\":\"baseline_first\",\"baseline_ns_per_page\":300,\"unrolled_ns_per_page\":287},{\"order\":\"unrolled_first\",\"baseline_ns_per_page\":301,\"unrolled_ns_per_page\":288},{\"order\":\"baseline_first\",\"baseline_ns_per_page\":302,\"unrolled_ns_per_page\":289},{\"order\":\"unrolled_first\",\"baseline_ns_per_page\":303,\"unrolled_ns_per_page\":290},{\"order\":\"baseline_first\",\"baseline_ns_per_page\":304,\"unrolled_ns_per_page\":291}]},\"io_model_block_ns\":{\"sd_emulated\":390625,\"ssd_emulated\":48828},\"thresholds\":[{\"threshold\":4,\"negative_eligible\":141,\"negative_calls\":0,\"negative_useful\":0,\"structured_eligible\":320,\"structured_calls\":256,\"structured_useful\":256,\"routed_baseline_blocks\":200,\"routed_candidate_blocks\":165,\"routed_blocks_saved\":35,\"routed_baseline_extents\":100,\"routed_candidate_extents\":85,\"routed_extents_saved\":15,\"routed_cpu_ns_total\":2500000,\"routed_cpu_ns_per_page\":4340,\"ns_per_saved_block\":71428,\"negative_profiles\":[{\"name\":\"zero\",\"pages\":32,\"eligible\":0,\"calls\":0,\"useful\":0},{\"name\":\"repeat\",\"pages\":32,\"eligible\":0,\"calls\":0,\"useful\":0},{\"name\":\"entropy\",\"pages\":64,\"eligible\":64,\"calls\":0,\"useful\":0},{\"name\":\"mixed\",\"pages\":64,\"eligible\":13,\"calls\":0,\"useful\":0},{\"name\":\"medium\",\"pages\":64,\"eligible\":64,\"calls\":0,\"useful\":0}]},{\"threshold\":8,\"negative_eligible\":141,\"negative_calls\":0,\"negative_useful\":0,\"structured_eligible\":320,\"structured_calls\":256,\"structured_useful\":256,\"routed_baseline_blocks\":200,\"routed_candidate_blocks\":165,\"routed_blocks_saved\":35,\"routed_baseline_extents\":100,\"routed_candidate_extents\":85,\"routed_extents_saved\":15,\"routed_cpu_ns_total\":2500000,\"routed_cpu_ns_per_page\":4340,\"ns_per_saved_block\":71428,\"negative_profiles\":[{\"name\":\"zero\",\"pages\":32,\"eligible\":0,\"calls\":0,\"useful\":0},{\"name\":\"repeat\",\"pages\":32,\"eligible\":0,\"calls\":0,\"useful\":0},{\"name\":\"entropy\",\"pages\":64,\"eligible\":64,\"calls\":0,\"useful\":0},{\"name\":\"mixed\",\"pages\":64,\"eligible\":13,\"calls\":0,\"useful\":0},{\"name\":\"medium\",\"pages\":64,\"eligible\":64,\"calls\":0,\"useful\":0}]},{\"threshold\":16,\"negative_eligible\":141,\"negative_calls\":0,\"negative_useful\":0,\"structured_eligible\":320,\"structured_calls\":256,\"structured_useful\":256,\"routed_baseline_blocks\":200,\"routed_candidate_blocks\":165,\"routed_blocks_saved\":35,\"routed_baseline_extents\":100,\"routed_candidate_extents\":85,\"routed_extents_saved\":15,\"routed_cpu_ns_total\":2500000,\"routed_cpu_ns_per_page\":4340,\"ns_per_saved_block\":71428,\"negative_profiles\":[{\"name\":\"zero\",\"pages\":32,\"eligible\":0,\"calls\":0,\"useful\":0},{\"name\":\"repeat\",\"pages\":32,\"eligible\":0,\"calls\":0,\"useful\":0},{\"name\":\"entropy\",\"pages\":64,\"eligible\":64,\"calls\":0,\"useful\":0},{\"name\":\"mixed\",\"pages\":64,\"eligible\":13,\"calls\":0,\"useful\":0},{\"name\":\"medium\",\"pages\":64,\"eligible\":64,\"calls\":0,\"useful\":0}]},{\"threshold\":24,\"negative_eligible\":141,\"negative_calls\":0,\"negative_useful\":0,\"structured_eligible\":320,\"structured_calls\":256,\"structured_useful\":256,\"routed_baseline_blocks\":200,\"routed_candidate_blocks\":165,\"routed_blocks_saved\":35,\"routed_baseline_extents\":100,\"routed_candidate_extents\":85,\"routed_extents_saved\":15,\"routed_cpu_ns_total\":2500000,\"routed_cpu_ns_per_page\":4340,\"ns_per_saved_block\":71428,\"negative_profiles\":[{\"name\":\"zero\",\"pages\":32,\"eligible\":0,\"calls\":0,\"useful\":0},{\"name\":\"repeat\",\"pages\":32,\"eligible\":0,\"calls\":0,\"useful\":0},{\"name\":\"entropy\",\"pages\":64,\"eligible\":64,\"calls\":0,\"useful\":0},{\"name\":\"mixed\",\"pages\":64,\"eligible\":13,\"calls\":0,\"useful\":0},{\"name\":\"medium\",\"pages\":64,\"eligible\":64,\"calls\":0,\"useful\":0}]},{\"threshold\":32,\"negative_eligible\":141,\"negative_calls\":0,\"negative_useful\":0,\"structured_eligible\":320,\"structured_calls\":256,\"structured_useful\":256,\"routed_baseline_blocks\":200,\"routed_candidate_blocks\":165,\"routed_blocks_saved\":35,\"routed_baseline_extents\":100,\"routed_candidate_extents\":85,\"routed_extents_saved\":15,\"routed_cpu_ns_total\":2500000,\"routed_cpu_ns_per_page\":4340,\"ns_per_saved_block\":71428,\"negative_profiles\":[{\"name\":\"zero\",\"pages\":32,\"eligible\":0,\"calls\":0,\"useful\":0},{\"name\":\"repeat\",\"pages\":32,\"eligible\":0,\"calls\":0,\"useful\":0},{\"name\":\"entropy\",\"pages\":64,\"eligible\":64,\"calls\":0,\"useful\":0},{\"name\":\"mixed\",\"pages\":64,\"eligible\":13,\"calls\":0,\"useful\":0},{\"name\":\"medium\",\"pages\":64,\"eligible\":64,\"calls\":0,\"useful\":0}]}],\"transforms\":[{\"name\":\"delta64\",\"adopted\":77,\"raw_rescued\":17,\"cliff_2024\":27,\"saved_payload_bytes\":97000,\"baseline_blocks\":200,\"candidate_blocks\":163,\"planner_blocks_saved\":37,\"baseline_extents\":100,\"candidate_extents\":83,\"planner_extents_saved\":17,\"transform_backend\":\"sse2\",\"inverse_backend\":\"sse2\",\"transform_ns_per_page\":1300,\"inverse_ns_per_page\":1200,\"scalar_transform_ns_per_page\":1500,\"scalar_inverse_ns_per_page\":1400,\"second_lz4_ns_per_page\":5300}],\"production_route\":{\"scope\":\"OFFLINE_NATIVE_ONLY_NOT_KERNEL_POLICY\",\"general_threshold\":24,\"packing_threshold\":16,\"eligible_pages\":461,\"packing_eligible_pages\":20,\"classifier_passes\":100,\"candidate_attempts\":100,\"adopted_pages\":80,\"raw_rescues\":20,\"lz4_rescues\":60,\"packing_adoptions\":10,\"payload_bytes_saved\":10000,\"baseline_blocks\":400,\"candidate_blocks\":350,\"blocks_saved\":50,\"baseline_extents\":200,\"candidate_extents\":180,\"extents_saved\":20,\"modeled_wall_ns_total\":2500000,\"modeled_wall_ns_per_page\":4340,\"ns_per_saved_block\":50000}}'\n"
                "printf '%s\\n' 'SWAPZ_GC_SCAN_SCALE_EVIDENCE={\"scope\":\"OFFLINE_NATIVE_GC_SCALE_ONLY\",\"rows\":[{\"logical_pages\":262144,\"segments\":1024,\"legacy_score_scan_ns\":2000000,\"incremental_select_ns\":20000,\"relocation_scan_ns\":800000,\"relocation_list_ns\":4000,\"legacy_dead_probe_ns\":700000,\"mapped_dead_probe_ns\":12000,\"victim_records\":256},{\"logical_pages\":1048576,\"segments\":4096,\"legacy_score_scan_ns\":8000000,\"incremental_select_ns\":80000,\"relocation_scan_ns\":3200000,\"relocation_list_ns\":4500,\"legacy_dead_probe_ns\":2800000,\"mapped_dead_probe_ns\":15000,\"victim_records\":256}]}'\n"
                "printf '%s\\n' 'SWAPZ_EXTENT_GEOMETRY_EVIDENCE={\"scope\":\"OFFLINE_NATIVE_GEOMETRY_ONLY_NOT_FORMAT_POLICY\",\"logical_pages\":1024,\"normal_windows\":64,\"rows\":[{\"name\":\"aligned_1_2_4\",\"physical_blocks\":320,\"waste_blocks\":24,\"write_runs\":80,\"cold_read_blocks_x1000\":1800,\"seq_4m_requests\":1500},{\"name\":\"packed_1_2_4\",\"physical_blocks\":320,\"waste_blocks\":4,\"write_runs\":60,\"cold_read_blocks_x1000\":1800,\"seq_4m_requests\":1500},{\"name\":\"packed_1_2_3_4\",\"physical_blocks\":300,\"waste_blocks\":3,\"write_runs\":55,\"cold_read_blocks_x1000\":1750,\"seq_4m_requests\":1450},{\"name\":\"packed_1_2_4_8\",\"physical_blocks\":292,\"waste_blocks\":2,\"write_runs\":48,\"cold_read_blocks_x1000\":1900,\"seq_4m_requests\":1300},{\"name\":\"packed_1_2_4_8_16\",\"physical_blocks\":288,\"waste_blocks\":1,\"write_runs\":44,\"cold_read_blocks_x1000\":2150,\"seq_4m_requests\":1200}]}'\n"
                "printf 'rootless\\n' >> build/order.log\n")
            # Keep this synthetic native marker aligned with the four
            # production GC-scaling geometries checked by the reporter.
            gc_scale_fixture = {
                "scope": "OFFLINE_NATIVE_GC_SCALE_ONLY",
                "rows": [
                    {"logical_pages": 262144, "segments": 1024,
                     "legacy_score_scan_ns": 2000000,
                     "incremental_select_ns": 20000,
                     "relocation_scan_ns": 800000,
                     "relocation_list_ns": 4000,
                     "legacy_dead_probe_ns": 700000,
                     "mapped_dead_probe_ns": 12000,
                     "victim_records": 256},
                    {"logical_pages": 1048576, "segments": 4096,
                     "legacy_score_scan_ns": 8000000,
                     "incremental_select_ns": 80000,
                     "relocation_scan_ns": 3200000,
                     "relocation_list_ns": 4500,
                     "legacy_dead_probe_ns": 2800000,
                     "mapped_dead_probe_ns": 15000,
                     "victim_records": 256},
                    {"logical_pages": 4194304, "segments": 16384,
                     "legacy_score_scan_ns": 32000000,
                     "incremental_select_ns": 320000,
                     "relocation_scan_ns": 12800000,
                     "relocation_list_ns": 4600,
                     "legacy_dead_probe_ns": 11200000,
                     "mapped_dead_probe_ns": 60000,
                     "victim_records": 256},
                    {"logical_pages": 27080192, "segments": 105782,
                     "legacy_score_scan_ns": 200000000,
                     "incremental_select_ns": 2000000,
                     "relocation_scan_ns": 80000000,
                     "relocation_list_ns": 5000,
                     "legacy_dead_probe_ns": 70000000,
                     "mapped_dead_probe_ns": 100000,
                     "victim_records": 256},
                ],
            }
            rootless_script = fixture / "tests/tools/test-rootless.sh"
            script_lines = [
                line for line in rootless_script.read_text().splitlines()
                if "SWAPZ_GC_SCAN_SCALE_EVIDENCE=" not in line
            ]
            marker_index = script_lines.index(
                "printf 'rootless\\n' >> build/order.log")
            marker = (
                "printf '%s\\n' 'SWAPZ_GC_SCAN_SCALE_EVIDENCE=" +
                json.dumps(gc_scale_fixture, separators=(",", ":")) + "'")
            script_lines.insert(marker_index, marker)
            rootless_script.write_text("\n".join(script_lines) + "\n")
            # Synthetic records mirror the modeled RAM-only session schemas;
            # mock Kbuild / loaded phase never touch actual host devices.
            # This is STILL an unprivileged mock. The loaded fixture replaces
            # this marker with its own committed source SHA at execution time.
            runner_spec = importlib.util.spec_from_file_location(
                "swapz_fixture_runner", ROOT / "tests/tools/run-tests.py")
            runner_contract = importlib.util.module_from_spec(runner_spec)
            runner_spec.loader.exec_module(runner_contract)
            mocked_source_sha = "SWAPZ_FIXTURE_SOURCE_SHA"

            def mock_kernel_write(mode, target):
                record = {field: 0 for field in runner_contract.KERNEL_WRITE_FIELDS}
                record.update({
                    "physical_write_reqs": 5,
                    "lz4_acceleration": 1,
                    "delta64_rescue": runner_contract.PRODUCTION_DELTA64_RESCUE,
                    "delta64_lz4_acceleration":
                        runner_contract.PRODUCTION_DELTA64_LZ4_ACCELERATION,
                    "delta64_prepare_workers": 1,
                    "write_pipeline_depth": 1,
                    "pipeline_active_max": 1 if mode else 0,
                    "read_coalesce_max_blocks": 8,
                    "work_conserving_hand_records":
                        runner_contract.PRODUCTION_WORK_CONSERVING_HAND_RECORDS,
                    "lz4_wall_ns": 20000000,
                    "ordered_lz4_wall_ns": 15000000,
                    "prep_lz4_wall_ns": 5000000,
                    "write_copy_wall_ns": 3000000,
                    "write_copy_bytes": 6000000,
                    "ordered_write_copy_wall_ns": 2000000,
                    "prep_write_copy_wall_ns": 1000000,
                    "direct_lz4_input_pages": 3000,
                    "window_sort_wall_ns": 1000000,
                    "window_commit_wall_ns": 40000000,
                    "window_commit_nonio_wall_ns": 10000000,
                    "engine_plan_wall_ns": 1000000,
                    "engine_pack_wall_ns": 2000000,
                    "engine_publish_wall_ns": 3000000,
                    "engine_publish_crc_wall_ns": 1000000,
                    "engine_publish_auth_wall_ns": 2000000,
                    "engine_prehashed_records": 2500,
                    "batch_snapshot_crc_wall_ns": 250000,
                    "batch_pause_crc_wall_ns": 100000,
                    "batch_resume_crc_wall_ns": 150000,
                    "prep_crc_wall_ns": 700000,
                    "ordered_crc_wall_ns": 1300000,
                    "lower_write_wall_ns": 30000000,
                    "ordered_worker_wall_ns": 52000000,
                    "prep_worker_wall_ns": 5000000,
                    "ordered_worker_cpu_ns": 16000000,
                    "prep_worker_cpu_ns": 3000000,
                    "read_worker_cpu_ns": 1000000,
                    "prep_wait_wall_ns": 500000,
                    "prep_lower_write_overlap_ns": 5000000,
                    "prep_lower_write_samples": 5,
                    "prep_lower_write_start_queued": 4,
                    "prep_lower_write_start_nonempty": 3,
                    "prep_lower_write_end_queued": 1,
                    "prep_lower_write_end_nonempty": 1,
                    "pipeline_async_runs": 4 if mode else 0,
                    "pipeline_active_wall_ns": 800000000 if mode else 0,
                    "pipeline_finalize_wait_wall_ns": 5000000 if mode else 0,
                    "k1_ready_wait_windows": 2 if mode else 0,
                    "k1_ready_wait_records": 12 if mode else 0,
                    "k1_ready_wait_wall_ns": 4000000 if mode else 0,
                    "k1_ready_wait_max_records": 8 if mode else 0,
                    "k1_ready_wait_pack_ready": 2 if mode else 0,
                    "write_wait_le1ms": 2,
                    "write_wait_1to4ms": 2,
                    "write_wait_gt4ms": 1,
                    "retained_burst_target": target,
                    "windows": 20,
                    "one_page_windows": 4,
                    "win1": 4,
                    "win3_4": 8,
                    "win5_8": 8,
                    "close_idle": 4,
                    "close_deadline": 2,
                    "close_pack_ready": 14,
                    "pack_close_tail_target": 5,
                    "pack_close_tail_target_le4": 4,
                    "pack_close_burst_target": 6,
                    "pack_close_service_dry": 3,
                    "pack_close_burst_admission": 4,
                    "pack_close_burst_worker": 2,
                    "pack_close_burst_target_le4": 2,
                    "pack_close_burst_target_5_8": 4,
                    "pack_close_burst_count_le4": 1,
                    "pack_close_burst_count_5_8": 5,
                    "pack_close_burst_overshoot": 1,
                    "win1_idle": 1,
                    "win1_deadline": 2,
                    "win1_pack_ready": 1,
                    "win1_pack_tail_target": 1,
                    "win1_pack_read_bypass": 0,
                    "win1_pack_wave_interrupted": 0,
                    "single_tail_deferrals": 0,
                    "single_tail_companions": 0,
                    "win1_deadline_deferred_tail": 0,
                    "win1_idle_deferred_tail": 0,
                    "single_tail_other_clears": 0,
                    "deadline_before_bio": 1,
                    "deadline_worker_empty": 1,
                    "packed_early_commits": 8,
                    "single_pack_deferrals": 24,
                    "accepted_burst_extensions": 6,
                    "accepted_burst_tail_flushes": 5,
                    "accepted_burst_read_caps": 4,
                    "prep_lower_write_overlap_starts": 42 if mode else 0,
                    "prep_wave_kicks": 5 if mode else 0,
                    "prep_producer_head_claims": 2 if mode else 0,
                    "prep_producer_tail_claims": 3 if mode else 0,
                    "prep_ordered_inline": 4 if mode else 0,
                    "prep_ordered_handoffs": 3 if mode else 0,
                    "prep_ordered_waits": 1 if mode else 0,
                })
                return record

            def mock_lower_inflight(has_reads):
                read_mean = 0.25 if has_reads else 0.0
                return {
                    "target_interval_ns": 500000,
                    "samples": 4000,
                    "read_start": 0, "write_start": 0,
                    "read_end": 0, "write_end": 0,
                    "read_peak": 1 if has_reads else 0,
                    "write_peak": 1, "total_peak": 1,
                    "read_time_weighted": read_mean,
                    "write_time_weighted": 0.5,
                    "total_time_weighted": read_mean + 0.5,
                }

            def mock_opportunity():
                return {
                    "scope": "TRACE_FIXTURE_OPPORTUNITY_ONLY_NOT_KERNEL_SAVINGS",
                    "measured_write_ops": 100,
                    "measured_unique_write_payloads": 20,
                    "nonzero_same_filled_write_ops": 5,
                    "same_page_rewrite_ops": 7,
                    "resident_duplicate_write_ops": 30,
                    "final_live_unique_payloads": 18,
                    "final_live_duplicate_pages": 40,
                    "final_live_nonzero_same_filled_pages": 3,
                }

            def mock_arm(candidate, mode):
                is_swapz = candidate == "swapz"
                return json.dumps({
                    "candidate": candidate, "verdict": "PASS",
                    "source_sha": mocked_source_sha,
                    "fixture_sha256": "fake-fixture",
                    "trace_sha256": "fake-trace", "verified_pages": 1024,
                    "read_p95_ns": 4000000 if is_swapz else 8000000,
                    "read_p99_ns": 5000000 if is_swapz else 10000000,
                    "write_p99_ns": 3000000,
                    "seconds": 2,
                    "mixed_replay_cpu_user_s": 0.12,
                    "mixed_replay_cpu_system_s": 0.08,
                    "mixed_replay_peak_rss_kb": 10000,
                    "host_cpu": {
                        "status": "AVAILABLE", "wall_ns": 2_000_000_000,
                        "online_cpus": 4, "affinity_cpus": 4, "tick_hz": 100,
                        "busy_fraction": 0.50, "steal_fraction": 0.0,
                        "pressure_some_fraction": 0.10,
                    },
                    "lower_inflight": mock_lower_inflight(True),
                    "workload_opportunity": mock_opportunity(),
                    "kernel_write_path": (
                        mock_kernel_write(mode, 8) if is_swapz else None),
                    "packed_read": {
                        "logical_bytes": 4194304,
                        "logical_image_sha256": "m" * 64,
                        "packed_close_delta": 7 if is_swapz else None,
                        "passes": {
                            key: {
                                "logical_bytes": 4194304,
                                "verified_pages": 1024,
                                "verified_image_sha256": "m" * 64,
                                "seconds": 0.6 if is_swapz else 1.,
                                "useful_read_mbps": 7. if is_swapz else 4.,
                                "read_p99_ms": 3. if is_swapz else 4.,
                                "lower_io": {
                                    "lower_read_bytes": 4194304,
                                    "lower_read_requests": 1024,
                                },
                                # Mirror the loaded schema; rootless only
                                # fabricates counters for runner plumbing.
                                "kernel_read_path": ({
                                    "read_meta_reqs": 1024,
                                    "read_payload_reqs": 512,
                                    "read_payload_blocks": 512,
                                    "lower_read_wall_ns": 120000000,
                                    "decode_wall_ns": 20000000,
                                    "read_copy_wall_ns": 4000000,
                                    "read_copy_bytes": 4194304,
                                    "read_engine_nonio_wall_ns": 6000000,
                                    "read_meta_cache_hits": 128,
                    "read_meta_lru_hits": 100,
                    "read_meta_set_lookups": 1024,
                    "read_meta_set_hits": 100,
                    "read_meta_primary_hits": 80,
                    "read_meta_secondary_hits": 20,
                    "read_meta_set_probes": 7700,
                    "read_meta_set_replacements": 12,
                    "read_meta_copy_bytes": 207200,
                    "read_full_extent_reqs": 200,
                    "read_full_cache_hits": 64,
                    "read_two_block_skips": 128,
                    "parallel_read_pairs": 128,
                    "parallel_read_same_extent_pairs": 64,
                    "parallel_read_async_batches": 32,
                    "parallel_read_async_slots": 64,
                    "parallel_read_distinct_extent_pairs": 64,
                    "parallel_read_adjacent_extent_pairs": 24,
                    "parallel_read_adjacent_extent_blocks": 144,
                    "parallel_read_adjacent_chain_3plus": 0,
                    "parallel_read_adjacent_chain_extent_max": 0,
                    "parallel_read_adjacent_chain_blocks_max": 0,
                    "parallel_read_coalesced_pairs": 20,
                    "parallel_read_coalesced_reqs_saved": 20,
                    "parallel_read_coalesced_blocks": 80,
                    "parallel_read_coalesce_extra_blocks": 0,
                    "parallel_read_coalesce_skip_cached": 1,
                    "parallel_read_coalesce_skip_noncontig_slot": 2,
                    "parallel_read_coalesce_skip_gap": 1,
                    "parallel_read_coalesce_skip_other": 0,
                    "read_worker_cpu_ns": 1000000,
                    "read_coalesce_max_blocks": 8,
                                } if is_swapz else None),
                            }
                            for key in ("sequential", "seeded_random")
                        },
                    },
                    "throughput_mbps": {
                        "logical_write_mbps": 20 if is_swapz else 14,
                        "lower_write_mbps": 12 if is_swapz else 14,
                        "logical_read_mbps": 6 if is_swapz else 4,
                        "logical_read_bytes": 4000,
                        "logical_write_bytes": 8000,
                    },
                    "lower_io": {
                        "lower_write_bytes": 5000 if is_swapz else 8000,
                        "lower_read_bytes": 4000,
                        "lower_write_requests": 5 if is_swapz else 8,
                        "lower_read_requests": 4
                    }
                }, sort_keys=True)
            def mock_parallel_arm(enabled, sd=False):
                record = json.loads(mock_arm("swapz", 0))
                for phase in record["packed_read"]["passes"].values():
                    kernel = phase["kernel_read_path"]
                    if sd:
                        kernel["read_worker_cpu_ns"] = 0
                    if not enabled:
                        for field in (
                                "parallel_read_pairs",
                                "parallel_read_same_extent_pairs",
                                "parallel_read_distinct_extent_pairs",
                                "parallel_read_adjacent_extent_pairs",
                                "parallel_read_adjacent_extent_blocks"):
                            kernel[field] = 0
                    for field in (
                            "parallel_read_coalesced_pairs",
                            "parallel_read_coalesced_reqs_saved",
                            "parallel_read_coalesced_blocks",
                            "parallel_read_coalesce_extra_blocks",
                            "parallel_read_coalesce_skip_cached",
                            "parallel_read_coalesce_skip_noncontig_slot",
                            "parallel_read_coalesce_skip_gap",
                            "parallel_read_coalesce_skip_other"):
                        kernel[field] = 0
                return json.dumps(record, sort_keys=True)

            def mock_fanout_arm(enabled):
                record = json.loads(mock_parallel_arm(enabled))
                coalesce_fields = (
                    "parallel_read_adjacent_extent_pairs",
                    "parallel_read_adjacent_extent_blocks",
                    "parallel_read_adjacent_chain_3plus",
                    "parallel_read_adjacent_chain_extent_max",
                    "parallel_read_adjacent_chain_blocks_max",
                    "parallel_read_coalesced_pairs",
                    "parallel_read_coalesced_reqs_saved",
                    "parallel_read_coalesced_blocks",
                    "parallel_read_coalesce_extra_blocks",
                    "parallel_read_coalesce_skip_cached",
                    "parallel_read_coalesce_skip_noncontig_slot",
                    "parallel_read_coalesce_skip_gap",
                    "parallel_read_coalesce_skip_other",
                )
                for phase in record["packed_read"]["passes"].values():
                    kernel = phase["kernel_read_path"]
                    for field in coalesce_fields:
                        kernel[field] = 0
                    if not enabled:
                        kernel["parallel_read_async_batches"] = 0
                        kernel["parallel_read_async_slots"] = 0
                mixed = dict(
                    record["packed_read"]["passes"]["sequential"]
                    ["kernel_read_path"])
                if enabled:
                    mixed["parallel_read_async_batches"] = 48
                    mixed["parallel_read_async_slots"] = 144
                    record["throughput_mbps"]["logical_write_mbps"] = 21
                    record["throughput_mbps"]["logical_read_mbps"] = 7
                    record["read_p99_ns"] = 4_000_000
                    record["lower_io"]["lower_read_requests"] = 3
                else:
                    mixed["parallel_read_async_batches"] = 0
                    mixed["parallel_read_async_slots"] = 0
                record["kernel_read_path"] = mixed
                return json.dumps(record, sort_keys=True)

            def mock_coalesce_arm(enabled, sd=False):
                record = json.loads(mock_parallel_arm(enabled, sd=sd))
                for key, phase in record["packed_read"]["passes"].items():
                    kernel = phase["kernel_read_path"]
                    if enabled:
                        kernel["parallel_read_coalesced_pairs"] = (
                            20 if key == "sequential" else 2)
                        kernel["parallel_read_coalesced_reqs_saved"] = (
                            kernel["parallel_read_coalesced_pairs"])
                        kernel["parallel_read_coalesced_blocks"] = (
                            80 if key == "sequential" else 8)
                        if key == "sequential":
                            kernel["parallel_read_coalesce_skip_cached"] = 1
                            kernel["parallel_read_coalesce_skip_noncontig_slot"] = 2
                            kernel["parallel_read_coalesce_skip_gap"] = 1
                        else:
                            kernel["parallel_read_coalesce_skip_cached"] = 8
                            kernel["parallel_read_coalesce_skip_noncontig_slot"] = 10
                            kernel["parallel_read_coalesce_skip_gap"] = 4
                        phase["lower_io"]["lower_read_requests"] -= (
                            kernel["parallel_read_coalesced_reqs_saved"])
                        phase["read_p99_ms"] *= .95
                return json.dumps(record, sort_keys=True)

            def mock_write_arm(candidate, qd, mode):
                is_swapz = candidate == "swapz"
                logical = 4096 * 4096
                lower = int(logical / 1.4) if is_swapz else logical
                return json.dumps({
                    "candidate": candidate, "verdict": "PASS",
                    "source_sha": mocked_source_sha,
                    "fixture_sha256": "fake-fixture",
                    "trace_sha256": ("f" * 60) + f"{qd:04x}",
                    "replay_mode": "persistent-write",
                    "write_p99_ns": 3000000,
                    "seconds": 2,
                    "mixed_replay_cpu_user_s": 0.12,
                    "mixed_replay_cpu_system_s": 0.08,
                    "mixed_replay_peak_rss_kb": 10000,
                    "host_cpu": {
                        "status": "AVAILABLE", "wall_ns": 2_000_000_000,
                        "online_cpus": 4, "affinity_cpus": 4, "tick_hz": 100,
                        "busy_fraction": 0.50, "steal_fraction": 0.0,
                        "pressure_some_fraction": 0.10,
                    },
                    "lower_inflight": mock_lower_inflight(False),
                    "kernel_write_path": (
                        mock_kernel_write(mode, max(4, qd))
                        if is_swapz else None),
                    "throughput_mbps": {
                        "logical_write_mbps": 20 if is_swapz else 14,
                        "lower_write_mbps": 12 if is_swapz else 14,
                        "logical_read_mbps": 0,
                        "logical_read_bytes": 0,
                        "logical_write_bytes": logical,
                    },
                    "lower_io": {
                        "lower_write_bytes": lower,
                        "lower_read_bytes": 0,
                        "lower_write_requests": 5 if is_swapz else 8,
                        "lower_read_requests": 0,
                    },
                }, sort_keys=True)

            def mock_lz4_acceleration_arm(candidate, acceleration):
                record = json.loads(mock_arm(candidate, 1))
                record["fixture_sha256"] = "b" * 64
                record["trace_sha256"] = "c" * 64
                if candidate == "swapz":
                    # Retired ordinary-LZ4 A/B keeps the production delta64
                    # stack enabled; only ordinary LZ4 acceleration varies.
                    record["kernel_write_path"]["delta64_rescue"] = (
                        runner_contract.PRODUCTION_DELTA64_RESCUE)
                    record["kernel_write_path"]["lz4_acceleration"] = acceleration
                return json.dumps(record, sort_keys=True)

            def mock_delta64_arm(workers):
                record = json.loads(mock_write_arm("swapz", 32, 1))
                kernel = record["kernel_write_path"]
                kernel.update({
                    "delta64_rescue": 1,
                    "delta64_prepare_workers": workers,
                    "delta64_prepare_active_max": workers,
                    "delta64_prepare_pages": 100,
                    "delta64_prepare_parallel_starts": 0 if workers == 1 else 20,
                    "delta64_eligible": 100,
                    "delta64_classifier_pass": 100,
                    "delta64_attempts": 100,
                    "delta64_adopted": 100,
                    "delta64_raw_rescues": 0,
                    "delta64_lz4_rescues": 100,
                    "delta64_pack_eligible": 0,
                    "delta64_pack_attempts": 0,
                    "delta64_pack_cliff_crossings": 0,
                    "delta64_pack_adopted": 0,
                    "delta64_score_0_7": 0,
                    "delta64_score_8_15": 0,
                    "delta64_score_16_23": 0,
                    "delta64_score_ge24": 100,
                    "delta64_payload_bytes_saved": 100000,
                    "delta64_raw_payload_bytes_saved": 0,
                    "delta64_lz4_payload_bytes_saved": 100000,
                    "delta64_transform_calls": 100,
                    "delta64_transform_wall_ns": 100000,
                    "delta64_wall_ns": 1500000,
                })
                record["throughput_mbps"]["logical_write_mbps"] = 18 + workers
                record["fixture_sha256"] = "e" * 64
                record["trace_sha256"] = "f" * 64
                return json.dumps(record, sort_keys=True)

            def mock_write_pipeline_arm(depth):
                record = json.loads(mock_write_arm("swapz", 32, 1))
                kernel = record["kernel_write_path"]
                kernel["delta64_rescue"] = (
                    runner_contract.PRODUCTION_DELTA64_RESCUE)
                kernel["write_pipeline_depth"] = depth
                kernel["pipeline_active_max"] = depth
                if depth == 2:
                    record["throughput_mbps"]["logical_write_mbps"] = 22.0
                    record["write_p99_ns"] = 2700000
                    record["lower_io"]["lower_write_requests"] = 4
                record["fixture_sha256"] = "7" * 64
                record["trace_sha256"] = "8" * 64
                return json.dumps(record, sort_keys=True)

            def mock_k1_read_bypass_arm(allow):
                record = json.loads(mock_arm("swapz", 1))
                kernel = record["kernel_write_path"]
                kernel["k1_allow_after_read_bypass"] = allow
                kernel["read_coalesce_max_blocks"] = 8
                kernel["invalidate_cache_on_write_admit"] = 0
                kernel["pipeline_read_bypass_skips"] = 4 if not allow else 0
                record["fixture_sha256"] = "1" * 64
                record["trace_sha256"] = "2" * 64
                return json.dumps(record, sort_keys=True)

            def mock_read_coalesce_cap_arm(cap, sd=False):
                record = json.loads(mock_coalesce_arm(True, sd=sd))
                for phase in record["packed_read"]["passes"].values():
                    phase["kernel_read_path"]["read_coalesce_max_blocks"] = cap
                record["fixture_sha256"] = "3" * 64
                record["trace_sha256"] = "4" * 64
                return json.dumps(record, sort_keys=True)

            records = [
                "PASS_LOADED_CONSTRUCTOR_FAILURE_CLEANUP=stages:8 lower_io_delta:0",
                "PASS_LOADED_MAXIMUM_CAPACITY=logical_pages:3727616 logical_bytes:15268315136 lower_bytes:17178820608 physical_blocks:4194048 segments:16383 initial_mapper_read_bytes:4096 constructor_lower_io_delta:0 boundary_pages:2 boundary_page_bytes:4096 boundary_lower_read_bytes:8192 boundary_lower_write_bytes:8192",
                "PASS_LOADED_GC_ROLL_FORWARD_RECOVERY=foreground_writes:768 fault_nth:769 injected:1 retry_attempts:2 roll_forwards:1 destination_advances:0 reserve_initial:2 reserve_current:2 relocated_pages:510 verified_pages:512",
                "PASS_LOADED_RAW_READ_FANOUT=profiles:2 verified_pages:2048 async_batches:64 lower_read_reqs:512",
                "PASS_LOADED_ORACLE_PROFILE=raw_pages:64 zero_pages:9 flush_calls:2",
                "PASS_LOADED_DELTA64_POSITIVE=pages:128 classifier_pass:128 adopted:128",
                "PASS_LOADED_LIVE_GC=victims:12 rotations:12 pages:12 read_bytes:49152 write_bytes:49152 read_reqs:12 write_reqs:12 distinct:6 victim_min:1 victim_max:3 last:11->29 discards:12 discard_sectors:24576 discard_unsupported:0 discard_failed:0 verified_pages:4096",
                "PASS_LOADED_GC_PRESSURE=rounds:5 write_wall_ns:1000000000 baseline_p99_ns:1000000 pressure_p99_ns:5000000 gc_wall_ns:200000000 gc_fraction_ppm:200000 choose_wall_ns:20000000 choose_calls:12 choose_map_entries:0 choose_segment_entries:768 relocation_map_entries:12 no_headroom_skips:3 alignment_hole_fg:4 alignment_hole_gc:1 tail_waste_fg:4 tail_waste_gc:1 run_splits_by_hole:0 alloc_probe_segments:1024 alloc_probe_full_scans:16 alloc_probe_wall_ns:50000 trim_skipped:6 segment_program_min:0 segment_program_sum:80 segment_program_max:4 segment_program_segments:32",
                "PASS_LOADED_DISCARD_TRIM=pages:256 immediate_discards:1 immediate_sectors:2048 reuse_skips:1 verified_pages:4096",
                "PASS_LOADED_PACKED_PLACEMENT=enabled:1 verified_pages:128 holes:0 run_splits:0 failed:0",
                "PASS_LOADED_SUSPEND_DRAIN=retain_ms:64 observed_open:1 verified_pages:128",
                "PASS_LOADED_COMPLETION_HANDOFF=offloaded:4 verified_pages:128 completed_writes:16512 active_after:0 fault_offloaded:2 fault_injected:1 post_failure_eio:1",
                "PASS_RETAINED_SYNTHETIC_WRITE_FAULT=retain_ms:2 injected:1 syscall_errno:EIO lower_write_delta:0",
                "PASS_LOADED_SYNTHETIC_READ_FAULT=page:3072 injected:1 syscall_errno:EIO lower_read_delta:0 submitted_delta:0",
                "PASS_RETAINED_SYNTHETIC_FLUSH_FAULT=retain_ms:2 injected:1 data_write_reached_lower:1",
                "PASS_LOADED_CODEC_ERROR_PATHS=owners:3 injected:3 inline_lower_write_delta:0 submitter_lower_write_delta:0 background_error_completions:1",
                "PASS_ID36_RESOURCE_PRESSURE=memory_high_events:8 memory_peak_bytes:734003200 cpu_some_usec:250000 cpu_workers:8 pressure_mib:576 oom:0 oom_kill:0",
                "PASS_LOADED_PRIMARY_NULLBLK_LIFECYCLE=run_id:0123456789abcdef0123456789abcdef partuuid:7fb9401d-04 device:8:4 prepare:READY start:ACTIVE swapon:true stop:COMPLETE recovery_required:false",
                "PASS_LOADED_PRIMARY_NULLBLK_INTERRUPTION=start-starting",
                "PASS_LOADED_PRIMARY_NULLBLK_INTERRUPTION=start-header-written",
                "PASS_LOADED_PRIMARY_NULLBLK_INTERRUPTION=start-module-inserted",
                "PASS_LOADED_PRIMARY_NULLBLK_INTERRUPTION=start-module-loaded",
                "PASS_LOADED_PRIMARY_NULLBLK_INTERRUPTION=start-mapper-inactive",
                "PASS_LOADED_PRIMARY_NULLBLK_INTERRUPTION=start-mapper-resumed",
                "PASS_LOADED_PRIMARY_NULLBLK_INTERRUPTION=start-mkswap",
                "PASS_LOADED_PRIMARY_NULLBLK_INTERRUPTION=start-swapon",
                "PASS_LOADED_PRIMARY_NULLBLK_INTERRUPTION=stop-stopping",
                "PASS_LOADED_PRIMARY_NULLBLK_INTERRUPTION=stop-swapoff",
                "PASS_LOADED_PRIMARY_NULLBLK_INTERRUPTION=stop-mapper-removed",
                "PASS_LOADED_PRIMARY_NULLBLK_INTERRUPTION=stop-module-unloaded",
                "PASS_LOADED_PRIMARY_NULLBLK_INTERRUPTION=stop-restored",
                "PASS_LOADED_PRIMARY_NULLBLK_INTERRUPTION=recover-recovering",
                "PASS_LOADED_PRIMARY_NULLBLK_INTERRUPTION=recover-swapoff",
                "PASS_LOADED_PRIMARY_NULLBLK_INTERRUPTION=recover-mapper-removed",
                "PASS_LOADED_PRIMARY_NULLBLK_INTERRUPTION=recover-module-unloaded",
                "PASS_LOADED_PRIMARY_NULLBLK_INTERRUPTION=recover-restored",
                "PASS_LOADED_PRIMARY_NULLBLK_INTERRUPTION_RECOVERY=cases:18 fresh_process:true host_swap_identity:preserved repeat_recovery:safe",
                "PASS_LOADED_PRIMARY_NULLBLK_NEGATIVE_RECOVERY=cases:13 ambiguous_syscall:true inventory_failure:true definite_io_error:true wrong_mapper:true failed_swapoff:true stale_run:true fsync_failure:true lost_provenance:true repeat_recovery:safe host_swap_identity:preserved",
            ]
            specs = (("sd_emulated", 10, 1000000, 2, 2, 1, 1),
                     ("ssd_emulated", 80, 150000, 2, 2, 1, 64))
            confirmation = (0, 1, 1, 0, 0, 1, 1, 0, 0, 1)
            for regime, cap, ns, irq, queue_mode, submit_queues, hw_depth in specs:
                records.append(f"START_OWNED_RAM_REGIME={regime}")
                modes = confirmation if regime == "ssd_emulated" else (0, 1, 1, 0)
                for i, mode in enumerate(modes):
                    records.extend((
                        f"START_OWNED_RAM_PAIR_ASYNC_PREPARE={mode}",
                        "REPLAY_ORDER=swapz-first" if i % 2 else "REPLAY_ORDER=off-first",
                        f"PASS_RAM_MODEL_LOWER_MBPS={cap} COMPLETION_NSEC={ns} IRQMODE={irq} QUEUE_MODE={queue_mode} SUBMIT_QUEUES={submit_queues} HW_QUEUE_DEPTH={hw_depth}",
                        "SWAPZ_STATUS_BEFORE=windows=0 close_unknown=0 close_full=0 close_duplicate=0 close_zero=0 close_fua=0 close_raw=0 close_read_conflict=0 close_read_unrelated=0 close_discard=0 close_preflush=0 close_quantum=0 close_idle=0 close_shutdown=0 close_other=0 close_deadline=0 close_pack_ready=0 burst_tail_flushes=0 packed_early_commits=0 single_pack_deferrals=0 accepted_burst_extensions=0 accepted_burst_tail_flushes=0 accepted_burst_read_caps=0 accepted_burst_cap_extra_blocks=0 accepted_burst_cap_extra_gt1_windows=0 accepted_burst_four_extents_avoided=0 accepted_burst_plan_stats_failures=0 accepted_burst_cap3_pareto_candidates=0 accepted_burst_cap3_recovered_blocks=0 accepted_burst_cap3_full_recovery_windows=0 one_page_windows=0 gc_victims=0 gc_role_rotations=0 win1_unknown=0 win1_full=0 win1_duplicate=0 win1_zero=0 win1_fua=0 win1_raw=0 win1_read_conflict=0 win1_read_unrelated=0 win1_discard=0 win1_preflush=0 win1_quantum=0 win1_idle=0 win1_shutdown=0 win1_other=0 win1_deadline=0 win1_pack_ready=0 win1_pack_tail_target=0 win1_pack_read_bypass=0 win1_pack_wave_interrupted=0 single_tail_deferrals=0 single_tail_companions=0 win1_deadline_deferred_tail=0 win1_idle_deferred_tail=0 single_tail_other_clears=0 deadline_before_bio=0 deadline_after_read=0 deadline_worker_with_local=0 deadline_worker_empty=0 prep_producer_head_claims=0 prep_producer_tail_claims=0 prep_ordered_inline=0 prep_ordered_handoffs=0 prep_ordered_waits=0 prep_lower_write_overlap_starts=0 prep_wave_kicks=0",
                        f"SWAPZ_STATUS_AFTER=windows=20 close_unknown=0 close_full=0 close_duplicate=0 close_zero=0 close_fua=0 close_raw=0 close_read_conflict=0 close_read_unrelated=0 close_discard=0 close_preflush=0 close_quantum=0 close_idle=0 close_shutdown=0 close_other=0 close_deadline=2 close_pack_ready=18 burst_tail_flushes=7 packed_early_commits=8 single_pack_deferrals=24 accepted_burst_extensions=6 accepted_burst_tail_flushes=5 accepted_burst_read_caps=4 accepted_burst_cap_extra_blocks=4 accepted_burst_cap_extra_gt1_windows=1 accepted_burst_four_extents_avoided=8 accepted_burst_plan_stats_failures=0 accepted_burst_cap3_pareto_candidates=1 accepted_burst_cap3_recovered_blocks=2 accepted_burst_cap3_full_recovery_windows=1 one_page_windows=4 gc_victims=0 gc_role_rotations=0 win1_unknown=0 win1_full=0 win1_duplicate=0 win1_zero=0 win1_fua=0 win1_raw=0 win1_read_conflict=0 win1_read_unrelated=1 win1_discard=0 win1_preflush=0 win1_quantum=0 win1_idle=0 win1_shutdown=0 win1_other=0 win1_deadline=2 win1_pack_ready=1 win1_pack_tail_target=1 win1_pack_read_bypass=0 win1_pack_wave_interrupted=0 single_tail_deferrals=0 single_tail_companions=0 win1_deadline_deferred_tail=0 win1_idle_deferred_tail=0 single_tail_other_clears=0 deadline_before_bio=1 deadline_after_read=0 deadline_worker_with_local=0 deadline_worker_empty=1 prep_producer_head_claims={2 if mode else 0} prep_producer_tail_claims={3 if mode else 0} prep_ordered_inline={4 if mode else 0} prep_ordered_handoffs={3 if mode else 0} prep_ordered_waits={1 if mode else 0} prep_lower_write_overlap_starts={42 if mode else 0} prep_wave_kicks={5 if mode else 0}",
                        mock_arm("swapz", mode) if i % 2 else mock_arm("off", mode),
                        mock_arm("off", mode) if i % 2 else mock_arm("swapz", mode),
                        f"PASS_OWNED_RAM_PAIR_ASYNC_PREPARE={mode}",
                    ))
                records.append(f"PASS_OWNED_RAM_REGIME={regime}")
            for envelope in runner_contract.STORAGE_ENVELOPE_ORDER:
                env_spec = runner_contract.STORAGE_ENVELOPE_SPECS[envelope]
                off = json.loads(mock_write_arm("off", 32, 0))
                off["fixture_sha256"] = "b" * 64
                off["trace_sha256"] = "c" * 64
                off["replay_engine"] = "native-c"
                swapz = json.loads(mock_write_arm("swapz", 32, 0))
                swapz["fixture_sha256"] = "b" * 64
                swapz["trace_sha256"] = "c" * 64
                swapz["replay_engine"] = "native-c"
                swapz["kernel_write_path"]["pipeline_post_lower_wall_ns"] = 1000
                swapz["kernel_write_path"]["pipeline_active_wall_ns"] = 5000
                records.extend((
                    f"START_STORAGE_ENVELOPE={envelope}",
                    "REPLAY_ORDER=off-first",
                    f"PASS_RAM_MODEL_LOWER_MBPS={env_spec['cap_mib_s']} "
                    f"COMPLETION_NSEC={env_spec['completion_nsec']} "
                    f"IRQMODE={env_spec['irqmode']} "
                    f"QUEUE_MODE={env_spec['queue_mode']} "
                    f"SUBMIT_QUEUES={env_spec['submit_queues']} "
                    f"HW_QUEUE_DEPTH={env_spec['hw_queue_depth']}",
                    json.dumps(off, sort_keys=True),
                    json.dumps(swapz, sort_keys=True),
                    f"PASS_STORAGE_ENVELOPE={envelope}",
                ))
            lz4_sequence = [
                4 if bit else 1 for bit in runner_contract.CONFIRMATION_SEQUENCE]
            for index, acceleration in enumerate(lz4_sequence):
                records.extend((
                    f"START_LZ4_ACCELERATION={acceleration}",
                    "REPLAY_ORDER=swapz-first" if index % 2 else
                    "REPLAY_ORDER=off-first",
                    "PASS_RAM_MODEL_LOWER_MBPS=80 COMPLETION_NSEC=150000 "
                    "IRQMODE=2 QUEUE_MODE=2 SUBMIT_QUEUES=1 "
                    "HW_QUEUE_DEPTH=64",
                    mock_lz4_acceleration_arm(
                        "swapz" if index % 2 else "off", acceleration),
                    mock_lz4_acceleration_arm(
                        "off" if index % 2 else "swapz", acceleration),
                    f"PASS_LZ4_ACCELERATION={acceleration}",
                ))
            for index, enabled in enumerate(confirmation):
                records.extend((
                    f"START_READ_COALESCE_AB={enabled}",
                    "REPLAY_ORDER=swapz-first" if index % 2 else "REPLAY_ORDER=off-first",
                    f"PASS_RAM_MODEL_LOWER_MBPS={cap} COMPLETION_NSEC={ns} IRQMODE={irq} QUEUE_MODE={queue_mode} SUBMIT_QUEUES={submit_queues} HW_QUEUE_DEPTH={hw_depth}",
                    mock_coalesce_arm(enabled) if index % 2 else mock_arm("off", 0),
                    mock_arm("off", 0) if index % 2 else mock_coalesce_arm(enabled),
                    f"PASS_READ_COALESCE_AB={enabled}",
                ))
            cap, ns, irq, queue_mode, submit_queues, hw_depth = (10, 1000000, 2, 2, 1, 1)
            for index, enabled in enumerate(confirmation):
                records.extend((
                    f"START_SD_READ_COALESCE_AB={enabled}",
                    "REPLAY_ORDER=swapz-first" if index % 2 else "REPLAY_ORDER=off-first",
                    f"PASS_RAM_MODEL_LOWER_MBPS={cap} COMPLETION_NSEC={ns} IRQMODE={irq} QUEUE_MODE={queue_mode} SUBMIT_QUEUES={submit_queues} HW_QUEUE_DEPTH={hw_depth}",
                    mock_coalesce_arm(enabled, sd=True) if index % 2 else mock_arm("off", 0),
                    mock_arm("off", 0) if index % 2 else mock_coalesce_arm(enabled, sd=True),
                    f"PASS_SD_READ_COALESCE_AB={enabled}",
                ))
            cap, ns, irq, queue_mode, submit_queues, hw_depth = (
                80, 150000, 2, 2, 1, 64)
            for index, enabled in enumerate(confirmation):
                records.extend((
                    f"START_PARALLEL_READ_AB={enabled}",
                    "REPLAY_ORDER=swapz-first" if index % 2 else
                    "REPLAY_ORDER=off-first",
                    f"PASS_RAM_MODEL_LOWER_MBPS={cap} COMPLETION_NSEC={ns} "
                    f"IRQMODE={irq} QUEUE_MODE={queue_mode} "
                    f"SUBMIT_QUEUES={submit_queues} "
                    f"HW_QUEUE_DEPTH={hw_depth}",
                    mock_fanout_arm(enabled) if index % 2 else
                    mock_arm("off", 0),
                    mock_arm("off", 0) if index % 2 else
                    mock_fanout_arm(enabled),
                    f"PASS_PARALLEL_READ_AB={enabled}",
                ))
            for regime, cap, ns, irq, queue_mode, submit_queues, hw_depth in specs:
                for index, allow in enumerate(confirmation):
                    records.extend((
                        f"START_K1_READ_BYPASS_AB={regime}:{allow}",
                        "REPLAY_ORDER=swapz-first" if index % 2 else
                        "REPLAY_ORDER=off-first",
                        f"PASS_RAM_MODEL_LOWER_MBPS={cap} COMPLETION_NSEC={ns} "
                        f"IRQMODE={irq} QUEUE_MODE={queue_mode} "
                        f"SUBMIT_QUEUES={submit_queues} "
                        f"HW_QUEUE_DEPTH={hw_depth}",
                        mock_k1_read_bypass_arm(allow) if index % 2 else
                        mock_arm("off", 1),
                        mock_arm("off", 1) if index % 2 else
                        mock_k1_read_bypass_arm(allow),
                        f"PASS_K1_READ_BYPASS_AB={regime}:{allow}",
                    ))
                for index, read_cap in enumerate(
                        runner_contract.READ_COALESCE_CAP_SEQUENCE):
                    records.extend((
                        f"START_READ_COALESCE_CAP_AB={regime}:{read_cap}",
                        "REPLAY_ORDER=swapz-first" if index % 2 else
                        "REPLAY_ORDER=off-first",
                        f"PASS_RAM_MODEL_LOWER_MBPS={cap} COMPLETION_NSEC={ns} "
                        f"IRQMODE={irq} QUEUE_MODE={queue_mode} "
                        f"SUBMIT_QUEUES={submit_queues} "
                        f"HW_QUEUE_DEPTH={hw_depth}",
                        mock_read_coalesce_cap_arm(
                            read_cap, sd=(regime == "sd_emulated"))
                        if index % 2 else mock_arm("off", 0),
                        mock_arm("off", 0) if index % 2 else
                        mock_read_coalesce_cap_arm(
                            read_cap, sd=(regime == "sd_emulated")),
                        f"PASS_READ_COALESCE_CAP_AB={regime}:{read_cap}",
                    ))
            cap, ns, irq, queue_mode, submit_queues, hw_depth = (
                80, 150000, 2, 2, 1, 64)
            delta64_sequence = [
                2 if bit else 1 for bit in runner_contract.CONFIRMATION_SEQUENCE]
            for index, workers in enumerate(delta64_sequence):
                off = json.loads(mock_write_arm("off", 32, 0))
                off["fixture_sha256"] = "e" * 64
                off["trace_sha256"] = "f" * 64
                swapz = json.loads(mock_delta64_arm(workers))
                records.extend((
                    f"START_DELTA64_PREPARE_WORKERS={workers}",
                    "REPLAY_ORDER=swapz-first" if index % 2 else
                    "REPLAY_ORDER=off-first",
                    f"PASS_RAM_MODEL_LOWER_MBPS={cap} COMPLETION_NSEC={ns} IRQMODE={irq} QUEUE_MODE={queue_mode} SUBMIT_QUEUES={submit_queues} HW_QUEUE_DEPTH={hw_depth}",
                    json.dumps(swapz if index % 2 else off, sort_keys=True),
                    json.dumps(off if index % 2 else swapz, sort_keys=True),
                    f"PASS_DELTA64_PREPARE_WORKERS={workers}",
                ))
            for regime, cap, ns, irq, queue_mode, submit_queues, hw_depth in specs:
                records.append(f"START_WRITE_SATURATION_REGIME={regime}")
                index = 0
                for qd in (1, 4, 8, 32):
                    modes = (confirmation
                             if ((regime == "ssd_emulated" and
                                  qd in (4, 8, 32)) or
                                 (regime == "sd_emulated" and qd == 32))
                             else (0, 1))
                    for mode in modes:
                        records.extend((
                            f"START_WRITE_SATURATION_PAIR_QD={qd} ASYNC_PREPARE={mode}",
                            "REPLAY_ORDER=swapz-first" if index % 2 else "REPLAY_ORDER=off-first",
                            f"PASS_RAM_MODEL_LOWER_MBPS={cap} COMPLETION_NSEC={ns} IRQMODE={irq} QUEUE_MODE={queue_mode} SUBMIT_QUEUES={submit_queues} HW_QUEUE_DEPTH={hw_depth}",
                            "SWAPZ_STATUS_BEFORE=windows=0 one_page_windows=0 "
                            "win1=0 win2=0 win3_4=0 win5_8=0 win9_16=0 "
                            "win17_64=0 close_idle=0 close_deadline=0 "
                            "close_pack_ready=0 retained_burst_target=4 "
                            "prep_producer_head_claims=0 prep_producer_tail_claims=0 "
                            "prep_ordered_inline=0 prep_ordered_handoffs=0 "
                            "prep_ordered_waits=0 prep_lower_write_overlap_starts=0 "
                            "prep_wave_kicks=0",
                            "SWAPZ_STATUS_AFTER=windows=20 one_page_windows=4 "
                            "win1=4 win2=0 win3_4=8 win5_8=8 win9_16=0 "
                            "win17_64=0 close_idle=4 close_deadline=2 "
                            f"close_pack_ready=14 retained_burst_target={max(4, qd)} "
                            f"prep_producer_head_claims={2 if mode else 0} "
                            f"prep_producer_tail_claims={3 if mode else 0} "
                            f"prep_ordered_inline={4 if mode else 0} "
                            f"prep_ordered_handoffs={3 if mode else 0} "
                            f"prep_ordered_waits={1 if mode else 0} "
                            f"prep_lower_write_overlap_starts={42 if mode else 0} "
                            f"prep_wave_kicks={5 if mode else 0}",
                            mock_write_arm("swapz", qd, mode) if index % 2 else mock_write_arm("off", qd, mode),
                            mock_write_arm("off", qd, mode) if index % 2 else mock_write_arm("swapz", qd, mode),
                            f"PASS_WRITE_SATURATION_PAIR_QD={qd} ASYNC_PREPARE={mode}",
                        ))
                        index += 1
                records.append(f"PASS_WRITE_SATURATION_REGIME={regime}")
            depth_sequence = [
                2 if bit else 1 for bit in runner_contract.CONFIRMATION_SEQUENCE]
            for index, depth in enumerate(depth_sequence):
                off = json.loads(mock_write_arm("off", 32, 1))
                off["fixture_sha256"] = "7" * 64
                off["trace_sha256"] = "8" * 64
                swapz = json.loads(mock_write_pipeline_arm(depth))
                records.extend((
                    f"START_WRITE_PIPELINE_DEPTH={depth}",
                    "REPLAY_ORDER=swapz-first" if index % 2 else
                    "REPLAY_ORDER=off-first",
                    "PASS_RAM_MODEL_LOWER_MBPS=80 COMPLETION_NSEC=150000 "
                    "IRQMODE=2 QUEUE_MODE=2 SUBMIT_QUEUES=1 HW_QUEUE_DEPTH=64",
                    json.dumps(swapz if index % 2 else off, sort_keys=True),
                    json.dumps(off if index % 2 else swapz, sort_keys=True),
                    f"PASS_WRITE_PIPELINE_DEPTH={depth}",
                ))
            script = ("#!/bin/bash\nset -eu\n"
                      "source_sha=$(git rev-parse --verify HEAD)\n"
                      "test \"$(tail -n 1 build/order.log)\" = 'kbuild:2'\n"
                      "printf 'loaded\\n' >> build/order.log\n"
                      "printf '%s\\n' "
                      "'KERNEL_DEBUG_FEATURES=kasan:0 kcsan:0 lockdep:0 config:build'\n"
                      "printf '%s\\n' "
                      "'KERNEL_DEBUG_OBSERVATION=checked:1 baseline_stable:1 "
                      "reports:0 swapz_reports:0'\n"
                      "sed \"s/SWAPZ_FIXTURE_SOURCE_SHA/$source_sha/g\" "
                      "<<'MOCK_RECORDS'\n" + "\n".join(records) +
                      "\nMOCK_RECORDS\n")
            (fixture / "tests/tools/test-loaded.sh").write_text(script)

            def fixture_git(*arguments):
                return subprocess.run(
                    ["git", *arguments], cwd=fixture, check=True,
                    capture_output=True, text=True, timeout=5)

            # Give the copied Makefile and reporter one real, isolated source
            # identity. This synthetic main has no remote, so publication is
            # inert while the canonical-main gate is still exercised.
            fixture_git("init", "--initial-branch=main")
            fixture_git("config", "user.name", "swapz incremental fixture")
            fixture_git("config", "user.email",
                        "swapz-incremental-fixture@example.invalid")
            fixture_git("add", ".")
            fixture_git("commit", "-m", "fixture: tracked incremental source")
            runner_contract.ROOT = fixture
            fixture_source_sha = runner_contract.git_sha()
            self.assertRegex(fixture_source_sha, r"^[0-9a-f]{40}$")
            self.assertEqual(
                fixture_source_sha,
                fixture_git("rev-parse", "HEAD").stdout.strip())

            env = os.environ.copy()
            env.pop("MAKEFLAGS", None)
            env.pop("MFLAGS", None)
            env.pop("W", None)
            sign_calls = fixture / "build/sign-module.calls"
            env["SWAPZ_SIGNING_TEST_LOG"] = str(sign_calls)
            make_invocations = []

            def execute(phase, *, expect_clean):
                print(f"MAKE_INCREMENTAL_PHASE={phase}", flush=True)
                proc = subprocess.run(
                    ["make", "test", f"KDIR={fixture / 'fake-headers'}"],
                    cwd=fixture, env=env, capture_output=True, text=True,
                    timeout=30)
                if expect_clean:
                    self.assertEqual(
                        proc.returncode, 0,
                        f"phase={phase} first_error=clean fixture refused "
                        f"reason={proc.stdout}\n{proc.stderr}")
                else:
                    self.assertEqual(
                        proc.returncode, 2,
                        f"phase={phase} first_error=dirty fixture exit mismatch "
                        f"reason={proc.stdout}\n{proc.stderr}")
                    self.assertIn(
                        "Qualification refusal: phase=report-binding "
                        "reason=build_provenance_mismatch",
                        proc.stdout,
                        f"phase={phase} first_error=missing dirty refusal "
                        "reason=qualification must reject clean=0 provenance")
                make_invocations.append(phase)
                self.assertEqual(
                    sign_calls.read_text(), "call\n" * len(make_invocations),
                    "the hermetic signing stub must observe each make invocation",
                )
                self.assertRegex(
                    proc.stdout,
                    r"independent compilation uses automatic -j[1-9][0-9]*[.]",
                )
                self.assertEqual(
                    runner_contract.git_sha(), fixture_source_sha,
                    f"phase={phase} first_error=reporter source changed "
                    "reason=dirty development edits must not advance HEAD")
                build_info = (fixture / "build/source-build-info.h").read_text()
                self.assertIn(
                    f'#define SWAPZ_BUILD_SOURCE_SHA "{fixture_source_sha}"',
                    build_info,
                    f"phase={phase} first_error=unexpected source "
                    "reason=Makefile and reporter must bind the fixture HEAD",
                )
                expected_clean_string = "1" if expect_clean else "0"
                self.assertIn(
                    f'#define SWAPZ_BUILD_SOURCE_CLEAN_STRING '
                    f'"{expected_clean_string}"',
                    build_info,
                    f"phase={phase} first_error=unexpected clean state "
                    "reason=generated provenance must reflect fixture dirtiness",
                )
                order = (fixture / "build/order.log").read_text().splitlines()
                self.assertEqual(order[-5:],
                                 ["kbuild:", "rootless", "kbuild:1",
                                  "kbuild:2", "loaded"])

            module = fixture / "build/kernel/experimental/dm-swapz.ko"
            staged = fixture / "build/kernel/experimental/dm-target.c"
            staged_authority = fixture / "build/kernel/experimental/authority.h"
            staged_make = fixture / "build/kernel/experimental/Makefile"
            w1_module = fixture / "build/kernel/w1/dm-swapz.ko"
            w2_module = fixture / "build/kernel/w2/dm-swapz.ko"
            w1_staged = fixture / "build/kernel/w1/dm-target.c"
            w2_staged = fixture / "build/kernel/w2/dm-target.c"
            w1_authority = fixture / "build/kernel/w1/authority.h"
            w2_authority = fixture / "build/kernel/w2/authority.h"
            device = fixture / "build/tests/device-roundtrip"
            direct_probe = fixture / "build/tests/direct-write-probe"
            direct_read_probe = fixture / "build/tests/direct-read-probe"
            cli_out = fixture / "build/userspace/swapzctl"
            execute("initial", expect_clean=True)
            tracked = (module, w1_module, w2_module, staged,
                       w1_staged, w2_staged, staged_authority,
                       w1_authority, w2_authority, staged_make, device,
                       direct_probe, direct_read_probe, cli_out)
            first = {p: p.stat().st_mtime_ns for p in tracked}
            execute("unchanged", expect_clean=True)
            self.assertEqual(first,
                             {p: p.stat().st_mtime_ns for p in tracked},
                             "An unchanged make test must reuse binaries "
                             "and staged kernel sources")

            time.sleep(0.03)
            cli.write_text("int main(void) { return 1; }\n")
            execute("cli-source", expect_clean=False)
            self.assertGreater(cli_out.stat().st_mtime_ns, first[cli_out],
                               "MAKE_INCREMENTAL_PHASE=cli-source")
            # The first source edit changes the embedded clean bit from 1 to
            # 0. Every provenance-bound artifact must be rebuilt for that
            # transition, even when the edited source is userspace-only.
            self.assertGreater(module.stat().st_mtime_ns, first[module],
                               str(module))
            self.assertIn("#define SWAPZ_BUILD_SOURCE_CLEAN 0",
                          module.read_text())
            for p in (w1_module, w2_module, staged, w1_staged, w2_staged,
                      staged_authority, w1_authority, w2_authority,
                      staged_make, device, direct_probe, direct_read_probe):
                self.assertEqual(first[p], p.stat().st_mtime_ns, str(p))

            second = {p: p.stat().st_mtime_ns for p in tracked}
            time.sleep(0.03)
            cli.write_text("int main(void) { return 2; }\n")
            execute("cli-source-still-dirty", expect_clean=False)
            self.assertGreater(cli_out.stat().st_mtime_ns, second[cli_out],
                               "MAKE_INCREMENTAL_PHASE=cli-source-still-dirty")
            for p in (module, w1_module, w2_module, staged, w1_staged,
                      w2_staged, staged_authority, w1_authority, w2_authority,
                      staged_make, device, direct_probe, direct_read_probe):
                self.assertEqual(second[p], p.stat().st_mtime_ns, str(p))

            second = {p: p.stat().st_mtime_ns for p in tracked}
            authority_header = fixture / "src/kernel/authority.h"
            time.sleep(0.03)
            authority_header.write_text(
                authority_header.read_text() +
                "\n/* incremental authority dependency probe */\n")
            execute("authority-header", expect_clean=False)
            self.assertGreater(
                cli_out.stat().st_mtime_ns, second[cli_out],
                "MAKE_INCREMENTAL_PHASE=authority-header")
            for p in (module, w1_module, w2_module, staged_authority,
                      w1_authority, w2_authority):
                self.assertGreater(p.stat().st_mtime_ns, second[p], str(p))
            for p in (staged, w1_staged, w2_staged, staged_make, device,
                      direct_probe, direct_read_probe):
                self.assertEqual(second[p], p.stat().st_mtime_ns, str(p))

            second = {p: p.stat().st_mtime_ns for p in tracked}
            time.sleep(0.03)
            kernel_source.write_text("int fake_kernel_source = 2;\n")
            execute("kernel-source", expect_clean=False)
            self.assertEqual(staged.read_text(), kernel_source.read_text(),
                             "MAKE_INCREMENTAL_PHASE=kernel-source")
            self.assertGreater(staged.stat().st_mtime_ns, second[staged])
            for p in (module, w1_module, w2_module, w1_staged, w2_staged):
                self.assertGreater(p.stat().st_mtime_ns, second[p])
            for p in (staged_make, device, direct_probe, cli_out):
                self.assertEqual(second[p], p.stat().st_mtime_ns, str(p))

            # Changing only canonical VERSION must regenerate every kernel
            # staging header and dependent module, without editing Kbuild or C.
            from_version = fixture / "src/kernel/VERSION"
            to_version = "3.0.0-alpha.99\n"
            if from_version.read_text() == to_version:
                to_version = "3.0.0-alpha.100\n"
            headers = [fixture / "build/kernel" / kind / "swapz-version.h"
                       for kind in ("experimental", "w1", "w2")]
            before_version = [p.stat().st_mtime_ns for p in headers]
            before_module = [p.stat().st_mtime_ns
                             for p in (module, w1_module, w2_module)]
            time.sleep(0.03)
            from_version.write_text(to_version)
            execute("version", expect_clean=False)
            for p, old_mtime in zip(headers, before_version):
                self.assertGreater(p.stat().st_mtime_ns, old_mtime)
                self.assertIn(to_version.strip(), p.read_text())
            for p, old_mtime in zip(
                    (module, w1_module, w2_module), before_module):
                self.assertGreater(p.stat().st_mtime_ns, old_mtime)

    def test_async_preparation_gate_accepts_real_submitter_work_only(self):
        # Execute the actual benchmark admission gate with synthetic drained
        # target statuses. Zero background overlap is valid only with real
        # completed submitter work; neither missing evidence nor active
        # submitter ownership may pass the loaded pair.
        benchmark = (ROOT / "tests/tools/benchmark-owned-pair.sh").read_text()
        start = benchmark.index("# ID150 async preparation activity gate:")
        end = benchmark.index("\nfi\nfi\nCOMPARE_ARGS=()", start) + len("\nfi\n")
        gate = benchmark[start:end]
        cases = (
            ("background", 7, 0, 0, 0, 0, True),
            ("submitter", 0, 1, 19, 18, 0, True),
            ("neither", 0, 1, 0, 0, 0, False),
            ("disabled", 0, 0, 19, 18, 0, False),
            ("invalid_claims", 0, 1, 4, 9, 0, False),
            ("active_owner", 0, 1, 19, 18, 1, False),
        )
        for name, overlap, enabled, claims, pages, active, expected in cases:
            with self.subTest(name=name):
                status = (
                    f"prep_lower_write_overlap_starts={overlap} "
                    f"submitter_prepare={enabled} "
                    f"submitter_prepare_claims={claims} "
                    f"submitter_prepare_pages={pages} "
                    f"submitter_prepare_active={active}")
                command = (
                    'set -euo pipefail\n'
                    'fail() { echo "BLOCKED: $*" >&2; exit 1; }\n'
                    'note() { printf "%s\\n" "$*"; }\n'
                    'ASYNC_PREPARE=1 WRITE_ONLY_QD=0\n'
                    f"swapz_status_after='{status}'\n" + gate)
                result = subprocess.run(
                    ["bash", "-c", command], capture_output=True,
                    text=True, timeout=5)
                self.assertEqual(result.returncode == 0, expected,
                                 result.stdout + result.stderr)
                if expected:
                    self.assertIn("PASS_ASYNC_PREPARATION_ACTIVITY=",
                                  result.stdout)
                else:
                    self.assertIn("BLOCKED:", result.stderr)

    def test_packaging_and_loaded_tests_are_bounded(self):
        self.assertIn("packaging/package-dkms.sh install", MAKE)
        self.assertIn("packaging/package-dkms.sh uninstall", MAKE)
        self.assertIn("\ninstall:\n", MAKE)
        self.assertNotIn("\ninstall: all\n", MAKE)
        self.assertIn("tests/tools/test-rootless.sh", (ROOT / "tests/tools/run-tests.py").read_text())
        rootless_test_recipe = MAKE.split("\ntest:\n", 1)[1]
        self.assertIn("tests/tools/run-tests.py", rootless_test_recipe)
        reporter = (ROOT / "tests/tools/run-tests.py").read_text()
        self.assertIn("tests/tools/test-rootless.sh", reporter)
        self.assertIn("tests/tools/test-loaded.sh", reporter)
        self.assertIn("W=1", reporter)
        self.assertIn("W=2", reporter)
        self.assertLess(reporter.index('"Native and rootless contracts"'),
                        reporter.index('"Kernel warnings W=1"'))
        self.assertLess(reporter.index('"Kernel warnings W=2"'),
                        reporter.index('"Owned RAM smoke + mixed/QD pilot"'))
        for privileged in ("sudo -v", "sudo bash", "modprobe", "dmsetup"):
            self.assertNotIn(privileged, rootless_test_recipe)
        loaded = (ROOT / "tests/tools/test-loaded.sh").read_text()
        deploy = ROOT / "tests/tools/deploy-nullblk.sh"
        self.assertTrue(deploy.stat().st_mode & 0o100)
        self.assertIn("bash packaging/package-dkms.sh", MAKE)
        self.assertIn(
            "python3 -B tests/runtime/native/package-dkms-test.py",
            (ROOT / "tests/tools/test-rootless.sh").read_text())
        self.assertIn("sudo -n true", loaded)
        self.assertIn("sudo -n bash", loaded)
        self.assertIn("BLOCKED_LOADED_QUALIFICATION", loaded)
        self.assertIn("tests/tools/deploy-nullblk.sh", loaded)
        self.assertIn("tests/tools/loaded-preflight.sh", loaded)
        self.assertIn("tests/tools/benchmark-owned-pair.sh", loaded)
        preflight = (ROOT / "tests/tools/loaded-preflight.sh").read_text()
        self.assertIn("/sys/module/dm_swapz/refcnt", preflight)
        self.assertIn("[[ $refcount == 0 ]]", preflight)
        self.assertNotIn("rmmod dm_swapz", preflight)
        self.assertIn("expected_proof=creation_authority", preflight)
        self.assertIn("retained_state_action=retain_module", preflight)
        self.assertNotIn("AUTO_REMOVED_IDLE_DM_SWAPZ=1", preflight)
        self.assertNotIn("AUTO_REMOVED_STALE_OWNED_DM_SWAPZ=1", preflight)
        self.assertIn('token="${owned_map#swapz-demo-}"', preflight)
        self.assertIn('is_hex16 "$token"', preflight)
        self.assertIn('""|0*|*[!0-9]*) return 1', preflight)
        self.assertNotIn("=~", preflight)
        self.assertIn('length($2) > 18', preflight)
        self.assertIn('elif (( early_available_kib < 1048576 )); then', preflight)
        self.assertLess(
            preflight.index('if ! is_uint "$early_available_kib"; then'),
            preflight.index('elif (( early_available_kib < 1048576 )); then'))
        self.assertEqual(preflight.count("(("), 1)
        self.assertIn('"SWAPZ-TEST-$token"', preflight)
        self.assertIn('"SWAPZ-TEST-$token-packed"', preflight)
        self.assertIn('case "$uuid" in', preflight)
        self.assertNotIn("BASH_REMATCH", preflight)
        self.assertIn("memory_backed", preflight)
        self.assertIn('dmsetup deps -o devno "$owned_map"', preflight)
        self.assertIn('[[ $sysfs_devno == "$lower_devno" ]]', preflight)
        self.assertIn("assert_mapper_is_only_lower_holder mapper_remove", preflight)
        self.assertIn('is_uint "$mapper_kernel_index"', preflight)
        self.assertIn(
            'exec {owned_power_fd}<> "/proc/$$/fd/$owned_config_fd/power"',
            preflight)
        self.assertIn('dmsetup remove --retry "$uuid"', preflight)
        self.assertNotIn('dmsetup remove --retry "$owned_map"', preflight)
        self.assertNotIn("rmmod -f", preflight)
        self.assertNotIn("dmsetup remove --force", preflight)
        self.assertIn("--lower-mbps 10 --hw-queue-depth 1 --completion-nsec 1000000", loaded)
        self.assertIn("--lower-mbps 80 --hw-queue-depth 64 --completion-nsec 150000", loaded)
        self.assertIn("for regime in sd_emulated ssd_emulated", loaded)
        self.assertNotIn("START_LZ4_ACCELERATION=", loaded)
        self.assertNotIn("PASS_LZ4_ACCELERATION=", loaded)
        self.assertNotIn("--lz4-acceleration", loaded)
        self.assertNotIn("START_READ_COALESCE_CAP_AB=", loaded)
        self.assertNotIn("--read-coalesce-max-blocks", loaded)
        self.assertIn("--async-prepare", loaded)
        self.assertIn("confirmation_modes=(0 1 1 0 0 1 1 0 0 1)", loaded)
        self.assertIn('for async_prepare in "${modes[@]}"', loaded)
        self.assertNotIn('for parallel_reads in "${directional_modes[@]}"', loaded)
        self.assertNotIn("START_BURST_GUARD_AB=", loaded)
        self.assertNotIn("--guard-inflight-zero-shrink", loaded)
        self.assertNotIn("START_PARALLEL_READ_AB=", loaded)
        self.assertNotIn("PASS_PARALLEL_READ_AB=", loaded)
        self.assertNotIn('for parallel_reads in "${confirmation_modes[@]}"', loaded)
        self.assertNotIn("--parallel-reads", loaded)
        self.assertIn("qualify-resource-pressure.sh", loaded)
        self.assertNotIn("START_SD_READ_GROUPING_AB=", loaded)
        self.assertNotIn("PASS_SD_READ_GROUPING_AB=", loaded)
        self.assertIn("START_SD_READ_COALESCE_AB=", loaded)
        self.assertIn("PASS_SD_READ_COALESCE_AB=", loaded)
        self.assertNotIn("START_DELTA64_PREPARE_WORKERS=", loaded)
        self.assertNotIn("PASS_DELTA64_PREPARE_WORKERS=", loaded)
        self.assertGreaterEqual(
            loaded.count(
                "--lower-mbps 10 --hw-queue-depth 1 --completion-nsec 1000000"),
            2)
        self.assertIn("for qd in 1 4 8 32", loaded)
        self.assertIn("$qd == 4 || $qd == 8 || $qd == 32", loaded)
        self.assertIn("--write-only-qd", loaded)
        self.assertIn("--sustained-write", loaded)
        self.assertIn("START_WRITE_SATURATION_PAIR_QD=", loaded)
        self.assertNotIn("START_WRITE_PIPELINE_DEPTH=", loaded)
        self.assertNotIn("PASS_WRITE_PIPELINE_DEPTH=", loaded)
        self.assertNotIn("--write-pipeline-depth", loaded)
        self.assertIn("def parse_write_pipeline_depth", reporter)
        self.assertIn("PASS_WRITE_PIPELINE_DEPTH_EVIDENCE", reporter)
        self.assertNotIn("--delta64-lz4-acceleration", loaded)
        self.assertNotIn("--delta64-rescue", loaded)
        self.assertNotIn("--no-delta64-rescue", loaded)
        self.assertNotIn("START_DELTA64_RESCUE=", loaded)
        self.assertNotIn("PASS_DELTA64_RESCUE=", loaded)
        self.assertIn("START_STORAGE_ENVELOPE=%s", loaded)
        self.assertLess(loaded.index("tests/tools/deploy-nullblk.sh"),
                        loaded.index("tests/tools/benchmark-owned-pair.sh"))
        self.assertNotIn("swapon ", loaded)
        self.assertNotIn("swapoff ", loaded)
        self.assertIn("--shared-plan", loaded)
        self.assertIn("--swapz-first", loaded)
        self.assertIn("W=1", reporter)
        self.assertIn("W=2", reporter)
        package = (ROOT / "packaging/package-dkms.sh").read_text()
        for token in ("AUTOINSTALL", '"$dkms_bin" add', '"$dkms_bin" build',
                      '"$dkms_bin" install', '"$dkms_bin" remove',
                      "swapz:", "/sys/module/dm_swapz"):
            self.assertIn(token, package)
        self.assertNotIn("swapon ", package)
        self.assertNotIn("swapoff ", package)
        self.assertIn("swapzctl", package)
        self.assertIn("src/userspace/swapzctl.c", MAKE)
        self.assertIn("tests/runtime/native/package-dkms-test.py", (ROOT / "tests/tools/test-rootless.sh").read_text())
        ci = (ROOT / ".github/workflows/project-goals.yml").read_text()
        self.assertIn("bash tests/tools/test-rootless.sh", ci)
        self.assertEqual(
            ci.count("python3 -B tests/tools/ci-failure-diagnostics-test.py -v"),
            1)
        self.assertNotIn("make verify", ci)



class ProjectGoalsRepositoryPolicyContract(unittest.TestCase):
    """Exercise real CI policy and aggregate scripts against rootless Git fixtures."""

    @classmethod
    def setUpClass(cls):
        workflow = (ROOT / ".github/workflows/project-goals.yml").read_text()
        policy_marker = (
            "          cat > build/ci-standards-policy.sh <<'SWAPZ_CI_SCRIPT'\n")
        conclusion_marker = (
            "      - name: Reject failed, skipped, or cancelled prerequisite jobs\n"
            "        shell: bash\n"
            "        run: |\n")
        if workflow.count(policy_marker) != 1 or workflow.count(conclusion_marker) != 1:
            raise ValueError("project-goal CI script markers missing or ambiguous")
        cls.policy_script = "\n".join(
            line.removeprefix("          ")
            for line in workflow.split(policy_marker, 1)[1].split(
                "\n          SWAPZ_CI_SCRIPT", 1)[0].splitlines()) + "\n"
        cls.conclusion_script = "\n".join(
            line.removeprefix("          ")
            for line in workflow.split(conclusion_marker, 1)[1].split(
                "\n      - name: Audit current-run mandatory jobs", 1
            )[0].splitlines()) + "\n"
        audit_marker = (
            "      - name: Audit current-run mandatory jobs\n"
            "        shell: bash\n"
            "        env:\n"
            "          GITHUB_TOKEN: ${{ github.token }}\n"
            "        run: |\n"
            "          python3 -B - <<\x27PY\x27\n"
        )
        if workflow.count(audit_marker) != 1:
            raise ValueError("exact-SHA job-census script marker missing or ambiguous")
        cls.audit_script = "\n".join(
            line.removeprefix("          ")
            for line in workflow.split(audit_marker, 1)[1].split(
                "\n          PY", 1)[0].splitlines()) + "\n"

    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory(
            prefix="swapz-policy-")
        self.addCleanup(self.temporary_directory.cleanup)
        self.repository = pathlib.Path(self.temporary_directory.name) / "repo"
        self.repository.mkdir()
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.name", "Rootless Fixture")
        self.git("config", "user.email", "fixture@example.invalid")
        self.commit({"docs/compile.md": "initial standard\n"}, "initial standard")

    def git(self, *arguments, input_text=None):
        completed = subprocess.run(
            ["git", *arguments], cwd=self.repository, input=input_text,
            capture_output=True, text=True, timeout=6, check=True)
        return completed.stdout.strip()

    def commit(self, files, message):
        for name, content in files.items():
            path = self.repository / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        self.git("add", "-A")
        self.git("commit", "-qm", message)
        return self.git("rev-parse", "HEAD")

    def check_policy(self, sha=None, repository=None, extra_environment=None):
        environment = os.environ.copy()
        environment["GITHUB_SHA"] = sha or self.git("rev-parse", "HEAD")
        # Synthetic fixtures default to manual-dispatch semantics. Tests that
        # exercise push ranges opt in with an explicit pre-push SHA.
        environment["GITHUB_EVENT_NAME"] = "workflow_dispatch"
        environment.pop("SWAPZ_PUSH_BEFORE_SHA", None)
        environment.update(extra_environment or {})
        return subprocess.run(
            ["bash", "-c", self.policy_script],
            cwd=repository or self.repository, env=environment,
            capture_output=True, text=True, timeout=8)

    def test_compliant_code_only_docs_only_rootless_and_evidence_commits(self):
        self.commit({
            "src/kernel/codec.c": "int codec = 1;\n",
            "docs/compile.md": "initial standard\ncode contract updated\n",
        }, "implementation and updated standard")
        result = self.check_policy()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout + result.stderr, "")

        commit_sha = self.commit(
            {"src/kernel/codec.c": "int codec = 2;\n"},
            "implementation without standard")
        result = self.check_policy()
        self.assertNotEqual(result.returncode, 0)
        for token in (commit_sha, "src/kernel/codec.c", "docs/compile.md",
                      "docs/testing_standards.md", "same-commit"):
            self.assertIn(token, result.stderr)

        self.commit({"docs/README.md": "documentation-only\n"}, "docs only")
        self.assertEqual(self.check_policy().returncode, 0)

        rootless_sha = self.commit({
            "tests/runtime/native/rootless-fixture.py": "# rootless test\n",
        }, "test change without standard")
        result = self.check_policy()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(rootless_sha, result.stderr)
        self.assertIn("tests/runtime/native/rootless-fixture.py", result.stderr)

        self.commit({
            "tests/runtime/native/rootless-fixture.py": "# amended test\n",
            "docs/testing_standards.md": "new rootless test contract\n",
        }, "rootless test with standard")
        self.assertEqual(self.check_policy().returncode, 0)

        self.commit({"test_results.json": '{"status":"BLOCKED"}\n'},
                    "evidence only [skip ci]")
        self.assertEqual(self.check_policy().returncode, 0)

        violation_sha = self.commit({"Makefile": "all:\n\t@true\n"},
                                    "implementation [skip ci]")
        result = self.check_policy()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(violation_sha, result.stderr)
        self.assertIn("Makefile", result.stderr)

    def test_push_audits_every_introduced_first_parent_commit(self):
        workflow = (ROOT / ".github/workflows/project-goals.yml").read_text()
        repository_job = workflow.split("  repository-policy:\n", 1)[1].split(
            "\n  project-goals-conclusion:", 1)[0]
        self.assertIn("fetch-depth: 0", repository_job)
        self.assertIn(
            "SWAPZ_PUSH_BEFORE_SHA: ${{ github.event.before }}",
            repository_job)

        push_before = self.git("rev-parse", "HEAD")
        violating_sha = self.commit(
            {"src/kernel/codec.c": "int codec = 1;\n"},
            "implementation without standard")
        self.commit(
            {"docs/compile.md": "initial standard\nlate documentation\n"},
            "documentation cannot qualify previous commit")
        result = self.check_policy(extra_environment={
            "GITHUB_EVENT_NAME": "push",
            "SWAPZ_PUSH_BEFORE_SHA": push_before,
        })
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(violating_sha, result.stderr)
        self.assertIn("src/kernel/codec.c", result.stderr)
        self.assertIn("same-commit", result.stderr)

        # A multi-commit push remains valid when each implementation commit
        # independently carries its own canonical standards update.
        self.git("reset", "--hard", push_before)
        self.commit({
            "src/kernel/codec.c": "int codec = 2;\n",
            "docs/compile.md": "initial standard\ncode contract updated\n",
        }, "implementation and same-commit standard")
        self.commit({"docs/README.md": "documentation-only follow-up\n"},
                    "documentation-only follow-up")
        result = self.check_policy(extra_environment={
            "GITHUB_EVENT_NAME": "push",
            "SWAPZ_PUSH_BEFORE_SHA": push_before,
        })
        self.assertEqual(result.returncode, 0, result.stderr)

        malformed = self.check_policy(extra_environment={
            "GITHUB_EVENT_NAME": "push",
            "SWAPZ_PUSH_BEFORE_SHA": "not-a-sha",
        })
        self.assertNotEqual(malformed.returncode, 0)
        self.assertIn("push base SHA unavailable or malformed",
                      malformed.stderr)

    def test_missing_checkout_parent_sha_and_malformed_changeset_fail_closed(self):
        initial_sha = self.git("rev-parse", "HEAD")
        result = self.check_policy()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("missing first parent", result.stderr)
        self.assertIn(initial_sha, result.stderr)

        result = self.check_policy(sha="0" * 40)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("checkout SHA mismatch", result.stderr)

        absent_checkout = pathlib.Path(self.temporary_directory.name) / "absent"
        absent_checkout.mkdir()
        result = self.check_policy(repository=absent_checkout)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("missing checked-out HEAD", result.stderr)

        self.commit({"src/kernel/codec.c": "int codec = 1;\n"}, "code only")
        fake_bin = pathlib.Path(self.temporary_directory.name) / "bin"
        fake_bin.mkdir()
        real_git = pathlib.Path(shutil.which("git")).resolve()
        fake_git = fake_bin / "git"
        fake_git.write_text(
            "#!/bin/sh\n"
            "if [ \"$1\" = diff ]; then printf 'src/kernel/unclosed'; exit 0; fi\n"
            f"exec '{real_git}' \"$@\"\n")
        fake_git.chmod(0o755)
        environment = {"PATH": f"{fake_bin}:{os.environ['PATH']}"}
        result = self.check_policy(extra_environment=environment)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("malformed NUL-delimited changeset", result.stderr)

        fake_git.write_text(
            "#!/bin/sh\n"
            "if [ \"$1\" = diff ]; then printf '\\000'; exit 0; fi\n"
            f"exec '{real_git}' \"$@\"\n")
        result = self.check_policy(extra_environment=environment)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("empty path in changeset", result.stderr)

    def test_bounded_paths_noncanonical_docs_and_diff_errors(self):
        changed_files = {
            f"tests/runtime/native/fixture-{index:02d}.py": "# changed\n"
            for index in range(12)
        }
        changed_files["docs/README.md"] = "not a canonical standard\n"
        commit_sha = self.commit(changed_files, "test changes with noncanonical docs")
        result = self.check_policy()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(commit_sha, result.stderr)
        self.assertIn("showing 8/12", result.stderr)
        self.assertIn("docs/benchmark.md", result.stderr)
        self.assertNotIn("fixture-11.py", result.stderr)

        fake_bin = pathlib.Path(self.temporary_directory.name) / "bin"
        fake_bin.mkdir()
        fake_git = fake_bin / "git"
        real_git = pathlib.Path(shutil.which("git")).resolve()
        fake_git.write_text(
            "#!/bin/sh\n"
            "if [ \"$1\" = diff ]; then exit 3; fi\n"
            f"exec '{real_git}' \"$@\"\n")
        fake_git.chmod(0o755)
        result = self.check_policy(extra_environment={
            "PATH": f"{fake_bin}:{os.environ['PATH']}"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unable to read first-parent changeset", result.stderr)

    def test_merge_compares_only_first_parent(self):
        base = self.git("rev-parse", "HEAD")
        second_parent = self.commit(
            {"docs/compile.md": "a second parent's documentation\n"},
            "independent documentation")
        self.git("reset", "--hard", base)
        tree_commit = self.commit({
            "src/kernel/codec.c": "int codec = 1;\n",
            "docs/compile.md": "a second parent's documentation\n",
        }, "merged tree content")
        merged_tree = self.git("rev-parse", "HEAD^{tree}")
        self.git("reset", "--hard", base)
        # Construct a merge object without creating any additional branch.
        merge_sha = self.git("commit-tree", merged_tree, "-p", base,
                             "-p", second_parent,
                             input_text="synthetic two-parent changeset\n")
        self.git("update-ref", "refs/heads/main", merge_sha, base)
        result = self.check_policy()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotEqual(tree_commit, merge_sha)
        self.assertIn("src/kernel/codec.c", self.git(
            "diff", "--name-only", second_parent, merge_sha))
        self.assertNotIn("docs/compile.md", self.git(
            "diff", "--name-only", second_parent, merge_sha))

    def test_skipped_dependency_cannot_qualify_exact_sha(self):
        sha = self.git("rev-parse", "HEAD")
        environment = os.environ.copy()
        environment.update({"GITHUB_SHA": sha, "GITHUB_RUN_ID": "12345",
                            "NATIVE_RESULT": "success", "MAKE_RESULT": "success",
                            "FOCUSED_RESULT": "success", "POLICY_RESULT": "success"})
        passed = subprocess.run(["bash", "-c", self.conclusion_script],
                                env=environment, capture_output=True,
                                text=True, timeout=6)
        self.assertEqual(passed.returncode, 0, passed.stderr)
        # The initial needs check alone must never emit the qualification marker.
        self.assertEqual(passed.stdout, "")
        for failed_result in ("failure", "skipped", "cancelled", ""):
            with self.subTest(result=failed_result):
                environment["POLICY_RESULT"] = failed_result
                failed = subprocess.run(
                    ["bash", "-c", self.conclusion_script], env=environment,
                    capture_output=True, text=True, timeout=6)
                self.assertNotEqual(failed.returncode, 0)
                self.assertIn(
                    f"job=POLICY result={failed_result} tested_sha={sha}",
                    failed.stdout)
                self.assertNotIn("EXACT_SHA_ROOTLESS_CI_COMPLETE", failed.stdout)


    def test_job_census_requires_every_current_source_job(self):
        """A green aggregate cannot hide a missing or conflicting matrix member."""
        import contextlib
        import io
        from unittest import mock

        source_sha = self.git("rev-parse", "HEAD")
        prefixes = (
            "Native rootless", "Make interface", "Rootless source-contract",
            "Rootless primary-lifecycle-audit", "Rootless production-readiness",
            "Repository policy", "Exact-SHA CI result",
        )
        passing_jobs = [
            {"name": f"{prefix} {source_sha}", "head_sha": source_sha,
             "run_id": 12345, "run_attempt": 1,
             "status": "completed" if index < 6 else "in_progress",
             "conclusion": "success" if index < 6 else None}
            for index, prefix in enumerate(prefixes)
        ]
        environment = {
            "GITHUB_SHA": source_sha, "GITHUB_RUN_ID": "12345",
            "GITHUB_RUN_ATTEMPT": "1", "GITHUB_REPOSITORY": "fixture/swapz",
            "GITHUB_TOKEN": "fixture-private-token",
            "GITHUB_API_URL": "https://api.github.com",
        }

        def census(rows, *, total_count=None, checkout_sha=None, api_error=None):
            payload = json.dumps({
                "total_count": len(rows) if total_count is None else total_count,
                "jobs": rows,
            }).encode()
            requested_urls = []

            def open_manifest(request, timeout):
                self.assertEqual(timeout, 10)
                requested_urls.append(request.full_url)
                if api_error is not None:
                    raise OSError(api_error)
                return io.BytesIO(payload)

            with mock.patch.dict(os.environ, environment), \
                 mock.patch(
                     "subprocess.run",
                     return_value=subprocess.CompletedProcess(
                         [], 0, stdout=checkout_sha or source_sha)), \
                 mock.patch("urllib.request.urlopen",
                            side_effect=open_manifest), \
                 contextlib.redirect_stdout(io.StringIO()) as output, \
                 contextlib.redirect_stderr(io.StringIO()) as errors:
                try:
                    exec(compile(self.audit_script, "<exact-SHA CI census>",
                                 "exec"), {"__name__": "__main__"})
                    exit_code = 0
                except SystemExit as error:
                    exit_code = error.code
            return (exit_code, output.getvalue(), errors.getvalue(),
                    requested_urls)

        code, output, errors, requested_urls = census(passing_jobs)
        self.assertEqual((code, output, errors),
                         (0, f"EXACT_SHA_ROOTLESS_CI_COMPLETE={source_sha}\n", ""))
        self.assertEqual(requested_urls, [
            "https://api.github.com/repos/fixture/swapz/actions/runs/"
            "12345/attempts/1/jobs?per_page=100",
        ])

        for scenario in (
                "missing", "missing-matrix-member", "extra",
                "duplicate", "failure", "skipped", "cancelled",
                "in_progress", "stale-source", "wrong-run",
                "wrong-attempt", "checkout-mismatch", "partial-page",
                "conclusion-completed"):
            with self.subTest(scenario=scenario):
                jobs = json.loads(json.dumps(passing_jobs))
                total_count = None
                checkout_sha = None
                if scenario == "missing":
                    jobs.pop(0)
                elif scenario == "missing-matrix-member":
                    jobs[2]["name"] = f"Unrequired green job {source_sha}"
                elif scenario == "extra":
                    jobs.append(dict(jobs[0]))
                elif scenario == "duplicate":
                    jobs[1] = dict(jobs[0])
                elif scenario in ("failure", "skipped", "cancelled"):
                    jobs[0]["conclusion"] = scenario
                elif scenario == "in_progress":
                    jobs[0]["status"] = "in_progress"
                    jobs[0]["conclusion"] = None
                elif scenario == "stale-source":
                    jobs[2]["head_sha"] = "e" * 40
                elif scenario == "wrong-run":
                    jobs[2]["run_id"] = 23456
                elif scenario == "wrong-attempt":
                    jobs[2]["run_attempt"] = 2
                elif scenario == "checkout-mismatch":
                    checkout_sha = "f" * 40
                elif scenario == "partial-page":
                    total_count = 8
                else:
                    jobs[-1]["status"] = "completed"
                code, output, errors, requested_urls = census(
                    jobs, total_count=total_count, checkout_sha=checkout_sha)
                self.assertNotEqual(code, 0)
                self.assertEqual(output, "")
                for field in (f"tested_sha={source_sha}",
                              "phase=exact-sha-census", "gate=", "required=",
                              "observed=", "corrective_procedure="):
                    self.assertIn(field, errors)
                self.assertNotIn("fixture-private-token", errors)
                self.assertLessEqual(len(errors.strip()), 255)
                # Checkout identity is checked before any authenticated API call.
                if scenario == "checkout-mismatch":
                    self.assertEqual(requested_urls, [])
                else:
                    self.assertEqual(requested_urls, [
                        "https://api.github.com/repos/fixture/swapz/actions/runs/"
                        "12345/attempts/1/jobs?per_page=100",
                    ])

        code, output, errors, requested_urls = census(
            passing_jobs, api_error="token=fixture-private-token /home/private")
        self.assertNotEqual(code, 0)
        self.assertEqual(output, "")
        self.assertIn("gate=job-census-api", errors)
        self.assertNotIn("fixture-private-token", errors)
        self.assertNotIn("/home/private", errors)
        self.assertEqual(requested_urls, [
            "https://api.github.com/repos/fixture/swapz/actions/runs/"
            "12345/attempts/1/jobs?per_page=100",
        ])

        # Invalid source identities must not leak into diagnostics or call GitHub.
        environment["GITHUB_SHA"] = "private-untrusted-source-token"
        code, output, errors, requested_urls = census(passing_jobs)
        self.assertNotEqual(code, 0)
        self.assertEqual(output, "")
        self.assertIn("tested_sha=invalid", errors)
        self.assertIn("phase=exact-sha-census", errors)
        self.assertNotIn("private-untrusted-source-token", errors)
        self.assertEqual(requested_urls, [])

class CiFailureDiagnosticContract(unittest.TestCase):
    """Synthetic rootless diagnostics must never misrepresent CI outcomes."""

    @classmethod
    def setUpClass(cls):
        path = ROOT / "tests/tools/product_goals.py"
        spec = importlib.util.spec_from_file_location("ci_product_goals", path)
        cls.diagnostics = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.diagnostics)

    def test_first_causal_error_and_failure_categories(self):
        examples = (
            ("native-rootless",
             "src/kernel/codec.c:42:3: error: invalid operand\n"
             "make: *** [test-all] Error 1\n",
             2, "NATIVE_COMPILE", "codec.c:42"),
            ("runtime",
             "FAIL: test_range (__main__.NativeCase)\nTraceback\n"
             "AssertionError: expected safe offset\nFAILED (failures=1)\n",
             1, "RUNTIME_ASSERTION",
             "AssertionError: [private exception detail omitted]"),
            ("rootless",
             "BLOCKED: Operation not permitted when opening device\n",
             1, "HOST_PERMISSION", "Operation not permitted"),
            ("make-interface",
             "SOURCE_CONTRACT_MISMATCH: source sha differs\n",
             1, "SOURCE_CONTRACT", "SOURCE_CONTRACT_MISMATCH"),
            ("setup",
             "E: Failed to fetch archive from mirror\n",
             100, "INFRASTRUCTURE", "Failed to fetch"),
            ("rootless", "Terminated\n", 143,
             "CANCELLATION", "execution interrupted"),
            ("setup", "", 124, "INFRASTRUCTURE", "timed out"),
        )
        for suite, log, exit_code, category, evidence in examples:
            with self.subTest(suite=suite, category=category):
                result = self.diagnostics.diagnose_ci_failure(
                    log.splitlines(), exit_code, suite)
                self.assertNotEqual(result["status"], "PASS")
                self.assertEqual(result["category"], category)
                self.assertIn(evidence, result["reason"])
                self.assertIn("prerequisite", result)
        failed = self.diagnostics.diagnose_ci_failure(
            ["FAIL: test_range (__main__.NativeCase)",
             "AssertionError: expected safe offset",
             "FAILED (failures=1)"], 1, "runtime")
        self.assertEqual(failed["test"], "__main__.NativeCase.test_range")
        self.assertEqual(failed["first_error"],
                         "AssertionError: [private exception detail omitted]")
        self.assertNotIn("expected safe offset", failed["reason"])

    def test_expected_negative_output_is_not_the_causal_failure(self):
        negative_fixture = [
            "swapzctl format: REFUSED: pre-open identity: Permission denied",
            "BLOCKED: expected fixture import failed: No such device",
            "FAIL: test_runtime_boundary "
            "(__main__.NativeFixture.test_runtime_boundary)",
            "Traceback (most recent call last):",
            "AssertionError: wrong tail guard",
            "FAILED (failures=1)",
        ]
        result = self.diagnostics.diagnose_ci_failure(
            negative_fixture, 1, "native-rootless")
        self.assertEqual(result["category"], "RUNTIME_ASSERTION")
        self.assertEqual(
            result["test"],
            "__main__.NativeFixture.test_runtime_boundary")
        self.assertEqual(result["first_error"],
                         "AssertionError: [private exception detail omitted]")
        self.assertNotIn("wrong tail guard", result["reason"])
        self.assertNotIn("expected fixture import", result["reason"])

        source_contract = self.diagnostics.diagnose_ci_failure(
            [
                "FAIL: test_contract "
                "(__main__.SourceQualification.test_contract)",
                '  File "/repo/tests/runtime/native/source-contract-test.py", '
                "line 42, in test_contract",
                "ValueError: substring not found",
                "FAILED (errors=1)",
            ],
            1, "native-rootless")
        self.assertEqual(source_contract["category"], "SOURCE_CONTRACT")
        self.assertEqual(
            source_contract["test"],
            "__main__.SourceQualification.test_contract")
        self.assertEqual(source_contract["first_error"],
                         "ValueError: substring not found")

        # Authenticate the real source-controlled recipe, not a stale
        # hardcoded line from a previous Makefile layout.
        makefile_lines = (
            ROOT / "tests/suites/Makefile").read_text().splitlines()
        userspace_target_line = next(
            index for index, line in enumerate(makefile_lines)
            if line.startswith("test-userspace:"))
        userspace_recipe_index = userspace_target_line + 1
        self.assertTrue(
            makefile_lines[userspace_recipe_index].startswith("\t"))
        userspace_recipe_line = userspace_recipe_index + 1
        aborted = self.diagnostics.diagnose_ci_failure(
            [f"make[1]: *** [Makefile:{userspace_recipe_line}: "
             "test-userspace] Error 134"],
            2, "native-rootless")
        self.assertEqual(aborted["category"], "RUNTIME_ASSERTION")
        self.assertEqual(aborted["test"], "make:test-userspace")
        self.assertIn("Error 134", aborted["first_error"])

        fixture_error = self.diagnostics.diagnose_ci_failure(
            [
                "ERROR: setUpClass (__main__.NativeFixture)",
                "Traceback (most recent call last):",
                "KeyError: 'missing fixture key'",
                "FAILED (errors=1)",
            ],
            1, "runtime")
        self.assertEqual(fixture_error["category"], "RUNTIME_ASSERTION")
        self.assertEqual(
            fixture_error["test"], "__main__.NativeFixture.setUpClass")
        self.assertEqual(
            fixture_error["first_error"],
            "KeyError: [private exception detail omitted]")
        self.assertNotIn("missing fixture key", fixture_error["reason"])

    def test_skips_and_cancellation_cannot_pass_workflow_aggregation(self):
        workflow = (ROOT / ".github/workflows/project-goals.yml").read_text()
        self.assertIn("if: always()", workflow)
        self.assertIn('if [[ "$result" != success ]]; then', workflow)
        self.assertIn("cancel-in-progress: false", workflow)
        concurrency = workflow.split("concurrency:\n", 1)[1].split(
            "\nenv:\n", 1)[0]
        self.assertIn(
            "group: project-goals-${{ github.ref }}-${{ github.run_id }}",
            concurrency)
        self.assertIn("cancel-in-progress: false", concurrency)
        self.assertIn("fail-fast: false", workflow)

    def test_ci_runner_is_quiet_on_success_and_redacts_failure(self):
        import json
        import os

        module = ROOT / "tests/tools/product_goals.py"
        source = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
            text=True, check=True).stdout.strip()
        environment = os.environ.copy()
        environment["GITHUB_SHA"] = source
        environment["GITHUB_JOB"] = "synthetic"
        command = ["python3", "-B", str(module), "ci-run", "--suite",
                   "synthetic", "--", "python3", "-c"]
        log = ROOT / "build/ci-logs/synthetic.log"
        log.unlink(missing_ok=True)
        try:
            successful = subprocess.run(
                command + ["print('no success transcript')"], cwd=ROOT,
                env=environment, capture_output=True, text=True, timeout=12)
            self.assertEqual(successful.returncode, 0, successful.stderr)
            self.assertEqual(successful.stdout, "")
            self.assertFalse(log.exists())
            failed = subprocess.run(
                command + [
                    "import sys; sys.stderr.write("
                    "'AssertionError: token=privatevalue ' + 'x' * 5000 + "
                    "' token=tailprivate\\n'); sys.exit(3)"],
                cwd=ROOT, env=environment, capture_output=True,
                text=True, timeout=12)
            self.assertEqual(failed.returncode, 3)
            self.assertIn("SWAPZ_CI_FAILURE=", failed.stdout)
            payload = json.loads(failed.stdout.split("SWAPZ_CI_FAILURE=", 1)[1])
            self.assertEqual(payload["tested_sha"], source)
            self.assertEqual(payload["status"], "FAIL")
            self.assertEqual(payload["category"], "RUNTIME_ASSERTION")
            self.assertEqual(payload["job"], "synthetic")
            self.assertTrue(log.exists())
            retained = log.read_text()
            self.assertIn("SWAPZ_CI_FAILURE=", retained)
            self.assertIn(source, retained)
            self.assertIn("[truncated]", retained)
            for secret in ("privatevalue", "tailprivate"):
                self.assertNotIn(secret, retained)
                self.assertNotIn(secret, failed.stdout)

            cancel_log = ROOT / "build/ci-logs/synthetic-cancel.log"
            cancel_log.unlink(missing_ok=True)
            cancelled = subprocess.run(
                ["python3", "-B", str(module), "ci-run", "--suite",
                 "synthetic-cancel", "--", "python3", "-c",
                 "import os, signal; "
                 "os.kill(os.getpid(), signal.SIGTERM)"],
                cwd=ROOT, env=environment, capture_output=True,
                text=True, timeout=12)
            self.assertEqual(cancelled.returncode, 1, cancelled.stderr)
            self.assertIn("SWAPZ_CI_FAILURE=", cancelled.stdout)
            cancelled_payload = json.loads(
                cancelled.stdout.split("SWAPZ_CI_FAILURE=", 1)[1])
            self.assertEqual(cancelled_payload["status"], "CANCELLED")
            self.assertEqual(cancelled_payload["category"], "CANCELLATION")
            self.assertEqual(cancelled_payload["tested_sha"], source)
            self.assertTrue(cancel_log.exists())
            self.assertIn('"status": "CANCELLED"',
                          cancel_log.read_text())

            environment["GITHUB_SHA"] = "0" * 40
            mismatch = subprocess.run(
                command + ["print('must not execute')"], cwd=ROOT,
                env=environment, capture_output=True, text=True, timeout=12)
            self.assertNotEqual(mismatch.returncode, 0)
            self.assertIn("SOURCE_CONTRACT", mismatch.stdout)
        finally:
            log.unlink(missing_ok=True)
            (ROOT / "build/ci-logs/synthetic-cancel.log").unlink(
                missing_ok=True)


if __name__ == "__main__":
    unittest.main()
