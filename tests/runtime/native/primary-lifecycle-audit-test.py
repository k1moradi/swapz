#!/usr/bin/env python3
"""Rootless adversarial contracts for the native primary swap lifecycle.

The behavioral model is intentionally independent of the production coordinator:
it describes externally observable transaction/kernel-state invariants without
performing swapon, swapoff, Device Mapper operations, or privileged I/O.
"""
import errno
import fcntl
import importlib.util
import json
import os
import tempfile
from dataclasses import dataclass, field
from enum import Enum, auto
from functools import lru_cache
from pathlib import Path
import re
import subprocess
import time
import unittest

ROOT = Path(__file__).resolve().parents[3]
PRIMARY_SOURCE = ROOT / "src/userspace/swapz-primary.c"
SWAPZCTL_SOURCE = ROOT / "src/userspace/swapzctl.c"
PACKAGE_DKMS = ROOT / "packaging/package-dkms.sh"
ROOTLESS_RUNNER = ROOT / "tests/tools/test-rootless.sh"
ROOT_MAKEFILE = ROOT / "Makefile"


# C comments and quoted diagnostics must never satisfy native operation guards.
_C_NON_CODE = re.compile(
    r'/\*.*?\*/|//[^\n]*|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'',
    re.DOTALL)


@lru_cache(maxsize=4)
def _c_code_only(source: str) -> str:
    # Keep character offsets and line numbers stable for source-order checks.
    return _C_NON_CODE.sub(
        lambda match: re.sub(r'[^\n]', ' ', match.group(0)), source)


@lru_cache(maxsize=1024)
def c_function_body(source: str, symbol: str, *, code_only: bool = True) -> str:
    """Return one executable C body, optionally preserving literals/comments."""
    parsed_source = _c_code_only(source)
    match = re.search(
        r"(?:static\s+)?(?:int|long)\s+" + re.escape(symbol) +
        r"\s*\([^;]*?\)\s*\{",
        parsed_source, re.S)
    if not match:
        raise AssertionError("missing production function " + symbol)
    start = match.end()
    depth = 1
    for position in range(start, len(parsed_source)):
        if parsed_source[position] == "{":
            depth += 1
        elif parsed_source[position] == "}":
            depth -= 1
            if depth == 0:
                body_source = parsed_source if code_only else source
                return body_source[start:position]
    raise AssertionError("unclosed production function " + symbol)


def c_preprocessed_function_body(source: str, symbol: str,
                                 *, code_only: bool = True) -> str:
    """Return one ordinary-build C body after honoring local conditionals."""
    raw_body = c_function_body(source, symbol, code_only=False)
    synthetic_source = f"int {symbol}(void) {{\n{raw_body}\n}}\n"
    result = subprocess.run(
        ["cc", "-std=c11", "-E", "-P", "-x", "c", "-"],
        cwd=ROOT, input=synthetic_source, text=True, encoding="utf-8",
        errors="replace", stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        check=False)
    if result.returncode:
        raise AssertionError(
            "function preprocessor failed for " + symbol + ":\n" +
            result.stderr)
    return c_function_body(result.stdout, symbol, code_only=code_only)

def c_primary_function_names(source: str) -> tuple[str, ...]:
    """Return production primary function symbols without trusting comments."""
    parsed_source = _c_code_only(source)
    return tuple(dict.fromkeys(re.findall(
        r"(?:static\s+)?(?:int|long)\s+(swapz_primary_[A-Za-z0-9_]+)"
        r"\s*\(",
        parsed_source)))


def c_function_calls(source: str, symbol: str,
                     available: set[str]) -> set[str]:
    body = c_function_body(source, symbol)
    # Scan executable calls once instead of searching every candidate name.
    called = set(re.findall(r"\b(swapz_primary_[A-Za-z0-9_]+)\s*\(", body))
    return (called & available) - {symbol}


def c_function_reaches(source: str, start: str, target: str,
                       available: set[str],
                       seen: set[str] | None = None) -> bool:
    """Follow only executable production calls; never comments/diagnostics."""
    if start == target:
        return True
    visited = set() if seen is None else set(seen)
    if start in visited:
        return False
    visited.add(start)
    return any(
        c_function_reaches(source, called, target, available, visited)
        for called in c_function_calls(source, start, available))


def cross_namespace_mount_scanners(source: str) -> tuple[str, ...]:
    """Locate production PID mount-table scanners by behavior, not name."""
    candidates = []
    for symbol in c_primary_function_names(source):
        executable = c_function_body(source, symbol)
        raw = c_function_body(source, symbol, code_only=False)
        enumerates = re.search(
            r"\b(?:readdir|fdopendir|getdents|getdents64)\s*\(",
            executable)
        if "mountinfo" in raw and enumerates:
            candidates.append(symbol)
    if not candidates:
        raise AssertionError(
            "missing production cross-PID mountinfo scanner")
    return tuple(candidates)


def _primary_preprocessor(definitions=(), source_text=None):
    command = ["cc", "-std=c11", "-E", "-dM"]
    command.extend(f"-D{definition}" for definition in definitions)
    if source_text is None:
        command.append(str(PRIMARY_SOURCE))
    else:
        command.extend(("-x", "c", "-"))
    return subprocess.run(
        command, cwd=ROOT, input=source_text, text=True, encoding="utf-8",
        errors="replace", stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        check=False)


def active_preprocessor_macros(definitions=(), source_text=None):
    result = _primary_preprocessor(definitions, source_text)
    if result.returncode:
        raise AssertionError(
            "primary preprocessor configuration failed:\n" + result.stderr)
    macros = {}
    for line in result.stdout.splitlines():
        match = re.fullmatch(
            r"#define\s+([A-Za-z_]\w*)(?:\s+(.*))?", line)
        if match:
            macros[match.group(1)] = match.group(2) or ""
    return macros


def preprocessed_primary_source(definitions=()):
    command = ["cc", "-std=c11", "-E", "-P"]
    command.extend(f"-D{definition}" for definition in definitions)
    command.append(str(PRIMARY_SOURCE))
    result = subprocess.run(
        command, cwd=ROOT, text=True, encoding="utf-8", errors="replace",
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if result.returncode:
        raise AssertionError(
            "primary preprocessor source failed:\n" + result.stderr)
    return result.stdout


class DurableStage(Enum):
    READY = auto()
    STARTING = auto()
    ACTIVE = auto()
    STOPPING = auto()
    RECOVERY_REQUIRED = auto()
    RECOVERING = auto()
    RESTORED = auto()
    COMPLETE = auto()


class OperationResult(Enum):
    SUCCESS = auto()
    FAILURE = auto()
    AMBIGUOUS = auto()


class InventoryResult(Enum):
    EXACT_ACTIVE = auto()
    EXACT_INACTIVE = auto()
    WRONG_DEVICE_ACTIVE = auto()
    UNREADABLE = auto()


@dataclass
class KernelFacts:
    mapper_present: bool = True
    mapper_active: bool = False
    raw_backing_active: bool = False
    mapper_identity_matches: bool = True


@dataclass
class FakeKernelAdapter:
    facts: KernelFacts
    swapon_result: OperationResult = OperationResult.SUCCESS
    swapoff_result: OperationResult = OperationResult.SUCCESS
    # Inventories cannot contradict actual fake kernel state. Only an
    # unreadable inventory or an unexpected device may be injected freely.
    inventory_results: tuple[InventoryResult, ...] = ()
    swapon_applies: bool = True
    swapoff_applies: bool = True
    swapon_calls: int = 0
    swapoff_calls: int = 0
    remove_calls: int = 0
    inventory_calls: int = 0
    remove_failure_once: bool = False
    operation_trace: list[str] = field(default_factory=list)

    def swapon(self) -> OperationResult:
        self.operation_trace.append("swapon")
        self.swapon_calls += 1
        if (self.swapon_result is not OperationResult.FAILURE and
                self.swapon_applies):
            self.facts.mapper_active = True
        return self.swapon_result

    def swapoff(self) -> OperationResult:
        self.operation_trace.append("swapoff")
        self.swapoff_calls += 1
        if (self.swapoff_result is not OperationResult.FAILURE and
                self.swapoff_applies):
            self.facts.mapper_active = False
        return self.swapoff_result

    def inventory(self) -> InventoryResult:
        self.operation_trace.append("inventory")
        observed = (self.inventory_results[self.inventory_calls]
                    if self.inventory_calls < len(self.inventory_results)
                    else None)
        self.inventory_calls += 1
        actual = (InventoryResult.EXACT_ACTIVE if self.facts.mapper_active
                  else InventoryResult.EXACT_INACTIVE)
        if observed in (InventoryResult.EXACT_ACTIVE,
                        InventoryResult.EXACT_INACTIVE) and observed is not actual:
            raise AssertionError("fake inventory contradicts kernel state")
        return observed if observed is not None else actual

    def remove_mapper(self) -> bool:
        self.operation_trace.append("remove_mapper")
        self.remove_calls += 1
        if self.facts.mapper_active:
            return False
        if self.remove_failure_once:
            self.remove_failure_once = False
            return False
        self.facts.mapper_present = False
        return True


@dataclass
class LifecycleModel:
    run_id: str
    owner_run_id: str
    stage: DurableStage = DurableStage.READY

    def _authorized(self, run_id: str) -> bool:
        return run_id == self.run_id == self.owner_run_id

    def begin_start(self, run_id: str) -> bool:
        if not self._authorized(run_id) or self.stage is not DurableStage.READY:
            return False
        self.stage = DurableStage.STARTING
        return True

    def activate(self, run_id: str, kernel: FakeKernelAdapter) -> bool:
        if not self._authorized(run_id) or self.stage is not DurableStage.STARTING:
            return False
        if (not kernel.facts.mapper_present or
                not kernel.facts.mapper_identity_matches or
                kernel.facts.raw_backing_active):
            self.stage = DurableStage.RECOVERY_REQUIRED
            return False

        before = kernel.inventory()
        if before is InventoryResult.EXACT_ACTIVE:
            # STARTING is never promoted from a pre-existing active mapper.
            # Recovery owns reconciliation of an interrupted swapon attempt.
            self.stage = DurableStage.RECOVERY_REQUIRED
            return False
        if before is not InventoryResult.EXACT_INACTIVE:
            self.stage = DurableStage.RECOVERY_REQUIRED
            return False

        operation = kernel.swapon()
        if operation is OperationResult.FAILURE:
            self.stage = DurableStage.RECOVERY_REQUIRED
            return False
        after = kernel.inventory()
        if after is InventoryResult.EXACT_ACTIVE:
            self.stage = DurableStage.ACTIVE
            return True

        # A successful or ambiguous syscall is not proof of activation. The
        # exact mapper must be independently visible in the kernel inventory.
        self.stage = DurableStage.RECOVERY_REQUIRED
        return False

    def begin_stop(self, run_id: str) -> bool:
        if not self._authorized(run_id) or self.stage is not DurableStage.ACTIVE:
            return False
        self.stage = DurableStage.STOPPING
        return True

    def deactivate_and_remove(self, run_id: str, kernel: FakeKernelAdapter) -> bool:
        if (not self._authorized(run_id) or
                self.stage not in (DurableStage.STOPPING,
                                   DurableStage.RECOVERING)):
            return False
        if (not kernel.facts.mapper_identity_matches or
                kernel.facts.raw_backing_active):
            self.stage = DurableStage.RECOVERY_REQUIRED
            return False

        before = kernel.inventory()
        if before in (InventoryResult.WRONG_DEVICE_ACTIVE,
                      InventoryResult.UNREADABLE):
            self.stage = DurableStage.RECOVERY_REQUIRED
            return False
        if before is InventoryResult.EXACT_ACTIVE:
            operation = kernel.swapoff()
            if operation is OperationResult.FAILURE:
                self.stage = DurableStage.RECOVERY_REQUIRED
                return False
            after = kernel.inventory()
            if after is not InventoryResult.EXACT_INACTIVE:
                self.stage = DurableStage.RECOVERY_REQUIRED
                return False

        if kernel.facts.mapper_present and not kernel.remove_mapper():
            self.stage = DurableStage.RECOVERY_REQUIRED
            return False
        self.stage = DurableStage.COMPLETE
        return True

    def begin_recovery(self, run_id: str) -> bool:
        if not self._authorized(run_id):
            return False
        if self.stage not in (DurableStage.STARTING,
                              DurableStage.ACTIVE,
                              DurableStage.STOPPING,
                              DurableStage.RECOVERY_REQUIRED,
                              DurableStage.RECOVERING,
                              DurableStage.RESTORED):
            return False
        self.stage = DurableStage.RECOVERING
        return True


class PrimaryLifecycleBehaviorTest(unittest.TestCase):
    def new_model(self):
        return LifecycleModel(run_id="a" * 32, owner_run_id="a" * 32)

    def test_active_requires_exact_kernel_inventory_proof(self):
        model = self.new_model()
        self.assertTrue(model.begin_start(model.run_id))
        kernel = FakeKernelAdapter(
            KernelFacts(),
            inventory_results=(InventoryResult.EXACT_INACTIVE,
                               InventoryResult.EXACT_ACTIVE))
        self.assertTrue(model.activate(model.run_id, kernel))
        self.assertIs(model.stage, DurableStage.ACTIVE)
        self.assertEqual(kernel.swapon_calls, 1)
        self.assertEqual(kernel.operation_trace,
                         ["inventory", "swapon", "inventory"])

    def test_duplicate_start_is_rejected(self):
        model = self.new_model()
        self.assertTrue(model.begin_start(model.run_id))
        self.assertFalse(model.begin_start(model.run_id))
        self.assertIs(model.stage, DurableStage.STARTING)

    def test_swapon_success_without_inventory_proof_requires_recovery(self):
        model = self.new_model()
        self.assertTrue(model.begin_start(model.run_id))
        kernel = FakeKernelAdapter(
            KernelFacts(),
            swapon_result=OperationResult.SUCCESS,
            inventory_results=(InventoryResult.EXACT_INACTIVE,
                               InventoryResult.UNREADABLE))
        self.assertFalse(model.activate(model.run_id, kernel))
        self.assertIs(model.stage, DurableStage.RECOVERY_REQUIRED)

    def test_ambiguous_swapon_can_be_reconciled_only_by_exact_active_state(self):
        model = self.new_model()
        self.assertTrue(model.begin_start(model.run_id))
        kernel = FakeKernelAdapter(
            KernelFacts(),
            swapon_result=OperationResult.AMBIGUOUS,
            inventory_results=(InventoryResult.EXACT_INACTIVE,
                               InventoryResult.EXACT_ACTIVE))
        self.assertTrue(model.activate(model.run_id, kernel))
        self.assertIs(model.stage, DurableStage.ACTIVE)

    def test_preexisting_exact_active_mapper_requires_recovery(self):
        model = self.new_model()
        self.assertTrue(model.begin_start(model.run_id))
        kernel = FakeKernelAdapter(
            KernelFacts(mapper_active=True),
            inventory_results=(InventoryResult.EXACT_ACTIVE,))
        self.assertFalse(model.activate(model.run_id, kernel))
        self.assertEqual(kernel.swapon_calls, 0)
        self.assertIs(model.stage, DurableStage.RECOVERY_REQUIRED)

    def test_recovery_reconciles_exact_active_mapper_without_reissuing_swapon(self):
        model = self.new_model()
        model.stage = DurableStage.STARTING
        kernel = FakeKernelAdapter(KernelFacts(mapper_active=True))
        self.assertTrue(model.begin_recovery(model.run_id))
        self.assertTrue(model.deactivate_and_remove(model.run_id, kernel))
        self.assertEqual(kernel.swapon_calls, 0)
        self.assertEqual(kernel.swapoff_calls, 1)
        self.assertEqual(kernel.remove_calls, 1)
        self.assertIs(model.stage, DurableStage.COMPLETE)

    def test_recovery_refuses_active_mapper_with_unexpected_identity(self):
        model = self.new_model()
        model.stage = DurableStage.STARTING
        kernel = FakeKernelAdapter(
            KernelFacts(mapper_active=True, mapper_identity_matches=False))
        self.assertTrue(model.begin_recovery(model.run_id))
        self.assertFalse(model.deactivate_and_remove(model.run_id, kernel))
        self.assertEqual(kernel.swapoff_calls, 0)
        self.assertEqual(kernel.remove_calls, 0)
        self.assertIs(model.stage, DurableStage.RECOVERY_REQUIRED)

    def test_wrong_active_device_never_satisfies_activation(self):
        model = self.new_model()
        self.assertTrue(model.begin_start(model.run_id))
        kernel = FakeKernelAdapter(
            KernelFacts(),
            inventory_results=(InventoryResult.EXACT_INACTIVE,
                               InventoryResult.WRONG_DEVICE_ACTIVE))
        self.assertFalse(model.activate(model.run_id, kernel))
        self.assertIs(model.stage, DurableStage.RECOVERY_REQUIRED)

    def test_raw_backing_swap_refuses_activation_before_swapon(self):
        model = self.new_model()
        self.assertTrue(model.begin_start(model.run_id))
        kernel = FakeKernelAdapter(
            KernelFacts(raw_backing_active=True),
            inventory_results=(InventoryResult.EXACT_INACTIVE,
                               InventoryResult.EXACT_ACTIVE))
        self.assertFalse(model.activate(model.run_id, kernel))
        self.assertEqual(kernel.swapon_calls, 0)

    def test_swapoff_success_and_inactive_proof_precede_removal(self):
        model = self.new_model()
        model.stage = DurableStage.ACTIVE
        self.assertTrue(model.begin_stop(model.run_id))
        kernel = FakeKernelAdapter(
            KernelFacts(mapper_active=True),
            inventory_results=(InventoryResult.EXACT_ACTIVE,
                               InventoryResult.EXACT_INACTIVE))
        self.assertTrue(model.deactivate_and_remove(model.run_id, kernel))
        self.assertEqual(kernel.swapoff_calls, 1)
        self.assertEqual(kernel.remove_calls, 1)
        self.assertFalse(kernel.facts.mapper_present)
        self.assertEqual(kernel.operation_trace,
                         ["inventory", "swapoff", "inventory", "remove_mapper"])
        self.assertIs(model.stage, DurableStage.COMPLETE)

    def test_definite_swapoff_failure_preserves_mapper(self):
        model = self.new_model()
        model.stage = DurableStage.ACTIVE
        self.assertTrue(model.begin_stop(model.run_id))
        kernel = FakeKernelAdapter(
            KernelFacts(mapper_active=True),
            swapoff_result=OperationResult.FAILURE,
            inventory_results=(InventoryResult.EXACT_ACTIVE,
                               InventoryResult.EXACT_INACTIVE))
        self.assertFalse(model.deactivate_and_remove(model.run_id, kernel))
        self.assertEqual(kernel.remove_calls, 0)
        self.assertTrue(kernel.facts.mapper_present)
        self.assertIs(model.stage, DurableStage.RECOVERY_REQUIRED)

    def test_ambiguous_swapoff_with_active_inventory_preserves_mapper(self):
        model = self.new_model()
        model.stage = DurableStage.ACTIVE
        self.assertTrue(model.begin_stop(model.run_id))
        kernel = FakeKernelAdapter(
            KernelFacts(mapper_active=True),
            swapoff_result=OperationResult.AMBIGUOUS,
            swapoff_applies=False,
            inventory_results=(InventoryResult.EXACT_ACTIVE,
                               InventoryResult.EXACT_ACTIVE))
        self.assertFalse(model.deactivate_and_remove(model.run_id, kernel))
        self.assertEqual(kernel.remove_calls, 0)

    def test_ambiguous_swapoff_with_exact_inactive_proof_can_finish(self):
        model = self.new_model()
        model.stage = DurableStage.RECOVERING
        kernel = FakeKernelAdapter(
            KernelFacts(mapper_active=True),
            swapoff_result=OperationResult.AMBIGUOUS,
            inventory_results=(InventoryResult.EXACT_ACTIVE,
                               InventoryResult.EXACT_INACTIVE))
        self.assertTrue(model.deactivate_and_remove(model.run_id, kernel))
        self.assertEqual(kernel.remove_calls, 1)
        self.assertIs(model.stage, DurableStage.COMPLETE)

    def test_inventory_failure_after_swapoff_blocks_mapper_removal(self):
        model = self.new_model()
        model.stage = DurableStage.STOPPING
        kernel = FakeKernelAdapter(
            KernelFacts(mapper_active=True),
            inventory_results=(InventoryResult.EXACT_ACTIVE,
                               InventoryResult.UNREADABLE))
        self.assertFalse(model.deactivate_and_remove(model.run_id, kernel))
        self.assertEqual(kernel.remove_calls, 0)

    def test_recovery_skips_swapoff_when_exact_mapper_is_already_inactive(self):
        model = self.new_model()
        model.stage = DurableStage.RECOVERING
        kernel = FakeKernelAdapter(
            KernelFacts(mapper_active=False),
            inventory_results=(InventoryResult.EXACT_INACTIVE,))
        self.assertTrue(model.deactivate_and_remove(model.run_id, kernel))
        self.assertEqual(kernel.swapoff_calls, 0)
        self.assertEqual(kernel.remove_calls, 1)
        self.assertIs(model.stage, DurableStage.COMPLETE)

    def test_recovery_repeats_after_swapoff_before_mapper_removal(self):
        model = self.new_model()
        model.stage = DurableStage.ACTIVE
        self.assertTrue(model.begin_stop(model.run_id))
        kernel = FakeKernelAdapter(
            KernelFacts(mapper_active=True), remove_failure_once=True)
        self.assertFalse(model.deactivate_and_remove(model.run_id, kernel))
        self.assertIs(model.stage, DurableStage.RECOVERY_REQUIRED)
        self.assertTrue(kernel.facts.mapper_present)
        self.assertFalse(kernel.facts.mapper_active)

        self.assertTrue(model.begin_recovery(model.run_id))
        self.assertTrue(model.deactivate_and_remove(model.run_id, kernel))
        self.assertEqual(kernel.swapoff_calls, 1)
        self.assertEqual(kernel.remove_calls, 2)
        self.assertFalse(kernel.facts.mapper_present)
        self.assertIs(model.stage, DurableStage.COMPLETE)

    def test_recovery_accepts_proven_inactive_already_absent_mapper(self):
        model = self.new_model()
        model.stage = DurableStage.RECOVERING
        kernel = FakeKernelAdapter(
            KernelFacts(mapper_present=False, mapper_active=False),
            inventory_results=(InventoryResult.EXACT_INACTIVE,))
        self.assertTrue(model.deactivate_and_remove(model.run_id, kernel))
        self.assertEqual(kernel.swapoff_calls, 0)
        self.assertEqual(kernel.remove_calls, 0)
        self.assertIs(model.stage, DurableStage.COMPLETE)

    def test_stale_old_run_cannot_activate_new_transaction(self):
        model = LifecycleModel(run_id="b" * 32, owner_run_id="b" * 32,
                               stage=DurableStage.STARTING)
        kernel = FakeKernelAdapter(
            KernelFacts(),
            inventory_results=(InventoryResult.EXACT_INACTIVE,
                               InventoryResult.EXACT_ACTIVE))
        self.assertFalse(model.activate("a" * 32, kernel))
        self.assertEqual(kernel.swapon_calls, 0)
        self.assertIs(model.stage, DurableStage.STARTING)

    def test_stale_old_run_cannot_deactivate_new_transaction(self):
        model = LifecycleModel(run_id="b" * 32, owner_run_id="b" * 32,
                               stage=DurableStage.STOPPING)
        kernel = FakeKernelAdapter(
            KernelFacts(mapper_active=True),
            inventory_results=(InventoryResult.EXACT_ACTIVE,
                               InventoryResult.EXACT_INACTIVE))
        self.assertFalse(model.deactivate_and_remove("a" * 32, kernel))
        self.assertEqual(kernel.swapoff_calls, 0)
        self.assertEqual(kernel.remove_calls, 0)

    def test_successful_swapon_without_kernel_effect_cannot_claim_active(self):
        model = self.new_model()
        self.assertTrue(model.begin_start(model.run_id))
        kernel = FakeKernelAdapter(KernelFacts(), swapon_applies=False)
        self.assertFalse(model.activate(model.run_id, kernel))
        self.assertFalse(kernel.facts.mapper_active)
        self.assertEqual(kernel.swapon_calls, 1)
        self.assertIs(model.stage, DurableStage.RECOVERY_REQUIRED)

    def test_successful_swapoff_without_kernel_effect_cannot_remove_mapper(self):
        model = self.new_model()
        model.stage = DurableStage.STOPPING
        kernel = FakeKernelAdapter(KernelFacts(mapper_active=True),
                                   swapoff_applies=False)
        self.assertFalse(model.deactivate_and_remove(model.run_id, kernel))
        self.assertEqual(kernel.swapoff_calls, 1)
        self.assertEqual(kernel.remove_calls, 0)
        self.assertTrue(kernel.facts.mapper_present)
        self.assertTrue(kernel.facts.mapper_active)
        self.assertIs(model.stage, DurableStage.RECOVERY_REQUIRED)

    def test_inventory_cannot_fabricate_inactive_swap_state(self):
        kernel = FakeKernelAdapter(
            KernelFacts(mapper_active=True),
            inventory_results=(InventoryResult.EXACT_INACTIVE,))
        with self.assertRaisesRegex(AssertionError, "contradicts kernel state"):
            kernel.inventory()
        self.assertTrue(kernel.facts.mapper_active)

    def test_ambiguous_swapon_without_kernel_effect_remains_recoverable(self):
        model = self.new_model()
        self.assertTrue(model.begin_start(model.run_id))
        kernel = FakeKernelAdapter(KernelFacts(),
                                   swapon_result=OperationResult.AMBIGUOUS,
                                   swapon_applies=False)
        self.assertFalse(model.activate(model.run_id, kernel))
        self.assertIs(model.stage, DurableStage.RECOVERY_REQUIRED)
        self.assertFalse(kernel.facts.mapper_active)

    def test_durable_interruption_snapshots_recover_exact_owned_state(self):
        snapshots = (
            # STARTING can be durable before any mapper mutation, after mapper
            # creation/resume, or after swapon but before ACTIVE is persisted.
            ("start-before-mapper", DurableStage.STARTING, False, False, 0, 0),
            ("start-mapper-inactive", DurableStage.STARTING, True, False, 0, 1),
            ("start-after-swapon", DurableStage.STARTING, True, True, 1, 1),
            ("active-before-stop", DurableStage.ACTIVE, True, True, 1, 1),
            # STOPPING is durable before swapoff, after swapoff and after remove.
            ("stop-before-swapoff", DurableStage.STOPPING, True, True, 1, 1),
            ("stop-after-swapoff", DurableStage.STOPPING, True, False, 0, 1),
            ("stop-after-remove", DurableStage.STOPPING, False, False, 0, 0),
            ("required-active", DurableStage.RECOVERY_REQUIRED, True, True, 1, 1),
            # RECOVERING itself can be interrupted at each cleanup boundary.
            ("recover-before-swapoff", DurableStage.RECOVERING, True, True, 1, 1),
            ("recover-after-swapoff", DurableStage.RECOVERING, True, False, 0, 1),
            ("recover-after-remove", DurableStage.RECOVERING, False, False, 0, 0),
            # RESTORED is durable after cleanup but before COMPLETE/owner release.
            ("restored-before-complete", DurableStage.RESTORED, False, False, 0, 0),
        )

        for (name, stage, mapper_present, mapper_active,
             expected_swapoff, expected_remove) in snapshots:
            with self.subTest(snapshot=name):
                model = self.new_model()
                model.stage = stage
                kernel = FakeKernelAdapter(KernelFacts(
                    mapper_present=mapper_present,
                    mapper_active=mapper_active))
                self.assertTrue(model.begin_recovery(model.run_id))
                self.assertIs(model.stage, DurableStage.RECOVERING)
                self.assertTrue(
                    model.deactivate_and_remove(model.run_id, kernel))
                self.assertEqual(kernel.swapoff_calls, expected_swapoff)
                self.assertEqual(kernel.remove_calls, expected_remove)
                self.assertFalse(kernel.facts.mapper_active)
                self.assertFalse(kernel.facts.mapper_present)
                self.assertIs(model.stage, DurableStage.COMPLETE)

    def test_interruption_recovery_never_touches_wrong_mapper(self):
        for stage in (DurableStage.STARTING, DurableStage.ACTIVE,
                      DurableStage.STOPPING, DurableStage.RECOVERY_REQUIRED,
                      DurableStage.RECOVERING, DurableStage.RESTORED):
            with self.subTest(stage=stage.name):
                model = self.new_model()
                model.stage = stage
                kernel = FakeKernelAdapter(KernelFacts(
                    mapper_present=True, mapper_active=True,
                    mapper_identity_matches=False))
                self.assertTrue(model.begin_recovery(model.run_id))
                self.assertFalse(
                    model.deactivate_and_remove(model.run_id, kernel))
                self.assertEqual(kernel.swapoff_calls, 0)
                self.assertEqual(kernel.remove_calls, 0)
                self.assertTrue(kernel.facts.mapper_present)
                self.assertTrue(kernel.facts.mapper_active)
                self.assertIs(model.stage, DurableStage.RECOVERY_REQUIRED)

    def test_repeated_recovery_after_complete_is_rejected(self):
        model = self.new_model()
        model.stage = DurableStage.COMPLETE
        self.assertFalse(model.begin_recovery(model.run_id))


class PrimaryLifecycleSourceGuardTest(unittest.TestCase):
    def test_owned_nullblk_btrfs_root_matches_recovery_across_dev_numbers(self):
        source = PRIMARY_SOURCE.read_text(encoding="utf-8")
        body = c_function_body(
            source,
            "swapz_primary_owned_nullblk_btrfs_filesystems_match",
            code_only=False)
        fixture = r'''#define _GNU_SOURCE
#include <linux/btrfs.h>
#include <linux/magic.h>
#include <sys/stat.h>
#include <sys/sysmacros.h>
#include <sys/vfs.h>
#include <string.h>

static int swapz_primary_owned_nullblk_btrfs_filesystems_match(
    const struct stat *root_directory,
    const struct statfs *root_filesystem_info,
    const struct btrfs_ioctl_fs_info_args *root_filesystem,
    const struct stat *recovery_directory,
    const struct statfs *recovery_filesystem_info,
    const struct btrfs_ioctl_fs_info_args *recovery_filesystem)
{
''' + body + r'''
}

static void set_valid_fs(struct btrfs_ioctl_fs_info_args *filesystem,
                         unsigned char fsid_byte)
{
    filesystem->num_devices = 1;
    filesystem->max_id = 1;
    memset(filesystem->fsid, fsid_byte, BTRFS_FSID_SIZE);
}

int main(void)
{
    struct stat root_directory = {
        .st_dev = makedev(0, 38), .st_mode = S_IFDIR | 0755
    };
    struct stat recovery_directory = {
        .st_dev = makedev(0, 39), .st_mode = S_IFDIR | 0700
    };
    struct statfs root_filesystem_info = {.f_type = BTRFS_SUPER_MAGIC};
    struct statfs recovery_filesystem_info = {
        .f_type = BTRFS_SUPER_MAGIC
    };
    struct btrfs_ioctl_fs_info_args root_filesystem = {0};
    struct btrfs_ioctl_fs_info_args recovery_filesystem = {0};

    set_valid_fs(&root_filesystem, 0x5a);
    set_valid_fs(&recovery_filesystem, 0x5a);
    if (!swapz_primary_owned_nullblk_btrfs_filesystems_match(
            &root_directory, &root_filesystem_info, &root_filesystem,
            &recovery_directory, &recovery_filesystem_info,
            &recovery_filesystem))
        return 1;

    recovery_filesystem.fsid[0] ^= 1;
    if (swapz_primary_owned_nullblk_btrfs_filesystems_match(
            &root_directory, &root_filesystem_info, &root_filesystem,
            &recovery_directory, &recovery_filesystem_info,
            &recovery_filesystem))
        return 2;

    recovery_filesystem.fsid[0] ^= 1;
    root_filesystem.num_devices = 2;
    if (swapz_primary_owned_nullblk_btrfs_filesystems_match(
            &root_directory, &root_filesystem_info, &root_filesystem,
            &recovery_directory, &recovery_filesystem_info,
            &recovery_filesystem))
        return 3;

    root_filesystem.num_devices = 1;
    root_filesystem.max_id = 2;
    if (swapz_primary_owned_nullblk_btrfs_filesystems_match(
            &root_directory, &root_filesystem_info, &root_filesystem,
            &recovery_directory, &recovery_filesystem_info,
            &recovery_filesystem))
        return 4;

    root_filesystem.max_id = 1;
    root_directory.st_dev = makedev(259, 2);
    if (swapz_primary_owned_nullblk_btrfs_filesystems_match(
            &root_directory, &root_filesystem_info, &root_filesystem,
            &recovery_directory, &recovery_filesystem_info,
            &recovery_filesystem))
        return 5;

    root_directory.st_dev = makedev(0, 38);
    root_filesystem_info.f_type = 0xEF53;
    if (swapz_primary_owned_nullblk_btrfs_filesystems_match(
            &root_directory, &root_filesystem_info, &root_filesystem,
            &recovery_directory, &recovery_filesystem_info,
            &recovery_filesystem))
        return 6;

    root_filesystem_info.f_type = BTRFS_SUPER_MAGIC;
    root_directory.st_dev = makedev(0, 0);
    if (swapz_primary_owned_nullblk_btrfs_filesystems_match(
            &root_directory, &root_filesystem_info, &root_filesystem,
            &recovery_directory, &recovery_filesystem_info,
            &recovery_filesystem))
        return 7;

    root_directory.st_dev = makedev(0, 38);
    recovery_directory.st_dev = makedev(8, 3);
    if (swapz_primary_owned_nullblk_btrfs_filesystems_match(
            &root_directory, &root_filesystem_info, &root_filesystem,
            &recovery_directory, &recovery_filesystem_info,
            &recovery_filesystem))
        return 8;
    return 0;
}
'''
        with tempfile.TemporaryDirectory(
                prefix="swapz-btrfs-root-identity-") as directory:
            fixture_path = Path(directory) / "fixture.c"
            executable = Path(directory) / "fixture"
            fixture_path.write_text(fixture, encoding="utf-8")
            compiled = subprocess.run(
                ["cc", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
                 str(fixture_path), "-o", str(executable)],
                cwd=ROOT, capture_output=True, text=True, check=False)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            result = subprocess.run(
                [str(executable)], cwd=ROOT, capture_output=True, text=True,
                check=False)
            self.assertEqual(result.returncode, 0,
                             result.stdout + result.stderr)

    def test_native_swap_operations_are_transaction_ordered(self):
        source = PRIMARY_SOURCE.read_text(encoding="utf-8")
        native_swapon = c_function_body(
            source, "swapz_primary_native_swapon")
        activate = c_function_body(source, "swapz_primary_activate_mapper_swap")
        deactivate = c_function_body(
            source, "swapz_primary_deactivate_mapper_swap")
        macros = active_preprocessor_macros()
        start = c_function_body(source, "swapz_primary_start_prepared")
        stop = c_function_body(source, "swapz_primary_stop_active")
        recover = c_function_body(source, "swapz_primary_recover")

        self.assertIn("swapz_primary_swap_transition_apply(", activate)
        self.assertLess(
            activate.index("swapz_primary_transaction_manifest_matches_at("),
            activate.index("swapz_primary_swap_transition_apply("))
        self.assertIn("swapz_primary_dm_mapper_verify_fd(", activate)
        self.assertEqual(macros.get("SWAP_FLAG_DISCARD"), "0x10000")
        self.assertEqual(
            macros.get("SWAPZ_PRIMARY_SWAP_FLAG_DISCARD_PAGES"), "0x40000")
        self.assertRegex(
            native_swapon,
            r"\bswap_flags\s*=\s*SWAP_FLAG_DISCARD\s*\|\s*"
            r"SWAPZ_PRIMARY_SWAP_FLAG_DISCARD_PAGES\s*;")
        self.assertRegex(
            native_swapon,
            r"\bsyscall\s*\(\s*SYS_swapon\s*,\s*mapper_path\s*,"
            r"\s*swap_flags\s*\)")
        self.assertEqual(native_swapon.count("syscall"), 1)
        self.assertNotIn("SWAP_FLAG_DISCARD_ONCE", native_swapon)
        self.assertNotIn("SWAP_FLAG_PREFER", native_swapon)
        self.assertNotRegex(
            native_swapon,
            r"\bsyscall\s*\(\s*SYS_swapon\s*,\s*mapper_path\s*,"
            r"\s*0\s*\)")
        self.assertLess(
            start.index("swapz_primary_activate_mapper_swap("),
            start.index("active_state.stage = SWAPZ_PRIMARY_STAGE_ACTIVE"))

        self.assertIn("swapz_primary_swap_transition_apply(", deactivate)
        self.assertLess(
            deactivate.index("swapz_primary_transaction_manifest_matches_at("),
            deactivate.index("swapz_primary_swap_transition_apply("))
        self.assertIn("return syscall(SYS_swapoff, mapper_path);", source)
        self.assertIn("swapz_primary_dm_mapper_verify_fd(", deactivate)
        transition = c_function_body(
            source, "swapz_primary_swap_transition_apply")
        self.assertLess(
            transition.index("ops->swapon(ops->context, mapper_path)"),
            transition.index(
                "ops->device_active(ops->context, mapper_device)",
                transition.index("ops->swapon(ops->context, mapper_path)")))
        self.assertIn("syscall_errno != EINTR", transition)
        self.assertLess(
            stop.index("swapz_primary_deactivate_mapper_swap("),
            stop.index("swapz_primary_dm_remove_mapper("))
        self.assertLess(
            recover.index("swapz_primary_deactivate_mapper_swap("),
            recover.index("swapz_primary_dm_remove_mapper("))

    def test_cross_namespace_mount_scan_revalidates_before_first_mutation(self):
        source = PRIMARY_SOURCE.read_text(encoding="utf-8")
        functions = set(c_primary_function_names(source))
        scanners = cross_namespace_mount_scanners(source)

        current_mounts_raw = c_function_body(
            source, "swapz_primary_read_mount_facts", code_only=False)
        self.assertIn("/proc/self/mountinfo", current_mounts_raw)

        # Build executable call references once. Reverse reachability retains
        # the transitive scanner guard, including cycles, without repeated C
        # parsing or searching the full function inventory at every edge.
        direct_callers = {symbol: set() for symbol in functions}
        for caller in functions:
            for callee in c_function_calls(source, caller, functions):
                direct_callers[callee].add(caller)

        def callers_reaching(targets: set[str]) -> set[str]:
            reached = set(targets)
            pending = list(targets)
            while pending:
                for caller in direct_callers[pending.pop()]:
                    if caller not in reached:
                        reached.add(caller)
                        pending.append(caller)
            return reached

        namespace_helpers = {
            symbol for symbol in functions
            if "ns/mnt" in c_function_body(
                source, symbol, code_only=False)
        }
        namespace_callers = callers_reaching(namespace_helpers)
        classified_scanners = tuple(
            scanner for scanner in scanners
            if scanner in namespace_callers)
        self.assertTrue(
            classified_scanners,
            "PID scanner does not classify vanished mount namespaces")

        prepare = c_function_body(source, "swapz_primary_prepare_metadata")
        start = c_function_body(source, "swapz_primary_start_prepared")

        scanner_callers = callers_reaching(set(classified_scanners))

        def text_reaches_scanner(text: str) -> bool:
            # The source slices are already masked against comments and
            # literals, so diagnostics cannot forge a mount scanner call.
            mentioned = set(re.findall(
                r"\b(swapz_primary_[A-Za-z0-9_]+)\s*\(", text))
            return not mentioned.isdisjoint(scanner_callers)

        self.assertTrue(
            text_reaches_scanner(prepare),
            "prepare admission does not reach the cross-PID mount scanner")

        # STARTING must be durable before the first device mutation, but the
        # host/selector snapshot authorizing that mutation must be fresh.
        starting_write = start.index("swapz_primary_state_write_at(")
        # c_function_body() masks quoted arguments to prevent diagnostics
        # from satisfying executable-call checks. Confirm the executable
        # macro call first, then inspect its phase argument in aligned raw C.
        starting_interrupt = start.index("SWAPZ_PRIMARY_TEST_INTERRUPT_AFTER(")
        start_raw = c_function_body(
            source, "swapz_primary_start_prepared", code_only=False)
        self.assertTrue(
            start_raw.startswith(
                'SWAPZ_PRIMARY_TEST_INTERRUPT_AFTER("start-starting")',
                starting_interrupt),
            "STARTING interruption must retain its original phase")
        raw_swapoff = start.index("swapz_primary_transition_original_swap(")
        target_open = start.index("swapz_primary_target_open_exclusive(")
        mapper_create = start.index("swapz_primary_dm_create_mapper(")
        self.assertLess(starting_write, starting_interrupt)
        self.assertLess(starting_interrupt, raw_swapoff)
        self.assertLess(raw_swapoff, target_open)
        self.assertLess(target_open, mapper_create)
        self.assertNotIn("swapz_primary_write_header_checked_fd(", start)

        preswap_window = start[starting_interrupt:raw_swapoff]
        self.assertTrue(
            text_reaches_scanner(preswap_window),
            "cross-PID mount inventory is not freshly revalidated after "
            "durable STARTING and before raw swapoff")
        for required in (
                "swapz_primary_recovery_source_chain(",
                "swapz_primary_root_source_chain(",
                "swapz_primary_selector_admission_still_live(",
                "swapz_primary_selector_admission_read_partuuid(",
                "swapz_primary_target_revalidate("):
            self.assertIn(required, preswap_window)

        # The post-swapoff exclusive backing decision gets another fresh
        # namespace/topology scan before mapper creation. Raw swapoff cannot
        # substitute for mapper-time admission.
        post_swapoff_window = start[target_open:mapper_create]
        self.assertTrue(
            text_reaches_scanner(post_swapoff_window),
            "cross-PID mount inventory is not revalidated after raw swapoff "
            "and before mapper creation")
        self.assertIn("swapz_primary_swap_device_active(", post_swapoff_window)

        # PREPARE still checks the raw target repeatedly without mutation and
        # binds the final activation/priority policy snapshot into the manifest.
        raw_swap_gate = (
            "swapz_primary_original_swap_policy_admissible(original_swap_size_kib)")
        self.assertEqual(prepare.count(raw_swap_gate), 3)
        self.assertIn("swapz_primary_original_swap_policy_snapshot(", prepare)
        self.assertIn("manifest.original_swap_active", prepare)
        self.assertIn("manifest.original_swap_priority", prepare)

        # START owns swapoff; STOP and RECOVER own restoration. All of these
        # transitions are based on the volatile manifest, never raw header data.
        self.assertRegex(
            start,
            r"swapz_primary_transition_original_swap\s*\(\s*&manifest,\s*0,")
        for function_name in (
                "swapz_primary_stop_active", "swapz_primary_recover"):
            body = c_function_body(source, function_name)
            self.assertRegex(
                body,
                r"swapz_primary_transition_original_swap\s*\(\s*&manifest,\s*1,")

    def assert_lifecycle_failure_epilogues(self, source: str):
        """Trace the single fail-closed errno helper from all three epilogues."""
        helper_code = c_preprocessed_function_body(
            source, "swapz_primary_require_recovery_preserving_errno")
        helper_raw = c_preprocessed_function_body(
            source, "swapz_primary_require_recovery_preserving_errno",
            code_only=False)
        self.assertRegex(
            helper_code,
            r"\bif\s*\(\s*swapz_primary_state_require_recovery_at\s*\(")
        self.assertEqual(
            helper_code.count("swapz_primary_state_require_recovery_at("), 1,
            "recovery helper must persist RECOVERY_REQUIRED exactly once")
        self.assertIn("const int primary_errno = original_errno ? original_errno : EIO;",
                      helper_code)
        self.assertIn("const int recovery_errno = errno ? errno : EIO;",
                      helper_code)
        self.assertIn("errno = primary_errno;", helper_code)
        self.assertIn("return primary_errno;", helper_code)
        self.assertIn('"original_errno=%d recovery_errno=%d "', helper_raw)
        self.assertIn("operation, primary_errno, recovery_errno);", helper_code)

        for symbol, operation, persisted, success_stage in (
                ("swapz_primary_start_prepared", "START",
                 "starting_persisted", "ACTIVE"),
                ("swapz_primary_stop_active", "STOP",
                 "stopping_persisted", "COMPLETE"),
                ("swapz_primary_recover", "RECOVER",
                 "recovering_persisted", "COMPLETE")):
            body_code = c_preprocessed_function_body(source, symbol)
            body_raw = c_preprocessed_function_body(
                source, symbol, code_only=False)
            epilogue_start = body_code.rfind("\nout:\n")
            self.assertGreaterEqual(
                epilogue_start, 0, f"{operation}: missing failure epilogue")
            epilogue_code = body_code[epilogue_start:]
            epilogue_raw = body_raw[epilogue_start:]

            persisted_condition = re.escape(persisted)
            if operation != "START":
                persisted_condition += r"\s*&&\s*!complete_persisted"
            guard = re.search(
                r"\bif\s*\(\s*result\s*<\s*0\s*&&\s*" +
                persisted_condition +
                r"\s*&&\s*recovery_fd\s*>=\s*0\s*&&\s*"
                r"lock_fd\s*>=\s*0\s*\)\s*"
                r"saved_errno\s*=\s*"
                r"swapz_primary_require_recovery_preserving_errno\s*\(",
                epilogue_code)
            self.assertIsNotNone(
                guard, f"{operation}: recovery helper is not fail-closed")
            self.assertEqual(
                body_code.count(
                    "swapz_primary_require_recovery_preserving_errno("), 1,
                f"{operation}: recovery helper must run at most once")
            call = re.search(
                rf"saved_errno\s*=\s*"
                rf"swapz_primary_require_recovery_preserving_errno\s*\("
                rf"\s*recovery_fd\s*,\s*lock_fd\s*,\s*state\.run_id\s*,"
                rf'\s*0\s*,\s*"{operation}"\s*,\s*saved_errno\s*\);',
                epilogue_raw)
            self.assertIsNotNone(
                call, f"{operation}: helper must receive the original errno")
            capture = epilogue_code.find("saved_errno = errno ? errno : EIO;")
            self.assertGreaterEqual(
                capture, 0, f"{operation}: original errno not captured")
            publication = re.search(
                rf'if\s*\(\s*result\s*==\s*0\s*\)\s*printf\s*\(\s*'
                rf'"PRIMARY_{operation}={success_stage}', epilogue_raw)
            self.assertIsNotNone(
                publication, f"{operation}: success publication not gated")
            restore = re.search(
                r"if\s*\(\s*result\s*<\s*0\s*\)\s*"
                r"errno\s*=\s*saved_errno\s*;", epilogue_code)
            self.assertIsNotNone(
                restore, f"{operation}: original errno not returned")
            self.assertLess(capture, guard.start())
            self.assertLess(guard.start(), call.start())
            self.assertLess(call.end(), epilogue_code.index("(void)close(target_fd);"))
            self.assertLess(call.end(), publication.start())
            self.assertLess(publication.end(), restore.start())
            self.assertLess(restore.end(), epilogue_code.index("return result;"))

    def test_recovery_persists_fail_closed_interruption_order(self):
        source = PRIMARY_SOURCE.read_text(encoding="utf-8")
        recover = c_function_body(
            source, "swapz_primary_recover", code_only=False)
        recovery_errno_helper = c_function_body(
            source, "swapz_primary_require_recovery_preserving_errno",
            code_only=False)

        normalize = recover.index("swapz_primary_recovery_required_state(")
        persist_required = recover.index(
            "swapz_primary_state_write_at(", normalize)
        persist_recovering = recover.index(
            "recovering_state.stage = SWAPZ_PRIMARY_STAGE_RECOVERING")
        deactivate = recover.index("swapz_primary_deactivate_mapper_swap(")
        remove = recover.index("swapz_primary_dm_remove_mapper(")
        restored = recover.index(
            "restored_state.stage = SWAPZ_PRIMARY_STAGE_RESTORED")
        complete = recover.index(
            "complete_state.stage = SWAPZ_PRIMARY_STAGE_COMPLETE")
        release = recover.index("swapz_primary_release_partition_owner_at(")

        self.assertLess(normalize, persist_required)
        self.assertLess(persist_required, persist_recovering)
        self.assertLess(persist_recovering, deactivate)
        self.assertLess(deactivate, remove)
        self.assertLess(remove, restored)
        self.assertLess(restored, complete)
        self.assertLess(complete, release)
        recovery_update = recover.index(
            "swapz_primary_require_recovery_preserving_errno(")
        self.assertLess(release, recovery_update)
        self.assertLess(
            recover.index("saved_errno = errno ? errno : EIO;"),
            recovery_update)
        self.assertIn(
            "recovering_persisted && !complete_persisted", recover)
        self.assertIn('"RECOVER", saved_errno', recover[recovery_update:])
        self.assertIn(
            "swapz_primary_state_require_recovery_at(",
            recovery_errno_helper)
        self.assertIn("errno = primary_errno;", recovery_errno_helper)
        self.assertIn(
            "original_errno=%d recovery_errno=%d", recovery_errno_helper)
        self.assertIn(
            "case SWAPZ_PRIMARY_STAGE_RESTORED:",
            c_function_body(source, "swapz_primary_state_recoverable"))

        self.assert_lifecycle_failure_epilogues(source)

        # Each isolated source mutant must fail the actual production-linked
        # guard, not a behavioral mock or a comment/string-only assertion.
        for symbol, operation, persisted, success_stage in (
                ("swapz_primary_start_prepared", "START",
                 "starting_persisted", "ACTIVE"),
                ("swapz_primary_stop_active", "STOP",
                 "stopping_persisted", "COMPLETE"),
                ("swapz_primary_recover", "RECOVER",
                 "recovering_persisted", "COMPLETE")):
            body = c_function_body(source, symbol, code_only=False)
            omitted = re.sub(
                r"saved_errno\s*=\s*"
                r"swapz_primary_require_recovery_preserving_errno\s*"
                r"\([^;]*\);", "saved_errno = saved_errno;", body, count=1)
            self.assertNotEqual(omitted, body)
            with self.subTest(operation=operation, mutation="omit-recovery"):
                with self.assertRaises(AssertionError):
                    self.assert_lifecycle_failure_epilogues(
                        source.replace(body, omitted, 1))
            persisted_condition = re.escape(persisted)
            if operation != "START":
                persisted_condition += r"\s*&&\s*!complete_persisted"
            recovery_guard = re.search(
                r"if\s*\(\s*result\s*<\s*0\s*&&\s*" +
                persisted_condition +
                r"\s*&&\s*recovery_fd\s*>=\s*0\s*&&\s*"
                r"lock_fd\s*>=\s*0\s*\)\s*"
                r"saved_errno\s*=\s*"
                r"swapz_primary_require_recovery_preserving_errno\s*"
                r"\([^;]*\);",
                body)
            self.assertIsNotNone(recovery_guard)
            disabled = (
                body[:recovery_guard.start()] + "#if 0\n" +
                recovery_guard.group(0) + "\n#endif" +
                body[recovery_guard.end():])
            with self.subTest(
                    operation=operation,
                    mutation="preprocessor-disabled-recovery"):
                with self.assertRaises(AssertionError):
                    self.assert_lifecycle_failure_epilogues(
                        source.replace(body, disabled, 1))

            publication = re.search(
                rf'if\s*\(result == 0\)\s*printf\s*\(\s*'
                rf'"PRIMARY_{operation}={success_stage}.*?;\n',
                body, re.S)
            self.assertIsNotNone(publication)
            premature = body.replace(publication.group(0), "", 1)
            premature = premature.replace(
                "saved_errno = errno ? errno : EIO;",
                "saved_errno = errno ? errno : EIO;\n" +
                publication.group(0), 1)
            with self.subTest(operation=operation, mutation="early-success"):
                with self.assertRaises(AssertionError):
                    self.assert_lifecycle_failure_epilogues(
                        source.replace(body, premature, 1))

            false_success = body.replace(
                "if (result == 0)\n\t\tprintf(",
                "if (result < 0)\n\t\tprintf(", 1)
            self.assertNotEqual(false_success, body)
            with self.subTest(operation=operation, mutation="failure-as-success"):
                with self.assertRaises(AssertionError):
                    self.assert_lifecycle_failure_epilogues(
                        source.replace(body, false_success, 1))

    def test_execution_gate_is_boot_scoped_pending_live_lifecycle_evidence(self):
        source = PRIMARY_SOURCE.read_text(encoding="utf-8")
        ordinary = active_preprocessor_macros()
        self.assertEqual(
            ordinary.get("SWAPZ_PRIMARY_EXECUTION_ENABLED"), "1",
            "ordinary production must compile the exact lifecycle artifact")
        self.assertEqual(
            ordinary.get("SWAPZ_PRIMARY_CONFIG_BASE"), '"/etc/swapz"')
        self.assertEqual(
            ordinary.get("SWAPZ_PRIMARY_RUNTIME_STATE_BASE"),
            "SWAPZ_PRIMARY_EXECUTION_RUNTIME_DIRECTORY")
        self.assertEqual(
            ordinary.get("SWAPZ_PRIMARY_EXECUTION_RUNTIME_DIRECTORY"),
            '"/run/swapz"')

        owned_definitions = (
            "SWAPZ_PRIMARY_OWNED_NULLBLK_TEST=1",
            'SWAPZ_PRIMARY_TEST_CONFIG_BASE="/var/tmp/swapz-primary-owned-nullblk/config"',
            'SWAPZ_PRIMARY_TEST_RUNTIME_STATE_BASE="/var/tmp/swapz-primary-owned-nullblk/runtime-state"',
            'SWAPZ_PRIMARY_TEST_MUTATION_LOCK_DIRECTORY="/var/tmp/swapz-primary-owned-nullblk/mutation-lock"',
            'SWAPZ_PRIMARY_TEST_QUALIFICATION_REPORT="/var/tmp/swapz-primary-owned-nullblk/recovery/qualification.json"',
        )
        owned = active_preprocessor_macros(owned_definitions)
        self.assertEqual(owned.get("SWAPZ_PRIMARY_EXECUTION_ENABLED"), "1")
        self.assertEqual(
            owned.get("SWAPZ_PRIMARY_CONFIG_BASE"),
            "SWAPZ_PRIMARY_TEST_CONFIG_BASE")
        self.assertEqual(
            owned.get("SWAPZ_PRIMARY_RUNTIME_STATE_BASE"),
            "SWAPZ_PRIMARY_TEST_RUNTIME_STATE_BASE")
        for required in (
                "SWAPZ_PRIMARY_TEST_CONFIG_BASE",
                "SWAPZ_PRIMARY_TEST_RUNTIME_STATE_BASE",
                "SWAPZ_PRIMARY_TEST_MUTATION_LOCK_DIRECTORY",
                "SWAPZ_PRIMARY_TEST_QUALIFICATION_REPORT"):
            missing = tuple(
                definition for definition in owned_definitions
                if not definition.startswith(required + "="))
            self.assertNotEqual(
                _primary_preprocessor(missing).returncode, 0,
                f"owned-null_blk seam compiled without {required}")

        physical_definitions = (
            "SWAPZ_PRIMARY_PHYSICAL_QUALIFICATION_TEST=1",
            'SWAPZ_PRIMARY_PHYSICAL_QUALIFIED_CONTROL="/usr/local/sbin/swapzctl"',
        )
        physical = active_preprocessor_macros(physical_definitions)
        self.assertEqual(physical.get("SWAPZ_PRIMARY_EXECUTION_ENABLED"), "1")
        self.assertEqual(
            physical.get("SWAPZ_PRIMARY_CONFIG_BASE"), '"/etc/swapz"')
        self.assertNotEqual(
            _primary_preprocessor(
                ("SWAPZ_PRIMARY_PHYSICAL_QUALIFICATION_TEST=1",)).returncode,
            0, "physical qualification compiled without explicit control path")
        self.assertNotEqual(
            _primary_preprocessor(
                owned_definitions + physical_definitions).returncode,
            0, "private lifecycle modes compiled together")

        gate = c_function_body(
            source, "swapz_primary_privileged_execution_enabled")
        cleanup_gate = c_function_body(
            source, "swapz_primary_cleanup_execution_enabled")
        runtime_gate = c_function_body(
            source, "swapz_primary_lifecycle_runtime_enabled")
        production_authorization = c_function_body(
            source, "swapz_primary_production_execution_authorized")
        plan = c_function_body(source, "swapz_primary_read_only_plan")
        plan_raw = c_function_body(
            source, "swapz_primary_read_only_plan", code_only=False)
        command = c_function_body(source, "swapz_primary_command")
        self.assertIn("SWAPZ_PRIMARY_EXECUTION_ENABLED", gate)
        self.assertIn("swapz_primary_lifecycle_runtime_enabled()", gate)
        self.assertIn("SWAPZ_PRIMARY_EXECUTION_ENABLED", cleanup_gate)
        self.assertIn(
            "swapz_primary_privileged_execution_enabled()", cleanup_gate)
        self.assertIn(
            "swapz_primary_production_execution_authorized()", runtime_gate)
        for required in (
                "SWAPZ_PRIMARY_EXECUTION_RUNTIME_DIRECTORY",
                "SWAPZ_PRIMARY_EXECUTION_RECORD_NAME",
                "swapz_primary_read_current_boot_id(boot_id)",
                "swapz_primary_configured_target(&target)",
                "swapz_primary_execution_record_matches(",
                "target.device_major", "target.device_minor",
                "SWAPZ_BUILD_SOURCE_SHA"):
            self.assertIn(required, production_authorization)
        self.assertIn("swapz_primary_privileged_execution_enabled()", plan)
        self.assertIn(
            '"\\\"privileged_execution_enabled\\\":%s,"', plan_raw)
        self.assertNotIn(
            '"\\\"privileged_execution_enabled\\\":false,"', plan_raw)
        self.assertIn(
            "!swapz_primary_privileged_execution_enabled()", command)
        self.assertIn(
            "!swapz_primary_cleanup_execution_enabled()", command)

        stop = c_function_body(source, "swapz_primary_stop_active")
        recover = c_function_body(source, "swapz_primary_recover")
        for cleanup in (stop, recover):
            self.assertIn("SWAPZ_BUILD_SOURCE_CLEAN != 1", cleanup)
            self.assertIn(
                "!swapz_primary_valid_source_sha(SWAPZ_BUILD_SOURCE_SHA)",
                cleanup)
            self.assertIn(
                "strcmp(manifest.source_sha, SWAPZ_BUILD_SOURCE_SHA)",
                cleanup)

        ordinary_source = preprocessed_primary_source()
        physical_source = preprocessed_primary_source(physical_definitions)
        self.assertNotIn(
            "SWAPZ_PRIMARY_PHYSICAL_QUALIFICATION", ordinary_source,
            "ordinary production build must not read the physical marker")
        self.assertIn(
            '"/run/swapz"', ordinary_source,
            "ordinary production must retain the boot-scoped runtime lock")
        self.assertIn(
            '"primary-execution.env"', ordinary_source,
            "ordinary production must require the canonical runtime token")
        self.assertRegex(
            physical_source,
            r'\bgetenv\s*\(\s*"SWAPZ_PRIMARY_PHYSICAL_QUALIFICATION"\s*\)')
        self.assertRegex(
            physical_source,
            r'return\s+enabled\s*&&\s*!strcmp\s*\(\s*enabled\s*,\s*"1"'
            r'\s*\)\s*;')

        public_build_files = [ROOT_MAKEFILE]
        public_build_files.extend(sorted(ROOT.glob("src/**/Makefile")))
        public_build_files.extend(
            path for path in sorted((ROOT / "packaging").rglob("*"))
            if path.is_file())
        for path in public_build_files:
            contents = path.read_text(encoding="utf-8")
            for seam in (
                    "SWAPZ_PRIMARY_OWNED_NULLBLK_TEST",
                    "SWAPZ_PRIMARY_PHYSICAL_QUALIFICATION_TEST"):
                self.assertNotIn(
                    seam, contents,
                    f"public build/install file exposes private seam: "
                    f"{path.relative_to(ROOT)}")

        topology = c_function_body(source, "swapz_primary_recovery_source_chain")
        self.assertIn(
            "source_device == SWAPZ_PRIMARY_TARGET_DEVICE", topology)
        self.assertIn("swapz_primary_owned_nullblk_parent(", topology)
        self.assertIn('strstr(device_realpath, "/virtual/") != NULL', source)
        self.assertLess(
            topology.index("swapz_primary_owned_nullblk_parent("),
            topology.index("strstr(device_realpath"))
        self.assertIn(
            'sscanf(line, " %u %63s %c", &major_number, name, &extra) != 2',
            source)
        self.assertIn('strcmp(name, "nullb")', source)

    def test_package_and_primary_share_global_mutation_lock_identity(self):
        package = PACKAGE_DKMS.read_text(encoding="utf-8")
        macros = active_preprocessor_macros()
        ordinary = preprocessed_primary_source()
        lifecycle = c_function_body(
            ordinary, "swapz_primary_run_mutating_action")

        self.assertEqual(
            macros.get("SWAPZ_PRIMARY_MUTATION_LOCK_DIRECTORY"),
            '"/run/lock/swapz"')
        self.assertEqual(
            macros.get("SWAPZ_PRIMARY_MUTATION_LOCK_NAME"),
            '"package.lock"')
        self.assertIn(
            'package_lock="/run/lock/swapz/package.lock"', package)
        self.assertLess(
            package.index("flock -n 9"),
            package.index('primary_runtime_state_base="/run/swapz"'))
        self.assertLess(
            package.index("flock -n 9"),
            package.index("assert_no_primary_runtime_authority upgrade"))
        self.assertLess(
            lifecycle.index("swapz_primary_mutation_lock()"),
            lifecycle.index("swapz_primary_prepare_metadata("))
        self.assertLess(
            lifecycle.index("swapz_primary_mutation_lock()"),
            lifecycle.index("swapz_primary_start_prepared()"))
        self.assertLess(
            lifecycle.index("swapz_primary_mutation_lock()"),
            lifecycle.index("swapz_primary_stop_active()"))
        self.assertLess(
            lifecycle.index("swapz_primary_mutation_lock()"),
            lifecycle.index("swapz_primary_recover()"))

    def test_durable_package_transactions_gate_prepare_and_start(self):
        package = PACKAGE_DKMS.read_text(encoding="utf-8")
        source = PRIMARY_SOURCE.read_text(encoding="utf-8")
        macros = active_preprocessor_macros()
        lifecycle = c_function_body(
            preprocessed_primary_source(),
            "swapz_primary_run_mutating_action")
        transaction_guard = c_function_body(
            source, "swapz_primary_package_transactions_clear_at")

        self.assertIn(
            'transaction_parent="/var/lib/swapz-package-transactions"',
            package)
        self.assertEqual(
            macros.get("SWAPZ_PRIMARY_PACKAGE_TRANSACTION_DIRECTORY"),
            '"/var/lib/swapz-package-transactions"')
        self.assertIn("swapz_primary_mutation_lock()", lifecycle)
        self.assertIn(
            "swapz_primary_package_transactions_clear_at(", lifecycle)
        self.assertLess(
            lifecycle.index("swapz_primary_mutation_lock()"),
            lifecycle.index("swapz_primary_package_transactions_clear_at("))
        self.assertLess(
            lifecycle.index("swapz_primary_package_transactions_clear_at("),
            lifecycle.index("swapz_primary_prepare_metadata("))
        self.assertLess(
            lifecycle.index("swapz_primary_package_transactions_clear_at("),
            lifecycle.index("swapz_primary_start_prepared()"))
        self.assertRegex(
            lifecycle,
            r"action\s*==\s*SWAPZ_PRIMARY_MUTATING_PREPARE\s*\|\|"
            r"\s*action\s*==\s*SWAPZ_PRIMARY_MUTATING_START")
        self.assertIn("goto unlock;", lifecycle)
        self.assertIn("fdopendir(", transaction_guard)
        self.assertIn("readdir(", transaction_guard)
        self.assertIn("O_NOFOLLOW", transaction_guard)
        self.assertIn("O_NONBLOCK", transaction_guard)
        self.assertIn("AT_SYMLINK_NOFOLLOW", transaction_guard)
        self.assertIn("STATX_MNT_ID", transaction_guard)
        self.assertIn("STATX_BASIC_STATS | STATX_MNT_ID", transaction_guard)
        self.assertIn("stx_mnt_id", transaction_guard)
        self.assertIn("named_transaction_mount", transaction_guard)
        self.assertIn(
            "named_transaction_mount.stx_mnt_id !=",
            transaction_guard)
        self.assertIn(
            "named_transaction_mount.stx_ino != transaction_info.st_ino",
            transaction_guard)
        self.assertIn(
            "named_transaction_mount.stx_dev_major !=",
            transaction_guard)
        self.assertLess(
            transaction_guard.index("readdir(entries)"),
            transaction_guard.index("named_transaction_mount.stx_mnt_id !="))
        self.assertIn("EBUSY", transaction_guard)
        self.assertNotIn("state.json", transaction_guard)

    def test_qualification_import_serializes_before_partition_state(self):
        source = PRIMARY_SOURCE.read_text(encoding="utf-8")
        ordinary = preprocessed_primary_source()
        serialized = c_function_body(
            ordinary, "swapz_primary_qualification_import_serialized")
        command = c_function_body(source, "swapz_primary_command")

        self.assertIn("swapz_primary_mutation_lock()", serialized)
        self.assertIn(
            "swapz_primary_qualification_import(report_path)", serialized)
        self.assertLess(
            serialized.index("swapz_primary_mutation_lock()"),
            serialized.index("swapz_primary_qualification_import(report_path)"))
        self.assertIn(
            "swapz_primary_qualification_import_serialized(argv[1])", command)
        self.assertNotIn(
            "swapz_primary_qualification_import(argv[1])", command)

    def test_execution_gate_cannot_enable_without_native_swap_operations(self):
        source = PRIMARY_SOURCE.read_text(encoding="utf-8")
        native_swapon = c_function_body(source, "swapz_primary_native_swapon")
        native_swapoff = c_function_body(source, "swapz_primary_native_swapoff")
        activate = c_function_body(source, "swapz_primary_activate_mapper_swap")
        deactivate = c_function_body(source, "swapz_primary_deactivate_mapper_swap")
        self.assertRegex(
            native_swapon, r"\bsyscall\s*\(\s*SYS_swapon\s*,",
            "native transition ops lack executable swapon")
        self.assertRegex(
            native_swapoff, r"\bsyscall\s*\(\s*SYS_swapoff\s*,",
            "native transition ops lack executable swapoff")
        self.assertIn(
            "&swapz_primary_native_swap_transition_ops", activate)
        self.assertIn(
            "&swapz_primary_native_swap_transition_ops", deactivate)

    def test_source_guard_ignores_comments_and_string_literals(self):
        sample = """static int swapz_primary_activate_mapper_swap(void) {
            /* } syscall(SYS_swapon, mapper_path, 0); */
            const char *diagnostic = "syscall(SYS_swapon, mapper_path, 0)";
            return -1;
        }"""
        executable = c_function_body(sample, "swapz_primary_activate_mapper_swap")
        self.assertNotIn("syscall(SYS_swapon, mapper_path, 0)", executable)
        self.assertIn("return -1;", executable)

        gate_sample = """
            /* #define SWAPZ_PRIMARY_EXECUTION_ENABLED 1 */
            static const char *fake =
                "#define SWAPZ_PRIMARY_EXECUTION_ENABLED 1";
            #define SWAPZ_PRIMARY_EXECUTION_ENABLED 0
        """
        macros = active_preprocessor_macros(source_text=gate_sample)
        self.assertEqual(macros.get("SWAPZ_PRIMARY_EXECUTION_ENABLED"), "0")

    def test_rootless_runner_registers_lifecycle_audit(self):
        runner = ROOTLESS_RUNNER.read_text(encoding="utf-8")
        invocation = (
            "python3 -B tests/runtime/native/primary-lifecycle-audit-test.py -v"
        )
        self.assertIn(invocation, runner)

    def test_public_swapzctl_primary_dispatch_reaches_admission_interface(self):
        control = SWAPZCTL_SOURCE.read_text(encoding="utf-8")
        main = c_function_body(control, "main", code_only=False)
        selector = '!strcmp(argv[1], "primary")'
        dispatch = 'return swapz_primary_command(argc - 2, argv + 2);'

        self.assertIn(selector, main)
        self.assertEqual(main.count("swapz_primary_command("), 1)
        self.assertIn(dispatch, main)
        self.assertLess(main.index(selector), main.index(dispatch))


class PackageCrashToPrimaryAdmissionTest(unittest.TestCase):
    """SIGKILL a real rootless package transaction, then call primary's C API.

    Only the production C function boundaries and guard are source-extracted;
    privileged lifecycle side effects are replaced by counters. The package
    process and its durable journal come from package-dkms-test.py unchanged.
    """

    @classmethod
    def setUpClass(cls):
        if os.geteuid() == 0:
            raise unittest.SkipTest("package crash fixture requires nonroot")
        cls.fixture_directory = tempfile.TemporaryDirectory(
            prefix="swapz-package-primary-admission-")
        cls.addClassCleanup(cls.fixture_directory.cleanup)
        cls.executable = cls._compile_primary_admission_fixture()
        cls.sanitized_executable = cls._compile_primary_admission_fixture(
            sanitizers=True)

    @staticmethod
    def _function_definition(source: str, symbol: str) -> str:
        """Keep production declarations and bodies; never match comments."""
        executable = _c_code_only(source)
        match = re.search(
            r"(?m)^(?:static\s+)?int\s+" + re.escape(symbol) +
            r"\s*\([^;]*?\)\s*\{", executable, re.S)
        if match is None:
            raise AssertionError(f"missing primary definition: {symbol}")
        depth = 1
        for position in range(match.end(), len(executable)):
            if executable[position] == "{":
                depth += 1
            elif executable[position] == "}":
                depth -= 1
                if depth == 0:
                    return source[match.start():position + 1]
        raise AssertionError(f"unclosed primary definition: {symbol}")

    @staticmethod
    def _enum_definition(source: str, symbol: str) -> str:
        """Return one production enum declaration with its exact ordering."""
        executable = _c_code_only(source)
        match = re.search(
            r"(?m)^enum\s+" + re.escape(symbol) + r"\s*\{", executable)
        if match is None:
            raise AssertionError(f"missing primary enum: {symbol}")
        depth = 1
        for position in range(match.end(), len(executable)):
            if executable[position] == "{":
                depth += 1
            elif executable[position] == "}":
                depth -= 1
                if depth == 0:
                    semicolon = position + 1
                    while (semicolon < len(executable) and
                           executable[semicolon].isspace()):
                        semicolon += 1
                    if (semicolon >= len(executable) or
                            executable[semicolon] != ";"):
                        raise AssertionError(
                            f"unterminated primary enum: {symbol}")
                    return source[match.start():semicolon + 1]
        raise AssertionError(f"unclosed primary enum: {symbol}")

    @classmethod
    def _compile_primary_admission_fixture(
            cls, *, unsafe_bypass=False, refuse_all=False, sanitizers=False):
        if unsafe_bypass and refuse_all:
            raise AssertionError("admission mutants must remain independent")
        source = PRIMARY_SOURCE.read_text(encoding="utf-8")
        headers = (ROOT / "src/userspace/swapz-primary.h").read_text(
            encoding="utf-8")
        lock_name_match = re.search(
            r'(?m)^#define\s+SWAPZ_PRIMARY_MUTATION_LOCK_NAME\s+'
            r'("(?:\\.|[^"\\])*")\s*$', source)
        if lock_name_match is None:
            raise AssertionError("missing production mutation-lock name macro")
        mutation_lock_name = lock_name_match.group(1)
        codec_header = (ROOT / "src/kernel/codec.h").read_text(
            encoding="utf-8")
        symbols = (
            "swapz_primary_mutation_lock_at",
            "swapz_primary_mutation_lock",
            "swapz_primary_package_transactions_clear_at",
            "swapz_primary_run_mutating_action",
            "swapz_primary_command",
        )
        definitions = {name: cls._function_definition(source, name)
                       for name in symbols}
        mutating_action_enum = cls._enum_definition(
            source, "swapz_primary_mutating_action")
        # The only rootless change to each real coordinator boundary is to
        # substitute our nonroot fixture uid for the production uid 0. The
        # directory macros below similarly redirect to private test paths.
        for name, function_call in (
                ("swapz_primary_mutation_lock",
                 "SWAPZ_PRIMARY_MUTATION_LOCK_DIRECTORY"),
                ("swapz_primary_run_mutating_action",
                 "SWAPZ_PRIMARY_PACKAGE_TRANSACTION_DIRECTORY")):
            pattern = (r"(" + re.escape(function_call) + r"\s*,\s*)0(\s*\))")
            # The coordinator calls the guard across a line break; the lock
            # wrapper calls _at with the same arguments and owner literal.
            changed, count = re.subn(
                pattern, lambda match: match.group(1) +
                "geteuid()" + match.group(2), definitions[name])
            if count != 1:
                raise AssertionError(f"uid seam moved in {name}: {count}")
            definitions[name] = changed
        if unsafe_bypass:
            old = ("action == SWAPZ_PRIMARY_MUTATING_PREPARE ||\n"
                   "\t     action == SWAPZ_PRIMARY_MUTATING_START")
            new = ("action == SWAPZ_PRIMARY_MUTATING_STOP ||\n"
                   "\t     action == SWAPZ_PRIMARY_MUTATING_RECOVER")
            if definitions["swapz_primary_run_mutating_action"].count(old) != 1:
                raise AssertionError("production coordinator guard moved")
            definitions["swapz_primary_run_mutating_action"] = (
                definitions["swapz_primary_run_mutating_action"].replace(
                    old, new, 1))
        if refuse_all:
            coordinator = definitions["swapz_primary_run_mutating_action"]
            switch_anchor = "\tswitch (action) {"
            if coordinator.count(switch_anchor) != 1:
                raise AssertionError("production coordinator switch moved")
            definitions["swapz_primary_run_mutating_action"] = (
                coordinator.replace(
                    switch_anchor,
                    "\terrno = EBUSY;\n"
                    "\tresult = -1;\n"
                    "\tgoto unlock;\n"
                    + switch_anchor,
                    1))
        constants = {}
        for name in ("SWAPZ_PRIMARY_PARTUUID_LENGTH",
                     "SWAPZ_PRIMARY_SYSTEMD_UNIT_NAME_MAX",
                     "SWAPZ_PRIMARY_RUN_ID_LENGTH",
                     "SWAPZ_PRIMARY_SOURCE_SHA_LENGTH"):
            match = re.search(r"(?m)^#define\s+" + name +
                              r"\s+(\d+U?)\s*$", headers)
            if not match:
                raise AssertionError("missing source-derived constant " + name)
            constants[name] = match.group(1)
        block_bytes = re.search(
            r"(?m)^#define\s+SWAPZ_BLOCK_BYTES\s+(\d+U?)\s*$",
            codec_header)
        if not block_bytes:
            raise AssertionError("missing source-derived SWAPZ_BLOCK_BYTES")
        constants["SWAPZ_BLOCK_BYTES"] = block_bytes.group(1)
        preamble = f'''/* Source-extracted production C, unprivileged test linkage. */
#define _GNU_SOURCE
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <linux/stat.h>
#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <sys/file.h>
#include <sys/stat.h>
#include <sys/sysmacros.h>
#include <sys/types.h>
#include <unistd.h>
#define SWAPZ_PRIMARY_PARTUUID_LENGTH {constants["SWAPZ_PRIMARY_PARTUUID_LENGTH"]}
#define SWAPZ_PRIMARY_SYSTEMD_UNIT_NAME_MAX {constants["SWAPZ_PRIMARY_SYSTEMD_UNIT_NAME_MAX"]}
#define SWAPZ_PRIMARY_MUTATION_LOCK_NAME {mutation_lock_name}
#define SWAPZ_PRIMARY_RUN_ID_LENGTH {constants["SWAPZ_PRIMARY_RUN_ID_LENGTH"]}
#define SWAPZ_PRIMARY_SOURCE_SHA_LENGTH {constants["SWAPZ_PRIMARY_SOURCE_SHA_LENGTH"]}
#define SWAPZ_PRIMARY_BLOCK_BYTES ((uint64_t){constants["SWAPZ_BLOCK_BYTES"]})
#define SWAPZ_PRIMARY_MUTATION_LOCK_DIRECTORY getenv("SWAPZ_TEST_LOCK_DIRECTORY")
#define SWAPZ_PRIMARY_PACKAGE_TRANSACTION_DIRECTORY getenv("SWAPZ_TEST_PACKAGE_TRANSACTIONS")
{mutating_action_enum}
int swapz_primary_prepare_metadata(char *prepared_run_id,
    char *prepared_source_sha, uint64_t *prepared_logical_pages);
static uint64_t swapz_primary_linux_swap_size_kib(uint64_t logical_pages) {{
    return logical_pages * SWAPZ_PRIMARY_BLOCK_BYTES / 1024U - 4U;
}}
int swapz_primary_start_prepared(void);
int swapz_primary_stop_active(void);
int swapz_primary_recover(void);
int swapz_primary_privileged_execution_enabled(void);
int swapz_primary_cleanup_execution_enabled(void);
int swapz_primary_read_only_plan(void);
int swapz_primary_target_config_read(char *partuuid);
int swapz_primary_systemd_target_units(const char *partuuid,
    char *device_unit, char *swap_unit);
int swapz_primary_qualification_import_serialized(const char *report_path);
'''
        fixture_name = "primary-admission"
        if unsafe_bypass:
            fixture_name += "-unsafe"
        if refuse_all:
            fixture_name += "-refuse-all"
        if sanitizers:
            fixture_name += "-sanitized"
        fixture_source = Path(cls.fixture_directory.name) / (fixture_name + ".c")
        executable = Path(cls.fixture_directory.name) / fixture_name
        fixture_source.write_text(
            preamble + "\n\n".join(definitions.values()) + "\n",
            encoding="utf-8")
        command = [
            "cc", "-std=c11", "-O1", "-g", "-Wall", "-Wextra",
            "-Wpedantic", "-Werror", "-Wstrict-prototypes",
            "-DSWAPZ_PRIMARY_PACKAGE_ADMISSION_FIXTURE",
        ]
        if sanitizers:
            command.extend((
                "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
                "-fno-omit-frame-pointer"))
        command.extend((
            str(fixture_source),
            str(ROOT / "tests/runtime/native/primary-lifecycle-fault-shim-harness.c"),
            "-o", str(executable)))
        compiled = subprocess.run(
            command, cwd=ROOT, text=True, capture_output=True, check=False)
        if compiled.returncode:
            raise AssertionError("primary admission C fixture compilation failed:\n" +
                                 compiled.stderr)
        return executable

    def _package_fixture(self):
        spec = importlib.util.spec_from_file_location(
            "swapz_package_crash_tests",
            ROOT / "tests/runtime/native/package-dkms-test.py")
        if spec is None or spec.loader is None:
            self.fail("cannot import real package crash fixture")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        package = module.PackageLifecycle(
            methodName="test_clean_repeat_uninstall_and_reinstall")
        package.setUp()
        self.addCleanup(package.doCleanups)
        return package

    def _primary(self, package, action, *, executable=None, extra=None):
        environment = dict(os.environ,
                           SWAPZ_TEST_LOCK_DIRECTORY=str(package.home),
                           SWAPZ_TEST_PACKAGE_TRANSACTIONS=str(
                               package.home / "transactions"),
                           ASAN_OPTIONS=(
                               "halt_on_error=1:abort_on_error=1:"
                               "detect_leaks=1"),
                           UBSAN_OPTIONS=(
                               "halt_on_error=1:print_stacktrace=1"))
        if extra:
            environment.update(extra)
        result = subprocess.run(
            [str(executable or self.executable), action],
            cwd=package.repo_root, env=environment, text=True,
            capture_output=True, timeout=10, check=False)
        simulation_lines = [
            line for line in result.stdout.splitlines()
            if line.startswith("SIMULATION ")]
        self.assertEqual(len(simulation_lines), 1,
                         f"invalid primary fixture trace: {result!r}")
        match = re.fullmatch(
            r"SIMULATION prepare=(\d+) start=(\d+) stop=(\d+) "
            r"recover=(\d+) header=(\d+) mapper=(\d+) "
            r"mkswap=(\d+) swapon=(\d+)", simulation_lines[0])
        self.assertIsNotNone(match, f"invalid primary fixture trace: {result!r}")
        ready_lines = [
            line for line in result.stdout.splitlines()
            if line.startswith("PRIMARY_PREPARE=READY ")]
        if action == "prepare" and result.returncode == 0:
            self.assertEqual(len(ready_lines), 1, result)
            self.assertRegex(
                ready_lines[0],
                r"^PRIMARY_PREPARE=READY run_id=[0-9a-f]{32} "
                r"source=[0-9a-f]{40} logical_pages=[1-9][0-9]* "
                r"logical_bytes=[1-9][0-9]* swap_kib=[1-9][0-9]*$")
        else:
            self.assertEqual(ready_lines, [], result)
        return result, dict(zip(
            ("prepare", "start", "stop", "recover", "header", "mapper",
             "mkswap", "swapon"), map(int, match.groups())))

    def _assert_package_blocked(self, package, action, *, extra=None,
                                executable=None, expected_errno=errno.EBUSY):
        result, calls = self._primary(package, action, executable=executable,
                                      extra=extra)
        self.assertEqual(result.returncode, 2, result)
        self.assertEqual(set(calls.values()), {0}, result)
        if action not in ("prepare", "start"):
            self.fail("only prepare/start are package-gated")
        self.assertIn("phase=package-transaction-preflight", result.stderr)
        if action == "prepare":
            self.assertIn("PRIMARY_PREPARE=FAILED", result.stderr)
            if expected_errno is not None:
                self.assertIn(f"errno={expected_errno}", result.stderr)
        elif action == "start":
            self.assertIn("PRIMARY_START=FAILED "
                          "phase=package-transaction-preflight", result.stderr)
            self.assertIn("BLOCKED: primary-swap start failed:", result.stderr)
            if expected_errno is not None:
                self.assertIn(f"errno={expected_errno}", result.stderr)
                self.assertIn(os.strerror(expected_errno), result.stderr)

    def _assert_cleanup_allowed(self, package, *, executable=None):
        for action in ("stop", "recover"):
            result, calls = self._primary(
                package, action, executable=executable)
            self.assertEqual(result.returncode, 0, f"{action}: {result}")
            self.assertEqual(calls[action], 1, f"{action}: {result}")
            self.assertEqual(sum(calls.values()), 1, f"{action}: {result}")

    def _assert_clean_admission(self, package, *, executable=None):
        for action, forbidden in (
                ("prepare", {"mkswap", "swapon"}),
                ("start", {"header"})):
            result, calls = self._primary(
                package, action, executable=executable)
            self.assertEqual(result.returncode, 0, f"{action}: {result}")
            self.assertEqual(calls[action], 1, f"{action}: {result}")
            self.assertGreater(sum(calls.values()), 1, f"{action}: {result}")
            for name in forbidden:
                self.assertEqual(calls[name], 0, f"{action}: {result}")

    def _crash_and_reacquire(
            self, package, action, phase, extra=None, *,
            checkpoint_timeout_seconds=None):
        crash_options = (
            {} if checkpoint_timeout_seconds is None
            else {"checkpoint_timeout_seconds": checkpoint_timeout_seconds})
        transaction = package.kill_at_durable_phase(
            action, phase, extra, **crash_options)
        self.assertTrue(transaction.is_dir())
        self.assertEqual(json.loads((transaction / "state.json").read_text())[
            "phase"], phase)
        # The killed installer no longer holds flock. Reacquiring this same
        # inode is a negative control for a test that only checks lock refusal.
        with (package.home / "package.lock").open("r+b") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            locked, _ = self._primary(package, "prepare")
            self.assertIn("phase=global-mutation-lock", locked.stderr)
            self.assertNotIn("phase=package-transaction-preflight",
                             locked.stderr)
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        self._assert_package_blocked(package, "prepare")
        self._assert_package_blocked(package, "start")
        self._assert_cleanup_allowed(package)
        return transaction

    def test_clean_and_empty_directory_admit_and_cleanup(self):
        package = self._package_fixture()
        self._assert_clean_admission(package)  # missing transaction root
        transactions = package.home / "transactions"
        transactions.mkdir(mode=0o700)
        self._assert_clean_admission(package)  # existing, empty root
        self._assert_cleanup_allowed(package)

    def test_sanitized_fixture_covers_clean_blocked_and_cleanup_paths(self):
        package = self._package_fixture()
        transactions = package.home / "transactions"
        transactions.mkdir(mode=0o700)
        self._assert_clean_admission(
            package, executable=self.sanitized_executable)
        (transactions / "stale-transaction").mkdir(mode=0o700)
        for action in ("prepare", "start"):
            self._assert_package_blocked(
                package, action, executable=self.sanitized_executable)
        self._assert_cleanup_allowed(
            package, executable=self.sanitized_executable)

    def test_real_sigkill_phases_block_both_commands_not_cleanup(self):
        for action, phase, install_first in (
                ("install", "source-created", False),
                ("install", "module-promoted", False),
                ("install", "cli-published", False),
                ("uninstall", "dkms-removed", True),
                ("uninstall", "systemd-reload-complete", True)):
            with self.subTest(action=action, phase=phase):
                package = self._package_fixture()
                if install_first:
                    # Earlier rootless work can delay this setup install.
                    # Use the ordinary bounded package watchdog; the injected
                    # SIGKILL checkpoint keeps its separate finite deadline.
                    installed = package.invoke("install")
                    self.assertEqual(
                        installed.returncode, 0,
                        "phase=crash-audit-setup-install "
                        f"action={action} checkpoint={phase} "
                        f"exit={installed.returncode}\n{installed.stderr}")
                self._crash_and_reacquire(package, action, phase)

    def test_blocked_start_reports_explicit_package_recovery_phase(self):
        package = self._package_fixture()
        package.kill_at_durable_phase("install", "module-promoted")
        result, calls = self._primary(package, "start")
        self.assertEqual(result.returncode, 2, result)
        self.assertEqual(set(calls.values()), {0}, result)
        # Admission diagnostics identify the durable package gate instead of
        # collapsing it into a generic lifecycle failure.
        self.assertIn(
            "PRIMARY_START=FAILED phase=package-transaction-preflight",
            result.stderr)

    def test_directory_substitution_during_named_recheck_fails_closed(self):
        for action in ("prepare", "start"):
            with self.subTest(action=action):
                package = self._package_fixture()
                transactions = package.home / "transactions"
                transactions.mkdir(mode=0o700)
                result, calls = self._primary(
                    package, action,
                    extra={
                        "SWAPZ_TEST_SUBSTITUTE_TRANSACTION_DURING_STATX": "1"
                    })
                displaced = package.home / "transactions.before-statx"
                self.assertTrue(transactions.is_dir())
                self.assertTrue(displaced.is_dir())
                self.assertTrue(
                    (transactions / "swapz-package.substituted").is_dir())
                self.assertNotEqual(
                    transactions.stat().st_ino, displaced.stat().st_ino)
                self.assertEqual(result.returncode, 2, result)
                self.assertEqual(set(calls.values()), {0}, result)
                self.assertIn(
                    "phase=package-transaction-preflight", result.stderr)

    def test_malformed_and_substituted_package_journals_fail_closed(self):
        package = self._package_fixture()
        transaction = self._crash_and_reacquire(
            package, "install", "module-promoted")
        journal = transaction / "state.json"
        original = journal.read_bytes()
        try:
            journal.write_bytes(b"{bad package journal\n")
            for action in ("prepare", "start"):
                self._assert_package_blocked(package, action)
            self._assert_cleanup_allowed(package)
        finally:
            journal.write_bytes(original)
        transactions = package.home / "transactions"
        retained = package.home / "transactions-retained"
        transactions.rename(retained)
        try:
            transactions.symlink_to(retained, target_is_directory=True)
            for action in ("prepare", "start"):
                self._assert_package_blocked(
                    package, action, expected_errno=None)
            self._assert_cleanup_allowed(package)
            transactions.unlink()
            transactions.write_text("not a directory")
            for action in ("prepare", "start"):
                self._assert_package_blocked(
                    package, action, expected_errno=None)
            self._assert_cleanup_allowed(package)
        finally:
            if transactions.is_symlink() or transactions.is_file():
                transactions.unlink()
            retained.rename(transactions)
        # Wrong owner is rejected before the journal entry is enumerated.
        for action in ("prepare", "start"):
            result, calls = self._primary(
                package, action,
                extra={"SWAPZ_TEST_WRONG_TRANSACTION_OWNER": "1"})
            self.assertEqual(result.returncode, 2, result)
            self.assertEqual(set(calls.values()), {0}, result)
            self.assertIn("phase=package-transaction-preflight",
                          result.stderr)
            if action == "prepare":
                self.assertIn(f"errno={errno.EPERM}", result.stderr)
            else:
                self.assertIn(os.strerror(errno.EPERM), result.stderr)
        self._assert_cleanup_allowed(package)

        # A nonempty directory rejects at readdir(EBUSY) first. An empty
        # directory is essential for proving the later statx mount-ID check.
        clean_package = self._package_fixture()
        (clean_package.home / "transactions").mkdir(mode=0o700)
        self._assert_clean_admission(clean_package)
        for action in ("prepare", "start"):
            result, calls = self._primary(
                clean_package, action,
                extra={"SWAPZ_TEST_CHANGED_MOUNT_ID": "1"})
            self.assertEqual(result.returncode, 2, result)
            self.assertEqual(set(calls.values()), {0}, result)
            self.assertIn("phase=package-transaction-preflight",
                          result.stderr)
            if action == "prepare":
                self.assertIn(f"errno={errno.ESTALE}", result.stderr)
            else:
                self.assertIn(os.strerror(errno.ESTALE), result.stderr)
        self._assert_cleanup_allowed(clean_package)

    def test_crash_checkpoint_timeout_override_is_finite(self):
        package = self._package_fixture()
        for timeout_seconds in (0, -1, 91, True):
            with self.subTest(timeout_seconds=timeout_seconds):
                with self.assertRaisesRegex(ValueError, "bounded checkpoint"):
                    package.kill_at_durable_phase(
                        "install", "committed",
                        checkpoint_timeout_seconds=timeout_seconds)

    def test_committed_journal_then_verified_package_recovery_allows_reentry(self):
        package = self._package_fixture()
        # Commit-phase fsync/rename work can be slower on USB-root hosts.
        # Only this durable checkpoint gets a longer finite wait; no crash,
        # lock, reentry, or exact installed-payload assertion is relaxed.
        transaction = self._crash_and_reacquire(
            package, "install", "committed",
            checkpoint_timeout_seconds=90)
        state = json.loads((transaction / "state.json").read_text())
        self.assertEqual(state["schema"], "swapz-package-install-v1")
        self.assertEqual(state["phase"], "committed")
        package.assert_installed_exact()  # verified installed payload, not a guess
        # Normal package mutation remains gated until explicit recovery verifies
        # the retained journal and exact installed package under package.lock.
        blocked = package.invoke("install")
        self.assertNotEqual(blocked.returncode, 0)
        self.assertIn("incomplete package transaction retained", blocked.stderr)
        recovered = package.invoke("recover")
        self.assertEqual(recovered.returncode, 0, recovered.stderr)
        package.assert_installed_exact()
        self.assertFalse(transaction.exists())
        self.assertEqual(list((package.home / "transactions").iterdir()), [])
        self.assertEqual(package.invoke("recover").returncode, 0)
        for _ in range(2):
            self._assert_clean_admission(package)
            self._assert_cleanup_allowed(package)

    def test_all_refusing_coordinator_fake_cannot_satisfy_contract(self):
        package = self._package_fixture()
        refuse_all = self._compile_primary_admission_fixture(refuse_all=True)
        for action in ("prepare", "start", "stop", "recover"):
            result, calls = self._primary(
                package, action, executable=refuse_all)
            self.assertEqual(result.returncode, 2, result)
            self.assertEqual(set(calls.values()), {0}, result)
        # A fake that returns failure for every lifecycle action can resemble a
        # package guard only if clean admission and cleanup are never tested.
        with self.assertRaises(AssertionError):
            self._assert_clean_admission(package, executable=refuse_all)
        with self.assertRaises(AssertionError):
            self._assert_cleanup_allowed(package, executable=refuse_all)

    def test_unsafe_coordinator_bypass_mutant_is_observably_rejected(self):
        package = self._package_fixture()
        self._crash_and_reacquire(package, "install", "module-promoted")
        unsafe = self._compile_primary_admission_fixture(unsafe_bypass=True)
        for action in ("prepare", "start"):
            with self.subTest(action=action):
                # An inverted coordinator guard must demonstrably fail the
                # same assertion as the real path, and reach side-effect fakes.
                with self.assertRaises(AssertionError):
                    self._assert_package_blocked(
                        package, action, executable=unsafe)
                result, calls = self._primary(package, action, executable=unsafe)
                self.assertEqual(result.returncode, 0, result)
                self.assertEqual(calls[action], 1, result)
                self.assertGreater(
                    sum(calls[name] for name in
                        ("header", "mapper", "mkswap", "swapon")), 0)
        for action in ("stop", "recover"):
            with self.subTest(action=action):
                result, calls = self._primary(package, action, executable=unsafe)
                self.assertEqual(result.returncode, 2, result)
                self.assertEqual(set(calls.values()), {0}, result)


class PrimaryOwnerReleaseDurabilityTest(unittest.TestCase):
    """Exercise the production owner-release C body at a private fsync fault.

    This is a rootless durability-boundary check, not loaded swap evidence.
    The fixture substitutes only record parsing/ownership admission and reads
    private regular files; the production unlink/fsync and recoverability
    decisions are compiled unchanged with the existing linker-wrap fault shim.
    """

    _RUN_ID = "a" * 32

    @classmethod
    def setUpClass(cls):
        cls.temporary_directory = tempfile.TemporaryDirectory(
            prefix="swapz-primary-owner-release-")
        cls.addClassCleanup(cls.temporary_directory.cleanup)
        cls.executable = Path(cls.temporary_directory.name) / "owner-release"
        production_source = PRIMARY_SOURCE.read_text(encoding="utf-8")
        extractor = PackageCrashToPrimaryAdmissionTest._function_definition
        release_body = extractor(
            production_source, "swapz_primary_release_partition_owner_at")
        recoverable_body = extractor(
            production_source, "swapz_primary_state_recoverable")
        recovery_body = c_function_body(production_source,
                                        "swapz_primary_recover")
        if "!swapz_primary_state_recoverable(&state)" not in recovery_body:
            raise AssertionError("production recoverability admission changed")
        fixture_source = Path(cls.temporary_directory.name) / "owner-release.c"
        fixture_source.write_text(r'''
/* Private regular-file harness; release and recoverability bodies follow. */
#define _GNU_SOURCE
#include "src/userspace/swapz-primary.h"
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>
#define SWAPZ_PRIMARY_BLOCK_BYTES 4096U
#define SWAPZ_PRIMARY_STATE_RECORD_MAX 4096U
#define SWAPZ_PRIMARY_PARTITION_NAME_BYTES 128U
#define SWAPZ_PRIMARY_PARTUUID "fixture"
#define FIXTURE_RUN_ID "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"

static int swapz_primary_valid_run_id(const char *run_id)
{
    return run_id && strcmp(run_id, FIXTURE_RUN_ID) == 0;
}

static int swapz_primary_state_valid(const struct swapz_primary_state *state)
{
    return state && swapz_primary_valid_run_id(state->run_id) &&
           state->stage == SWAPZ_PRIMARY_STAGE_COMPLETE;
}

static int swapz_primary_state_lock_valid(int recovery_fd, int lock_fd,
                                           uid_t expected_owner)
{
    return recovery_fd >= 0 && lock_fd >= 0 && expected_owner == geteuid();
}

static int swapz_primary_owner_claim_matches_at(int recovery_fd,
                                                 const char *run_id,
                                                 uid_t expected_owner)
{
    struct stat marker;
    return expected_owner == geteuid() &&
           swapz_primary_valid_run_id(run_id) &&
           fstatat(recovery_fd, "partition-fixture.active", &marker,
                   AT_SYMLINK_NOFOLLOW) == 0 && S_ISREG(marker.st_mode);
}

static int swapz_primary_record_read_at(int recovery_fd, const char *name,
                                         uid_t expected_owner, char *record,
                                         size_t capacity, size_t *length,
                                         struct stat *identity)
{
    int descriptor;
    ssize_t received;
    struct stat info;
    if (expected_owner != geteuid() || !record || capacity < 2U) {
        errno = EPERM;
        return -1;
    }
    descriptor = openat(recovery_fd, name, O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
    if (descriptor < 0)
        return -1;
    if (fstat(descriptor, &info) < 0 || !S_ISREG(info.st_mode) ||
        info.st_nlink != 1 || info.st_size <= 0 ||
        (uintmax_t)info.st_size >= capacity) {
        (void)close(descriptor);
        errno = EBADMSG;
        return -1;
    }
    received = read(descriptor, record, (size_t)info.st_size);
    if (received != info.st_size || close(descriptor) < 0) {
        errno = EIO;
        return -1;
    }
    record[received] = '\0';
    *length = (size_t)received;
    if (identity)
        *identity = info;
    return 0;
}

int swapz_primary_state_parse(const char *record, size_t length,
                              struct swapz_primary_state *state)
{
    if (!record || !length || !state ||
        !strstr(record, "\"run_id\":\"" FIXTURE_RUN_ID "\"") ||
        !strstr(record, "\"stage\":\"COMPLETE\"")) {
        errno = EBADMSG;
        return -1;
    }
    memset(state, 0, sizeof(*state));
    memcpy(state->run_id, FIXTURE_RUN_ID, sizeof(FIXTURE_RUN_ID));
    state->stage = SWAPZ_PRIMARY_STAGE_COMPLETE;
    return 0;
}
''' + "\n" + recoverable_body + "\n" + release_body + r'''
int main(int argc, char **argv)
{
    int recovery_fd;
    int lock_fd;
    int result;
    int original_errno;
    char record[SWAPZ_PRIMARY_STATE_RECORD_MAX + 1U];
    size_t record_length = 0U;
    struct swapz_primary_state state = {0};
    if (argc != 3) return 3;
    recovery_fd = open(argv[1], O_RDONLY | O_DIRECTORY | O_CLOEXEC);
    if (recovery_fd < 0) return 3;
    lock_fd = openat(recovery_fd, "partition.lock",
                     O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
    if (lock_fd < 0) return 3;
    if (!strcmp(argv[2], "release")) {
        errno = 0;
        result = swapz_primary_release_partition_owner_at(
            recovery_fd, lock_fd, FIXTURE_RUN_ID, geteuid());
        original_errno = errno;
        printf("phase=owner-release status=%s original_errno=%d "
               "durable_stage=COMPLETE\n",
               result == 0 ? "COMPLETE" : "FAILED", original_errno);
    } else if (!strcmp(argv[2], "recover")) {
        if (swapz_primary_record_read_at(recovery_fd, "primary-state.json",
                geteuid(), record, sizeof(record), &record_length, NULL) < 0 ||
            swapz_primary_state_parse(record, record_length, &state) < 0)
            return 3;
        result = swapz_primary_state_recoverable(&state) ? 0 : -1;
        original_errno = result == 0 ? 0 : EPERM;
        printf("phase=recovery-admission status=%s original_errno=%d "
               "durable_stage=COMPLETE\n",
               result == 0 ? "ADMITTED" : "BLOCKED", original_errno);
    } else {
        return 3;
    }
    (void)close(lock_fd);
    (void)close(recovery_fd);
    return result == 0 ? 0 : 2;
}
''', encoding="utf-8")
        compiled = subprocess.run([
            "cc", "-std=c11", "-O1", "-g", "-Wall", "-Wextra", "-Wpedantic",
            "-Werror", "-Wstrict-prototypes", "-I", str(ROOT),
            "-Wl,--wrap=fsync", "-Wl,--wrap=open", "-Wl,--wrap=syscall",
            str(fixture_source),
            str(ROOT / "tests/tools/primary-lifecycle-fault-shim.c"),
            "-o", str(cls.executable),
        ], cwd=ROOT, text=True, capture_output=True, check=False)
        if compiled.returncode:
            raise AssertionError("owner-release C fixture failed to compile:\n" +
                                 compiled.stderr)

    def test_stop_and_recover_propagate_owner_release_failure(self):
        source = PRIMARY_SOURCE.read_text(encoding="utf-8")
        for symbol in ("swapz_primary_stop_active", "swapz_primary_recover"):
            with self.subTest(symbol=symbol):
                executable = c_function_body(source, symbol)
                raw = c_function_body(source, symbol, code_only=False)
                complete = executable.index("complete_persisted = 1;")
                release = executable.index(
                    "swapz_primary_release_partition_owner_at(", complete)
                success = executable.index("result = 0;", release)
                failure_exit = executable.index("out:", success)
                saved_errno = executable.index(
                    "saved_errno = errno ? errno : EIO;", failure_exit)

                # COMPLETE is durable before owner release today. If release
                # fails, the coordinator must not convert that failure into
                # success or overwrite its original errno.
                self.assertLess(complete, release)
                self.assertLess(release, success)
                phase = raw.rfind(
                    'failure_phase = "owner-release";', complete, release)
                self.assertGreaterEqual(
                    phase, 0, f"{symbol} lost owner-release phase attribution")
                checked_release = executable[release:success]
                self.assertRegex(
                    checked_release,
                    r"swapz_primary_release_partition_owner_at\("
                    r"[^;]*\)\s*<\s*0\s*\)\s*goto\s+out\s*;",
                    f"{symbol} can ignore owner-release failure")
                self.assertIn(
                    "&& !complete_persisted", executable[failure_exit:],
                    f"{symbol} no longer retains COMPLETE after release failure")
                self.assertRegex(
                    executable[saved_errno:],
                    r"if\s*\(\s*result\s*<\s*0\s*\)\s*"
                    r"errno\s*=\s*saved_errno\s*;",
                    f"{symbol} does not restore the original failure errno")
                success_marker = (
                    "PRIMARY_STOP=COMPLETE"
                    if symbol == "swapz_primary_stop_active"
                    else "PRIMARY_RECOVER=COMPLETE")
                success_gate = executable.index("if (result == 0)", saved_errno)
                function_return = executable.index("return result;", success_gate)
                success_window = raw[success_gate:function_return]
                self.assertRegex(
                    success_window,
                    r"if\s*\(\s*result\s*==\s*0\s*\)\s*printf\s*\(\s*\"" +
                    re.escape(success_marker),
                    f"{symbol} can report COMPLETE after owner-release failure")

                # COMPLETE recovery admission must reject before any swap or
                # mapper cleanup. This is source-order evidence only; the
                # private fixture below does not observe live kernel state.
                if symbol == "swapz_primary_recover":
                    admission = executable.index(
                        "!swapz_primary_state_recoverable(&state)")
                    deactivate = executable.index(
                        "swapz_primary_deactivate_mapper_swap(")
                    remove = executable.index(
                        "swapz_primary_dm_remove_mapper(")
                    self.assertLess(admission, deactivate)
                    self.assertLess(admission, remove)

    def test_failed_owner_release_fsync_stays_blocked_across_fresh_recovery(self):
        with tempfile.TemporaryDirectory(
                prefix="swapz-primary-release-state-") as private_directory:
            recovery_path = Path(private_directory)
            state_bytes = (
                '{"schema":"swapz-primary-state-v1","run_id":"' +
                self._RUN_ID +
                '","stage":"COMPLETE","recovery_previous_stage":null}\n'
            ).encode("ascii")
            state_path = recovery_path / "primary-state.json"
            marker_path = recovery_path / "partition-fixture.active"
            state_path.write_bytes(state_bytes)
            marker_path.write_bytes(b"owned-by-private-fixture\n")
            (recovery_path / "partition.lock").touch()
            for filename in (state_path, marker_path):
                with filename.open("rb") as durable_file:
                    os.fsync(durable_file.fileno())
            directory_fd = os.open(private_directory, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)

            def invoke(action, *, inject_fsync_failure=False):
                environment = os.environ.copy()
                environment.pop("SWAPZ_PRIMARY_TEST_FAULT", None)
                environment.pop("SWAPZ_PRIMARY_TEST_FSYNC_FAIL_DIRECTORY_CALL",
                                None)
                if inject_fsync_failure:
                    environment["SWAPZ_PRIMARY_TEST_FSYNC_FAIL_DIRECTORY_CALL"] = "1"
                return subprocess.run(
                    [str(self.executable), private_directory, action],
                    env=environment, text=True, capture_output=True,
                    timeout=10, check=False)

            failure = invoke("release", inject_fsync_failure=True)
            observed_state_bytes = state_path.read_bytes()
            observed_durable = (
                "COMPLETE" if observed_state_bytes == state_bytes else "CHANGED")
            observed_owner_marker = (
                "present" if marker_path.exists() else "absent")
            diagnostic = (
                "phase=owner-release original_errno=EIO(5) "
                "expected_durable=COMPLETE "
                f"observed_durable={observed_durable} "
                "expected_release=FAILED "
                f"observed_release={failure.stdout.strip()} "
                "expected_owner_marker=absent "
                f"observed_owner_marker={observed_owner_marker} "
                "expected_mapper=UNOBSERVED observed_mapper=UNOBSERVED "
                "expected_swap=UNOBSERVED observed_swap=UNOBSERVED "
                "expected_recovery=BLOCKED observed_recovery=NOT_RUN"
            )
            self.assertEqual(failure.returncode, 2, diagnostic)
            self.assertIn("phase=owner-release status=FAILED original_errno=5",
                          failure.stdout, diagnostic)
            self.assertIn("SWAPZ_PRIMARY_TEST_FSYNC_DIRECTORY_HIT=1",
                          failure.stderr, diagnostic)
            self.assertEqual(state_path.read_bytes(), state_bytes, diagnostic)
            self.assertFalse(marker_path.exists(), diagnostic)

            # A failed directory fsync does not prove unlink durability; a
            # restart may see either absence or the previous owner marker.
            for marker_persisted in (False, True):
                with self.subTest(marker_persisted=marker_persisted):
                    if marker_persisted:
                        marker_path.write_bytes(b"owned-by-private-fixture\n")
                    else:
                        marker_path.unlink(missing_ok=True)
                    before = (state_path.read_bytes(), marker_path.exists())
                    for _ in range(2):
                        recovery = invoke("recover")
                        after = (
                            state_path.read_bytes(), marker_path.exists())
                        observed_durable = (
                            "COMPLETE" if after[0] == state_bytes else "CHANGED")
                        expected_owner_marker = (
                            "present" if marker_persisted else "absent")
                        observed_owner_marker = (
                            "present" if after[1] else "absent")
                        recovery_diagnostic = (
                            "phase=recovery-admission original_errno=EPERM(1) "
                            "expected_durable=COMPLETE "
                            f"observed_durable={observed_durable} "
                            "expected_recovery=BLOCKED "
                            f"observed_recovery={recovery.stdout.strip()} "
                            f"expected_owner_marker={expected_owner_marker} "
                            f"observed_owner_marker={observed_owner_marker} "
                            "expected_mapper=UNOBSERVED observed_mapper=UNOBSERVED "
                            "expected_swap=UNOBSERVED observed_swap=UNOBSERVED"
                        )
                        self.assertEqual(recovery.returncode, 2,
                                         recovery_diagnostic)
                        self.assertIn("phase=recovery-admission status=BLOCKED "
                                      "original_errno=1", recovery.stdout,
                                      recovery_diagnostic)
                        self.assertEqual(after, before, recovery_diagnostic)


class PrimaryLifecycleTimingResult(unittest.TextTestResult):
    """Observational individual-case wall time including setup and teardown.

    Emitting timing cannot change unittest's outcome or expose case-generated
    stdout/stderr. Only source-defined class and method identifiers are used.
    """
    def startTest(self, test):
        super().startTest(test)
        try:
            self._case_start_ns = time.monotonic_ns()
        except OSError:
            self._case_start_ns = None

    def stopTest(self, test):
        try:
            started_ns = getattr(self, "_case_start_ns", None)
            if started_ns is not None:
                elapsed_ns = time.monotonic_ns() - started_ns
                class_name = type(test).__name__
                method_name = getattr(test, "_testMethodName", "")
                if (elapsed_ns >= 0 and
                        re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}", class_name)
                        and re.fullmatch(r"test_[A-Za-z0-9_]{1,126}", method_name)):
                    # Some cases redirect Python-level sys.stdout. Keep the
                    # source-defined marker on unittest's original progress
                    # stream so the asynchronous stderr relay cannot splice
                    # it into an unfinished result line from another pipe.
                    marker = (
                        f"PRIMARY_LIFECYCLE_CASE_TIMING index={self.testsRun - 1} "
                        f"elapsed_ms={elapsed_ns // 1_000_000} "
                        f"class={class_name} method={method_name}\n")
                    self.stream.write(marker)
                    self.stream.flush()
        except (OSError, ValueError, OverflowError):
            # A failed clock or output pipe is not a test failure.
            pass
        finally:
            super().stopTest(test)


class PrimaryLifecycleTimingRunner(unittest.TextTestRunner):
    resultclass = PrimaryLifecycleTimingResult


if __name__ == "__main__":
    unittest.main(testRunner=PrimaryLifecycleTimingRunner)
