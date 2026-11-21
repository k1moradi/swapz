# Round057 Agent3 — original guarded clone-source retirement (NO_AUTH)

Issue #174, official ROUND_OPEN comment 7061417569, Agent1 latest checkpoint
7061875421. Frozen engineering `1c89862e5293b12401923fd092d3753c6797d1aa`;
frozen task `193f9985ecda40b014c02a4f7877fdd83803dcf4`.

## Verified ancestor and concrete missing source-owner proof

The actual original pinned `torvalds/linux@c339f4010dea8b0d754f84ace70cd1b089878ef8`
70 C KUnit cases (66 inherited + four clone cases) and GCC/Clang host original
source mutants passed terminal at the **ancestor engineering SHA only**:
[clone workflow #44892251767](https://github.com/k1moradi/swapz/actions/runs/44892251767),
original boot job 136824279717. This is not target mapping authorization.

Root-cause negative: the default-undefined original clone-ticket helper
previously retained a full-view witness on its child after original parent
`bio_uninit`, despite borrowing the parent's original bvec allocation.
Retaining a reference to the small ticket does not retain that BIO or bvec.
The narrow guarded fix keeps original BIO pointer identity comparison only,
adds atomic source liveness, clears liveness when the *original* BIO drops
its ref, rejects clone views and new propagation after retirement, and
preserves exact-once independent child ticket release. It never dereferences
retired source storage or attempts to pin original swap_iocb.

The existing four genuine C KUnit cases now assert sibling refusal after
original teardown; existing 84 host scenarios enforce the same property.
Two targeted changed-source semantic mutants test (1) skipping original-owner
retirement and (2) incorrectly ignoring the source-live flag. Host path now
executes 18 changed C mutants per compiler (existing 16 remain untouched).
Isolated rootless C11 ABI smoke: GCC and Clang strict
`-Wall -Wextra -Wconversion -Wshadow -Werror -fsanitize=address,undefined`
with no recovery, leak detection: baseline PASS and both targeted changed-C
mutants rejected by named first error, not by compiler or sanitizer crash.
This isolated smoke is **not** a full original pinned Linux CI result; the
new exact-source workflow must complete before that claim.

## Scope and explicit NO_GO

Only test-gated original clone hook/KUnit/host fixtures, owned verifier and
owned workflow changed. The original staging composer, original Agent2
pre-erase, production `src/kernel` Device Mapper, products' native BIO refusal,
codec source and active Linux MM remain unchanged. The actual native accepted
current target source ownership, safe parent bvec lifetime, table SRCU/DM
lease, selected decoder after source-pool teardown, durable lower write,
single real upper ACK and full verified 4096-byte imported read are still
missing. Ordinary RAW_4096 remains full original uncompressed bytes;
`SOURCE_MAPPED_AUTHENTICATED=0`, `PHASE_A=BLOCKED`,
`DIRECT_COMPRESSED_HANDOFF=DISABLED`, `FORCED_RAW_BYPASS=DISABLED`.
Protect entire first physical SWAPSPACE2 4096 bytes and parent table. No
owner make test/fast_test, privilege, loaded kernel, swap activation, actual
pressure or physical media trials. LZO GCC upstream sign conversion and
Clang upstream misaligned u32 UBSan remain real RED unless separately
qualified by Agent4. Agent2 original source first errors remain separate.
