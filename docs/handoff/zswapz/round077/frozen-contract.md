# Round077 frozen contract — three existing independent agents 4, 6 and 10

Official issue: https://github.com/k1moradi/swapz/issues/194. Source planning SHA 9ae3c090fb91eb61a253bc7590e02896be68e9b2; pinned original Linux torvalds/linux@c339f4010dea8b0d754f84ace70cd1b089878ef8. Start only after one authoritative issue comment containing message: ROUND_OPEN and the verified task commit SHA. Read AGENTS.md, docs/testing_standards.md, docs/handoff/zswapz/evidence-policy.md and your entire individual task.

## Staffing and scheduling

**Three reused agents, excluding manager Agent1: 4, 6, 10.** No new agent IDs. All work from the already committed latest main independently and simultaneously; no same-round peer code/test/API/CI depends on another's new work. Only publication of direct GitHub sole main commits serializes, via fresh expected-head CAS one-parent nonforce fast-forward, followed by remote verification. Zero other branches or PRs, no force, monitoring automations, owner as evidence courier, privileged/loaded/activated swap/physical/real-pressure operations.

- Agent4 DOCS ONLY: original pinned Linux zswap compressed-byte handoff feasibility, source identity and ownership, lifetime, original codec vs swapz codec, real recovery and proof gates. It takes over unfinished Round076 Agent8 read-only source audit, which was blocked by inaccessible GitHub and has no committed canonical files; NEVER fabricate Agent8 results. Agent4's prior Round074 original-source host PASS has terminal evidence and no work blocking it.
- Agent6 HOST CI only: correct Round074 dependency install cancellation, bounded/preinstalled toolchain decision; one changed-source GCC/Clang strict ASan/UBSan and 25 compiled/executed semantic mutants/compiler, not native/physical.
- Agent10 ORIGINAL PINNED NATIVE only: correct Round073 test fixture usleep_range undeclared original UML compiler failure and prove four genuine KUnit cases with JSON/KTAP after valid new source-host checks; no production kernel code.

All prior open rounds retain their exact statuses. In particular R073 Agent10 genuine native source FAIL before KUnit, R074 Agent6 CANCELLED before compiler, R075 Agent5 in progress, Agents9/11 queued, R076 Agent2 queued and Agent8 BLOCKED. Do not spawn duplicate original UML CI or source-work ownership.

## Verified first errors

Agent10 source ecaf63cb7860879364a6e3943884bc30e578ca63, run https://github.com/k1moradi/swapz/actions/runs/45134656124: host job137557932353 SUCCESS, native job137610101851 FAILURE at original staged linux/mm/zswap.c:5307:25: implicit declaration of function usleep_range [-Werror=implicit-function-declaration]. Original stage ten final postimages passed; actual KUnit cases ZERO. Current test-only fragment tests/runtime/native/fixtures/round073-original-reader-pin-gc-kunit.cfrag calls usleep_range(1000,2000) but lacks explicit linux/delay.h in its existing include scope. Fix test-only declaration, not production or warnings.

Agent6 source 1868d599c6cf33823a36b93c962847cd6e36d475, run https://github.com/k1moradi/swapz/actions/runs/45145752021: job137594490455 CANCELLED during unbounded sudo apt-get update/install in 15-minute host job. Exact SHA/git diff check succeeded; C verifier/mutants SKIPPED. Cause of apt stall unknown, not a C fail or PASS. Repair dependency step in .github/workflows/phase-a-round074-eviction-lease-copy-budget-host-noauth.yml, require true compilation/execution.

Agent4 previous R074 source SHA14f8fe29280f0f77b1bf013aef8904913eaa869f, run45145423813 terminal SUCCESS (host-only 20 compiled/executed C mutants). Existing Agent8 R076 missing files and source audit must be delivered by Agent4 as R077 work; prior #193 remains honestly blocked. See https://github.com/k1moradi/swapz/issues/193#issuecomment-7101330167.

## Architecture and safety

Original Linux MM/zswap exclusively owns compressed RAM and natural pressure-driven eviction/reclaim. swapz manages disk payload packing, extent allocation and GC only, with NO second shrinker/pressure timer or recompression of original authentic compressed bytes. Pinned original https://github.com/torvalds/linux/blob/c339f4010dea8b0d754f84ace70cd1b089878ef8/mm/zswap.c#L994-L1095 zswap_writeback_entry creates locked swapcache folio, validates XArray, DECOMPRESSES original entry, erases/frees original compressed source and issues ordinary swap_writeout. Hence ordinary swapz RAW_4096 always full ORIGINAL UNCOMPRESSED 4096 and cannot be compressed handoff. A future separate ORIGINAL_COMPRESSED_OPAQUE path needs actual authenticated original STORED folio/slot/generation, current selected DM target, bounded immutable pre-erase compressed copy, volatile original codec LZO1X or raw LZ4 independent of swapz disk codecs, independent retained decoder and GC reader pins, full original 4096 verification, data-only lower 4/8/16KiB allocation, actual lower WRITE+FUA/flush then once-only real upper BIO ACK. Protect physical SWAPSPACE2 first 4096 UUID/signature/partition, exact 20B volatile map. No recovery claim after map loss. No mock/host witness is source authentication.

SOURCE_MAPPED_AUTHENTICATED=0; PHASE_A=BLOCKED; DIRECT_COMPRESSED_HANDOFF=DISABLED; FORCED_RAW_BYPASS=DISABLED; import ACTIVE0. Production C/H read-only this round.

## Delivery and tests

Each agent commits BOTH docs/handoff/zswapz/round077/agentN-evidence.md and agentN-results.json to main, and posts #194 actual source SHA+parent, GitHub Actions run/jobs, compiler/semantic and genuine original KUnit JSON/KTAP counts or DOCS_ONLY, first error and immutable links to BOTH files. Agent4 also commits detailed agent4-source-seam-audit.md. On terminal exact CI update those files in evidence-only direct-main commit; never relabel old failed/canceled source green. Agent6/10 code/workflow changes require meaningful same-commit literal-prefix-preserving docs/testing_standards.md appendix, git diff --check HEAD^ HEAD and canonical policy. Agent4 docs-only needs no CI. No owner make test or fast_test for administrative docs; focused new exact-source tests only.
