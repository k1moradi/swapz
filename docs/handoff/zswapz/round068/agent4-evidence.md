# Round068 Agent4 — actual pinned-original native decoder-owner KUnit

Official [Round068 #185](https://github.com/k1moradi/swapz/issues/185),
[ROUND_OPEN](https://github.com/k1moradi/swapz/issues/185#issuecomment-7079842049).
Last frozen product source 6a52194b5b03c1ae82543dc8420fb4218301bd6d;
task-doc SHA e55d970830358453324928fd9c20a421eb368ec8.

## Inherited original native positive and negatives already qualified

Previous Agent4 exact source [run45023772039](https://github.com/k1moradi/swapz/actions/runs/45023772039)
3/3 terminal PASS; real pristine original Linux
c339f4010dea8b0d754f84ace70cd1b089878ef8,
x86 ZSWAP=n job137212729772 and ZSWAP=y job137212729796
full original vmlinux/modules and true external GPL matched consumer.
Both matrices independently returned
positive=0 diagnostics=0 missing_export_negative=0 omitted_branch_negative=0,
with real missing-export original modpost and selected-LZ4 omitted branch
negative. This does not execute any native reader-owner lifetime.
Host job137212199075 GCC/Clang ASan+UBSan 2 actual C baselines +
18 compiled/executed semantic mutants, and mock kernel spin/wait C
2 baselines+4 mutants, passed. These were not native kernel scheduling.

## New independent test-only original kernel execution

- New original Linux *UML* KUnit fixture directly links unchanged
  src/kernel/zswap-import-decoder-owner.c/.h, unchanged product codec.c/h
  and dormant import codec header inside a separate staged lib/ test-only
  composite. Staging requires pristine pinned original lib/Makefile
  Git blob a2afe954805cb8a9973762f017d352ec9315e419, copies source
  blobs byte-identically, adds exactly one test-only lib/Makefile rule,
  rejects dirty kernel trees, and emits full SHA256 postimage manifest.
  No original zswap, DM or mm source is modified or given a new API.
- The four actual KUnit cases test both LZO1X and LZ4 immutable source
  codec profiles, wrong profile/version, duplicate lease get/put, ref
  overflow, and rejection of late get after close. A real original
  kthread calls sleepable close while two pinned reader leases remain
  held; a bounded original scheduler observation confirms close is
  still blocked, then two actual puts trigger last-reader wake, close
  joins before owner storage is released. Repeats 24 times.
- Actual pinned original Linux LZO1X and raw LZ4 compressors create
  separately owned byte streams. After an independent copy, the
  source-owned compressed buffer is *freed* before the live reader lease
  calls unchanged import decoder, native original decoder implementations,
  genuine product CRC32C and native SHA256. Both actual 4096-byte
  output comparisons and SHA-corruption output-unchanged refusal run.
  Exact authority/ACK/FUA fields are **synthetic test inputs**, not proof
  of original STORED slot, real durable lower WRITE, real upper ACK,
  authenticated table/source or real source-pool retirement.
- Rootless strict GCC/Clang -Wall -Wextra -Wconversion -Wshadow -Werror
  ASan+UBSan run unchanged actual decoder-owner C with 18 genuinely
  compiled-and-executed semantic owner mutants and 4 wake/close
  changed-C mutants. New KUnit JSON+KTAP verifier requires all four
  real kernel cases PASS, no skip/crash/error, no forged suite and real
  KTAP per-case execution. Its 8 false verdict variants are rejected
  in a separate structural regression; these are NOT C mutants.

## Scope and unproven

New native original UML CI is required to qualify these claims as
EXECUTED, separately from source-host. Until terminal exact run/job
raw results, status PROGRESS. Compilation-only, synthetic JSON, mock
spin/wait and host ABI tests never count as real original kernel runtime.
The native UML runs rootless without actual module load/unload, without
original source pool/tfm lifetime transitions, no actual production
zswap original STORED slot, no real DM current-table lease, no actual
lower BIO/FUA physical durability, no upper ACK, no authentic map,
GC admission or physical device operation.

Owner lifetime requires caller to keep owner storage live through
close_and_drain AND until concurrent new gets have quiesced; close
must be sleepable and must not execute on its own pinned reader task.
There is no per-page module_get/put. Built-in real original decoder
calls in UML do not prove modular decoder provider pin across unload:
Round067 matched native module dependencies were static only.

Linux MM alone controls zswap compressed RAM/natural memory pressure
eviction; swapz performs disk compression, packing and GC only.
Ordinary RAW_4096 remains the FULL ORIGINAL UNCOMPRESSED 4096-byte
page, separate from native codec-tagged volatile LZO1X/LZ4.
SOURCE_MAPPED_AUTHENTICATED=0, PHASE_A=BLOCKED, imported ACTIVE0,
DIRECT_COMPRESSED_HANDOFF=DISABLED, FORCED_RAW_BYPASS=DISABLED.
No owner Make, privileged, loaded-kernel, physical, actual-pressure,
mkswap, swapoff or repartition. SWAPSPACE2 first4096/header/signature/
UUID and physical parent partition table untouched.
