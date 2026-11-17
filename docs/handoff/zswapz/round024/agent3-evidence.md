# Round024 Agent 3 — actual Kbuild-compiled disabled dm-swapz ingress

Official ROUND_OPEN: https://github.com/k1moradi/swapz/issues/141#issuecomment-6933673371
Frozen contract SHA: 0f812e51b242b13229cc78f00368eff1f67085a2

The production DM file now includes the actual Round023 codec/admission C
only when SWAPZ_ROUND024_DM_IMPORT_KBUILD_PROBE is selected explicitly in
source Kbuild CI. The original #if 0 research importer remains disabled.
The new unreferenced kernel-compiled function type-checks and emits the
existing real compressed-block decoder and full original 4096 SHA256/CRC
read validator, but returns EOPNOTSUPP regardless of any mock transaction
result. No real WRITE admission, metadata, mapping, ACK, BIO payload, GC,
physical extent, kernel ABI or module option is added. It is never called
by production DM. This preserves normal source/RAW/delta/SHUF8 behavior.

Tests committed for the exact source SHA include default original C and
host GCC/Clang ASan/UBSan test plus matched external module W=1/W=2,
normal and isolated KCFLAGS opt-in Kbuild, nm identity proof. The first
actual compiler/Kbuild failure, if any, must be reported from GitHub Actions;
no local checkout or pinned Linux tree was available for module compilation
in the authoring container. **Do not interpret this evidence as an executed
local kernel build**. The source tests and true Kbuild results are qualified
only by their final exact-SHA hosted run after publication.

LOADED=NOT_RUN; LOADED_4096=NOT_RUN; PHYSICAL=NOT_RUN;
ACTIVE_COMPRESSED=DISABLED; PHASE_A=BLOCKED;
PHASE_B_FORCED_RAW_BYPASS=DISABLED; SWAPSPACE2_HEADER=UNTOUCHED.
