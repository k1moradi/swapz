#!/usr/bin/env bash
# swapz package only: never load modules, create DM devices or activate swap.
set -Eeuo pipefail
umask 022
[[ $# == 2 && ( $1 == install || $1 == uninstall ) ]] || {
  echo "BLOCKED: usage install|uninstall ABSOLUTE_PREFIX" >&2; exit 2;
}
action="$1"; prefix="$2"
[[ "$prefix" == /* && "$prefix" != / && "$prefix" != */ &&
   "$prefix" != *..* && "$prefix" != *//* && "$prefix" != *'|'* ]] || {
  echo "BLOCKED: invalid install prefix" >&2; exit 2;
}
root="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd -P)"
cd "$root"
version="$(cat src/kernel/VERSION)"
# DKMS must resolve the same version from its own installed source tree.
grep -Fqx 'PACKAGE_VERSION="$(cat "$(dirname "${BASH_SOURCE[0]}")/src/kernel/VERSION")"' dkms.conf || {
  echo "BLOCKED: DKMS config no longer follows canonical VERSION" >&2; exit 1;
}
[[ "$version" =~ ^3[.]0[.]0-alpha[.][0-9]+$ ]] &&
  grep -Fxq 'AUTOINSTALL="no"' dkms.conf || {
  echo "BLOCKED: unrecognized DKMS version/autoinstall state" >&2; exit 1;
}
test_root="$(printenv SWAPZ_PACKAGE_TEST_ROOT 2>/dev/null || true)"
if [[ -n "$test_root" ]]; then
  [[ $(id -u) != 0 ]] || { echo "BLOCKED: root test mode forbidden" >&2; exit 1; }
  sandbox="$(realpath -m -- "$test_root")"
  case "$sandbox" in "$root/build/tests/package-sandbox/"*) ;; *)
    echo "BLOCKED: test sandbox outside build/" >&2; exit 1 ;;
  esac
  [[ "$prefix" == "$sandbox/usr/local" ]] || {
    echo "BLOCKED: test prefix mismatch" >&2; exit 1;
  }
  srcbase="$sandbox/usr/src"; dkms_bin="$sandbox/bin/dkms"
  build_info="${SWAPZ_TEST_BUILD_INFO:-$root/build/source-build-info.h}"
  build_info="$(realpath -m -- "$build_info")"
  case "$build_info" in "$sandbox"/*) ;; *)
    echo "BLOCKED: test build metadata outside package sandbox" >&2; exit 1 ;;
  esac
  module_artifact="${SWAPZ_TEST_MODULE_ARTIFACT:-}"
  [[ -n "$module_artifact" ]] || {
    echo "BLOCKED: test module artifact was not supplied" >&2; exit 1;
  }
  module_artifact="$(realpath -m -- "$module_artifact")"
  case "$module_artifact" in "$sandbox"/*) ;; *)
    echo "BLOCKED: test module artifact outside package sandbox" >&2; exit 1 ;;
  esac
else
  [[ $(id -u) == 0 ]] || { echo "BLOCKED: root required" >&2; exit 1; }
  srcbase="/usr/src"
  build_info="$root/build/source-build-info.h"
  module_artifact="$root/build/kernel/experimental/dm-swapz.ko"
  dkms_bin="$(command -v dkms)" || {
    echo "BLOCKED: DKMS unavailable" >&2; exit 1;
  }
fi
primary_recovery_base="/var/lib/swapz/physical-recovery"
primary_state="$primary_recovery_base/primary-state.json"
if [[ -n "$test_root" ]]; then
  primary_recovery_base="$sandbox/var/lib/swapz/physical-recovery"
  primary_state="$primary_recovery_base/primary-state.json"
fi
[[ -x "$dkms_bin" ]] || { echo "BLOCKED: no DKMS executable" >&2; exit 1; }
src="$srcbase/swapz-$version"
cli_dir="$prefix/sbin"; cli="$cli_dir/swapzctl"
helper_dir="$prefix/libexec/swapz"; helper="$helper_dir/device-roundtrip"
unit_dir="$prefix/lib/systemd/system"
generator_dir="$prefix/lib/systemd/system-generators"
primary_generator="$generator_dir/swapz-primary-generator"
boot_verifier="$cli_dir/swapz-primary-boot-verify"
mapper_service="$unit_dir/swapz-primary-mapper.service"
boot_verifier_service="$unit_dir/swapz-primary-boot-verify.service"
swap_unit_name="$(systemd-escape --path --suffix=swap /dev/mapper/swapz-primary)"
[[ "$swap_unit_name" == 'dev-mapper-swapz\x2dprimary.swap' ]] || {
  echo "BLOCKED: unexpected systemd-escaped primary swap unit name" >&2; exit 1;
}
primary_swap="$unit_dir/$swap_unit_name"
marker=".swapz-owned"
[[ ! -L "$srcbase" && ! -L "$prefix" &&
   ! -L "$cli_dir" && ! -L "$helper_dir" &&
   ! -L "$prefix/lib" && ! -L "$prefix/lib/systemd" &&
   ! -L "$unit_dir" && ! -L "$generator_dir" ]] || {
  echo "BLOCKED: symlinked package prefix" >&2; exit 1;
}
if [[ -z "$test_root" && "$action" == uninstall ]] &&
   [[ -e /sys/module/dm_swapz || -e /sys/module/dm-swapz ]]; then
  echo "BLOCKED: loaded module; refusing DKMS removal" >&2; exit 1;
fi
if [[ "$action" == uninstall ]]; then
  [[ ! -e "$primary_state" && ! -L "$primary_state" ]] || {
    echo "BLOCKED: primary recovery state exists; preserve it during package removal" >&2
    exit 1
  }
  if compgen -G "$primary_recovery_base/partition-*.active" >/dev/null; then
    echo "BLOCKED: a primary partition ownership marker exists; preserve the recovery path during package removal" >&2
    exit 1
  fi
fi
if [[ -z "$test_root" && "$action" == uninstall ]]; then
  for unit in swapz-primary-boot-verify.service swapz-primary-mapper.service \
      "$swap_unit_name"; do
    systemctl is-active --quiet "$unit" && {
      echo "BLOCKED: $unit is active; refusing package removal" >&2; exit 1;
    }
    systemctl is-enabled --quiet "$unit" && {
      echo "BLOCKED: $unit is enabled; disable swapz through its recovery procedure first" >&2
      exit 1
    }
  done
fi
verify_owned() {
  [[ -d "$src" && ! -L "$src" && -f "$src/$marker" &&
     -f "$src/.swapz-sources.sha256" &&
     -f "$src/.swapz-binaries.sha256" &&
     -f "$cli" && ! -L "$cli" && -f "$helper" && ! -L "$helper" &&
     -f "$helper_dir/dm-swapz.ko" && ! -L "$helper_dir/dm-swapz.ko" &&
     -f "$primary_generator" && -x "$primary_generator" &&
     ! -L "$primary_generator" &&
     -f "$boot_verifier" && -x "$boot_verifier" &&
     ! -L "$boot_verifier" &&
     -f "$mapper_service" && ! -L "$mapper_service" &&
     -f "$boot_verifier_service" && ! -L "$boot_verifier_service" &&
     -f "$primary_swap" && ! -L "$primary_swap" ]] || return 1
  grep -Fxq "swapz:$version" "$src/$marker" || return 1
  (cd "$src" && sha256sum --quiet -c .swapz-sources.sha256) || return 1
  sha256sum --quiet -c "$src/.swapz-binaries.sha256" || return 1
}
cleanup_owned() {
  if [[ -e "$src/build" ]]; then
    [[ -d "$src/build" && ! -L "$src/build" &&
       -z "$(find "$src/build" -type l -print -quit)" ]] || return 1
    rm -r -- "$src/build"
  fi
  rm -f -- "$cli" "$boot_verifier" "$helper" "$helper_dir/dm-swapz.ko" \
    "$primary_generator" "$mapper_service" "$boot_verifier_service" \
    "$primary_swap"
  rmdir -- "$helper_dir"
  for file in src/kernel/Makefile src/kernel/*.c src/kernel/*.h; do
    rm -f -- "$src/src/kernel/$(basename "$file")"
  done
  rm -f -- "$src/dkms.conf" "$src/src/kernel/VERSION" "$src/$marker" \
    "$src/.swapz-sources.sha256" "$src/.swapz-binaries.sha256"
  rmdir -- "$src/src/kernel" "$src/src" "$src"
}
if [[ "$action" == uninstall ]]; then
  verify_owned || { echo "BLOCKED: foreign, absent or modified swapz package" >&2; exit 1; }
  "$dkms_bin" remove -m swapz -v "$version" --all || {
    echo "BLOCKED: DKMS remove failed; package retained" >&2; exit 1;
  }
  cleanup_owned || {
    echo "BLOCKED: package cleanup incomplete; inspect ownership" >&2; exit 1;
  }
  if [[ -z "$test_root" ]]; then
    systemctl daemon-reload || {
      echo "BLOCKED: package removed but systemd did not reload; inspect unit cache" >&2
      exit 1
    }
  fi
  echo "Uninstalled owned swapz package without touching swap"
  exit 0
fi
[[ -x build/userspace/swapzctl && -x build/tests/device-roundtrip &&
   -f "$module_artifact" && ! -L "$module_artifact" ]] || {
  echo "BLOCKED: run make before packaging" >&2; exit 1;
}
[[ -f "$build_info" && ! -L "$build_info" ]] || {
  echo "BLOCKED: committed-source build provenance missing" >&2; exit 1;
}
[[ ! -e "$src" && ! -L "$src" &&
   ! -e "$cli" && ! -L "$cli" &&
   ! -e "$helper_dir" && ! -L "$helper_dir" &&
   ! -e "$primary_generator" && ! -L "$primary_generator" &&
   ! -e "$boot_verifier" && ! -L "$boot_verifier" &&
   ! -e "$mapper_service" && ! -L "$mapper_service" &&
   ! -e "$boot_verifier_service" && ! -L "$boot_verifier_service" &&
   ! -e "$primary_swap" && ! -L "$primary_swap" ]] || {
  echo "BLOCKED: existing DKMS source/program; refusing overwrite" >&2; exit 1;
}
install -d -m0755 "$src/src/kernel" "$cli_dir" "$helper_dir" \
  "$unit_dir" "$generator_dir"
install -m0644 dkms.conf "$src/dkms.conf"
install -m0644 src/kernel/VERSION "$src/src/kernel/VERSION"
for file in src/kernel/Makefile src/kernel/*.c src/kernel/*.h; do
  install -m0644 "$file" "$src/src/kernel/$(basename "$file")"
done
# DKMS recompiles the module after installation; carry the exact provenance
# header used by the userspace binary and the development module build.
install -m0644 "$build_info" "$src/src/kernel/swapz-build-info.h"
install -m0755 build/userspace/swapzctl "$cli"
install -m0755 packaging/swapz-primary-boot-verify "$boot_verifier"
install -m0755 build/tests/device-roundtrip "$helper"
install -m0644 "$module_artifact" \
  "$helper_dir/dm-swapz.ko"
sed "s|@SWAPZ_SBINDIR@|$cli_dir|g" \
  packaging/swapz-primary-mapper.service > "$mapper_service"
chmod 0644 "$mapper_service"
sed "s|@SWAPZ_SBINDIR@|$cli_dir|g" \
  packaging/swapz-primary-boot-verify.service > "$boot_verifier_service"
chmod 0644 "$boot_verifier_service"
sed "s|@SWAPZ_SBINDIR@|$cli_dir|g" \
  packaging/swapz-primary-generator > "$primary_generator"
chmod 0755 "$primary_generator"
install -m0644 packaging/swapz-primary.swap "$primary_swap"
printf 'swapz:%s\n' "$version" > "$src/$marker"
(cd "$src" && sha256sum dkms.conf src/kernel/VERSION src/kernel/Makefile \
  src/kernel/*.c src/kernel/*.h) > "$src/.swapz-sources.sha256"
sha256sum "$cli" "$boot_verifier" "$helper" "$helper_dir/dm-swapz.ko" \
  "$primary_generator" "$mapper_service" "$boot_verifier_service" \
  "$primary_swap" > "$src/.swapz-binaries.sha256"
rollback() {
  rc=$?
  trap - ERR
  echo "BLOCKED: DKMS operation failed; attempting version-owned rollback" >&2
  if "$dkms_bin" remove -m swapz -v "$version" --all; then
    if verify_owned; then
      cleanup_owned || echo "BLOCKED: partial owned files require inspection" >&2
    else
      echo "BLOCKED: ownership changed, no deletion attempted" >&2
    fi
  else
    echo "BLOCKED: partial DKMS registration retained for inspection" >&2
  fi
  exit "$rc"
}
trap rollback ERR
"$dkms_bin" add -m swapz -v "$version"
"$dkms_bin" build -m swapz -v "$version" -k "$(uname -r)"
"$dkms_bin" install -m swapz -v "$version" -k "$(uname -r)"
status="$("$dkms_bin" status -m swapz -v "$version" -k "$(uname -r)")"
[[ "$status" == *installed* ]]
if [[ -z "$test_root" ]]; then
  systemctl daemon-reload
fi
trap - ERR
echo "Installed swapz DKMS and disabled primary-swap units; no mapper or swap activated"
