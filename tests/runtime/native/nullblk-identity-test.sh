#!/usr/bin/env bash
# Rootless fixture test: fake sysfs only, no module, block IO or mknod.
set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "$0")/../../.." && pwd -P)"
source "$ROOT/tests/tools/nullblk-identity.sh"
mkdir -p "$ROOT/build/tests"
TMP="$(mktemp -d "$ROOT/build/tests/nullblk-name.XXXXXXXX")"
NAME=nullb-swapz-0123456789abcdef
cleanup() {
    rm -f -- "$TMP/$NAME/dev" "$TMP/nullb7/dev"
    rmdir "$TMP/$NAME" "$TMP/nullb7" "$TMP"
}
trap cleanup EXIT
mkdir "$TMP/$NAME" "$TMP/nullb7"
printf '240:7\n' > "$TMP/$NAME/dev"
[[ "$(swapz_resolve_owned_disk "$NAME" 7 "$TMP")" == "$NAME" ]]
rm "$TMP/$NAME/dev"
printf '240:7\n' > "$TMP/nullb7/dev"
[[ "$(swapz_resolve_owned_disk "$NAME" 7 "$TMP")" == nullb7 ]]
printf '240:7\n' > "$TMP/$NAME/dev"
if swapz_resolve_owned_disk "$NAME" 7 "$TMP" >/dev/null; then
    echo 'FAIL ambiguous disk accepted' >&2; exit 1
fi
rm "$TMP/$NAME/dev" "$TMP/nullb7/dev"
if swapz_resolve_owned_disk "$NAME" 7 "$TMP" >/dev/null; then
    echo 'FAIL absent disk accepted' >&2; exit 1
fi
if swapz_resolve_owned_disk swapz-0123456789abcdef 7 "$TMP" >/dev/null; then
    echo 'FAIL unsafe name accepted' >&2; exit 1
fi
if swapz_resolve_owned_disk "$NAME" abc "$TMP" >/dev/null; then
    echo 'FAIL invalid index accepted' >&2; exit 1
fi
echo 'PASS: supported null_blk names, missing/ambiguous refused'
