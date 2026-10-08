#!/usr/bin/env bash
# Rootless Bash coprocess integration. Only owned test sleep/exit workers.
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
BRIDGE="$ROOT/tests/runtime/recall-control-bridge.py"
TMP=$(mktemp -d)
trap 'rm -rf -- "$TMP"' EXIT

check_reply() {
  python3 - "$1" "$2" <<'PY'
import json,re,sys
d=json.loads(sys.argv[1])
assert d["status"]==sys.argv[2],d
assert type(d["cleanup_allowed"]) is bool and d["preserve_backing"] is not d["cleanup_allowed"],d
assert "pid" not in d and "argv" not in d,d
if "handle" in d:
    assert re.fullmatch(r"[A-Za-z0-9_-]{1,128}",d["handle"]) and not d["handle"].isdecimal(),d
PY
}

success() (
  coproc BR { python3 -B "$BRIDGE" 2>"$TMP/success.log"; }
  local bridge_pid=$BR_PID r writer a b pair id handle rc=0
  IFS= read -r -t 10 r <&"${BR[0]}"; check_reply "$r" bridge_ready
  printf '%s\n' '{"id":1,"op":"LAUNCH_TEST","command":"sleep","duration_ms":150}' >&"${BR[1]}"
  IFS= read -r -t 10 r <&"${BR[0]}"; check_reply "$r" ready
  writer=$(python3 -c 'import json,sys;print(json.loads(sys.argv[1])["handle"])' "$r")
  printf '%s\n' '{"id":2,"op":"LAUNCH_TEST","command":"sleep","duration_ms":150}' >&"${BR[1]}"
  IFS= read -r -t 10 r <&"${BR[0]}"; check_reply "$r" ready
  a=$(python3 -c 'import json,sys;print(json.loads(sys.argv[1])["handle"])' "$r")
  printf '%s\n' '{"id":3,"op":"LAUNCH_TEST","command":"sleep","duration_ms":150}' >&"${BR[1]}"
  IFS= read -r -t 10 r <&"${BR[0]}"; check_reply "$r" ready
  b=$(python3 -c 'import json,sys;print(json.loads(sys.argv[1])["handle"])' "$r")
  [[ "$writer" != "$a" && "$writer" != "$b" && "$a" != "$b" ]]
  # Both reader-equivalent test workers launched before either wait.
  for pair in "4:$a" "5:$b" "6:$writer"; do
    id=${pair%%:*}; handle=${pair#*:}
    printf '{"id":%s,"op":"WAIT","handle":"%s","timeout_ms":4000}\n' "$id" "$handle" >&"${BR[1]}"
    IFS= read -r -t 10 r <&"${BR[0]}"; check_reply "$r" reaped
  done
  printf '%s\n' '{"id":7,"op":"STOP_ALL"}' >&"${BR[1]}"
  IFS= read -r -t 10 r <&"${BR[0]}"; check_reply "$r" stopped
  [[ "$r" == *"\"$writer\""* && "$r" == *"\"$a\""* && "$r" == *"\"$b\""* ]]
  printf '%s\n' '{"id":8,"op":"SHUTDOWN"}' >&"${BR[1]}"
  IFS= read -r -t 10 r <&"${BR[0]}"; check_reply "$r" shutdown_verified
  touch "$TMP/clean-me"
  printf '%s\n' '{"id":9,"op":"FINALIZE"}' >&"${BR[1]}"
  IFS= read -r -t 10 r <&"${BR[0]}"; check_reply "$r" cleanup_authorized
  [[ "$r" == *'"cleanup_allowed":true'* ]]
  rm -- "$TMP/clean-me"
  wait "$bridge_pid" || rc=$?
  [[ $rc -eq 0 && ! -e "$TMP/clean-me" ]]
)

failed_worker_preserves() (
  coproc BR { python3 -B "$BRIDGE" 2>"$TMP/failed.log"; }
  local bridge_pid=$BR_PID r handle rc=0
  IFS= read -r -t 10 r <&"${BR[0]}"; check_reply "$r" bridge_ready
  touch "$TMP/preserved-backing"
  printf '%s\n' '{"id":1,"op":"LAUNCH_TEST","command":"exit","code":7}' >&"${BR[1]}"
  IFS= read -r -t 10 r <&"${BR[0]}"; check_reply "$r" ready
  handle=$(python3 -c 'import json,sys;print(json.loads(sys.argv[1])["handle"])' "$r")
  printf '{"id":2,"op":"WAIT","handle":"%s","timeout_ms":3000}\n' "$handle" >&"${BR[1]}"
  IFS= read -r -t 10 r <&"${BR[0]}"; check_reply "$r" preserve_backing
  wait "$bridge_pid" || rc=$?
  [[ $rc -ne 0 && -f "$TMP/preserved-backing" ]]
  grep -q BRIDGE_PRESERVE "$TMP/failed.log"
)

controller_disconnect_preserves() (
  coproc BR { python3 -B "$BRIDGE" 2>"$TMP/eof.log"; }
  local bridge_pid=$BR_PID r rc=0 fd
  IFS= read -r -t 10 r <&"${BR[0]}"; check_reply "$r" bridge_ready
  touch "$TMP/diagnostics"
  printf '%s\n' '{"id":1,"op":"LAUNCH_TEST","command":"sleep","duration_ms":100}' >&"${BR[1]}"
  IFS= read -r -t 10 r <&"${BR[0]}"; check_reply "$r" ready
  fd=${BR[1]}
  exec {fd}>&-
  wait "$bridge_pid" || rc=$?
  [[ $rc -ne 0 && -f "$TMP/diagnostics" ]]
  grep -q BRIDGE_PRESERVE "$TMP/eof.log"
)

timeout 60s python3 -B "$ROOT/tests/runtime/recall-control-bridge-test.py" -v
# Bash rejects truncated or contradictory bridge replies, rather than
# treating absent/ambiguous cleanup permission as success.
if check_reply '{"status":' stopped >/dev/null 2>&1; then
  echo 'ERROR: accepted truncated bridge response' >&2
  exit 1
fi
if check_reply '{"status":"stopped","cleanup_allowed":true,"preserve_backing":true}' stopped >/dev/null 2>&1; then
  echo 'ERROR: accepted contradictory bridge cleanup verdict' >&2
  exit 1
fi
echo "BRIDGE_BASH_MALFORMED_RESPONSE_REJECTED: PASS"
success
echo "BRIDGE_BASH_PERSISTENT_THREE_WORKERS: PASS"
failed_worker_preserves
echo "BRIDGE_BASH_FAILURE_PRESERVES_BACKING: PASS"
controller_disconnect_preserves
echo "BRIDGE_BASH_DISCONNECT_PRESERVES_BACKING: PASS"
echo "BRIDGE_BASH_ROOTLESS_GATE: PASS"
