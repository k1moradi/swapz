#!/usr/bin/env python3
"""Extract actual frozen producer emitters and designated-initializer shapes.

Only the values are supplied by a host fixture. No peer source or modeled
success replaces an actual recorder/bridge call. This is not native MM/DM I/O.
"""
import re
import subprocess
import sys
from pathlib import Path

FREEZE = "8a83828717ea3000d102043ead78fd86ad0391a8"


def frozen(path, blob):
    name = FREEZE + ":" + path
    assert subprocess.check_output(["git", "rev-parse", name], text=True).strip() == blob
    return subprocess.check_output(["git", "show", name], text=True)


def function(text, signature):
    start = text.index(signature)
    body = text.index("{", start)
    depth = 1
    end = body + 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


def added(patch):
    return "\n".join(line[1:] for line in patch.splitlines()
                     if line.startswith("+") and not line.startswith("+++"))


dm = frozen("src/kernel/dm-target.c", "d3cb8525f482321c975cefd91a03aa73fcb7bef2")
mm = added(frozen("tests/tools/round104-original-mm-core-witness.patch",
                  "132c03fcefe961696f468a41c763666f1dc4f90c"))
old_mm = added(frozen("tests/tools/round098-original-mm-scope-events.patch",
                      "3832b6aa76b783f3790b869cf40512b114d66cd6"))
controller = frozen("src/kernel/native-observation-controller.c",
                    "06cf0279cc449330e35873829aab1118a2bee151")
correlation = added(frozen("tests/tools/round105-original-mm-terminal-correlation.patch",
                          "ff20785a8b12780d94778b49aeaf0526ebfa1b80"))
assert "if (ticket && record.operation)" in correlation
assert "slot && slot->observed && slot->operation && slot->original" in correlation
emitters = [
    function(dm, "static u32 swapz_scope_status("),
    function(dm, "static bool swapz_scope_observation_live("),
    function(dm, "static void swapz_scope_observe_invalid(void)"),
    function(dm, "static void swapz_scope_observe_event("),
    function(mm, "static inline bool swapz_mm_observation_emit("),
    *[function(dm, "static void swapz_scope_observe_" + name + "(")
      for name in ("accept", "simple", "credit", "clone", "release")],
    function(dm, "static __maybe_unused int swapz_round090_storage_write("),
    function(dm, "static __maybe_unused int swapz_round090_storage_read("),
    function(dm, "static __maybe_unused int swapz_round090_storage_flush("),
    function(dm, "static int swapz_lower_write("),
    function(dm, "static bool swapz_scope_transaction("),
    function(controller, "static bool swapz_controller_recorder_join("),
    function(controller, "int swapz_trial_controller_finish("),
]
shapes = []
for source, event, selector, extra in [
    (dm, "ACCEPT", "SWAPZ_OBS_TYPED_WRITE", ()),
    (dm, "ACCEPT", "SWAPZ_OBS_TYPED_READ", ()),
    (dm, "ACCEPT", ".operation_kind = kind", ()),
    (dm, "PIN", None, ()),
    (dm, "PIN_RELEASE", None, ()),
    (dm, "ORACLE", None, ("page_sha256", "observed_sha256", "status")),
    (dm, "CLONE_ENDIO", None, ()),
    (dm, "QUARANTINE", None, ()),
    (dm, "DISCARD", None, ()),
    (mm, "UPPER_ENDIO", None, ()),
    (old_mm, "BIND", None, ()),
    (old_mm, "CARRIER_RELEASE", None, ()),
]:
    # Extract the actual designated fields; values at native producer sites
    # depend on folio/BIO/target objects unavailable in a rootless fixture.
    candidates = [body for body in re.findall(
        r"(?:record\s*=\s*(?:\(struct swapz_observation_record\))?\s*\{)([^{}]+)\};",
        source) if re.search(r"\.event\s*=\s*SWAPZ_OBS_" + event + r"\b", body) and
        (selector is None or selector in body)]
    assert len(candidates) == 1, (event, selector, len(candidates))
    body = candidates[0]
    fields = re.findall(r"\.(\w+)\s*=", body)
    assert len(fields) == len(set(fields))
    condition = "record->event == SWAPZ_OBS_" + event
    if selector and selector.startswith("SWAPZ_OBS_"):
        condition += " && record->operation_kind == " + selector
    elif selector:
        condition += " && (record->operation_kind == SWAPZ_OBS_ORDINARY_WRITE || record->operation_kind == SWAPZ_OBS_DISCARD_BIO)"
    shapes.append("if (" + condition + ") {\n"
                  "\tstruct swapz_observation_record projected = {\n" +
                  "".join("\t\t." + field + " = record->" + field + ",\n" for field in fields) +
                  "\t};\n" +
                  "".join("\tmemcpy(projected." + field + ", record->" + field + ", 32);\n"
                          if field.endswith("sha256") else
                          "\tprojected." + field + " = record->" + field + ";\n"
                          for field in extra) +
                  "\tassert(!memcmp(&projected, record, sizeof(projected)));\n"
                  "\treturn;\n}")
# Frozen R104 lacks a complete ordinary/fallback/error/CLEANUP producer
# transcript. Missing shapes are supplied only by the labeled synthetic
# fixture, never credited as native call sites.
header = "\n\n".join(emitters) + "\n\nstatic void frozen_shape(const struct swapz_observation_record *record)\n{\n" + "\n".join(shapes) + "\n}\n"
Path(sys.argv[1]).write_text(header)
print("R106 frozen producer functions=17 initializer_shapes=12")
