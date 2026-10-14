#!/usr/bin/env bash
# Bounded paired V3 status/backing-stat quiescence. Only call on an already
# verified owned RAM null_blk. Caller owns global result; NOT thread-safe.
# It is not a promise that external I/O cannot occur during the oracle.
swapz_capture_quiescent_io() {
    local mapping_name="$1" lower_stats_file="$2" maximum_attempts="$3"
    local interval_seconds="$4" initial_status final_status attempt
    local -a initial_lower=() final_lower=()

    SWAPZ_QUIET_STATUS=""
    SWAPZ_QUIET_LOWER=()
    SWAPZ_QUIET_ATTEMPTS=0
    [[ $maximum_attempts =~ ^[1-9][0-9]*$ ]] || return 1
    for ((attempt=1; attempt<=maximum_attempts; ++attempt)); do
        initial_status="$(dmsetup status "$mapping_name")" || return 1
        read -r -a initial_lower < "$lower_stats_file" || return 1
        (( ${#initial_lower[@]} >= 7 )) || return 1
        sleep "$interval_seconds" || return 1
        final_status="$(dmsetup status "$mapping_name")" || return 1
        read -r -a final_lower < "$lower_stats_file" || return 1
        (( ${#final_lower[@]} >= 7 )) || return 1
        # Compare the entire status AND stat line; no untracked changes to
        # in-flight, read, write, or flush counters during the sample.
        if [[ "$initial_status" == "$final_status" &&
              "${initial_lower[*]}" == "${final_lower[*]}" ]]; then
            SWAPZ_QUIET_STATUS="$final_status"
            SWAPZ_QUIET_LOWER=("${final_lower[@]}")
            SWAPZ_QUIET_ATTEMPTS="$attempt"
            return 0
        fi
    done
    return 1
}
