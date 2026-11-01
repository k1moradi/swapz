# Handoff migration plan

Status: **in progress — rows 1-12, 14 and 17 complete**.

This plan applies the `docs/coding_standards.md` **Change discipline** rule to
the current `docs/handoff/` directory. It is intentionally outside
`docs/handoff/` so it remains available while the temporary handoff bundles
are removed row by row.

## Scope and terminal state

There are **69 migration candidates** in `docs/handoff/`. Two files are
explicitly out of scope and must remain:

- `docs/handoff/host-history.json` — machine-read host-history registry.
- `docs/handoff/lane-gap-diagnostics.md` — ID178 is still open.

When rows 1-21 are complete, those two files must be the only remaining files
under `docs/handoff/`. Row 22 is the final validation/closeout.

Canonical destinations are limited to `docs/context.md`, `docs/VISION.md`,
`docs/coding_standards.md`, `docs/testing_standards.md`, and the applicable
row or nearby explanatory text in `docs/ROADMAP.md`. Do not create a new
archive document to preserve handoff prose: immutable Git history is the
archive.

## Execution contract for every row

1. **All migration edits must be made directly on the existing `main` branch.**
   Do not create or use a new branch (including a temporary migration, review,
   or work branch), and do not create a pull request as a substitute for a
   direct `main` update. This includes migration-document updates, code,
   comments, tests, scripts, link fixes and deletions. Fetch the current remote
   head immediately before each write, preserve concurrent work, and update
   `main` only with a lease-protected fast-forward. Never force-push, rewrite
   history, or overwrite concurrent work. If the lease fails, re-read the new
   remote HEAD and reconcile before trying another fast-forward.
2. Read every source file named by the row plus its canonical destination.
   Treat companion `.json`, `.json.gz`, and `.patch` files as evidence,
   not as automatic canonical content. **Inspect all relevant executable
   consumers and active references across the entire tracked repository**, not
   only the named handoff bundle or `docs/`: production code, inline comments,
   headers, tests, Python/shell scripts, Makefiles, CI workflows, YAML/JSON,
   README and other documentation. Read the referenced context before editing
   or deleting; a machine-consumed path must be repointed safely and its reader
   checked rather than silently broken.
3. Migrate only **durable** material that is not already canonical:
   production/ownership invariants, accepted or rejected decisions and their
   reusable reason, exact qualification boundaries that still govern future
   interpretation, and reusable testing/measurement rules.
4. Do **not** migrate raw observations already summarized in the ROADMAP,
   per-run logs, exhaustive sample matrices, patch bytes, temporary scripts,
   local `build/` paths, source/hash manifests, superseded work orders, or
   unconfirmed historical-candidate lists unless a canonical rule explicitly
   depends on them.
5. Repoint a surviving reference to a canonical document or replace it with
   plain `ROADMAP ID NNN` text. **Update every active reference in code,
   comments, tests, scripts, Makefiles, CI and documentation as needed**;
   changing only Markdown links is not sufficient. Preserve executable
   behavior and ownership guarantees when a reader's input path changes.
   Never redirect one deleted handoff link to another temporary handoff file.
   Remove references whose only purpose was to expose a superseded raw packet.
6. Before editing and again after editing, **search the entire tracked tree**
   for every source file's basename, path, stem, and applicable relative
   Markdown/URL forms, using `git grep -n -F` (and inspect detected indirect
   directory/path construction in scripts). Include hidden tracked files such
   as `.github/`; do not restrict searches to `docs/` or exclude source
   comments. Classify each match as a live code/path dependency, an active
   link/instruction, or an inert historical mention. Repoint/remove all live
   dependencies and active references; review their callers/tests when changed.
   A remaining machine reader is a **blocker** unless safely migrated.
7. **Delete every file assigned to the row**, including the corresponding
   handoff document and any associated packets/patches, **in the same commit**
   as its canonical migration and reference updates. A completed row must
   show both the deleted paths and all reference fixes in `git diff --name-status`
   and must show no assigned path in `git ls-files`. Do not merely deprecate,
   rename, move to another archive directory, or leave a migrated handoff
   document behind. The only exceptions for the entire project are the two
   explicitly excluded files in Scope; do not delete either.
8. Keep each row as one reviewable commit and update this plan's Status/commit
   cell in that commit. A row is not complete if its files are gone but an
   active reference remains, a migrated handoff file still exists, or durable
   content was copied without deleting its temporary source.
9. Row-level validation is `git diff --check`, assigned-path absence, and the
   repository-wide reference audit; run targeted rootless checks when a row
   changes code or scripts. The exact requested `tests/tools/test-rootless.sh`
   run is the final gate in row 22 after all migrations are assembled.

**Historical-inventory exception:** This plan intentionally names the original
handoff files in its migration table and may retain their names as an inert
audit ledger after deletion. Those `docs/handoff_migration_plan.md` entries
and immutable Git history are **not** active references or dangling links.
Every other tracked occurrence must be examined and justified; an active
link, reader, instruction, or code comment pointing to a deleted file is never
exempt merely because the name also appears here.

## Migration rows

| Row | Round and source files | Canonical migration and link action | Evidence to drop after migration | Validation | Status / commit |
| ---: | --- | --- | --- | --- | --- |
| 1 | **Legacy x86 continuation + ID148/ID149 direct lower WRITE**: `direct-bio-x86-pilot.json`; `direct-lower-write-review.md`; `direct-lower-write-state.json`; `direct-lower-write.patch`; `goal-prompt.md`; `x86-continuation-result.md`; `x86-handoff.md`; `x86-history-candidates.json` | Reconcile against ROADMAP IDs **148-149**, `context.md`, and the Change-discipline/host-history rules. Preserve only if missing: ID148 callback lifetime rule (completion + owner notification remain inside the existing drain/lifetime gate; final unlock is last callback target access), the interrupted busy-host qualification boundary, ID149's rejected direct-BIO disposition/reopen condition, and the rule that unconfirmed historical reports never enter an exact-host series. Remove the ROADMAP introductory links to `goal-prompt.md`, `x86-handoff.md`, `x86-continuation-result.md`, and the ID149 packet/result links. Do **not** copy `x86-history-candidates.json` into `host-history.json`: its entries are explicitly unconfirmed and the durable selection rule is already canonical. | Portable draft patch/state, fixed pilot packet, superseded receiving-host prompts, duplicated naming/test instructions, backend microbench numbers already superseded by qualified reports, and unconfirmed candidate inventory. | No basename from this row may remain in `git grep`; ROADMAP IDs 148/149 must remain self-contained; `host-history.json` unchanged unless a schema-supported owner-confirmed fact is discovered (none is expected). | **Complete — canonical rules verified, ROADMAP references cleaned, and all eight assigned artifacts deleted in this commit.** |
| 2 | **dm-linear calibration + serial-owner/budget diagnostics**: `dm-linear-x86-calibration.json`; `dm-linear-x86-calibration.md`; `serial-budget-x86-diagnostic.json`; `serial-owner-x86-profile.json`; `serial-owner-x86-profile.md` | Reconcile with ROADMAP ID **151**, the ROADMAP dm-linear explanatory paragraph, and testing-standard profiling caveats. Preserve only if missing: dm-linear is a calibration reference, not an exact unavoidable DM budget; scheduler/phase clocks overlap and must not be summed into removable CPU; mapped-snapshot preparation is not direct mapped-BIO LZ4 input. Remove the ID151 handoff link. | Per-run calibration matrices, raw phase timings, stack populations, source/hash packets, and local-artifact paths once those three reusable conclusions are canonical. | ROADMAP/testing standards contain the three rules above without handoff links; all five files and their references are gone. | **Complete — canonical calibration/profiling rules verified, ID151 link removed, and all five assigned artifacts deleted in this commit.** |
| 3 | **ID152 LZ4 state reuse**: `lz4-state-x86-pilot.json.gz`; `lz4-state-x86-result.json`; `lz4-state-x86-result.md`; `lz4-state-x86.patch` | Reconcile with ROADMAP ID **152** and the nearby current-work narrative. Preserve only if missing: the tested mechanism was the exported continuation API with zero-length dictionary reset and changed hash behavior, **not** a custom small-table 4KiB encoder; the fixed pilot missed its +3% benefit screen; production returned to stateless LZ4; do not repeat the same variant without a new mechanism. Remove both ROADMAP links to the result. | Full 36-block packet, result matrices, experimental patch and source/hash manifests. | ID152/narrative state the mechanism scope and rejection without a temporary link; all four files deleted. | **Complete — durable ID152 mechanism/rejection scope merged into ROADMAP, both active result links removed, and all four assigned artifacts deleted in this commit.** |
| 4 | **ID153 CPU-targeted completion**: `cpu-completion-x86-lifecycle.json.gz`; `cpu-completion-x86-pilot.json.gz`; `cpu-completion-x86-pilot.patch`; `cpu-completion-x86-plan.json`; `cpu-completion-x86-result.json`; `cpu-completion-x86-result.md`; `cpu-completion-x86-review.md`; `cpu-completion-x86-validation.json.gz`; `cpu-completion-x86.patch` | Reconcile with ROADMAP ID **153**. Preserve only if missing: candidate removed after the fixed benefit screen; remote-completion work, if ever revisited, must re-prove callback-cell lifetime/drain join and invalid/offline/same-CPU fallback rather than treating placement as free; no total-CPU reduction was established. Remove the ROADMAP result link. | Draft/review, lifecycle and invalid-destination validation packets, pilot plan/results, both archived patches, exact size/source manifests. | ID153 is self-contained and no CPU-completion handoff reference survives. | **Complete — ID153 made self-contained with revisit/lifetime/fallback/CPU limits, the ROADMAP handoff link removed, and all nine assigned artifacts deleted in this commit.** |
| 5 | **ID154 direct admission contention diagnostic**: `admission-x86-diagnostic.json.gz`; `admission-x86-diagnostic.md`; `admission-x86-diagnostic.patch` | Reconcile with ROADMAP ID **154** and testing-standard CPU/lock attribution language. Preserve only if missing: failed-trylock fallback wall is not full lock wait/hold, CPU, or an upper bound on savings; perturbation evidence did not justify a lockless rewrite. Remove the ROADMAP packet link. | Diagnostic counter packet, probe patch, excluded/noisy effect tables. | ID154 contains the interpretation limit; no row-154 handoff links/files remain. | **Complete — ID154 interpretation limits merged, ROADMAP handoff link removed, and all three assigned artifacts deleted in this commit.** |
| 6 | **ID155 systematic admission hold sampling**: `admission-hold-x86-result.json`; `admission-hold-x86.json.gz`; `admission-hold-x86.md`; `admission-hold-x86.patch` | Reconcile with ROADMAP ID **155**. Preserve only if missing: one-in-64 partial IRQ-disabled hold samples are not exact CPU/total hold/removable budget; any future out-of-lock notification must preserve acceptance/FIFO/producer protection and an admission-close/drain lifetime join. Remove the ROADMAP result link. | Sampling packet, patch, clock-overhead tables and superseded candidate work order. | ID155 remains self-contained; all four files and links removed. | **Complete — ID155 sampling/lifetime limits made self-contained, the ROADMAP handoff link removed, and all four assigned artifacts deleted in this commit.** |
| 7 | **ID156 lifetime-pinned owner notification outside admission lock**: `admission-wake-lifetime-review.json.gz`; `admission-wake-quiet-x86-pilot.json.gz`; `admission-wake-quiet-x86-plan.json`; `admission-wake-quiet-x86-result.json`; `admission-wake-quiet-x86-result.md`; `admission-wake-quiet-x86.md`; `admission-wake-x86-pilot.json.gz`; `admission-wake-x86-plan.json`; `admission-wake-x86-result.json`; `admission-wake-x86-result.md`; `admission-wake-x86-review.md`; `admission-wake-x86-validation.json.gz`; `admission-wake-x86.patch` | Reconcile with ROADMAP ID **156** and the current-work narrative. Keep the two studies distinct in canonical text: first pilot unusable (71/72 excluded), second prospectively restarted after the competing workload ended and still missed the declared retention screen. Preserve the candidate-lifetime rule only as a future-revisit requirement, not production behavior. Remove the ROADMAP ID156/result/narrative links. | Both pilot packets/plans/results, lifetime-review packet, validation packet, candidate review and patch. Do not preserve the rejected implementation merely because its ownership proof was good. | ROADMAP explains both noisy and quiet dispositions without links; every admission-wake file above is deleted. | **Complete — ID156 now keeps the noisy and quiet studies distinct, retains the lifetime proof only as a future-revisit requirement, removes the ROADMAP handoff links, and deletes all 13 assigned artifacts in this commit.** |
| 8 | **ID157 pack/submit ancestry diagnostic**: `pack-owner-x86-profile.json`; `pack-owner-x86-profile.json.gz`; `pack-owner-x86-profile.md` | Reconcile with ROADMAP ID **157**. Preserve only if missing: observed null_blk allocation/initialization/locking ancestry is backend work, not a pure swapz pack budget; broad pack/stage labels and cycle samples are not exact CPU or proof of RAM-bandwidth saturation; this evidence alone does not reopen direct BIO. Remove the ROADMAP link. | Resolved stack populations, packet, hashes and local profiling paths. | ID157 contains those interpretation limits; all three files and references removed. | **Complete — ID157 interpretation limits made self-contained, the ROADMAP handoff link removed, and all three assigned artifacts deleted in this commit.** |
| 9 | **ID158 both-arm backing materialization sensitivity**: `backing-materialization-x86-pilot.json.gz`; `backing-materialization-x86-plan.json`; `backing-materialization-x86-result.json`; `backing-materialization-x86-result.md`; `backing-materialization-x86.md`; `backing-materialization-x86.patch` | Reconcile with ROADMAP ID **158**. Preserve only if missing: treatment applies to **both** raw and swapz backing; cross-condition raw changes are outcomes, not exclusion criteria; n/adjusted-sign requirements were not met; materialization is a model sensitivity study, not product promotion, physical-NVMe fidelity, or proof of RAM-bandwidth saturation. Remove the ROADMAP link. | Prospective plan, all round data, helper patch, failed technical-attempt details and hashes. | ID158 is self-contained; all six files/links removed. | **Complete — ID158 made self-contained with both-arm treatment, raw-outcome/exclusion, qualification-boundary and model-sensitivity limits; the ROADMAP handoff link was removed and all six assigned artifacts were deleted in this commit.** |
| 10 | **ID162 early-hand width**: `hand16-production-stack-result.md` | Reconcile with ROADMAP ID **162** and the linked testing-standard paragraph. Preserve inline in canonical docs: production hand remains 8; hand16 reduced fragmentation/requests but did not establish the required useful-service gain and raised accepted-work idle; threshold64 and submitter-off remain separate untested questions. Replace/remove both ROADMAP and testing-standard links to the result. | Full pilot provenance/exclusion prose and local artifact list already summarized by ID162. | No link to the result remains; ROADMAP/testing standards still state the hand8 decision and untested boundaries. | **Complete — ID162/testing standards now preserve the hand8 decision and untested threshold64/submitter-off boundaries inline, both active handoff links are removed, and the assigned result is deleted in this commit.** |
| 11 | **ID163 four-record async detach**: `four-record-detach-oldpc-result.md` | Reconcile with ROADMAP ID **163**. Preserve the fixed decision already summarized there: activity/packing improved but useful-service benefit was unproved and idle increased; production strict >4 predicate restored; no equivalence/causal-regression claim. Remove the ROADMAP link. | Exact source hashes, block-by-block plan, local artifact list. | ID163 remains self-contained and the file/link is gone. | **Complete — ID163 already held the fixed decision; the strict >4 production predicate is now explicit, the ROADMAP handoff link is removed, and the assigned result artifact is deleted in this commit.** |
| 12 | **ID164 bounded early acknowledgement proposal**: `early-ack-staging-proposal.md` | This row requires a real canonical merge. In `context.md`, add the durable Linux-v7 swap failure fact if absent: block-backed swap WRITE completion failure re-dirties/retains the folio, so early success removes that recovery path; also document that swapz's volatile authority cannot survive reboot and therefore is not a hibernation resume device. In ROADMAP ID **164**, replace the proposal link with concise approval prerequisites from the handoff: no early ACK for FUA/PREFLUSH; acknowledged staged generations must be bounded and independently owned after the BIO; overwrite/DISCARD/late lower completion cannot resurrect stale generations; READ must never expose stale lower data; suspend/drain/table removal must not discard acknowledged unwritten generations; lower failure after ACK needs an explicit owner-approved contract. `coding_standards.md` must continue to state the current invariant: success ACK follows confirmed lower success unless the owner explicitly changes that contract. | The long architecture sketch, kernel-source link catalog, speculative upper-bound arithmetic, and implementation staging proposal once the kernel semantics and approval gates are canonical. | Context and ID164 contain the durable semantics; no proposal link remains; no production behavior is accidentally described as already approved. | **Complete — Linux swap-failure/hibernation semantics and ID164 approval gates merged canonically, proposal links removed, and the assigned handoff file deleted in this commit.** |
| 13 | **ID165 blocked-prefix dispatch**: `submitter-blocked-prefix-oldpc-result.md` | Reconcile with ROADMAP ID **165** and its testing-standard link. Preserve inline: candidate split useful aggregation, missed fast-QD8 service and violated request guards; a submitter deferral is not automatically removable idle; reopen only for a distinct measured mechanism. Remove ROADMAP/testing links. | Candidate C hashes, probe details, fixed block logs and artifact path list. | ROADMAP/testing standard retain the rejected decision without the handoff. | Pending |
| 14 | **ID166 visible-queue wake suppression**: `submitter-queued-wake-oldpc-result.md` | Reconcile with ROADMAP ID **166** and testing standards. Preserve inline: locked worker ownership recheck is required for lost-wake safety; the visible-head suppression variant did not establish service/deferral gain; it did not test empty/private FIFO suppression. Remove links. | Exact candidate/control hashes, per-block evidence and local artifacts. | Canonical text keeps the lost-wake boundary and rejection; file/link gone. | **Complete — ID166 lost-wake ownership boundary and rejection retained canonically; ROADMAP/testing links removed and the assigned handoff result deleted in this commit.** |
| 15 | **ID167 private-FIFO wake suppression**: `submitter-private-wake-oldpc-result.md` | Reconcile with ROADMAP ID **167** and testing standards. Preserve inline: second suppression variant also missed service/deferral targets; do not add another wake predicate without attributed unnecessary-wake evidence plus complete progress proof. Remove links. | Candidate details, fixed observations, hashes/artifact manifests. | Canonical docs carry the no-repeat rule; file/link gone. | Pending |
| 16 | **IDs168-170 preparation placement / producer-during-I/O confirmation / longer mixed trace**: `preparation-placement-oldpc-result.md`; `submitter-during-io-confirmation.json` | Reconcile with ROADMAP IDs **168-170** and the testing-standard ID169 reference. Preserve inline: global submitter-off missed QD4 target; conditional active-lower-WRITE guard has confirmed QD8 signal and QD8/QD32 guards, while the fixed shorter mixed cohort lacked minimum coverage; owner later promoted the frozen guard with x86/ARM watchpoints; `MIXED_OPS=65536` is a separate development cohort and cannot be pooled with the completed confirmation. Remove result/machine-summary links. | Pilot/confirmation exclusions, machine summary, local quiet-screen diagnostic and artifact manifests after their conclusions are canonical. | IDs168-170 and testing standards fully describe the decision/protocol separation; both files deleted. | Pending |
| 17 | **ID171 early submitter snapshot release**: `submitter-snapshot-oldpc-result.md`; `submitter-snapshot-oldpc.json` | Reconcile with ROADMAP ID **171** and testing standards. Preserve inline: bounded two-reference ownership tests passed but the candidate missed the 5% service floor and increased lower bytes beyond the 1% guard; control restored; the zero asynchronous-LZ4 EWMA observation motivated ID172 but does not retain ID171. Remove links. | Machine summary, administrative-resume detail, candidate/probe/mutant manifests and per-block estimates. | ID171/testing standards retain decision + ID172 motivation; both files/links gone. | **Complete — durable ID171 rejection/ownership and ID172-motivation facts merged inline, active links repointed/removed, and both assigned artifacts deleted in this commit.** |
| 18 | **ID172 completed asynchronous LZ4 cost coverage**: `prepared-cost-coverage-result.md` | Reconcile with ROADMAP ID **172** and the existing work-conserving-preparation standard. Preserve inline if missing: both asynchronous owners publish per-page LZ4 elapsed only before terminal READY; only ordered owner updates estimator from READY_COMPRESSED/READY_RAW; zero/unknown/unready/error samples do not train it; owner `make test` passed and this is an estimator-coverage correctness repair, not a throughput claim. Remove the ROADMAP link. | Qualification narrative, host timing/history counts and local artifact path already represented by the qualified report and ROADMAP. | ID172/standards remain sufficient to implement/interpret the estimator; file/link removed. | Pending |
| 19 | **ID173 acquire READY after lost RAW-selection race + superseded next-agent handoff**: `preparation-ready-acquire-result.md`; `next-agent-preparation-and-pressure.md` | Reconcile with ROADMAP ID **173** and testing-standard memory-order section. Preserve inline: failed conditional RMW is unordered; after losing PREPARING→RAW selection, reacquire stable READY while the consumer reference prevents reuse; ordinary READY/RAW-win paths do not gain extra reads. Preserve the qualification boundary: owner run is BLOCKED because the raw ID36 control timed out under `memory.high`; do not retry, relax pressure, or relabel it PASS; a test-owned stop used only after terminal failure is cleanup evidence, not unattended acceptance. Remove the ROADMAP result link and any cross-link to the next-agent file. | Detailed pressure stack, partial performance watchpoints, operating prompt, local artifact inventory and duplicated main/test rules. | ID173/testing standards contain memory-order + BLOCKED interpretation; both files gone. | Pending |
| 20 | **Old-PC QD4 reissue diagnostic**: `qd4-reissue-oldpc-result.md` | Reconcile with the ROADMAP narrative immediately following the old-PC QD4 analysis. Preserve inline: final capture lost events/missed independent counts/failed screening and cannot guide C; earlier captures used wrong/silent tracepoints; `sync4_reissue_gap_ns` spans ACK, writer reissue, admission/preparation and retention and is not wholly removable idle. Remove the ROADMAP diagnostic link. | Invalid/corrected capture chronology, exact event counts, tool versions and local manifest details after the invalidation rule is canonical. | ROADMAP keeps the invalid-capture lesson and timer scope; file/link removed. | Pending |
| 21 | **Repository-wide handoff link/deletion audit** | Sweep **all tracked text** after rows 1-20, including C/headers and comments, tests, shell/Python scripts, Makefiles, `.github/` workflows, JSON/YAML, README and other docs, not just `docs/`. Search `git grep -n -F` for all 69 deleted paths/basenames plus `handoff/`, review path construction and check links to already-deleted files. Active references must point only to canonical docs or the two excluded files; the Change-discipline directory description and this plan's inert historical inventory are allowed. Resolve every other occurrence deliberately. Check `git ls-files docs/handoff/` and `find docs/handoff -maxdepth 1 -type f`: each must list exactly the two exclusions. Never delete or rewrite either excluded file. | Any overlooked live reader, stale code comment, script path, dead link, or orphaned handoff file. | Zero **active** dangling references in the entire tracked repository; 69 source files deleted and exactly two excluded files remain; `git diff --check` passes. | Pending |
| 22 | **Final validation and closeout** | Update this plan's overall status and per-row ledger, then run exactly `tests/tools/test-rootless.sh` from the repository root. The migration is complete only on exit 0. Record the final migration commit range and a concise ledger of **merged** canonical facts/rules versus **dropped** evidence/work-order material. Recheck the **entire tracked repository** for active references and confirm all 69 migrations were deleted, with only the two excluded files remaining. Re-fetch `origin/main` immediately before the final write and fast-forward **directly on `main`** with a lease; never create another branch or force-push. | Nothing else. If rootless fails, keep the migration unclosed and fix the failure in the responsible row rather than weakening the test. | `tests/tools/test-rootless.sh` exit 0; no active dangling references; clean tracked tree; remote `main` equals the final local commit; only the two excluded handoff files remain. | Pending |

## Expected merged-versus-dropped ledger

The final report should not enumerate every deleted raw observation. Report by
durable category:

**Expected canonical merges**

- ID148/149 callback-lifetime/direct-BIO disposition only if a detail is missing
  from their ROADMAP rows.
- Calibration/profiling interpretation rules: dm-linear is a reference, phase
  clocks overlap, lock/stack wall is not exact removable CPU.
- Rejected-candidate reopen boundaries for IDs152-158 and 162-173 where the
  existing ROADMAP row is not already self-contained.
- ID164 kernel failure/hibernation semantics and explicit approval prerequisites.
- ID173 memory-order and BLOCKED-pressure interpretation if not already complete.

**Expected drops**

- Fixed pilot/study packets and readable duplicate result JSON.
- Compressed validation/lifecycle packets.
- Unapplied experiment patches and patch manifests.
- Superseded prospective plans, work orders and receiving-agent prompts.
- Local `build/` artifact inventories and source/hash manifests.
- Unconfirmed x86 historical-candidate list.
- Per-run/exclusion/sample tables already summarized canonically.

The executor must record an actual merge/drop decision for each row; “already
canonical, no text added” counts as **merged by reference verification**, not as
a reason to preserve the handoff file.
