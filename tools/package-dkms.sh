#!/usr/bin/env bash
# V3 only. Installing DKMS is NEVER activation; no module loading, swapon,
# swapoff, dmsetup, host swap modifications or access to physical media.
set -Eeuo pipefail
[[ $# == 2 && ( $1 == install || $1 == uninstall ) ]] || {
  echo "BLOCKED: usage package-dkms.sh install|uninstall ABSOLUTE_PREFIX" >&2; exit 2;
}
action="$1"
prefix="$2"
[[ "$prefix" == /* && "$prefix" != / && "$prefix" != *'..'* && "$prefix" != *'//'*
   && "$prefix" != *'/' ]] || { echo "BLOCKED: unsafe PREFIX" >&2; exit 2; }
[[ $(id -u) == 0 ]] || { echo "BLOCKED: root required for DKMS" >&2; exit 1; }
command -v dkms >/dev/null || { echo "BLOCKED: dkms missing" >&2; exit 1; }
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd "$root"
version="$(sed -n 's/^PACKAGE_VERSION="\([^"]*\)"$/\1/p' dkms.conf)"
[[ "$version" =~ ^3\.0\.0-alpha\.[0-9]+$ ]] || {
  echo "BLOCKED: unexpected version" >&2; exit 1;
}
grep -Fxq 'AUTOINSTALL="no"' dkms.conf || {
  echo "BLOCKED: DKMS autoinstall must stay disabled" >&2; exit 1;
}
src="/usr/src/swapz-$version"
dir="$prefix/libexec/swapz"
bin="$dir/device-roundtrip"
marker=".swapz-v3-owned"
if [[ "$action" == uninstall ]] && [[ -e /sys/module/dm_swapz || -e /sys/module/dm-swapz ]]; then
  echo "BLOCKED: module is loaded; never remove an active module" >&2; exit 1
fi
if [[ "$action" == install ]]; then
  [[ -f build/kernel/experimental/dm-swapz.ko && -x build/tests/device-roundtrip ]] || {
    echo "BLOCKED: build with make -j2 first" >&2; exit 1;
  }
  [[ ! -e "$src" && ! -L "$src" && ! -e "$dir" && ! -L "$dir" ]] || {
    echo "BLOCKED: existing package or install destination; refusing overwrite" >&2; exit 1;
  }
  install -d -m0755 "$src/kernel/extent-v3" "$dir"
  install -m0644 dkms.conf "$src/dkms.conf"
  for file in kernel/extent-v3/Makefile kernel/extent-v3/*.c kernel/extent-v3/*.h; do
    install -m0644 "$file" "$src/kernel/extent-v3/$(basename "$file")"
  done
  printf 'swapz-v3:%s\n' "$version" > "$src/$marker"
  printf 'swapz-v3:%s\n' "$version" > "$dir/$marker"
  install -m0755 build/tests/device-roundtrip "$bin"
  dkms add -m swapz -v "$version"
  dkms build -m swapz -v "$version" -k "$(uname -r)"
  dkms install -m swapz -v "$version" -k "$(uname -r)"
  echo "V3 DKMS package and safe binary installed; module NOT loaded"
  exit 0
fi
[[ ! -L "$src" && ! -L "$dir" && -f "$src/$marker" && -f "$dir/$marker" ]] || {
  echo "BLOCKED: package not owned by swapz V3" >&2; exit 1;
}
grep -Fxq "swapz-v3:$version" "$src/$marker" &&
  grep -Fxq "swapz-v3:$version" "$dir/$marker" || {
  echo "BLOCKED: package ownership mismatch" >&2; exit 1;
}
[[ -f "$bin" && ! -L "$bin" ]] || { echo "BLOCKED: helper missing or replaced" >&2; exit 1; }
# Only DKMS's version-scoped uninstall; NEVER unload/force-remove a module.
dkms remove -m swapz -v "$version" --all
rm -f -- "$bin" "$dir/$marker"
rmdir -- "$dir"
for file in kernel/extent-v3/Makefile kernel/extent-v3/*.c kernel/extent-v3/*.h; do
  rm -f -- "$src/kernel/extent-v3/$(basename "$file")"
done
rm -f -- "$src/dkms.conf" "$src/$marker"
rmdir -- "$src/kernel/extent-v3" "$src/kernel" "$src"
echo "Removed only the owned V3 DKMS package and helper"
