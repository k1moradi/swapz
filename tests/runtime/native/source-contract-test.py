#!/usr/bin/env python3
"""Fail-closed source qualifications for *real* swapz vs codec-only smoke.

This is not a replacement for live kernel BIO/GC tests. It prevents CI and
future privileged harnesses from accidentally selecting the old swapz module
or the standalone memory-only research smoke instead of the real DM target.
"""
from collections import Counter
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[3]
DM = (ROOT / "src/kernel/dm-target.c").read_text()
ENGINE = (ROOT / "src/kernel/engine.c").read_text()
AUTH = (ROOT / "src/kernel/authority.c").read_text()
CODEC = (ROOT / "src/kernel/codec.c").read_text()
MK = (ROOT / "src/kernel/Makefile").read_text()
README = (ROOT / "docs/README.md").read_text()
PRIMARY = (ROOT / "src/userspace/swapz-primary.c").read_text()
SWAPZCTL = (ROOT / "src/userspace/swapzctl.c").read_text()
PACKAGE_DKMS = (ROOT / "packaging/package-dkms.sh").read_text()
MANDATORY_ROOTLESS_PYTHON_SUITES = (
    "tests/runtime/native/source-contract-test.py",
    "tests/runtime/native/primary-lifecycle-audit-test.py",
    "tests/runtime/native/primary-lifecycle-nullblk-qualifier-test.py",
    "tests/runtime/native/primary-real-swap-test.py",
    "tests/runtime/benchmark/io-replay-test.py",
    "tests/runtime/native/make-interface-test.py",
    "tests/runtime/native/test-report-test.py",
    "tests/runtime/native/production-readiness-test.py",
    "tests/runtime/native/package-dkms-test.py",
    "tests/runtime/native/systemd/swapz-primary-systemd-test.py",
    "tests/runtime/native/physical-swap-probe-test.py",
    "tests/runtime/native/live-swap-supervisor-test.py",
)


def _raw_body(symbol: str) -> str:
    match = re.search(r"static\s+(?:int|void|bool|u64|unsigned\s+long|enum\s+hrtimer_restart|const\s+u8\s*\*)\s*" + re.escape(symbol) +
                      r"\s*\([^;]*?\)\s*\{", DM, re.S)
    if not match:
        raise AssertionError(f"Missing production symbol {symbol}")
    start = match.end()
    depth = 1
    for pos in range(start, len(DM)):
        if DM[pos] == "{":
            depth += 1
        elif DM[pos] == "}":
            depth -= 1
            if depth == 0:
                return DM[start:pos]
    raise AssertionError("Unclosed function: " + symbol)


def body(symbol: str) -> str:
    source = _raw_body(symbol)
    if symbol == "swapz_status":
        return source + "\n" + status_format_sequence(source)
    return source


def source_body(symbol: str, source: str) -> str:
    match = re.search(r"(?:static\s+)?(?:int|void|swapz_u8|swapz_u16|swapz_u32)\s+" + re.escape(symbol) +
                      r"\s*\([^;]*?\)\s*\{", source, re.S)
    if not match:
        raise AssertionError(f"Missing source symbol {symbol}")
    start = match.end()
    depth = 1
    for pos in range(start, len(source)):
        if source[pos] == "{":
            depth += 1
        elif source[pos] == "}":
            depth -= 1
            if depth == 0:
                return source[start:pos]
    raise AssertionError("Unclosed source function: " + symbol)


def status_format_sequence(source: str = "") -> str:
    """Reconstruct INFO status text across bounded DMEMIT calls."""
    if not source:
        source = _raw_body("swapz_status")
    source = source.split("case STATUSTYPE_INFO:", 1)[1]
    source = source.split("case STATUSTYPE_TABLE:", 1)[0]
    emitted = []
    cursor = 0
    while True:
        start = source.find("DMEMIT(", cursor)
        if start < 0:
            break
        pos = start + len("DMEMIT(")
        arg_start = pos
        depth = 1
        in_string = False
        escaped = False
        while pos < len(source) and depth:
            char = source[pos]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
            elif char == '"':
                in_string = True
            elif char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
            pos += 1
        if depth:
            raise AssertionError("Unclosed DMEMIT in swapz_status")
        call = source[arg_start:pos - 1]
        literals = re.findall(r'"([^"\\]*(?:\\.[^"\\]*)*)"', call)
        if literals:
            text = "".join(literals)
            if not text.startswith("status_snapshot_error="):
                emitted.append(text)
        cursor = pos
    return "".join(emitted)


class SwapzProductionSourceQualification(unittest.TestCase):
    def test_rootless_runner_registers_every_mandatory_python_suite_once(self):
        runner = (ROOT / "tests/tools/test-rootless.sh").read_text(
            encoding="utf-8")
        for relative_path in MANDATORY_ROOTLESS_PYTHON_SUITES:
            with self.subTest(relative_path=relative_path):
                self.assertTrue(
                    (ROOT / relative_path).is_file(),
                    f"mandatory rootless suite missing: {relative_path}")
                invocation = f"python3 -B {relative_path} -v"
                self.assertEqual(
                    runner.count(invocation), 1,
                    f"mandatory rootless suite must run exactly once: "
                    f"{relative_path}")

    def test_package_and_primary_share_global_mutation_lock(self):
        mutation = source_body("swapz_primary_run_mutating_action", PRIMARY)
        command = source_body("swapz_primary_command", PRIMARY)
        self.assertIn(
            '#define SWAPZ_PRIMARY_MUTATION_LOCK_DIRECTORY "/run/lock/swapz"',
            PRIMARY)
        self.assertIn(
            '#define SWAPZ_PRIMARY_MUTATION_LOCK_NAME "package.lock"',
            PRIMARY)
        self.assertIn(
            'package_lock="/run/lock/swapz/package.lock"', PACKAGE_DKMS)
        lock_position = mutation.index("swapz_primary_mutation_lock()")
        for operation in (
                "swapz_primary_prepare_metadata()",
                "swapz_primary_start_prepared()",
                "swapz_primary_stop_active()",
                "swapz_primary_recover()"):
            self.assertIn(operation, mutation)
            self.assertLess(lock_position, mutation.index(operation))
        for action in (
                "SWAPZ_PRIMARY_MUTATING_PREPARE",
                "SWAPZ_PRIMARY_MUTATING_START",
                "SWAPZ_PRIMARY_MUTATING_STOP",
                "SWAPZ_PRIMARY_MUTATING_RECOVER"):
            self.assertIn(action, command)
        self.assertNotIn("swapz_primary_prepare_metadata()", command)
        self.assertNotIn("swapz_primary_start_prepared()", command)
        self.assertNotIn("swapz_primary_stop_active()", command)
        self.assertNotIn("swapz_primary_recover()", command)

    def test_native_make_stage_keeps_analyzer_contract_discovered(self):
        relative_path = (
            "tests/runtime/native/codec/anon-page-analyzer-test.py")
        suites = (ROOT / "tests/suites/Makefile").read_text(
            encoding="utf-8")
        self.assertTrue((ROOT / relative_path).is_file())
        self.assertEqual(
            suites.count(
                'python3 -B "$(NATIVE)/codec/anon-page-analyzer-test.py" '
                '"$(OUT)/anon-page-analyzer"'),
            1)
        self.assertIn(
            "test-predictor: $(OUT)/predictor-qualification "
            "test-anon-page-analyzer", suites)
        self.assertIn("test-all: test-codec test-predictor", suites)

    def test_native_sanitizers_fail_hard_in_ci(self):
        suites = (ROOT / "tests/suites/Makefile").read_text(encoding="utf-8")
        workflow = (
            ROOT / ".github/workflows/product-codec.yml").read_text(
                encoding="utf-8")
        self.assertIn(
            "-fsanitize=address,undefined -fno-sanitize-recover=all "
            "-fno-omit-frame-pointer",
            suites)
        self.assertIn(
            "ASAN_OPTIONS: halt_on_error=1:abort_on_error=1:detect_leaks=1",
            workflow)
        self.assertIn(
            "UBSAN_OPTIONS: halt_on_error=1:print_stacktrace=1",
            workflow)
        self.assertIn("TSAN_OPTIONS: halt_on_error=1", workflow)

    def test_product_codec_runs_for_every_main_push(self):
        workflow = (
            ROOT / ".github/workflows/product-codec.yml").read_text(
                encoding="utf-8")
        trigger = workflow.split("jobs:", 1)[0]
        self.assertIn("push:\n    branches: [main]", trigger)
        self.assertNotIn(
            "paths:", trigger,
            "exact-source production-C evidence cannot use path-filtered pushes")

    def test_owned_nullblk_lifecycle_interruptions_are_test_only(self):
        primary = PRIMARY
        start = source_body("swapz_primary_start_prepared", primary)
        stop = source_body("swapz_primary_stop_active", primary)
        recover = source_body("swapz_primary_recover", primary)
        self.assertIn("#ifdef SWAPZ_PRIMARY_OWNED_NULLBLK_TEST", primary)
        self.assertIn(
            'getenv("SWAPZ_PRIMARY_TEST_INTERRUPT_AFTER")', primary)
        self.assertIn(
            "#define SWAPZ_PRIMARY_TEST_INTERRUPT_AFTER(phase) do { } while (0)",
            primary)
        for phase in (
                "start-starting", "start-header-written",
                "start-module-inserted", "start-module-loaded",
                "start-mapper-resumed", "start-mkswap", "start-swapon"):
            self.assertIn(
                f'SWAPZ_PRIMARY_TEST_INTERRUPT_AFTER("{phase}")', start)
        self.assertIn(
            'SWAPZ_PRIMARY_TEST_INTERRUPT_AFTER("start-mapper-inactive")',
            source_body("swapz_primary_dm_create_mapper", primary))
        for phase in ("stop-stopping", "stop-swapoff"):
            self.assertIn(
                f'SWAPZ_PRIMARY_TEST_INTERRUPT_AFTER("{phase}")', stop)
        for phase in (
                "recover-recovering", "recover-swapoff", "recover-mapper-removed",
                "recover-module-unloaded",
                "recover-restored"):
            self.assertIn(
                f'SWAPZ_PRIMARY_TEST_INTERRUPT_AFTER("{phase}")', recover)
        self.assertLess(
            start.index("swapz_primary_activate_mapper_swap("),
            start.index("active_state.stage = SWAPZ_PRIMARY_STAGE_ACTIVE"))
        self.assertLess(
            stop.index("swapz_primary_deactivate_mapper_swap("),
            stop.index("swapz_primary_dm_remove_mapper("))
        self.assertLess(
            recover.index("swapz_primary_deactivate_mapper_swap("),
            recover.index("swapz_primary_dm_remove_mapper("))
        preflight = source_body("swapz_primary_target_preflight", primary)
        prepare = source_body("swapz_primary_prepare_metadata", primary)
        self.assertLess(
            preflight.index("swapz_primary_partuuid_normalize(partuuid"),
            preflight.index("memset(target, 0, sizeof(*target))"))
        self.assertIn(
            "swapz_primary_target_inspect(expected_partuuid, target)",
            preflight)
        self.assertIn("target.partuuid, &target", prepare)

        existing_mapper = source_body(
            "swapz_primary_dm_existing_mapper_ioctl_initialize", primary)
        self.assertIn(
            "io, buffer_bytes, NULL, expected_uuid", existing_mapper)
        for symbol in (
                "swapz_primary_dm_table_load_buffer",
                "swapz_primary_dm_status_fd",
                "swapz_primary_dm_inactive_target_count_fd",
                "swapz_primary_dm_table_query_fd",
                "swapz_primary_dm_dependencies_match_fd",
                "swapz_primary_dm_create_mapper",
                "swapz_primary_dm_remove_mapper"):
            self.assertIn(
                "swapz_primary_dm_existing_mapper_ioctl_initialize(",
                source_body(symbol, primary),
                f"{symbol} must select an existing mapper by UUID only")
        create = source_body("swapz_primary_dm_create_mapper", primary)
        self.assertRegex(
            create,
            r"swapz_primary_dm_ioctl_initialize\([^;]*mapper_name\s*,\s*mapper_uuid",
            "DM_DEV_CREATE must bind both the expected name and UUID")
        self.assertNotRegex(
            primary.replace(create, "", 1),
            r"swapz_primary_dm_ioctl_initialize\([^;]*mapper_name\s*,\s*mapper_uuid",
            "existing mapper lookups must not provide both Device Mapper selectors")

        rehearsal = (
            ROOT / "tests/tools/qualify-primary-lifecycle-nullblk.sh").read_text()
        for phase in (
                "start-starting", "start-header-written",
                "start-module-inserted", "start-module-loaded",
                "start-mapper-inactive", "start-mapper-resumed",
                "start-mkswap", "start-swapon",
                "stop-stopping", "stop-swapoff",
                "stop-mapper-removed", "stop-module-unloaded",
                "stop-restored", "recover-recovering", "recover-swapoff",
                "recover-mapper-removed", "recover-module-unloaded",
                "recover-restored"):
            self.assertIn(phase, rehearsal)
        self.assertIn(
            'SWAPZ_PRIMARY_TEST_INTERRUPT_AFTER="$phase"', rehearsal)
        self.assertIn('"$CONTROL" primary recover', rehearsal)
        self.assertIn(
            "PASS_LOADED_PRIMARY_NULLBLK_INTERRUPTION_RECOVERY=cases:18",
            rehearsal)
        self.assertEqual(
            rehearsal.count('"$CONTROL" primary prepare 2>&1'), 2)
        self.assertNotIn(
            'output="$("$CONTROL" primary prepare 2>&1)', rehearsal)
        self.assertNotIn(
            'prepare_output="$("$CONTROL" primary prepare 2>&1)', rehearsal)
        self.assertIn(
            'timeout --signal=TERM --kill-after=10s 90s \\\n'
            '\t\t"$CONTROL" primary prepare 2>&1', rehearsal)
        self.assertIn(
            'timeout --signal=TERM --kill-after=10s 90s \\\n'
            '\t"$CONTROL" primary prepare 2>&1', rehearsal)
        self.assertIn(
            'timeout --signal=TERM --kill-after=10s 90s \\\n'
            '\t\t"$CONTROL" primary plan 2>&1', rehearsal)
        self.assertIn(
            'TEST_BASE="/var/lib/swapz-primary-owned-nullblk-test-$TOKEN"',
            rehearsal)
        self.assertIn(
            '"$TEST_BASE" != '
            '"/var/lib/swapz-primary-owned-nullblk-test-$TOKEN"',
            rehearsal)
        self.assertEqual(
            rehearsal.count("TOKEN=\"$(od -An -N8 -tx1 /dev/urandom"), 1)
        self.assertNotIn(
            "TEST_BASE=/var/lib/swapz-primary-owned-nullblk-test\n",
            rehearsal)

    def test_physical_real_swap_source_admission_is_unprivileged(self):
        child = (
            ROOT / "tests/tools/qualify-primary-real-swap.py").read_text()
        parent = (
            ROOT / "tests/tools/qualify-primary-real-swap-parent.py").read_text()

        self.assertNotIn("_check_git_source", child)
        self.assertNotIn('["git",', child)
        self.assertIn("class SourceAdmissionClient:", child)
        self.assertIn("socket.SO_PEERCRED", child)
        self.assertIn('admission.require(f"cycle-{index}")', child)
        self.assertIn('admission.require("final")', child)
        self.assertIn("def _check_git_source(", parent)
        self.assertIn('_trusted_executable("git")', parent)
        self.assertIn('"ls-remote"', parent)
        self.assertIn("source_admission_parent_must_be_unprivileged", parent)
        self.assertIn("socket.SO_PEERCRED", parent)
        for forbidden in ('["swapon"', '["swapoff"', '["dmsetup", "remove"'):
            self.assertNotIn(forbidden, parent)

    def test_physical_lifecycle_qualification_seam_is_noninstalled_and_guarded(self):
        primary = PRIMARY
        command = source_body("swapz_primary_command", primary)
        live_hashes = source_body("swapz_primary_live_artifact_hashes", primary)
        runtime_gate = source_body(
            "swapz_primary_lifecycle_runtime_enabled", primary)
        privileged_gate = source_body(
            "swapz_primary_privileged_execution_enabled", primary)
        plan = source_body("swapz_primary_read_only_plan", primary)
        production_authorization = source_body(
            "swapz_primary_production_execution_authorized", primary)
        boot_verify = (
            ROOT / "packaging/swapz-primary-boot-verify").read_text()
        mapper_service = (
            ROOT / "packaging/swapz-primary-mapper.service").read_text()
        rootless = (ROOT / "tests/tools/test-rootless.sh").read_text()

        self.assertIn("#define SWAPZ_PRIMARY_EXECUTION_ENABLED 1", primary)
        self.assertIn(
            "#elif defined(SWAPZ_PRIMARY_PHYSICAL_QUALIFICATION_TEST)",
            primary)
        self.assertIn(
            "#error \"physical lifecycle qualification requires installed "
            "qualified control path\"",
            primary)
        self.assertIn(
            "#error \"primary lifecycle test modes are mutually exclusive\"",
            primary)
        self.assertIn(
            'getenv("SWAPZ_PRIMARY_PHYSICAL_QUALIFICATION")', runtime_gate)
        self.assertIn('!strcmp(enabled, "1")', runtime_gate)
        self.assertIn(
            "swapz_primary_production_execution_authorized()", runtime_gate)
        self.assertIn(
            "SWAPZ_PRIMARY_EXECUTION_RUNTIME_DIRECTORY",
            production_authorization)
        self.assertIn(
            "swapz_primary_execution_record_matches(",
            production_authorization)
        self.assertIn(
            "swapz_primary_configured_target(&target)",
            production_authorization)
        self.assertIn(
            "SWAPZ_BUILD_SOURCE_SHA", production_authorization)
        self.assertIn("SWAPZ_PRIMARY_EXECUTION_ENABLED", privileged_gate)
        self.assertIn(
            "swapz_primary_lifecycle_runtime_enabled()", privileged_gate)
        self.assertIn(
            "!swapz_primary_privileged_execution_enabled()", command)
        self.assertIn(
            "swapz_primary_privileged_execution_enabled()", plan)
        self.assertIn(
            '"\\\"privileged_execution_enabled\\\":%s,"', plan)
        self.assertNotIn(
            '"\\\"privileged_execution_enabled\\\":false,"', plan)
        self.assertIn(
            "SWAPZ_PRIMARY_PHYSICAL_QUALIFIED_CONTROL", live_hashes)
        self.assertIn(
            "swapz_primary_hash_regular_path(control_path, 1", live_hashes)
        self.assertIn(
            "-DSWAPZ_PRIMARY_PHYSICAL_QUALIFICATION_TEST=1", rootless)
        self.assertIn(
            'SWAPZ_PRIMARY_PHYSICAL_QUALIFIED_CONTROL="/usr/local/sbin/swapzctl"',
            rootless)
        self.assertNotIn(
            "SWAPZ_PRIMARY_PHYSICAL_QUALIFICATION_TEST",
            (ROOT / "Makefile").read_text())
        self.assertIn(
            "commit_runtime_authorization", boot_verify)
        self.assertIn(
            "clear_runtime_authorization", boot_verify)
        self.assertLess(
            boot_verify.index("clear_runtime_authorization",
                              boot_verify.index("preflight_boot()")),
            boot_verify.index("validate_arm_file",
                              boot_verify.index("preflight_boot()")))
        self.assertIn("RuntimeDirectory=swapz", mapper_service)
        self.assertIn("RuntimeDirectoryMode=0700", mapper_service)
        self.assertLess(
            mapper_service.index(
                "ExecStartPre=@SWAPZ_SBINDIR@/swapz-primary-boot-verify preflight"),
            mapper_service.index(
                "ExecStartPre=-@SWAPZ_SBINDIR@/swapzctl primary recover"))

    def test_primary_manager_target_is_runtime_selected(self):
        # Historical trial paths and device numbers may appear in fixtures or
        # recovery documentation, but must never become production manager
        # constants. The configured PARTUUID is resolved and its observed
        # identity/geometry is carried through the transaction manifest.
        for fixed_target in (
                "/dev/sda4", "8:4", "17179869184"):
            self.assertNotIn(fixed_target, PRIMARY)
        self.assertIn("swapz_primary_selected_target.device_bytes", PRIMARY)
        self.assertIn("swapz_primary_selected_target.device_major", PRIMARY)
        self.assertIn("swapz_primary_selected_target.device_minor", PRIMARY)
        self.assertIn("swapz_primary_configured_target(&target)", PRIMARY)
        self.assertIn("manifest.target = target", PRIMARY)

    def test_standalone_formatter_is_identity_bound_and_never_discards(self):
        self.assertNotIn(
            'if (argc == 3 && !strcmp(argv[1], "format"))', SWAPZCTL)
        for required in (
                "--expect-major-minor", "--expect-bytes",
                "--expect-partuuid", "--expect-parent-major-minor",
                "--expect-parent-model", "--expect-parent-transport",
                "O_RDWR | O_EXCL | O_CLOEXEC",
                "BLKROGET",
                "format_device_with_ops",
                "format_report_uncertain",
                "swapz_primary_target_config_read(configured_partuuid)",
                "format_default_authorized_target_verify",
                "format_authorized_opened_verify",
                "format_parent_only_partition",
                "format_usb_transport_path",
                "target identity changed before header write",
                "SWZ header readback mismatch"):
            self.assertIn(required, SWAPZCTL)
        self.assertIn("ssize_t count = pwrite(fd, bytes, length, 0);",
                      SWAPZCTL)
        self.assertNotIn("pwrite(fd, bytes + done", SWAPZCTL)
        for destructive in ("BLKDISCARD", "FITRIM"):
            self.assertNotIn(destructive, SWAPZCTL)
        for fixed_target in (
                "/dev/sda1", "/dev/sda4", "124787884032", "f13428f6-01",
                "Multi-Card"):
            self.assertNotIn(fixed_target, SWAPZCTL)

    def test_lane_gap_observation_only_and_single_owner(self):
        header = (ROOT / "src/kernel/lane-gap.h").read_text()
        engine_header = (ROOT / "src/kernel/engine.h").read_text()
        helper_names = (
            "swapz_lane_gap_note_foreign_write", "swapz_lane_gap_publish",
            "swapz_lane_gap_submit", "swapz_lane_gap_note_owner_read",
            "swapz_lane_gap_sync_sealed", "swapz_lane_gap_sync_published",
            "swapz_lane_gap_sync_window_begin",
            "swapz_lane_gap_sync_window_end", "swapz_lane_gap_ack",
        )
        for symbol in helper_names:
            source = body(symbol)
            for forbidden in ("wait_for_completion(", "mutex_lock(",
                              "spin_lock(", "queue_work(", "kmalloc(",
                              "kzalloc(", "vmalloc("):
                self.assertNotIn(forbidden, source)
        self.assertIn('#include "codec.h"', header)
        self.assertIn("struct swapz_lane_gap_parts", header)
        self.assertNotIn("mutex_", header)
        self.assertNotIn("wait_for_completion(", header)
        self.assertIn("write_sealed", engine_header)
        self.assertIn("write_published", engine_header)
        self.assertGreaterEqual(ENGINE.count("io.write_sealed"), 2)
        self.assertGreaterEqual(ENGINE.count("io.write_published"), 2)
        self.assertIn("struct swapz_bio_ref {", DM)
        for field in ("lane_admitted_ns", "lane_owned_ns", "published_ns",
                      "published_deferred"):
            self.assertIn(field + ";", DM)
        self.assertIn("atomic64_t lane_profile_epoch;", DM)
        self.assertIn("u64 lane_prev_epoch;", DM)
        self.assertIn("u64 lane_epoch;", DM)
        # t3 is the seal start (commit_start_ns), never a post-prepare mark.
        self.assertNotIn("lane_seal_ns;", DM)
        self.assertNotIn("lane_prev_foreign", DM)
        self.assertIn("u64 lane_foreign_write_end_ns;", DM)
        self.assertIn("bool lane_sync_run_pending;", DM)
        self.assertIn("entry->lane_admitted_ns = entry->admitted_ns;",
                      body("swapz_map"))
        self.assertIn("entry->lane_owned_ns = owned_ns;",
                      body("swapz_worker_pass"))
        self.assertIn("entry->lane_owned_ns = ktime_get_ns();",
                      body("swapz_submitter_dispatch"))
        self.assertIn("ctx->write_admit_worker_samples++;",
                      body("swapz_worker_pass"))
        self.assertIn("ctx->write_admit_worker_wall_ns +=",
                      body("swapz_worker_pass"))
        epoch = body("swapz_message")
        self.assertIn("atomic64_inc(&ctx->lane_profile_epoch)", epoch)
        self.assertIn("WRITE_ONCE(ctx->lane_prev_valid, false)", epoch)
        self.assertIn("WRITE_ONCE(ctx->sync4_last_done_ns, 0)", epoch)
        self.assertNotIn("lane_runs_submitted =", epoch)
        submit = body("swapz_lane_gap_submit")
        self.assertIn("atomic64_read(&ctx->lane_profile_epoch)", submit)
        self.assertIn("READ_ONCE(ctx->lane_prev_epoch) == epoch", submit)
        self.assertIn("page_count > ctx->batch_count - first_page", submit)
        self.assertIn("ctx->planned_to_batch[planned_index]", submit)
        self.assertIn("WRITE_ONCE(ctx->lane_prev_valid, false)", submit)
        worker = body("swapz_worker")
        self.assertIn("mutex_lock(&ctx->ordered_owner)", worker)
        self.assertIn("swapz_worker_pass(ctx)", worker)
        self.assertIn("mutex_unlock(&ctx->ordered_owner)", worker)
        submitter = body("swapz_submitter_dispatch")
        self.assertIn("mutex_unlock(&ctx->ordered_owner)", submitter)
        completion = body("swapz_async_lower_write_done")
        self.assertNotIn("lane_prev_", completion)
        complete = body("swapz_complete")
        self.assertLess(complete.index("swapz_lane_gap_ack(ctx, entry);"),
                        complete.index("bio_endio(bio);"))
        self.assertIn("atomic64_inc(count)", body("swapz_lane_gap_ack"))
        self.assertIn("entry->ack_batch->bins[mode][bin]++",
                      body("swapz_lane_gap_ack"))
        self.assertIn("swapz_lane_gap_ack_flush(ctx, &acknowledgements)",
                      body("swapz_completion_work"))
        self.assertIn("swapz_lane_gap_ack_flush(ctx, &acknowledgements)",
                      body("swapz_deliver_bio_list"))
        self.assertIn("entry->ack_batch = NULL;", body("swapz_map"))
        self.assertIn("atomic64_add(", body("swapz_lane_gap_ack"))
        lower = body("swapz_lower")
        self.assertIn("lane_epoch_before", lower)
        # Only the one run the engine sealed is consumed; every other lower
        # WRITE (GC relocation, single-page RAW) is foreign by its end time.
        self.assertIn("ctx->lane_sync_window &&\n\t    ctx->lane_sync_run_pending", lower)
        self.assertIn("ctx->lane_sync_run_pending = false;", lower)
        self.assertIn("swapz_lane_gap_note_foreign_write(ctx, section_end)",
                      lower)
        # Accounting follows the synchronous lower WRITE, never precedes it.
        self.assertLess(lower.index("swapz_dm_io(&req, &region, &bitmap)"),
                        lower.index("swapz_lane_gap_submit(ctx, lane_epoch,"))
        self.assertIn("ctx->lane_sync_published_pages", lower)
        self.assertIn("ctx->lane_sync_run_pages", lower)
        self.assertIn("lane_seal_ns ? lane_seal_ns : section_start", lower)
        submit = body("swapz_lane_gap_submit")
        self.assertIn("ctx->lane_foreign_write_end_ns > previous_done_ns",
                      submit)
        async_submit = body("swapz_submit_inflight_write")
        self.assertIn("swapz_lane_gap_submit(ctx, inflight->lane_epoch, 0, "
                      "inflight->count,\n\t\t\t      inflight->commit_start_ns, "
                      "inflight->lower_start_ns);", async_submit)
        # Only a submitted run is counted, after the asynchronous dm_io.
        self.assertLess(async_submit.index("swapz_dm_io(&req, &region, NULL)"),
                        async_submit.index("swapz_lane_gap_submit("))
        self.assertLess(async_submit.index("ctx->pipeline_async_runs++;"),
                        async_submit.index("swapz_lane_gap_submit("))
        flush = body("swapz_flush_window")
        self.assertLess(flush.index("inflight->commit_start_ns = prepare_start;"),
                        flush.index("swapz_engine_prepare_batched_run("))
        self.assertNotIn("prepare_end", flush)
        self.assertIn("swapz_lane_gap_sync_window_begin(ctx, committed, "
                      "section_start);", flush)
        self.assertIn("swapz_lane_gap_sync_window_begin(ctx, 0, prepare_start);",
                      flush)
        self.assertIn("swapz_lane_gap_sync_sealed(ctx, prepared);", flush)
        self.assertEqual(flush.count("swapz_lane_gap_sync_window_end("), 2)
        begin = body("swapz_lane_gap_sync_window_begin")
        self.assertIn("ctx->lane_sync_published_pages = committed;", begin)
        self.assertIn("ctx->lane_sync_seal_ns = seal_ns;", begin)
        window_end = body("swapz_lane_gap_sync_window_end")
        self.assertIn("ctx->lane_sync_run_pending || ctx->lane_sync_done_ns",
                      window_end)
        self.assertIn("WRITE_ONCE(ctx->lane_prev_valid, false);", window_end)
        sync_sealed = body("swapz_lane_gap_sync_sealed")
        # GC compaction drives the same engine with no window open.
        self.assertIn("if (!ctx->lane_sync_window)\n\t\treturn;", sync_sealed)
        self.assertIn("ctx->lane_sync_run_pages = sealed_pages;", sync_sealed)
        self.assertIn("ctx->lane_sync_run_pending = true;", sync_sealed)
        self.assertNotIn("ktime_get_ns()", sync_sealed)
        sync_publish = body("swapz_lane_gap_sync_published")
        self.assertIn("if (!ctx->lane_sync_window)\n\t\treturn;", sync_publish)
        self.assertIn("published_pages != ctx->lane_sync_run_pages",
                      sync_publish)
        self.assertNotIn("!ctx->lane_sync_epoch", sync_publish)
        self.assertIn("entry->published_ns = published_ns;", sync_publish)
        self.assertIn("ctx->lane_sync_seal_ns = published_ns;", sync_publish)
        self.assertIn("atomic64_inc(&ctx->lane_profile_epoch);",
                      body("swapz_resume"))
        self.assertIn("ctx->lane_gap_owner_read_ns +=", submit)
        constructor = body("swapz_ctr")
        self.assertIn("ctx->engine.io.write_sealed = "
                      "swapz_lane_gap_sync_sealed;", constructor)
        self.assertIn("ctx->engine.io.write_published = "
                      "swapz_lane_gap_sync_published;", constructor)
        self.assertIn("atomic64_set(&ctx->lane_profile_epoch, 1);",
                      constructor)
        status = body("swapz_status")
        for key in ("lane_gap_wall_ns", "lane_gap_invalid",
                    "ack_dwell_deferred_gt_1ms",
                    "lane_successor_admitted_by_completion_16_plus"):
            self.assertIn(key + "=%llu", status)
        for forbidden in ("if (ctx->lane_gap_", "if (ctx->ack_dwell_"):
            self.assertNotIn(forbidden, body("swapz_worker_pass"))

    def test_lane_gap_chronology_executes_actual_helpers(self):
        """Run the real ID178 chronology bodies through boundary sequences."""
        import subprocess
        import tempfile
        signatures = {
            "swapz_lane_gap_note_foreign_write":
                "static void swapz_lane_gap_note_foreign_write("
                "struct swapz_dm *ctx, u64 end_ns)",
            "swapz_lane_gap_publish":
                "static void swapz_lane_gap_publish(struct swapz_dm *ctx, "
                "u64 epoch, u64 done_ns, u64 observed_ns, u64 published_ns, "
                "bool success)",
            "swapz_lane_gap_submit":
                "static void swapz_lane_gap_submit(struct swapz_dm *ctx, "
                "u64 epoch, swapz_u8 first_page, swapz_u8 page_count, "
                "u64 seal_ns, u64 submit_ns)",
            "swapz_lane_gap_sync_sealed":
                "static void swapz_lane_gap_sync_sealed(void *opaque, "
                "swapz_u8 sealed_pages)",
            "swapz_lane_gap_sync_published":
                "static void swapz_lane_gap_sync_published(void *opaque, "
                "swapz_u8 published_pages)",
            "swapz_lane_gap_sync_window_begin":
                "static void swapz_lane_gap_sync_window_begin("
                "struct swapz_dm *ctx, swapz_u8 committed, u64 seal_ns)",
            "swapz_lane_gap_sync_window_end":
                "static void swapz_lane_gap_sync_window_end("
                "struct swapz_dm *ctx, int error)",
        }
        functions = "\n".join(
            signature + "\n{" + body(name) + "}\n"
            for name, signature in signatures.items())
        source = r"""
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include "lane-gap.h"
typedef unsigned long long u64;
typedef long long s64;
typedef struct { s64 counter; } atomic64_t;
#define U64_MAX UINT64_MAX
#define READ_ONCE(value) (value)
#define WRITE_ONCE(value, new_value) ((value) = (new_value))
static s64 atomic64_read(const atomic64_t *value) { return value->counter; }
static u64 clock_ns;
static u64 ktime_get_ns(void) { return clock_ns; }
struct swapz_bio_ref {
    u64 lane_admitted_ns, lane_owned_ns, published_ns;
    bool published_deferred;
};
struct bio { struct swapz_bio_ref ref; };
struct swapz_pending_bio { struct bio *bio; };
#define dm_per_bio_data(bio, size) (&(bio)->ref)
struct swapz_dm {
    atomic64_t lane_profile_epoch;
    u64 lane_prev_epoch, lane_prev_done_ns, lane_prev_owner_ns;
    u64 lane_prev_published_ns, lane_foreign_write_end_ns;
    bool lane_prev_valid, lane_sync_window, lane_sync_run_pending;
    u64 lane_sync_epoch, lane_sync_seal_ns, lane_sync_done_ns;
    swapz_u8 lane_sync_published_pages, lane_sync_run_pages, batch_count;
    u64 lane_gap_pending_owner_read_ns, lane_gap_pending_owner_reads;
    u64 lane_runs_submitted, lane_gap_runs, lane_gap_wall_ns;
    u64 lane_gap_completion_wake_ns, lane_gap_publication_ns;
    u64 lane_gap_no_work_ns, lane_gap_admitted_unowned_ns;
    u64 lane_gap_staged_held_ns, lane_gap_seal_ns;
    u64 lane_gap_foreign_runs, lane_gap_foreign_ns;
    u64 lane_gap_unpaired_runs, lane_gap_invalid;
    u64 lane_gap_owner_read_ns, lane_gap_owner_reads;
    u64 lane_gap_successor_admitted_by_completion[SWAPZ_LANE_SUCCESSOR_BINS];
    u64 lane_gap_successor_owned_by_completion[SWAPZ_LANE_SUCCESSOR_BINS];
    struct swapz_pending_bio batch[4];
    swapz_u8 planned_to_batch[4];
};
FUNCTIONS
static struct bio bios[4];
static void window(struct swapz_dm *ctx, u64 admitted0, u64 owned0,
                   u64 admitted1, u64 owned1)
{
    unsigned int index;
    for (index = 0; index < 4; ++index) {
        bios[index].ref = (struct swapz_bio_ref){0};
        ctx->batch[index].bio = &bios[index];
        /* Planned order differs from batch order on purpose. */
        ctx->planned_to_batch[index] = (swapz_u8)(3 - index);
    }
    ctx->batch_count = 4;
    bios[3].ref.lane_admitted_ns = admitted0;
    bios[3].ref.lane_owned_ns = owned0;
    bios[2].ref.lane_admitted_ns = admitted1;
    bios[2].ref.lane_owned_ns = owned1;
    /* Already-published prefix pages carry earlier marks. */
    bios[1].ref.lane_admitted_ns = 1;
    bios[1].ref.lane_owned_ns = 1;
}
static u64 parts(const struct swapz_dm *ctx)
{
    return ctx->lane_gap_completion_wake_ns + ctx->lane_gap_publication_ns +
        ctx->lane_gap_no_work_ns + ctx->lane_gap_admitted_unowned_ns +
        ctx->lane_gap_staged_held_ns + ctx->lane_gap_seal_ns;
}
int main(void)
{
    static struct swapz_dm zero;
    struct swapz_dm ctx = zero;

    ctx.lane_profile_epoch.counter = 1;
    /* Paired: t0=100 t1=110 t2=120 a=125 s=140 t3=150 t4=160. */
    swapz_lane_gap_publish(&ctx, 1, 100, 110, 120, true);
    assert(ctx.lane_prev_valid);
    window(&ctx, 130, 140, 125, 150);
    swapz_lane_gap_submit(&ctx, 1, 0, 2, 150, 160);
    assert(ctx.lane_gap_runs == 1 && ctx.lane_gap_wall_ns == 60);
    assert(ctx.lane_gap_completion_wake_ns == 10);
    assert(ctx.lane_gap_publication_ns == 10);
    assert(ctx.lane_gap_no_work_ns == 5);
    assert(ctx.lane_gap_admitted_unowned_ns == 15);
    assert(ctx.lane_gap_staged_held_ns == 10 && ctx.lane_gap_seal_ns == 10);
    assert(parts(&ctx) == ctx.lane_gap_wall_ns);
    assert(ctx.lane_gap_successor_admitted_by_completion[0] == 1);
    assert(!ctx.lane_prev_valid && ctx.lane_runs_submitted == 1);

    /* Successor work admitted/owned by t0 lands in the 2-3 bins. */
    swapz_lane_gap_publish(&ctx, 1, 200, 205, 210, true);
    window(&ctx, 180, 190, 195, 220);
    swapz_lane_gap_submit(&ctx, 1, 0, 2, 230, 240);
    assert(ctx.lane_gap_successor_admitted_by_completion[2] == 1);
    assert(ctx.lane_gap_successor_owned_by_completion[1] == 1);
    assert(ctx.lane_gap_no_work_ns == 5 && parts(&ctx) == ctx.lane_gap_wall_ns);

    /* A planned range starting after a published prefix ignores it. */
    swapz_lane_gap_publish(&ctx, 1, 250, 251, 252, true);
    window(&ctx, 260, 261, 262, 263);
    swapz_lane_gap_submit(&ctx, 1, 1, 1, 264, 265);
    assert(ctx.lane_gap_runs == 3 && parts(&ctx) == ctx.lane_gap_wall_ns);

    /* A foreign WRITE ending inside the gap makes it foreign as a whole,
     * even when it ran before the predecessor was published. */
    ctx.lane_foreign_write_end_ns = 305;
    swapz_lane_gap_publish(&ctx, 1, 300, 310, 320, true);
    window(&ctx, 330, 331, 332, 333);
    swapz_lane_gap_submit(&ctx, 1, 0, 2, 340, 350);
    assert(ctx.lane_gap_foreign_runs == 1 && ctx.lane_gap_foreign_ns == 50);
    assert(ctx.lane_gap_runs == 3);
    /* A foreign WRITE that ended before t0 does not. */
    swapz_lane_gap_note_foreign_write(&ctx, 360);
    swapz_lane_gap_publish(&ctx, 1, 400, 401, 402, true);
    window(&ctx, 403, 404, 405, 406);
    swapz_lane_gap_submit(&ctx, 1, 0, 2, 407, 408);
    assert(ctx.lane_gap_runs == 4);

    /* profile_epoch between publication and submission: unpaired; a stale
     * finalizer can neither create nor clear a newer predecessor. */
    swapz_lane_gap_publish(&ctx, 1, 500, 501, 502, true);
    ctx.lane_profile_epoch.counter = 2;         /* swapz_message() */
    ctx.lane_prev_valid = false;
    window(&ctx, 503, 504, 505, 506);
    swapz_lane_gap_submit(&ctx, 2, 0, 2, 507, 508);
    assert(ctx.lane_gap_unpaired_runs == 1 && !ctx.lane_prev_valid);
    swapz_lane_gap_publish(&ctx, 1, 510, 511, 512, true);
    assert(!ctx.lane_prev_valid);
    swapz_lane_gap_publish(&ctx, 2, 520, 521, 522, true);
    swapz_lane_gap_publish(&ctx, 1, 530, 531, 532, false);
    assert(ctx.lane_prev_valid && ctx.lane_prev_done_ns == 520);
    window(&ctx, 525, 526, 527, 528);
    swapz_lane_gap_submit(&ctx, 0, 0, 2, 529, 540);
    assert(ctx.lane_gap_unpaired_runs == 2);

    /* GC drives the engine with no window open: hooks are inert. */
    ctx.lane_sync_window = false;
    swapz_lane_gap_sync_sealed(&ctx, 3);
    swapz_lane_gap_sync_published(&ctx, 3);
    assert(!ctx.lane_sync_run_pending && !ctx.lane_gap_invalid);

    /* Synchronous two-run window: second run seals at the first publish. */
    swapz_lane_gap_publish(&ctx, 2, 600, 601, 602, true);
    window(&ctx, 610, 611, 612, 613);
    swapz_lane_gap_sync_window_begin(&ctx, 0, 615);
    swapz_lane_gap_sync_sealed(&ctx, 1);
    assert(ctx.lane_sync_run_pending && ctx.lane_sync_run_pages == 1);
    ctx.lane_sync_run_pending = false;          /* swapz_lower consumes */
    ctx.lane_sync_epoch = 2;
    ctx.lane_sync_done_ns = 640;
    swapz_lane_gap_submit(&ctx, 2, ctx.lane_sync_published_pages,
                          ctx.lane_sync_run_pages, ctx.lane_sync_seal_ns, 620);
    assert(ctx.lane_gap_runs == 5 && parts(&ctx) == ctx.lane_gap_wall_ns);
    clock_ns = 650;
    swapz_lane_gap_sync_published(&ctx, 1);
    assert(bios[3].ref.published_ns == 650 && !bios[3].ref.published_deferred);
    assert(ctx.lane_prev_valid && ctx.lane_prev_done_ns == 640);
    assert(ctx.lane_sync_seal_ns == 650 && ctx.lane_sync_published_pages == 1);
    swapz_lane_gap_sync_sealed(&ctx, 1);
    ctx.lane_sync_run_pending = false;
    ctx.lane_sync_epoch = 0;                    /* profile_epoch race */
    ctx.lane_sync_done_ns = 680;
    swapz_lane_gap_submit(&ctx, 0, ctx.lane_sync_published_pages,
                          ctx.lane_sync_run_pages, ctx.lane_sync_seal_ns, 660);
    clock_ns = 690;
    swapz_lane_gap_sync_published(&ctx, 1);
    assert(bios[2].ref.published_ns == 690 && !ctx.lane_gap_invalid);
    assert(!ctx.lane_prev_valid);
    swapz_lane_gap_sync_window_end(&ctx, 0);
    assert(!ctx.lane_sync_window && !ctx.lane_gap_invalid);

    /* A sealed run that was never submitted without an engine error is an
     * accounting anomaly; with an error it only drops the predecessor. */
    swapz_lane_gap_publish(&ctx, 2, 700, 701, 702, true);
    swapz_lane_gap_sync_window_begin(&ctx, 0, 705);
    swapz_lane_gap_sync_sealed(&ctx, 1);
    swapz_lane_gap_sync_window_end(&ctx, -5);
    assert(!ctx.lane_gap_invalid && !ctx.lane_prev_valid);
    swapz_lane_gap_sync_window_begin(&ctx, 0, 710);
    swapz_lane_gap_sync_sealed(&ctx, 1);
    swapz_lane_gap_sync_window_end(&ctx, 0);
    assert(ctx.lane_gap_invalid == 1 && !ctx.lane_sync_run_pending);
    assert(ctx.lane_runs_submitted == ctx.lane_gap_runs +
           ctx.lane_gap_foreign_runs + ctx.lane_gap_unpaired_runs);
    return 0;
}
""".replace("FUNCTIONS", functions)
        with tempfile.TemporaryDirectory(prefix="swapz-lane-gap-") as temp:
            binary = Path(temp) / "lane-gap-chronology"
            compiled = subprocess.run(
                ["cc", "-std=c11", "-Wall", "-Wextra", "-Werror",
                 "-I", str(ROOT / "src/kernel"), "-x", "c", "-", "-o",
                 str(binary)], input=source, text=True,
                capture_output=True, timeout=30)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            executed = subprocess.run([str(binary)], cwd=temp,
                                      capture_output=True, text=True,
                                      timeout=5)
            self.assertEqual(executed.returncode, 0, executed.stderr)


    def test_raw_selected_codec_error_gates_success_ack(self):
        helper = body("swapz_wait_raw_selected_preparation")
        accept = body("swapz_accept_write")
        flush = body("swapz_flush_window")
        finalize = body("swapz_finalize_inflight_write")

        self.assertIn("SWAPZ_PREPARATION_RAW_SELECTED", helper)
        self.assertIn("wait_for_completion(&prepared->result_ready)", helper)
        self.assertIn("error = READ_ONCE(prepared->length)", helper)
        self.assertIn("return error < 0 ? error : 0;", helper)
        self.assertIn(
            "prepared_state != SWAPZ_PREPARATION_RAW_SELECTED", accept)
        self.assertLess(
            flush.index("swapz_wait_raw_selected_preparation(bio)"),
            flush.index("acknowledgements.delivered_ns = ktime_get_ns();"))
        self.assertLess(
            finalize.index("swapz_wait_raw_selected_preparation("),
            finalize.index("swapz_lane_gap_publish(ctx,"))
        self.assertLess(
            finalize.index("swapz_wait_raw_selected_preparation("),
            finalize.index("swapz_defer_upper_completion(ctx,"))

        import subprocess
        import tempfile

        source = r"""
#include <assert.h>
#include <errno.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdbool.h>
#include <string.h>

#define SWAPZ_PREPARATION_READY_RAW 3
#define SWAPZ_PREPARATION_RAW_SELECTED 4
typedef struct { _Atomic int value; } atomic_t;
struct completion {
    pthread_mutex_t lock;
    pthread_cond_t condition;
    bool done;
    bool waiter_present;
};
struct swapz_prepared_page {
    atomic_t state;
    struct completion result_ready;
    int length;
};
struct swapz_bio_ref { struct swapz_prepared_page *prepared_page; };
struct bio { struct swapz_bio_ref reference; };
#define READ_ONCE(value) (value)
#define dm_per_bio_data(bio, size) ((void)(size), &(bio)->reference)
static int swapz_preparation_read_state(const atomic_t *state)
{
    return atomic_load_explicit(&state->value, memory_order_acquire);
}
static void wait_for_completion(struct completion *completion)
{
    assert(pthread_mutex_lock(&completion->lock) == 0);
    completion->waiter_present = true;
    assert(pthread_cond_broadcast(&completion->condition) == 0);
    while (!completion->done)
        assert(pthread_cond_wait(&completion->condition,
                                 &completion->lock) == 0);
    assert(pthread_mutex_unlock(&completion->lock) == 0);
}
"""
        source += (
            "static int swapz_wait_raw_selected_preparation(struct bio *bio) {\n" +
            helper + "\n}\n")
        source += r"""
struct waiter_context {
    struct bio *bio;
    _Atomic bool returned;
    int result;
};
static void *waiter(void *opaque)
{
    struct waiter_context *context = opaque;
    context->result = swapz_wait_raw_selected_preparation(context->bio);
    atomic_store_explicit(&context->returned, true, memory_order_release);
    return NULL;
}
static void init_completion(struct completion *completion)
{
    memset(completion, 0, sizeof(*completion));
    assert(pthread_mutex_init(&completion->lock, NULL) == 0);
    assert(pthread_cond_init(&completion->condition, NULL) == 0);
}
static void complete_result(struct swapz_prepared_page *prepared, int result)
{
    assert(pthread_mutex_lock(&prepared->result_ready.lock) == 0);
    prepared->length = result;
    prepared->result_ready.done = true;
    assert(pthread_cond_broadcast(&prepared->result_ready.condition) == 0);
    assert(pthread_mutex_unlock(&prepared->result_ready.lock) == 0);
}
static void wait_until_blocked(struct completion *completion)
{
    assert(pthread_mutex_lock(&completion->lock) == 0);
    while (!completion->waiter_present)
        assert(pthread_cond_wait(&completion->condition,
                                 &completion->lock) == 0);
    assert(pthread_mutex_unlock(&completion->lock) == 0);
}
int main(void)
{
    struct swapz_prepared_page prepared;
    struct bio bio = {0};
    struct waiter_context context = {.bio = &bio};
    pthread_t thread;

    memset(&prepared, 0, sizeof(prepared));
    init_completion(&prepared.result_ready);
    atomic_init(&prepared.state.value, SWAPZ_PREPARATION_RAW_SELECTED);
    atomic_init(&context.returned, false);
    bio.reference.prepared_page = &prepared;
    assert(pthread_create(&thread, NULL, waiter, &context) == 0);
    wait_until_blocked(&prepared.result_ready);
    assert(!atomic_load_explicit(&context.returned, memory_order_acquire));
    complete_result(&prepared, -EIO);
    assert(pthread_join(thread, NULL) == 0);
    assert(context.result == -EIO);

    prepared.result_ready.done = false;
    prepared.result_ready.waiter_present = false;
    atomic_store(&context.returned, false);
    context.result = -1;
    assert(pthread_create(&thread, NULL, waiter, &context) == 0);
    wait_until_blocked(&prepared.result_ready);
    complete_result(&prepared, 2048);
    assert(pthread_join(thread, NULL) == 0);
    assert(context.result == 0);

    atomic_store(&prepared.state.value, SWAPZ_PREPARATION_READY_RAW);
    prepared.result_ready.done = false;
    assert(swapz_wait_raw_selected_preparation(&bio) == 0);
    return 0;
}
"""
        with tempfile.TemporaryDirectory(prefix="swapz-raw-ack-barrier-") as temp:
            binary = Path(temp) / "probe"
            compiled = subprocess.run(
                ["cc", "-std=c11", "-O1", "-Wall", "-Wextra", "-Werror",
                 "-pthread", "-x", "c", "-", "-o", str(binary)],
                input=source, text=True, capture_output=True, timeout=30)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            executed = subprocess.run(
                [str(binary)], capture_output=True, text=True, timeout=10)
            self.assertEqual(executed.returncode, 0, executed.stderr)

    def test_pressure_hand_requires_completed_representation(self):
        ready = body("swapz_next_local_write_ready")
        policy = (ROOT / "src/kernel/window-policy.h").read_text()
        self.assertNotIn("swapz_window_inline_short_tail_fits(", policy)
        self.assertNotIn("spin_lock_irqsave(&ctx->queue_lock", ready)
        self.assertNotIn("preparation_ordered_inline", ready)
        self.assertIn("prepared = READ_ONCE(next_entry->prepared_page);", ready)
        self.assertIn("if (!prepared)", ready)
        self.assertIn("completion_done(&next_entry->preparation_snapshot_ready)", ready)
        self.assertIn("SWAPZ_PREPARATION_READY_COMPRESSED", ready)
        self.assertIn("SWAPZ_PREPARATION_READY_RAW", ready)
        self.assertNotIn("wait_for_completion(", ready)

    def test_retained_read_bypass_requires_open_window(self):
        concurrent = body("swapz_try_concurrent_read_slots")
        coalesced = body("swapz_try_parallel_read_batch")
        self.assertIn("if (missing_slots < 2U)", concurrent)
        self.assertIn(
            "retained_bypass = ctx->batch_count && ctx->retain_ms;", concurrent)
        self.assertIn("ctx->batch_count || skipped_write_count", concurrent)
        self.assertIn(
            "retained_bypass = ctx->batch_count && ctx->retain_ms;", coalesced)

    def test_source_body_extracts_u16_definition_after_prototype(self):
        source = """
static swapz_u16 swapz_probe_set(swapz_u32 block);
static swapz_u16 swapz_probe_set(
        swapz_u32 block)
{
    return (swapz_u16)(block & 127U);
}
"""
        self.assertEqual(source_body("swapz_probe_set", source).strip(),
                         "return (swapz_u16)(block & 127U);")

    def test_swz_capacity_policy_keeps_authorization_header_version(self):
        legacy_format_name = "SWZ" + "3"
        text_suffixes = {".c", ".h", ".md", ".py", ".sh", ".yml", ".yaml"}
        paths = [ROOT / "Makefile", ROOT / "dkms.conf"]

        for source_root in (ROOT / "docs", ROOT / "src", ROOT / "tests",
                            ROOT / "packaging", ROOT / ".github"):
            paths.extend(
                path for path in source_root.rglob("*")
                if path.is_file() and
                (path.suffix in text_suffixes or path.name == "Makefile"))

        for path in paths:
            with self.subTest(path=path.relative_to(ROOT)):
                self.assertNotIn(legacy_format_name, path.read_text())

        codec_header = (ROOT / "src/kernel/codec.h").read_text()
        self.assertIn("#define SWAPZ_MAGIC 0x005a5753U", codec_header)
        self.assertIn("swapz_u16 flags_le;", codec_header)
        self.assertNotIn("SWAPZ_VERSION", codec_header)

        superblock = (ROOT / "src/kernel/superblock.h").read_text()
        self.assertIn("#define SWAPZ_SUPERBLOCK_VERSION 1U", superblock)
        self.assertIn("#define SWAPZ_SUPERBLOCK_BYTES 4096U", superblock)

    def test_publish_crc_probe_times_only_final_payload_crc(self):
        descriptor = source_body("swapz_lookup_validated_descriptor", CODEC)
        validated = source_body("swapz_lookup_validated", CODEC)
        finish = source_body("swapz_finish", AUTH)
        self.assertNotIn("swapz_crc32c_bytes", descriptor)
        self.assertIn("swapz_crc32c_bytes", validated)
        self.assertIn("swapz_lookup_validated_descriptor", finish)
        self.assertIn("swapz_publish_crc32c(a, payload, decoded.payload_length)",
                      finish)
        self.assertNotIn("swapz_lookup_validated(image", finish)

    def test_completed_dry_probe_is_removed_and_queue_starvation_probe_is_bounded(self):
        lower = body("swapz_lower")
        self.assertNotIn("dry_pack_", DM)
        self.assertIn("prep_lower_write_start_queued", lower)
        self.assertIn("prep_lower_write_end_queued", lower)
        self.assertIn("ctx->preparation_queued", lower)
        self.assertIn("ctx->preparation_queued++", DM)
        self.assertGreaterEqual(DM.count("ctx->preparation_queued--"), 2)

    def test_gc_tracks_committed_victim_distribution(self):
        gc = body("swapz_gc_compact_one_inner")
        self.assertIn("gc_segment_evictions[victim]", gc)
        self.assertIn("gc_distinct_victims", DM)
        self.assertIn("gc_victim_min_evictions", DM)
        self.assertIn("gc_victim_max_evictions", DM)
        self.assertIn("kvfree(ctx->gc_segment_evictions)", DM)

    def test_dead_segment_probe_and_trim_lifecycle_are_fail_safe(self):
        pick = source_body("swapz_pick_dead_segment", AUTH)
        eligible = source_body("swapz_dead_segment_eligible", AUTH)
        claim = source_body("swapz_claim_dead_segment", AUTH)
        dead_sidecars = source_body("swapz_dead_segment_sidecars_validate", AUTH)
        commit_rotation = source_body("swapz_gc_commit_rotation", AUTH)
        self.assertIn("!a->segment_mapped_pages[segment]", eligible)
        self.assertIn("a->alloc_probe_segments++", pick)
        self.assertNotIn("a->balance_segment_opens", pick)
        self.assertNotIn("programs < best", pick)
        self.assertIn("a->alloc_probe_full_scans++", claim)
        self.assertIn("for (off = 0; off < SWAPZ_SEGMENT_BLOCKS; ++off)", claim)
        self.assertIn("swapz_dead_segment_sidecars_validate(a, segment)", claim)
        self.assertIn("swapz_page_list_validate_segment(a, segment)", dead_sidecars)
        self.assertIn("a->segment_gc_live_bytes[segment]", dead_sidecars)
        self.assertIn("a->segment_gc_io_cost[segment]", dead_sidecars)
        self.assertIn("a->segment_gc_min_live_blocks[segment]", dead_sidecars)
        self.assertLess(claim.index("swapz_dead_segment_sidecars_validate"),
                        claim.index("a->dead_segment_recycle"))
        self.assertIn("swapz_dead_segment_sidecars_validate(a, victim)",
                      commit_rotation)
        self.assertIn("a->segment_program_counts[segment]++", claim)
        stage = source_body("swapz_stage_policy", AUTH)
        self.assertIn("tail_waste = SWAPZ_SEGMENT_BLOCKS -", stage)
        self.assertLess(stage.index("tail_waste = SWAPZ_SEGMENT_BLOCKS -"),
                        stage.index("error = swapz_pick_dead_segment(a)"))
        self.assertNotIn("swapz_placement_start", AUTH)
        resume = source_body("swapz_batch_resume", AUTH)
        self.assertNotIn("packed_placement", resume)
        self.assertNotIn("tx->start_block % tx->extent_blocks", resume)

        discard = body("swapz_discard_dead_segment")
        lower = body("swapz_lower")
        async_submit = body("swapz_submit_inflight_write")
        dirty = body("swapz_mark_segments_dirty")
        status = body("swapz_status")
        self.assertIn("segment_discards_skipped_already_trimmed", discard)
        self.assertIn("READ_ONCE(ctx->segment_trimmed[segment])", discard)
        self.assertIn("WRITE_ONCE(ctx->segment_trimmed[segment], 1)", discard)
        self.assertIn("swapz_mark_segments_dirty(ctx, block, blocks)", lower)
        self.assertIn("swapz_mark_segments_dirty(ctx, inflight->run.start_block",
                      async_submit)
        self.assertIn("WRITE_ONCE(ctx->segment_trimmed[segment], 0)", dirty)
        upper_discard = body("swapz_discard")
        self.assertIn("became_dead", upper_discard)
        self.assertIn("swapz_discard_dead_segment(ctx, old_segment)", upper_discard)
        self.assertNotIn("swapz_packed_placement", DM)
        self.assertNotIn("module_param_named(packed_placement", DM)
        self.assertIn("packed_placement=%u", status)
        engine = (ROOT / "src/kernel/engine.c").read_text()
        self.assertNotIn("packed_placement", engine)
        self.assertIn("alignment_cursor % SWAPZ_SEGMENT_BLOCKS", engine)
        self.assertIn("alignment_hole_blocks_foreground", status)
        self.assertIn("segment_tail_waste_blocks_foreground", status)
        self.assertIn("segment_tail_waste_blocks_gc", status)
        self.assertIn("alloc_probe_full_scans", status)
        self.assertIn("segment_program_sum", status)
        self.assertIn("logical_open_balance=%u", status)
        self.assertNotIn("module_param_named(logical_open_balance", DM)
        self.assertNotIn("swapz_logical_open_balance", DM)
        self.assertIn("swapz_enable_segment_page_lists", DM)
        self.assertIn("ctx->segment_first_page", DM)
        self.assertIn("ctx->page_next_in_segment", DM)
        self.assertNotIn("balance_segment_opens", DM)

    def test_codec_append_rejects_invalid_length_before_payload_hash(self):
        validate = source_body("swapz_validate", CODEC)
        self.assertIn("swapz_record_logical_le(bytes, earlier)", validate)
        self.assertNotIn("swapz_get_record(bytes, earlier", validate)
        append = source_body("swapz_append", CODEC)
        guard = append.index("length > SWAPZ_MAX_COMPRESSED")
        payload_hash = append.index("swapz_crc32c_bytes(payload, length)")
        self.assertLess(guard, payload_hash)
        self.assertIn("!payload || !length", append)

    def test_separate_target_and_release_metadata(self):
        self.assertRegex(DM, r'\.name\s*=\s*"swapz"')
        self.assertRegex(DM, r'MODULE_ALIAS\("dm-swapz"\)')
        version = (ROOT / "src/kernel/VERSION").read_text().strip()
        self.assertRegex(version, r"^3\.0\.0-alpha\.[0-9]+$")
        self.assertIn('#include "swapz-version.h"', DM)
        self.assertIn("MODULE_VERSION(SWAPZ_ALPHA_VERSION)", DM)
        self.assertNotIn('#define SWAPZ_ALPHA_VERSION "3.0.0-alpha.', DM)
        self.assertIn('swapz-version.h', MK)
        self.assertIn('$(CURDIR)/VERSION', MK)
        self.assertIn('^3[.]0[.]0-alpha[.][0-9]+', MK)
        dkms = (ROOT / "dkms.conf").read_text()
        self.assertIn('BASH_SOURCE[0]', dkms)
        self.assertIn('src/kernel/VERSION', dkms)
        self.assertNotIn('PACKAGE_VERSION="' + version + '"', dkms)
        self.assertIn("obj-m += dm-swapz.o", MK)
        self.assertNotIn('"swapz3"', DM)
        for path in ("docs/README.md", "docs/VISION.md",
                     "docs/coding_standards.md", "docs/testing_standards.md",
                     "docs/compile.md", "docs/benchmark.md",
                     "docs/context.md"):
            with self.subTest(naming_policy=path):
                document = (ROOT / path).read_text()
                self.assertIn("Immutable naming policy (read before every prompt)",
                              document)
                self.assertIn("Device Mapper target is exactly `swapz`",
                              document)
                self.assertIn("module alias is `dm-swapz`", document)
        self.assertNotIn("SWAPZ_BUILD_SMOKE", MK)
        self.assertNotIn("swapz_extent", MK)
        # A public README must link to the single version source rather
        # than becoming a second, manually edited alpha-number string.
        self.assertIn(
            "[`src/kernel/VERSION`](../src/kernel/VERSION)", README)
        self.assertIn("single source of truth", README)

    def test_write_saturation_evidence_stays_private_bounded_and_write_only(self):
        loaded = (ROOT / "tests/tools/test-loaded.sh").read_text()
        pair = (ROOT / "tests/tools/benchmark-owned-pair.sh").read_text()
        reporter = (ROOT / "tests/tools/run-tests.py").read_text()
        for qd in ("1", "4", "8", "32"):
            self.assertIn("for qd in 1 4 8 32", loaded)
        self.assertIn("--read-pct 0", loaded)
        self.assertIn("--write-only-qd", loaded)
        self.assertIn("--sustained-write", loaded)
        self.assertIn("START_WRITE_SATURATION_PAIR_QD=", loaded)
        self.assertIn("PASS_WRITE_SATURATION_PAIR_QD=", loaded)
        self.assertIn("WRITE_ONLY_QD=0", pair)
        self.assertIn("READ_PCT=0", pair)
        self.assertIn("PACKED_READ=0", pair)
        self.assertIn("ASYNC_PREPARE && !WRITE_ONLY_QD", pair)
        self.assertIn("def parse_write_saturation", reporter)
        self.assertIn('"replay_mode": obj.get("replay_mode")', reporter)
        self.assertIn('arm.get("replay_mode") != "persistent-write"', reporter)
        self.assertIn("PASS_WRITE_SATURATION_EVIDENCE", reporter)
        self.assertIn(
            "FAST_QD4_QD8_QD32_AND_SERIAL_QD32_PAIRED_95PCT_CI", reporter)
        self.assertIn("serial_qd32_paired", reporter)
        self.assertIn("fast_qd4_paired", reporter)
        self.assertIn("fast_qd8_paired", reporter)
        self.assertIn("fast_qd32_paired", reporter)
        self.assertIn("$qd == 4 || $qd == 8 || $qd == 32", loaded)
        self.assertIn("confirmation_modes=(0 1 1 0 0 1 1 0 0 1)", loaded)


    def test_lz4_foreground_size_histogram_is_attempt_side_only(self):
        accept = body("swapz_accept_write")
        compressor = body("swapz_compress_page")
        status = body("swapz_status")
        self.assertIn("baseline = LZ4_compress_fast(input", compressor)
        self.assertIn("ctx->lz4_attempts++", accept)
        self.assertIn("ctx->lz4_size_bins[5]++", accept)
        self.assertIn("ctx->lz4_accepted_bytes += length", accept)
        for threshold in ("256", "1024", "2048", "3072"):
            self.assertIn(f"length <= {threshold}", accept)
        self.assertLess(accept.index("length = swapz_compress_page("),
                        accept.index("ctx->lz4_attempts++"))
        self.assertLess(accept.index("ctx->lz4_size_bins[5]++"),
                        accept.index("if (length <= 0 && bulk_raw_eligible)"))
        self.assertIn("lz4_attempts=%llu lz4_accepted_bytes=%llu", status)
        self.assertIn("lz4_size_3073_3568=%llu lz4_raw_fallback=%llu", status)
        self.assertIn("ctx->lz4_size_bins[5]", status)
        self.assertNotIn("LZ4_compress_fast(", body("swapz_gc_compact_one_inner"))

    def test_production_delta64_telemetry_has_separate_worker_owners(self):
        compressor = body("swapz_compress_page")
        route = (ROOT / "src/kernel/predictor-route.h").read_text()
        producer = body("swapz_preparation_worker")
        ordered = body("swapz_accept_write")
        status = body("swapz_status")
        totals = body("swapz_preparation_totals_snapshot")
        self.assertIn("&lane->delta64", producer)
        self.assertNotIn("&ctx->ordered_delta64", producer)
        self.assertIn("&ctx->ordered_delta64", ordered)
        self.assertNotIn("&lane->delta64", ordered)
        self.assertIn("swapz_delta64_stats_add(&total->delta64, &lane->delta64)",
                      totals)
        self.assertNotIn("atomic_", compressor)
        self.assertNotIn("spin_lock", compressor)
        self.assertIn("swapz_engine_next_uniform_pack_limit", route)
        self.assertIn("SWAPZ_PREDICTOR_PACK_THRESHOLD", route)
        self.assertLess(compressor.index("swapz_predict_delta64_sample_score"),
                        compressor.index("ordinary:"))
        self.assertLess(compressor.index("swapz_predict_delta64_sample_score"),
                        compressor.index("baseline = LZ4_compress_fast(input"))
        self.assertLess(compressor.index("stats->classifier_pass++"),
                        compressor.index("swapz_predict_delta64_shuf8(input"))
        self.assertLess(compressor.index("stats->attempts++"),
                        compressor.index("swapz_predict_delta64_shuf8(input"))
        self.assertIn("candidate <= (int)SWAPZ_PREDICTOR_RESCUE_MIN_LENGTH",
                      compressor)
        self.assertIn("stats->direct_adopted++", compressor)
        self.assertIn("stats->first_lz4_skipped++", compressor)
        self.assertIn("swapz_delta64_route_init", compressor)
        self.assertIn("swapz_delta64_candidate_adoptable", compressor)
        self.assertIn("swapz_delta64_candidate_smaller", compressor)
        self.assertIn("saved = baseline > 0 ? (u64)baseline : SWAPZ_BLOCK_BYTES",
                      compressor)
        self.assertIn("stats->raw_payload_bytes_saved += saved", compressor)
        self.assertIn("stats->lz4_payload_bytes_saved += saved", compressor)
        self.assertIn("stats->wall_ns += rescue_wall", compressor)
        for field in ("eligible", "classifier_pass", "attempts", "adopted",
                      "direct_adopted", "first_lz4_skipped",
                      "raw_rescues", "lz4_rescues", "pack_eligible",
                      "pack_attempts", "pack_cliff_crossings", "pack_adopted",
                      "score_0_7", "score_8_15", "score_16_23", "score_ge24",
                      "payload_bytes_saved", "raw_payload_bytes_saved",
                      "lz4_payload_bytes_saved", "transform_calls",
                      "transform_wall_ns", "wall_ns"):
            self.assertIn(f"delta64_{field}=%llu", status)
            self.assertIn(f"READ_ONCE(ctx->ordered_delta64.{field})", status)
            self.assertIn(f"prep->delta64.{field}", status)

    def test_preparation_array_reservation_and_release_are_bounded(self):
        slots = (ROOT / "src/kernel/preparation-slots.h").read_text()
        claim = source_body("swapz_preparation_claim_slot", slots)
        release_slot = source_body("swapz_preparation_release_slot", slots)
        producer = body("swapz_preparation_worker")
        drain = body("swapz_drain")
        self.assertIn("SWAPZ_MAX_RECORDS != 64U", slots)
        self.assertIn("attempt <= SWAPZ_MAX_RECORDS", claim)
        self.assertIn("if (!mask)", claim)
        self.assertIn("__ffs64(mask)", claim)
        self.assertIn("atomic64_cmpxchg", claim)
        self.assertLess(release_slot.index("smp_mb__before_atomic()"),
                        release_slot.index("atomic64_or("))
        self.assertIn("prepared = &ctx->preparation_pages[slot]", producer)
        self.assertEqual(producer.count("swapz_preparation_release_slot("), 2)
        self.assertIn("refcount_set(&prepared->refs, 2)", producer)
        self.assertIn("reinit_completion(&prepared->result_ready)", producer)
        self.assertIn("complete(&prepared->result_ready)", producer)
        self.assertNotIn("-ENOMEM", producer)
        for allocation in ("kmalloc(", "kzalloc(", "vzalloc(", "mempool_alloc("):
            self.assertNotIn(allocation, producer)
        self.assertIn("atomic64_read(&ctx->preparation_free_mask)", drain)
        self.assertIn("SWAPZ_PREPARATION_FREE_MASK", drain)

    def test_delta64_rescue_defaults_on_and_disabled_avoids_scratch(self):
        ctor = body("swapz_ctr")
        producer = body("swapz_preparation_worker")
        ordered = body("swapz_accept_write")
        compressor = body("swapz_compress_page")
        read = body("swapz_read")
        slot_read = body("swapz_read_slot_run")
        # Product policy: emulated devices always use the production-on stack;
        # the module-level 0 remains only a debug/compatibility escape hatch.
        self.assertRegex(
            DM, r"static\s+bool\s+swapz_delta64_rescue_enabled\s*=\s*true\s*;")
        self.assertIn("default on (0 disables)", DM)
        self.assertIn("module_param_named(delta64_rescue, "
                      "swapz_delta64_rescue_enabled, bool, 0444)", DM)
        self.assertIn("ctx->delta64_rescue_enabled = swapz_delta64_rescue_enabled",
                      ctor)
        self.assertIn("prepared->length = swapz_compress_prepared_page(", producer)
        self.assertIn("prepared->raw_bytes", producer)
        self.assertIn("swapz_preparation_publish_codec_result(", producer)
        self.assertIn("length = swapz_compress_page(", ordered)
        self.assertIn("if (ctx->delta64_rescue_enabled)", compressor)
        self.assertIn("swapz_predict_delta64_sample_score(input)", compressor)
        self.assertRegex(
            ctor,
            r"(?s)if \(ctx->delta64_rescue_enabled\)\s*\{\s*"
            r"ctx->predictor_page = kvmalloc\(.*?"
            r"ctx->delta64_candidate_page = kvmalloc\(")
        self.assertRegex(
            ctor,
            r"if \(ctx->delta64_rescue_enabled\)\s+"
            r"slot->predictor_page = kvmalloc\(")
        self.assertRegex(
            ctor,
            r"(?s)if \(ctx->delta64_rescue_enabled\)\s*\{\s*"
            r"lane->predictor_page =.*?"
            r"lane->delta64_candidate_page =")
        self.assertIn("if (!ctx->predictor_page)", read)
        self.assertIn("if (!slot->predictor_page)", slot_read)
        self.assertIn("delta64_rescue=%u", body("swapz_status"))
        self.assertIn("ctx->preparation_worker_count =", ctor)
        self.assertIn("ctx->async_prepare ? SWAPZ_DELTA64_PREPARATION_WORKERS : 0U",
                      ctor)
        self.assertNotIn("ctx->delta64_rescue_enabled ?", ctor)
        deploy = (ROOT / "tests/tools/deploy-nullblk.sh").read_text()
        self.assertIn("delta64_rescue=1([[:space:]]|$)", deploy)
        self.assertIn('PASS_DEFAULT_DELTA64_RESCUE=1', deploy)
        self.assertIn('status_u64 "$packed_before" delta64_rescue) == 1', deploy)
        self.assertIn('require_delta64_default "$status_after"', deploy)
        self.assertNotIn("require_delta64_disabled", deploy)
        # Retiring the off/on benchmark must not retire loaded positive-path
        # coverage: the default-policy smoke writes and reads back 128
        # delta64-positive pages and requires classifier passes and adoptions
        # before the oracle profile is accepted.
        oracle_phase = deploy.split('note "PASS_LOADED_ORACLE_PROFILE=', 1)[0]
        for needle in ("--delta64-write-series 128 1",
                       "--delta64-verify-series 128 1",
                       "delta64_counter_delta delta64_classifier_pass",
                       "delta64_counter_delta delta64_adopted",
                       "delta64_pass >= 128 && delta64_adopted >= 128"):
            self.assertIn(needle, oracle_phase)
        self.assertLess(oracle_phase.index("--delta64-write-series"),
                        oracle_phase.index("--delta64-verify-series"))
        roundtrip = (ROOT / "tests/tools/device-roundtrip.c").read_text()
        self.assertIn("static void delta64_pattern(", roundtrip)
        self.assertIn('"--delta64-write-series"', roundtrip)
        self.assertIn('"--delta64-verify-series"', roundtrip)
        self.assertIn("raw_series == 2", roundtrip)
        pair = (ROOT / "tests/tools/benchmark-owned-pair.sh").read_text()
        self.assertIn("\nDELTA64_RESCUE=1\n", pair)
        self.assertIn("\nDELTA64_LZ4_ACCELERATION=4\n", pair)
        self.assertNotIn("--no-delta64-rescue", pair)
        self.assertNotIn("--delta64-rescue", pair)
        self.assertNotIn("DELTA64_POSITIVE_EXPERIMENT", pair)
        self.assertNotIn('"delta64_rescue=$DELTA64_RESCUE" \\\\n', pair)
        self.assertNotIn('"delta64_lz4_acceleration=$DELTA64_LZ4_ACCELERATION" \\\\n', pair)
        loaded = (ROOT / "tests/tools/test-loaded.sh").read_text()
        self.assertNotIn("--no-delta64-rescue", loaded)
        self.assertNotIn("--delta64-rescue", loaded)
        self.assertNotIn("START_DELTA64_RESCUE=", loaded)
        self.assertNotIn("PASS_DELTA64_RESCUE=", loaded)
        self.assertIn("START_STORAGE_ENVELOPE=%s", loaded)
        runner = (ROOT / "tests/tools/run-tests.py").read_text()
        self.assertIn("PRODUCTION_DELTA64_RESCUE = 1", runner)
        fast = (ROOT / "tests/tools/fast-test.py").read_text()
        self.assertNotIn("DELTA64=0", fast)
        self.assertNotIn('os.environ.get("DELTA64"', fast)
        self.assertNotIn('parser.add_argument("--delta64"', fast)
        for doc_name in ("README.md", "VISION.md", "testing_standards.md",
                         "benchmark.md", "ROADMAP.md"):
            doc = (ROOT / "docs" / doc_name).read_text()
            self.assertIn("DELTA64_SHUF8", doc)
        striped = (ROOT / "tests/tools/benchmark-striped-owned.sh").read_text()
        self.assertIn('STRIPED_PAIR = "tests/tools/benchmark-striped-owned.sh"', fast)
        self.assertIn("--run-owned-striped", striped)
        self.assertIn('fast:4)  LOWER_MBPS=20;', striped)
        self.assertIn('OFFERED_QD="${WORKLOAD: -1}"', striped)
        self.assertIn('report.get("replay_mode") != expected_mode', striped)
        self.assertIn('report.get("qd") != offered_qd // stripes', striped)
        self.assertIn('STRIPED_WRITE_QDS = (4, 8)', fast)
        self.assertIn('arguments += ["--submitter-prepare", "0"]', fast)
        self.assertNotIn("START_SERIAL_QUEUE_CONTROL=", loaded)
        self.assertNotIn("benchmark-striped-owned.sh", loaded)
        pair = (ROOT / "tests/tools/benchmark-owned-pair.sh").read_text()
        self.assertIn("SUBMITTER_PREPARE_EXPLICIT=0", pair)
        self.assertIn("== --submitter-prepare", pair)
        self.assertIn('submitter_prepare=$SUBMITTER_PREPARE', pair)
        self.assertIn('submitter_prepare=$expected_submitter_prepare', pair)
        self.assertIn("SUBMITTER_PREPARE_EXPLICIT ))", pair)
        # ID161 is retired; ordinary qualification never varies submitter placement.
        self.assertEqual(loaded.count("--submitter-prepare 0"), 0)
        self.assertIn('"host_load_profile": args.host_load_profile', fast)
        self.assertIn("reject_raw_drift(striped_rows)", fast)

    def test_reclaim_scratch_uses_kvmalloc_and_read_bypass_is_window_local(self):
        ctor = body("swapz_ctr")
        freeing = body("swapz_free")
        flush = body("swapz_flush_window")
        self.assertIn("ctx->lz4_workmem = kvmalloc(LZ4_MEM_COMPRESS, GFP_KERNEL)", ctor)
        self.assertIn("lane->lz4_workmem = kvmalloc(LZ4_MEM_COMPRESS, GFP_KERNEL)", ctor)
        self.assertIn("ctx->predictor_page = kvmalloc(SWAPZ_BLOCK_BYTES, GFP_KERNEL)", ctor)
        self.assertIn("ctx->delta64_candidate_page = kvmalloc(SWAPZ_BLOCK_BYTES, GFP_KERNEL)", ctor)
        self.assertIn("slot->predictor_page = kvmalloc(SWAPZ_BLOCK_BYTES, GFP_KERNEL)", ctor)
        self.assertIn("kvfree(ctx->lz4_workmem)", freeing)
        self.assertIn("kvfree(ctx->predictor_page)", freeing)
        self.assertIn("kvfree(ctx->delta64_candidate_page)", freeing)
        reset = flush.rindex("ctx->retained_window_read_bypasses = 0;")
        policy = flush.rindex("if (!ctx->retain_ms || hard_boundary ||")
        self.assertLess(reset, policy)

    def test_exact_zero_write_elides_lower_io_without_losing_ordering(self):
        accept = body("swapz_accept_write")
        compressor = body("swapz_compress_page")
        read = body("swapz_read")
        status = body("swapz_status")
        self.assertIn("length > 0 && length <= 64", accept)
        self.assertIn("baseline > 0 && baseline <= 64 && swapz_page_is_zero(input)",
                      compressor)
        self.assertIn("candidate <= 64 && swapz_page_is_zero(input)", compressor)
        self.assertIn("(prepared_async ? entry->prepared_page->zero : inline_zero)",
                      accept)
        self.assertLess(accept.index("length = swapz_compress_page("),
                        accept.index("kunmap_local(mapped_input)"))
        self.assertIn("swapz_flush_window(ctx)", accept)
        self.assertIn("swapz_discard_page(&ctx->authority, logical)", accept)
        self.assertIn("ctx->logical_write_bytes += SWAPZ_BLOCK_BYTES", accept)
        self.assertIn("ctx->zero_elided_pages++", accept)
        self.assertIn("swapz_complete(bio, error)", accept)
        self.assertIn("swapz_issue_flush(ctx)", accept)
        zero_branch = accept.index(
            "(prepared_async ? entry->prepared_page->zero : inline_zero)")
        self.assertLess(zero_branch,
                        accept.index("swapz_flush_window(ctx);", zero_branch))
        self.assertLess(accept.index("swapz_flush_window(ctx);", zero_branch),
                        accept.index("swapz_discard_page(&ctx->authority"))
        self.assertIn("if (!map->valid)", read)
        self.assertIn("memset(ctx->read_page, 0, SWAPZ_BLOCK_BYTES)", read)
        self.assertIn("zero_elided=%llu", status)
        # The predicate itself is exercised by an actual-C native test.
        engine = (ROOT / "src/kernel/engine.c").read_text()
        zero_scan = source_body("swapz_page_is_zero", engine)
        self.assertIn("4U * sizeof(unsigned long long)", zero_scan)
        self.assertIn("word0 | word1 | word2 | word3", zero_scan)
        self.assertIn("became_dead", accept)
        self.assertIn("ctx->segment_mapped_pages[old_segment] == 1U", accept)
        self.assertLess(accept.index("swapz_discard_page(&ctx->authority, logical)"),
                        accept.index("swapz_discard_dead_segment(ctx, old_segment)"))

    def test_zero_elision_bounds_checks_old_map_before_segment_probe(self):
        accept = body("swapz_accept_write")
        bounds = body("swapz_map_extent_bounds_valid")
        start = accept.index("if (length > 0 && length <= 64 &&")
        end = accept.index("if (length <= 0 && bulk_raw_eligible)", start)
        zero = accept[start:end]
        self.assertIn("blocks <= ctx->physical_blocks - start", bounds)
        self.assertIn(
            "start % SWAPZ_SEGMENT_BLOCKS + blocks <= SWAPZ_SEGMENT_BLOCKS",
            bounds)
        self.assertIn("!swapz_map_extent_bounds_valid(ctx, old)", zero)
        self.assertLess(
            zero.index("!swapz_map_extent_bounds_valid(ctx, old)"),
            zero.index("ctx->segment_mapped_pages[old_segment]"))
        self.assertRegex(
            zero,
            r"if \(!error\)\s+error = swapz_discard_page\(")
        self.assertLess(
            zero.index("ctx->segment_mapped_pages[old_segment]"),
            zero.index("swapz_discard_page(&ctx->authority, logical)"))

    def test_targeted_read_metadata_and_payload_diagnostics_are_success_only(self):
        engine = (ROOT / "src/kernel/engine.c").read_text()
        header = (ROOT / "src/kernel/engine.h").read_text()
        status = body("swapz_status")
        self.assertIn("read_metadata_requests", header)
        self.assertIn("read_payload_requests", header)
        self.assertIn("read_payload_blocks", header)
        self.assertIn("engine->read_metadata_requests++", engine)
        self.assertIn("engine->read_payload_requests++", engine)
        self.assertIn("engine->read_payload_blocks += count", engine)
        self.assertLess(engine.index("error = engine->io.read_blocks(", engine.index(
            "int swapz_engine_read_page(")),
            engine.index("engine->read_metadata_requests++"))
        self.assertIn("read_meta_reqs=%u read_payload_reqs=%u", status)
        self.assertIn("read_payload_blocks=%u", status)
        self.assertIn("read_meta_cache_hits=%u", status)
        self.assertIn("read_meta_lru_hits=%u", status)
        self.assertIn("read_meta_set_lookups=%llu read_meta_set_hits=%llu", status)
        self.assertIn("read_meta_set_probes=%llu read_meta_set_replacements=%llu", status)
        self.assertIn("read_meta_primary_hits=%llu read_meta_secondary_hits=%llu", status)
        self.assertIn("read_meta_copy_bytes=%llu", status)
        self.assertIn("read_full_extent_reqs=%u read_full_cache_hits=%u", status)
        self.assertIn("read_two_block_skips=%u", status)
        self.assertIn("read_two_block_skips++", engine)
        self.assertIn("peek.payload_offset != observed.payload_offset", engine)
        engine_read = source_body("swapz_engine_read_page", engine)
        peeked_authority = source_body(
            "swapz_read_authoritative_peeked_payload", AUTH)
        self.assertIn("swapz_read_authoritative_peeked_payload(", engine_read)
        self.assertNotIn("swapz_read_authoritative(", engine_read)
        self.assertIn("swapz_crc32c_bytes(", peeked_authority)
        self.assertIn("swapz_disk_sequence(", peeked_authority)
        self.assertNotIn("swapz_lookup(", peeked_authority)
        self.assertIn("payload_offsets[index] = decoded.payload_offset",
                      (ROOT / "src/kernel/authority.c").read_text())
        self.assertIn("read_full_extent_requests", header)
        self.assertIn("read_full_extent_cache_hits", header)
        self.assertIn("engine->read_full_extent_requests++", engine)
        self.assertIn("engine->read_full_extent_cache_hits++", engine)
        self.assertIn("engine->max_read_blocks_per_record != 1", engine)
        self.assertIn("engine->read_metadata_cache_hits++", engine)
        self.assertIn("engine->read_metadata_lru_hits++", engine)
        self.assertIn("swapz_read_metadata_lru_lookup(", engine)
        self.assertIn("swapz_read_metadata_lru_commit(", engine)
        self.assertIn("metadata != engine->read_scratch", engine_read)
        self.assertIn("engine->read_metadata_copy_bytes +=", engine_read)
        self.assertIn("reusable_mask &= (swapz_u8)~1U", engine_read)
        self.assertIn("#define SWAPZ_READ_METADATA_CACHE_ENTRIES 512U", header)
        self.assertIn("#define SWAPZ_READ_METADATA_CACHE_WAYS 4U", header)
        self.assertIn("#define SWAPZ_READ_METADATA_CACHE_CHOICES 2U", header)
        self.assertIn("SWAPZ_READ_METADATA_CACHE_SETS", header)
        self.assertNotIn("read_metadata_front_slots", header)
        set_lookup = source_body("swapz_read_metadata_set_lookup", engine)
        lookup = source_body("swapz_read_metadata_lru_lookup", engine)
        lru_commit = source_body("swapz_read_metadata_lru_commit", engine)
        self.assertIn("way < SWAPZ_READ_METADATA_CACHE_WAYS", set_lookup)
        self.assertNotIn("SWAPZ_READ_METADATA_CACHE_ENTRIES", set_lookup)
        self.assertIn("engine->read_metadata_set_lookups++", lookup)
        self.assertIn("engine->read_metadata_set_probes += probes", lookup)
        self.assertIn("engine->read_metadata_primary_hits++", lookup)
        self.assertIn("engine->read_metadata_secondary_hits++", lookup)
        self.assertIn("choice < SWAPZ_READ_METADATA_CACHE_CHOICES", set_lookup)
        self.assertIn("choice < SWAPZ_READ_METADATA_CACHE_CHOICES", lru_commit)
        secondary = source_body("swapz_read_metadata_secondary_set", engine)
        self.assertIn("if (secondary == primary)", secondary)
        self.assertIn("swapz_read_metadata_secondary_set(", set_lookup)
        self.assertIn("swapz_read_metadata_secondary_set(", lru_commit)
        self.assertIn("way < SWAPZ_READ_METADATA_CACHE_WAYS", lru_commit)
        self.assertNotIn("index < SWAPZ_READ_METADATA_CACHE_ENTRIES", lru_commit)
        self.assertIn("engine->read_metadata_set_replacements++", lru_commit)
        self.assertIn("tag->start_block == start_block", lru_commit)
        self.assertIn("tag->extent_blocks == extent_blocks", lru_commit)
        self.assertIn("hit_slot = candidate", lru_commit)
        self.assertIn("if (hit_slot < 0 && have_slot &&", lru_commit)
        self.assertIn("if (hit_slot < 0)\n\t\tmemcpy(", lru_commit)
        self.assertIn("struct swapz_read_metadata_tag", header)
        self.assertIn("read_metadata_tags[SWAPZ_READ_METADATA_CACHE_ENTRIES]", header)
        self.assertIn("__attribute__((aligned(64)))", header)
        self.assertIn("epoch = engine->read_metadata_epoch", set_lookup)
        self.assertIn("tag = &tags[slot]", set_lookup)
        self.assertIn("tag->epoch == epoch", set_lookup)
        self.assertIn("tag->age < oldest_age", lru_commit)
        self.assertIn("engine->read_metadata_cache +", engine)
        self.assertNotIn("read_metadata_lru_valid", engine)
        invalidate = source_body("swapz_engine_invalidate_read_cache", engine)
        planned = source_body("swapz_engine_write_window_planned", engine)
        stage_pos = planned.index("error = swapz_stage(")
        write_pos = planned.index("error = engine->io.write_extent(")
        range_pos = planned.index("swapz_engine_invalidate_read_range(",
                                  stage_pos)
        self.assertLess(stage_pos, range_pos)
        self.assertLess(range_pos, write_pos)
        self.assertNotIn("swapz_engine_invalidate_read_cache(engine)",
                         planned[:stage_pos])
        self.assertIn("if (engine->verify_after_write)",
                      planned[stage_pos:write_pos])
        self.assertIn("swapz_engine_invalidate_read_cache(engine)",
                      planned[stage_pos:write_pos])
        self.assertIn("if (engine->read_metadata_lru_clock)", invalidate)
        self.assertIn("swapz_read_metadata_advance_epoch(engine)", invalidate)
        self.assertNotIn("memset(engine->read_metadata_tags", invalidate)
        self.assertIn("engine->read_cache_valid = 0", engine)
        self.assertIn("swapz_engine_invalidate_read_cache(engine)", engine)
        self.assertIn("swapz_engine_invalidate_read_range(e,", engine)
        self.assertIn("swapz_invalidate_read_caches_range(ctx,", body("swapz_lower"))
        self.assertIn("swapz_invalidate_read_caches(ctx)", body("swapz_process"))
        self.assertIn("ctx->engine.read_metadata_cache =",
                      body("swapz_ctr"))
        self.assertIn("SWAPZ_READ_METADATA_CACHE_ENTRIES * SWAPZ_BLOCK_BYTES",
                      body("swapz_ctr"))
        self.assertIn("vfree(ctx->engine.read_metadata_cache)",
                      body("swapz_free"))

    def test_synthetic_anon_fixture_is_deterministic_and_size_exact(self):
        import importlib.util
        path = ROOT / "tests/runtime/benchmark/anon-page-fixture.py"
        spec = importlib.util.spec_from_file_location("anon_page_fixture", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        for name in module.PROFILES:
            a = module.page_bytes(123, 7, name)
            self.assertEqual(len(a), 4096, name)
            self.assertEqual(a, module.page_bytes(123, 7, name))
        self.assertEqual(len(module.schedule(7, 103, module.parse_weights(
            module.DEFAULT_WEIGHTS))), 103)
        # Fully deterministic without installing liblz4 on rootless CI:
        # the fake compressor exercises manifest/scheduling logic, not
        # the real compression size measurement claim.
        fake = lambda src, dst, page_size, cap, acceleration: (
            0 if bytes(src)[:4] == b"\\0" * 4 else 1024)
        raw_a, report_a = module.generate(91, 31, module.parse_weights(
            module.DEFAULT_WEIGHTS), fake)
        raw_b, report_b = module.generate(91, 31, module.parse_weights(
            module.DEFAULT_WEIGHTS), fake)
        self.assertEqual(raw_a, raw_b)
        self.assertEqual(report_a, report_b)
        self.assertEqual(len(raw_a), 31 * 4096)
        self.assertEqual(sum(report_a["lz4_size_buckets"].values()), 31)
        self.assertEqual(sum(report_a["profile_pages"].values()), 31)
        self.assertEqual(report_a["fixture_sha256"],
                         __import__("hashlib").sha256(raw_a).hexdigest())
        self.assertEqual(module.classify(0), "raw")
        self.assertEqual(module.classify(3568), "3073_3568")
        self.assertEqual(module.classify(256), "1_256")

    def test_actual_liblz4_anonymous_page_controls(self):
        import importlib.util
        path = ROOT / "tests/runtime/benchmark/anon-page-fixture.py"
        spec = importlib.util.spec_from_file_location("anon_page_fixture", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        try:
            compress = module.lz4_compressor()
        except RuntimeError as err:
            self.skipTest(str(err))
        zero = module.measure(compress, module.page_bytes(444, 0, "zero"))
        entropy = module.measure(compress, module.page_bytes(444, 0, "entropy"))
        self.assertGreater(zero, 0)
        self.assertLessEqual(zero, 256)
        self.assertEqual(entropy, 0)
        pages, info = module.generate(
            444, 70, module.parse_weights(module.DEFAULT_WEIGHTS), compress)
        self.assertEqual(len(pages), 70 * 4096)
        self.assertEqual(sum(info["lz4_size_buckets"].values()), 70)
        self.assertEqual(info["raw_page_bytes"], info["raw_pages"] * 4096)
        self.assertGreater(info["lz4_accepted_payload_bytes"], 0)
        self.assertGreater(info["raw_pages"], 0)

    def test_representative_fixture_never_crosses_unprotected_copy_process(self):
        owned_pair = (ROOT / "tests/tools/benchmark-owned-pair.sh").read_text()
        striped_pair = (ROOT / "tests/tools/benchmark-striped-owned.sh").read_text()
        fast_test = (ROOT / "tests/tools/fast-test.py").read_text()
        self.assertGreaterEqual(
            fast_test.count('args.content == "representative"'), 3)
        for helper in (owned_pair, striped_pair):
            self.assertNotIn(
                'cp -- "$SHARED_PLAN/fixture.bin" "$SESSION/fixture.bin"', helper)
            self.assertIn("--private-fixture", helper)
            self.assertIn("SWAPZ_PRIVATE_FIXTURE=1", helper)
            self.assertIn(
                "tests/runtime/benchmark/private_memory.py copy-fixture", helper)
            self.assertIn('--source "$SHARED_PLAN/fixture.bin"', helper)
            self.assertIn('--destination "$SESSION/fixture.bin"', helper)
            self.assertIn('FIXTURE_PATH="$SESSION/fixture.bin"', helper)
            self.assertIn('--fixture "$FIXTURE_PATH"', helper)
        self.assertIn(
            '-f $SHARED_PLAN/fixture.json && ! -L $SHARED_PLAN/fixture.json',
            striped_pair)

    def test_identical_off_swapz_replay_contract(self):
        # Rootless regular files exercise the immutable plan and full-image
        # oracle. They do NOT claim a loaded swapz module test.
        import subprocess
        import sys
        script = ROOT / "tests/runtime/benchmark/io-replay-test.py"
        # The bounded 65536-op mixed oracle/prefix checks bring this CPU-only
        # suite to ~44s on the two-core qualification host. This is separate
        # from every loaded-I/O and kernel-progress watchdog.
        result = subprocess.run([sys.executable, str(script)],
                                capture_output=True, text=True, timeout=90)
        self.assertEqual(result.returncode, 0,
                         result.stdout + "\\n" + result.stderr)
        self.assertIn("OK", result.stderr)

    def test_physical_backing_is_opt_in_and_superblock_guarded(self):
        ctr = body("swapz_ctr")
        lower = body("swapz_lower")
        parallel = body("swapz_parallel_lower_read")
        async_read = body("swapz_submit_read_slot_range")
        submit = body("swapz_submit_inflight_write")
        discard = body("swapz_discard_dead_segment")
        validator = body("swapz_validate_physical_superblock")
        fail = body("swapz_fail")
        process = body("swapz_process")

        self.assertIn('disk_name, "nullb", 5', ctr)
        arch_gate = body("swapz_physical_backing_arch_supported")
        self.assertIn("#if defined(CONFIG_X86_64)", arch_gate)
        self.assertIn("return true", arch_gate)
        self.assertIn("return false", arch_gate)
        self.assertIn("swapz_physical_backing_arch_supported()", ctr)
        self.assertIn("Physical backing is qualified only on x86_64", ctr)
        self.assertIn("swapz_allow_physical_backing", ctr)
        compact_ctr = re.sub(r"\s+", " ", ctr)
        compact_validator = re.sub(r"\s+", " ", validator)
        self.assertIn(
            "swapz_validate_physical_superblock( ctx, device_bytes, "
            "&superblock_magic_present)", compact_ctr)
        self.assertIn(
            "swapz_validate_physical_superblock( ctx, device_bytes, NULL)",
            compact_ctr)
        self.assertIn("error != -EPERM || superblock_magic_present", compact_ctr)
        self.assertIn("if (swapz_allow_physical_backing)", compact_ctr)
        self.assertIn("ctx->physical_backing = true", compact_ctr)
        self.assertIn("ctx->physical_backing = false", compact_ctr)
        self.assertLess(
            compact_ctr.rindex("if (swapz_allow_physical_backing)"),
            compact_ctr.index(
                "swapz_validate_physical_superblock( ctx, device_bytes, "
                "&superblock_magic_present)"))
        physical_path = compact_ctr.rsplit(
            "if (!swapz_physical_backing_arch_supported())", 1)[1]
        self.assertLess(physical_path.index("swapz_allow_physical_backing"),
                        physical_path.index(
                            "swapz_validate_physical_superblock("))
        self.assertIn("ctx->data_start_block = 0", ctr)
        self.assertIn("ctx->data_start_block = 1U", ctr)
        self.assertIn("flush_fail_nth || write_fail_nth", ctr)
        self.assertIn("swapz_sb_valid(block, device_bytes)", validator)
        self.assertIn(
            "if (!error && magic_present) *magic_present = "
            "swapz_sb_magic_matches(block)", compact_validator)
        self.assertIn("region.sector = 0", validator)
        self.assertIn("ctx->data_start_block + block", lower)
        self.assertIn("ctx->data_start_block + block", parallel)
        self.assertIn("ctx->data_start_block +", async_read)
        self.assertIn("ctx->data_start_block + inflight->run.start_block", submit)
        self.assertIn("ctx->data_start_block * SWAPZ_SECTORS", discard)
        self.assertIn("if (error == -ENOSPC)", fail)
        self.assertIn("error != -ENOSPC", process)
        self.assertGreaterEqual(process.count("op == REQ_OP_READ && error == -ENOSPC"),
                                2)

    def test_real_swapz_not_memory_smoke(self):
        for snippet in ("dm_register_target(&swapz_target)",
                        "LZ4_compress_fast(", "LZ4_decompress_safe(",
                        "swapz_dm_io(&req,", "DM_IO_VMA", "SWAPZ_SECTORS"):
            self.assertIn(snippet, DM)

    def test_dm_io_unsupported_bitmap_api_is_feature_probed(self):
        wrapper = body("swapz_dm_io")
        write_done = body("swapz_async_lower_write_done")
        read_done = body("swapz_async_lower_read_done")
        self.assertIn("sync_unsup_bits", MK)
        self.assertIn("SWAPZ_DM_IO_HAS_UNSUPPORTED_BITS", MK)
        self.assertIn("$(srctree)/include/linux/dm-io.h", MK)
        self.assertNotIn("LINUX_VERSION_CODE", MK)
        self.assertIn("#ifdef SWAPZ_DM_IO_HAS_UNSUPPORTED_BITS", wrapper)
        self.assertIn("sync_unsupported_bits", wrapper)
        self.assertIn("&unsupported_bits", wrapper)
        self.assertIn("return -EOPNOTSUPP", wrapper)
        self.assertIn("dm_io(req, 1, region, sync_error_bits,", wrapper)
        self.assertIn("SWAPZ_DM_IO_NOTIFY_PARAMETERS(error, context)", DM)
        self.assertIn("do { (error_name) |= unsupported; } while (0)", DM)
        self.assertIn("SWAPZ_DM_IO_MERGE_UNSUPPORTED(error)", write_done)
        self.assertIn("SWAPZ_DM_IO_MERGE_UNSUPPORTED(error)", read_done)
        self.assertIn(".fn = swapz_async_lower_write_done",
                      body("swapz_submit_inflight_write"))
        self.assertIn(".fn = swapz_async_lower_read_done",
                      body("swapz_submit_read_slot_range"))

    def test_allocation_has_gc_reserve_and_fail_closed_reuse(self):
        compact = body("swapz_gc_compact_one_inner")
        relocate = body("swapz_gc_relocate_one")
        ctor = body("swapz_ctr")
        self.assertIn("swapz_gc_compact_one(ctx)", body("swapz_flush_window"))
        self.assertIn("swapz_gc_compact_one(ctx)", body("swapz_raw_write"))
        self.assertIn("swapz_gc_choose_victim(ctx,", compact)
        self.assertIn("live_total += a->live_records[start + off]", AUTH)
        self.assertIn("a->segment_mapped_pages[segment]", AUTH)
        self.assertIn("if (live_total)", AUTH)
        self.assertIn("swapz_enable_segment_mapping_counts", AUTH)
        self.assertIn("swapz_gc_live_byte_cost(m)", AUTH)
        self.assertIn("a->segment_gc_live_bytes[segment] += bytes", AUTH)
        self.assertIn("swapz_gc_prefer(score, count, best, best_count)", DM)
        self.assertIn("swapz_gc_relocate_one(ctx, victim, logical)", compact)
        self.assertIn("swapz_engine_read_page(&ctx->engine", relocate)
        self.assertIn("swapz_authority_validate_geometry(", ctor)
        self.assertLess(
            ctor.index("swapz_authority_validate_geometry("),
            ctor.index("ctx->gc_scores = kvcalloc"))
        self.assertLess(
            ctor.index("swapz_authority_validate_geometry("),
            ctor.index("ctx->maps = kvcalloc"))
        self.assertIn("swapz_gc_flush(ctx)", compact)
        self.assertIn("swapz_finish_raw(&ctx->authority", body("swapz_gc_move_raw"))
        self.assertIn("if (a->live_records[block])", compact)

    def test_discard_validates_entire_range_before_mutating(self):
        discard = body("swapz_discard")
        self.assertLess(discard.index("while (check_remaining)"),
                        discard.index("while (remaining)"))
        self.assertLess(discard.index("if (m->generation =="),
                        discard.index("swapz_discard_page(&ctx->authority"))
        self.assertIn("swapz_map_extent_bounds_valid(ctx, m)", discard)
        self.assertIn("ctx->live_records[start]--", discard)
        self.assertIn("ctx->live_records[m->start_block]++", discard)
        self.assertIn("for (restore_sector = sector;", discard)
        self.assertLess(discard.index("ctx->live_records[start]--"),
                        discard.index("ctx->live_records[m->start_block]++"))
        self.assertLess(discard.index("ctx->live_records[m->start_block]++"),
                        discard.index("swapz_discard_page(&ctx->authority"))
        self.assertNotIn("discard_epoch", DM)
        self.assertNotIn("discard_count", DM)
        self.assertNotIn("discard_serial", DM)

    def test_discard_preflight_extent_bounds_exercises_production_c(self):
        """A corrupt later extent cannot partially discard an earlier page."""
        import subprocess
        import tempfile

        # Use the real Device Mapper function body, not a rewritten model.
        # Both failures must occur before the first authority mutation.
        self.assertIn("#define SWAPZ_SEGMENT_BLOCKS 256U",
                      (ROOT / "src/kernel/authority.h").read_text())
        source = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
#include <errno.h>
typedef uint64_t sector_t;
typedef uint32_t swapz_u32;
typedef uint8_t swapz_u8;
#define SWAPZ_SECTORS 8U
#define SWAPZ_SEGMENT_BLOCKS 256U
#define PHYSICAL_BLOCKS 512U
struct swapz_map { swapz_u32 start_block, generation; unsigned extent_blocks, valid; };
struct swapz_authority { swapz_u32 open_segment; };
struct swapz_dm {
    swapz_u32 logical_pages, physical_blocks;
    struct swapz_map *maps;
    uint8_t *extent_classes;
    uint16_t *live_records;
    swapz_u32 *segment_mapped_pages;
    struct swapz_authority authority;
    unsigned discard_pages;
};
struct bio { struct { sector_t bi_sector; } bi_iter; sector_t sectors; };
static struct swapz_dm *current;
static unsigned discarded;
static sector_t bio_sectors(struct bio *bio) { return bio->sectors; }
static int swapz_discard_page(struct swapz_authority *authority, swapz_u32 logical) {
    struct swapz_map *map = &current->maps[logical];
    assert(authority == &current->authority && map->valid);
    assert(current->live_records[map->start_block]);
    --current->live_records[map->start_block];
    --current->segment_mapped_pages[map->start_block / SWAPZ_SEGMENT_BLOCKS];
    map->valid = 0;
    ++map->generation;
    ++discarded;
    return 0;
}
static int swapz_discard_dead_segment(struct swapz_dm *ctx, swapz_u32 segment) {
    (void)ctx; (void)segment;
    assert(!"unexpected dead-segment TRIM");
    return 0;
}
static bool swapz_map_extent_bounds_valid(const struct swapz_dm *ctx,
                                          const struct swapz_map *map) {
'''
        source += body("swapz_map_extent_bounds_valid")
        source += r'''
}
static int swapz_discard(struct swapz_dm *ctx, struct bio *bio) {
'''
        source += body("swapz_discard")
        source += r'''
}
static struct swapz_dm ctx;
static struct swapz_map maps[2];
static uint8_t classes[PHYSICAL_BLOCKS];
static uint16_t live[PHYSICAL_BLOCKS];
static swapz_u32 segments[PHYSICAL_BLOCKS / SWAPZ_SEGMENT_BLOCKS];
static void initialize(unsigned second_start, unsigned second_blocks) {
    memset(&ctx,0,sizeof(ctx)); memset(maps,0,sizeof(maps));
    memset(classes,0,sizeof(classes)); memset(live,0,sizeof(live));
    memset(segments,0,sizeof(segments));
    ctx.logical_pages=2; ctx.physical_blocks=PHYSICAL_BLOCKS;
    ctx.maps=maps; ctx.extent_classes=classes; ctx.live_records=live;
    ctx.segment_mapped_pages=segments; ctx.authority.open_segment=0;
    maps[0]=(struct swapz_map){ .start_block=0, .generation=1, .extent_blocks=1, .valid=1 };
    maps[1]=(struct swapz_map){ .start_block=second_start, .generation=1,
                               .extent_blocks=second_blocks, .valid=1 };
    classes[0]=1; live[0]=1; segments[0]++;
    classes[second_start]=second_blocks; live[second_start]=1;
    segments[second_start / SWAPZ_SEGMENT_BLOCKS]++;
    current=&ctx; discarded=0;
}
int main(void) {
    struct bio whole={.bi_iter.bi_sector=0, .sectors=2*SWAPZ_SECTORS};
    initialize(PHYSICAL_BLOCKS-1,4); /* Overruns physical capacity. */
    assert(swapz_discard(&ctx,&whole)==-EUCLEAN);
    assert(!discarded && !ctx.discard_pages && live[0]==1 &&
           live[PHYSICAL_BLOCKS-1]==1 && maps[0].valid && maps[1].valid &&
           maps[0].generation==1 && maps[1].generation==1);
    initialize(SWAPZ_SEGMENT_BLOCKS-1,2); /* Crosses segment boundary. */
    assert(swapz_discard(&ctx,&whole)==-EUCLEAN);
    assert(!discarded && !ctx.discard_pages && live[0]==1 &&
           live[SWAPZ_SEGMENT_BLOCKS-1]==1 && maps[0].valid && maps[1].valid &&
           maps[0].generation==1 && maps[1].generation==1);
    initialize(4,2); /* Valid two-page DISCARD still succeeds. */
    assert(swapz_discard(&ctx,&whole)==0);
    assert(discarded==2 && ctx.discard_pages==2 && !live[0] && !live[4]);
    assert(!maps[0].valid && !maps[1].valid &&
           maps[0].generation==2 && maps[1].generation==2);
    return 0;
}
'''
        with tempfile.TemporaryDirectory(prefix="swapz-discard-bounds-") as temp:
            path = Path(temp)
            (path / "probe.c").write_text(source)
            built = subprocess.run(
                ["cc", "-std=c11", "-O1", "-Wall", "-Wextra", "-Werror",
                 str(path / "probe.c"), "-o", str(path / "probe")],
                capture_output=True, text=True)
            self.assertEqual(built.returncode, 0, built.stderr)
            ran = subprocess.run([str(path / "probe")],
                                 capture_output=True, text=True)
            self.assertEqual(ran.returncode, 0, ran.stderr)

    def test_fua_acknowledged_only_after_flush(self):
        flush = body("swapz_flush_window")
        self.assertLess(flush.index("swapz_issue_flush(ctx)"),
                        flush.index("swapz_complete(bio, 0)"))
        self.assertIn("if (error && needs_fua &&", flush)
        self.assertIn("(!recoverable_gc_error || committed)", flush)
        self.assertLess(
            flush.index("error = swapz_issue_flush(ctx)"),
            flush.index("if (error && needs_fua &&"))
        self.assertIn("swapz_fail(ctx, error)", flush)
        self.assertNotIn("DM_MAPIO_KILL; /* Until FUA", body("swapz_map"))

    def test_valid_empty_flush_protocol_and_failure_accounting(self):
        # REQ_OP_FLUSH as a BIO is rejected in Linux blk-core itself.
        # The supported upper-bio encoding is zero sector WRITE|PREFLUSH.
        admitted = body("swapz_map")
        process = body("swapz_process")
        lower = body("swapz_issue_flush")
        raw = body("swapz_accept_write")
        drain = body("swapz_drain")
        self.assertIn("REQ_OP_WRITE && !count", admitted)
        self.assertIn("bio->bi_opf & REQ_PREFLUSH", admitted)
        self.assertNotIn("bio_op(bio) != REQ_OP_FLUSH", admitted)
        self.assertNotIn("case REQ_OP_FLUSH:", process)
        self.assertIn("if (bio->bi_opf & REQ_PREFLUSH)", process)
        self.assertIn("swapz_issue_flush(ctx)", process)
        self.assertIn("swapz_issue_flush(ctx)", raw)
        self.assertIn("swapz_issue_flush(ctx)", drain)
        self.assertIn("swapz_flush_accounted(&ctx->flush_meter", lower)
        self.assertIn("swapz_fail(ctx, error)", lower)
        status = status_format_sequence()
        self.assertIn("flush_calls=%llu flush_ok=%llu flush_err=%llu", status)
        self.assertIn("flush_injected=%llu flush_fault_nth=%u", status)
        self.assertIn("flush_fail_nth > 64U", body("swapz_ctr"))
        self.assertIn("flush_meter.fail_nth = flush_fail_nth", body("swapz_ctr"))

    def test_owned_nullblk_codec_fault_covers_all_compression_owners(self):
        ctor = body("swapz_ctr")
        submitter = body("swapz_submitter_prepare_payload")
        background = body("swapz_preparation_worker")
        ordered = body("swapz_accept_write")
        injector = body("swapz_maybe_inject_codec_fault")
        status = body("swapz_status")
        deploy = (ROOT / "tests/tools/deploy-nullblk.sh").read_text()

        for owner in ("SWAPZ_CODEC_FAULT_SUBMITTER",
                      "SWAPZ_CODEC_FAULT_BACKGROUND",
                      "SWAPZ_CODEC_FAULT_INLINE"):
            self.assertIn(owner, DM)
        self.assertIn("ctx->codec_fault_owner != (u32)owner", injector)
        self.assertIn("atomic64_inc(&ctx->codec_fault_calls)", injector)
        self.assertIn("atomic_cmpxchg(&ctx->codec_fault_injected, 0, 1)",
                      injector)
        self.assertIn("return -EIO", injector)

        submitter_fault = submitter.index("swapz_maybe_inject_codec_fault(")
        self.assertLess(submitter_fault,
                        submitter.index("swapz_compress_prepared_page("))
        self.assertIn("SWAPZ_CODEC_FAULT_SUBMITTER", submitter)

        background_fault = background.index("swapz_maybe_inject_codec_fault(")
        self.assertLess(background_fault,
                        background.index("swapz_compress_prepared_page("))
        self.assertIn("SWAPZ_CODEC_FAULT_BACKGROUND", background)

        inline_fault = ordered.index("swapz_maybe_inject_codec_fault(")
        self.assertLess(inline_fault, ordered.index("swapz_compress_page("))
        self.assertIn("SWAPZ_CODEC_FAULT_INLINE", ordered)
        self.assertLess(inline_fault, ordered.index("if (unlikely(length < 0))"))
        self.assertIn("swapz_fail(ctx, length)", ordered)

        self.assertIn("argc < 1 || argc > 11", ctor)
        self.assertIn("codec_fault_owner > SWAPZ_CODEC_FAULT_INLINE", ctor)
        self.assertIn("ctx->codec_fault_owner = codec_fault_owner", ctor)
        self.assertIn("flush_fail_nth || write_fail_nth || codec_fault_owner",
                      ctor)
        self.assertIn("read_fail_nth", ctor)
        self.assertIn("codec_fault_owner=%u codec_fault_calls=%lld "
                      "codec_fault_injected=%d", status)

        self.assertIn("START_LOADED_CODEC_ERROR_PATHS", deploy)
        self.assertIn("PASS_LOADED_CODEC_ERROR_PATHS=", deploy)
        self.assertIn("run_codec_fault_direct_case 3 inline async_prepare=0",
                      deploy)
        self.assertIn(
            "run_codec_fault_direct_case 1 submitter async_prepare=1 "
            "submitter_prepare=1", deploy)
        self.assertIn(
            'insmod "$MODULE" async_prepare=1 submitter_prepare=0', deploy)
        self.assertIn(
            '--table "0 32768 swapz $LOWER 0 64 0 2 0 1 0 2 2"', deploy)
        self.assertIn(
            'after[4] == before[4] && after[6] == before[6]', deploy)

    def test_serialized_completed_lower_write_wall_wait_buckets(self):
        lower = body("swapz_lower")
        status = body("swapz_status")
        self.assertIn("elapsed_ns = swapz_elapsed_ns(section_start", lower)
        self.assertIn("ctx->lower_write_wall_ns += elapsed_ns", lower)
        self.assertIn("ctx->write_wait_le_1ms++", lower)
        self.assertIn("ctx->write_wait_1_to_4ms++", lower)
        self.assertIn("ctx->write_wait_gt_4ms++", lower)
        self.assertLess(lower.index("if (error || bitmap)"),
                        lower.index("ctx->write_wait_le_1ms++"))
        self.assertIn("write_wait_le1ms=%llu write_wait_1to4ms=%llu", status)
        self.assertIn("write_wait_gt4ms=%llu", status)

    def test_owned_nullblk_lower_read_fault_is_pre_submission_and_counted(self):
        ctor = body("swapz_ctr")
        injector = body("swapz_maybe_inject_read_fault")
        lower = body("swapz_lower")
        parallel = body("swapz_parallel_lower_read")
        async_range = body("swapz_submit_read_slot_range")
        status = body("swapz_status")
        deploy = (ROOT / "tests/tools/deploy-nullblk.sh").read_text()

        self.assertIn("argc < 1 || argc > 11", ctor)
        self.assertIn("read_fail_nth > 65535U", ctor)
        self.assertIn("ctx->read_fault_nth = read_fail_nth", ctor)
        self.assertIn("read_fail_nth", ctor)
        self.assertIn("atomic64_inc_return(&ctx->read_fault_calls)", injector)
        self.assertIn("atomic_cmpxchg(&ctx->read_fault_injected, 0, 1)",
                      injector)
        self.assertIn("return -EIO", injector)

        for read_path in (lower, parallel, async_range):
            fault = read_path.index("swapz_maybe_inject_read_fault(")
            self.assertLess(fault, read_path.index("swapz_dm_io(&req"))
        self.assertLess(
            lower.index("swapz_maybe_inject_read_fault("),
            lower.index("ctx->lower_read_submitted_reqs++"))
        self.assertLess(
            parallel.index("swapz_maybe_inject_read_fault("),
            parallel.index("slot->lower_read_submitted_reqs++"))
        self.assertLess(
            async_range.index("swapz_maybe_inject_read_fault("),
            async_range.index("slot->lower_read_submitted_reqs++"))

        self.assertIn("read_fault_nth=%u", status)
        self.assertIn("read_fault_calls=%lld read_fault_injected=%d", status)
        self.assertIn("START_LOADED_SYNTHETIC_READ_FAULT", deploy)
        self.assertIn("PASS_LOADED_SYNTHETIC_READ_FAULT=", deploy)
        self.assertIn('--write-page "$read_fault_seed_page" 73', deploy)
        self.assertIn('"$READ_PROBE" "/dev/mapper/$DMNAME" "$read_fault_seed_page"', deploy)
        self.assertIn('"PASS_LOADED_SYNTHETIC_READ_FAULT=page:$read_fault_seed_page', deploy)
        self.assertIn('READ_FAULT_SEED calls:$read_fault_seed_calls', deploy)
        self.assertIn('logical:$read_fault_seed_logical', deploy)
        self.assertIn('submitted:$read_fault_seed_submitted', deploy)
        self.assertIn('physical:$read_fault_seed_physical', deploy)
        self.assertIn('lower:req$read_fault_seed_lower_reqs', deploy)
        self.assertIn(
            '--table "0 32768 swapz $LOWER 0 64 0 2 0 1 0 2 0 1"', deploy)
        self.assertIn(
            'read_fault_lower_after[2] == read_fault_lower_before[2]', deploy)
        self.assertIn(
            'read_fault_submitted_delta == 0', deploy)
        self.assertIn('READ_PROBE="$ROOT/build/tests/direct-read-probe"', deploy)
        self.assertIn('"$READ_PROBE" "/dev/mapper/$DMNAME"', deploy)
        self.assertIn("read_fault_probe_rc", deploy)
        read_probe = (ROOT / "tests/tools/direct-read-probe.c").read_text()
        self.assertIn("O_RDONLY | O_DIRECT | O_CLOEXEC", read_probe)
        self.assertIn("pread(fd, buffer, PROBE_BYTES, offset)", read_probe)
        self.assertIn("page > (unsigned long long)LLONG_MAX / PROBE_BYTES",
                      read_probe)
        self.assertIn('!strcmp(argv[2], "--write-page")',
                      (ROOT / "tests/tools/device-roundtrip.c").read_text())
        self.assertIn('!strcmp(argv[2], "--verify-page")',
                      (ROOT / "tests/tools/device-roundtrip.c").read_text())
        self.assertIn("read_ret == -1 && read_errno == EIO", read_probe)
        self.assertIn("DIRECT_READ_PROBE", read_probe)
        mk = (ROOT / "Makefile").read_text()
        self.assertIn(
            "build/tests/direct-read-probe: tests/tools/direct-read-probe.c Makefile",
            mk)
        device_roundtrip_rule = mk.split(
            "build/tests/device-roundtrip:", 1)[1].split("\n", 1)[0]
        self.assertIn("build/tests/direct-read-probe", device_roundtrip_rule)

    def test_owned_nullblk_lower_write_fault_is_pre_submission_and_counted(self):
        # This tests fail-closed propagation through the actual dm_io adapter.
        # It cannot model a device-originated partial/torn write.
        ctor = body("swapz_ctr")
        lower = body("swapz_lower")
        status = body("swapz_status")
        self.assertIn('disk_name, "nullb", 5', ctor)
        self.assertIn("argc < 1 || argc > 11", ctor)
        self.assertIn("write_fail_nth > 65535U", ctor)
        self.assertIn("ctx->write_fault_nth = write_fail_nth", ctor)
        self.assertIn("op == REQ_OP_WRITE", lower)
        self.assertIn("++ctx->write_fault_calls == ctx->write_fault_nth", lower)
        self.assertIn("ctx->write_fault_injected++", lower)
        self.assertIn("return -EIO", lower)
        self.assertLess(lower.index("ctx->write_fault_injected++"),
                        lower.index("ctx->lower_write_submitted_reqs++"))
        self.assertLess(lower.index("ctx->write_fault_injected++"),
                        lower.index("error = swapz_dm_io(&req"))
        self.assertIn("swapz_lower(ctx, REQ_OP_WRITE", body("swapz_lower_write"))
        self.assertIn("swapz_lower(ctx, REQ_OP_WRITE", body("swapz_lower_write_run"))
        async_submit = body("swapz_submit_inflight_write")
        self.assertIn("++ctx->write_fault_calls == ctx->write_fault_nth", async_submit)
        self.assertIn("ctx->write_fault_injected++", async_submit)
        self.assertIn("write_fault_nth=%u write_fault_calls=%llu "
                      "write_fault_injected=%llu", status)
        self.assertIn("ctx->engine.bulk_enabled, ctx->write_fault_nth", status)

    def test_failed_target_cannot_complete_new_upper_write_success(self):
        complete = body("swapz_complete")
        status = body("swapz_status")
        self.assertIn("if (!error && ctx && smp_load_acquire(&ctx->failed))", complete)
        self.assertIn("error = READ_ONCE(ctx->last_error)", complete)
        self.assertIn("error = -EIO", complete)
        self.assertIn("bio->bi_status = errno_to_blk_status(error)", complete)
        self.assertIn("atomic64_inc(&ctx->upper_write_completed_err)", complete)
        self.assertIn("atomic64_inc(&ctx->upper_write_completed_ok)", complete)
        self.assertLess(complete.index("atomic64_inc(&ctx->upper_write_completed_err)"),
                        complete.index("bio_endio(bio)"))
        self.assertIn("upper_write_completed_ok=%llu upper_write_completed_err=%llu",
                      status)
        deploy = (ROOT / "tests/tools/deploy-nullblk.sh").read_text()
        self.assertIn('status_u64 "$write_fault_status_after" upper_write_completed_ok',
                      deploy)
        self.assertIn('status_u64 "$write_fault_status_after" upper_write_completed_err',
                      deploy)
        self.assertIn('status_u64 "$write_fault_unexpected_status" upper_write_completed_err',
                      deploy)

    def test_dm_clone_endio_retains_injected_write_error(self):
        endio = body("swapz_end_io")
        status = body("swapz_status")
        self.assertIn("blk_status_t *error", DM)
        self.assertIn("if (*error)", endio)
        self.assertIn("atomic64_inc(&ctx->endio_write_seen_err)", endio)
        self.assertIn("if (!*error && smp_load_acquire(&ctx->failed))", endio)
        self.assertIn("*error = errno_to_blk_status(failure ? failure : -EIO)", endio)
        self.assertIn("atomic64_inc(&ctx->endio_write_forced_err)", endio)
        self.assertIn("return DM_ENDIO_DONE", endio)
        self.assertIn(".end_io = swapz_end_io", DM)
        self.assertIn("endio_write_seen_ok=%llu endio_write_seen_err=%llu", status)
        self.assertIn("endio_write_forced_err=%llu", status)
        deploy = (ROOT / "tests/tools/deploy-nullblk.sh").read_text()
        self.assertIn('status_u64 "$write_fault_unexpected_status" endio_write_seen_err',
                      deploy)
        self.assertIn('status_u64 "$write_fault_status_after" endio_write_seen_err',
                      deploy)

    def test_retained_write_fault_uses_exact_direct_syscall_oracle(self):
        mk = (ROOT / "Makefile").read_text()
        deploy = (ROOT / "tests/tools/deploy-nullblk.sh").read_text()
        probe = (ROOT / "tests/tools/direct-write-probe.c").read_text()
        self.assertIn("build/tests/direct-write-probe", mk)
        self.assertIn(
            "build/tests/device-roundtrip: tests/tools/device-roundtrip.c Makefile "
            "build/tests/direct-write-probe", mk)
        self.assertIn('WRITE_PROBE="$ROOT/build/tests/direct-write-probe"', deploy)
        self.assertIn('"$WRITE_PROBE" "/dev/mapper/$DMNAME"', deploy)
        self.assertIn("write_fault_probe_rc", deploy)
        self.assertIn("did not observe EIO", deploy)
        write_fault = deploy.split("START_LOADED_RETAINED_WRITE_FAULT", 1)[1].split(
            "START_LOADED_RETAINED_FLUSH_FAULT", 1)[0]
        self.assertIn('"$WRITE_PROBE" "/dev/mapper/$DMNAME"', write_fault)
        self.assertNotIn("dd if=/dev/urandom", write_fault)
        self.assertIn("O_DIRECT", probe)
        self.assertIn("posix_memalign", probe)
        self.assertIn("pwrite(fd, buffer, PROBE_BYTES, 0)", probe)
        self.assertIn("write_errno == EIO", probe)
        self.assertIn("DIRECT_WRITE_PROBE", probe)
        self.assertIn("write_ret=%zd write_errno=%d", probe)

    def test_immutable_io_run_split_preserves_publication_gate(self):
        engine_h = (ROOT / "src/kernel/engine.h").read_text()
        engine = (ROOT / "src/kernel/engine.c").read_text()
        prepare = source_body("swapz_engine_prepare_batched_run", engine)
        complete = source_body("swapz_engine_complete_batched_run", engine)
        self.assertIn("struct swapz_io_run", engine_h)
        self.assertIn("swapz_u8 *bytes", engine_h)
        self.assertIn("struct swapz_tx *txs", engine_h)
        self.assertIn("swapz_batch_pause(e->authority, tx)", prepare)
        self.assertNotIn("e->io.write_run(", prepare)
        self.assertIn("swapz_batch_resume(e->authority, tx)", complete)
        self.assertIn("swapz_finish(", complete)
        self.assertIn("swapz_finish_raw(", complete)
        self.assertIn("swapz_bulk_abort(e, run, 0)", complete)
        self.assertLess(complete.index("swapz_batch_resume"),
                        complete.index("swapz_finish("))

    def test_bounded_lower_run_aggregation_preserves_commit_gate(self):
        engine = (ROOT / "src/kernel/engine.c").read_text()
        authority = (ROOT / "src/kernel/authority.c").read_text()
        writer = source_body("swapz_engine_write_window_batched_read_cap", engine)
        prepare = source_body("swapz_engine_prepare_batched_run", engine)
        complete = source_body("swapz_engine_complete_batched_run", engine)
        pause = source_body("swapz_batch_pause", authority)
        resume = source_body("swapz_batch_resume", authority)
        self.assertIn("SWAPZ_BULK_BLOCKS 64U",
                      (ROOT / "src/kernel/engine.h").read_text())
        self.assertIn("swapz_engine_write_window_batched_read_cap(&ctx->engine", DM)
        self.assertIn("ctx->engine.io.write_run = swapz_lower_write_run", DM)
        self.assertIn("swapz_batch_pause(e->authority, tx)", prepare)
        self.assertIn("swapz_engine_prepare_batched_run(", writer)
        planner = source_body("swapz_engine_plan_bounded_policy", engine)
        self.assertIn("swapz_u32 alignment_cursor", engine)
        self.assertIn("candidate_objective != objectives[position]", planner)
        self.assertIn("hole == best_hole && blocks > chosen_class", planner)
        self.assertIn("e->authority->next_block", prepare)
        self.assertIn("swapz_batch_resume(e->authority, tx)", complete)
        self.assertLess(writer.index("e->io.write_run"),
                        writer.index("swapz_engine_complete_batched_run"))
        self.assertLess(complete.index("swapz_batch_resume(e->authority, tx)"),
                        complete.index("swapz_finish("))
        self.assertIn("swapz_bulk_abort(e, run, 0)", complete)
        self.assertIn("a->batch_pending++", pause)
        self.assertIn("a->batch_replaying = 1", resume)
        self.assertIn("ctx->engine.bulk_writes", body("swapz_status"))
        self.assertIn("bulk_mode=%u", body("swapz_status"))
        ctor = body("swapz_ctr")
        self.assertIn("lower_bulk = 1", ctor)
        self.assertIn("lower_bulk > 2U", ctor)
        self.assertIn("ctx->engine.bulk_enabled = lower_bulk", ctor)
        self.assertIn("e->bulk_enabled == 1", prepare)
        self.assertIn("placed = e->authority->next_block;", prepare)
        self.assertIn("(e->bulk_enabled == 1 && placed != run_end)", prepare)
        self.assertIn("tx->start_block != run_start + run_blocks", prepare)
        self.assertNotIn("e->run_splits_by_hole++", prepare)
        self.assertIn("swapz_stage_batch_unique(e->authority", prepare)
        self.assertIn("batch_hashes", authority)
        self.assertIn("batch_stage_allowed", authority)
        self.assertIn("a->batch_pending", source_body("swapz_gc_commit_rotation", authority))

    def test_partial_extent_read_cache_tracks_only_successful_blocks(self):
        engine_h = (ROOT / "src/kernel/engine.h").read_text()
        engine = (ROOT / "src/kernel/engine.c").read_text()
        read = source_body("swapz_engine_read_page", engine)
        invalidate = source_body("swapz_engine_invalidate_read_cache", engine)
        process = body("swapz_process")
        lower = body("swapz_lower")
        submit = body("swapz_submit_inflight_write")
        self.assertIn("read_cached_block_mask", engine_h)
        self.assertIn("read_extent_cache", engine_h)
        self.assertIn("engine->read_cached_block_mask = 0", invalidate)
        self.assertIn("read_extent_lru_valid", invalidate)
        self.assertIn("cached_mask = cached_extent ?", read)
        self.assertIn("cached_metadata = cached_extent && !!(cached_mask & 1U)", read)
        self.assertIn("cached_mask |= 1U", read)
        self.assertIn("(1U << initial_blocks) - 1U", read)
        self.assertIn("while (start <= last && (cached_mask & (1U << start)))",
                      read)
        self.assertIn("while (start <= last && (cached_mask & (1U << last)))",
                      read)
        payload_read = read.index("engine->io.read_blocks",
                                  read.index("if (last >= start)"))
        residency_gate = read.index("if (observed.extent_blocks > 1 &&",
                                    payload_read)
        self.assertLess(payload_read, residency_gate)
        self.assertIn("engine->max_read_blocks_per_record != 1",
                      read[residency_gate:residency_gate + 300])
        self.assertLess(residency_gate,
                        read.index("cached_mask |=", residency_gate))
        self.assertIn("reusable_mask = cached_mask", read)
        self.assertIn("reusable_mask &= (swapz_u8)~1U", read)
        self.assertIn("engine->read_cached_block_mask = reusable_mask", read)
        self.assertIn("engine->read_cached_full = observed.extent_blocks > 1 &&",
                      read)
        self.assertIn("engine->max_read_blocks_per_record != 1",
                      read[read.index("engine->read_cached_full ="):])
        self.assertIn("swapz_read_extent_lru_commit(engine", read)
        # RAM-only WRITE admission must not throw away validated residency.
        # Physical WRITE submission remains the mutation boundary.
        self.assertNotIn("op != REQ_OP_READ", process)
        self.assertIn("op == REQ_OP_DISCARD", process)
        self.assertIn(
            "op == REQ_OP_WRITE && ctx->invalidate_cache_on_write_admit",
            process)
        self.assertIn("REQ_PREFLUSH | REQ_FUA", process)
        self.assertIn("swapz_invalidate_read_caches_range(ctx,", lower)
        self.assertIn("swapz_invalidate_read_caches_range(ctx,", submit)

    def test_authority_snapshot_copies_only_active_transaction_prefix(self):
        authority = (ROOT / "src/kernel/authority.c").read_text()
        stage = source_body("swapz_stage_policy", authority)
        pause = source_body("swapz_batch_pause", authority)
        resume = source_body("swapz_batch_resume", authority)
        forget = source_body("swapz_forget_active", authority)

        self.assertIn("swapz_tx_active_bytes", authority)
        # Keep the caller-visible handle fully initialized; only the private
        # authoritative snapshot is copied and cleared by active prefix.
        self.assertIn("memset(out, 0, sizeof(*out))", stage)
        self.assertIn("memcpy(&a->active_tx, out, swapz_tx_active_bytes(count))",
                      stage)
        self.assertNotIn("a->active_tx = *out", stage)
        self.assertIn(
            "memset(&a->active_tx, 0, swapz_tx_active_bytes(a->active_count))",
            pause)
        self.assertIn(
            "memcpy(&a->active_tx, tx, swapz_tx_active_bytes(tx->count))",
            resume)
        self.assertNotIn("a->active_tx = *tx", resume)
        self.assertIn(
            "memset(&a->active_tx, 0, swapz_tx_active_bytes(a->active_count))",
            forget)


    def test_mixed_raw_lower_run_preserves_authority_and_barriers(self):
        engine = (ROOT / "src/kernel/engine.c").read_text()
        writer = source_body("swapz_engine_write_window_batched_read_cap", engine)
        prepare = source_body("swapz_engine_prepare_batched_run", engine)
        engine_complete = source_body("swapz_engine_complete_batched_run", engine)
        accept = body("swapz_accept_write")
        dm_complete = body("swapz_flush_window")
        process = body("swapz_process")
        self.assertIn("!ctx->engine.verify_after_write", accept)
        self.assertIn("ctx->engine.bulk_enabled", accept)
        self.assertIn("ctx->batch_count++", accept)
        self.assertIn(".raw = 1", accept)
        self.assertIn("ctx->batch[index].raw", body("swapz_order_window"))
        self.assertIn("run->raw[staged] = raw", prepare)
        self.assertIn("swapz_finish_raw(", engine_complete)
        self.assertLess(writer.index("e->io.write_run"),
                        writer.index("swapz_engine_complete_batched_run"))
        self.assertIn("ctx->planned[index].raw", dm_complete)
        self.assertIn("bulk_mixed_io=%u", body("swapz_status"))
        self.assertIn("bulk_raw_only_io=%u", body("swapz_status"))
        self.assertIn("bulk_raw_entries=%u", body("swapz_status"))
        self.assertLess(dm_complete.index("swapz_issue_flush(ctx)"),
                        dm_complete.index("swapz_complete(bio, 0)"))
        self.assertIn("swapz_flush_window(ctx)", process)
        self.assertIn("REQ_PREFLUSH", process)
        self.assertIn("swapz_raw_write(ctx, bio, logical)", accept)

    def test_gc_refuses_any_unpublished_lower_group(self):
        compact = body("swapz_gc_compact_one_inner")
        self.assertIn("a->batch_pending", compact)
        self.assertIn("a->batch_replaying", compact)
        self.assertLess(compact.index("a->batch_pending"),
                        compact.index("swapz_gc_choose_victim(ctx, &victim)"))
        drain = body("swapz_drain")
        self.assertIn("ctx->authority.batch_pending", drain)
        self.assertIn("ctx->authority.in_flight", drain)

    def test_gc_production_uses_exact_segment_mapping_counts(self):
        authority = (ROOT / "src/kernel/authority.c").read_text()
        finish = source_body("swapz_finish", authority)
        raw = source_body("swapz_finish_raw", authority)
        discard = source_body("swapz_discard_page", authority)
        dead = source_body("swapz_pick_dead_segment", authority)
        eligible = source_body("swapz_dead_segment_eligible", authority)
        claim = source_body("swapz_claim_dead_segment", authority)
        rotate = source_body("swapz_gc_commit_rotation", authority)
        ctor = body("swapz_ctr")
        compact = body("swapz_gc_compact_one_inner")
        self.assertIn("segment_mapped_pages", (ROOT / "src/kernel/authority.h").read_text())
        self.assertIn("segment_delta->mapped_pages++", finish)
        self.assertIn("a->segment_mapped_pages[delta->segment] -=", finish)
        self.assertIn("delta->mapped_pages", finish)
        self.assertIn("a->segment_mapped_pages[new_segment] += tx->count", finish)
        self.assertIn("segment_mapped_pages[new_segment]++", raw)
        self.assertIn("segment_mapped_pages[old_segment]--", discard)
        self.assertIn("!a->segment_mapped_pages[segment]", eligible)
        self.assertIn("swapz_dead_segment_eligible(a, segment)", dead)
        self.assertIn("swapz_claim_dead_segment(a, segment, probe_start)", dead)
        self.assertIn("for (off = 0; off < SWAPZ_SEGMENT_BLOCKS; ++off)", claim)
        self.assertIn("if (live_total)", claim)
        self.assertIn("a->segment_mapped_pages[victim]", rotate)
        self.assertIn("ctx->segment_mapped_pages = kvcalloc", ctor)
        self.assertIn("swapz_enable_segment_mapping_counts(&ctx->authority", ctor)
        self.assertIn("a->segment_mapped_pages[victim]", compact)

    def test_gc_large_record_preflight_avoids_pointless_full_relocation(self):
        choose = body("swapz_gc_choose_victim")
        cost = (ROOT / "src/kernel/gc-cost.h").read_text()
        ctr = body("swapz_ctr")
        self.assertIn("SWAPZ_GC_UNSHAREABLE_MIN_LENGTH", cost)
        self.assertIn("swapz_gc_min_live_blocks", cost)
        self.assertIn("swapz_gc_candidate_can_free_block", cost)
        self.assertIn("a->segment_gc_min_live_blocks[segment] +=", AUTH)
        self.assertIn("swapz_gc_candidate_can_free_block", choose)
        self.assertIn("ctx->gc_no_headroom_skips++", choose)
        status = body("swapz_status")
        advance = body("swapz_gc_recovery_advance_destination")
        roll_forward = body("swapz_gc_recovery_roll_forward")
        self.assertIn("gc_no_headroom_skips=%llu", status)
        self.assertIn("gc_reserve_segments_initial=%u", status)
        self.assertIn("gc_reserve_segments_current=%u", status)
        self.assertIn("gc_destination_advances=%llu", status)
        self.assertIn("gc_roll_forwards=%llu", status)
        self.assertIn("ctx->gc_reserve_segments_current--", advance)
        self.assertIn("ctx->gc_destination_advances++", advance)
        self.assertIn("ctx->gc_roll_forwards++", roll_forward)
        self.assertIn("ctx->gc_reserve_segments_current =", ctr)
        self.assertIn("ctx->gc_min_live_blocks = kvcalloc", ctr)

    def test_gc_io_aware_default_retains_old_control_policies(self):
        choose = body("swapz_gc_choose_victim")
        ctor = body("swapz_ctr")
        self.assertIn("gc_policy = 2", ctor)
        self.assertIn("gc_policy > 2U", ctor)
        self.assertIn("swapz_gc_estimated_io_cost(m)", AUTH)
        self.assertIn("a->segment_gc_io_cost[segment] += io_cost", AUTH)
        self.assertIn("case 0:", choose)
        self.assertIn("case 1:", choose)
        self.assertIn("score = ctx->gc_io_scores[segment]", choose)
        self.assertIn("gc_selected_io_estimate", body("swapz_status"))

    def test_gc_does_not_consume_or_complete_upper_bios(self):
        gc = body("swapz_gc_compact_one_inner")
        commit = source_body("swapz_gc_commit_rotation", AUTH)
        self.assertNotIn("swapz_complete(", gc)
        self.assertIn("ctx->gc_read_bytes", gc)
        self.assertIn("ctx->gc_write_bytes", gc)
        self.assertIn("swapz_gc_commit_rotation(a, victim)", gc)
        self.assertIn("a->gc_allocation = 0", commit)
        self.assertIn("a->gc_forbidden_open = ~(swapz_u32)0", commit)
        self.assertIn("a->gc_forbidden_victim = ~(swapz_u32)0", commit)

    def test_deferred_upper_completions_have_one_owner_and_join_before_drain(self):
        wrapper = body("swapz_worker")
        # ID175: the work item owns the ordered domain for its whole pass and
        # acknowledges its detached private list only after releasing it.
        self.assertLess(wrapper.index("mutex_lock(&ctx->ordered_owner);"),
                        wrapper.index("ctx->defer_upper_completions = true;"))
        self.assertLess(wrapper.index("ctx->defer_upper_completions = true;"),
                        wrapper.index("swapz_worker_pass(ctx);"))
        self.assertLess(wrapper.index("swapz_worker_pass(ctx);"),
                        wrapper.index("ctx->defer_upper_completions = false;"))
        self.assertLess(wrapper.index("ctx->defer_upper_completions = false;"),
                        wrapper.index(
                            "bio_list_merge(&ready, &ctx->deferred_upper_completions);"))
        self.assertLess(wrapper.index(
                            "bio_list_init(&ctx->deferred_upper_completions);"),
                        wrapper.index("mutex_unlock(&ctx->ordered_owner);"))
        self.assertLess(wrapper.index("mutex_unlock(&ctx->ordered_owner);"),
                        wrapper.index("swapz_deliver_bio_list(ctx, &ready);"))
        self.assertNotIn("swapz_deliver_upper_completions(ctx);", wrapper)
        self.assertNotIn("mutex_trylock", wrapper)
        finalize = body("swapz_finalize_inflight_write")
        # Deliver before sleeping on the lower device, never after.
        self.assertLess(finalize.index("swapz_deliver_upper_completions(ctx);"),
                        finalize.index("wait_for_completion(&inflight->lower_done)"))
        success = finalize[finalize.rindex("for (index = 0; index < inflight->count"):]
        self.assertIn("defer_for_successor =\n"
                      "\t\tctx->batch_count || !list_empty(&ctx->incoming);",
                      finalize)
        self.assertIn("defer = ctx->defer_upper_completions &&\n"
                      "\t\t(defer_for_successor || submitter_dispatched);",
                      finalize)
        # The ID175 marker is consumed exactly once, before either outcome.
        self.assertLess(finalize.index(
                            "inflight->submitter_dispatched = false;"),
                        finalize.index("if (error || committed != inflight->count)"))
        self.assertIn("if (defer)", success)
        self.assertIn("swapz_defer_upper_completion(ctx,", success)
        # Failed runs are still acknowledged immediately with their error.
        failed = finalize[finalize.index("if (error || committed != inflight->count)"):
                          finalize.rindex("for (index = 0; index < inflight->count")]
        self.assertIn("swapz_complete(inflight->bios[index], error)", failed)
        self.assertNotIn("swapz_defer_upper_completion", failed)
        defer = body("swapz_defer_upper_completion")
        self.assertLess(defer.index("swapz_release_prepared(bio);"),
                        defer.index("bio_list_add(&ctx->deferred_upper_completions"))
        deliver = body("swapz_deliver_upper_completions")
        self.assertIn("swapz_deliver_bio_list(ctx, &ctx->deferred_upper_completions)",
                      deliver)
        self.assertLess(deliver.index("swapz_try_completion_handoff(ctx)"),
                        deliver.index("swapz_deliver_bio_list("))
        delivered = body("swapz_deliver_bio_list")
        self.assertIn("bio_list_pop(bios)", delivered)
        self.assertIn("swapz_complete(bio, 0)", delivered)
        self.assertLess(delivered.index("preempt_disable();"),
                        delivered.index("bio_list_pop(bios)"))
        worker = body("swapz_worker_pass")
        self.assertIn("if (list_empty(&local) || !ctx->batch_count ||\n"
                      "\t\t\t    swapz_has_inflight(ctx))\n"
                      "\t\t\t\tswapz_deliver_upper_completions(ctx);", worker)
        self.assertIn("bio_list_init(&ctx->deferred_upper_completions);", DM)
        handoff = body("swapz_try_completion_handoff")
        # The retired early-publication exception must not bypass this gate.
        pending_guard = "swapz_inflight_lower_pending(ctx)"
        self.assertEqual(handoff.count(pending_guard), 2)
        self.assertLess(handoff.index(pending_guard),
                        handoff.index("spin_lock_irqsave"))
        self.assertLess(handoff.index("spin_lock_irqsave"),
                        handoff.rindex(pending_guard))
        self.assertNotIn("allow_without_lower_pending", handoff)
        self.assertLess(handoff.index("spin_lock_irqsave"),
                        handoff.index("ctx->accepting && !READ_ONCE(ctx->failed)"))
        self.assertLess(handoff.index("queue_work("),
                        handoff.index("spin_unlock_irqrestore"))
        self.assertIn("count > SWAPZ_MAX_RECORDS", handoff)
        self.assertIn("atomic_cmpxchg(&ctx->completion_active, 0, 1)", handoff)
        drain = body("swapz_drain")
        self.assertLess(drain.rindex("drain_workqueue(ctx->preparation_workqueue)"),
                        drain.index("atomic_read(&ctx->completion_active)"))
        self.assertIn("cancel_work_sync(&ctx->completion_work)", body("swapz_free"))

    def test_lower_write_completion_notification_shares_drain_lifetime_gate(self):
        """A waiter observing done cannot destroy the queue before notification."""
        import subprocess
        import tempfile

        callback = body("swapz_async_lower_write_done")
        unlock_tail = callback.split(
            "spin_unlock_irqrestore(&ctx->queue_lock, flags);", 1)[1]
        self.assertNotRegex(unlock_tail, r"\b(?:ctx|inflight)->")
        source = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
typedef uint64_t u64;
#define WRITE_ONCE(x,v) ((x)=(v))
struct completion { bool done; };
struct swapz_dm {
    int queue_lock, lower_write_active, worker;
    unsigned preparation_queued;
    u64 prep_lower_write_end_queued, prep_lower_write_end_nonempty;
    void *workqueue;
};
struct swapz_inflight_write {
    struct swapz_dm *ctx;
    struct completion lower_done;
    int lower_error;
    u64 lower_end_ns;
};
static bool alive, teardown_waiting;
static unsigned lock_depth, notified, blocked;
static void drain_gate(void) {
    if (lock_depth) { ++blocked; teardown_waiting=true; return; }
    alive=false;
}
static void lock(void) { assert(alive&&!lock_depth); ++lock_depth; }
static void unlock(void) {
    assert(lock_depth==1); --lock_depth;
    if (teardown_waiting) { assert(notified==1); drain_gate(); }
}
#define spin_lock_irqsave(p,f) do { (void)(p);(f)=0;lock(); } while(0)
#define spin_unlock_irqrestore(p,f) do { (void)(p);assert(!(f));unlock(); } while(0)
static void atomic_dec(int *p) { assert(alive&&*p==1); --*p; }
static u64 ktime_get_ns(void) { return 42; }
static void complete(struct completion *c) {
    assert(alive&&!c->done); c->done=true;
    /* The awakened owner has finalized its last BIO; model a concurrent
     * teardown reaching the final queue-lock drain gate immediately. */
    drain_gate();
}
static void mod_delayed_work(void *queue,int *worker,unsigned delay) {
    (void)worker; assert(alive&&queue&&delay==0); ++notified;
}
#define EIO 5
'''
        signatures = (
            ("unsigned long error, void *context", "", "0, &inflight", "1, &inflight"),
            ("unsigned long error, unsigned long unsupported, void *context",
             "error |= unsupported;", "0, 0, &inflight", "0, 1, &inflight"))
        with tempfile.TemporaryDirectory(prefix="swapz-lower-lifetime-") as temp:
            path = Path(temp)
            for index, (params, merge, success, failure) in enumerate(signatures):
                unit = source + (
                    "#define SWAPZ_DM_IO_MERGE_UNSUPPORTED(error) do { " + merge + " } while(0)\n"
                    "static void callback(" + params + ") {\n" + callback + "\n}\n")
                unit += r'''
static void init(struct swapz_dm *ctx, struct swapz_inflight_write *inflight) {
    memset(ctx,0,sizeof(*ctx));memset(inflight,0,sizeof(*inflight));
    ctx->lower_write_active=1;ctx->preparation_queued=3;ctx->workqueue=ctx;
    inflight->ctx=ctx;alive=true;teardown_waiting=false;lock_depth=notified=blocked=0;
}
int main(void) {
    struct swapz_dm ctx;struct swapz_inflight_write inflight;
    init(&ctx,&inflight);
    callback(SUCCESS);
    assert(!alive&&blocked==1&&notified==1&&!lock_depth);
    assert(inflight.lower_done.done&&!inflight.lower_error&&inflight.lower_end_ns==42);
    assert(!ctx.lower_write_active&&ctx.prep_lower_write_end_queued==3);
    assert(ctx.prep_lower_write_end_nonempty==1);
    init(&ctx,&inflight);ctx.preparation_queued=0;
    callback(FAILURE);
    assert(!alive&&blocked==1&&notified==1&&inflight.lower_done.done);
    assert(inflight.lower_error==-EIO&&!ctx.lower_write_active);
    assert(!ctx.prep_lower_write_end_queued&&!ctx.prep_lower_write_end_nonempty);
    return 0;
}
'''.replace("SUCCESS", success).replace("FAILURE", failure)
                (path / "probe.c").write_text(unit)
                built = subprocess.run(
                    ["cc", "-std=c11", "-O1", "-Wall", "-Wextra", "-Werror",
                     str(path / "probe.c"), "-o", str(path / "probe")],
                    capture_output=True, text=True)
                self.assertEqual(built.returncode, 0, built.stderr)
                ran = subprocess.run([str(path / "probe")], capture_output=True, text=True)
                self.assertEqual(ran.returncode, 0, f"ABI {index}: {ran.stderr}")

    def test_ack_batch_executes_actual_accounting_helpers(self):
        """One cohort clock plus batched atomics must preserve dwell accounting."""
        import subprocess
        import tempfile

        completion_work = body("swapz_completion_work")
        ordered_delivery = body("swapz_deliver_bio_list")
        finalize = body("swapz_finalize_inflight_write")
        synchronous_flush = body("swapz_flush_window")
        self.assertIn("acknowledgements.delivered_ns = ktime_get_ns();",
                      completion_work)
        self.assertIn("acknowledgements.delivered_ns = start_ns;",
                      ordered_delivery)
        self.assertIn("acknowledgements.delivered_ns = ktime_get_ns();",
                      finalize)
        self.assertIn("entry->ack_batch = &acknowledgements", finalize)
        self.assertIn("swapz_lane_gap_ack_flush(ctx, &acknowledgements);",
                      finalize)
        self.assertIn("acknowledgements.delivered_ns = ktime_get_ns();",
                      synchronous_flush)
        self.assertIn("entry->published_ns = acknowledgements.delivered_ns;",
                      synchronous_flush)
        self.assertIn("entry->ack_batch = &acknowledgements;",
                      synchronous_flush)
        self.assertIn("swapz_lane_gap_ack_flush(ctx, &acknowledgements);",
                      synchronous_flush)

        source = r"""
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
#include "lane-gap.h"
typedef uint64_t u64;
typedef int64_t s64;
typedef struct { s64 counter; } atomic64_t;
struct swapz_ack_dwell_batch {
    u64 delivered_ns;
    u64 count[2], duration_ns[2], bins[2][SWAPZ_LANE_DWELL_BINS];
};
struct swapz_bio_ref {
    u64 published_ns;
    bool published_deferred;
    struct swapz_ack_dwell_batch *ack_batch;
};
struct swapz_dm {
    atomic64_t ack_dwell_deferred_count, ack_dwell_deferred_ns;
    atomic64_t ack_dwell_immediate_count, ack_dwell_immediate_ns;
    atomic64_t ack_dwell_deferred_bins[SWAPZ_LANE_DWELL_BINS];
    atomic64_t ack_dwell_immediate_bins[SWAPZ_LANE_DWELL_BINS];
};
static u64 clock_ns;
static unsigned int clock_reads;
static u64 ktime_get_ns(void) { ++clock_reads; return clock_ns; }
static void atomic64_inc(atomic64_t *p) { ++p->counter; }
static void atomic64_add(u64 value, atomic64_t *p) { p->counter += (s64)value; }
"""
        for name, signature in (
                ("swapz_lane_gap_ack",
                 "static void swapz_lane_gap_ack(struct swapz_dm *ctx, const struct swapz_bio_ref *entry)"),
                ("swapz_lane_gap_ack_flush",
                 "static void swapz_lane_gap_ack_flush(struct swapz_dm *ctx, const struct swapz_ack_dwell_batch *batch)")):
            source += signature + " {\n" + body(name) + "\n}\n"
        source += r"""
int main(void) {
    struct swapz_dm ctx = {0};
    struct swapz_ack_dwell_batch batch = {.delivered_ns=5001};
    struct swapz_bio_ref entry = {.published_ns=4001, .ack_batch=&batch};

    clock_ns=999999; swapz_lane_gap_ack(&ctx,&entry);
    assert(clock_reads==0);
    assert(batch.count[0]==1 && batch.duration_ns[0]==1000 && batch.bins[0][0]==1);
    assert(ctx.ack_dwell_immediate_count.counter==0);
    entry.published_deferred=true;
    entry.published_ns=1000; swapz_lane_gap_ack(&ctx,&entry);
    entry.published_ns=4001; swapz_lane_gap_ack(&ctx,&entry);
    assert(clock_reads==0);
    assert(batch.count[1]==2 && batch.duration_ns[1]==5001);
    assert(batch.bins[1][0]==1 && batch.bins[1][2]==1);
    entry.published_ns=6000; swapz_lane_gap_ack(&ctx,&entry);
    assert(batch.count[1]==2 && clock_reads==0);
    swapz_lane_gap_ack_flush(&ctx,&batch);
    assert(ctx.ack_dwell_immediate_count.counter==1);
    assert(ctx.ack_dwell_immediate_ns.counter==1000);
    assert(ctx.ack_dwell_immediate_bins[0].counter==1);
    assert(ctx.ack_dwell_deferred_count.counter==2);
    assert(ctx.ack_dwell_deferred_ns.counter==5001);
    assert(ctx.ack_dwell_deferred_bins[0].counter==1);
    assert(ctx.ack_dwell_deferred_bins[2].counter==1);

    memset(&entry,0,sizeof(entry));
    entry.published_ns=1000;
    clock_ns=65001; swapz_lane_gap_ack(&ctx,&entry);
    assert(clock_reads==1);
    assert(ctx.ack_dwell_immediate_count.counter==2);
    assert(ctx.ack_dwell_immediate_ns.counter==65001);
    assert(ctx.ack_dwell_immediate_bins[4].counter==1);
    entry.published_ns=70000; clock_ns=69999;
    swapz_lane_gap_ack(&ctx,&entry);
    assert(clock_reads==2);
    assert(ctx.ack_dwell_immediate_count.counter==2);
    return 0;
}
"""
        with tempfile.TemporaryDirectory(prefix="swapz-ack-batch-") as temp:
            path = Path(temp)
            (path / "probe.c").write_text(source)
            built = subprocess.run(
                ["cc", "-std=c11", "-O1", "-Wall", "-Wextra", "-Werror",
                 "-I", str(ROOT / "src/kernel"), str(path / "probe.c"),
                 "-o", str(path / "probe")], capture_output=True, text=True)
            self.assertEqual(built.returncode, 0, built.stderr)
            ran = subprocess.run([str(path / "probe")],
                                 capture_output=True, text=True)
            self.assertEqual(ran.returncode, 0, ran.stderr)

    def test_striped_plans_are_shared_by_same_workload_models(self):
        """Build the real plan split once for two models and clean failures."""
        import json
        import runpy
        import shutil
        import tempfile

        fast = runpy.run_path(str(ROOT / "tests/tools/fast-test.py"))
        plan = fast["prepare_plan"]("medium", need_stripes=True)
        try:
            fast["prepare_striped_workload_plans"](
                plan, (1, 2, 4), (("nvme5", "mixed"), ("sata", "mixed")))
            parent_manifest = json.loads(
                (plan / "plan-striped-base" / "manifest.json").read_text())
            for stripe_count in (1, 2, 4):
                stripe_root = plan / f"striped-{stripe_count}"
                self.assertTrue(stripe_root.is_dir())
                for stripe_index in range(stripe_count):
                    child = stripe_root / f"stripe-{stripe_index}"
                    manifest = json.loads(
                        (child / "manifest.json").read_text())
                    self.assertEqual(manifest["stripe_count"], stripe_count)
                    self.assertEqual(manifest["stripe_index"], stripe_index)
                    self.assertEqual(manifest["parent_trace_sha256"],
                                     parent_manifest["trace_sha256"])
        finally:
            shutil.rmtree(plan, ignore_errors=True)

        with tempfile.TemporaryDirectory(prefix="swapz-striped-plan-") as temp:
            owned_plan = Path(temp) / "plan"
            owned_plan.mkdir()
            with self.assertRaisesRegex(ValueError,
                                        "unsupported striped workload"):
                fast["prepare_striped_workload_plans"](
                    owned_plan, (1,), (("nvme5", "invalid"),))
            self.assertFalse(owned_plan.exists())

    def test_completion_handoff_real_bodies_preserve_ownership_and_failure(self):
        """Exercise actual target C under controlled queue/close/reuse interleavings."""
        import subprocess
        import tempfile

        source = r'''
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>
#include <errno.h>
typedef uint64_t u64;
typedef int blk_status_t;
typedef int atomic_t;
typedef uint64_t atomic64_t;
#define READ_ONCE(x) (x)
#define smp_load_acquire(ptr) __atomic_load_n((ptr), __ATOMIC_ACQUIRE)
#define SWAPZ_MAX_RECORDS 64U
#define REQ_OP_WRITE 1
#define DM_ENDIO_DONE 0
#define container_of(p,t,m) ((t *)((char *)(p)-offsetof(t,m)))
struct swapz_dm;
/* Keep fields consumed by extracted production completion bodies in sync. */
struct swapz_ack_dwell_batch { u64 delivered_ns; unsigned count[2]; };
struct swapz_bio_ref {
    struct swapz_dm *preparation_ctx;
    struct swapz_ack_dwell_batch *ack_batch;
};
struct bio { struct bio *bi_next; struct swapz_bio_ref ref; unsigned id, ended; int bi_status; bool prepared; };
struct bio_list { struct bio *head, *tail; };
struct work_struct { void (*func)(struct work_struct *); };
struct dm_target { struct swapz_dm *private; };
struct swapz_dm {
    bool defer_upper_completions, accepting, failed, lower_pending;
    int last_error, queue_lock;
    void *preparation_workqueue;
    struct bio_list deferred_upper_completions, completion_bios;
    struct work_struct completion_work;
    atomic_t completion_active;
    u64 completion_offloaded_batches, deferred_upper_completion_bios;
    u64 deferred_upper_completion_wall_ns;
    atomic64_t upper_write_completed_ok, upper_write_completed_err;
    atomic64_t endio_write_seen_ok, endio_write_seen_err, endio_write_forced_err;
};
static struct work_struct *pending;
static struct swapz_dm *close_at_lock;
static void (*release_hook)(void);
static int lock_depth, preempt_depth, released, fail_after=-1, fail_at_endio=-1;
static int atomic_cmpxchg(atomic_t *p,int old,int new_value) { int v=*p; if(v==old)*p=new_value; return v; }
static void atomic64_inc(atomic64_t *p) { ++*p; }
static void atomic_set_release(atomic_t *p,int v) {
    *p=v;
    if(release_hook) { void (*hook)(void)=release_hook; release_hook=NULL; hook(); }
}
static void lock(void) { assert(!lock_depth); if(close_at_lock) {close_at_lock->accepting=false;close_at_lock=NULL;} ++lock_depth; }
#define spin_lock_irqsave(p,f) do { (void)(p); (f)=0; lock(); } while(0)
#define spin_unlock_irqrestore(p,f) do { (void)(p);assert(!(f));assert(lock_depth==1);--lock_depth; } while(0)
static void preempt_disable(void) { ++preempt_depth; }
static void preempt_enable(void) { assert(preempt_depth); --preempt_depth; }
static void bio_list_init(struct bio_list *l) { l->head=l->tail=NULL; }
static bool bio_list_empty(const struct bio_list *l) { return !l->head; }
static void bio_list_add(struct bio_list *l,struct bio *b) { b->bi_next=NULL; if(l->tail)l->tail->bi_next=b;else l->head=b;l->tail=b; }
static struct bio *bio_list_pop(struct bio_list *l) { struct bio *b=l->head; if(b) {l->head=b->bi_next;if(!l->head)l->tail=NULL;b->bi_next=NULL;}return b; }
static unsigned bio_list_size(const struct bio_list *l) { unsigned n=0;for(struct bio *b=l->head;b;b=b->bi_next)++n;return n; }
static bool queue_work(void *queue,struct work_struct *w) { assert(queue&&lock_depth&&!pending);pending=w;return true; }
static struct swapz_bio_ref *dm_per_bio_data(struct bio *b,size_t size) { (void)size; return &b->ref; }
static int bio_op(struct bio *b) { (void)b;return REQ_OP_WRITE; }
static unsigned bio_sectors(struct bio *b) { (void)b;return 8; }
static int errno_to_blk_status(int error) { return -error; }
static void swapz_release_prepared(struct bio *b) { if(b->prepared) {b->prepared=false;++released;} }
/* The completion probe asserts BIO ownership; ID178 atomic dwell is covered
 * by its separate source contract and native accounting test. */
static void swapz_lane_gap_ack(struct swapz_dm *ctx,
                               const struct swapz_bio_ref *entry)
{ (void)ctx; (void)entry; }
static void swapz_lane_gap_ack_flush(struct swapz_dm *ctx,
                                    const struct swapz_ack_dwell_batch *batch)
{ (void)ctx; (void)batch; }
static u64 ktime_get_ns(void) { static u64 clock;return ++clock; }
static u64 swapz_elapsed_ns(u64 a,u64 b) { return b-a; }
static bool swapz_inflight_lower_pending(struct swapz_dm *ctx) { return ctx->lower_pending; }
static int swapz_end_io(struct dm_target *,struct bio *,blk_status_t *);
static void bio_endio(struct bio *b) {
    struct swapz_dm *ctx=b->ref.preparation_ctx;
    struct dm_target ti={ctx};
    assert(!b->ended++);
    if((int)b->id==fail_at_endio) {ctx->failed=true;ctx->last_error=-EIO;}
    assert(swapz_end_io(&ti,b,&b->bi_status)==DM_ENDIO_DONE);
    if((int)b->id==fail_after) {ctx->failed=true;ctx->last_error=-EIO;}
}
'''
        # Use the real policy constants as well as the actual function bodies.
        # A private four-record stub previously hid the product's eight-record
        # dispatch threshold accidentally gating completion handoff as well.
        for name in ("SWAPZ_WORK_CONSERVING_HAND_RECORDS",
                     "SWAPZ_COMPLETION_HANDOFF_MIN_BIOS"):
            definition = re.search(r"^#define " + name + r" .+$", DM, re.M)
            self.assertIsNotNone(definition, name)
            source = definition.group(0) + "\n" + source
        for name, signature in (
                ("swapz_end_io", "static int swapz_end_io(struct dm_target *ti, struct bio *bio, blk_status_t *error)"),
                ("swapz_complete", "static void swapz_complete(struct bio *bio, int error)"),
                ("swapz_defer_upper_completion", "static void swapz_defer_upper_completion(struct swapz_dm *ctx, struct bio *bio)"),
                ("swapz_completion_work", "static void swapz_completion_work(struct work_struct *work)"),
                ("swapz_try_completion_handoff", "static bool swapz_try_completion_handoff(struct swapz_dm *ctx)"),
                ("swapz_deliver_bio_list", "static void swapz_deliver_bio_list(struct swapz_dm *ctx, struct bio_list *bios)"),
                ("swapz_deliver_upper_completions", "static void swapz_deliver_upper_completions(struct swapz_dm *ctx)")):
            source += signature + " {\n" + body(name) + "\n}\n"
        source += r'''
static struct swapz_dm ctx;
static struct bio bios[70];
static void init(void) {
    memset(&ctx,0,sizeof(ctx));memset(bios,0,sizeof(bios));
    assert(!pending&&!preempt_depth&&!lock_depth);
    ctx.defer_upper_completions=ctx.accepting=ctx.lower_pending=true;
    ctx.preparation_workqueue=&ctx;ctx.completion_work.func=swapz_completion_work;
    released=0;fail_after=fail_at_endio=-1;
    for(unsigned i=0;i<70;++i) {bios[i].id=i;bios[i].ref.preparation_ctx=&ctx;bios[i].prepared=true;}
}
static void add(unsigned start,unsigned count) {
    for(unsigned i=start;i<start+count;++i)swapz_defer_upper_completion(&ctx,&bios[i]);
}
static void run(void) { struct work_struct *w=pending;assert(w);pending=NULL;w->func(w); }
static void reuse(void) { add(4,4);assert(swapz_try_completion_handoff(&ctx)); }
int main(void) {
    init();add(0,4);assert(swapz_try_completion_handoff(&ctx));
    assert(ctx.completion_active&&bio_list_empty(&ctx.deferred_upper_completions));
    assert(released==4&&!bios[0].ended);
    add(4,4);assert(!swapz_try_completion_handoff(&ctx));
    swapz_deliver_upper_completions(&ctx); /* Occupied slot: original inline path. */
    for(unsigned i=0;i<8;++i)assert(bios[i].ended==(i>=4));
    run();assert(!ctx.completion_active&&released==8&&ctx.upper_write_completed_ok==8);
    for(unsigned i=0;i<8;++i)assert(bios[i].ended==1&&!bios[i].bi_status);

    /* Same work item is requeued after release, before its old call returns. */
    init();add(0,4);assert(swapz_try_completion_handoff(&ctx));release_hook=reuse;
    run();assert(ctx.completion_active&&pending&&ctx.completion_offloaded_batches==2);
    for(unsigned i=0;i<8;++i)assert(bios[i].ended==(i<4));
    run();assert(!ctx.completion_active&&ctx.upper_write_completed_ok==8);

    /* Closing admission between eligibility and lock acquisition rejects handoff. */
    init();add(0,4);close_at_lock=&ctx;assert(!swapz_try_completion_handoff(&ctx));
    assert(!pending&&!ctx.completion_active&&bio_list_size(&ctx.deferred_upper_completions)==4);
    swapz_deliver_upper_completions(&ctx);assert(ctx.upper_write_completed_ok==4);
    init();add(0,3);assert(!swapz_try_completion_handoff(&ctx));
    swapz_deliver_upper_completions(&ctx);assert(ctx.upper_write_completed_ok==3);
    init();add(0,65);assert(!swapz_try_completion_handoff(&ctx));
    swapz_deliver_upper_completions(&ctx);assert(ctx.upper_write_completed_ok==65);
    init();add(0,4);ctx.lower_pending=false;assert(!swapz_try_completion_handoff(&ctx));
    swapz_deliver_upper_completions(&ctx);assert(ctx.upper_write_completed_ok==4);
    init();add(0,4);ctx.defer_upper_completions=false;
    swapz_deliver_upper_completions(&ctx);assert(!pending&&ctx.upper_write_completed_ok==4);

    /* ID175 worker tail: a detached private list is acknowledged exactly once,
       with balanced preemption and no handoff or deferred-list access. */
    init();add(0,5);ctx.defer_upper_completions=false;
    {
        struct bio_list ready=ctx.deferred_upper_completions;
        bio_list_init(&ctx.deferred_upper_completions);
        swapz_deliver_bio_list(&ctx,&ready);
        assert(bio_list_empty(&ready)&&!pending&&!preempt_depth);
        assert(ctx.upper_write_completed_ok==5&&released==5);
        for(unsigned i=0;i<5;++i)assert(bios[i].ended==1);
        swapz_deliver_bio_list(&ctx,&ready);assert(ctx.upper_write_completed_ok==5);
    }

    /* Already-published BIOs still fail closed if failure precedes delivery. */
    init();add(0,4);assert(swapz_try_completion_handoff(&ctx));fail_after=0;run();
    assert(ctx.upper_write_completed_ok==1&&ctx.upper_write_completed_err==3);
    for(unsigned i=1;i<4;++i)assert(bios[i].bi_status==EIO);
    init();add(0,4);assert(swapz_try_completion_handoff(&ctx));fail_at_endio=0;run();
    assert(ctx.endio_write_forced_err==1&&bios[0].bi_status==EIO);
    assert(ctx.upper_write_completed_err==3&&!ctx.completion_active);
    return 0;
}
'''
        with tempfile.TemporaryDirectory(prefix="swapz-completion-") as temp:
            path = Path(temp)
            (path / "probe.c").write_text(source)
            built = subprocess.run(
                ["cc", "-std=c11", "-O1", "-Wall", "-Wextra", "-Werror",
                 str(path / "probe.c"), "-o", str(path / "probe")],
                capture_output=True, text=True)
            self.assertEqual(built.returncode, 0, built.stderr)
            subprocess.run([str(path / "probe")], check=True)

        deploy = (ROOT / "tests/tools/deploy-nullblk.sh").read_text()
        live = deploy.split('UUID="SWAPZ-TEST-$TOKEN-completion"', 1)[1].split(
            'dmsetup suspend "$DMNAME"', 1)[0]
        # The live handoff probe repeats the fixed series (bounded), polls each
        # writer until exit without a fixed poll budget, and needs a handoff
        # newer than that pass's own baseline while the writer is alive.
        self.assertIn("for completion_pass in {1..16}; do", live)
        self.assertNotIn("{1..500}", live)
        self.assertIn('while kill -0 "$writer_pid" 2>/dev/null; do', live)
        self.assertIn("completion_batches > completion_pass_base", live)
        self.assertLess(live.index('completion_before="$(dmsetup status'),
                        live.index("--parallel-write-series 128 128"))
        self.assertIn("(( completion_observed )) && break", live)
        # Include setup before the UUID: window/ordinal/pass bounds belong to
        # this fixture and must be checked within the same extracted region.
        completion_fault = deploy.split(
            "# The preceding mapping independently proves", 1)[1].split(
            'PASS_LOADED_COMPLETION_HANDOFF=', 1)[0]
        self.assertIn("completion_fault_window=4", completion_fault)
        self.assertIn("completion_fault_nth=65535", completion_fault)
        self.assertIn("completion_fault_max_passes=16", completion_fault)
        self.assertIn(
            '--table "0 32768 swapz $LOWER 0 $completion_fault_window 0 2 0 1 $completion_fault_nth 2"',
            completion_fault)
        self.assertIn("fault_calls == completion_fault_nth", completion_fault)
        # Eight known zero elisions leave 16,504 nonzero WRITEs. A four-record
        # window therefore guarantees ceil(16,504 / 4) = 4,126 lower attempts
        # per pass, so 16 bounded passes always reach fault ordinal 65,535.
        self.assertIn(
            "for ((fault_pass = 1; fault_pass <= completion_fault_max_passes; ++fault_pass)); do",
            completion_fault)
        self.assertGreaterEqual(16 * 4126, 65535)
        self.assertIn("(( fault_writer_rc == 0 )) || break", completion_fault)
        self.assertIn("(( fault_writer_rc == 1 )) ||", completion_fault)
        self.assertIn(">>\"$SESSION/completion-fault-writer.log\"",
                      completion_fault)
        for field in ("fault_batches", "fault_active", "fault_failed",
                      "fault_calls", "fault_injected", "fault_upper_err",
                      "fault_passes"):
            self.assertIn(field, completion_fault)
        self.assertIn(
            "completion-handoff fault invariant mismatch:", completion_fault)
        # The live mapping above proves handoff execution. This fresh fault
        # mapping may legitimately observe zero offloads before terminal failure.
        self.assertNotIn("fault_batches > 0", completion_fault)

    def test_worker_yields_after_finite_window_and_preserves_fifo(self):
        # Assert the finite-quantum semantics, not one obsolete decrement idiom.
        worker = body("swapz_worker_pass")
        self.assertIn("SWAPZ_WORK_QUANTUM_BIOS", worker)
        self.assertIn("while (remaining && !list_empty(&local))", worker)
        self.assertIn("remaining -= processed_bios", worker)
        self.assertIn("unsigned int processed_bios = 1", worker)
        self.assertIn("list_splice_init(&local, &ctx->incoming)", worker)
        self.assertIn("mod_delayed_work(ctx->workqueue, &ctx->worker, 0)", worker)
        self.assertIn("cond_resched()", worker)
        self.assertLess(worker.index("remaining -= processed_bios"),
                        worker.rindex("list_splice_init(&local, &ctx->incoming)"))
        self.assertLess(worker.index("swapz_flush_window(ctx)"),
                        worker.rindex("list_splice_init(&local, &ctx->incoming)"))

    def test_shutdown_completes_all_accepted_queued_bios(self):
        worker = body("swapz_worker_pass")
        drain = body("swapz_drain")
        self.assertIn("for (;;)", worker)
        self.assertIn("remaining = SWAPZ_WORK_QUANTUM_BIOS", worker)
        self.assertIn("if (ctx->accepting)", worker)
        self.assertIn("mod_delayed_work(ctx->workqueue, &ctx->worker, 0)", worker)
        self.assertIn("cond_resched();", worker)
        self.assertLess(worker.index("if (ctx->accepting)"),
                        worker.rindex("cond_resched();"))
        self.assertIn("drain_workqueue(ctx->workqueue)", drain)
        self.assertIn("swapz drain invariant: accepted BIOs remain", drain)
        self.assertIn("ctx->authority.batch_pending", drain)
        self.assertIn("ctx->authority.in_flight", drain)
        self.assertIn("swapz_fail(ctx, -EUCLEAN)", drain)

    def test_raw_read_slots_verify_authority_and_never_seed_swz_cache(self):
        import subprocess
        import tempfile

        def definition(name):
            match = re.search(r"static\s+(?:int|void|bool)\s+" + name +
                              r"\s*\([^;]*?\)\s*\{", DM, re.S)
            self.assertIsNotNone(match)
            return match.group(0) + body(name) + "}\n"

        start = DM.index("struct swapz_read_slot {")
        end = DM.index("\n};", start) + 3
        source = r'''
/* Execute the real target selection, decode and completion bodies. */
#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
#include "authority.h"
#include "engine.h"
typedef uint8_t u8;
typedef uint64_t u64;
#define SWAPZ_SECTORS 8U
#define REQ_OP_READ 0U
#define REQ_PREFLUSH 0x10U
#define REQ_FUA 0x20U
#define bio_op(bio) ((bio)->op)
#define READ_ONCE(value) (value)
struct completion { int done; };
struct bio { struct { unsigned long bi_sector; } bi_iter; unsigned int op, bi_opf; };
struct swapz_dm { struct swapz_map *maps; struct swapz_authority authority;
                 swapz_u32 physical_blocks; };
static unsigned int engine_reads, seeds, waits, independence_calls;
static bool independent = true;
static u64 clock_ns;
static u64 ktime_get_ns(void) { return ++clock_ns; }
static u64 swapz_elapsed_ns(u64 a, u64 b) { return b - a; }
static void wait_for_completion(struct completion *done) { assert(done->done); waits++; }
static bool swapz_read_can_parallel(struct swapz_dm *ctx, struct bio *bio)
{ (void)ctx; (void)bio; independence_calls++; return independent; }
void swapz_engine_invalidate_read_cache(struct swapz_engine *engine)
{ engine->read_cache_valid = 0; }
int swapz_engine_read_page(struct swapz_engine *engine, swapz_u32 logical,
                          swapz_u8 *output, swapz_u16 capacity, swapz_u16 *bytes)
{ (void)engine; (void)logical; (void)output; (void)capacity; (void)bytes;
  engine_reads++; return -EIO; }
int swapz_engine_seed_read_range(struct swapz_engine *engine, swapz_u32 start,
                                swapz_u8 extent, swapz_u8 first, swapz_u8 blocks)
{ (void)engine; (void)start; (void)extent; (void)first; (void)blocks; seeds++; return 0; }
void swapz_unpredict_delta64(const void *src, void *dst)
{ (void)src; (void)dst; assert(false); }
void swapz_unpredict_delta64_shuf8(const void *src, void *scratch, void *dst)
{ (void)src; (void)scratch; (void)dst; assert(false); }
static int LZ4_decompress_safe(const void *src, void *dst, int length, int capacity)
{ (void)src; (void)dst; (void)length; (void)capacity; assert(false); return -1; }
/* Insert actual struct swapz_read_slot and target function definitions here. */
''' + DM[start:end] + "\n" + "\n".join(definition(name) for name in (
            "swapz_parallel_read_extent_mapped", "swapz_parallel_read_extent",
            "swapz_read_slot_prepare", "swapz_read_slot_run",
            "swapz_finish_read_slot_range")) + r'''
int main(void)
{
    struct swapz_map maps[2] = {{0}};
    swapz_u8 classes[8] = {0};
    swapz_u16 live[8] = {0};
    u8 raw[SWAPZ_BLOCK_BYTES], outputs[2 * SWAPZ_BLOCK_BYTES];
    struct swapz_dm ctx = {.maps = maps, .physical_blocks = 8};
    struct bio bio = {.bi_iter.bi_sector = 0, .op = REQ_OP_READ};
    struct swapz_read_slot slot = {.ctx = &ctx};
    swapz_u32 start;
    swapz_u8 blocks;
    unsigned int i;

    for (i = 0; i < sizeof(raw); ++i) raw[i] = (u8)(i * 13 + i / 17);
    maps[0] = (struct swapz_map){.valid = 1, .raw = 1, .start_block = 3,
        .extent_blocks = 1, .payload_length = SWAPZ_BLOCK_BYTES,
        .raw_crc32c = swapz_crc32c_bytes(raw, sizeof(raw)), .generation = 7};
    classes[3] = 1; live[3] = 1;
    ctx.authority = (struct swapz_authority){.maps = maps, .logical_pages = 2,
        .physical_blocks = 8, .extent_classes = classes, .live_records = live};
    /* RAW never enters compressed coalescing; asynchronous fan-out opts in. */
    assert(!swapz_parallel_read_extent(&ctx, &bio, &start, &blocks, false));
    assert(swapz_parallel_read_extent(&ctx, &bio, &start, &blocks, true));
    assert(start == 3 && blocks == 1 && independence_calls == 1);
    independent = false;
    assert(!swapz_parallel_read_extent(&ctx, &bio, &start, &blocks, true));
    independent = true;
    bio.bi_opf = REQ_FUA;
    assert(!swapz_parallel_read_extent(&ctx, &bio, &start, &blocks, true));
    bio.bi_opf = REQ_PREFLUSH;
    assert(!swapz_parallel_read_extent(&ctx, &bio, &start, &blocks, true));
    bio.bi_opf = 0; bio.op = 1;
    assert(!swapz_parallel_read_extent(&ctx, &bio, &start, &blocks, true));
    bio.op = REQ_OP_READ; maps[0].extent_blocks = 2;
    assert(!swapz_parallel_read_extent(&ctx, &bio, &start, &blocks, true));
    maps[0].extent_blocks = 1; maps[0].start_block = 8;
    assert(!swapz_parallel_read_extent(&ctx, &bio, &start, &blocks, true));
    maps[0].start_block = 3;

    slot.engine.read_scratch = raw; slot.raw = true;
    swapz_read_slot_prepare(&slot, 3, 1);
    assert(!slot.raw && slot.bio_count == 0);
    slot.raw = true; slot.bio_count = 2; slot.bios[0] = slot.bios[1] = &bio;
    slot.read_pages = outputs;
    memset(outputs, 0, sizeof(outputs));
    assert(swapz_read_slot_run(&slot) == 0);
    assert(!memcmp(raw, outputs, sizeof(raw)));
    assert(!memcmp(raw, outputs + sizeof(raw), sizeof(raw)));
    assert(engine_reads == 0);
    /* A corrupt RAW page must fail through the real authority CRC verifier. */
    raw[101] ^= 1;
    assert(swapz_read_slot_run(&slot) == -EBADMSG);
    raw[101] ^= 1;
    classes[3] = 0;
    assert(swapz_read_slot_run(&slot) == -EUCLEAN);
    classes[3] = 1; maps[0].raw = 0;
    assert(swapz_read_slot_run(&slot) == -ESTALE);
    maps[0].raw = 1; maps[0].start_block = 4;
    assert(swapz_read_slot_run(&slot) == -ESTALE);
    maps[0].start_block = 3;
    slot.extent_blocks = 2; maps[0].extent_blocks = 2;
    assert(swapz_read_slot_run(&slot) == -EUCLEAN);
    slot.extent_blocks = maps[0].extent_blocks = 1;

    /* Lower failure joins once and publishes no successful physical work. */
    slot.lower_done.done = 1; slot.lower_submitted = true; slot.lower_error = -EIO;
    slot.lower_blocks = 1; slot.lower_start_ns = 1; slot.lower_end_ns = 3;
    assert(swapz_finish_read_slot_range(&slot) == -EIO);
    assert(!slot.lower_submitted && !slot.physical_read_reqs && seeds == 0);
    slot.lower_submitted = true; slot.lower_error = 0;
    assert(swapz_finish_read_slot_range(&slot) == 0);
    assert(slot.physical_read_reqs == 1 && slot.physical_read_bytes == 4096);
    assert(seeds == 0 && waits == 2);
    slot.raw = false; slot.lower_submitted = true;
    assert(swapz_finish_read_slot_range(&slot) == 0 && seeds == 1);
    return 0;
}
'''
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / "probe.c").write_text(source)
            subprocess.run(["cc", "-std=c11", "-O1", "-Wall", "-Wextra", "-Werror",
                            "-I", str(ROOT / "src/kernel"), str(path / "probe.c"),
                            str(ROOT / "src/kernel/authority.c"),
                            str(ROOT / "src/kernel/codec.c"), "-o", str(path / "probe")],
                           check=True, capture_output=True, text=True)
            subprocess.run([str(path / "probe")], check=True)
        concurrent = body("swapz_try_concurrent_read_slots")
        self.assertRegex(concurrent,
                         r"if \(!slot->raw\)\s+swapz_engine_prime_read_slot")
        self.assertRegex(concurrent,
                         r"if \(!slot->raw\)\s+swapz_engine_absorb_read_slot")

    def test_rejected_read_batches_charge_single_bio_quantum(self):
        import subprocess
        import tempfile

        worker = body("swapz_worker_pass")
        start = worker.index("unsigned int processed_bios = 1;")
        end = worker.index("entry = list_first_entry(&local,", start)
        # Execute the real dispatch selection, including the success gotos.
        # A rejected probe owns no BIOs; its output count is not authoritative.
        dispatch = worker[start:end]
        source = r'''
#include <assert.h>
#include <stdbool.h>
struct probe {
    unsigned int batch, slots, rejected, slot_calls, batch_calls, op;
};
/* The real dispatch source includes observational ID178 READ timing only;
 * this probe verifies the unchanged BIO quantum and reject/success gotos. */
typedef unsigned long long u64;
static u64 ktime_get_ns(void) { return 1; }
static void swapz_lane_gap_note_owner_read(struct probe *ctx,
                                            u64 start, u64 end, unsigned int count)
{ (void)ctx; (void)start; (void)end; (void)count; }
struct bio { unsigned int op; };
struct swapz_bio_ref { struct bio *bio; };
#define REQ_OP_READ 0U
#define bio_op(bio) ((bio)->op)
#define list_first_entry(head, type, member) ((type *)(head))
static bool swapz_try_parallel_read_batch(struct probe *ctx, void *local,
                                        unsigned int remaining,
                                        unsigned int *processed)
{
    (void)local; (void)remaining;
    ctx->batch_calls++;
    *processed = ctx->batch ? ctx->batch : ctx->rejected;
    return ctx->batch != 0;
}
static bool swapz_try_concurrent_read_slots(struct probe *ctx, void *local,
                                          unsigned int remaining,
                                          unsigned int *processed)
{
    (void)local; (void)remaining;
    ctx->slot_calls++;
    *processed = ctx->slots ? ctx->slots : ctx->rejected;
    return ctx->slots != 0;
}
static unsigned int charge(struct probe *ctx, unsigned int remaining)
{
    struct bio bio = {ctx->op};
    struct swapz_bio_ref local = {&bio};
DISPATCH
    return processed_bios;
processed_bio:
    return processed_bios;
}
int main(void)
{
    struct probe ctx = {0};
    unsigned int remaining, completed = 0, count;
    assert(charge(&ctx, 64) == 1); /* coalescer clears count on rejection */
    ctx.rejected = 37;
    assert(charge(&ctx, 64) == 1); /* any rejected speculative output */
    ctx.batch = 5; ctx.slot_calls = 0;
    assert(charge(&ctx, 64) == 5 && ctx.slot_calls == 0);
    ctx.batch = 0; ctx.slots = 3;
    assert(charge(&ctx, 64) == 3);
    ctx.batch = 5; ctx.slot_calls = 0; ctx.batch_calls = 0;
    assert(charge(&ctx, 1) == 1);
    assert(ctx.batch_calls == 0 && ctx.slot_calls == 0);
    ctx.op = 1; ctx.batch = 5; ctx.slots = 3;
    ctx.batch_calls = 0; ctx.slot_calls = 0;
    assert(charge(&ctx, 64) == 1);
    assert(ctx.batch_calls == 0 && ctx.slot_calls == 0);
    ctx.op = REQ_OP_READ; ctx.batch = 0; ctx.slots = 0;
    for (remaining = 64; remaining; remaining -= count) {
        count = charge(&ctx, remaining);
        assert(count == 1 && count <= remaining);
        completed += count;
    }
    assert(completed == 64);
    return 0;
}
'''.replace("DISPATCH", dispatch)
        with tempfile.TemporaryDirectory(prefix="swapz-quantum-") as temp:
            binary = Path(temp) / "quantum"
            compiled = subprocess.run(
                ["cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-x", "c",
                 "-", "-o", str(binary)], input=source, text=True,
                capture_output=True, timeout=30)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            executed = subprocess.run([str(binary)], cwd=temp,
                                      capture_output=True, text=True, timeout=5)
            self.assertEqual(executed.returncode, 0, executed.stderr)

    def test_raw_crc_protection_and_gc_relocation(self):
        auth = (ROOT / "src/kernel/authority.c").read_text()
        auth_h = (ROOT / "src/kernel/authority.h").read_text()
        engine = (ROOT / "src/kernel/engine.c").read_text()
        dm = (ROOT / "src/kernel/dm-target.c").read_text()
        self.assertIn("raw_crc32c", auth_h)
        self.assertIn("_Static_assert(sizeof(struct swapz_map) == 16", auth_h)
        self.assertIn("extent_sequence_delta", auth_h)
        self.assertIn("segment_sequence_base", auth_h)
        self.assertIn("swapz_enable_extent_sequence_index(", dm)
        self.assertIn("kvfree(ctx->extent_sequence_delta)", dm)
        self.assertIn("kvfree(ctx->segment_sequence_base)", dm)
        sequence_delta = source_body("swapz_extent_sequence_delta_for", auth)
        self.assertIn("sequence - base > (swapz_u8)~0U", sequence_delta)
        sequence_reset = source_body("swapz_claim_dead_segment", auth)
        self.assertIn("extent_sequence_delta + start", sequence_reset)
        self.assertIn("segment_sequence_base[segment] = 0", sequence_reset)
        self.assertIn("swapz_verify_raw(", auth)
        self.assertIn("swapz_crc32c_bytes(raw_page, SWAPZ_BLOCK_BYTES)", auth)
        engine_read = source_body("swapz_engine_read_page", engine)
        observed_authority = source_body(
            "swapz_read_observed_authority", auth)
        self.assertLess(engine_read.index("observed.raw"),
                        engine_read.index("observed.payload_offset"))
        self.assertLess(observed_authority.index("current_map->raw"),
                        observed_authority.index("current_map->payload_offset"))
        self.assertIn("swapz_verify_raw(&ctx->authority, logical, ctx->read_page)",
                      body("swapz_read"))
        self.assertIn("swapz_verify_raw(&ctx->authority, logical, ctx->input_page)",
                      body("swapz_gc_move_raw"))

    def test_gc_explicitly_forbids_paused_open_and_victim(self):
        authority = (ROOT / "src/kernel/authority.c").read_text()
        gc = body("swapz_gc_compact_one_inner")
        begin = source_body("swapz_gc_begin_rotation", authority)
        commit = source_body("swapz_gc_commit_rotation", authority)
        roll_forward = source_body("swapz_gc_roll_forward_rotation", authority)
        advance = source_body("swapz_gc_advance_rotation_destination", authority)
        eligible = source_body("swapz_dead_segment_eligible", authority)
        recovery = body("swapz_gc_recovery_validate")
        recovery_advance = body("swapz_gc_recovery_advance_destination")
        self.assertIn("a->gc_forbidden_open = a->open_segment", begin)
        self.assertIn("a->gc_forbidden_victim = victim", begin)
        self.assertIn("segment == a->gc_forbidden_open", eligible)
        self.assertIn("segment == a->gc_forbidden_victim", eligible)
        self.assertIn("victim != a->gc_forbidden_victim", commit)
        self.assertIn("dest == a->gc_forbidden_open", commit)
        self.assertIn(
            "a->gc_forbidden_victim != recovery->victim", recovery)
        self.assertIn(
            "a->gc_forbidden_open != recovery->forbidden_open", recovery)
        self.assertIn("swapz_gc_begin_rotation(a, victim)", gc)
        self.assertIn("swapz_gc_recovery_roll_forward(ctx)", gc)
        self.assertIn("swapz_gc_commit_rotation(a, victim)", gc)
        self.assertIn(
            "swapz_claim_dead_segment(a, evacuated_victim, probe_start)",
            roll_forward)
        self.assertIn(
            "a->segment_foreground[exhausted_destination] = 1",
            roll_forward)
        self.assertIn(
            "a->segment_foreground[evacuated_victim] = 0",
            roll_forward)
        self.assertIn(
            "a->gc_forbidden_victim = exhausted_destination",
            roll_forward)
        self.assertIn("a->gc_destination = evacuated_victim", roll_forward)
        self.assertIn("swapz_verify_recovery_victim_dead(a, segment)", advance)
        self.assertLess(
            advance.index("swapz_claim_dead_segment(a, segment, probe_start)"),
            advance.index("a->segment_foreground[blocked_destination] = 1"))
        self.assertIn("segment == blocked_destination", advance)
        self.assertIn("a->gc_destination = segment", advance)
        self.assertIn(
            "swapz_gc_advance_rotation_destination(", recovery_advance)
        self.assertIn(
            "recovery->destination = a->gc_destination", recovery_advance)
        self.assertIn("goto retry_relocation", gc)
        self.assertIn("recovery_rebound", gc)
        self.assertIn("error = -EUCLEAN", gc)
        self.assertIn("swapz_enable_segment_rotation(&ctx->authority", body("swapz_ctr"))
        self.assertIn("!ctx->segment_roles[segment]", body("swapz_gc_choose_victim"))
        self.assertIn("a->segment_foreground[dest] = 1", commit)
        self.assertIn("a->segment_foreground[victim] = 0", commit)

    def test_optional_write_verify_before_raw_publication(self):
        ctor = body("swapz_ctr")
        verifier = body("swapz_verify_raw_write")
        for name in ("swapz_gc_move_raw", "swapz_raw_write"):
            raw = body(name)
            self.assertLess(raw.index("swapz_verify_raw_write(ctx"),
                            raw.index("swapz_finish_raw(&ctx->authority"))
        self.assertIn("engine.verify_after_write = verify", ctor)
        self.assertIn("verify > 1U", ctor)
        self.assertIn("if (!ctx->engine.verify_after_write)", verifier)
        self.assertIn("return memcmp(", verifier)
        self.assertIn("-EBADMSG", verifier)

    def test_attempted_and_completed_lower_io_are_distinct(self):
        lower = body("swapz_lower")
        self.assertLess(lower.index("ctx->lower_write_submitted_reqs++"),
                        lower.index("error = swapz_dm_io(&req"))
        self.assertLess(lower.index("error = swapz_dm_io(&req"),
                        lower.index("ctx->physical_write_reqs++"))
        self.assertIn("one_page_windows", body("swapz_flush_window"))
        self.assertIn("worker_requeues", body("swapz_worker_pass"))

    def test_online_batching_bounded_and_barrier_first(self):
        admitted = body("swapz_map")
        ctor = body("swapz_ctr")
        drain = body("swapz_drain")
        worker = body("swapz_worker_pass")
        self.assertNotIn("msecs_to_jiffies", admitted)
        self.assertIn("REQ_PREFLUSH | REQ_FUA", admitted)
        self.assertIn("bio_op(bio) != REQ_OP_WRITE", admitted)
        self.assertIn("queue_delayed_work(ctx->workqueue", admitted)
        self.assertIn("mod_delayed_work(ctx->workqueue", admitted)
        self.assertIn("INIT_DELAYED_WORK(&ctx->worker", ctor)
        self.assertIn("ctx->window_size_counts[count]++", body("swapz_flush_window"))
        self.assertIn("ctx->one_page_close_reasons[close_reason]++",
                      body("swapz_flush_window"))
        self.assertIn("win1_read_conflict=%llu win1_read_unrelated=%llu",
                      body("swapz_status"))
        self.assertIn("win1_deadline=%llu win1_pack_ready=%llu",
                      body("swapz_status"))
        for field in ("win1_pack_tail_target=%llu",
                      "win1_pack_read_bypass=%llu",
                      "win1_pack_wave_interrupted=%llu"):
            self.assertIn(field, body("swapz_status"))
        flush = body("swapz_flush_window")
        self.assertIn("win1_pack_tail_target = count == 1U", flush)
        self.assertIn("ctx->retained_tail_target == 1U", flush)
        self.assertIn("win1_pack_read_bypass = count == 1U", flush)
        self.assertIn("ctx->retained_window_read_bypasses", flush)
        self.assertIn("win1_pack_wave_interrupted = count == 1U", flush)
        self.assertIn("ctx->retained_wave_interrupted", flush)
        self.assertIn("ctx->win1_pack_tail_target++", flush)
        self.assertIn("ctx->win1_pack_read_bypass++", flush)
        self.assertIn("ctx->win1_pack_wave_interrupted++", flush)
        self.assertIn("ctx->window_bins[0]++", body("swapz_flush_window"))
        self.assertIn("ctx->window_bins[5]++", body("swapz_flush_window"))
        self.assertIn("gc_read_reqs=%llu gc_write_reqs=%llu", DM)
        self.assertIn("ctx->gc_read_reqs += ctx->physical_read_reqs - before_read_reqs",
                      body("swapz_gc_compact_one_inner"))
        self.assertIn("flush_delayed_work(&ctx->worker)", drain)
        self.assertLess(worker.index("swapz_flush_window(ctx)"),
                        worker.index("list_splice_init(&local, &ctx->incoming)"))

    def test_gc_uses_committed_actual_payload_lengths(self):
        authority = (ROOT / "src/kernel/authority.c").read_text()
        self.assertIn("payload_lengths[index] = decoded.payload_length", authority)
        self.assertIn(".payload_length = payload_lengths[index]", authority)
        self.assertIn(".payload_length = SWAPZ_BLOCK_BYTES", authority)
        self.assertIn("peeked->payload_length != current_map->payload_length", authority)
        self.assertIn("ctx->gc_cost_policy", body("swapz_gc_choose_victim"))
        self.assertIn("gc_selected_live_bytes", body("swapz_gc_choose_victim"))
        # READ coalescing telemetry may appear in global status; GC cost must
        # still expose no synthetic/coalesced GC-byte estimator.
        self.assertNotIn("gc_coalesc", body("swapz_status"))

    def test_worker_close_reasons_cover_dependencies_and_control(self):
        flush = body("swapz_flush_window")
        write = body("swapz_accept_write")
        process = body("swapz_process")
        worker = body("swapz_worker_pass")
        status = body("swapz_status")
        # The implementation snapshots the primary reason before resetting
        # next_window_close so the singleton cross-tab and legacy marginal
        # counter must index the same captured value.
        self.assertIn("ctx->window_close_reasons[close_reason]++", flush)
        self.assertIn("ctx->next_window_close = SWAPZ_CLOSE_UNKNOWN", flush)
        self.assertLess(flush.index("if (!count)"),
                        flush.index("ctx->window_close_reasons[close_reason]++"))
        self.assertIn("ctx->window_gc_pressure++", flush)
        for cause in ("FULL", "DUPLICATE", "ZERO", "FUA", "RAW"):
            self.assertIn("SWAPZ_CLOSE_" + cause, write)
        for cause in ("PREFLUSH", "READ_CONFLICT", "READ_UNRELATED", "DISCARD"):
            self.assertIn("SWAPZ_CLOSE_" + cause, process)
        for cause in ("QUANTUM", "IDLE", "SHUTDOWN"):
            self.assertIn("SWAPZ_CLOSE_" + cause, worker)
        for status_key in ("close_unknown", "close_full", "close_duplicate",
                           "close_zero", "close_fua", "close_raw",
                           "close_read_conflict", "close_read_unrelated",
                           "close_discard", "close_preflush", "close_quantum",
                           "close_idle", "close_shutdown", "close_other",
                           "window_gc_pressure"):
            self.assertIn(status_key + "=%llu", status)
        self.assertIn("swapz_flush_window(ctx)", process)
        self.assertIn("swapz_flush_window(ctx)", worker)

    def test_alpha10_open_age_counts_one_per_window_before_io(self):
        admitted = body("swapz_window_admit_clock")
        flush = body("swapz_flush_window")
        write = body("swapz_accept_write")
        status = body("swapz_status")
        self.assertIn("if (!ctx->batch_count)", admitted)
        self.assertIn("ctx->window_first_ns = ktime_get_ns()", admitted)
        self.assertEqual(write.count("swapz_window_admit_clock(ctx)"), 2)
        self.assertIn("end_ns = ktime_get_ns()", flush)
        self.assertIn("ctx->window_first_ns = 0", flush)
        self.assertLess(flush.index("ctx->window_age_sum_ns += open_age_ns"),
                        flush.index("swapz_order_window(ctx)"))
        for counter in ("window_age_le_100us++",
                        "window_age_101_1000us++", "window_age_gt_1000us++"):
            self.assertIn(counter, flush)
        for field in ("age_le100us", "age_101_1000us", "age_gt1000us",
                      "age_sum_ns", "age_max_ns"):
            self.assertIn(field + "=%llu", status)
        self.assertIn("#include <linux/ktime.h>", DM)

    def test_alpha20_worker_restores_finite_snapshot_requeue(self):
        worker = body("swapz_worker_pass")
        header = (ROOT / "src/kernel/window-policy.h").read_text()
        status = body("swapz_status")
        self.assertIn("for (;;)", worker)
        self.assertIn("remaining = SWAPZ_WORK_QUANTUM_BIOS;", worker)
        self.assertLess(worker.index("for (;;)"),
                        worker.index("remaining = SWAPZ_WORK_QUANTUM_BIOS;"))
        self.assertIn("while (remaining && !list_empty(&local))", worker)
        self.assertIn("remaining -= processed_bios", worker)
        self.assertIn("unsigned int processed_bios = 1", worker)
        self.assertIn("list_splice_tail_init(&ctx->incoming, &local)", worker)
        self.assertIn("list_splice_init(&local, &ctx->incoming)", worker)
        self.assertIn("if (ctx->accepting) {", worker)
        self.assertIn("ctx->worker_requeues++", worker)
        self.assertIn("mod_delayed_work(ctx->workqueue, &ctx->worker, 0)", worker)
        self.assertLess(worker.index("list_splice_init(&local, &ctx->incoming)"),
                        worker.index("ctx->worker_requeues++"))
        self.assertIn("cond_resched();", worker)
        self.assertNotIn("swapz_worker_can_inline_drain", worker)
        self.assertNotIn("swapz_worker_can_inline_drain", header)
        self.assertNotIn("worker_inline_drains", status)
        self.assertIn("hrtimer_cancel(&ctx->retention_timer)", body("swapz_drain"))
        self.assertIn("drain_workqueue(ctx->workqueue)", body("swapz_drain"))
        self.assertIn("swapz_flush_window(ctx)", worker)

    def test_retained_burst_target_learns_only_from_admitted_tail(self):
        flush = body("swapz_flush_window")
        worker = body("swapz_worker_pass")
        sample = body("swapz_sample_pack_tail_locked")
        status = body("swapz_status")
        policy = (ROOT / "src/kernel/window-policy.h").read_text()
        self.assertIn("swapz_window_initial_burst_target", policy)
        self.assertIn("swapz_window_grow_burst_target", policy)
        self.assertIn("swapz_window_shrink_burst_target", policy)
        self.assertIn("swapz_window_burst_close_ready", policy)
        self.assertIn("ctx->retained_chain_completed", flush)
        self.assertIn("if (chain_continues)", flush)
        self.assertIn("unsigned int chain = packed_close ?", flush)
        self.assertIn("count : (unsigned int)ctx->retained_chain_completed + count", flush)
        self.assertIn("ctx->pack_close_pending_tail_sample = packed_close", flush)
        self.assertIn("list_for_each_entry(entry, local, list)", sample)
        self.assertIn("list_for_each_entry(entry, &ctx->incoming, list)", sample)
        self.assertLess(sample.index("list_for_each_entry(entry, local, list)"),
                        sample.index("list_for_each_entry(entry, &ctx->incoming, list)"))
        self.assertIn("swapz_plain_retained_write(entry->bio)", sample)
        self.assertIn("if (!ctx->pack_close_pending_tail_sample)", sample)
        self.assertIn("if (swapz_has_inflight(ctx))", sample)
        self.assertLess(sample.index("if (swapz_has_inflight(ctx))"),
                        sample.index("room = ctx->retained_chain_completed"))
        self.assertIn("staged_tail = min_t(swapz_u8, ctx->batch_count, room)", sample)
        self.assertLess(sample.index("staged_tail = min_t(swapz_u8, ctx->batch_count, room)"),
                        sample.index("list_for_each_entry(entry, local, list)"))
        self.assertIn("queued_tail++", sample)
        self.assertIn("ctx->retained_chain_completed,\n\t\t\tstaged_tail, ctx->max_window", sample)
        self.assertNotIn("ctx->retained_chain_completed,\n\t\t\ttail, ctx->max_window", sample)
        self.assertNotIn("swapz_window_post_pack_sample_ready", policy)
        self.assertNotIn("swapz_window_post_pack_learning_tail", policy)
        self.assertNotIn("swapz_window_post_pack_close_target", policy)
        self.assertNotIn("base_completed", sample)
        self.assertIn("if (tail == 1U)", sample)
        self.assertIn("ctx->retained_tail_target = 0", sample)
        self.assertIn("ctx->single_tail_deferrals++", sample)
        self.assertIn("ctx->retained_single_tail_deferred = true", sample)
        self.assertIn("ctx->single_tail_other_clears++", sample)
        self.assertIn("tail, queued_tail,", sample)
        self.assertIn("swapz_window_sampled_tail_target(", policy)
        self.assertIn("tail < SWAPZ_WINDOW_DRY_PACK_MIN_RECORDS", policy)
        self.assertIn("ctx->retained_single_tail_deferred = false", sample)
        self.assertNotIn("ctx->single_pack_deferred && !ctx->retained_tail_target", sample)
        map_body = body("swapz_map")
        process_body = body("swapz_process")
        parallel_slots = body("swapz_try_concurrent_read_slots")
        parallel_batch = body("swapz_try_parallel_read_batch")
        self.assertNotIn("closed_small_tail_target", DM)
        self.assertNotIn("closed_small_tail_deadline_ns", DM)
        self.assertNotIn("swapz_note_closed_small_tail_companion_locked", DM)
        self.assertNotIn("swapz_arm_closed_small_tail_observation", DM)
        self.assertNotIn("suppressed_tail_", DM)
        self.assertNotIn("SWAPZ_SUPPRESSED_TAIL_RESUBMIT_NS", policy)
        self.assertIn("!prefix_open || saw_independent_read", sample)
        self.assertIn("queued_tail && ctx->retained_wave_read_seen", sample)
        self.assertIn("scan_truncated ? 0 :", sample)
        self.assertIn("scanned_bios++ >= SWAPZ_WORK_QUANTUM_BIOS", sample)
        self.assertIn("swapz_tail_read_is_independent_locked(", sample)
        independent = body("swapz_tail_read_is_independent_locked")
        self.assertIn("ctx->batch[index].logical == logical", independent)
        self.assertIn("queued_writes[index] == logical", independent)
        self.assertIn("bio_sectors(bio) != SWAPZ_SECTORS", independent)
        self.assertIn("ctx->authority.batch_pending", independent)
        self.assertNotIn("ctx->retained_wave_read_seen = true", sample)
        self.assertIn("prefix_open = false", sample)
        self.assertIn("ctx->retained_wave_read_seen = true", process_body)
        self.assertIn("ctx->retained_wave_read_seen = true", parallel_slots)
        self.assertIn("ctx->retained_wave_read_seen = true", parallel_batch)
        self.assertNotIn("retained_wave_read_seen", map_body)
        replay = (ROOT / "tests/runtime/benchmark/io-replay.py").read_text()
        runner = (ROOT / "tests/tools/run-tests.py").read_text()
        self.assertNotIn("SUPPRESSED_TAIL_FIELDS", replay)
        self.assertNotIn("SUPPRESSED_TAIL_FIELDS", runner)
        self.assertNotIn("suppressed_tail_", replay)
        self.assertNotIn("suppressed_tail_", runner)
        for field in ("pack_close_tail_target_2", "pack_close_tail_target_3",
                      "pack_close_tail_target_4"):
            self.assertIn(field + "=%llu", status)
            self.assertIn("ctx->" + field, status)
            self.assertIn(f'"{field}"', replay)
            self.assertIn(f'"{field}"', runner)
        self.assertIn("swapz_sample_pack_tail_locked(ctx, &local)", worker)
        top_finalize = worker.index("while (swapz_has_inflight(ctx))")
        top_sample = worker.index("swapz_sample_pack_tail_locked(ctx, &local)",
                                  top_finalize)
        top_splice = worker.index("list_splice_init(&ctx->incoming, &local)",
                                  top_sample)
        self.assertLess(top_sample, top_splice)
        processed = worker.index("processed_bio:")
        processed_finalize = worker.index(
            "swapz_finalize_inflight_write(ctx, false)", processed)
        processed_sample = worker.index(
            "swapz_sample_pack_tail_locked(ctx, &local)", processed_finalize)
        processed_tail = worker.index(
            "if (remaining > 1U && list_empty(&local))", processed_sample)
        self.assertLess(processed_finalize, processed_sample)
        self.assertLess(processed_sample, processed_tail)
        self.assertIn("if (!ctx->batch_count && !swapz_has_inflight(ctx))", worker)
        self.assertIn("swapz_window_shrink_burst_target(", worker)
        self.assertNotIn("!ctx->retained_chain_completed", worker)
        close_ready = body("swapz_retained_pack_close_ready")
        service_dry = body("swapz_service_proven_dry_pack")
        self.assertNotIn("swapz_retained_target_close_ready", DM)
        self.assertIn("swapz_window_service_close_ready(", service_dry)
        self.assertIn("swapz_window_service_close_ready(", policy)
        self.assertNotIn("pack_close_pending_tail_sample", close_ready)
        self.assertIn("ctx->retained_single_tail_deferred && ctx->batch_count == 1U",
                      close_ready)
        self.assertIn("swapz_service_proven_dry_pack(ctx)", close_ready)
        self.assertIn("ctx->batch_count", service_dry)
        self.assertIn("ctx->retained_chain_completed", service_dry)
        self.assertIn("ctx->retained_window_read_bypasses", service_dry)
        self.assertIn("ctx->retained_wave_interrupted", service_dry)
        self.assertIn("swapz_window_post_pack_read_boundary_ready(", service_dry)
        self.assertIn("ctx->retained_post_pack_read_boundary", service_dry)
        boundary_observer = body("swapz_note_post_pack_read_boundary")
        admit_clock = body("swapz_window_admit_clock")
        self.assertIn("ctx->retained_post_pack_read_boundary = true;",
                      boundary_observer)
        self.assertIn("swapz_window_post_pack_read_boundary_observed(",
                      boundary_observer)
        self.assertNotIn("pack_close_pending_tail_sample", boundary_observer)
        self.assertIn("ctx->retained_post_pack_read_boundary = false;",
                      admit_clock)
        self.assertIn("ctx->retained_post_pack_read_boundary = false;",
                      body("swapz_flush_window"))
        self.assertIn("swapz_note_post_pack_read_boundary(ctx);", process_body)
        self.assertIn("swapz_note_post_pack_read_boundary(ctx);", parallel_slots)
        self.assertIn("swapz_note_post_pack_read_boundary(ctx);", parallel_batch)
        self.assertLess(parallel_slots.rfind("if (batch_error)"),
                        parallel_slots.rfind("swapz_note_post_pack_read_boundary(ctx)"))
        self.assertLess(parallel_batch.rfind("if (batch_error)"),
                        parallel_batch.rfind("swapz_note_post_pack_read_boundary(ctx)"))
        boundary_policy = source_body(
            "swapz_window_post_pack_read_boundary_ready", policy)
        self.assertIn("read_serviced_after_tail && !tail_sample_pending",
                      boundary_policy)
        self.assertIn("count < SWAPZ_WINDOW_DRY_PACK_MIN_RECORDS",
                      boundary_policy)
        self.assertIn("!swapz_has_inflight(ctx)", service_dry)
        service_policy = source_body("swapz_window_service_close_ready", policy)
        self.assertIn("if (count < 2U || sampled_tail_target)", service_policy)
        self.assertIn("count >= SWAPZ_WINDOW_DRY_PACK_MIN_RECORDS && lower_idle", service_policy)
        self.assertIn("if (!valid_pack)", service_policy)
        self.assertLess(service_policy.index("if (count < 2U || sampled_tail_target)"),
                        service_policy.index("count >= SWAPZ_WINDOW_DRY_PACK_MIN_RECORDS && lower_idle"))
        self.assertIn("count < SWAPZ_WINDOW_DRY_PACK_MIN_RECORDS",
                      service_policy)
        self.assertIn("return read_bypasses || wave_interrupted",
                      service_policy)
        self.assertIn("return chain_completed || read_bypasses", service_policy)
        self.assertIn("swapz_window_burst_close_ready(", close_ready)
        self.assertIn("retained_burst_target=%u", status)
        self.assertIn("#define SWAPZ_WINDOW_DRY_PACK_MIN_RECORDS 4U", policy)
        self.assertIn("int has_valid_pack", policy)
        self.assertIn("next_local_is_plain_write || admitted_tail_target", policy)
        self.assertIn("count >= SWAPZ_WINDOW_DRY_PACK_MIN_RECORDS", policy)
        self.assertIn("if (count < 2U)", policy)
        accept = body("swapz_accept_write")
        companion = body("swapz_resolve_single_tail_companion")
        self.assertIn("swapz_resolve_single_tail_companion(ctx)", accept)
        self.assertIn("ctx->single_tail_companions++", companion)
        self.assertIn("ctx->retained_single_tail_deferred = false", companion)
        self.assertIn("bool deferred_single_tail = ctx->retained_single_tail_deferred", flush)
        self.assertIn("ctx->win1_deadline_deferred_tail++", flush)
        self.assertIn("ctx->win1_idle_deferred_tail++", flush)
        self.assertIn("ctx->single_tail_other_clears++", flush)
        self.assertIn("ctx->single_tail_other_clears++", worker)
        for field in ("single_tail_deferrals", "single_tail_companions",
                      "win1_deadline_deferred_tail", "win1_idle_deferred_tail",
                      "single_tail_other_clears"):
            self.assertIn(field + "=%llu", status)
            self.assertIn("ctx->" + field, status)
        terminal = body("swapz_account_single_tail_terminal")
        finalize = body("swapz_finalize_inflight_write")
        process = body("swapz_process")
        parallel_batch = body("swapz_try_parallel_read_batch")
        self.assertIn("ctx->single_tail_deferred_start_ns = ktime_get_ns()", sample)
        self.assertNotIn("SWAPZ_SINGLE_TAIL_CUTOFF_NS", DM)
        self.assertNotIn("swapz_window_single_tail_deadline_ns(", DM)
        self.assertNotIn("single_tail_age_cutoff_closes", DM)
        self.assertNotIn("single_tail_cutoff_late_companions", DM)
        self.assertNotIn("single_tail_cutoff_original_deadline_ns", DM)
        deadline = body("swapz_first_record_deadline_ns")
        self.assertIn("swapz_window_retention_deadline_ns(", deadline)
        self.assertNotIn("single_tail_deferred_start_ns", deadline)
        self.assertNotIn("single_tail_deferred_start_ns",
                         body("swapz_retention_deadline_ns"))
        self.assertIn("!ctx->retained_single_tail_deferred", worker)
        self.assertIn("ctx->single_tail_lower_done_seen = false", sample)
        self.assertIn("ctx->single_tail_read_bypass_seen = false", sample)
        self.assertIn("elapsed <= 250000ULL", terminal)
        self.assertIn("elapsed <= 500000ULL", terminal)
        self.assertIn("elapsed <= 1000000ULL", terminal)
        self.assertIn("elapsed <= 1250000ULL", terminal)
        self.assertIn("elapsed <= 1500000ULL", terminal)
        self.assertIn("elapsed <= 1750000ULL", terminal)
        self.assertIn("single_tail_companion_age_1001_1250us", terminal)
        self.assertIn("single_tail_companion_age_1251_1500us", terminal)
        self.assertIn("single_tail_companion_age_1501_1750us", terminal)
        self.assertIn("single_tail_companion_age_gt1750us", terminal)
        self.assertIn("single_tail_companion_after_lower_done", terminal)
        self.assertIn("single_tail_deadline_after_read_bypass", terminal)
        self.assertIn("single_tail_deadline_after_both", terminal)
        self.assertIn("ctx->single_tail_lower_done_seen = true", finalize)
        self.assertIn("swapz_note_single_tail_read_bypass(ctx)", process)
        self.assertIn("swapz_note_single_tail_read_bypass(ctx)", parallel_batch)
        for label, member in (
                ("single_tail_comp_age_le250us", "single_tail_companion_age_le250us"),
                ("single_tail_comp_age_251_500us", "single_tail_companion_age_251_500us"),
                ("single_tail_comp_age_501_1000us", "single_tail_companion_age_501_1000us"),
                ("single_tail_comp_age_gt1000us", "single_tail_companion_age_gt1000us"),
                ("single_tail_comp_age_1001_1250us", "single_tail_companion_age_1001_1250us"),
                ("single_tail_comp_age_1251_1500us", "single_tail_companion_age_1251_1500us"),
                ("single_tail_comp_age_1501_1750us", "single_tail_companion_age_1501_1750us"),
                ("single_tail_comp_age_gt1750us", "single_tail_companion_age_gt1750us"),
                ("single_tail_deadline_age_le250us", "single_tail_deadline_age_le250us"),
                ("single_tail_deadline_age_251_500us", "single_tail_deadline_age_251_500us"),
                ("single_tail_deadline_age_501_1000us", "single_tail_deadline_age_501_1000us"),
                ("single_tail_deadline_age_gt1000us", "single_tail_deadline_age_gt1000us"),
                ("single_tail_comp_after_lower_done", "single_tail_companion_after_lower_done"),
                ("single_tail_comp_after_read_bypass", "single_tail_companion_after_read_bypass"),
                ("single_tail_comp_after_both", "single_tail_companion_after_both"),
                ("single_tail_deadline_after_lower_done", "single_tail_deadline_after_lower_done"),
                ("single_tail_deadline_after_read_bypass", "single_tail_deadline_after_read_bypass"),
                ("single_tail_deadline_after_both", "single_tail_deadline_after_both")):
            self.assertIn(label + "=%llu", status)
            self.assertIn("ctx->" + member, status)

    def test_worker_wall_and_scheduler_cpu_attribution_are_separate(self):
        policy = (ROOT / "src/kernel/window-policy.h").read_text()
        lower = body("swapz_lower")
        accept = body("swapz_accept_write")
        compressor = body("swapz_compress_page")
        read = body("swapz_read")
        flush = body("swapz_flush_window")
        producer = body("swapz_preparation_worker")
        worker = body("swapz_worker_pass")
        status = body("swapz_status")
        totals = body("swapz_preparation_totals_snapshot")
        engine_prepare = source_body("swapz_engine_prepare_batched_run", ENGINE)
        engine_complete = source_body("swapz_engine_complete_batched_run", ENGINE)
        self.assertIn("static inline unsigned long long swapz_elapsed_ns", policy)
        self.assertIn("end_ns >= start_ns ? end_ns - start_ns : 0", policy)
        self.assertIn("section_start = ktime_get_ns();", lower)
        self.assertLess(lower.index("section_start = ktime_get_ns();"),
                        lower.index("error = swapz_dm_io("))
        self.assertIn("ctx->lower_read_wall_ns +=", lower)
        self.assertIn("ctx->lower_write_wall_ns +=", lower)
        self.assertIn("swapz_compress_page(", accept)
        self.assertIn("*lz4_wall_ns += swapz_elapsed_ns", compressor)
        self.assertIn("ctx->decode_wall_ns +=", read)
        self.assertIn("ctx->window_sort_wall_ns +=", flush)
        self.assertIn("ctx->window_commit_wall_ns +=", flush)
        self.assertIn("e->plan_wall_ns +=", engine_prepare)
        self.assertIn("e->publish_wall_ns +=", engine_complete)
        compact = body("swapz_gc_compact_one")
        self.assertIn("ctx->gc_wall_ns +=", compact)
        self.assertIn("#include <linux/sched.h>", DM)
        self.assertNotIn("#include <linux/sched/cputime.h>", DM)
        self.assertNotIn("task_cputime_adjusted(current", DM)
        cpu_sample = body("swapz_worker_cpu_sample")
        self.assertIn("READ_ONCE(current->se.sum_exec_runtime)", cpu_sample)
        self.assertIn("cpu_start_ns = swapz_worker_cpu_sample()", producer)
        self.assertIn("cpu_start_ns = swapz_worker_cpu_sample()", worker)
        self.assertIn("lane->worker_cpu_ns +=", producer)
        self.assertIn("ctx->ordered_worker_cpu_ns", worker)
        self.assertIn("READ_ONCE(lane->worker_cpu_ns)", totals)
        self.assertNotIn("swapz_read_slot_worker", DM)
        self.assertNotIn("read_worker_cpu_ns +=", DM)
        self.assertIn("prep_worker_wall_ns=%llu", status)
        self.assertIn("prep_worker_cpu_ns=%llu", status)
        self.assertIn("prep->worker_wall_ns", status)
        self.assertIn("prep->worker_cpu_ns", status)
        for key in ("lz4_wall_ns", "decode_wall_ns", "read_copy_wall_ns",
                    "read_copy_bytes", "read_engine_nonio_wall_ns",
                    "window_sort_wall_ns", "window_commit_wall_ns",
                    "window_commit_nonio_wall_ns", "engine_plan_wall_ns",
                    "engine_pack_wall_ns", "engine_publish_wall_ns",
                    "engine_publish_crc_wall_ns",
                    "lower_read_wall_ns", "lower_write_wall_ns",
                    "ordered_worker_wall_ns", "ordered_worker_cpu_ns",
                    "read_worker_cpu_ns", "gc_wall_ns",
                    "gc_choose_wall_ns", "gc_choose_calls",
                    "gc_choose_map_entries", "gc_choose_segment_entries",
                    "gc_relocation_map_entries", "ordered_crc_wall_ns",
                    "prep_lower_write_samples",
                    "prep_lower_write_start_queued",
                    "prep_lower_write_start_nonempty",
                    "prep_lower_write_end_queued",
                    "prep_lower_write_end_nonempty"):
            self.assertIn(key + "=%llu", status)
        self.assertIn("engine_publish_auth_wall_ns=%llu", status)
        self.assertIn("prep_crc_wall_ns=%llu", status)
        self.assertIn("prep->crc_wall_ns", status)

    def test_id61_native_gc_scan_scaling_is_bounded_and_reported(self):
        scale = (ROOT / "tests/runtime/native/gc/scan-scaling.c").read_text()
        suites = (ROOT / "tests/suites/Makefile").read_text()
        runner = (ROOT / "tests/tools/run-tests.py").read_text()
        self.assertIn('print("       loaded qualification progress:")', runner)
        self.assertIn("subprocess.Popen(", runner)
        self.assertIn("def loaded_progress_line(line):", runner)
        self.assertIn("progress = loaded_progress_line(line)", runner)
        self.assertIn('sys.stdout.write("       " + progress + "\\n")', runner)
        self.assertNotIn('sys.stdout.write("       " + line)', runner)
        authority = (ROOT / "src/kernel/authority.h").read_text()

        self.assertIn("262144U, 1048576U", scale)
        self.assertIn("legacy_score_scan", scale)
        self.assertIn("incremental_select", scale)
        self.assertIn("relocation_scan", scale)
        self.assertIn("SWAPZ_GC_SCAN_SCALE_EVIDENCE=", scale)
        self.assertIn("gc-scan-scaling", suites)
        self.assertIn("def parse_gc_scan_scale_evidence", runner)
        self.assertIn("OFFLINE_NATIVE_GC_SCALE_ONLY", runner)
        self.assertNotIn("reverse_index", authority)
        self.assertNotIn("logical_backref", authority)

    def test_id63_read_coalescing_is_cache_coherent(self):
        header = (ROOT / "src/kernel/engine.h").read_text()
        engine = (ROOT / "src/kernel/engine.c").read_text()
        batch = body("swapz_try_parallel_read_batch")
        slot_run = body("swapz_read_slot_run")
        lower = body("swapz_parallel_lower_read")
        invalidation = body("swapz_invalidate_read_caches")
        ctor = body("swapz_ctr")
        freeing = body("swapz_free")
        status = body("swapz_status")

        self.assertIn("#define SWAPZ_PARALLEL_READ_SLOTS (2U * SWAPZ_MAX_BLOCKS)", header)
        self.assertIn("#define SWAPZ_READ_EXTENT_CACHE_ENTRIES 16U", header)
        self.assertIn("read_extent_cache", header)
        self.assertIn("swapz_engine_prime_read_slot", header)
        self.assertIn("swapz_engine_absorb_read_slot", header)
        self.assertIn("swapz_engine_required_read_range", header)
        self.assertIn("swapz_engine_required_read_range_cached", header)
        self.assertIn("swapz_engine_coalesced_span", header)
        self.assertIn("swapz_engine_coalesce_read_chain", header)
        self.assertIn("swapz_engine_coalesce_read_pair", header)
        self.assertIn("read_coalesced_block_mask", header)
        self.assertIn("struct swapz_read_slot", DM)
        self.assertIn("struct swapz_engine engine;", DM)
        self.assertIn("struct bio *bios[SWAPZ_MAX_RECORDS]", DM)
        self.assertIn("u8 *read_pages", DM)
        self.assertNotIn("read_workqueue", DM)
        self.assertNotIn("swapz_read_slot_worker", DM)
        self.assertIn("SWAPZ_MERGE_READ_COUNTER(physical_read_blocks)", engine)
        self.assertIn("swapz_read_extent_lru_lookup", engine)
        self.assertIn("swapz_read_extent_lru_commit", engine)
        self.assertIn("swapz_engine_prime_read_slot", engine)
        self.assertIn("swapz_engine_absorb_read_slot", engine)
        self.assertIn("int swapz_engine_required_read_range", engine)
        self.assertIn("int swapz_engine_required_read_range_cached", engine)
        self.assertIn("int swapz_engine_coalesced_span", engine)
        self.assertIn("int swapz_engine_coalesce_read_chain", engine)
        self.assertIn("int swapz_engine_coalesce_read_pair", engine)
        self.assertIn("engine->read_coalesced_block_mask", engine)
        self.assertIn("read_extent_lru_valid",
                      source_body("swapz_engine_invalidate_read_cache", engine))
        self.assertIn("!ctx->read_grouping_enabled", batch)
        self.assertIn("!ctx->read_coalescing_enabled", batch)
        self.assertLess(batch.index("!ctx->read_coalescing_enabled"),
                        batch.index("head_range_error = swapz_engine_required_read_range_cached("))
        self.assertLess(batch.index("!ctx->read_coalescing_enabled"),
                        batch.index("swapz_adjacent_extent_chain_candidate("))
        self.assertIn("list_for_each_entry(entry, local, list)", batch)
        self.assertIn("swapz_read_can_parallel(ctx, entry->bio)", batch)
        self.assertIn("swapz_parallel_read_extent", batch)
        self.assertIn("swapz_adjacent_extent_chain_candidate(", batch)
        self.assertIn("swapz_engine_required_read_range_cached(", batch)
        self.assertIn("head_range_error = swapz_engine_required_read_range_cached(", batch)
        self.assertIn("if (!head_range_error && !head_blocks)", batch)
        self.assertLess(
            batch.index("head_range_error = swapz_engine_required_read_range_cached("),
            batch.index("swapz_adjacent_extent_chain_candidate("))
        self.assertIn("swapz_engine_prime_read_slot(&ctx->engine", batch)
        self.assertIn("swapz_engine_coalesce_read_chain(", batch)
        self.assertIn("covered_prefix++", batch)
        self.assertIn("if (covered_prefix != prefix &&", batch)
        self.assertLess(batch.index("if (covered_prefix != prefix &&"),
                        batch.index("swapz_engine_coalesce_read_chain("))
        self.assertIn("execute_count = chain_last - chain_first + 1U", batch)
        self.assertIn("if (execute_count != chain_count)", batch)
        self.assertLess(batch.index("if (execute_count != chain_count)"),
                        batch.index("swapz_engine_coalesce_read_chain("))
        self.assertIn("parallel_read_coalesced_reqs_saved += execute_count - 1U", batch)
        self.assertIn("ctx->read_pages_store +", batch)
        self.assertLess(batch.index("swapz_engine_required_read_range_cached("),
                        batch.index("swapz_engine_prime_read_slot(&ctx->engine"))
        self.assertLess(batch.index("chain_last == chain_first"),
                        batch.index("swapz_engine_prime_read_slot(&ctx->engine"))
        self.assertLess(batch.index("swapz_engine_prime_read_slot(&ctx->engine"),
                        batch.index("list_del_init(&entry->list)"))
        self.assertNotIn("queue_work(ctx->read_workqueue", batch)
        self.assertNotIn("wait_for_completion(", batch)
        self.assertNotIn("flush_work(", batch)
        self.assertIn("slot->error = swapz_read_slot_run(slot)", batch)
        self.assertIn("swapz_engine_absorb_read_slot", body("swapz_merge_read_slot"))
        self.assertIn("*processed_out = selected", batch)
        self.assertIn("swapz_copy_bio_accounted(", batch)
        self.assertIn("swapz_complete(slot->bios[index]", batch)
        success_complete = batch.rindex("swapz_complete(slot->bios[index], 0)")
        success_absorb = batch.rindex("swapz_engine_absorb_read_slot(")
        # A slot may ACK after its own generation/CRC validation and copy.
        # Later unrelated slot failure must only fail BIOs still worker-owned.
        self.assertLess(batch.index("slot->error = swapz_read_slot_run(slot)"),
                        success_complete)
        self.assertIn("slot->bios[index] = NULL", batch)
        self.assertIn("if (slot->bios[index])", batch)
        self.assertLess(success_complete, success_absorb)
        self.assertNotIn("swapz_complete(", slot_run)
        self.assertNotIn("swapz_finish(", slot_run)
        self.assertNotIn("swapz_stage(", slot_run)
        self.assertIn("for (index = 0; index < slot->bio_count; ++index)", slot_run)
        self.assertIn("REQ_OP_READ | REQ_SWAP | REQ_SYNC", lower)
        self.assertNotIn("ctx->physical_read_reqs++", lower)
        self.assertIn("slot->physical_read_reqs++", lower)
        self.assertIn("swapz_engine_invalidate_read_cache(&ctx->engine)", invalidation)
        self.assertIn("swapz_engine_invalidate_read_cache(&ctx->read_slots[slot].engine)",
                      invalidation)
        self.assertNotIn("module_param_named(parallel_reads,", DM)
        self.assertNotIn("static bool swapz_parallel_reads", DM)
        self.assertIn("static bool swapz_read_coalesce = true;", DM)
        self.assertIn("module_param_named(read_coalesce, swapz_read_coalesce, bool, 0444)", DM)
        self.assertNotIn("module_param_named(read_coalesce_max_blocks,", DM)
        self.assertNotIn("module_param_named(k1_allow_after_read_bypass,", DM)
        self.assertIn("k1_allow_after_read_bypass=0", status)
        self.assertIn("module_param_named(invalidate_cache_on_write_admit,", DM)
        self.assertIn("ctx->read_grouping_enabled = true;", ctor)
        self.assertIn("ctx->read_coalescing_enabled = swapz_read_coalesce;", ctor)
        self.assertNotIn("ctx->read_coalesce_max_blocks", DM)
        self.assertIn("#define SWAPZ_READ_COALESCE_MAX_BLOCKS (2U * SWAPZ_MAX_BLOCKS)", DM)
        self.assertNotIn("bdev_get_queue(ctx->backing->bdev)->nr_requests > 1U", ctor)
        self.assertIn("if (ctx->read_grouping_enabled)", ctor)
        self.assertIn("SWAPZ_READ_EXTENT_CACHE_ENTRIES * SWAPZ_MAX_EXTENT_BYTES", ctor)
        self.assertNotIn('"swapz-read"', ctor)
        self.assertIn("slot->engine.read_scratch = vzalloc(SWAPZ_MAX_EXTENT_BYTES)", ctor)
        self.assertIn("ctx->read_pages_store =", ctor)
        self.assertNotIn("slot->read_pages = vzalloc(", ctor)
        self.assertIn("vfree(ctx->engine.read_extent_cache)", freeing)
        self.assertIn("vfree(ctx->read_pages_store)", freeing)
        self.assertNotIn("vfree(ctx->read_slots[slot].read_pages)", freeing)
        self.assertIn("read_worker_cpu_ns=%llu", status)
        self.assertIn("read_grouping_enabled=%u", status)
        self.assertIn("read_coalescing_enabled=%u", status)
        self.assertIn("parallel_reads_enabled=%u", status)
        self.assertIn("parallel_read_pairs=%llu", status)
        self.assertIn("parallel_read_same_extent_pairs=%llu", status)
        self.assertIn("parallel_read_async_batches=%llu", status)
        self.assertIn("parallel_read_async_slots=%llu", status)
        self.assertIn("parallel_read_distinct_extent_pairs=%llu", status)
        self.assertIn("parallel_read_adjacent_extent_pairs=%llu", status)
        self.assertIn("parallel_read_adjacent_extent_blocks=%llu", status)
        self.assertIn("parallel_read_coalesced_pairs=%llu", status)
        self.assertIn("parallel_read_coalesced_reqs_saved=%llu", status)
        self.assertIn("parallel_read_coalesced_blocks=%llu", status)
        self.assertIn("parallel_read_coalesce_extra_blocks=%llu", status)
        for field in (
                "parallel_read_coalesce_skip_cached",
                "parallel_read_coalesce_skip_noncontig_slot",
                "parallel_read_coalesce_skip_gap",
                "parallel_read_coalesce_skip_other"):
            self.assertIn(field + "=%llu", status)

        pair = (ROOT / "tests/tools/benchmark-owned-pair.sh").read_text()
        loaded = (ROOT / "tests/tools/test-loaded.sh").read_text()
        runner = (ROOT / "tests/tools/run-tests.py").read_text()
        self.assertNotIn("--parallel-reads", pair)
        self.assertIn("--read-coalesce 0|1", pair)
        self.assertNotIn("--read-coalesce-max-blocks", pair)
        self.assertNotIn("--k1-allow-after-read-bypass", pair)
        self.assertNotIn("$K1_ALLOW_AFTER_READ_BYPASS", pair)
        self.assertIn("--invalidate-cache-on-write-admit 0|1", pair)
        self.assertIn("PARALLEL_READS=1", pair)
        self.assertNotIn("$PARALLEL_READS", pair)
        self.assertIn('"read_coalesce=$READ_COALESCE"', pair)
        self.assertIn("read_coalesce_max_blocks=8", pair)
        self.assertIn("k1_allow_after_read_bypass=0", pair)
        self.assertIn('"invalidate_cache_on_write_admit=$INVALIDATE_CACHE_ON_WRITE_ADMIT"', pair)
        self.assertIn("expected_grouping=1", pair)
        self.assertIn("expected_coalescing=$READ_COALESCE", pair)
        self.assertIn("expected_parallel=1", pair)
        self.assertIn("parallel_reads_enabled=$expected_parallel", pair)
        self.assertNotIn('for parallel_reads in "${directional_modes[@]}"', loaded)
        self.assertNotIn("START_BURST_GUARD_AB=", loaded)
        self.assertNotIn("PASS_BURST_GUARD_AB=", loaded)
        self.assertNotIn("--guard-inflight-zero-shrink", pair)
        self.assertIn("guard_inflight_zero_shrink=0", pair)
        self.assertNotIn("START_PARALLEL_READ_AB=", loaded)
        self.assertNotIn("PASS_PARALLEL_READ_AB=", loaded)
        self.assertNotIn('for parallel_reads in "${confirmation_modes[@]}"', loaded)
        self.assertNotIn('--parallel-reads "$parallel_reads"', loaded)
        self.assertNotIn("START_SD_READ_GROUPING_AB=", loaded)
        self.assertIn("START_READ_COALESCE_AB=", loaded)
        self.assertIn('for read_coalesce in "${confirmation_modes[@]}"', loaded)
        self.assertIn("START_SD_READ_COALESCE_AB=", loaded)
        self.assertIn("--lower-mbps 10 --hw-queue-depth 1 --completion-nsec 1000000",
                      loaded)
        self.assertIn("def parse_parallel_read_ab", runner)
        self.assertIn("def parallel_read_ab_verdict", runner)
        self.assertIn("PASS_PARALLEL_READ_AB_EVIDENCE", runner)
        self.assertIn("parallel_read_async_batches", runner)
        self.assertIn("parallel_read_async_slots", runner)
        self.assertNotIn("PASS_PARALLEL_READ_DIRECTIONAL_CONTROL", runner)
        self.assertNotIn("def parse_burst_guard_ab", runner)
        self.assertNotIn("PASS_BURST_GUARD_AB_CONFIRMATION", runner)
        self.assertIn("def parse_read_coalesce_ab", runner)
        self.assertIn("PASS_READ_COALESCE_AB_CONFIRMATION", runner)
        self.assertNotIn("def parse_sd_read_grouping_ab", runner)
        self.assertNotIn("PASS_SD_READ_GROUPING_DIRECTIONAL_CONTROL", runner)
        self.assertIn("def parse_sd_read_coalesce_ab", runner)
        self.assertIn("PASS_SD_READ_COALESCE_AB_CONFIRMATION", runner)
        self.assertIn("def parse_k1_read_bypass_ab", runner)
        self.assertIn("PASS_K1_READ_BYPASS_AB_EVIDENCE", runner)
        self.assertIn("def parse_read_coalesce_cap_ab", runner)
        self.assertIn("PASS_READ_COALESCE_CAP_EVIDENCE", runner)
        self.assertNotIn("START_K1_READ_BYPASS_AB=", loaded)
        self.assertNotIn("--k1-allow-after-read-bypass", loaded)
        self.assertIn("--async-prepare", loaded)
        self.assertNotIn("START_READ_COALESCE_CAP_AB=", loaded)
        self.assertNotIn("START_DELTA64_RESCUE=", loaded)
        self.assertNotIn("PASS_DELTA64_RESCUE=", loaded)
        self.assertNotIn("--delta64-lz4-acceleration", loaded)
        self.assertNotIn("--delta64-prepare-workers", loaded)
        compressor = body("swapz_compress_page")
        producer = body("swapz_preparation_worker")
        ordered = body("swapz_accept_write")
        self.assertIn("swapz_compress_prepared_page(", producer)
        self.assertIn("swapz_compress_page(", body("swapz_compress_prepared_page"))
        self.assertIn("swapz_compress_page(", ordered)
        self.assertIn("swapz_predict_delta64_sample_score(input)", compressor)
        self.assertIn("candidate <= (int)SWAPZ_PREDICTOR_RESCUE_MIN_LENGTH",
                      compressor)
        self.assertIn("stats->direct_adopted++", compressor)
        self.assertIn("stats->first_lz4_skipped++", compressor)
        self.assertNotIn("START_WRITE_PIPELINE_DEPTH=", loaded)
        self.assertNotIn("PASS_WRITE_PIPELINE_DEPTH=", loaded)
        self.assertNotIn("--write-pipeline-depth", loaded)
        self.assertIn("def parse_write_pipeline_depth", runner)
        self.assertIn("PASS_WRITE_PIPELINE_DEPTH_EVIDENCE", runner)
        self.assertNotIn("read_coalesce_cap_sequence=", loaded)
        self.assertIn("CONFIRMATION_SEQUENCE = (0, 1, 1, 0, 0, 1, 1, 0, 0, 1)",
                      runner)
        self.assertNotIn("DIRECTIONAL_SEQUENCE =", runner)
        self.assertIn("def paired_ci95", runner)
        self.assertIn('"parallel_read_pairs",', runner)
        self.assertIn('p["kernel_read_path"][field]', runner)
        self.assertIn("parallel_read_coalesced_reqs_saved", runner)
        self.assertIn("parallel_read_coalesce_extra_blocks", runner)
        self.assertIn('"seq MB/s"', runner)
        self.assertIn('"rnd MB/s"', runner)
        self.assertNotIn('not row["read_coalesce"] and kernel["parallel_read_pairs"]',
                         runner)

        concurrent = body("swapz_try_concurrent_read_slots")
        submit_read = body("swapz_submit_read_slot_range")
        done_read = body("swapz_async_lower_read_done")
        finish_read = body("swapz_finish_read_slot_range")
        self.assertIn("missing_slots < 2U", concurrent)
        self.assertNotIn("parallel_reads_enabled", concurrent)
        self.assertNotIn("!ctx->read_coalescing_enabled", concurrent)
        self.assertIn("ctx->retain_ms &&", concurrent)
        self.assertIn("swapz_plain_retained_write(bio)", concurrent)
        self.assertIn("ctx->batch_count && ctx->retain_ms", concurrent)
        self.assertNotIn(
            "(ctx->batch_count || skipped_write_count) && ctx->retain_ms",
            concurrent)
        self.assertNotIn("swapz_lower_read_overlap_begin(ctx)", concurrent)
        self.assertNotIn("swapz_lower_read_overlap_end(ctx)", concurrent)
        self.assertIn("skipped_writes[SWAPZ_MAX_RECORDS]", concurrent)
        self.assertIn("skipped_write_count", concurrent)
        self.assertIn("write_conflict", concurrent)
        self.assertIn("skipped_writes[write_index] == logical", concurrent)
        self.assertIn("entry = list_first_entry(local, struct swapz_bio_ref, list)",
                      concurrent)
        self.assertIn("if (bio_op(entry->bio) != REQ_OP_READ)", concurrent)
        self.assertNotIn(
            "else if (ctx->retain_ms && ctx->worker_has_immediate_followup)",
            concurrent)
        self.assertIn(".fn = swapz_async_lower_read_done", submit_read)
        self.assertIn(".context = slot", submit_read)
        self.assertIn("complete(&slot->lower_done)", done_read)
        self.assertNotIn("swapz_complete(", done_read)
        self.assertNotIn("swapz_engine_absorb_read_slot", done_read)
        self.assertIn("wait_for_completion(&slot->lower_done)", finish_read)
        self.assertIn("swapz_engine_seed_read_range", finish_read)
        self.assertLess(concurrent.index("swapz_submit_read_slot_range("),
                        concurrent.index("swapz_finish_read_slot_range("))
        self.assertLess(concurrent.index("swapz_complete(slot->bios[index], 0)"),
                        concurrent.index("swapz_engine_absorb_read_slot"))
        self.assertIn("slot->bios[index] = NULL", concurrent)

    def test_id67_delta64_is_single_candidate_with_arch_dispatch(self):
        predictor = (ROOT / "src/kernel/predictor.h").read_text()
        internal = (ROOT / "src/kernel/predictor-internal.h").read_text()
        dispatch = (ROOT / "src/kernel/predictor.c").read_text()
        route = (ROOT / "src/kernel/predictor-route.h").read_text()
        sse2 = (ROOT / "src/kernel/predictor-sse2.c").read_text()
        avx2 = (ROOT / "src/kernel/predictor-avx2.c").read_text()
        avx512 = (ROOT / "src/kernel/predictor-avx512.c").read_text()
        neon = (ROOT / "src/kernel/predictor-neon.c").read_text()
        qualification = (
            ROOT / "tests/runtime/native/codec/predictor-qualification.c").read_text()
        suites = (ROOT / "tests/suites/Makefile").read_text()
        kbuild = (ROOT / "src/kernel/Makefile").read_text()
        runner = (ROOT / "tests/tools/run-tests.py").read_text()
        workflow = (ROOT / ".github/workflows/product-codec.yml").read_text()
        authority = (ROOT / "src/kernel/authority.c").read_text()
        codec = (ROOT / "src/kernel/codec.c").read_text()
        engine = (ROOT / "src/kernel/engine.c").read_text()

        for retired in ("swapz_predict_cl_delta32x2",
                        "swapz_predict_cl_bytedelta8",
                        "swapz_predict_delta32",
                        "swapz_predict_delta64_512",
                        "swapz_predict_xor64"):
            self.assertNotIn(retired, predictor)
            self.assertNotIn(retired, internal)
            self.assertNotIn(retired, qualification)

        self.assertIn("swapz_predict_delta64_sample_score", predictor)
        self.assertIn("swapz_predict_delta64", predictor)
        self.assertIn("swapz_unpredict_delta64", predictor)
        self.assertIn("swapz_predict_delta64_scalar", internal)
        self.assertIn("swapz_predict_delta64_sample_score_scalar", internal)
        self.assertIn("SWAPZ_PREDICTOR_STAGE1_PAIRS 8U", predictor)
        self.assertIn("SWAPZ_PREDICTOR_SAMPLE_PAIRS 32U", predictor)
        self.assertIn("SWAPZ_PREDICTOR_SAMPLE_PHASE_BYTES 16U", predictor)
        self.assertIn("SWAPZ_PREDICTOR_SAMPLE_PHASE_STEP 2U", predictor)
        self.assertIn("SWAPZ_PREDICTOR_SUBPAGE_LANES", predictor)
        self.assertIn("SWAPZ_PREDICTOR_SAMPLE_PHASES", predictor)
        self.assertIn("for (step = 1U; step < SWAPZ_PREDICTOR_SUBPAGE_LANES;",
                      dispatch)
        self.assertNotIn("if (lane == subpage % SWAPZ_PREDICTOR_SUBPAGE_LANES)",
                         dispatch)

        self.assertIn("DEFINE_STATIC_CALL", dispatch)
        self.assertIn("static_call_update", dispatch)
        self.assertIn("kernel_fpu_begin()", dispatch)
        self.assertNotIn("swapz_predictor_score_call", dispatch)
        self.assertIn("return swapz_predict_delta64_sample_score_scalar(input);",
                      dispatch)
        self.assertIn("kernel_fpu_end()", dispatch)
        self.assertIn("SWAPZ_X86_INVERSE_WRAPPER(avx512)", dispatch)
        self.assertIn(
            "static_call_update(swapz_predictor_inverse_call, swapz_unpredict_avx512)",
            dispatch)
        self.assertIn(
            "swapz_unpredict_impl = swapz_unpredict_delta64_avx512",
            dispatch)
        self.assertIn("X86_FEATURE_AVX512F", dispatch)
        self.assertIn("XFEATURE_MASK_AVX512", dispatch)
        self.assertIn("X86_FEATURE_AVX2", dispatch)
        self.assertIn("XFEATURE_MASK_YMM", dispatch)
        self.assertIn("X86_FEATURE_XMM2", dispatch)
        self.assertIn("kernel_fpu_available()", dispatch)
        self.assertIn('"avx512"', dispatch)
        self.assertIn('"avx2"', dispatch)
        self.assertIn('"sse2"', dispatch)
        self.assertIn('"neon"', dispatch)
        self.assertIn("__builtin_cpu_supports(\"avx512f\")", dispatch)
        self.assertIn("__builtin_cpu_supports(\"avx2\")", dispatch)

        self.assertIn("__attribute__((vector_size(16)))", sse2)
        self.assertIn("2U * SWAPZ_PREDICTOR_U64_BYTES", sse2)
        self.assertIn("__attribute__((vector_size(32)))", avx2)
        self.assertIn("__attribute__((vector_size(64)))", avx512)
        self.assertIn("valignq", avx512)
        self.assertIn("vpslldq", avx2)
        self.assertIn("vpermq", avx2)
        for source, function in (
                (sse2, "swapz_unpredict_delta64_sse2"),
                (avx2, "swapz_unpredict_delta64_avx2"),
                (avx512, "swapz_unpredict_delta64_avx512")):
            inverse = source_body(function, source)
            self.assertIn("swapz_u32 offset = 0;", inverse)
            self.assertIn("step_pair = step0 + step1;", inverse)
            self.assertNotIn("base += step0;", inverse)
            self.assertNotIn("base += step1;", inverse)
        avx512_inverse = source_body("swapz_unpredict_delta64_avx512", avx512)
        self.assertIn("shifted0", avx512_inverse)
        self.assertIn("shifted1", avx512_inverse)
        self.assertNotIn("__asm__ volatile", avx512_inverse)
        self.assertIn("Advanced SIMD/NEON", neon)
        self.assertIn("__attribute__((vector_size(16)))", neon)
        for retired_score in (
                "swapz_predict_delta64_sample_score_sse2",
                "swapz_predict_delta64_sample_score_avx2",
                "swapz_predict_delta64_sample_score_avx512",
                "swapz_predict_delta64_sample_score_neon"):
            self.assertNotIn(retired_score, internal)
            self.assertNotIn(retired_score, sse2 + avx2 + avx512 + neon)

        self.assertIn("predictor.o", kbuild)
        self.assertIn("predictor-sse2.o predictor-avx2.o predictor-avx512.o",
                      kbuild)
        self.assertIn("CFLAGS_predictor-avx2.o += $(CC_FLAGS_FPU) -mavx2",
                      kbuild)
        self.assertIn("CFLAGS_REMOVE_predictor-avx2.o", kbuild)
        self.assertIn("CFLAGS_predictor-avx512.o += $(CC_FLAGS_FPU) -mavx512f",
                      kbuild)
        self.assertIn("CFLAGS_REMOVE_predictor-avx512.o", kbuild)
        self.assertIn("predictor-neon.o", kbuild)
        self.assertIn("CFLAGS_REMOVE_predictor-neon.o += $(CC_FLAGS_NO_FPU)",
                      kbuild)

        self.assertIn("PREDICTOR_TRANSFORM_NAMES = (\"delta64\",)", runner)
        self.assertIn("PREDICTOR_BACKENDS", runner)
        self.assertIn("swapz_predictor_init()", qualification)
        self.assertIn("swapz_predictor_transform_backend_name()", qualification)
        self.assertIn("swapz_predictor_inverse_backend_name()", qualification)
        compressor = body("swapz_compress_page")
        self.assertIn("swapz_predict_delta64_sample_score", compressor)
        self.assertIn("swapz_delta64_route_init", compressor)
        self.assertIn("swapz_delta64_candidate_smaller", compressor)
        self.assertIn("swapz_delta64_candidate_adoptable", compressor)
        self.assertIn("swapz_engine_next_uniform_pack_limit", route)
        self.assertIn("SWAPZ_PREDICTOR_PRODUCTION_THRESHOLD", route)
        self.assertIn("SWAPZ_PREDICTOR_PACK_THRESHOLD", route)
        self.assertIn("SWAPZ_PREDICTOR_RESCUE_MIN_LENGTH", route)
        self.assertIn("baseline_length <= 0", route)
        self.assertIn("candidate_length <= (int)route->pack_limit", route)
        self.assertIn("swapz_predict_delta64", compressor)
        self.assertIn("LZ4_compress_fast", compressor)
        self.assertIn("swapz_unpredict_delta64", DM)
        predictor_header = (ROOT / "src/kernel/predictor.h").read_text()
        codec_header = (ROOT / "src/kernel/codec.h").read_text()
        authority_header = (ROOT / "src/kernel/authority.h").read_text()
        self.assertIn("SWAPZ_PREDICTOR_PRODUCTION_THRESHOLD 24U",
                      predictor_header)
        self.assertIn("SWAPZ_PREDICTOR_PACK_THRESHOLD 16U",
                      predictor_header)
        self.assertIn("SWAPZ_RECORD_DELTA64_FLAG 0x8000U", codec_header)
        self.assertIn("SWAPZ_ENCODING_DELTA64 1U", codec_header)
        self.assertNotIn("SWAPZ_VERSION", codec_header)
        self.assertIn("swapz_map_pack_record_index", authority_header)
        self.assertIn("swapz_map_encoding", authority_header)
        self.assertIn("swapz_predict_delta64_scalar(page, scalar_transform_page)",
                      qualification)
        self.assertIn("swapz_predict_delta64_sample_score_scalar(page)",
                      qualification)
        self.assertIn("evaluate_sampling_controls", qualification)
        self.assertIn("repeated_512b_headers", qualification)
        self.assertIn("lane1_only_signal", qualification)
        self.assertIn("evaluate_route_controls", qualification)
        self.assertIn("production_route", qualification)
        self.assertIn('#include "predictor-route.h"', DM)
        self.assertIn("routed_blocks_saved", qualification)
        self.assertIn("benchmark_classifier", qualification)
        self.assertIn("scalar_ns_per_page", qualification)
        self.assertIn("scalar_transform_ns_per_page", qualification)
        self.assertIn("scalar_inverse_ns_per_page", qualification)
        self.assertIn("backend_benchmarks", qualification)
        self.assertIn("routed_cpu_ns_per_page", qualification)
        self.assertIn("ns_per_saved_block", qualification)
        self.assertIn("TRANSFORM_BENCH_REPEATS 64U", qualification)
        self.assertIn("-msse2 -c $(KERNEL)/predictor-sse2.c", suites)
        self.assertIn("-mavx2 -c $(KERNEL)/predictor-avx2.c", suites)
        self.assertIn("-mavx512f -c $(KERNEL)/predictor-avx512.c", suites)
        rootless = (ROOT / "tests/tools/test-rootless.sh").read_text()
        self.assertIn("predictor-sse2.disasm", rootless)
        self.assertIn("predictor-avx2.disasm", rootless)
        self.assertIn("predictor-avx512.disasm", rootless)
        self.assertNotIn("objdump -d build/tests/native/predictor-sse2.o |",
                         rootless)
        self.assertIn("liblz4-dev", workflow)
        self.assertIn("ubuntu-24.04-arm", workflow)
        self.assertIn("arch: arm64", workflow)
        self.assertIn("runs-on: ${{ matrix.runner }}", workflow)

        self.assertIn('#include "predictor.h"', DM)
        init_start = DM.index("static int __init swapz_dm_init")
        init_end = DM.index("static void __exit swapz_dm_exit", init_start)
        init = DM[init_start:init_end]
        self.assertIn("swapz_predictor_init()", init)
        # Rescue writes DELTA64_SHUF8 only; plain DELTA64 stays decodable.
        self.assertIn("swapz_predict_delta64_shuf8(input, candidate_output,", DM)
        self.assertNotIn("swapz_predict_delta64(input", DM)
        self.assertEqual(DM.count("*encoding = SWAPZ_ENCODING_DELTA64_SHUF8;"), 2)
        self.assertNotIn("*encoding = SWAPZ_ENCODING_DELTA64;", DM)
        self.assertEqual(DM.count("swapz_unpredict_delta64_shuf8("), 2)
        self.assertEqual(DM.count("ctx->read_compressed,\n\t\t\t\t\t\t\t      ctx->read_page"), 1)
        self.assertIn("SWAPZ_RECORD_SHUF8_FLAG 0x4000U", (ROOT / "src/kernel/codec.h").read_text())
        self.assertIn("SWAPZ_RECORD_LENGTH_MASK 0x3fffU", (ROOT / "src/kernel/codec.h").read_text())
        self.assertIn("return SWAPZ_ENCODING_INVALID;", codec)
        self.assertIn("!swapz_encoding_valid(out->encoding)", codec)
        self.assertIn("SWAPZ_MAP_SHUF8_FLAG 0x40U", authority_header := (ROOT / "src/kernel/authority.h").read_text())
        shuffle_header = (ROOT / "src/kernel/predictor-shuffle.h").read_text()
        self.assertNotIn("__asm__", shuffle_header)
        for isa in ("sse2", "avx2", "avx512", "neon"):
            unit = (ROOT / f"src/kernel/predictor-{isa}.c").read_text()
            self.assertIn('#include "predictor-shuffle.h"', unit)
            self.assertIn(f"void swapz_shuffle8_{isa}(", unit)
        predictor_src = (ROOT / "src/kernel/predictor.c").read_text()
        for tier in ("avx512", "avx2", "sse2", "neon_guarded"):
            self.assertIn(f"swapz_predict_shuf8_{tier})", predictor_src.replace("\n\t\t\t\t   ", ""))
        self.assertNotIn('#include "predictor.h"', authority)
        self.assertNotIn('#include "predictor.h"', codec)
        self.assertNotIn('#include "predictor.h"', engine)
        self.assertNotIn("payload_filter", codec)
        self.assertNotIn("policy_length", DM)

    def test_id64_is_retired_after_completion_aware_zero_tail_sampling(self):
        policy = (ROOT / "src/kernel/window-policy.h").read_text()
        pair = (ROOT / "tests/tools/benchmark-owned-pair.sh").read_text()
        loaded = (ROOT / "tests/tools/test-loaded.sh").read_text()
        worker = body("swapz_worker_pass")
        flush = body("swapz_flush_window")
        status = body("swapz_status")
        self.assertNotIn("module_param_named(guard_inflight_zero_shrink", DM)
        self.assertNotIn("swapz_window_guard_burst_target_shrink", policy)
        self.assertNotIn("ctx->burst_shrink_inflight_zero_skips++", worker)
        self.assertNotIn("ctx->last_pack_tail_zero_inflight", DM)
        self.assertNotIn("ctx->burst_shrink_after_inflight_zero++", worker)
        self.assertIn("if (swapz_has_inflight(ctx))",
                      body("swapz_sample_pack_tail_locked"))
        self.assertIn("guard_inflight_zero_shrink=%u", status)
        self.assertIn("burst_shrink_inflight_zero_skips=%llu", status)
        self.assertIn("burst_shrink_after_inflight_zero=%llu", status)
        self.assertNotIn("--guard-inflight-zero-shrink", pair)
        self.assertNotIn("START_BURST_GUARD_AB=", loaded)
        detach_start = flush.index("async_detach_ready =")
        detach_end = flush.index("/*", detach_start)
        detach = flush[detach_start:detach_end]
        self.assertIn(
            "(count > SWAPZ_WINDOW_DRY_PACK_MIN_RECORDS ||", detach)
        self.assertIn("READ_ONCE(ctx->preparation_queued) > 0U", detach)
        self.assertIn("close_reason == SWAPZ_CLOSE_PACK_READY", detach)
        self.assertIn("close_reason == SWAPZ_CLOSE_IDLE", detach)
        self.assertIn("close_reason == SWAPZ_CLOSE_DEADLINE", detach)
        self.assertNotIn("count > 1U && !needs_fua", detach)

    def test_alpha17_uniform_compressed_windows_skip_greedy_reordering(self):
        policy = (ROOT / "src/kernel/window-policy.h").read_text()
        reorder = body("swapz_order_window")
        greedy = body("swapz_order_window_greedy")
        flush = body("swapz_flush_window")
        self.assertIn("swapz_window_uniform_compressed(", policy)
        self.assertIn("!pending || !count || count > SWAPZ_MAX_RECORDS", policy)
        self.assertIn("pending[0].raw || !pending[0].length", policy)
        self.assertIn("pending[index].raw || pending[index].length != length",
                      policy)
        self.assertIn("swapz_window_uniform_compressed(ctx->batch", reorder)
        self.assertIn("ctx->planned_to_batch[position] = position", reorder)
        self.assertIn("swapz_order_window_greedy(ctx)", reorder)
        self.assertLess(reorder.index("swapz_order_window_greedy(ctx)"),
                        reorder.index("ctx->planned[position] ="))
        self.assertIn("ctx->used[largest] = 1", greedy)
        self.assertIn("ctx->planned_to_batch[position++] = (u8)largest",
                      greedy)
        self.assertIn("if (index != position)", reorder)
        self.assertIn("swapz_order_window(ctx)", flush)
        self.assertIn("swapz_engine_write_window_batched_read_cap", flush)

    def test_retention_timer_keeps_ordinary_pinned_deadline(self):
        policy = (ROOT / "src/kernel/window-policy.h").read_text()
        worker = body("swapz_worker_pass")
        status = body("swapz_status")
        self.assertIn("swapz_retention_timer_needs_arm(", policy)
        self.assertIn("swapz_window_timer_enabled(retain_ms) && !queued", policy)
        self.assertNotIn("swapz_retention_timer_needs_rearm(", policy)
        # A queued timer may move earlier (idle bound), never later.
        self.assertIn("ktime_to_ns(hrtimer_get_expires(", worker)
        self.assertIn("swapz_retention_deadline_ns(ctx)) {", worker)
        self.assertIn("Earlier only: never extend a queued deadline.", worker)
        self.assertIn("hrtimer_is_queued(&ctx->retention_timer)", worker)
        self.assertNotIn("swapz_effective_wait_deadline_ns", DM)
        self.assertIn("ns_to_ktime(swapz_retention_deadline_ns(ctx))", worker)
        self.assertLess(worker.index("hrtimer_is_queued(&ctx->retention_timer)"),
                        worker.index("hrtimer_start(&ctx->retention_timer"))
        self.assertIn("ctx->retain_timer_arms++", worker)
        self.assertIn("ctx->retain_timer_arm_skips++", worker)
        self.assertIn("HRTIMER_MODE_ABS", worker)
        self.assertIn("retain_timer_arm_skips=%llu", status)
        self.assertIn("ctx->retain_timer_arm_skips", status)
        self.assertIn("hrtimer_cancel(&ctx->retention_timer)", body("swapz_drain"))
        self.assertIn("hrtimer_cancel(&ctx->retention_timer)", body("swapz_free"))

    def test_alpha15_nonretained_hot_path_skips_unarmed_timer_cancel(self):
        window = (ROOT / "src/kernel/window-policy.h").read_text()
        flush = body("swapz_flush_window")
        worker = body("swapz_worker_pass")
        drain = body("swapz_drain")
        free = body("swapz_free")
        self.assertIn("static inline int swapz_window_timer_enabled", window)
        self.assertIn("return retain_ms != 0;", window)
        self.assertIn("if (swapz_window_timer_enabled(ctx->retain_ms))", flush)
        self.assertIn("hrtimer_cancel(&ctx->retention_timer);", flush)
        self.assertLess(
            flush.index("if (swapz_window_timer_enabled(ctx->retain_ms))"),
            flush.index("hrtimer_cancel(&ctx->retention_timer);"))
        self.assertIn("swapz_window_timer_enabled(ctx->retain_ms)", worker)
        self.assertIn("hrtimer_start(&ctx->retention_timer", worker)
        # Drain and free always cancel, even if admission was disabled.
        self.assertIn("hrtimer_cancel(&ctx->retention_timer);", drain)
        self.assertIn("hrtimer_cancel(&ctx->retention_timer);", free)

    def test_alpha21_geometry_early_closure_only_after_valid_admission(self):
        policy = (ROOT / "src/kernel/window-policy.h").read_text()
        writer = body("swapz_accept_write")
        flush = body("swapz_flush_window")
        status = body("swapz_status")
        self.assertIn("swapz_window_pack_ready(", policy)
        self.assertIn("extent_bytes += pending[i].length", policy)
        self.assertIn("sizeof(struct swapz_header)", policy)
        self.assertIn("static inline int swapz_window_compressed_extent_fits(", policy)
        compressed = source_body("swapz_window_compressed_extent_fits", policy)
        self.assertIn("pending[count - 1U].raw", compressed)
        self.assertIn("if (pending[i].raw)", compressed)
        self.assertIn("if (++compressed > compressed_target)", compressed)
        self.assertIn("extent_bytes >", compressed)
        self.assertIn("return compressed == compressed_target", compressed)
        self.assertIn("compressed_target * sizeof(struct swapz_record)", compressed)
        self.assertIn("static inline int swapz_window_first_compressed_extent_fits(", policy)
        first = source_body("swapz_window_first_compressed_extent_fits", policy)
        self.assertIn("if (++compressed == compressed_target)", first)
        self.assertIn("static inline int swapz_window_single_pack_ready(", policy)
        self.assertIn("static inline int swapz_window_prior_single_pack_ready(", policy)
        self.assertIn("static inline int swapz_window_pack_ready(", policy)
        single = source_body("swapz_window_single_pack_ready", policy)
        pack = source_body("swapz_window_pack_ready", policy)
        self.assertIn("if (count == 4U)", single)
        self.assertLess(single.index("if (count == 4U)"),
                        single.index("swapz_window_compressed_extent_fits("))
        self.assertIn("read_budget, 2U, 1U", single)
        self.assertNotIn("read_budget, 2U, 2U", single)
        self.assertIn("read_budget, 3U, 2U", single)
        self.assertIn("swapz_window_first_compressed_extent_fits(", single)
        self.assertNotIn("for (prefix", single)
        self.assertNotIn("read_budget, 4U", single)
        prior = source_body("swapz_window_prior_single_pack_ready", policy)
        self.assertIn("count <= SWAPZ_WINDOW_DRY_PACK_MIN_RECORDS", prior)
        self.assertIn("pending, count, 2U, 1U", prior)
        self.assertNotIn("pending, count, 2U, 2U", prior)
        self.assertIn("pending, count, 3U, 2U", prior)
        self.assertIn("read_budget, 4U, 2U", pack)
        self.assertIn("read_budget, 6U, 4U", pack)
        self.assertIn("swapz_window_extent_fits(", policy)
        self.assertIn("!retain_ms || read_budget || !pending", policy)
        self.assertIn("extent_blocks * SWAPZ_BLOCK_BYTES", policy)
        record_geometry = body("swapz_record_pack_geometry")
        self.assertIn("swapz_window_single_pack_ready(", record_geometry)
        self.assertIn("swapz_window_prior_single_pack_ready(", record_geometry)
        self.assertIn("swapz_window_pack_ready(", record_geometry)
        self.assertEqual(DM.count("swapz_record_pack_geometry(ctx)"), 2)
        self.assertLess(writer.index("if (bio->bi_opf & REQ_FUA)",
                                     writer.index("ctx->batch_count++")),
                        writer.rindex("swapz_record_pack_geometry(ctx)"))
        worker = body("swapz_worker_pass")
        # Admission records finite pack geometry only. Every PACK_READY close
        # is owned by the serialized worker after accepted-tail refresh.
        self.assertNotIn("ctx->next_window_close = SWAPZ_CLOSE_PACK_READY", writer)
        self.assertIn("swapz_close_worker_pack(ctx)", worker)
        self.assertNotIn("worker_followup_bios", DM)
        refresh = body("swapz_refresh_accepted_followup")
        self.assertIn("spin_lock_irqsave(&ctx->queue_lock, flags)", refresh)
        self.assertIn("!list_empty(&ctx->incoming)", refresh)
        self.assertIn("ctx->worker_has_immediate_followup = true", refresh)
        self.assertIn("swapz_refresh_accepted_followup(ctx)", writer)
        self.assertLess(writer.index("ctx->batch_count++"),
                        writer.index("swapz_refresh_accepted_followup(ctx)"))
        self.assertLess(writer.index("swapz_refresh_accepted_followup(ctx)"),
                        writer.rindex("swapz_record_pack_geometry(ctx)"))
        local_successor = worker.index("entry->list.next != &local")
        initial_refresh = worker.index("swapz_refresh_accepted_followup(ctx)",
                                       local_successor)
        list_delete = worker.index("list_del_init(&entry->list)")
        self.assertLess(local_successor, initial_refresh)
        self.assertLess(initial_refresh, list_delete)
        post_process = worker.index("swapz_process(ctx, entry->bio)")
        tail_guard = worker.index(
            "if (remaining > 1U && list_empty(&local))", post_process)
        tail_splice = worker.index(
            "list_splice_tail_init(&ctx->incoming, &local)", tail_guard)
        self.assertLess(post_process, tail_guard)
        self.assertLess(tail_guard, tail_splice)
        self.assertNotIn("!ctx->worker_has_immediate_followup",
                         worker[post_process:tail_guard])
        self.assertIn("ctx->accepted_burst_pack_ready = true", record_geometry)
        self.assertIn("ctx->accepted_burst_extensions++", record_geometry)
        self.assertIn("ctx->single_pack_deferred = true", record_geometry)
        self.assertNotIn("swapz_window_admission_burst_close_ready(", policy)
        self.assertNotIn("swapz_retained_target_close_ready", DM)
        self.assertNotIn("swapz_retained_pack_close_ready(ctx)", writer)
        ready = body("swapz_worker_pack_close_ready")
        close = body("swapz_close_worker_pack_cause")
        close_wrapper = body("swapz_close_worker_pack")
        self.assertIn("swapz_close_worker_pack_cause(ctx, SWAPZ_PACK_CLOSE_NONE)",
                      close_wrapper)
        self.assertIn("swapz_retained_pack_close_ready(ctx)", ready)
        self.assertIn("!ctx->worker_has_immediate_followup", ready)
        self.assertIn("!swapz_retention_expired(ctx)", ready)
        self.assertIn("SWAPZ_PACK_CLOSE_SERVICE_DRY", close)
        self.assertIn("SWAPZ_PACK_CLOSE_TAIL_TARGET", close)
        self.assertIn("SWAPZ_PACK_CLOSE_BURST_TARGET", close)
        self.assertIn("SWAPZ_BURST_CLOSE_WORKER", close)
        self.assertLess(worker.index("swapz_process(ctx, entry->bio)"),
                        worker.index("list_splice_tail_init(&ctx->incoming, &local)"))
        self.assertLess(worker.index("list_splice_tail_init(&ctx->incoming, &local)"),
                        worker.index("swapz_close_worker_pack(ctx)"))
        self.assertLess(worker.index("swapz_sample_pack_tail_locked(ctx, &local)"),
                        worker.index("list_splice_tail_init(&ctx->incoming, &local)"))
        post_finalize = worker.rindex("swapz_finalize_inflight_write(ctx, false)")
        post_sample = worker.index(
            "swapz_sample_pack_tail_locked(ctx, &local)", post_finalize)
        post_requeue = worker.index(
            "list_splice_init(&local, &ctx->incoming)", post_sample)
        post_ready = worker.index(
            "swapz_worker_pack_close_ready(ctx)", post_requeue)
        post_unlock = worker.index(
            "spin_unlock_irqrestore(&ctx->queue_lock, flags)", post_ready)
        post_close = worker.index("swapz_close_worker_pack(ctx)", post_unlock)
        timer_arm = worker.index("hrtimer_start(&ctx->retention_timer", post_close)
        self.assertLess(post_finalize, post_sample)
        self.assertLess(post_sample, post_requeue)
        self.assertLess(post_requeue, post_ready)
        self.assertLess(post_ready, post_unlock)
        self.assertLess(post_unlock, post_close)
        self.assertLess(post_close, timer_arm)
        self.assertLess(close.index("ctx->accepted_burst_tail_flushes++"),
                        close.index("swapz_flush_window(ctx)"))
        self.assertIn("ctx->accepted_burst_pack_ready = false", flush)
        self.assertIn("ctx->single_pack_deferred = false", flush)
        self.assertIn("ctx->single_pack_deferrals++", record_geometry)
        self.assertNotIn("ctx->packed_early_commits++", writer)
        self.assertIn("ctx->packed_early_commits++", close)
        self.assertIn("swapz_flush_window(ctx)", writer)
        self.assertIn("swapz_flush_window(ctx)", worker)
        self.assertIn("close_pack_ready=%llu", status)
        for field in ("pack_close_tail_target", "pack_close_tail_target_le4",
                      "pack_close_burst_target", "pack_close_service_dry",
                      "pack_close_burst_admission", "pack_close_burst_worker",
                      "pack_close_burst_target_le4", "pack_close_burst_target_5_8",
                      "pack_close_burst_target_9_16", "pack_close_burst_target_17_64",
                      "pack_close_burst_count_le4", "pack_close_burst_count_5_8",
                      "pack_close_burst_count_9_16", "pack_close_burst_count_17_64",
                      "pack_close_burst_overshoot",
                      "pack_tail_samples", "pack_tail_zero_inflight",
                      "pack_tail_zero_idle", "pack_tail_one_inflight",
                      "pack_tail_one_idle", "pack_tail_many_inflight",
                      "pack_tail_many_idle", "burst_target_grows",
                      "burst_target_shrinks",
                      "burst_shrink_after_read_bypass",
                      "burst_shrink_other",
                      "burst_shrink_target_le8",
                      "burst_shrink_target_9_32",
                      "burst_shrink_target_gt32",
                      "k1_ready_wait_windows", "k1_ready_wait_records",
                      "k1_ready_wait_wall_ns", "k1_ready_wait_max_records",
                      "k1_ready_wait_pack_ready", "k1_ready_wait_full",
                      "k1_ready_wait_deadline", "k1_ready_wait_fence",
                      "k1_ready_wait_other"):
            self.assertIn(field + "=%llu", status)
            self.assertIn("ctx->" + field, status)
        for retired in ("burst_shrink_inflight_zero_skips",
                        "burst_shrink_after_inflight_zero"):
            self.assertIn(retired + "=%llu", status)
            self.assertNotIn("ctx->" + retired, DM)
        self.assertNotIn("SWAPZ_PACK_CLOSE_TAIL_TARGET", writer)
        self.assertNotIn("SWAPZ_PACK_CLOSE_BURST_TARGET", writer)
        self.assertIn("SWAPZ_PACK_CLOSE_SERVICE_DRY", close)
        self.assertIn("pack_close_cause", flush)
        self.assertIn("ctx->pack_close_tail_target++", flush)
        self.assertIn("ctx->pack_close_tail_target_le4++", flush)
        self.assertIn("ctx->pack_close_burst_target++", flush)
        self.assertIn("ctx->pack_close_service_dry++", flush)
        self.assertIn("ctx->pack_close_burst_admission++", flush)
        self.assertIn("ctx->pack_close_burst_worker++", flush)
        self.assertIn("ctx->pack_close_burst_target_le4++", flush)
        self.assertIn("ctx->pack_close_burst_count_le4++", flush)
        self.assertIn("ctx->pack_close_burst_overshoot++", flush)
        sample = body("swapz_sample_pack_tail_locked")
        self.assertIn("swapz_has_inflight(ctx)", sample)
        self.assertNotIn("ctx->inflight_write", sample)
        # Sampling is completion-only: the direct K1 guard returns before
        # accounting, so the historical inflight sample buckets stay passive.
        self.assertLess(sample.index("if (swapz_has_inflight(ctx))"),
                        sample.index("ctx->pack_tail_samples++"))
        self.assertIn("ctx->pack_tail_samples++", sample)
        for field in ("pack_tail_zero_idle", "pack_tail_one_idle",
                      "pack_tail_many_idle", "burst_target_grows"):
            self.assertIn("ctx->" + field + "++", sample)
        for field in ("pack_tail_one_inflight", "pack_tail_many_inflight"):
            self.assertNotIn("ctx->" + field + "++", sample)
        self.assertNotIn("ctx->pack_tail_zero_inflight++", sample)
        self.assertNotIn("swapz_window_guard_burst_target_shrink(", worker)
        self.assertNotIn("ctx->burst_shrink_inflight_zero_skips++", worker)
        self.assertNotIn("ctx->last_pack_tail_zero_inflight", DM)
        self.assertNotIn("ctx->burst_shrink_after_inflight_zero++", worker)
        self.assertIn("ctx->burst_shrink_after_read_bypass++", worker)
        self.assertIn("ctx->burst_shrink_other++", worker)
        self.assertIn("ctx->burst_shrink_target_le8++", worker)
        self.assertIn("ctx->burst_shrink_target_9_32++", worker)
        self.assertIn("ctx->burst_shrink_target_gt32++", worker)
        self.assertNotIn("pack_tail_zero_deferred", DM)
        self.assertNotIn("pack_ready_busy_deferrals", DM)
        self.assertNotIn("hold_zero_after_finalize", DM)
        self.assertNotIn("swapz_inflight_write_busy", DM)
        self.assertIn("ctx->k1_ready_wait_windows++", flush)
        self.assertIn("head && !completion_done(&head->lower_done)", flush)
        self.assertIn("SWAPZ_WRITE_PIPELINE_DEPTH == 1U", flush)
        self.assertNotIn("ctx->write_pipeline_depth", DM)
        self.assertIn("ctx->pipeline_finalize_wait_wall_ns", flush)
        self.assertNotIn("SWAPZ_BURST_CLOSE_ADMISSION", writer)
        self.assertIn("SWAPZ_BURST_CLOSE_WORKER", close)
        self.assertNotIn("ctx->next_burst_close_target =", writer)
        self.assertIn("ctx->next_burst_close_target =", close)
        self.assertIn("packed_early_commits=%llu", status)
        self.assertIn("single_pack_deferrals=%llu accepted_burst_extensions=%llu", status)
        self.assertIn("accepted_burst_tail_flushes=%llu", status)
        self.assertIn("accepted_burst_read_caps=%llu", status)
        self.assertIn("bool accepted_burst_extended = ctx->accepted_burst_pack_ready", flush)
        self.assertIn("swapz_u8 planning_read_cap = ctx->engine.max_read_blocks_per_record", flush)
        self.assertIn("if (accepted_burst_extended && !planning_read_cap)", flush)
        self.assertIn("planning_read_cap = 2U", flush)
        self.assertIn("ctx->accepted_burst_read_caps++", flush)
        self.assertIn("swapz_engine_write_window_batched_read_cap(&ctx->engine", flush)
        self.assertIn("planning_read_cap);", flush)
        self.assertNotIn("swapz_engine_plan_stats(", flush)
        self.assertNotIn("cap3", flush)
        self.assertIn("ctx->window_close_reasons[close_reason]++", flush)

    def test_dead_segment_trim_is_post_deadness_and_advisory(self):
        authority = (ROOT / "src/kernel/authority.c").read_text()
        claim = source_body("swapz_claim_dead_segment", authority)
        gc = body("swapz_gc_compact_one_inner")
        discard = body("swapz_discard_dead_segment")
        status = body("swapz_status")
        self.assertIn("a->dead_segment_recycle", authority)
        map_validation = claim.index("swapz_verify_segment_authoritative_maps(")
        recycle = claim.index(
            "if (reclaim_required && a->dead_segment_recycle)")
        descriptor_clear = claim.index("memset(a->extent_classes + start")
        self.assertLess(map_validation, recycle)
        self.assertLess(recycle, descriptor_clear)
        self.assertIn("swapz_gc_commit_rotation(a, victim)", gc)
        self.assertLess(gc.index("swapz_gc_commit_rotation(a, victim)"),
                        gc.index("swapz_discard_dead_segment(ctx, victim)"))
        self.assertIn("a->active_start / SWAPZ_SEGMENT_BLOCKS == segment", discard)
        self.assertIn("a->batch_segment == segment", discard)
        self.assertIn("swapz_inflight_uses_segment(ctx, segment)", discard)
        self.assertIn("bdev_max_discard_sectors(ctx->backing->bdev)", discard)
        self.assertIn("blkdev_issue_discard(ctx->backing->bdev", discard)
        self.assertIn("error == -EOPNOTSUPP", discard)
        for field in ("segment_discards_eligible", "segment_discards_issued",
                      "segment_discards_completed", "segment_discards_unsupported",
                      "segment_discards_failed", "segment_discard_sectors",
                      "segment_discard_wall_ns"):
            self.assertIn(field + "=%llu", status)

    def test_timed_window_telemetry_uses_measurement_snapshots(self):
        replay = (ROOT / "tests/runtime/benchmark/io-replay.py").read_text()
        runner = (ROOT / "tests/tools/run-tests.py").read_text()
        self.assertIn("WINDOW_INTERVAL_FIELDS", replay)
        self.assertIn("KERNEL_WRITE_COUNTER_FIELDS", replay)
        self.assertIn(
            'KERNEL_WRITE_GAUGE_FIELDS = (',
            replay)
        self.assertIn("counters[key] = after[key]", replay)
        self.assertIn('before["delta64_rescue"] != after["delta64_rescue"]', replay)
        self.assertIn('after["delta64_rescue"] not in (0, 1)', replay)
        self.assertIn('if not after["delta64_rescue"] and any(', replay)
        self.assertIn("TIMED_WINDOW_COUNTER_FIELDS", runner)
        self.assertIn("def timed_window_error", runner)
        self.assertIn("PACK_CLOSE_PRIMARY_FIELDS", runner)
        self.assertIn("BURST_CLOSE_DETAIL_FIELDS", runner)
        self.assertIn("TAIL_SAMPLE_FIELDS", runner)
        self.assertIn("burst_shrink_inflight_zero_skips", runner)
        self.assertIn("burst_shrink_after_inflight_zero", runner)
        self.assertIn("parallel_read_coalesce_skip_noncontig_slot", runner)
        self.assertIn("K1_READY_WAIT_FIELDS", runner)
        self.assertIn("burst_close_detail_delta_paired_95pct_ci", runner)
        self.assertIn("Mixed burst-close split", runner)
        self.assertIn("Mixed post-PACK tail samples", runner)
        self.assertIn("K=1 ready wait win/records/ms", runner)
        self.assertIn("pack_close_burst_admission", replay)
        self.assertIn("pack_tail_zero_inflight", replay)
        self.assertIn("k1_ready_wait_windows", replay)
        self.assertIn("pipeline_finalize_wait_wall_ns", replay)
        self.assertIn("accepted_work_lower_idle_events", replay)
        self.assertIn("accepted_work_lower_idle_ns", replay)
        self.assertIn("accepted_work_lower_idle_undersized_batch_ns", replay)
        self.assertIn("accepted_work_lower_idle_worker_unscheduled_ns", replay)
        self.assertIn("accepted_work_lower_idle_preparing_head_ns", replay)
        self.assertIn("accepted_work_lower_idle_no_ready_work_ns", replay)
        self.assertIn("accepted_work_lower_idle_post_lower_ns", replay)
        self.assertIn("inconsistent accepted lower-idle attribution", replay)
        self.assertIn("inconsistent accepted lower-idle attribution", runner)
        for field in ("write_admit_worker_samples",
                      "write_admit_worker_wall_ns", "sync4_windows",
                      "sync4_wall_ns", "sync4_lower_write_ns",
                      "sync4_nonio_ns", "sync4_reissue_samples",
                      "sync4_reissue_gap_ns"):
            self.assertIn(field, replay)
            self.assertIn(field, runner)
        self.assertIn("inconsistent synchronous four-record attribution", replay)
        self.assertIn("pack_close_burst_target_5_8", replay)
        self.assertIn("single_tail_comp_age_1001_1250us", runner)
        self.assertIn("ordered_worker_cpu_ns", runner)
        self.assertIn("read_worker_cpu_ns", runner)
        self.assertIn('"kernel_write_path": obj.get("kernel_write_path")',
                      runner)
        self.assertIn(
            "Full-process status includes prefill/warmup/post-mixed work",
            runner)
        self.assertIn(
            "Never use full-process window counters for the QD pilot", runner)
        fast = (ROOT / "tests/tools/fast-test.py").read_text()
        self.assertIn('"sata-mixed", "nvme4-mixed", "nvme5-mixed"', fast)
        self.assertIn('"fast-mixed", "fast-w4", "fast-w8"', fast)
        self.assertIn('os.environ.get("REPEAT", "3")', fast)
        self.assertIn("K=1 critical-path profile", fast)
        dm = (ROOT / "src/kernel/dm-target.c").read_text()
        self.assertIn("entry->admitted_ns = ktime_get_ns()", dm)
        self.assertIn("ctx->write_admit_worker_samples++", dm)
        self.assertIn("ctx->sync4_windows++", dm)
        self.assertIn("sync4_reissue_gap_ns", dm)

    def test_id114_measurement_epoch_breaks_warmup_sync4_link_only(self):
        import subprocess
        import tempfile

        replay = (ROOT / "tests/runtime/benchmark/io-replay.py").read_text()
        dm = (ROOT / "src/kernel/dm-target.c").read_text()
        message = body("swapz_message")
        self.assertIn('strcmp(argv[0], "profile_epoch")', message)
        self.assertIn("unsigned int sz = 0;", message)
        self.assertIn("WRITE_ONCE(ctx->sync4_last_done_ns, 0)", message)
        self.assertNotIn("sync4_windows =", message)
        self.assertIn(".message = swapz_message", dm)
        self.assertIn("def kernel_write_profile_epoch", replay)
        self.assertGreaterEqual(
            replay.count("kernel_write_profile_epoch(path, identity)"), 3)
        self.assertIn('"dmsetup", "message", str(path), "0", "profile_epoch"', replay)
        self.assertIn("profile_epoch=1", replay)

        # Execute the production callback. DM only exports a message reply
        # when the callback returns 1; success-without-output (0) loses it.
        source = r'''
#include <assert.h>
#include <errno.h>
#include <stdio.h>
#include <string.h>
#include <stdbool.h>
typedef unsigned long long atomic64_t;
static void atomic64_inc(atomic64_t *value) { ++*value; }
struct swapz_dm {
    unsigned long long sync4_last_done_ns;
    unsigned long long sync4_windows;
    bool lane_prev_valid;
    atomic64_t lane_profile_epoch;
};
struct dm_target { void *private; };
#define WRITE_ONCE(value, new_value) ((value) = (new_value))
#define DMEMIT(...) (sz += snprintf(result + sz, maxlen - sz, __VA_ARGS__))
static int swapz_message(struct dm_target *ti, unsigned int argc, char **argv,
                         char *result, unsigned int maxlen)
{CALLBACK}
int main(void)
{
    struct swapz_dm ctx = {
        .sync4_last_done_ns = 123,
        .sync4_windows = 7,
        .lane_prev_valid = true,
        .lane_profile_epoch = 9,
    };
    struct dm_target ti = {&ctx};
    char *valid[] = {"profile_epoch"};
    char *invalid[] = {"unknown"};
    char result[64] = "unchanged";

    assert(swapz_message(&ti, 0, NULL, result, sizeof(result)) == -EINVAL);
    assert(swapz_message(&ti, 2, valid, result, sizeof(result)) == -EINVAL);
    assert(swapz_message(&ti, 1, invalid, result, sizeof(result)) == -EINVAL);
    assert(ctx.sync4_last_done_ns == 123 && ctx.sync4_windows == 7);
    assert(ctx.lane_prev_valid && ctx.lane_profile_epoch == 9);
    assert(!strcmp(result, "unchanged"));
    assert(swapz_message(&ti, 1, valid, result, sizeof(result)) == 1);
    assert(!strcmp(result, "profile_epoch=1"));
    assert(ctx.sync4_last_done_ns == 0 && ctx.sync4_windows == 7);
    assert(!ctx.lane_prev_valid && ctx.lane_profile_epoch == 10);
    return 0;
}
'''.replace("CALLBACK", message)
        with tempfile.TemporaryDirectory(prefix="swapz-message-") as temp:
            binary = Path(temp) / "message"
            compiled = subprocess.run(
                ["cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-x", "c",
                 "-", "-o", str(binary)], input=source, text=True,
                capture_output=True, timeout=30)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            executed = subprocess.run([str(binary)], cwd=temp,
                                      capture_output=True, text=True, timeout=5)
            self.assertEqual(executed.returncode, 0, executed.stderr)

    def test_alpha12_retention_has_absolute_timer_and_drain(self):
        deadline = body("swapz_first_record_deadline_ns")
        effective = body("swapz_retention_deadline_ns")
        expiry = body("swapz_retention_expired")
        wake = body("swapz_retention_wake")
        process = body("swapz_process")
        worker = body("swapz_worker_pass")
        flush = body("swapz_flush_window")
        mapping = body("swapz_map")
        drain = body("swapz_drain")
        ctr = body("swapz_ctr")
        status = body("swapz_status")
        self.assertIn("ctx->window_first_ns", deadline)
        self.assertIn("swapz_window_retention_deadline_ns", deadline)
        # The device-relative idle bound may only make the first-record
        # deadline earlier while no lower WRITE is in flight.
        self.assertIn("swapz_first_record_deadline_ns(ctx)", effective)
        self.assertIn("swapz_window_effective_deadline_ns(", effective)
        self.assertIn("swapz_window_idle_bound_ns(ctx->lower_write_service_ewma_ns",
                      effective)
        self.assertIn("swapz_has_inflight(ctx) ? 0 :", effective)
        self.assertIn("ctx->accepted_work_lower_idle_start_ns", effective)
        self.assertNotIn("swapz_window_single_tail_deadline_ns", deadline)
        self.assertNotIn("SWAPZ_SINGLE_TAIL_CUTOFF_NS", DM)
        self.assertNotIn("single_tail_deferred_start_ns", deadline)
        self.assertIn("swapz_window_deadline_expired", expiry)
        self.assertIn("swapz_retention_deadline_ns(ctx)", expiry)
        self.assertIn("ktime_get_ns()", expiry)
        self.assertNotIn("nsecs_to_jiffies64", DM)
        self.assertNotIn("swapz_retention_delay", DM)
        self.assertIn("hrtimer_start(&ctx->retention_timer", worker)
        self.assertIn("swapz_retention_timer_needs_arm(", worker)
        self.assertIn("ns_to_ktime(swapz_retention_deadline_ns(ctx))",
                      worker)
        self.assertIn("HRTIMER_MODE_ABS", worker)
        self.assertIn("spin_lock_irqsave(&ctx->queue_lock", wake)
        self.assertIn("if (ctx->accepting)", wake)
        self.assertIn("mod_delayed_work(ctx->workqueue, &ctx->worker, 0)", wake)
        self.assertIn("return HRTIMER_NORESTART", wake)
        for forbidden in ("swapz_flush_window(", "swapz_complete(", "swapz_lower(",
                          "ctx->batch", "ctx->authority", "ctx->window_first_ns"):
            self.assertNotIn(forbidden, wake)
        self.assertIn("SWAPZ_CLOSE_DEADLINE", process)
        before_deadline = process.index("ctx->deadline_before_bio++")
        before_gate = process.rfind("!ctx->worker_has_immediate_followup",
                                    0, before_deadline)
        self.assertGreaterEqual(before_gate, 0)
        after_deadline = process.index("ctx->deadline_after_read++")
        after_gate = process.rfind("!ctx->worker_has_immediate_followup",
                                   before_deadline, after_deadline)
        self.assertGreater(after_gate, before_deadline)
        self.assertIn("ctx->deadline_worker_with_local++", worker)
        self.assertIn("ctx->deadline_worker_empty++", worker)
        self.assertIn("!list_empty(&local)", worker)
        self.assertIn("#define SWAPZ_SINGLETON_DEADLINE_STREAK 2U", DM)
        self.assertIn("ctx->singleton_deadline_streak++", worker)
        self.assertIn("ctx->singleton_fast_close = true", worker)
        self.assertIn("ctx->singleton_fast_close = false", worker)
        self.assertIn("ctx->singleton_fast_close && ctx->batch_count == 1U",
                      worker)
        learned_close = worker.index(
            "ctx->singleton_fast_close && ctx->batch_count == 1U")
        timer_arm = worker.index("hrtimer_start(&ctx->retention_timer",
                                 learned_close)
        self.assertLess(learned_close, timer_arm)
        self.assertIn("ctx->next_window_close = SWAPZ_CLOSE_IDLE",
                      worker[learned_close:timer_arm])
        self.assertIn("ctx->singleton_deadline_streak = 0", flush)
        self.assertIn("ctx->singleton_fast_close = false", flush)
        self.assertIn("bool ordering_boundary =", flush)
        ordering_start = flush.index("bool ordering_boundary =")
        hard_start = flush.index("bool hard_boundary =")
        ordering_reset = flush.index("if (ordering_boundary)")
        empty_flush = flush.index("if (!count)")
        self.assertLess(ordering_start, hard_start)
        self.assertLess(ordering_reset, empty_flush)
        ordering_definition = flush[ordering_start:hard_start]
        for reason in ("SWAPZ_CLOSE_FUA", "SWAPZ_CLOSE_PREFLUSH",
                       "SWAPZ_CLOSE_DISCARD", "SWAPZ_CLOSE_SHUTDOWN",
                       "SWAPZ_CLOSE_OTHER"):
            self.assertIn(reason, ordering_definition)
        self.assertNotIn("SWAPZ_CLOSE_IDLE", ordering_definition)
        self.assertNotIn("SWAPZ_CLOSE_DEADLINE", ordering_definition)
        ordering_reset_block = flush[ordering_reset:empty_flush]
        self.assertIn("ctx->singleton_deadline_streak = 0",
                      ordering_reset_block)
        self.assertIn("ctx->singleton_fast_close = false",
                      ordering_reset_block)
        self.assertIn("swapz_flush_window(ctx)", process)
        self.assertIn("ctx->retain_worker_passes++", worker)
        self.assertIn("ctx->retain_timer_arms++", worker)
        self.assertIn("SWAPZ_CLOSE_SHUTDOWN", worker)
        self.assertIn("ctx->batch_count >= ctx->max_window", worker)
        self.assertIn("mod_delayed_work(ctx->workqueue, &ctx->worker, 0)", mapping)
        self.assertIn("WRITE_ONCE(ctx->accepting, false)", drain)
        self.assertLess(drain.index("WRITE_ONCE(ctx->accepting, false)"),
                        drain.index("hrtimer_cancel(&ctx->retention_timer)"))
        self.assertLess(drain.index("spin_unlock_irqrestore"),
                        drain.index("hrtimer_cancel(&ctx->retention_timer)"))
        self.assertLess(drain.index("hrtimer_cancel(&ctx->retention_timer)"),
                        drain.index("flush_delayed_work(&ctx->worker)"))
        freeing = body("swapz_free")
        self.assertLess(freeing.index("hrtimer_cancel(&ctx->retention_timer)"),
                        freeing.index("destroy_workqueue(ctx->workqueue)"))
        self.assertLess(ctr.index("hrtimer_setup(&ctx->retention_timer"),
                        ctr.index("error = dm_get_device("))
        self.assertIn("KERNEL_VERSION(6, 13, 0)", ctr)
        self.assertIn("hrtimer_init(&ctx->retention_timer", ctr)
        self.assertIn("flush_delayed_work(&ctx->worker)", drain)
        self.assertIn("drain_workqueue(ctx->workqueue)", drain)
        self.assertIn("argc > 11", ctr)
        self.assertIn("retain > SWAPZ_NULLBLK_TEST_MAX_RETAIN_MS", ctr)
        self.assertIn("!is_nullb && retain > SWAPZ_MAX_RETAIN_MS", ctr)
        self.assertIn("ctx->retain_ms = retain", ctr)
        for field in ("retain_ms=%u", "retain_passes=%llu",
                      "retain_timer_arms=%llu", "close_deadline=%llu",
                      "deadline_before_bio=%llu",
                      "deadline_after_read=%llu",
                      "deadline_worker_with_local=%llu",
                      "deadline_worker_empty=%llu"):
            self.assertIn(field, status)
        self.assertIn("SWAPZ_CLOSE_DEADLINE", DM)
        self.assertIn("if (bio->bi_opf & REQ_FUA)", body("swapz_accept_write"))

    def test_retained_writes_prepare_before_the_deadline(self):
        mapping = body("swapz_map")
        self.assertIn("!bio_sectors(bio) || ctx->retain_ms", mapping)
        self.assertLess(mapping.index("!bio_sectors(bio) || ctx->retain_ms"),
                        mapping.index("mod_delayed_work(ctx->workqueue, &ctx->worker, 0)"))
        self.assertIn("queue_delayed_work(ctx->workqueue, &ctx->worker, 0)", mapping)
        self.assertNotIn("msecs_to_jiffies", mapping)
        self.assertNotIn("window_first_ns", mapping)
        self.assertNotIn("hrtimer_start", mapping)

    def test_retained_reads_require_independence_and_abort_on_failure(self):
        self.assertNotIn("swapz_read_is_independentstatic bool", DM)
        independent = body("swapz_read_is_independent")
        process = body("swapz_process")
        flush = body("swapz_flush_window")
        for fence in ("!READ_ONCE(ctx->accepting)", "ctx->failed",
                      "ctx->authority.in_flight", "ctx->authority.batch_replaying",
                      "REQ_PREFLUSH | REQ_FUA"):
            self.assertIn(fence, independent)
        self.assertIn("ctx->authority.batch_pending && !inflight_active", independent)
        run_fence = body("swapz_inflight_run_touches_logical")
        self.assertIn(
            "ctx->authority.batch_pending != run->extent_count", run_fence)
        self.assertIn("struct swapz_inflight_write *inflight = &ctx->inflight_write",
                      run_fence)
        self.assertNotIn("slot_index", run_fence)
        self.assertIn("tx->records[record].logical_page == logical", run_fence)
        self.assertIn("swapz_inflight_run_touches_logical(ctx, logical)", independent)
        self.assertIn("swapz_window_read_independent(ctx->batch, ctx->batch_count",
                      independent)
        self.assertIn("logical, ctx->retain_ms, blocked", independent)
        # A dispatched K=1 run with no open window must not force a drain:
        # only an empty batch with an idle lane stays a dependency.
        self.assertIn("(!ctx->batch_count && !inflight_active)", independent)
        self.assertNotIn("!ctx->retain_ms || !ctx->batch_count ||", independent)
        self.assertLess(independent.index("if (!ctx->batch_count)\n\t\treturn !blocked;"),
                        independent.index("swapz_window_read_independent("))
        independent_read = process.index(
            "if (op == REQ_OP_READ && swapz_read_is_independent(ctx, bio))")
        bypass = process[independent_read:
                         process.index("if (op != REQ_OP_WRITE ||",
                                       independent_read)]
        self.assertIn("swapz_read_is_independent(ctx, bio)", bypass)
        self.assertIn("ctx->retained_wave_read_seen = true", bypass)
        self.assertLess(bypass.index("error = swapz_read(ctx, bio)"),
                        bypass.index("ctx->retained_wave_read_seen = true"))
        self.assertLess(bypass.index("error = swapz_read(ctx, bio)"),
                        bypass.index("swapz_fail(ctx, error)"))
        self.assertLess(bypass.index("swapz_fail(ctx, error)"),
                        bypass.index("swapz_flush_window(ctx)"))
        self.assertIn("u64 read_start_ns = ktime_get_ns()", bypass)
        self.assertIn("u64 lower_reqs_before = ctx->lower_read_submitted_reqs", bypass)
        self.assertIn("u64 read_end_ns = ktime_get_ns()", bypass)
        self.assertIn("bool had_lower_io =", bypass)
        self.assertIn("ctx->lower_read_submitted_reqs != lower_reqs_before", bypass)
        self.assertIn("if (had_lower_io && ctx->batch_count)", bypass)
        self.assertIn("swapz_note_single_tail_read_bypass(ctx)", bypass)
        self.assertIn("ctx->window_first_ns += read_elapsed", bypass)
        self.assertIn("ctx->window_first_ns = read_end_ns", bypass)
        had_lower_io = bypass.index("if (had_lower_io && ctx->batch_count)")
        wave_read_seen = bypass.index("ctx->retained_wave_read_seen = true")
        note_bypass = bypass.index("swapz_note_single_tail_read_bypass(ctx)")
        service_shift = bypass.index("ctx->window_first_ns += read_elapsed")
        completion = bypass.index("swapz_complete(bio, error)")
        self.assertLess(bypass.index("error = swapz_read(ctx, bio)"),
                        had_lower_io)
        self.assertLess(wave_read_seen, had_lower_io)
        self.assertLess(had_lower_io, note_bypass)
        self.assertIn("ctx->batch_count || ctx->retained_chain_completed", bypass)
        self.assertLess(note_bypass, service_shift)
        self.assertLess(service_shift, completion)
        # An empty batch has a zero (always expired) deadline; never turn a
        # dispatched-run READ into an empty flush that waits for the lane.
        self.assertIn("if (!error && ctx->batch_count &&\n\t\t    "
                      "!ctx->worker_has_immediate_followup &&", bypass)
        deadline_gate = bypass.index("!ctx->worker_has_immediate_followup",
                                     completion)
        deadline_expiry = bypass.index("swapz_retention_expired(ctx)",
                                       deadline_gate)
        self.assertLess(completion, deadline_gate)
        self.assertLess(deadline_gate, deadline_expiry)
        self.assertLess(flush.index("if (!count)"),
                        flush.index("ctx->single_pack_deferred = false"))
        batch_reset = flush.index("ctx->batch_count = 0;")
        wave_read_reset = flush.index(
            "ctx->retained_wave_read_seen = false;", batch_reset)
        self.assertLess(batch_reset, wave_read_reset)
        self.assertIn("error || committed != count || !chain_continues", flush)
        self.assertIn("ctx->retained_wave_interrupted", flush)
        reset_pos = flush.rindex("ctx->retained_window_read_bypasses = 0;")
        policy_pos = flush.rindex("if (!ctx->retain_ms")
        self.assertLess(reset_pos, policy_pos)
        evidence_reset = flush[policy_pos:flush.rindex("return 0;")]
        self.assertIn("packed_close && !ctx->worker_has_immediate_followup",
                      evidence_reset)
        self.assertIn("close_reason == SWAPZ_CLOSE_DUPLICATE", evidence_reset)
        self.assertIn("ctx->retained_wave_interrupted = false", evidence_reset)
        self.assertIn("swapz_refresh_accepted_followup(ctx)", process)
        normal_read = process[process.index("case REQ_OP_READ:"):
                              process.index("case REQ_OP_DISCARD:")]
        self.assertIn("swapz_refresh_accepted_followup(ctx)", normal_read)
        self.assertNotIn("ctx->retained_window_read_bypasses++", normal_read)
        self.assertNotIn("swapz_note_single_tail_read_bypass(ctx)", normal_read)
        abort = flush[flush.index("if (smp_load_acquire(&ctx->failed))"):
                      flush.index("swapz_order_window(ctx)")]
        self.assertIn("swapz_complete(ctx->batch[index].bio, error)", abort)
        self.assertIn("goto accounted;", abort)
        self.assertNotIn("planned_to_batch", abort)
        self.assertNotIn("swapz_engine_write", abort)
        self.assertLess(flush.index("accounted:"), flush.index("ctx->batch_count = 0"))
        self.assertIn("retained_read_bypasses=%llu", body("swapz_status"))

    def test_id61_foreground_gc_pressure_evidence_is_observational(self):
        choose = body("swapz_gc_choose_victim")
        compact_inner = body("swapz_gc_compact_one_inner")
        compact = body("swapz_gc_compact_one")
        status = body("swapz_status")
        deploy = (ROOT / "tests/tools/deploy-nullblk.sh").read_text()
        oracle = (ROOT / "tests/tools/device-roundtrip.c").read_text()
        runner = (ROOT / "tests/tools/run-tests.py").read_text()
        ctor = body("swapz_ctr")

        self.assertIn("ctx->gc_choose_calls++", choose)
        self.assertNotIn("ctx->gc_choose_map_entries++", choose)
        self.assertIn("ctx->segment_mapped_pages[segment]", choose)
        self.assertIn("ctx->gc_scores[segment]", choose)
        self.assertNotIn("balance_segment_opens", choose)
        self.assertNotIn("programs < best_programs", choose)
        self.assertIn("swapz_enable_segment_gc_accounting", ctor)
        self.assertIn("ctx->gc_choose_segment_entries++", choose)
        self.assertIn("ctx->gc_relocation_map_entries++", compact_inner)
        self.assertIn("a->segment_first_page[victim]", compact_inner)
        self.assertIn("next = a->page_next_in_segment[logical]", compact_inner)
        self.assertLess(
            compact_inner.index("next = a->page_next_in_segment[logical]"),
            compact_inner.index("swapz_gc_relocate_one(ctx, victim, logical)"))
        self.assertIn("visited_victim_pages >= expected_victim_pages", compact_inner)
        self.assertIn("visited_victim_pages != expected_victim_pages", compact_inner)
        self.assertIn("ctx->gc_choose_wall_ns +=", compact_inner)
        self.assertIn("ctx->gc_wall_ns +=", compact)
        self.assertIn("swapz_gc_compact_one_inner(ctx)", compact)
        for name in (
                "gc_choose_wall_ns", "gc_choose_calls",
                "gc_choose_map_entries", "gc_choose_segment_entries",
                "gc_relocation_map_entries"):
            self.assertIn(name + "=%llu", status)
            self.assertIn("ctx->" + name, status)

        self.assertIn("GC_PRESSURE_ROUND=", oracle)
        self.assertIn("CLOCK_MONOTONIC", oracle)
        self.assertIn("write_p99_ns", oracle)
        self.assertIn("PASS_LOADED_GC_PRESSURE=", deploy)
        self.assertIn("gc_fraction_ppm", deploy)
        self.assertIn("gc_choose_map_entries == 0", deploy)
        self.assertIn("gc_relocation_map_entries == gc_pages", deploy)
        self.assertIn('"gc_pressure": re.compile(', runner)
        self.assertIn('"gc_fraction_ppm": gc_fraction_ppm', runner)
        self.assertIn('"gc_no_headroom_skips": gc_no_headroom_skips', runner)

        # This phase measures the current foreground collector only. It does
        # not add a background worker or alter victim scoring/allocation.
        self.assertNotIn("gc_workqueue", DM)
        self.assertNotIn("queue_work(ctx->gc", DM)
        self.assertNotIn("kthread", compact_inner)

    def test_gc_status_is_truthful(self):
        self.assertIn("mode=alpha-live-gc", body("swapz_status"))
        self.assertNotIn("mode=alpha-no-gc", body("swapz_status"))
        self.assertIn("experimental live GC", DM)

    def test_single_lower_write_owner_keeps_publication_on_ordered_worker(self):
        submit = body("swapz_submit_inflight_write")
        done = body("swapz_async_lower_write_done")
        finalize = body("swapz_finalize_inflight_write")
        flush = body("swapz_flush_window")
        worker = body("swapz_worker_pass")
        drain = body("swapz_drain")
        authority = (ROOT / "src/kernel/authority.c").read_text()
        engine = (ROOT / "src/kernel/engine.c").read_text()
        status = body("swapz_status")
        self.assertIn("#define SWAPZ_WRITE_PIPELINE_DEPTH 1U", DM)
        self.assertIn("struct swapz_inflight_write inflight_write;", DM)
        self.assertNotIn("inflight_writes[", DM)
        self.assertNotIn("module_param_named(write_pipeline_depth,", DM)
        self.assertNotIn("SWAPZ_PRODUCTION_WRITE_PIPELINE_DEPTH", DM)
        self.assertIn(".fn = swapz_async_lower_write_done", submit)
        self.assertIn(".context = inflight", submit)
        self.assertIn("DM_IO_VMA", submit)
        self.assertIn("complete(&inflight->lower_done)", done)
        self.assertNotIn("swapz_engine_complete_batched_run", done)
        self.assertNotIn("swapz_complete(", done)
        self.assertNotIn("bio_endio", done)
        self.assertIn("swapz_engine_complete_batched_run", finalize)
        self.assertIn(
            "lower_elapsed = swapz_elapsed_ns(inflight->lower_start_ns, lower_end)",
            finalize)
        self.assertIn("if (!lower_end || lower_end < inflight->lower_start_ns)",
                      finalize)
        self.assertIn("lower_error = -EUCLEAN", finalize)
        timestamp_guard = finalize[
            finalize.index("if (!lower_end || lower_end < inflight->lower_start_ns)"):
            finalize.index("ctx->lower_write_wall_ns +=")]
        self.assertNotIn("return", timestamp_guard)
        self.assertLess(
            finalize.index("if (!lower_end || lower_end < inflight->lower_start_ns)"),
            finalize.index("swapz_engine_complete_batched_run"))
        self.assertNotIn("ctx->inflight_head", DM)
        self.assertNotIn("ctx->inflight_tail", DM)
        self.assertNotIn("% SWAPZ_WRITE_PIPELINE_DEPTH", submit)
        self.assertNotIn("% SWAPZ_WRITE_PIPELINE_DEPTH", finalize)
        self.assertIn("ctx->pipeline_active_wall_ns +=", finalize)
        self.assertIn("ctx->pipeline_post_lower_wall_ns +=", finalize)
        self.assertIn("pipeline_post_lower_wall_ns=%llu", status)
        self.assertIn("swapz_complete(inflight->bios[index]", finalize)
        self.assertNotIn("swapz_write_pipeline_can_append", DM)
        self.assertNotIn("append_second", flush)
        self.assertIn("prepared == count", flush)
        self.assertIn("swapz_inflight_tail_slot(ctx)", flush)
        self.assertIn("swapz_engine_abort_batched_run_tail", flush)
        self.assertIn("detached_inflight->bios[index] = bio", flush)
        self.assertIn("swapz_finalize_all_inflight(ctx, true)", flush)
        self.assertIn("swapz_batch_abort_tail", authority)
        self.assertIn("!a->batch_pending || a->batch_consumed", authority)
        self.assertIn("swapz_engine_abort_batched_run_tail", engine)
        self.assertIn("initial_batch_pending ?", engine)
        self.assertIn("pipeline_collected_pages", DM)
        self.assertIn("write_pipeline_depth=%u pipeline_active_max=%u", status)
        self.assertIn("while (swapz_has_inflight(ctx))", worker)
        self.assertIn("while (swapz_has_inflight(ctx))", drain)

    def test_bvec_iterator_is_not_double_advanced_for_folio_slices(self):
        copy = body("swapz_copy_bio")
        direct = body("swapz_map_single_bio_input")
        self.assertIn("bio_for_each_segment(vec, bio, iter)", copy)
        self.assertIn("kmap_local_page(vec.bv_page)", copy)
        self.assertNotIn("nth_page(", copy)
        self.assertIn("bio_for_each_segment(vec, bio, iter)", direct)
        self.assertNotIn("nth_page(", direct)

    def test_compound_and_segmented_bio_qualification_is_contract_covered(self):
        oracle = (ROOT / "tests/tools/device-roundtrip.c").read_text()
        deploy = (ROOT / "tests/tools/deploy-nullblk.sh").read_text()
        status = body("swapz_status")
        mapper = body("swapz_map")
        self.assertIn("--segmented-write-series", oracle)
        self.assertIn("--segmented-verify-series", oracle)
        self.assertIn("--thp-write-series", oracle)
        self.assertIn("--thp-verify-series", oracle)
        self.assertIn("series_thp", oracle)
        self.assertIn("#ifndef MADV_COLLAPSE", oracle)
        self.assertIn("madvise(thp_buf, thp_size, MADV_COLLAPSE)", oracle)
        self.assertIn("START_LOADED_COMPOUND_BIO", deploy)
        self.assertIn("PASS_LOADED_COMPOUND_BIO=", deploy)
        self.assertIn("transfer_segmented", oracle)
        self.assertIn("series_segmented", oracle)
        self.assertIn("bio_compound_folio_pages", deploy)
        self.assertIn("bio_segments_gt1", deploy)
        self.assertIn("bio_nonzero_offset", deploy)
        self.assertIn("bio_copy_fallback_pages", deploy)
        self.assertIn("bio_compound_folio_pages=%llu", status)
        self.assertIn("bio_segments_gt1=%llu", status)
        self.assertIn("bio_segments_max=%u", status)
        self.assertIn("bio_nonzero_offset=%llu", status)
        self.assertIn("bio_copy_fallback_pages=%llu", status)
        self.assertRegex(
            status,
            r"ctx->ordered_copy_fallback_pages\s*\+\s*"
            r"prep->copy_fallback_pages\s*\+\s*"
            r"submitter->copy_fallback_pages")
        self.assertIn("PageCompound(vec.bv_page)", mapper)
        self.assertIn("folio_test_large(page_folio(vec.bv_page))", mapper)

    def test_async_lz4_preparation_overlaps_lower_io_without_publication(self):
        producer = body("swapz_preparation_worker")
        queue_helper = body("swapz_queue_preparation_workers")
        accept = body("swapz_accept_write")
        mapper = body("swapz_map")
        ordered = body("swapz_worker_pass")
        lower = body("swapz_lower")
        finish = body("swapz_complete")
        release = body("swapz_release_prepared")
        prepared_put = body("swapz_prepared_put")
        ctor = body("swapz_ctr")
        drain = body("swapz_drain")
        freeing = body("swapz_free")
        status = body("swapz_status")
        benchmark = (ROOT / "tests/tools/benchmark-owned-pair.sh").read_text()
        deploy = (ROOT / "tests/tools/deploy-nullblk.sh").read_text()
        runner = (ROOT / "tests/tools/run-tests.py").read_text()
        loaded = (ROOT / "tests/tools/test-loaded.sh").read_text()
        fixture = (ROOT / "tests/runtime/benchmark/anon-page-fixture.py").read_text()
        prep_slots = (ROOT / "src/kernel/preparation-slots.h").read_text()
        prep_slots_native = (
            ROOT / "tests/runtime/native/io/preparation-slots.c").read_text()

        self.assertRegex(DM, r"static\s+bool\s+swapz_async_prepare\s*=\s*true\s*;")
        self.assertIn(
            "module_param_named(async_prepare, swapz_async_prepare, bool, 0444);",
            DM)
        self.assertNotIn("module_param_named(delta64_prepare_workers,", DM)
        self.assertIn("#define SWAPZ_DELTA64_PREPARATION_WORKERS 1U", DM)
        self.assertIn("ctx->async_prepare = swapz_async_prepare", ctor)
        self.assertIn("ctx->preparation_worker_count =", ctor)
        self.assertIn("SWAPZ_DELTA64_PREPARATION_WORKERS", ctor)
        self.assertNotIn("swapz_delta64_prepare_workers", ctor)
        self.assertIn("INIT_WORK(&lane->work, swapz_preparation_worker)", ctor)
        # The ordered owner runs on the submitting CPU: a bound queue keeps
        # admission, K=1 completion and upper wakeups off idle remote CPUs.
        self.assertIn('"swapz", WQ_MEM_RECLAIM, 1', ctor)
        self.assertNotIn('"swapz", WQ_MEM_RECLAIM | WQ_UNBOUND', ctor)
        self.assertIn('"swapz-lz4", WQ_MEM_RECLAIM | WQ_UNBOUND,', ctor)
        self.assertIn("ctx->preparation_worker_count);", ctor)
        self.assertIn("ctx->preparation_pages = vzalloc(SWAPZ_MAX_RECORDS *", ctor)
        self.assertIn("ctx->preparation_lanes = kcalloc(", ctor)
        self.assertNotIn("lane->input_page = vzalloc", ctor)
        self.assertIn("lane->lz4_workmem = kvmalloc(LZ4_MEM_COMPRESS", ctor)
        self.assertIn("atomic64_set(&ctx->preparation_free_mask", ctor)
        self.assertRegex(DM, r"struct swapz_prepared_page \{[^}]+\} __aligned\(64\);")
        self.assertRegex(DM, r"struct swapz_preparation_lane \{[^}]+\};")
        self.assertIn("if (!READ_ONCE(ctx->preparation_queued))", producer)
        self.assertIn("swapz_preparation_claim_slot(&ctx->preparation_free_mask)",
                      producer)
        self.assertNotIn("mempool_", DM)
        self.assertNotRegex(DM, r"\bpreparation_slots\b")
        self.assertLess(producer.index("swapz_preparation_claim_slot("),
                        producer.index("spin_lock_irqsave(&ctx->queue_lock, flags)"))
        self.assertLess(producer.index("swapz_preparation_claim_slot("),
                        producer.index("list_del_init(&entry->preparation_list)"))
        self.assertIn("prepared->length = swapz_compress_prepared_page(", producer)
        self.assertIn("lane->lz4_workmem", producer)
        self.assertNotIn("lane->input_page", producer)
        self.assertIn("lane->predictor_page", producer)
        self.assertIn("&lane->delta64", producer)
        self.assertNotIn("ctx->preparation_lz4_workmem", producer)
        self.assertIn("atomic_read(&ctx->lower_write_active)", producer)
        self.assertIn("bool detached_lower_write;", producer)
        self.assertIn("bool lower_write_active;", producer)
        self.assertRegex(
            producer,
            r"detached_lower_write\s*=\s*lower_write_active\s*&&\s*"
            r"swapz_has_inflight\(ctx\);")
        self.assertIn("if (lower_write_active && !detached_lower_write)",
                      producer)
        self.assertRegex(
            producer,
            r"\(!detached_lower_write\s*&&\s*"
            r"!atomic_xchg\(&ctx->preparation_tail_credit, 0\)\)")
        self.assertIn("if (detached_lower_write)", producer)
        self.assertNotIn("lower_read_active", DM)
        self.assertNotIn("swapz_lower_read_overlap_begin", DM)
        self.assertNotIn("swapz_lower_read_overlap_end", DM)
        self.assertIn("list_first_entry(&ctx->preparation_incoming", producer)
        self.assertIn("list_last_entry(&ctx->preparation_incoming", producer)
        self.assertIn("list_is_singular(&ctx->preparation_incoming)", producer)
        self.assertNotIn("ctx->preparation_worker_count > 1U", producer)
        self.assertIn("SWAPZ_PREPARATION_TAIL_CLAIM_MIN", producer)
        self.assertNotIn("parallel_tail_claim", producer)
        self.assertIn("atomic_xchg(&ctx->preparation_tail_credit, 0)", producer)
        self.assertIn("ctx->preparation_producer_head_claims++", producer)
        self.assertIn("ctx->preparation_producer_tail_claims++", producer)
        self.assertIn("complete_all(&entry->preparation_snapshot_ready)", producer)
        self.assertNotIn("complete(&entry->preparation_snapshot_ready)", DM)
        call = "complete_all(&entry->preparation_snapshot_ready);"
        producer_tail = producer[producer.rindex(call) + len(call):]
        self.assertNotIn("entry->", producer_tail)
        for forbidden in ("swapz_complete(", "swapz_finish(", "swapz_stage(",
                          "swapz_flush_window(", "dm_io(", "bio_endio(",
                          "swapz_engine_write_window"):
            self.assertNotIn(forbidden, producer)
        self.assertIn("for (lane = 0; lane < ctx->preparation_worker_count; ++lane)",
                      queue_helper)
        self.assertIn("queue_work(ctx->preparation_workqueue", queue_helper)
        self.assertIn("&ctx->preparation_lanes[lane].work", queue_helper)
        self.assertIn("swapz_queue_preparation_workers(ctx)", mapper)
        self.assertNotIn("lower_read_active", mapper)
        self.assertIn("swapz_queue_preparation_workers(ctx)", lower)
        self.assertIn("ctx->preparation_queued", lower)
        self.assertNotIn("swapz_lower_read_overlap_begin(ctx)", lower)
        self.assertNotIn("swapz_lower_read_overlap_end(ctx)", lower)
        self.assertIn("ctx->prep_lower_write_start_queued", lower)
        self.assertIn("ctx->prep_lower_write_end_queued", lower)
        self.assertIn("prep_lower_read_overlap_starts=%llu", status)
        self.assertIn("prep_lower_read_overlap_ns=%llu", status)
        self.assertRegex(status, r"prep->prepared_during_lower_write,\s*"
                         r"prep->lower_write_overlap_ns,\s*0ULL,\s*0ULL,")
        self.assertLess(lower.index("atomic_set(&ctx->lower_write_active, 1)"),
                        lower.index("swapz_queue_preparation_workers(ctx)"))
        self.assertLess(lower.index("swapz_queue_preparation_workers(ctx)"),
                        lower.index("error = swapz_dm_io("))
        self.assertIn("&entry->preparation_snapshot_ready", ordered)
        self.assertIn("entry->preparation_force_raw = true", ordered)
        self.assertIn("bool raw_pressure_hand_dispatchable;", ordered)
        self.assertIn("swapz_window_raw_pressure_hand_dispatchable(", ordered)
        # RAW for latency only when measured inline LZ4 costs more lower idle
        # than the extra RAW block costs lower service.
        self.assertRegex(ordered,
            r"ctx->batch_count >=\s*SWAPZ_WINDOW_DRY_PACK_MIN_RECORDS - 1U\s*&&"
            r"\s*raw_pressure_hand_dispatchable\s*&&"
            r"\s*swapz_window_raw_hand_pays\(\s*ctx->ordered_lz4_page_ewma_ns,"
            r"\s*ctx->lower_write_block_service_ewma_ns\)\s*&&"
            r"\s*!lower_write_busy && accepted_backlog")
        self.assertIn("ctx->preparation_ordered_raw++", ordered)
        self.assertIn("ctx->work_conserving_hand_records", ordered)
        self.assertIn("swapz_next_local_write_ready(ctx, &local)", ordered)
        self.assertIn("static bool swapz_next_local_write_ready", DM)
        self.assertIn("completion_done(&next_entry->preparation_snapshot_ready)", DM)
        self.assertIn("!list_empty(&entry->preparation_list)", ordered)
        self.assertIn("list_del_init(&entry->preparation_list)", ordered)
        self.assertIn("entry->preparation_inline = true", ordered)
        self.assertNotIn("defer_for_preparation", ordered)
        self.assertIn("bool lower_write_busy;", ordered)
        self.assertIn("lower_write_busy = swapz_has_inflight(ctx)", ordered)
        self.assertIn("!lower_write_busy && accepted_backlog", ordered)
        self.assertIn("ctx->batch_count <", ordered)
        self.assertIn("ctx->batch_count + ctx->preparation_queued >=", ordered)
        self.assertIn("swapz_window_work_conserving_close_ready(", ordered)
        dry_pack_call = re.compile(
            r"swapz_window_work_conserving_close_ready\(\s*ctx->retain_ms,\s*"
            r"ctx->single_pack_deferred \|\|\s*"
            r"ctx->accepted_burst_pack_ready,")
        self.assertEqual(len(dry_pack_call.findall(ordered)), 2)
        self.assertIn("ctx->batch_count >= ctx->work_conserving_hand_records",
                      ordered)
        self.assertIn("if (list_empty(&ctx->incoming))", ordered)
        self.assertIn("swapz_local_head_is_plain_write(&local)", ordered)
        self.assertIn("swapz_close_worker_pack_cause(", ordered)
        self.assertIn("queue_work() is only a request, not an ownership", ordered)
        self.assertIn("swapz_preparation_read_state(", ordered)
        self.assertIn("atomic_read_acquire(state)", prep_slots)
        self.assertIn("memory_order_relaxed", prep_slots_native)
        self.assertIn("static int atomic_read_acquire(", prep_slots_native)
        # A failed conditional kernel RMW does not guarantee acquire ordering.
        # Keep the native shim honest so it cannot conceal the READY race.
        raw_cas_shim = source_body("atomic_cmpxchg", prep_slots_native)
        self.assertIn("memory_order_seq_cst, memory_order_relaxed", raw_cas_shim)
        self.assertNotIn("memory_order_acquire", raw_cas_shim)
        self.assertIn("test_ready_publication_wins_raw_cas", prep_slots_native)
        self.assertNotIn("ordered_worker_busy", DM)
        self.assertIn("atomic_set(&ctx->preparation_tail_credit, 1)", ordered)
        self.assertIn("atomic_set(&ctx->preparation_tail_credit, 0)", ordered)
        self.assertIn("bool inline_preparation = false", ordered)
        self.assertIn("inline_preparation = true", ordered)
        self.assertIn("ctx->preparation_ordered_inline++", ordered)
        self.assertIn("ctx->preparation_ordered_handoffs++", ordered)
        self.assertIn("ctx->preparation_ordered_waits++", ordered)
        self.assertIn("wait_for_completion(&entry->preparation_snapshot_ready)", ordered)
        self.assertIn("prepared = READ_ONCE(entry->prepared_page);", ordered)
        self.assertLess(ordered.index("wait_for_completion("),
                        ordered.index("swapz_process(ctx, entry->bio)"))
        self.assertIn("prepared_async = ctx->async_prepare && !entry->preparation_inline",
                      accept)
        self.assertIn("prepared->bytes", accept)
        self.assertIn("entry->prepared_page->raw_bytes", accept)
        self.assertIn("swapz_preparation_select_raw(&prepared->state)", accept)
        self.assertGreaterEqual(
            accept.count("ctx->work_conserving_window = true"), 4)
        self.assertIn("accepted_work_lower_idle_events=%llu", status)
        self.assertIn("accepted_work_lower_idle_ns=%llu", status)
        self.assertIn("swapz_end_accepted_lower_idle(ctx", DM)
        self.assertIn("ctx->lz4_workmem", accept)
        self.assertIn("swapz_release_prepared(bio)", finish)
        self.assertLess(finish.index("swapz_release_prepared(bio)"),
                        finish.index("bio_endio(bio)"))
        self.assertIn("swapz_prepared_put(ctx, prepared)", release)
        self.assertIn("prepared - ctx->preparation_pages", prepared_put)
        self.assertIn("refcount_dec_and_test(&prepared->refs)", prepared_put)
        self.assertIn("drain_workqueue(ctx->preparation_workqueue)", drain)
        self.assertLess(drain.index("drain_workqueue(ctx->preparation_workqueue)"),
                        drain.index("drain_workqueue(ctx->workqueue)"))
        self.assertLess(drain.index("drain_workqueue(ctx->workqueue)"),
                        drain.rindex("drain_workqueue(ctx->preparation_workqueue)"))
        self.assertIn("cancel_work_sync(&ctx->preparation_lanes[prep_lane].work)",
                      freeing)
        self.assertIn("destroy_workqueue(ctx->preparation_workqueue)", freeing)
        self.assertIn("kvfree(ctx->preparation_lanes[prep_lane].lz4_workmem)",
                      freeing)
        self.assertIn("kfree(ctx->preparation_lanes)", freeing)
        self.assertIn("vfree(ctx->preparation_pages)", freeing)
        self.assertIn("ctx->lz4_wall_ns + prep->lz4_wall_ns", status)
        self.assertIn("prep->copy_wall_ns", status)
        self.assertIn("prep->worker_wall_ns", status)
        self.assertIn("prep->worker_cpu_ns", status)
        self.assertIn("delta64_prepare_workers=%u", status)
        self.assertIn("delta64_prepare_active_max=%u", status)
        self.assertIn("delta64_prepare_pages=%llu", status)
        self.assertIn("delta64_prepare_parallel_starts=%llu", status)
        self.assertIn("atomic_read(&ctx->preparation_workers_active_max)", status)
        self.assertNotIn("preparation_parallel_starts", DM)
        self.assertNotIn("atomic64_inc(", producer)
        self.assertIn("write_copy_wall_ns=%llu write_copy_bytes=%llu", status)
        self.assertIn("direct_lz4_input_pages=%llu", status)
        self.assertIn("static const u8 *swapz_map_single_bio_input", DM)
        self.assertIn("swapz_map_single_bio_input(entry->bio", producer)
        self.assertIn("swapz_memcpy_accounted(prepared->raw_bytes", producer)
        self.assertLess(
            producer.index("swapz_memcpy_accounted(prepared->raw_bytes"),
            producer.rindex("WRITE_ONCE(entry->prepared_page, prepared)"))
        self.assertLess(
            producer.rindex("WRITE_ONCE(entry->prepared_page, prepared)"),
            producer.rindex("complete_all(&entry->preparation_snapshot_ready)"))
        self.assertIn("async_prepare=%u delta64_prepare_workers=%u", status)
        self.assertNotIn('"delta64_rescue=$DELTA64_RESCUE"', benchmark)
        self.assertNotIn('"delta64_lz4_acceleration=$DELTA64_LZ4_ACCELERATION"',
                         benchmark)
        self.assertRegex(benchmark, r"(?m)^DELTA64_LZ4_ACCELERATION=4$")
        self.assertRegex(
            DM, r"static unsigned int swapz_delta64_lz4_acceleration =\s*"
            r"SWAPZ_LZ4_DELTA64_ACCELERATION_DEFAULT;")
        self.assertIn("PRODUCTION_DELTA64_LZ4_ACCELERATION = 4",
                      (ROOT / "tests/tools/run-tests.py").read_text())
        self.assertNotRegex(benchmark, r"(?m)^PARALLEL_READS=")
        self.assertNotIn("DELTA64_PARALLEL_READS", benchmark)
        self.assertNotIn("$DELTA64_PREPARE_WORKERS", benchmark)
        self.assertNotIn("--delta64-prepare-workers", benchmark)
        self.assertIn("expected_delta64_workers=$ASYNC_PREPARE", benchmark)
        self.assertIn("delta64_prepare_workers=$expected_delta64_workers", benchmark)
        self.assertNotIn("START_DELTA64_PREPARE_WORKERS=", loaded)
        self.assertNotIn("--weights delta64=100", loaded)
        self.assertIn('"delta64"', fixture)
        self.assertIn("def parse_delta64_prepare_sessions", runner)
        self.assertIn("PASS_DELTA64_PREPARE_AB", runner)
        self.assertIn("matched_value_pairs(sessions, \"workers\", 1, 2)", runner)
        self.assertIn("delta64_prepare_parallel_starts", runner)
        self.assertNotIn('for delta64_mode in "${confirmation_modes[@]}"', loaded)
        self.assertNotIn("for delta64_workers in 1 2 4", loaded)
        self.assertRegex(benchmark, r"(?m)^ASYNC_PREPARE=0$")
        self.assertIn("--async-prepare", benchmark)
        self.assertIn("async_prepare=1([[:space:]]|$)", deploy)
        self.assertIn('status_u64 "$packed_before" async_prepare', deploy)
        self.assertGreaterEqual(deploy.count('insmod "$MODULE"'), 2)
        self.assertIn("10:1000000:1:1|80:150000:1:64", benchmark)

    def test_loaded_privilege_boundary_preserves_git_metadata(self):
        deploy = (ROOT / "tests/tools/deploy-nullblk.sh").read_text()
        benchmark = (ROOT / "tests/tools/benchmark-owned-pair.sh").read_text()
        lifecycle = (
            ROOT / "tests/tools/qualify-primary-lifecycle-nullblk.sh").read_text()
        loaded = (ROOT / "tests/tools/test-loaded.sh").read_text()
        self.assertIn("git diff --cached --quiet", loaded)
        self.assertIn("assert_git_metadata_unchanged", loaded)
        self.assertIn("run_privileged()", loaded)
        self.assertIn("--validated-source", loaded)
        for script in (deploy, benchmark):
            self.assertIn("--validated-source", script)
            self.assertIn("VALIDATED_SOURCE", script)
            self.assertNotIn("GIT_OPTIONAL_LOCKS", script)
            self.assertNotIn("git branch --show-current", script)
            self.assertNotIn("git merge-base", script)
            self.assertNotIn("git rev-parse", script)
            self.assertNotRegex(script, r"(?m)^\s*git\s")
            self.assertNotIn("$(git ", script)
        self.assertIn("--validated-source", lifecycle)
        self.assertIn("SOURCE_HEAD", lifecycle)
        self.assertNotIn("GIT_OPTIONAL_LOCKS", lifecycle)
        self.assertNotIn("git rev-parse", lifecycle)
        self.assertNotIn("git diff", lifecycle)
        self.assertNotRegex(lifecycle, r"(?m)^\s*git\s")
        self.assertNotIn("$(git ", lifecycle)
        self.assertIn("${TMPDIR:-/tmp}/swapz-deploy.", deploy)
        self.assertIn("${TMPDIR:-/tmp}/swapz-benchmark.", benchmark)

    def test_retired_lz4_ab_is_not_an_overall_gate(self):
        runner = (ROOT / "tests/tools/run-tests.py").read_text()
        self.assertIn("def required_benchmark_gates_pass(benchmarks):", runner)
        self.assertIn('"PASS_BOUNDED_RAM_MATRIX"', runner)
        self.assertIn('"PASS_WRITE_SATURATION_EVIDENCE"', runner)
        self.assertNotIn(
            'lz4_sweep.get("overall") != "PASS_LZ4_ACCELERATION_AB"',
            runner)


    def test_id36_admission_inventory_and_phase_are_fail_closed(self):
        """The early observation is advisory; only a valid late 1 GiB sample admits."""
        import subprocess
        import tempfile

        pressure = (ROOT / "tests/tools/qualify-resource-pressure.sh").read_text()
        preflight = (ROOT / "tests/tools/loaded-preflight.sh").read_text()
        self.assertIn(
            "OBSERVED_ID36_EARLY_HOST_MEMORY=source:/proc/meminfo", preflight)
        self.assertIn("admission:no", preflight)
        self.assertIn("MIN_AVAILABLE_KIB=$((1024 * 1024))", pressure)
        self.assertIn(
            "MIN_AVAILABLE_BYTES=$((MIN_AVAILABLE_KIB * 1024))", pressure)
        self.assertIn("for admission_sample in 1 2 3 4 5; do", pressure)
        self.assertIn("if (( available_kib >= MIN_AVAILABLE_KIB )); then", pressure)
        self.assertIn("sleep 1", pressure)
        self.assertIn("ID36_PARENT_CGROUP_MEMORY=source:", pressure)
        self.assertIn("root-exempt root-exempt unbounded", pressure)
        self.assertNotIn("BLOCKED: ID36 parent cgroup budget below 896 MiB", pressure)
        self.assertIn(
            "BLOCKED: ID36 cgroup root lacks 1 GiB effective memory headroom",
            pressure)
        self.assertIn("BLOCKED: ID36 host lacks 1 GiB MemAvailable", pressure)
        self.assertLess(
            pressure.index("START_ID36_RESOURCE_PRESSURE=admission"),
            pressure.index('for admission_sample in 1 2 3 4 5; do'))
        start = pressure.index("read_host_memory_inventory() {")
        end = pressure.index("\n}\n", start) + 2
        helper = pressure[start:end].replace("/proc/meminfo", '"$1"')
        command = helper + "\nread_host_memory_inventory \"$1\"\n"
        sample = (
            "MemTotal: 3863624 kB\n"
            "MemAvailable: 894992 kB\n"
            "MemFree: 100000 kB\n"
            "Cached: 400000 kB\n"
            "SReclaimable: 90000 kB\n"
            "SwapTotal: 2097152 kB\n"
            "SwapFree: 1573076 kB\n"
        )
        with tempfile.TemporaryDirectory(prefix="swapz-id36-meminfo-") as folder:
            path = Path(folder) / "meminfo"

            def observe(contents):
                path.write_text(contents)
                return subprocess.run(
                    ["bash", "-c", command, "_", str(path)],
                    capture_output=True, text=True, timeout=5)

            result = observe(sample)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                result.stdout.strip(),
                "3863624 894992 100000 400000 90000 2097152 1573076")
            for bad in (
                sample.replace("894992 kB", "894992 bytes"),
                sample.replace("894992 kB", "0894992 kB"),
                sample.replace("MemAvailable: 894992 kB\n", ""),
                sample + "MemAvailable: 894992 kB\n",
                sample.replace("894992 kB", "99999999999999999999 kB"),
            ):
                with self.subTest(bad=bad[-55:]):
                    self.assertNotEqual(observe(bad).returncode, 0)
            path.unlink()
            unavailable = subprocess.run(
                ["bash", "-c", command, "_", str(path)],
                capture_output=True, text=True, timeout=5)
            self.assertNotEqual(unavailable.returncode, 0)

        cgroup_start = pressure.index("read_cgroup_root_memory_inventory() {")
        cgroup_end = pressure.index("\n}\n", cgroup_start) + 2
        cgroup_helper = pressure[cgroup_start:cgroup_end]
        cgroup_command = (
            "set -euo pipefail\nCGROUP_ROOT=$1\n"
            "MIN_AVAILABLE_BYTES=$((1024 * 1024 * 1024))\n" +
            cgroup_helper + "\nread_cgroup_root_memory_inventory\n")
        with tempfile.TemporaryDirectory(
                prefix="swapz-id36-cgroup-root-") as folder:
            root = Path(folder)

            def cgroup_inventory():
                return subprocess.run(
                    ["bash", "-c", cgroup_command, "_", str(root)],
                    capture_output=True, text=True, timeout=5)

            result = cgroup_inventory()
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                result.stdout.strip(), "root-exempt root-exempt unbounded")

            (root / "memory.max").write_text("max\n")
            (root / "memory.current").write_text("123\n")
            result = cgroup_inventory()
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), "max 123 unbounded")

            (root / "memory.max").write_text(str(2 * 1024 * 1024 * 1024) + "\n")
            (root / "memory.current").write_text(str(512 * 1024 * 1024) + "\n")
            result = cgroup_inventory()
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                result.stdout.strip(),
                f"{2 * 1024 * 1024 * 1024} {512 * 1024 * 1024} sufficient")

            # The same frozen 1 GiB floor also applies to a finite ancestor
            # budget so an environmental cgroup cap cannot become a later OOM.
            # One byte under the 1 GiB floor near 2^53 must stay BLOCKED.
            huge_current = 2**53 + 1
            huge_limit = huge_current + 1024**3 - 1
            (root / "memory.max").write_text(str(huge_limit) + "\n")
            (root / "memory.current").write_text(str(huge_current) + "\n")
            result = cgroup_inventory()
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(result.stdout.strip().endswith("insufficient"))

            (root / "memory.max").write_text(str(512 * 1024 * 1024) + "\n")
            (root / "memory.current").write_text("123\n")
            result = cgroup_inventory()
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                result.stdout.strip(),
                f"{512 * 1024 * 1024} 123 insufficient")

            for maximum, current in (
                    ("01\n", "123\n"),
                    ("max\n", "0123\n"),
                    ("garbage\n", "123\n"),
                    ("123\n", "124\n")):
                with self.subTest(maximum=maximum, current=current):
                    (root / "memory.max").write_text(maximum)
                    (root / "memory.current").write_text(current)
                    self.assertNotEqual(cgroup_inventory().returncode, 0)

            u64_max = (1 << 64) - 1
            (root / "memory.max").write_text(str(u64_max) + "\n")
            (root / "memory.current").write_text(
                str(u64_max - 2 * 1024**3) + "\n")
            result = cgroup_inventory()
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(result.stdout.strip().endswith("sufficient"))

            for maximum, current in (
                    (str(u64_max + 1) + "\n", "0\n"),
                    ("max\n", str(u64_max + 1) + "\n")):
                with self.subTest(maximum=maximum, current=current):
                    (root / "memory.max").write_text(maximum)
                    (root / "memory.current").write_text(current)
                    self.assertNotEqual(cgroup_inventory().returncode, 0)

            (root / "memory.max").write_text("max\n")
            (root / "memory.current").write_text("1" * 21 + "\n")
            self.assertNotEqual(cgroup_inventory().returncode, 0)

            (root / "memory.current").unlink()
            self.assertNotEqual(cgroup_inventory().returncode, 0)


    def test_id36_memory_events_and_cpu_psi_require_real_counters(self):
        """Missing OOM or PSI cannot masquerade as a healthy zero reading."""
        import subprocess
        import tempfile

        pressure = (ROOT / "tests/tools/qualify-resource-pressure.sh").read_text()
        start = pressure.index("event_value() {")
        end = pressure.index("\n}\n", pressure.index("cpu_some_total() {")) + 2
        reader = pressure[start:end]
        command = ("set -euo pipefail\nCGROUP=$1\n" + reader +
                   "\nif [[ $2 == event ]]; then event_value \"$3\"; "
                   "else cpu_some_total; fi\n")
        with tempfile.TemporaryDirectory(prefix="swapz-id36-events-") as folder:
            cgroup = Path(folder)
            events = cgroup / "memory.events"
            psi = cgroup / "cpu.pressure"
            healthy = (
                "low 0\nhigh 7\nmax 0\noom 0\noom_kill 0\n"
                "oom_group_kill 0\n"
            )
            cpu_healthy = (
                "some avg10=0.00 avg60=0.00 avg300=0.00 total=25\n"
                "full avg10=0.00 avg60=0.00 avg300=0.00 total=0\n"
            )

            def read(kind, key="oom"):
                return subprocess.run(
                    ["bash", "-c", command, "_", str(cgroup), kind, key],
                    capture_output=True, text=True, timeout=5)

            events.write_text(healthy)
            psi.write_text(cpu_healthy)
            self.assertEqual(read("event", "high").stdout.strip(), "7")
            self.assertEqual(read("event", "oom").stdout.strip(), "0")
            self.assertEqual(read("psi").stdout.strip(), "25")
            for invalid in (
                healthy.replace("oom 0\n", ""),
                healthy + "oom 0\n",
                healthy.replace("oom 0", "oom -1"),
                healthy.replace("oom 0", "oom 00"),
                healthy.replace("oom 0", "oom 0 bytes"),
                healthy.replace("oom 0", "oom 1000000000000000000"),
            ):
                with self.subTest(events=invalid[-32:]):
                    events.write_text(invalid)
                    result = read("event", "oom")
                    self.assertEqual(result.returncode, 2)
                    self.assertIn("BLOCKED:", result.stderr)
            events.write_text(healthy)
            for invalid in (
                cpu_healthy.replace("total=25", "avg10=0.00"),
                cpu_healthy.replace("total=25", "total=bad"),
                cpu_healthy.replace("total=25", "total=25 total=25"),
                cpu_healthy.replace("some ", "full ", 1),
                cpu_healthy.replace("total=25", "total=1000000000000000000"),
            ):
                with self.subTest(psi=invalid[:45]):
                    psi.write_text(invalid)
                    result = read("psi")
                    self.assertEqual(result.returncode, 2)
                    self.assertIn("BLOCKED:", result.stderr)

    def test_id36_resource_pressure_is_bounded_and_owned(self):
        loaded = (ROOT / "tests/tools/test-loaded.sh").read_text()
        pressure = (ROOT / "tests/tools/qualify-resource-pressure.sh").read_text()
        benchmark = (ROOT / "tests/tools/benchmark-owned-pair.sh").read_text()
        helper = (ROOT / "tests/runtime/benchmark/resource-pressure.py").read_text()
        replay = (ROOT / "tests/runtime/benchmark/io-replay.py").read_text()
        rootless = (ROOT / "tests/tools/test-rootless.sh").read_text()
        runner = (ROOT / "tests/tools/run-tests.py").read_text()

        self.assertIn("qualify-resource-pressure.sh", loaded)
        self.assertIn("--validated-source \"$tested_source\"", loaded)
        self.assertIn("--shared-plan \"$shared_plan\"", loaded)
        self.assertIn("CGROUP_ROOT=/sys/fs/cgroup", pressure)
        self.assertIn("MEMORY_HEADROOM_BYTES=$((64 * 1024 * 1024))", pressure)
        self.assertIn("MEMORY_MAX_BYTES=$((896 * 1024 * 1024))", pressure)
        self.assertIn("MEMORY_HIGH_BYTES=$((pressure_current + MEMORY_HEADROOM_BYTES))", pressure)
        self.assertIn("PAIR_REPLAY_TIMEOUT_SECONDS=280", pressure)
        self.assertIn(
            "PAIR_OUTER_SLACK_SECONDS=$PAIR_REPLAY_TIMEOUT_SECONDS", pressure)
        self.assertIn(
            "PAIR_OUTER_SECONDS=$((PAIR_REPLAY_TIMEOUT_SECONDS * 2 + PAIR_OUTER_SLACK_SECONDS))",
            pressure)
        self.assertIn("memory.swap.max", pressure)
        self.assertIn("cpu_workers=$((online_cpus * 2))", pressure)
        self.assertIn("PRESSURE_MIB=576", pressure)
        self.assertIn("PRESSURE_RAMP_MIB=80", pressure)
        self.assertIn(
            "READY_PRESSURE_MIB=$((PRESSURE_MIB - PRESSURE_RAMP_MIB))",
            pressure)
        self.assertIn("PASS_ID36_RESOURCE_PRESSURE=", pressure)
        self.assertIn("high_delta > 0", pressure)
        self.assertIn("oom_ready == oom_start && oom_kill_ready == oom_kill_start", pressure)
        self.assertIn("oom_delta == 0 && oom_kill_delta == 0", pressure)
        self.assertIn("cpu_some_delta > 0", pressure)
        self.assertIn("--async-prepare --resource-pressure-short --shared-plan", pressure)
        self.assertIn('PRESSURE_ACTIVATE="$SESSION/pressure.activate"', pressure)
        self.assertIn('PRESSURE_ACTIVE="$SESSION/pressure.active"', pressure)
        self.assertIn('PAIR_READY="$SESSION/pair.ready"', pressure)
        self.assertIn('PAIR_GO="$SESSION/pair.go"', pressure)
        self.assertLess(pressure.index(': > "$PRESSURE_ACTIVATE"'),
                        pressure.index(': > "$PAIR_GO"'))
        self.assertIn("high_active > high_before", pressure)
        self.assertIn("SWAPZ_ID36_PAIR_READY", pressure)
        self.assertIn('SWAPZ_ID36_CGROUP="$CGROUP"', pressure)
        self.assertIn(
            'SWAPZ_ID36_REPLAY_TIMEOUT_SECONDS="$PAIR_REPLAY_TIMEOUT_SECONDS"',
            pressure)
        self.assertIn('ID36_CGROUP="${SWAPZ_ID36_CGROUP:-}"', benchmark)
        self.assertIn(
            'ID36_REPLAY_TIMEOUT_SECONDS="${SWAPZ_ID36_REPLAY_TIMEOUT_SECONDS:-}"',
            benchmark)
        self.assertIn('[[ $ID36_REPLAY_TIMEOUT_SECONDS == 280 ]]', benchmark)
        self.assertIn('REPLAY_TIMEOUT="${ID36_REPLAY_TIMEOUT_SECONDS}s"', benchmark)
        self.assertIn("PASS_ID36_NULLBLK_PREWARM", benchmark)
        self.assertIn("PASS_ID36_PAIR_CGROUP", benchmark)
        self.assertIn('> "$ID36_CGROUP/cgroup.procs"', benchmark)
        self.assertIn('grep -Fxq "$$" "$ID36_CGROUP/cgroup.procs"', benchmark)
        self.assertLess(benchmark.index("PASS_ID36_NULLBLK_PREWARM"),
                        benchmark.index('> "$ID36_CGROUP/cgroup.procs"'))
        self.assertIn("pair_cgroup_pid=", pressure)
        self.assertIn('grep -Fxq "$pair_cgroup_pid" "$CGROUP/cgroup.procs"', pressure)
        self.assertIn("for _ in {1..800}", pressure)
        self.assertIn("for _ in {1..1200}", benchmark)
        self.assertIn('"${PAIR_OUTER_SECONDS}s"', pressure)
        self.assertIn(
            "run_privileged_bounded 960 tests/tools/qualify-resource-pressure.sh",
            loaded)
        self.assertIn("oflag=direct", benchmark)
        self.assertIn("--lower-mbps 80 --hw-queue-depth 64", pressure)
        self.assertIn('PAIR_LOG="$SESSION/pair.log"', pressure)
        self.assertIn('wait "$PAIR_PID"', pressure)
        self.assertIn("pair_rc=$?", pressure)
        self.assertNotIn("PIPESTATUS", pressure)
        self.assertIn("RESOURCE_PRESSURE_SHORT=0", benchmark)
        self.assertIn("--resource-pressure-short", benchmark)
        self.assertIn("WARMUP_OPS=128", benchmark)
        self.assertIn("MEASURE_OPS=2048", benchmark)
        # Keep the ID36 mixed trace in a fixed-lane native engine: allocations
        # in the old Python per-wave Future dispatcher are reclaim-throttled
        # under the deliberately exceeded cgroup memory.high watermark.
        pressure_mode = benchmark.split(
            "if (( RESOURCE_PRESSURE_SHORT )); then", 1)[1].split(
                "if (( WRITE_ONLY_QD )); then", 1)[0]
        self.assertIn("NATIVE_REPLAY=1", pressure_mode)
        self.assertIn("[[ -x build/tests/native/io-replay-native ]]", pressure_mode)
        self.assertIn("REPLAY_ARGS+=(--native-replay)", benchmark)
        native = (ROOT / "tests/runtime/benchmark/io-replay-native.c").read_text()
        self.assertIn("ctx.events = calloc(ctx.event_count,", native)
        self.assertIn("ctx.latencies = calloc(ctx.measure_ops,", native)
        self.assertIn("pthread_barrier_wait(&ctx->wave_barrier)", native)
        self.assertIn("pthread_create(&threads[index]", native)
        self.assertLess(native.index("ctx.events = calloc("),
                        native.index("pthread_create(&threads[index]"))
        self.assertIn('("persistent-write", "persistent-mixed") else "waves")', replay)
        self.assertIn("REPLAY_ARGS+=(--allocation-bounded-packed-read)", benchmark)
        self.assertIn("--allocation-bounded-packed-read", replay)
        self.assertIn("allocation_bounded=args.allocation_bounded_packed_read", replay)
        self.assertIn("pool.submit(persistent_lane_worker, lane)", replay)
        self.assertIn("image_hash.update(", replay)
        self.assertIn("jobs = [pool.submit(read_one, page, slot)", replay)
        self.assertIn('plan_dir="$SHARED_PLAN/plan-id36"', benchmark)
        self.assertIn('--output-dir "$shared_plan/plan-id36"', loaded)
        self.assertNotIn("swapon", pressure)
        self.assertNotIn("allow_physical_backing", pressure)
        self.assertIn("mmap.mmap(", helper)
        self.assertIn("--ready-memory-mib", helper)
        self.assertIn("--activate-file", helper)
        self.assertIn("--active-file", helper)
        self.assertIn("multiprocessing.get_context(\"fork\")", helper)
        self.assertLess(helper.index("for worker in workers:\n        worker.start()"),
                        helper.index("pressure = mmap.mmap("))
        self.assertIn("os.nice(10)", helper)
        self.assertIn("worker.is_alive()", helper)
        self.assertIn("resource-pressure.py --help", rootless)
        self.assertIn('"id36": re.compile(', runner)
        self.assertIn("ID36 low-RAM/heavy-CPU evidence is incomplete", runner)

    def test_id36_failed_pair_pressure_stop_is_private_and_failure_only(self):
        """Execute the actual shell helper without cgroups or privileged devices."""
        import subprocess
        import tempfile

        benchmark = (ROOT / "tests/tools/benchmark-owned-pair.sh").read_text()
        start = benchmark.index("id36_release_failed_pair_pressure() {")
        end = benchmark.index("\n}\n", start) + 2
        helper = benchmark[start:end]
        script = ("set -euo pipefail\n"
                  "note() { :; }\n"
                  "RESOURCE_PRESSURE_SHORT=$1\n"
                  "id36_pair_dir=$2\n"
                  "ID36_PAIR_READY=$id36_pair_dir/pair.ready\n"
                  "ID36_PAIR_GO=$id36_pair_dir/pair.go\n" +
                  helper + "\n"
                  'id36_release_failed_pair_pressure "$3"\n')
        with tempfile.TemporaryDirectory(prefix="swapz-id36-stop-") as folder:
            private = Path(folder) / "owned"
            private.mkdir()
            (private / "pair.ready").write_text("pid=1\n")
            stop = private / "pressure.stop"

            def invoke(pressure, failed):
                result = subprocess.run(
                    ["bash", "-c", script, "_", str(pressure), str(private),
                     str(failed)],
                    capture_output=True, text=True, timeout=5)
                self.assertEqual(result.returncode, 0, result.stderr)

            invoke(1, 0)
            self.assertFalse(stop.exists())
            invoke(0, 1)
            self.assertFalse(stop.exists())
            invoke(1, 1)
            self.assertTrue(stop.exists())
            stop.unlink()

            # Never follow an attacker-controlled stop-file symlink.
            foreign = Path(folder) / "foreign"
            foreign.write_text("unchanged\n")
            stop.symlink_to(foreign)
            invoke(1, 1)
            self.assertEqual(foreign.read_text(), "unchanged\n")
            stop.unlink()
            (private / "pair.ready").unlink()
            invoke(1, 1)
            self.assertFalse(stop.exists())

    def test_loaded_preflight_recovers_only_proven_stale_owned_mapping(self):
        preflight = (ROOT / "tests/tools/loaded-preflight.sh").read_text()
        pair = (ROOT / "tests/tools/benchmark-owned-pair.sh").read_text()
        loaded = (ROOT / "tests/tools/test-loaded.sh").read_text()
        rootless = (ROOT / "tests/tools/test-rootless.sh").read_text()
        recovery = preflight[preflight.index("swapz_map_list="):]
        self.assertIn('swapz_map_list="$(', preflight)
        self.assertIn("cannot enumerate pre-existing swapz mappings", preflight)
        self.assertIn("cannot parse pre-existing swapz mapping list", preflight)
        self.assertIn('[[ ${#swapz_maps[@]} == 1 ]]', preflight)
        self.assertIn('token="${owned_map#swapz-demo-}"', recovery)
        self.assertIn('is_hex16 "$token"', recovery)
        self.assertIn('"SWAPZ-TEST-$token-flushfault"', recovery)
        self.assertNotIn("BASH_REMATCH", recovery)
        self.assertIn("value !~ /[()[:space:]]/", recovery)
        self.assertIn('lower_index="${lower_name#nullb}"', recovery)
        self.assertIn('opens == 0', preflight)
        self.assertIn('memory_backed', preflight)
        self.assertIn("is_uint()", preflight)
        self.assertIn('""|0*|*[!0-9]*) return 1', preflight)
        self.assertIn("is_hex16()", preflight)
        self.assertNotIn("=~", preflight)
        self.assertNotIn("((", preflight)
        self.assertIn('for attempt in {1..30}; do', recovery)
        self.assertIn("preflight_internal_error()", preflight)
        self.assertIn(
            "FAIL: loaded preflight internal command failed status=%s line=%s",
            preflight)
        self.assertIn(
            "trap 'rc=$?; preflight_internal_error \"$rc\" \"$LINENO\"' ERR",
            preflight)
        self.assertNotIn("BASH_COMMAND", preflight)
        self.assertLess(
            preflight.index("trap 'rc=$?; preflight_internal_error"),
            preflight.index("clean_orphaned_nullb()"))
        self.assertIn('mapper_node="$(readlink -f "$mapper"', recovery)
        self.assertIn('mapper_dev="$(stat -Lc', recovery)
        self.assertIn('canonical_dev="$(stat -Lc', recovery)
        self.assertIn('$mapper_dev == "$canonical_dev"', recovery)
        self.assertLess(
            recovery.index("canonical device identity changed"),
            recovery.index('fuser -k -TERM "$mapper_node"'))
        self.assertIn('fuser -k -TERM "$mapper_node"', recovery)
        self.assertIn('fuser -k -KILL "$mapper_node"', recovery)
        self.assertIn("reboot required before make test", recovery)
        self.assertLess(
            recovery.index('[[ -n $owned_config &&'),
            recovery.index('fuser -k -TERM "$mapper_node"'))
        self.assertLess(
            recovery.index('lower="/dev/$lower_name"'),
            recovery.index('fuser -k -TERM "$mapper_node"'))
        self.assertNotIn('fuser -k -TERM "$mapper"', recovery)
        self.assertIn('dmsetup remove --retry "$owned_map"', preflight)
        self.assertIn('timeout --signal=TERM --kill-after=2s 10s', preflight)
        self.assertIn("run_privileged_bounded()", loaded)
        self.assertIn(
            "loaded preflight exited with shell/runtime status 2", loaded)
        self.assertIn("[[ -x tests/tools/loaded-preflight.sh ]]", rootless)
        # Private loaded helpers are shell scripts and are intentionally invoked
        # through bash; the watchdog must not add an executable-bit requirement.
        self.assertIn(
            'exec timeout --signal=TERM --kill-after=10s "${limit}s" bash "$@"',
            loaded)
        self.assertNotIn(
            'exec timeout --signal=TERM --kill-after=10s "${limit}s" "$@"',
            loaded)
        self.assertIn("run_privileged_bounded 60 tests/tools/loaded-preflight.sh",
                      loaded)
        self.assertIn("run_privileged_bounded 600 tests/tools/deploy-nullblk.sh",
                      loaded)
        self.assertIn(
            "run_privileged_bounded 14400 "
            "tests/tools/qualify-primary-lifecycle-nullblk.sh", loaded)
        self.assertIn("run_privileged_bounded 720 tests/tools/benchmark-owned-pair.sh",
                      loaded)
        self.assertIn("run_privileged_bounded 960 tests/tools/qualify-resource-pressure.sh",
                      loaded)
        self.assertNotIn('dmsetup remove --force', preflight)
        self.assertIn('dmsetup remove --retry "$DMNAME"', pair)
        self.assertIn('open_before_remove="$(dm_open_count)"', pair)
        self.assertIn('open_after_remove="$(dm_open_count)"', pair)
        self.assertIn("wait_for_retired_dm_holder_release", pair)
        self.assertIn("retired owned DM holder did not settle", pair)
        self.assertIn("unexpected holder appeared after owned DM removal", pair)
        self.assertIn("remove_owned_ram_config", pair)
        self.assertIn("owned RAM block device did not settle after power-off", pair)
        self.assertIn("settle_udev", pair)
        self.assertNotIn('dmsetup remove --force', pair)

    def test_loaded_maximum_capacity_boundary_probe_is_owned_and_bounded(self):
        loaded = (ROOT / "tests/tools/test-loaded.sh").read_text()
        deploy = (ROOT / "tests/tools/deploy-nullblk.sh").read_text()
        self.assertIn('--validated-source "$tested_source" --max-boundary-probe', loaded)
        self.assertLess(
            loaded.index("--max-boundary-probe"),
            loaded.index("START_LOADED_OWNED_NULLBLK_SMOKE"))
        sizing_start = deploy.index("NULLBLK_SIZE_MIB=64")
        sizing_end = deploy.index("\nfi", sizing_start)
        sizing = deploy[sizing_start:sizing_end]
        self.assertIn("if (( MAX_BOUNDARY_PROBE )); then", sizing)
        self.assertIn("NULLBLK_SIZE_MIB=16383", sizing)

        capacity_start = deploy.index(
            "if (( MAX_BOUNDARY_PROBE )); then\n\tMAX_LOGICAL_PAGES=3727616")
        capacity_end = deploy.index("\n\texit 0\nfi", capacity_start)
        capacity = deploy[capacity_start:capacity_end]
        for evidence in (
                "MAX_LOGICAL_PAGES=3727616",
                "MAX_LOGICAL_SECTORS=29820928",
                "MAX_LOGICAL_BYTES=15268315136",
                "EXPECTED_PHYSICAL_BLOCKS=4194048",
                "EXPECTED_SEGMENTS=16383",
                "blockdev --getsize64 \"/dev/mapper/$DMNAME\"",
                "logical_write physical_write physical_write_reqs",
                "physical_read physical_read_reqs",
                "capacity_logical_read_bytes=\"$(status_u64 \"$capacity_status\" logical_read)\"",
                "[[ \"$lower_stats_after\" == \"$lower_stats_before\" ]]",
                '"$ORACLE" "/dev/mapper/$DMNAME" --maximum-capacity-boundary "$UUID"',
                "boundary_logical_write_bytes == 8192",
                "boundary_logical_read_bytes >= 8192",
                "boundary_target_read_bytes == boundary_lower_read_bytes",
                "boundary_target_write_bytes == boundary_lower_write_bytes",
                'boundary_failed_count="$(status_u64 "$capacity_status_after_io" failed)"',
                "boundary_failed_count == 0",
                "dmsetup remove --retry \"$DMNAME\"",
                "PASS_LOADED_MAXIMUM_CAPACITY="):
            self.assertIn(evidence, capacity)
        self.assertNotIn("logical_read; do", capacity)
        for forbidden in ("mkswap", "swapon", "swapoff", "dd "):
            self.assertNotIn(forbidden, capacity)
        roundtrip = (ROOT / "tests/tools/device-roundtrip.c").read_text()
        self.assertIn('"--maximum-capacity-boundary"', roundtrip)
        self.assertIn("MAX_CAPACITY_LOGICAL_PAGES = 3727616U", roundtrip)
        self.assertIn(
            "(uint64_t)MAX_CAPACITY_LOGICAL_PAGES * PAGE", roundtrip)
        self.assertNotIn("UINT64_C(15269363712)", roundtrip)
        self.assertIn("maximum_capacity_boundary_roundtrip", roundtrip)
        self.assertIn("verify_dm_uuid_exact", roundtrip)

    def test_loaded_constructor_failure_matrix_is_nullblk_only_and_mandatory(self):
        ctor = body("swapz_ctr")
        cleanup = body("swapz_free")
        deploy = (ROOT / "tests/tools/deploy-nullblk.sh").read_text()
        runner = (ROOT / "tests/tools/run-tests.py").read_text()

        self.assertIn("module_param_named(test_fail_constructor_stage", DM)
        self.assertIn("swapz_test_fail_constructor_stage, uint, 0444", DM)
        self.assertIn("module_param_cb(test_fail_constructor_hits", DM)
        constructor_injector = body("swapz_constructor_test_should_fail")
        self.assertIn(
            "atomic_inc(&swapz_test_fail_constructor_hits)",
            constructor_injector)
        self.assertIn(
            "Constructor fault injection is restricted to null_blk", ctor)
        self.assertIn("swapz_test_fail_constructor_stage >", ctor)
        self.assertIn(
            "SWAPZ_CONSTRUCTOR_FAIL_AFTER_PREPARATION_WORKQUEUE", ctor)
        for stage in (
                "SWAPZ_CONSTRUCTOR_FAIL_AFTER_BACKING",
                "SWAPZ_CONSTRUCTOR_FAIL_AFTER_IO_CLIENT",
                "SWAPZ_CONSTRUCTOR_FAIL_AFTER_AUTHORITY",
                "SWAPZ_CONSTRUCTOR_FAIL_AFTER_CORE_SCRATCH",
                "SWAPZ_CONSTRUCTOR_FAIL_AFTER_READ_SLOTS",
                "SWAPZ_CONSTRUCTOR_FAIL_AFTER_WORKQUEUE",
                "SWAPZ_CONSTRUCTOR_FAIL_AFTER_PREPARATION_SCRATCH",
                "SWAPZ_CONSTRUCTOR_FAIL_AFTER_PREPARATION_WORKQUEUE"):
            self.assertIn(stage, ctor)
        self.assertIn("swapz_free(ctx)", ctor)
        for release in (
                "destroy_workqueue(ctx->preparation_workqueue)",
                "destroy_workqueue(ctx->workqueue)",
                "dm_io_client_destroy(ctx->io_client)",
                "dm_put_device(ctx->target, ctx->backing)",
                "kvfree(ctx->maps)",
                "kfree(ctx)"):
            self.assertIn(release, cleanup)

        self.assertIn("START_LOADED_CONSTRUCTOR_FAILURE_CLEANUP", deploy)
        self.assertIn("for constructor_stage in {1..8}; do", deploy)
        self.assertIn(
            'insmod "$MODULE" test_fail_constructor_stage="$constructor_stage"',
            deploy)
        self.assertIn(
            '[[ -z "$(ls -A "/sys/block/$DISK/holders" 2>/dev/null)" ]]',
            deploy)
        self.assertIn(
            '[[ "$constructor_lower_after" == "$constructor_lower_before" ]]',
            deploy)
        self.assertIn("parameters/test_fail_constructor_stage", deploy)
        self.assertIn("parameters/test_fail_constructor_hits", deploy)
        self.assertIn('"$constructor_hits" == 1', deploy)
        self.assertIn("rmmod dm_swapz ||", deploy)
        self.assertIn(
            "PASS_LOADED_CONSTRUCTOR_FAILURE_CLEANUP=stages:8 lower_io_delta:0",
            deploy)
        self.assertIn('"constructor_cleanup": re.compile(', runner)
        self.assertIn(
            "constructor_cleanup_stages != 8 or "
            "constructor_cleanup_lower_io_delta != 0",
            runner)

    def test_dkms_sandbox_does_not_depend_on_host_module_state(self):
        package = (ROOT / "packaging/package-dkms.sh").read_text()
        self.assertIn(
            'if [[ -z "$test_root" && "$action" == uninstall ]] &&',
            package)
        self.assertIn(
            '[[ -e /sys/module/dm_swapz || -e /sys/module/dm-swapz ]]',
            package)
        self.assertIn(
            'BLOCKED: loaded module; refusing DKMS removal',
            package)

    def test_owned_nullblk_smoke_qualifies_retained_synthetic_faults(self):
        deploy = (ROOT / "tests/tools/deploy-nullblk.sh").read_text()
        # These are deliberately pre-submission injections on the already
        # authenticated RAM null_blk lower, not claims about torn/device faults.
        self.assertIn('echo 2 > "$CONFIG/queue_mode"', deploy)
        self.assertIn('echo 1 > "$CONFIG/submit_queues"', deploy)
        self.assertIn('echo 1 > "$CONFIG/hw_queue_depth"', deploy)
        self.assertIn("PASS_RETAINED_SYNTHETIC_WRITE_FAULT=", deploy)
        self.assertIn("PASS_RETAINED_SYNTHETIC_FLUSH_FAULT=", deploy)
        self.assertIn('--table "0 32768 swapz $LOWER 0 64 1 2 0 1 1 2"', deploy)
        self.assertIn('--table "0 32768 swapz $LOWER 0 64 1 2 1 1 0 2"', deploy)
        self.assertIn('status_u64 "$write_fault_status_before" retain_ms', deploy)
        self.assertIn('status_u64 "$flush_fault_status_before" retain_ms', deploy)
        self.assertIn('write_fault_lower_after[6] == write_fault_lower_before[6]',
                      deploy)
        self.assertIn('status_u64 "$write_fault_status_after" write_fault_injected',
                      deploy)
        self.assertIn('status_u64 "$flush_fault_status_after" flush_injected',
                      deploy)
        self.assertIn('status_u64 "$flush_fault_status_after" flush_err', deploy)
        self.assertIn('flush_fault_lower_after[6] > flush_fault_lower_before[6]',
                      deploy)
        self.assertIn('if timeout --signal=TERM --kill-after=5s 20s dd', deploy)
        self.assertIn('swapz_verify_owned_dm_node() {', deploy)
        self.assertIn('stat -Lc \'%t:%T\' "$mapper_node"', deploy)
        self.assertIn('sysfs_device="/sys/dev/block/$node_dev/dm"', deploy)
        self.assertIn('"$(cat "$sysfs_device/uuid")" == "$UUID"', deploy)
        self.assertIn('"$(cat "$sysfs_device/name")" == "$DMNAME"', deploy)
        self.assertGreaterEqual(deploy.count('swapz_verify_owned_dm_node\n'), 7)
        self.assertLess(deploy.index('swapz_verify_owned_dm_node\n',
                                     deploy.index('START_LOADED_RETAINED_WRITE_FAULT')),
                        deploy.index('write_fault_status_before='))
        self.assertIn('write_fault_unexpected_status="$(dmsetup status "$DMNAME")"',
                      deploy)
        self.assertIn('status_u64 "$write_fault_unexpected_status" write_fault_calls',
                      deploy)
        self.assertIn('status_u64 "$write_fault_unexpected_status" write_fault_injected',
                      deploy)
        self.assertIn("PASS_LOADED_ORACLE_PROFILE=", deploy)
        self.assertIn("raw_writes == 64", deploy)
        self.assertIn("flush_ok == flush_calls", deploy)
        self.assertIn("START_LOADED_LIVE_GC", deploy)
        self.assertIn("--gc-stress 5", deploy)
        self.assertIn("gc_victims >= 2", deploy)
        self.assertIn("gc_rotations == gc_victims", deploy)
        self.assertIn("gc_victim != gc_destination", deploy)
        self.assertIn("PASS_LOADED_LIVE_GC=", deploy)
        self.assertIn("PASS_LOADED_GC_PRESSURE=", deploy)
        self.assertIn("PASS_LOADED_DISCARD_TRIM=", deploy)
        self.assertIn("--discard-pages 0 256", deploy)
        self.assertIn("--raw-write-series 4096", deploy)
        self.assertIn("trim_reuse_delta >= 1", deploy)
        self.assertIn('dmsetup remove --retry "$DMNAME"', deploy)
        self.assertIn("trim_open_before_remove=", deploy)
        self.assertIn("trim_open_after_remove=", deploy)
        self.assertIn("timeout --signal=TERM --kill-after=2s 10s", deploy)
        self.assertNotIn('dmsetup remove --force "$DMNAME"', deploy)
        self.assertIn("PASS_LOADED_PACKED_PLACEMENT=", deploy)
        self.assertNotIn('insmod "$MODULE" packed_placement=1', deploy)
        self.assertIn("packed_holes == 0 && packed_splits == 0", deploy)
        self.assertIn("tail_waste_fg == alignment_hole_fg", deploy)
        self.assertIn("tail_waste_gc == alignment_hole_gc", deploy)
        loaded = (ROOT / "tests/tools/test-loaded.sh").read_text()
        pair = (ROOT / "tests/tools/benchmark-owned-pair.sh").read_text()
        runner = (ROOT / "tests/tools/run-tests.py").read_text()
        self.assertNotIn("START_PACKED_PLACEMENT_REGIME=", loaded)
        self.assertNotIn("START_PACKED_PLACEMENT_AB=", loaded)
        self.assertNotIn("placement_modes=", loaded)
        self.assertNotIn("--packed-placement", pair)
        self.assertNotIn("PACKED_PLACEMENT", pair)
        self.assertNotIn("packed_placement_ab_verdict", runner)
        self.assertIn("GC_PRESSURE_ROUND=", (ROOT / "tests/tools/device-roundtrip.c").read_text())
        self.assertIn("START_LOADED_SUSPEND_DRAIN", deploy)
        self.assertIn('--table "0 32768 swapz $LOWER 0 64 1 2 0 1 0 64"', deploy)
        self.assertIn("SWAPZ_NULLBLK_TEST_MAX_RETAIN_MS 64U", DM)
        self.assertIn("SWAPZ_MAX_RETAIN_MS 4U", DM)
        self.assertIn("timer_arms > lifecycle_windows", deploy)
        self.assertIn('while kill -0 "$writer_pid" 2>/dev/null', deploy)
        self.assertNotIn("for i in {1..400}", deploy)
        self.assertLess(deploy.index('>"$SESSION/suspend-writer.log" 2>&1 &'),
                        deploy.index('while kill -0 "$writer_pid" 2>/dev/null'))
        self.assertIn('dmsetup suspend "$DMNAME"', deploy)
        self.assertIn('dmsetup resume "$DMNAME"', deploy)
        self.assertIn("observed_open:$open_window", deploy)
        self.assertIn("lifecycle_failed == 0", deploy)
        self.assertIn("PASS_LOADED_SUSPEND_DRAIN=", deploy)
        self.assertNotIn("shutdown_after > shutdown_before", deploy)
        self.assertIn("SUSPENDED=0", deploy)
        self.assertNotIn("dmsetup remove -f", deploy)
        self.assertNotIn("dmsetup remove --force", deploy)
        oracle = (ROOT / "tests/tools/device-roundtrip.c").read_text()
        self.assertIn("--write-series", oracle)
        self.assertIn("--verify-series", oracle)
        self.assertIn("--raw-write-series", oracle)
        self.assertIn("--raw-verify-series", oracle)
        self.assertIn("--discard-pages", oracle)
        self.assertIn("BLKDISCARD", oracle)
        self.assertIn("--gc-stress", oracle)
        self.assertIn("GC_PAGES = 4096", oracle)
        self.assertIn("gc_expected_round", oracle)
        self.assertIn("(page % 256U) < round", oracle)
        self.assertIn("offset < rounds - 1U ? offset : rounds - 1U", oracle)
        self.assertIn("LIVE_GC_EVIDENCE=", deploy)
        self.assertIn("dead_segment_reuses", deploy)
        self.assertIn("gc_no_headroom_skips", deploy)
        self.assertIn("open_flags &= ~O_SYNC", oracle)
        self.assertIn('const char *prefix = "/dev/mapper/swapz-demo-"', oracle)
        self.assertNotIn("tests/runtime/write-fault.sh", deploy)
        self.assertNotIn("tests/runtime/read-fault.sh", deploy)

    def test_cpu_and_cache_optimization_contracts(self):
        engine = (ROOT / "src/kernel/engine.c").read_text()
        engine_h = (ROOT / "src/kernel/engine.h").read_text()
        authority = (ROOT / "src/kernel/authority.c").read_text()
        authority_h = (ROOT / "src/kernel/authority.h").read_text()
        codec = (ROOT / "src/kernel/codec.c").read_text()
        predictor_sse2 = (ROOT / "src/kernel/predictor-sse2.c").read_text()
        predictor_qualification = (
            ROOT / "tests/runtime/native/codec/predictor-qualification.c"
        ).read_text()
        authority_benchmark = (
            ROOT / "tests/runtime/native/mapping/authority-throughput.c"
        ).read_text()
        producer = body("swapz_preparation_worker")
        accept = body("swapz_accept_write")
        compressor = body("swapz_compress_page")
        read = source_body("swapz_engine_read_page", engine)
        finish = source_body("swapz_finish", authority)
        gc_relocate = body("swapz_gc_relocate_one")
        gc_choose = body("swapz_gc_choose_victim")
        gc_sort = body("swapz_gc_sort")
        gc_commit = source_body("swapz_gc_commit_rotation", authority)
        inflight_touch = body("swapz_inflight_run_touches_logical")
        parallel_extent = body("swapz_parallel_read_extent")
        validate = source_body("swapz_validate", codec)
        metadata_validate = source_body("swapz_validate_metadata_crc", codec)
        append_crc = source_body("swapz_append_crc", codec)
        append_page = source_body("swapz_append_page", engine)
        stage_policy = source_body("swapz_stage_policy", authority)
        active = source_body("swapz_is_active", authority)
        complete_run = source_body("swapz_engine_complete_batched_run", engine)

        predictor_avx2 = (
            ROOT / "src/kernel/predictor-avx2.c"
        ).read_text()
        predictor_avx512 = (
            ROOT / "src/kernel/predictor-avx512.c"
        ).read_text()
        predictor_neon = (
            ROOT / "src/kernel/predictor-neon.c"
        ).read_text()
        predictor_dispatch = (
            ROOT / "src/kernel/predictor.c"
        ).read_text()

        # SIMD inverse scans keep their cross-vector carry in SIMD registers.
        # The local prefix/total is independent of the incoming base, allowing
        # OoO execution to overlap shuffle work across the two-way unroll.
        self.assertIn('shufpd $1', predictor_sse2)
        self.assertIn('pslldq $8', predictor_sse2)
        self.assertIn('pshufd $0xee', predictor_sse2)
        sse2_inverse = source_body("swapz_unpredict_delta64_sse2",
                                   predictor_sse2)
        self.assertIn("swapz_u32 offset = 0", sse2_inverse)
        self.assertIn("step_pair = step0 + step1", sse2_inverse)
        self.assertIn("base += step_pair", sse2_inverse)
        self.assertNotIn("base += step0", sse2_inverse)
        self.assertNotIn("previous = prefix.u64[1]", predictor_sse2)
        self.assertIn("#ifndef __KERNEL__", predictor_sse2)
        self.assertIn("swapz_predict_delta64_sse2_baseline", predictor_sse2)
        sse2_forward = source_body("swapz_predict_delta64_sse2", predictor_sse2)
        sse2_baseline = source_body(
            "swapz_predict_delta64_sse2_baseline", predictor_sse2)
        self.assertIn("2U * sizeof(swapz_u64x2)", sse2_forward)
        self.assertNotIn("2U * sizeof(swapz_u64x2)", sse2_baseline)
        self.assertNotIn("swapz_predict_delta64_sse2_baseline",
                         predictor_dispatch)
        self.assertIn("benchmark_sse2_forward_ab(count, sse2_forward_ab)",
                      predictor_qualification)
        self.assertIn("SAME_HOST_NATIVE_BASELINE_VS_PROMOTED_PRODUCTION",
                      predictor_qualification)
        self.assertNotIn(
            "input + offset - SWAPZ_PREDICTOR_U64_BYTES", predictor_sse2)

        avx2_inverse = source_body("swapz_unpredict_delta64_avx2",
                                   predictor_avx2)
        self.assertIn("swapz_u32 offset = 0", avx2_inverse)
        self.assertIn('vpermq $0xff', avx2_inverse)
        self.assertIn("step_pair = step0 + step1", avx2_inverse)
        self.assertIn("base += step_pair", avx2_inverse)
        self.assertNotIn("base += step0", avx2_inverse)
        self.assertNotIn("previous = prefix.u64[3]", predictor_avx2)

        avx512_forward = source_body(
            "swapz_predict_delta64_avx512", predictor_avx512)
        self.assertIn("previous_block = { 0 }", avx512_forward)
        self.assertIn("swapz_u32 offset = 0", avx512_forward)
        self.assertIn("2U * sizeof(swapz_u64x8)", avx512_forward)
        self.assertIn('valignq $7', avx512_forward)
        self.assertNotIn("swapz_predictor_store64(", avx512_forward)
        self.assertIn("2U * sizeof(swapz_u64x8)", predictor_avx512)
        avx512_inverse = source_body("swapz_unpredict_delta64_avx512",
                                     predictor_avx512)
        self.assertIn("swapz_u32 offset = 0", avx512_inverse)
        self.assertIn("step_pair = step0 + step1", avx512_inverse)
        self.assertIn("base += step_pair", avx512_inverse)
        self.assertNotIn("base += step0", avx512_inverse)
        self.assertNotIn("previous = prefix[7]", predictor_avx512)
        self.assertIn(
            "static_call_update(swapz_predictor_inverse_call, swapz_unpredict_avx2)",
            predictor_dispatch)
        self.assertIn(
            "swapz_unpredict_impl = swapz_unpredict_delta64_avx2",
            predictor_dispatch)
        neon_forward = source_body("swapz_predict_delta64_neon", predictor_neon)
        neon_inverse = source_body("swapz_unpredict_delta64_neon", predictor_neon)
        for neon_body in (neon_forward, neon_inverse):
            self.assertIn("swapz_u32 offset = 0", neon_body)
            self.assertNotIn("2U * sizeof(swapz_u64x2)", neon_body)
        # Forward: one 64-byte line per iteration, EXT predecessors from
        # registers (unaligned predecessor reloads measured slower).
        self.assertIn("4U * sizeof(swapz_u64x2)", neon_forward)
        self.assertIn("previous = { 0ULL, 0ULL }", neon_forward)
        self.assertIn('ext %0.16b', neon_forward)
        # Inverse: 16-word ZIP column scan; one carried add per 128 bytes.
        self.assertIn("8U * sizeof(swapz_u64x2)", neon_inverse)
        self.assertIn("base = { 0ULL, 0ULL }", neon_inverse)
        self.assertIn('"zip1 %0.2d, %1.2d, %2.2d"', predictor_neon)
        self.assertIn('"zip2 %0.2d, %1.2d, %2.2d"', predictor_neon)
        self.assertIn("SWAPZ_NEON_ZIP1(c0, q0, q4);", neon_inverse)
        self.assertIn('ext %0.16b', neon_inverse)
        self.assertIn('addp %0.2d', neon_inverse)
        self.assertIn("base += total;", neon_inverse)
        self.assertEqual(neon_inverse.count("base +="), 1)
        self.assertNotIn("ld4", predictor_neon)
        self.assertNotIn("dup %0.2d", neon_inverse)

        # Validated metadata-cache bytes bypass full swapz_validate(), but a
        # sequence mismatch is rejected before any lower payload read.
        self.assertIn("metadata_already_validated", read)
        self.assertIn("swapz_lookup_validated_descriptor(", read)
        self.assertIn("&peek, NULL);", read)
        self.assertIn("swapz_extent_sequence_lookup(", read)
        self.assertIn("metadata_sequence != expected_sequence", read)
        self.assertLess(read.index("metadata_sequence != expected_sequence"),
                        read.index("if (last >= start)"))
        self.assertIn("copy_mask = extent_mask &", read)
        self.assertIn("coalesced_mask &= (swapz_u8)~extent_mask", read)
        self.assertIn("copy_mask = block_mask &",
                      source_body("swapz_read_extent_lru_commit", engine))
        prime = source_body("swapz_engine_prime_read_slot", engine)
        self.assertIn("(swapz_u8)~master->read_coalesced_block_mask", prime)
        self.assertIn("copy_mask = extent_mask & (swapz_u8)~mask", prime)

        # Batched production planning consumes the uniqueness proof it already
        # paid for; the public planner still performs duplicate protection.
        self.assertIn("logical_pages_unique", engine)
        prepare = source_body("swapz_engine_prepare_batched_run", engine)
        self.assertIn("&extent_count, 1, 1,", prepare)
        public_plan = source_body("swapz_engine_plan_bounded", engine)
        self.assertIn("extent_count, 0, 0, 0", public_plan)
        planner = source_body("swapz_engine_plan_bounded_policy", engine)
        self.assertNotIn("cached_takes", planner)
        self.assertNotIn("cached_reads", planner)
        self.assertIn("swapz_u8 previous_take = 0", planner)
        self.assertIn("take == previous_take", planner)
        self.assertIn("swapz_u32 objectives[SWAPZ_MAX_RECORDS + 1U]", planner)
        self.assertNotIn("selected_class[", planner)
        self.assertNotIn("selected_count[", planner)
        self.assertIn("classes[index] = blocks", planner)
        self.assertIn("records_per_extent[index] = take", planner)
        self.assertEqual(planner.count("swapz_fit_count("), 2)
        boundary_recompute = planner.rindex("swapz_fit_count(")
        self.assertGreater(
            boundary_recompute,
            planner.index("if (prefer_large_ties &&"))
        fit = source_body("swapz_fit_count", engine)
        self.assertIn("if (blocks == 2U)", fit)
        self.assertIn("1U + (payload_start > SWAPZ_BLOCK_BYTES)", fit)
        batched_write = source_body(
            "swapz_engine_write_window_batched_read_cap", engine)
        self.assertIn("run.bytes = e->bulk_scratch", batched_write)
        self.assertIn("for (index = count; index > 0; --index)", batched_write)
        self.assertNotIn("run = (struct swapz_io_run)", batched_write)

        # Publication preflight is local/bounded and does not mutate+restore
        # global GC arrays or apply per-record GC transitions in phase 2.
        self.assertIn("struct swapz_finish_extent_delta", authority_h)
        self.assertIn("finish_segment_deltas[SWAPZ_MAX_RECORDS]", authority_h)
        self.assertNotIn("swapz_gc_account_batch_preflight", authority)
        self.assertIn("swapz_finish_extent_delta_get", finish)
        self.assertIn("swapz_finish_segment_delta_get", finish)
        self.assertNotIn("swapz_gc_account_transition_apply", finish)
        self.assertNotIn("swapz_gc_account_costs(a, old", finish)
        self.assertIn("swapz_gc_live_byte_cost(old)", finish)
        self.assertEqual(
            authority.count("for (index = *count; index > 0; --index)"), 2)
        self.assertIn(
            "finish_extent_deltas[index - 1U].start_block == start_block",
            authority)
        self.assertIn(
            "finish_segment_deltas[index - 1U].segment == segment",
            authority)

        # Cheap rejection must remain fail-closed: map/type checks may precede
        # dependency scans, but every mapped candidate still scans dependencies.
        self.assertLess(parallel_extent.index("bio_op(bio) != REQ_OP_READ"),
                        parallel_extent.index("swapz_read_can_parallel"))
        self.assertLess(parallel_extent.index("swapz_parallel_read_extent_mapped"),
                        parallel_extent.index("swapz_read_can_parallel"))
        self.assertIn(
            "ctx->authority.batch_pending != run->extent_count",
            inflight_touch)
        self.assertIn("return false;", inflight_touch)
        self.assertIn("if (!cached_metadata && engine->read_metadata_cache)", read)
        self.assertIn("if (engine->read_metadata_cache)", read)

        # Packed payloads are stored back-to-back from bytes_total downward.
        # Exact adjacency plus bounded 16-bit fields makes the removed explicit
        # bytes_total subtraction checks redundant without weakening validation.
        self.assertIn("start + length != previous_end", validate)
        self.assertNotIn("start > bytes_total", validate)
        self.assertNotIn("length > bytes_total - start", validate)

        # Publication authenticates header/descriptor bytes once, then folds
        # descriptor adjacency/identity into the existing authoritative pass.
        self.assertIn("swapz_validate_metadata_crc(image", finish)
        self.assertNotIn("swapz_validate(image", finish)
        self.assertIn("decoded.payload_offset < metadata_end", finish)
        self.assertIn("previous_end = decoded.payload_offset", finish)
        self.assertIn("swapz_record_logical_le", validate)
        self.assertNotIn("swapz_record_logical_le", metadata_validate)

        # Window-wide uniqueness may skip only redundant quadratic scans.
        # Generic codec/stage entry points retain duplicate defense, while
        # range/generation checks remain in the unique staging policy.
        self.assertIn("if (!logical_page_unique)", append_crc)
        self.assertIn("swapz_append_prehashed_encoded_unique", append_page)
        self.assertIn("swapz_stage_batch_unique", prepare)
        self.assertIn("page >= a->logical_pages", stage_policy)
        self.assertIn("generation == ~(swapz_u32)0", stage_policy)
        self.assertIn("if (!logical_pages_unique)", stage_policy)

        # A resumed batch may finish through only the authenticated
        # authority-owned snapshot; external handles still compare records.
        self.assertIn("tx == &a->active_tx", active)
        self.assertIn("active_tx = &e->authority->active_tx", complete_run)
        self.assertLess(complete_run.index("swapz_batch_resume"),
                        complete_run.index("active_tx = &e->authority->active_tx"))
        self.assertIn("e->authority, active_tx", complete_run)
        self.assertIn(r'\"validate64_full\"', authority_benchmark)
        self.assertIn(r'\"validate64_metadata_crc\"', authority_benchmark)
        self.assertIn(r'\"append64_checked\"', authority_benchmark)
        self.assertIn(r'\"append64_unique\"', authority_benchmark)

        # First-pass LZ4 can be qualified at 1/2/3/4 without changing the
        # delta64 rescue LZ4 setting. Zero recognition stays inside the shared
        # compressor so producer and ordered paths cannot diverge.
        self.assertNotIn("module_param_named(lz4_acceleration,", DM)
        predictor_header = (ROOT / "src/kernel/predictor.h").read_text()
        self.assertIn("SWAPZ_LZ4_ORDINARY_ACCELERATION_DEFAULT 1U",
                      predictor_header)
        self.assertIn("SWAPZ_LZ4_DELTA64_ACCELERATION_DEFAULT 4U",
                      predictor_header)
        self.assertNotIn("#define SWAPZ_ORDINARY_LZ4_ACCELERATION", DM)
        self.assertNotIn("ctx->lz4_acceleration", DM)
        self.assertIn("SWAPZ_LZ4_ORDINARY_ACCELERATION_DEFAULT", compressor)
        self.assertIn("ctx->delta64_lz4_acceleration", compressor)
        high_score_start = compressor.index("if (high_score)")
        ordinary_start = compressor.index("\nordinary:")
        high_score = compressor[high_score_start:ordinary_start]
        self.assertIn(
            "LZ4_compress_fast(\n\t\t\t\ttransform_scratch, output,",
            high_score)
        self.assertNotIn("memcpy(output, candidate_output", high_score)
        self.assertIn("memcpy(candidate_output, output, (size_t)candidate)",
                      high_score)
        self.assertIn("prepared->length = swapz_compress_prepared_page(", producer)
        self.assertIn("length = swapz_compress_page(", accept)
        self.assertIn("prepared->length > 0 && !prepared->zero", producer)
        self.assertIn("if (!prepared->zero)", accept)
        self.assertIn("prepared_async ? entry->prepared_page->zero : inline_zero",
                      accept)
        self.assertIn("length > 0 && !inline_zero", accept)

        # Production transform telemetry includes the dispatched SIMD wrapper;
        # native qualification continues to report the raw backend separately.
        self.assertIn("stats->transform_wall_ns", compressor)
        self.assertIn("stats->transform_calls++", compressor)
        self.assertIn("delta64_transform_wall_ns=%llu", body("swapz_status"))
        self.assertIn(r'\"lz4_acceleration_sweep\"', predictor_qualification)
        self.assertIn("1U, 2U, 3U, 4U", predictor_qualification)
        self.assertIn("planner_length_totals(", predictor_qualification)
        self.assertIn("LZ4_decompress_safe(", predictor_qualification)

        # ID63 may actively merge 2..8 exact contiguous missing ranges while
        # the full-extent 3+ counters remain conservative opportunity evidence.
        batch = body("swapz_try_parallel_read_batch")
        self.assertIn("swapz_adjacent_extent_chain_candidate(", batch)
        self.assertIn("swapz_engine_coalesce_read_chain(", batch)
        self.assertIn("parallel_read_adjacent_chain_3plus++", batch)
        self.assertIn("parallel_read_adjacent_chain_extent_max=%llu",
                      body("swapz_status"))
        self.assertIn("parallel_read_adjacent_chain_blocks_max=%llu",
                      body("swapz_status"))

        # Reuse already verified survivor CRCs and preserve circular allocator
        # fairness across successful GC rotations and equal-cost victim ties.
        self.assertIn("read_validated_payload_crc32c", engine_h)
        self.assertIn(
            "engine->read_validated_payload_crc32c = peek.payload_crc32c", read)
        self.assertIn("ctx->engine.read_validated_payload_crc32c", gc_relocate)
        self.assertIn("start_probe = ctx->authority.next_segment_probe", gc_choose)
        self.assertIn("(start_probe + scan) % ctx->segment_count", gc_choose)
        self.assertNotIn("next_segment_probe = (victim + 1U)", gc_commit)
        self.assertIn("swapz_window_uniform_compressed", gc_sort)

        pair = (ROOT / "tests/tools/benchmark-owned-pair.sh").read_text()
        loaded = (ROOT / "tests/tools/test-loaded.sh").read_text()
        replay = (ROOT / "tests/runtime/benchmark/io-replay.py").read_text()
        runner = (ROOT / "tests/tools/run-tests.py").read_text()
        self.assertNotIn("--lz4-acceleration", pair)
        self.assertIn("lz4_acceleration=1", pair)
        self.assertNotIn('for acceleration_mode in "${confirmation_modes[@]}"', loaded)
        self.assertNotIn("START_LZ4_ACCELERATION=", loaded)
        self.assertIn('"lz4_acceleration"', replay)
        self.assertIn("delta64_transform_wall_ns", replay)
        self.assertIn("kernel_read_before = kernel_read_snapshot(path, identity)",
                      replay)
        self.assertIn("kernel_read_after = kernel_read_snapshot(path, identity)",
                      replay)
        self.assertIn('"kernel_read_path": kernel_read_delta(', replay)
        self.assertIn("LZ4_ACCELERATIONS = (1, 2, 3, 4)", runner)
        self.assertIn("PASS_LZ4_ACCELERATION_AB", runner)
        self.assertIn('matched_value_pairs(\n            sessions, "lz4_acceleration", 1, 4)', runner)

    def test_modern_storage_envelopes_use_native_replay_helper(self):
        pair = (ROOT / "tests/tools/benchmark-owned-pair.sh").read_text()
        replay = (ROOT / "tests/runtime/benchmark/io-replay.py").read_text()
        helper = (ROOT / "tests/runtime/benchmark/io-replay-native.c").read_text()
        suites = (ROOT / "tests/suites/Makefile").read_text()
        runner = (ROOT / "tests/tools/run-tests.py").read_text()

        self.assertIn("NATIVE_REPLAY=1", pair)
        self.assertIn('REPLAY_ARGS+=(--native-replay)', pair)
        self.assertIn("build/tests/native/io-replay-native", pair)
        self.assertIn('"replay_engine": "native-c" if args.native_replay', replay)
        self.assertIn("pass_fds=(fd, fixture_fd, plan.fileno(), result.fileno())",
                      replay)
        self.assertIn("native replay is restricted to unpaced qualification",
                      replay)
        self.assertIn("PR_SET_PDEATHSIG", helper)
        self.assertIn("pthread_barrier_wait(&ctx->wave_barrier)", helper)
        self.assertIn("fsync(ctx.device_fd)", helper)
        self.assertIn("io-replay-native_SRC := $(BENCHMARK)/io-replay-native.c",
                      suites)
        self.assertIn('off.get("replay_engine") != "native-c"', runner)

    def test_work_conserving_hand_width_is_bounded_nullblk_only(self):
        ctor = body("swapz_ctr")
        status = body("swapz_status")
        fast = (ROOT / "tests/tools/fast-test.py").read_text()
        pair = (ROOT / "tests/tools/benchmark-owned-pair.sh").read_text()
        loaded = (ROOT / "tests/tools/test-loaded.sh").read_text()
        runner = (ROOT / "tests/tools/run-tests.py").read_text()
        policy = (ROOT / "src/kernel/window-policy.h").read_text()
        makefile = (ROOT / "Makefile").read_text()
        self.assertIn("module_param_named(work_conserving_hand_records,", DM)
        self.assertIn("swapz_work_conserving_hand_records != 16U", ctor)
        self.assertIn("swapz_work_conserving_hand_records != 64U", ctor)
        self.assertIn(
            "nondefault hand threshold requires async_prepare=1 retain_ms>0",
            ctor)
        self.assertIn("nondefault hand threshold is restricted to null_blk", ctor)
        self.assertIn("ctx->work_conserving_hand_records", body("swapz_worker_pass"))
        self.assertIn("ctx->work_conserving_hand_records,", status)
        self.assertIn('default=int(os.environ.get("HAND_RECORDS", "8"))', fast)
        self.assertIn('choices=(8, 16, 64)', fast)
        self.assertIn('--hand-records', pair)
        self.assertIn('work_conserving_hand_records=$HAND_RECORDS', pair)
        self.assertIn("HAND_RECORDS=8|16|64", makefile)
        for retired_surface in (DM, policy, pair, fast, loaded, runner, makefile):
            self.assertNotIn("lone_raw", retired_surface)
            self.assertNotIn("LONE_RAW", retired_surface)

    def test_map_and_teardown_are_owned(self):
        admitted = body("swapz_map")
        drained = body("swapz_drain")
        self.assertIn("dm_per_bio_data(", admitted)
        self.assertIn("WQ_MEM_RECLAIM", body("swapz_ctr"))
        self.assertIn("drain_workqueue(ctx->workqueue)", drained)
        self.assertLess(drained.index("mod_delayed_work(ctx->workqueue"),
                        drained.index("flush_delayed_work(&ctx->worker)"))
        self.assertLess(drained.index("flush_delayed_work(&ctx->worker)"),
                        drained.index("drain_workqueue(ctx->workqueue)"))
        self.assertIn("cancel_delayed_work_sync(&ctx->worker)", body("swapz_free"))
        self.assertIn("destroy_workqueue(ctx->workqueue)", body("swapz_free"))
        self.assertLess(admitted.index("spin_lock_irqsave(&ctx->queue_lock"),
                        admitted.index("if (!ctx->accepting)"))
        self.assertLess(admitted.index("if (!ctx->accepting)"),
                        admitted.index("list_add_tail(&entry->list"))
        final_queue = admitted.index("queue_delayed_work(ctx->workqueue")
        final_unlock = admitted.index(
            "spin_unlock_irqrestore(&ctx->queue_lock, flags);", final_queue)
        submitter_call = admitted.rindex(
            "swapz_submitter_prepare_entry(ctx, entry")
        submitted = admitted.index("return DM_MAPIO_SUBMITTED")
        self.assertLess(final_queue, final_unlock)
        self.assertLess(final_unlock, submitter_call)
        self.assertLess(submitter_call, submitted)
        self.assertIn("return READ_ONCE(ctx->failed) ? DM_MAPIO_KILL : DM_MAPIO_REQUEUE;", admitted)
        self.assertIn("mod_delayed_work(ctx->workqueue, &ctx->worker, 0)", admitted)
        self.assertIn("flush_delayed_work(&ctx->worker)", drained)
        self.assertLess(drained.index("WRITE_ONCE(ctx->accepting, false)"),
                        drained.index("drain_workqueue(ctx->workqueue)"))
        self.assertIn("spin_lock_irqsave(&ctx->queue_lock", drained)
        self.assertIn(".postsuspend = swapz_drain", DM)
        self.assertNotIn(".presuspend = swapz_drain", DM)
        self.assertNotIn("drain_completed_bios", DM)
        self.assertNotIn("drain_endio_work", DM)
        self.assertNotIn("drain_active", DM)
        self.assertNotIn("usleep_range(", DM)



    def test_prepared_lz4_cost_reaches_the_single_owner_after_ready(self):
        import subprocess
        import tempfile

        compressor = body("swapz_compress_prepared_page")
        observer = body("swapz_observe_prepared_lz4_cost")
        for name in ("swapz_preparation_worker", "swapz_submitter_prepare_payload"):
            preparing = body(name)
            self.assertIn("prepared->length = swapz_compress_prepared_page(", preparing)
            self.assertLess(preparing.index("swapz_compress_prepared_page("),
                            preparing.index("swapz_preparation_publish_codec_result("))
        accept = body("swapz_accept_write")
        self.assertIn("swapz_observe_prepared_lz4_cost(ctx, prepared, prepared_state)",
                      accept)
        self.assertLess(accept.index("swapz_preparation_select_raw("),
                        accept.index("swapz_observe_prepared_lz4_cost("))
        # Execute the actual writer/consumer bodies. A poisoned unready page
        # catches reads of metadata that an optional producer may still mutate.
        states = re.search(r"enum swapz_preparation_state\s*\{.*?\};",
                           (ROOT / "src/kernel/preparation-slots.h").read_text(),
                           re.S).group(0)
        prefix = r'''
#define _GNU_SOURCE
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/resource.h>
#include <unistd.h>
#include "window-policy.h"
typedef uint64_t u64;
typedef unsigned char u8;
struct swapz_dm { u64 ordered_lz4_page_ewma_ns; };
struct swapz_delta64_stats { unsigned calls; };
struct swapz_prepared_page {
 u8 raw_bytes[4096], bytes[4096], encoding;
 bool zero;
 u64 lz4_wall_ns;
};
static struct swapz_dm ctx;
static struct swapz_prepared_page page;
static struct swapz_delta64_stats stats;
static u8 predictor[4096], candidate[4096], workmem[16];
static int selected_length;
static u64 charge;
static int swapz_compress_page(struct swapz_dm *c,const u8 *in,u8 *out,
 u8 *p,u8 *d,void *w,u64 *wall,u8 *encoding,
 struct swapz_delta64_stats *s,bool *zero) {
 assert(c==&ctx && in==page.raw_bytes && out==page.bytes);
 assert(p==predictor && d==candidate && w==workmem && s==&stats);
 *wall+=charge;*encoding=SWAPZ_ENCODING_LZ4;*zero=selected_length==16;
 memset(out,0x5a,32);s->calls++;return selected_length;
}
'''
        writer = "static int swapz_compress_prepared_page(\n" \
                 "struct swapz_dm *ctx, struct swapz_prepared_page *prepared,\n" \
                 "u8 *predictor_page, u8 *delta64_candidate_page, void *lz4_workmem,\n" \
                 "u64 *lz4_wall_ns, struct swapz_delta64_stats *delta64) {\n"
        reader = "static void swapz_observe_prepared_lz4_cost(\n" \
                 "struct swapz_dm *ctx, const struct swapz_prepared_page *prepared,\n" \
                 "int state) {\n"
        suffix = r'''
int main(void) {
 struct rlimit no_core={0,0};assert(setrlimit(RLIMIT_CORE,&no_core)==0);
 u64 wall=100000;
 selected_length=128;charge=1600;
 assert(swapz_compress_prepared_page(&ctx,&page,predictor,candidate,workmem,
        &wall,&stats)==128);
 assert(wall==101600 && page.lz4_wall_ns==1600 && !page.zero);
 swapz_observe_prepared_lz4_cost(&ctx,&page,SWAPZ_PREPARATION_READY_COMPRESSED);
 assert(ctx.ordered_lz4_page_ewma_ns==1600);
 selected_length=0;charge=800;
 assert(swapz_compress_prepared_page(&ctx,&page,predictor,candidate,workmem,
        &wall,&stats)==0);
 assert(page.lz4_wall_ns==800 && wall==102400);
 swapz_observe_prepared_lz4_cost(&ctx,&page,SWAPZ_PREPARATION_READY_RAW);
 assert(ctx.ordered_lz4_page_ewma_ns==1500);
 selected_length=16;charge=0;
 assert(swapz_compress_prepared_page(&ctx,&page,predictor,candidate,workmem,
        &wall,&stats)==16 && page.zero && page.lz4_wall_ns==0);
 swapz_observe_prepared_lz4_cost(&ctx,&page,SWAPZ_PREPARATION_READY_COMPRESSED);
 assert(ctx.ordered_lz4_page_ewma_ns==1500 && stats.calls==3);
 size_t granule=(size_t)sysconf(_SC_PAGESIZE);
 size_t bytes=(sizeof(struct swapz_prepared_page)+granule-1)/granule*granule;
 void *poison=mmap(NULL,bytes,PROT_NONE,MAP_ANONYMOUS|MAP_PRIVATE,-1,0);
 assert(poison!=MAP_FAILED);
 int invalid[]={SWAPZ_PREPARATION_EMPTY,SWAPZ_PREPARATION_PREPARING,
                SWAPZ_PREPARATION_RAW_SELECTED,SWAPZ_PREPARATION_ERROR};
 for(unsigned i=0;i<sizeof(invalid)/sizeof(invalid[0]);i++) {
  swapz_observe_prepared_lz4_cost(&ctx,poison,invalid[i]);
  assert(ctx.ordered_lz4_page_ewma_ns==1500);
 }
 assert(munmap(poison,bytes)==0);return 0;
}
'''
        guard = ("if (state != SWAPZ_PREPARATION_READY_COMPRESSED &&\n"
                 "\t    state != SWAPZ_PREPARATION_READY_RAW)\n\t\treturn;")
        self.assertIn(guard, observer)
        variants = [(compressor, observer, True),
                    (compressor.replace("*lz4_wall_ns - before",
                                        "*lz4_wall_ns - before + before"), observer, False),
                    (compressor, observer.replace(guard, "(void)state;"), False)]
        with tempfile.TemporaryDirectory(prefix="swapz-prepared-cost-") as temp:
            path = Path(temp)
            for compress_body, observe_body, passes in variants:
                (path / "probe.c").write_text(prefix + states + "\n" + writer +
                    compress_body + "}\n" + reader + observe_body + "}\n" + suffix)
                subprocess.run(["cc", "-std=c11", "-O2", "-Wall", "-Wextra",
                                "-Werror", "-I", str(ROOT / "src/kernel"),
                                str(path / "probe.c"), "-o", str(path / "probe")],
                               check=True, capture_output=True, text=True, timeout=15)
                result = subprocess.run([str(path / "probe")], capture_output=True,
                                        text=True, timeout=5)
                self.assertEqual(result.returncode == 0, passes,
                                 result.stdout + result.stderr)

    def test_snapshot_inputs_are_not_reported_as_direct_lz4(self):
        for name in ("swapz_preparation_worker", "swapz_submitter_prepare_payload"):
            preparing = body(name)
            self.assertIn("lane->mapped_snapshot_pages++", preparing)
            self.assertNotIn("direct_lz4_pages", preparing)
            self.assertIn("swapz_compress_prepared_page(", preparing)
        self.assertIn("ctx, prepared->raw_bytes, prepared->bytes",
                      body("swapz_compress_prepared_page"))
        status = body("swapz_status")
        self.assertIn("mapped_snapshot_input_pages=%llu", status)
        self.assertIn("prep->mapped_snapshot_pages + submitter->mapped_snapshot_pages", status)
        # This counter is the final argument in its DMEMIT chunk.
        self.assertRegex(status, r"ctx->ordered_direct_lz4_pages\s*\)")
        ordered = body("swapz_accept_write")
        force_raw = ordered.index("if (force_raw && bulk_raw_eligible)")
        direct = ordered.index("ctx->ordered_direct_lz4_pages++")
        self.assertGreater(direct, force_raw)
        self.assertLess(direct, ordered.index("length = swapz_compress_page(", force_raw))

    def test_submitter_preparation_is_bounded_and_owner_gated(self):
        mapper = body("swapz_map")
        claim = body("swapz_claim_submitter_preparation_locked")
        submitter = body("swapz_submitter_prepare_entry")
        payload = body("swapz_submitter_prepare_payload")
        ordered = body("swapz_worker_pass")
        ctor = body("swapz_ctr")
        drain = body("swapz_drain")
        freeing = body("swapz_free")
        status = body("swapz_status")
        replay = (ROOT / "tests/runtime/benchmark/io-replay.py").read_text()
        reporter = (ROOT / "tests/tools/run-tests.py").read_text()

        self.assertRegex(
            DM, r"static\s+bool\s+swapz_submitter_prepare\s*=\s*true\s*;")
        self.assertIn(
            "module_param_named(submitter_prepare, swapz_submitter_prepare, bool, 0444)",
            DM)
        self.assertIn("#define SWAPZ_SUBMITTER_PREPARATION_LANES_MAX 8U", DM)
        self.assertIn(
            "ctx->submitter_prepare = ctx->async_prepare && swapz_submitter_prepare",
            ctor)
        self.assertIn("num_possible_cpus()", ctor)
        self.assertIn("SWAPZ_SUBMITTER_PREPARATION_LANES_MAX", ctor)
        self.assertIn("kvcalloc(ctx->submitter_lane_count", ctor)
        self.assertIn("lane->lz4_workmem = kvmalloc(LZ4_MEM_COMPRESS", ctor)

        self.assertIn(
            "swapz_preparation_claim_slot(&ctx->submitter_lane_free_mask)",
            claim)
        self.assertIn(
            "swapz_preparation_claim_slot(&ctx->preparation_free_mask)", claim)
        self.assertIn("refcount_set(&prepared->refs, 1)", claim)
        self.assertIn(
            "atomic_set(&entry->preparation_submitter_active, 1)", claim)
        # ID169: an active lower WRITE leaves preparation to the bounded
        # producer before any lane, slot or ownership state is touched.
        guard = claim.index("atomic_read(&ctx->lower_write_active)")
        self.assertLess(guard, claim.index("return -1;"))
        self.assertLess(guard, claim.index(
            "swapz_preparation_claim_slot(&ctx->submitter_lane_free_mask)"))
        self.assertLess(guard, claim.index("ctx->submitter_preparation_claims++"))
        for allocation in ("kmalloc(", "kzalloc(", "vzalloc(", "kvmalloc(",
                           "kvcalloc(", "mempool_alloc("):
            self.assertNotIn(allocation, claim)
            self.assertNotIn(allocation, submitter)
            self.assertNotIn(allocation, payload)

        self.assertLess(
            mapper.index("list_add_tail(&entry->list, &ctx->incoming)"),
            mapper.index("swapz_claim_submitter_preparation_locked(ctx, entry)"))
        self.assertRegex(
            mapper,
            r"if \(in_task\(\) && !irqs_disabled_flags\(flags\) &&\s*"
            r"!\(bio->bi_opf & \(REQ_PREFLUSH \| REQ_FUA\)\)\)")
        self.assertIn("if (submitter_lane < 0)", mapper)
        self.assertIn("swapz_submitter_prepare_entry(ctx, entry", mapper)
        self.assertLess(
            mapper.index("list_add_tail(&entry->list, &ctx->incoming)"),
            mapper.rindex("swapz_submitter_prepare_entry(ctx, entry"))
        # A submitter-owned descriptor must not wake the CPU-bound owner at
        # admission: that pass would only defer on the still-active head. The
        # admission wake chain is skipped and the submitter wakes after release.
        self.assertIn("if (submitter_lane >= 0) {", mapper,
                      "submitter-owned admission must skip the owner wake")
        skip_wake = mapper.index("if (submitter_lane >= 0) {")
        self.assertLess(skip_wake, mapper.index(
            "mod_delayed_work(ctx->workqueue, &ctx->worker, 0)"))
        self.assertLess(skip_wake, mapper.index(
            "queue_delayed_work(ctx->workqueue, &ctx->worker, 0)"))
        self.assertLess(skip_wake, mapper.index(
            "spin_unlock_irqrestore(&ctx->queue_lock, flags);\n"
            "\tif (ordered_owned && !submitter_dispatch)"))

        active_gate = re.search(
            r"atomic_read_acquire\(\s*&entry->preparation_submitter_active\s*\)",
            ordered)
        self.assertIsNotNone(active_gate)
        self.assertLess(
            active_gate.start(), ordered.index("swapz_process(ctx, entry->bio)"))
        self.assertIn("list_splice_init(&local, &ctx->incoming)", ordered)
        self.assertIn("ctx->submitter_owner_deferrals++", ordered)

        self.assertIn("complete_all(&entry->preparation_snapshot_ready)",
                      payload)
        self.assertIn("prepared->length = swapz_compress_prepared_page(", payload)
        self.assertIn("swapz_preparation_publish_codec_result(", payload)
        self.assertNotIn("preparation_submitter_active", payload)
        self.assertNotIn("_delayed_work(", payload)
        self.assertNotIn("swapz_preparation_release_slot(", payload)
        release_call = (
            "atomic_set_release(&entry->preparation_submitter_active, 0)")
        self.assertIn(release_call, submitter)
        self.assertLess(
            submitter.index("swapz_submitter_prepare_payload(ctx, entry,"),
            submitter.index(release_call))
        release = submitter.index(release_call) + len(release_call)
        self.assertNotIn("entry->", submitter[release:])
        self.assertNotIn("prepared->", submitter[release:])
        after_release = submitter[release:]
        # The owner wake follows the release, mirrors swapz_map()'s retained
        # policy, and the drain-visible active count is the final ctx access.
        self.assertIn("if (ctx->retain_ms)", after_release)
        self.assertIn("mod_delayed_work(ctx->workqueue, &ctx->worker, 0)",
                      after_release)
        self.assertIn("queue_delayed_work(ctx->workqueue, &ctx->worker, 0)",
                      after_release)
        # The active count is left while the lane is still held, so its peak
        # can never exceed the lane count (io-replay rejects active_max >
        # lanes); returning the lane is the final ctx access.
        active_dec = "atomic_dec(&ctx->submitter_preparation_active)"
        lane_release = ("swapz_preparation_release_slot("
                        "&ctx->submitter_lane_free_mask, lane_slot)")
        self.assertNotIn(active_dec, submitter[:release])
        self.assertLess(after_release.rindex("_delayed_work(ctx->workqueue"),
                        after_release.index(active_dec))
        self.assertLess(after_release.index(active_dec),
                        after_release.index(lane_release))
        self.assertEqual(after_release[after_release.index(lane_release):]
                         .strip().rstrip("}").strip(), lane_release + ";")
        # Drain waits for every submitter tail before any queue is drained.
        lane_wait = drain.index(
            "atomic64_read_acquire(&ctx->submitter_lane_free_mask)")
        self.assertIn("schedule_timeout_uninterruptible(1)", drain)
        self.assertLess(lane_wait, drain.index(
            "mod_delayed_work(ctx->workqueue, &ctx->worker, 0)"))
        self.assertLess(lane_wait, drain.index("drain_workqueue("))
        for forbidden in ("swapz_complete(", "swapz_finish(", "swapz_stage(",
                          "swapz_flush_window(", "dm_io(", "bio_endio(",
                          "swapz_engine_write_window"):
            self.assertNotIn(forbidden, submitter)
            self.assertNotIn(forbidden, payload)

        self.assertIn("ctx->submitter_lane_free_mask", drain)
        self.assertIn("ctx->submitter_lane_full_mask", drain)
        self.assertIn("atomic_read(&ctx->submitter_preparation_active)", drain)
        self.assertIn("kvfree(ctx->submitter_lanes[prep_lane].lz4_workmem)",
                      freeing)
        for field in (
                "submitter_prepare", "submitter_prepare_lanes",
                "submitter_prepare_claims", "submitter_prepare_lane_misses",
                "submitter_prepare_page_misses", "submitter_prepare_active",
                "submitter_prepare_active_max", "submitter_owner_deferrals",
                "submitter_prepare_pages", "submitter_prepare_wall_ns",
                "submitter_prepare_cpu_ns", "submitter_lz4_wall_ns",
                "submitter_copy_wall_ns", "submitter_copy_bytes",
                "submitter_crc_wall_ns", "submitter_dispatches",
                "submitter_dispatch_declines"):
            self.assertRegex(status, rf"{field}=%[ul]+")
            self.assertIn(f'"{field}"', replay)
            self.assertIn(f'"{field}"', reporter)

    def test_idle_lane_submitter_dispatch_never_waits_inside_map(self):
        """ID175: a submitter may own the ordered domain only I/O-wait-free."""
        mapper = body("swapz_map")
        dispatch = body("swapz_submitter_dispatch")
        flush = body("swapz_flush_window")
        policy = (ROOT / "src/kernel/window-policy.h").read_text()
        authority = (ROOT / "src/kernel/authority.c").read_text()
        fits = authority[authority.index("int swapz_open_segment_fits("):
                         authority.index("int swapz_stage(")]

        # Mapper: never sleeps for ownership; a trylock precedes queue_lock and
        # every non-dispatch or closed-admission path releases it.
        self.assertIn("mutex_trylock(&ctx->ordered_owner)", mapper)
        self.assertNotIn("mutex_lock(&ctx->ordered_owner)", mapper)
        self.assertLess(mapper.index("mutex_trylock(&ctx->ordered_owner)"),
                        mapper.index("spin_lock_irqsave(&ctx->queue_lock, flags);"))
        hint = mapper[mapper.index("ID175 hint"):
                      mapper.index("mutex_trylock(&ctx->ordered_owner)")]
        for gate in ("in_task()", "!irqs_disabled()", "REQ_NOWAIT",
                     "REQ_PREFLUSH | REQ_FUA", "ctx->submitter_prepare",
                     "ctx->retain_ms",
                     "READ_ONCE(ctx->singleton_fast_close)",
                     "!atomic_read(&ctx->lower_write_active)"):
            self.assertIn(gate, hint)
        closed = mapper[mapper.index("if (!ctx->accepting) {"):]
        closed = closed[:closed.index("}")]
        self.assertIn("mutex_unlock(&ctx->ordered_owner);", closed)
        unlink = mapper[mapper.index("if (submitter_lane >= 0 && ordered_owned &&"):]
        unlink = unlink[:unlink.index("}")]
        for gate in ("list_is_singular(&ctx->incoming)",
                     "list_empty(&ctx->preparation_incoming)",
                     "!ctx->preparation_queued", "list_del_init(&entry->list);"):
            self.assertIn(gate, unlink)
        tail = mapper[mapper.rindex("spin_unlock_irqrestore(&ctx->queue_lock, flags);"):]
        self.assertLess(tail.index("if (ordered_owned && !submitter_dispatch)"),
                        tail.index("swapz_submitter_dispatch(ctx, entry"))
        self.assertIn("mutex_unlock(&ctx->ordered_owner);", tail)

        # Dispatch: the payload is prepared before eligibility is re-proved
        # under the owner mutex and queue_lock; every proof is explicit.
        self.assertLess(dispatch.index("swapz_submitter_prepare_payload(ctx, entry,"),
                        dispatch.index("spin_lock_irqsave(&ctx->queue_lock, flags);"))
        for proof in ("swapz_window_submitter_dispatch_ready(",
                      "swapz_open_segment_fits(&ctx->authority, SWAPZ_MAX_BLOCKS)",
                      "!prepared->zero", "SWAPZ_PREPARATION_READY_RAW",
                      "ctx->engine.bulk_enabled",
                      "!ctx->engine.verify_after_write",
                      "!atomic_read(&ctx->lower_write_active)",
                      "swapz_has_inflight(ctx)", "ctx->accepting",
                      "!READ_ONCE(ctx->failed)"):
            self.assertIn(proof, dispatch)
        self.assertIn("list_add(&entry->list, &ctx->incoming);", dispatch)
        self.assertNotIn("list_add_tail(&entry->list", dispatch)
        active = dispatch.index("ctx->submitter_dispatch_active = true;")
        self.assertLess(active, dispatch.index("swapz_flush_window(ctx);"))
        self.assertLess(dispatch.index("swapz_flush_window(ctx);"),
                        dispatch.index("ctx->submitter_dispatch_active = false;"))
        self.assertLess(dispatch.index("swapz_process(ctx, bio);"), active)
        self.assertLess(dispatch.rindex("mutex_unlock(&ctx->ordered_owner);"),
                        dispatch.index("atomic_dec(&ctx->submitter_preparation_active)"))
        lane_release = ("swapz_preparation_release_slot("
                        "&ctx->submitter_lane_free_mask, lane_slot);")
        self.assertEqual(dispatch[dispatch.index(lane_release):]
                         .strip().rstrip("}").strip(), lane_release)
        declined = dispatch[dispatch.index("ctx->submitter_dispatch_declines++"):]
        self.assertLess(declined.index("mutex_unlock(&ctx->ordered_owner);"),
                        declined.index(
                            "atomic_set_release(&entry->preparation_submitter_active, 0)"))
        for forbidden in ("wait_for_completion", "swapz_issue_flush",
                          "swapz_gc_compact_one", "swapz_finalize",
                          "mutex_lock(", "msleep", "schedule", "swapz_raw_write",
                          "swapz_discard_dead_segment"):
            self.assertNotIn(forbidden, dispatch)

        # Flush: dispatch detaches, records its marker and never falls back to
        # the synchronous loop or GC retry from ->map.
        detach = flush[flush.index("async_detach_ready ="):]
        detach = detach[:detach.index(";")]
        self.assertIn("ctx->submitter_dispatch_active", detach)
        self.assertIn("inflight->submitter_dispatched =\n"
                      "\t\t\t\t\tctx->submitter_dispatch_active;", flush)
        guard = flush.index(
            "if (ctx->submitter_dispatch_active && !async_submitted && !error)")
        self.assertLess(guard, flush.index("while (!async_submitted && committed < count)"))
        self.assertIn("error = -EUCLEAN;", flush[guard:guard + 200])

        # Policy and placement proofs stay pure and read-only.
        ready = policy[policy.index("swapz_window_submitter_dispatch_ready("):]
        ready = ready[:ready.index("}")]
        for term in ("retain_ms", "singleton_fast_close", "!single_tail_deferred",
                     "!pending_tail_sample", "!batch_count",
                     "!lower_write_inflight", "!queued_followers"):
            self.assertIn(term, ready)
        for term in ("a->in_flight", "a->batch_pending", "a->gc_allocation",
                     "a->open_segment", "SWAPZ_SEGMENT_BLOCKS"):
            self.assertIn(term, fits)
        for mutation in ("a->next_block =", "swapz_pick_dead_segment",
                         "dead_segment_recycle", "++", "+="):
            self.assertNotIn(mutation, fits)
        self.assertIn("mutex_init(&ctx->ordered_owner);", body("swapz_ctr"))


class CapacityMemoryAccountingContracts(unittest.TestCase):
    """Audit *current* capacity-sized constructor sites without allocation.

    Compiled-type/admission checks also run in mapping/authority.c. This
    independent source inventory detects an added, resized or leaked index
    rather than continuing to report an obsolete fixed 740 MiB estimate.
    """

    INDEXES = {
        "maps": ("logical", "struct swapz_map", 16),
        "page_prev_in_segment": ("logical", "swapz_u32", 4),
        "page_next_in_segment": ("logical", "swapz_u32", 4),
        "live_records": ("physical", "swapz_u16", 2),
        "extent_classes": ("physical", "swapz_u8", 1),
        "extent_sequence_delta": ("physical", "swapz_u8", 1),
        "gc_scores": ("ctx->segment_count", "swapz_u32", 4),
        "gc_io_scores": ("ctx->segment_count", "swapz_u32", 4),
        "gc_min_live_blocks": ("ctx->segment_count", "swapz_u16", 2),
        "gc_segment_evictions": ("ctx->segment_count", "swapz_u32", 4),
        "segment_mapped_pages": ("ctx->segment_count", "swapz_u32", 4),
        "segment_program_counts": ("ctx->segment_count", "swapz_u32", 4),
        "segment_first_page": ("ctx->segment_count", "swapz_u32", 4),
        "segment_last_page": ("ctx->segment_count", "swapz_u32", 4),
        "segment_sequence_base": ("ctx->segment_count", "swapz_u32", 4),
        "segment_trimmed": ("ctx->segment_count", "swapz_u8", 1),
        "segment_roles": ("ctx->segment_count", "swapz_u8", 1),
    }

    INDEX_ORDER = (
        "gc_scores", "gc_io_scores", "gc_min_live_blocks",
        "gc_segment_evictions", "segment_mapped_pages",
        "segment_program_counts", "segment_first_page", "segment_last_page",
        "page_prev_in_segment", "page_next_in_segment", "segment_trimmed",
        "segment_roles", "maps", "live_records", "extent_classes",
        "extent_sequence_delta", "segment_sequence_base",
    )

    FIXED_ALLOCATIONS = (
        ("ctx", "kzalloc"),
        ("ctx->batch_bytes", "vzalloc"),
        ("ctx->gc_bytes_store", "vzalloc"),
        ("ctx->input_page", "vzalloc"),
        ("ctx->predictor_page", "kvmalloc"),
        ("ctx->delta64_candidate_page", "kvmalloc"),
        ("ctx->read_page", "vzalloc"),
        ("ctx->read_compressed", "vzalloc"),
        ("ctx->engine.write_scratch", "vzalloc"),
        ("ctx->engine.read_scratch", "vzalloc"),
        ("ctx->engine.read_metadata_cache", "vzalloc"),
        ("ctx->engine.read_extent_cache", "vzalloc"),
        ("ctx->read_slots", "kvcalloc"),
        ("ctx->read_pages_store", "vzalloc"),
        ("ctx->read_coalesce_scratch", "vzalloc"),
        ("ctx->engine.bulk_scratch", "vzalloc"),
        ("ctx->engine.bulk_txs", "kvcalloc"),
        ("ctx->lz4_workmem", "kvmalloc"),
        ("slot->engine.read_scratch", "vzalloc"),
        ("slot->read_compressed", "vzalloc"),
        ("slot->predictor_page", "kvmalloc"),
        ("ctx->preparation_pages", "vzalloc"),
        ("ctx->preparation_lanes", "kcalloc"),
        ("ctx->submitter_lanes", "kvcalloc"),
        ("lane->predictor_page", "kvmalloc"),
        ("lane->predictor_page", "kvmalloc"),
        ("lane->delta64_candidate_page", "kvmalloc"),
        ("lane->delta64_candidate_page", "kvmalloc"),
        ("lane->lz4_workmem", "kvmalloc"),
        ("lane->lz4_workmem", "kvmalloc"),
    )

    DIRECT_FREES = (
        ("ctx->preparation_lanes[prep_lane].predictor_page", "kvfree"),
        ("ctx->preparation_lanes[prep_lane].delta64_candidate_page", "kvfree"),
        ("ctx->preparation_lanes[prep_lane].lz4_workmem", "kvfree"),
        ("ctx->preparation_lanes", "kfree"),
        ("ctx->submitter_lanes[prep_lane].predictor_page", "kvfree"),
        ("ctx->submitter_lanes[prep_lane].delta64_candidate_page", "kvfree"),
        ("ctx->submitter_lanes[prep_lane].lz4_workmem", "kvfree"),
        ("ctx->submitter_lanes", "kvfree"),
        ("ctx->preparation_pages", "vfree"),
        ("ctx->maps", "kvfree"),
        ("ctx->live_records", "kvfree"),
        ("ctx->extent_classes", "kvfree"),
        ("ctx->extent_sequence_delta", "kvfree"),
        ("ctx->segment_sequence_base", "kvfree"),
        ("ctx->batch_bytes", "vfree"),
        ("ctx->gc_bytes_store", "vfree"),
        ("ctx->gc_scores", "kvfree"),
        ("ctx->gc_io_scores", "kvfree"),
        ("ctx->gc_min_live_blocks", "kvfree"),
        ("ctx->gc_segment_evictions", "kvfree"),
        ("ctx->segment_mapped_pages", "kvfree"),
        ("ctx->segment_program_counts", "kvfree"),
        ("ctx->segment_first_page", "kvfree"),
        ("ctx->segment_last_page", "kvfree"),
        ("ctx->page_prev_in_segment", "kvfree"),
        ("ctx->page_next_in_segment", "kvfree"),
        ("ctx->segment_trimmed", "kvfree"),
        ("ctx->segment_roles", "kvfree"),
        ("ctx->input_page", "vfree"),
        ("ctx->predictor_page", "kvfree"),
        ("ctx->delta64_candidate_page", "kvfree"),
        ("ctx->read_page", "vfree"),
        ("ctx->read_compressed", "vfree"),
        ("ctx->engine.write_scratch", "vfree"),
        ("ctx->engine.read_scratch", "vfree"),
        ("ctx->engine.read_metadata_cache", "vfree"),
        ("ctx->engine.read_extent_cache", "vfree"),
        ("ctx->read_pages_store", "vfree"),
        ("ctx->read_coalesce_scratch", "vfree"),
        ("ctx->read_slots[slot].engine.read_scratch", "vfree"),
        ("ctx->read_slots[slot].read_compressed", "vfree"),
        ("ctx->read_slots[slot].predictor_page", "kvfree"),
        ("ctx->read_slots", "kvfree"),
        ("ctx->engine.bulk_scratch", "vfree"),
        ("ctx->engine.bulk_txs", "kvfree"),
        ("ctx->lz4_workmem", "kvfree"),
        ("ctx", "kfree"),
    )

    @staticmethod
    def allocation_inventory(constructor):
        # Require exactly the production kvcalloc count and sizeof expression.
        pattern = re.compile(
            r"ctx->([a-z_]+)\s*=\s*kvcalloc\(\s*"
            r"(logical|physical|ctx->segment_count)\s*,\s*"
            r"sizeof\(\*ctx->\1\)\s*,\s*GFP_KERNEL\s*\)", re.S)
        return [(match.group(1), match.group(2), match.start())
                for match in pattern.finditer(constructor)]

    def audit_constructor(self, constructor):
        inventory = self.allocation_inventory(constructor)
        observed = {name: scale for name, scale, _ in inventory}
        self.assertEqual(len(inventory), len(self.INDEXES),
                         "capacity index site added, removed or malformed")
        self.assertEqual(set(observed), set(self.INDEXES))
        self.assertEqual(
            tuple(name for name, _, _ in inventory), self.INDEX_ORDER,
            "constructor capacity-index allocation order changed")
        for name, (scale, _, _) in self.INDEXES.items():
            self.assertEqual(observed[name], scale)

        # Every explicit capacity-scaled allocation follows deterministic
        # geometry rejection. Match the whole allocation expression so a
        # wrapper/cast or a different kernel allocation API cannot evade the
        # preflight-order contract.
        preflight = constructor.index("swapz_authority_validate_geometry(")
        self.assertLess(preflight, min(position for _, _, position in inventory))
        direct_allocator = re.compile(
            r"\b(?:kcalloc|kzalloc|kmalloc|kmalloc_array|kvmalloc|"
            r"kvmalloc_array|kvcalloc|kvzalloc|vmalloc|vzalloc)\s*"
            r"\((?P<args>[^;]*)\);", re.S)
        preflight_allocations = list(
            direct_allocator.finditer(constructor[:preflight]))
        self.assertEqual(
            len(preflight_allocations), 1,
            "new direct allocation appeared before geometry rejection")
        self.assertRegex(
            preflight_allocations[0].group(0),
            r"kzalloc\(sizeof\(\*ctx\),\s*GFP_KERNEL\)",
            "only the small target context may be directly allocated "
            "before geometry rejection")
        for allocation in preflight_allocations:
            self.assertNotRegex(
                allocation.group("args"),
                r"\b(?:logical|physical|segment_count)\b",
                "capacity-scaled allocation appeared before geometry rejection")
        self.assertIn("goto fail;", constructor[preflight:])
        self.assertLess(constructor.index("swapz_authority_validate_geometry("),
                        constructor.index("error = swapz_authority_init("))
        self.assertIn("swapz_free(ctx);", constructor)

    def test_exact_allocations_widths_frees_and_rejection_order(self):
        constructor = body("swapz_ctr")
        destruction = body("swapz_free")
        self.audit_constructor(constructor)
        target_struct = DM.split("struct swapz_dm {", 1)[1].split("\n};", 1)[0]
        for name, (_, element_type, _) in self.INDEXES.items():
            self.assertRegex(
                target_struct, re.escape(element_type) +
                r"\s*\*\s*" + re.escape(name) + r"\s*;")
            self.assertEqual(
                len(re.findall(r"\bkvfree\(ctx->" + name + r"\);",
                               destruction)), 1, "missing/duplicate index free")
        self.assertIn("_Static_assert(sizeof(struct swapz_map) == 16",
                      (ROOT / "src/kernel/authority.h").read_text())
        authority = source_body(
            "swapz_authority_validate_candidate", AUTH)
        self.assertIn("sizeof(struct swapz_map)", authority)
        self.assertIn("sizeof(swapz_u16)", authority)
        self.assertIn("(size_t)-1", authority)

    def test_all_constructor_allocations_and_frees_are_inventoried(self):
        constructor = body("swapz_ctr")
        destruction = body("swapz_free")
        allocation_pattern = re.compile(
            r"([A-Za-z0-9_>.\-\[\]]+)\s*=\s*"
            r"(kzalloc|kcalloc|kmalloc|kmalloc_array|kvmalloc|"
            r"kvmalloc_array|kvcalloc|kvzalloc|vmalloc|vzalloc)\s*\(")
        observed_allocations = Counter(
            allocation_pattern.findall(constructor))
        expected_allocations = Counter(self.FIXED_ALLOCATIONS)
        expected_allocations.update(
            (f"ctx->{name}", "kvcalloc") for name in self.INDEX_ORDER)
        self.assertEqual(
            observed_allocations, expected_allocations,
            "constructor direct allocation inventory changed; update the "
            "capacity/RAM accounting before accepting the change")
        self.assertEqual(sum(observed_allocations.values()), 47)
        direct_allocator_calls = re.findall(
            r"\b(?:kzalloc|kcalloc|kmalloc|kmalloc_array|kvmalloc|"
            r"kvmalloc_array|kvcalloc|kvzalloc|vmalloc|vzalloc)\s*\(",
            constructor)
        self.assertEqual(
            len(direct_allocator_calls), 47,
            "constructor contains an unaccounted direct allocator call")

        free_pattern = re.compile(
            r"\b(kfree|kvfree|vfree)\s*\(\s*"
            r"([A-Za-z0-9_>.\-\[\]]+)\s*\)")
        observed_frees = Counter(
            (expression, allocator)
            for allocator, expression in free_pattern.findall(destruction))
        self.assertEqual(observed_frees, Counter(self.DIRECT_FREES))
        self.assertEqual(sum(observed_frees.values()), 47)

        # Allocation families outside the inventoried direct heap/vmalloc set
        # must not appear silently; each would need explicit accounting first.
        self.assertNotRegex(
            constructor,
            r"\b(?:alloc_page|alloc_pages|__get_free_pages|"
            r"kmem_cache_alloc|mempool_alloc|krealloc|kvrealloc|"
            r"vmalloc_user)\s*\(")
        self.assertEqual(constructor.count("alloc_workqueue("), 2)
        self.assertEqual(destruction.count("destroy_workqueue("), 2)
        self.assertEqual(constructor.count("dm_io_client_create()"), 1)
        self.assertEqual(destruction.count("dm_io_client_destroy("), 1)
        self.assertEqual(constructor.count("dm_get_device("), 1)
        self.assertEqual(destruction.count("dm_put_device("), 1)

    def test_new_or_early_index_allocation_fails_source_audit(self):
        constructor = body("swapz_ctr")
        guard = constructor.index("swapz_authority_validate_geometry(")
        injected = (constructor[:guard] +
                    "ctx->maps = kvcalloc(logical, sizeof(*ctx->maps), GFP_KERNEL);\n" +
                    constructor[guard:])
        with self.assertRaises(AssertionError):
            self.audit_constructor(injected)
        injected = constructor.replace(
            "ctx->maps = kvcalloc(logical, sizeof(*ctx->maps), GFP_KERNEL);",
            "ctx->maps = kvcalloc(physical, sizeof(*ctx->maps), GFP_KERNEL);")
        with self.assertRaises(AssertionError):
            self.audit_constructor(injected)
        injected = (
            constructor[:guard] +
            "ctx->maps = kvmalloc_array((size_t)logical, "
            "sizeof(*ctx->maps), GFP_KERNEL);\n" +
            constructor[guard:])
        with self.assertRaises(AssertionError):
            self.audit_constructor(injected)
        injected = (
            constructor[:guard] +
            "ctx->batch_bytes = vzalloc((size_t)logical * 4096U);\n" +
            constructor[guard:])
        with self.assertRaises(AssertionError):
            self.audit_constructor(injected)
        injected = (
            constructor[:guard] +
            "ctx->batch_bytes = kmalloc(4096U, GFP_KERNEL);\n" +
            constructor[guard:])
        with self.assertRaises(AssertionError):
            self.audit_constructor(injected)

    def audit_partial_constructor_ownership(self, constructor, destruction):
        """Bounded source fault-site audit, not a loaded kernel allocation test.

        Each of the 47 direct allocation attempts must have an -ENOMEM path;
        partially built slots and worker lanes must remain zero-initialized
        until their buffers exist. Only the final admitted constructor may
        enable BIO acceptance. Loaded null_blk injection remains mandatory.
        """
        self.audit_constructor(constructor)
        index_end = max(
            offset for _, _, offset in self.allocation_inventory(constructor))
        index_guard = constructor[
            index_end:constructor.index("error = swapz_authority_init(")]
        for name in self.INDEXES:
            self.assertEqual(
                len(re.findall(r"!ctx->" + re.escape(name) + r"\b",
                               index_guard)), 1,
                f"{name} is not checked before authority initialization")
        self.assertRegex(index_guard, r"error\s*=\s*-ENOMEM;\s*goto fail;")

        core_start = constructor.index("ctx->batch_bytes = vzalloc(")
        core_end = constructor.index(
            "SWAPZ_CONSTRUCTOR_FAIL_AFTER_CORE_SCRATCH", core_start)
        core = constructor[core_start:core_end]
        read_start = constructor.index(
            "for (read_slot = 0; ctx->read_grouping_enabled", core_end)
        read_end = constructor.index(
            "SWAPZ_CONSTRUCTOR_FAIL_AFTER_READ_SLOTS", read_start)
        read_slots = constructor[read_start:read_end]
        preparation_start = constructor.index(
            "if (ctx->async_prepare) {", read_end)
        preparation_end = constructor.index(
            "SWAPZ_CONSTRUCTOR_FAIL_AFTER_PREPARATION_SCRATCH",
            preparation_start)
        preparation = constructor[preparation_start:preparation_end]

        # Audit all fixed heap sites, including the optional delta64 scratch
        # and the per-slot/per-lane partial failures, not just the 17 indexes.
        for expression, _ in self.FIXED_ALLOCATIONS:
            if expression == "ctx":
                self.assertRegex(
                    constructor[:constructor.index("ti->private = ctx;")],
                    r"if \(!ctx\)\s*return -ENOMEM;")
                continue
            if expression.startswith("slot->"):
                scope = read_slots
            elif expression.startswith("lane->"):
                scope = preparation
            elif expression in (
                    "ctx->preparation_pages", "ctx->preparation_lanes",
                    "ctx->submitter_lanes"):
                scope = preparation
            else:
                scope = core
            self.assertIn("!" + expression, scope,
                          f"missing partial-allocation guard: {expression}")
        self.assertRegex(read_slots, r"error\s*=\s*-ENOMEM;\s*goto fail;")
        self.assertRegex(preparation, r"error\s*=\s*-ENOMEM;\s*goto fail;")
        self.assertEqual(
            len(re.findall(r"!lane->predictor_page\b", preparation)), 2)
        self.assertEqual(
            len(re.findall(r"!lane->delta64_candidate_page\b", preparation)),
            2)
        self.assertEqual(
            len(re.findall(r"!lane->lz4_workmem\b", preparation)), 2)

        # The constructor may INIT work items, but must never queue a worker
        # before DM publishes a successfully constructed target.
        self.assertNotRegex(
            constructor,
            r"\b(?:queue_work|queue_delayed_work|mod_delayed_work|"
            r"kthread_run|schedule_work)\s*\(")
        self.assertLess(
            constructor.index("INIT_DELAYED_WORK(&ctx->worker"),
            constructor.index("dm_get_device("))
        self.assertLess(
            constructor.index("hrtimer_init(&ctx->retention_timer"),
            constructor.index("dm_get_device("))
        first_failure = constructor.index("goto fail;")
        for initialized_before_failure in (
                "INIT_DELAYED_WORK(&ctx->worker",
                "INIT_WORK(&ctx->completion_work",
                "hrtimer_setup(&ctx->retention_timer",
                "hrtimer_init(&ctx->retention_timer"):
            self.assertLess(
                constructor.index(initialized_before_failure), first_failure,
                f"{initialized_before_failure} must precede cleanup")
        for count_assignment in (
                "ctx->preparation_worker_count =",
                "ctx->submitter_lane_count ="):
            self.assertLess(
                constructor.index(count_assignment), first_failure,
                f"{count_assignment} must precede partial-lane cleanup")
        self.assertLess(
            constructor.index("INIT_WORK(&lane->work", preparation_start),
            constructor.index(
                "ctx->preparation_workqueue = alloc_workqueue(",
                preparation_start))
        self.assertRegex(
            preparation,
            r"ctx->preparation_lanes\s*=\s*kcalloc\(")
        self.assertRegex(
            preparation,
            r"ctx->submitter_lanes\s*=\s*\n?\s*kvcalloc\(")
        self.assertLess(
            constructor.index("ctx->preparation_lanes = kcalloc("),
            constructor.index("for (prep_lane = 0; prep_lane < "
                              "ctx->preparation_worker_count"))
        self.assertLess(
            constructor.index("if (!ctx->preparation_pages ||"),
            constructor.index("for (prep_lane = 0; prep_lane < "
                              "ctx->preparation_worker_count"))
        self.assertLess(
            constructor.index("ctx->preparation_workqueue = alloc_workqueue("),
            constructor.index(
                "SWAPZ_CONSTRUCTOR_FAIL_AFTER_PREPARATION_WORKQUEUE"))

        # All eight post-acquisition fault injections explicitly return
        # ENOMEM via the common idempotent cleanup, never by falling through.
        for stage in (
                "BACKING", "IO_CLIENT", "AUTHORITY", "CORE_SCRATCH",
                "READ_SLOTS", "WORKQUEUE", "PREPARATION_SCRATCH",
                "PREPARATION_WORKQUEUE"):
            marker = constructor.rindex("SWAPZ_CONSTRUCTOR_FAIL_AFTER_" + stage)
            self.assertRegex(
                constructor[marker:marker + 180],
                r"\)\)\s*\{\s*error = -ENOMEM;\s*goto fail;\s*\}")

        private_assignments = re.findall(
            r"ti->private\s*=\s*([^;]+);", constructor)
        self.assertEqual(private_assignments, ["ctx", "NULL"])
        acquired_context = constructor[
            constructor.index("ti->private = ctx;"):]
        self.assertEqual(
            re.findall(r"\breturn\s+([^;]+);", acquired_context),
            ["0", "error"],
            "post-acquisition returns must not bypass common cleanup")
        self.assertEqual(
            set(re.findall(
                r"\bgoto\s+([A-Za-z_][A-Za-z0-9_]*)\s*;",
                acquired_context)),
            {"fail"},
            "post-acquisition failures must converge on the common unwind")
        publications = list(re.finditer(
            r"(?:WRITE_ONCE\(\s*ctx->accepting\s*,\s*true\s*\)|"
            r"ctx->accepting\s*=\s*true\s*;)",
            constructor))
        self.assertEqual(
            len(publications), 1,
            "constructor must publish acceptance exactly once")
        success = publications[0].start()
        self.assertLess(constructor.index("dm_set_target_max_io_len("),
                        success)
        self.assertLess(
            constructor.rindex(
                "SWAPZ_CONSTRUCTOR_FAIL_AFTER_PREPARATION_WORKQUEUE"),
            success)
        self.assertLess(success, constructor.rindex("return 0;"))
        self.assertRegex(
            constructor[constructor.rindex("fail:"):],
            r"fail:\s*swapz_free\(ctx\);\s*ti->private = NULL;\s*return error;")
        self.assertLess(constructor.index("ti->private = ctx;"),
                        constructor.index("dm_get_device("))

        # Resource dependencies determine teardown order: cancel/drain both
        # workqueues before freeing lane/read scratch; free the host IO client
        # and backing reference once; release ctx last. This is safe for
        # partially initialized, zero-filled arrays, including a failed lane.
        for worker in ("ctx->workqueue", "ctx->preparation_workqueue"):
            self.assertIn("if (" + worker + ")", destruction)
            self.assertEqual(
                destruction.count("destroy_workqueue(" + worker + ")"), 1)
        self.assertLess(
            destruction.index("destroy_workqueue(ctx->workqueue)"),
            destruction.index("kvfree(ctx->read_slots);"))
        self.assertLess(
            destruction.index("destroy_workqueue(ctx->preparation_workqueue)"),
            destruction.index("kfree(ctx->preparation_lanes);"))
        self.assertLess(
            destruction.index("destroy_workqueue(ctx->preparation_workqueue)"),
            destruction.index("kvfree(ctx->submitter_lanes);"))
        for resource, release in (
                ("ctx->backing", "dm_put_device(ctx->target, ctx->backing)"),
                ("ctx->io_client", "dm_io_client_destroy(ctx->io_client)"),
                ("ctx->read_slots", "kvfree(ctx->read_slots)"),
                ("ctx->preparation_lanes", "kfree(ctx->preparation_lanes)"),
                ("ctx->submitter_lanes", "kvfree(ctx->submitter_lanes)")):
            self.assertIn("if (" + resource + ")", destruction)
            self.assertEqual(destruction.count(release), 1)
        self.assertTrue(destruction.rstrip().endswith("kfree(ctx);"))
        self.assertIn("if (!ctx)\n\t\treturn;", destruction)

    def test_all_constructor_fault_sites_and_unwind_are_fail_closed(self):
        constructor = body("swapz_ctr")
        destruction = body("swapz_free")
        self.audit_partial_constructor_ownership(constructor, destruction)
        # Mutations prove that each failure path is an enforced contract,
        # rather than a source-presence assertion against unrelated code.
        with self.assertRaises(AssertionError):
            self.audit_partial_constructor_ownership(
                constructor.replace("!ctx->segment_roles", "ctx->segment_roles",
                                    1), destruction)
        with self.assertRaises(AssertionError):
            self.audit_partial_constructor_ownership(
                constructor.replace(
                    "ti->private = NULL;\n\treturn error;",
                    "return error;", 1), destruction)
        with self.assertRaises(AssertionError):
            self.audit_partial_constructor_ownership(
                constructor, destruction.replace(
                    "destroy_workqueue(ctx->preparation_workqueue);",
                    "/* missing worker teardown */", 1))
        with self.assertRaises(AssertionError):
            self.audit_partial_constructor_ownership(
                constructor.replace(
                    "error = dm_get_device(",
                    "ctx->accepting = true;\n\terror = dm_get_device(", 1),
                destruction)
        with self.assertRaises(AssertionError):
            self.audit_partial_constructor_ownership(
                constructor.replace(
                    "spin_lock_init(&ctx->queue_lock);",
                    "error = -EINVAL;\n\tgoto fail;\n\t"
                    "spin_lock_init(&ctx->queue_lock);", 1),
                destruction)
        with self.assertRaises(AssertionError):
            self.audit_partial_constructor_ownership(
                constructor.replace(
                    "error = dm_get_device(",
                    "return -ENOMEM;\n\terror = dm_get_device(", 1),
                destruction)

    def test_capacity_index_fault_fixture_matches_constructor_order(self):
        """Pin the executable 17-site ENOMEM model and reverse-order unwind."""
        fixture = (
            ROOT / "tests/runtime/native/mapping/authority.c").read_text()
        function = source_body(
            "test_small_index_failure_and_repeated_lifecycle", fixture)

        allocation_sizes = function.split(
            "const size_t allocation_sizes[] = {", 1)[1].split("};", 1)[0]
        observed_types = re.findall(
            r"sizeof\((struct swapz_map|swapz_u(?:8|16|32))\)",
            allocation_sizes)
        expected_types = [
            self.INDEXES[name][1] for name in self.INDEX_ORDER]
        self.assertEqual(observed_types, expected_types)
        self.assertIn("CHECK(allocation_count == 17U);", function)
        self.assertIn(
            "8U * (allocation_count + 1U)", function,
            "fixture must inject every index site plus successful attach "
            "for eight lifecycle repetitions")
        self.assertIn(
            "failure_site = iteration % (allocation_count + 1U)", function)
        self.assertRegex(
            function,
            r"if \(site == failure_site\) \{\s*"
            r"error = -ENOMEM;\s*continue;\s*\}")
        self.assertIn("swapz_authority_init(", function)
        self.assertRegex(
            function,
            r"for \(site = allocation_count; site > 0U; --site\)\s*"
            r"free\(allocated_indexes\[site - 1U\]\);",
            "fault fixture must unwind acquired indexes in reverse order")

    def test_checked_geometry_oracle_tracks_production_headers(self):
        """Cross-check source-defined geometry with bounded sizing, not RAM."""
        import json
        import runpy

        codec = (ROOT / "src/kernel/codec.h").read_text()
        authority = (ROOT / "src/kernel/authority.h").read_text()
        context = (ROOT / "docs/AGENT_CONTEXT.md").read_text()
        acceptance = json.loads(
            (ROOT / "docs/production-acceptance.json").read_text())

        def definition(header, name):
            values = re.findall(
                r"^#define\s+" + re.escape(name) + r"\s+([0-9]+)U?\s*$",
                header, flags=re.M)
            self.assertEqual(len(values), 1, name)
            return int(values[0])

        page_bytes = definition(codec, "SWAPZ_BLOCK_BYTES")
        segment_blocks = definition(authority, "SWAPZ_SEGMENT_BLOCKS")
        self.assertEqual(
            definition(authority, "SWAPZ_LINUX_SWAP_HEADER_BLOCKS"), 1)
        self.assertEqual((page_bytes, segment_blocks), (4096, 256))
        type_widths = {}
        for type_name, kernel_type, bits in (
                ("swapz_u8", "u8", 8), ("swapz_u16", "u16", 16),
                ("swapz_u32", "u32", 32), ("swapz_u64", "u64", 64)):
            self.assertIn(f"typedef {kernel_type} {type_name};", codec)
            self.assertIn(f"typedef uint{bits}_t {type_name};", codec)
            type_widths[type_name] = bits // 8
        map_width_match = re.search(
            r"_Static_assert\(sizeof\(struct swapz_map\) == ([0-9]+)",
            authority)
        self.assertIsNotNone(map_width_match)
        source_widths = {
            **type_widths,
            "struct swapz_map": int(map_width_match.group(1)),
        }
        for name, (_, element_type, expected_width) in self.INDEXES.items():
            self.assertEqual(
                expected_width, source_widths[element_type],
                f"{name} byte width drifted from its source definition")
        self.assertIn("(swapz_u64)logical_pages +", authority)
        self.assertIn("logical_pages / 8U", authority)
        self.assertIn("logical_pages % 8U", authority)

        model = runpy.run_path(
            str(ROOT / "tests/runtime/benchmark/metadata_ram_evidence.py"))
        self.assertEqual(model["BLOCK_BYTES"], page_bytes)
        self.assertEqual(model["SEGMENT_BLOCKS"], segment_blocks)
        self.assertEqual(model["FOREGROUND_HEADROOM_BLOCKS"], segment_blocks)
        self.assertEqual(
            model["MAP_RECORD_BYTES"], source_widths["struct swapz_map"])
        self.assertEqual(
            model["PHYSICAL_LIVENESS_RECORD_BYTES"],
            source_widths["swapz_u16"])
        self.assertEqual(acceptance["status"], "FROZEN")
        measured_peak_ram_ceiling = acceptance["physical_qualification"][
            "acceptance"]["sustained"][
                "metadata_and_target_peak_ram_bytes_max"]
        self.assertEqual(measured_peak_ram_ceiling, 1342177280)
        current_card = re.search(
            r"^- size:\s*\x60([0-9]+)\x60 bytes\s*$", context, flags=re.M)
        self.assertIsNotNone(current_card)
        partition_bytes = int(current_card.group(1))
        self.assertEqual(partition_bytes, 124787884032)
        physical = ((partition_bytes // page_bytes - 1) //
                    segment_blocks) * segment_blocks
        segments = physical // segment_blocks
        maximum = model["maximum_logical_pages_for_partition"]
        logical = maximum(partition_bytes, size_t_max=(1 << 64) - 1)
        self.assertEqual((physical, segments, logical),
                         (30465536, 119006, 27080192))
        logical_mapper_bytes = model["_checked_product"](
            logical, page_bytes, model["MAX_UINT64"])
        self.assertEqual(logical_mapper_bytes, 110920466432)
        reserve = max(logical // 8 + (logical % 8 != 0),
                      2 * segment_blocks)
        self.assertEqual(reserve, 3385024)
        self.assertLessEqual(
            logical + segment_blocks,
            (physical - reserve) // segment_blocks * segment_blocks)
        next_logical = logical + 1
        next_reserve = max(next_logical // 8 +
                           (next_logical % 8 != 0), 2 * segment_blocks)
        self.assertGreater(
            next_logical + segment_blocks,
            (physical - next_reserve) // segment_blocks * segment_blocks)

        def checked_length(count, width, limit):
            if width <= 0 or count > limit // width:
                raise OverflowError("capacity-index byte length overflow")
            return count * width

        dimensions = {
            "logical": logical, "physical": physical,
            "ctx->segment_count": segments,
        }
        lengths = [
            (name, checked_length(
                dimensions[scale], source_widths[element_type],
                (1 << 64) - 1))
            for name, (scale, element_type, _) in self.INDEXES.items()
        ]
        self.assertEqual(len(lengths), 17)
        payload_bytes = 0
        rounded_index_bytes = 0
        leaf_pte_pages = 0
        for _, length in lengths:
            payload_bytes = model["_checked_sum"](
                payload_bytes, length, model["MAX_UINT64"])
            self.assertIsNotNone(payload_bytes)
            round_input = model["_checked_sum"](
                length, page_bytes - 1, model["MAX_UINT64"])
            self.assertIsNotNone(round_input)
            rounded_length = model["_checked_product"](
                round_input // page_bytes, page_bytes, model["MAX_UINT64"])
            self.assertIsNotNone(rounded_length)
            rounded_index_bytes = model["_checked_sum"](
                rounded_index_bytes, rounded_length, model["MAX_UINT64"])
            self.assertIsNotNone(rounded_index_bytes)
            allocation_pages = rounded_length // page_bytes
            leaf_round_input = model["_checked_sum"](
                allocation_pages, 511, model["MAX_UINT64"])
            self.assertIsNotNone(leaf_round_input)
            leaf_pte_pages = model["_checked_sum"](
                leaf_pte_pages, leaf_round_input // 512,
                model["MAX_UINT64"])
            self.assertIsNotNone(leaf_pte_pages)
        self.assertEqual(payload_bytes, 776070968)
        self.assertEqual(rounded_index_bytes, 776114176)
        # Predicted index bytes are source accounting only. Do not compare
        # them with the measured-host peak-RAM acceptance ceiling.
        self.assertEqual(dict(lengths)["maps"], 433283072)
        leaf_pte_bytes = model["_checked_product"](
            leaf_pte_pages, page_bytes, model["MAX_UINT64"])
        self.assertEqual(leaf_pte_pages, 382)
        self.assertEqual(leaf_pte_bytes, 1564672)
        self.assertIsNone(maximum(partition_bytes + 1))
        exactly_three_data_segments = (
            (3 * segment_blocks + 1) * page_bytes)
        self.assertEqual(
            ((exactly_three_data_segments // page_bytes - 1) //
             segment_blocks) * segment_blocks,
            3 * segment_blocks)
        self.assertIsNone(maximum(exactly_three_data_segments))
        self.assertIsNone(maximum(
            ((1 << 32) + segment_blocks + 1) * page_bytes))
        self.assertIsNone(maximum(
            (0xffffff00 + 1) * page_bytes, size_t_max=(1 << 32) - 1))
        self.assertIsNone(
            model["_checked_product"](1 << 63, 2, (1 << 64) - 1))
        self.assertIsNone(
            model["_checked_sum"]((1 << 64) - 1, 1, (1 << 64) - 1))
        with self.assertRaises(OverflowError):
            checked_length(1 << 32, 16, (1 << 32) - 1)

    def test_ram_trace_rejects_forged_clock_and_hidden_teardown_leaks(self):
        """Offline negative fixtures never qualify a real loaded host."""
        import copy
        import datetime
        import runpy

        evidence = runpy.run_path(
            str(ROOT / "tests/runtime/benchmark/metadata_ram_evidence.py"))
        source_sha = "a" * 40
        mapper_uuid = "SWAPZ-PRIMARY-" + "f" * 32
        start_utc = datetime.datetime(
            2026, 11, 3, tzinfo=datetime.timezone.utc)
        samples = []
        phases = (
            ("baseline", 11), ("initialization", 2), ("steady", 2),
            ("gc", 2), ("teardown", 22),
        )
        for phase, count in phases:
            for phase_index in range(count):
                index = len(samples) + 1
                timestamp = (
                    start_utc +
                    datetime.timedelta(milliseconds=100 * index))
                present = (
                    phase == "steady" or phase == "gc" or
                    (phase == "initialization" and phase_index > 0) or
                    (phase == "teardown" and phase_index == 0))
                samples.append({
                    "phase": phase,
                    "monotonic_ns": index * 100_000_000,
                    "timestamp_utc":
                        timestamp.isoformat(timespec="milliseconds").replace(
                            "+00:00", "Z"),
                    "mem_available_kib":
                        1_000_000 - (10_000 if present else 0),
                    "s_unreclaim_kib": 1000 + (500 if present else 0),
                    "vmalloc_used_kib": 2000 + (500 if present else 0),
                    "mapper_present": present,
                })
        trace = {
            "schema": "swapz-metadata-ram-samples-v1",
            "capture": "serialized-loaded-host",
            "scope": "whole-host-conservative-metadata-and-target-ram",
            "source_sha": source_sha, "mapper_uuid": mapper_uuid,
            "host_boot_id": "11111111-1111-4111-8111-111111111111",
            "sampling_interval_ns": 100_000_000, "meminfo_unit": "kB",
            "samples": samples,
        }
        validate = evidence["validate_metadata_ram_trace"]
        expected_peak = 10_000 * 1024
        summary = validate(
            trace, source_sha=source_sha, mapper_uuid=mapper_uuid)
        self.assertEqual(summary["peak_ram_bytes"], expected_peak)

        # Robust medians are part of the frozen method. Isolated baseline or
        # final-recovery noise must not become a hidden stricter gate.
        isolated_outlier = copy.deepcopy(trace)
        isolated_outlier["samples"][0]["mem_available_kib"] -= 10_000
        self.assertEqual(
            validate(
                isolated_outlier, source_sha=source_sha,
                mapper_uuid=mapper_uuid)["peak_ram_bytes"],
            expected_peak)
        for field, delta in (
                ("mem_available_kib", -1),
                ("s_unreclaim_kib", 1),
                ("vmalloc_used_kib", 1)):
            isolated_final = copy.deepcopy(trace)
            isolated_final["samples"][-1][field] += delta
            self.assertEqual(
                validate(
                    isolated_final, source_sha=source_sha,
                    mapper_uuid=mapper_uuid)["peak_ram_bytes"],
                expected_peak)

        def forged_middle_timestamp(damaged):
            sample = damaged["samples"][15]
            timestamp = datetime.datetime.fromisoformat(
                sample["timestamp_utc"].replace("Z", "+00:00"))
            sample["timestamp_utc"] = (
                timestamp + datetime.timedelta(milliseconds=80)
            ).isoformat(timespec="milliseconds").replace("+00:00", "Z")

        def duplicate_utc_at_tolerance_boundary(damaged):
            # Old validation accepted 0/200 ms UTC gaps paired with 50/150 ms
            # monotonic gaps because both cross-clock differences were exactly
            # the allowed 50 ms and the first/last spans were unchanged.
            previous = damaged["samples"][14]
            sample = damaged["samples"][15]
            sample["monotonic_ns"] = (
                previous["monotonic_ns"] + 50_000_000)
            sample["timestamp_utc"] = previous["timestamp_utc"]

        def persistent_memory_leak(damaged):
            for sample in damaged["samples"][-6:]:
                sample["mem_available_kib"] -= 1

        def baseline_outlier_cannot_hide_leak(damaged):
            damaged["samples"][0]["mem_available_kib"] -= 10_000
            persistent_memory_leak(damaged)

        def persistent_slab_leak(damaged):
            for sample in damaged["samples"][-6:]:
                sample["s_unreclaim_kib"] += 1

        def persistent_vmalloc_leak(damaged):
            for sample in damaged["samples"][-6:]:
                sample["vmalloc_used_kib"] += 1

        def missing_teardown(damaged):
            damaged["samples"].pop()

        for corrupt in (
                forged_middle_timestamp,
                duplicate_utc_at_tolerance_boundary,
                persistent_memory_leak,
                baseline_outlier_cannot_hide_leak,
                persistent_slab_leak,
                persistent_vmalloc_leak,
                missing_teardown):
            with self.subTest(corruption=corrupt.__name__):
                invalid = copy.deepcopy(trace)
                corrupt(invalid)
                with self.assertRaises(ValueError):
                    validate(invalid, source_sha=source_sha,
                             mapper_uuid=mapper_uuid)

    def test_selected_card_allocation_free_bytes_and_addressability(self):
        # Independently compute the current admission result and page-rounded
        # allocation footprint. These estimates exclude vmalloc metadata, PTEs,
        # slab/workqueue overhead and fixed scratch: NOT host RAM evidence.
        page = 4096
        partition_bytes = 124787884032
        total_blocks = partition_bytes // page
        physical = ((total_blocks - 1) // 256) * 256
        segments = physical // 256

        def reserve(logical_pages):
            return max((logical_pages + 7) // 8, 512)

        def admitted(logical_pages):
            available = ((physical - reserve(logical_pages)) // 256) * 256
            return logical_pages + 256 <= available

        self.assertEqual((physical, segments), (30465536, 119006))
        logical = 27080192
        self.assertTrue(admitted(logical))
        self.assertFalse(admitted(logical + 1))
        self.assertEqual(reserve(logical), 3385024)
        self.assertEqual(logical * page, 110920466432)
        self.assertEqual((logical - 1) * page, 110920462336)
        dimensions = {
            "logical": logical,
            "physical": physical,
            "ctx->segment_count": segments,
        }
        allocations = [
            (dimensions[scale] * width, name)
            for name, (scale, _, width) in self.INDEXES.items()
        ]
        self.assertEqual(sum(length for length, _ in allocations), 776070968)
        allocation_pages = [
            (length + page - 1) // page for length, _ in allocations]
        self.assertEqual(sum(allocation_pages) * page, 776114176)
        # Conservative leaf-PTE scale if every current capacity index is
        # vmalloc-backed and independently mapped. Upper-level vmalloc tables,
        # allocator metadata and any kmalloc/slab rounding remain host-measured.
        leaf_pte_pages = sum(
            (pages + 511) // 512 for pages in allocation_pages)
        self.assertEqual(leaf_pte_pages, 382)
        self.assertEqual(leaf_pte_pages * page, 1564672)
        self.assertEqual(max(allocations), (433283072, "maps"))
        self.assertEqual(len(allocations), 17)
        self.assertLess(logical * 16, (1 << 32))
        self.assertLess(physical * 2, (1 << 32))
        # At the top segment-aligned physical u32 geometry, 32-bit
        # addressability rejects liveness before attempting any allocation.
        self.assertGreater(0xffffff00 * 2, (1 << 32) - 1)
        self.assertGreater(3817748224 * 16, (1 << 32) - 1)
        self.assertIn("swapz_authority_validate_geometry(", constructor := body("swapz_ctr"))
        self.assertLess(constructor.index("swapz_authority_validate_geometry("),
                        constructor.index("ctx->maps = kvcalloc("))


if __name__ == "__main__":
    unittest.main(verbosity=2)
