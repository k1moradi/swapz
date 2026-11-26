# Agent2 — R094 native per-BIO evidence

Status: SOURCE_PUBLISHED / QUEUED / NO_GO_LIVE. Exact source
[9f0a2a7ec0d0cbd7f58abb74b83e423924b19076](https://github.com/k1moradi/swapz/commit/9f0a2a7ec0d0cbd7f58abb74b83e423924b19076), sole parent
e0f42294a1969407742779037ddc9eb3174be76e, remote head read back after expected-head nonforce main FF.
Engineering freeze efd77858cd20650213559ceb9cb4d0362db32ea5, task
e4de57c4e96669add5072290870ca199d17d8a04, original Linux
c339f4010dea8b0d754f84ace70cd1b089878ef8. No same-round peer inputs.

- [Parser](https://github.com/k1moradi/swapz/blob/9f0a2a7ec0d0cbd7f58abb74b83e423924b19076/tests/tools/native-bio-evidence.py) blob 554d1145729e7b5ff02ceb4357b0fff837c4db95.
- [Fabricated fixture tests](https://github.com/k1moradi/swapz/blob/9f0a2a7ec0d0cbd7f58abb74b83e423924b19076/tests/runtime/native/native-bio-evidence-test.py) blob cbcb1413fbd51409988bca67a3451f9af069425f.
- [Observation contract / exact frozen source map](https://github.com/k1moradi/swapz/blob/9f0a2a7ec0d0cbd7f58abb74b83e423924b19076/docs/handoff/zswapz/round094/agent2-native-observation-contract.md) blob 2225144877341c48cf5694c0fba7390b1a2cf87d.
- [Dedicated workflow](https://github.com/k1moradi/swapz/blob/9f0a2a7ec0d0cbd7f58abb74b83e423924b19076/.github/workflows/phase-a-native-bio-evidence-noauth.yml) blob 70c42237fdf1596b306ab5a9942ce2462c167010.
- [Standards](https://github.com/k1moradi/swapz/blob/9f0a2a7ec0d0cbd7f58abb74b83e423924b19076/docs/testing_standards.md) blob 18b2101a762092abb0febd94ffec25e534040b27; actual
  parent blob 48c8fd42e507d04be37b46302bf0292fc9abf7de; 1,840,110 +
  1,448 = 1,841,558 bytes. Recreated original blob hash, verified
  complete engineering-freeze and actual-parent prefix and exact
  appended blob remote readback. No historical deletion.

Single-target/session/route, bounded read-only JSON with externally
supplied expected scope digest, nonpointer per-run opaque identities,
sequence/loss/overflow/truncation strictness, source/slot/store and
accepted descriptor correlation, typed 0x5a LZ4/LZO1X v1 dictionary-free
M3568, full-page RAW only for limited ordinary fallback/overwrite
fixture profile. Exact reserve/claim/refuse/verified tail cancel,
lower length/digest/status/flush, map publication, exactly-once ACK,
independent 4096-byte read oracle, pin release, GC read plus relocation
with generation AND GC epoch increments, discard and cleanup debt.
Failed issued writes quarantine; no fallback after claim. Output never
echoes record identities and all admission/authentication gates are
hard false. Source map describes **missing** producer instrumentation
at frozen MM/DM/authority/storage/decoder/broker boundaries. No actual
native capture, no tracing activation, no kernel source modification.
Conservative profile: initially empty selected range, serial ordered
release, one 4096B extent, no M4095, ordinary compressed/zero fallback,
multi-page discard or arbitrary concurrent histories. Unsupported
histories block rather than approximate. Caller-provided scope digest
and opaque-shaped IDs cannot authenticate source or producer.

## Qualification

[Automatic focused push run 45763872508](https://github.com/k1moradi/swapz/actions/runs/45763872508), [job 139719991043](https://github.com/k1moradi/swapz/actions/runs/45763872508/job/139719991043),
observed queued. No manual dispatch,
rerun or repeat of accepted R093 corpus. Other preexisting automatic
path-triggered workflows may run on the mandatory standards co-change;
no additional manual workflows started. Local git ls-remote failed DNS
("Could not resolve host: github.com"); connector used for publication,
no local Python execution or git diff-check claim. New fixture source
contains four unittest methods including complete fabricated LZ4/LZO1X
stream, semantic negatives, observed failure histories and bounded CLI
negatives; executed counts and artifact IDs are not claimed until
exact-job logs are reviewed. First CI failure not yet established.
R093 aggregate evidence remains accepted as aggregate only.

AUTH=0; Phase A BLOCKED; compressed handoff, forced RAW bypass and import
OFF. No branches, PRs, force pushes, VM, module load, privileged action,
physical mutation, device access or ordinary helper edits. Future
producer and source/binary/capture authentication separately required.
