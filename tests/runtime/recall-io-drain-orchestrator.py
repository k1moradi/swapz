#!/usr/bin/env python3
"""Rootless, synthetic-only orchestrator of Codex's fail-closed drain policy.

This code does NOT inspect, suspend, remove, or detach any real Linux device.
The only operations are mutations of explicitly fabricated in-memory fixture
state and, on complete authorization, unlink of a private synthetic marker.
It is *not* a trusted kernel evidence collector or production teardown path.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import stat
import sys
from typing import Any

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location(
    "swapz_mock_drain_policy", HERE / "recall-io-drain-policy.py"
)
if spec is None or spec.loader is None:
    raise RuntimeError("drain policy implementation unavailable")
policy_module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = policy_module
spec.loader.exec_module(policy_module)
DMIODrainPolicy = policy_module.DMIODrainPolicy
DrainDenied = policy_module.DrainDenied
ROLES = frozenset(("writer", "a", "b", "a2", "b2"))


class SyntheticFixtureOps:
    """Fabricated state/operation witness; never run subprocesses or syscalls.

    Optional fault injection returns deliberately contradictory evidence or
    raises a synthetic error. Test code may inspect the immutable trace.
    """

    def __init__(self, names: tuple[str, ...], loop: str,
                 handles: dict[str, str] | None = None,
                 faults: dict[str, dict[str, object] | str] | None = None):
        self.names = names
        self.loop = loop
        self.handles = (dict(handles) if handles is not None else
                        {role: f"fixture-handle-{role}" for role in ROLES})
        self.faults = dict(faults or {})
        self.trace: list[str] = []
        self.admission_open = True
        self.swap_active = True
        self.loop_attached = True
        self.dm: dict[str, dict[str, object]] = {
            name: {"suspended": False, "open": 0, "holders": 0,
                   "descriptors": True, "present": True}
            for name in names
        }

    def perform(self, event: str, name: str | None = None) -> dict[str, object]:
        label = event if name is None else f"{event}:{name}"
        self.trace.append(label)
        if name is not None and name not in self.dm:
            raise DrainDenied("synthetic operation targets unknown mapping")
        state = self.dm.get(name) if name is not None else None

        if event == "admission_closed":
            self.admission_open = False
            evidence = {"closed": not self.admission_open}
        elif event == "workers_reaped":
            inventory = self.handles
            complete = (set(inventory) == ROLES and len(set(inventory.values())) == 5
                        and all(type(handle) is str and bool(handle) for handle in inventory.values()))
            evidence = {"inventory_complete": complete, "all_reaped": complete,
                        "errors_empty": complete}
        elif event == "swap_quiescent":
            before = self.swap_active
            self.swap_active = False  # fabricated successful swapoff
            evidence = {"inventory_valid": True, "mapper_active_before": before,
                        "swapoff_attempted": before, "swapoff_succeeded": before,
                        "mapper_active_after": self.swap_active}
        elif event == "dm_suspended" and state is not None:
            state["suspended"] = True  # simulated normal suspend, never a kernel ioctl
            evidence = {"name": name, "ioctl_succeeded": True,
                        "ordinary_flush": True, "noflush": False,
                        "timed_out": False, "identity_matches": True,
                        "suspended": state["suspended"]}
        elif event == "dm_descriptors_closed" and state is not None:
            state["descriptors"] = False
            evidence = {"name": name, "all_closed": True, "close_errors_empty": True}
        elif event == "dm_open_count_zero" and state is not None:
            evidence = {"name": name, "inventory_valid": True,
                        "identity_matches": True, "open_count": state["open"],
                        "holders_empty": state["holders"] == 0}
        elif event == "dm_removed" and state is not None:
            if state["suspended"] and not state["descriptors"] and state["open"] == 0:
                state["present"] = False
            evidence = {"name": name, "remove_succeeded": not state["present"],
                        "normal_remove": True, "force": False, "deferred": False,
                        "identity_matches": True}
        elif event == "dm_absent" and state is not None:
            absent = not state["present"]
            evidence = {"name": name, "inventory_valid": True, "all_rows_valid": True,
                        "name_absent": absent, "uuid_absent": absent,
                        "device_number_absent": absent}
        elif event == "loop_dependencies_clear":
            absent = all(not item["present"] for item in self.dm.values())
            evidence = {"dm_stack_absent": absent, "holder_inventory_valid": True,
                        "holders_empty": absent, "loop_identity_matches": True}
        elif event == "loop_detached":
            absent = all(not item["present"] for item in self.dm.values())
            if absent:
                self.loop_attached = False
            evidence = {"detach_succeeded": not self.loop_attached,
                        "normal_detach": True, "inventory_valid": True,
                        "exact_loop_absent": not self.loop_attached}
        else:
            raise DrainDenied("unexpected fabricated teardown operation")

        injected = self.faults.get(label)
        if isinstance(injected, str):
            raise DrainDenied("injected operation failure: " + injected)
        if isinstance(injected, dict):
            evidence.update(injected)
        return evidence


class RootlessMockDrainSession:
    """Run all stages, preserve marker on every uncertain or failed stage."""

    def __init__(self, names: tuple[str, ...], loop: str, marker: Path,
                 *, ops: SyntheticFixtureOps):
        if type(ops) is not SyntheticFixtureOps:
            raise DrainDenied("only the explicitly synthetic fixture witness is accepted")
        if not isinstance(marker, Path) or not marker.is_absolute():
            raise DrainDenied("synthetic marker must be an absolute private path")
        self.policy = DMIODrainPolicy(names, loop)
        if ops.names != tuple(names) or ops.loop != loop:
            raise DrainDenied("fixture identity differs from exact drain policy")
        self.ops = ops
        self.marker = marker
        self.failed = False
        self.completed = False
        self._original = self._marker_stat()

    def _marker_stat(self) -> os.stat_result:
        directory = os.stat(self.marker.parent, follow_symlinks=False)
        if not stat.S_ISDIR(directory.st_mode) or directory.st_uid != os.geteuid() or directory.st_mode & 0o077:
            raise DrainDenied("backing marker directory is not private")
        info = os.stat(self.marker, follow_symlinks=False)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or info.st_nlink != 1 or info.st_mode & 0o077):
            raise DrainDenied("backing marker is not private or not a single regular inode")
        return info

    def run(self) -> bool:
        if self.failed or self.completed:
            raise DrainDenied("synthetic session cannot be repeated after failure/completion")
        stages = [("admission_closed", None), ("workers_reaped", None),
                  ("swap_quiescent", None)]
        for name in self.policy.dm_names:
            stages.extend((("dm_suspended", name),
                           ("dm_descriptors_closed", name),
                           ("dm_open_count_zero", name),
                           ("dm_removed", name),
                           ("dm_absent", name)))
        stages.extend((("loop_dependencies_clear", None), ("loop_detached", None)))
        try:
            for event, name in stages:
                evidence = self.ops.perform(event, name)
                self.policy.observe(event, evidence)
            if not self.policy.cleanup_allowed:
                raise DrainDenied("policy did not positively authorize full teardown")
            current = self._marker_stat()
            if ((current.st_dev, current.st_ino) !=
                    (self._original.st_dev, self._original.st_ino)):
                raise DrainDenied("synthetic backing marker was replaced")
            # This is the only filesystem effect: a PRIVATE SYNTHETIC marker.
            self.marker.unlink()
            self.completed = True
            return True
        except BaseException:
            self.failed = True
            raise


__all__ = ["RootlessMockDrainSession", "SyntheticFixtureOps", "DrainDenied"]
