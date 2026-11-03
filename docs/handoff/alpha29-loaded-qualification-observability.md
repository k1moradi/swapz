# Historical Alpha.29 loaded qualification observability and preflight repair

This is a preserved engineering transcript from the historical ROADMAP at
commit `e0be25169867b403cd4053f2c03a56b2fca2f02f`, not a current-host qualification result, public test
command, or authorization to mutate a block device. The active fail-closed
preflight and rootless test contracts are normative in
[testing_standards.md](../testing_standards.md); the sole qualification
interface and current evidence policy are documented in
[README.md](../README.md) and [AGENT_CONTEXT.md](../AGENT_CONTEXT.md).

### Alpha.29 loaded qualification observability repair

After alpha.29 portable qualification, an owner `make test` was observed with
no terminal output after stage 4. This exposed a harness defect independent of
the benchmark verdict: stage 5 was fully captured by `subprocess.run()` and
had no visible progress until all loaded work returned. The harness now streams
the existing phase markers live and wraps each privileged top-level helper in a
root-owned outer watchdog. This does not qualify ID83 and does not change
production kernel behavior; it makes any subsequent loaded stall attributable
to an exact smoke/benchmark phase and bounded in time. The first owner rerun
then exposed a second harness-only regression: the watchdog executed private
shell helpers directly, adding an executable-bit requirement that the previous
`bash helper.sh` privilege path did not have. The bounded wrapper now invokes
those helpers through `bash` inside `timeout`, preserving the original helper
contract while keeping the outer deadline. Live stage-5 output is also filtered
to concise phase transitions and failure/block diagnostics; full raw evidence is
still captured for the report instead of flooding the terminal with status and
JSON records. A later rerun after an async kernel stall exposed a third recovery
issue: stale-open cleanup signaled holders before proving that the mapper's lower
device was private harness RAM. Preflight now completes the exact mapper/UUID and
memory-backed null_blk proof first, then targets only the canonical owned DM node.
A holder that remains open after bounded TERM/KILL is reported as requiring a
host reboot; force removal remains forbidden. The next owner rerun exposed a
repository-mode regression in that repair: `loaded-preflight.sh` had lost its
executable bit, while rootless qualification only syntax-checked the file. The
helper mode is restored and rootless qualification now locks it; status-two
preflight runtime exits also surface a concise live failure marker instead of
being reduced to a generic missing-diagnostic verdict. The following owner rerun
then exposed that an earlier malformed repair had re-entered history as a
duplicated tail in `source-contract-test.py`. The file is rebuilt from the
known-good baseline with only the intended stale-recovery assertions, and
rootless qualification now rejects multiple terminal test runners. The next
owner run reached preflight but returned shell status 2 before any normal safety
diagnostic. The stale-recovery path no longer depends on Bash extended-regex
capture state for mapper/UUID/lower/open validation: it uses exact shell
patterns, a guarded dependency parser, and separately checked canonical-device
stats. This preserves the same positive-ownership boundary while converting
malformed or unexpected state into explicit `BLOCKED:` results instead of an
opaque shell-runtime status. The numeric internal-error trap remains as a
last-resort diagnostic. A subsequent owner run exposed one stale native interface assertion that still required the removed regex literals; that contract is aligned with the exact-token ownership checks and now explicitly rejects reintroduction of `BASH_REMATCH`. The following loaded owner rerun still returned shell status 2 before a safety verdict, so the remaining runtime `=~` expressions and C-style arithmetic commands are removed from privileged preflight as well. Canonical decimal validation, exact shell patterns and fixed bounded retry iteration now cover the path end-to-end without weakening positive ownership checks. The following native rerun exposed three stale harness assertions that still required the removed arithmetic spellings (source contract, Make interface contract, and rootless literal grep); all three are aligned to the non-arithmetic preflight forms in one change. The following loaded qualification run exposed that the multi-line `case` pattern in `loaded-preflight.sh` omitted trailing backslashes on continuation lines, triggering a Bash syntax error (unexpected newline) and exit status 2 before execution. The continuation lines are escaped with `\`, and `test-rootless.sh` is updated to invoke `bash -n` individually across every shell harness script so future syntax regressions fail in Stage 2 rather than during privileged loaded execution.
