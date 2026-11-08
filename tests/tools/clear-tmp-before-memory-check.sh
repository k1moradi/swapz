# Clean fully completed private benchmark sessions and deployments older
# than one hour before the host-memory observation.
# Keep unrelated /tmp occupants, recent deployments, failed/quarantined
# sessions and all sessions without matching completion proof.
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
