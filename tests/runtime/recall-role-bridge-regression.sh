#!/usr/bin/env bash
# Genuine Bash coprocess lifecycle for synthetic-only five-role controller.
# All direct work in this fixture is simulated on temporary regular files.
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
FIXTURE="$ROOT/tests/runtime/recall-role-bridge-fixture.py"
TMP=$(mktemp -d)
trap 'rm -rf -- "$TMP"' EXIT

check_reply() {
  python3 - "$1" "$2" <<'PY'
import json, re, sys
reply = json.loads(sys.argv[1])
assert reply["status"] == sys.argv[2], reply
assert type(reply["cleanup_allowed"]) is bool, reply
assert reply["preserve_backing"] is not reply["cleanup_allowed"], reply
assert "pid" not in reply and "argv" not in reply, reply
if "handle" in reply:
    handle = reply["handle"]
    assert isinstance(handle, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", handle), reply
    assert not handle.isdecimal(), reply
PY
}

handle_from() {
  python3 -c 'import json,sys; print(json.loads(sys.argv[1])["handle"])' "$1"
}

rootless_role_success() (
  coproc ROLE { python3 -B "$FIXTURE" 2>"$TMP/role-success.log"; }
  local role_pid=$ROLE_PID response handle id rc=0
  local -a handles=()
  IFS= read -r -t 10 response <&"${ROLE[0]}"
  check_reply "$response" rootless_role_bridge_ready
  id=0
  for role in writer a b a2 b2; do
    id=$((id + 1))
    printf '{"id":%s,"op":"LAUNCH_ROLE","role":"%s"}\n' "$id" "$role" >&"${ROLE[1]}"
    IFS= read -r -t 10 response <&"${ROLE[0]}"
    check_reply "$response" ready
    handle=$(handle_from "$response")
    handles+=("$handle")
  done
  [[ ${#handles[@]} -eq 5 ]]
  [[ "${handles[3]}" != "${handles[4]}" ]]
  # Both A/B concurrent-phase roles were admitted before either WAIT.
  for handle in "${handles[@]}"; do
    id=$((id + 1))
    printf '{"id":%s,"op":"WAIT","handle":"%s","timeout_ms":2000}\n' "$id" "$handle" >&"${ROLE[1]}"
    IFS= read -r -t 10 response <&"${ROLE[0]}"
    check_reply "$response" reaped
  done
  id=$((id + 1))
  printf '{"id":%s,"op":"STOP_ALL"}\n' "$id" >&"${ROLE[1]}"
  IFS= read -r -t 10 response <&"${ROLE[0]}"
  check_reply "$response" stopped
  [[ "$response" == *'"cleanup_allowed":false'* ]]
  id=$((id + 1))
  printf '{"id":%s,"op":"SHUTDOWN"}\n' "$id" >&"${ROLE[1]}"
  IFS= read -r -t 10 response <&"${ROLE[0]}"
  check_reply "$response" shutdown_verified
  touch "$TMP/synthetic-backing"
  id=$((id + 1))
  printf '{"id":%s,"op":"FINALIZE"}\n' "$id" >&"${ROLE[1]}"
  IFS= read -r -t 10 response <&"${ROLE[0]}"
  check_reply "$response" cleanup_authorized
  [[ "$response" == *'"cleanup_allowed":true'* ]]
  rm -- "$TMP/synthetic-backing"
  wait "$role_pid" || rc=$?
  [[ $rc -eq 0 && ! -e "$TMP/synthetic-backing" ]]
)

rootless_role_failure_preserves() (
  coproc ROLE { python3 -B "$FIXTURE" 2>"$TMP/role-failure.log"; }
  local role_pid=$ROLE_PID response rc=0
  IFS= read -r -t 10 response <&"${ROLE[0]}"
  check_reply "$response" rootless_role_bridge_ready
  touch "$TMP/preserve-on-failure"
  printf '%s\n' '{"id":1,"op":"LAUNCH_ROLE","role":"a"}' >&"${ROLE[1]}"
  IFS= read -r -t 10 response <&"${ROLE[0]}"
  check_reply "$response" preserve_backing
  wait "$role_pid" || rc=$?
  [[ $rc -ne 0 && -f "$TMP/preserve-on-failure" ]]
  grep -q ROOTLESS_ROLE_PRESERVE "$TMP/role-failure.log"
)

rootless_role_disconnect_preserves() (
  coproc ROLE { python3 -B "$FIXTURE" 2>"$TMP/role-disconnect.log"; }
  local role_pid=$ROLE_PID response rc=0 fd
  IFS= read -r -t 10 response <&"${ROLE[0]}"
  check_reply "$response" rootless_role_bridge_ready
  touch "$TMP/preserve-on-disconnect"
  printf '%s\n' '{"id":1,"op":"LAUNCH_ROLE","role":"writer"}' >&"${ROLE[1]}"
  IFS= read -r -t 10 response <&"${ROLE[0]}"
  check_reply "$response" ready
  fd=${ROLE[1]}
  exec {fd}>&-
  wait "$role_pid" || rc=$?
  [[ $rc -ne 0 && -f "$TMP/preserve-on-disconnect" ]]
  grep -q ROOTLESS_ROLE_PRESERVE "$TMP/role-disconnect.log"
)

rootless_role_success
echo "ROLE_BRIDGE_BASH_FIVE_ROLES: PASS"
rootless_role_failure_preserves
echo "ROLE_BRIDGE_BASH_ROLE_FAILURE_PRESERVES: PASS"
rootless_role_disconnect_preserves
echo "ROLE_BRIDGE_BASH_DISCONNECT_PRESERVES: PASS"
