#!/usr/bin/env bash
# Pure/read-only name discovery. Caller MUST also prove actual null_blk
# driver major, index/minor, sysfs devno, node rdev, size and ownership.
# Reject missing final newlines, extra records, symlinks and oversized devnos.
# This read-only telemetry parser cannot establish creation authority.
swapz_read_canonical_devno() {
    local device_record_path="$1" device_number='' extra_record=''
    [[ -f "$device_record_path" && ! -L "$device_record_path" ]] || return 1
    {
        IFS= read -r device_number || return 1
        if IFS= read -r extra_record || [[ -n $extra_record ]]; then
            return 1
        fi
    } < "$device_record_path"
    [[ ${#device_number} -le 21 &&
       "$device_number" =~ ^(0|[1-9][0-9]*):(0|[1-9][0-9]*)$ ]] || return 1
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
