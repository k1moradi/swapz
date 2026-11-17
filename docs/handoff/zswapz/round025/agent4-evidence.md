# Round 025 — Agent 4 pinned Linux BIO sideband ownership feasibility

Official owner: https://github.com/k1moradi/swapz/issues/142#issuecomment-6939041436

Frozen Round024 engineering source: `c2469a86107f632dc795f4957113234f5bac62f6`.
Task publication source: `7c3b087e8af3a428b2703902653140ed4c9e7a5f`.
Exact upstream torvalds/linux: `c339f4010dea8b0d754f84ace70cd1b089878ef8`.

## Actual pinned source first blockers

The existing `bi_swap_origin` is an **already decompressed original full 4096-byte
REQ_SWAP WRITE** scalar; it is not an owned compressed buffer nor real source
slot-epoch mapping. The pinned original `struct bio` has `bi_private` reserved
for existing end-I/O and bio-chain ownership, and `bio_init` initializes it
NULL. `__bio_clone` copies `bi_io_vec` and `bi_iter`, not any compressed
descriptor. `bio_reset` calls `bio_uninit` then clears exactly
`BIO_RESET_BYTES`; `bio_reuse` saves/restores `bi_private` and completion
while resetting; `bio_prepare_reissue` retains the same BIO but resets
flags/completion. `bio_uninit` is also reached by free and clone failure.
The original `mm/page_io.c` uses 4096-byte ordinary `bio_init` followed by
`bio_uninit` on completion. Existing BIO clone/split/merge/DM sites cannot be
assumed to preserve a new semantic pointer without source hooks and independent
refcounting. A borrowed zpool pointer, descriptor put into `bi_private`,
normal BIO byte-count reinterpretation, or guessed equality of Linux swap
slot vs DM logical page is **not a supported ABI**.

## New source modifications (CI compile only)

`tests/tools/stage-pinned-linux-zswap-sideband.py` checks stock SHA-1 Git
blobs `0cc09b975d8ffbd45ca3dc47533a71f8e8164de6`
(`include/linux/blk_types.h`) and
`b0fcc69de653524479e3b328aa29a37e97945b84`
(`block/bio.c`). It verifies unique fixed source anchors and writes
**only those two** files to a disposable exact full upstream Linux checkout,
never this swapz repository's kernel/DM code. All changes are under the
undefined-by-default `SWAPZ_ROUND025_SIDEBAND_CI_ONLY` macro. The guarded
`bio` field contains only a separately typed owned descriptor reference,
NOT an ordinary `bi_private` or `bi_io_vec`. Refcounted immutable copied
payload lifetime on real `__bio_clone`, release on `bio_uninit`, stale
retry dropping via `bio_prepare_reissue`, and clearing on `bio_reset`
are compile-tested. Plain `bio_reuse` calls `bio_reset`, so drops the
descriptor. `swapz_ci_bio_merge_allowed` refuses any sideband; it is NOT
connected to live merge call sites, and live admission unconditionally
returns `-EOPNOTSUPP` because there is **no source-authentic epoch,
store-time digest, or DM sideband transport**. The actual RAW and 4096
upper BIO path are unchanged.

The same CI-only `block/bio.c` includes three actual pinned KUnit cases
testing real `bio_init_clone`, refcounted release, retry/reset/abort,
invalid length/CRC/codec/version and unconditional refusal. Mere compilation
of cases is **not KUnit runtime execution**. Host rootless supplemental
tests exercise the same ownership helper definitions with mocked
clone/split and ASan/UBSan. They neither authenticate a real Linux swap
slot nor demonstrate loaded MM-to-DM semantics.

## Test execution and first-failure policy

Planned exact-SHA host checks and compiler-only hosted job:

```sh
python3 -B swapz/tests/runtime/native/pinned-linux-zswap-sideband-test.py -v
python3 -B swapz/tests/tools/stage-pinned-linux-zswap-sideband.py --linux-root linux
git -C linux diff --check
make -s -C linux O=<separate-output> CC=gcc KCFLAGS=-DSWAPZ_ROUND025_SIDEBAND_CI_ONLY block/bio.o
```

The dedicated `phase-a-zswap-sideband.yml` checkout pins original Linux;
runs both GCC and Clang native host sanitizers with strict warnings;
stages only those two exact blobs; compiles real kernel `block/bio.o` with
GCC for both `CONFIG_ZSWAP=y/n` and `CONFIG_KUNIT=y`, then confirms
the KUnit suite symbol. The source does not request privileged kernel,
device, mapper, RAM pressure or physical swap operations. If source
verification, compiler API, KUnit type, or Kbuild fails, the FIRST source
error is an honest `BLOCKED`, not a fabricated success. At drafting,
the imported full checked-out source and Kbuild have NOT been executed
locally because this container cannot resolve github.com; exact hosted
CI evidence must be consulted before declaring the published code PASS.

`LIVE_CARRIER=DISABLED`, `LOADED_ORIGINAL_4096=NOT_RUN`,
`PHYSICAL_SWAPSPACE2=NOT_RUN`, `KUNIT_EXECUTION=NOT_RUN`.
Phase A BLOCKED. Forced RAW bypass DISABLED. Direct compressed
handoff DISABLED. Existing RAW means the original UNCOMPRESSED 4096
bytes. SWAPSPACE2 first header, UUID/signature, and partition table
remain untouched, as do existing disk format and the zswap cache's
exclusive memory-pressure/eviction ownership.


## Hosted pinned source checks and genuine bio_split compiler follow-up

For first published Agent4 commit
`59a743c9ac62d0d1d95c964acef87cf8649bf788`,
the exact-SHA GitHub Actions [run 44041682956](https://github.com/k1moradi/swapz/actions/runs/44041682956)
completed SUCCESS: native Python/rootless tests 5/5, GCC and Clang
ASan+UBSan source helper fixtures, exact two original Linux Git-blob
SHA/anchor admission, `git diff --check` in the staged disposable
upstream, real pinned `block/bio.o` GCC Kbuild/KUnit case suite symbol
for **both** `CONFIG_ZSWAP=y` and `CONFIG_ZSWAP=n`.
Both source build profiles printed `KUNIT_COMPILE=PASS`. This is compile
only: no booted KUnit cases or loaded kernel were executed. The first
observed source compiler failure at that exact SHA: NONE.

The independent source extension adds a KUnit test invoking the actual
pinned `bio_split()`, not a hand-written mock. The test performs
source-owned reference counting over the real clone path, checks proper
2048/2048 sector split, disallows sideband merge and cleans both BIO
and the temporary page with fail-closed error unwind. The previously
published full compile evidence does not establish this **new** test
compiled until its own exact-SHA run succeeds. No Agent 2/3 source was
changed; only the assigned separate Agent4 stager and regression file
were extended, with this append-only evidence and a separate uniquely
headed standards note. No production compressed carrier activation.
