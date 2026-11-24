# Round087 Agent11 — rootless actual SMP broker QEMU TCG correction

**IN_PROGRESS — actual corrective source published; hosted QEMU preflight and native qualification pending.** [Assignment](https://github.com/k1moradi/swapz/commit/9924c6a88e7f2dcce2b729d4d9263703dd92139f), sole parent `4b4b22358aa061c207c85b0162f64246597b3ca3`. [Source/test commit](https://github.com/k1moradi/swapz/commit/67a036d89a1a7412a27f9450df549347146e758f), sole parent `034274ddecf1c0f62b06459b014a7d4456752e52`. [Run 45455624750](https://github.com/k1moradi/swapz/actions/runs/45455624750), [job 138664150782](https://github.com/k1moradi/swapz/actions/runs/45455624750/job/138664150782), in progress at observation. Exact-main source and canonical standards step completed successfully; original checkout running. Corrected first CI error: none reported; confirmed builds/boots/cases 0/0/0. No local native execution or QEMU availability claimed.

## Historical failure (preserved, not rerun)

R086 exact [source 87eb611ed091979541e6754369af8976131f2e64](https://github.com/k1moradi/swapz/commit/87eb611ed091979541e6754369af8976131f2e64), [failed job](https://github.com/k1moradi/swapz/actions/runs/45447861121/job/138636485096), [artifact 14947585659](https://github.com/k1moradi/swapz/actions/runs/45447861121/artifacts/14947585659). Rechecked job log: actual stage and 6 negative plans PASS, actual broker/CRC/six symbols built, kernel SHA256 `6ad838ec6b13787abd17078c2f02e274fecbbbc5d5d70e8a9ec6f5b31b73c5e6`, phase=boot exit=1. Agent1 inspected raw retained artifact and recorded first actual error: **SMP is not supported with PTRACE userspace.** No KTAP, zero cases, one error. This agent rechecked artifact metadata/digest `sha256:d617e19b571f1c1c8e7e3565fe20c4b14fbd162f869f888ea94c53044681cbd4` and job log, did not independently unpack ZIP. Original build remains PASS, boot FAIL; no demonstrated product broker defect. Historical R084 host GCC32/Clang32 not rerun.

## Correction and qualification design

Use the pinned x86_64 KUnit QEMU configuration, not UML/PTRACE or UP. Pinned kunit_kernel.py defaults to KVM, HVF, TCG; exact unique anchor replaced only inside ephemeral original checkout with `tcg,thread=multi`, no KVM/HVF fallback. Stage now modifies three verified original scratch paths and copies six test files (nine exact postimages); eight negative plans including missing/duplicate accelerator anchor. No upstream publication or production changes. Preserve actual product broker/codec bytes, normal Kbuild/DM target/map. Rootless QMP preflight before compilation checks actual QEMU version, firmware load from /usr/share/qemu/qboot.rom, two instantiated vCPUs and KVM disabled; artifact includes firmware digest, private stdout/stderr and command. Approved disposable GitHub runner dependency provisioning only; all QEMU/kernel execution unprivileged, no attached disks or networking. Fail closed if tools/firmware/TCG unavailable. Local container has no QEMU executable and GitHub DNS fails; no local build/boot or full verifier execution claimed.

One corrected x86_64 build, effective SMP/NR_CPUS2/debug spinlock/debug atomic sleep/CRC config with SWAP/ZSWAP disabled; verify actual vmlinux broker/CRC/case symbols and bzImage/vmlinux/config hashes, one filtered native boot, exact logged TCG-only command. No duplicate unchanged CI. Inherited six tests preserved; contention test strengthened to real remote IPI lock holder, release/acquire rendezvous, five-second deadlines, synchronous join before stack/fixture lifetime ends. Actual failed reserve from enabled IRQ state and failed claim from disabled IRQ state with preempt/IRQ restoration. All KUnit checks/logging occur outside held lock; remote holder does not allocate or sleep. Distinct holder/contender CPUs and actual online count required in raw KTAP, not inferred from config alone. Existing cross-CPU retained lease/revoke/last put, separate count/byte credits, both ceilings, immutable CRC/claim, ABA/overflow/cancel cases retained.

Cases:
- `r086_capacity`
- `r086_irq_and_contention`
- `r086_seal_claim`
- `r086_revoke_close`
- `r086_generation_refs`
- `r086_copy_failures`

Seven rootless diagnostic extraction regressions run before build (pending): actual PTRACE refusal over generic no-KTAP, generic no KTAP, real named KUnit not-ok, first raw lock/BUG precedence, missing diagnostic with exit, bounded path redaction, firmware preflight marker. Retain raw log even without KTAP and emit bounded first meaningful cause/exit. First publication-script syntax error corrected before ref update; not a CI failure. Actual remote execution of all gates, QEMU preflight, native JSON/KTAP and sizes pending.

## Immutable original and product pins

Original Linux `c339f4010dea8b0d754f84ace70cd1b089878ef8`; whole Git blob verification required in CI:
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
- tools/testing/kunit/qemu_configs/x86_64.py `4a6bf4e048f5b05c889e3b9b03046f14cc9b0bcc`
- tools/testing/kunit/kunit_kernel.py `58557c47d85f696f82e165df58fa905094e45f5c`
- tools/testing/kunit/qemu_config.py `b1fba9016eed00d010c853f2910c9624e01d4af5`
- arch/x86/Kconfig `58dce0b66179b6039c4ec9cc4273194c8e382b77`
- arch/x86/kernel/smpboot.c `ba01a9e919b7840a0e625a39de0d473f222b3b64`
- arch/x86/include/asm/spinlock.h `934632b78d09c07f5337982b238db138c640738b`
- arch/x86/include/asm/irqflags.h `6f25de05ed58f59ba022f94146fa3ac2fedf49fc`
- arch/x86/include/asm/qspinlock.h `25a1919542d9d5222f44befffd08ed03d508b83d`
- kernel/smp.c `89a30d831ef5320561c676a4e69018d42d02eebb`
- include/linux/timekeeping.h `efa9442aaeef44a3b7ff88f247f616419b243553`
- include/linux/ktime.h `f247e564602fcc0614d8f1cf08e340dfa280c381`

Product and fixture:
- src/kernel/zswap-original-ticket.c `dcea7cbc40094fed2997d6704c712ac47aa164a1`
- src/kernel/zswap-original-ticket.h `b772cc28755a68719f4dcdabefeefe57b5efea67`
- src/kernel/codec.c `d920dcaac6f2b7de1334d4133770bd649719c66d`
- src/kernel/codec.h `e89d316b9cf49f82df0b77648c1be1731607987d`
- src/kernel/authority.h `3bb5bab5a5bdb2aa087f5793fc8b5e90d6636031`
- src/kernel/dm-target.c `f1cab252cd990190646c82da81378d1563475826`
- src/kernel/Makefile `ed6e19ae28a84a4a3e92117812adc445d5c2e8e5`
- tests/runtime/native/fixtures/round086-original-ticket-kunit.c `bdfb9fa138ba7acf2e20d8b49950b669da0e6e55`

Corrective test files:
- [tests/runtime/native/fixtures/round086-original-ticket-kunit.c](https://github.com/k1moradi/swapz/blob/67a036d89a1a7412a27f9450df549347146e758f/tests/runtime/native/fixtures/round086-original-ticket-kunit.c) `bdfb9fa138ba7acf2e20d8b49950b669da0e6e55`
- [tests/tools/round086-original-ticket-kernel-verify.py](https://github.com/k1moradi/swapz/blob/67a036d89a1a7412a27f9450df549347146e758f/tests/tools/round086-original-ticket-kernel-verify.py) `7952a8695c1971da3019d36fb707dd9cb3851703`
- [.github/workflows/phase-a-round086-original-ticket-kernel-noauth.yml](https://github.com/k1moradi/swapz/blob/67a036d89a1a7412a27f9450df549347146e758f/.github/workflows/phase-a-round086-original-ticket-kernel-noauth.yml) `1253bf79262e85d045e183b3eb3ba8c1f8c7fa0e`

Same-commit standards exact prefix verified, previous `5ee4b0e3eaf6272e910e6f3ded3750ac2db12860`, appended `c795cae6fd7c0f52bdecae7f1dc796b3a2f7ed64`. Verified sole parent and exact changed paths; eight automatic workflows observed at first census; only one corrected focused lane, no manual reruns/cancel/monitoring. No Agent7 dependency.

## Limits

No native PASS until real six-case JSON/KTAP, actual online CPUs/command/config and no lock warning. No actual selected-DM claim/enqueue, foreign lock-order proof, lower durability or real upper ACK. No production C/H/Kbuild change, no physical testing or privileged host swap, no production BIO cap, no extra reclaim. Ordinary RAW_4096 means full original uncompressed page, ordinary 3568 and exact20B map unchanged. AUTH0 PhaseA BLOCKED direct compressed handoff/forced RAW bypass/import OFF.
