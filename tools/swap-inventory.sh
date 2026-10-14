#!/usr/bin/env bash
# Canonical host swap identity for isolated RAM-only tests.
# "Used" is volatile, not a change in swap-device configuration.
swapz_swap_inventory_identity() {
    local input="$1" lines
    [[ -r "$input" ]] || return 1
    lines="$(awk '
        NR == 1 {
            if (NF != 5 || $1 != "Filename" || $2 != "Type" ||
                $3 != "Size" || $4 != "Used" || $5 != "Priority")
                exit 1
            next
        }
        {
            if (NF != 5 || substr($1, 1, 1) != "/" ||
                $3 !~ /^[0-9]+$/ || $4 !~ /^[0-9]+$/ ||
                $5 !~ /^-?[0-9]+$/ || seen[$1]++)
                exit 1
            printf "%s\t%s\t%s\t%s\n", $1, $2, $3, $5
        }
        END { if (NR == 0) exit 1 }
    ' "$input")" || return 1
    [[ -n "$lines" ]] || return 0
    printf '%s\n' "$lines" | LC_ALL=C sort
}
