# Clear temporary files before a host-memory observation.
# Callers run this only during serialized qualification on the owner host.
swapz_clear_tmp_before_memory_check() {
    local tmp_metadata nested_mount leftover

    [[ $(id -u) == 0 ]] || {
        printf '%s\n' 'BLOCKED: clearing /tmp before memory admission requires root' >&2
        return 1
    }
    [[ -d /tmp && ! -L /tmp ]] || {
        printf '%s\n' 'BLOCKED: /tmp is not a real directory' >&2
        return 1
    }
    tmp_metadata="$(stat -c '%u:%a' -- /tmp 2>/dev/null)" || {
        printf '%s\n' 'BLOCKED: cannot verify /tmp ownership and mode' >&2
        return 1
    }
    [[ $tmp_metadata == 0:1777 ]] || {
        printf '%s\n' 'BLOCKED: /tmp is not root-owned mode 1777' >&2
        return 1
    }

    # Do not let recursive removal cross a mount nested below /tmp. Mountinfo
    # escapes whitespace, but the /tmp/ prefix remains unambiguous.
    nested_mount="$(awk '$5 != "/tmp" && index($5, "/tmp/") == 1 { print $5; exit }' \
        /proc/self/mountinfo 2>/dev/null)" || {
        printf '%s\n' 'BLOCKED: cannot inspect mounts below /tmp' >&2
        return 1
    }
    [[ -z $nested_mount ]] || {
        printf '%s\n' 'BLOCKED: a mountpoint exists below /tmp' >&2
        return 1
    }

    find /tmp -mindepth 1 -maxdepth 1 -exec rm -rf -- {} + || {
        printf '%s\n' 'BLOCKED: could not clear all /tmp contents' >&2
        return 1
    }
    leftover="$(find /tmp -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null)" || {
        printf '%s\n' 'BLOCKED: cannot verify that /tmp is empty' >&2
        return 1
    }
    [[ -z $leftover ]] || {
        printf '%s\n' 'BLOCKED: /tmp was repopulated during cleanup' >&2
        return 1
    }
}
