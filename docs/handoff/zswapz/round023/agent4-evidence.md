# Round 023 — Agent 4 independent frozen source cross-ABI audit

Official opener: https://github.com/k1moradi/swapz/issues/140#issuecomment-6928573299
Frozen task baseline: dd08a3dbc8309da266f49f975b6733cd33a25a8d
Current source: Round022 compile-disabled producer + standalone consumer.

This change adds only new owned cross-ABI test files and CI. The Python
test extracts the actual #if0 pinned-Linux producer C from the existing
stager and the actual host shim, compiles it with the original swapz
LZ4 imported decoder and original production codec.c, then executes real
GCC and Clang warning-clean ASan/UBSan C. The separately authored C adapter
must explicitly map mock producer slot and store-generation to distinct
synthetic DM logical page, DM generation and GC epoch. The mapping is
MOCK/UNTRUSTED and has no actual Linux MM/BIO owner or transport authority.

Positive fixture: one genuine userspace LZ4 block of 4096 original bytes
→ source-model zpool entry → copied immutable producer payload
→ original SHA recorded at synthetic store → canonical kernel
~crc32c(~0U) → production swapz_crc32c_bytes → consumer exact
LZ4 block decoded 4096 → separately checked SHA256/memcmp. Reject old
IEEE CRC32 and raw crc32c(0) (9-byte known vector distinguishes them),
missing mock source authority, source slot/epoch/DM generation mismatch,
unsupported codec/version/dictionary, bad length 0/>3568, corrupted
CRC/SHA, partial lower read, no durable write/mapping/upper ACK,
duplicate upper ACK, teardown, aliased buffers and once-only source
completion. No successful upper read or partial output on rejection.

Important source boundary: no original Linux source has authenticated
zswap store-time SHA/generation transport to DM; a rootless mock does
not establish this. Real booted modified Linux, loaded matching DM,
owned ephemeral RAM, real stored eviction or actual 4096 kernel readback
have NOT_RUN status. No physical SWAPSPACE2 header/UUID/partition
operation, module, swap or memory pressure performed. Current RAW is
ORIGINAL UNCOMPRESSED 4096, no compressed handoff/forced RAW bypass
enabled, Phase A BLOCKED.


## Original exact-source CI first failure and correction

The first pinned new workflow on SHA f6bb8f5e8b7c9045e3afb889459f747dd730f9bf,
run #43953308556, genuinely FAILED GCC and Clang compilation:
zswap_swapz_owned_payload_abort was unused in the new excerpt;
existing production codec.c emits size_t→swapz_u32 conversion warnings.
No runtime decoded 4096 result may be claimed for that failed run.
A negative assertion now exercises abort refusal after submit. The Python
compiler pipeline builds unchanged original codec.c separately with
-Werror and explicit -Wno-conversion only on its translation unit;
the extracted producer/consumer C fixture retains strict
-Wall -Wextra -Werror -Wconversion -Wshadow ASan/UBSan.
This isolates existing production warnings without modifying/weakening
new fixture source or touching any kernel/device.


## Independent frozen Git-object follow-up (append-only)

Preserves the earlier published Agent4 main commit; supplements it with
`tests/runtime/native/zswap-compressed-cross-abi-frozen-test.py` and its
separate `fixtures/round023-cross-abi-interop.c`. Unlike mutable HEAD-source
extraction, this driver demands the exact authenticated Round022 stager,
standalone import header, production codec C and header Git blob identities
under source SHA `8ad53ee4f57c5f8b272ca3ef4fadf1d8cd7cfbc8`.
The repository's own existing workflow is extended (not replaced) with
`fetch-depth: 0`, preservation of the first cross-ABI test, new Python
fixture, and GCC+Clang -Wall/-Wextra/-Werror/-Wconversion/-Wshadow with
ASan/UBSan. The program exercises actual extracted disabled original producer
functions and linked original production codec/header. Its host-created
source→DM mapping, source pool, lower I/O and ACK values are explicitly
MOCK/UNTRUSTED, never a kernel transport or real I/O.

Additional first-failure matrix: internally consistent wrong initial seed
`~crc32c(0U,...)` and IEEE CRC32 **compiled producer source mutants**
MUST fail original consumer CRC32C, even with valid copied payload and
coherent fake record. This rejects a producer/consumer mismatch that
a consumer-only mutation cannot catch. The producer's exact owned-copy
lifetime, stale xarray/slot/proof, original independent SHA256, no partial
output, codec/length/representation, source/DM generation/GC-domain,
ACK 0/2, lower failure and teardown are exercised with fail-closed negative
assertions; no fake numerical identity is promoted to live provenance.

Locally executed rootless isolated CRC32C/LZ4/SHA smoke (NOT the complete
repository fixture, since container GitHub DNS blocked a local checkout):

- `gcc -std=c11 -O1 -g -Wall -Wextra -Werror -Wconversion -Wshadow -fsanitize=address,undefined -fno-sanitize-recover=all /mnt/data/round023_crc_lz4_smoke.c -llz4 -lcrypto -o /mnt/data/round023-smoke-gcc`: EXIT 0.
- `ASAN_OPTIONS=detect_leaks=1 UBSAN_OPTIONS=halt_on_error=1 /mnt/data/round023-smoke-gcc`: EXIT 0; CRC32C `123456789`=0xe3069283, raw seed0=0x58e3fa20, LZ4 length=326, original SHA256 computed.
- Matching `clang` compile/run with the same flags: EXIT 0, same output.
- `git ls-remote https://github.com/k1moradi/swapz.git refs/heads/main`: EXIT 128, cannot resolve host. The exact pinned original source tests were NOT_RUN locally; GitHub Actions must validate full import and GCC/Clang fixtures on the published SHA.

The original user-owner private physical failure numbers remain unavailable.
No kernel, device, module, swap, mapper, pressure or physical operation was
performed. SOURCE_ONLY after exact-SHA hosted verification; KUnit source/build
historical and independent; LIVE_HANDOFF=NOT_RUN,
LOADED_4096=NOT_RUN, PHYSICAL=NOT_RUN. Phase A BLOCKED;
Phase B forced RAW bypass DISABLED, compressed direct transfer DISABLED.
RAW still contains the original uncompressed 4096-byte page.


## Hosted first compiler failure and nonproduction test correction

The first exact-SHA cross-ABI workflow run
`43953872320` on `f053e7ff65c72756b7c77d585110fb95877cbf15`
completed FAILURE. The preexisting Round023 ordinary cross-fixture ran
two tests successfully; the new frozen-source test had two Python/static
checks PASS and three GCC subcases fail at **compilation**, not
interoperability. First compiler errors were our chained boolean
comparison in an `assert()` (`-Werror=parentheses`) and legacy
`sizeof` to `swapz_u32` conversions in the exact original production
`codec.c` (`-Werror=conversion`) when the driver used a blanket
`-Wconversion` on both translation units.

The correction makes the boolean CRC comparison explicit, compiles the
**new fixture** at -Wall/-Wextra/-Werror/-Wconversion/-Wshadow,
compiles the **unaltered frozen production codec.c** separately under
its established -Wall/-Wextra/-Werror gate, links both with ASan/UBSan,
and preserves source authentication, CRC fault injection, no partial
output and disabled production. There is no change to kernel codec/DM,
checksum arithmetic, frozen producer or physical acceptance. This is
a test harness compiler-flag scope repair, **not** proof of loaded
interoperability. Any later runtime failure must be separately reported.


## Same-round producer carrier integration: source-only refusal

The second hosted source-only cross-ABI workflow
`43954356412` on `b6babfd18f7f490ceb123b3d900950e7a73df690`
failed BEFORE the new frozen-source driver could run. Both GCC and Clang
rejected the **previous** mutable-HEAD Agent4 fixture because Agent2's
concurrently published disabled producer now defines two additional
`static int` source-only carrier functions without test references
(`-Werror=unused-function`). There is no executed kernel MM/BIO/DM
interop outcome in that failing step.

The minimal Agent4-only reconciliation preserves the exact Agent2 C
bodies and existing warnings-as-errors: if *both* optional static
helpers are present in the source, the original host test calls real
`zswap_swapz_carrier_snapshot_source_only` after its synthetic
submitted owner and demands `source_only_untrusted=true`. It calls
real `zswap_swapz_carrier_publish_disabled` even with all mock flags
true and after a forged `source_only_untrusted=false`; **both must
return -EOPNOTSUPP**. Missing one half refuses source drift; if
neither helper exists, the Round022-only baseline remains testable.
The independent frozen-original test runs first in the CI job so a
future HEAD-only integration failure cannot hide its verdict. No
production carrier is activated and no warning is suppressed.


## Optional post-publication source CI extension

After separately published Agent3 disabled DM admission source arrived,
the existing Agent4-owned rootless cross-ABI workflow gained an additional
isolated execution of zswap-compressed-admission-test.py. This preserves
prior frozen-source tests and runs the original actual committed
admission header + exact existing codec.c under compiler/sanitizer
negative cases with no module, swap, pressure or physical operation.
It is an integration source QA step only, not a dependency for Agent4
start or a loaded DM READ proof.
