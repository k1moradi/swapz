#!/usr/bin/env bash
# Private rootless half of make test, also used in unprivileged CI.
set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)"
cd "$ROOT"

# Bash's built-in SECONDS attributes failure wall time without a child process
# for each passing test. The official reporter still captures unmodified test
# stdout/stderr; only a failed command creates a local private diagnostic.
rootless_stage_started_seconds=$SECONDS
rootless_phase='rootless initialization'
rootless_phase_started_seconds=$SECONDS
rootless_failure_reported=0

# Capture completed source-controlled suite boundaries without new processes
# or changes to the existing first-failure/cleanup traps. These measurements
# are observational and emitted only when all rootless contracts finish.
rootless_timed_phase=$rootless_phase
rootless_timing_names=()
rootless_timing_seconds=()
rootless_begin_phase() {
  local phase_boundary_seconds=$SECONDS
  rootless_timing_names+=("$rootless_timed_phase")
  rootless_timing_seconds+=("$((phase_boundary_seconds - rootless_phase_started_seconds))")
  rootless_timed_phase=$rootless_phase
  rootless_phase_started_seconds=$phase_boundary_seconds
}

rootless_private_diagnostic_path=
rootless_private_diagnostic_log=
rootless_capture_directory=
rootless_capture_path=
rootless_capture_input_fd=2
rootless_capture_output_fd=
rootless_capture_pid=
rootless_capture_failure_reason=
rootless_classified_reason=nonzero_exit
rootless_classified_subtest=unavailable
rootless_classified_test=unavailable
rootless_classified_unittest_class=unavailable
rootless_classified_kind=unavailable
rootless_classified_errno=unavailable

begin_rootless_private_stderr_capture() {
  rootless_capture_directory=
  rootless_capture_path=
  rootless_capture_input_fd=2
  rootless_capture_output_fd=
  rootless_capture_pid=
  rootless_capture_failure_reason=
  command -v tee >/dev/null 2>&1 || return 0
  mkdir -p "$ROOT/build/tests" >/dev/null 2>&1 || return 0
  [[ -d $ROOT/build/tests && ! -L $ROOT/build/tests ]] || return 0
  rootless_capture_directory=$(
    mktemp -d "$ROOT/build/tests/rootless-failure.XXXXXXXX" 2>/dev/null
  ) || return 0
  rootless_capture_path="$rootless_capture_directory/diagnostic.log"
  # Captured stages write diagnostics to stderr. Relay those bytes unchanged
  # while retaining one private copy for a failed run.
  coproc ROOTLESS_STDERR_CAPTURE {
    umask 077
    # Keep the unused coprocess output pipe alive until tee exits. It carries
    # no child bytes and gives the parent a bounded, fail-only EOF signal.
    exec 3>&1
    # Relay diagnostics are private; never print a failed tee pathname.
    exec tee "$rootless_capture_path" >&2 2>/dev/null
  }
  rootless_capture_input_fd=${ROOTLESS_STDERR_CAPTURE[1]}
  rootless_capture_output_fd=${ROOTLESS_STDERR_CAPTURE[0]}
  rootless_capture_pid=$ROOTLESS_STDERR_CAPTURE_PID
}

finish_rootless_private_stderr_capture() {
  local original_exit_code=$1
  local capture_exit_code=0
  local cleanup_failed=0
  local relay_read_status=0
  local relay_unexpected_byte=
  if [[ -n $rootless_capture_pid ]]; then
    # Once the tested child exits, a descendant can still hold the input pipe.
    # Probe the relay's unused output pipe, without copying child output or
    # waiting indefinitely for tee. EOF is the only complete-capture proof.
    if ! exec {rootless_capture_input_fd}>&-; then
      rootless_capture_failure_reason=stderr_relay_failure
    fi
    if IFS= read -r -n 1 -t 5 -u "$rootless_capture_output_fd" \
        relay_unexpected_byte 2>/dev/null; then
      relay_read_status=0
    else
      relay_read_status=$?
    fi
    if (( relay_read_status != 1 )) || [[ -n $relay_unexpected_byte ]]; then
      # An incomplete relay cannot authenticate the first unittest identity.
      rootless_capture_failure_reason=stderr_relay_failure
      kill -KILL "$rootless_capture_pid" 2>/dev/null || :
    fi
    if ! exec {rootless_capture_output_fd}<&-; then
      rootless_capture_failure_reason=stderr_relay_failure
    fi
    if wait "$rootless_capture_pid" 2>/dev/null; then
      :
    else
      capture_exit_code=$?
      rootless_capture_failure_reason=stderr_relay_failure
    fi
  fi

  if (( original_exit_code == 0 )); then
    if [[ -n $rootless_capture_path ]]; then
      rm -f -- "$rootless_capture_path" 2>/dev/null || cleanup_failed=1
    fi
    if [[ -n $rootless_capture_directory ]]; then
      rmdir -- "$rootless_capture_directory" 2>/dev/null || cleanup_failed=1
    fi
  elif [[ -n $rootless_capture_path && -f $rootless_capture_path &&
          ! -L $rootless_capture_path ]]; then
    rootless_private_diagnostic_path=$rootless_capture_path
    rootless_private_diagnostic_log="build/tests/${rootless_capture_directory##*/}/diagnostic.log"
  else
    if [[ -n $rootless_capture_path ]]; then
      rm -f -- "$rootless_capture_path" 2>/dev/null || cleanup_failed=1
    fi
    if [[ -n $rootless_capture_directory ]]; then
      rmdir -- "$rootless_capture_directory" 2>/dev/null || cleanup_failed=1
    fi
  fi

  # A cleanup error must not replace the first failed child status. A passing
  # child with a broken relay is reported as a harness failure instead.
  if (( cleanup_failed != 0 )) && [[ -z $rootless_capture_failure_reason ]]; then
    rootless_capture_failure_reason=stderr_relay_cleanup_failure
  fi
  # A failed child retains any surviving regular capture even when the relay
  # itself failed. Partial bytes remain private diagnostic evidence only; they
  # never authenticate unittest identity. If cleanup failed before unlinking a
  # passing capture, reuse that file instead of orphaning it and allocating a
  # second log.
  if (( cleanup_failed != 0 )) &&
     [[ -n $rootless_capture_directory && -d $rootless_capture_directory &&
        ! -L $rootless_capture_directory && -n $rootless_capture_path &&
        -f $rootless_capture_path && ! -L $rootless_capture_path ]]; then
    rootless_private_diagnostic_path=$rootless_capture_path
    rootless_private_diagnostic_log="build/tests/${rootless_capture_directory##*/}/diagnostic.log"
  fi

  rootless_capture_directory=
  rootless_capture_path=
  rootless_capture_input_fd=2
  rootless_capture_output_fd=
  rootless_capture_pid=
}

classify_rootless_private_unittest_failure() {
  local diagnostic_path=$1
  local line
  local detailed_header_regex="^(FAIL|ERROR): (test_[A-Za-z0-9_]{1,96}) \\(__main__\\.(PackageLifecycle|PrimaryRealSwapContracts|SourceAdmissionPeerOwnership|GeneratorPublicationTest|PrimaryLifecycleBehaviorTest|PrimaryLifecycleSourceGuardTest|PackageCrashToPrimaryAdmissionTest|PrimaryOwnerReleaseDurabilityTest)\\.(test_[A-Za-z0-9_]{1,96})\\)"
  local progress_regex="^[[:space:]]*(test_[A-Za-z0-9_]{1,96}) \\(__main__\\.(PackageLifecycle|PrimaryRealSwapContracts|SourceAdmissionPeerOwnership|PrimaryLifecycleBehaviorTest|PrimaryLifecycleSourceGuardTest|PackageCrashToPrimaryAdmissionTest|PrimaryOwnerReleaseDurabilityTest)\\.(test_[A-Za-z0-9_]{1,96})\\)( \\([^[:cntrl:]]{1,512}\\))? \\.\\.\\. (FAIL|ERROR)$"
  local simple_phase_context_regex="^ \\(phase='([a-z0-9_-]{1,64})'\\)$"
  # Other generator subtest keys identify a failed method, never public data.
  local generator_progress_regex="^[[:space:]]*(test_[A-Za-z0-9_]{1,96}) \\(__main__\\.GeneratorPublicationTest\\.(test_[A-Za-z0-9_]{1,96})\\)( \\([^[:cntrl:]]{1,192}\\))? \\.\\.\\. (FAIL|ERROR)$"
  local subtest_regex="\\(phase='([a-z0-9_-]{1,64})'\\)$"
  local errno_regex='^(OSError|PermissionError|FileNotFoundError): \[Errno ([1-9][0-9]{0,3})\]'
  # PackageInvocationTimeout subclasses subprocess.TimeoutExpired; unittest
  # prints its custom class name rather than the base-class name.
  # Accept only the fixed, path-free watchdog envelope from the matched
  # first PackageLifecycle failure, never arbitrary child exception text.
  local package_timeout_regex='^PackageInvocationTimeout: SWAPZ_PACKAGE_TEST_TIMEOUT codec_variant=(uncompressed|unknown|mixed|[.](zst|xz|gz)) operation=(install|uninstall|recover) elapsed_seconds=[0-9]{1,5}[.][0-9]{3} budget_seconds=[0-9]{1,5}([.][0-9]{1,3})? budget_reason=(ordinary_fixture_watchdog|compressed_dkms_durable_io|explicit_test_watchdog) final_process_disposition=(reaped_exit_-?[0-9]{1,3}|kill_sent_reap_timeout) first_cause=fixture_watchdog_expired$'
  local errno_candidate
  local expected_unittest_classes=
  local progress_context=
  local first_progress_class=
  local first_progress_kind=
  local first_progress_test=
  local first_progress_subtest=unavailable
  local header_class
  local header_kind
  local header_test
  local header_subtest
  local found_failure_header=0
  rootless_classified_reason=nonzero_exit
  rootless_classified_subtest=unavailable
  rootless_classified_test=unavailable
  rootless_classified_unittest_class=unavailable
  rootless_classified_kind=unavailable
  rootless_classified_errno=unavailable
  [[ -f $diagnostic_path && -r $diagnostic_path && ! -L $diagnostic_path ]] || return 0
  # Only the active source-controlled suite can authenticate a failure.
  # Expected negative tests may relay stderr from a different unittest class.
  case $rootless_phase in
    'tests/runtime/native/package-dkms-test.py')
      expected_unittest_classes=PackageLifecycle ;;
    'tests/runtime/native/primary-lifecycle-audit-test.py')
      # This suite registers four source-controlled unittest classes.
      expected_unittest_classes='PrimaryLifecycleBehaviorTest:PrimaryLifecycleSourceGuardTest:PackageCrashToPrimaryAdmissionTest:PrimaryOwnerReleaseDurabilityTest' ;;
    'tests/runtime/native/primary-real-swap-test.py')
      expected_unittest_classes=PrimaryRealSwapContracts ;;
    'tests/runtime/native/primary-real-swap-parent-ownership-test.py')
      expected_unittest_classes=SourceAdmissionPeerOwnership ;;
    'tests/runtime/native/systemd/swapz-primary-generator-transaction-test.py')
      expected_unittest_classes=GeneratorPublicationTest ;;
    *) return 0 ;;
  esac

  # unittest preserves execution order in verbose "... FAIL/ERROR" progress
  # records, but groups detailed ERROR blocks before FAIL blocks in its summary.
  # Bind the first failed progress record to its matching detailed traceback so
  # a later teardown error cannot replace the primary assertion.
  while IFS= read -r line || [[ -n $line ]]; do
    if [[ $line =~ $progress_regex ]]; then
      [[ ":$expected_unittest_classes:" == *":${BASH_REMATCH[2]}:"* &&
         ${BASH_REMATCH[3]} == "${BASH_REMATCH[1]}" ]] || continue
      first_progress_test=${BASH_REMATCH[1]}
      first_progress_class=${BASH_REMATCH[2]}
      progress_context=${BASH_REMATCH[4]}
      first_progress_kind=${BASH_REMATCH[5]}
      # Arbitrary subtest keys remain private. Preserve the existing public
      # subtest only when the context is exactly one allowlisted phase key.
      if [[ $progress_context =~ $simple_phase_context_regex ]]; then
        first_progress_subtest=${BASH_REMATCH[1]}
      fi
    elif [[ $expected_unittest_classes == GeneratorPublicationTest &&
            $line =~ $generator_progress_regex ]]; then
      [[ ${BASH_REMATCH[2]} == "${BASH_REMATCH[1]}" ]] || continue
      # Report only the allowlisted method; arbitrary subtest details stay private.
      first_progress_test=${BASH_REMATCH[1]}
      first_progress_class=GeneratorPublicationTest
      first_progress_kind=${BASH_REMATCH[4]}
    else
      continue
    fi
    # A progress-only record is not a confirmed failure: a passing negative
    # fixture may print it before the actual suite emits its traceback.
    break
  done < "$diagnostic_path"

  while IFS= read -r line || [[ -n $line ]]; do
    if (( found_failure_header == 0 )); then
      if [[ $line =~ $detailed_header_regex ]]; then
        header_kind=${BASH_REMATCH[1]}
        header_test=${BASH_REMATCH[2]}
        header_class=${BASH_REMATCH[3]}
        [[ ":$expected_unittest_classes:" == *":$header_class:"* &&
           ${BASH_REMATCH[4]} == "$header_test" ]] || continue
        header_subtest=unavailable
        if [[ $line =~ $subtest_regex ]]; then
          header_subtest=${BASH_REMATCH[1]}
        fi
        if [[ -n $first_progress_test ]]; then
          [[ $header_kind == "$first_progress_kind" &&
             $header_test == "$first_progress_test" &&
             $header_class == "$first_progress_class" ]] || continue
          if [[ $first_progress_subtest != unavailable &&
                $header_subtest != "$first_progress_subtest" ]]; then
            continue
          fi
        else
          # Synthetic/legacy controls without verbose progress retain the
          # previous first-detailed-block fallback.
          first_progress_class=$header_class
          first_progress_subtest=$header_subtest
        fi
        # Authenticate identity only after a matching detailed failure block.
        rootless_classified_test=$header_test
        rootless_classified_unittest_class=$header_class
        rootless_classified_kind=$header_kind
        # Real unittest phase labels may contain underscores. They are useful
        # for private execution-order matching, but the existing public marker
        # grammar intentionally exposes only lowercase alnum/hyphen subtests.
        rootless_classified_subtest=unavailable
        if [[ $first_progress_subtest =~ ^[a-z0-9-]{1,64}$ ]]; then
          rootless_classified_subtest=$first_progress_subtest
        fi
        if [[ $header_kind == FAIL ]]; then
          rootless_classified_reason=unittest_assertion
        else
          rootless_classified_reason=unittest_error
        fi
        found_failure_header=1
      fi
      continue
    fi
    [[ $line == '======================================================================' ]] && break
    if [[ $line == *"subprocess.TimeoutExpired:"* ]] ||
       [[ $expected_unittest_classes == PackageLifecycle &&
          $line =~ $package_timeout_regex ]]; then
      rootless_classified_reason=unittest_timeout
    elif [[ $rootless_classified_errno == unavailable &&
            $line =~ $errno_regex ]]; then
      errno_candidate=${BASH_REMATCH[2]}
      if (( 10#$errno_candidate <= 4095 )); then
        rootless_classified_errno=$errno_candidate
      fi
    fi
  done < "$diagnostic_path"
}

# The initial Make stage can fail inside this source-extracted C fixture. Its
# Python assertion is not a unittest progress record. Authenticate the compile
# traceback only if it owns the first failed Make target; earlier Make failures
# keep first-error precedence even when another parallel job fails later.
classify_rootless_private_make_failure() {
  local diagnostic_path=$1
  local line
  local traceback_line_regex='^[[:space:]]*File "([^"]*/)?swapz-primary-late-race-test[.]py", line [0-9]+, in (compile_and_run|main|<module>)$'
  local make_error_regex='^make(\[[0-9]+\])?: \*\*\* \[[^]]+\] Error [0-9]+$'
  # Authenticate a nested target against the source-controlled recipe line.
  local make_nested_target_regex='^make(\[[0-9]+\])?: \*\*\* \[Makefile:([0-9]+): (test-(codec|predictor|mapping|gc|lower-io|userspace|replay-helper|anon-page-analyzer))\] Error [0-9]+$'
  local make_recipe_line
  local make_target
  local traceback_seen=0
  local compile_assertion_seen=0
  local compiler_error_seen=0
  rootless_classified_reason=nonzero_exit
  rootless_classified_subtest=unavailable
  rootless_classified_test=unavailable
  rootless_classified_unittest_class=unavailable
  rootless_classified_kind=unavailable
  rootless_classified_errno=unavailable
  [[ -f $diagnostic_path && -r $diagnostic_path && ! -L $diagnostic_path ]] || return 0
  while IFS= read -r line || [[ -n $line ]]; do
    if [[ $line == 'Traceback (most recent call last):' ]]; then
      traceback_seen=0
      compile_assertion_seen=0
      compiler_error_seen=0
    elif [[ $line =~ $traceback_line_regex ]]; then
      traceback_seen=1
    elif (( traceback_seen )) &&
         [[ $line =~ ^AssertionError:[[:space:]]+(production|mutant)[.]c[[:space:]]+compile[[:space:]]+failed: ]]; then
      compile_assertion_seen=1
    elif (( compile_assertion_seen )) && [[ $line == *': error:'* ]]; then
      compiler_error_seen=1
    elif [[ $line =~ $make_error_regex ]]; then
      if [[ $line =~ $make_nested_target_regex ]]; then
        make_recipe_line=${BASH_REMATCH[2]}
        make_target=${BASH_REMATCH[3]}
        # Child stderr can imitate GNU Make. Promote a target only when the
        # reported line is a recipe line actually owned by that target.
        if LC_ALL=C awk -v expected_line="$make_recipe_line" \
             -v expected_target="$make_target" '
             /^[A-Za-z0-9_.-]+:/ {
               owner = $1
               sub(/:.*/, "", owner)
             }
             NR == expected_line {
               found = 1
               matched = ($0 ~ /^\t/ && owner == expected_target)
               exit matched ? 0 : 1
             }
             END {
               if (!found) exit 1
             }
           ' "$ROOT/tests/suites/Makefile" >/dev/null 2>&1; then
          rootless_classified_subtest=$make_target
          if [[ $make_target == test-userspace ]] &&
             (( traceback_seen && compile_assertion_seen && compiler_error_seen )); then
            # The declaration and arbitrary source paths remain private. The
            # source-controlled script name and fixed compile category are public.
            rootless_classified_reason=native_compile
            rootless_classified_subtest=compile
            rootless_classified_test=swapz-primary-late-race-test.py
          fi
        fi
      fi
      return 0
    fi
  done < "$diagnostic_path"
}

report_rootless_failure() {
  local original_exit_code=$1
  local failed_at_line=$2
  local failure_reason=${3:-nonzero_exit}
  local failed_subtest=${4:-unavailable}
  local failed_test=${5:-unavailable}
  local failed_unittest_kind=${6:-unavailable}
  local failed_errno=${7:-unavailable}
  local cleanup_disposition=${8:-not_independently_verified}
  local failed_unittest_class=${9:-unavailable}
  if [[ $failed_errno != unavailable ]]; then
    if [[ ! $failed_errno =~ ^[1-9][0-9]{0,3}$ ]] ||
       (( 10#$failed_errno > 4095 )); then
      failed_errno=unavailable
    fi
  fi
  case $cleanup_disposition in
    not_independently_verified|relay_incomplete|relay_cleanup_failed) ;;
    *) cleanup_disposition=not_independently_verified ;;
  esac
  case $failed_unittest_class in
    PackageLifecycle|PrimaryRealSwapContracts|SourceAdmissionPeerOwnership|GeneratorPublicationTest|PrimaryLifecycleBehaviorTest|PrimaryLifecycleSourceGuardTest|PackageCrashToPrimaryAdmissionTest|PrimaryOwnerReleaseDurabilityTest|unavailable) ;;
    *) failed_unittest_class=unavailable ;;
  esac
  # ERR is inherited by command substitutions under -E. Their eventual
  # enclosing assertion, not an incidental internal command, owns the failure.
  if (( BASH_SUBSHELL != 0 )); then
    return "$original_exit_code"
  fi
  rootless_failure_reported=1
  trap - ERR EXIT INT TERM
  set +e
  if [[ $failure_reason == nonzero_exit &&
        $failed_subtest == unavailable && $failed_test == unavailable ]]; then
    case $original_exit_code in
      124) failure_reason=timeout_or_exit_124 ;;
      13[0-9]|14[0-9]|15[0-9]) failure_reason=signal_or_child_exit ;;
    esac
  fi
  local phase_wall_seconds=$((SECONDS - rootless_phase_started_seconds))
  local stage_wall_seconds=$((SECONDS - rootless_stage_started_seconds))
  local private_diagnostic_path=${rootless_private_diagnostic_path:-}
  local private_diagnostic_log=${rootless_private_diagnostic_log:-unavailable}
  local private_directory
  # Ordinary failures allocate only after the failure. The captured native
  # Make stage and unittests may already have private stderr, retained only on fail.
  if [[ -z $private_diagnostic_path ]]; then
    mkdir -p "$ROOT/build/tests" >/dev/null 2>&1
    if [[ -d $ROOT/build/tests && ! -L $ROOT/build/tests ]] &&
       private_directory=$(
         mktemp -d "$ROOT/build/tests/rootless-failure.XXXXXXXX" 2>/dev/null
       ); then
      private_diagnostic_path="$private_directory/diagnostic.log"
      private_diagnostic_log="build/tests/${private_directory##*/}/diagnostic.log"
      if ! (umask 077; : > "$private_diagnostic_path"); then
        private_diagnostic_path=
        private_diagnostic_log=unavailable
      fi
    fi
  fi

  if [[ -n $private_diagnostic_path && -f $private_diagnostic_path &&
        ! -L $private_diagnostic_path ]]; then
    local captured_bytes
    captured_bytes=$(wc -c < "$private_diagnostic_path" 2>/dev/null)
    if [[ ! $captured_bytes =~ ^[0-9]+$ ]]; then
      rm -f -- "$private_diagnostic_path" 2>/dev/null
      private_diagnostic_path=
      private_diagnostic_log=unavailable
    elif (( captured_bytes > 258048 )); then
      # Reserve 4096 bytes for attribution metadata inside the 256-KiB cap.
      # Keep a bounded execution-first failure excerpt plus the transcript
      # tail. Unittest blocks retain both ends; the generated-C fixture also
      # pins its first compiler error so later parallel Make output cannot
      # displace the actual declaration from private evidence.
      if LC_ALL=C awk -v target_reason="$failure_reason" \
           -v target_kind="$failed_unittest_kind" \
           -v target_test="$failed_test" \
           -v target_class="$failed_unittest_class" \
           -v target_subtest="$failed_subtest" '
           BEGIN {
             compile_mode = (target_reason == "native_compile" &&
                             target_test == "swapz-primary-late-race-test.py" &&
                             target_subtest == "compile")
             if (compile_mode) {
               prefix_limit = 24576
               suffix_limit = 24576
               critical_limit = 16384
             } else {
               prefix_limit = 32768
               suffix_limit = 32768
               critical_limit = 0
             }
           }
           function matches_target(text, pattern) {
             if (compile_mode) {
               return text ~ /^[[:space:]]*File "([^"]*\/)?swapz-primary-late-race-test[.]py", line [0-9]+, in (compile_and_run|main|<module>)$/
             }
             if (target_test != "unavailable" &&
                 target_kind != "unavailable") {
               if (target_class != "unavailable") {
                 pattern = "^" target_kind ": " target_test " \\(__main__\\." target_class "\\." target_test "\\)"
               } else {
                 pattern = "^" target_kind ": " target_test " \\(__main__\\.(PackageLifecycle|PrimaryRealSwapContracts|SourceAdmissionPeerOwnership|GeneratorPublicationTest|PrimaryLifecycleBehaviorTest|PrimaryLifecycleSourceGuardTest|PackageCrashToPrimaryAdmissionTest|PrimaryOwnerReleaseDurabilityTest)\\." target_test "\\)"
               }
               if (text !~ pattern) return 0
               if (target_subtest != "unavailable" &&
                   text !~ "\\(phase=\047" target_subtest "\047\\)$") return 0
               return 1
             }
             return text ~ /^(FAIL|ERROR): test_[A-Za-z0-9_]+ \(__main__\.(PackageLifecycle|PrimaryRealSwapContracts|SourceAdmissionPeerOwnership|GeneratorPublicationTest|PrimaryLifecycleBehaviorTest|PrimaryLifecycleSourceGuardTest|PackageCrashToPrimaryAdmissionTest|PrimaryOwnerReleaseDurabilityTest)\.test_[A-Za-z0-9_]+\)/
           }
           function target_ends(text) {
             if (compile_mode) {
               return text ~ /^make(\[[0-9]+\])?: \*\*\* \[Makefile:[0-9]+: test-userspace\] Error [0-9]+$/
             }
             return text == "======================================================================"
           }
           function retain_suffix(text, excess) {
             suffix = suffix text
             excess = length(suffix) - suffix_limit
             if (excess > 0) suffix = substr(suffix, excess + 1)
           }
           {
             if (!seen) {
               if (!matches_target($0)) next
               seen = 1
             } else if (!compile_mode && target_ends($0)) {
               exit
             }
             line = $0 "\n"
             if (compile_mode && critical == "" && $0 ~ /: error:/) {
               critical = substr(line, 1, critical_limit)
             }
             remaining = prefix_limit - written
             if (remaining > 0) {
               if (length(line) <= remaining) {
                 printf "%s", line
                 written += length(line)
               } else {
                 printf "%s", substr(line, 1, remaining)
                 written += remaining
                 retain_suffix(substr(line, remaining + 1))
               }
             } else {
               retain_suffix(line)
             }
             if (compile_mode && target_ends($0)) exit
           }
           END { printf "%s%s", critical, suffix }
         ' "$private_diagnostic_path" > "$private_diagnostic_path.tail" 2>/dev/null &&
         tail -c 192512 -- "$private_diagnostic_path" \
           >> "$private_diagnostic_path.tail" 2>/dev/null &&
         chmod 0600 "$private_diagnostic_path.tail" 2>/dev/null &&
         mv -f -- "$private_diagnostic_path.tail" \
           "$private_diagnostic_path" 2>/dev/null; then
        :
      else
        rm -f -- "$private_diagnostic_path" 2>/dev/null
        private_diagnostic_path=
        private_diagnostic_log=unavailable
      fi
      rm -f -- "$private_diagnostic_path.tail" 2>/dev/null
    fi
    if [[ -n $private_diagnostic_path ]] &&
       ! printf '\n--- swapz rootless attribution ---\nphase=%s\nsubtest=%s\ntest=%s\nunittest_kind=%s\nreason=%s\nexit_code=%s\nfirst_errno=%s\ncleanup_disposition=%s\nphase_wall_s=%s\nstage_wall_s=%s\nsource_line=%s\nnext_step=inspect_first_captured_FAIL_or_ERROR_locally\n' \
         "$rootless_phase" "$failed_subtest" "$failed_test" "$failed_unittest_kind" \
         "$failure_reason" "$original_exit_code" "$failed_errno" "$cleanup_disposition" \
         "$phase_wall_seconds" "$stage_wall_seconds" "$failed_at_line" \
         >> "$private_diagnostic_path"; then
      private_diagnostic_log=unavailable
    fi
  fi

  # Fixed safe fields let the private reporter retain the first unit failure
  # and attach the exact script/phase, original status and elapsed wall time.
  local failure_phase=$rootless_phase
  if [[ $failed_subtest != unavailable ]]; then
    failure_phase+=" subtest $failed_subtest"
  fi
  printf 'FAIL: rootless phase=%s subtest=%s test=%s exit=%s reason=%s phase_s=%s stage_s=%s line=%s log=%s\n' \
    "${rootless_phase##*/}" "$failed_subtest" "$failed_test" "$original_exit_code" \
    "$failure_reason" "$phase_wall_seconds" "$stage_wall_seconds" \
    "$failed_at_line" "$private_diagnostic_log" >&2
  printf 'Failed during: %s\n' "$failure_phase" >&2
  printf 'Reason: exit=%s reason=%s subtest=%s phase_wall_s=%s stage_wall_s=%s line=%s log=%s first_errno=%s cleanup=%s\n' \
    "$original_exit_code" "$failure_reason" "$failed_subtest" \
    "$phase_wall_seconds" "$stage_wall_seconds" "$failed_at_line" \
    "$private_diagnostic_log" "$failed_errno" "$cleanup_disposition" >&2
  printf '%s\n' \
    'NEXT: inspect the mode-0600 local log and first captured FAIL/ERROR; do not publish private data.' >&2
  exit "$original_exit_code"
}

# Reuse the bounded relay for detailed unittests, including live
# subprocess-ownership and sensitive admission failure diagnostics.
# A failed child owns the exit status even if stderr relay or cleanup fails.
finish_and_report_rootless_unittest() {
  local original_exit_code=$1
  local command_line=$2
  local cleanup_disposition=not_independently_verified
  finish_rootless_private_stderr_capture "$original_exit_code"
  case $rootless_capture_failure_reason in
    stderr_relay_failure) cleanup_disposition=relay_incomplete ;;
    stderr_relay_cleanup_failure) cleanup_disposition=relay_cleanup_failed ;;
  esac
  if (( original_exit_code == 0 )); then
    if [[ -n $rootless_capture_failure_reason ]]; then
      report_rootless_failure 1 "$command_line" "$rootless_capture_failure_reason" \
        unavailable unavailable unavailable unavailable "$cleanup_disposition"
    fi
    return 0
  fi
  if [[ -z $rootless_capture_failure_reason ]]; then
    classify_rootless_private_unittest_failure \
      "$rootless_private_diagnostic_path"
  else
    # A partial relay is not authoritative for a unittest classification.
    rootless_classified_reason=nonzero_exit
    rootless_classified_subtest=unavailable
    rootless_classified_test=unavailable
    rootless_classified_unittest_class=unavailable
    rootless_classified_kind=unavailable
    rootless_classified_errno=unavailable
  fi
  report_rootless_failure "$original_exit_code" "$command_line" \
    "$rootless_classified_reason" "$rootless_classified_subtest" \
    "$rootless_classified_test" "$rootless_classified_kind" \
    "$rootless_classified_errno" "$cleanup_disposition" \
    "$rootless_classified_unittest_class"
}

rootless_unexpected_error() {
  local original_exit_code=$1
  local failed_at_line=$2
  if (( BASH_SUBSHELL == 0 )); then
    report_rootless_failure "$original_exit_code" "$failed_at_line"
  fi
  return "$original_exit_code"
}

rootless_exit_fallback() {
  local original_exit_code=$1
  if (( original_exit_code != 0 && rootless_failure_reported == 0 && BASH_SUBSHELL == 0 )); then
    # Explicit 'exit' has no reliable ERR source line.
    report_rootless_failure "$original_exit_code" unavailable
  fi
}
trap 'rootless_unexpected_error "$?" "$LINENO"' ERR
trap 'rootless_exit_fallback "$?"' EXIT
trap 'report_rootless_failure 143 unavailable received_TERM' TERM
trap 'report_rootless_failure 130 unavailable received_INT' INT
export PYTHONPYCACHEPREFIX="$ROOT/build/python-cache"
mkdir -p build/python-cache
# The inherited GNU Make jobserver may run native evidence-producing targets
# concurrently. Keep each target's output together so structured records stay
# intact for the official reporter.
make_args=(make --output-sync=target)
if [[ -n ${SWAPZ_TEST_JOBS:-} ]]; then
  [[ $SWAPZ_TEST_JOBS =~ ^[1-9][0-9]*$ ]] && (( SWAPZ_TEST_JOBS <= 16 )) ||
    { printf '%s\n' 'BLOCKED: invalid automatic build job count' >&2; exit 2; }
  make_args+=("-j$SWAPZ_TEST_JOBS")
fi
rootless_phase='tests/Makefile native and metadata'
rootless_begin_phase
# Preserve stdout and stderr relay while privately retaining a failed compile.
begin_rootless_private_stderr_capture
rootless_make_command_line=$LINENO
if "${make_args[@]}" -C tests test 2>&"$rootless_capture_input_fd"; then
  rootless_make_exit_code=0
else
  rootless_make_exit_code=$?
fi
finish_rootless_private_stderr_capture "$rootless_make_exit_code"
rootless_make_cleanup_disposition=not_independently_verified
case $rootless_capture_failure_reason in
  stderr_relay_failure) rootless_make_cleanup_disposition=relay_incomplete ;;
  stderr_relay_cleanup_failure) rootless_make_cleanup_disposition=relay_cleanup_failed ;;
esac
if (( rootless_make_exit_code != 0 )); then
  if [[ -z $rootless_capture_failure_reason ]]; then
    classify_rootless_private_make_failure "$rootless_private_diagnostic_path"
  fi
  report_rootless_failure "$rootless_make_exit_code" "$rootless_make_command_line" \
    "$rootless_classified_reason" "$rootless_classified_subtest" \
    "$rootless_classified_test" "$rootless_classified_kind" \
    "$rootless_classified_errno" "$rootless_make_cleanup_disposition"
fi
if [[ -n $rootless_capture_failure_reason ]]; then
  report_rootless_failure 1 "$rootless_make_command_line" "$rootless_capture_failure_reason" \
    unavailable unavailable unavailable unavailable "$rootless_make_cleanup_disposition"
fi
rootless_native_make_elapsed_seconds=$((SECONDS - rootless_phase_started_seconds))
rootless_contracts_started_seconds=$SECONDS
rootless_phase='tests/runtime/native/source-contract-test.py'
rootless_begin_phase
python3 -B tests/runtime/native/source-contract-test.py -v
rootless_phase='tests/runtime/native/userspace/swapzctl-active-swap-provenance-test.py'
rootless_begin_phase
python3 -B tests/runtime/native/userspace/swapzctl-active-swap-provenance-test.py -v
rootless_phase='tests/runtime/native/tmp-cleanup-test.py'
rootless_begin_phase
python3 -B tests/runtime/native/tmp-cleanup-test.py -v
rootless_phase='tests/runtime/native/resource-admission-test.py'
rootless_begin_phase
python3 -B tests/runtime/native/resource-admission-test.py -v
rootless_phase='tests/runtime/native/resource-pressure-cleanup-ownership-test.py'
rootless_begin_phase
python3 -B tests/runtime/native/resource-pressure-cleanup-ownership-test.py -v
rootless_phase='tests/runtime/native/primary-lifecycle-audit-test.py'
rootless_begin_phase
# Preserve the first failure across multiple unittest classes. Any traceback
# and subtest payload remain confined to the mode-0600 private capture.
begin_rootless_private_stderr_capture
rootless_audit_command_line=$LINENO
if python3 -B tests/runtime/native/primary-lifecycle-audit-test.py -v \
    2>&"$rootless_capture_input_fd"; then
  rootless_audit_exit_code=0
else
  rootless_audit_exit_code=$?
fi
finish_and_report_rootless_unittest "$rootless_audit_exit_code" "$rootless_audit_command_line"
rootless_phase='tests/runtime/native/primary-lifecycle-nullblk-qualifier-test.py'
rootless_begin_phase
python3 -B tests/runtime/native/primary-lifecycle-nullblk-qualifier-test.py -v
rootless_phase='tests/runtime/native/primary-real-swap-test.py'
rootless_begin_phase
begin_rootless_private_stderr_capture
rootless_primary_command_line=$LINENO
if python3 -B tests/runtime/native/primary-real-swap-test.py -v \
    2>&"$rootless_capture_input_fd"; then
  rootless_primary_exit_code=0
else
  rootless_primary_exit_code=$?
fi
finish_and_report_rootless_unittest "$rootless_primary_exit_code" "$rootless_primary_command_line"
rootless_phase='tests/runtime/native/primary-real-swap-parent-ownership-test.py'
rootless_begin_phase
begin_rootless_private_stderr_capture
rootless_ownership_command_line=$LINENO
if python3 -B tests/runtime/native/primary-real-swap-parent-ownership-test.py -v \
    2>&"$rootless_capture_input_fd"; then
  rootless_ownership_exit_code=0
else
  rootless_ownership_exit_code=$?
fi
finish_and_report_rootless_unittest "$rootless_ownership_exit_code" "$rootless_ownership_command_line"
rootless_phase='tests/runtime/native/primary-real-swap-oracle-terminal-test.py'
rootless_begin_phase
python3 -B tests/runtime/native/primary-real-swap-oracle-terminal-test.py -v
rootless_phase='tests/runtime/benchmark/metadata-ram-evidence-test.py'
rootless_begin_phase
python3 -B tests/runtime/benchmark/metadata-ram-evidence-test.py -v
rootless_phase='tests/runtime/benchmark/io-replay-test.py'
rootless_begin_phase
python3 -B tests/runtime/benchmark/io-replay-test.py -v
rootless_phase='tests/runtime/native/make-interface-test.py'
rootless_begin_phase
python3 -B tests/runtime/native/make-interface-test.py -v
rootless_phase='tests/runtime/native/test-report-test.py'
rootless_begin_phase
python3 -B tests/runtime/native/test-report-test.py -v
rootless_phase='tests/runtime/native/production-readiness-test.py'
rootless_begin_phase
python3 -B tests/runtime/native/production-readiness-test.py -v
rootless_phase='tests/runtime/native/rootless-direct-evidence-test.py'
rootless_begin_phase
python3 -B tests/runtime/native/rootless-direct-evidence-test.py -v
rootless_phase='tests/runtime/native/rootless-attribution-test.py'
rootless_begin_phase
python3 -B tests/runtime/native/rootless-attribution-test.py -v
rootless_phase='tests/runtime/native/ci-failure-diagnostics-test.py'
rootless_begin_phase
python3 -B tests/runtime/native/ci-failure-diagnostics-test.py
rootless_phase='tests/runtime/native/package-dkms-test.py'
rootless_begin_phase
begin_rootless_private_stderr_capture
rootless_package_command_line=$LINENO
if python3 -B tests/runtime/native/package-dkms-test.py -v \
    2>&"$rootless_capture_input_fd"; then
  rootless_package_exit_code=0
else
  rootless_package_exit_code=$?
fi
finish_and_report_rootless_unittest "$rootless_package_exit_code" "$rootless_package_command_line"
rootless_phase='tests/runtime/native/systemd/swapz-primary-systemd-test.py'
rootless_begin_phase
python3 -B tests/runtime/native/systemd/swapz-primary-systemd-test.py -v
rootless_phase='tests/runtime/native/systemd/swapz-primary-generator-transaction-test.py'
rootless_begin_phase
begin_rootless_private_stderr_capture
rootless_generator_command_line=$LINENO
if python3 -B tests/runtime/native/systemd/swapz-primary-generator-transaction-test.py -v \
    2>&"$rootless_capture_input_fd"; then
  rootless_generator_exit_code=0
else
  rootless_generator_exit_code=$?
fi
finish_and_report_rootless_unittest "$rootless_generator_exit_code" "$rootless_generator_command_line"
rootless_phase='tests/runtime/native/physical-swap-probe-test.py'
rootless_begin_phase
python3 -B tests/runtime/native/physical-swap-probe-test.py -v
rootless_phase='tests/runtime/native/live-swap-supervisor-test.py'
rootless_begin_phase
python3 -B tests/runtime/native/live-swap-supervisor-test.py -v
# Compile the noninstalled lifecycle rehearsal branch on every rootless/CI
# architecture. Private paths are deliberately nonexistent; this is syntax and
# warning qualification only and cannot mutate a device.
rootless_phase='C syntax: owned nullblk lifecycle seam'
rootless_begin_phase
cc -std=c11 -O2 -g -Wall -Wextra -Werror -fsyntax-only \
  -DSWAPZ_PRIMARY_OWNED_NULLBLK_TEST=1 \
  '-DSWAPZ_PRIMARY_TEST_CONFIG_BASE="/var/tmp/swapz-primary-owned-nullblk/config"' \
  '-DSWAPZ_PRIMARY_TEST_RECOVERY_BASE="/var/tmp/swapz-primary-owned-nullblk/recovery"' \
  '-DSWAPZ_PRIMARY_TEST_MUTATION_LOCK_DIRECTORY="/var/tmp/swapz-primary-owned-nullblk/mutation-lock"' \
  '-DSWAPZ_PRIMARY_TEST_QUALIFICATION_REPORT="/var/tmp/swapz-primary-owned-nullblk/recovery/qualification.json"' \
  src/userspace/swapz-primary.c
rootless_phase='C syntax: physical lifecycle seam'
rootless_begin_phase
cc -std=c11 -O2 -g -Wall -Wextra -Werror -fsyntax-only \
  -DSWAPZ_PRIMARY_PHYSICAL_QUALIFICATION_TEST=1 \
  '-DSWAPZ_PRIMARY_PHYSICAL_QUALIFIED_CONTROL="/usr/local/sbin/swapzctl"' \
  src/userspace/swapz-primary.c
rootless_phase='C syntax: unqualified physical seam rejection'
rootless_begin_phase
if cc -std=c11 -O2 -g -Wall -Wextra -Werror -fsyntax-only \
     -DSWAPZ_PRIMARY_PHYSICAL_QUALIFICATION_TEST=1 \
     src/userspace/swapz-primary.c >/dev/null 2>&1; then
  printf '%s\n' 'FAIL: physical qualification seam compiled without qualified control path' >&2
  exit 1
fi
rootless_phase='C syntax: mutually exclusive lifecycle seams'
rootless_begin_phase
if cc -std=c11 -O2 -g -Wall -Wextra -Werror -fsyntax-only \
     -DSWAPZ_PRIMARY_PHYSICAL_QUALIFICATION_TEST=1 \
     -DSWAPZ_PRIMARY_OWNED_NULLBLK_TEST=1 \
     '-DSWAPZ_PRIMARY_PHYSICAL_QUALIFIED_CONTROL="/usr/local/sbin/swapzctl"' \
     '-DSWAPZ_PRIMARY_TEST_CONFIG_BASE="/var/tmp/swapz-primary-owned-nullblk/config"' \
     '-DSWAPZ_PRIMARY_TEST_RECOVERY_BASE="/var/tmp/swapz-primary-owned-nullblk/recovery"' \
     '-DSWAPZ_PRIMARY_TEST_MUTATION_LOCK_DIRECTORY="/var/tmp/swapz-primary-owned-nullblk/mutation-lock"' \
     '-DSWAPZ_PRIMARY_TEST_QUALIFICATION_REPORT="/var/tmp/swapz-primary-owned-nullblk/recovery/qualification.json"' \
     src/userspace/swapz-primary.c >/dev/null 2>&1; then
  printf '%s\n' 'FAIL: physical and null_blk lifecycle seams compiled together' >&2
  exit 1
fi
rootless_phase='tests/runtime/benchmark/resource-pressure.py --help'
rootless_begin_phase
python3 -B tests/runtime/benchmark/resource-pressure.py --help >/dev/null
rootless_phase='loaded-preflight executable contract'
rootless_begin_phase
[[ -x tests/tools/loaded-preflight.sh ]] || {
  printf '%s\n' 'FAIL: loaded-preflight.sh must remain executable' >&2
  exit 1
}
rootless_phase='source-contract single test runner'
rootless_begin_phase
[[ "$(grep -Fc 'if __name__ == "__main__":' tests/runtime/native/source-contract-test.py)" == 1 ]] || {
  printf '%s\n' 'FAIL: source-contract-test.py must have exactly one test runner' >&2
  exit 1
}
for script in tests/tools/test-rootless.sh tests/tools/test-loaded.sh \
  tests/tools/qualify-resource-pressure.sh \
  tests/tools/qualify-logical-open-balance.sh packaging/package-dkms.sh \
  packaging/swapz-primary-boot-verify packaging/sign-module.sh \
  tests/tools/deploy-nullblk.sh tests/tools/qualify-primary-lifecycle-nullblk.sh \
  tests/tools/loaded-preflight.sh tests/tools/swap-inventory.sh \
  tests/tools/quiet-lower-io.sh \
  tests/tools/benchmark-owned-pair.sh tests/tools/benchmark-striped-owned.sh \
  tests/tools/nullblk-identity.sh \
  tests/runtime/native/nullblk-identity-test.sh \
  tests/runtime/native/quiet-lower-io-test.sh \
  tests/runtime/native/swap-inventory-test.sh; do
  rootless_phase="bash syntax ${script##*/}"
  rootless_begin_phase
  bash -n "$script"
done
rootless_phase='tests/runtime/native/nullblk-identity-test.sh'
rootless_begin_phase
bash tests/runtime/native/nullblk-identity-test.sh
rootless_phase='tests/runtime/native/quiet-lower-io-test.sh'
rootless_begin_phase
bash tests/runtime/native/quiet-lower-io-test.sh
rootless_phase='tests/runtime/native/swap-inventory-test.sh'
rootless_begin_phase
bash tests/runtime/native/swap-inventory-test.sh
rootless_phase='x86_64 native SIMD disassembly contracts'
rootless_begin_phase
if [[ "$(uname -m)" == "x86_64" ]]; then
  objdump -d build/tests/native/predictor-sse2.o > build/tests/native/predictor-sse2.disasm
  objdump -d build/tests/native/predictor-avx2.o > build/tests/native/predictor-avx2.disasm
  objdump -d build/tests/native/predictor-avx512.o > build/tests/native/predictor-avx512.disasm
  grep -Eq 'psubq|paddq' build/tests/native/predictor-sse2.disasm
  grep -Eq 'vpsubq|vpaddq' build/tests/native/predictor-avx2.disasm
  grep -Eq 'vpsubq|vpaddq' build/tests/native/predictor-avx512.disasm
  grep -Eq 'valignq' build/tests/native/predictor-avx512.disasm
  rm -f build/tests/native/predictor-sse2.disasm build/tests/native/predictor-avx2.disasm \
    build/tests/native/predictor-avx512.disasm
fi
rootless_phase='static source/interface contract assertions'
rootless_begin_phase
grep -Fq 'dmsetup create "$DMNAME" --uuid "$UUID"' tests/tools/deploy-nullblk.sh
grep -Fq 'memory_backed' tests/tools/deploy-nullblk.sh
grep -Fq 'modprobe lz4_compress || fail "kernel LZ4 compressor unavailable"' tests/tools/deploy-nullblk.sh
grep -Fq 'SWAPS_ID_BEFORE' tests/tools/deploy-nullblk.sh
grep -Fq 'qualify-primary-lifecycle-nullblk.sh' tests/tools/test-loaded.sh
grep -Fq 'SWAPZ_PRIMARY_OWNED_NULLBLK_TEST=1' tests/tools/qualify-primary-lifecycle-nullblk.sh
grep -Fq '"$CONTROL" primary prepare' tests/tools/qualify-primary-lifecycle-nullblk.sh
grep -Fq '"$CONTROL" primary start' tests/tools/qualify-primary-lifecycle-nullblk.sh
grep -Fq '"$CONTROL" primary stop' tests/tools/qualify-primary-lifecycle-nullblk.sh
grep -Fq '"$CONTROL" primary recover' tests/tools/qualify-primary-lifecycle-nullblk.sh
grep -Fq 'swapz_swap_inventory_identity /proc/swaps' tests/tools/qualify-primary-lifecycle-nullblk.sh
grep -Fq 'QUARANTINED_PRIMARY_NULLBLK_LIFECYCLE=' tests/tools/qualify-primary-lifecycle-nullblk.sh
! grep -Eq 'rmmod[[:space:]]|dmsetup remove.*--force' tests/tools/qualify-primary-lifecycle-nullblk.sh
grep -Fq 'SWAPS_ID' tests/tools/benchmark-owned-pair.sh
grep -Fq 'cat /sys/module/dm_swapz/refcnt' tests/tools/loaded-preflight.sh
grep -Fq '[[ $refcount == 0 ]]' tests/tools/loaded-preflight.sh
grep -Fq 'expected_proof=creation_authority observed_proof=refcount_only' tests/tools/loaded-preflight.sh
grep -Fq 'retained_state_action=retain_module' tests/tools/loaded-preflight.sh
! grep -Eq '^[[:space:]]*rmmod([[:space:]]|$)' tests/tools/loaded-preflight.sh
! grep -Fq 'rmmod -f' tests/tools/loaded-preflight.sh
grep -Fq 'QUARANTINED: host swap identity changed' tests/tools/deploy-nullblk.sh
grep -Fq 'PASS_ZERO_WRITE_LOWER_IO=' tests/tools/deploy-nullblk.sh
grep -Fq 'zero_writes == 9' tests/tools/deploy-nullblk.sh
grep -Fq 'lower_write_bytes == target_write_bytes' tests/tools/deploy-nullblk.sh
grep -Fq 'lower_read_bytes != target_read_bytes' tests/tools/deploy-nullblk.sh
grep -Fq 'swapz_capture_quiescent_io' tests/tools/deploy-nullblk.sh
grep -Fq 'target/backing not quiescent before oracle: $SWAPZ_QUIET_LAST_FAILURE' tests/tools/deploy-nullblk.sh
grep -Fq 'target/backing not quiescent after oracle: $SWAPZ_QUIET_LAST_FAILURE' tests/tools/deploy-nullblk.sh
grep -Fq 'UNATTRIBUTED_LOWER_READ=' tests/tools/deploy-nullblk.sh
grep -Fq 'PASS_ORACLE_LOWER_READ=' tests/tools/deploy-nullblk.sh
grep -Fq 'close_total == window_delta' tests/tools/deploy-nullblk.sh
grep -Fq 'PASS_WINDOW_CLOSE_REASONS=' tests/tools/deploy-nullblk.sh
grep -Fq 'age_total == window_delta' tests/tools/deploy-nullblk.sh
grep -Fq 'PASS_WINDOW_OPEN_AGE=' tests/tools/deploy-nullblk.sh
grep -Fq 'raw_writes == 64' tests/tools/deploy-nullblk.sh
grep -Fq 'PASS_LOADED_ORACLE_PROFILE=' tests/tools/deploy-nullblk.sh
grep -Fq 'timer_arms > lifecycle_windows' tests/tools/deploy-nullblk.sh
grep -Fq 'dmsetup suspend "$DMNAME"' tests/tools/deploy-nullblk.sh
grep -Fq 'PASS_LOADED_SUSPEND_DRAIN=' tests/tools/deploy-nullblk.sh
grep -Fq 'PASS_RETAINED_SYNTHETIC_WRITE_FAULT=' tests/tools/deploy-nullblk.sh
grep -Fq 'PASS_RETAINED_SYNTHETIC_FLUSH_FAULT=' tests/tools/deploy-nullblk.sh
grep -Fq -- '--write-series' tests/tools/device-roundtrip.c
grep -Fq -- '--verify-series' tests/tools/device-roundtrip.c
# Record the final suite before emitting a bounded, source-controlled
# per-phase breakdown. Never emit these as qualification success markers.
rootless_timing_finished_seconds=$SECONDS
rootless_timing_names+=("$rootless_phase")
rootless_timing_seconds+=("$((rootless_timing_finished_seconds - rootless_phase_started_seconds))")
for phase_index in "${!rootless_timing_names[@]}"; do
  printf 'ROOTLESS_PHASE_TIMING index=%d elapsed_s=%d label=%s\n' \
    "$phase_index" "${rootless_timing_seconds[phase_index]}" \
    "${rootless_timing_names[phase_index]}"
done
# Observational timing only: no new subprocesses or test-order changes.
printf 'ROOTLESS_TIMING native_make_s=%d remaining_contracts_s=%d\n' \
  "$rootless_native_make_elapsed_seconds" "$((SECONDS - rootless_contracts_started_seconds))"
printf '%s\n' 'PASS: rootless C tests, source contracts, Make policy and owned-device preflights'
