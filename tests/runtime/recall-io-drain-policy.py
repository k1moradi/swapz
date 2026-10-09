#!/usr/bin/env python3
"""Pure fail-closed model for DM and loop teardown evidence.

This module executes no device commands. A future separately reviewed fixture
must collect each item of evidence from its real worker, swap, DM and loop
operations before mapping those results into this state machine.
"""

from __future__ import annotations

import re
from typing import Mapping


class DrainDenied(RuntimeError):
    """The observed teardown evidence cannot authorize backing cleanup."""


_TEST_DM_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.+-]{0,127}\Z")
_LOOP_NAME = re.compile(r"/dev/loop[0-9]+\Z")


class DMIODrainPolicy:
    """Require a fixed, ordered evidence sequence for one DM stack and loop.

    ``dm_names`` is ordered upper-to-lower. Any skipped, repeated, malformed,
    contradictory, timed-out or failed observation permanently denies
    ``cleanup_allowed``; later positive observations cannot clear the denial.
    Evidence dictionaries have exact schemas so omitted or extra fields cannot
    be interpreted as an implicit safe default.
    """

    _INITIAL_FIELDS = {
        "admission_closed": {"closed": True},
        "workers_reaped": {
            "inventory_complete": True,
            "all_reaped": True,
            "errors_empty": True,
        },
        "swap_quiescent": {
            "inventory_valid": True,
            "mapper_active_before": bool,
            "swapoff_attempted": bool,
            "swapoff_succeeded": bool,
            "mapper_active_after": False,
        },
    }

    def __init__(self, dm_names: tuple[str, ...] | list[str], loop_device: str) -> None:
        if not isinstance(dm_names, (tuple, list)):
            raise DrainDenied("test DM stack must be an explicit ordered list")
        names = tuple(dm_names)
        if (not names or any(not isinstance(name, str) or _TEST_DM_NAME.fullmatch(name) is None
                             for name in names)
                or len(set(names)) != len(names)
                or not isinstance(loop_device, str) or _LOOP_NAME.fullmatch(loop_device) is None):
            raise DrainDenied("test DM stack or loop identity is malformed")
        self.dm_names = names
        self.loop_device = loop_device
        self._events: list[str] = []
        self._expected: list[tuple[str, str | None]] = [
            ("admission_closed", None),
            ("workers_reaped", None),
            ("swap_quiescent", None),
        ]
        for name in names:
            self._expected.extend((
                ("dm_suspended", name),
                ("dm_descriptors_closed", name),
                ("dm_open_count_zero", name),
                ("dm_removed", name),
                ("dm_absent", name),
            ))
        self._expected.extend((("loop_dependencies_clear", None), ("loop_detached", None)))
        self._denial: str | None = None

    @property
    def cleanup_allowed(self) -> bool:
        return self._denial is None and len(self._events) == len(self._expected)

    @property
    def preserve_backing(self) -> bool:
        return not self.cleanup_allowed

    @property
    def denial(self) -> str | None:
        return self._denial

    @property
    def events(self) -> tuple[str, ...]:
        return tuple(self._events)

    def observe(self, event: str, evidence: Mapping[str, object]) -> None:
        if self._denial is not None:
            raise DrainDenied(f"cleanup authorization is permanently denied: {self._denial}")
        if len(self._events) >= len(self._expected):
            self._deny("unexpected evidence after teardown completion")
        expected_event, expected_name = self._expected[len(self._events)]
        if event != expected_event:
            self._deny(f"out-of-order teardown evidence: expected {expected_event}, got {event}")
        if not isinstance(evidence, Mapping):
            self._deny("teardown evidence is not a mapping")
        try:
            values = dict(evidence)
        except Exception as exc:
            self._deny(f"cannot read teardown evidence fields: {exc}")
        if expected_name is not None:
            if values.pop("name", None) != expected_name:
                self._deny(f"DM identity mismatch for {expected_name}")
        if event in self._INITIAL_FIELDS:
            schema = self._INITIAL_FIELDS[event]
            self._check_exact(values, schema)
            if event == "swap_quiescent":
                if values["mapper_active_before"]:
                    if not values["swapoff_attempted"] or not values["swapoff_succeeded"]:
                        self._deny("active test swap was not successfully disabled")
                elif values["swapoff_attempted"] or values["swapoff_succeeded"]:
                    self._deny("swapoff result contradicts the initially inactive mapping")
        elif event == "dm_suspended":
            self._check_exact(values, {
                "ioctl_succeeded": True, "ordinary_flush": True,
                "noflush": False, "timed_out": False, "identity_matches": True,
                "suspended": True,
            })
        elif event == "dm_descriptors_closed":
            self._check_exact(values, {"all_closed": True, "close_errors_empty": True})
        elif event == "dm_open_count_zero":
            self._check_exact(values, {
                "inventory_valid": True, "identity_matches": True,
                "open_count": 0, "holders_empty": True,
            })
        elif event == "dm_removed":
            self._check_exact(values, {
                "remove_succeeded": True, "normal_remove": True,
                "force": False, "deferred": False, "identity_matches": True,
            })
        elif event == "dm_absent":
            self._check_exact(values, {
                "inventory_valid": True, "all_rows_valid": True,
                "name_absent": True, "uuid_absent": True, "device_number_absent": True,
            })
        elif event == "loop_dependencies_clear":
            self._check_exact(values, {
                "dm_stack_absent": True, "holder_inventory_valid": True,
                "holders_empty": True, "loop_identity_matches": True,
            })
        elif event == "loop_detached":
            self._check_exact(values, {
                "detach_succeeded": True, "normal_detach": True,
                "inventory_valid": True, "exact_loop_absent": True,
            })
        else:
            self._deny(f"unsupported teardown evidence event: {event}")
        self._events.append(event + (":" + expected_name if expected_name else ""))

    def _check_exact(self, values: dict[str, object], schema: dict[str, object]) -> None:
        if set(values) != set(schema):
            self._deny("teardown evidence fields are missing or unexpected")
        for key, expected in schema.items():
            actual = values[key]
            if expected is bool:
                if type(actual) is not bool:
                    self._deny(f"teardown evidence {key} is not a boolean")
            elif type(actual) is not type(expected) or actual != expected:
                self._deny(f"teardown evidence {key} is not the required value")
            elif isinstance(expected, bool) and actual is not expected:
                self._deny(f"teardown evidence {key} contradicts the required value")

    def _deny(self, reason: str) -> None:
        self._denial = reason
        raise DrainDenied(reason)


__all__ = ["DMIODrainPolicy", "DrainDenied"]
