#!/usr/bin/env python3
"""Rootless synthetic lifecycle and conservation checks, never native evidence."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import json

PATH = Path(__file__).resolve().parents[2] / "tools/phase-a-storage-credit-replay.py"
spec = importlib.util.spec_from_file_location("credits", PATH)
credits = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = credits
spec.loader.exec_module(credits)
P = credits.PAGE
M = credits.Metadata


class CreditTests(unittest.TestCase):
    def ledger(self, capacity=4*P, depth=4, extent=P, mode="conservative"):
        return credits.Ledger(capacity, depth, extent, mode)

    def reserve(self, ledger, logical=0, meta=M(1, 512), retry=False):
        return ledger.reserve(logical, meta, 850, 50, retry)

    def finish(self, ledger, token, status=0):
        self.assertEqual(ledger.dispatch(), token)
        ledger.complete(token, status, ledger.jobs[token].size if not status else 0)

    def write(self, ledger, logical, ordinary=512, label=1, meta=M(1, 512)):
        token = self.reserve(ledger, logical, meta)
        ledger.claim(token, ordinary, label)
        self.finish(ledger, token)
        return token

    def retire(self, ledger, logical):
        ledger.invalidate(logical)
        self.finish(ledger, ledger.control(logical, "gc"))

    def reject(self, ledger, action, reason):
        # Rejected external transitions must leave the ledger exactly intact.
        from copy import deepcopy
        snapshot = deepcopy(ledger.__dict__)
        with self.assertRaisesRegex(credits.Invalid, "^"+reason+"$"):
            action()
        self.assertEqual(ledger.__dict__, snapshot)
        ledger.audit()

    def test_capacity_queue_and_retry(self):
        ledger = self.ledger(capacity=2*P)
        first = self.reserve(ledger)
        second = self.reserve(ledger, 1)
        self.assertIsNone(self.reserve(ledger, 2))
        self.assertEqual(ledger.occupied, 2*P)
        self.assertEqual(len(ledger.jobs), 2)
        ledger.claim(first, 512, 1)
        self.finish(ledger, first)
        self.assertEqual(ledger.occupied, 2*P)  # completion returns queue, not live space
        self.assertIsNone(self.reserve(ledger, 2, retry=True))
        ledger.cancel(second)
        self.assertEqual(ledger.occupied, P)
        third = self.reserve(ledger, 2, retry=True)
        ledger.claim(third, 512, 1)
        self.finish(ledger, third)
        self.retire(ledger, 0)
        retry = self.reserve(ledger, 1, retry=True)
        self.assertNotEqual(retry, second)
        ledger.claim(retry, 512, 1)
        self.finish(ledger, retry)
        self.retire(ledger, 1)
        self.retire(ledger, 2)
        result = ledger.cleanup()
        self.assertEqual(result["write_acks"], 3)
        self.assertEqual(result["deferrals"], 2)
        self.assertEqual(result["unique_deferred"], 1)
        self.assertEqual(result["cancellations"], 1)
        self.assertEqual(result["reserved_bytes"], result["returned_bytes"])

    def test_completion_identity_order_and_size(self):
        ledger = self.ledger()
        a, b = self.reserve(ledger), self.reserve(ledger, 1)
        self.reject(ledger, lambda: ledger.complete(a, 0, P), "completion_order")
        self.reject(ledger, lambda: ledger.claim(a, 4097, 1), "outcome_bounds")
        ledger.claim(a, 512, 1)
        ledger.claim(b, 512, 1)
        self.reject(ledger, lambda: ledger.cancel(a), "reservation_order")
        self.reject(ledger, lambda: ledger.claim(a, 512, 1), "reservation_order")
        self.assertEqual(ledger.dispatch(), a)
        for token, status, size, reason in ((b, 0, P, "completion_order"),
                (True, 0, P, "completion_order"), (a, False, P, "completion_size_or_status"),
                (a, 0, P-1, "completion_size_or_status"), (a, 1, P, "completion_size_or_status")):
            self.reject(ledger, lambda: ledger.complete(token, status, size), reason)
        self.reject(ledger, ledger.dispatch, "active_service")
        ledger.complete(a, 0, P)
        self.reject(ledger, lambda: ledger.complete(a, 0, P), "completion_order")
        self.finish(ledger, b)
        self.retire(ledger, 0)
        self.retire(ledger, 1)
        self.assertEqual(ledger.cleanup()["write_acks"], 2)

    def test_quarantine_and_failed_controls(self):
        ledger = self.ledger()
        token = self.reserve(ledger)
        ledger.claim(token, 512, 1)
        self.finish(ledger, token, 1)
        self.assertEqual(ledger.occupied, P)
        self.assertEqual(ledger.records[0].phase, "quarantine")
        self.reject(ledger, lambda: ledger.reserve(0, M(1,512),850,50,True), "arrival_order")
        self.reject(ledger, lambda: ledger.invalidate(0), "invalidate_order")
        self.reject(ledger, lambda: ledger.control(0,"gc"), "control_order_or_credit")
        self.write(ledger, 1)
        self.finish(ledger, ledger.control(1, "read"), 1)
        self.assertFalse(ledger.records[1].pin)
        ledger.invalidate(1)
        self.finish(ledger, ledger.control(1,"gc"), 1)
        self.assertEqual(ledger.occupied, 2*P)
        self.finish(ledger, ledger.control(1,"gc"))
        self.assertEqual(ledger.occupied, P)
        self.assertEqual(ledger.stats["write_acks"], 1)
        self.assertEqual(ledger.stats["failed_writes"], 1)
        self.assertEqual(ledger.stats["quarantined_bytes"], P)
        self.reject(ledger, ledger.cleanup, "cleanup_debt")

    def test_control_progress_under_writes(self):
        ledger = self.ledger(capacity=8*P, depth=5)
        self.write(ledger, 0)
        self.write(ledger, 1)
        a = self.reserve(ledger, 2)
        b = self.reserve(ledger, 3)
        c = self.reserve(ledger, 4)
        for token in (a,b,c): ledger.claim(token, 512, 1)
        read = ledger.control(0,"read")
        ledger.invalidate(1)
        gc = ledger.control(1,"gc")
        self.assertEqual(len(ledger.jobs),5)
        self.assertIsNone(self.reserve(ledger,5))
        self.reject(ledger, lambda: ledger.invalidate(0), "invalidate_order")
        self.reject(ledger, lambda: ledger.control(0,"read"), "control_order_or_credit")
        dispatched = []
        while ledger.jobs:
            token = ledger.dispatch()
            dispatched.append(token)
            ledger.complete(token,0,ledger.jobs[token].size)
        self.assertLessEqual(dispatched.index(read),2)
        self.assertLessEqual(dispatched.index(gc),2)
        for logical in (0,2,3,4): self.retire(ledger,logical)
        self.write_retry(ledger,5)
        self.retire(ledger,5)
        self.assertEqual(ledger.cleanup()["peak_queue"],5)

    def write_retry(self, ledger, logical):
        token = self.reserve(ledger, logical, retry=True)
        ledger.claim(token,512,1)
        self.finish(ledger,token)

    def test_zero_raw_and_preclaim_fallback(self):
        for extent in credits.CLASSES:
            with self.subTest(extent=extent):
                ledger = self.ledger(capacity=3*extent,extent=extent,mode="eligible_always")
                zero = self.reserve(ledger,0)
                ledger.claim(zero,0,0)
                self.assertEqual(ledger.occupied,extent)
                self.finish(ledger,zero)
                self.assertEqual(ledger.occupied,0)
                self.write(ledger,1,P,0,M(1,4114))
                self.assertEqual(ledger.occupied,P)
                self.write(ledger,2,26,0,M(1,26))
                self.assertEqual(ledger.occupied,P+extent)
                for logical in (0,1,2): self.retire(ledger,logical)
                result = ledger.cleanup()
                self.assertEqual(result["preclaim_fallbacks"],2)
                self.assertEqual(result["write_bytes"],P+extent)

    def test_metadata_bounds_and_no_label_leakage(self):
        self.assertTrue(credits.select(M(1,768),750,100,16,P,"conservative"))
        for meta in (M(1,769),M(1,127),M(2,512),M(1,512,version=2),M(1,512,dictionary=1),
                     M(1,512,stored=False),M(1,512,compatible=False),M(1,512,hypothetical_authority=False),
                     M(True,512),M(1,True),M(1,512,stored=1)):
            self.assertFalse(credits.select(meta,850,50,0,P,"conservative"))
        for pressure,likelihood,depth,space in ((749,50,0,P),(850,101,0,P),(850,50,17,P),
                (850,50,48,P),(850,50,0,P-1),(True,50,0,P),(850,50,0,64*P+1)):
            self.assertFalse(credits.select(M(1,512),pressure,likelihood,depth,space,"conservative"))
        self.assertTrue(credits.select(M(2,3568),850,50,0,P,"eligible_always"))
        self.assertFalse(credits.select(M(2,3569),850,50,0,P,"eligible_always"))
        decisions=[]
        for ordinary,label in ((512,1),(48,1),(0,0)):
            ledger=self.ledger()
            token=self.reserve(ledger)
            decisions.append((ledger.records[0].attempt,ledger.occupied))
            ledger.claim(token,ordinary,label)
            self.finish(ledger,token)
            self.retire(ledger,0)
            ledger.cleanup()
        self.assertEqual(decisions,[(True,P)]*3)
        for capacity,depth,extent in ((P-1,4,P),(64*P+1,4,P),(P,2,P),(P,65,P),(P,4,512),(True,4,P)):
            with self.assertRaises(credits.Invalid): self.ledger(capacity,depth,extent)
        ledger=self.ledger()
        self.reject(ledger,lambda:self.reserve(ledger,True),"arrival_shape")
        self.reject(ledger,lambda:self.reserve(ledger,0,M(1,512,stored=1)),"arrival_shape")
        token=self.reserve(ledger)
        self.reject(ledger,lambda:self.reserve(ledger),"arrival_order")
        self.reject(ledger,ledger.cleanup,"cleanup_debt")
        ledger.cancel(token)
        self.reject(ledger,lambda:ledger.cancel(token),"stale_token")
        self.reject(ledger,lambda:self.reserve(ledger,0,M(1,513),True),"arrival_order")
        self.reject(ledger,ledger.cleanup,"cleanup_debt")
        ledger.events=credits.MAX_EVENTS
        self.reject(ledger,lambda:self.reserve(ledger,0,retry=True),"event_limit")

    def test_determinism_and_redaction(self):
        rows=[[i%6 if i<192 else 6,i,512,512,1] for i in range(224)]
        first=credits.replay_one(rows,1,"conservative",credits.CONFIGS[0])
        self.assertEqual(first,credits.replay_one(rows,1,"conservative",credits.CONFIGS[0]))
        self.assertEqual(first["write_acks"],224)
        self.assertEqual(first["reserved_bytes"],first["returned_bytes"])
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"private-secret"
            path.write_bytes(b'{"secret":"never-print"}')
            for candidate in (path,path.with_name("missing")):
                run=subprocess.run([sys.executable,"-B",str(PATH),str(candidate)],capture_output=True,check=False)
                self.assertEqual(run.returncode,2)
                self.assertEqual(run.stderr,b"")
                self.assertNotIn(b"private-secret",run.stdout)
                self.assertNotIn(b"never-print",run.stdout)
                output=json.loads(run.stdout)
                self.assertEqual(output["status"],"BLOCKED")
                for key,value in credits.GATES.items(): self.assertEqual(output[key],value)


if __name__ == "__main__":
    unittest.main()
