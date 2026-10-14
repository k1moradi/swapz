#!/usr/bin/env bash
# Pure fake /proc/swaps test, no privileged host operations.
set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "$0")/../../.." && pwd -P)"
source "$ROOT/tools/swap-inventory.sh"
mkdir -p "$ROOT/build/tests"
TMP="$(mktemp -d "$ROOT/build/tests/swap-inventory.XXXXXXXX")"
trap 'rm -f "$TMP/before" "$TMP/after"; rmdir "$TMP"' EXIT
cat > "$TMP/before" <<'EOF'
Filename                                Type            Size            Used            Priority
/swapfile                               file            524284          1624            -1
/dev/sda1                               partition       121863164       1616            -1
EOF
before="$(swapz_swap_inventory_identity "$TMP/before")"
cat > "$TMP/after" <<'EOF'
Filename                                Type            Size            Used            Priority
/dev/sda1                               partition       121863164       1616            -1
/swapfile                               file            524284          1620            -1
EOF
[[ "$(swapz_swap_inventory_identity "$TMP/after")" == "$before" ]] || {
    echo 'FAIL: swap usage drift/order falsely treated as inventory change' >&2
    exit 1
}
for edited in \
    '/swapfile file 524284 1620 -2' \
    '/swapfile file 524288 1620 -1' \
    '/swapfile partition 524284 1620 -1' \
    '/another-swapfile file 524284 1620 -1'; do
    printf 'Filename Type Size Used Priority\n%s\n/dev/sda1 partition 121863164 1616 -1\n' "$edited" > "$TMP/after"
    [[ "$(swapz_swap_inventory_identity "$TMP/after")" != "$before" ]] || {
        echo "FAIL: changed swap identity accepted: $edited" >&2
        exit 1
    }
done
printf 'Filename Type Size Used Priority\n/swapfile file 524284 1620 -1\n' > "$TMP/after"
[[ "$(swapz_swap_inventory_identity "$TMP/after")" != "$before" ]] || exit 1
cat "$TMP/before" > "$TMP/after"
printf '/dev/new partition 4096 0 1\n' >> "$TMP/after"
[[ "$(swapz_swap_inventory_identity "$TMP/after")" != "$before" ]] || exit 1
for bad in \
    'Filename Type Size Used Priority|/swapfile file 524284 bad -1' \
    'Filename Type Size Used Priority|/swapfile file 524284 5' \
    'Filename Type Size Used Priority|/swapfile file -42 5 -1' \
    'Filename Type Size Used Priority|/swapfile file 524284 5 -1|/swapfile file 524284 5 -1' \
    'Wrong Type Size Used Priority|/swapfile file 524284 5 -1'; do
    printf '%s\n' "$bad" | tr '|' '\n' > "$TMP/after"
    if swapz_swap_inventory_identity "$TMP/after" >/dev/null; then
        echo "FAIL: malformed inventory accepted: $bad" >&2
        exit 1
    fi
done
: > "$TMP/after"
if swapz_swap_inventory_identity "$TMP/after" >/dev/null; then
    echo 'FAIL: empty inventory accepted' >&2
    exit 1
fi
printf 'Filename Type Size Used Priority\n' > "$TMP/after"
[[ -z "$(swapz_swap_inventory_identity "$TMP/after")" ]] || exit 1
echo 'PASS: volatile Used ignored; swap configuration changes/malformed rows rejected'
