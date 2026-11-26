#!/usr/bin/env python3
"""Current-source scope gate for the unchanged v2 observation wire.

Expected source is an independent exact build manifest input, not the old
header lineage or an assertion extracted from the capture. No authentication,
runtime admission, or device access. Legacy CLI/parser is unchanged.
"""
import importlib.util
import json
from pathlib import Path
import re
import struct
import sys

_spec = importlib.util.spec_from_file_location(
    "swapz_legacy_observation", Path(__file__).with_name("native-observation-export.py"))
legacy = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(legacy)


def validate_current(raw, scope, expected_source):
    legacy.require(type(expected_source) is str and
                   re.fullmatch("[0-9a-f]{40}", expected_source) is not None and
                   expected_source not in ("0" * 40, legacy.MAPPING_SOURCE),
                   "expected_build_source")
    legacy.check_scope(scope)
    legacy.require(scope["source"] == expected_source, "stale_build_source")
    return legacy.validate(raw, scope)


def main():
    try:
        legacy.require(len(sys.argv) == 3 and len(sys.argv[2]) <= 4096,
                       "current_scope_argument")
        scope = json.loads(sys.argv[2], object_pairs_hook=legacy.unique_object)
        raw = sys.stdin.buffer.read(legacy.MAX_BYTES + 1)
        result = validate_current(raw, scope, sys.argv[1])
    except legacy.Invalid as error:
        result = dict(status="BLOCKED", reason=str(error),
                      event_id=getattr(error, "event_id", None), **legacy.GATES)
    except (ValueError, TypeError, KeyError, RecursionError, OSError, struct.error):
        result = dict(status="BLOCKED", reason="invalid_input", **legacy.GATES)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "CONSISTENT_RECORDER_OBSERVATIONS_ONLY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
