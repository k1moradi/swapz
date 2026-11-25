# Round089 Agent7 — isolated original LZ4 noDict decoder qualification

Status: **FAIL_OR_UNVERIFIED_TERMINAL**. Frozen baseline db9252db73721a768be912965ad4402e332039e8; task 0c893ee7a3ffc158d747c11c96b67fcf0b3efa15, [ROUND_OPEN lease](https://github.com/k1moradi/swapz/issues/207#issuecomment-7144215635). Source [4ef323e0e451dee64c6019ead1044c66fbe15c76](https://github.com/k1moradi/swapz/commit/4ef323e0e451dee64c6019ead1044c66fbe15c76), sole parent 0c893ee7a3ffc158d747c11c96b67fcf0b3efa15; main-only fresh expected-head nonforce fast-forward verified. Three owned paths only (verifier, existing host workflow, append-only standards 21 lines), no candidate C/H/fixture change. No peer output dependency. Exact [CI run/job](https://github.com/k1moradi/swapz/actions/runs/45576879949/job/139076892305), status completed, conclusion success.

## Source-derived correction and test scope

Original Linux pin c339f4010dea8b0d754f84ace70cd1b089878ef8; original decompressor pristine blob 3a2cd9acada4a09ef70a344090d48167c46088a1, computed exact postimage 8ca9e57ea0d03918e85e4aabcf472fe906b6bc7f. Verified original whole blob with independently computed Git hash before transformation. Original line 89 unconditionally evaluates dictStart + dictSize. In noDict, LZ4_decompress_safe and partial (459–474) pass NULL,0; small-prefix wrapper (505) also passes NULL,0. dictEnd use sites 349/360 only under usingExtDict branch at 336; noDict selects dictStart without arithmetic. withPrefix64k and external/double dictionary expressions unchanged (including empty external dictionary and prefix null cases, unqualified). Empty output/input returns remain unchanged at 110–117; nonnull source and destination assumed as in original, no general short-size pointer-arithmetic repair claimed. Existing actual fixture retains short decoded output, malformed stream, output immutability and M3568/M4095 checks; same 4098 corpus streams incl 4095-byte input.

Compressor original blob 2a397bb2c661d9c2e4a7a67d5f50f06bfd42f1f2, historical first failed postimage a1d860d6085109bc01ed6a593cf369ccbd6edc67, second 63eb4be2e23caf770649af18f6a7b2b82d79a5e7 preserved. Nine negative guards across both staging transforms and exact reversible diff; private staged copies with pinned header, final pristine verification. Prior R088 [failed job](https://github.com/k1moradi/swapz/actions/runs/45482877472/job/138760389279) artifact14963910496 actual clang UBSan lz4_decompress.c:89:55 null+0, exit1; final Clang baseline not run then. New three controls: original pristine compressor with same corpus, first-stage compressor with exact actual typed fixture and pristine decoder (not interleaved corpus), separate prior-stage compressor plus pristine decoder interleaved corpus reproducing second-file failure. Actual unexpected control failure recorded as first_error before generic RuntimeError; real sanitizer child regression. Strict flags unchanged, four GCC original/staged compressor/decoder combinations read back byte-identical streams; Clang staged pair compares against actual GCC pristine reference, never disables sanitizer. No system LZ4/LZO libraries.

## Actual execution snapshot

- Set up job: completed / success
- Run actions/checkout@v4: completed / success
- Exact main source, actual push parent, policy and candidate postimages: completed / success
- Run actions/checkout@v4: completed / success
- Pristine original source and all whole blobs and mutation anchors before compilers: completed / success
- Actual historical controls and staged noDict LZ4 compressor and decompressor plus pinned LZO1X: completed / success
- Retain exact host result and bounded first error: completed / success
- Post Run actions/checkout@v4: completed / success
- Post Run actions/checkout@v4: completed / success
- Complete job: completed / success

Full actual compiler counts and first current diagnostic not yet available from terminal logs; no GCC/Clang baseline or kill PASS claimed for this source.
Artifact [15003753677](https://github.com/k1moradi/swapz/actions/runs/45576879949/artifacts/15003753677), 5428 bytes, digest sha256:b9ec3cf8fc5c081d8e2c2ebc2320691954fdab1c829b0c41a930c2dcfa208375; archive not independently extracted.

Local git ls-remote failed DNS (Could not resolve host github.com), full pinned-source local tests NOT_RUN. Exact automatic source census at inspection: 10 runs, all in progress including mandatory project-goals and existing product qualification, no new manual dispatch or cancellation; other lanes may fail inherited defects. No periodic monitoring, duplicate test dispatch, VM qualification or physical operation. AUTH0 Phase A BLOCKED, direct compressed handoff/forced RAW/import OFF. No upstream/production adoption. Any further genuine sanitizer diagnostic is a failure, not a reason for blind retry.
