#!/usr/bin/env python3
"""Exact frozen current terminal producer shape and narrow bridge mutants."""
from pathlib import Path
import re
import subprocess
import sys

freeze = "f600b79e0e1a812cae4c1c0ae8ab9f68c3d34da3"
controller_path = "src/kernel/native-observation-controller.c"
name = freeze + ":" + controller_path
assert subprocess.check_output(["git", "rev-parse", name], text=True).strip() == "0ea943f55449cacae473c182f33e75c48eb371bb"
controller = subprocess.check_output(["git", "show", name], text=True)
start = controller.index("int swapz_trial_controller_finish(")
end = controller.index("EXPORT_SYMBOL_GPL(swapz_trial_controller_finish)", start)
finish = controller[start:end]
cleanup = re.search(r"cleanup = \(struct swapz_observation_record\)\{([^}]+)\};", finish)
assert cleanup is not None
assert set(re.findall(r"\.(\w+)\s*=", cleanup[1])) == {
    "event", "flags", "caps", "tickets", "pins", "reservations", "bios", "maps", "quarantines"}
assert finish.index("!terminal->quarantines") < cleanup.start()
assert cleanup.end() < finish.index("swapz_trial_observation_append_sequence(&cleanup)") < finish.index("swapz_trial_byte_event(&cleanup, sequence, NULL, 0)") < finish.index("swapz_trial_observation_stop(")
print("R108_FROZEN_CURRENT_CONTROLLER_SHAPE_PASS (source only)")
source = Path("src/kernel/native-observation-byte-bridge.c").read_text()
root = Path(sys.argv[1])
for mode, old, new in [
    ("pending_finish", "state->input[index].token || state->input[index].committed", "state->input[index].committed"),
    ("unrepresented", "state->input[index].token || state->input[index].committed", "state->input[index].token"),
    ("late_finish_internal", "if (state->cleaned) {\n\t\tlose(state);\n\t\tgoto out;\n\t}", "if (false) {\n\t\tlose(state);\n\t\tgoto out;\n\t}"),
    ("quarantine_debt", "record->maps || record->quarantines)", "record->maps)"),
    ("close_pending", "!state->bound || !state->cleaned || !terminal_ready(state)", "!state->bound || !state->cleaned"),
]:
    assert source.count(old) == 1, mode
    dest = root / mode
    dest.mkdir()
    (dest / "native-observation-byte-bridge.c").write_text(source.replace(old, new))
