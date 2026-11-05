#!/usr/bin/env bash
# Syntactic /proc/swaps inventory identity for isolated RAM-only tests.
# This is not proof of the kernel-held inode/device behind a swap pathname.
# "Used" is volatile, not a change in swap-device configuration.
swapz_swap_inventory_identity() {
    local input="$1" snapshot="" snapshot_bytes="" identity=""
    local operation_status=0 cleanup_status=0

    # /dev/stdin can be a one-shot pipe. Snapshot it once, within the same
    # bound as the parser, before tail and awk independently read the input.
    if [[ "$input" == /dev/stdin ]]; then
        if snapshot="$(mktemp "${TMPDIR:-/tmp}/swapz-swap-inventory.XXXXXXXX" 2>/dev/null)"; then
            :
        else
            operation_status=$?
            printf 'swap-inventory: phase=stream-snapshot-create record=all expected=private-snapshot observed=create-error first_exit=%d\n' "$operation_status" >&2
            return "$operation_status"
        fi

        if head -c 16777217 -- "$input" > "$snapshot" 2>/dev/null; then
            :
        else
            operation_status=$?
            printf 'swap-inventory: phase=stream-snapshot-read record=all expected=readable-stream observed=read-error first_exit=%d\n' "$operation_status" >&2
        fi

        if (( operation_status == 0 )); then
            if snapshot_bytes="$(wc -c < "$snapshot" 2>/dev/null)"; then
                snapshot_bytes="${snapshot_bytes//[[:space:]]/}"
                if [[ ! "$snapshot_bytes" =~ ^[0-9]+$ ]]; then
                    operation_status=1
                    printf '%s\n' 'swap-inventory: phase=stream-snapshot-size record=all expected=decimal-byte-count observed=invalid-byte-count first_exit=1' >&2
                elif (( snapshot_bytes > 16777216 )); then
                    operation_status=1
                    printf '%s\n' 'swap-inventory: phase=stream-snapshot-size record=all expected=at-most-16MiB observed=oversized-inventory first_exit=1' >&2
                fi
            else
                operation_status=$?
                printf 'swap-inventory: phase=stream-snapshot-size record=all expected=readable-byte-count observed=size-error first_exit=%d\n' "$operation_status" >&2
            fi
        fi

        if (( operation_status == 0 )); then
            if identity="$(swapz_swap_inventory_identity_file "$snapshot")"; then
                :
            else
                operation_status=$?
            fi
        fi

        if rm -f -- "$snapshot" 2>/dev/null; then
            :
        else
            cleanup_status=$?
        fi

        if (( operation_status != 0 )); then
            if (( cleanup_status != 0 )); then
                printf 'swap-inventory: phase=stream-snapshot-cleanup record=all expected=temporary-file-removed observed=cleanup-error secondary_exit=%d\n' "$cleanup_status" >&2
            fi
            return "$operation_status"
        fi
        if (( cleanup_status != 0 )); then
            printf 'swap-inventory: phase=stream-snapshot-cleanup record=all expected=temporary-file-removed observed=cleanup-error first_exit=%d\n' "$cleanup_status" >&2
            return "$cleanup_status"
        fi
        [[ -n "$identity" ]] && printf '%s\n' "$identity"
        return 0
    fi

    swapz_swap_inventory_identity_file "$input"
}

swapz_swap_inventory_identity_file() {
    local input="$1" lines last_byte sorted_lines exit_status
    if [[ ! -r "$input" ]]; then
        printf '%s\n' 'swap-inventory: phase=open record=input expected=readable-inventory observed=unreadable first_exit=1' >&2
        return 1
    fi
    if last_byte="$(LC_ALL=C tail -c 1 -- "$input" && printf '.')"; then
        if [[ "$last_byte" != $'\n.' ]]; then
            printf '%s\n' 'swap-inventory: phase=read record=last expected=newline-terminated-record observed=unterminated-or-empty first_exit=1' >&2
            return 1
        fi
    else
        exit_status=$?
        printf 'swap-inventory: phase=read record=last expected=readable-last-byte observed=read-error first_exit=%d\n' "$exit_status" >&2
        return "$exit_status"
    fi
    if lines="$(LC_ALL=C awk '
        function reject(field, expected, observed) {
            printf "swap-inventory: phase=parse record=%d field=%s expected=%s observed=%s first_exit=1\n", \
                NR, field, expected, observed > "/dev/stderr"
            exit 1
        }
        function within_limit(number, maximum) {
            return length(number) < length(maximum) || \
                (length(number) == length(maximum) && ("x" number) <= ("x" maximum))
        }
        function decode_path(encoded_path,    decoded_path, position, character, escaped_code) {
            if (index(encoded_path, "\\") == 0 && index(encoded_path, sprintf("%c", 0)) == 0)
                return encoded_path
            decoded_path = ""
            for (position = 1; position <= length(encoded_path); position++) {
                character = substr(encoded_path, position, 1)
                if (character == sprintf("%c", 0))
                    return ""
                if (character == "\\") {
                    escaped_code = substr(encoded_path, position + 1, 3)
                    if (escaped_code == "040") character = " "
                    else if (escaped_code == "011") character = "\t"
                    else if (escaped_code == "012") character = "\n"
                    else if (escaped_code == "134") character = "\\"
                    else return ""
                    position += 3
                }
                decoded_path = decoded_path character
            }
            return decoded_path
        }
        {
            inventory_bytes += length($0) + 1
            if (inventory_bytes > 16777216)
                reject("inventory", "at-most-16MiB", "oversized-inventory")
            # length($0) excludes the mandatory newline byte.
            if (length($0) >= 8191)
                reject("record", "shorter-than-8192-bytes", "oversized-record")
        }
        NR == 1 {
            if ($0 != "Filename\t\t\t\tType\t\tSize\t\tUsed\t\tPriority")
                reject("header", "exact-tabbed-five-column-header", "invalid-header")
            next
        }
        {
            if (NF != 5)
                reject("record", "five-fields", "invalid-field-count")
            if (substr($1, 1, 1) != "/")
                reject("Filename", "absolute-path", "nonabsolute-path")
            decoded_path = decode_path($1)
            if (decoded_path == "")
                reject("Filename", "kernel-escaped-path", "invalid-escape-or-nul")
            if ($2 != "file" && $2 != "partition")
                reject("Type", "file-or-partition", "invalid-type")
            if ($3 !~ /^[1-9][0-9]*$/ || !within_limit($3, "18446744073709551615"))
                reject("Size", "positive-u64-decimal", "invalid-capacity")
            if ($4 !~ /^(0|[1-9][0-9]*)$/ || !within_limit($4, $3))
                reject("Used", "decimal-not-greater-than-size", "invalid-usage")
            if ($5 !~ /^(0|[1-9][0-9]*|-[1-9][0-9]*)$/ ||
                (substr($5, 1, 1) == "-" && !within_limit(substr($5, 2), "2147483648")) ||
                (substr($5, 1, 1) != "-" && !within_limit($5, "2147483647")))
                reject("Priority", "signed-int-decimal", "invalid-priority")
            if (seen[decoded_path]++)
                reject("Filename", "unique-decoded-path", "duplicate-decoded-path")
            if (NR > 65537)
                reject("record", "at-most-65536-swap-rows", "too-many-rows")
            printf "%s\t%s\t%s\t%s\n", $1, $2, $3, $5
        }
        END {
            if (NR == 0)
                reject("header", "exact-tabbed-five-column-header", "empty-inventory")
        }
    ' "$input")"; then
        :
    else
        exit_status=$?
        if (( exit_status != 1 )); then
            printf 'swap-inventory: phase=read record=unknown expected=readable-inventory observed=awk-error first_exit=%d\n' "$exit_status" >&2
        fi
        return "$exit_status"
    fi
    [[ -n "$lines" ]] || return 0
    if sorted_lines="$(LC_ALL=C sort <<< "$lines")"; then
        printf '%s\n' "$sorted_lines"
    else
        exit_status=$?
        printf 'swap-inventory: phase=sort record=all expected=sortable-inventory observed=sort-error first_exit=%d\n' "$exit_status" >&2
        return "$exit_status"
    fi
}
