# Offline rootless recall-denial telemetry

This source-only tool classifies **already-denied synthetic recall sessions** into
diagnostic categories. It cannot establish positive admission, worker reaping,
kernel drain, backing cleanup, or production behavior. Codex owns the broker
implementation; this tool does not modify the broker, its protocol, or the
security predicates.

Source: `tests/runtime/recall-denial-telemetry.py`.
Tests: `tests/runtime/recall-denial-telemetry-test.py`.
The test suite uses only in-memory JSONL, regular files, and owned short-lived
Python processes exercising the analyzer CLI. No device or worker commands
are executed.

## Exact input format

Supply one LF-terminated JSON object per **failed rootless session**. Every
row must have exactly these ten keys:

| Key | Constraint |
| --- | --- |
| `schema` | Literal `swapz-rootless-recall-denial-v1` |
| `source_revision` | 40 lowercase hex characters, identical for all rows |
| `session_id` | Unique nonempty 1–64 character identifier using alphanumerics, dots, underscores, hyphens |
| `role` | One of `writer, a, b, a2, b2` or null where no role is applicable |
| `phase` | One of `LAUNCH, READY, WAIT, READBACK, WRITER_READY, CHANNEL, PIDFD, FINALIZE, STOP` |
| `status` | Explicit known failure status, e.g. `launch_failure` or `lifecycle_failure` |
| `error` | Nonempty printable bounded diagnostic text of at most 256 characters |
| `service_returncode` | Null, or an integer in [-255, 255] |
| `preserve_backing` | Literal true |
| `cleanup_allowed` | Literal false |

Launch, READY, WAIT, READBACK, and synthetic writer readiness phases require
a fixed role. WRITER_READY is restricted to writer; READBACK excludes writer.

Use a separate session ID for every independently fresh failed trial.
Do not create a row from a passing/ambiguous session. A missing trusted
denial or contradictory cleanup statement is a fatal input rejection.
For convenience, this parser accepts the *transcribed* statuses emitted by
the synthetic service model, but it does not query the service or infer a
failure from a missing WAIT worker field. The earlier pinned-readback race
is explicitly categorized from READBACK evidence rather than guessed
from its downstream missing receipt.

Example synthetic record (not authenticated evidence):

```json
{"schema":"swapz-rootless-recall-denial-v1","source_revision":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","session_id":"fixture-1","role":"a","phase":"READBACK","status":"lifecycle_failure","error":"pinned readback rejected: byte mismatch","service_returncode":null,"preserve_backing":true,"cleanup_allowed":false}
```

Invocation:

```bash
python3 -B tests/runtime/recall-denial-telemetry.py \
  --observations /path/to/synthetic-denials.jsonl > /path/to/denial-summary.json
python3 -B tests/runtime/recall-denial-telemetry-test.py -v
```

## Fail-closed rules and output

Input is a retained singly-linked regular-file descriptor opened with
`O_NOFOLLOW` and bounded to 1 MiB and 2,048 sessions. The
validator requires exact original LF framing, unique JSON keys, unique
session IDs, a shared source revision, typed negative verdicts, printable
bounded diagnostic text, and consistent phase/role constraints. Source
byte SHA-256 is computed without modifying or rounding input.

Report includes source revision, original-byte SHA-256, denied-session
counts, sorted diagnostic categories, and sorted session identifiers.
Diagnostics are deliberately grouped by typed phase. Text can select only
the narrow readback-integrity subtype. An unknown READBACK error stays
`readback_other_denial`; it never becomes success.
Successful exit status zero is not accepted as proof of cleanup.

The following claims are *always false* in successful output:
`source_authenticated`, `kernel_drain_proved`,
`physical_selection_authorized`,
`backing_release_authorized`,
`cleanup_authorized`, and
`production_qualified`.
The V2.2 strategy and batch-size winner remains `UNDETERMINED`.

This is an **offline classification aid**. User-created JSONL can contain
fabricated phases, errors, sessions and SHA; source-byte hashing does not
prove origin. Its success must not be promoted into trusted evidence for
real DM/NBD/swap lifecycle, kernel drain, or physical benchmark selection.
Failure prints a bounded denial prefix to stderr, produces no success
report, and preserves any backing without cleanup operations.
