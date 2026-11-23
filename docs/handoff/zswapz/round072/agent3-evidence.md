# Round072 Agent3 — original swapcache/STORED source reachability (AUTH0)

**Authority:** Round072 [assignment](agent3-original-stored-provenance-boundary.md), [issue #189](https://github.com/k1moradi/swapz/issues/189#issuecomment-7092930425), task SHA 3c1919f1b2c2ea428045a1afb5c278151cf06ccc; engineering baseline 4083449f12c3392d5ea534ee4e536865b4caf3ee. The initial evidence is committed alongside source/test code. Git commits cannot embed their own SHA; the exact source commit and parent will be added by the required subsequent evidence-only revision.

## Genuine original Linux source anchors

Pristine torvalds/linux@c339f4010dea8b0d754f84ace70cd1b089878ef8, verified Git blobs:

| Path | Git blob | Original source boundary |
| --- | --- | --- |
| mm/zswap.c | ae19e301fced7e357a4c7587dfdd6abb890b9163 | zswap_store_page() sets pool index before XArray store, charges and completes initialization before LRU publication; the genuine zswap_store() expects locked swapcache folio; natural writeback acquires device before allocating true swapcache folio, rechecks XArray before dereference, decompresses, frees entry, writes uncompressed folio |
| mm/swapfile.c | 254ce86fa923e6b5f1fefda88c39315c4cc00642 | get_swap_device() verifies nonzero slot, registered type, live users reference and offset bounds; absent slots return NULL or ERR_PTR(-EIO), callers must balance successful refs |
| mm/swap.h | d5bf21f517dceae58eb94fb0ce5f4e1fdc679409 | folio_matches_swap_entry() requires actual swapcache ownership under a locked folio; genuine valid slot and object lifetime cannot arise from scalar witnesses |

**First real missing prerequisite: BLOCKED_NO_SWAP_DEVICE.** A legitimate selected swp_entry_t and live registered original swap-device ref are prerequisites to __swap_cache_alloc_folio(), the original locked swapcache folio and a genuine zswap_store_page()-published STORED XArray entry. Rootless unactivated UML has no swap device. A same-value test-created XArray, synthetic epoch or manually locked ordinary folio is NOT source authentication. Original normal writeback decompresses to a conventional full uncompressed BIO; it does not expose original compressed bytes.

## New independent owned qualification

New files: tests/runtime/native/fixtures/round072-original-swapcache-provenance.cfrag, tests/tools/round072-stage-original-swapcache-provenance.py, tests/tools/round072-original-swapcache-provenance-verify.py, .github/workflows/phase-a-round072-original-swapcache-provenance-noauth.yml, these two evidence files, and a literal-prefix-preserving testing standards append. No production C, original upstream source or another agent's fixture is changed.

The new original UML KUnit calls **real get_swap_device()** on a nonzero unregistered slot, releasing any unexpectedly live ref, and requires refusal. A second native case locks an original folio_alloc() folio and proves it is **not swapcache backed** via real folio_matches_swap_entry(). Third case refuses even all-true untrusted scalar provenance with -EACCES, and rejects missing true device, swapped-out STORED entry and DM source ownership. The already-green Round071 4/4 KUnit is NOT rerun. Test-only native staging pins all three original Git blobs, exact original writeback order, inherited Round058/069/071 postimages and nine changed-source/manifest/double-stage negative controls, then appends only to ephemeral original mm/zswap.c.

**Local executed:** GCC 14.2.0 PASS; Clang 17.0.0 PASS; 16 changed-C guard scenarios and 14/14 compiled/executed source semantic mutants per compiler with -Wall -Wextra -Wconversion -Wshadow -Werror and ASan+UBSan, zero sanitizer findings. Both Python files compile; workflow YAML parses. **Original UML 3-case JSON/KTAP and nine original staging negatives NOT_RUN locally** without a pristine pinned Linux tree. Exact source-specific CI must supply those results; no native PASS is presumed.

## Production status

SOURCE_MAPPED_AUTHENTICATED=0, PHASE_A=BLOCKED, DIRECT_COMPRESSED_HANDOFF=DISABLED, FORCED_RAW_BYPASS=DISABLED, import ACTIVE0. No swap activation, loaded/privileged/physical device, real memory pressure, actual lower durable WRITE+FUA or upper ACK. Linux MM/zswap alone manages compressed RAM and natural eviction; swapz only disk compression/packing/GC, never a second shrinker/recompressor. Original LZO1X/raw LZ4 opaque volatile codec is distinct from conventional RAW_4096, meaning complete original **uncompressed 4096**. On-disk map/first SWAPSPACE2 block/UUID and partition table remain protected.
## Actual terminal Round072 CI failure — preserved for Round074 requalification

The exact tested source commit `471b406d81b08e097d3bbddc8518d06bab687d8d` (parent `adc38477c80706908df94097467c75e0a0727753`) produced [GitHub run 45127526042](https://github.com/k1moradi/swapz/actions/runs/45127526042). Host job [137535206988](https://github.com/k1moradi/swapz/actions/runs/45127526042/job/137535206988) **FAILURE**, first real diagnostic `docs/testing_standards.md:19120: new blank line at EOF.` from `git diff --check HEAD^ HEAD`, exit 2, **before** new GCC/Clang source CI tests. Native job [137551007262](https://github.com/k1moradi/swapz/actions/runs/45127526042/job/137551007262) **SKIPPED** by dependency: zero executed new original UML tests, no KTAP or native JSON. Original stage negative tests also not executed by CI. Prior local host-model PASS remains historical and does not qualify this red source SHA. Corrective code-bearing Round074 work is separate; this failed source run must remain FAIL and never be retroactively reclassified. `SOURCE_MAPPED_AUTHENTICATED=0`, `PHASE_A=BLOCKED`, all compressed handoff activation OFF.
