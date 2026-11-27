# R105 Agent 10 — PASS_CONNECTED_COMPILE_LINK_ONLY (AUTH0)

Issue [#223](https://github.com/k1moradi/swapz/issues/223). One actual connected frozen kernel and external DM module build completed successfully. [Run 45965476047](https://github.com/k1moradi/swapz/actions/runs/45965476047) / [job 140393001987](https://github.com/k1moradi/swapz/actions/runs/45965476047/job/140393001987), attempt 1. No second full build or manual dispatch. Agent 1 retains sole final integration/acceptance.

## Exact inputs and publication

- Engineering freeze `ae7dc02e5db07fc6d133e02ffd558cb68c8e3159`, tree `3cc943f1e9dd46d6174f18e5adf7519a7e2f3f7c`; original Linux `c339f4010dea8b0d754f84ace70cd1b089878ef8`.
- Immutable historical stage `d2baba1bda02b78eb7df265d22c5e9dbee09e2b1`, baseline `5a36cabf0989dfffc75de52a6ab8cc021092ebf6`. Actual R102/R103/R104 historical helper chain and strict A1 correction reused, no historical verifier edits.
- [Tested source 9d7ebfc4531db341ecf889d8e0b85969443dc147](https://github.com/k1moradi/swapz/commit/9d7ebfc4531db341ecf889d8e0b85969443dc147), sole parent `5148f7f941fa9144d01c51b047fec16a7b9e557f`, tree `a5cc2d0e89cdf6a98eb07829d2f9a9ee15a640b0`; verifier blob `1bf717b1c4c5bebc6c5200156229d42f35058078`, workflow `562ffcf68b16ece08984456a09a5631d979269a3`. Previous testing-standards blob `5dd2baba9de981dba18c80229cb39449bf224fcb` reproduced exactly, complete prefix verified in `14b05a8ddf527584482e641792ed251d85eead11`.
- A1 overlay `3048e05e3f594dbaa6a10241fe1fa9c6092fbb54`, exact terminal include preimage `1ecc86d30f20790f1fae7506a3f55d612200831a` -> postimage `2bfc139f380461c71da78a8c7f9469d1e7eb0b22`. Actual logs show all five check/apply/reverse-check/reverse/reapply steps PASS. Staged diff and exact postimage guards passed. No same-round peer implementation consumed. Full product census 63; staged Linux paths 34; module inputs 57.

## Actual build and modpost

Hosted GCC 13.3.0 (Ubuntu 13.3.0-6ubuntu2~24.04.1), GNU ld 2.42. Actual ELF and OpenSSL compile/link/probe prerequisites PASS. Generated configuration: x86_64 64BIT SMP TREE_RCU NR_CPUS=4, SWAP/ZSWAP/MD/BLK_DEV_DM built-in, MODULES=y, isolated MM carrier test enabled; ZSWAP default-on and shrinker default-on disabled, MODVERSIONS disabled. Exact common guard set and absolute command arguments retained in private CI results.json. Reproduction from sibling exact checkouts in the dedicated workflow:

```sh
python3 -B swapz/tests/tools/round105-connected-build-verify.py frozen historical baseline linux r105-build r105-a10-evidence
```

Actual preflight module composite compiled; real source GPL-import audit passed. Full kernel link and kernel MODPOST passed; external module MODPOST consumed the same full kernel output. Bounded actual log excerpts:

```text
R098_PASS full-kernel-link
R098_BEGIN external-module-modpost-link
R098_PASS external-module-modpost-link
R105_A10_CONNECTED_COMPILE_LINK_PASS AUTH0 NO_RUNTIME
```

Kernel log: MODPOST Module.symvers; LD vmlinux.unstripped; OBJCOPY vmlinux. External log: MODPOST Module.symvers; CC [M] dm-swapz.mod.o; CC [M] .module-common.o; LD [M] dm-swapz.ko. No warning lines in either link log and no verified first error. No fabricated symbol table, suppression, stale objects or prior object archive. Actual elapsed 167.184 seconds; child user 254.896146 s, system 44.684916 s, maximum child RSS 186820 KiB (not aggregate peak).

## Downloaded evidence verified independently

[Artifact 15183260293](https://github.com/k1moradi/swapz/actions/runs/45965476047/artifacts/15183260293) — 3740239 bytes, ZIP SHA-256 `b079c5c6eae1e06a4f3e3de8f09bb5e9645053b6b54fbdd250f058984b09b3ed`, matches GitHub digest; every entry passes ZIP CRC. Independently checked byte lengths, SHA-256 and Git blob hashes of both binaries, Module.symvers and effective.config against actual CI results. Local readelf/nm analysis, not binary execution or module loading.

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| vmlinux | 12862816 | `bbbec10f3cd422f9ec3b33fddd856c2a4912ea49d9d055675ea40dc5ff41d284` |
| dm-swapz.ko | 470104 | `892ed64cb9a45c565107c63fdd8da9f07cb6ea77b0f3b31e5f0d53e37b325325` |
| kernel-Module.symvers | 221424 | `c9f048da609f2abce24da695cc9a3a0d001906013316925f179bfee5c99b511d` |
| effective.config | 46577 | `f9bbfa2580fb2bb6a1d95316e0dff1f9f64d1656dc9d8974abcc4f9bc95db8cf` |

Actual vmlinux x86-64 EXEC, zero strong undefined symbols; actual dm-swapz.ko x86-64 REL, 125 strong imports all resolved in the 4040-row kernel Module.symvers. All 27 private imports are GPL exports from vmlinux. Exact-query definition occurs once in vmlinux, one actual module relocation, export row `0x00000000 swapz_mm_trial_scope_matches_exact vmlinux EXPORT_SYMBOL_GPL`. GPL license, no module dependencies, vermagic `7.3.0+ SMP preempt`, frozen source SHA and clean=1 embedded. Independent readelf verifies module metadata. Source and config post-build pins checked by hosted verifier. Archive results.json SHA-256 `81854e8b530e713b93a97375485bd4096f16e08df72c7db0cf9246a6ef9b0e9c`; historical unified-base manifest `78bcc288135a417cdcc28772895f9dfd8ed29ed1f8e41f712894e288e084d475`; connected-source.diff `ebf476c231abcc6f922ca61cf85ad054a3a257143c2eaa785541b715cc3dd6d0`. Complete staged manifests, guard flags, config, symbol tables and relocations are in the linked artifact.

## Boundaries

Prior local GitHub DNS blocker (exit 128) bypassed using authorized hosted Linux checkout, not a credential workaround or fake local source. No local compilation repeated; independent binary inspection only. This is a compile/link checkpoint of frozen R104 plus A1's exact repair, NOT the final R105 composition, host-boot-compatible candidate, runtime qualification, trusted admission, successful lifetime retirement, byte-contract or physical proof. No new full build this round. No VM/boot/install/load/activation/device I/O/physical mutation. AUTH=0, Phase A BLOCKED, compressed handoff/forced RAW/import OFF. Agent 1 reviews and integrates separately.
