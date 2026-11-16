# Round 016 — Agent 1 accountable engineering closeout

Issue: https://github.com/k1moradi/swapz/issues/133. [Original unedited worker reports](original-report-archive.md).

**Integrated source:** [b26c42d1ea7524a78747eafc431e35a1d1e94d35](https://github.com/k1moradi/swapz/commit/b26c42d1ea7524a78747eafc431e35a1d1e94d35), one non-force checked fast-forward from prior main `3dc116b34fefb1a10ffd46e01d788fdd545fe06d`. Both verified detached one-parent worker commits originated at `f716a5162a098742ec4bf7ab17b6a6a977bb75d4`: [Agent 2 manifest verifier 5af1e3e0](https://github.com/k1moradi/swapz/commit/5af1e3e0aa03fcbc3091f94042dde270346f138d) (2 files), [Agent 3 DM-source & CI 3c269221](https://github.com/k1moradi/swapz/commit/3c269221e53adca79c0c56c404b36a87ef52d80f) (6 files). Agent 1 validated changed blob SHAs against the reports and reconciled both independent `docs/testing_standards.md` appendices, preserving unrelated concurrent main fixes. Only branch main, zero open PRs. Subsequent unrelated [d3a43c129bf2](https://github.com/k1moradi/swapz/commit/d3a43c129bf207e6d1f7020ef2aafbc3f0789c4e) updated null_blk fault testing and was preserved.

## Real code

Agent 2: typed multi-object per-profile manifest grammar, exact distinct 3/4 object identity SHA-256 inventory, reverify no digest drift; ordinary duplicate fields, forged PASS and manifest mutation still rejected. Rootless worker claims 9/9 PASS, historical real artifact replay PASS; hosted UML y/n was NOT_RUN by worker.

Agent 3: `src/kernel/dm-target.c` per-BIO `origin_commit_counted` reset on admission and before single increment under the serialized ordered owner. Authentic stored origin remains observational, no routing change. Added source-extracted unmodified actual C helper GCC/Clang/UBSan fixture, negative mutations, and real matched-Linux workflow triggers/ABI checks. Worker reported compiler source-helper PASS and 24 source assertions/mutations; full hosted build NOT_RUN locally. Both workers' original reports preserved separately.

## Exact-source hosted CI and first failure (source b26c42d1ea7524a78747eafc431e35a1d1e94d35)

| Exact workflow | Outcome observed at source close | Scope |
|---|---|---|
| [rootless physical evidence audit #43842886656](https://github.com/k1moradi/swapz/actions/runs/43842886656) | **PASS** | Rootless audit, not physical device |
| [private/static contracts #43842886826](https://github.com/k1moradi/swapz/actions/runs/43842886826) | **PASS** | source/static |
| [production C #43842886924](https://github.com/k1moradi/swapz/actions/runs/43842886924) | **PASS** | compiled production-C suite |
| [real pinned Linux BIO KUnit #43842886936](https://github.com/k1moradi/swapz/actions/runs/43842886936) | **FAIL** | first failure verify_uml_config malformed-config-entry |
| [native project goals #43842886921](https://github.com/k1moradi/swapz/actions/runs/43842886921) | IN_PROGRESS | exact source native tests |
| [systemd/package #43842886849](https://github.com/k1moradi/swapz/actions/runs/43842886849) | IN_PROGRESS | host package gates |
| [modified Linux + matched module #43842886913](https://github.com/k1moradi/swapz/actions/runs/43842886913) | IN_PROGRESS | source-linked Kbuild, not loaded |

**New first failure:** Full [job 133215686189](https://github.com/k1moradi/swapz/actions/runs/43842886936) log and actual [artifact 14214860003](https://github.com/k1moradi/swapz/actions/runs/43842886936/artifacts/14214860003) show enabled `defconfig_exit=0`, `scripts_config_exit=0`, `olddefconfig_exit=0`, `prepare_exit=0`, `modified_objects_exit=0`, `zswap_object_exit=0`, `uml_kunit_exit=0`, but `verify_uml_config_exit=1` with `malformed-config-entry`. The earlier repeated `object=` first failure is gone, and the new typed object inventory and SHA manifest gates executed before `check_config()`. Both exact config SHA and object-inventory SHA were recorded before failure. The offending effective-request Kconfig line is **not retained in this artifact**; do not assume its content or loosen parser checks without reproducing it. The actual y/n config gate and five-case TAP never completed. Disabled profile was not run.

Late Round 015 pinned modified-Linux matched module on old source [#43834985929](https://github.com/k1moradi/swapz/actions/runs/43834985929) was **PASS**; not interchangeable with this source or loaded kernel. Watch pending jobs and report any later first failure. Closure is a **source-integration checkpoint with a known KUnit failure**, not entire project success.

## Final disposition

**CLOSED_SOURCE_INTEGRATED_CI_PARTIAL_KUNIT_CONFIG_FAIL.** Phase A BLOCKED pending genuine booted matched-Linux MM→BIO→DM authenticated stored-entry write, successful committed authority, byte-exact 4096-byte swap-in and fault/GC/retry/teardown. Phase B forced RAW bypass and compressed direct handoff DISABLED. Current swapz RAW stores original uncompressed 4096 bytes; CRC32 vs CRC32C and plaintext SHA of compile-disabled prototypes still do not form a valid compressed transport. The next round targets this first actual Kconfig parser failure and DM readback qualification in parallel, not speculative active memory-pressure policy.
