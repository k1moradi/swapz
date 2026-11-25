#!/usr/bin/env python3
"""Fabricated traces only; no probe import, host or device access."""
import copy
import hashlib
import importlib.util
from pathlib import Path
import unittest

PATH = Path(__file__).resolve().parents[2] / "tools" / "round092-integrated-evidence.py"
SPEC = importlib.util.spec_from_file_location("integrated", PATH)
MODEL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODEL)


def hashed(label, length=64):
    return hashlib.sha256(label.encode()).hexdigest()[:length]


def fixture():
    scope = {key: hashed(key, 40 if key in ("source", "kernel")
                         else 32 if key == "nonce" else 64) for key in MODEL.SCOPE}
    protected = {key: scope[key] for key in MODEL.PROTECTION}
    prefix = ["eviction", "enqueue_unclaimed", "ordered_head", "reserve"]
    variants = [
        ("typed_success", ["claim", "lower_complete", "lower_durable", "map_publish",
                           "upper_ack", "read", "gc_move", "read_after_gc", "overwrite",
                           "discard"], (1, 1, 0, 1)),
        ("preclaim_decline", ["claim_refused", "cancel", "ordinary_fallback",
                              "ordinary_lower_complete", "ordinary_lower_durable",
                              "ordinary_map_publish", "ordinary_upper_ack", "read"],
         (1, 0, 1, 1)),
        ("claimed_error", ["claim", "lower_error", "quarantine", "upper_error_redirty"],
         (1, 1, 0, 1)),
    ]
    pages, sequence = [], 0
    for index, (outcome, tail, counts) in enumerate(variants):
        identity = {key: hashed(f"{key}-{index}") for key in
                    ("folio", "bio", "descriptor", "credential")}
        identity.update(slot=index, generation=1, route_epoch=1)
        full, compressed = ("ab" * 4096, "c1" * 3568)
        success = outcome != "claimed_error"
        typed = outcome == "typed_success"
        events = []
        for step in prefix + tail:
            sequence += 1
            events.append(dict(step=step, sequence=sequence, identity=copy.deepcopy(identity)))
        page = dict(identity=identity, scope=copy.deepcopy(scope), outcome=outcome,
                    codec=1 if index != 1 else 2, version=1, dictionary=False,
                    original_page=full, original_compressed=compressed,
                    lower_payload=compressed if typed else None,
                    read_payload=compressed if typed else None,
                    gc_payload=compressed if typed else None,
                    pagein=full if success else None, events=events,
                    lower_complete=success, lower_durable=success,
                    map_published=success, upper_success=success)
        page.update(zip(("enqueue_count", "claim_count", "recompress_count", "ack_count"),
                        counts))
        pages.append(page)
    metrics = dict(cpu_ns=100, peak_ram_bytes=4096, physical_write_bytes=8192,
                   logical_bytes=8192, handoffs=0, ordinary_encodes=2,
                   capacity_bytes=4096 * 128, gc_bytes=4096)
    integrated = dict(metrics, handoffs=1, ordinary_encodes=1)
    record = dict(schema="swapz-r092-integrated-model-v1",
                  mode="integrated_natural_pressure", proof_kind="fabricated_model_only",
                  scope=copy.deepcopy(scope), guards=dict.fromkeys(MODEL.GUARDS, True),
                  preflight_kind="exact_private_reuse",
                  protected_before=copy.deepcopy(protected),
                  protected_after=copy.deepcopy(protected),
                  cleanup=dict.fromkeys(MODEL.CLEANUP, True), pages=pages,
                  baseline=dict(scope=copy.deepcopy(scope), handoff_enabled=False,
                                metrics=metrics),
                  integrated=dict(scope=copy.deepcopy(scope), handoff_enabled=True,
                                  metrics=integrated))
    return record, scope


class IntegratedEvidence(unittest.TestCase):
    def test_model_consistent_and_never_admitted(self):
        record, scope = fixture()
        result = MODEL.validate_model(record, scope)
        self.assertEqual(result["status"], "MODEL_CONSISTENT")
        self.assertEqual(result["outcomes"], dict.fromkeys(
            ("typed_success", "preclaim_decline", "claimed_error"), 1))
        self.assertFalse(result["actual_physical_io"])
        self.assertFalse(result["source_mapped_authenticated"])
        self.assertFalse(MODEL.live_admission(scope, record)["admitted"])
        record["preflight_kind"] = "one_narrow_fast_test"
        self.assertEqual(MODEL.validate_model(record, scope)["pages"], 3)
        self.assertFalse(MODEL.live_admission()["admitted"])

    def test_adversarial_trace_mutations(self):
        cases = [
            ("mode", ("mode",), "ordinary_zswap_off"),
            ("untrusted_physical_claim", ("proof_kind",), "actual_physical"),
            ("wrong_scope", ("scope", "device"), hashed("wrong")),
            ("wrong_scope", ("scope", "module"), hashed("wrong")),
            ("scope_digest", ("scope", "kernel"), None),
            ("mixed_page_scope", ("pages", 0, "scope", "source"), hashed("wrong", 40)),
            ("guard_refused", ("guards", "owner_scope"), False),
            ("guard_refused", ("guards", "exclusive_after_swapoff"), 1),
            ("preflight_kind", ("preflight_kind",), "manual_duplicate"),
            ("protected_identity", ("protected_after", "header"), hashed("wrong")),
            ("protected_identity", ("protected_after", "swap_uuid"), hashed("wrong")),
            ("protected_identity", ("protected_after", "partition_table"), hashed("wrong")),
            ("cleanup_required", ("cleanup", "journal_complete"), False),
            ("cleanup_required", ("cleanup", "no_force"), False),
            ("original_profile", ("pages", 0, "codec"), 90),
            ("original_profile", ("pages", 0, "dictionary"), True),
            ("payload_shape", ("pages", 0, "original_compressed"), "ab" * 3569),
            ("compressed_bytes", ("pages", 0, "lower_payload"), "aa" * 3568),
            ("compressed_bytes", ("pages", 0, "gc_payload"), "aa" * 3568),
            ("page_oracle", ("pages", 0, "pagein"), "aa" * 4096),
            ("durable_publication", ("pages", 0, "lower_durable"), False),
            ("ownership_counts", ("pages", 0, "ack_count"), 2),
            ("ownership_counts", ("pages", 0, "enqueue_count"), 2),
            ("ownership_counts", ("pages", 0, "recompress_count"), 1),
            ("event_order_or_identity", ("pages", 0, "events", 6, "step"), "upper_ack"),
            ("event_sequence", ("pages", 0, "events", 6, "sequence"), 1),
            ("event_order_or_identity", ("pages", 0, "events", 6, "identity", "bio"),
             hashed("wrong")),
            ("decline_typed_payload", ("pages", 1, "lower_payload"), "aa"),
            ("failed_claim_publication", ("pages", 2, "map_published"), True),
            ("ownership_counts", ("pages", 2, "recompress_count"), 1),
            ("arm_scope", ("baseline", "handoff_enabled"), True),
            ("metric_attribution", ("integrated", "metrics", "handoffs"), 2),
            ("metric_value", ("baseline", "metrics", "cpu_ns"), True),
        ]
        for category, path, replacement in cases:
            with self.subTest(path=path):
                record, scope = fixture()
                target = record
                for key in path[:-1]:
                    target = target[key]
                target[path[-1]] = replacement
                with self.assertRaisesRegex(MODEL.InvalidEvidence, "^" + category + "$"):
                    MODEL.validate_model(record, scope)
                self.assertFalse(MODEL.live_admission(scope, record)["admitted"])
        print("R092_MODEL_FIELD_NEGATIVES=" + str(len(cases)))

    def test_missing_duplicate_and_malformed(self):
        for category, modify in (
            ("record_fields", lambda r: r.pop("scope")),
            ("page_fields", lambda r: r["pages"][0].pop("identity")),
            ("duplicate_identity", lambda r: r["pages"][1]["identity"].update(
                bio=r["pages"][0]["identity"]["bio"])),
            ("event_count", lambda r: r["pages"][0]["events"].pop()),
            ("page_count", lambda r: r.update(pages=r["pages"] * 44)),
        ):
            with self.subTest(category=category):
                record, scope = fixture()
                modify(record)
                with self.assertRaisesRegex(MODEL.InvalidEvidence, "^" + category + "$"):
                    MODEL.validate_model(record, scope)
        print("R092_MODEL_STRUCTURE_NEGATIVES=5")


if __name__ == "__main__":
    unittest.main()
