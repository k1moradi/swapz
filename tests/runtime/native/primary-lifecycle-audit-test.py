#!/usr/bin/env python3
"""Rootless adversarial contracts for the native primary swap lifecycle.

The behavioral model is intentionally independent of the production coordinator:
it describes externally observable transaction/kernel-state invariants without
performing swapon, swapoff, Device Mapper operations, or privileged I/O.
"""
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
import re
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[3]
PRIMARY_SOURCE = ROOT / "src/userspace/swapz-primary.c"
PACKAGE_DKMS = ROOT / "packaging/package-dkms.sh"
ROOTLESS_RUNNER = ROOT / "tests/tools/test-rootless.sh"
ROOT_MAKEFILE = ROOT / "Makefile"


# C comments and quoted diagnostics must never satisfy native operation guards.
_C_NON_CODE = re.compile(
    r'/\*.*?\*/|//[^\n]*|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'',
    re.DOTALL)


def _c_code_only(source: str) -> str:
    # Keep character offsets and line numbers stable for source-order checks.
    return _C_NON_CODE.sub(
        lambda match: re.sub(r'[^\n]', ' ', match.group(0)), source)


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
    def test_native_swap_operations_are_transaction_ordered(self):
        source = PRIMARY_SOURCE.read_text(encoding="utf-8")
        activate = c_function_body(source, "swapz_primary_activate_mapper_swap")
        deactivate = c_function_body(
            source, "swapz_primary_deactivate_mapper_swap")
        start = c_function_body(source, "swapz_primary_start_prepared")
        stop = c_function_body(source, "swapz_primary_stop_active")
        recover = c_function_body(source, "swapz_primary_recover")

        self.assertIn("swapz_primary_swap_transition_apply(", activate)
        self.assertLess(
            activate.index("swapz_primary_transaction_manifest_matches_at("),
            activate.index("swapz_primary_swap_transition_apply("))
        self.assertIn("swapz_primary_dm_mapper_verify_fd(", activate)
        self.assertIn(
            "return syscall(SYS_swapon, mapper_path, 0);", source)
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

    def test_recovery_persists_fail_closed_interruption_order(self):
        source = PRIMARY_SOURCE.read_text(encoding="utf-8")
        recover = c_function_body(source, "swapz_primary_recover")

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
        self.assertIn(
            "recovering_persisted && !complete_persisted", recover)
        self.assertIn("swapz_primary_state_require_recovery_at(", recover)
        self.assertIn(
            "case SWAPZ_PRIMARY_STAGE_RESTORED:",
            c_function_body(source, "swapz_primary_state_recoverable"))

    def test_execution_gate_remains_disabled_pending_live_lifecycle_evidence(self):
        source = PRIMARY_SOURCE.read_text(encoding="utf-8")
        ordinary = active_preprocessor_macros()
        self.assertEqual(
            ordinary.get("SWAPZ_PRIMARY_EXECUTION_ENABLED"), "0",
            "ordinary production lifecycle needs physical evidence")
        self.assertEqual(
            ordinary.get("SWAPZ_PRIMARY_CONFIG_BASE"), '"/etc/swapz"')
        self.assertEqual(
            ordinary.get("SWAPZ_PRIMARY_RECOVERY_BASE"),
            '"/var/lib/swapz/physical-recovery"')

        owned_definitions = (
            "SWAPZ_PRIMARY_OWNED_NULLBLK_TEST=1",
            'SWAPZ_PRIMARY_TEST_CONFIG_BASE="/var/tmp/swapz-primary-owned-nullblk/config"',
            'SWAPZ_PRIMARY_TEST_RECOVERY_BASE="/var/tmp/swapz-primary-owned-nullblk/recovery"',
            'SWAPZ_PRIMARY_TEST_MUTATION_LOCK_DIRECTORY="/var/tmp/swapz-primary-owned-nullblk/mutation-lock"',
            'SWAPZ_PRIMARY_TEST_QUALIFICATION_REPORT="/var/tmp/swapz-primary-owned-nullblk/recovery/qualification.json"',
        )
        owned = active_preprocessor_macros(owned_definitions)
        self.assertEqual(owned.get("SWAPZ_PRIMARY_EXECUTION_ENABLED"), "1")
        self.assertEqual(
            owned.get("SWAPZ_PRIMARY_CONFIG_BASE"),
            "SWAPZ_PRIMARY_TEST_CONFIG_BASE")
        self.assertEqual(
            owned.get("SWAPZ_PRIMARY_RECOVERY_BASE"),
            "SWAPZ_PRIMARY_TEST_RECOVERY_BASE")
        for required in (
                "SWAPZ_PRIMARY_TEST_CONFIG_BASE",
                "SWAPZ_PRIMARY_TEST_RECOVERY_BASE",
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
        plan = c_function_body(source, "swapz_primary_read_only_plan")
        plan_raw = c_function_body(
            source, "swapz_primary_read_only_plan", code_only=False)
        command = c_function_body(source, "swapz_primary_command")
        self.assertIn("SWAPZ_PRIMARY_EXECUTION_ENABLED", gate)
        self.assertIn("swapz_primary_lifecycle_runtime_enabled()", gate)
        self.assertIn("swapz_primary_privileged_execution_enabled()", plan)
        self.assertIn(
            '"\\\"privileged_execution_enabled\\\":%s,"', plan_raw)
        self.assertNotIn(
            '"\\\"privileged_execution_enabled\\\":false,"', plan_raw)
        self.assertIn(
            "!swapz_primary_privileged_execution_enabled()", command)

        ordinary_source = preprocessed_primary_source()
        physical_source = preprocessed_primary_source(physical_definitions)
        self.assertNotIn(
            "SWAPZ_PRIMARY_PHYSICAL_QUALIFICATION", ordinary_source,
            "ordinary production build must not read the physical marker")
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
            package.index('primary_recovery_base="/var/lib/swapz/physical-recovery"'))
        self.assertLess(
            package.index("flock -n 9"),
            package.index("assert_no_primary_recovery_authority upgrade"))
        self.assertLess(
            lifecycle.index("swapz_primary_mutation_lock()"),
            lifecycle.index("swapz_primary_prepare_metadata()"))
        self.assertLess(
            lifecycle.index("swapz_primary_mutation_lock()"),
            lifecycle.index("swapz_primary_start_prepared()"))
        self.assertLess(
            lifecycle.index("swapz_primary_mutation_lock()"),
            lifecycle.index("swapz_primary_stop_active()"))
        self.assertLess(
            lifecycle.index("swapz_primary_mutation_lock()"),
            lifecycle.index("swapz_primary_recover()"))

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


if __name__ == "__main__":
    unittest.main()
