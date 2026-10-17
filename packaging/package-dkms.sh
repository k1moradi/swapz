#!/usr/bin/env bash
# V3 package only: never load modules, create DM devices or activate swap.
set -Eeuo pipefail
umask 022
[[ $# == 2 && ( $1 == install || $1 == uninstall ) ]] || {
  echo "BLOCKED: usage install|uninstall ABSOLUTE_PREFIX" >&2; exit 2;
}
action="$1"; prefix="$2"
[[ "$prefix" == /* && "$prefix" != / && "$prefix" != */ &&
   "$prefix" != *..* && "$prefix" != *//* ]] || {
  echo "BLOCKED: invalid install prefix" >&2; exit 2;
}
root="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd -P)"
cd "$root"
version="$(cat kernel/extent-v3/VERSION)"
# DKMS must resolve the same version from its own installed source tree.
grep -Fqx 'PACKAGE_VERSION="$(cat "$(dirname "${BASH_SOURCE[0]}")/kernel/extent-v3/VERSION")"' dkms.conf || {
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
else
  [[ $(id -u) == 0 ]] || { echo "BLOCKED: root required" >&2; exit 1; }
  srcbase="/usr/src"
  dkms_bin="$(command -v dkms)" || {
    echo "BLOCKED: DKMS unavailable" >&2; exit 1;
  }
fi
[[ -x "$dkms_bin" ]] || { echo "BLOCKED: no DKMS executable" >&2; exit 1; }
src="$srcbase/swapz-$version"
cli_dir="$prefix/sbin"; cli="$cli_dir/swapz3ctl"
helper_dir="$prefix/libexec/swapz"; helper="$helper_dir/device-roundtrip"
marker=".swapz-v3-owned"
[[ ! -L "$srcbase" && ! -L "$prefix" &&
   ! -L "$cli_dir" && ! -L "$helper_dir" ]] || {
  echo "BLOCKED: symlinked package prefix" >&2; exit 1;
}
if [[ "$action" == uninstall ]] &&
   [[ -e /sys/module/dm_swapz || -e /sys/module/dm-swapz ]]; then
  echo "BLOCKED: loaded module; refusing DKMS removal" >&2; exit 1;
fi
verify_owned() {
  [[ -d "$src" && ! -L "$src" && -f "$src/$marker" &&
     -f "$src/.swapz-v3-sources.sha256" &&
     -f "$src/.swapz-v3-binaries.sha256" &&
     -f "$cli" && ! -L "$cli" && -f "$helper" && ! -L "$helper" ]] || return 1
  grep -Fxq "swapz-v3:$version" "$src/$marker" || return 1
  (cd "$src" && sha256sum --quiet -c .swapz-v3-sources.sha256) || return 1
  sha256sum --quiet -c "$src/.swapz-v3-binaries.sha256" || return 1
}
cleanup_owned() {
  if [[ -e "$src/build" ]]; then
    [[ -d "$src/build" && ! -L "$src/build" &&
       -z "$(find "$src/build" -type l -print -quit)" ]] || return 1
    rm -r -- "$src/build"
  fi
  rm -f -- "$cli" "$helper"
  rmdir -- "$helper_dir"
  for file in kernel/extent-v3/Makefile kernel/extent-v3/*.c kernel/extent-v3/*.h; do
    rm -f -- "$src/kernel/extent-v3/$(basename "$file")"
  done
  rm -f -- "$src/dkms.conf" "$src/kernel/extent-v3/VERSION" "$src/$marker" \
    "$src/.swapz-v3-sources.sha256" "$src/.swapz-v3-binaries.sha256"
  rmdir -- "$src/kernel/extent-v3" "$src/kernel" "$src"
}
if [[ "$action" == uninstall ]]; then
  verify_owned || { echo "BLOCKED: foreign, absent or modified V3 package" >&2; exit 1; }
  "$dkms_bin" remove -m swapz -v "$version" --all || {
    echo "BLOCKED: DKMS remove failed; package retained" >&2; exit 1;
  }
  cleanup_owned || {
    echo "BLOCKED: package cleanup incomplete; inspect ownership" >&2; exit 1;
  }
  echo "Uninstalled owned V3 package without touching swap"
  exit 0
fi
[[ -x build/userspace/swapz3ctl && -x build/tests/device-roundtrip ]] || {
  echo "BLOCKED: run make before packaging" >&2; exit 1;
}
if [[ -z "$test_root" ]]; then
  [[ -f build/kernel/experimental/dm-swapz.ko ]] || {
    echo "BLOCKED: V3 kernel module missing" >&2; exit 1;
  }
fi
[[ ! -e "$src" && ! -L "$src" &&
   ! -e "$cli" && ! -L "$cli" &&
   ! -e "$helper_dir" && ! -L "$helper_dir" ]] || {
  echo "BLOCKED: existing DKMS source/program; refusing overwrite" >&2; exit 1;
}
install -d -m0755 "$src/kernel/extent-v3" "$cli_dir" "$helper_dir"
install -m0644 dkms.conf "$src/dkms.conf"
install -m0644 kernel/extent-v3/VERSION "$src/kernel/extent-v3/VERSION"
for file in kernel/extent-v3/Makefile kernel/extent-v3/*.c kernel/extent-v3/*.h; do
  install -m0644 "$file" "$src/kernel/extent-v3/$(basename "$file")"
done
install -m0755 build/userspace/swapz3ctl "$cli"
install -m0755 build/tests/device-roundtrip "$helper"
printf 'swapz-v3:%s\n' "$version" > "$src/$marker"
(cd "$src" && sha256sum dkms.conf kernel/extent-v3/VERSION kernel/extent-v3/Makefile \
  kernel/extent-v3/*.c kernel/extent-v3/*.h) > "$src/.swapz-v3-sources.sha256"
sha256sum "$cli" "$helper" > "$src/.swapz-v3-binaries.sha256"
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
trap - ERR
echo "Installed V3 DKMS, read-only swapz3ctl and helper; module NOT loaded"
