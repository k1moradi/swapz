#!/usr/bin/env python3
import copy
import hashlib
import importlib.util
import json
import subprocess
import sys
import unittest
from unittest import mock
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[3]
EVALUATOR_PATH = ROOT / "tests/tools/evaluate-production-readiness.py"
SPEC = importlib.util.spec_from_file_location("swapz_release_eval", EVALUATOR_PATH)
EVALUATOR = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(EVALUATOR)

SOURCE = "a" * 40
HOST_ID = "9" * 64
KERNEL_RELEASE = "6.8.0-48-generic"
ARTIFACTS = {
    "formatter_sha256": "1" * 64,
    "module_sha256": "2" * 64,
    "oracle_sha256": "3" * 64,
}
TARGET = {"partuuid": "f13428f6-01", "size_bytes": 124787884032}


def acceptance_policy():
    # Synthetic tests must exercise the tracked frozen manifest, not a
    # partial policy that could silently drift from production.
    return json.loads(
        (ROOT / "docs/production-acceptance.json").read_text(encoding="utf-8"))


def encoded(value):
    # Qualification consumes the frozen file's canonical bytes, not an
    # equivalent reserialization with a different artifact digest.
    if (isinstance(value, dict) and
            value.get("schema") == "swapz-production-acceptance-v1"):
        frozen_raw = (
            ROOT / "docs/production-acceptance.json").read_bytes()
        if EVALUATOR._same_json_value(value, json.loads(frozen_raw)):
            return frozen_raw
    return (json.dumps(
        value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def cold_boot_arm_evidence_raw(**overrides):
    fields = {
        "schema": "swapz-primary-boot-arm-v1",
        "arm_boot_id": "11111111-1111-4111-8111-111111111111",
        "arm_kernel_release": KERNEL_RELEASE,
        "armed_epoch": "1",
        "expected_partuuid": TARGET["partuuid"],
        "expected_target_size_bytes": str(TARGET["size_bytes"]),
        "expected_target_model": "USB Multi-Card",
        "expected_target_serial": "reader-serial-1",
        "expected_target_wwn": "unavailable",
        "expected_target_transport": "usb",
        "expected_target_removable": "1",
        "expected_module_sha256": ARTIFACTS["module_sha256"],
        "expected_module_source_sha": SOURCE,
        "expected_module_source_clean": "1",
    }
    fields.update({key: str(value) for key, value in overrides.items()})
    return "".join(f"{key}={value}\n" for key, value in fields.items()).encode()


def cold_boot_evidence_raw(**overrides):
    fields = {
        "schema": "swapz-primary-cold-boot-v1",
        "status": "PASS",
        "cold_boot_observed": "yes",
        "boot_id": "22222222-2222-4222-8222-222222222222",
        "armed_boot_id": "11111111-1111-4111-8111-111111111111",
        "kernel_release": KERNEL_RELEASE,
        "selected_partuuid": TARGET["partuuid"],
        "selected_target_major_minor": "8:1",
        "selected_target_size_bytes": str(TARGET["size_bytes"]),
        "selected_target_parent": "sda",
        "selected_target_model": "USB Multi-Card",
        "selected_target_serial": "reader-serial-1",
        "selected_target_wwn": "unavailable",
        "selected_target_transport": "usb",
        "selected_target_removable": "1",
        "module_artifact": "/usr/local/libexec/swapz/dm-swapz.ko",
        "module_artifact_sha256": ARTIFACTS["module_sha256"],
        "module_build_source_sha": SOURCE,
        "module_build_source_clean": "1",
        "loaded_module_build_source_sha": SOURCE,
        "loaded_module_build_source_clean": "1",
        "active_transaction_run_id": "0123456789abcdef0123456789abcdef",
        "expected_dm_uuid":
            "SWAPZ-PRIMARY-0123456789abcdef0123456789abcdef",
        "dm_uuid": "SWAPZ-PRIMARY-0123456789abcdef0123456789abcdef",
        "dm_table": "0 216641536 swapz 8:1 0 64 0 2 0 1 0 0",
        "dm_logical_sectors": "216641536",
        "expected_dm_logical_sectors": "216641536",
        "dm_logical_bytes": "110920466432",
        "dm_status_file": "/var/lib/swapz/boot/report.dm-status.txt",
        "swap_total_entries": "2",
        "swap_mapper_entries": "1",
        "swap_path": "/dev/mapper/swapz-primary",
        "swap_type": "partition",
        "swap_size_kib": "108320764",
        "swap_used_kib": "0",
        "swap_priority": "-1",
        "mapper_service_active_state": "active",
        "mapper_service_sub_state": "exited",
        "mapper_service_result": "success",
        "swap_unit_active_state": "active",
        "swap_unit_sub_state": "active",
        "swap_unit_result": "success",
        "swapz_failed": "0",
        "swapz_error": "0",
        "swapz_flush_err": "0",
        "swapz_segment_discards_failed": "0",
        "swapz_upper_write_completed_err": "0",
        "swapz_endio_write_seen_err": "0",
        "swapz_endio_write_forced_err": "0",
        "kernel_error_count": "0",
        "kernel_error_log": "/var/lib/swapz/boot/report.kernel-errors.log",
        "failure_reasons": "",
        "incomplete_reasons": "",
    }
    fields.update({key: str(value) for key, value in overrides.items()})
    return "".join(f"{key}={value}\n" for key, value in fields.items()).encode()


def owner_report():
    return {
        "schema": "swapz-test-results-v1",
        "source_sha": SOURCE,
        "tested_commit_sha": SOURCE,
        "kernel_release": KERNEL_RELEASE,
        "host_identity": {
            "schema": "swapz-host-v1",
            "architecture": "x86_64",
            "id_sha256": HOST_ID,
        },
        "qualification": "RAM_BACKED_NULL_BLK_ONLY",
        "overall": "PASS",
        "qualified_artifacts": {
            "status": "AVAILABLE",
            **dict(ARTIFACTS),
        },
        "stages": [
            {"name": name, "status": "PASS", "exit_code": 0}
            for name in EVALUATOR.REQUIRED_STAGES
        ],
    }


def pass_record(**extra):
    return {
        "status": "PASS",
        "current": True,
        "source_sha": SOURCE,
        "observed_at_utc": "2026-11-03T00:00:12Z",
        **extra,
    }



def real_swap_workload(primary):
    # Rootless producer-shaped proof: two concurrent oracles, two complete
    # reuse rounds, independent swap/mapper/vmstat/lower-device counters.
    minimum_bytes = primary["minimum_swap_traffic_mib"] * 1048576
    page_bytes = primary["page_bytes"]
    verified_pages = primary["workload_mib"] * 1048576 // page_bytes
    worker_pages = verified_pages // 2
    worker_digests = ("1" * 64, "2" * 64)
    aggregate_digest = hashlib.sha256(b"".join(
        bytes.fromhex(value) for value in worker_digests)).hexdigest()
    verified = {
        "verified_pages": verified_pages,
        "verified_bytes": verified_pages * page_bytes,
        "mismatches": 0,
        "digest": aggregate_digest,
        "expected_digest": aggregate_digest,
    }
    physical_bytes = minimum_bytes // 2
    sectors = physical_bytes // 512
    rounds = []
    for round_index in (1, 2):
        worker_records = [{
            "pid": 101 + worker_index,
            "verified_pages": worker_pages,
            "verified_bytes": worker_pages * page_bytes,
            "mismatches": 0,
            "digest": digest,
            "expected_digest": digest,
        } for worker_index, digest in enumerate(worker_digests)]
        rounds.append({
            "round": round_index,
            "concurrent_workers": 2,
            "worker_pids": [101, 102],
            "worker_memory_mib": [primary["workload_mib"] // 2] * 2,
            "oracle_filled": [{
                "pid": record["pid"],
                "digest": record["digest"],
            } for record in worker_records],
            "oracle_verified": worker_records,
            "aggregate_verified": copy.deepcopy(verified),
            "cgroup_swap_current_bytes_after_fill": minimum_bytes,
            "cgroup_swap_peak_bytes": minimum_bytes,
            "mapper_used_start_kib": 0,
            "mapper_used_delta_kib": minimum_bytes // 1024,
            "swapz_logical_write_delta": minimum_bytes,
            "swapz_physical_write_delta": physical_bytes,
            "swapz_logical_read_delta": minimum_bytes,
            "swapz_physical_read_delta": physical_bytes,
            "lower_write_sector_delta": sectors,
            "lower_write_bytes_delta": sectors * 512,
            "lower_read_sector_delta": sectors,
            "lower_read_bytes_delta": sectors * 512,
            "pswpout_delta": minimum_bytes // page_bytes,
            "pswpin_delta": minimum_bytes // page_bytes,
            "oom_delta": 0,
            "oom_kill_delta": 0,
            "release_swap_current_bytes": 0,
            "mapper_used_released_kib": 0,
        })
    summed_fields = (
        "mapper_used_delta_kib",
        "swapz_logical_write_delta", "swapz_physical_write_delta",
        "swapz_logical_read_delta", "swapz_physical_read_delta",
        "lower_write_sector_delta", "lower_write_bytes_delta",
        "lower_read_sector_delta", "lower_read_bytes_delta",
        "pswpout_delta", "pswpin_delta", "oom_delta", "oom_kill_delta",
    )
    return {
        "concurrent_workers": 2,
        "reuse_rounds": 2,
        "slot_reuse_proven": True,
        "rounds": rounds,
        "cgroup_swap_peak_bytes": minimum_bytes,
        "cgroup_memory_pressure_some_usec": 0,
        **{name: sum(row[name] for row in rounds) for name in summed_fields},
    }


def real_swap_cycle(primary, index):
    run_id = f"{index + 1:032x}"
    return {
        "cycle": index + 1,
        "run_id": run_id,
        "mapper_uuid": "SWAPZ-PRIMARY-" + run_id,
        "mapper_device": "253:0",
        "linux_swap_uuid": f"00000000-0000-0000-0000-{index + 1:012x}",
        "swap_priority": -1,
        "workload": real_swap_workload(primary),
        "stop_order": {
            "initial_active": True,
            "swapoff_before_remove_witness": True,
            "final_absent": True,
            "samples": 42,
        },
        "fresh_mapper_used_kib": 0,
        "durable_final_stage": "COMPLETE",
    }


def real_swap_result(report_raw, policy_raw):
    policy = json.loads(policy_raw)
    primary = policy["primary_real_swap"]
    return {
        "schema": "swapz-primary-real-swap-v1",
        "status": "PASS",
        "source_sha": SOURCE,
        "acceptance_manifest_sha256": hashlib.sha256(policy_raw).hexdigest(),
        "helper_sha256": hashlib.sha256(
            EVALUATOR.REAL_SWAP_HELPER.read_bytes()).hexdigest(),
        "oracle_sha256": hashlib.sha256(
            EVALUATOR.REAL_SWAP_ORACLE.read_bytes()).hexdigest(),
        "qualification_report_sha256": hashlib.sha256(report_raw).hexdigest(),
        "qualified_installed_artifacts": dict(ARTIFACTS),
        "physical_execution_control_sha256": "4" * 64,
        "installed_control_privileged_execution_enabled": False,
        "partuuid": TARGET["partuuid"],
        "target_size_bytes": TARGET["size_bytes"],
        "target_device": "8:1",
        "cycles_requested": primary["cycles"],
        "cycles_passed": primary["cycles"],
        "workload_mib": primary["workload_mib"],
        "resident_limit_mib": primary["resident_mib"],
        "swap_limit_mib": primary["swap_limit_mib"],
        "timeout_seconds": primary["timeout_seconds"],
        "concurrent_oracles": 2,
        "reuse_rounds_per_cycle": 2,
        "evidence_path": "/var/lib/swapz/physical-recovery/test.json",
        "cycles": [
            real_swap_cycle(primary, index)
            for index in range(primary["cycles"])
        ],
    }


def real_swap_evidence(report_raw, policy_raw):
    result = real_swap_result(report_raw, policy_raw)
    envelope_keys = (
        "source_sha", "acceptance_manifest_sha256",
        "qualification_report_sha256", "helper_sha256", "oracle_sha256",
        "qualified_installed_artifacts", "physical_execution_control_sha256",
        "installed_control_privileged_execution_enabled",
        "partuuid", "target_size_bytes", "target_device",
        "cycles_requested", "workload_mib",
        "resident_limit_mib", "swap_limit_mib", "timeout_seconds",
        "concurrent_oracles", "reuse_rounds_per_cycle", "cycles",
    )
    return {
        "schema": "swapz-primary-real-swap-evidence-v1",
        "attempt_id": "f" * 32,
        "status": "PASS",
        "reason": None,
        "phase": "COMPLETE",
        "started_unix_ns": 1,
        "updated_unix_ns": 2,
        **{key: copy.deepcopy(result[key]) for key in envelope_keys},
        "result": result,
    }


def campaign_artifact(name, byte):
    return {
        "name": name,
        "size_bytes": 1,
        "sha256": byte * 64,
    }


def sampled_metadata_ram_trace(peak_ram_bytes=900 * 1024 * 1024):
    # Rootless fixture only. Real RAM must come from the serialized loaded host.
    if peak_ram_bytes % 1024:
        raise ValueError("synthetic RAM peak must be KiB-aligned")
    baseline_available_kib = 8 * 1024 * 1024
    baseline_s_unreclaim_kib = 100 * 1024
    baseline_vmalloc_kib = 200 * 1024
    phase_values = (
        ("baseline", [0] * 11, False),
        ("initialization", [200 * 1024, 400 * 1024], True),
        ("steady", [600 * 1024, 800 * 1024], True),
        ("gc", [peak_ram_bytes // 1024, 850 * 1024], True),
        ("teardown", [850 * 1024] + [0] * 21, None),
    )
    samples = []
    for phase, deltas_kib, mapper_present in phase_values:
        for phase_index, delta_kib in enumerate(deltas_kib):
            index = len(samples) + 1
            seconds, tenths = divmod(index, 10)
            present = (
                phase_index > 0 if phase == "initialization" else
                phase_index == 0 if phase == "teardown" else mapper_present)
            samples.append({
                "phase": phase,
                "monotonic_ns": index * 100_000_000,
                "timestamp_utc":
                    f"2026-11-03T00:00:{seconds:02d}.{tenths}Z",
                "mem_available_kib": baseline_available_kib - delta_kib,
                "s_unreclaim_kib": (
                    baseline_s_unreclaim_kib +
                    (delta_kib // 8 if present else 0)),
                "vmalloc_used_kib": (
                    baseline_vmalloc_kib +
                    (delta_kib // 16 if present else 0)),
                "mapper_present": present,
            })
    return {
        "schema": "swapz-metadata-ram-samples-v1",
        "capture": "serialized-loaded-host",
        "scope": "whole-host-conservative-metadata-and-target-ram",
        "source_sha": SOURCE,
        "mapper_uuid": "SWAPZ-PRIMARY-" + "f" * 32,
        "host_boot_id": "11111111-1111-4111-8111-111111111111",
        "sampling_interval_ns": 100_000_000,
        "meminfo_unit": "kB",
        "samples": samples,
    }

def reseal_synthetic_ram_trace_artifact(campaign):
    """Refresh only the synthetic trace digest; never impersonate host capture."""
    trace = campaign["capacity_and_ram"]["metadata_ram_trace"]
    canonical = (json.dumps(trace, indent=2, sort_keys=True) + "\n").encode()
    campaign["artifacts"]["metadata_ram_trace"] = {
        "name": "metadata-ram-trace.json",
        "size_bytes": len(canonical),
        "sha256": hashlib.sha256(canonical).hexdigest(),
    }


def physical_campaign_evidence(policy_raw):
    trace = sampled_metadata_ram_trace()
    ram_summary = EVALUATOR.RAM_TRACE_VALIDATOR[
        "validate_metadata_ram_trace"](
            trace, source_sha=SOURCE,
            mapper_uuid="SWAPZ-PRIMARY-" + "f" * 32,
            expected_peak_ram_bytes=900 * 1024 * 1024)
    return {
        "schema": "swapz-performance-campaign-evidence-v1",
        "sealed_at_utc": "2026-11-03T00:00:11+00:00",
        "source_sha": SOURCE,
        "source_tree_sha": "b" * 40,
        "campaign_source_sha": SOURCE,
        "pair_source_shas": [SOURCE],
        "source_consistent": True,
        "arm_boot_consistent": True,
        "physical_evidence_audit": {
            "status": "PASS",
            "diagnostics": [],
            "omitted_diagnostic_count": 0,
            "claim_boundary": json.loads(policy_raw)[
                "physical_qualification"]["claim_boundary"],
            "measurement_authority": "host-visible lower I/O, not NAND wear",
        },
        "campaign_status": "PASS",
        "qualification_status": "PASS",
        "evaluation_protocol": "v2",
        "target": {
            "partuuid": TARGET["partuuid"],
            "device_bytes": TARGET["size_bytes"],
        },
        "qualification_target_binding": {
            "status": "MATCH",
            "consistent": True,
            "expected": {
                "physical_partuuid": TARGET["partuuid"],
                "physical_device_bytes": TARGET["size_bytes"],
                "lower_major_minor": "8:1",
            },
            "observed": {
                "physical_partuuid": TARGET["partuuid"],
                "physical_device_bytes": TARGET["size_bytes"],
                "lower_major_minor": "8:1",
            },
        },
        "capacity_and_ram": {
            "page_bytes": 4096,
            "logical_pages": 27080192,
            "logical_capacity_bytes": 110920466432,
            "peak_ram_bytes": 900 * 1024 * 1024,
            "mapper_uuid": "SWAPZ-PRIMARY-" + "f" * 32,
            "metadata_ram_trace": trace,
            "metadata_ram_summary": ram_summary,
            "metadata_ram_arm_binding": {
                "arm_started_monotonic_ns": 1_300_000_000,
                "arm_finished_monotonic_ns": 1_700_000_000,
                "gc_activity_intervals": [{
                    "start_monotonic_ns": 1_500_000_000,
                    "end_monotonic_ns": 1_700_000_000,
                    "gc_wall_ns": 1,
                    "gc_victims": 1,
                    "gc_pages": 1,
                }],
            },
            "metadata_ram_host_binding": {
                "host_boot_id":
                    "11111111-1111-4111-8111-111111111111",
                "host_before_captured_at_utc":
                    "2026-11-03T00:00:00+00:00",
                "host_after_captured_at_utc":
                    "2026-11-03T00:00:10+00:00",
                "memory_total_bytes": 16 * 1024 * 1024 * 1024,
            },
        },
        "host_stability": {
            "status": "STABLE",
            "checks": {
                "source_sha": True,
                "source_tree_sha": True,
                "admitted_device_quiescent_before": True,
                "admitted_device_quiescent_after": True,
            },
            "failed_checks": [],
        },
        "admitted_device_boundary": {
            "before": {"quiescent": True},
            "after": {"quiescent": True},
        },
        "policy": {
            "acceptance_manifest": {
                "name": "production-acceptance.json",
                "sha256": hashlib.sha256(policy_raw).hexdigest(),
            },
            "prospective_amendment": {
                "name": EVALUATOR.PHYSICAL_CAMPAIGN_AMENDMENT.name,
                "sha256": hashlib.sha256(
                    EVALUATOR.PHYSICAL_CAMPAIGN_AMENDMENT.read_bytes()
                ).hexdigest(),
            },
            "evaluator": {
                "name": EVALUATOR.PHYSICAL_CAMPAIGN_EVALUATOR.name,
                "sha256": hashlib.sha256(
                    EVALUATOR.PHYSICAL_CAMPAIGN_EVALUATOR.read_bytes()
                ).hexdigest(),
            },
            "evidence_sealer": {
                "name": EVALUATOR.PHYSICAL_CAMPAIGN_SEALER.name,
                "sha256": hashlib.sha256(
                    EVALUATOR.PHYSICAL_CAMPAIGN_SEALER.read_bytes()
                ).hexdigest(),
            },
            "metadata_ram_validator": {
                "name": EVALUATOR.METADATA_RAM_VALIDATOR.name,
                "sha256": hashlib.sha256(
                    EVALUATOR.METADATA_RAM_VALIDATOR.read_bytes()
                ).hexdigest(),
            },
        },
        "artifacts": {
            "metadata_ram_trace": {
                "name": "metadata-ram-trace.json",
                "size_bytes": len((
                    json.dumps(trace,
                               indent=2, sort_keys=True) + "\n").encode()),
                "sha256": hashlib.sha256((
                    json.dumps(trace,
                               indent=2, sort_keys=True) + "\n").encode()
                ).hexdigest(),
            },
            "host_before": campaign_artifact("host-before.json", "4"),
            "host_after": campaign_artifact("host-after.json", "5"),
            "qualification_summary": campaign_artifact("summary.json", "6"),
            "pairs": [
                {
                    **campaign_artifact(
                        f"{workload}-{pair_index}.json",
                        "0123456789abcdef"[artifact_index]),
                    "workload": workload,
                    "pair_id": f"{workload}-{pair_index}",
                    "pair_index": pair_index,
                    "order": specification["counterbalanced_order"][pair_index - 1],
                    "status": "PASS",
                    "excluded": False,
                }
                for artifact_index, (workload, specification, pair_index) in
                enumerate(
                    (workload, specification, pair_index)
                    for workload, specification in
                    json.loads(policy_raw)["physical_qualification"]["workloads"].items()
                    for pair_index in range(1, specification["pairs"] + 1))
            ],
        },
        "record_count": sum(
            specification["pairs"] for specification in
            json.loads(policy_raw)["physical_qualification"]["workloads"].values()),
    }


def current_evidence(
        report_raw, policy_raw, physical_raw=None, campaign_raw=None,
        cold_boot_arm_raw=None):
    policy_digest = hashlib.sha256(policy_raw).hexdigest()
    report_digest = hashlib.sha256(report_raw).hexdigest()
    if physical_raw is None:
        physical_raw = encoded(real_swap_evidence(report_raw, policy_raw))
    if campaign_raw is None:
        campaign_raw = encoded(physical_campaign_evidence(policy_raw))
    if cold_boot_arm_raw is None:
        cold_boot_arm_raw = cold_boot_arm_evidence_raw()
    return {
        "schema": "swapz-production-readiness-v2",
        "snapshot_kind": "CURRENT",
        "host": {
            "architecture": "x86_64",
            "kernel_release": KERNEL_RELEASE,
            "page_size_bytes": 4096,
        },
        "repository": {
            "branch": "main",
            "local_sha": SOURCE,
            "origin_main_sha": SOURCE,
            "production_source_sha": SOURCE,
            "synchronized": True,
        },
        "authorized_target": dict(TARGET),
        "release_evidence": {
            "production_source": pass_record(),
            "clean_build_state": pass_record(clean=True),
            "qualified_artifact_hashes": pass_record(
                qualified=True, hashes=dict(ARTIFACTS)),
            "required_ci": pass_record(runs=[
                {
                    "workflow": workflow,
                    "head_sha": SOURCE,
                    "result": "PASS",
                    "status": "completed",
                    "conclusion": "success",
                    "run_id": str(index + 1),
                }
                for index, workflow in enumerate(
                    EVALUATOR.REQUIRED_CI_WORKFLOWS)
            ]),
            "exact_source_owner_make_test": pass_record(
                overall="PASS",
                tested_source_sha=SOURCE,
                report_sha256=report_digest,
                hashes=dict(ARTIFACTS)),
            "owned_nullblk_qualification": pass_record(
                overall="PASS", evidence_sha256="5" * 64,
                hashes=dict(ARTIFACTS)),
            "unresolved_critical_issues": pass_record(
                count=0, issues=[]),
            "real_linux_swap": pass_record(
                policy_sha256=policy_digest,
                target=dict(TARGET),
                hashes=dict(ARTIFACTS),
                evidence_sha256=hashlib.sha256(physical_raw).hexdigest()),
            "maximum_capacity_and_ram": pass_record(
                policy_sha256=policy_digest,
                target=dict(TARGET),
                logical_capacity_bytes=110920466432,
                peak_ram_bytes=900 * 1024 * 1024,
                evidence_sha256=hashlib.sha256(campaign_raw).hexdigest()),
            "sustained_physical_performance": pass_record(
                policy_sha256=policy_digest,
                target=dict(TARGET),
                evidence_sha256=hashlib.sha256(campaign_raw).hexdigest()),
            "lifecycle_deployment_state": pass_record(
                target=dict(TARGET), overall="PASS",
                lifecycle="PASS", deployment="PASS",
                evidence_sha256="6" * 64),
            "installed_artifact_identity": pass_record(
                target=dict(TARGET),
                installed=True,
                hashes=dict(ARTIFACTS)),
            "cold_boot_harness": pass_record(
                target=dict(TARGET),
                armed=True,
                evidence_sha256=hashlib.sha256(
                    cold_boot_arm_raw).hexdigest()),
            "owner_observed_reboot": {
                "status": "BLOCKED",
                "current": True,
                "source_sha": SOURCE,
                "observed_at_utc": "2026-11-03T00:00:00Z",
                "target": dict(TARGET),
                "observed": False,
                "overall": "BLOCKED",
            },
        },
    }


_AUTO_ARM = object()


def evaluate(
        report=None, evidence=None, policy=None, physical=None,
        campaign=None, cold_boot_raw=None, cold_boot_arm_raw=_AUTO_ARM):
    report = owner_report() if report is None else report
    policy = acceptance_policy() if policy is None else policy
    report_raw = encoded(report)
    policy_raw = encoded(policy)
    physical = (
        real_swap_evidence(report_raw, policy_raw)
        if physical is None else physical)
    physical_raw = encoded(physical)
    campaign = (
        physical_campaign_evidence(policy_raw)
        if campaign is None else campaign)
    campaign_raw = encoded(campaign)
    if cold_boot_arm_raw is _AUTO_ARM:
        cold_boot_arm_raw = cold_boot_arm_evidence_raw()
    if evidence is None:
        evidence = current_evidence(
            report_raw, policy_raw, physical_raw, campaign_raw,
            cold_boot_arm_raw)
    cold_boot_arm = (
        None if cold_boot_arm_raw is None
        else EVALUATOR.parse_env_strict(cold_boot_arm_raw))
    cold_boot = (
        None if cold_boot_raw is None
        else EVALUATOR.parse_env_strict(cold_boot_raw))
    return EVALUATOR.evaluate_release(
        SOURCE, report, report_raw, evidence, policy, policy_raw,
        physical, physical_raw, campaign, campaign_raw,
        cold_boot, cold_boot_raw, cold_boot_arm, cold_boot_arm_raw)


class ProductionReadinessEvaluatorTest(unittest.TestCase):
    def test_complete_pre_reboot_evidence_passes_both_readiness_gates(self):
        result = evaluate()
        self.assertEqual(result["CODE_PRODUCTION_READY"], "PASS")
        self.assertEqual(result["DEPLOYMENT_PRODUCTION_READY"], "PASS")
        self.assertEqual(result["PRODUCTION_READY_FOR_OWNER_REBOOT"], "PASS")
        self.assertEqual(result["COLD_BOOT_HARNESS"], "ARMED")
        self.assertEqual(result["COLD_BOOT_OBSERVED"], "NO")
        self.assertEqual(result["release_verdict"], "BLOCKED")
        self.assertEqual(result["code_blockers"], [])
        self.assertEqual(result["deployment_blockers"], [])

    def test_release_kernel_must_match_owner_qualification(self):
        report = owner_report()
        report["kernel_release"] = "6.8.0-49-generic"
        result = evaluate(report=report)
        self.assertEqual(result["CODE_PRODUCTION_READY"], "BLOCKED")
        self.assertIn(
            "release host kernel does not match owner qualification",
            result["code_blockers"])

    def test_release_host_platform_is_fail_closed(self):
        report = owner_report()
        policy = acceptance_policy()
        for page_size_bytes in (65536, 4096.0):
            with self.subTest(page_size_bytes=page_size_bytes):
                evidence = current_evidence(encoded(report), encoded(policy))
                evidence["host"]["page_size_bytes"] = page_size_bytes
                result = evaluate(report, evidence, policy)
                self.assertEqual(result["CODE_PRODUCTION_READY"], "BLOCKED")
                self.assertIn(
                    "release host page size is unsupported",
                    result["code_blockers"])

    def test_owner_reboot_readiness_requires_exact_durable_arm_record(self):
        report = owner_report()
        policy = acceptance_policy()
        evidence = current_evidence(encoded(report), encoded(policy))

        missing = evaluate(
            report, evidence, policy, cold_boot_arm_raw=None)
        self.assertEqual(
            missing["DEPLOYMENT_PRODUCTION_READY"], "BLOCKED")
        self.assertEqual(missing["PRODUCTION_READY_FOR_OWNER_REBOOT"], "NO")
        self.assertTrue(any(
            "persistent arm evidence is missing" in blocker
            for blocker in missing["deployment_blockers"]))

        wrong = cold_boot_arm_evidence_raw(
            expected_module_source_sha="b" * 40)
        evidence = current_evidence(
            encoded(report), encoded(policy), cold_boot_arm_raw=wrong)
        result = evaluate(
            report, evidence, policy, cold_boot_arm_raw=wrong)
        self.assertEqual(result["DEPLOYMENT_PRODUCTION_READY"], "BLOCKED")
        self.assertTrue(any(
            "arm module source binding is invalid" in blocker
            for blocker in result["deployment_blockers"]))

    def test_invalid_arm_cannot_authenticate_cold_boot_pass(self):
        report = owner_report()
        policy = acceptance_policy()
        invalid_arm_raw = cold_boot_arm_evidence_raw(
            expected_module_source_sha="b" * 40)
        cold_raw = cold_boot_evidence_raw()
        evidence = current_evidence(
            encoded(report), encoded(policy),
            cold_boot_arm_raw=invalid_arm_raw)
        evidence["release_evidence"]["owner_observed_reboot"].update(
            status="PASS", observed=True, overall="PASS",
            evidence_sha256=hashlib.sha256(cold_raw).hexdigest())
        result = evaluate(
            report, evidence, policy, cold_boot_raw=cold_raw,
            cold_boot_arm_raw=invalid_arm_raw)
        self.assertEqual(result["DEPLOYMENT_PRODUCTION_READY"], "BLOCKED")
        self.assertEqual(result["COLD_BOOT_OBSERVED"], "NO")
        self.assertEqual(result["release_verdict"], "BLOCKED")
        self.assertTrue(any(
            "no validated arm record" in blocker
            for blocker in result["cold_boot_blockers"]))

    def test_cold_boot_report_is_cross_bound_to_exact_arm_record(self):
        report = owner_report()
        policy = acceptance_policy()
        arm_raw = cold_boot_arm_evidence_raw()
        cold_raw = cold_boot_evidence_raw(
            armed_boot_id="33333333-3333-4333-8333-333333333333")
        evidence = current_evidence(
            encoded(report), encoded(policy), cold_boot_arm_raw=arm_raw)
        evidence["release_evidence"]["owner_observed_reboot"].update(
            status="PASS", observed=True, overall="PASS",
            evidence_sha256=hashlib.sha256(cold_raw).hexdigest())
        result = evaluate(
            report, evidence, policy, cold_boot_raw=cold_raw,
            cold_boot_arm_raw=arm_raw)
        self.assertEqual(result["release_verdict"], "BLOCKED")
        self.assertTrue(any(
            "not bound to the arm boot" in blocker
            for blocker in result["cold_boot_blockers"]))

    def test_owner_reboot_is_separate_from_code_and_deployment_readiness(self):
        report = owner_report()
        policy = acceptance_policy()
        evidence = current_evidence(encoded(report), encoded(policy))
        reboot = evidence["release_evidence"]["owner_observed_reboot"]
        cold_boot_raw = cold_boot_evidence_raw()
        reboot.update(
            status="PASS", observed=True, overall="PASS",
            evidence_sha256=hashlib.sha256(cold_boot_raw).hexdigest())
        result = evaluate(
            report, evidence, policy, cold_boot_raw=cold_boot_raw)
        self.assertEqual(result["CODE_PRODUCTION_READY"], "PASS")
        self.assertEqual(result["DEPLOYMENT_PRODUCTION_READY"], "PASS")
        self.assertEqual(result["COLD_BOOT_OBSERVED"], "PASS")
        self.assertEqual(result["cold_boot_blockers"], [])
        self.assertEqual(result["release_verdict"], "PASS")

        reboot.update(status="FAIL", observed=True, overall="FAIL")
        result = evaluate(report, evidence, policy)
        self.assertEqual(result["CODE_PRODUCTION_READY"], "PASS")
        self.assertEqual(result["DEPLOYMENT_PRODUCTION_READY"], "PASS")
        self.assertEqual(result["COLD_BOOT_OBSERVED"], "FAIL")
        self.assertEqual(result["release_verdict"], "FAIL")

    def test_current_owner_reboot_failure_dominates_stale_readiness(self):
        report = owner_report()
        policy = acceptance_policy()
        evidence = current_evidence(encoded(report), encoded(policy))
        evidence["release_evidence"]["installed_artifact_identity"][
            "installed"] = False
        evidence["release_evidence"]["owner_observed_reboot"].update(
            status="FAIL", observed=True, overall="FAIL")
        result = evaluate(report, evidence, policy)
        self.assertEqual(result["CODE_PRODUCTION_READY"], "PASS")
        self.assertEqual(result["DEPLOYMENT_PRODUCTION_READY"], "BLOCKED")
        self.assertEqual(result["COLD_BOOT_OBSERVED"], "FAIL")
        self.assertEqual(result["release_verdict"], "FAIL")

    def test_owner_reboot_pass_requires_persistent_cold_boot_evidence(self):
        report = owner_report()
        policy = acceptance_policy()
        evidence = current_evidence(encoded(report), encoded(policy))
        reboot = evidence["release_evidence"]["owner_observed_reboot"]
        cold_boot_raw = cold_boot_evidence_raw()
        reboot.update(
            status="PASS", observed=True, overall="PASS",
            evidence_sha256=hashlib.sha256(cold_boot_raw).hexdigest())

        missing = evaluate(report, evidence, policy)
        self.assertEqual(missing["CODE_PRODUCTION_READY"], "PASS")
        self.assertEqual(missing["DEPLOYMENT_PRODUCTION_READY"], "PASS")
        self.assertEqual(missing["COLD_BOOT_OBSERVED"], "NO")
        self.assertEqual(missing["release_verdict"], "BLOCKED")
        self.assertTrue(any(
            "persistent cold-boot evidence is missing" in blocker
            for blocker in missing["cold_boot_blockers"]))

        reboot["evidence_sha256"] = "f" * 64
        mismatched = evaluate(
            report, evidence, policy, cold_boot_raw=cold_boot_raw)
        self.assertEqual(mismatched["COLD_BOOT_OBSERVED"], "NO")
        self.assertEqual(mismatched["release_verdict"], "BLOCKED")
        self.assertTrue(any(
            "evidence digest mismatch" in blocker
            for blocker in mismatched["cold_boot_blockers"]))

    def test_cold_boot_evidence_is_fail_closed_on_identity_and_errors(self):
        report = owner_report()
        policy = acceptance_policy()
        for label, overrides, reason in (
                ("source", {"loaded_module_build_source_sha": "b" * 40},
                 "module source binding"),
                ("target", {"selected_target_size_bytes":
                            str(TARGET["size_bytes"] + 4096)},
                 "authorized target identity"),
                ("capacity", {
                    "dm_logical_sectors": "216641528",
                    "expected_dm_logical_sectors": "216641528",
                    "dm_logical_bytes": "110920462336",
                    "swap_size_kib": "108320760",
                }, "capacity differs from authorized target"),
                ("errors", {"swapz_error": "5"}, "runtime error evidence")):
            with self.subTest(label=label):
                raw = cold_boot_evidence_raw(**overrides)
                evidence = current_evidence(encoded(report), encoded(policy))
                evidence["release_evidence"]["owner_observed_reboot"].update(
                    status="PASS", observed=True, overall="PASS",
                    evidence_sha256=hashlib.sha256(raw).hexdigest())
                result = evaluate(
                    report, evidence, policy, cold_boot_raw=raw)
                self.assertEqual(result["COLD_BOOT_OBSERVED"], "NO")
                self.assertEqual(result["release_verdict"], "BLOCKED")
                self.assertTrue(any(
                    reason in blocker
                    for blocker in result["cold_boot_blockers"]))

    def test_cold_boot_evidence_parser_rejects_duplicate_keys(self):
        canonical_raw = cold_boot_evidence_raw()
        for key, suffix in (
                ("status", b"status=FAIL\n"),
                ("unrecognized_key",
                 b"unrecognized_key=1\nunrecognized_key=2\n")):
            with self.subTest(key=key):
                with self.assertRaises(EVALUATOR.EvidenceError) as rejected:
                    EVALUATOR.parse_env_strict(canonical_raw + suffix)
                self.assertEqual(
                    str(rejected.exception),
                    f"duplicate cold-boot evidence key: {key!r}")

    def test_cold_boot_evidence_parser_rejects_invalid_keys(self):
        canonical_raw = cold_boot_evidence_raw()
        line_number = canonical_raw.count(b"\n") + 1
        for suffix, reason in (
                (b"=value\n", "has invalid key"),
                (b"Status=value\n", "has invalid key"),
                (b"1status=value\n", "has invalid key"),
                (b"bad-key=value\n", "has invalid key"),
                (b"bad key=value\n", "has invalid key"),
                (b"bad/path=/private/source/secret\n", "has invalid key"),
                (b"bad\xc3\xa9=value\n", "has invalid key"),
                (b"bad\x00key=value\n", "has invalid key"),
                (b"missing_equals\n", "is malformed")):
            with self.subTest(suffix=suffix[:24]):
                with self.assertRaises(EVALUATOR.EvidenceError) as rejected:
                    EVALUATOR.parse_env_strict(canonical_raw + suffix)
                diagnostic = str(rejected.exception)
                self.assertEqual(
                    diagnostic, f"cold-boot evidence line {line_number} {reason}")
                self.assertNotIn("/private/source/secret", diagnostic)
                self.assertLess(len(diagnostic), 160)

    def test_cold_boot_evidence_parser_bounds_identifiers_and_errors(self):
        canonical_raw = cold_boot_evidence_raw()
        oversized_key = "unrecognized_" + "x" * 4096
        private_path = "/private/source/secret-evidence.txt"
        for suffix, expected in (
                (f"{oversized_key}=1\n{oversized_key}=2\n".encode("ascii"),
                 "duplicate cold-boot evidence key: "
                 f"{oversized_key[:80]!r} (truncated)"),
                (f"status={private_path}\n".encode("ascii"),
                 "duplicate cold-boot evidence key: 'status'")):
            with self.subTest(expected=expected):
                with self.assertRaises(EVALUATOR.EvidenceError) as rejected:
                    EVALUATOR.parse_env_strict(canonical_raw + suffix)
                diagnostic = str(rejected.exception)
                self.assertEqual(diagnostic, expected)
                self.assertLess(len(diagnostic), 160)
                self.assertNotIn(oversized_key[80:], diagnostic)
                self.assertNotIn(private_path, diagnostic)

        for invalid_input in (
                None, "", b"", bytearray(b"status=PASS\n"),
                memoryview(b"status=PASS\n")):
            with self.subTest(input_type=type(invalid_input).__name__):
                with self.assertRaises(EVALUATOR.EvidenceError) as rejected:
                    EVALUATOR.parse_env_strict(invalid_input)
                self.assertEqual(
                    str(rejected.exception),
                    "cold-boot evidence bytes are empty or invalid")

        with self.assertRaises(EVALUATOR.EvidenceError) as rejected:
            EVALUATOR.parse_env_strict(
                b"x" * (EVALUATOR.MAX_ENV_EVIDENCE_INPUT_BYTES + 1))
        self.assertEqual(
            str(rejected.exception),
            "cold-boot evidence exceeds 1048576-byte input bound")

    def test_cold_boot_report_rejects_missing_unknown_and_oversized_keys(self):
        report = owner_report()
        policy = acceptance_policy()
        canonical_raw = cold_boot_evidence_raw()
        for label, raw in (
                ("unknown", canonical_raw + b"unrecognized_key=PASS\n"),
                ("oversized", canonical_raw +
                 ("unrecognized_" + "x" * 4096 + "=PASS\n").encode("ascii")),
                ("missing", canonical_raw.replace(
                    b"swap_used_kib=0\n", b"", 1))):
            with self.subTest(label=label):
                evidence = current_evidence(encoded(report), encoded(policy))
                evidence["release_evidence"]["owner_observed_reboot"].update(
                    status="PASS", observed=True, overall="PASS",
                    evidence_sha256=hashlib.sha256(raw).hexdigest())
                result = evaluate(
                    report, evidence, policy, cold_boot_raw=raw)
                self.assertEqual(result["COLD_BOOT_OBSERVED"], "NO")
                self.assertEqual(result["release_verdict"], "BLOCKED")
                self.assertIn(
                    "owner_observed_reboot: persistent cold-boot report "
                    "field set is non-canonical",
                    result["cold_boot_blockers"])

    def test_cold_boot_report_field_set_and_dm_table_are_exact(self):
        report = owner_report()
        policy = acceptance_policy()
        for raw, reason in (
                (cold_boot_evidence_raw(unexpected="value"),
                 "field set is non-canonical"),
                (cold_boot_evidence_raw(
                    dm_table="0 216641536 swapz 8:2 0 64 0 2 0 1 0 0"),
                 "mapper table is inconsistent"),
                (cold_boot_evidence_raw(
                    selected_target_serial="unavailable",
                    selected_target_wwn="unavailable"),
                 "removable parent identity is invalid")):
            with self.subTest(reason=reason):
                evidence = current_evidence(encoded(report), encoded(policy))
                evidence["release_evidence"]["owner_observed_reboot"].update(
                    status="PASS", observed=True, overall="PASS",
                    evidence_sha256=hashlib.sha256(raw).hexdigest())
                result = evaluate(
                    report, evidence, policy, cold_boot_raw=raw)
                self.assertEqual(result["release_verdict"], "BLOCKED")
                self.assertTrue(any(
                    reason in blocker
                    for blocker in result["cold_boot_blockers"]))

    def test_historical_or_unsynchronized_source_cannot_pass(self):
        report = owner_report()
        policy = acceptance_policy()
        evidence = current_evidence(encoded(report), encoded(policy))
        evidence["snapshot_kind"] = "HISTORICAL"
        evidence["repository"]["origin_main_sha"] = "b" * 40
        result = evaluate(report, evidence, policy)
        self.assertEqual(result["CODE_PRODUCTION_READY"], "BLOCKED")
        self.assertTrue(any(
            "historical" in blocker for blocker in result["code_blockers"]))
        self.assertTrue(any(
            "frozen on synchronized main" in blocker
            for blocker in result["code_blockers"]))

    def test_current_pass_records_require_auditable_utc_timestamp(self):
        report = owner_report()
        policy = acceptance_policy()
        evidence = current_evidence(encoded(report), encoded(policy))
        del evidence["release_evidence"]["clean_build_state"]["observed_at_utc"]
        result = evaluate(report, evidence, policy)
        self.assertEqual(result["CODE_PRODUCTION_READY"], "BLOCKED")
        self.assertTrue(any(
            "observation timestamp" in blocker
            for blocker in result["code_blockers"]))

        evidence = current_evidence(encoded(report), encoded(policy))
        evidence["release_evidence"]["clean_build_state"][
            "observed_at_utc"] = "2026-11-03 00:00:00"
        result = evaluate(report, evidence, policy)
        self.assertEqual(result["CODE_PRODUCTION_READY"], "BLOCKED")

    def test_required_ci_pass_requires_concrete_run_ids(self):
        report = owner_report()
        policy = acceptance_policy()
        evidence = current_evidence(encoded(report), encoded(policy))
        del evidence["release_evidence"]["required_ci"]["runs"][0]["run_id"]
        result = evaluate(report, evidence, policy)
        self.assertEqual(result["CODE_PRODUCTION_READY"], "BLOCKED")
        self.assertTrue(any(
            "concrete run ID" in blocker
            for blocker in result["code_blockers"]))

    def test_required_ci_run_id_validation_is_nonthrowing_and_ascii(self):
        self.assertFalse(EVALUATOR._valid_run_id("0" * 5000))
        self.assertFalse(EVALUATOR._valid_run_id("9" * 5000))
        self.assertFalse(EVALUATOR._valid_run_id(1 << 63))
        self.assertFalse(EVALUATOR._valid_run_id("9223372036854775808"))
        self.assertFalse(EVALUATOR._valid_run_id("01"))
        self.assertFalse(EVALUATOR._valid_run_id("١"))
        self.assertTrue(EVALUATOR._valid_run_id("123456789"))
        self.assertTrue(EVALUATOR._valid_run_id((1 << 63) - 1))

    def test_cancelled_or_pending_ci_never_satisfies_release_readiness(self):
        report = owner_report()
        policy = acceptance_policy()
        for field, value in (
                ("status", "queued"),
                ("status", "in_progress"),
                ("status", "cancelled"),
                ("conclusion", "cancelled"),
                ("conclusion", "failure"),
                ("conclusion", None),
                ("status", None)):
            evidence = current_evidence(encoded(report), encoded(policy))
            evidence["release_evidence"]["required_ci"]["runs"][0][field] = value
            result = evaluate(report, evidence, policy)
            self.assertEqual(result["CODE_PRODUCTION_READY"], "BLOCKED",
                             (field, value, result))
            self.assertTrue(any(
                "completed-success" in blocker
                for blocker in result["code_blockers"]), (field, value))

    def test_required_ci_rejects_duplicate_run_ids_and_extra_rows(self):
        report = owner_report()
        policy = acceptance_policy()
        for mutation in ("shared_run_id", "extra_workflow", "malformed_row"):
            with self.subTest(mutation=mutation):
                evidence = current_evidence(encoded(report), encoded(policy))
                runs = evidence["release_evidence"]["required_ci"]["runs"]
                if mutation == "shared_run_id":
                    # Decimal text and integer identify the same Actions run.
                    runs[1]["run_id"] = 1
                elif mutation == "extra_workflow":
                    runs.append({
                        "workflow": "Optional unrelated workflow",
                        "head_sha": SOURCE, "result": "PASS",
                        "status": "completed", "conclusion": "success",
                        "run_id": "4",
                    })
                else:
                    runs.append(None)
                verdict = evaluate(report, evidence, policy)
                self.assertEqual(
                    verdict["CODE_PRODUCTION_READY"], "BLOCKED")
                self.assertTrue(any(
                    "required_ci:" in reason for reason
                    in verdict["code_blockers"]))

    def test_zero_critical_count_requires_an_empty_issue_list(self):
        report = owner_report()
        policy = acceptance_policy()
        evidence = current_evidence(encoded(report), encoded(policy))
        evidence["release_evidence"]["unresolved_critical_issues"][
            "issues"] = ["publication race"]
        result = evaluate(report, evidence, policy)
        self.assertEqual(result["CODE_PRODUCTION_READY"], "BLOCKED")
        self.assertTrue(any(
            "count/list is inconsistent" in blocker
            for blocker in result["code_blockers"]))

    def test_deployment_pass_requires_retained_lifecycle_digest(self):
        report = owner_report()
        policy = acceptance_policy()
        evidence = current_evidence(encoded(report), encoded(policy))
        del evidence["release_evidence"]["lifecycle_deployment_state"][
            "evidence_sha256"]
        result = evaluate(report, evidence, policy)
        self.assertEqual(result["DEPLOYMENT_PRODUCTION_READY"], "BLOCKED")
        self.assertTrue(any(
            "lifecycle_deployment_state: evidence digest is invalid" in blocker
            for blocker in result["deployment_blockers"]))

    def test_owner_reboot_status_requires_timestamp_and_matching_overall(self):
        report = owner_report()
        policy = acceptance_policy()
        evidence = current_evidence(encoded(report), encoded(policy))
        reboot = evidence["release_evidence"]["owner_observed_reboot"]
        cold_boot_raw = cold_boot_evidence_raw()
        reboot.update(
            status="PASS", observed=True, overall="PASS",
            evidence_sha256=hashlib.sha256(cold_boot_raw).hexdigest())
        del reboot["observed_at_utc"]
        result = evaluate(
            report, evidence, policy, cold_boot_raw=cold_boot_raw)
        self.assertEqual(result["COLD_BOOT_OBSERVED"], "NO")

        evidence = current_evidence(encoded(report), encoded(policy))
        reboot = evidence["release_evidence"]["owner_observed_reboot"]
        reboot.update(
            status="PASS", observed=True, overall="BLOCKED",
            evidence_sha256=hashlib.sha256(cold_boot_raw).hexdigest())
        result = evaluate(
            report, evidence, policy, cold_boot_raw=cold_boot_raw)
        self.assertEqual(result["COLD_BOOT_OBSERVED"], "NO")

    def test_current_owner_failure_overrides_self_declared_pass_records(self):
        report = owner_report()
        report["overall"] = "FAIL"
        policy = acceptance_policy()
        evidence = current_evidence(encoded(report), encoded(policy))
        result = evaluate(report, evidence, policy)
        self.assertEqual(result["CODE_PRODUCTION_READY"], "BLOCKED")
        self.assertTrue(any(
            "make test is not PASS" in blocker
            for blocker in result["code_blockers"]))

    def test_each_required_ci_workflow_must_pass_the_exact_source(self):
        report = owner_report()
        policy = acceptance_policy()
        evidence = current_evidence(encoded(report), encoded(policy))
        runs = evidence["release_evidence"]["required_ci"]["runs"]
        runs[0]["head_sha"] = "b" * 40
        result = evaluate(report, evidence, policy)
        self.assertEqual(result["CODE_PRODUCTION_READY"], "BLOCKED")
        self.assertTrue(any(
            "required_ci:" in blocker and
            "Native kernel-C project-goal regressions" in blocker and
            "exact-source" in blocker
            for blocker in result["code_blockers"]))

    def test_systemd_package_workflow_is_a_required_release_gate(self):
        report = owner_report()
        policy = acceptance_policy()
        evidence = current_evidence(encoded(report), encoded(policy))
        runs = evidence["release_evidence"]["required_ci"]["runs"]
        runs[:] = [
            run for run in runs
            if run["workflow"] != "Systemd and package production-readiness"
        ]
        result = evaluate(report, evidence, policy)
        self.assertEqual(result["CODE_PRODUCTION_READY"], "BLOCKED")
        self.assertTrue(any(
            "Systemd and package production-readiness" in blocker
            for blocker in result["code_blockers"]))

    def test_artifact_hash_mappings_are_cross_bound_independently(self):
        report = owner_report()
        policy = acceptance_policy()
        evidence = current_evidence(encoded(report), encoded(policy))
        qualified = evidence["release_evidence"]["qualified_artifact_hashes"]["hashes"]
        owner = evidence["release_evidence"]["exact_source_owner_make_test"]["hashes"]
        real_swap = evidence["release_evidence"]["real_linux_swap"]["hashes"]
        installed = evidence["release_evidence"]["installed_artifact_identity"]["hashes"]
        self.assertIsNot(qualified, owner)
        self.assertIsNot(owner, real_swap)
        self.assertIsNot(real_swap, installed)

        real_swap["module_sha256"] = "4" * 64
        self.assertEqual(owner["module_sha256"], ARTIFACTS["module_sha256"])
        result = evaluate(report, evidence, policy)
        self.assertEqual(result["CODE_PRODUCTION_READY"], "BLOCKED")
        self.assertTrue(any(
            "installed artifact binding mismatch" in blocker
            for blocker in result["code_blockers"]))

    def test_lifecycle_deployment_requires_explicit_pass_components(self):
        report = owner_report()
        policy = acceptance_policy()
        for field in ("overall", "lifecycle", "deployment"):
            with self.subTest(field=field):
                evidence = current_evidence(encoded(report), encoded(policy))
                lifecycle = evidence["release_evidence"][
                    "lifecycle_deployment_state"]
                lifecycle[field] = "FAIL"
                result = evaluate(report, evidence, policy)
                self.assertEqual(
                    result["DEPLOYMENT_PRODUCTION_READY"], "BLOCKED")
                self.assertTrue(any(
                    "lifecycle/deployment result is not PASS" in blocker
                    for blocker in result["deployment_blockers"]))

    def test_owned_nullblk_pass_requires_lifecycle_result_digest_and_production_bytes(self):
        report = owner_report()
        policy = acceptance_policy()
        evidence = current_evidence(encoded(report), encoded(policy))
        nullblk = evidence["release_evidence"]["owned_nullblk_qualification"]

        nullblk["evidence_sha256"] = "not-a-digest"
        result = evaluate(report, evidence, policy)
        self.assertEqual(result["CODE_PRODUCTION_READY"], "BLOCKED")
        self.assertTrue(any(
            "owned_nullblk_qualification: evidence digest is invalid" in blocker
            for blocker in result["code_blockers"]))

        nullblk["evidence_sha256"] = "5" * 64
        nullblk["hashes"]["formatter_sha256"] = "4" * 64
        result = evaluate(report, evidence, policy)
        self.assertEqual(result["CODE_PRODUCTION_READY"], "PASS", result)

        nullblk["hashes"]["module_sha256"] = "6" * 64
        result = evaluate(report, evidence, policy)
        self.assertEqual(result["CODE_PRODUCTION_READY"], "BLOCKED")
        self.assertTrue(any(
            "owned_nullblk_qualification: module/oracle artifact binding mismatch"
            in blocker for blocker in result["code_blockers"]))

        nullblk["hashes"] = dict(ARTIFACTS)
        nullblk["overall"] = "FAIL"
        result = evaluate(report, evidence, policy)
        self.assertEqual(result["CODE_PRODUCTION_READY"], "BLOCKED")
        self.assertTrue(any(
            "owned_nullblk_qualification: lifecycle result is not PASS" in blocker
            for blocker in result["code_blockers"]))

    def test_policy_and_target_bindings_are_exact(self):
        report = owner_report()
        policy = acceptance_policy()
        evidence = current_evidence(encoded(report), encoded(policy))
        evidence["release_evidence"]["maximum_capacity_and_ram"][
            "policy_sha256"] = "5" * 64
        evidence["release_evidence"]["sustained_physical_performance"][
            "target"]["size_bytes"] += 4096
        result = evaluate(report, evidence, policy)
        self.assertEqual(result["CODE_PRODUCTION_READY"], "BLOCKED")
        self.assertTrue(any(
            "policy binding mismatch" in blocker
            for blocker in result["code_blockers"]))
        self.assertTrue(any(
            "target binding mismatch" in blocker
            for blocker in result["code_blockers"]))

    def test_release_target_partuuid_uses_production_selector_grammar(self):
        valid = {
            "partuuid": "550e8400-e29b-41d4-a716-446655440000",
            "size_bytes": TARGET["size_bytes"],
        }
        self.assertEqual(
            EVALUATOR._normalize_target(valid),
            (valid["partuuid"], valid["size_bytes"]))
        for partuuid in (
                "--------", "-f13428f6", "f13428f6-",
                "f13428f6--01", "1234-567", "F13428F6-01"):
            with self.subTest(partuuid=partuuid):
                self.assertIsNone(EVALUATOR._normalize_target({
                    "partuuid": partuuid,
                    "size_bytes": TARGET["size_bytes"],
                }))

        report = owner_report()
        policy = acceptance_policy()
        evidence = current_evidence(encoded(report), encoded(policy))
        evidence["authorized_target"]["partuuid"] = "f13428f6--01"
        result = evaluate(report, evidence, policy)
        self.assertEqual(result["CODE_PRODUCTION_READY"], "BLOCKED")
        self.assertTrue(any(
            "canonical authorized target identity is invalid" in blocker
            for blocker in result["code_blockers"]))

    def test_full_capacity_peak_ram_must_fit_frozen_limit(self):
        report = owner_report()
        policy = acceptance_policy()
        evidence = current_evidence(encoded(report), encoded(policy))
        limit = policy["physical_qualification"]["acceptance"]["sustained"][
            "metadata_and_target_peak_ram_bytes_max"]
        evidence["release_evidence"]["maximum_capacity_and_ram"][
            "peak_ram_bytes"] = limit + 1
        result = evaluate(report, evidence, policy)
        self.assertEqual(result["CODE_PRODUCTION_READY"], "BLOCKED")
        self.assertTrue(any(
            "peak exceeds frozen limit" in blocker
            for blocker in result["code_blockers"]))

    def test_capacity_and_ram_are_bound_to_sealed_campaign(self):
        report = owner_report()
        policy = acceptance_policy()
        report_raw = encoded(report)
        policy_raw = encoded(policy)
        physical = real_swap_evidence(report_raw, policy_raw)
        physical_raw = encoded(physical)
        campaign = physical_campaign_evidence(policy_raw)
        campaign_raw = encoded(campaign)
        evidence = current_evidence(
            report_raw, policy_raw, physical_raw, campaign_raw)

        evidence["release_evidence"]["maximum_capacity_and_ram"][
            "logical_capacity_bytes"] += 4096
        mismatch = EVALUATOR.evaluate_release(
            SOURCE, report, report_raw, evidence, policy, policy_raw,
            physical, physical_raw, campaign, campaign_raw)
        self.assertEqual(mismatch["CODE_PRODUCTION_READY"], "BLOCKED")
        self.assertTrue(any(
            "sealed campaign measurement mismatch" in blocker
            for blocker in mismatch["code_blockers"]))

        evidence = current_evidence(
            report_raw, policy_raw, physical_raw, campaign_raw)
        evidence["release_evidence"]["maximum_capacity_and_ram"][
            "evidence_sha256"] = "8" * 64
        digest_mismatch = EVALUATOR.evaluate_release(
            SOURCE, report, report_raw, evidence, policy, policy_raw,
            physical, physical_raw, campaign, campaign_raw)
        self.assertEqual(
            digest_mismatch["CODE_PRODUCTION_READY"], "BLOCKED")
        self.assertTrue(any(
            "campaign evidence digest binding mismatch" in blocker
            for blocker in digest_mismatch["code_blockers"]))

    def test_resealed_malformed_ram_trace_never_qualifies_release(self):
        report = owner_report()
        policy = acceptance_policy()
        report_raw = encoded(report)
        policy_raw = encoded(policy)
        physical = real_swap_evidence(report_raw, policy_raw)
        physical_raw = encoded(physical)

        changes = {
            "missing_trace": lambda capacity: capacity.pop("metadata_ram_trace"),
            "early_teardown": lambda capacity: capacity["metadata_ram_trace"][
                "samples"].pop(),
            "sample_peak_disagrees": lambda capacity: capacity[
                "metadata_ram_trace"]["samples"][15].update(
                    mem_available_kib=(
                        8 * 1024 * 1024 - 900 * 1024 - 1)),
            "source_mismatch": lambda capacity: capacity[
                "metadata_ram_trace"].update(source_sha="b" * 40),
            "summary_tamper": lambda capacity: capacity[
                "metadata_ram_summary"].update(sample_count=1),
            "arm_binding_tamper": lambda capacity: capacity[
                "metadata_ram_arm_binding"]["gc_activity_intervals"][0].update(
                    start_monotonic_ns=1_700_000_001),
            "host_binding_tamper": lambda capacity: capacity[
                "metadata_ram_host_binding"].update(
                    host_boot_id="22222222-2222-4222-8222-222222222222"),
            "short_capacity": lambda capacity: (
                capacity.update(logical_pages=27080191,
                                logical_capacity_bytes=27080191 * 4096)),
            "float_page_bytes": lambda capacity: capacity.update(
                page_bytes=4096.0),
        }
        for label, change in changes.items():
            with self.subTest(change=label):
                campaign = physical_campaign_evidence(policy_raw)
                change(campaign["capacity_and_ram"])
                campaign_raw = encoded(campaign)
                evidence = current_evidence(
                    report_raw, policy_raw, physical_raw, campaign_raw)
                result = EVALUATOR.evaluate_release(
                    SOURCE, report, report_raw, evidence, policy, policy_raw,
                    physical, physical_raw, campaign, campaign_raw)
                self.assertEqual(result["CODE_PRODUCTION_READY"], "BLOCKED")
                expected = (
                    "sealed campaign capacity/RAM evidence is invalid"
                    if label in ("short_capacity", "float_page_bytes") else
                    "sealed campaign RAM trace summary does not match"
                    if label == "summary_tamper" else
                    "sealed campaign RAM trace is invalid")
                self.assertTrue(
                    any(expected in blocker for blocker in result["code_blockers"]),
                    (label, result["code_blockers"]))

    def test_resealed_ram_trace_artifact_digest_mismatch_blocks_release(self):
        report = owner_report()
        policy = acceptance_policy()
        report_raw = encoded(report)
        policy_raw = encoded(policy)
        physical = real_swap_evidence(report_raw, policy_raw)
        physical_raw = encoded(physical)
        campaign = physical_campaign_evidence(policy_raw)
        campaign["artifacts"]["metadata_ram_trace"]["sha256"] = "f" * 64
        campaign_raw = encoded(campaign)
        evidence = current_evidence(
            report_raw, policy_raw, physical_raw, campaign_raw)
        result = EVALUATOR.evaluate_release(
            SOURCE, report, report_raw, evidence, policy, policy_raw,
            physical, physical_raw, campaign, campaign_raw)
        self.assertEqual(result["CODE_PRODUCTION_READY"], "BLOCKED")
        self.assertTrue(any(
            "sealed campaign RAM trace artifact digest mismatch" in blocker
            for blocker in result["code_blockers"]))

    def test_host_sampled_full_capacity_over_limit_is_blocked(self):
        report = owner_report()
        policy = acceptance_policy()
        report_raw = encoded(report)
        policy_raw = encoded(policy)
        physical_raw = encoded(real_swap_evidence(report_raw, policy_raw))
        limit = policy["physical_qualification"]["acceptance"]["sustained"][
            "metadata_and_target_peak_ram_bytes_max"]
        observed_peak = limit + 1024
        campaign = physical_campaign_evidence(policy_raw)
        capacity = campaign["capacity_and_ram"]
        trace = sampled_metadata_ram_trace(observed_peak)
        capacity["metadata_ram_trace"] = trace
        capacity["metadata_ram_summary"] = EVALUATOR.RAM_TRACE_VALIDATOR[
            "validate_metadata_ram_trace"](
                trace, source_sha=SOURCE, mapper_uuid=capacity["mapper_uuid"],
                expected_peak_ram_bytes=observed_peak)
        capacity["peak_ram_bytes"] = observed_peak
        reseal_synthetic_ram_trace_artifact(campaign)
        campaign_raw = encoded(campaign)
        evidence = current_evidence(
            report_raw, policy_raw, physical_raw, campaign_raw)
        evidence["release_evidence"]["maximum_capacity_and_ram"][
            "peak_ram_bytes"] = observed_peak

        result = EVALUATOR.evaluate_release(
            SOURCE, report, report_raw, evidence, policy, policy_raw,
            json.loads(physical_raw), physical_raw, campaign, campaign_raw)
        self.assertEqual(result["CODE_PRODUCTION_READY"], "BLOCKED")
        self.assertEqual(result["METADATA_RAM_MEASUREMENT"]["status"],
                         "MEASURED_OVER_LIMIT")
        self.assertEqual(
            result["METADATA_RAM_MEASUREMENT"]["observed_peak_ram_bytes"],
            observed_peak)
        self.assertTrue(any(
            f"observed={observed_peak} limit={limit}" in blocker
            for blocker in result["code_blockers"]))

    def test_resealed_adversarial_ram_samples_are_not_measured(self):
        report = owner_report()
        policy = acceptance_policy()
        report_raw = encoded(report)
        policy_raw = encoded(policy)
        physical = real_swap_evidence(report_raw, policy_raw)
        physical_raw = encoded(physical)

        def persistent_teardown_leak(trace):
            for sample in trace["samples"][-8:]:
                sample["mem_available_kib"] -= 1
                sample["s_unreclaim_kib"] += 1
                sample["vmalloc_used_kib"] += 1

        def duplicate_utc(trace):
            trace["samples"][16]["timestamp_utc"] = (
                trace["samples"][15]["timestamp_utc"])

        corruptions = {
            "missing_sample": lambda trace: trace["samples"].pop(14),
            "interrupted_teardown": lambda trace: trace["samples"].pop(),
            "duplicate_utc": duplicate_utc,
            "nonfinite_counter": lambda trace: trace["samples"][15].update(
                mem_available_kib=float("nan")),
            "infinite_counter": lambda trace: trace["samples"][15].update(
                mem_available_kib=float("inf")),
            "boolean_byte_counter": lambda trace: trace["samples"][15].update(
                mem_available_kib=True),
            "float_byte_counter": lambda trace: trace["samples"][15].update(
                mem_available_kib=float(8 * 1024 * 1024 - 900 * 1024)),
            "overflow_counter": lambda trace: trace["samples"][15].update(
                vmalloc_used_kib=1 << 64),
            "overflow_clock": lambda trace: trace["samples"][15].update(
                monotonic_ns=1 << 65),
            "float_sampling_interval": lambda trace: trace.update(
                sampling_interval_ns=100_000_000.0),
            "persistent_teardown_leak": persistent_teardown_leak,
            "recovered_but_mapper_reappeared": lambda trace: trace[
                "samples"][-1].update(mapper_present=True),
            "source_mismatch": lambda trace: trace.update(source_sha="b" * 40),
            "boot_mismatch": lambda trace: trace.update(
                host_boot_id="22222222-2222-4222-8222-222222222222"),
        }
        for name, damage in corruptions.items():
            with self.subTest(corruption=name):
                campaign = physical_campaign_evidence(policy_raw)
                damage(campaign["capacity_and_ram"]["metadata_ram_trace"])
                reseal_synthetic_ram_trace_artifact(campaign)
                campaign_raw = encoded(campaign)
                evidence = current_evidence(
                    report_raw, policy_raw, physical_raw, campaign_raw)
                result = EVALUATOR.evaluate_release(
                    SOURCE, report, report_raw, evidence, policy, policy_raw,
                    physical, physical_raw, campaign, campaign_raw)
                self.assertEqual(result["CODE_PRODUCTION_READY"], "BLOCKED")
                self.assertEqual(
                    result["METADATA_RAM_MEASUREMENT"]["status"],
                    "NOT_MEASURED", (name, result["code_blockers"]))
                self.assertEqual(
                    result["FULL_CAPACITY_LOADED_CONSTRUCTION"],
                    "NOT_MEASURED")
                expected_gap = (
                    "sealed campaign evidence bytes are malformed"
                    if name in {
                        "nonfinite_counter", "infinite_counter",
                        "overflow_counter", "overflow_clock",
                    }
                    else "sealed campaign RAM trace is invalid")
                self.assertTrue(any(
                    expected_gap in blocker
                    for blocker in result["code_blockers"]),
                    (name, result["code_blockers"]))
                if name in ("source_mismatch", "boot_mismatch"):
                    identity_metric = (
                        "metric=source_sha" if name == "source_mismatch"
                        else "metric=host_boot_id")
                    self.assertTrue(any(
                        identity_metric in blocker
                        for blocker in result["code_blockers"]),
                        (name, result["code_blockers"]))
                if name == "recovered_but_mapper_reappeared":
                    self.assertTrue(any(
                        "metric=mapper_present observed=true" in blocker
                        for blocker in result["code_blockers"]),
                        result["code_blockers"])

    def test_missing_or_mismatched_capacity_provenance_never_passes(self):
        report = owner_report()
        policy = acceptance_policy()
        report_raw = encoded(report)
        policy_raw = encoded(policy)
        physical = real_swap_evidence(report_raw, policy_raw)
        physical_raw = encoded(physical)
        cases = {
            "missing_trace": lambda campaign: campaign[
                "capacity_and_ram"].pop("metadata_ram_trace"),
            "source_tree_identity": lambda campaign: campaign.update(
                campaign_source_sha="b" * 40),
            "arm_boot_mismatch": lambda campaign: campaign.update(
                arm_boot_consistent=False),
            "validator_artifact": lambda campaign: campaign["policy"][
                "metadata_ram_validator"].update(sha256="f" * 64),
            "ram_trace_artifact": lambda campaign: campaign["artifacts"][
                "metadata_ram_trace"].update(sha256="f" * 64),
        }
        for name, damage in cases.items():
            with self.subTest(case=name):
                campaign = physical_campaign_evidence(policy_raw)
                damage(campaign)
                campaign_raw = encoded(campaign)
                evidence = current_evidence(
                    report_raw, policy_raw, physical_raw, campaign_raw)
                result = EVALUATOR.evaluate_release(
                    SOURCE, report, report_raw, evidence, policy, policy_raw,
                    physical, physical_raw, campaign, campaign_raw)
                self.assertEqual(result["CODE_PRODUCTION_READY"], "BLOCKED")
                self.assertEqual(
                    result["METADATA_RAM_MEASUREMENT"]["status"],
                    "NOT_MEASURED")
                self.assertEqual(
                    result["FULL_CAPACITY_LOADED_CONSTRUCTION"],
                    "NOT_MEASURED")
                self.assertTrue(any(
                    "maximum_capacity_and_ram:" in blocker
                    for blocker in result["code_blockers"]))

    def test_capacity_report_identity_mismatch_cannot_claim_host_peak(self):
        report = owner_report()
        policy = acceptance_policy()
        policy_raw = encoded(policy)
        report_raw = encoded(report)
        physical = real_swap_evidence(report_raw, policy_raw)
        physical_raw = encoded(physical)
        campaign = physical_campaign_evidence(policy_raw)
        campaign_raw = encoded(campaign)
        modifications = {
            "record_source": lambda record: record.update(source_sha="b" * 40),
            "record_policy": lambda record: record.update(
                policy_sha256="f" * 64),
            "record_target": lambda record: record.update(
                target={"partuuid": "f13428f6-02",
                        "size_bytes": TARGET["size_bytes"]}),
            "record_digest": lambda record: record.update(
                evidence_sha256="f" * 64),
        }
        for name, damage in modifications.items():
            with self.subTest(case=name):
                evidence = current_evidence(
                    report_raw, policy_raw, physical_raw, campaign_raw)
                damage(evidence["release_evidence"]["maximum_capacity_and_ram"])
                result = EVALUATOR.evaluate_release(
                    SOURCE, report, report_raw, evidence, policy, policy_raw,
                    physical, physical_raw, campaign, campaign_raw)
                self.assertEqual(result["CODE_PRODUCTION_READY"], "BLOCKED")
                self.assertEqual(result["METADATA_RAM_MEASUREMENT"]["status"],
                                 "NOT_MEASURED", (name, result["code_blockers"]))
                self.assertEqual(result["FULL_CAPACITY_LOADED_CONSTRUCTION"],
                                 "NOT_MEASURED")

    def test_robust_ram_medians_accept_isolated_noise_without_new_gates(self):
        report = owner_report()
        policy = acceptance_policy()
        report_raw = encoded(report)
        policy_raw = encoded(policy)
        physical = real_swap_evidence(report_raw, policy_raw)
        physical_raw = encoded(physical)
        campaign = physical_campaign_evidence(policy_raw)
        capacity = campaign["capacity_and_ram"]
        trace = capacity["metadata_ram_trace"]
        trace["samples"][0]["mem_available_kib"] -= 1
        trace["samples"][-1]["mem_available_kib"] -= 1
        trace["samples"][-1]["s_unreclaim_kib"] += 1
        trace["samples"][-1]["vmalloc_used_kib"] += 1
        reseal_synthetic_ram_trace_artifact(campaign)
        campaign_raw = encoded(campaign)
        evidence = current_evidence(
            report_raw, policy_raw, physical_raw, campaign_raw)
        result = EVALUATOR.evaluate_release(
            SOURCE, report, report_raw, evidence, policy, policy_raw,
            physical, physical_raw, campaign, campaign_raw)
        measured = result["METADATA_RAM_MEASUREMENT"]
        self.assertEqual(measured["status"], "MEASURED_WITHIN_LIMIT",
                         result["code_blockers"])
        self.assertEqual(measured["observed_peak_ram_bytes"],
                         900 * 1024 * 1024)
        self.assertEqual(measured["initialization_peak_ram_bytes"],
                         400 * 1024 * 1024)
        self.assertEqual(measured["initialization_samples"], 2)
        self.assertEqual(measured["steady_peak_ram_bytes"],
                         800 * 1024 * 1024)
        self.assertEqual(measured["steady_samples"], 2)
        self.assertEqual(measured["gc_peak_ram_bytes"],
                         900 * 1024 * 1024)
        self.assertEqual(measured["gc_samples"], 2)
        self.assertEqual(measured["teardown_recovery"],
                         "MEASURED_RECOVERED")
        self.assertEqual(measured["teardown_recovery_samples"], 11)
        self.assertEqual(measured["teardown_recovery_span_ns"],
                         1_000_000_000)
        estimate = result["CAPACITY_INDEX_ESTIMATE"]
        self.assertEqual(estimate["status"], "PREDICTED_ONLY")
        self.assertEqual(estimate["logical_pages"], 27080192)
        self.assertEqual(estimate["logical_mapper_bytes"], 110920466432)
        self.assertEqual(estimate["physical_blocks"], 30465536)
        self.assertEqual(estimate["segment_count"], 119006)
        self.assertEqual(estimate["array_count"], 17)
        self.assertEqual(estimate["payload_bytes"], 776070968)
        self.assertEqual(estimate["page_rounded_bytes"], 776114176)
        self.assertEqual(
            result["ALLOCATION_FAILURE_COVERAGE"],
            "SEPARATE_NOT_CONSTRUCTION_EVIDENCE")
        self.assertEqual(result["FULL_CAPACITY_LOADED_CONSTRUCTION"],
                         "SAMPLED_LOADED_HOST")

    def test_missing_host_campaign_does_not_inherit_allocation_test_success(self):
        report = owner_report()
        policy = acceptance_policy()
        report_raw = encoded(report)
        policy_raw = encoded(policy)
        physical = real_swap_evidence(report_raw, policy_raw)
        physical_raw = encoded(physical)
        evidence = current_evidence(report_raw, policy_raw, physical_raw)
        result = EVALUATOR.evaluate_release(
            SOURCE, report, report_raw, evidence, policy, policy_raw,
            physical, physical_raw)
        self.assertEqual(result["CODE_PRODUCTION_READY"], "BLOCKED")
        self.assertEqual(result["METADATA_RAM_MEASUREMENT"]["status"],
                         "NOT_MEASURED")
        self.assertIsNone(
            result["METADATA_RAM_MEASUREMENT"]["observed_peak_ram_bytes"])
        self.assertEqual(result["FULL_CAPACITY_LOADED_CONSTRUCTION"],
                         "NOT_MEASURED")
        estimate = result["CAPACITY_INDEX_ESTIMATE"]
        self.assertEqual(estimate["status"], "PREDICTED_ONLY")
        self.assertEqual(estimate["logical_pages"], 27080192)
        self.assertEqual(estimate["logical_mapper_bytes"], 110920466432)
        self.assertEqual(estimate["page_rounded_bytes"], 776114176)
        self.assertEqual(result["ALLOCATION_FAILURE_COVERAGE"],
                         "SEPARATE_NOT_CONSTRUCTION_EVIDENCE")

    def test_capacity_index_estimate_uses_checked_exact_arithmetic(self):
        validator = EVALUATOR.RAM_TRACE_VALIDATOR
        estimate = validator["capacity_index_estimate"](
            27080192, 30465536, size_t_max=validator["MAX_UINT64"])
        self.assertEqual(estimate, {
            "array_count": 17,
            "payload_bytes": 776070968,
            "page_rounded_bytes": 776114176,
        })
        self.assertIsNone(validator["capacity_index_estimate"](
            3817748224, 0xffffff00, size_t_max=(1 << 32) - 1))
        self.assertIsNone(validator["capacity_index_estimate"](
            27080192, 30465535, size_t_max=validator["MAX_UINT64"]))

    def test_mutable_campaign_object_cannot_substitute_sealed_bytes(self):
        report = owner_report()
        policy = acceptance_policy()
        report_raw = encoded(report)
        policy_raw = encoded(policy)
        physical = real_swap_evidence(report_raw, policy_raw)
        physical_raw = encoded(physical)
        campaign = physical_campaign_evidence(policy_raw)
        campaign_raw = encoded(campaign)
        evidence = current_evidence(
            report_raw, policy_raw, physical_raw, campaign_raw)
        campaign["sealed_at_utc"] = "2026-11-04T00:00:00+00:00"
        result = EVALUATOR.evaluate_release(
            SOURCE, report, report_raw, evidence, policy, policy_raw,
            physical, physical_raw, campaign, campaign_raw)
        self.assertEqual(result["CODE_PRODUCTION_READY"], "BLOCKED")
        self.assertEqual(result["METADATA_RAM_MEASUREMENT"]["status"],
                         "NOT_MEASURED")
        self.assertTrue(any(
            "sealed campaign object differs from artifact bytes" in blocker
            for blocker in result["code_blockers"]))
        self.assertFalse(any(
            "observation predates sealed campaign" in blocker
            for blocker in result["code_blockers"]))

    def test_serialized_owner_report_is_authoritative(self):
        policy = acceptance_policy()
        policy_raw = encoded(policy)
        serialized_report = owner_report()
        serialized_report["overall"] = "FAIL"
        report_raw = encoded(serialized_report)
        report = owner_report()
        physical = real_swap_evidence(report_raw, policy_raw)
        physical_raw = encoded(physical)
        campaign = physical_campaign_evidence(policy_raw)
        campaign_raw = encoded(campaign)
        evidence = current_evidence(
            report_raw, policy_raw, physical_raw, campaign_raw)

        result = EVALUATOR.evaluate_release(
            SOURCE, report, report_raw, evidence, policy, policy_raw,
            physical, physical_raw, campaign, campaign_raw)
        self.assertEqual(result["CODE_PRODUCTION_READY"], "BLOCKED")
        self.assertTrue(any(
            "owner qualification report: parsed object differs from "
            "serialized bytes" in blocker
            for blocker in result["code_blockers"]))

    def test_serialized_policy_cannot_be_paired_with_larger_ram_limit(self):
        report = owner_report()
        report_raw = encoded(report)
        frozen_policy = acceptance_policy()
        policy_raw = encoded(frozen_policy)
        policy = copy.deepcopy(frozen_policy)
        policy["physical_qualification"]["acceptance"]["sustained"][
            "metadata_and_target_peak_ram_bytes_max"] *= 2
        physical = real_swap_evidence(report_raw, policy_raw)
        physical_raw = encoded(physical)
        campaign = physical_campaign_evidence(policy_raw)
        campaign_raw = encoded(campaign)
        evidence = current_evidence(
            report_raw, policy_raw, physical_raw, campaign_raw)

        result = EVALUATOR.evaluate_release(
            SOURCE, report, report_raw, evidence, policy, policy_raw,
            physical, physical_raw, campaign, campaign_raw)
        self.assertEqual(result["CODE_PRODUCTION_READY"], "BLOCKED")
        self.assertEqual(result["METADATA_RAM_MEASUREMENT"]["status"],
                         "NOT_MEASURED")
        self.assertEqual(
            result["METADATA_RAM_MEASUREMENT"]["limit_bytes"],
            frozen_policy["physical_qualification"]["acceptance"][
                "sustained"]["metadata_and_target_peak_ram_bytes_max"])
        self.assertTrue(any(
            "production acceptance policy: parsed object differs from "
            "serialized bytes" in blocker
            for blocker in result["code_blockers"]))

    def test_serialized_real_swap_evidence_is_authoritative(self):
        report = owner_report()
        policy = acceptance_policy()
        report_raw = encoded(report)
        policy_raw = encoded(policy)
        physical = real_swap_evidence(report_raw, policy_raw)
        serialized_physical = copy.deepcopy(physical)
        serialized_physical["status"] = "FAIL"
        physical_raw = encoded(serialized_physical)
        campaign = physical_campaign_evidence(policy_raw)
        campaign_raw = encoded(campaign)
        evidence = current_evidence(
            report_raw, policy_raw, physical_raw, campaign_raw)

        result = EVALUATOR.evaluate_release(
            SOURCE, report, report_raw, evidence, policy, policy_raw,
            physical, physical_raw, campaign, campaign_raw)
        self.assertEqual(result["CODE_PRODUCTION_READY"], "BLOCKED")
        self.assertTrue(any(
            "persistent real-swap evidence: parsed object differs from "
            "serialized bytes" in blocker
            for blocker in result["code_blockers"]))

    def test_serialized_cold_boot_arm_evidence_is_authoritative(self):
        report = owner_report()
        policy = acceptance_policy()
        report_raw = encoded(report)
        policy_raw = encoded(policy)
        physical = real_swap_evidence(report_raw, policy_raw)
        physical_raw = encoded(physical)
        campaign = physical_campaign_evidence(policy_raw)
        campaign_raw = encoded(campaign)
        arm_raw = cold_boot_arm_evidence_raw(
            expected_module_source_sha="b" * 40)
        evidence = current_evidence(
            report_raw, policy_raw, physical_raw, campaign_raw, arm_raw)
        valid_arm = EVALUATOR.parse_env_strict(cold_boot_arm_evidence_raw())

        result = EVALUATOR.evaluate_release(
            SOURCE, report, report_raw, evidence, policy, policy_raw,
            physical, physical_raw, campaign, campaign_raw,
            None, None, valid_arm, arm_raw)
        self.assertEqual(result["DEPLOYMENT_PRODUCTION_READY"], "BLOCKED")
        self.assertTrue(any(
            "cold-boot arm evidence: parsed object differs from serialized "
            "bytes" in blocker
            for blocker in result["deployment_blockers"]))

    def test_malformed_campaign_top_level_blocks_without_exception(self):
        report = owner_report()
        policy = acceptance_policy()
        report_raw = encoded(report)
        policy_raw = encoded(policy)
        physical = real_swap_evidence(report_raw, policy_raw)
        physical_raw = encoded(physical)
        campaign = physical_campaign_evidence(policy_raw)
        campaign_raw = b"[]\n"
        evidence = current_evidence(
            report_raw, policy_raw, physical_raw, campaign_raw)

        result = EVALUATOR.evaluate_release(
            SOURCE, report, report_raw, evidence, policy, policy_raw,
            physical, physical_raw, campaign, campaign_raw)
        self.assertEqual(result["CODE_PRODUCTION_READY"], "BLOCKED")
        self.assertEqual(result["METADATA_RAM_MEASUREMENT"]["status"],
                         "NOT_MEASURED")
        self.assertTrue(any(
            "sealed campaign evidence bytes have invalid top level" in blocker
            for blocker in result["code_blockers"]))

        nested_raw = (
            b'{"nested":' + b"[" * 10000 + b"0" +
            b"]" * 10000 + b"}\n")
        evidence = current_evidence(
            report_raw, policy_raw, physical_raw, nested_raw)
        result = EVALUATOR.evaluate_release(
            SOURCE, report, report_raw, evidence, policy, policy_raw,
            physical, physical_raw, campaign, nested_raw)
        self.assertEqual(result["CODE_PRODUCTION_READY"], "BLOCKED")
        self.assertEqual(result["METADATA_RAM_MEASUREMENT"]["status"],
                         "NOT_MEASURED")
        self.assertTrue(any(
            "sealed campaign evidence bytes are malformed" in blocker
            for blocker in result["code_blockers"]))

    def test_oversized_decimal_cold_boot_fields_block_without_exception(self):
        report = owner_report()
        policy = acceptance_policy()
        report_raw = encoded(report)
        policy_raw = encoded(policy)
        physical = real_swap_evidence(report_raw, policy_raw)
        physical_raw = encoded(physical)
        campaign = physical_campaign_evidence(policy_raw)
        campaign_raw = encoded(campaign)
        huge_decimal = "9" * 5000
        arm_raw = cold_boot_arm_evidence_raw(
            expected_target_size_bytes=huge_decimal)
        arm = EVALUATOR.parse_env_strict(arm_raw)
        evidence = current_evidence(
            report_raw, policy_raw, physical_raw, campaign_raw, arm_raw)

        result = EVALUATOR.evaluate_release(
            SOURCE, report, report_raw, evidence, policy, policy_raw,
            physical, physical_raw, campaign, campaign_raw,
            None, None, arm, arm_raw)
        self.assertEqual(result["DEPLOYMENT_PRODUCTION_READY"], "BLOCKED")
        self.assertTrue(any(
            "cold-boot arm authorized target identity mismatch" in blocker
            for blocker in result["deployment_blockers"]))

        cold_raw = cold_boot_evidence_raw(dm_logical_bytes=huge_decimal)
        cold = EVALUATOR.parse_env_strict(cold_raw)
        arm_raw = cold_boot_arm_evidence_raw()
        arm = EVALUATOR.parse_env_strict(arm_raw)
        evidence = current_evidence(
            report_raw, policy_raw, physical_raw, campaign_raw, arm_raw)
        reboot = evidence["release_evidence"]["owner_observed_reboot"]
        reboot.update(
            status="PASS", observed=True, overall="PASS",
            evidence_sha256=hashlib.sha256(cold_raw).hexdigest())
        result = EVALUATOR.evaluate_release(
            SOURCE, report, report_raw, evidence, policy, policy_raw,
            physical, physical_raw, campaign, campaign_raw,
            cold, cold_raw, arm, arm_raw)
        self.assertEqual(result["COLD_BOOT_OBSERVED"], "NO")
        self.assertTrue(any(
            "mapper capacity differs from authorized target" in blocker
            for blocker in result["cold_boot_blockers"]))

    def test_direct_evidence_inputs_are_bounded_and_nonthrowing(self):
        with self.assertRaises(EVALUATOR.EvidenceError):
            EVALUATOR.parse_env_strict(
                b"schema=" +
                b"x" * EVALUATOR.MAX_ENV_EVIDENCE_INPUT_BYTES + b"\n")

        long_key = b"a" * 4096
        duplicate_key_evidence = (
            long_key + b"=first\n" + long_key + b"=second\n")
        with self.assertRaises(EVALUATOR.EvidenceError) as failure:
            EVALUATOR.parse_env_strict(duplicate_key_evidence)
        self.assertLess(len(str(failure.exception)), 400)
        self.assertIn("(truncated)", str(failure.exception))

        with mock.patch.object(
                EVALUATOR, "_same_json_value",
                side_effect=RecursionError("synthetic nesting")):
            with self.assertRaisesRegex(
                    EVALUATOR.EvidenceError, "nesting exceeds"):
                EVALUATOR._bound_json_object(
                    {}, b"{}\n", "synthetic nested evidence")

        report = owner_report()
        policy = acceptance_policy()
        report_raw = encoded(report)
        policy_raw = encoded(policy)
        physical = real_swap_evidence(report_raw, policy_raw)
        physical_raw = encoded(physical)
        campaign = physical_campaign_evidence(policy_raw)
        campaign_raw = encoded(campaign)
        evidence = current_evidence(
            report_raw, policy_raw, physical_raw, campaign_raw)

        result = EVALUATOR.evaluate_release(
            SOURCE, report, report_raw, evidence, policy, policy_raw,
            physical, physical_raw, campaign, "not-bytes")
        self.assertEqual(result["CODE_PRODUCTION_READY"], "BLOCKED")
        self.assertEqual(result["METADATA_RAM_MEASUREMENT"]["status"],
                         "NOT_MEASURED")
        self.assertTrue(any(
            "sealed campaign evidence bytes are invalid" in blocker
            for blocker in result["code_blockers"]))

    def test_nested_campaign_numeric_types_must_remain_exact(self):
        report = owner_report()
        policy = acceptance_policy()
        report_raw = encoded(report)
        policy_raw = encoded(policy)
        physical = real_swap_evidence(report_raw, policy_raw)
        physical_raw = encoded(physical)

        changes = {
            "ram_summary": (
                lambda campaign: campaign["capacity_and_ram"][
                    "metadata_ram_summary"].update(
                        gc_peak_ram_bytes=float(900 * 1024 * 1024)),
                "sealed campaign RAM trace summary does not match raw samples"),
            "target_observation": (
                lambda campaign: campaign["qualification_target_binding"][
                    "observed"].update(
                        physical_device_bytes=float(TARGET["size_bytes"])),
                "qualification target observations disagree"),
        }
        for name, (damage, expected) in changes.items():
            with self.subTest(case=name):
                campaign = physical_campaign_evidence(policy_raw)
                damage(campaign)
                campaign_raw = encoded(campaign)
                evidence = current_evidence(
                    report_raw, policy_raw, physical_raw, campaign_raw)
                result = EVALUATOR.evaluate_release(
                    SOURCE, report, report_raw, evidence, policy, policy_raw,
                    physical, physical_raw, campaign, campaign_raw)
                self.assertEqual(result["CODE_PRODUCTION_READY"], "BLOCKED")
                self.assertEqual(
                    result["METADATA_RAM_MEASUREMENT"]["status"],
                    "NOT_MEASURED")
                self.assertTrue(any(
                    expected in blocker for blocker in result["code_blockers"]),
                    (name, result["code_blockers"]))

    def test_real_swap_numeric_fields_require_exact_integer_types(self):
        report = owner_report()
        policy = acceptance_policy()
        report_raw = encoded(report)
        policy_raw = encoded(policy)
        physical = real_swap_evidence(report_raw, policy_raw)
        numeric_value = physical["cycles_requested"]
        physical["cycles_requested"] = float(numeric_value)
        physical["result"]["cycles_requested"] = float(numeric_value)
        physical_raw = encoded(physical)
        campaign = physical_campaign_evidence(policy_raw)
        campaign_raw = encoded(campaign)
        evidence = current_evidence(
            report_raw, policy_raw, physical_raw, campaign_raw)

        result = EVALUATOR.evaluate_release(
            SOURCE, report, report_raw, evidence, policy, policy_raw,
            physical, physical_raw, campaign, campaign_raw)
        self.assertEqual(result["CODE_PRODUCTION_READY"], "BLOCKED")
        self.assertTrue(any(
            "nested result cycles_requested is not an exact integer" in blocker
            for blocker in result["code_blockers"]))

    def test_campaign_raw_numeric_type_mismatch_is_not_authenticated(self):
        report = owner_report()
        policy = acceptance_policy()
        report_raw = encoded(report)
        policy_raw = encoded(policy)
        physical = real_swap_evidence(report_raw, policy_raw)
        physical_raw = encoded(physical)
        campaign = physical_campaign_evidence(policy_raw)
        campaign_raw = encoded(campaign)
        count_bytes = f'"record_count":{campaign["record_count"]}'.encode()
        typed_raw = campaign_raw.replace(
            count_bytes, count_bytes + b".0", 1)
        self.assertNotEqual(typed_raw, campaign_raw)
        evidence = current_evidence(
            report_raw, policy_raw, physical_raw, typed_raw)
        result = EVALUATOR.evaluate_release(
            SOURCE, report, report_raw, evidence, policy, policy_raw,
            physical, physical_raw, campaign, typed_raw)
        self.assertEqual(result["CODE_PRODUCTION_READY"], "BLOCKED")
        self.assertEqual(result["METADATA_RAM_MEASUREMENT"]["status"],
                         "NOT_MEASURED")
        self.assertTrue(any(
            "sealed campaign object differs from artifact bytes" in blocker
            for blocker in result["code_blockers"]))

    def test_strict_json_rejects_nonfinite_and_overflow_exponents(self):
        with TemporaryDirectory(prefix="swapz-ram-json-") as directory:
            path = Path(directory) / "evidence.json"
            for number in (
                    "NaN", "Infinity", "-Infinity", "1e999",
                    str((1 << 64)), str(-(1 << 64)), "9" * 5000):
                with self.subTest(number=number):
                    path.write_text('{"value":' + number + '}')
                    with self.assertRaises(EVALUATOR.EvidenceError):
                        EVALUATOR.load_json_strict(path)

            path.write_bytes(
                b'{"value":' + b"[" * 10000 + b"0" +
                b"]" * 10000 + b"}\n")
            with self.assertRaisesRegex(
                    EVALUATOR.EvidenceError, "nesting exceeds validation depth"):
                EVALUATOR.load_json_strict(path)

            # The top-level object contributes one container level.
            bounded = EVALUATOR.MAX_JSON_NESTING_DEPTH - 1
            path.write_bytes(
                b'{"value":' + b"[" * bounded + b"0" +
                b"]" * bounded + b"}\n")
            parsed, _raw = EVALUATOR.load_json_strict(path)
            self.assertIn("value", parsed)

            # Bracket characters inside JSON strings do not count as
            # container nesting.
            path.write_text('{"value":"' + "[" * 10000 + "}" * 10000 + '"}')
            parsed, _raw = EVALUATOR.load_json_strict(path)
            self.assertEqual(len(parsed["value"]), 20000)

    def test_unresolved_critical_issue_blocks_code_readiness(self):
        report = owner_report()
        policy = acceptance_policy()
        for bad_count in (1, -1, False, "0", None):
            with self.subTest(count=bad_count):
                evidence = current_evidence(encoded(report), encoded(policy))
                evidence["release_evidence"]["unresolved_critical_issues"][
                    "count"] = bad_count
                result = evaluate(report, evidence, policy)
                self.assertEqual(result["CODE_PRODUCTION_READY"], "BLOCKED")
                self.assertTrue(any(
                    "unresolved critical correctness issue count/list is inconsistent"
                    in blocker for blocker in result["code_blockers"]))

    def test_owner_report_stage_set_order_status_and_exit_are_exact(self):
        policy = acceptance_policy()

        report = owner_report()
        report["stages"][-1]["name"] = report["stages"][0]["name"]
        result = evaluate(report, policy=policy)
        self.assertEqual(result["CODE_PRODUCTION_READY"], "BLOCKED")
        self.assertTrue(any(
            "stage set/order is not exactly canonical" in blocker
            for blocker in result["code_blockers"]))

        report = owner_report()
        report["stages"][2]["exit_code"] = 1
        result = evaluate(report, policy=policy)
        self.assertEqual(result["CODE_PRODUCTION_READY"], "BLOCKED")
        self.assertTrue(any(
            "PASS with exit code 0" in blocker
            for blocker in result["code_blockers"]))

        report = owner_report()
        report["stages"].append(
            {"name": "Unexpected stage", "status": "PASS", "exit_code": 0})
        result = evaluate(report, policy=policy)
        self.assertEqual(result["CODE_PRODUCTION_READY"], "BLOCKED")
        self.assertTrue(any(
            "stage set/order is not exactly canonical" in blocker
            for blocker in result["code_blockers"]))

    def test_owner_artifact_hash_record_rejects_unknown_fields(self):
        report = owner_report()
        report["qualified_artifacts"]["unexpected"] = "field"
        result = evaluate(report)
        self.assertEqual(result["CODE_PRODUCTION_READY"], "BLOCKED")
        self.assertTrue(any(
            "artifact hash record is non-canonical" in blocker
            for blocker in result["code_blockers"]))

    def test_deployment_evidence_does_not_backfill_code_readiness(self):
        report = owner_report()
        policy = acceptance_policy()
        evidence = current_evidence(encoded(report), encoded(policy))
        evidence["release_evidence"]["owned_nullblk_qualification"]["status"] = "IN_PROGRESS"
        result = evaluate(report, evidence, policy)
        self.assertEqual(result["CODE_PRODUCTION_READY"], "BLOCKED")
        self.assertEqual(result["DEPLOYMENT_PRODUCTION_READY"], "BLOCKED")
        self.assertTrue(any(
            "code production-readiness" in blocker
            for blocker in result["deployment_blockers"]))

    def test_installed_bytes_and_armed_harness_are_deployment_gates(self):
        report = owner_report()
        policy = acceptance_policy()
        evidence = current_evidence(encoded(report), encoded(policy))
        evidence["release_evidence"]["installed_artifact_identity"]["installed"] = False
        evidence["release_evidence"]["cold_boot_harness"]["armed"] = False
        result = evaluate(report, evidence, policy)
        self.assertEqual(result["CODE_PRODUCTION_READY"], "PASS")
        self.assertEqual(result["DEPLOYMENT_PRODUCTION_READY"], "BLOCKED")
        self.assertEqual(result["PRODUCTION_READY_FOR_OWNER_REBOOT"], "NO")
        self.assertTrue(any(
            "installed bytes" in blocker for blocker in result["deployment_blockers"]))
        self.assertTrue(any(
            "not armed" in blocker for blocker in result["deployment_blockers"]))

    def test_real_swap_requires_persistent_evidence_and_exact_digest_binding(self):
        report = owner_report()
        policy = acceptance_policy()
        report_raw = encoded(report)
        policy_raw = encoded(policy)
        physical = real_swap_evidence(report_raw, policy_raw)
        raw = encoded(physical)
        evidence = current_evidence(report_raw, policy_raw, raw)

        missing = EVALUATOR.evaluate_release(
            SOURCE, report, report_raw, evidence, policy, policy_raw)
        self.assertEqual(missing["CODE_PRODUCTION_READY"], "BLOCKED")
        self.assertTrue(any(
            "persistent physical evidence is missing" in blocker
            for blocker in missing["code_blockers"]))

        evidence["release_evidence"]["real_linux_swap"]["evidence_sha256"] = (
            "9" * 64)
        mismatched = EVALUATOR.evaluate_release(
            SOURCE, report, report_raw, evidence, policy, policy_raw,
            physical, raw)
        self.assertEqual(mismatched["CODE_PRODUCTION_READY"], "BLOCKED")
        self.assertTrue(any(
            "persistent evidence digest binding mismatch" in blocker
            for blocker in mismatched["code_blockers"]))

    def test_real_swap_persistent_evidence_binds_nested_result_and_helpers(self):
        report = owner_report()
        policy = acceptance_policy()
        report_raw = encoded(report)
        policy_raw = encoded(policy)
        for name, key, value in (
                ("execution-control", "physical_execution_control_sha256", "bad"),
                ("helper", "helper_sha256", "5" * 64),
                ("oracle", "oracle_sha256", "6" * 64),
                ("cycles", "cycles_passed", 1),
                ("owner-report", "qualification_report_sha256", "7" * 64)):
            with self.subTest(name=name):
                physical = real_swap_evidence(report_raw, policy_raw)
                physical["result"][key] = value
                raw = encoded(physical)
                evidence = current_evidence(report_raw, policy_raw, raw)
                result = EVALUATOR.evaluate_release(
                    SOURCE, report, report_raw, evidence, policy, policy_raw,
                    physical, raw)
                self.assertEqual(result["CODE_PRODUCTION_READY"], "BLOCKED")

    def test_real_swap_private_executor_must_be_distinct_and_installed_locked(self):
        report = owner_report()
        policy = acceptance_policy()
        report_raw = encoded(report)
        policy_raw = encoded(policy)

        aliased = real_swap_evidence(report_raw, policy_raw)
        aliased["physical_execution_control_sha256"] = ARTIFACTS[
            "formatter_sha256"]
        aliased["result"]["physical_execution_control_sha256"] = ARTIFACTS[
            "formatter_sha256"]
        raw = encoded(aliased)
        evidence = current_evidence(report_raw, policy_raw, raw)
        result = EVALUATOR.evaluate_release(
            SOURCE, report, report_raw, evidence, policy, policy_raw,
            aliased, raw)
        self.assertEqual(result["CODE_PRODUCTION_READY"], "BLOCKED")
        self.assertTrue(any(
            "private execution control aliases installed formatter" in blocker
            for blocker in result["code_blockers"]))

        unlocked = real_swap_evidence(report_raw, policy_raw)
        unlocked["installed_control_privileged_execution_enabled"] = True
        unlocked["result"][
            "installed_control_privileged_execution_enabled"] = True
        raw = encoded(unlocked)
        evidence = current_evidence(report_raw, policy_raw, raw)
        result = EVALUATOR.evaluate_release(
            SOURCE, report, report_raw, evidence, policy, policy_raw,
            unlocked, raw)
        self.assertEqual(result["CODE_PRODUCTION_READY"], "BLOCKED")
        self.assertTrue(any(
            "installed production control was not runtime-locked" in blocker
            for blocker in result["code_blockers"]))

    def test_real_swap_persistent_evidence_requires_fresh_ids_and_matching_envelope(self):
        report = owner_report()
        policy = acceptance_policy()
        report_raw = encoded(report)
        policy_raw = encoded(policy)
        physical = real_swap_evidence(report_raw, policy_raw)
        nested = physical["result"]
        nested["cycles"][1]["run_id"] = nested["cycles"][0]["run_id"]
        nested["cycles"][1]["linux_swap_uuid"] = nested["cycles"][0][
            "linux_swap_uuid"]
        physical["cycles"] = copy.deepcopy(nested["cycles"])
        raw = encoded(physical)
        evidence = current_evidence(report_raw, policy_raw, raw)
        result = EVALUATOR.evaluate_release(
            SOURCE, report, report_raw, evidence, policy, policy_raw,
            physical, raw)
        self.assertEqual(result["CODE_PRODUCTION_READY"], "BLOCKED")
        self.assertTrue(any(
            "reused a transaction run_id" in blocker
            for blocker in result["code_blockers"]))
        self.assertTrue(any(
            "reused a Linux swap UUID" in blocker
            for blocker in result["code_blockers"]))

        physical = real_swap_evidence(report_raw, policy_raw)
        physical["workload_mib"] += 1
        raw = encoded(physical)
        evidence = current_evidence(report_raw, policy_raw, raw)
        result = EVALUATOR.evaluate_release(
            SOURCE, report, report_raw, evidence, policy, policy_raw,
            physical, raw)
        self.assertEqual(result["CODE_PRODUCTION_READY"], "BLOCKED")
        self.assertTrue(any(
            "persistent evidence/result mismatch for workload_mib" in blocker
            for blocker in result["code_blockers"]))

        physical = real_swap_evidence(report_raw, policy_raw)
        physical["result"]["target_device"] = "invalid-device"
        raw = encoded(physical)
        evidence = current_evidence(report_raw, policy_raw, raw)
        result = EVALUATOR.evaluate_release(
            SOURCE, report, report_raw, evidence, policy, policy_raw,
            physical, raw)
        self.assertEqual(result["CODE_PRODUCTION_READY"], "BLOCKED")
        self.assertTrue(any(
            "target device identity is invalid" in blocker
            for blocker in result["code_blockers"]))

        physical = real_swap_evidence(report_raw, policy_raw)
        physical["target_device"] = "8:2"
        raw = encoded(physical)
        evidence = current_evidence(report_raw, policy_raw, raw)
        result = EVALUATOR.evaluate_release(
            SOURCE, report, report_raw, evidence, policy, policy_raw,
            physical, raw)
        self.assertEqual(result["CODE_PRODUCTION_READY"], "BLOCKED")
        self.assertTrue(any(
            "persistent evidence/result mismatch for target_device" in blocker
            for blocker in result["code_blockers"]))

    def test_real_swap_persistent_evidence_binds_exact_target_byte_size(self):
        report = owner_report()
        policy = acceptance_policy()
        report_raw = encoded(report)
        policy_raw = encoded(policy)
        physical = real_swap_evidence(report_raw, policy_raw)
        wrong_size = TARGET["size_bytes"] + 4096
        physical["target_size_bytes"] = wrong_size
        physical["result"]["target_size_bytes"] = wrong_size
        raw = encoded(physical)
        evidence = current_evidence(report_raw, policy_raw, raw)
        result = EVALUATOR.evaluate_release(
            SOURCE, report, report_raw, evidence, policy, policy_raw,
            physical, raw)
        self.assertEqual(result["CODE_PRODUCTION_READY"], "BLOCKED")
        self.assertTrue(any(
            "authorized target identity mismatch" in blocker
            for blocker in result["code_blockers"]))

    def test_sustained_physical_requires_sealed_campaign_evidence(self):
        report = owner_report()
        policy = acceptance_policy()
        report_raw = encoded(report)
        policy_raw = encoded(policy)
        physical = real_swap_evidence(report_raw, policy_raw)
        physical_raw = encoded(physical)
        campaign = physical_campaign_evidence(policy_raw)
        campaign_raw = encoded(campaign)
        evidence = current_evidence(
            report_raw, policy_raw, physical_raw, campaign_raw)

        missing = EVALUATOR.evaluate_release(
            SOURCE, report, report_raw, evidence, policy, policy_raw,
            physical, physical_raw)
        self.assertEqual(missing["CODE_PRODUCTION_READY"], "BLOCKED")
        self.assertTrue(any(
            "persistent campaign evidence is missing" in blocker
            for blocker in missing["code_blockers"]))

        evidence["release_evidence"]["sustained_physical_performance"][
            "evidence_sha256"] = "8" * 64
        mismatched = EVALUATOR.evaluate_release(
            SOURCE, report, report_raw, evidence, policy, policy_raw,
            physical, physical_raw, campaign, campaign_raw)
        self.assertEqual(mismatched["CODE_PRODUCTION_READY"], "BLOCKED")
        self.assertTrue(any(
            "campaign evidence digest binding mismatch" in blocker
            for blocker in mismatched["code_blockers"]))

    def test_sealed_campaign_binds_source_target_policy_and_tooling(self):
        report = owner_report()
        policy = acceptance_policy()
        policy_raw = encoded(policy)

        mutations = (
            ("source",
             lambda value: value.__setitem__("source_sha", "b" * 40),
             "metric=source_sha observed=" + "b" * 40 +
             " expected=" + SOURCE),
            ("target",
             lambda value: value["target"].__setitem__(
                 "device_bytes", TARGET["size_bytes"] + 4096),
             "authorized target binding mismatch"),
            ("policy",
             lambda value: value["policy"]["acceptance_manifest"].__setitem__(
                 "sha256", "8" * 64),
             "production policy binding mismatch"),
            ("stability",
             lambda value: value["host_stability"].__setitem__(
                 "status", "CHANGED"),
             "host stability is not STABLE"),
            ("sealer",
             lambda value: value["policy"]["evidence_sealer"].__setitem__(
                 "sha256", "9" * 64),
             "evidence_sealer digest differs from current source"),
            ("pair-target-binding",
             lambda value: value["qualification_target_binding"].__setitem__(
                 "consistent", False),
             "qualification target binding is not MATCH"),
        )
        for name, mutate, expected in mutations:
            with self.subTest(name=name):
                campaign = physical_campaign_evidence(policy_raw)
                mutate(campaign)
                result = evaluate(
                    report=report, policy=policy, campaign=campaign)
                self.assertEqual(
                    result["CODE_PRODUCTION_READY"], "BLOCKED")
                self.assertTrue(any(
                    expected in blocker
                    for blocker in result["code_blockers"]))

    def test_strict_json_rejects_duplicate_policy_keys(self):
        with TemporaryDirectory(prefix="swapz-release-json-") as directory:
            path = Path(directory) / "acceptance.json"
            path.write_text(
                '{"schema":"swapz-production-acceptance-v1",'
                '"status":"FROZEN","status":"FROZEN",'
                '"primary_real_swap":{},'
                '"physical_qualification":{}}\n')
            with self.assertRaises(EVALUATOR.EvidenceError):
                EVALUATOR.load_json_strict(path)

    def test_reformatted_frozen_policy_is_not_canonical_evidence(self):
        policy = acceptance_policy()
        serialized_copy = (
            json.dumps(policy, sort_keys=True, separators=(",", ":")) +
            "\n").encode()
        self.assertNotEqual(
            serialized_copy,
            (ROOT / "docs/production-acceptance.json").read_bytes())
        with self.assertRaisesRegex(
                EVALUATOR.EvidenceError, "exact_typed_frozen_bytes"):
            EVALUATOR.validate_acceptance_policy(policy, serialized_copy)

    def test_self_declared_frozen_policy_cannot_raise_host_ram_limit(self):
        policy = acceptance_policy()
        policy["physical_qualification"]["acceptance"]["sustained"][
            "metadata_and_target_peak_ram_bytes_max"] *= 2
        result = evaluate(policy=policy)
        self.assertEqual(result["CODE_PRODUCTION_READY"], "BLOCKED")
        self.assertEqual(result["METADATA_RAM_MEASUREMENT"]["status"],
                         "NOT_MEASURED")
        self.assertEqual(
            result["METADATA_RAM_MEASUREMENT"]["limit_bytes"], 1342177280)
        self.assertTrue(any(
            "differs from tracked frozen manifest" in blocker
            for blocker in result["code_blockers"]))
        self.assertTrue(any(
            "metric=metadata_and_target_peak_ram_bytes observed=unavailable "
            "limit=1342177280" in blocker
            for blocker in result["code_blockers"]))

    def test_seal_must_follow_host_after_capture(self):
        policy = acceptance_policy()
        campaign = physical_campaign_evidence(encoded(policy))
        campaign["sealed_at_utc"] = "2026-11-03T00:00:00+00:00"
        result = evaluate(policy=policy, campaign=campaign)
        self.assertEqual(result["CODE_PRODUCTION_READY"], "BLOCKED")
        self.assertEqual(result["METADATA_RAM_MEASUREMENT"]["status"],
                         "NOT_MEASURED")
        self.assertTrue(any(
            "metric=sealed_at_utc" in blocker
            for blocker in result["code_blockers"]))

    def test_campaign_and_host_times_require_canonical_utc(self):
        policy = acceptance_policy()
        policy_raw = encoded(policy)
        campaign = physical_campaign_evidence(policy_raw)
        trace = campaign["capacity_and_ram"]["metadata_ram_trace"]
        binding = copy.deepcopy(
            campaign["capacity_and_ram"]["metadata_ram_host_binding"])
        binding["host_after_captured_at_utc"] = (
            "2026-11-03 00:00:10+00:00")
        with self.assertRaisesRegex(ValueError, "canonical UTC"):
            EVALUATOR.RAM_TRACE_VALIDATOR[
                "validate_metadata_ram_host_binding"](trace, binding)

        nanosecond_trace = sampled_metadata_ram_trace()
        nanosecond_trace["samples"][-1]["timestamp_utc"] = (
            "2026-11-03T00:00:03.900000001Z")
        EVALUATOR.RAM_TRACE_VALIDATOR["validate_metadata_ram_trace"](
            nanosecond_trace, source_sha=SOURCE,
            mapper_uuid=nanosecond_trace["mapper_uuid"],
            expected_peak_ram_bytes=900 * 1024 * 1024)
        nanosecond_binding = copy.deepcopy(
            campaign["capacity_and_ram"]["metadata_ram_host_binding"])
        nanosecond_binding["host_after_captured_at_utc"] = (
            "2026-11-03T00:00:03.900000000+00:00")
        with self.assertRaisesRegex(ValueError, "outside host snapshot window"):
            EVALUATOR.RAM_TRACE_VALIDATOR[
                "validate_metadata_ram_host_binding"](
                    nanosecond_trace, nanosecond_binding)

        for sealed_at in (
                "2026-11-03 00:00:11+00:00",
                "2026-11-03T00:00:11." + "1" * 10000 + "+00:00"):
            with self.subTest(sealed_at=sealed_at[:32]):
                malformed = physical_campaign_evidence(policy_raw)
                malformed["sealed_at_utc"] = sealed_at
                result = evaluate(policy=policy, campaign=malformed)
                self.assertEqual(
                    result["CODE_PRODUCTION_READY"], "BLOCKED")
                self.assertEqual(
                    result["METADATA_RAM_MEASUREMENT"]["status"],
                    "NOT_MEASURED")
                ram_blockers = [
                    blocker for blocker in result["code_blockers"]
                    if "sealed campaign RAM trace is invalid" in blocker]
                self.assertTrue(ram_blockers, result["code_blockers"])
                self.assertLess(max(map(len, ram_blockers)), 500)

    def test_campaign_report_cannot_predate_sealed_host_evidence(self):
        report = owner_report()
        policy = acceptance_policy()
        report_raw, policy_raw = encoded(report), encoded(policy)
        physical_raw = encoded(real_swap_evidence(report_raw, policy_raw))
        campaign = physical_campaign_evidence(policy_raw)
        campaign_raw = encoded(campaign)
        for record_name in (
                "maximum_capacity_and_ram",
                "sustained_physical_performance"):
            with self.subTest(record=record_name):
                evidence = current_evidence(
                    report_raw, policy_raw, physical_raw, campaign_raw)
                evidence["release_evidence"][record_name][
                    "observed_at_utc"] = "2026-11-03T00:00:10Z"
                result = evaluate(
                    report=report, evidence=evidence, policy=policy,
                    physical=json.loads(physical_raw), campaign=campaign)
                self.assertEqual(result["CODE_PRODUCTION_READY"], "BLOCKED")
                self.assertTrue(any(
                    f"{record_name}: observation predates sealed campaign"
                    in blocker for blocker in result["code_blockers"]))
                if record_name == "maximum_capacity_and_ram":
                    self.assertEqual(
                        result["METADATA_RAM_MEASUREMENT"]["status"],
                        "NOT_MEASURED")
                    self.assertEqual(
                        result["FULL_CAPACITY_LOADED_CONSTRUCTION"],
                        "NOT_MEASURED")

        nanosecond_campaign = physical_campaign_evidence(policy_raw)
        nanosecond_campaign["sealed_at_utc"] = (
            "2026-11-03T00:00:11.123456789+00:00")
        nanosecond_raw = encoded(nanosecond_campaign)
        evidence = current_evidence(
            report_raw, policy_raw, physical_raw, nanosecond_raw)
        evidence["release_evidence"]["maximum_capacity_and_ram"][
            "observed_at_utc"] = "2026-11-03T00:00:11.123456788Z"
        result = evaluate(
            report=report, evidence=evidence, policy=policy,
            physical=json.loads(physical_raw), campaign=nanosecond_campaign)
        self.assertEqual(result["CODE_PRODUCTION_READY"], "BLOCKED")
        self.assertEqual(
            result["METADATA_RAM_MEASUREMENT"]["status"], "NOT_MEASURED")
        self.assertTrue(any(
            "observation predates sealed campaign" in blocker
            for blocker in result["code_blockers"]))

    def test_gc_binding_handles_many_ordered_activity_windows(self):
        # Rootless stress of the declared evidence bounds, with no loaded
        # target and no quadratic per-sample rescan of GC telemetry.
        windows = [{
            "start_monotonic_ns": 100 + index * 4,
            "end_monotonic_ns": 103 + index * 4,
            "gc_wall_ns": 1,
            "gc_victims": 1,
            "gc_pages": 1,
        } for index in range(2000)]
        trace = {"samples": [
            {"phase": "baseline", "monotonic_ns": 1},
            {"phase": "initialization", "monotonic_ns": 50},
            {"phase": "steady", "monotonic_ns": 90},
            *({"phase": "gc",
               "monotonic_ns": window["start_monotonic_ns"] + 1}
              for window in windows),
            {"phase": "teardown", "monotonic_ns": 9000},
        ]}
        binding = {
            "arm_started_monotonic_ns": 80,
            "arm_finished_monotonic_ns": 8500,
            "gc_activity_intervals": windows,
        }
        verify = EVALUATOR.RAM_TRACE_VALIDATOR[
            "validate_metadata_ram_arm_binding"]
        verify(trace, binding)
        trace["samples"][-2]["monotonic_ns"] = 100
        with self.assertRaisesRegex(
                ValueError, "GC sample chronology is invalid"):
            verify(trace, binding)

    def test_adversarial_ram_diagnostics_are_bounded(self):
        validator = EVALUATOR.RAM_TRACE_VALIDATOR[
            "validate_metadata_ram_trace"]
        for metric, invalid in (
                ("timestamp_utc", "private-data" * 10000),
                ("monotonic_ns", 1 << 100000),
                ("mem_available_kib", float("inf")),
                ("mapper_present", "private-data" * 10000)):
            with self.subTest(metric=metric):
                trace = sampled_metadata_ram_trace()
                trace["samples"][15][metric] = invalid
                with self.assertRaises(ValueError) as failure:
                    validator(
                        trace, source_sha=SOURCE,
                        mapper_uuid=trace["mapper_uuid"])
                self.assertLess(len(str(failure.exception)), 400)
                self.assertIn(
                    ("MemAvailable_kib" if metric == "mem_available_kib"
                     else metric), str(failure.exception))

        trace = sampled_metadata_ram_trace()
        with self.assertRaises(ValueError) as failure:
            validator(
                trace, source_sha=SOURCE, mapper_uuid=trace["mapper_uuid"],
                expected_peak_ram_bytes=1 << 100000)
        self.assertLess(len(str(failure.exception)), 400)
        self.assertIn("<integer_over_64_bits>", str(failure.exception))
        self.assertIn(
            f"maximum={EVALUATOR.RAM_TRACE_VALIDATOR['MAX_UINT64']}",
            str(failure.exception))

    def test_missing_host_peak_names_frozen_limit_and_required_samples(self):
        report = owner_report()
        policy = acceptance_policy()
        report_raw, policy_raw = encoded(report), encoded(policy)
        physical = real_swap_evidence(report_raw, policy_raw)
        physical_raw = encoded(physical)
        evidence = current_evidence(report_raw, policy_raw, physical_raw)
        verdict = EVALUATOR.evaluate_release(
            SOURCE, report, report_raw, evidence, policy, policy_raw,
            physical, physical_raw)
        self.assertEqual(verdict["CODE_PRODUCTION_READY"], "BLOCKED")
        self.assertTrue(any(
            "metric=metadata_and_target_peak_ram_bytes observed=unavailable "
            "limit=1342177280" in blocker and "verified teardown" in blocker
            for blocker in verdict["code_blockers"]))

    def test_policy_rejects_extra_top_level_fields(self):
        policy = acceptance_policy()
        policy["unreviewed"] = True
        with self.assertRaises(EVALUATOR.EvidenceError):
            EVALUATOR.validate_acceptance_policy(policy, encoded(policy))


    def test_cli_exit_code_tracks_full_release_verdict(self):
        with mock.patch.object(
                EVALUATOR, "evaluate_release",
                return_value={
                    "schema": "swapz-production-readiness-evaluation-v1",
                    "source_sha": SOURCE,
                    "release_verdict": "PASS",
                    "CODE_PRODUCTION_READY": "PASS",
                    "DEPLOYMENT_PRODUCTION_READY": "PASS",
                    "PRODUCTION_READY_FOR_OWNER_REBOOT": "PASS",
                    "COLD_BOOT_HARNESS": "ARMED",
                    "COLD_BOOT_OBSERVED": "PASS",
                    "code_blockers": [],
                    "deployment_blockers": [],
                }), \
                mock.patch.object(EVALUATOR, "load_json_strict",
                                  return_value=({}, b"{}")), \
                mock.patch.object(sys, "argv", [
                    str(EVALUATOR_PATH), "--source-sha", SOURCE,
                    "--test-results", "/tmp/test-results.json",
                    "--evidence", "/tmp/evidence.json",
                    "--acceptance", "/tmp/acceptance.json",
                ]):
            with mock.patch("builtins.print"):
                self.assertEqual(EVALUATOR.main(), 0)

        for verdict, expected in (("BLOCKED", 2), ("FAIL", 1)):
            with self.subTest(verdict=verdict), \
                    mock.patch.object(
                        EVALUATOR, "evaluate_release",
                        return_value={
                            "schema": "swapz-production-readiness-evaluation-v1",
                            "source_sha": SOURCE,
                            "release_verdict": verdict,
                            "CODE_PRODUCTION_READY": "PASS",
                            "DEPLOYMENT_PRODUCTION_READY": "PASS",
                            "PRODUCTION_READY_FOR_OWNER_REBOOT": "PASS",
                            "COLD_BOOT_HARNESS": "ARMED",
                            "COLD_BOOT_OBSERVED": (
                                "FAIL" if verdict == "FAIL" else "NO"),
                            "code_blockers": [],
                            "deployment_blockers": [],
                        }), \
                    mock.patch.object(EVALUATOR, "load_json_strict",
                                      return_value=({}, b"{}")), \
                    mock.patch.object(sys, "argv", [
                        str(EVALUATOR_PATH), "--source-sha", SOURCE,
                        "--test-results", "/tmp/test-results.json",
                        "--evidence", "/tmp/evidence.json",
                        "--acceptance", "/tmp/acceptance.json",
                    ]):
                with mock.patch("builtins.print"):
                    self.assertEqual(EVALUATOR.main(), expected)

    def test_cli_returns_blocked_for_historical_snapshot(self):
        report = owner_report()
        policy = acceptance_policy()
        evidence = current_evidence(encoded(report), encoded(policy))
        evidence["snapshot_kind"] = "HISTORICAL"
        with TemporaryDirectory(prefix="swapz-release-cli-") as directory:
            directory = Path(directory)
            report_path = directory / "test_results.json"
            evidence_path = directory / "readiness.json"
            acceptance_path = directory / "acceptance.json"
            report_path.write_bytes(encoded(report))
            evidence_path.write_bytes(encoded(evidence))
            acceptance_path.write_bytes(encoded(policy))
            command = [
                sys.executable,
                str(EVALUATOR_PATH),
                "--source-sha",
                SOURCE,
                "--test-results",
                str(report_path),
                "--evidence",
                str(evidence_path),
                "--acceptance",
                str(acceptance_path),
            ]
            result = subprocess.run(
                command, cwd=ROOT, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 2, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["CODE_PRODUCTION_READY"], "BLOCKED")
        self.assertEqual(payload["DEPLOYMENT_PRODUCTION_READY"], "BLOCKED")
        self.assertEqual(payload["release_verdict"], "BLOCKED")

    def test_development_only_restoration_and_fast_test_do_not_replace_make_test(
            self):
        # Cleanup success and a development fast-test PASS cannot replace the
        # incomplete five-stage owner qualification.
        report = owner_report()
        report["overall"] = "BLOCKED"
        report["stages"] = report["stages"][:2]
        private_marker = "secret-private-path-and-token"
        development = {
            "schema": "swapz-physical-development-results-v1",
            "evidence_class": "DEVELOPMENT_ONLY_NOT_PHYSICAL_QUALIFICATION",
            "development_only": True,
            "current_git_head": SOURCE,
            "source_commit_sha": SOURCE,
            "linux_swap_activation_tested": False,
            "physical_media_acceptance": False,
            "production_qualification": False,
            "target_remains_inactive": True,
            "original_header_matches_final": True,
            "final_recovery_state": "COMPLETE",
            "development_test_evidence": {
                "outcome": "FAST_TEST_PASS",
                "preflight": {"status": "PASS", "check": "complete"},
                "native_status": "PASS",
                "fast_test_status": "PASS",
            },
            "device_uuid_path": private_marker,
        }
        result = evaluate(report=report, physical=development)
        self.assertEqual(result["CODE_PRODUCTION_READY"], "BLOCKED")
        self.assertEqual(result["release_verdict"], "BLOCKED")
        self.assertTrue(any(
            "exact-source owner make test is not PASS" in item
            for item in result["code_blockers"]))
        self.assertTrue(any(
            "owner qualification stage set/order is not exactly canonical"
            in item for item in result["code_blockers"]))
        self.assertTrue(any(
            "real_linux_swap: persistent evidence schema is invalid" in item
            for item in result["code_blockers"]))
        self.assertNotIn(private_marker, json.dumps(result))

    def test_blocked_real_swap_preflight_cannot_be_overridden_by_nested_pass(
            self):
        report = owner_report()
        policy = acceptance_policy()
        physical = real_swap_evidence(encoded(report), encoded(policy))
        physical.update(
            status="BLOCKED", phase="PREFLIGHT",
            reason="active unrelated swap")
        result = evaluate(report=report, policy=policy, physical=physical)
        self.assertEqual(result["CODE_PRODUCTION_READY"], "BLOCKED")
        self.assertEqual(result["release_verdict"], "BLOCKED")
        self.assertTrue(any(
            "real_linux_swap: persistent evidence disposition is not PASS"
            in item for item in result["code_blockers"]))
        self.assertTrue(any(
            "real_linux_swap: persistent evidence is not COMPLETE" in item
            for item in result["code_blockers"]))

    def test_known_failed_stage_and_unavailable_stages_are_distinct(self):
        failed = owner_report()
        failed["overall"] = "FAIL"
        failed["stages"][1].update(
            status="FAIL", exit_code=1, failed_phase="native-contract",
            diagnostic="synthetic failure")
        failed_result = evaluate(report=failed)
        self.assertEqual(failed_result["CODE_PRODUCTION_READY"], "BLOCKED")
        self.assertTrue(any(
            "exact-source owner make test is not PASS" in item
            for item in failed_result["code_blockers"]))
        self.assertTrue(any(
            "mandatory owner qualification stages are not PASS" in item
            for item in failed_result["code_blockers"]))

        incomplete = owner_report()
        incomplete["overall"] = "BLOCKED"
        incomplete["stages"] = incomplete["stages"][:1]
        incomplete_result = evaluate(report=incomplete)
        self.assertEqual(incomplete_result["CODE_PRODUCTION_READY"], "BLOCKED")
        self.assertTrue(any(
            "stage set/order is not exactly canonical" in item
            for item in incomplete_result["code_blockers"]))
        self.assertFalse(any(
            "mandatory owner qualification stages are not PASS" in item
            for item in incomplete_result["code_blockers"]))

    def test_previous_source_and_artifact_cannot_qualify_new_source(self):
        report = owner_report()
        policy = acceptance_policy()
        report_raw = encoded(report)
        policy_raw = encoded(policy)
        evidence = current_evidence(report_raw, policy_raw)
        newer_source_sha = "b" * 40
        stale = EVALUATOR.evaluate_release(
            newer_source_sha, report, report_raw, evidence, policy,
            policy_raw)
        self.assertEqual(stale["CODE_PRODUCTION_READY"], "BLOCKED")
        self.assertTrue(any(
            "owner make test is not bound to the release source" in item
            for item in stale["code_blockers"]))
        self.assertTrue(any(
            "release candidate is not frozen on synchronized main" in item
            for item in stale["code_blockers"]))

        changed_artifacts = owner_report()
        changed_artifacts["qualified_artifacts"]["module_sha256"] = "7" * 64
        stale_artifacts = evaluate(report=changed_artifacts)
        self.assertEqual(stale_artifacts["CODE_PRODUCTION_READY"], "BLOCKED")
        self.assertTrue(any(
            "qualified_artifact_hashes: owner artifact binding mismatch"
            in item for item in stale_artifacts["code_blockers"]))

    def test_contradictory_pass_and_blocked_reboot_is_not_observed_pass(self):
        report = owner_report()
        policy = acceptance_policy()
        evidence = current_evidence(encoded(report), encoded(policy))
        evidence["release_evidence"]["owner_observed_reboot"].update(
            status="PASS", observed=True, overall="BLOCKED")
        result = evaluate(report=report, policy=policy, evidence=evidence)
        self.assertEqual(result["COLD_BOOT_OBSERVED"], "NO")
        self.assertEqual(result["release_verdict"], "BLOCKED")

    def test_missing_frozen_physical_arms_cannot_qualify_campaign(self):
        # Historical pre-fix observation, now guarded by this regression:
        # Known evaluator gap: one internally consistent pair currently passes.
        # A self-consistent pair must not replace the frozen cohort.
        policy = acceptance_policy()
        required_pair_count = sum(
            workload["pairs"] for workload in
            policy["physical_qualification"]["workloads"].values())
        campaign = physical_campaign_evidence(encoded(policy))
        self.assertEqual(len(campaign["artifacts"]["pairs"]), required_pair_count)
        campaign["artifacts"]["pairs"] = campaign["artifacts"]["pairs"][:1]
        campaign["record_count"] = 1
        result = evaluate(policy=policy, campaign=campaign)
        self.assertEqual(result["CODE_PRODUCTION_READY"], "BLOCKED")
        self.assertTrue(any(
            f"required={required_pair_count} observed=1" in blocker
            for blocker in result["code_blockers"]))

    def test_zero_real_swap_traffic_cannot_qualify_real_swap(self):
        # Model the producer's workload fields; zero traffic with zero byte
        # mismatches is unavailable proof, not a real-swap PASS.
        report = owner_report()
        policy = acceptance_policy()
        physical = real_swap_evidence(encoded(report), encoded(policy))
        zero_traffic_workload = {
            "concurrent_workers": 2,
            "reuse_rounds": 2,
            "slot_reuse_proven": True,
            "rounds": [
                {"aggregate_verified": {"mismatches": 0}},
                {"aggregate_verified": {"mismatches": 0}},
            ],
            "cgroup_swap_peak_bytes": 0,
            "cgroup_memory_pressure_some_usec": 0,
            "mapper_used_delta_kib": 0,
            "swapz_logical_write_delta": 0,
            "swapz_physical_write_delta": 0,
            "swapz_logical_read_delta": 0,
            "swapz_physical_read_delta": 0,
            "lower_write_sector_delta": 0,
            "lower_write_bytes_delta": 0,
            "lower_read_sector_delta": 0,
            "lower_read_bytes_delta": 0,
            "pswpout_delta": 0,
            "pswpin_delta": 0,
            "oom_delta": 0,
            "oom_kill_delta": 0,
        }
        for cycle in physical["result"]["cycles"]:
            cycle["workload"] = copy.deepcopy(zero_traffic_workload)
        physical["cycles"] = copy.deepcopy(physical["result"]["cycles"])
        result = evaluate(report=report, policy=policy, physical=physical)
        self.assertEqual(result["CODE_PRODUCTION_READY"], "BLOCKED")
        self.assertTrue(any(
            "cycle=1 workload." in blocker and "required=" in blocker
            for blocker in result["code_blockers"]))


    def test_complete_frozen_campaign_and_producer_swap_traffic_pass(self):
        # Complete producer-shaped synthetic qualification is still admissible
        # before the independent owner-reboot gate, not physical qualification.
        policy = acceptance_policy()
        campaign = physical_campaign_evidence(encoded(policy))
        pairs = campaign["artifacts"]["pairs"]
        required = policy["physical_qualification"]["workloads"]
        self.assertEqual(len(pairs), sum(row["pairs"] for row in required.values()))
        for workload, specification in required.items():
            rows = [row for row in pairs if row["workload"] == workload]
            self.assertEqual(
                [row["pair_index"] for row in rows],
                list(range(1, specification["pairs"] + 1)))
            self.assertEqual(
                [row["order"] for row in rows],
                specification["counterbalanced_order"])
        physical = real_swap_evidence(
            encoded(owner_report()), encoded(policy))
        for cycle in physical["cycles"]:
            self.assertEqual(len(cycle["workload"]["rounds"]), 2)
            self.assertGreaterEqual(
                cycle["workload"]["rounds"][0]["swapz_logical_read_delta"],
                policy["primary_real_swap"]["minimum_swap_traffic_mib"] * 1048576)
        result = evaluate(policy=policy, physical=physical, campaign=campaign)
        self.assertEqual(result["CODE_PRODUCTION_READY"], "PASS", result["code_blockers"])
        self.assertEqual(result["DEPLOYMENT_PRODUCTION_READY"], "PASS")

    def test_claimed_pass_cannot_override_failing_physical_audit(self):
        policy = acceptance_policy()
        for mutation in ("missing", "failed", "diagnostics", "omitted"):
            with self.subTest(mutation=mutation):
                campaign = physical_campaign_evidence(encoded(policy))
                audit = campaign["physical_evidence_audit"]
                if mutation == "missing":
                    campaign.pop("physical_evidence_audit")
                elif mutation == "failed":
                    audit["status"] = "FAIL"
                elif mutation == "diagnostics":
                    audit["diagnostics"] = [{
                        "status": "FAIL", "metric": "pair.status"}]
                else:
                    audit["omitted_diagnostic_count"] = 1
                result = evaluate(policy=policy, campaign=campaign)
                self.assertEqual(result["CODE_PRODUCTION_READY"], "BLOCKED")
                self.assertTrue(any(
                    "physical evidence audit is not a complete PASS" in blocker
                    for blocker in result["code_blockers"]))

    def test_frozen_campaign_pair_identity_and_disposition_are_required(self):
        policy = acceptance_policy()
        mutations = (
            ("duplicate-index", lambda rows: rows[1].__setitem__(
                "pair_index", rows[0]["pair_index"])),
            ("missing-workload", lambda rows: rows[0].__setitem__(
                "workload", "not-a-frozen-workload")),
            ("wrong-order", lambda rows: rows[0].__setitem__(
                "order", "swapz-first")),
            ("duplicate-name", lambda rows: rows[1].__setitem__(
                "name", rows[0]["name"])),
            ("excluded-pair", lambda rows: rows[0].update(
                status="EXCLUDED", excluded=True)),
        )
        for name, mutate in mutations:
            with self.subTest(name=name):
                campaign = physical_campaign_evidence(encoded(policy))
                mutate(campaign["artifacts"]["pairs"])
                result = evaluate(policy=policy, campaign=campaign)
                self.assertEqual(result["CODE_PRODUCTION_READY"], "BLOCKED")
                self.assertTrue(any(
                    "sealed campaign" in blocker
                    for blocker in result["code_blockers"]))

    def test_real_swap_round_traffic_thresholds_and_aggregate_binding(self):
        policy = acceptance_policy()
        report = owner_report()
        mutations = (
            ("cgroup-swap", "cgroup_swap_current_bytes_after_fill", 0),
            ("mapper-usage", "mapper_used_delta_kib", 0),
            ("logical-write", "swapz_logical_write_delta", 0),
            ("physical-write", "swapz_physical_write_delta", 0),
            ("logical-read", "swapz_logical_read_delta", 0),
            ("physical-read", "swapz_physical_read_delta", 0),
            ("lower-write", "lower_write_sector_delta", 0),
            ("lower-read", "lower_read_sector_delta", 0),
            ("swapout", "pswpout_delta", 0),
            ("swapin", "pswpin_delta", 0),
            ("byte-mismatch", "aggregate_verified.mismatches", 1),
            ("under-floor", "cgroup_swap_peak_bytes",
             policy["primary_real_swap"]["minimum_swap_traffic_mib"] * 1048576 - 1),
        )
        for name, metric, value in mutations:
            with self.subTest(name=name):
                physical = real_swap_evidence(
                    encoded(report), encoded(policy))
                round_evidence = physical["result"]["cycles"][0]["workload"]["rounds"][0]
                if metric.startswith("aggregate_verified."):
                    round_evidence["aggregate_verified"][metric.split(".")[1]] = value
                else:
                    round_evidence[metric] = value
                physical["cycles"] = copy.deepcopy(physical["result"]["cycles"])
                result = evaluate(report=report, policy=policy, physical=physical)
                self.assertEqual(result["CODE_PRODUCTION_READY"], "BLOCKED")
                self.assertTrue(any(
                    "cycle=1 workload." in blocker for blocker in result["code_blockers"]),
                    result["code_blockers"])


    def _failed_owner_diagnostics(self, private_marker):
        report = owner_report()
        policy = acceptance_policy()
        observed_source_sha = "b" * 40
        observed_module_sha256 = "7" * 64
        report["overall"] = "FAIL"
        report["source_sha"] = observed_source_sha
        report["tested_commit_sha"] = observed_source_sha
        report["qualified_artifacts"][
            "module_sha256"] = observed_module_sha256
        report["stages"][1].update(
            status="FAIL", exit_code=1, failed_phase="native-contract",
            diagnostic=private_marker)
        result = evaluate(report=report, policy=policy)
        return (
            "\n".join(result["code_blockers"]),
            observed_source_sha,
            observed_module_sha256,
        )

    def test_proven_current_source_owner_failure_is_not_missing_evidence(self):
        report = owner_report()
        report["overall"] = "FAIL"
        report["stages"][1].update(
            status="FAIL", exit_code=1, failed_phase="native-contract")
        result = evaluate(report=report)
        self.assertEqual(result["CODE_PRODUCTION_READY"], "BLOCKED")
        self.assertEqual(result["release_verdict"], "FAIL")
        report["source_sha"] = "b" * 40
        report["tested_commit_sha"] = "b" * 40
        stale = evaluate(report=report)
        self.assertEqual(stale["CODE_PRODUCTION_READY"], "BLOCKED")
        self.assertEqual(stale["release_verdict"], "BLOCKED")

    def test_failure_diagnostics_do_not_disclose_private_input(self):
        private_marker = "/private/workspace token=do-not-echo"
        diagnostics, _, _ = self._failed_owner_diagnostics(private_marker)
        self.assertNotIn(private_marker, diagnostics)

    def test_failure_diagnostics_preserve_phase_and_source_artifact_identity(self):
        # Historical pre-fix observation, now guarded by this regression:
        # Known diagnostic gap: the first authoritative failed phase and the
        # required/observed source and artifact identities are currently lost.
        # Retain their exact bindings without exposing raw evidence.
        diagnostics, observed_source_sha, observed_module_sha256 = (
            self._failed_owner_diagnostics("synthetic-private-marker"))
        required_markers = (
            "native-contract",
            "FAIL",
            "owner qualification",
            "mandatory owner qualification stages",
            "required",
            "observed",
            SOURCE,
            observed_source_sha,
            ARTIFACTS["module_sha256"],
            observed_module_sha256,
        )
        missing = [
            marker for marker in required_markers
            if marker not in diagnostics
        ]
        self.assertEqual(missing, [], diagnostics)

if __name__ == "__main__":
    unittest.main()
