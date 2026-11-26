#!/usr/bin/env python3
"""Extract exact frozen event constructors; no MM/DM postimage or execution claim."""
import hashlib
from pathlib import Path
import re
import subprocess
import sys

freeze = "5a36cabf0989dfffc75de52a6ab8cc021092ebf6"
out = Path(sys.argv[1])


def frozen(path, expected):
    raw = subprocess.check_output(["git", "show", freeze + ":" + path])
    actual = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
    if actual != expected:
        raise ValueError("frozen blob mismatch: " + path)
    print(path, actual)
    return raw.decode()


patch = frozen("tests/tools/round097-original-mm-producer.patch",
               "c35b35c18cc11f9b86c0b65856dbc0cd2a0bd2c8")
dm = frozen("src/kernel/dm-target.c", "f1922cc26caf7bfa097c1f561f8719744c3a4e75")
support = frozen("tests/runtime/native/fixtures/native-observation-owner-host.c",
                 "0ad7332910fed9e385171c20f3250014c411a4b8")
# Only the new hunk's added code; do not apply, edit or simulate entire MM.
added = "\n".join(line[1:] for line in patch.splitlines()
                  if line.startswith("+") and not line.startswith("+++"))
begin = "static void swapz_mm_observation_capture("
end = "\n#endif"
assert added.count(begin) == 1
mm = added[added.index(begin):].split(end, 1)[0] + "\n"
assert all(mm.count(name + "(") == 1 for name in (
    "swapz_mm_observation_capture", "swapz_mm_observation_bind",
    "swapz_mm_observation_endio", "swapz_mm_observation_release"))
assert mm.count("swapz_trial_observation_append(") == 6
match = re.search(r"^static void swapz_round097_observe_missing_lineage\(void\)\n\{\n"
                  r"[^}]+\n\}", dm, re.M)
assert match and match.group().count("swapz_trial_observation_append(NULL)") == 1
assert support.count("static void disabled(void)") == 1
# Frozen R097 host primitive and scope initialization support ONLY; no old tests.
pieces = {
    "frozen-mm-events.inc": mm,
    "frozen-dm-missing.inc": match.group() + "\n",
    "frozen-owner-support.inc": support.split("static void disabled(void)", 1)[0],
}
for name, content in pieces.items():
    (out / name).write_text(content, encoding="utf-8")
    print(name, len(content.encode()), hashlib.sha256(content.encode()).hexdigest())
