#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
SRC="$ROOT/kernel/dm-swapz.c"

fail() {
  echo "V2.2 source invariant failure: $*" >&2
  exit 1
}

grep -q 'alloc_ordered_workqueue' "$SRC" ||
  fail "state-machine workqueue is not explicitly ordered"
if grep -q 'alloc_workqueue' "$SRC"; then
  fail "generic alloc_workqueue remains in V2.2 state-machine path"
fi
if grep -q 'WQ_UNBOUND' "$SRC"; then
  fail "WQ_UNBOUND remains; V2.2 requires explicit global serialization"
fi

grep -q 'try_wait_for_completion' "$SRC" ||
  fail "nonblocking stream reap does not consume the completion token"
grep -q 'wait_for_completion_timeout' "$SRC" ||
  fail "blocking stream reap is not bounded by the async watchdog"
grep -q 'SWAPZ_ASYNC_WATCHDOG_MS' "$SRC" ||
  fail "async stream watchdog constant missing"
if grep -Eq '\bio_done\b' "$SRC"; then
  fail "parallel io_done completion state remains"
fi
if grep -Eq '\bcompletion_work\b' "$SRC"; then
  fail "obsolete completion_work indirection remains"
fi

grep -q 'atomic_t async_callbacks' "$SRC" ||
  fail "async dm-io callback lifetime counter missing"
grep -q 'swapz_wait_async_callbacks' "$SRC" ||
  fail "teardown callback barrier missing"
grep -q 'wait_event(context->async_callback_wait' "$SRC" ||
  fail "teardown does not wait for callback references"

grep -q 'swapz_fail_unsent_upper_bios' "$SRC" ||
  fail "failure path does not explicitly drain unsent upper BIO ownership"
grep -q 'swapz_complete_buffer_bios' "$SRC" ||
  fail "buffer BIO failure completion helper missing"

grep -q 'swapz_commit_previous_generation' "$SRC" ||
  fail "same-slot rewrite does not preserve an uncommitted prior generation"

python3 - "$SRC" <<'PY'
from pathlib import Path
import re
import sys

src = Path(sys.argv[1]).read_text()

install = re.search(
    r"static void swapz_install_mapping\(.*?\n\}",
    src,
    flags=re.S,
)
if not install:
    raise SystemExit("V2.2 source invariant failure: swapz_install_mapping not found")
body = install.group(0)
failed = body.find("if (unlikely(context->failed))")
unaccount = body.find("swapz_unaccount_mapping(context, mapping)")
if failed < 0 or unaccount < 0 or failed > unaccount:
    raise SystemExit(
        "V2.2 source invariant failure: old mapping can be unaccounted before failed-state guard"
    )

process_write = re.search(
    r"static int swapz_process_write\(.*?\n\}",
    src,
    flags=re.S,
)
if not process_write:
    raise SystemExit("V2.2 source invariant failure: swapz_process_write not found")
body = process_write.group(0)
commit = body.find("swapz_commit_previous_generation(context, logical_page)")
advance = body.find("previous_generation = context->generations[logical_page]")
if commit < 0 or advance < 0 or commit > advance:
    raise SystemExit(
        "V2.2 source invariant failure: same-slot generation advances before prior commit gate"
    )
PY

grep -Eq 'REQ_OP_WRITE[[:space:]]*\|[[:space:]]*REQ_SWAP' "$SRC" ||
  fail "lower stream writes do not preserve swap priority"
grep -Eq 'operation[[:space:]]*\|[[:space:]]*REQ_SWAP' "$SRC" ||
  fail "lower synchronous reads do not preserve swap priority"
grep -q 'target->bio->bi_opf & REQ_FUA' "$SRC" ||
  fail "staged early completion is not guarded against REQ_FUA"

for field in fill_id inflight_id pack_records async_cb buf0_state buf1_state; do
  grep -q "$field=" "$SRC" ||
    fail "diagnostic status field $field missing"
done

echo "V2.2 async/source invariants: PASS"
