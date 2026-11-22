# Round064 Agent4 — diagnostic-first original decoder P0

Official issue #181; original pristine pin
`c339f4010dea8b0d754f84ace70cd1b089878ef8`.

## Actual first error, before changing decoder source

[Prior exact workflow #44970260193](https://github.com/k1moradi/swapz/actions/runs/44970260193)
at engineering `3e79823eb79fed85afb4e9a3ee67cc59835e68ed`.
Source-host job137048279421 terminal success; native
[y job137055334554](https://github.com/k1moradi/swapz/actions/runs/44970260193/job/137055334554)
and [n job137055334642](https://github.com/k1moradi/swapz/actions/runs/44970260193/job/137055334642)
both passed pristine native defconfig/olddefconfig/full vmlinux/all modules
and actual external positive GPL modpost. Both fail:
`compiled module did not retain original decoder link LZ4_decompress_safe retained=lzo1x_decompress_safe,sha256 missing=LZ4_decompress_safe`.
Prior positive root and source function presence gates passed. Actual
negative missing-export modpost not reached. No previous downloadable
artifact, .cmd, .i, or per-object traces retained. Container cannot
resolve GitHub for direct Linux clone; installed headers are NOT the
pinned full original Linux. Actual omission stage and root cause remain
unknown, no decoder-source change is justified.

## New engineering evidence and diagnostic-first workflow

Keep fixture, real decoder source, and existing native verifier unchanged.
Add an inspector of genuine .cmd, Kbuild .i, source identity, native
config/provider, real consumer .o, codec.o, combined .o and final .ko,
including nm, readelf and objdump. Bounded symbol/relocation counts and
compiler flags appear in exact CI output; raw evidence remains private.
Both original configs will execute actual absent-symbol negative modpost
even on positive failure and compile an independent real-source LZ4
omission mutant. All positive/diagnostic/negative statuses are required.
The diagnostic change itself does not presume a cause or fix the real
decoder path. Actual native results pending.

Local rootless GCC 14.2 and Clang 17 compiled and inspected four actual
strict warning-clean C objects, two baseline and two missing-LZ4 mutants:
`ROUND064_REAL_GCC_CLANG_ELF_ORACLE_SELFTEST_PASS objects=4 omission_negatives=2 structural_only=1`.
The real compiler object omitted only the LZ4 external reference and
text relocation in each negative. This is a structural oracle test, not
original codec semantics or native modpost. Local script Git blob
`80bea7d4d9cfbc512f44034b092b7330d1d6c307` matches remote.
Exact proposed workflow Git blob
`bbf514f1e494b667ef49dbd7504b2d05716aacaa`: PyYAML parse and all bash
run bodies passed bash -n. Exact shell aggregation with mocked
compiler/verification statuses tested 4/4 positive/negative combinations;
both negative branches reached even if positive verifier failed; either
status nonzero fails overall. No mocked native result claimed.
Existing actual rootless sanitizer and ten executed codec mutants remain
required by source-host, exact new CI pending.

AUTH0 Phase A BLOCKED, imported ACTIVE=0, compressed handoff and forced
RAW bypass DISABLED, normal RAW_4096 full original uncompressed page,
no loaded decoder lifetime, durable I/O, source/DM authorization, ACK,
or owner physical/pressure/privileged/Make testing.
