# Agent 6 — swapzctl architecture, integration and security review

**Inspected source:** `main` at `94012dffdeaede38ee7a73cbb93c35fbbef3fff1` (2026-11-14). This is a
source-level review and an integration decision, **not** an assertion that a
Lubuntu host, mapper, Linux swap space or physical partition was inspected.
For actual acceptance, re-fetch the current `main` SHA and its exact-SHA
CI jobs after every change. Historical CI remains source-bound.

**Decision summary:** Public read-only discovery/status/inspection/health
may remain observational. `--bytes` and `list --no-headers` are shipped;
`stats --watch` is **STAGED, NOT PUBLIC**; automatic `swapzctl` development
mapper `stop`/`recover` is **BLOCKED**. Existing guarded
`swapzctl primary` commands are a separate authority and must not be
extended to a retained development trial.

## 1. Authority and ownership architecture

1. **Linux owns paging.** Linux kernel swap/reclaim selects pages and
   swapon/swapoff policy. The `swapz` Device Mapper target performs block I/O
   transformation and owns bounded, **volatile** RAM-only mapping metadata.
   After module unload there is no persistent compressed-map recovery source.
2. **Physical image is pre-existing ordinary SWAPSPACE2.** Never format,
   repartition, rewrite the raw 4096-byte first page/UUID, or infer that
   a mapper snapshot authorizes physical operations. Only a newly created,
   independently qualified inactive *virtual mapper* can be formatted
   by an already owner-gated workflow.
3. **Public observation is not custody.** The `swapzctl.c` collector
   uses bounded `DM_LIST_DEVICES` / `DM_TABLE_STATUS`, two matched
   INFO observations and a final inventory comparison. Parsed DM UUID,
   major:minor, event generation, geometry and status are useful observation
   identities; even successive stable snapshots are **not** an atomic
   exclusion lock against another process replacing a mapper.
4. **Linux swap inventory is advisory.** `/proc/swaps` pathnames can be
   renamed, overmounted or observed from a different namespace. `active`,
   `not_observed` and `unknown` cannot serve as a verified drain or
   exclusive-ownership predicate. Lifetime compression ratios and
   unmodified `failed/error` fields are not liveness or wear proof.
5. **Two distinct lifecycle owners.** `src/userspace/swapz-primary.c`
   is the guarded production-primary manager. The retained Lubuntu
   `swapz-demo-physical-*` trial belongs exclusively to the private
   same-boot journal-based recovery in
   `tests/tools/physical-swap-probe.py`, not to `swapzctl primary stop`
   or a matcher on the mapper prefix. Never add a generic `dmsetup remove`,
   `swapoff`, module-unload or `mkswap` fallback in `swapzctl`.

## 2. Read-only watch integration contract — Agent 1 + Agent 4

The isolated `src/userspace/swapzctl-watch.c/.h` sampler has bounded
monotonic intervals and rootless regression coverage. The public CLI currently
does not link or invoke it. The kernel INFO formatter in
`src/kernel/dm-target.c::swapz_status` exposes the relevant cumulative
fields, but the validated public collector currently retains only a narrower
write/ratio subset. **Do not link a sampler fed by unverified defaults.**

| Sampler counter | Kernel INFO key |
| --- | --- |
| logical READ bytes | `logical_read` |
| logical WRITE bytes | `logical_write` |
| lower READ bytes / requests | `physical_read` / `physical_read_reqs` |
| lower WRITE bytes / requests | `physical_write` / `physical_write_reqs` |
| GC READ bytes / requests | `gc_read` / `gc_read_reqs` |
| GC WRITE bytes / requests | `gc_write` / `gc_write_reqs` |
| foreground representation counts | `compressed`, `raw`, `zero_elided` |

**Mandatory implementation gates:**

- Parse each required counter as a **single canonical bounded unsigned
  decimal**, refusing missing, duplicate, noncanonical and overflowed
  tokens; enforce page-to-byte and GC-versus-lower subset invariants.
  The existing full validated DM snapshot, not a separate opportunistic
  string parse, must own the measurements.
- A selected name must uniquely resolve to **exactly one** swapz target.
  Bind every sample to the same full mapper name, DM major:minor/UUID,
  target index/start/length/table and compatible event-generation identity.
  Failure, removal, recreation, geometry changes and ambiguous targets
  terminate sampling without publishing the next interval.
- Require two validated stable status observations **including the new
  counters** and final inventory checks. Retry boundedly when a concurrent
  commit is observed; never silently coerce inconsistent counters.
- Calculate deltas from monotonic time actually elapsed, reject zero or
  backward time, counter reset/wrap and unsafe divisions; keep sampling
  bounded by the sampler's maximum sample count and interval limits.
  A quiet interval is not proof of stalled I/O or of a drained device.
- Restrict `--watch` to `stats NAME`, preserve current read-only command
  behavior, define exact human and JSON framing before implementation,
  and test SIGINT, SIGTERM, EPIPE, failing output, shutdown/recreation and
  no-module paths without any mutating ioctl.

**Integration owner:** Agent 1 owns the C collector/CLI merge; Agent 4
owns sampler equivalence/identity assertions; Agent 2 adds end-to-end
hostile-input, formatting and signal tests. None should widen the primary
manager or physical admission authority to make a watch test pass.

## 3. Retained trial recovery security gates — Agent 3

The audit in `swapzctl-trial-ownership-audit.md` identifies these
independent P0 hazards:

| Hazard | Required proof before adding public delegation |
| --- | --- |
| Journal/marker substitution | Use pinned root-owned directory and file descriptors with no-follow and `fstat` owner/type/mode/link/inode checks; reject namespace/mount changes, duplicate records and concurrent replacement. Revalidate state and result bindings under the original partition lock. |
| `COMPLETE` state with retained active marker | Add a dedicated idempotent **read-only post-COMPLETE reconciliation** followed only by authenticated conditional marker release; never re-run swapoff or mapper removal from an already `COMPLETE` journal. A failed sync or uncertain marker must remain recovery-required. |
| Mapper recreation between snapshots and `dmsetup remove` | Bind exact DM name, UUID, dev_t, table geometry, lower block identity, kernel module and current namespace to the same owner journal; reject replacement/foreign holder and independently recheck immediately before each privileged mutation. An ordinary DM event number alone is not an unforgeable incarnation token. |
| Executable/module provenance drift | Independently authenticate the running helper and **currently loaded** module against the saved owner record and admitted source, not merely saved result-vs-state equality. |
| Linux swap drain uncertainty | Failed or ambiguous `swapoff`, ENOMEM, unconfirmed live pages, foreign active aliases or insufficient headroom preserve the mapper, all volatile mappings and owner marker. A `Used=0` sample or missing procfs row is insufficient. |
| Process interruption/reboot | Same-boot root-owned `/run` state is authoritative for current trial. A lost journal, boot-ID change, missing marker or ambiguous run blocks takeover, even if a mapper name looks familiar. Do not attempt to rebuild volatile mapping state from disk. |

**Decision:** Do not add `swapzctl stop`/`recover` or a systemd
auto-cleanup of the retained development mapper in this stage. The existing
private `recover-pending` command remains the **only** conditionally owned
reconciliation path, subject to its existing guard failures. A future
delegation must be a separately reviewed, strictly one-way request to
that original owner and must never accept arbitrary mapper paths.

## 4. Rootless integration and evidence contract — Agent 6 + Agent 2

- `tests/suites/Makefile test-userspace` must run the 20-case
  `swapzctl-trial-ownership-test.py` model after the existing C and primary
  late-race regressions, preserving the original failure code and fixed script
  identity. `make-interface-test.py` guards registration and Make-escaped
  shell variables (`$$?` and `$$script_exit_status`).
- `tests/tools/test-rootless.sh` and
  `tests/tools/product_goals.py` must recognize the exact fixed script
  only with the authenticated `Makefile native and metadata` /
  `test-userspace` failure envelope; malformed identity, phase, subtest,
  reason or status is `UNKNOWN_FAILURE`. Raw assertion values stay private.
- The source- and script-bound fixtures are **mocked transition/parser
  evidence**. Passing CI does not qualify privileged `swapoff`, Linux
  anonymous-page-out/in correctness, live mapper removal, physical-media
  header preservation or cold-boot recovery. Each needs a separate
  owner-authorized test on the actual exact host/source/target.
- Repository policy requires applicable normative standards in the **same
  commit** as source/test changes. Publish only non-force expected-head
  fast-forwards on `main`; never overwrite other agents' work, create
  branches/PRs, or arm systemd while tests run.

## 5. Release decision matrix

| Deliverable | Current architectural decision | Promotion gate |
| --- | --- | --- |
| List/status/inspect/stats/health/diagnose, JSON | Read-only permitted, with unverified ownership and unknown liveness | Exact-head rootless CI and documented limits |
| `--bytes` and `list --no-headers` | Implemented human views | Dedicated option regressions and exact-head CI |
| `stats NAME --watch SECONDS` | **STAGED / NOT PUBLIC** | All counters/identity parsed, end-to-end signal/JSON/rootless qualification |
| Private retained-trial `recover-pending` | Existing **conditional** helper only | Own exact journal/host gates; refuse uncertainty |
| New public development-trial stop/recover | **BLOCKED** | All P0 security gates above, independent review and source-bound live/physical qualification |
| Primary deployment/systemd activation | **BLOCKED absent qualification** | Separate primary manager admission, release evidence and boot acceptance |

**Never reinterpret a passing rootless build or a healthy DM INFO bit as
permission to unload a module holding live volatile swap mappings.**
