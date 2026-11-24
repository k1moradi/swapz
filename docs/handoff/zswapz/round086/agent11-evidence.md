# Round086 Agent11 — actual disabled broker kernel adapter

**QUEUED — implementation and exact-source focused workflow published; native qualification not yet executed/confirmed.** [Assignment](https://github.com/k1moradi/swapz/commit/7732ea3eb7defb8112a87ead4b578dbe61c453ab), sole parent `d77ef98bc218ffd260b7114ffcb32c411d66bb31`. [Source/test commit](https://github.com/k1moradi/swapz/commit/87eb611ed091979541e6754369af8976131f2e64), sole parent `70a9a3478290004ea6d93f7469df3afbce006ba6`. [Run 45447861121](https://github.com/k1moradi/swapz/actions/runs/45447861121), [job 138636485096](https://github.com/k1moradi/swapz/actions/runs/45447861121/job/138636485096), queued at observation. First CI error: none reported. Confirmed builds/boots/cases: 0/0/0; actual native verdict/counts pending. No local native execution claimed.

## Implemented qualification

No product C/H changes: prior broker and codec blobs unchanged (R084 host GCC32/Clang32 success is historical, not repeated). Actual byte-exact broker/CRC C/H staged into an isolated pinned original Linux checkout under lib/kunit/swapz-round086, with only opt-in KUnit Makefile/Kconfig additions in that checkout. No external Linux publication, no normal product Kbuild, no production DM route. Select test-only KUnit config, SMP and two virtual CPUs, DEBUG_SPINLOCK, DEBUG_ATOMIC_SLEEP and CRC32; swap disabled. Pinned UP debug implementation explicitly diagnoses failed spin_trylock as a bug, so a UP debug contention test would be invalid. This uses the actual SMP spin_trylock_irqsave adapter and deliberately held own broker lock, not a mock or a foreign lock. All checks/reporting occur after unlocking. A separate ordered IPI retain/last-put test targets the other online CPU with synchronous completion before storage destruction. It is not a probabilistic concurrency stress test or proof of concurrent destruction. No allocator or callback API in the broker lock paths; exact copy/CRC unlock/relock boundary independently checked. Native debug checks remain pending.

Six directed actual API cases:
- `r086_capacity`
- `r086_irq_and_contention`
- `r086_seal_claim`
- `r086_revoke_close`
- `r086_generation_refs`
- `r086_copy_failures`

Capacity covers both M3568/4095, separate count and logical-byte credits, physical stride and actual native sizeof. IRQ success/failure and preemption restoration includes contention refusal and disabled-IRQ caller success. Seal/claim tests exact CRC32C standard vector, immutable copy, typed identity, duplicate claim, ref ownership. Revoke/close checks charged held remote lease, failed late retain/reserve, and final remote put before destroy. Generation/refs checks stale reuse, output preservation, ref/generation exhaustion. Failure cases verify invalid profile/raw4096, short copy, CRC error and cancellation. Test-created bytes/keys do not prove selected source.

## Exact stage/build gate

Connector preflight checked immutable task parent, 17 original and seven product blob metadata, two exact tail anchors, exact unlocked copy/CRC sequence, absence of named alloc/sleep APIs, six registrations and fixture whitespace. Standards prior text re-created to identical blob before append; verified source parent and three exclusive added test files plus five appended standards lines, zero deletions. Hosted preflight verifies exact main SHA/event parent, clean tracked/untracked checkout, diff whitespace and canonical policy; original/product full byte hashes, six negative stage plans, eight exact postimages and no unrelated tracked/untracked changes. Only then one rootless UML build and one filtered boot; verify actual linked kernel symbols, effective config, kernel SHA256, exact six genuine JSON/KTAP PASS and no skipped/failed/crashed/errors or kernel warnings. Build/config/KTAP/first-error evidence retained by workflow. Build prerequisites are checked on hosted runner without privileged dependency installation; if unavailable the job fails closed. No native pass or kernel allocation size claimed yet.

## Immutable original pins

Linux `c339f4010dea8b0d754f84ace70cd1b089878ef8`:
- lib/kunit/Makefile `204e02b10eba1030c6d511991fe2f6271de64603`
- lib/kunit/Kconfig `cbda6189a308a0b159f63b7c1933456c9427e39e`
- include/linux/crc32c.h `b8cff2f4309a70efb6521491438dce0be19e0d74`
- include/linux/crc32.h `da78b215ff2e9365188cf6318c111163c0c7af32`
- include/linux/spinlock.h `3d405cc4c1218c188b8cbaab24736ac7a8819ef6`
- include/linux/spinlock_up.h `3a50976471d7118ac66b3f3594329c1e96545dac`
- include/linux/spinlock_api_smp.h `90909d933dab7c6654546ac2a6bc1f6bee2feac1`
- kernel/locking/spinlock_debug.c `2338b3adfb55ffd806dedadc4fef20b1f1ee7e63`
- arch/um/Kconfig `7245e3ada1c5a7e8f3f23cb28dece946172e4361`
- arch/x86/um/Kconfig `44b12e45f9a058bb06d2c628168d21e961aa3943`
- arch/um/kernel/smp.c `92ea1beaed8b21d6a7ad45008dc240004bb65ee3`
- arch/um/include/asm/irqflags.h `31e49e0894c5e7ccf842ae81f9bfbe0af5958f49`
- include/linux/irqflags.h `57b074e0cfbbb3ac2a1384ead68c2f074e4c9a2a`
- lib/Kconfig.debug `2d22638ec13a63364d0f41d1086027ed48d320e0`
- lib/crc/Kconfig `927fc6a6b2b9d32fc78bf6f21d113c78c53894ab`
- tools/testing/kunit/kunit.py `91d234ac3b579260a33557955ecf7979c8439d01`
- tools/testing/kunit/kunit_json.py `80fa4e354a17afde99c92666a71b0c7ca237a594`

Product:
- src/kernel/zswap-original-ticket.c `dcea7cbc40094fed2997d6704c712ac47aa164a1`
- src/kernel/zswap-original-ticket.h `b772cc28755a68719f4dcdabefeefe57b5efea67`
- src/kernel/codec.c `d920dcaac6f2b7de1334d4133770bd649719c66d`
- src/kernel/codec.h `e89d316b9cf49f82df0b77648c1be1731607987d`
- src/kernel/authority.h `3bb5bab5a5bdb2aa087f5793fc8b5e90d6636031`
- src/kernel/dm-target.c `f1cab252cd990190646c82da81378d1563475826`
- src/kernel/Makefile `ed6e19ae28a84a4a3e92117812adc445d5c2e8e5`

New test files:
- [tests/runtime/native/fixtures/round086-original-ticket-kunit.c](https://github.com/k1moradi/swapz/blob/87eb611ed091979541e6754369af8976131f2e64/tests/runtime/native/fixtures/round086-original-ticket-kunit.c) `90da2e570cc9177c8a674a47bbd404690b2578c7`
- [tests/tools/round086-original-ticket-kernel-verify.py](https://github.com/k1moradi/swapz/blob/87eb611ed091979541e6754369af8976131f2e64/tests/tools/round086-original-ticket-kernel-verify.py) `ba10fbe434334086083642eef6b0dafcecff1d00`
- [.github/workflows/phase-a-round086-original-ticket-kernel-noauth.yml](https://github.com/k1moradi/swapz/blob/87eb611ed091979541e6754369af8976131f2e64/.github/workflows/phase-a-round086-original-ticket-kernel-noauth.yml) `7e054894dc0accfeba4d65eadfc2cf9184d984b5`

Standards previous `f4a096e74fbd45e38b614e7c2af2e6b0fba86f09`, appended `8a4074ced01c8d9088b5f40d383ba73496105f20`.

## Limits and next gate

Historical R084 host evidence preserved. The six registered cases and successful connector checks are not actual executed KUnit results; exact hosted job is queued. One focused lane triggered automatically, eight unrelated existing lanes observed; no manual dispatch, cancellation, monitoring or repeated build. No same-round peer dependency. Kernel adapter unqualified until actual native results; selected DM lock order and atomic claim/enqueue, real carrier lifetime/quiescence, real lower durability/upper ACK, full integration remain unproven. No foreign-lock relaxation, production BIO cap, reclaim/recompression, physical testing, swapon or production activation. Ordinary RAW_4096 remains full original uncompressed 4096; exact20B map untouched. SOURCE_MAPPED_AUTHENTICATED=0, PHASE_A=BLOCKED, direct/forced RAW/import OFF.
