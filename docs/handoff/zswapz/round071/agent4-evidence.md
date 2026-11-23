# Round071 Agent4 — original-kernel pool retirement and decoder qualification

Task authority: [issue #188 / ROUND_OPEN](https://github.com/k1moradi/swapz/issues/188#issuecomment-7091199100). Original pinned Linux: `torvalds/linux@c339f4010dea8b0d754f84ace70cd1b089878ef8`; exact original `mm/zswap.c` Git blob `ae19e301fced7e357a4c7587dfdd6abb890b9163`. Engineering baseline: `73446b1a5f88ec8d3ba1e45e623825fd5fed2880`; task-publishing commit: `057346ca1fbbed73c7c664c56a3272c9b1a5fbb6`.

## Source and ownership

Only **new Agent4-owned test fixtures/stager/validator/workflow** are modified. The actual default-inactive product decoder-owner C/H is unchanged: no reproduced product defect warrants mutation. The stage first invokes the **existing, independently green Round068** original decoder stage. It checks all eight inherited SHA-256 staged postimages, original Git SHA and original `mm/zswap.c` blob, then makes exactly two bounded test-only insertions into original `mm/zswap.c`: a static destruction-complete counter next to original `zswap_pool_destroy()` and an increment **after** the original hotplug/per-CPU tfm/zsmalloc release and `kfree(pool)`. It finally appends a new original-translation-unit KUnit fragment. Its manifest checks exact postimage bytes and nine total staged objects; no upstream production edit or partial original replacement is accepted.

The actual **original** `zswap_pool_create("lzo"/"lz4")`, original per-CPU `crypto_acomp_compress()`, `percpu_ref_kill()`, `__zswap_pool_empty()`/XArray removal, `queue_rcu_work()`, `__zswap_pool_release()` and original `zswap_pool_destroy()` must run in original UML. This is distinct from freeing a test-only source buffer. The copied byte-identical owned stream is independently decoded to the full original 4096 with real product decoder-owner leases **after actual source tfm/pool destruction**. The two new native KUnit cases each exercise 24 reader/close/last-put/wake cycles with a real kernel kthread. They reject stale codec, CRC corruption, late get, double put and nonzero output modification on failure. Four previously green original LZO1X/LZ4 and ownership cases must still execute.

### Exact verification policy

- Host: `round071-stage-original-pool-retirement.py self-test`; `round071-original-pool-retirement-verify.py self-test`; inherited original decoder and Kconfig verifiers; **actual production owner C** compiled and executed with strict GCC and Clang ASan/UBSan and 22 compiled/executed semantic C mutants via existing Round066 tools.
- Native: pristine pinned Linux and original Kconfig must be verified, request `CONFIG_ZSWAP_DEFAULT_ON=y` **only to register the ordinary built-in zswap CPU hotplug pool**; `CONFIG_ZSWAP_SHRINKER_DEFAULT_ON=n`, no swap activation/device/pressure. Build original rootless UML using `KCFLAGS=-Werror`. Two new plus four inherited KUnit cases must all PASS with JSON/KTAP agreement and **zero FAIL/SKIP**. Test runner fails immediately on an exact original blob/postimage mismatch, native compiler error, missing provider, execution timeout, skipped case or any sanitizer report.
- Staged original boot uses only in-memory allocated test pools and native KUnit; **not** a real module unload and **not** a real swapcache-backed natural eviction. Original source-pool death does not confer a real source-owner authentication, actual lower FUA, upper BIO ACK or imported active state.

### Evidence ledger (honest pre-CI state)

| Evidence | Status at source publication | Interpretation |
| --- | --- | --- |
| Local `python3 -m py_compile` of both new Python scripts | PASS | Syntax only, not original Linux runtime |
| Local `round071-stage-original-pool-retirement.py self-test` | PASS, 4/4 fixture-path negatives | Structural verifier, **not** 4 native/KUnit cases or C mutants |
| Exact GitHub Actions host GCC/Clang ASan/UBSan and 22 executed C mutants | NOT_RUN until source-specific job executes | Reuse tested previous committed tools; no speculative PASS |
| Pinned original UML with real pool tfm retirement, 6 KUnit + JSON/KTAP | NOT_RUN until source-specific job executes | Native acceptance BLOCKED pending exact job results |
| Genuine selected original swapcache STORED provenance; physical source auth; upper BIO; real device/pressure | BLOCKED | Out of Agent4 proof; no activation or waived gate |

Report only actual job IDs, first source/native errors and final verdict in [issue #188](https://github.com/k1moradi/swapz/issues/188) after results exist. No `make test`, `make fast_test`, privileged or loaded-kernel operation, actual swap/physical I/O, pressure or forced reclaim is authorized.

**Invariants unchanged:** `SOURCE_MAPPED_AUTHENTICATED=0`, `PHASE_A=BLOCKED`, `DIRECT_COMPRESSED_HANDOFF=DISABLED`, `FORCED_RAW_BYPASS=DISABLED`, all import `ACTIVE=0`. Ordinary `RAW_4096` remains an original **uncompressed** 4096-byte page. Original Linux MM is sole compressed-RAM/pressure owner; no secondary swapz shrinker. First SWAPSPACE2 block, UUID/signature, 20-byte map and partition table are unchanged.
