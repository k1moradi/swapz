#!/usr/bin/env python3
"""Rootless model tests; generated size labels are not native data."""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

PATH = Path(__file__).resolve().parents[2] / "tools/phase-a-preservation-policy-replay.py"
spec = importlib.util.spec_from_file_location("policy", PATH)
policy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(policy)


def metadata(**changes):
    result = dict(codec=1, length=768, version=1, dictionary=0, stored=True,
                  compatible=True, hypothetical_authority=True)
    result.update(changes)
    return result


def fixture():
    cases = []
    for codec in (1, 2):
        groups = []
        for stratum in range(7):
            rows = [[32*stratum+i, 600, 500, 1] for i in range(32)]
            groups.append(rows)
        for stratum, rows in [(-1, sum(groups[:6], [])), *enumerate(groups)]:
            count = len(rows)
            cases.append(dict(codec=codec, stratum=stratum,
                name="r112_shared" if stratum == -1 else policy.CATEGORIES[stratum],
                pages=count, eligible=count, payload=[500*count, 600*count],
                byte_exact=True, rows=copy.deepcopy(rows), pairs=[[100, 100, 80, 120] for _ in range(20)]))
    return dict(source_blob=policy.SOURCE_BLOB, identity=copy.deepcopy(policy.IDENTITY), cases=cases)


class PolicyTests(unittest.TestCase):
    def test_safety_metadata(self):
        cold = policy.SCENARIOS["cold"]
        self.assertEqual(policy.select(metadata(), cold), (True, "counterfactual_only"))
        for key, values in {"codec": (0, 3, True, "1", None), "length": (0, 3569, True, 1.0, None),
                            "version": (0, 2, True), "dictionary": (1, False, None),
                            "stored": (False, 1, None), "compatible": (False, 1, None),
                            "hypothetical_authority": (False, 1, None)}.items():
            for value in values:
                with self.subTest(key=key, value=value):
                    self.assertFalse(policy.select(metadata(**{key:value}), cold)[0])
        for key in policy.META_KEYS:
            meta = metadata()
            del meta[key]
            self.assertFalse(policy.select(meta, cold)[0])
        self.assertFalse(policy.select(metadata(extra=1), cold)[0])
        self.assertFalse(policy.select(metadata(codec=2), cold)[0])
        for length, expected in ((1, False), (127, False), (128, True), (768, True), (769, False), (3568, False)):
            self.assertEqual(policy.select(metadata(length=length), cold)[0], expected)
        self.assertTrue(policy.select(metadata(length=3568), cold, 3568)[0])
        self.assertFalse(policy.select(metadata(length=3569), cold, 3568)[0])
        for limit in (True, 127, 3569, None):
            self.assertFalse(policy.select(metadata(), cold, limit)[0])

    def test_states_and_boundaries(self):
        cold = policy.SCENARIOS["cold"]
        for key, values in {"pressure": (-1, 1001, True, None), "read_likelihood": (-1, 1001, True, None),
                            "queue_depth": (-1, 65, True, None), "packing_budget": (-1, 64*4096+1, True, None)}.items():
            for value in values:
                with self.subTest(key=key, value=value):
                    self.assertFalse(policy.select(metadata(), dict(cold, **{key:value}))[0])
        for key in policy.STATE_KEYS:
            state = cold.copy()
            del state[key]
            self.assertFalse(policy.select(metadata(), state)[0])
        for key, value, expected in (("pressure",749,False),("pressure",750,True),
            ("read_likelihood",100,True),("read_likelihood",101,False),
            ("queue_depth",16,True),("queue_depth",17,False),("queue_depth",47,False),
            ("queue_depth",48,False),("packing_budget",4095,False),("packing_budget",4096,True)):
            self.assertEqual(policy.select(metadata(), dict(cold, **{key:value}))[0], expected)
        for name, scenario in policy.SCENARIOS.items():
            self.assertEqual(policy.select(metadata(), scenario)[0], name == "cold")

    def test_strict_dataset_and_coverage(self):
        self.assertEqual(len(policy.validate(fixture())), 16)
        changes = [lambda x: x["identity"].update(auth=False), lambda x: x["identity"].update(round=115),
            lambda x: x.update(source_blob="0"*40), lambda x: x["cases"].pop(),
            lambda x: x["cases"][1].update(codec=True), lambda x: x["cases"][1].update(stratum=-1),
            lambda x: x["cases"][1].update(byte_exact=1), lambda x: x["cases"][1].update(name="bad"),
            lambda x: x["cases"][1]["rows"][1].__setitem__(0,0),
            lambda x: x["cases"][1]["rows"][0].__setitem__(1,3569),
            lambda x: x["cases"][1]["rows"][0].__setitem__(2,4097),
            lambda x: x["cases"][1]["rows"][0].__setitem__(3,True),
            lambda x: x["cases"][1]["payload"].__setitem__(0,0),
            lambda x: x["cases"][1]["pairs"][0].__setitem__(0,10**12+1),
            lambda x: x["cases"][1]["pairs"].pop(),
            lambda x: x["cases"][1]["rows"][0].__setitem__(0,32),
            lambda x: x["cases"][7]["rows"][0].__setitem__(0,0),
            lambda x: x["cases"][1].update(extra=True)]
        for i, change in enumerate(changes):
            with self.subTest(case=i):
                data = fixture()
                change(data)
                with self.assertRaises(policy.Invalid):
                    policy.validate(data)
        for raw in (b"", b"{}", b"x"*(policy.MAX_INPUT+1)):
            with self.assertRaises(policy.Invalid):
                policy.load(raw)
        with self.assertRaisesRegex(policy.Invalid, "duplicate_key"):
            json.loads('{"x":1,"x":2}', object_pairs_hook=policy.unique_object)

    def test_projection_equivalence(self):
        data = fixture()
        report = {k:v for k,v in data["identity"].items() if k not in ("columns", "categories", "lane_status")}
        lane = dict(status="PASS", cases=[dict(codec=c["codec"], stratum=c["stratum"], stratum_name=c["name"],
            pages=c["pages"], eligible=c["eligible"], payload_bytes=c["payload"], byte_exact=c["byte_exact"],
            page_sizes=c["rows"], pairs=c["pairs"]) for c in data["cases"]])
        report["measurements"] = dict(page_sizes_columns=data["identity"]["columns"], category_order=data["identity"]["categories"],
            results={"gcc-optimized":lane})
        self.assertTrue(policy.strict_equal(policy.project(report), data))

    def test_no_future_label_leakage_and_regret(self):
        cold = policy.SCENARIOS["cold"]
        original = [(1, 3, 1, 600, 600, 1), (1, 4, 2, 700, 40, 1)]
        changed = [(1, 6, 99, 600, 20, 1), (1, 0, 98, 700, 700, 0)]
        with patch.object(policy, "select", wraps=policy.select) as observed:
            first = policy.evaluate(original, cold, "conservative")
            calls = observed.call_args_list.copy()
            observed.reset_mock()
            second = policy.evaluate(changed, cold, "conservative")
            self.assertEqual(calls, observed.call_args_list)
        self.assertEqual(first["attempted"], second["attempted"])
        self.assertEqual(first["attempted"], 2)
        self.assertEqual(first["byte_regret"], 660)
        self.assertEqual(second["byte_regret"], 580)
        self.assertEqual(second["diagnostic_ineligible_attempts"], 1)
        self.assertEqual(second["fallback_bytes"], 700)

    def test_packing_and_bounded_arithmetic(self):
        self.assertEqual(policy.pack([0,4096,2048,2048,1],4096), 3*4096)
        self.assertEqual(policy.pack([1]*65,16384), 2*16384)
        self.assertEqual(policy.pack([4096]*224,4096), 224*4096)
        for lengths, extent in (([1]*225,4096),([4097],4096),([True],4096),([1],8193)):
            with self.assertRaises(policy.Invalid):
                policy.pack(lengths, extent)
        with self.assertRaises(policy.Invalid):
            policy.evaluate([(1,0,0,600,500,1)], (), "conservative")

    def test_replay_and_gates(self):
        indexed = policy.validate(fixture())
        result = policy.replay(indexed)
        self.assertEqual(result, policy.replay(indexed))
        self.assertTrue(result["matched_backing_results_identical"])
        self.assertEqual(result["verdict"], "NO_GO")
        for key, value in policy.GATES.items():
            self.assertIs(type(result[key]), type(value))
            self.assertEqual(result[key], value)
        for codec, data in result["results"].items():
            self.assertEqual(data["scenarios"]["cold"]["ordinary"]["pages"],224)
            self.assertEqual(data["scenarios"]["congested"]["eligible_always"]["selected"],0)
            self.assertEqual(data["scheduled"]["conservative"]["selected"],64 if codec=="1" else 0)
            self.assertEqual(data["scenarios"]["cold"]["conservative"]["selected"],224 if codec=="1" else 0)
            self.assertEqual(data["whole_case_cpu"]["r112_shared"]["paired_write_batch_delta_ns"],-20)
            self.assertEqual(data["whole_case_cpu"]["r112_shared"]["read_weighted_batch_delta_ns"]["cold"],-19)

    def test_cli_private_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/"private-name"
            path.write_text('{"private":"secret"}', encoding="utf-8")
            link = path.with_name("link")
            link.symlink_to(path)
            for target, reason in ((path,"input_identity"),(link,"regular_file_required")):
                proc = subprocess.run([sys.executable,"-B",str(PATH),str(target)],capture_output=True,check=False)
                self.assertEqual(proc.returncode,2)
                self.assertEqual(proc.stderr,b"")
                self.assertNotIn(b"private",proc.stdout)
                self.assertNotIn(b"secret",proc.stdout)
                self.assertNotIn(str(folder).encode(),proc.stdout)
                result = json.loads(proc.stdout)
                self.assertEqual(result["reason"],reason)
                for key,value in policy.GATES.items():
                    self.assertEqual(result[key],value)


if __name__ == "__main__":
    unittest.main()
