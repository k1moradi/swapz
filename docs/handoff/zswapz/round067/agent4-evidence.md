# Round067 Agent4 — original selected decoder-owner P0 compiler first error

Official [Round067 #184](https://github.com/k1moradi/swapz/issues/184),
[ROUND_OPEN](https://github.com/k1moradi/swapz/issues/184#issuecomment-7078429736),
prior engineering b181201a38dc7dde9d561e2c21a214b6c1e8e1ec,
frozen docs aeceaf19ddb0499fc01b3251136111f53f4c6eca.

## Actual inherited terminal native failure, not an ELF retention problem

Latest inherited [45014248163](https://github.com/k1moradi/swapz/actions/runs/45014248163)
actual x86 job137186573213 (zswap=y) and job137186573218 (zswap=n)
both terminal FAIL. Both full *original unmodified* kernel vmlinux/all
modules passed; first actual external module compile error is
`include/linux/wait.h:223:54: error: 'TASK_NORMAL' undeclared`.
The exact original `wake_up_all` macro uses `TASK_NORMAL` and the
pinned original `include/linux/sched.h:144` supplies it.
Pins: original kernel c339f4010dea8b0d754f84ace70cd1b089878ef8;
wait.h blob c2af98b0074dcbdb2175850d05e377bf3b935663,
sched.h blob 1c93da75226e32400d248bf77066200a181a3f20.
The dormant decoder-owner header previously included original wait.h but
not sched.h. Its `put` calls the actual wake-up and therefore needs both.
The previous rootless host mock defined its own wait/sched primitives and
cannot qualify this pinned kernel include dependency.

The reporter then masked the *first* native compiler error with
`invalid original build phase`, because its lowercase-only regex rejected
the workflow's actual `actual-original-GPL-modpost` phase. Separately the
deliberate undefined decoder negative died at C compilation, **not** at
real original kernel modpost: the positive, diagnostics, missing-export
negative and omission negative aggregate statuses were 2/1/1/2 in BOTH
configurations, not success. The previous Round065 ELF parser P0 remains
closed and is not modified.

## Scoped source correction and preserved close/wake fix

- `src/kernel/zswap-import-decoder-owner.h` includes original
  `<linux/sched.h>` directly before original wait/spin facilities, so
  `TASK_NORMAL` is available at the actual `wake_up_all` expansion.
- Original direct source verifier pins both original Linux header Git blobs
  and validates expected wake/define, plus the actual owner include contract.
  The native first-error reporter uses an explicit fixed list of real build
  phases instead of silently rejecting the uppercase GPL name. A rootless
  self-test captures the exact bounded sanitized first C compiler error,
  refuses three invalid build phases, refuses compiler error as modpost
  negative and accepts a deliberately isolated true modpost diagnostic.
  An invalid negative C build now emits its earliest bounded source error
  before failing closed. All prior semantic ELF/provider/omission checks
  remain unchanged.
- The Round066 actual owner.c final reader wake under owner spinlock,
  wait_event condition and close rejoin after final put are **unchanged**.
  Its existing strict GCC/Clang mock synchronization two semantic mutants
  per compiler, original LZO1X/LZ4 full 4096 host ABI decode and nine
  compiled/executed product owner C semantic mutants per compiler remain
  obligatory in the same exact-source hosted source job.
- The native original x86 y/n workflow compiles the *real* owner C/header,
  real original selected provider LZO1X and raw LZ4, product codec.c and
  selected public SHA. The positive, diagnostics, actual nonexistent-export
  original modpost negative and real omitted-LZ4 source negative all must
  have independent zero statuses for BOTH y and n. Merely compiling a
  false negative or seeing host mock PASS is explicitly insufficient.

## Unresolved live/runtime/physical qualification

Until exact-source terminal native y/n results are read: **PROGRESS**
rather than native REPORT_READY. Even all four native compile/link gates
PASS only proves static selected decoder linkage, module dependency
metadata and source-bound ownership code, NOT loaded module provider refs,
runtime pool teardown, actual source-current-DM table lifetime, lower
durable compressed WRITE/FUA, ordinary production map GC, a real upper
ACK or a real physical independent read. Never infer loaded lifetime from
the test-only compile consumer: its module_init still refuses
`-EOPNOTSUPP`. Original Linux MM alone controls compressed RAM and
natural memory-pressure eviction; swapz owns disk compression/packing/GC.
`SOURCE_MAPPED_AUTHENTICATED=0`, `PHASE_A=BLOCKED`, imported ACTIVE=0,
direct compressed handoff DISABLED, forced RAW bypass DISABLED.
Ordinary `RAW_4096` is the entire original UNCOMPRESSED page; original
native LZO1X/LZ4 uses a separate codec-tagged volatile representation.
SWAPSPACE2 header/first4096/UUID/signature and parent partition table
untouched; no owner Make, loaded/privileged/physical/actual-pressure tests.
