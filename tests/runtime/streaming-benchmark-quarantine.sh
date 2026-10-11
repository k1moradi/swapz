#!/usr/bin/env bash
# Sourced by streaming-benchmark.sh. Rootless unit tests source this helper
# with harmless mocked commands. NO implicit device/module operations here.

swapz_benchmark_bounded() {
  # Any nonzero result, including GNU timeout's 124/137, means kernel-side
  # completion is not independently attested. Preserve the owned stack.
  local stage=$1 seconds=$2
  shift 2
  local rc=0
  timeout --signal=TERM --kill-after=2s "$seconds" "$@" || rc=$?
  if (( rc != 0 )); then
    BENCH_QUARANTINE=1
    BENCH_QUARANTINE_REASON="$stage returned $rc (completion/ownership uncertain)"
    echo "ERROR: $BENCH_QUARANTINE_REASON; preserving test resources." >&2
    return "$rc"
  fi
}

swapz_benchmark_verify_owned_target() {
  # A name match is NOT sufficient authority to remove a DM mapping.
  # The UUID assigned at creation must still be attached to this exact name.
  # An error, empty value or mismatch is always uncertain: preserve backing.
  local observed rc=0
  observed=$(timeout --signal=TERM --kill-after=2s 8s dmsetup info \
      --columns --noheadings -o uuid "$TARGET") || rc=$?
  if (( rc != 0 )); then
    BENCH_QUARANTINE=1
    BENCH_QUARANTINE_REASON="cannot verify benchmark target UUID (rc=$rc)"
    return 1
  fi
  observed=$(printf '%s' "$observed" | tr -d '[:space:]')
  if [[ -z "${TARGET_UUID:-}" || "$observed" != "$TARGET_UUID" ]]; then
    BENCH_QUARANTINE=1
    BENCH_QUARANTINE_REASON="owned DM UUID mismatch; target name cannot authorize removal"
    return 1
  fi
  return 0
}
swapz_benchmark_target_exists() {
  # 0=positively present, 1=positively absent, 2=uncertain/error.
  # Only a successful COMPLETE inventory can establish absence, unlike
  # a single-device dmsetup info request with ambiguous nonzero statuses.
  local names rc=0 name
  names=$(timeout --signal=TERM --kill-after=2s 8s dmsetup info \
      --columns --noheadings -o name) || rc=$?
  if (( rc != 0 )); then
    BENCH_QUARANTINE=1
    BENCH_QUARANTINE_REASON="cannot conclusively enumerate Device Mapper targets (rc=$rc)"
    return 2
  fi
  while IFS= read -r name; do
    name=$(printf '%s' "$name" | tr -d '[:space:]')
    if [[ "$name" == "$TARGET" ]]; then
      return 0
    fi
  done <<<"$names"
  return 1
}

swapz_benchmark_record_quarantine() {
  # Evidence is written exclusively to the runner's generated directory.
  # This is a runner statement, not independent device attestation.
  local reason=$1 result=$2
  [[ -n "$TMP" && -d "$TMP" ]] || {
    echo "ERROR: quarantine directory absent; preserve host state" >&2
    return 1
  }
  python3 -B - "$TMP" "$reason" "$result" \
      "$TARGET" "$BACKING" "$NULL_CFG" \
      "$TARGET_ACTIVE" "$TARGET_CANDIDATE" "$IO_STARTED" <<'PY'
import json
import os
import stat
import sys
directory, reason, status, target, backing, config, active, candidate, io = sys.argv[1:]
dirfd = os.open(directory, os.O_RDONLY | os.O_NOFOLLOW |
                os.O_DIRECTORY | os.O_CLOEXEC)
try:
    owned = os.fstat(dirfd)
    if not stat.S_ISDIR(owned.st_mode) or owned.st_uid != os.geteuid():
        raise ValueError("quarantine directory ownership differs")
    record = {
        "schema": "swapz-v22-benchmark-quarantine-v1",
        "state": "QUARANTINED_NO_AUTOMATIC_CLEANUP",
        "reason": reason[:500],
        "exit_status": int(status),
        "target_name_source_reported": target,
        "backing_name_source_reported": backing,
        "null_config_source_reported": config,
        "target_active_source_reported": active == "1",
        "target_create_candidate_source_reported": candidate == "1",
        "live_io_started_source_reported": io == "1",
        "independent_device_attestation": False,
        "instruction": (
            "STOP. Preserve existing target/backing and diagnostics. "
            "No force removal, swap manipulation, reboot, or further "
            "benchmark case; operator must separately inspect ownership."
        ),
    }
    payload = (json.dumps(record, sort_keys=True) + "\n").encode("utf-8")
    fd = os.open("QUARANTINED.json", os.O_WRONLY | os.O_CREAT |
                 os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600,
                 dir_fd=dirfd)
    try:
        with os.fdopen(fd, "wb", closefd=False) as output:
            output.write(payload)
            output.flush()
            os.fsync(fd)
    finally:
        os.close(fd)
finally:
    os.close(dirfd)
PY
}
