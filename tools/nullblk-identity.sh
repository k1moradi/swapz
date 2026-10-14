#!/usr/bin/env bash
# Pure/read-only name discovery. Caller MUST also prove actual null_blk
# driver major, index/minor, sysfs devno, node rdev, size and ownership.
swapz_resolve_owned_disk() {
    local name="$1" index="$2" sysblock="$3"
    [[ "$name" =~ ^nullb-swapz-[a-f0-9]{16}$ ]] || return 2
    [[ "$index" =~ ^(0|[1-9][0-9]*)$ ]] || return 2
    if [[ -r "$sysblock/$name/dev" && ! -e "$sysblock/nullb$index/dev" ]]; then
        printf '%s\n' "$name"
    elif [[ -r "$sysblock/nullb$index/dev" && ! -e "$sysblock/$name/dev" ]]; then
        printf 'nullb%s\n' "$index"
    else
        return 1
    fi
}
