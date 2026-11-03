#!/usr/bin/env python3
"""Rootless adversarial contracts for the native primary swap lifecycle.

The behavioral model is intentionally independent of the production coordinator:
it describes externally observable transaction/kernel-state invariants without
performing swapon, swapoff, Device Mapper operations, or privileged I/O.
"""
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[3]
PRIMARY_SOURCE = ROOT / "src/userspace/swapz-primary.c"
ROOTLESS_RUNNER = ROOT / "tests/tools/test-rootless.sh"


class DurableStage(Enum):
    READY = auto()
    STARTING = auto()
    ACTIVE = auto()
    STOPPING = auto()
    RECOVERY_REQUIRED = auto()
    RECOVERING = auto()
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
    inventory_results: tuple[InventoryResult, ...] = (
        InventoryResult.EXACT_INACTIVE,
    )
    swapon_calls: int = 0
    swapoff_calls: int = 0
    remove_calls: int = 0
    inventory_calls: int = 0

    def swapon(self) -> OperationResult:
        self.swapon_calls += 1
        return self.swapon_result

    def swapoff(self) -> OperationResult:
        self.swapoff_calls += 1
        return self.swapoff_result

    def inventory(self) -> InventoryResult:
        index = min(self.inventory_calls, len(self.inventory_results) - 1)
        self.inventory_calls += 1
        return self.inventory_results[index]

    def remove_mapper(self) -> bool:
        self.remove_calls += 1
        if self.facts.mapper_active:
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
            kernel.facts.mapper_active = True
            self.stage = DurableStage.ACTIVE
            return True
        if before is not InventoryResult.EXACT_INACTIVE:
            self.stage = DurableStage.RECOVERY_REQUIRED
            return False

        operation = kernel.swapon()
        if operation is OperationResult.FAILURE:
            self.stage = DurableStage.RECOVERY_REQUIRED
            return False
        after = kernel.inventory()
        if after is InventoryResult.EXACT_ACTIVE:
            kernel.facts.mapper_active = True
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

        kernel.facts.mapper_active = False
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
                              DurableStage.RECOVERING):
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

    def test_existing_exact_active_mapper_is_adopted_without_duplicate_swapon(self):
        model = self.new_model()
        self.assertTrue(model.begin_start(model.run_id))
        kernel = FakeKernelAdapter(
            KernelFacts(mapper_active=True),
            inventory_results=(InventoryResult.EXACT_ACTIVE,))
        self.assertTrue(model.activate(model.run_id, kernel))
        self.assertEqual(kernel.swapon_calls, 0)
        self.assertIs(model.stage, DurableStage.ACTIVE)

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

    def test_repeated_recovery_after_complete_is_rejected(self):
        model = self.new_model()
        model.stage = DurableStage.COMPLETE
        self.assertFalse(model.begin_recovery(model.run_id))


class PrimaryLifecycleSourceGuardTest(unittest.TestCase):
    def test_execution_gate_cannot_enable_without_native_swap_operations(self):
        source = PRIMARY_SOURCE.read_text(encoding="utf-8")
        gate = re.search(
            r"^#define\s+SWAPZ_PRIMARY_EXECUTION_ENABLED\s+([01])\s*$",
            source, re.MULTILINE)
        self.assertIsNotNone(gate, "primary execution gate must remain explicit")
        if gate.group(1) == "0":
            return
        self.assertRegex(
            source, r"\b(?:SYS_swapon|swapon)\b",
            "privileged lifecycle enabled without native swapon support")
        self.assertRegex(
            source, r"\b(?:SYS_swapoff|swapoff)\b",
            "privileged lifecycle enabled without native swapoff support")

    def test_rootless_runner_registers_lifecycle_audit(self):
        runner = ROOTLESS_RUNNER.read_text(encoding="utf-8")
        invocation = (
            "python3 -B tests/runtime/native/primary-lifecycle-audit-test.py -v"
        )
        self.assertIn(invocation, runner)


if __name__ == "__main__":
    unittest.main()
