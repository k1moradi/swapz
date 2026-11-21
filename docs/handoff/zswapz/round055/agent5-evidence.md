# Round055 Agent5 — finite-service scheduling frontier, independent rootless result

Frozen engineering `31adfb7ff57cc5c061304beae749b485d093130b`; full task `3e0b4c7fd6d1554e616bc668a18edad8a49ca980`. Scope is the isolated model, runner, existing scheduler workflow and documentation only. No production/kernel/MM/codec/DM source changes. Real product `src/kernel/dm-target.c` frozen blob d5b70c5cf200d360f4024abdf83232fbd58557c4 already has retain_ms, batch_count, singleton_fast_close, swapz_worker_pack_close_ready, swapz_service_proven_dry_pack, swapz_worker_pass and ordered in-flight completion. Its singleton streak fast-close and hard 2ms deadline are not the model's synthetic ticks. Do not install an additional batcher or reclaim controller.

## Actual local executions, exact fixture blobs, limits

GCC 14.2.0 and Clang 17.0.0 actual C23, -Wall -Wextra -Wconversion -Wshadow -Werror, ASan/UBSan with recovery disabled. Both:
* inherited 192 events/21 directed hostile cases PASS;
* inherited Round054 48 comparative traces, 9 directed cases and **10 compiled/executed named semantic C mutants** PASS, counters unchanged; small fixture-only reserve parameter allows 0/1/2/4 blocks, default remains four;
* new 13 scenario triplets (39 actual policy runs), decision gates and timed RAW EIO/rollback/retry and durable-but-rejected teardown test PASS; **7 compiled/executed C mutants per compiler** exit 1 with the intended named semantic C assertion, not warning/ASan/crash kills. Deterministic output agrees across compilers.
Local exact tested Git blobs: changed prior C fixture 48750a1fd8089188fe71242fd65d88b782d85885, new C c688ff4377c7d878aab324455e441d23f14287b9, runner e026515f82f9266abb0776719c4b321cba9ef4c1. The isolated local compiler harness uses the five exact frozen product codec.h geometry macros, not a full pristine checkout. Direct Git transport DNS unavailable; no local actual-history repository --enforce or HEAD^ HEAD check claimed. Local changed text has no trailing whitespace; the existing workflow retains full clean main checkout, actual push-before SHA, git diff --check HEAD^ HEAD, canonical --enforce, and both inherited suites before the new runner. [Frozen combined scheduler #44882508812](https://github.com/k1moradi/swapz/actions/runs/44882508812) job 136780657744 verified terminal SUCCESS at frozen engineering SHA only. Current source CI must independently run and qualify.

## Model and measured model counters

Fixed external deterministic arrivals (not a reclaim loop), 20 arrival ticks, identical event IDs and fault schedules within each scenario; strict FIFO of accepted pages, at most eight retained full 4096-byte pages including active I/O, four records per pack. One ordered lower owner, a fast 1-tick, slow 2+blocks or variable 1+(head ID*13 mod 4)+blocks/2 service time (maximum six), one modeled dispatch per tick; queue delay is admission-to-submit, service delay submit-to-terminal callback, ACK wait admission-to-terminal, intentional idle hold separately limited to two ticks. Read/flush are ordering-only fences, not measured lower read/flush costs; no later admissions while the synthetic fence drains earlier work. External harness retries only its oldest refused arrival at most twice, then drops that ID; no ACK/ownership on refused events and no hidden internal extra queue. Trace drain cap 512 ticks and admitted queue wait <=8*6+2; actual max hold 0/0/2. Full original upper page is always checked; compressed modeled lower records are opaque prefixes, not LZ4 or full decompression verification.

Policies: FIFO immediate one page; ready-only immediate packs independent already-accepted ready prefix; adaptive waits only if 2 or 3 independent compressed records, recent accepted burst evidence, spare room >=512 in proposed valid extent, no fence/RAW/singleton/closed/full queue, >4 available nonreserve blocks and head age <2. No waiting for a singleton or forced MM write. Larger allocation refusal falls back once to single page. No production policy change or real timer assumption.

Aggregate counts over the 13 scenarios, with no setup seed cost (identical for policies within each trace):

| Counter | FIFO | Ready-only | Adaptive |
| --- | ---: | ---: | ---: |
| External arrivals | 365 | 365 | 365 |
| Accepted / decoded / independently compressed | 249 | 265 | 265 |
| Successful | 203 | 216 | 216 |
| Failed accepted | 46 | 49 | 49 |
| Unaccepted dropped | 116 | 100 | 100 |
| External retry attempts | 250 | 215 | 215 |
| Foreground attempted requests | 216 | 147 | 137 |
| Foreground durable completed requests | 203 | 134 | 124 |
| Foreground authoritative committed requests | 203 | 133 | 123 |
| Foreground attempted bytes | 884736 | 700416 | 659456 |
| Foreground durable completed bytes | 831488 | 647168 | 606208 |
| Foreground authoritative committed padded bytes | 831488 | 630784 | 589824 |
| Committed padding | 419904 | 197260 | 156300 |
| GC attempted write bytes | 28672 | 28672 | 28672 |
| GC completed write bytes | 12288 | 12288 | 12288 |
| GC read bytes | 28672 | 28672 | 28672 |
| Total attempted requests incl GC read/write | 222 | 153 | 143 |
| Total completed requests incl GC read/write | 208 | 139 | 129 |
| Total attempted bytes incl GC read/write | 942080 | 757760 | 716800 |
| Total durable completed bytes incl GC read/write | 872448 | 688128 | 647168 |
| Worst admitted queue wait, ticks | 21 | 16 | 16 |
| Worst lower service wait, ticks | 4 | 6 | 6 |
| Worst admitted ACK wait, ticks | 24 | 19 | 19 |
| Max retained raw bytes | 32768 | 32768 | 32768 |

Ready-only vs adaptive matches successful ID sets, accepted/failed/dropped counts in all 13 scenarios (and equal retry counts). This pair has equal actual modeled decode/compress count (265 each; 1,085,440 upper bytes each). FIFO aggregate useful work differs, so its aggregate is *not* an equal-success speedup comparison. The model accounts physically completed but map-aborted teardown bytes separately from authoritative commits, verified by the new seventh mutant. GC counts three attempted relocation writes (two successful, one injected EIO) and three successful copy reads; all policies have identical GC cost. The GC model rotates an equal-size contiguous reserved destination, not unrestricted production GC, and does not model read amplification or device/cache durability. No CPU milliseconds, cycles, physical IOPS or hardware measurements.

| Scenario | Ready-only / adaptive total requests attempted | Completed bytes | Success IDs/count | Queue p95 (ticks) | Service p95 | ACK max |
| --- | --- | --- | --- | --- | --- | --- |
| sparse-fast | 5 / 5 | 20480 / 20480 | same 5 | 0 / 0 | 1 / 1 | 1 / 1 |
| ready-burst-fast | 7 / 7 | 28672 / 28672 | same 28 | 0 / 0 | 1 / 1 | 1 / 1 |
| paired-fast | 10 / 6 | 40960 / 24576 | same 20 | 0 / 2 | 1 / 1 | 1 / 3 |
| paired-slow | 8 / 6 | 32768 / 24576 | same 20 | 2 / 2 | 3 / 3 | 5 / 5 |
| paired-variable | 10 / 6 | 40960 / 24576 | same 20 | 2 / 2 | 3 / 3 | 3 / 5 |
| overload-variable | 19 / 19 | 102400 / 102400 | same 28 | 12 / 12 | 4 / 4 | 15 / 15 |
| GC raw | 16 / 16 | 65536 / 65536 | same 15 | 16 / 16 | 4 / 4 | 19 / 19 |
| GC two | 17 / 17 | 81920 / 81920 | same 18 | 12 / 12 | 4 / 4 | 16 / 16 |
| GC four EIO | 17 / 17 | 81920 / 81920 | same 18 | 12 / 12 | 4 / 4 | 16 / 16 |
| target close | 4 / 4 | 28672 / 28672 | same 3 | 13 / 13 | 6 / 6 | 14 / 14 |

Cumulative paired-profile savings 10 attempted lower requests and 40960 completed bytes, but fast paired p95 queue delay rises 0->2 and peak retained raw bytes 8192->16384. Variable paired ACK max rises 3->5. Slow paired has same observed p95/ACK max. No gain from waiting in the other ten scenarios. Absolute memory bound: fixed pending array 33056 bytes on tested ABI, including 32768 raw payload plus 288 event metadata (not including static RAM-disk fixture, external trace or measurement arrays). Same fixed array under all three model policies.

Same low-capacity no-GC mixed trace: 16 physical blocks minus block zero gives 15 data blocks; reserving 0/1/4 leaves 15/14/11 usable (0, 6.67%, 26.67% of data capacity). Ready/adaptive successes 18/13/10 respectively; this is *not* a speed improvement through dropping work. No-GC reserve cost is real in the model; reserve sized to actual relocation requirement, never promise a 16KiB move with a shorter reserve. A four-block reserve is 16KiB and 6.35% of a 63-data-block disk. Real product allocator and GC invariants remain authoritative; no proposed shrink of its mandatory safety reserve.

## Recommendation and boundaries

**NO_CHANGE to production.** Prefer work-conserving already-ready pack when no evidence warrants added delay. Adaptive finite retention remains a **default-OFF future candidate**, only with evidence of paired bursts and an independently qualified actual device/service model and existing ordered owner/retention; max eight retained, four records, two modeled ticks (not ms), no added waits under sparse/pressure/fence/teardown, no extra allocations for a new batcher. Preserve existing GC safety and make reserve capacity explicit. This finite-service host model does not authenticate original source slot or real DM lifetime. One authoritative map and one modeled ACK only after durable successful current mapping; EIO, late/duplicate callbacks, cancellation, GC and full original 4096 rollback remain covered; entire synthetic physical first page and partition sentinel checked. Ordinary RAW_4096 is original UNCOMPRESSED 4096. Future codec-aware lower staging is explicitly counterfactual and disabled, so zero recompression avoided; no real codec-aware read/ownership proof claimed. SOURCE_MAPPED_AUTHENTICATED=0 PHASE_A=BLOCKED DIRECT_COMPRESSED_HANDOFF=DISABLED FORCED_RAW_BYPASS=DISABLED. No owner make test/fast_test, privileged, loaded-module, physical-swap or real-pressure tests.
