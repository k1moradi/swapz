#!/usr/bin/env bash
# Pure/read-only name discovery. Caller MUST also prove actual null_blk
# driver major, index/minor, sysfs devno, node rdev, size and ownership.
swapz_resolve_owned_disk() {
    local name="$1" index="$2" sysblock="$3"
    [[ "$name" =~ ^nullb-swapz-[a-f0-9]{16}$ ]] || return 2
    [[ "$index" =~ ^(0|[1-9][0-9]*)$ ]] || return 2
    local selected_disk selected_devno extra_devno
    if [[ -r "$sysblock/$name/dev" && ! -e "$sysblock/nullb$index/dev" ]]; then
        selected_disk="$name"
    elif [[ -r "$sysblock/nullb$index/dev" && ! -e "$sysblock/$name/dev" ]]; then
        selected_disk="nullb$index"
    else
        return 1
    fi

    # A readable, uniquely named sysfs entry with malformed or symlinked dev
    # telemetry is not usable device identity. The caller must still prove
    # actual null_blk major/minor, node rdev, index, geometry and ownership.
    [[ -f "$sysblock/$selected_disk/dev" &&
       ! -L "$sysblock/$selected_disk/dev" ]] || return 1
    {
        IFS= read -r selected_devno || return 1
        if IFS= read -r extra_devno || [[ -n $extra_devno ]]; then
            return 1
        fi
    } < "$sysblock/$selected_disk/dev"
    [[ "$selected_devno" =~ ^(0|[1-9][0-9]*):(0|[1-9][0-9]*)$ ]] ||
        return 1
    printf '%s\n' "$selected_disk"
}
