# Clean only fully completed, private swapz benchmark sessions before a
# host-memory observation. Other /tmp occupants, incomplete/quarantined runs,
# and swapz sessions without completion proof are never cleanup candidates.
swapz_clear_tmp_before_memory_check() {
    [[ $# == 0 && $(id -u) == 0 ]] || {
        printf '%s\n' 'BLOCKED: owned /tmp cleanup requires root and no arguments' >&2
        return 1
    }
    local helper_directory
    helper_directory="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)" || return 1
    timeout --signal=TERM --kill-after=2s 30s \
        python3 -I -B "$helper_directory/cleanup-owned-tmp.py" /tmp 0 1777 || {
        printf '%s\n' 'BLOCKED: cannot safely remove verified completed swapz /tmp sessions' >&2
        return 1
    }
}
