# Round069 Agent4 — original UML decoder Kconfig and native-owner P0

Official Round069 #186 / ROUND_OPEN comment 7082028898; frozen source documentation 111a833fc05e08bac259b4470504eeea9d8e9adb; inherited engineering f98d00a8fa95ee2bb9df3270bf6262d5d6b040e0.

## Inherited original failure, NOT native lifetime PASS

Exact prior workflow https://github.com/k1moradi/swapz/actions/runs/45028541067 source-host job137226795249 SUCCESS: strict actual owner C GCC+Clang ASan/UBSan four baselines, 22 genuinely compiled/executed semantic C mutants and eight structural verifier negatives. The pinned genuine-original UML job137228196276 terminal FAILED after original lib/Makefile pin and all eight staged source postimages passed, BEFORE original C compilation, Linux UML boot or ANY of the four KUnit cases. First actual error was: ERROR:root:Not all Kconfig options selected in kunitconfig were in the generated .config. Previous workflow captured only the generic first diagnostic; the detailed Missing per-config line and private generated .config were not retained. Thus precise old failed keys are UNKNOWN FROM THAT JOB, not guessed.

## Pinned actual Kconfig dependency and exact-key control

Pinned original kernel torvalds/linux c339f4010dea8b0d754f84ace70cd1b089878ef8 and exact original Kconfig blobs:
- crypto/Kconfig 981d5dc422d4c89c743b5724aeacd6aa5120c009;
- lib/Kconfig 1e42f5167c68bc6c734ed7ad69a9eef906af54b9;
- lib/crc/Kconfig 927fc6a6b2b9d32fc78bf6f21d113c78c53894ab;
- lib/crypto/Kconfig 56f308dd027311f69959e7b3166ec9213ccb85fc;
- mm/Kconfig afff1b25b5438756f15e464f63dabdbd5ec6102c.

Original CONFIG_LZO_COMPRESS/DECOMPRESS, CONFIG_LZ4_COMPRESS/DECOMPRESS, CONFIG_CRC32 and CONFIG_CRYPTO_LIB_SHA256 are hidden library tristates, not independently selectable. Actual crypto/Kconfig defines visible CRYPTO_LZO selecting both LZO symbols, CRYPTO_LZ4 selecting both LZ4 symbols, CRYPTO_CRC32C selecting CRC32, CRYPTO_SHA256 selecting CRYPTO_LIB_SHA256. Original ZSWAP selects CRYPTO/ZSMALLOC and may select LZO via its default compressor, but does not establish LZ4/CRC32. The Round068 KUnit request directly required hidden LZ4/CRC32 without visible selectors.

New workflow performs a genuine native original UML negative Kconfig control with the EXACT original 14-line Round068 request, in an independent output directory. It must fail; a dedicated bounded parser compares actual generated .config against requested values and prints every real missing CONFIG key and effective value. THEN native positive in a separate original output tree requests CRYPTO_LZO=y, CRYPTO_LZ4=y, CRYPTO_CRC32C=y with every original KUnit/SWAP/ZSWAP, SHA and hidden codec option retained. On native failure the same comparator first emits exact CONFIG mismatch (if present) before the bounded source/build/run first compiler error and original exit. Corrected actual generated config must match all requested values. No option is silently deleted to trick KUnit. Strict existing GCC+Clang original owner C 22 compiled and executed semantic mutants remain in the exact source-host job; new config comparator self-test has ten source-options negative cases and is not described as compiled C mutants.

No production owner C/H and no original Linux zswap/DM/MM, algorithm C or authority changes. Original staging code still pins actual product dormant owner C, both original codecs, original lib/Makefile and eight SHA256 postimages. Four unchanged native KUnit cases require native kthread spinlock/wait_event/wake/close two leases, repeat 24 times, duplicate put/late get/overflow plus actual pinned Linux LZO1X/raw LZ4 full ORIGINAL 4096 bytes, product CRC32C and native SHA with test-only source-compressed buffer freed before decode. Original pinned native y/n GPL positive/absent-export modpost/omission negatives #45023772039 remain previous compile/link evidence, never substituted for native KUnit runtime.

Until new exact-source host and genuine original UML both terminal green, status PROGRESS, not REPORT_READY. Unit source pool freed as MODEL, not actual live zswap pool/tfm/module retirement. Builtin codecs don't qualify a modular provider unload, synthetic test authority flags are NOT real lower durable FUA or upper ACK; genuine source XArray slot/folio/current native DM and imported authoritative map remain unproven.

Linux MM exclusively controls compressed zswap RAM and natural pressure eviction. swapz only disk compression/packing/GC; no new reclaim. Ordinary RAW_4096 is entire ORIGINAL UNCOMPRESSED 4096 bytes; selected native LZO1X/raw LZ4 would need distinct volatile codec tag. SOURCE_MAPPED_AUTHENTICATED=0, PHASE_A=BLOCKED, ACTIVE=0, direct compressed handoff disabled, forced RAW bypass disabled. Protect SWAPSPACE2 first 4096 header/UUID/signature and parent partition table; preserve ordinary fixed20B map and data-only 4/8/16KiB. No owner Make, root, privileged, loaded, actual physical device/pressure, mkswap, swapoff or repartition.
