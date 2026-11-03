#!/usr/bin/env bash
# swapz package only: never load modules, create DM devices or activate swap.
set -Eeuo pipefail
umask 022

transaction_active=0
transaction_dir=""

staging_abort() {
  local rc="${1:-1}" reason="${2:-failure}"
  trap - ERR HUP INT TERM
  transaction_active=0
  echo "BLOCKED: package $reason before mutation; removing staging data" >&2
  [[ -z "$transaction_dir" ]] || rm -rf -- "$transaction_dir"
  exit "$rc"
}

blocked() {
  printf 'BLOCKED: %s\n' "$*" >&2
  if (( transaction_active == 1 )); then
    rollback 2 failure
  elif (( transaction_active == 2 )); then
    staging_abort 2 failure
  elif (( transaction_active == 3 )); then
    uninstall_rollback 2 failure
  fi
  exit 2
}

[[ $# == 2 && ( $1 == install || $1 == uninstall ) ]] ||
  blocked "usage install|uninstall ABSOLUTE_PREFIX"
action="$1"
prefix="$2"
[[ "$prefix" == /* && "$prefix" != / && "$prefix" != */ &&
   "$prefix" != *..* && "$prefix" != *//* && "$prefix" != *'|'* ]] ||
  blocked "invalid install prefix"

script_path="${BASH_SOURCE[0]}"
case "$script_path" in
  */*) script_dir="${script_path%/*}" ;;
  *) script_dir=. ;;
esac
root="$(CDPATH= cd -- "$script_dir/.." && pwd -P)"
cd "$root"
test_root="${SWAPZ_PACKAGE_TEST_ROOT:-}"
if [[ -z "$test_root" ]]; then
  PATH=/usr/sbin:/usr/bin:/sbin:/bin
  export PATH
fi
IFS= read -r version < src/kernel/VERSION || blocked "cannot read canonical VERSION"
grep -Fqx 'PACKAGE_VERSION="$(cat "$(dirname "${BASH_SOURCE[0]}")/src/kernel/VERSION")"' dkms.conf ||
  blocked "DKMS config no longer follows canonical VERSION"
[[ "$version" =~ ^3[.]0[.]0-alpha[.][0-9]+$ ]] &&
  grep -Fxq 'AUTOINSTALL="no"' dkms.conf ||
  blocked "unrecognized DKMS version/autoinstall state"

if [[ -n "$test_root" ]]; then
  [[ $(id -u) != 0 ]] || blocked "root test mode forbidden"
  sandbox="$(realpath -m -- "$test_root")"
  case "$sandbox" in "$root/build/tests/package-sandbox/"*) ;; *)
    blocked "test sandbox outside build/" ;;
  esac
  [[ "$prefix" == "$sandbox/usr/local" ]] || blocked "test prefix mismatch"
  srcbase="$sandbox/usr/src"
  modules_root="$sandbox/lib/modules"
  dkms_bin="$sandbox/bin/dkms"
  depmod_bin="$sandbox/bin/depmod"
  systemctl_bin="$sandbox/bin/systemctl"
  build_info="${SWAPZ_TEST_BUILD_INFO:-$root/build/source-build-info.h}"
  build_info="$(realpath -m -- "$build_info")"
  case "$build_info" in "$sandbox"/*) ;; *)
    blocked "test build metadata outside package sandbox" ;;
  esac
  cli_artifact="${SWAPZ_TEST_CLI_ARTIFACT:-}"
  oracle_artifact="${SWAPZ_TEST_ORACLE_ARTIFACT:-}"
  module_artifact="${SWAPZ_TEST_MODULE_ARTIFACT:-}"
  [[ -n "$cli_artifact" && -n "$oracle_artifact" && -n "$module_artifact" ]] ||
    blocked "test package artifacts were not supplied"
  cli_artifact="$(realpath -m -- "$cli_artifact")"
  oracle_artifact="$(realpath -m -- "$oracle_artifact")"
  module_artifact="$(realpath -m -- "$module_artifact")"
  for artifact in "$cli_artifact" "$oracle_artifact" "$module_artifact"; do
    case "$artifact" in "$sandbox"/*) ;; *)
      blocked "test artifact outside package sandbox" ;;
    esac
  done
  qualification_report="${SWAPZ_TEST_QUALIFICATION_REPORT:-}"
  [[ -n "$qualification_report" ]] || blocked "test qualification report was not supplied"
  qualification_report="$(realpath -m -- "$qualification_report")"
  case "$qualification_report" in "$sandbox"/*) ;; *)
    blocked "test qualification report outside package sandbox" ;;
  esac
  kernel_release="${SWAPZ_TEST_KERNEL_RELEASE:-test-kernel}"
  [[ "$kernel_release" =~ ^[A-Za-z0-9._+-]+$ ]] || blocked "invalid test kernel release"
  package_lock="$sandbox/package.lock"
  transaction_parent="$sandbox/transactions"
else
  [[ $(id -u) == 0 ]] || blocked "root required"
  [[ "$prefix" == /usr/local ]] || blocked "production prefix must be /usr/local"
  srcbase="/usr/src"
  modules_root="/lib/modules"
  build_info="$root/build/source-build-info.h"
  cli_artifact="$root/build/userspace/swapzctl"
  oracle_artifact="$root/build/tests/device-roundtrip"
  module_artifact="$root/build/kernel/experimental/dm-swapz.ko"
  qualification_report="$root/test_results.json"
  kernel_release="$(uname -r)"
  package_lock="/run/lock/swapz/package.lock"
  transaction_parent="/var/lib/swapz-package-transactions"
  dkms_bin="$(command -v dkms 2>/dev/null || true)"
  depmod_bin="$(command -v depmod 2>/dev/null || true)"
  systemctl_bin="$(command -v systemctl 2>/dev/null || true)"
  modules_root="$(readlink -f -- "$modules_root" 2>/dev/null || true)"
  srcbase="$(readlink -f -- "$srcbase" 2>/dev/null || true)"
  [[ -n "$modules_root" && -n "$srcbase" ]] ||
    blocked "cannot canonicalize system package roots"
fi

trusted_system_executable() {
  local path="$1" resolved uid mode
  [[ "$path" == /* ]] || return 1
  resolved="$(readlink -f -- "$path" 2>/dev/null || true)"
  case "$resolved" in /usr/bin/*|/usr/sbin/*|/bin/*|/sbin/*) ;; *) return 1 ;; esac
  [[ -f "$resolved" && -x "$resolved" && ! -L "$resolved" ]] || return 1
  IFS=: read -r uid mode < <(stat -c '%u:%a' -- "$resolved") || return 1
  [[ "$uid" == 0 ]] && (( (8#$mode & 8#022) == 0 ))
}

if [[ -n "$test_root" ]]; then
  [[ -x "$dkms_bin" && ! -L "$dkms_bin" ]] || blocked "no trusted DKMS executable"
  [[ -x "$depmod_bin" && ! -L "$depmod_bin" ]] || blocked "no trusted depmod executable"
  [[ -x "$systemctl_bin" && ! -L "$systemctl_bin" ]] ||
    blocked "no trusted systemctl executable"
else
  trusted_system_executable "$dkms_bin" || blocked "no trusted DKMS executable"
  trusted_system_executable "$depmod_bin" || blocked "no trusted depmod executable"
  trusted_system_executable "$systemctl_bin" ||
    blocked "no trusted systemctl executable"
fi
for required_command in python3 sha256sum stat install cp rm mkdir rmdir sed grep find realpath readlink flock modinfo systemd-escape awk cmp basename mktemp git uname mv; do
  command -v "$required_command" >/dev/null 2>&1 || blocked "$required_command unavailable"
done
if [[ -z "$test_root" ]]; then
  install -d -o 0 -g 0 -m0755 "$(dirname "$package_lock")"
fi
[[ ! -L "$package_lock" ]] || blocked "symlinked package lock"
exec 9>"$package_lock"
chmod 0600 "$package_lock" || blocked "cannot secure package lock"
flock -n 9 || blocked "another swapz package operation is active"

primary_recovery_base="/var/lib/swapz/physical-recovery"
primary_state="$primary_recovery_base/primary-state.json"
if [[ -n "$test_root" ]]; then
  primary_recovery_base="$sandbox/var/lib/swapz/physical-recovery"
  primary_state="$primary_recovery_base/primary-state.json"
fi

src="$srcbase/swapz-$version"
cli_dir="$prefix/sbin"
cli="$cli_dir/swapzctl"
boot_verifier="$cli_dir/swapz-primary-boot-verify"
helper_dir="$prefix/libexec/swapz"
helper="$helper_dir/device-roundtrip"
module_snapshot="$helper_dir/dm-swapz.ko"
unit_dir="$prefix/lib/systemd/system"
generator_dir="$prefix/lib/systemd/system-generators"
primary_generator="$generator_dir/swapz-primary-generator"
mapper_service="$unit_dir/swapz-primary-mapper.service"
boot_verifier_service="$unit_dir/swapz-primary-boot-verify.service"
swap_unit_name="$(systemd-escape --path --suffix=swap /dev/mapper/swapz-primary)"
[[ "$swap_unit_name" == 'dev-mapper-swapz\x2dprimary.swap' ]] ||
  blocked "unexpected systemd-escaped primary swap unit name"
primary_swap="$unit_dir/$swap_unit_name"
installed_module_dir="$modules_root/$kernel_release/updates/dkms"
installed_module="$installed_module_dir/dm-swapz.ko"
module_candidate_paths=(
  "$installed_module"
  "$installed_module.xz"
  "$installed_module.zst"
  "$installed_module.gz"
)
marker=".swapz-owned"
qualification_marker=".swapz-qualification"
source_manifest=".swapz-sources.sha256"
binary_manifest=".swapz-binaries.sha256"

hash_file() {
  local path="$1"
  [[ -f "$path" && ! -L "$path" ]] || return 1
  sha256sum -- "$path" | awk '{print $1}'
}

safe_input_file() {
  local path="$1" mode owner links
  [[ -f "$path" && ! -L "$path" ]] || return 1
  IFS=: read -r owner mode links < <(stat -c '%u:%a:%h' -- "$path") || return 1
  (( (8#$mode & 8#022) == 0 )) || return 1
  [[ "$links" == 1 ]]
}

expected_installed_owner="$(id -u)"
expected_installed_group="$(id -g)"
if [[ -z "$test_root" ]]; then
  expected_installed_owner=0
  expected_installed_group=0
fi

installed_directory_metadata() {
  local path="$1" expected_mode="$2" uid gid mode
  [[ -d "$path" && ! -L "$path" ]] || return 1
  IFS=: read -r uid gid mode < <(stat -c '%u:%g:%a' -- "$path") || return 1
  [[ "$uid" == "$expected_installed_owner" &&
     "$gid" == "$expected_installed_group" &&
     "$mode" == "$expected_mode" ]]
}

reject_symlinked_destination() {
  local path="$1"
  [[ ! -L "$path" ]] || blocked "symlinked package destination: $path"
}

for destination in "$srcbase" "$modules_root" "$modules_root/$kernel_release" "$prefix" \
    "$prefix/sbin" "$prefix/lib" "$prefix/libexec" "$prefix/lib/systemd" \
    "$unit_dir" "$generator_dir" "$installed_module_dir"; do
  if [[ -e "$destination" || -L "$destination" ]]; then
    reject_symlinked_destination "$destination"
    [[ -d "$destination" ]] || blocked "non-directory package destination: $destination"
    IFS=: read -r destination_uid destination_gid destination_mode < <(
      stat -c '%u:%g:%a' -- "$destination"
    ) || blocked "cannot inspect package destination: $destination"
    [[ "$destination_uid" == "$expected_installed_owner" &&
       "$destination_gid" == "$expected_installed_group" ]] ||
      blocked "unexpected package destination ownership: $destination"
    (( (8#$destination_mode & 8#022) == 0 )) ||
      blocked "writable package destination directory: $destination"
  fi
done

installed_file_metadata() {
  local path="$1" expected_mode="$2" uid gid mode links
  [[ -f "$path" && ! -L "$path" ]] || return 1
  IFS=: read -r uid gid mode links < <(stat -c '%u:%g:%a:%h' -- "$path") || return 1
  [[ "$uid" == "$expected_installed_owner" &&
     "$gid" == "$expected_installed_group" &&
     "$mode" == "$expected_mode" && "$links" == 1 ]]
}

verify_source_metadata() {
  local path
  installed_directory_metadata "$src" 755 || return 1
  installed_directory_metadata "$src/src" 755 || return 1
  installed_directory_metadata "$src/src/kernel" 755 || return 1
  for path in "$src/dkms.conf" "$src/src/kernel/VERSION" \
      "$src/src/kernel/Makefile" "$src/$marker" \
      "$src/$source_manifest" "$src/$binary_manifest"; do
    installed_file_metadata "$path" 644 || return 1
  done
  for path in "$src"/src/kernel/*.c "$src"/src/kernel/*.h; do
    installed_file_metadata "$path" 644 || return 1
  done
}

swapz_module_loaded() {
  if [[ -n "$test_root" ]]; then
    [[ ${SWAPZ_TEST_MODULE_ACTIVE:-0} == 1 ]]
    return
  fi
  [[ -e /sys/module/dm_swapz || -e /sys/module/dm-swapz ]]
}

swapz_mapper_present() {
  local dm name uuid
  if [[ -n "$test_root" ]]; then
    [[ ${SWAPZ_TEST_MAPPING_ACTIVE:-0} == 1 ]]
    return
  fi
  shopt -s nullglob
  for dm in /sys/block/dm-*; do
    [[ -r "$dm/dm/name" && -r "$dm/dm/uuid" ]] || continue
    IFS= read -r name < "$dm/dm/name" || continue
    IFS= read -r uuid < "$dm/dm/uuid" || continue
    case "$name:$uuid" in
      swapz-*:*|*:SWAPZ-*) shopt -u nullglob; return 0 ;;
    esac
  done
  shopt -u nullglob
  return 1
}

verify_source_manifest() {
  [[ -f "$src/$source_manifest" && ! -L "$src/$source_manifest" ]] || return 1
  (cd "$src" && sha256sum --quiet -c "$source_manifest")
}

verify_binary_manifest() {
  [[ -f "$src/$binary_manifest" && ! -L "$src/$binary_manifest" ]] || return 1
  sha256sum --quiet -c "$src/$binary_manifest"
}

verify_owned_legacy() {
  verify_source_metadata || return 1
  [[ -d "$src" && ! -L "$src" && -f "$src/$marker" &&
     -f "$src/$source_manifest" && -f "$src/$binary_manifest" &&
     -f "$cli" && ! -L "$cli" && -f "$helper" && ! -L "$helper" &&
     -f "$module_snapshot" && ! -L "$module_snapshot" &&
     -f "$primary_generator" && -x "$primary_generator" && ! -L "$primary_generator" &&
     -f "$boot_verifier" && -x "$boot_verifier" && ! -L "$boot_verifier" &&
     -f "$mapper_service" && ! -L "$mapper_service" &&
     -f "$boot_verifier_service" && ! -L "$boot_verifier_service" &&
     -f "$primary_swap" && ! -L "$primary_swap" ]] || return 1
  grep -Fxq "swapz:$version" "$src/$marker" || return 1
  verify_source_manifest && verify_binary_manifest
}

verify_installed_module_set() {
  local candidate count=0 matched=""
  for candidate in "${module_candidate_paths[@]}"; do
    if [[ -e "$candidate" || -L "$candidate" ]]; then
      count=$((count + 1))
      matched="$candidate"
    fi
  done
  [[ "$count" == 1 && "$matched" == "$installed_module" ]]
}

verify_owned() {
  verify_owned_legacy || return 1
  verify_installed_module_set || return 1
  [[ -f "$src/$qualification_marker" && ! -L "$src/$qualification_marker" &&
     -f "$installed_module" && ! -L "$installed_module" ]] || return 1
  installed_file_metadata "$src/$qualification_marker" 644 || return 1
  installed_file_metadata "$cli" 755 || return 1
  installed_file_metadata "$boot_verifier" 755 || return 1
  installed_file_metadata "$helper" 755 || return 1
  installed_file_metadata "$module_snapshot" 644 || return 1
  installed_file_metadata "$primary_generator" 755 || return 1
  installed_file_metadata "$mapper_service" 644 || return 1
  installed_file_metadata "$boot_verifier_service" 644 || return 1
  installed_file_metadata "$primary_swap" 644 || return 1
  installed_file_metadata "$installed_module" 644 || return 1
  verify_binary_manifest
}

package_paths_present() {
  local candidate
  if [[ -e "$src" || -L "$src" || -e "$cli" || -L "$cli" ||
        -e "$boot_verifier" || -L "$boot_verifier" ||
        -e "$helper_dir" || -L "$helper_dir" ||
        -e "$primary_generator" || -L "$primary_generator" ||
        -e "$mapper_service" || -L "$mapper_service" ||
        -e "$boot_verifier_service" || -L "$boot_verifier_service" ||
        -e "$primary_swap" || -L "$primary_swap" ]]; then
    return 0
  fi
  for candidate in "${module_candidate_paths[@]}"; do
    [[ -e "$candidate" || -L "$candidate" ]] && return 0
  done
  return 1
}

cleanup_activation_files() {
  rm -f -- "$cli" "$boot_verifier" "$helper" "$module_snapshot" \
    "$primary_generator" "$mapper_service" "$boot_verifier_service" "$primary_swap"
  rmdir -- "$helper_dir" 2>/dev/null || true
}

cleanup_source_files() {
  if [[ -d "$src" && ! -L "$src" ]]; then
    rm -rf -- "$src"
  elif [[ -L "$src" ]]; then
    rm -f -- "$src"
  fi
}

cleanup_package_files() {
  cleanup_activation_files
  cleanup_source_files
}

ensure_transaction_parent() {
  if [[ -e "$transaction_parent" || -L "$transaction_parent" ]]; then
    installed_directory_metadata "$transaction_parent" 700 ||
      blocked "unsafe package transaction directory"
  elif [[ -z "$test_root" ]]; then
    install -d -o 0 -g 0 -m0700 "$transaction_parent"
  else
    install -d -m0700 "$transaction_parent"
  fi
}

assert_no_incomplete_package_transactions() {
  local -a stale_transactions=()
  [[ -e "$transaction_parent" || -L "$transaction_parent" ]] || return 0
  installed_directory_metadata "$transaction_parent" 700 ||
    blocked "unsafe package transaction directory"
  shopt -s nullglob
  stale_transactions=(
    "$transaction_parent"/swapz-package.*
    "$transaction_parent"/swapz-uninstall.*
  )
  shopt -u nullglob
  (( ${#stale_transactions[@]} == 0 )) ||
    blocked "incomplete package transaction retained at ${stale_transactions[0]}"
}

persist_uninstall_state() {
  local phase="$1"
  python3 - "$transaction_dir" "$phase" "$version" "$kernel_release" <<'PY'
import hashlib
import json
import os
import stat
import sys
from pathlib import Path

transaction = Path(sys.argv[1])
phase = sys.argv[2]
version = sys.argv[3]
kernel_release = sys.argv[4]
backup = transaction / "backup"
if not backup.is_dir() or backup.is_symlink():
    raise SystemExit("missing backup directory")

entries = []
# Fsync the transaction parent too: the rollback directory entry itself must
# survive before any installed artifact is removed.
directories = {backup, transaction, transaction.parent}
for path in sorted(backup.rglob("*")):
    if path.is_symlink():
        raise SystemExit(f"unsafe backup symlink: {path}")
    metadata = path.stat()
    if path.is_dir():
        directories.add(path)
        continue
    if not path.is_file():
        raise SystemExit(f"unsafe backup entry: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
        os.fsync(stream.fileno())
    entries.append({
        "path": str(path.relative_to(backup)),
        "sha256": digest.hexdigest(),
        "size": metadata.st_size,
        "mode": stat.S_IMODE(metadata.st_mode),
        "uid": metadata.st_uid,
        "gid": metadata.st_gid,
    })

for directory in sorted(directories, key=lambda item: len(item.parts), reverse=True):
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)

state = {
    "schema": "swapz-package-uninstall-v1",
    "phase": phase,
    "version": version,
    "kernel_release": kernel_release,
    "backup_files": entries,
}
temporary = transaction / "state.json.tmp"
final = transaction / "state.json"
with temporary.open("w", encoding="utf-8") as stream:
    json.dump(state, stream, sort_keys=True, separators=(",", ":"))
    stream.write("\n")
    stream.flush()
    os.fsync(stream.fileno())
os.chmod(temporary, 0o600)
os.replace(temporary, final)
descriptor = os.open(transaction, os.O_RDONLY | os.O_DIRECTORY)
try:
    os.fsync(descriptor)
finally:
    os.close(descriptor)
PY
}

backup_verified_package_for_uninstall() {
  backup_dir="$transaction_dir/backup"
  mkdir -m0700 "$backup_dir" "$backup_dir/source" "$backup_dir/source/src" \
    "$backup_dir/source/src/kernel" "$backup_dir/files"
  cp -a -- "$src/dkms.conf" "$src/$marker" "$src/$qualification_marker" \
    "$src/$source_manifest" "$src/$binary_manifest" "$backup_dir/source/"
  cp -a -- "$src/src/kernel/VERSION" "$src/src/kernel/Makefile" \
    "$src"/src/kernel/*.c "$src"/src/kernel/*.h "$backup_dir/source/src/kernel/"
  for file in "$cli" "$boot_verifier" "$helper" "$module_snapshot" \
      "$primary_generator" "$mapper_service" "$boot_verifier_service" "$primary_swap"; do
    cp -a -- "$file" "$backup_dir/files/$(printf '%s' "$file" | sha256sum | awk '{print $1}')"
  done
  printf '%s\n' \
    "$cli" "$boot_verifier" "$helper" "$module_snapshot" \
    "$primary_generator" "$mapper_service" "$boot_verifier_service" "$primary_swap" \
    > "$backup_dir/file-paths"
  cp -a -- "$installed_module" "$backup_dir/installed-module"
}

restore_uninstall_file_backups_except_cli() {
  local path digest backup_path
  [[ -f "$backup_dir/file-paths" && ! -L "$backup_dir/file-paths" ]] || return 1
  while IFS= read -r path; do
    [[ "$path" == "$cli" ]] && continue
    digest="$(printf '%s' "$path" | sha256sum | awk '{print $1}')"
    backup_path="$backup_dir/files/$digest"
    [[ -f "$backup_path" && ! -L "$backup_path" ]] || return 1
    install -d -m0755 "$(dirname "$path")"
    cp -a -- "$backup_path" "$path"
    cmp -s "$backup_path" "$path" || return 1
  done < "$backup_dir/file-paths"
}

restore_uninstall_cli_backup() {
  local digest backup_path temporary_cli
  digest="$(printf '%s' "$cli" | sha256sum | awk '{print $1}')"
  backup_path="$backup_dir/files/$digest"
  [[ -f "$backup_path" && ! -L "$backup_path" ]] || return 1
  install -d -m0755 "$cli_dir"
  temporary_cli="$cli_dir/.swapzctl.restore.$$"
  [[ ! -e "$temporary_cli" && ! -L "$temporary_cli" ]] || return 1
  install -m0755 "$backup_path" "$temporary_cli" || return 1
  cmp -s "$backup_path" "$temporary_cli" || {
    rm -f -- "$temporary_cli"
    return 1
  }
  mv -f -- "$temporary_cli" "$cli"
}

restore_uninstall_backup() {
  local current_status
  backup_dir="$transaction_dir/backup"
  cleanup_activation_files
  cleanup_source_files
  rm -f -- "$installed_module"
  current_status="$({ "$dkms_bin" status -m swapz -v "$version" || true; } 2>/dev/null)"
  if [[ -n "$current_status" ]]; then
    "$dkms_bin" remove -m swapz -v "$version" --all || return 1
  fi

  install -d -m0755 "$src/src/kernel"
  cp -a -- "$backup_dir/source/dkms.conf" "$src/dkms.conf"
  cp -a -- "$backup_dir/source/$marker" "$src/$marker"
  cp -a -- "$backup_dir/source/$qualification_marker" "$src/$qualification_marker"
  cp -a -- "$backup_dir/source/$source_manifest" "$src/$source_manifest"
  cp -a -- "$backup_dir/source/$binary_manifest" "$src/$binary_manifest"
  cp -a -- "$backup_dir/source/src/kernel/"* "$src/src/kernel/"
  (cd "$src" && sha256sum -c "$source_manifest" >/dev/null) || return 1

  "$dkms_bin" add -m swapz -v "$version" || return 1
  "$dkms_bin" build -m swapz -v "$version" -k "$kernel_release" || return 1
  "$dkms_bin" install -m swapz -v "$version" -k "$kernel_release" || return 1
  install -d -m0755 "$installed_module_dir"
  install -m0644 "$backup_dir/installed-module" "$installed_module" || return 1
  cmp -s "$backup_dir/installed-module" "$installed_module" || return 1
  "$depmod_bin" "$kernel_release" || return 1
  cmp -s "$backup_dir/installed-module" "$installed_module" || return 1
  persist_uninstall_state rollback-backend-restored || return 1

  # Restore all non-CLI package files only after module/DKMS state and depmod
  # are valid. The CLI is the activation gate and is restored atomically last.
  restore_uninstall_file_backups_except_cli || return 1
  persist_uninstall_state rollback-files-restored || return 1
  "$systemctl_bin" daemon-reload || return 1
  persist_uninstall_state rollback-systemd-reloaded || return 1
  restore_uninstall_cli_backup || return 1
  persist_uninstall_state rollback-cli-restored || return 1
  verify_owned
}

uninstall_rollback() {
  local rc="${1:-1}" reason="${2:-failure}"
  trap - ERR HUP INT TERM
  transaction_active=0
  echo "BLOCKED: package uninstall $reason; attempting transaction rollback" >&2
  persist_uninstall_state rollback-started >/dev/null 2>&1 || true
  if restore_uninstall_backup; then
    persist_uninstall_state rolled-back >/dev/null 2>&1 || true
    rm -rf -- "$transaction_dir"
  else
    persist_uninstall_state rollback-incomplete >/dev/null 2>&1 || true
    echo "BLOCKED: uninstall rollback incomplete; verified recovery data retained at $transaction_dir" >&2
  fi
  exit "$rc"
}

uninstall_test_checkpoint() {
  local phase="$1"
  [[ -n "$test_root" ]] || return 0
  [[ ${SWAPZ_TEST_UNINSTALL_FAIL_AFTER:-never} != "$phase" ]] || {
    blocked "test uninstall checkpoint after $phase"
  }
}

assert_no_incomplete_package_transactions

if [[ "$action" == uninstall ]]; then
  if [[ -z "$test_root" && "$action" == uninstall ]] &&
     [[ -e /sys/module/dm_swapz || -e /sys/module/dm-swapz ]]; then
    echo "BLOCKED: loaded module; refusing DKMS removal" >&2
    exit 1
  fi
  if [[ -n "$test_root" ]] && swapz_module_loaded; then
    echo "BLOCKED: loaded module; refusing DKMS removal" >&2
    exit 1
  fi
  swapz_mapper_present && blocked "active swapz mapping; refusing package removal"
  [[ ! -e "$primary_state" && ! -L "$primary_state" ]] ||
    blocked "primary recovery state exists; preserve it during package removal"
  if compgen -G "$primary_recovery_base/partition-*.active" >/dev/null; then
    blocked "a primary partition ownership marker exists; preserve the recovery path during package removal"
  fi
  if [[ -z "$test_root" ]]; then
    for unit in swapz-primary-boot-verify.service swapz-primary-mapper.service "$swap_unit_name"; do
      "$systemctl_bin" is-active --quiet "$unit" &&
        blocked "$unit is active; refusing package removal"
      "$systemctl_bin" is-enabled --quiet "$unit" &&
        blocked "$unit is enabled; disable swapz through its recovery procedure first"
    done
  fi
  verify_owned || { echo "BLOCKED: foreign, absent or modified swapz package" >&2; exit 1; }

  ensure_transaction_parent
  transaction_dir="$(mktemp -d "$transaction_parent/swapz-uninstall.XXXXXXXX")"
  chmod 0700 "$transaction_dir"
  transaction_active=2
  trap 'staging_abort $? failure' ERR
  trap 'staging_abort 129 interruption' HUP
  trap 'staging_abort 130 interruption' INT
  trap 'staging_abort 143 interruption' TERM
  backup_verified_package_for_uninstall
  persist_uninstall_state prepared

  transaction_active=3
  trap 'uninstall_rollback $? failure' ERR
  trap 'uninstall_rollback 129 interruption' HUP
  trap 'uninstall_rollback 130 interruption' INT
  trap 'uninstall_rollback 143 interruption' TERM

  # Remove all activation entry points only after the private rollback snapshot
  # and its independently verifiable hash manifest are durable.
  persist_uninstall_state removing-activation-files
  cleanup_activation_files
  persist_uninstall_state activation-files-removed
  uninstall_test_checkpoint activation-files-removed

  persist_uninstall_state removing-dkms
  "$dkms_bin" remove -m swapz -v "$version" --all
  persist_uninstall_state dkms-removed
  uninstall_test_checkpoint dkms-removed

  persist_uninstall_state removing-source
  cleanup_source_files
  persist_uninstall_state source-removed
  uninstall_test_checkpoint source-removed

  persist_uninstall_state removing-installed-module
  rm -f -- "$installed_module"
  persist_uninstall_state installed-module-removed
  uninstall_test_checkpoint installed-module-removed

  persist_uninstall_state depmod-pending
  "$depmod_bin" "$kernel_release"
  persist_uninstall_state depmod-complete
  uninstall_test_checkpoint depmod-complete

  persist_uninstall_state systemd-reload-pending
  "$systemctl_bin" daemon-reload
  persist_uninstall_state systemd-reload-complete
  uninstall_test_checkpoint systemd-reload-complete

  transaction_active=0
  trap - ERR HUP INT TERM
  rm -rf -- "$transaction_dir"
  echo "Uninstalled owned swapz package without touching swap"
  exit 0
fi

# Installation consumes the exact artifacts already qualified by make test. It
# never rebuilds or re-signs them, because either operation would change the
# bytes whose digests were admitted by the qualification report.
for input in "$cli_artifact" "$oracle_artifact" "$module_artifact" "$build_info" "$qualification_report"; do
  safe_input_file "$input" || blocked "unsafe or missing package input: $input"
done
[[ -x "$cli_artifact" && -x "$oracle_artifact" ]] ||
  blocked "qualified userspace artifacts are not executable"
for payload in dkms.conf src/kernel/VERSION \
    packaging/swapz-primary-boot-verify \
    packaging/swapz-primary-mapper.service \
    packaging/swapz-primary-boot-verify.service \
    packaging/swapz-primary-generator packaging/swapz-primary.swap; do
  safe_input_file "$payload" || blocked "unsafe package payload: $payload"
done

qualification_output="$(python3 - "$qualification_report" <<'PY'
import json
import re
import sys
from pathlib import Path

report = json.loads(Path(sys.argv[1]).read_text())
required_stages = (
    "Build module and helpers",
    "Native and rootless contracts",
    "Kernel warnings W=1",
    "Kernel warnings W=2",
    "Owned RAM smoke + mixed/QD pilot",
)
if report.get("schema") != "swapz-test-results-v1":
    raise SystemExit("bad schema")
source = report.get("source_sha")
tested = report.get("tested_commit_sha")
if not isinstance(source, str) or not re.fullmatch(r"[0-9a-f]{40}", source) or tested != source:
    raise SystemExit("bad source")
if report.get("overall") != "PASS" or report.get("qualification") != "RAM_BACKED_NULL_BLK_ONLY":
    raise SystemExit("not qualified")
stages = report.get("stages")
if not isinstance(stages, list) or len(stages) != len(required_stages):
    raise SystemExit("bad stages")
for expected, stage in zip(required_stages, stages):
    if not isinstance(stage, dict) or stage.get("name") != expected or stage.get("status") != "PASS" or stage.get("exit_code") != 0:
        raise SystemExit("stage failed")
artifacts = report.get("qualified_artifacts")
if not isinstance(artifacts, dict) or artifacts.get("status") != "AVAILABLE":
    raise SystemExit("artifacts unavailable")
values = []
for key in ("formatter_sha256", "module_sha256", "oracle_sha256"):
    value = artifacts.get(key)
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise SystemExit("bad digest")
    values.append(value)
print(source)
print(*values, sep="\n")
PY
)" || blocked "qualification report is invalid or incomplete"
mapfile -t qualification_fields <<< "$qualification_output"
[[ ${#qualification_fields[@]} == 4 ]] || blocked "qualification report fields are incomplete"
qualified_source_sha="${qualification_fields[0]}"
qualified_cli_sha256="${qualification_fields[1]}"
qualified_module_sha256="${qualification_fields[2]}"
qualified_oracle_sha256="${qualification_fields[3]}"
qualification_report_sha256="$(hash_file "$qualification_report")" || blocked "cannot hash qualification report"

build_source_sha="$(sed -n 's/^#define SWAPZ_BUILD_SOURCE_SHA "\([0-9a-f]\{40\}\)"$/\1/p' "$build_info")"
build_source_clean="$(sed -n 's/^#define SWAPZ_BUILD_SOURCE_CLEAN \([01]\)$/\1/p' "$build_info")"
[[ "$build_source_sha" == "$qualified_source_sha" && "$build_source_clean" == 1 ]] ||
  blocked "build provenance does not match the qualified clean source"
if [[ -z "$test_root" ]]; then
  export GIT_OPTIONAL_LOCKS=0
  git -c safe.directory="$root" merge-base --is-ancestor "$qualified_source_sha" HEAD >/dev/null 2>&1 ||
    blocked "qualified source is not an ancestor of the current checkout"
  git -c safe.directory="$root" diff --quiet "$qualified_source_sha" HEAD -- . ':(exclude)test_results.json' ||
    blocked "checkout changed after qualification"
  [[ -z "$(git -c safe.directory="$root" status --porcelain --untracked-files=all -- \
      src/kernel src/userspace Makefile packaging dkms.conf tests/tools/device-roundtrip.c test_results.json)" ]] ||
    blocked "package inputs or qualification report are dirty"
fi

[[ "$(hash_file "$cli_artifact")" == "$qualified_cli_sha256" ]] ||
  blocked "swapzctl digest does not match qualification"
[[ "$(hash_file "$module_artifact")" == "$qualified_module_sha256" ]] ||
  blocked "module digest does not match qualification"
[[ "$(hash_file "$oracle_artifact")" == "$qualified_oracle_sha256" ]] ||
  blocked "round-trip oracle digest does not match qualification"

kernel_build_link="$modules_root/$kernel_release/build"
[[ -e "$kernel_build_link" || -L "$kernel_build_link" ]] || blocked "kernel headers are missing for $kernel_release"
kernel_build_dir="$(readlink -f -- "$kernel_build_link" 2>/dev/null || true)"
[[ -n "$kernel_build_dir" && -d "$kernel_build_dir" && -f "$kernel_build_dir/Makefile" ]] ||
  blocked "kernel headers are incomplete for $kernel_release"
if [[ -z "$test_root" ]]; then
  case "$kernel_build_dir" in /usr/src/*|/lib/modules/*) ;; *)
    blocked "kernel header path is outside trusted system locations" ;;
  esac
fi

module_vermagic="$(modinfo -F vermagic "$module_artifact" 2>/dev/null || true)"
module_kernel_release="${module_vermagic%% *}"
[[ "$module_kernel_release" == "$kernel_release" ]] ||
  blocked "qualified module does not match the running kernel"
if [[ -n "$test_root" ]]; then
  SWAPZ_SIGN_TEST_ROOT="$sandbox" bash packaging/sign-module.sh --verify "$module_artifact"
else
  bash packaging/sign-module.sh --verify "$module_artifact"
fi
[[ "$(hash_file "$module_artifact")" == "$qualified_module_sha256" ]] ||
  blocked "module bytes changed during signature verification"

incoming_identity() {
  printf '%s\n' \
    'schema=swapz-package-v1' \
    "version=$version" \
    "kernel_release=$kernel_release" \
    "source_sha=$qualified_source_sha" \
    "qualification_report_sha256=$qualification_report_sha256" \
    "swapzctl_sha256=$qualified_cli_sha256" \
    "module_sha256=$qualified_module_sha256" \
    "oracle_sha256=$qualified_oracle_sha256"
}

existing_kind=""
if package_paths_present; then
  if verify_owned; then
    existing_kind="current"
  elif verify_owned_legacy; then
    existing_kind="legacy"
  else
    blocked "existing package is partial, foreign, or modified"
  fi
fi

current_dkms_status="$({ "$dkms_bin" status -m swapz -v "$version" -k "$kernel_release" || true; } 2>/dev/null)"
if [[ -z "$existing_kind" && -n "$current_dkms_status" ]]; then
  blocked "DKMS state exists without a verified package"
fi
if [[ "$existing_kind" == current ]] &&
   cmp -s "$src/$qualification_marker" <(incoming_identity) &&
   [[ "$current_dkms_status" == *installed* ]]; then
  resolved_module="$(modinfo -n dm_swapz 2>/dev/null || true)"
  resolved_module="$(readlink -f -- "$resolved_module" 2>/dev/null || true)"
  [[ "$resolved_module" == "$installed_module" ]] ||
    blocked "installed module lookup does not match package ownership"
  echo "Installed swapz package already matches the exact qualified artifacts"
  exit 0
fi

swapz_module_loaded && blocked "loaded module; refusing package upgrade"
swapz_mapper_present && blocked "active swapz mapping; refusing package upgrade"

ensure_transaction_parent
transaction_dir="$(mktemp -d "$transaction_parent/swapz-package.XXXXXXXX")"
transaction_active=2
trap 'staging_abort $? failure' ERR
trap 'staging_abort 129 interruption' HUP
trap 'staging_abort 130 interruption' INT
trap 'staging_abort 143 interruption' TERM
chmod 0700 "$transaction_dir"
backup_dir="$transaction_dir/backup"
stage_dir="$transaction_dir/stage"
mkdir -m0700 "$backup_dir" "$stage_dir"
had_existing=0
if [[ -n "$existing_kind" ]]; then
  had_existing=1
  mkdir -p "$backup_dir/source/src/kernel" "$backup_dir/files"
  # Back up only package-owned source bytes; DKMS build output is reproducible.
  cp -a -- "$src/src/kernel/VERSION" "$src/src/kernel/Makefile" \
    "$src"/src/kernel/*.c "$src"/src/kernel/*.h "$backup_dir/source/src/kernel/"
  cp -a -- "$src/dkms.conf" "$src/$marker" "$src/$source_manifest" \
    "$src/$binary_manifest" "$backup_dir/source/"
  if [[ -f "$src/$qualification_marker" && ! -L "$src/$qualification_marker" ]]; then
    cp -a -- "$src/$qualification_marker" "$backup_dir/source/"
  fi
  for file in "$cli" "$boot_verifier" "$helper" "$module_snapshot" \
      "$primary_generator" "$mapper_service" "$boot_verifier_service" "$primary_swap"; do
    cp -a -- "$file" "$backup_dir/files/$(printf '%s' "$file" | sha256sum | awk '{print $1}')"
  done
  printf '%s\n' \
    "$cli" "$boot_verifier" "$helper" "$module_snapshot" \
    "$primary_generator" "$mapper_service" "$boot_verifier_service" "$primary_swap" \
    > "$backup_dir/file-paths"
  if [[ -f "$installed_module" && ! -L "$installed_module" ]]; then
    cp -a -- "$installed_module" "$backup_dir/installed-module"
  fi
fi

new_source_created=0
new_dkms_registered=0
new_files_committed=0
rollback_in_progress=0

restore_file_backups_except_cli() {
  local path digest backup_path
  [[ -f "$backup_dir/file-paths" ]] || return 0
  while IFS= read -r path; do
    [[ "$path" == "$cli" ]] && continue
    digest="$(printf '%s' "$path" | sha256sum | awk '{print $1}')"
    backup_path="$backup_dir/files/$digest"
    [[ -f "$backup_path" && ! -L "$backup_path" ]] || return 1
    install -d -m0755 "$(dirname "$path")"
    cp -a -- "$backup_path" "$path"
    cmp -s "$backup_path" "$path" || return 1
  done < "$backup_dir/file-paths"
}

restore_cli_backup() {
  local digest backup_path temporary_cli
  [[ -f "$backup_dir/file-paths" ]] || return 0
  digest="$(printf '%s' "$cli" | sha256sum | awk '{print $1}')"
  backup_path="$backup_dir/files/$digest"
  [[ -f "$backup_path" && ! -L "$backup_path" ]] || return 1
  install -d -m0755 "$cli_dir"
  temporary_cli="$cli_dir/.swapzctl.restore.$"
  [[ ! -e "$temporary_cli" && ! -L "$temporary_cli" ]] || return 1
  install -m0755 "$backup_path" "$temporary_cli" || return 1
  cmp -s "$backup_path" "$temporary_cli" || {
    rm -f -- "$temporary_cli"
    return 1
  }
  mv -f -- "$temporary_cli" "$cli"
}

restore_previous_package() {
  (( had_existing == 1 )) || return 0
  cleanup_package_files
  install -d -m0755 "$src/src/kernel"
  cp -a -- "$backup_dir/source/dkms.conf" "$src/dkms.conf"
  cp -a -- "$backup_dir/source/$marker" "$src/$marker"
  cp -a -- "$backup_dir/source/$source_manifest" "$src/$source_manifest"
  cp -a -- "$backup_dir/source/$binary_manifest" "$src/$binary_manifest"
  if [[ -f "$backup_dir/source/$qualification_marker" ]]; then
    cp -a -- "$backup_dir/source/$qualification_marker" "$src/$qualification_marker"
  fi
  cp -a -- "$backup_dir/source/src/kernel/"* "$src/src/kernel/"
  (cd "$src" && sha256sum -c "$source_manifest" >/dev/null) || return 1
  "$dkms_bin" add -m swapz -v "$version" || return 1
  "$dkms_bin" build -m swapz -v "$version" -k "$kernel_release" || return 1
  "$dkms_bin" install -m swapz -v "$version" -k "$kernel_release" || return 1
  if [[ -f "$backup_dir/installed-module" ]]; then
    install -d -m0755 "$installed_module_dir"
    install -m0644 "$backup_dir/installed-module" "$installed_module" || return 1
    cmp -s "$backup_dir/installed-module" "$installed_module" || return 1
  fi
  "$depmod_bin" "$kernel_release" || return 1
  if [[ -f "$backup_dir/installed-module" ]]; then
    cmp -s "$backup_dir/installed-module" "$installed_module" || return 1
  fi
  restore_file_backups_except_cli || return 1
  "$systemctl_bin" daemon-reload || return 1
  restore_cli_backup || return 1
  verify_owned
}

rollback() {
  local rc="${1:-1}" reason="${2:-failure}"
  (( rollback_in_progress == 0 )) || exit "$rc"
  rollback_in_progress=1
  trap - ERR HUP INT TERM
  echo "BLOCKED: package $reason; attempting transaction rollback" >&2
  if (( new_dkms_registered == 1 )) || [[ -n "$({ "$dkms_bin" status -m swapz -v "$version" || true; } 2>/dev/null)" ]]; then
    "$dkms_bin" remove -m swapz -v "$version" --all >/dev/null 2>&1 || true
  fi
  cleanup_package_files
  rm -f -- "$installed_module"
  if (( had_existing == 1 )); then
    if restore_previous_package; then
      rm -rf -- "$transaction_dir"
    else
      echo "BLOCKED: previous package restoration failed; preserved rollback data at $transaction_dir" >&2
    fi
  else
    local cleanup_ok=1
    "$depmod_bin" "$kernel_release" >/dev/null 2>&1 || cleanup_ok=0
    "$systemctl_bin" daemon-reload >/dev/null 2>&1 || cleanup_ok=0
    if (( cleanup_ok == 1 )); then
      rm -rf -- "$transaction_dir"
    else
      echo "BLOCKED: rollback cleanup incomplete; preserved transaction data at $transaction_dir" >&2
    fi
  fi
  exit "$rc"
}
transaction_active=1
trap 'rollback $? failure' ERR
trap 'rollback 129 interruption' HUP
trap 'rollback 130 interruption' INT
trap 'rollback 143 interruption' TERM

if (( had_existing == 1 )); then
  "$dkms_bin" remove -m swapz -v "$version" --all
  rm -rf -- "$src"
fi

[[ ! -e "$src" && ! -L "$src" ]] || blocked "DKMS source path became occupied"
install -d -m0755 "$src/src/kernel"
new_source_created=1
install -m0644 dkms.conf "$src/dkms.conf"
install -m0644 src/kernel/VERSION "$src/src/kernel/VERSION"
for file in src/kernel/Makefile src/kernel/*.c src/kernel/*.h; do
  safe_input_file "$file" || blocked "unsafe kernel package source: $file"
  install -m0644 "$file" "$src/src/kernel/$(basename "$file")"
done
install -m0644 "$build_info" "$src/src/kernel/swapz-build-info.h"
printf 'swapz:%s\n' "$version" > "$src/$marker"
incoming_identity > "$src/$qualification_marker"
chmod 0644 "$src/$marker" "$src/$qualification_marker"
(cd "$src" && sha256sum dkms.conf src/kernel/VERSION src/kernel/Makefile \
  src/kernel/*.c src/kernel/*.h "$qualification_marker") > "$src/$source_manifest"

"$dkms_bin" add -m swapz -v "$version"
new_dkms_registered=1
"$dkms_bin" build -m swapz -v "$version" -k "$kernel_release"
"$dkms_bin" install -m swapz -v "$version" -k "$kernel_release"
status="$("$dkms_bin" status -m swapz -v "$version" -k "$kernel_release")"
[[ "$status" == *installed* && "$status" == *"$kernel_release"* ]] ||
  blocked "DKMS did not report the current kernel installed"

existing_module_candidates=()
for candidate in "${module_candidate_paths[@]}"; do
  [[ -e "$candidate" || -L "$candidate" ]] && existing_module_candidates+=("$candidate")
done
[[ ${#existing_module_candidates[@]} == 1 ]] || blocked "unexpected DKMS module paths"
dkms_installed_module="${existing_module_candidates[0]}"
[[ -f "$dkms_installed_module" && ! -L "$dkms_installed_module" ]] ||
  blocked "DKMS installed module is not a regular file"
if [[ "$dkms_installed_module" != "$installed_module" ]]; then
  rm -f -- "$dkms_installed_module"
fi
install -d -m0755 "$installed_module_dir"
install -m0644 "$module_artifact" "$installed_module"
[[ "$(hash_file "$installed_module")" == "$qualified_module_sha256" ]] ||
  blocked "installed module digest mismatch"
"$depmod_bin" "$kernel_release"
[[ "$(hash_file "$installed_module")" == "$qualified_module_sha256" ]] ||
  blocked "installed module changed during depmod"
resolved_module="$(modinfo -n dm_swapz 2>/dev/null || true)"
resolved_module="$(readlink -f -- "$resolved_module" 2>/dev/null || true)"
[[ "$resolved_module" == "$installed_module" ]] ||
  blocked "module lookup does not resolve to the qualified installed image"

# Prepare all userspace/systemd bytes before replacing any live package file.
install -m0755 "$cli_artifact" "$stage_dir/swapzctl"
install -m0755 packaging/swapz-primary-boot-verify "$stage_dir/swapz-primary-boot-verify"
install -m0755 "$oracle_artifact" "$stage_dir/device-roundtrip"
install -m0644 "$module_artifact" "$stage_dir/dm-swapz.ko"
sed "s|@SWAPZ_SBINDIR@|$cli_dir|g" packaging/swapz-primary-mapper.service > "$stage_dir/swapz-primary-mapper.service"
sed "s|@SWAPZ_SBINDIR@|$cli_dir|g" packaging/swapz-primary-boot-verify.service > "$stage_dir/swapz-primary-boot-verify.service"
sed "s|@SWAPZ_SBINDIR@|$cli_dir|g" packaging/swapz-primary-generator > "$stage_dir/swapz-primary-generator"
chmod 0644 "$stage_dir/swapz-primary-mapper.service" "$stage_dir/swapz-primary-boot-verify.service"
chmod 0755 "$stage_dir/swapz-primary-generator"
install -m0644 packaging/swapz-primary.swap "$stage_dir/$swap_unit_name"

[[ "$(hash_file "$stage_dir/swapzctl")" == "$qualified_cli_sha256" &&
   "$(hash_file "$stage_dir/device-roundtrip")" == "$qualified_oracle_sha256" &&
   "$(hash_file "$stage_dir/dm-swapz.ko")" == "$qualified_module_sha256" ]] ||
  blocked "staged artifact digest mismatch"

install -d -m0755 "$cli_dir" "$helper_dir" "$unit_dir" "$generator_dir"
install -m0755 "$stage_dir/swapzctl" "$cli"
install -m0755 "$stage_dir/swapz-primary-boot-verify" "$boot_verifier"
install -m0755 "$stage_dir/device-roundtrip" "$helper"
install -m0644 "$stage_dir/dm-swapz.ko" "$module_snapshot"
install -m0755 "$stage_dir/swapz-primary-generator" "$primary_generator"
install -m0644 "$stage_dir/swapz-primary-mapper.service" "$mapper_service"
install -m0644 "$stage_dir/swapz-primary-boot-verify.service" "$boot_verifier_service"
install -m0644 "$stage_dir/$swap_unit_name" "$primary_swap"
new_files_committed=1

sha256sum "$cli" "$boot_verifier" "$helper" "$module_snapshot" \
  "$primary_generator" "$mapper_service" "$boot_verifier_service" "$primary_swap" \
  "$installed_module" > "$src/$binary_manifest"
verify_owned || blocked "installed ownership or digest verification failed"
[[ "$(hash_file "$cli")" == "$qualified_cli_sha256" &&
   "$(hash_file "$helper")" == "$qualified_oracle_sha256" &&
   "$(hash_file "$module_snapshot")" == "$qualified_module_sha256" &&
   "$(hash_file "$installed_module")" == "$qualified_module_sha256" ]] ||
  blocked "installed artifact digest mismatch"

"$systemctl_bin" daemon-reload

transaction_active=0
trap - ERR HUP INT TERM
rm -rf -- "$transaction_dir"
echo "Installed exact qualified swapz artifacts with DKMS compatibility registration; primary-swap units remain disabled"
