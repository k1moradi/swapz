#!/usr/bin/env bash
# Private root preflight for make test loaded qualification.
# It may remove only an idle pre-existing dm_swapz module, never a mapping.
set -Eeuo pipefail

fail() { printf 'BLOCKED: %s\n' "$*" >&2; exit 1; }
note() { printf '%s\n' "$*"; }

command -v rmmod >/dev/null || fail "missing required tool rmmod"
[[ $(id -u) == 0 ]] || fail "root required for loaded preflight"

if [[ ! -d /sys/module/dm_swapz ]]; then
    note "LOADED_PREFLIGHT_DM_SWAPZ=absent"
    exit 0
fi

[[ -r /sys/module/dm_swapz/refcnt ]] ||
    fail "pre-existing dm_swapz reference count is unreadable"
refcount="$(cat /sys/module/dm_swapz/refcnt)" ||
    fail "cannot read pre-existing dm_swapz reference count"
[[ $refcount =~ ^(0|[1-9][0-9]*)$ ]] ||
    fail "pre-existing dm_swapz reference count is malformed"
(( refcount == 0 )) ||
    fail "pre-existing dm_swapz module is busy; no cleanup attempted"

# This is deliberately ordinary removal. A concurrent new user makes rmmod
# fail, preserving the no-force safety boundary.
rmmod dm_swapz ||
    fail "idle pre-existing dm_swapz could not be removed normally"
[[ ! -d /sys/module/dm_swapz ]] ||
    fail "dm_swapz still present after ordinary removal"
note "AUTO_REMOVED_IDLE_DM_SWAPZ=1"
