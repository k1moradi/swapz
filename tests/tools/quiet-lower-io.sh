#!/usr/bin/env bash
# Bounded paired V3 status/backing-stat quiescence. Only call on an already
# verified owned RAM null_blk. Caller owns global result; NOT thread-safe.
# It is not a promise that external I/O cannot occur during the oracle.

# All parsed counters may subsequently enter signed Bash arithmetic. Do not
# evaluate an untrusted, overflowing or octal-looking value in (( ... )).
swapz_quiet_valid_counter() {
    local value="$1" LC_COLLATE=C
    [[ $value =~ ^(0|[1-9][0-9]*)$ ]] || return 1
    (( ${#value} <= 19 )) || return 1
    (( ${#value} < 19 )) || [[ $value == 9223372036854775807 ||
                               $value < 9223372036854775807 ]]
}

swapz_quiet_observe_dmsetup() {
    local observation="$1" command_rc
    shift
    SWAPZ_QUIET_OBSERVED_DMSETUP=""
    SWAPZ_QUIET_FAILURE_DETAIL=""
    SWAPZ_QUIET_OBSERVED_DMSETUP="$(timeout --signal=TERM --kill-after=1s 5s \
        dmsetup "$@" 2>/dev/null)" && command_rc=0 || command_rc=$?
    if (( command_rc != 0 )); then
        SWAPZ_QUIET_FAILURE_DETAIL="rc=$command_rc"
        SWAPZ_QUIET_PARSE_REASON="${observation}-command-failed"
        (( command_rc == 124 || command_rc == 137 )) &&
            SWAPZ_QUIET_PARSE_REASON="${observation}-command-timeout"
        return 1
    fi
}

# The complete single-line INFO status must contain the production fields at
# both ends, with no incomplete, duplicate or unparseable key/value tokens.
swapz_quiet_parse_status() {
    local status_text="$1" token key value required_field
    local -n parsed_values="$2"
    local expected_field_count=479
    local token_index=0
    local -a fields=()
    local -A seen_fields=()
    local IFS=$' \t\n'

    SWAPZ_QUIET_PARSE_REASON=malformed-status
    SWAPZ_QUIET_PARSE_DETAIL=""
    [[ -n $status_text ]] || {
        SWAPZ_QUIET_PARSE_DETAIL=empty-line
        return 1
    }
    (( ${#status_text} <= 65536 )) || {
        SWAPZ_QUIET_PARSE_DETAIL="line-too-long:length=${#status_text}"
        return 1
    }
    [[ $status_text != *$'\n'* && $status_text != *$'\r'* ]] || {
        SWAPZ_QUIET_PARSE_DETAIL=multiline-status
        return 1
    }
    [[ $status_text != *" status_snapshot_error="* ]] || {
        SWAPZ_QUIET_PARSE_REASON=status-snapshot-error
        SWAPZ_QUIET_PARSE_DETAIL=status-snapshot-error-field
        return 1
    }
    read -r -a fields <<< "$status_text"
    # Current production INFO has three DM header fields plus 476 complete
    # key/value fields, including a literal numeric compatibility token.
    # Schema drift blocks qualification until this oracle and its
    # source-derived rootless fixture are updated together.
    if (( ${#fields[@]} < expected_field_count )); then
        SWAPZ_QUIET_PARSE_REASON=incomplete-status
        SWAPZ_QUIET_PARSE_DETAIL="field-count:expected=${expected_field_count}:actual=${#fields[@]}"
        return 1
    fi
    (( ${#fields[@]} == expected_field_count )) || {
        SWAPZ_QUIET_PARSE_DETAIL="field-count:expected=${expected_field_count}:actual=${#fields[@]}"
        return 1
    }
    if ! swapz_quiet_valid_counter "${fields[0]}" ||
       ! swapz_quiet_valid_counter "${fields[1]}"; then
        SWAPZ_QUIET_PARSE_DETAIL=invalid-dm-header-number
        return 1
    fi
    [[ ${fields[2]} == swapz ]] || {
        SWAPZ_QUIET_PARSE_DETAIL=target-name-mismatch
        return 1
    }
    [[ ${fields[1]} != 0 ]] || {
        SWAPZ_QUIET_PARSE_DETAIL=zero-length-target
        return 1
    }
    SWAPZ_QUIET_PARSED_HEADER="${fields[0]} ${fields[1]} ${fields[2]}"
    parsed_values=()
    for token in "${fields[@]:3}"; do
        (( token_index += 1 ))
        [[ $token =~ ^([a-z][a-z0-9_]*)=(.+)$ ]] || {
            SWAPZ_QUIET_PARSE_DETAIL="invalid-field-token:index=${token_index}"
            return 1
        }
        key="${BASH_REMATCH[1]}"
        value="${BASH_REMATCH[2]}"
        (( ${#key} <= 64 )) || {
            SWAPZ_QUIET_PARSE_DETAIL="field-key-too-long:length=${#key}"
            return 1
        }
        [[ -z ${seen_fields[$key]+present} && $key != status_snapshot_error ]] || {
            SWAPZ_QUIET_PARSE_DETAIL="duplicate-or-reserved-field:key=${key}"
            return 1
        }
        seen_fields["$key"]=1
        case "$key" in
            version|mode)
                [[ $value =~ ^[a-zA-Z0-9._-]+$ ]] || {
                    SWAPZ_QUIET_PARSE_DETAIL="invalid-text-field:key=${key}"
                    return 1
                } ;;
            error)
                if [[ $value == -* ]]; then
                    [[ $value != -0 ]] && swapz_quiet_valid_counter "${value#-}" || {
                        SWAPZ_QUIET_PARSE_DETAIL=invalid-error-field
                        return 1
                    }
                else
                    swapz_quiet_valid_counter "$value" || {
                        SWAPZ_QUIET_PARSE_DETAIL=invalid-error-field
                        return 1
                    }
                fi ;;
            *) swapz_quiet_valid_counter "$value" || {
                SWAPZ_QUIET_PARSE_DETAIL="invalid-counter-field:key=${key}"
                return 1
            } ;;
        esac
        parsed_values["$key"]="$value"
    done
    for required_field in version mode logical_write logical_read physical_write \
            physical_write_reqs physical_read physical_read_reqs compressed raw \
            zero_elided discarded gc_pages gc_read gc_write segment_discards_issued \
            read_submitted read_submitted_reqs flush_calls flush_ok flush_err \
            window_records read_payload_reqs prep_ready_current prep_slots_in_use \
            submitter_prepare_active delta64_adopted failed error completion_active \
            upper_write_completed_ok upper_write_completed_err endio_write_forced_err; do
        [[ -n ${seen_fields[$required_field]+present} ]] || {
            SWAPZ_QUIET_PARSE_REASON="missing-status-field:$required_field"
            SWAPZ_QUIET_PARSE_DETAIL="missing-required-field:key=${required_field}"
            return 1
        }
    done
    [[ ${fields[-1]} == "endio_write_forced_err=${parsed_values[endio_write_forced_err]}" ]] || {
        SWAPZ_QUIET_PARSE_DETAIL=terminal-field-mismatch
        return 1
    }
    [[ ${parsed_values[failed]} == 0 || ${parsed_values[failed]} == 1 ]] || {
        SWAPZ_QUIET_PARSE_DETAIL=invalid-failed-flag
        return 1
    }
}

swapz_quiet_observe_identity() {
    local mapping_name="$1" identity_text uuid major minor events
    swapz_quiet_observe_dmsetup identity info -c --noheadings --separator : \
        -o uuid,major,minor,events "$mapping_name" || return 1
    identity_text="$SWAPZ_QUIET_OBSERVED_DMSETUP"
    SWAPZ_QUIET_PARSE_REASON=malformed-mapping-identity
    [[ ${#identity_text} -le 512 && $identity_text != *$'\n'* &&
       $identity_text =~ ^[[:blank:]]*([A-Za-z0-9_.+-]+)[[:blank:]]*:[[:blank:]]*([^:[:blank:]]+)[[:blank:]]*:[[:blank:]]*([^:[:blank:]]+)[[:blank:]]*:[[:blank:]]*([^:[:blank:]]+)[[:blank:]]*$ ]] || return 1
    uuid="${BASH_REMATCH[1]}"
    major="${BASH_REMATCH[2]}"
    minor="${BASH_REMATCH[3]}"
    events="${BASH_REMATCH[4]}"
    swapz_quiet_valid_counter "$major" && [[ $major != 0 ]] &&
        swapz_quiet_valid_counter "$minor" &&
        swapz_quiet_valid_counter "$events" || return 1
    SWAPZ_QUIET_OBSERVED_IDENTITY="$uuid:$major:$minor:$events"
}

swapz_quiet_observe_lower() {
    local stats_file="$1" stats_text value
    local -n lower_fields="$2"
    local IFS=$' \t\n'
    SWAPZ_QUIET_PARSE_REASON=lower-stat-read-failed
    stats_text="$(cat -- "$stats_file" 2>/dev/null)" || return 1
    SWAPZ_QUIET_PARSE_REASON=malformed-lower-stat
    [[ -n $stats_text && ${#stats_text} -le 4096 &&
       $stats_text != *$'\n'* && $stats_text != *$'\r'* ]] || return 1
    read -r -a lower_fields <<< "$stats_text"
    # Parse canonical Linux widths without padding omitted discard/flush
    # counters; the caller requires the complete 17-field layout to qualify.
    case ${#lower_fields[@]} in 11|15|17) ;; *) return 1 ;; esac
    for value in "${lower_fields[@]}"; do
        swapz_quiet_valid_counter "$value" || return 1
    done
}

swapz_quiet_unavailable() {
    local phase="$1" reason="$2" attempts="$3" budget="$4"
    local retained_status=none retained_evidence=none
    local -a retained_parts=()

    [[ -n $SWAPZ_QUIET_RETAINED_IDENTITY_BEFORE ]] && retained_parts+=(identity-before)
    [[ -n $SWAPZ_QUIET_RETAINED_STATUS_BEFORE ]] && {
        retained_status=initial
        retained_parts+=(status-before)
    }
    (( ${#SWAPZ_QUIET_RETAINED_LOWER_BEFORE[@]} != 0 )) &&
        retained_parts+=(lower-before)
    [[ -n $SWAPZ_QUIET_RETAINED_STATUS_AFTER ]] && {
        retained_status=initial+final
        retained_parts+=(status-after)
    }
    (( ${#SWAPZ_QUIET_RETAINED_LOWER_AFTER[@]} != 0 )) &&
        retained_parts+=(lower-after)
    [[ -n $SWAPZ_QUIET_RETAINED_IDENTITY_AFTER ]] &&
        retained_parts+=(identity-after)
    if (( ${#retained_parts[@]} != 0 )); then
        printf -v retained_evidence '%s,' "${retained_parts[@]}"
        retained_evidence="${retained_evidence%,}"
    fi
    SWAPZ_QUIET_LAST_FAILURE="phase=$phase reason=$reason attempts=$attempts/$budget retained_status=$retained_status retained_evidence=$retained_evidence"
    [[ -n $SWAPZ_QUIET_FAILURE_DETAIL ]] &&
        SWAPZ_QUIET_LAST_FAILURE+=" detail=$SWAPZ_QUIET_FAILURE_DETAIL"
    if [[ ($phase == initial-status || $phase == final-status) &&
          -n $SWAPZ_QUIET_PARSE_DETAIL ]]; then
        SWAPZ_QUIET_LAST_FAILURE+=" parse_detail=$SWAPZ_QUIET_PARSE_DETAIL"
    fi
    printf 'UNAVAILABLE: quiet-lower-io %s published=none\n' "$SWAPZ_QUIET_LAST_FAILURE" >&2
    return 1
}

swapz_capture_quiescent_io() {
    local mapping_name="$1" lower_stats_file="$2" maximum_attempts="$3"
    local interval_seconds="$4" initial_status final_status initial_identity
    local final_identity baseline_identity="" baseline_header="" baseline_width=0
    local initial_header="" attempt counter_key counter_index sleep_rc mismatch_reason
    local target_work_active active_counter_key
    local -a initial_lower=() final_lower=() previous_final_lower=()
    local -A initial_values=() final_values=() previous_final_values=()
    local -a monotonic_status_fields=(logical_write logical_read physical_write
        physical_write_reqs physical_read physical_read_reqs
        upper_write_completed_ok upper_write_completed_err endio_write_forced_err)
    local -a active_status_fields=(prep_ready_current prep_slots_in_use
        submitter_prepare_active completion_active)

    SWAPZ_QUIET_STATUS=""
    SWAPZ_QUIET_LOWER=()
    SWAPZ_QUIET_ATTEMPTS=0
    SWAPZ_QUIET_LAST_FAILURE=""
    SWAPZ_QUIET_FAILURE_DETAIL=""
    SWAPZ_QUIET_RETAINED_STATUS_BEFORE=""
    SWAPZ_QUIET_RETAINED_STATUS_AFTER=""
    SWAPZ_QUIET_RETAINED_LOWER_BEFORE=()
    SWAPZ_QUIET_RETAINED_LOWER_AFTER=()
    SWAPZ_QUIET_RETAINED_IDENTITY_BEFORE=""
    SWAPZ_QUIET_RETAINED_IDENTITY_AFTER=""

    [[ $mapping_name =~ ^[a-zA-Z0-9_][a-zA-Z0-9_.+-]*$ &&
       $maximum_attempts =~ ^[1-9][0-9]?$ &&
       $interval_seconds =~ ^(0|[1-9])(\.[0-9]{1,3})?$ &&
       -f $lower_stats_file && -r $lower_stats_file && ! -L $lower_stats_file ]] &&
       command -v dmsetup >/dev/null 2>&1 &&
       command -v timeout >/dev/null 2>&1 || {
        swapz_quiet_unavailable prerequisite invalid-or-missing 0 0
        return 1
    }
    for ((attempt=1; attempt<=maximum_attempts; ++attempt)); do
        active_counter_key=""
        SWAPZ_QUIET_FAILURE_DETAIL=""
        SWAPZ_QUIET_RETAINED_STATUS_BEFORE=""
        SWAPZ_QUIET_RETAINED_STATUS_AFTER=""
        SWAPZ_QUIET_RETAINED_LOWER_BEFORE=()
        SWAPZ_QUIET_RETAINED_LOWER_AFTER=()
        SWAPZ_QUIET_RETAINED_IDENTITY_BEFORE=""
        SWAPZ_QUIET_RETAINED_IDENTITY_AFTER=""

        swapz_quiet_observe_identity "$mapping_name" ||
            { swapz_quiet_unavailable initial-identity "$SWAPZ_QUIET_PARSE_REASON" "$attempt" "$maximum_attempts"; return 1; }
        initial_identity="$SWAPZ_QUIET_OBSERVED_IDENTITY"
        SWAPZ_QUIET_RETAINED_IDENTITY_BEFORE="$initial_identity"
        if [[ -n $baseline_identity && $initial_identity != "$baseline_identity" ]]; then
            swapz_quiet_unavailable initial-identity mapping-identity-changed "$attempt" "$maximum_attempts"
            return 1
        fi
        baseline_identity="$initial_identity"
        swapz_quiet_observe_dmsetup status status "$mapping_name" ||
            { swapz_quiet_unavailable initial-status "$SWAPZ_QUIET_PARSE_REASON" "$attempt" "$maximum_attempts"; return 1; }
        initial_status="$SWAPZ_QUIET_OBSERVED_DMSETUP"
        swapz_quiet_parse_status "$initial_status" initial_values ||
            { swapz_quiet_unavailable initial-status "$SWAPZ_QUIET_PARSE_REASON" "$attempt" "$maximum_attempts"; return 1; }
        initial_header="$SWAPZ_QUIET_PARSED_HEADER"
        SWAPZ_QUIET_RETAINED_STATUS_BEFORE="$initial_status"
        if [[ -n $baseline_header && $initial_header != "$baseline_header" ]]; then
            swapz_quiet_unavailable initial-status mapping-geometry-changed "$attempt" "$maximum_attempts"
            return 1
        fi
        baseline_header="$initial_header"
        # An unstable prior window cannot be followed by an apparent stable
        # window after counters have wrapped or reset between observations.
        if (( attempt > 1 )); then
            for counter_key in "${monotonic_status_fields[@]}"; do
                if (( initial_values[$counter_key] < previous_final_values[$counter_key] )); then
                    swapz_quiet_unavailable initial-status counter-regression-or-wrap "$attempt" "$maximum_attempts"
                    return 1
                fi
            done
        fi
        swapz_quiet_observe_lower "$lower_stats_file" initial_lower ||
            { swapz_quiet_unavailable initial-lower "$SWAPZ_QUIET_PARSE_REASON" "$attempt" "$maximum_attempts"; return 1; }
        SWAPZ_QUIET_RETAINED_LOWER_BEFORE=("${initial_lower[@]}")
        if (( baseline_width != 0 && ${#initial_lower[@]} != baseline_width )); then
            swapz_quiet_unavailable initial-lower lower-counter-width-changed "$attempt" "$maximum_attempts"
            return 1
        fi
        baseline_width=${#initial_lower[@]}
        if (( baseline_width != 17 )); then
            swapz_quiet_unavailable initial-lower incomplete-lower-stat-prerequisite "$attempt" "$maximum_attempts"
            return 1
        fi
        if (( attempt > 1 )); then
            for ((counter_index=0; counter_index<baseline_width; ++counter_index)); do
                if (( counter_index != 8 && initial_lower[counter_index] < previous_final_lower[counter_index] )); then
                    swapz_quiet_unavailable initial-lower counter-regression-or-wrap "$attempt" "$maximum_attempts"
                    return 1
                fi
            done
        fi

        if sleep "$interval_seconds"; then
            SWAPZ_QUIET_FAILURE_DETAIL=""
        else
            sleep_rc=$?
            SWAPZ_QUIET_FAILURE_DETAIL="rc=$sleep_rc"
            mismatch_reason=interval-command-failed
            (( sleep_rc == 124 || sleep_rc == 137 )) && mismatch_reason=interval-timeout
            swapz_quiet_unavailable sample-interval "$mismatch_reason" "$attempt" "$maximum_attempts"
            return 1
        fi
        swapz_quiet_observe_dmsetup status status "$mapping_name" ||
            { swapz_quiet_unavailable final-status "$SWAPZ_QUIET_PARSE_REASON" "$attempt" "$maximum_attempts"; return 1; }
        final_status="$SWAPZ_QUIET_OBSERVED_DMSETUP"
        swapz_quiet_parse_status "$final_status" final_values ||
            { swapz_quiet_unavailable final-status "$SWAPZ_QUIET_PARSE_REASON" "$attempt" "$maximum_attempts"; return 1; }
        SWAPZ_QUIET_RETAINED_STATUS_AFTER="$final_status"
        if [[ $SWAPZ_QUIET_PARSED_HEADER != "$baseline_header" ]]; then
            swapz_quiet_unavailable final-status mapping-geometry-changed "$attempt" "$maximum_attempts"
            return 1
        fi
        swapz_quiet_observe_lower "$lower_stats_file" final_lower ||
            { swapz_quiet_unavailable final-lower "$SWAPZ_QUIET_PARSE_REASON" "$attempt" "$maximum_attempts"; return 1; }
        SWAPZ_QUIET_RETAINED_LOWER_AFTER=("${final_lower[@]}")
        if (( ${#final_lower[@]} != baseline_width )); then
            swapz_quiet_unavailable final-lower lower-counter-width-changed "$attempt" "$maximum_attempts"
            return 1
        fi
        swapz_quiet_observe_identity "$mapping_name" ||
            { swapz_quiet_unavailable final-identity "$SWAPZ_QUIET_PARSE_REASON" "$attempt" "$maximum_attempts"; return 1; }
        final_identity="$SWAPZ_QUIET_OBSERVED_IDENTITY"
        SWAPZ_QUIET_RETAINED_IDENTITY_AFTER="$final_identity"
        if [[ $final_identity != "$baseline_identity" ]]; then
            swapz_quiet_unavailable final-identity mapping-identity-changed "$attempt" "$maximum_attempts"
            return 1
        fi
        for counter_key in "${monotonic_status_fields[@]}"; do
            if (( final_values[$counter_key] < initial_values[$counter_key] )); then
                swapz_quiet_unavailable target-counter counter-regression-or-wrap "$attempt" "$maximum_attempts"
                return 1
            fi
        done
        for ((counter_index=0; counter_index<baseline_width; ++counter_index)); do
            # stat field 8 is in-flight I/O (a gauge), not a monotonic counter.
            if (( counter_index != 8 && final_lower[counter_index] < initial_lower[counter_index] )); then
                swapz_quiet_unavailable lower-counter counter-regression-or-wrap "$attempt" "$maximum_attempts"
                return 1
            fi
        done
        # Equal samples are not quiescent while a lower request or target-owned
        # preparation/completion is still active across the whole interval.
        mismatch_reason=unstable-target-status
        if [[ "$initial_status" == "$final_status" ]]; then
            mismatch_reason=unstable-lower-counter
            if [[ "${initial_lower[*]}" == "${final_lower[*]}" ]]; then
                mismatch_reason=lower-io-in-flight
                if (( initial_lower[8] == 0 )); then
                    target_work_active=0
                    for counter_key in "${active_status_fields[@]}"; do
                        if (( initial_values[$counter_key] != 0 )); then
                            target_work_active=1
                            active_counter_key="$counter_key"
                            break
                        fi
                    done
                    mismatch_reason=active-target-work
                    if (( target_work_active == 0 )); then
                        SWAPZ_QUIET_STATUS="$final_status"
                        SWAPZ_QUIET_LOWER=("${final_lower[@]}")
                        SWAPZ_QUIET_ATTEMPTS="$attempt"
                        SWAPZ_QUIET_RETAINED_STATUS_BEFORE=""
                        SWAPZ_QUIET_RETAINED_STATUS_AFTER=""
                        SWAPZ_QUIET_RETAINED_LOWER_BEFORE=()
                        SWAPZ_QUIET_RETAINED_LOWER_AFTER=()
                        SWAPZ_QUIET_RETAINED_IDENTITY_BEFORE=""
                        SWAPZ_QUIET_RETAINED_IDENTITY_AFTER=""
                        return 0
                    fi
                    # Identify the outstanding work class without exposing
                    # its counter value or any raw status text.
                    SWAPZ_QUIET_FAILURE_DETAIL="active_field=$active_counter_key"
                fi
            fi
        fi
        previous_final_lower=("${final_lower[@]}")
        for counter_key in "${monotonic_status_fields[@]}"; do
            previous_final_values["$counter_key"]="${final_values[$counter_key]}"
        done
    done
    swapz_quiet_unavailable attempt-budget "exhausted:$mismatch_reason" "$maximum_attempts" "$maximum_attempts"
}
