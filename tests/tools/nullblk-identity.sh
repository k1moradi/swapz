#!/usr/bin/env bash
# Pure/read-only name discovery. Caller MUST also prove actual null_blk
# driver major, index/minor, sysfs devno, node rdev, size and ownership.
# Reject missing final newlines, extra records, symlinks and oversized devnos.
# This read-only telemetry parser cannot establish creation authority.
swapz_read_bounded_record() {
    local result_variable="$1" record_path="$2" max_characters="$3"
    local record='' extra_byte=''
    [[ "$max_characters" =~ ^([1-9]|[1-5][0-9]|6[0-4])$ ]] || return 2
    [[ -f "$record_path" && ! -L "$record_path" ]] || return 1
    {
        IFS= read -r -n "$((max_characters + 1))" record || return 1
        [[ ${#record} -le max_characters ]] || return 1
        if IFS= read -r -n 1 extra_byte || [[ -n $extra_byte ]]; then
            return 1
        fi
    } < "$record_path"
    printf -v "$result_variable" '%s' "$record"
}

swapz_read_canonical_uint() {
    local record_path="$1" max_digits="${2:-20}" value=''
    swapz_read_bounded_record value "$record_path" "$max_digits" || return $?
    [[ "$value" =~ ^(0|[1-9][0-9]*)$ ]] || return 1
    printf '%s\n' "$value"
}

swapz_read_canonical_devno() {
    local device_record_path="$1" device_number=''
    swapz_read_bounded_record device_number "$device_record_path" 21 || return $?
    [[ "$device_number" =~ ^(0|[1-9][0-9]*):(0|[1-9][0-9]*)$ ]] || return 1
    printf '%s\n' "$device_number"
}

swapz_resolve_owned_disk() {
    local name="$1" index="$2" sysblock="$3"
    [[ "$name" =~ ^nullb-swapz-[a-f0-9]{16}$ ]] || return 2
    [[ "$index" =~ ^(0|[1-9][0-9]*)$ ]] || return 2
    local selected_disk
    if [[ -r "$sysblock/$name/dev" &&
          ! -e "$sysblock/nullb$index" &&
          ! -L "$sysblock/nullb$index" ]]; then
        selected_disk="$name"
    elif [[ -r "$sysblock/nullb$index/dev" &&
            ! -e "$sysblock/$name" &&
            ! -L "$sysblock/$name" ]]; then
        selected_disk="nullb$index"
    else
        return 1
    fi

    # Any alternate disk entry is an ambiguous alias, even when its dev
    # attribute is absent or dangling. A readable, uniquely named sysfs entry
    # with malformed or symlinked dev
    # telemetry is not usable device identity. The caller must still prove
    # actual null_blk major/minor, node rdev, index, geometry and ownership.
    swapz_read_canonical_devno "$sysblock/$selected_disk/dev" >/dev/null ||
        return 1
    printf '%s\n' "$selected_disk"
}
