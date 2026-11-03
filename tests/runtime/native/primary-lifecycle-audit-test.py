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
import unittest

ROOT = Path(__file__).resolve().parents[3]
PRIMARY_SOURCE = ROOT / "src/userspace/swapz-primary.c"
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


def c_function_body(source: str, symbol: str) -> str:
    """Return one static-int executable body, ignoring comments and literals."""
    source = _c_code_only(source)
    match = re.search(
        r"static\s+int\s+" + re.escape(symbol) + r"\s*\([^;]*?\)\s*\{",
        source, re.S)
    if not match:
        raise AssertionError("missing production function " + symbol)
    start = match.end()
    depth = 1
    for position in range(start, len(source)):
        if source[position] == "{":
            depth += 1
        elif source[position] == "}":
            depth -= 1
            if depth == 0:
                return source[start:position]
    raise AssertionError("unclosed production function " + symbol)


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

        self.assertIn("syscall(SYS_swapon, mapper_path, 0)", activate)
        self.assertGreaterEqual(
            activate.count(
                "swapz_primary_swap_device_active(expected_mapper_device)"), 2)
        self.assertIn("swapz_primary_dm_mapper_verify_fd(", activate)
        self.assertLess(
            start.index("swapz_primary_activate_mapper_swap("),
            start.index("active_state.stage = SWAPZ_PRIMARY_STAGE_ACTIVE"))

        self.assertIn("syscall(SYS_swapoff, mapper_path)", deactivate)
        self.assertGreaterEqual(
            deactivate.count("swapz_primary_swap_device_active(mapper_device)"),
            2)
        self.assertIn("swapz_primary_dm_mapper_verify_fd(", deactivate)
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
        gate = re.search(
            r"^#define\s+SWAPZ_PRIMARY_EXECUTION_ENABLED\s+([01])\s*$",
            source, re.MULTILINE)
        self.assertIsNotNone(gate, "primary execution gate must remain explicit")
        self.assertEqual(
            gate.group(1), "0",
            "privileged lifecycle needs owned-null_blk and physical evidence")
        self.assertIn("#ifndef SWAPZ_PRIMARY_OWNED_NULLBLK_TEST", source)
        self.assertIn(
            "#define SWAPZ_PRIMARY_CONFIG_BASE \"/etc/swapz\"", source)
        self.assertIn(
            "#define SWAPZ_PRIMARY_RECOVERY_BASE "
            "\"/var/lib/swapz/physical-recovery\"", source)
        self.assertIn(
            "#define SWAPZ_PRIMARY_EXECUTION_ENABLED 1", source)
        self.assertNotIn(
            "SWAPZ_PRIMARY_OWNED_NULLBLK_TEST",
            ROOT_MAKEFILE.read_text(encoding="utf-8"),
            "public build must never enable the owned-null_blk lifecycle seam")

    def test_execution_gate_cannot_enable_without_native_swap_operations(self):
        source = PRIMARY_SOURCE.read_text(encoding="utf-8")
        gate = re.search(
            r"^#define\s+SWAPZ_PRIMARY_EXECUTION_ENABLED\s+([01])\s*$",
            source, re.MULTILINE)
        self.assertIsNotNone(gate, "primary execution gate must remain explicit")
        if gate.group(1) == "0":
            return
        activate = c_function_body(source, "swapz_primary_activate_mapper_swap")
        deactivate = c_function_body(source, "swapz_primary_deactivate_mapper_swap")
        self.assertRegex(
            activate, r"\bsyscall\s*\(\s*SYS_swapon\s*,",
            "privileged lifecycle enabled without executable native swapon")
        self.assertRegex(
            deactivate, r"\bsyscall\s*\(\s*SYS_swapoff\s*,",
            "privileged lifecycle enabled without executable native swapoff")

    def test_source_guard_ignores_comments_and_string_literals(self):
        sample = """static int swapz_primary_activate_mapper_swap(void) {
            /* } syscall(SYS_swapon, mapper_path, 0); */
            const char *diagnostic = "syscall(SYS_swapon, mapper_path, 0)";
            return -1;
        }"""
        executable = c_function_body(sample, "swapz_primary_activate_mapper_swap")
        self.assertNotIn("syscall(SYS_swapon, mapper_path, 0)", executable)
        self.assertIn("return -1;", executable)

    def test_rootless_runner_registers_lifecycle_audit(self):
        runner = ROOTLESS_RUNNER.read_text(encoding="utf-8")
        invocation = (
            "python3 -B tests/runtime/native/primary-lifecycle-audit-test.py -v"
        )
        self.assertIn(invocation, runner)


if __name__ == "__main__":
    unittest.main()
