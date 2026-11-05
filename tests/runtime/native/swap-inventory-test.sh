#!/usr/bin/env bash
# Pure fake /proc/swaps test, no privileged host operations.
set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "$0")/../../.." && pwd -P)"
source "$ROOT/tests/tools/swap-inventory.sh"
mkdir -p "$ROOT/build/tests"
TMP="$(mktemp -d "$ROOT/build/tests/swap-inventory.XXXXXXXX")"
trap 'rm -f "$TMP/before" "$TMP/after" "$TMP/result" "$TMP/diagnostic"; rmdir "$TMP"' EXIT
cat > "$TMP/before" <<'EOF'
Filename                                Type            Size            Used            Priority
/swapfile                               file            524284          1624            -1
/dev/sda1                               partition       121863164       1616            -1
EOF
before="$(swapz_swap_inventory_identity "$TMP/before")"
[[ "$before" == $'/dev/sda1\tpartition\t121863164\t-1\n/swapfile\tfile\t524284\t-1' ]] || {
    echo 'FAIL: valid inventory output changed' >&2
    exit 1
}
# Compare parse failures by phase, record index, category and original exit code.
expect_invalid_inventory() {
    local case_name="$1" phase="$2" record="$3" expected="$4" observed="$5"
    local exit_status=0 diagnostic
    swapz_swap_inventory_identity "$TMP/after" >"$TMP/result" 2>"$TMP/diagnostic" || exit_status=$?
    diagnostic="$(cat "$TMP/diagnostic")"
    if (( exit_status != 1 )) || [[ -s "$TMP/result" ]] ||
        [[ "$diagnostic" != *"phase=$phase record=$record"* ||
           "$diagnostic" != *"expected=$expected observed=$observed first_exit=1"* ]]; then
        printf 'FAIL: %s exit=%d diagnostic=%s\n' "$case_name" "$exit_status" "$diagnostic" >&2
        exit 1
    fi
}

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
    if swapz_swap_inventory_identity "$TMP/after" >/dev/null 2>"$TMP/diagnostic"; then
        echo "FAIL: malformed inventory accepted: $bad" >&2
        exit 1
    fi
done
: > "$TMP/after"
if swapz_swap_inventory_identity "$TMP/after" >/dev/null 2>"$TMP/diagnostic"; then
    echo 'FAIL: empty inventory accepted' >&2
    exit 1
fi
printf 'Filename Type Size Used Priority\n' > "$TMP/after"
[[ -z "$(swapz_swap_inventory_identity "$TMP/after")" ]] || exit 1
# Reject malformed rows even when two observations would contain identical bad text.
for case_data in \
    'invalid-type|/swapfile unknown 524284 5 -1|file-or-partition|invalid-type' \
    'zero-capacity|/swapfile file 0 0 -1|positive-u64-decimal|invalid-capacity' \
    'leading-zero-capacity|/swapfile file 0524284 5 -1|positive-u64-decimal|invalid-capacity' \
    'oversized-capacity|/swapfile file 18446744073709551616 5 -1|positive-u64-decimal|invalid-capacity' \
    'used-greater-than-size|/swapfile file 4 5 -1|decimal-not-greater-than-size|invalid-usage' \
    'leading-zero-used|/swapfile file 8 05 -1|decimal-not-greater-than-size|invalid-usage' \
    'priority-overflow|/swapfile file 524284 5 2147483648|signed-int-decimal|invalid-priority' \
    'priority-underflow|/swapfile file 524284 5 -2147483649|signed-int-decimal|invalid-priority' \
    'negative-zero-priority|/swapfile file 524284 5 -0|signed-int-decimal|invalid-priority' \
    'unknown-path-escape|/swap\999file file 524284 5 -1|kernel-escaped-path|invalid-escape-or-nul' \
    'unescaped-backslash|/swap\name file 524284 5 -1|kernel-escaped-path|invalid-escape-or-nul'; do
    IFS='|' read -r case_name swap_row expected observed <<< "$case_data"
    printf 'Filename Type Size Used Priority\n%s\n' "$swap_row" > "$TMP/after"
    field="Size"
    case "$case_name" in
        invalid-type) field="Type" ;;
        used-greater-than-size|leading-zero-used) field="Used" ;;
        priority-*) field="Priority" ;;
        negative-zero-priority) field="Priority" ;;
        *escape|unescaped-backslash) field="Filename" ;;
    esac
    expect_invalid_inventory "$case_name" parse 2 "$expected" "$observed"
done

printf '%s\n' 'Filename Type Size Used Priority' '/swap\040name file 4096 3 -1' '/swap\040name file 4096 1 -1' > "$TMP/after"
expect_invalid_inventory 'duplicated decoded pathname' parse 3 unique-decoded-path duplicate-decoded-path
printf '%s\n' 'Filename Type Size Used Priority' '/swap\134name file 4096 3 -1' '/swap\name file 4096 1 -1' > "$TMP/after"
expect_invalid_inventory 'alternate noncanonical escape' parse 3 kernel-escaped-path invalid-escape-or-nul
printf 'Filename Type Size Used Priority\n/swapfile file 4096 3 -1' > "$TMP/after"
expect_invalid_inventory 'missing final newline' read last newline-terminated-record unterminated-or-empty
printf 'Filename Type Size Used Priority' > "$TMP/after"
expect_invalid_inventory 'unterminated empty inventory' read last newline-terminated-record unterminated-or-empty
printf 'Filename Type Size Used Priority\n/swapfile file 4096 3' > "$TMP/after"
expect_invalid_inventory 'truncated final row' read last newline-terminated-record unterminated-or-empty
printf 'Filename Type Size Used Priority\n/swapfile file 4096\n' > "$TMP/after"
expect_invalid_inventory 'missing fields' parse 2 five-fields invalid-field-count
printf 'Filename Type Size Used Priority\n/sw\0ap file 4096 3 -1\n' > "$TMP/after"
expect_invalid_inventory 'embedded NUL' parse 2 kernel-escaped-path invalid-escape-or-nul
printf -v long_name '%08192d' 0
printf 'Filename Type Size Used Priority\n/%s file 4096 3 -1\n' "$long_name" > "$TMP/after"
expect_invalid_inventory 'oversized record' parse 2 shorter-than-8192-bytes oversized-record
LC_ALL=C awk 'BEGIN {
    print "Filename Type Size Used Priority"
    for (record_index = 1; record_index <= 65537; record_index++)
        printf "/swap%d file 4096 0 -1\n", record_index
}' > "$TMP/after"
expect_invalid_inventory 'too many records' parse 65538 at-most-65536-swap-rows too-many-rows
LC_ALL=C awk 'BEGIN {
    print "Filename Type Size Used Priority"
    path_suffix = sprintf("%06000d", 0)
    for (record_index = 1; record_index <= 2800; record_index++)
        printf "/swap%d%s file 4096 0 -1\n", record_index, path_suffix
}' > "$TMP/after"
# The phase/category must match; row index varies with decimal path length.
exit_status=0
swapz_swap_inventory_identity "$TMP/after" >"$TMP/result" 2>"$TMP/diagnostic" || exit_status=$?
[[ "$exit_status" == 1 && ! -s "$TMP/result" ]] || exit 1
[[ "$(cat "$TMP/diagnostic")" == *'phase=parse record='*' expected=at-most-16MiB observed=oversized-inventory first_exit=1' ]] || exit 1

# An unsuccessful sort must not leak a plausible partial identity to stdout.
printf 'Filename Type Size Used Priority\n/swapfile file 4096 3 -1\n' > "$TMP/after"
sort() { printf 'plausible-but-unsorted\n'; return 73; }
exit_status=0
swapz_swap_inventory_identity "$TMP/after" >"$TMP/result" 2>"$TMP/diagnostic" || exit_status=$?
unset -f sort
[[ "$exit_status" == 73 && ! -s "$TMP/result" ]] || exit 1
[[ "$(cat "$TMP/diagnostic")" == *'phase=sort record=all expected=sortable-inventory observed=sort-error first_exit=73' ]] || exit 1

# Kernel escapes are lexical data; this does not authenticate filesystem inodes.
cat > "$TMP/after" <<'EOF'
Filename Type Size Used Priority
/swap\040space\011tab\012newline\134slash file 4096 3 -1
EOF
swapz_swap_inventory_identity "$TMP/after" >"$TMP/result" 2>"$TMP/diagnostic"
[[ ! -s "$TMP/diagnostic" ]] || exit 1
[[ "$(cat "$TMP/result")" == $'/swap\\040space\\011tab\\012newline\\134slash\tfile\t4096\t-1' ]] || exit 1

# Different syntactic paths can still alias one inode; equality never proves backing identity.
printf 'Filename Type Size Used Priority\n/alias/../swapfile file 4096 3 -1\n/swapfile file 4096 1 -1\n' > "$TMP/after"
[[ "$(swapz_swap_inventory_identity "$TMP/after" | wc -l)" == 2 ]] || exit 1
echo 'PASS: Used/order tolerance; strict syntactic inventory checks; physical identity remains unproven'
