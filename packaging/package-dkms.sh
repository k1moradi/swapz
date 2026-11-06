#!/usr/bin/env bash
# swapz package only: never load modules, create DM devices or activate swap.
# To replay a retained journal under the package lock: package-dkms.sh recover /usr/local
# Recovery never auto-runs as part of install/uninstall.
set -Eeuo pipefail
umask 022

transaction_active=0
transaction_dir=""
# Describes the attempted transition, including journal-write failures.
transaction_phase="preflight"
# Updated only after the state-file replacement and transaction-directory fsync
# both succeed. Signal traps must never infer durability from transaction_phase.
durable_transaction_phase="preflight"
# Recovery is fail-closed by default. Only an independently verified committed
# install may temporarily preserve activation while read-only recovery admission
# checks run.
recovery_quarantine_on_error=1
# Recovery diagnostics distinguish read-only refusal, an incomplete replay,
# and a replay that already restored and durably verified the previous state.
recovery_rollback_outcome="not attempted"

staging_abort() {
  local rc="${1:-1}" reason="${2:-failure}"
  trap - ERR HUP INT TERM
  transaction_active=0
  echo "BLOCKED: package $reason before mutation; removing staging data" >&2
  local cleanup_status=0
  if [[ -n "$transaction_dir" ]]; then
    remove_transaction_record || cleanup_status=$?
  fi
  if (( cleanup_status != 0 )); then
    printf 'BLOCKED: staging transaction-record cleanup failed (status %d); no package mutation occurred\n' "$cleanup_status" >&2
  fi
  exit "$rc"
}

blocked() {
  local condition="$*"
  printf 'BLOCKED: %s\n' "$condition" >&2
  if (( transaction_active == 1 )); then
    rollback 2 "$condition (phase: $transaction_phase)"
  elif (( transaction_active == 2 )); then
    staging_abort 2 "$condition (phase: $transaction_phase)"
  elif (( transaction_active == 3 )); then
    uninstall_rollback 2 "$condition (phase: $transaction_phase)"
  elif (( transaction_active == 4 )); then
    if (( recovery_quarantine_on_error == 1 )); then
      quarantine_activation || true
    fi
    printf 'BLOCKED: recovery phase %s refused (%s); rollback %s; recovery-required record retained\n' "$transaction_phase" "$condition" "$recovery_rollback_outcome" >&2
  else
    printf 'BLOCKED: preflight phase %s refused (%s); rollback not attempted\n' "$transaction_phase" "$condition" >&2
  fi
  exit 2
}

[[ $# == 2 && ( $1 == install || $1 == uninstall || $1 == recover ) ]] ||
  blocked "usage install|uninstall|recover ABSOLUTE_PREFIX"
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
for required_command in python3 sha256sum stat install cp rm mkdir rmdir sed grep find realpath readlink flock modinfo systemd-escape awk cmp basename mktemp git uname mv timeout lsblk dmsetup journalctl blkid tr cut dirname sleep cat; do
  command -v "$required_command" >/dev/null 2>&1 || blocked "$required_command unavailable"
done
package_lock_dir="$(dirname "$package_lock")"
expected_lock_owner="$(id -u)"
expected_lock_group="$(id -g)"
if [[ -z "$test_root" ]]; then
  expected_lock_owner=0
  expected_lock_group=0
  if [[ ! -e "$package_lock_dir" && ! -L "$package_lock_dir" ]]; then
    install -d -o 0 -g 0 -m0755 "$package_lock_dir"
  fi
fi

verify_package_lock_directory() {
  local uid gid mode
  [[ -d "$package_lock_dir" && ! -L "$package_lock_dir" ]] || return 1
  IFS=: read -r uid gid mode < <(stat -c '%u:%g:%a' -- "$package_lock_dir") ||
    return 1
  [[ "$uid" == "$expected_lock_owner" &&
     "$gid" == "$expected_lock_group" ]] || return 1
  (( (8#$mode & 8#022) == 0 ))
}

verify_package_lock_file() {
  local uid gid mode links
  [[ -f "$package_lock" && ! -L "$package_lock" ]] || return 1
  IFS=: read -r uid gid mode links < <(stat -c '%u:%g:%a:%h' -- "$package_lock") ||
    return 1
  [[ "$uid" == "$expected_lock_owner" &&
     "$gid" == "$expected_lock_group" &&
     "$mode" == 600 && "$links" == 1 ]]
}

verify_package_lock_directory || blocked "unsafe package lock directory"
if [[ ! -e "$package_lock" && ! -L "$package_lock" ]]; then
  (umask 077; set -o noclobber; : > "$package_lock") 2>/dev/null ||
    blocked "cannot create package lock safely"
fi
verify_package_lock_file || blocked "unsafe package lock file"
exec 9<>"$package_lock" || blocked "cannot open package lock"
package_lock_descriptor_identity="$(stat -Lc '%d:%i' -- /proc/self/fd/9 2>/dev/null || true)"
package_lock_named_identity="$(stat -c '%d:%i' -- "$package_lock" 2>/dev/null || true)"
[[ -n "$package_lock_descriptor_identity" &&
   "$package_lock_descriptor_identity" == "$package_lock_named_identity" ]] ||
  blocked "package lock path changed while opening"
flock -n 9 || blocked "another swapz package operation is active"
verify_package_lock_file || blocked "package lock metadata changed while locked"
package_lock_named_identity="$(stat -c '%d:%i' -- "$package_lock" 2>/dev/null || true)"
[[ "$package_lock_descriptor_identity" == "$package_lock_named_identity" ]] ||
  blocked "package lock path changed while locked"

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
runtime_health="$cli_dir/swapz-primary-runtime-health"
helper_dir="$prefix/libexec/swapz"
helper="$helper_dir/device-roundtrip"
module_snapshot="$helper_dir/dm-swapz.ko"
unit_dir="$prefix/lib/systemd/system"
generator_dir="$prefix/lib/systemd/system-generators"
primary_generator="$generator_dir/swapz-primary-generator"
mapper_service="$unit_dir/swapz-primary-mapper.service"
boot_verifier_service="$unit_dir/swapz-primary-boot-verify.service"
runtime_health_service="$unit_dir/swapz-primary-runtime-health.service"
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

# Recovery snapshot filenames use a digest of the canonical destination path.
# Capture the producer status before using that digest as a filename component.
hash_path_key() {
  local path="$1" digest status=0 observed=malformed_output
  digest="$(printf '%s' "$path" | sha256sum | awk '{print $1}')" ||
    status=$?
  if (( status != 0 )) || [[ ! "$digest" =~ ^[0-9a-f]{64}$ ]]; then
    (( status != 0 )) && observed=producer_failed
    printf 'SWAPZ_PACKAGE_DIAGNOSTIC artifact=package_snapshot_path_key check=sha256 expected=successful_canonical_path_digest observed=%s command_status=%s next=inspect_sha256sum_tool_read_only retained_state=unchanged\n' \
      "$observed" "$status" >&2
    (( status != 0 )) && return "$status"
    return 1
  fi
  printf '%s\n' "$digest"
}

# Report only named artifact classes and canonical digests, never private paths.
# A stored installed marker is diagnostic evidence, not qualification authority.
report_qualified_digest() {
  local artifact_name="$1" expected_hash="$2" artifact_path="$3" provenance="$4"
  local observed_hash=missing_or_unsafe command_status=not_run
  if [[ -f "$artifact_path" && ! -L "$artifact_path" ]]; then
    command_status=0
    observed_hash="$(hash_file "$artifact_path" 2>/dev/null)" ||
      command_status=$?
    if (( command_status != 0 )) || [[ ! "$observed_hash" =~ ^[0-9a-f]{64}$ ]]; then
      observed_hash=unavailable
    fi
  fi
  [[ "$command_status" == 0 && "$observed_hash" == "$expected_hash" ]] && return 0
  printf 'SWAPZ_PACKAGE_DIAGNOSTIC artifact=%s check=sha256 provenance=%s expected_sha256=%s observed_sha256=%s command_status=%s next=inspect_qualification_and_artifact_bytes_read_only retained_state=unchanged\n' \
    "$artifact_name" "$provenance" "$expected_hash" "$observed_hash" "$command_status" >&2
  return 1
}

query_dkms_status() {
  local output_name="$1"
  local output rc=0
  shift
  output="$("$dkms_bin" status "$@" 2>/dev/null)" || rc=$?
  (( rc == 0 )) || return "$rc"
  printf -v "$output_name" '%s' "$output"
}

# DKMS versions differ in slash/comma formatting. Require one exact record for
# our version and running kernel; a successful status command or substring is
# not evidence that this module was installed for this kernel.
dkms_status_exact_installed() {
  local report="$1" record architecture
  local -a lines
  [[ -n "$report" ]] || return 1
  mapfile -t lines <<< "$report"
  (( ${#lines[@]} == 1 )) || return 1
  record="${lines[0]}"
  case "$record" in
    "swapz/$version, $kernel_release, "*": installed")
      architecture="${record#"swapz/$version, $kernel_release, "}"
      ;;
    "swapz, $version, $kernel_release, "*": installed")
      architecture="${record#"swapz, $version, $kernel_release, "}"
      ;;
    *) return 1 ;;
  esac
  architecture="${architecture%: installed}"
  [[ "$architecture" =~ ^[A-Za-z0-9_+.-]+$ ]]
}

# --all must never erase a registration for another installed kernel.
# A -k status query alone hides those registrations.
dkms_status_single_kernel_scope() {
  local report="$1" record architecture
  local -a records=()
  [[ -n "$report" ]] || return 0
  mapfile -t records <<< "$report"
  (( ${#records[@]} == 1 )) || return 1
  record="${records[0]}"
  case "$record" in
    "swapz/$version: added"|"swapz, $version: added") return 0 ;;
    "swapz/$version, $kernel_release, "*)
      architecture="${record#"swapz/$version, $kernel_release, "}" ;;
    "swapz, $version, $kernel_release, "*)
      architecture="${record#"swapz, $version, $kernel_release, "}" ;;
    *) return 1 ;;
  esac
  [[ "$architecture" =~ ^[A-Za-z0-9_+.-]+:\ (installed|built)$ ]]
}

# Compressed module variants for nonrunning kernels cannot be silently lost.
other_kernel_module_candidates_absent() {
  local kernel_directory candidate suffix
  for kernel_directory in "$modules_root"/*; do
    [[ -d "$kernel_directory" || -L "$kernel_directory" ]] || continue
    [[ "$kernel_directory" != "$modules_root/$kernel_release" ]] || continue
    [[ ! -L "$kernel_directory" && ! -L "$kernel_directory/updates" &&
       ! -L "$kernel_directory/updates/dkms" ]] || return 1
    for suffix in "" .xz .zst .gz; do
      candidate="$kernel_directory/updates/dkms/dm-swapz.ko$suffix"
      [[ ! -e "$candidate" && ! -L "$candidate" ]] || return 1
    done
  done
}

assert_single_kernel_dkms_scope() {
  local all_kernel_status="" all_kernel_status_rc=0
  query_dkms_status all_kernel_status -m swapz -v "$version" ||
    all_kernel_status_rc=$?
  if (( all_kernel_status_rc != 0 )); then
    printf 'SWAPZ_PACKAGE_DIAGNOSTIC artifact=dkms_registration_scope check=all_kernel_status expected=current_kernel_only_or_added observed=probe_failed command_status=%s next=inspect_dkms_status_read_only retained_state=unchanged\n' \
      "$all_kernel_status_rc" >&2
    blocked "cannot inspect DKMS registrations across installed kernels"
  fi
  if ! dkms_status_single_kernel_scope "$all_kernel_status"; then
    printf 'SWAPZ_PACKAGE_DIAGNOSTIC artifact=dkms_registration_scope check=all_kernel_status expected=current_kernel_only_or_added observed=other_kernel_or_ambiguous command_status=0 next=inspect_dkms_status_read_only retained_state=unchanged\n' >&2
    blocked "other-kernel or ambiguous DKMS registrations; refusing --all"
  fi
  if ! other_kernel_module_candidates_absent; then
    printf 'SWAPZ_PACKAGE_DIAGNOSTIC artifact=dkms_module_image_set check=other_kernel_absence expected=no_other_kernel_module_images observed=stale_or_foreign_image command_status=0 next=inspect_installed_kernel_module_images_read_only retained_state=unchanged\n' >&2
    blocked "other-kernel DKMS module variants exist; refusing --all"
  fi
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
  [[ ! -L "$path" ]] || blocked "symlinked package destination"
}

for destination in "$srcbase" "$modules_root" "$modules_root/$kernel_release" "$prefix" \
    "$prefix/sbin" "$prefix/lib" "$prefix/libexec" "$prefix/lib/systemd" \
    "$unit_dir" "$generator_dir" "$installed_module_dir"; do
  if [[ -e "$destination" || -L "$destination" ]]; then
    reject_symlinked_destination "$destination"
    [[ -d "$destination" ]] || blocked "non-directory package destination"
    IFS=: read -r destination_uid destination_gid destination_mode < <(
      stat -c '%u:%g:%a' -- "$destination" 2>/dev/null
    ) || blocked "cannot inspect package destination"
    [[ "$destination_uid" == "$expected_installed_owner" &&
       "$destination_gid" == "$expected_installed_group" ]] ||
      blocked "unexpected package destination ownership"
    (( (8#$destination_mode & 8#022) == 0 )) ||
      blocked "writable package destination directory"
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

assert_no_primary_recovery_authority() {
  local operation="$1"
  [[ ! -e "$primary_state" && ! -L "$primary_state" ]] ||
    blocked "primary recovery state exists; preserve it during package $operation"
  if compgen -G "$primary_recovery_base/partition-*.active" >/dev/null; then
    blocked "a primary partition ownership marker exists; preserve the recovery path during package $operation"
  fi
}

verify_source_manifest() {
  [[ -f "$src/$source_manifest" && ! -L "$src/$source_manifest" ]] || return 1
  (cd "$src" && sha256sum --quiet -c "$source_manifest")
}

verify_binary_manifest() {
  [[ -f "$src/$binary_manifest" && ! -L "$src/$binary_manifest" ]] || return 1
  # Binary-manifest destinations are absolute. Propagate only verification
  # status so a refusal never exposes a private sandbox or install path.
  sha256sum --quiet -c "$src/$binary_manifest" >/dev/null 2>&1
}

verify_owned_legacy() {
  temporary_activation_paths_absent || return 1
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
  # Legacy identity does not weaken installed file ownership or path safety.
  # Without these checks a mode-tampered current package is accepted as legacy.
  local legacy_path
  for legacy_path in "$cli" "$boot_verifier" "$helper" "$primary_generator"; do
    installed_file_metadata "$legacy_path" 755 || return 1
  done
  for legacy_path in "$module_snapshot" "$mapper_service" "$boot_verifier_service" "$primary_swap"; do
    installed_file_metadata "$legacy_path" 644 || return 1
  done
  if [[ -e "$src/$qualification_marker" || -L "$src/$qualification_marker" ]]; then
    installed_file_metadata "$src/$qualification_marker" 644 || return 1
  fi
  for legacy_path in "${module_candidate_paths[@]}"; do
    if [[ "$legacy_path" != "$installed_module" ]] &&
       [[ -e "$legacy_path" || -L "$legacy_path" ]]; then
      return 1
    fi
  done
  if [[ -e "$installed_module" || -L "$installed_module" ]]; then
    installed_file_metadata "$installed_module" 644 || return 1
    verify_module_resolution || return 1
  fi
  # Both monitoring artifacts are optional only for older verified packages.
  if [[ -e "$runtime_health" || -L "$runtime_health" ||
        -e "$runtime_health_service" || -L "$runtime_health_service" ]]; then
    installed_file_metadata "$runtime_health" 755 || return 1
    installed_file_metadata "$runtime_health_service" 644 || return 1
  fi
  grep -Fxq "swapz:$version" "$src/$marker" || return 1
  verify_source_manifest && verify_binary_manifest
}

qualification_identity_digest_failure=0

verify_qualification_identity() {
  local -a identity_lines
  local source_sha report_sha cli_sha module_sha oracle_sha
  local build_source_sha build_source_clean

  [[ -f "$src/$qualification_marker" && ! -L "$src/$qualification_marker" ]] ||
    return 1
  mapfile -t identity_lines < "$src/$qualification_marker" || return 1
  (( ${#identity_lines[@]} == 8 )) || return 1
  [[ "${identity_lines[0]}" == 'schema=swapz-package-v1' &&
     "${identity_lines[1]}" == "version=$version" &&
     "${identity_lines[2]}" == "kernel_release=$kernel_release" &&
     "${identity_lines[3]}" == source_sha=* &&
     "${identity_lines[4]}" == qualification_report_sha256=* &&
     "${identity_lines[5]}" == swapzctl_sha256=* &&
     "${identity_lines[6]}" == module_sha256=* &&
     "${identity_lines[7]}" == oracle_sha256=* ]] || return 1

  source_sha="${identity_lines[3]#source_sha=}"
  report_sha="${identity_lines[4]#qualification_report_sha256=}"
  cli_sha="${identity_lines[5]#swapzctl_sha256=}"
  module_sha="${identity_lines[6]#module_sha256=}"
  oracle_sha="${identity_lines[7]#oracle_sha256=}"
  [[ "$source_sha" =~ ^[0-9a-f]{40}$ &&
     "$report_sha" =~ ^[0-9a-f]{64}$ &&
     "$cli_sha" =~ ^[0-9a-f]{64}$ &&
     "$module_sha" =~ ^[0-9a-f]{64}$ &&
     "$oracle_sha" =~ ^[0-9a-f]{64}$ ]] || return 1

  build_source_sha="$(sed -n 's/^#define SWAPZ_BUILD_SOURCE_SHA "\([0-9a-f]\{40\}\)"$/\1/p'     "$src/src/kernel/swapz-build-info.h")"
  build_source_clean="$(sed -n 's/^#define SWAPZ_BUILD_SOURCE_CLEAN \([01]\)$/\1/p'     "$src/src/kernel/swapz-build-info.h")"
  [[ "$build_source_sha" == "$source_sha" && "$build_source_clean" == 1 ]] ||
    return 1
  report_qualified_digest installed_swapzctl "$cli_sha" "$cli" \
      installed_marker_unverified ||
    { qualification_identity_digest_failure=1; return 1; }
  report_qualified_digest installed_roundtrip_oracle "$oracle_sha" "$helper" \
      installed_marker_unverified ||
    { qualification_identity_digest_failure=1; return 1; }
  report_qualified_digest installed_module_snapshot "$module_sha" "$module_snapshot" \
      installed_marker_unverified ||
    { qualification_identity_digest_failure=1; return 1; }
  report_qualified_digest installed_dm-swapz.ko "$module_sha" "$installed_module" \
      installed_marker_unverified ||
    { qualification_identity_digest_failure=1; return 1; }
}

module_candidates_absent() {
  local candidate
  for candidate in "${module_candidate_paths[@]}"; do
    [[ ! -e "$candidate" && ! -L "$candidate" ]] || return 1
  done
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

prepare_exact_module_restore() {
  local candidate count=0 rebuilt_module=""
  for candidate in "${module_candidate_paths[@]}"; do
    if [[ -e "$candidate" || -L "$candidate" ]]; then
      count=$((count + 1))
      rebuilt_module="$candidate"
    fi
  done
  [[ "$count" == 1 && -f "$rebuilt_module" && ! -L "$rebuilt_module" ]] ||
    return 1
  if [[ "$rebuilt_module" != "$installed_module" ]]; then
    rm -f -- "$rebuilt_module" || return 1
  fi
}

module_resolution_observed=not_checked
module_resolution_command_status=0

verify_module_resolution() {
  local module_lookup_output resolved_module
  module_resolution_observed=not_checked
  module_resolution_command_status=0

  if module_lookup_output="$(modinfo -n dm_swapz 2>/dev/null)"; then
    :
  else
    module_resolution_command_status=$?
    module_resolution_observed=probe_failed
    return 1
  fi
  if [[ -z "$module_lookup_output" || "$module_lookup_output" == *$'\n'* ]]; then
    module_resolution_observed=invalid_output
    return 1
  fi
  if resolved_module="$(readlink -f -- "$module_lookup_output" 2>/dev/null)"; then
    :
  else
    module_resolution_command_status=$?
    module_resolution_observed=canonicalization_failed
    return 1
  fi
  if [[ -z "$resolved_module" || "$resolved_module" != "$installed_module" ]]; then
    module_resolution_observed=foreign_path
    return 1
  fi
  module_resolution_observed=owned_path
}

report_module_resolution_failure() {
  printf 'SWAPZ_PACKAGE_DIAGNOSTIC artifact=installed_dm-swapz.ko check=module_lookup expected=qualified_owned_current_kernel_image observed=%s command_status=%s next=inspect_modinfo_module_path_read_only retained_state=unchanged\n' \
    "$module_resolution_observed" "$module_resolution_command_status" >&2
}

verify_owned() {
  qualification_identity_digest_failure=0
  verify_owned_legacy || return 1
  verify_installed_module_set || return 1
  [[ -f "$src/$qualification_marker" && ! -L "$src/$qualification_marker" &&
     -f "$installed_module" && ! -L "$installed_module" ]] || return 1
  installed_file_metadata "$src/$qualification_marker" 644 || return 1
  installed_file_metadata "$cli" 755 || return 1
  installed_file_metadata "$boot_verifier" 755 || return 1
  installed_file_metadata "$runtime_health" 755 || return 1
  installed_file_metadata "$helper" 755 || return 1
  installed_file_metadata "$module_snapshot" 644 || return 1
  installed_file_metadata "$primary_generator" 755 || return 1
  installed_file_metadata "$mapper_service" 644 || return 1
  installed_file_metadata "$boot_verifier_service" 644 || return 1
  installed_file_metadata "$runtime_health_service" 644 || return 1
  installed_file_metadata "$primary_swap" 644 || return 1
  installed_file_metadata "$installed_module" 644 || return 1
  verify_qualification_identity || return 1
  verify_binary_manifest
}

# Called only on a definitively rejected existing install. Recorded digests
# help explain the rejection but cannot make an unverified marker authoritative.
report_existing_package_drift() {
  local stored_module_sha stored_cli_sha
  installed_directory_metadata "$src" 755 || return 0
  installed_file_metadata "$src/$qualification_marker" 644 || return 0
  stored_module_sha="$(sed -n 's/^module_sha256=\([0-9a-f]\{64\}\)$/\1/p' "$src/$qualification_marker" 2>/dev/null || true)"
  stored_cli_sha="$(sed -n 's/^swapzctl_sha256=\([0-9a-f]\{64\}\)$/\1/p' "$src/$qualification_marker" 2>/dev/null || true)"
  if (( qualification_identity_digest_failure == 0 )); then
    if [[ "$stored_module_sha" =~ ^[0-9a-f]{64}$ ]]; then
      report_qualified_digest installed_dm-swapz.ko "$stored_module_sha" "$installed_module" installed_marker_unverified || true
      report_qualified_digest installed_module_snapshot "$stored_module_sha" "$module_snapshot" installed_marker_unverified || true
    fi
    if [[ "$stored_cli_sha" =~ ^[0-9a-f]{64}$ ]]; then
      report_qualified_digest installed_swapzctl "$stored_cli_sha" "$cli" installed_marker_unverified || true
    fi
  fi
  if [[ -f "$installed_module" && ! -L "$installed_module" ]] &&
     ! verify_module_resolution; then
    report_module_resolution_failure
  fi
  if ! verify_source_manifest >/dev/null 2>&1; then
    printf 'SWAPZ_PACKAGE_DIAGNOSTIC artifact=installed_kernel_sources check=source_manifest expected=recorded_source_hashes observed=mismatch_or_unavailable next=inspect_source_manifest_read_only retained_state=unchanged\n' >&2
  fi
}

# An interrupted atomic CLI publish/restore may leave a separate executable.
# It is not a valid installed package, even when the named CLI is absent.
temporary_activation_paths_absent() {
  local -a pending_cli=()
  shopt -s nullglob
  pending_cli=("$cli_dir"/.swapzctl.publish.* "$cli_dir"/.swapzctl.restore.*)
  shopt -u nullglob
  (( ${#pending_cli[@]} == 0 ))
}

activation_entry_points_absent() {
  local activation_path
  temporary_activation_paths_absent || return 1
  for activation_path in "$cli" "$boot_verifier" "$runtime_health" "$helper"       "$module_snapshot" "$primary_generator" "$mapper_service"       "$boot_verifier_service" "$runtime_health_service" "$primary_swap"; do
    [[ ! -e "$activation_path" && ! -L "$activation_path" ]] || return 1
  done
}

cleanup_temporary_activation_files() {
  local candidate
  local -a pending_cli=()
  shopt -s nullglob
  pending_cli=("$cli_dir"/.swapzctl.publish.* "$cli_dir"/.swapzctl.restore.*)
  shopt -u nullglob
  for candidate in "${pending_cli[@]}"; do
    installed_file_metadata "$candidate" 755 || return 1
    rm -f -- "$candidate" || return 1
  done
  durable_package_paths "$cli_dir"
}

package_paths_present() {
  temporary_activation_paths_absent || return 0
  local candidate
  if [[ -e "$src" || -L "$src" || -e "$cli" || -L "$cli" ||
        -e "$boot_verifier" || -L "$boot_verifier" ||
        -e "$runtime_health" || -L "$runtime_health" ||
        -e "$helper_dir" || -L "$helper_dir" ||
        -e "$primary_generator" || -L "$primary_generator" ||
        -e "$mapper_service" || -L "$mapper_service" ||
        -e "$boot_verifier_service" || -L "$boot_verifier_service" ||
        -e "$runtime_health_service" || -L "$runtime_health_service" ||
        -e "$primary_swap" || -L "$primary_swap" ]]; then
    return 0
  fi
  for candidate in "${module_candidate_paths[@]}"; do
    [[ -e "$candidate" || -L "$candidate" ]] && return 0
  done
  return 1
}

# Rollback helpers are frequently called from if/|| contexts, where Bash
# suppresses errexit inside the entire function. Propagate destructive failures
# explicitly so a later best-effort command cannot mask them.
cleanup_activation_files() {
  # Package paths can include a private test root. Keep command diagnostics
  # private while preserving the exact status for the phase-aware caller.
  rm -f -- "$cli" "$boot_verifier" "$runtime_health" "$helper" "$module_snapshot" \
    "$primary_generator" "$mapper_service" "$boot_verifier_service" \
    "$runtime_health_service" "$primary_swap" 2>/dev/null || return $?
  rmdir -- "$helper_dir" 2>/dev/null || true
}

cleanup_source_files() {
  if [[ -d "$src" && ! -L "$src" ]]; then
    rm -rf -- "$src" 2>/dev/null || return $?
  elif [[ -L "$src" ]]; then
    rm -f -- "$src" 2>/dev/null || return $?
  fi
  return 0
}

cleanup_package_files() {
  cleanup_activation_files || return $?
  cleanup_source_files || return $?
}

# Failure paths must report unsuccessful quarantine/journaling rather than
# hide a second failure behind the original command status.
quarantine_activation() {
  local cleanup_status=0 durability_status=0
  # Deactivation is part of the durable recovery state, not merely an
  # in-memory best effort. Sync every directory whose entry set may change so
  # a power loss cannot resurrect an activation entry after rollback failure.
  cleanup_activation_files || cleanup_status=$?
  durable_package_paths "$cli_dir" "$prefix/libexec" "$unit_dir" "$generator_dir" ||
    durability_status=$?
  if (( cleanup_status != 0 )); then
    printf 'BLOCKED: activation quarantine failed (status %d); manual intervention required\n' "$cleanup_status" >&2
  fi
  if (( durability_status != 0 )); then
    printf 'BLOCKED: activation quarantine durability failed (status %d); manual intervention required\n' "$durability_status" >&2
  fi
  (( cleanup_status == 0 )) || return "$cleanup_status"
  return "$durability_status"
}

record_incomplete_rollback() {
  local journal_status=0
  persist_transaction_state rollback-incomplete || journal_status=$?
  if (( journal_status != 0 )); then
    printf 'BLOCKED: rollback-incomplete journal update failed (status %d); original recovery record retained\n' "$journal_status" >&2
  fi
  return "$journal_status"
}

# Sync payloads and their directory entries before journaling publication.
# A missing path records a deletion; no symlink or special file is followed.
durable_package_paths() {
  python3 - "$@" <<'PY'
import errno
import os
import stat
import sys
from pathlib import Path

paths = set()
for argument in sys.argv[1:]:
    path = Path(argument)
    if not path.is_absolute() or path.is_symlink():
        raise SystemExit("unsafe package durability path")
    if path.exists():
        paths.add(path)
    # Each newly created directory also needs its *parent* entry synced.
    # Walk every ancestor, not just the leaf's directory: install -d and
    # DKMS can create multiple nested directories in a single operation.
    directory = path.parent
    while True:
        if directory.is_symlink():
            raise SystemExit("symlinked package durability parent")
        # DKMS may fail before creating updates/dkms. For a deletion,
        # synchronize the nearest existing ancestor without assuming that
        # every intermediate component exists.
        if directory.exists():
            if not directory.is_dir():
                raise SystemExit("unsafe package durability parent")
            paths.add(directory)
        elif directory == directory.parent:
            raise SystemExit("missing package durability root")
        if directory == directory.parent:
            break
        directory = directory.parent

for path in sorted(paths, key=lambda candidate: len(candidate.parts), reverse=True):
    metadata = path.lstat()
    if not (stat.S_ISREG(metadata.st_mode) or stat.S_ISDIR(metadata.st_mode)):
        raise SystemExit("unsafe package durability entry")
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW
    if stat.S_ISDIR(metadata.st_mode):
        flags |= os.O_DIRECTORY
    descriptor = os.open(path, flags)
    try:
        if (os.environ.get("SWAPZ_PACKAGE_RECOVERY_ACTIVE") == "1"
                and os.environ.get("SWAPZ_TEST_RECOVERY_IO_FAILURE") == "fsync"):
            raise OSError(errno.EIO, "injected recovery fsync failure")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
PY
}

# Transaction state stops being recovery authority only after the verified final
# package state exists. First rename it atomically out of the recovery namespace
# and fsync that authority change; only then recursively delete the residue.
# A partial delete can therefore never masquerade as a recoverable journal.
remove_transaction_record() {
  local cleanup_failure="${SWAPZ_TEST_TRANSACTION_CLEANUP_FAILURE:-never}"
  local transaction_name cleanup_path
  if [[ -n "$test_root" && "$cleanup_failure" == remove ]]; then
    return 73
  fi
  transaction_name="${transaction_dir##*/}"
  [[ "$transaction_name" =~ ^swapz-(package|uninstall)[.][A-Za-z0-9]{8}$ ]] ||
    return 75
  [[ "$transaction_dir" == "$transaction_parent/$transaction_name" ]] ||
    return 75
  cleanup_path="$transaction_parent/.finalized-$transaction_name"
  [[ ! -e "$cleanup_path" && ! -L "$cleanup_path" ]] || return 75
  mv -- "$transaction_dir" "$cleanup_path" 2>/dev/null || return $?
  if [[ -n "$test_root" && ${SWAPZ_TEST_PAUSE_TRANSACTION_CLEANUP:-0} == 1 ]]; then
    : > "$sandbox/package-cleanup.ready"
    sleep 30
  fi
  if [[ -n "$test_root" && "$cleanup_failure" == fsync ]]; then
    return 74
  fi
  durable_package_paths "$transaction_parent" || return $?
  rm -rf -- "$cleanup_path" 2>/dev/null || return $?
  durable_package_paths "$transaction_parent"
}

# Finalized tombstones are no longer recovery authority, but repeated hard
# interruptions must not accumulate private rollback snapshots indefinitely.
cleanup_finalized_transaction_records() {
  local tombstone tombstone_name removed_any=0
  local -a tombstones=()
  shopt -s nullglob
  tombstones=("$transaction_parent"/.finalized-swapz-package.*
              "$transaction_parent"/.finalized-swapz-uninstall.*)
  shopt -u nullglob
  for tombstone in "${tombstones[@]}"; do
    tombstone_name="${tombstone##*/}"
    [[ "$tombstone_name" =~ ^[.]finalized-swapz-(package|uninstall)[.][A-Za-z0-9]{8}$ ]] ||
      return 1
    rm -rf -- "$tombstone" 2>/dev/null || return $?
    removed_any=1
  done
  (( removed_any == 0 )) || durable_package_paths "$transaction_parent"
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
  cleanup_finalized_transaction_records ||
    blocked "cannot clean finalized package transaction records"
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
    blocked "incomplete package transaction retained (explicit recover required)"
}

persist_transaction_state() {
  local phase="$1"
  # The active operation owns this phase until the next durable transition.
  transaction_phase="$phase"
  if [[ -n "$test_root" && ${SWAPZ_TEST_FAIL_TRANSACTION_PHASE:-never} == "$phase" ]]; then
    return 1
  fi
  python3 - "$transaction_dir" "$phase" "$version" "$kernel_release" "$action" <<'PY' || return 1
import errno
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
operation = sys.argv[5]
if operation not in ("install", "uninstall"):
    raise SystemExit("unknown package transaction")
backup = transaction / "backup"
# Reject swapped or permission-weakened directories before *any* journal write.
for directory in (transaction.parent, transaction, backup):
    if directory.is_symlink() or not directory.is_dir():
        raise SystemExit("unsafe package transaction directory")
    metadata = directory.stat()
    if (metadata.st_uid != os.geteuid()
            or metadata.st_gid != os.getegid()
            or stat.S_IMODE(metadata.st_mode) != 0o700):
        raise SystemExit("unsafe package transaction directory metadata")
allowed_phases = {
    "activation-files-removed",
    "adding-dkms",
    "building-dkms",
    "cli-published",
    "committed",
    "creating-source",
    "depmod-complete",
    "depmod-pending",
    "dkms-added",
    "dkms-built",
    "dkms-installed",
    "dkms-removed",
    "installed-module-removed",
    "installing-dkms",
    "module-promoted",
    "package-files-published",
    "prepared",
    "promoting-qualified-module",
    "publishing-cli",
    "publishing-package-files",
    "removing-activation-files",
    "removing-dkms",
    "removing-installed-module",
    "removing-source",
    "rollback-backend-restored",
    "rollback-cli-restored",
    "rollback-files-restored",
    "rollback-incomplete",
    "rollback-started",
    "rollback-systemd-reloaded",
    "rolled-back",
    "source-created",
    "source-removed",
    "systemd-reload-complete",
    "systemd-reload-pending",
}
if phase not in allowed_phases:
    raise SystemExit("invalid package transaction phase")
if os.environ.get("SWAPZ_PACKAGE_RECOVERY_ACTIVE") == "1":
    failure = os.environ.get("SWAPZ_TEST_RECOVERY_IO_FAILURE", "")
    if failure in ("enospc", "eio"):
        error_number = errno.ENOSPC if failure == "enospc" else errno.EIO
        raise OSError(error_number, "injected recovery journal write failure")
final = transaction / "state.json"
temporary = transaction / "state.json.tmp"
# The prepared state is the first durable point after the complete rollback
# snapshot is copied. Installer code does not modify the snapshot afterward.
# Later phase updates must still hash and metadata-check every entry, but
# re-fsyncing unchanged files and parent directories adds no durability.
snapshot_previously_journaled = final.exists() or final.is_symlink()

entries = []
# Fsync the transaction parent too: the rollback directory entry itself must
# survive before any installed artifact is removed.
# Include the parent of the transaction *root* too: creating
# /var/lib/swapz-package-transactions is not durable merely by fsyncing
# that newly created directory. Its entry lives in /var/lib.
directories = {backup, transaction, transaction.parent,
               transaction.parent.parent}
for path in sorted(backup.rglob("*")):
    if path.is_symlink():
        raise SystemExit("unsafe backup symlink")
    metadata = path.stat()
    if path.is_dir():
        directories.add(path)
        continue
    if not path.is_file():
        raise SystemExit("unsafe backup entry")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
        if not snapshot_previously_journaled:
            os.fsync(stream.fileno())
    relative = str(path.relative_to(backup))
    if len(relative) > 4096 or len(entries) >= 1024:
        raise SystemExit("package rollback snapshot exceeds manifest bounds")
    entries.append({
        "path": relative,
        "sha256": digest.hexdigest(),
        "size": metadata.st_size,
        "mode": stat.S_IMODE(metadata.st_mode),
        "uid": metadata.st_uid,
        "gid": metadata.st_gid,
    })

if not snapshot_previously_journaled:
    for directory in sorted(directories, key=lambda item: len(item.parts), reverse=True):
        descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

state = {
    "schema": f"swapz-package-{operation}-v1",
    "phase": phase,
    "version": version,
    "kernel_release": kernel_release,
    "backup_files": entries,
}
# Never silently rebaseline a backed-up file after the prepared checkpoint.
if final.exists() or final.is_symlink():
    if final.is_symlink() or not final.is_file():
        raise SystemExit("unsafe previous package journal")
    previous_metadata = final.stat()
    if (previous_metadata.st_uid != os.geteuid()
            or previous_metadata.st_gid != os.getegid()
            or stat.S_IMODE(previous_metadata.st_mode) != 0o600
            or previous_metadata.st_nlink != 1):
        raise SystemExit("unsafe previous package journal metadata")
    if previous_metadata.st_size > 1024 * 1024:
        raise SystemExit("oversized previous package journal")
    previous_bytes = final.read_bytes()
    previous = json.loads(previous_bytes)
    if (not isinstance(previous, dict)
            or set(previous) != set(state)
            or previous.get("phase") not in allowed_phases
            or previous_bytes != (json.dumps(previous, sort_keys=True,
                                             separators=(",", ":")) + "\n").encode()):
        raise SystemExit("noncanonical previous package journal")
    for field in ("schema", "version", "kernel_release", "backup_files"):
        if previous.get(field) != state[field]:
            raise SystemExit(f"package rollback snapshot changed: {field}")
state_bytes = (json.dumps(state, sort_keys=True, separators=(",", ":")) + "\n").encode()
if len(state_bytes) > 1024 * 1024:
    raise SystemExit("package journal exceeds size bound")
# A failed rename can leave a fully written temp journal. Only retry when
# its metadata and exact bytes match this independently verified transition.
# Partial writes and symlinks stay quarantined, never rebaselined.
if temporary.exists() or temporary.is_symlink():
    metadata = temporary.lstat()
    if (not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or metadata.st_gid != os.getegid()
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or metadata.st_nlink != 1
            or metadata.st_size != len(state_bytes)
            or temporary.read_bytes() != state_bytes):
        raise SystemExit("unsafe incomplete package journal temp")
    temporary.unlink()
    sync_descriptor = os.open(transaction, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(sync_descriptor)
    finally:
        os.close(sync_descriptor)
temporary_flags = (os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                   os.O_NOFOLLOW | os.O_CLOEXEC)
temporary_descriptor = os.open(temporary, temporary_flags, 0o600)
with os.fdopen(temporary_descriptor, "w", encoding="utf-8") as stream:
    # Create the private journal temp exclusively without following a stale
    # path, then make its exact mode durable with the journal contents.
    os.fchmod(stream.fileno(), 0o600)
    stream.write(state_bytes.decode("utf-8"))
    stream.flush()
    os.fsync(stream.fileno())
if (os.environ.get("SWAPZ_PACKAGE_RECOVERY_ACTIVE") == "1"
        and os.environ.get("SWAPZ_TEST_RECOVERY_IO_FAILURE") == "rename"):
    raise OSError(errno.EIO, "injected recovery journal rename failure")
os.replace(temporary, final)
if (os.environ.get("SWAPZ_PACKAGE_TEST_ROOT")
        and os.environ.get(
            "SWAPZ_TEST_FAIL_TRANSACTION_AFTER_RENAME_PHASE", "never") == phase):
    raise OSError(errno.EIO, "injected post-rename package journal failure")
descriptor = os.open(transaction, os.O_RDONLY | os.O_DIRECTORY)
try:
    os.fsync(descriptor)
finally:
    os.close(descriptor)
PY
  # Only a fully completed state-file replacement plus directory fsync owns a
  # durable phase. Set this before the crash checkpoint so a trapped signal at
  # that checkpoint cannot misclassify the journal as uncertain.
  durable_transaction_phase="$phase"
  # Hermetic crash injection occurs only after the journal and parent fsync.
  # SIGKILL here models a power loss without executing Bash rollback traps.
  if [[ -n "$test_root" && ${SWAPZ_TEST_PAUSE_AFTER:-never} == "$phase" ]]; then
    : > "$sandbox/package-checkpoint.ready"
    sleep 30
  fi
}

verify_transaction_snapshot() {
  python3 - "$transaction_dir" "$action" "$version" "$kernel_release" <<'PY'
import errno
import hashlib
import json
import os
import stat
import sys
from pathlib import Path

transaction = Path(sys.argv[1])
operation = sys.argv[2]
version = sys.argv[3]
kernel_release = sys.argv[4]
backup = transaction / "backup"
journal = transaction / "state.json"
if (transaction.parent.is_symlink() or transaction.is_symlink()
        or backup.is_symlink() or not backup.is_dir() or journal.is_symlink()
        or not journal.is_file()):
    raise SystemExit("missing or unsafe package rollback snapshot")
for directory in (transaction.parent, transaction, backup):
    metadata = directory.stat()
    if (metadata.st_uid != os.geteuid()
            or metadata.st_gid != os.getegid()
            or stat.S_IMODE(metadata.st_mode) != 0o700):
        raise SystemExit("unsafe package rollback directory metadata")
journal_metadata = journal.stat()
if (journal_metadata.st_uid != os.geteuid()
        or journal_metadata.st_gid != os.getegid()
        or stat.S_IMODE(journal_metadata.st_mode) != 0o600
        or journal_metadata.st_nlink != 1):
    raise SystemExit("unsafe package rollback journal metadata")
if journal_metadata.st_size > 1024 * 1024:
    raise SystemExit("oversized package rollback journal")
encoded_state = journal.read_bytes()
state = json.loads(encoded_state)
allowed_phases = {
    "activation-files-removed",
    "adding-dkms",
    "building-dkms",
    "cli-published",
    "committed",
    "creating-source",
    "depmod-complete",
    "depmod-pending",
    "dkms-added",
    "dkms-built",
    "dkms-installed",
    "dkms-removed",
    "installed-module-removed",
    "installing-dkms",
    "module-promoted",
    "package-files-published",
    "prepared",
    "promoting-qualified-module",
    "publishing-cli",
    "publishing-package-files",
    "removing-activation-files",
    "removing-dkms",
    "removing-installed-module",
    "removing-source",
    "rollback-backend-restored",
    "rollback-cli-restored",
    "rollback-files-restored",
    "rollback-incomplete",
    "rollback-started",
    "rollback-systemd-reloaded",
    "rolled-back",
    "source-created",
    "source-removed",
    "systemd-reload-complete",
    "systemd-reload-pending",
}
if not isinstance(state, dict):
    raise SystemExit("noncanonical package rollback journal type")
# Reject nonsensical operation/phase pairings, even if rehashed as canonical.
install_only = {
    "adding-dkms", "building-dkms", "cli-published", "creating-source",
    "dkms-added", "dkms-built", "dkms-installed", "installing-dkms",
    "module-promoted", "package-files-published", "promoting-qualified-module",
    "publishing-cli", "publishing-package-files", "source-created",
}
uninstall_only = {"installed-module-removed", "removing-installed-module"}
if (operation == "uninstall" and state.get("phase") in install_only
        or operation == "install" and state.get("phase") in uninstall_only):
    raise SystemExit("journal phase does not belong to this package operation")
if (not isinstance(state, dict) or set(state) != {
        "schema", "phase", "version", "kernel_release", "backup_files"}
        or state.get("phase") not in allowed_phases
        or encoded_state != (json.dumps(state, sort_keys=True,
                                        separators=(",", ":")) + "\n").encode()):
    raise SystemExit("noncanonical package rollback journal")
if (state.get("schema") != f"swapz-package-{operation}-v1"
        or state.get("version") != version
        or state.get("kernel_release") != kernel_release):
    raise SystemExit("package rollback journal does not match this operation")
entries = state.get("backup_files")
if not isinstance(entries, list) or len(entries) > 1024:
    raise SystemExit("invalid rollback file manifest")
seen = set()
for entry in entries:
    relative = entry.get("path") if isinstance(entry, dict) else None
    if (not isinstance(relative, str) or not relative or len(relative) > 4096
            or relative != Path(relative).as_posix()
            or Path(relative).is_absolute()
            or any(part in (".", "..") for part in Path(relative).parts)
            or relative in seen):
        raise SystemExit("invalid rollback file path")
    seen.add(relative)
    path = backup / relative
    if path.is_symlink() or not path.is_file():
        raise SystemExit("missing or substituted rollback file")
    metadata = path.stat()
    if (entry.get("size") != metadata.st_size
            or entry.get("mode") != stat.S_IMODE(metadata.st_mode)
            or entry.get("uid") != metadata.st_uid
            or entry.get("gid") != metadata.st_gid):
        raise SystemExit("rollback file metadata changed")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    if entry.get("sha256") != digest.hexdigest():
        raise SystemExit("rollback file digest changed")
actual = set()
for path in backup.rglob("*"):
    if path.is_symlink():
        raise SystemExit("substituted rollback entry")
    if path.is_file():
        actual.add(str(path.relative_to(backup)))
        if len(actual) > 1024:
            raise SystemExit("rollback snapshot file count exceeds bound")
    elif path.is_dir():
        metadata = path.stat()
        if (metadata.st_uid != os.geteuid()
                or metadata.st_gid != os.getegid()
                or stat.S_IMODE(metadata.st_mode) & 0o022):
            raise SystemExit("unsafe rollback subdirectory metadata")
    else:
        raise SystemExit("unexpected rollback entry type")
if actual != seen:
    raise SystemExit("rollback file set changed")
for path in transaction.rglob("*"):
    if path.is_symlink():
        raise SystemExit("symlinked package transaction entry")
PY
}


# A verified hash journal protects bytes, but a recovery snapshot must also be
# a *complete original package*, not an arbitrary set of hash-consistent files.
verify_recovery_backup() {
  python3 - "$backup_dir" "$version" "$kernel_release" "$installed_module" \
      "$cli" "$boot_verifier" "$runtime_health" "$helper" "$module_snapshot" \
      "$primary_generator" "$mapper_service" "$boot_verifier_service" \
      "$runtime_health_service" "$primary_swap" <<'PY'
import hashlib
import os
import re
import stat
import sys
from pathlib import Path

backup = Path(sys.argv[1])
version, kernel_release, installed_module = sys.argv[2:5]
package_files = sys.argv[5:]
source = backup / "source"
file_list = backup / "file-paths"
image = backup / "installed-module"
if not any(backup.iterdir()):
    print("none")
    raise SystemExit(0)
if not (source.is_dir() and (backup / "files").is_dir()
        and file_list.is_file() and image.is_file()):
    raise SystemExit("recovery backup lacks complete source, file map or module")
expected_directories = {"source", "source/src", "source/src/kernel", "files"}
actual_directories = {str(path.relative_to(backup))
                      for path in backup.rglob("*") if path.is_dir()}
if actual_directories != expected_directories:
    raise SystemExit("recovery backup directory layout differs")

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def check_file(path, mode):
    if path.is_symlink() or not path.is_file():
        raise SystemExit("unsafe recovery backup file")
    metadata = path.stat()
    if (metadata.st_uid != os.geteuid()
            or metadata.st_gid != os.getegid()
            or stat.S_IMODE(metadata.st_mode) != mode
            or metadata.st_nlink != 1):
        raise SystemExit("wrong recovery backup provenance")

source_files = {
    str(path.relative_to(source)): path
    for path in source.rglob("*") if path.is_file()
}
required_source = {
    "dkms.conf", ".swapz-owned", ".swapz-sources.sha256",
    ".swapz-binaries.sha256", "src/kernel/VERSION", "src/kernel/Makefile",
}
if not required_source <= source_files.keys():
    raise SystemExit("recovery source is incomplete")
for relative, path in source_files.items():
    check_file(path, 0o644)
    if relative not in required_source and relative != ".swapz-qualification" \
            and not re.fullmatch(r"src/kernel/[A-Za-z0-9_.+-]+\.[ch]", relative):
        raise SystemExit("unexpected recovery source file")
if source_files[".swapz-owned"].read_bytes() != f"swapz:{version}\n".encode():
    raise SystemExit("recovery source ownership marker differs")

source_manifest = {}
for line in source_files[".swapz-sources.sha256"].read_text().splitlines():
    match = re.fullmatch(r"([0-9a-f]{64})  ([A-Za-z0-9_.+/-]+)", line)
    if not match or match[2] in source_manifest or \
            match[2] not in source_files:
        raise SystemExit("noncanonical recovery source manifest")
    source_manifest[match[2]] = match[1]
if set(source_manifest) != set(source_files) - {
        ".swapz-owned", ".swapz-sources.sha256", ".swapz-binaries.sha256"}:
    raise SystemExit("recovery source manifest is incomplete")
for relative, expected_hash in source_manifest.items():
    if digest(source_files[relative]) != expected_hash:
        raise SystemExit("recovery source provenance digest differs")

check_file(file_list, 0o644)
check_file(image, 0o644)
paths = file_list.read_text().splitlines()
legacy_files = [path for index, path in enumerate(package_files)
                if index not in (2, 8)]
if paths not in (package_files, legacy_files):
    raise SystemExit("noncanonical recovery destination map")
for path in paths:
    if not path.startswith("/") or ".." in Path(path).parts:
        raise SystemExit("unsafe recovery destination")
expected_backups = {
    "installed-module", "file-paths",
    *("files/" + hashlib.sha256(path.encode()).hexdigest()
      for path in paths),
    *("source/" + relative for relative in source_files),
}
actual_backups = {str(path.relative_to(backup))
                  for path in backup.rglob("*") if path.is_file()}
if actual_backups != expected_backups:
    raise SystemExit("unexpected recovery backup contents")

binary_manifest = {}
for line in source_files[".swapz-binaries.sha256"].read_text().splitlines():
    # GNU sha256sum prefixes the digest with '\\' and escapes backslashes in
    # filenames (notably the literal systemd '\\x2d' swap unit). Decode only
    # its canonical spelling, then compare the exact round-trip representation.
    match = re.fullmatch(r"(\\?)([0-9a-f]{64})  (/[^\r\n]+)", line)
    if not match:
        raise SystemExit("noncanonical recovery binary manifest")
    prefix, expected_hash, encoded_path = match.groups()
    if prefix:
        # Decode escapes in pairs. A stray backslash fails the canonical
        # round trip below; a doubled one is never treated as a stray.
        path = re.sub(r"\\(\\|n)",
                      lambda escaped: "\\" if escaped[1] == "\\" else "\n",
                      encoded_path)
    else:
        path = encoded_path
    canonical_path = path.replace("\\", r"\\").replace("\n", r"\n")
    canonical_prefix = "\\" if canonical_path != path else ""
    if (line != f"{canonical_prefix}{expected_hash}  {canonical_path}"
            or path in binary_manifest):
        raise SystemExit("noncanonical recovery binary manifest")
    binary_manifest[path] = expected_hash
if set(binary_manifest) != set(paths) | {installed_module}:
    raise SystemExit("recovery binary manifest destination mismatch")
for path in paths:
    saved_file = backup / "files" / hashlib.sha256(path.encode()).hexdigest()
    check_file(saved_file, 0o755 if path in (
        package_files[0], package_files[1], package_files[2],
        package_files[3], package_files[5]) else 0o644)
    if digest(saved_file) != binary_manifest[path]:
        raise SystemExit("recovery binary provenance digest differs")
if digest(image) != binary_manifest[installed_module]:
    raise SystemExit("recovery kernel module digest differs")

qualification = source / ".swapz-qualification"
if qualification.exists() or qualification.is_symlink():
    check_file(qualification, 0o644)
    identity = qualification.read_text().splitlines()
    if (len(identity) != 8 or identity[:3] != [
            "schema=swapz-package-v1", f"version={version}",
            f"kernel_release={kernel_release}"]):
        raise SystemExit("recovery qualification identity differs")
    required_fields = {
        "source_sha": 40, "qualification_report_sha256": 64,
        "swapzctl_sha256": 64, "module_sha256": 64, "oracle_sha256": 64,
    }
    for line, (field, width) in zip(identity[3:], required_fields.items()):
        if not re.fullmatch(field + r"=[0-9a-f]{" + str(width) + r"}", line):
            raise SystemExit("malformed recovery qualification identity")
    if (identity[5] != "swapzctl_sha256=" + binary_manifest[package_files[0]]
            or identity[6] != "module_sha256=" + digest(image)
            or identity[7] != "oracle_sha256=" +
                binary_manifest[package_files[3]]):
        raise SystemExit("wrong recovery qualification provenance")
    print("current")
else:
    print("legacy")
PY
}

backup_verified_package_for_uninstall() {
  local file backup_key
  backup_dir="$transaction_dir/backup"
  mkdir -m0700 "$backup_dir" "$backup_dir/source" "$backup_dir/source/src" \
    "$backup_dir/source/src/kernel" "$backup_dir/files"
  cp -a -- "$src/dkms.conf" "$src/$marker" "$src/$qualification_marker" \
    "$src/$source_manifest" "$src/$binary_manifest" "$backup_dir/source/"
  cp -a -- "$src/src/kernel/VERSION" "$src/src/kernel/Makefile" \
    "$src"/src/kernel/*.c "$src"/src/kernel/*.h "$backup_dir/source/src/kernel/"
  for file in "$cli" "$boot_verifier" "$runtime_health" "$helper" "$module_snapshot" \
      "$primary_generator" "$mapper_service" "$boot_verifier_service" \
      "$runtime_health_service" "$primary_swap"; do
    backup_key="$(hash_path_key "$file")" || return $?
    cp -a -- "$file" "$backup_dir/files/$backup_key" || return $?
  done
  printf '%s\n' \
    "$cli" "$boot_verifier" "$runtime_health" "$helper" "$module_snapshot" \
    "$primary_generator" "$mapper_service" "$boot_verifier_service" \
    "$runtime_health_service" "$primary_swap" > "$backup_dir/file-paths"
  cp -a -- "$installed_module" "$backup_dir/installed-module"
}

restore_uninstall_file_backups_except_cli() {
  local path digest backup_path
  [[ -f "$backup_dir/file-paths" && ! -L "$backup_dir/file-paths" ]] || return 1
  while IFS= read -r path; do
    [[ "$path" == "$cli" ]] && continue
    digest="$(hash_path_key "$path")" || return $?
    backup_path="$backup_dir/files/$digest"
    [[ -f "$backup_path" && ! -L "$backup_path" ]] || return 1
    install -d -m0755 "$(dirname "$path")" || return 1
    cp -a -- "$backup_path" "$path" || return 1
    cmp -s "$backup_path" "$path" || return 1
  done < "$backup_dir/file-paths"
}

restore_uninstall_cli_backup() {
  local digest backup_path temporary_cli
  digest="$(hash_path_key "$cli")" || return $?
  backup_path="$backup_dir/files/$digest"
  [[ -f "$backup_path" && ! -L "$backup_path" ]] || return 1
  install -d -m0755 "$cli_dir" || return 1
  temporary_cli="$cli_dir/.swapzctl.restore.$$"
  [[ ! -e "$temporary_cli" && ! -L "$temporary_cli" ]] || return 1
  install -m0755 "$backup_path" "$temporary_cli" || return 1
  cmp -s "$backup_path" "$temporary_cli" || {
    rm -f -- "$temporary_cli"
    return 1
  }
  mv -f -- "$temporary_cli" "$cli" || return 1
}

durable_committed_transaction_record() {
  # persist_transaction_state sets transaction_phase before writing, so the
  # in-memory phase alone is not authority. The canonical journal must itself
  # be durable and say committed. Final-state checks and durability precede
  # that transition; a later signal must never reverse an accepted commit just
  # because a read-only DKMS/status probe is temporarily unavailable.
  verify_transaction_snapshot >/dev/null 2>&1 || return 1
  python3 - "$transaction_dir/state.json" <<'PY' >/dev/null 2>&1
import json
import sys

with open(sys.argv[1], encoding="utf-8") as stream:
    state = json.load(stream)
raise SystemExit(0 if state.get("phase") == "committed" else 1)
PY
}

restore_uninstall_backup() {
  local expected_package_kind="${1:-current}"
  local current_status="" restored_status=""
  [[ "$expected_package_kind" == current ||
     "$expected_package_kind" == legacy ]] || return 1
  backup_dir="$transaction_dir/backup"
  query_dkms_status current_status -m swapz -v "$version" || return 1
  dkms_status_single_kernel_scope "$current_status" &&
    other_kernel_module_candidates_absent || return 1
  cleanup_activation_files || return 1
  cleanup_source_files || return 1
  rm -f -- "$installed_module" || return 1
  if [[ -n "$current_status" ]]; then
    "$dkms_bin" remove -m swapz -v "$version" --all || return 1
  fi
  query_dkms_status current_status -m swapz -v "$version" || return 1
  [[ -z "$current_status" ]] && module_candidates_absent || return 1

  install -d -m0755 "$src/src/kernel" || return 1
  cp -a -- "$backup_dir/source/dkms.conf" "$src/dkms.conf" || return 1
  cp -a -- "$backup_dir/source/$marker" "$src/$marker" || return 1
  if [[ -f "$backup_dir/source/$qualification_marker" ]]; then
    cp -a -- "$backup_dir/source/$qualification_marker" "$src/$qualification_marker" ||
      return 1
  fi
  cp -a -- "$backup_dir/source/$source_manifest" "$src/$source_manifest" ||
    return 1
  cp -a -- "$backup_dir/source/$binary_manifest" "$src/$binary_manifest" ||
    return 1
  cp -a -- "$backup_dir/source/src/kernel/"* "$src/src/kernel/" || return 1
  (cd "$src" && sha256sum -c "$source_manifest" >/dev/null) || return 1

  "$dkms_bin" add -m swapz -v "$version" || return 1
  "$dkms_bin" build -m swapz -v "$version" -k "$kernel_release" || return 1
  "$dkms_bin" install -m swapz -v "$version" -k "$kernel_release" || return 1
  query_dkms_status restored_status -m swapz -v "$version" -k "$kernel_release" ||
    return 1
  dkms_status_exact_installed "$restored_status" || return 1
  query_dkms_status restored_status -m swapz -v "$version" || return 1
  dkms_status_exact_installed "$restored_status" || return 1
  other_kernel_module_candidates_absent || return 1
  prepare_exact_module_restore || return 1
  install -d -m0755 "$installed_module_dir" || return 1
  install -m0644 "$backup_dir/installed-module" "$installed_module" || return 1
  cmp -s "$backup_dir/installed-module" "$installed_module" || return 1
  "$depmod_bin" "$kernel_release" || return 1
  cmp -s "$backup_dir/installed-module" "$installed_module" || return 1
  verify_installed_module_set || return 1
  verify_module_resolution || return 1
  durable_package_paths "$src" "$src/src" "$src/src/kernel" \
    "$src/dkms.conf" "$src"/src/kernel/* "$src/$marker" \
    "$src/$source_manifest" "$src/$binary_manifest" \
    "$src/$qualification_marker" "$installed_module" || return 1
  persist_transaction_state rollback-backend-restored || return 1

  # Restore all non-CLI package files only after module/DKMS state, depmod and
  # module resolution are valid. The CLI is the activation gate and is restored
  # atomically last.
  restore_uninstall_file_backups_except_cli || return 1
  local -a restored_files=()
  mapfile -t restored_files < "$backup_dir/file-paths" || return 1
  durable_package_paths "${restored_files[@]}" || return 1
  persist_transaction_state rollback-files-restored || return 1
  "$systemctl_bin" daemon-reload || return 1
  persist_transaction_state rollback-systemd-reloaded || return 1
  restore_uninstall_cli_backup || return 1
  durable_package_paths "$cli" || return 1
  persist_transaction_state rollback-cli-restored || return 1
  # Hermetic failure at the last verification boundary after CLI publication.
  if [[ -n "$test_root" && ${SWAPZ_TEST_UNINSTALL_ROLLBACK_VERIFY_FAILURE:-0} == 1 ]]; then
    return 1
  fi
  # Snapshot identity is explicit: uninstall rollback always passes current,
  # while install recovery may restore a verified legacy package snapshot.
  if [[ "$expected_package_kind" == legacy ]]; then
    verify_owned_legacy || return 1
  else
    verify_owned || return 1
  fi
  durable_package_paths "$cli" "$installed_module" || return 1
}

uninstall_rollback() {
  local rc="${1:-1}" reason="${2:-failure}"
  trap - ERR HUP INT TERM
  transaction_active=0
  if [[ "$transaction_phase" == committed ]]; then
    transaction_active=0
    if [[ "$durable_transaction_phase" == committed ]] &&
       durable_committed_transaction_record; then
      echo "BLOCKED: package uninstall $reason after durable committed phase; committed uninstall verified; rollback not attempted; recovery-required journal retained" >&2
    else
      quarantine_activation || true
      echo "BLOCKED: package uninstall $reason while committed journal durability is uncertain; rollback not attempted; recovery-required journal retained" >&2
    fi
    exit "$rc"
  fi
  echo "BLOCKED: package uninstall $reason; attempting transaction rollback" >&2
  if ! verify_transaction_snapshot; then
    quarantine_activation || true
    echo "BLOCKED: uninstall rollback snapshot invalid; rollback not attempted; recovery-required journal retained" >&2
    exit "$rc"
  fi
  if ! persist_transaction_state rollback-started; then
    quarantine_activation || true
    echo "BLOCKED: cannot journal uninstall rollback; rollback not attempted; recovery-required journal retained" >&2
    exit "$rc"
  fi
  if restore_uninstall_backup current && persist_transaction_state rolled-back; then
    local cleanup_status=0
    remove_transaction_record || cleanup_status=$?
    if (( cleanup_status == 0 )); then
      echo "BLOCKED: uninstall rollback succeeded; previous installation verified and journal cleared" >&2
    else
      printf 'BLOCKED: uninstall rollback succeeded; previous installation verified; transaction-record cleanup failed (status %d)\n'         "$cleanup_status" >&2
    fi
  else
    # A failed final check must never leave activation entry points online.
    quarantine_activation || true
    record_incomplete_rollback || true
    echo "BLOCKED: uninstall rollback incomplete at phase $transaction_phase; verified recovery-required journal retained" >&2
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

# Recovery is deliberately explicit. Normal install/uninstall always retain the
# incomplete-transaction admission gate, including after SIGKILL at "committed".
if [[ "$action" == recover ]]; then
  ensure_transaction_parent
  shopt -s nullglob
  retained_transactions=(
    "$transaction_parent"/swapz-package.*
    "$transaction_parent"/swapz-uninstall.*
  )
  shopt -u nullglob
  (( ${#retained_transactions[@]} <= 1 )) ||
    blocked "recovery selection ambiguous: multiple retained package transactions"
  if (( ${#retained_transactions[@]} == 0 )); then
    # A repeat recovery is a no-op only for a complete installed or empty state.
    assert_single_kernel_dkms_scope
    repeated_status=""
    query_dkms_status repeated_status -m swapz -v "$version" ||
      blocked "recovery repeat cannot inspect DKMS state"
    if package_paths_present; then
      verify_owned || verify_owned_legacy ||
        blocked "recovery repeat found unverified installed package"
      dkms_status_exact_installed "$repeated_status" ||
        blocked "recovery repeat found unverified DKMS registration"
    else
      [[ -z "$repeated_status" ]] && module_candidates_absent ||
        blocked "recovery repeat found unowned DKMS state"
    fi
    echo "No retained package recovery record; installed state verified"
    exit 0
  fi

  transaction_dir="${retained_transactions[0]}"
  case "$transaction_dir" in
    "$transaction_parent"/swapz-package.*)
      [[ "${transaction_dir##*/}" =~ ^swapz-package\.[A-Za-z0-9]{8}$ ]] ||
        blocked "recovery directory name is not canonical"
      recovery_action=install ;;
    "$transaction_parent"/swapz-uninstall.*)
      [[ "${transaction_dir##*/}" =~ ^swapz-uninstall\.[A-Za-z0-9]{8}$ ]] ||
        blocked "recovery directory name is not canonical"
      recovery_action=uninstall ;;
    *) blocked "recovery directory selection is unsafe" ;;
  esac
  transaction_active=4
  action="$recovery_action"
  backup_dir="$transaction_dir/backup"
  verify_transaction_snapshot || blocked "recovery snapshot verification failed"
  recovery_kind="$(verify_recovery_backup)" ||
    blocked "recovery source, destination or binary provenance invalid"
  [[ "$recovery_kind" == none || "$recovery_kind" == current ||
     "$recovery_kind" == legacy ]] ||
    blocked "recovery backup identity ambiguous"
  if [[ "$action" == uninstall ]]; then
    [[ "$recovery_kind" == current ]] ||
      blocked "recovery uninstall lacks a verified current-package snapshot"
  fi
  recovery_phase="$(python3 - "$transaction_dir/state.json" <<'PY'
import json
import sys
with open(sys.argv[1], encoding="utf-8") as stream:
    print(json.load(stream)["phase"])
PY
  )" || blocked "recovery cannot read validated journal phase"
  transaction_phase="$recovery_phase"

  # A valid committed record normally preserves the exact published install.
  # If activation was deliberately quarantined because the commit transition
  # failed after rename but before durability was established, explicit recover
  # instead replays the independently verified previous snapshot.
  recovery_replay_previous=0
  if [[ "$recovery_phase" == committed && "$action" == install ]]; then
    if verify_owned; then
      recovery_quarantine_on_error=0
    elif activation_entry_points_absent; then
      recovery_replay_previous=1
    else
      blocked "recovery committed install is not exact before preflight"
    fi
  fi

  # These preflight checks happen under the existing package lock before any
  # DKMS --all or cleanup. A foreign kernel must not be silently erased.
  assert_single_kernel_dkms_scope
  swapz_module_loaded && blocked "recovery blocked by loaded swapz module"
  swapz_mapper_present && blocked "recovery blocked by active swapz mapping"
  assert_no_primary_recovery_authority recovery

  # Test-only fault injection never runs in production. The original I/O
  # exception stays on stderr; neither a failed fsync nor rename clears state.
  if [[ -n "$test_root" ]]; then
    export SWAPZ_PACKAGE_RECOVERY_ACTIVE=1
  fi

  cleanup_temporary_activation_files ||
    blocked "recovery temporary CLI provenance or durability invalid"

  # From this point onward rollback or final verification can expose an
  # ambiguous package, so failures quarantine activation entry points again.
  recovery_quarantine_on_error=1
  if [[ "$recovery_phase" != committed || "$recovery_replay_previous" == 1 ]]; then
    # Do not normalize substituted live destinations during rollback.
    for recovery_path in "$src" "$cli" "$boot_verifier" "$runtime_health" \
        "$helper" "$module_snapshot" "$primary_generator" "$mapper_service" \
        "$boot_verifier_service" "$runtime_health_service" "$primary_swap" \
        "$installed_module" "${module_candidate_paths[@]}"; do
      [[ ! -L "$recovery_path" ]] ||
        blocked "recovery found symlinked installed package destination"
    done
    # Replay the saved *previous* state, never forward-complete an ambiguous
    # install or uninstall. A rolled-back journal is also safe to re-verify.
    persist_transaction_state rollback-started ||
      blocked "recovery rollback-started journal not durable"
    recovery_rollback_outcome="incomplete"
    if [[ "$recovery_kind" == none ]]; then
      recovery_status=""
      query_dkms_status recovery_status -m swapz -v "$version" ||
        blocked "recovery cannot inspect DKMS before clean rollback"
      dkms_status_single_kernel_scope "$recovery_status" ||
        blocked "recovery detected other-kernel DKMS registrations"
      if [[ -n "$recovery_status" ]]; then
        "$dkms_bin" remove -m swapz -v "$version" --all ||
          blocked "recovery failed to remove new-kernel DKMS registration"
      fi
      cleanup_package_files ||
        blocked "recovery could not remove partial package files"
      rm -f -- "$installed_module" ||
        blocked "recovery could not remove partial module image"
      module_candidates_absent && other_kernel_module_candidates_absent ||
        blocked "recovery left compressed or other-kernel module variants"
      durable_package_paths "$src" "$cli" "$boot_verifier" "$runtime_health" \
          "$helper" "$module_snapshot" "$primary_generator" "$mapper_service" \
          "$boot_verifier_service" "$runtime_health_service" "$primary_swap" \
          "$installed_module_dir" ||
        blocked "recovery clean rollback filesystem sync failed"
      "$depmod_bin" "$kernel_release" ||
        blocked "recovery clean rollback depmod failed"
      "$systemctl_bin" daemon-reload ||
        blocked "recovery clean rollback systemd reload failed"
    else
      restore_uninstall_backup "$recovery_kind" ||
        blocked "recovery previous package rollback failed"
    fi
    persist_transaction_state rolled-back ||
      blocked "recovery rolled-back journal not durable"
    recovery_rollback_outcome="succeeded"
  fi

  # A crash after committed must not uninstall an already-published package.
  # Before forgetting *any* record, independently verify the final state,
  # complete DKMS scope, and fsync both installed files and directory entries.
  final_status=""
  query_dkms_status final_status -m swapz -v "$version" ||
    blocked "recovery final DKMS query failed"
  if [[ "$recovery_phase" == committed && "$action" == install &&
        "$recovery_replay_previous" == 0 ]]; then
    verify_owned && dkms_status_exact_installed "$final_status" ||
      blocked "recovery committed install verification failed"
  elif [[ "$recovery_phase" == committed && "$action" == uninstall ||
          "$recovery_kind" == none ]]; then
    [[ -z "$final_status" ]] && ! package_paths_present &&
      module_candidates_absent ||
      blocked "recovery empty-state verification failed"
  else
    if [[ "$recovery_kind" == legacy ]]; then
      verify_owned_legacy || blocked "recovery legacy package verification failed"
    else
      verify_owned || blocked "recovery restored package verification failed"
    fi
    dkms_status_exact_installed "$final_status" ||
      blocked "recovery restored all-kernel DKMS verification failed"
  fi
  other_kernel_module_candidates_absent ||
    blocked "recovery final other-kernel module image detected"
  durable_package_paths "$src" "$cli" "$boot_verifier" "$runtime_health" \
      "$helper" "$module_snapshot" "$primary_generator" "$mapper_service" \
      "$boot_verifier_service" "$runtime_health_service" "$primary_swap" \
      "$installed_module" "$installed_module_dir" ||
    blocked "recovery final installed filesystem sync failed"
  verify_transaction_snapshot && verify_recovery_backup >/dev/null ||
    blocked "recovery final rollback record re-verification failed"

  transaction_active=0
  cleanup_status=0
  remove_transaction_record || cleanup_status=$?
  if (( cleanup_status != 0 )); then
    printf 'BLOCKED: recovery phase %s final state verified; rollback %s; transaction-record cleanup failed (status %d)\n'       "$transaction_phase" "$recovery_rollback_outcome" "$cleanup_status" >&2
    exit "$cleanup_status"
  fi
  if [[ "$recovery_rollback_outcome" == succeeded ]]; then
    echo "Recovered verified swapz package transaction ($action: $recovery_phase; previous-state rollback succeeded)"
  else
    echo "Recovered verified swapz package transaction ($action: $recovery_phase; rollback not attempted)"
  fi
  exit 0
fi

assert_no_incomplete_package_transactions

if [[ "$action" == uninstall ]]; then
  uninstall_dkms_status=""
  uninstall_dkms_status_rc=0
  query_dkms_status uninstall_dkms_status -m swapz -v "$version" -k "$kernel_release" ||
    uninstall_dkms_status_rc=$?
  if (( uninstall_dkms_status_rc != 0 )); then
    printf 'SWAPZ_PACKAGE_DIAGNOSTIC artifact=current_kernel_dkms_registration check=exact_installed_state expected=one_exact_installed_record observed=probe_failed command_status=%s next=inspect_dkms_status_read_only retained_state=unchanged\n'       "$uninstall_dkms_status_rc" >&2
    blocked "cannot inspect current-kernel DKMS state before package removal"
  fi
  if ! dkms_status_exact_installed "$uninstall_dkms_status"; then
    printf 'SWAPZ_PACKAGE_DIAGNOSTIC artifact=current_kernel_dkms_registration check=exact_installed_state expected=one_exact_installed_record observed=missing_stale_or_ambiguous command_status=0 next=inspect_dkms_status_read_only retained_state=unchanged\n' >&2
    blocked "verified package does not have an installed current-kernel DKMS state"
  fi
  assert_single_kernel_dkms_scope
  if [[ -z "$test_root" && "$action" == uninstall ]] &&
     [[ -e /sys/module/dm_swapz || -e /sys/module/dm-swapz ]]; then
    echo "BLOCKED: loaded module; refusing DKMS removal; phase=uninstall preflight; rollback not attempted" >&2
    exit 1
  fi
  if [[ -n "$test_root" ]] && swapz_module_loaded; then
    echo "BLOCKED: loaded module; refusing DKMS removal; phase=uninstall preflight; rollback not attempted" >&2
    exit 1
  fi
  swapz_mapper_present && blocked "active swapz mapping; refusing package removal"
  assert_no_primary_recovery_authority removal
  # A passive .swap unit without [Install] is "static": systemctl reports
  # is-enabled exit 0 for it, although it has no enabled activation link.
  # Inspect both the state and the return code, and fail closed on errors.
  for unit in swapz-primary-boot-verify.service swapz-primary-mapper.service \
      swapz-primary-runtime-health.service "$swap_unit_name"; do
    unit_active_rc=0
    unit_active_state="$("$systemctl_bin" is-active "$unit" 2>/dev/null)" || unit_active_rc=$?
    case "$unit_active_state" in
      inactive|failed)
        (( unit_active_rc == 3 )) || blocked "cannot verify $unit is inactive"
        ;;
      active|activating|reloading|deactivating)
        blocked "$unit is active; refusing package removal"
        ;;
      *) blocked "cannot verify $unit is inactive" ;;
    esac
    unit_enabled_rc=0
    unit_enabled_state="$("$systemctl_bin" is-enabled "$unit" 2>/dev/null)" || unit_enabled_rc=$?
    case "$unit_enabled_state" in
      static)
        (( unit_enabled_rc == 0 )) || blocked "cannot verify $unit is static"
        ;;
      disabled|disabled-runtime|masked|masked-runtime)
        (( unit_enabled_rc == 1 )) || blocked "cannot verify $unit is disabled"
        ;;
      enabled|enabled-runtime|linked|linked-runtime|alias|indirect|generated|transient)
        blocked "$unit is enabled; disable swapz through its recovery procedure first"
        ;;
      *) blocked "cannot verify whether $unit is enabled" ;;
    esac
  done
  verify_owned || {
    report_existing_package_drift
    echo "BLOCKED: uninstall preflight: foreign, absent or modified swapz package; rollback not attempted" >&2
    exit 1
  }

  ensure_transaction_parent
  transaction_dir="$(mktemp -d "$transaction_parent/swapz-uninstall.XXXXXXXX")"
  chmod 0700 "$transaction_dir"
  transaction_active=2
  trap 'staging_abort $? "command failed during $transaction_phase"' ERR
  trap 'staging_abort 129 interruption' HUP
  trap 'staging_abort 130 interruption' INT
  trap 'staging_abort 143 interruption' TERM
  backup_verified_package_for_uninstall
  persist_transaction_state prepared

  transaction_active=3
  trap 'uninstall_rollback $? "command failed during $transaction_phase"' ERR
  trap 'uninstall_rollback 129 interruption' HUP
  trap 'uninstall_rollback 130 interruption' INT
  trap 'uninstall_rollback 143 interruption' TERM

  # Remove all activation entry points only after the private rollback snapshot
  # and its independently verifiable hash manifest are durable.
  persist_transaction_state removing-activation-files
  cleanup_activation_files
  durable_package_paths "$cli_dir" "$prefix/libexec" "$unit_dir" "$generator_dir"
  persist_transaction_state activation-files-removed
  uninstall_test_checkpoint activation-files-removed

  persist_transaction_state removing-dkms
  assert_single_kernel_dkms_scope
  "$dkms_bin" remove -m swapz -v "$version" --all
  removed_dkms_status=""
  query_dkms_status removed_dkms_status -m swapz -v "$version" ||
    blocked "cannot verify DKMS removal"
  [[ -z "$removed_dkms_status" ]] || blocked "DKMS removal left registered state"
  module_candidates_absent || blocked "DKMS removal left current-kernel module images"
  durable_package_paths "$installed_module_dir"
  persist_transaction_state dkms-removed
  uninstall_test_checkpoint dkms-removed

  persist_transaction_state removing-source
  cleanup_source_files
  durable_package_paths "$srcbase"
  persist_transaction_state source-removed
  uninstall_test_checkpoint source-removed

  persist_transaction_state removing-installed-module
  rm -f -- "$installed_module"
  durable_package_paths "$installed_module_dir"
  persist_transaction_state installed-module-removed
  uninstall_test_checkpoint installed-module-removed

  persist_transaction_state depmod-pending
  "$depmod_bin" "$kernel_release"
  persist_transaction_state depmod-complete
  uninstall_test_checkpoint depmod-complete

  persist_transaction_state systemd-reload-pending
  "$systemctl_bin" daemon-reload
  persist_transaction_state systemd-reload-complete
  uninstall_test_checkpoint systemd-reload-complete
  removed_dkms_status=""
  query_dkms_status removed_dkms_status -m swapz -v "$version" ||
    blocked "cannot verify all-kernel DKMS state after uninstall"
  [[ -z "$removed_dkms_status" ]] && ! package_paths_present &&
    other_kernel_module_candidates_absent ||
    blocked "uninstall left DKMS registrations or package files"
  durable_package_paths "$srcbase" "$installed_module_dir" "$cli_dir" "$unit_dir" "$generator_dir"
  persist_transaction_state committed

  transaction_active=0
  trap - ERR HUP INT TERM
  cleanup_status=0
  remove_transaction_record || cleanup_status=$?
  if (( cleanup_status != 0 )); then
    printf 'BLOCKED: uninstall committed and empty state verified; transaction-record cleanup failed (status %d)\n'       "$cleanup_status" >&2
    exit "$cleanup_status"
  fi
  echo "Uninstalled owned swapz package without touching swap"
  exit 0
fi

# Installation consumes the exact artifacts already qualified by make test. It
# never rebuilds or re-signs them, because either operation would change the
# bytes whose digests were admitted by the qualification report.
for input in "$cli_artifact" "$oracle_artifact" "$module_artifact" "$build_info" "$qualification_report"; do
  safe_input_file "$input" || blocked "unsafe or missing qualified package input"
done
[[ -x "$cli_artifact" && -x "$oracle_artifact" ]] ||
  blocked "qualified userspace artifacts are not executable"
for payload in dkms.conf src/kernel/VERSION \
    packaging/swapz-primary-boot-verify \
    packaging/swapz-primary-runtime-health \
    packaging/swapz-primary-mapper.service \
    packaging/swapz-primary-boot-verify.service \
    packaging/swapz-primary-runtime-health.service \
    packaging/swapz-primary-generator packaging/swapz-primary.swap; do
  safe_input_file "$payload" || blocked "unsafe package payload"
done

qualification_output="$(python3 - "$qualification_report" "$kernel_release" <<'PY'
import json
import re
import sys
from pathlib import Path

report = None


class DuplicateQualificationKeyError(ValueError):
    def __init__(self, key):
        self.key = key


def reject_duplicate_qualification_keys(pairs):
    record = {}
    for key, value in pairs:
        if key in record:
            raise DuplicateQualificationKeyError(key)
        record[key] = value
    return record


def safe_observed(value):
    """Return a bounded non-path representation for public diagnostics."""
    if value is None:
        return "missing"
    if value is True:
        return "true(bool)"
    if value is False:
        return "false(bool)"
    if type(value) is int:
        if -(10 ** 79) < value < 10 ** 79:
            return str(value)
        return "<int>"
    if (isinstance(value, str) and
            re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 ._:+-]{0,79}", value)):
        return value
    return f"<{type(value).__name__}>"


def reject(field, expected, observed, next_step):
    source = (safe_observed(report.get("source_sha"))
              if isinstance(report, dict) else "unavailable")
    tested = (safe_observed(report.get("tested_commit_sha"))
              if isinstance(report, dict) else "unavailable")
    raise SystemExit(
        "qualification report invalid: "
        f"field={field} source_sha={source} tested_commit_sha={tested} "
        f"expected={expected} observed={safe_observed(observed)} "
        f"next={next_step}")


try:
    report = json.loads(
        Path(sys.argv[1]).read_text(encoding="utf-8"),
        object_pairs_hook=reject_duplicate_qualification_keys)
except DuplicateQualificationKeyError as error:
    reject("duplicate_json_key", "unique-key-per-object", error.key,
           "rerun-make-test-for-exact-clean-source")
except (OSError, UnicodeError, ValueError, RecursionError):
    raise SystemExit(
        "qualification report invalid: field=document "
        "source_sha=unavailable tested_commit_sha=unavailable "
        "expected=UTF-8-JSON-object observed=unreadable "
        "next=rerun-make-test-for-exact-clean-source")
if not isinstance(report, dict):
    reject("document", "JSON-object", report,
           "rerun-make-test-for-exact-clean-source")

expected_kernel_release = sys.argv[2]
required_stages = (
    "Build module and helpers",
    "Native and rootless contracts",
    "Kernel warnings W=1",
    "Kernel warnings W=2",
    "Owned RAM smoke + mixed/QD pilot",
)
if report.get("schema") != "swapz-test-results-v1":
    reject("schema", "swapz-test-results-v1", report.get("schema"),
           "rerun-make-test-for-exact-clean-source")
if report.get("kernel_release") != expected_kernel_release:
    reject("kernel_release", expected_kernel_release, report.get("kernel_release"),
           "rerun-make-test-on-running-kernel")
source = report.get("source_sha")
tested = report.get("tested_commit_sha")
if not isinstance(source, str) or not re.fullmatch(r"[0-9a-f]{40}", source):
    reject("source_sha", "40-lower-hex", source,
           "rerun-make-test-for-exact-clean-source")
if not isinstance(tested, str) or not re.fullmatch(r"[0-9a-f]{40}", tested):
    reject("tested_commit_sha", "40-lower-hex", tested,
           "rerun-make-test-for-exact-clean-source")
if tested != source:
    reject("tested_commit_sha", source, tested,
           "rerun-make-test-for-exact-clean-source")
if report.get("overall") != "PASS":
    reject("overall", "PASS", report.get("overall"),
           "inspect-first-non-PASS-stage-and-rerun-make-test")
if report.get("qualification") != "RAM_BACKED_NULL_BLK_ONLY":
    reject("qualification", "RAM_BACKED_NULL_BLK_ONLY",
           report.get("qualification"),
           "rerun-make-test-for-exact-clean-source")
stages = report.get("stages")
if not isinstance(stages, list):
    reject("stages", "5-canonical-stages", stages,
           "rerun-make-test-for-exact-clean-source")
if len(stages) != len(required_stages):
    reject("stages", "5-canonical-stages", len(stages),
           "rerun-make-test-for-exact-clean-source")
for index, (expected, stage) in enumerate(zip(required_stages, stages)):
    if not isinstance(stage, dict):
        reject(f"stages[{index}]", "object", stage,
               "rerun-make-test-for-exact-clean-source")
    if stage.get("name") != expected:
        reject(f"stages[{index}].name", expected, stage.get("name"),
               "rerun-make-test-for-exact-clean-source")
    if stage.get("status") != "PASS":
        reject(f"stages[{index}].status", "PASS", stage.get("status"),
               "inspect-first-non-PASS-stage-and-rerun-make-test")
    exit_code = stage.get("exit_code")
    if type(exit_code) is not int or exit_code != 0:
        reject(f"stages[{index}].exit_code", "integer-0", exit_code,
               "rerun-make-test-for-exact-clean-source")

artifacts = report.get("qualified_artifacts")
if not isinstance(artifacts, dict):
    reject("qualified_artifacts", "canonical-artifact-object", artifacts,
           "rerun-make-test-and-rebuild-qualified-artifacts")
if artifacts.get("status") != "AVAILABLE":
    reject("qualified_artifacts.status", "AVAILABLE", artifacts.get("status"),
           "rerun-make-test-and-rebuild-qualified-artifacts")
artifact_keys = ("formatter_sha256", "module_sha256", "oracle_sha256")
values = []
for key in artifact_keys:
    value = artifacts.get(key)
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        reject(f"qualified_artifacts.{key}", "64-lower-hex-sha256", value,
               "rerun-make-test-and-rebuild-qualified-artifacts")
    values.append(value)
if set(artifacts) != {"status", *artifact_keys}:
    reject("qualified_artifacts.keys",
           "status+formatter_sha256+module_sha256+oracle_sha256",
           "noncanonical-fields",
           "rerun-make-test-and-rebuild-qualified-artifacts")
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
if [[ "$build_source_sha" != "$qualified_source_sha" || "$build_source_clean" != 1 ]]; then
  observed_source_sha="$build_source_sha"
  observed_clean_state="$build_source_clean"
  [[ "$observed_source_sha" =~ ^[0-9a-f]{40}$ ]] || observed_source_sha=unavailable
  [[ "$observed_clean_state" == 0 || "$observed_clean_state" == 1 ]] || observed_clean_state=unavailable
  printf 'SWAPZ_PACKAGE_DIAGNOSTIC artifact=qualified_kernel_build_info check=source_provenance expected_source_sha=%s observed_source_sha=%s expected_clean=1 observed_clean=%s next=inspect_qualification_and_build_info_read_only retained_state=unchanged\n' \
    "$qualified_source_sha" "$observed_source_sha" "$observed_clean_state" >&2
  blocked "build provenance does not match the qualified clean source"
fi
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

report_qualified_digest qualified_swapzctl "$qualified_cli_sha256" "$cli_artifact" qualified_report ||
  blocked "swapzctl digest does not match qualification"
report_qualified_digest qualified_dm-swapz.ko "$qualified_module_sha256" "$module_artifact" qualified_report ||
  blocked "module digest does not match qualification"
report_qualified_digest qualified_roundtrip_oracle "$qualified_oracle_sha256" "$oracle_artifact" qualified_report ||
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

module_vermagic_status=0
module_vermagic="$(modinfo -F vermagic "$module_artifact" 2>/dev/null)" ||
  module_vermagic_status=$?
module_kernel_release="${module_vermagic%% *}"
if [[ "$module_kernel_release" != "$kernel_release" || "$module_vermagic_status" -ne 0 ]]; then
  module_vermagic_observed=foreign_kernel
  if (( module_vermagic_status != 0 )); then
    module_vermagic_observed=modinfo_probe_failed
  elif [[ -z "$module_kernel_release" ]]; then
    module_vermagic_observed=missing_vermagic
  fi
  printf 'SWAPZ_PACKAGE_DIAGNOSTIC artifact=qualified_dm-swapz.ko check=module_vermagic expected=running_kernel observed=%s command_status=%s next=inspect_modinfo_vermagic_read_only retained_state=unchanged\n' \
    "$module_vermagic_observed" "$module_vermagic_status" >&2
  blocked "qualified module does not match the running kernel; phase=module_vermagic; command_status=$module_vermagic_status"
fi
if [[ -n "$test_root" ]]; then
  SWAPZ_SIGN_TEST_ROOT="$sandbox" bash packaging/sign-module.sh --verify "$module_artifact"
else
  bash packaging/sign-module.sh --verify "$module_artifact"
fi
report_qualified_digest qualified_dm-swapz.ko "$qualified_module_sha256" "$module_artifact" qualified_report ||
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
  elif [[ ! -e "$src/$qualification_marker" && ! -L "$src/$qualification_marker" ]] &&
       verify_owned_legacy; then
    existing_kind="legacy"
  else
    report_existing_package_drift
    blocked "existing package is partial, foreign, or modified"
  fi
fi

current_dkms_status=""
current_dkms_status_rc=0
query_dkms_status current_dkms_status -m swapz -v "$version" -k "$kernel_release" ||
  current_dkms_status_rc=$?
if (( current_dkms_status_rc != 0 )); then
  printf 'SWAPZ_PACKAGE_DIAGNOSTIC artifact=current_kernel_dkms_registration check=exact_installed_state expected=one_exact_installed_record observed=probe_failed command_status=%s next=inspect_dkms_status_read_only retained_state=unchanged\n'     "$current_dkms_status_rc" >&2
  blocked "cannot inspect current-kernel DKMS state"
fi
if [[ -n "$existing_kind" ]] && ! dkms_status_exact_installed "$current_dkms_status"; then
  printf 'SWAPZ_PACKAGE_DIAGNOSTIC artifact=current_kernel_dkms_registration check=exact_installed_state expected=one_exact_installed_record observed=missing_stale_or_ambiguous command_status=0 next=inspect_dkms_status_read_only retained_state=unchanged\n' >&2
  blocked "verified package does not have an installed current-kernel DKMS state"
fi
assert_single_kernel_dkms_scope
if [[ -z "$existing_kind" && -n "$current_dkms_status" ]]; then
  blocked "DKMS state exists without a verified package"
fi
if [[ -n "$existing_kind" ]]; then
  if ! verify_installed_module_set; then
    printf 'SWAPZ_PACKAGE_DIAGNOSTIC artifact=current_kernel_module_image_set check=module_image_set expected=exactly_one_uncompressed_owned_image observed=missing_or_ambiguous command_status=0 next=inspect_installed_kernel_module_images_read_only retained_state=unchanged\n' >&2
    blocked "verified package does not own exactly one current-kernel module image"
  fi
  if ! verify_module_resolution; then
    report_module_resolution_failure
    blocked "verified package module lookup does not match package ownership"
  fi
fi
if [[ "$existing_kind" == current ]] &&
   cmp -s "$src/$qualification_marker" <(incoming_identity) &&
   dkms_status_exact_installed "$current_dkms_status"; then
  if ! verify_module_resolution; then
    report_module_resolution_failure
    blocked "installed module lookup does not match package ownership"
  fi
  echo "Installed swapz package already matches the exact qualified artifacts"
  exit 0
fi

swapz_module_loaded && blocked "loaded module; refusing package upgrade"
swapz_mapper_present && blocked "active swapz mapping; refusing package upgrade"
assert_no_primary_recovery_authority upgrade

ensure_transaction_parent
transaction_dir="$(mktemp -d "$transaction_parent/swapz-package.XXXXXXXX")"
transaction_active=2
trap 'staging_abort $? "command failed during $transaction_phase"' ERR
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
  # Older installed packages predate monitoring; snapshot only files verified
  # to exist, and recover exactly that previous installed set.
  : > "$backup_dir/file-paths"
  for file in "$cli" "$boot_verifier" "$runtime_health" "$helper" "$module_snapshot" \
      "$primary_generator" "$mapper_service" "$boot_verifier_service" \
      "$runtime_health_service" "$primary_swap"; do
    [[ -f "$file" && ! -L "$file" ]] || continue
    backup_key="$(hash_path_key "$file")" ||
      blocked "cannot derive verified package backup path key"
    cp -a -- "$file" "$backup_dir/files/$backup_key"
    printf '%s\n' "$file" >> "$backup_dir/file-paths"
  done
  cp -a -- "$installed_module" "$backup_dir/installed-module"
fi

# Stage and hash every replacement before touching a verified installation.
# Prepare all userspace/systemd bytes before replacing any live package file.
install -m0755 "$cli_artifact" "$stage_dir/swapzctl"
install -m0755 packaging/swapz-primary-boot-verify "$stage_dir/swapz-primary-boot-verify"
install -m0755 packaging/swapz-primary-runtime-health "$stage_dir/swapz-primary-runtime-health"
install -m0755 "$oracle_artifact" "$stage_dir/device-roundtrip"
install -m0644 "$module_artifact" "$stage_dir/dm-swapz.ko"
sed "s|@SWAPZ_SBINDIR@|$cli_dir|g" packaging/swapz-primary-mapper.service > "$stage_dir/swapz-primary-mapper.service"
sed "s|@SWAPZ_SBINDIR@|$cli_dir|g" packaging/swapz-primary-boot-verify.service > "$stage_dir/swapz-primary-boot-verify.service"
sed "s|@SWAPZ_SBINDIR@|$cli_dir|g" packaging/swapz-primary-runtime-health.service > "$stage_dir/swapz-primary-runtime-health.service"
sed "s|@SWAPZ_SBINDIR@|$cli_dir|g" packaging/swapz-primary-generator > "$stage_dir/swapz-primary-generator"
chmod 0644 "$stage_dir/swapz-primary-mapper.service" "$stage_dir/swapz-primary-boot-verify.service" \
  "$stage_dir/swapz-primary-runtime-health.service"
chmod 0755 "$stage_dir/swapz-primary-generator"
install -m0644 packaging/swapz-primary.swap "$stage_dir/$swap_unit_name"

report_qualified_digest staged_swapzctl "$qualified_cli_sha256" \
    "$stage_dir/swapzctl" qualified_report ||
  blocked "staged swapzctl digest verification failed"
report_qualified_digest staged_roundtrip_oracle "$qualified_oracle_sha256" \
    "$stage_dir/device-roundtrip" qualified_report ||
  blocked "staged round-trip oracle digest verification failed"
report_qualified_digest staged_dm-swapz.ko "$qualified_module_sha256" \
    "$stage_dir/dm-swapz.ko" qualified_report ||
  blocked "staged module digest verification failed"

persist_transaction_state prepared

install_test_checkpoint() {
  local phase="$1"
  [[ -z "$test_root" || ${SWAPZ_TEST_INSTALL_FAIL_AFTER:-never} != "$phase" ]] ||
    blocked "test install checkpoint after $phase"
}

new_source_created=0
new_dkms_registered=0
new_files_committed=0
rollback_in_progress=0

restore_file_backups_except_cli() {
  local path digest backup_path
  [[ -f "$backup_dir/file-paths" ]] || return 0
  while IFS= read -r path; do
    [[ "$path" == "$cli" ]] && continue
    digest="$(hash_path_key "$path")" || return $?
    backup_path="$backup_dir/files/$digest"
    [[ -f "$backup_path" && ! -L "$backup_path" ]] || return 1
    install -d -m0755 "$(dirname "$path")" || return 1
    cp -a -- "$backup_path" "$path" || return 1
    cmp -s "$backup_path" "$path" || return 1
  done < "$backup_dir/file-paths"
}

restore_cli_backup() {
  local digest backup_path temporary_cli
  [[ -f "$backup_dir/file-paths" ]] || return 0
  digest="$(hash_path_key "$cli")" || return $?
  backup_path="$backup_dir/files/$digest"
  [[ -f "$backup_path" && ! -L "$backup_path" ]] || return 1
  install -d -m0755 "$cli_dir" || return 1
  temporary_cli="$cli_dir/.swapzctl.restore.$$"
  [[ ! -e "$temporary_cli" && ! -L "$temporary_cli" ]] || return 1
  install -m0755 "$backup_path" "$temporary_cli" || return 1
  cmp -s "$backup_path" "$temporary_cli" || {
    rm -f -- "$temporary_cli"
    return 1
  }
  mv -f -- "$temporary_cli" "$cli" || return 1
}

restore_previous_package() {
  local restored_status=""
  (( had_existing == 1 )) || return 0
  cleanup_package_files || return 1
  install -d -m0755 "$src/src/kernel" || return 1
  cp -a -- "$backup_dir/source/dkms.conf" "$src/dkms.conf" || return 1
  cp -a -- "$backup_dir/source/$marker" "$src/$marker" || return 1
  cp -a -- "$backup_dir/source/$source_manifest" "$src/$source_manifest" ||
    return 1
  cp -a -- "$backup_dir/source/$binary_manifest" "$src/$binary_manifest" ||
    return 1
  if [[ -f "$backup_dir/source/$qualification_marker" ]]; then
    cp -a -- "$backup_dir/source/$qualification_marker" "$src/$qualification_marker" ||
      return 1
  fi
  cp -a -- "$backup_dir/source/src/kernel/"* "$src/src/kernel/" || return 1
  (cd "$src" && sha256sum -c "$source_manifest" >/dev/null) || return 1
  "$dkms_bin" add -m swapz -v "$version" || return 1
  "$dkms_bin" build -m swapz -v "$version" -k "$kernel_release" || return 1
  "$dkms_bin" install -m swapz -v "$version" -k "$kernel_release" || return 1
  query_dkms_status restored_status -m swapz -v "$version" -k "$kernel_release" ||
    return 1
  dkms_status_exact_installed "$restored_status" || return 1
  query_dkms_status restored_status -m swapz -v "$version" || return 1
  dkms_status_exact_installed "$restored_status" || return 1
  other_kernel_module_candidates_absent || return 1
  prepare_exact_module_restore || return 1
  [[ -f "$backup_dir/installed-module" && ! -L "$backup_dir/installed-module" ]] ||
    return 1
  install -d -m0755 "$installed_module_dir" || return 1
  install -m0644 "$backup_dir/installed-module" "$installed_module" || return 1
  cmp -s "$backup_dir/installed-module" "$installed_module" || return 1
  "$depmod_bin" "$kernel_release" || return 1
  [[ -f "$backup_dir/installed-module" && ! -L "$backup_dir/installed-module" ]] ||
    return 1
  cmp -s "$backup_dir/installed-module" "$installed_module" || return 1
  verify_installed_module_set || return 1
  verify_module_resolution || return 1
  durable_package_paths "$src" "$src/src" "$src/src/kernel" \
    "$src/dkms.conf" "$src"/src/kernel/* "$src/$marker" \
    "$src/$source_manifest" "$src/$binary_manifest" \
    "$src/$qualification_marker" "$installed_module" || return 1
  persist_transaction_state rollback-backend-restored || return 1
  restore_file_backups_except_cli || return 1
  local -a restored_files=()
  mapfile -t restored_files < "$backup_dir/file-paths" || return 1
  durable_package_paths "${restored_files[@]}" || return 1
  persist_transaction_state rollback-files-restored || return 1
  "$systemctl_bin" daemon-reload || return 1
  persist_transaction_state rollback-systemd-reloaded || return 1
  restore_cli_backup || return 1
  durable_package_paths "$cli" || return 1
  persist_transaction_state rollback-cli-restored || return 1
  if [[ -n "$test_root" && ${SWAPZ_TEST_UPGRADE_ROLLBACK_VERIFY_FAILURE:-0} == 1 ]]; then
    return 1
  fi
  # The previously verified legacy package had no qualification marker.
  if [[ "$existing_kind" == legacy ]]; then
    verify_owned_legacy || return 1
  else
    verify_owned || return 1
  fi
  durable_package_paths "$cli" "$installed_module" || return 1
}

rollback() {
  local rc="${1:-1}" reason="${2:-failure}" rollback_dkms_status=""
  (( rollback_in_progress == 0 )) || exit "$rc"
  rollback_in_progress=1
  trap - ERR HUP INT TERM
  if [[ "$transaction_phase" == committed ]]; then
    transaction_active=0
    if [[ "$durable_transaction_phase" == committed ]] &&
       durable_committed_transaction_record; then
      echo "BLOCKED: package $reason after durable committed phase; committed install verified; rollback not attempted; recovery-required journal retained" >&2
    else
      quarantine_activation || true
      echo "BLOCKED: package $reason while committed journal durability is uncertain; rollback not attempted; recovery-required journal retained" >&2
    fi
    exit "$rc"
  fi
  echo "BLOCKED: package $reason; attempting transaction rollback" >&2
  if [[ -n "${temporary_cli:-}" ]]; then
    local temporary_cleanup_status=0
    rm -f -- "$temporary_cli" || temporary_cleanup_status=$?
    if (( temporary_cleanup_status == 0 )); then
      durable_package_paths "$cli_dir" || temporary_cleanup_status=$?
    fi
    if (( temporary_cleanup_status != 0 )); then
      quarantine_activation || true
      record_incomplete_rollback || true
      printf 'BLOCKED: rollback temporary CLI cleanup failed (status %d); rollback incomplete; recovery-required journal retained\n'         "$temporary_cleanup_status" >&2
      exit "$rc"
    fi
  fi
  if ! verify_transaction_snapshot; then
    quarantine_activation || true
    echo "BLOCKED: install rollback snapshot invalid; rollback not attempted; recovery-required journal retained" >&2
    exit "$rc"
  fi
  if ! persist_transaction_state rollback-started; then
    quarantine_activation || true
    echo "BLOCKED: cannot journal install rollback; rollback not attempted; recovery-required journal retained" >&2
    exit "$rc"
  fi
  if ! query_dkms_status rollback_dkms_status -m swapz -v "$version" ||
     ! dkms_status_single_kernel_scope "$rollback_dkms_status" ||
     ! other_kernel_module_candidates_absent; then
      quarantine_activation || true
      record_incomplete_rollback || true
      echo "BLOCKED: rollback DKMS scope uncertain (query, other kernel or variant); rollback incomplete; recovery-required journal retained" >&2
      exit "$rc"
  fi
  if [[ -n "$rollback_dkms_status" ]]; then
    local dkms_remove_status=0
    "$dkms_bin" remove -m swapz -v "$version" --all || dkms_remove_status=$?
    if (( dkms_remove_status != 0 )); then
      quarantine_activation || true
      record_incomplete_rollback || true
      printf 'BLOCKED: cannot clear DKMS state during rollback (status %d); rollback incomplete; recovery-required journal retained\n'         "$dkms_remove_status" >&2
      exit "$rc"
    fi
  fi
  if ! cleanup_package_files || ! rm -f -- "$installed_module"; then
    quarantine_activation || true
    record_incomplete_rollback || true
    echo "BLOCKED: install rollback package cleanup failed; rollback incomplete; recovery-required journal retained" >&2
    exit "$rc"
  fi
  if ! module_candidates_absent; then
    quarantine_activation || true
    record_incomplete_rollback || true
    echo "BLOCKED: rollback left ambiguous module images; rollback incomplete; recovery-required journal retained" >&2
    exit "$rc"
  fi
  # For an initial install there is no previous package to republish.
  # Therefore every removed source/userspace/module directory entry must be
  # durable before a rolled-back journal may cease to be recovery authority.
  durable_package_paths "$srcbase" "$installed_module_dir" "$cli_dir"     "$prefix/libexec" "$unit_dir" "$generator_dir" || {
    quarantine_activation || true
    record_incomplete_rollback || true
    echo "BLOCKED: install rollback filesystem durability failed; rollback incomplete; recovery-required journal retained" >&2
    exit "$rc"
  }
  if (( had_existing == 1 )); then
    if restore_previous_package && persist_transaction_state rolled-back; then
      local cleanup_status=0
      remove_transaction_record || cleanup_status=$?
      if (( cleanup_status == 0 )); then
        echo "BLOCKED: install rollback succeeded; previous installation verified and journal cleared" >&2
      else
        printf 'BLOCKED: install rollback succeeded; previous installation verified; transaction-record cleanup failed (status %d)\n'           "$cleanup_status" >&2
      fi
    else
      # Do not publish a CLI after failed rollback re-verification.
      quarantine_activation || true
      record_incomplete_rollback || true
      echo "BLOCKED: previous package restoration failed; rollback incomplete; verified recovery-required journal retained" >&2
    fi
  else
    local depmod_status=0 systemd_reload_status=0
    "$depmod_bin" "$kernel_release" || depmod_status=$?
    "$systemctl_bin" daemon-reload || systemd_reload_status=$?
    if (( depmod_status == 0 && systemd_reload_status == 0 )) &&
       persist_transaction_state rolled-back; then
      local cleanup_status=0
      remove_transaction_record || cleanup_status=$?
      if (( cleanup_status == 0 )); then
        echo "BLOCKED: initial install rollback succeeded; empty state verified and journal cleared" >&2
      else
        printf 'BLOCKED: initial install rollback succeeded; empty state verified; transaction-record cleanup failed (status %d)\n'           "$cleanup_status" >&2
      fi
    else
      record_incomplete_rollback || true
      if (( depmod_status != 0 )); then
        printf 'BLOCKED: rollback depmod failed (status %d); recovery-required journal retained\n'           "$depmod_status" >&2
      fi
      if (( systemd_reload_status != 0 )); then
        printf 'BLOCKED: rollback systemd reload failed (status %d); recovery-required journal retained\n'           "$systemd_reload_status" >&2
      fi
      echo "BLOCKED: rollback cleanup incomplete; recovery-required journal retained" >&2
    fi
  fi
  exit "$rc"
}
transaction_active=1
trap 'rollback $? "command failed during $transaction_phase"' ERR
trap 'rollback 129 interruption' HUP
trap 'rollback 130 interruption' INT
trap 'rollback 143 interruption' TERM

if (( had_existing == 1 )); then
  # Revoke activation-capable entry points before replacing the backend.
  persist_transaction_state removing-activation-files
  cleanup_activation_files
  durable_package_paths "$cli_dir" "$prefix/libexec" "$unit_dir" "$generator_dir"
  persist_transaction_state activation-files-removed
  install_test_checkpoint activation-files-removed

  persist_transaction_state removing-dkms
  assert_single_kernel_dkms_scope
  "$dkms_bin" remove -m swapz -v "$version" --all
  removed_dkms_status=""
  query_dkms_status removed_dkms_status -m swapz -v "$version" ||
    blocked "cannot verify DKMS removal"
  [[ -z "$removed_dkms_status" ]] || blocked "DKMS removal left registered state"
  module_candidates_absent || blocked "DKMS removal left current-kernel module images"
  durable_package_paths "$installed_module_dir"
  persist_transaction_state dkms-removed
  install_test_checkpoint dkms-removed

  persist_transaction_state removing-source
  rm -rf -- "$src"
  durable_package_paths "$srcbase"
  persist_transaction_state source-removed
  install_test_checkpoint source-removed
fi

[[ ! -e "$src" && ! -L "$src" ]] || blocked "DKMS source path became occupied"
persist_transaction_state creating-source
install -d -m0755 "$src/src/kernel"
new_source_created=1
install -m0644 dkms.conf "$src/dkms.conf"
install -m0644 src/kernel/VERSION "$src/src/kernel/VERSION"
for file in src/kernel/Makefile src/kernel/*.c src/kernel/*.h; do
  safe_input_file "$file" || blocked "unsafe kernel package source"
  install -m0644 "$file" "$src/src/kernel/$(basename "$file")"
done
install -m0644 "$build_info" "$src/src/kernel/swapz-build-info.h"
printf 'swapz:%s\n' "$version" > "$src/$marker"
incoming_identity > "$src/$qualification_marker"
chmod 0644 "$src/$marker" "$src/$qualification_marker"
(cd "$src" && sha256sum dkms.conf src/kernel/VERSION src/kernel/Makefile \
  src/kernel/*.c src/kernel/*.h "$qualification_marker") > "$src/$source_manifest"
durable_package_paths "$src" "$src/src" "$src/src/kernel" \
  "$src/dkms.conf" "$src"/src/kernel/* "$src/$marker" \
  "$src/$qualification_marker" "$src/$source_manifest"
persist_transaction_state source-created
install_test_checkpoint source-created

persist_transaction_state adding-dkms
"$dkms_bin" add -m swapz -v "$version"
new_dkms_registered=1
persist_transaction_state dkms-added
install_test_checkpoint dkms-added

persist_transaction_state building-dkms
"$dkms_bin" build -m swapz -v "$version" -k "$kernel_release"
persist_transaction_state dkms-built
install_test_checkpoint dkms-built

persist_transaction_state installing-dkms
"$dkms_bin" install -m swapz -v "$version" -k "$kernel_release"
persist_transaction_state dkms-installed
install_test_checkpoint dkms-installed
status=""
status_rc=0
query_dkms_status status -m swapz -v "$version" -k "$kernel_release" ||
  status_rc=$?
if (( status_rc != 0 )); then
  printf 'SWAPZ_PACKAGE_DIAGNOSTIC artifact=current_kernel_dkms_registration check=post_install_exact_state expected=one_exact_installed_record observed=probe_failed command_status=%s next=inspect_dkms_status_read_only retained_state=unchanged\n'     "$status_rc" >&2
  blocked "cannot verify current-kernel DKMS state after installation"
fi
if ! dkms_status_exact_installed "$status"; then
  printf 'SWAPZ_PACKAGE_DIAGNOSTIC artifact=current_kernel_dkms_registration check=post_install_exact_state expected=one_exact_installed_record observed=missing_stale_or_ambiguous command_status=0 next=inspect_dkms_status_read_only retained_state=unchanged\n' >&2
  blocked "DKMS did not report the current kernel installed"
fi

existing_module_candidates=()
for candidate in "${module_candidate_paths[@]}"; do
  [[ -e "$candidate" || -L "$candidate" ]] && existing_module_candidates+=("$candidate")
done
if (( ${#existing_module_candidates[@]} != 1 )); then
  printf 'SWAPZ_PACKAGE_DIAGNOSTIC artifact=current_kernel_module_image_set check=dkms_install_output expected=exactly_one_module_image observed=missing_or_ambiguous command_status=0 next=inspect_dkms_install_outputs_read_only retained_state=unchanged\n' >&2
  blocked "unexpected DKMS module paths"
fi
dkms_installed_module="${existing_module_candidates[0]}"
if [[ ! -f "$dkms_installed_module" || -L "$dkms_installed_module" ]]; then
  printf 'SWAPZ_PACKAGE_DIAGNOSTIC artifact=current_kernel_module_image_set check=dkms_install_output expected=regular_module_image observed=unsafe_or_nonregular command_status=0 next=inspect_dkms_install_outputs_read_only retained_state=unchanged\n' >&2
  blocked "DKMS installed module is not a regular file"
fi
persist_transaction_state promoting-qualified-module
if [[ "$dkms_installed_module" != "$installed_module" ]]; then
  rm -f -- "$dkms_installed_module"
fi
install -d -m0755 "$installed_module_dir"
install -m0644 "$module_artifact" "$installed_module"
report_qualified_digest installed_dm-swapz.ko "$qualified_module_sha256" "$installed_module" qualified_report ||
  blocked "installed module digest mismatch"
durable_package_paths "$installed_module"
persist_transaction_state module-promoted
install_test_checkpoint module-promoted

persist_transaction_state depmod-pending
"$depmod_bin" "$kernel_release"
report_qualified_digest installed_dm-swapz.ko "$qualified_module_sha256" "$installed_module" qualified_report ||
  blocked "installed module changed during depmod"
if ! verify_module_resolution; then
  report_module_resolution_failure
  blocked "module lookup does not resolve to the qualified installed image"
fi
persist_transaction_state depmod-complete
install_test_checkpoint depmod-complete

persist_transaction_state publishing-package-files
install -d -m0755 "$cli_dir" "$helper_dir" "$unit_dir" "$generator_dir"
install -m0755 "$stage_dir/swapz-primary-boot-verify" "$boot_verifier"
install -m0755 "$stage_dir/swapz-primary-runtime-health" "$runtime_health"
install -m0755 "$stage_dir/device-roundtrip" "$helper"
install -m0644 "$stage_dir/dm-swapz.ko" "$module_snapshot"
install -m0755 "$stage_dir/swapz-primary-generator" "$primary_generator"
install -m0644 "$stage_dir/swapz-primary-mapper.service" "$mapper_service"
install -m0644 "$stage_dir/swapz-primary-boot-verify.service" "$boot_verifier_service"
install -m0644 "$stage_dir/swapz-primary-runtime-health.service" "$runtime_health_service"
install -m0644 "$stage_dir/$swap_unit_name" "$primary_swap"
new_files_committed=1

# The activation-capable CLI is intentionally absent until the exact module,
# non-CLI helpers, unit files and systemd's cached unit view are all ready.
{
  sha256sum "$boot_verifier" "$runtime_health" "$helper" "$module_snapshot" \
    "$primary_generator" "$mapper_service" "$boot_verifier_service" \
    "$runtime_health_service" "$primary_swap" "$installed_module"
  printf '%s  %s\n' "$qualified_cli_sha256" "$cli"
} > "$src/$binary_manifest"
report_qualified_digest installed_roundtrip_oracle "$qualified_oracle_sha256" \
    "$helper" qualified_report ||
  blocked "installed round-trip oracle digest verification failed"
report_qualified_digest installed_module_snapshot "$qualified_module_sha256" \
    "$module_snapshot" qualified_report ||
  blocked "installed module snapshot digest verification failed"
report_qualified_digest installed_dm-swapz.ko "$qualified_module_sha256" \
    "$installed_module" qualified_report ||
  blocked "installed module digest verification failed"
durable_package_paths "$boot_verifier" "$runtime_health" "$helper" \
  "$module_snapshot" "$primary_generator" "$mapper_service" \
  "$boot_verifier_service" "$runtime_health_service" "$primary_swap" \
  "$src/$binary_manifest"
persist_transaction_state package-files-published
install_test_checkpoint package-files-published

persist_transaction_state systemd-reload-pending
"$systemctl_bin" daemon-reload
persist_transaction_state systemd-reload-complete
install_test_checkpoint systemd-reload-complete

# Re-admit the exact installed bytes and running-kernel DKMS registration
# immediately before creating any activation-capable CLI entry point.
pre_activation_status=""
query_dkms_status pre_activation_status -m swapz -v "$version" -k "$kernel_release" ||
  blocked "cannot recheck current-kernel DKMS state before CLI publication"
dkms_status_exact_installed "$pre_activation_status" ||
  blocked "current-kernel DKMS state changed before CLI publication"
verify_installed_module_set && verify_module_resolution &&
  verify_source_metadata && verify_source_manifest ||
  blocked "installed module or source provenance changed before CLI publication"
pre_activation_files=(
  "$boot_verifier" "$runtime_health" "$helper" "$module_snapshot"
  "$primary_generator" "$mapper_service" "$boot_verifier_service"
  "$runtime_health_service" "$primary_swap"
)
pre_activation_staged=(
  "$stage_dir/swapz-primary-boot-verify" "$stage_dir/swapz-primary-runtime-health"
  "$stage_dir/device-roundtrip" "$stage_dir/dm-swapz.ko"
  "$stage_dir/swapz-primary-generator" "$stage_dir/swapz-primary-mapper.service"
  "$stage_dir/swapz-primary-boot-verify.service"
  "$stage_dir/swapz-primary-runtime-health.service" "$stage_dir/$swap_unit_name"
)
pre_activation_modes=(755 755 755 644 755 644 644 644 644)
for ((file_index=0; file_index<${#pre_activation_files[@]}; ++file_index)); do
  installed_file_metadata "${pre_activation_files[file_index]}" \
    "${pre_activation_modes[file_index]}" &&
    cmp -s "${pre_activation_staged[file_index]}" \
      "${pre_activation_files[file_index]}" ||
    blocked "installed userspace or unit bytes changed before CLI publication"
done
report_qualified_digest installed_dm-swapz.ko "$qualified_module_sha256" "$installed_module" qualified_report ||
  blocked "installed module digest changed before CLI publication"

persist_transaction_state publishing-cli
temporary_cli="$cli_dir/.swapzctl.publish.$"
[[ ! -e "$temporary_cli" && ! -L "$temporary_cli" ]] ||
  blocked "temporary CLI destination became occupied"
install -m0755 "$stage_dir/swapzctl" "$temporary_cli"
cmp -s "$stage_dir/swapzctl" "$temporary_cli" ||
  blocked "temporary CLI digest mismatch"
mv -f -- "$temporary_cli" "$cli"
durable_package_paths "$cli"
persist_transaction_state cli-published
install_test_checkpoint cli-published
verify_owned || blocked "installed ownership or digest verification failed"
report_qualified_digest installed_swapzctl "$qualified_cli_sha256" "$cli" qualified_report ||
  blocked "installed CLI digest mismatch"
persist_transaction_state committed

transaction_active=0
trap - ERR HUP INT TERM
cleanup_status=0
remove_transaction_record || cleanup_status=$?
if (( cleanup_status != 0 )); then
  printf 'BLOCKED: install committed and exact package verified; transaction-record cleanup failed (status %d)\n'     "$cleanup_status" >&2
  exit "$cleanup_status"
fi
echo "Installed exact qualified swapz artifacts with DKMS compatibility registration; primary-swap units remain disabled"
