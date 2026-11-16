# Round 019 — Agent 2 pinned real TAP ownership repair

- Assignment: https://github.com/k1moradi/swapz/issues/136#issuecomment-6920207499
- Pinned Linux SHA: c339f4010dea8b0d754f84ace70cd1b089878ef8
- First authentic hosted failure: https://github.com/k1moradi/swapz/actions/runs/43876402555 artifact #14230122902. Enabled modified Kbuild/object and KUnit process exit=0; effective config gate exit=0; `first_failure_phase=capture_real_tap, first_failure_exit=1`. No raw captured TAP; five case statuses UNKNOWN, disabled profile NOT_RUN. Root cause: `run_checked` truncates the same shared log for `verify_uml_config` after the UML run.
- Fixed ordering: after successful pinned UML `--raw_output`, before another shared-log writer, require regular bounded nonempty source; exclusively create fresh per-profile owned capture with `set -C` and `umask 077`; require regular and bounded destination, capture immutable SHA-256, `chmod 0400`; then allow effective-config verification. Recheck exact content hash and regular bounded ownership immediately before the untouched strict five-case real TAP gate and final paired SHA check.
- Preserve 4/3 real object digests, exact pinned source Git blobs, separate y/n configs and kernel image SHA, mixed-case and CGROUPS-off conditional BLK_CGROUP semantics, absolute no-fabrication of TAP, first failed command and per-profile/setup exit.
- Test limits: synthetic rootless Bash capture fixtures and workflow contract mutation tests cannot demonstrate actual executed KUnit; exact-source hosted run and first failure, if any, must be separately qualified.
- Safety: no loaded kernel, physical swap, DM or real MM/BIO source use authorized; Phase A BLOCKED; Phase B RAW bypass and compressed handoff DISABLED; swapz RAW remains original 4096 uncompressed bytes.

## Exact-SHA hosted first follow-up and correction

- First integrated source run: https://github.com/k1moradi/swapz/actions/runs/43897211201, job 133403912605, 2026-11-16. `rootless` rejected after 33 executed Python methods (32 PASS, 1 failure) at `test_round019_workflow_capture_negative_mutations`; mutation deleting `[[ "$(wc -c < "$log")" -le 8388608 ]]` was not detected by the source-contract checker. The real newly added Bash capture, stale/symlink, hash-drift and initial TAP parser tests had passed; this is an exact source-contract **test** failure before modified-Linux execution, not a genuine KUnit TAP case failure.
- Follow-up correction: require the exact source log ≤8MiB check once and the captured file ≤8MiB check twice (immediately after capture and before TAP verification), and exercise removal of either bound. This closes the observed test gap without weakening the production Bash guard or five-case verifier.
