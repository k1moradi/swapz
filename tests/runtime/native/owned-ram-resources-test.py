#!/usr/bin/env python3
"""Creation-proof recovery controls; no real devices or privileged operations."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import subprocess
import unittest
from unittest import mock

SCRIPT = Path(__file__).resolve().parents[2] / "tools/owned-ram-resources.py"
SPEC = importlib.util.spec_from_file_location("owned_ram_resources", SCRIPT)
subject = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(subject)


def fixture():
    devices = [{"name": "nullb-swapz-" + digit * 16, "config": [12, i + 10],
                "memory_backed": 1, "size": 64, "blocksize": 4096, "queue_mode": 2,
                "power": 1, "index": i, "devno": f"251:{i}", "block": [13, i + 20]}
               for i, digit in enumerate("ab")]
    return {"schema": "swapz-owned-ram-v1", "boot": "1" * 8 + "-" + "2" * 27,
            "pid": 123, "start": 456, "source": "a" * 40, "session": [1, 22],
            "devices": devices, "module": {"identity": [13, 77], "source": "a" * 40},
            "host_swaps": [["/dev/safe-native", "partition", "12345", "-1"]],
            "mapper": {"name": "swapz-demo-" + "c" * 16,
                       "uuid": "SWAPZ-TEST-" + "c" * 16, "devno": "252:0",
                       "block": [13, 88], "kernel": "dm-0", "table": "d" * 64,
                       "slaves": ["251:1"], "target": "swapz"}}


class Backend:
    def __init__(self, claim):
        self.mod = copy.deepcopy(claim["module"])
        self.mapping = dict(copy.deepcopy(claim["mapper"]), opens=0)
        self.devices = {d["name"]: dict(copy.deepcopy(d), holders=["dm-0"] if i else [])
                        for i, d in enumerate(claim["devices"])}
        self.actions = []
        self.busy = False
        self.fail_device = False

    def module(self): return copy.deepcopy(self.mod)
    def mapper(self, *_): return copy.deepcopy(self.mapping)
    def device(self, name): return copy.deepcopy(self.devices.get(name))
    def unused(self, _): subject.require(not self.busy, "foreign-process-or-mount")
    def remove_mapper(self, _):
        self.actions.append("mapper")
        self.mapping = None
        for device in self.devices.values(): device["holders"] = []
    def remove_device(self, device):
        if self.fail_device:
            self.fail_device = False
            self.devices[device["name"]]["power"] = 0
            raise subject.Refused("interrupted-after-poweroff")
        self.actions.append(device["name"])
        del self.devices[device["name"]]
    def remove_module(self, expected):
        subject.require(self.mod == expected, "module-substitution")
        self.actions.append("module")
        self.mod = None


class OwnedRamResourceTests(unittest.TestCase):
    def test_loaded_preflight_recovers_before_module_ownership_refusal(self):
        tools = SCRIPT.parent
        preflight = (tools / "loaded-preflight.sh").read_text()
        start = preflight.index('if [[ ! -d /sys/module/dm_swapz ]]; then\n    # Do not interpret')
        self.assertLess(preflight.index('if swapz_recover_abandoned_ram_resources; then'), start)
        self.assertGreater(preflight.index('if swapz_clear_tmp_before_memory_check; then'), start)
        loaded = (tools / "test-loaded.sh").read_text()
        self.assertIn('run_privileged_bounded 150 tests/tools/qualify-owned-ram-recovery.sh', loaded)

    def test_complete_proof_and_legacy_refusal(self):
        claim = fixture()
        owner = b"pid=123\nsource_sha=" + b"a" * 40 + b"\n"
        self.assertEqual(subject.parse_claim(json.dumps(claim).encode(), [1, 22], owner), claim)
        for data in (owner, b"{}", json.dumps(dict(claim, extra=True)).encode()):
            with self.subTest(data=data[:20]), self.assertRaises((subject.Refused, ValueError)):
                subject.parse_claim(data, [1, 22], owner)

    def test_corrupted_or_foreign_claims_are_rejected(self):
        for change in (lambda c: c.update(session=[1, 23]),
                       lambda c: c.update(source="b" * 40),
                       lambda c: c["devices"][0].update(memory_backed=0),
                       lambda c: c["devices"][0].update(index=True),
                       lambda c: c["mapper"].update(uuid="SWAPZ-PHYSICAL-other"),
                       lambda c: c["mapper"].update(slaves=["259:3"]),
                       lambda c: c["module"].update(source="invalid")):
            claim = fixture(); change(claim)
            with self.assertRaises(subject.Refused):
                subject.parse_claim(json.dumps(claim).encode(), [1, 22],
                                    b"pid=123\nsource_sha=" + b"a" * 40 + b"\n")

    def test_report_head_and_embedded_module_source_are_separately_bound(self):
        claim = fixture(); claim["source"] = "e" * 40
        parsed = subject.parse_claim(json.dumps(claim).encode(), [1, 22],
                                     b"pid=123\nsource_sha=" + b"e" * 40 + b"\n")
        backend = Backend(parsed)
        subject.recover_claim(parsed, backend)
        self.assertEqual(backend.actions[-1], "module")

    def test_cleanup_preserves_the_original_child_exit(self):
        script = SCRIPT.with_name("benchmark-owned-pair.sh").read_text()
        start = script.index("cleanup() {")
        cleanup = script[start:script.index("\ntrap cleanup EXIT", start)]
        with tempfile.TemporaryDirectory() as directory:
            setup = '''
set +e
OWN_DM=0 OWN_MODULE=0 COUNT=0 READY_COUNT=0 QUARANTINE=0
RESOURCE_PROOF_CREATED=0 SOURCE=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
SWAPS_ID=different
id36_release_failed_pair_pressure() { return 0; }
swapz_swap_inventory_identity() { printf 'stable\\n'; }
note() { :; }
pair_timing_boundary() { :; }
cat() { printf 'Filename Type Size Used Priority\\n'; }
'''
            for original, expected in ((47, 47), (0, 1)):
                result = subprocess.run(["bash", "-c", setup + cleanup +
                                         f"\n(exit {original})\ncleanup\n"],
                                        env=dict(os.environ, SESSION=directory),
                                        capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, expected, result.stderr)
        self.assertNotIn("fuser -k", script)

    def test_active_and_reused_pid_and_foreign_boot(self):
        claim = fixture()
        self.assertFalse(subject.abandoned(claim, claim["boot"], 456))
        self.assertTrue(subject.abandoned(claim, claim["boot"], None))
        for boot, start in ((claim["boot"], 999), ("different-boot", None)):
            with self.assertRaises(subject.Refused): subject.abandoned(claim, boot, start)

    def test_positive_cleanup_order_and_idempotence(self):
        claim = fixture(); backend = Backend(claim)
        subject.recover_claim(claim, backend)
        self.assertEqual(backend.actions, ["mapper", claim["devices"][1]["name"],
                                          claim["devices"][0]["name"], "module"])
        subject.recover_claim(claim, backend)
        self.assertEqual(len(backend.actions), 4)

    def test_changes_or_busy_users_prevent_mutation(self):
        claim = fixture()
        for change in (lambda b: b.mapping.update(opens=1),
                       lambda b: b.mapping.update(uuid="wrong"),
                       lambda b: b.devices[claim["devices"][0]["name"]].update(config=[99, 99]),
                       lambda b: b.devices[claim["devices"][0]["name"]].update(block=[99, 99]),
                       lambda b: b.devices[claim["devices"][0]["name"]].update(holders=["foreign"]),
                       lambda b: b.mod.update(identity=[99, 99]),
                       lambda b: setattr(b, "busy", True)):
            backend = Backend(claim); change(backend)
            with self.assertRaises(subject.Refused): subject.recover_claim(claim, backend)
            self.assertEqual(backend.actions, [])

    def test_interrupted_poweroff_is_recoverable_without_touching_foreign_objects(self):
        claim = fixture(); backend = Backend(claim); backend.fail_device = True
        with self.assertRaisesRegex(subject.Refused, "interrupted-after-poweroff"):
            subject.recover_claim(claim, backend)
        self.assertEqual(backend.actions, ["mapper"])
        subject.recover_claim(claim, backend)
        self.assertIsNone(backend.mod)
        self.assertFalse(backend.devices)

    def test_module_not_created_by_session_is_never_unloaded(self):
        claim = fixture(); claim["module"] = None; claim["mapper"]["target"] = "linear"
        backend = Backend(claim)
        backend.mod = {"identity": [99, 77], "source": "f" * 40}
        subject.recover_claim(claim, backend)
        self.assertNotIn("module", backend.actions)
        self.assertEqual(backend.mod["identity"], [99, 77])

    def test_swap_used_is_volatile_but_identity_changes_are_not(self):
        before = b"Filename Type Size Used Priority\n/dev/safe partition 100 0 -1\n"
        self.assertEqual(subject.swap_identity(before), subject.swap_identity(before.replace(b"100 0", b"100 50")))
        self.assertNotEqual(subject.swap_identity(before), subject.swap_identity(before.replace(b"-1", b"1")))

    def test_private_record_symlink_hardlink_modes_and_changed_reads(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "proof"; path.write_bytes(b"proof"); path.chmod(0o600)
            directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
            try:
                self.assertEqual(subject.secure_read(directory, "proof", uid=os.getuid())[0], b"proof")
                os.link(path, Path(root) / "alias")
                with self.assertRaises(subject.Refused): subject.secure_read(directory, "proof", uid=os.getuid())
                (Path(root) / "alias").unlink()
                (Path(root) / "alias").symlink_to(path)
                with self.assertRaises(OSError): subject.secure_read(directory, "alias", uid=os.getuid())
                path.chmod(0o644)
                with self.assertRaises(subject.Refused): subject.secure_read(directory, "proof", uid=os.getuid())
                path.chmod(0o600)
                with mock.patch.object(subject.os, "pread", return_value=b"changed"):
                    with self.assertRaises(subject.Refused): subject.secure_read(directory, "proof", uid=os.getuid())
            finally:
                os.close(directory)


if __name__ == "__main__": unittest.main()
