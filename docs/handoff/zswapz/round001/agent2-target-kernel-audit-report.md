# Round 001 — Agent 2 target-kernel-audit report (archived GitHub submission)

- **Original GitHub report:** https://github.com/k1moradi/swapz/issues/118#issuecomment-6892178273
- **Task commit:** `b6817ac41f96a0e7df4b0f5f3af258e582723b9e`
- **Frozen source baseline:** `c128ac32374a753a0b27ae0ebec67693355b1b55`
- **Agent-stated task outcome:** PASS (source-review only)
- **Original issue-comment body SHA-256:** `3e70a267ff4c1c1d747296a29ee853b4c9c5e6b1ef2a579b91235d79f39fc13f` (UTF-8, excluding archival wrapper)
- **Archival date:** 2026-11-15 UTC
- **Evidence boundary:** Reporter results below are attributed to the agent, not independently rerun or Phase A kernel qualification.

---

message: REPORT_READY
round: "001"
agent: 2
task_id: agent2-target-kernel-audit
status: PASS
source_sha: c128ac32374a753a0b27ae0ebec67693355b1b55
task_commit_sha: b6817ac41f96a0e7df4b0f5f3af258e582723b9e
modified_files: []
tests:
  - command: "Read-only exact-ref GitHub source-anchor audit (9 file/revision groups; all required anchors present)"
    exit_code: 0
  - command: "bash -lc 'uname -r; uname -m; gcc -dumpfullversion -dumpversion; test -f /lib/modules/$(uname -r)/build/include/config/kernel.release || true; inspect locally available /lib/modules/*/build and pinned-source/Module.symvers presence'"
    exit_code: 0
  - command: "git apply --check against a complete c339f4010dea8b0d754f84ace70cd1b089878ef8 Linux checkout"
    exit_code: NOT_RUN
  - command: "real Linux Kbuild W=1/W=2, CONFIG_ZSWAP=y/n, matched swapz module and loaded origin tests"
    exit_code: NOT_RUN
evidence_class: source-review
blocking_findings:
  - "No exact authorized owner-test host running kernel, distro source commit, kernel .config, matching build tree/Module.symvers or booted image identity was supplied."
  - "The proposed six-file producer targets Linux 7.3-development source, not the previously observed Ubuntu 7.0.0-43-generic compile-only headers."
  - "Current proposed inline bi_swap_origin interface does not authenticate a running kernel with patched struct bio layout; A5-ABI remains blocked."
  - "No full-kernel Kbuild, linked producer/consumer, kernel BIO clone/split test or genuine zswap eviction evidence."
next_round_recommendations:
  - "Agent 1 obtains owner-test host kernel/source/config/build/symvers/architecture/PAGE_SIZE/image identity and selects the real integration target explicitly."
  - "Agent 2 ports or builds against that exact kernel, or uses c339f4010dea8b0d754f84ace70cd1b089878ef8 strictly as a source-level prototype if no host is selected."
  - "Agents 2/5 review a fail-closed runtime carrier guard and prove BIO init/reset/merge/clone/split/reissue; Agent 8 independently qualifies paired kernel/module."

# Agent 2 — Round 001 target-kernel/source/config audit

**Task verdict: PASS (source-review task only); Phase A remains BLOCKED; Phase B remains DEFERRED.** I completed the independently executable source/version comparison and supplied a conditional recommendation. This is **not** approval of a kernel image, compiled producer/BIO interface, boot, or the Phase A end-to-end contract. All work was read-only; I did not create branches, PRs, worktrees, source commits, mapper changes, module insertions or swap/device operations.

## Immutable inputs and observed environment

- Frozen swapz source: [`c128ac32374a753a0b27ae0ebec67693355b1b55`](https://github.com/k1moradi/swapz/tree/c128ac32374a753a0b27ae0ebec67693355b1b55); Round 001 task: [`b6817ac41f96a0e7df4b0f5f3af258e582723b9e`](https://github.com/k1moradi/swapz/blob/b6817ac41f96a0e7df4b0f5f3af258e582723b9e/docs/handoff/zswapz/round001/agent2-target-kernel-audit.md); [Round 001 opening](https://github.com/k1moradi/swapz/issues/118#issuecomment-6891942116).
- Historical producer proposal reviewed: [issue #116 Agent 2](https://github.com/k1moradi/swapz/issues/116#issuecomment-6890555852); prior independent caution: [issue #116 Agent 5](https://github.com/k1moradi/swapz/issues/116#issuecomment-6890759705), and [#117](https://github.com/k1moradi/swapz/issues/117). No same-round agent output was used.
- Upstream development Linux source is **`c339f4010dea8b0d754f84ace70cd1b089878ef8`**, whose [Makefile](https://github.com/torvalds/linux/blob/c339f4010dea8b0d754f84ace70cd1b089878ef8/Makefile#L2-L5) says `VERSION=7`, `PATCHLEVEL=3`, `SUBLEVEL=0`. This is a 7.3-development tree, **not a proven installed 7.3 kernel** and not Ubuntu 7.0.
- Separate *upstream comparison proxy*, tagged `v7.0`: source commit **`028ef9c96e96197026887c0f092424679298aae8`**, [tag/source](https://github.com/torvalds/linux/tree/028ef9c96e96197026887c0f092424679298aae8). The upstream tag is **not** the specific Ubuntu `7.0.0-43-generic` distribution source commit.
- The frozen [product-codec CI workflow](https://github.com/k1moradi/swapz/blob/c128ac32374a753a0b27ae0ebec67693355b1b55/.github/workflows/product-codec.yml#L67-L79) installs rolling `linux-headers-generic-hwe-24.04` and selects the highest installed generic header. Prior successful compile logs observed `7.0.0-43-generic`; the workflow does not pin that release for future runs. Its `W=1`, `W=2` and normal module compiles are **compile-only**, with no producer patch, load or runtime layout verification; cf. [docs/compile.md](https://github.com/k1moradi/swapz/blob/c128ac32374a753a0b27ae0ebec67693355b1b55/docs/compile.md).
- Read-only execution sandbox: `uname -r=6.18.57`, `uname -m=x86_64`, GCC `14.2.0`. The only listed kernel build-header link was `/lib/modules/6.12.107+deb13-amd64/build`; no headers matched `uname -r`. A full exact-`c339f4010dea8b0d754f84ace70cd1b089878ef8` Linux tree, `.config`, `Module.symvers` and exact kernel image were not available. This sandbox is **not the owner host**.

## Compatibility ranking (not a runtime selection)

| Choice | Exact known source / release | Host/source/config/Kbuild/ABI evidence | Decision and relative risk |
|---|---|---|---|
| **1 — owner-host exact kernel, once identified** | Full git/distro source SHA **UNKNOWN**; actual `UTS_RELEASE`, `.config`, kernel image identity, headers, generated headers, `Module.symvers`, toolchain, arch and page size **UNKNOWN** | No matching owner-host inventory provided; production image/source may be downstream patched | **Preferred eventual real test target only after identity and owner-qualification gates.** If it is v7.0-like, port producer to its actual direct-BIO path; do not select by guessed release. |
| **2 — pinned upstream development prototype** | `c339f4010dea8b0d754f84ace70cd1b089878ef8` (Makefile 7.3.0 development), complete source **remotely audited** | Patch has source-anchor/synthetic replay evidence from prior report only. No local full source/config/symvers, built image, matched module, authorized boot or runtime ABI proof | **Least producer-port churn for an isolated source prototype** because the preexisting six-file diff targets this exact tree. **Not** a boot-qualified integration kernel. |
| **3 — Ubuntu generic stock compile/fallback** | Prior CI header `7.0.0-43-generic`; distribution source commit and exact config **UNKNOWN**; rolling HWE selection may change | Existing swapz module compile-only W=1/W=2; custom zswap-origin API absent, and producer patch was not built here | **Valid fallback smoke only**: default origin UNKNOWN, unchanged codec. Positive-origin integration needs a separately reviewed **actual Ubuntu source port**, rebuilt kernel and matching module; upstream `v7.0` is merely a comparison proxy. |
| **4 — local sandbox** | Running 6.18.57, x86_64; available headers 6.12.107+deb13-amd64 | Running/header mismatch; no full exact producer kernel; toolchain GCC 14.2.0 | **Not a valid full-Kbuild or loaded qualification target.** No build was attempted. |

In every row **CONFIG_SWAP**, **CONFIG_ZSWAP**, **CONFIG_BLK_DEV_DM**, page size (must be 4096 for current swapz acceptance), effective architecture, compiler/config version, `Module.symvers`, `UTS_RELEASE`, `vermagic` and cryptographic image/module identities require **the exact chosen image and build artifacts**. The upstream Makefile version or a CI header package name does not supply these fields.

## Exact version-sensitive source findings

### A. Linux `c339f4010dea8b0d754f84ace70cd1b089878ef8` (proposed six-file carrier)

1. [`mm/zswap.c:1005–1086`](https://github.com/torvalds/linux/blob/c339f4010dea8b0d754f84ace70cd1b089878ef8/mm/zswap.c#L1005-L1086), blob `ae19e301fced7e357a4c7587dfdd6abb890b9163`: `zswap_writeback_entry()` has `struct swap_io_ctx ctx = {}`; tests `entry == xa_load(tree, offset)` around line 1048, successfully decompresses at 1053, frees the zswap entry, then uses `folio_set_dropbehind()` and `__swap_writeout(&ctx, folio); swap_write_submit(&ctx)` at 1085–86. The prior Agent 2 patch proposes setting the positive scalar **after** those validity/decompression checks and before `__swap_writeout`, not on `zswap_store()` rejection. The tag identifies reconstructed full-page bytes, not compressed zswap payload.
2. [`include/linux/swap_ops.h:7–20`](https://github.com/torvalds/linux/blob/c339f4010dea8b0d754f84ace70cd1b089878ef8/include/linux/swap_ops.h#L7-L20), blob `57ac6c703f685883d3a15ebc1a5c7f6c298deb1b`: defines `swap_iocb` and `swap_io_ctx`; these carry the proposed context/per-aggregation scalar. [`mm/page_io.c:325–370`](https://github.com/torvalds/linux/blob/c339f4010dea8b0d754f84ace70cd1b089878ef8/mm/page_io.c#L325-L370), blob `c6824fcd483e0aa2c412e14dae0d2a356b17c373`: `swap_can_merge()` currently checks swap-info identity/ops only; the proposed **additional write-origin homogeneity comparison** must force a submit before merging opposite origins. The freshly mempool-allocated `swap_iocb` must initialize its scalar on every allocation/reuse.
3. [`mm/page_io.c:596–624`](https://github.com/torvalds/linux/blob/c339f4010dea8b0d754f84ace70cd1b089878ef8/mm/page_io.c#L596-L624): `swap_bdev_submit_write()` initializes the owned BIO with `REQ_OP_WRITE | REQ_SWAP`, and the patch proposes copying the homogeneous `swap_iocb` origin to the BIO after `bio_init()`. `REQ_SWAP` alone never establishes an authenticated provenance.
4. [`include/linux/blk_types.h:210–294`](https://github.com/torvalds/linux/blob/c339f4010dea8b0d754f84ace70cd1b089878ef8/include/linux/blk_types.h#L210-L294), blob `0cc09b975d8ffbd45ca3dc47533a71f8e8164de6`: `struct bio` has the proposed insertion site after `bi_bvec_gap_bit` (around 231); `BIO_RESET_BYTES = offsetof(struct bio, bi_max_vecs)` at 294. [`block/bio.c:217–279,876–918`](https://github.com/torvalds/linux/blob/c339f4010dea8b0d754f84ace70cd1b089878ef8/block/bio.c#L217-L279), blob `b0fcc69de653524479e3b328aa29a37e97945b84`: the patch must initialize `bi_swap_origin=0` in `bio_init`, have `bio_reset` clear it, and explicitly copy it in `__bio_clone`. `bio_alloc_clone`, `bio_split`, and the [DM `alloc_io` / `alloc_tio` sites](https://github.com/torvalds/linux/blob/c339f4010dea8b0d754f84ace70cd1b089878ef8/drivers/md/dm.c#L565-L640) (DM blob `1881d86111fb2e655893ad898cf21b88f0e4e7f3`) can then preserve it **provided** the actual patched kernel paths are compiled and tested.
5. The proposed `include/linux/bio.h` capability macro and inline `bio_is_zswap_stored_writeback()` check request operation WRITE, `REQ_SWAP`, and exact origin 1; they are **not stock ABI**. **A5-ABI blocker:** patched headers paired with an unpatched same-release running kernel can cause the inline out-of-tree consumer to read a field the kernel never initialized. `vermagic`/macro/struct-size coincidence alone cannot guarantee the booted layout. Require exact image/source/config identity **or** an intentionally exported, kernel-resolved helper/capability that prevents loading into a kernel lacking that ABI. The helper is a *candidate mitigation*, **not present in or approved by the six-file original patch**.

### B. Upstream `v7.0` proxy (not Ubuntu distro source)

1. [`mm/zswap.c:994–1064`](https://github.com/torvalds/linux/blob/028ef9c96e96197026887c0f092424679298aae8/mm/zswap.c#L994-L1064), blob `16b2ef7223e12a580cde128d1c66bb673ea5248e`: source still authenticates entry equality and successful decompression, but uses `folio_set_reclaim()` then `__swap_writepage(folio, NULL)`, not `swap_io_ctx`/dropbehind/`__swap_writeout`.
2. [`mm/page_io.c:410–470`](https://github.com/torvalds/linux/blob/028ef9c96e96197026887c0f092424679298aae8/mm/page_io.c#L410-L470), blob `a2c034660c805ffb715e89979dc51af38d1179c3`: sync path constructs a stack BIO with `bio_init(&bio, ..., REQ_OP_WRITE|REQ_SWAP)`; async path uses `bio_alloc(..., REQ_OP_WRITE|REQ_SWAP)`, both per backing folio. The file-local `struct swap_iocb` around line 325 serves filesystem swap; the modern `include/linux/swap_ops.h` file is absent at this tag. This is a **real control-flow/API difference**: the six-file newer-context patch cannot be mechanically assumed to apply to `v7.0` or Ubuntu 7.0.
3. [`block/bio.c:870–920`](https://github.com/torvalds/linux/blob/028ef9c96e96197026887c0f092424679298aae8/block/bio.c#L870-L920), blob `d80d5d26804e32944bcfe4506ca190033308844f`, has its own `__bio_clone` and clone semantics; its copy path must be reviewed/ported explicitly. Whole-BIO origin homogeneity is simpler for a one-folio direct BIO, **but a larger folio, block split or DM clone still requires 4KiB-correct provenance**. Distro changes must be re-audited.

### C. What cannot be authenticated from existing evidence

The upstream development and tagged-v7.0 files have authenticated Git blobs, **not** a matching `.config` or runnable built kernel. The Ubuntu generic header is a build-input observation without a full Ubuntu source revision, running kernel image or an origin-bearing patch. The owner-host kernel and its source, loaded-module identity and supported 4KiB PAGE_SIZE are unknown. There is no reason to assert compatibility merely because both source families have a `struct bio` or share `REQ_SWAP`.

## Tests and explicit non-tests

**PASS — read-only source audit:** a programmatic `fetch_file` anchor check queried **nine exact kernel file/revision groups**: development `mm/zswap.c`, `mm/page_io.c`, `include/linux/swap_ops.h`, `block/bio.c`, `include/linux/blk_types.h`, `drivers/md/dm.c`; upstream `v7.0` `mm/zswap.c`, `mm/page_io.c`, `block/bio.c`. All required named functions and control-flow anchors were found (and their 1-based source line positions recorded in this report). This is a **source-review assertion**, not compiled code or synthetic hunk application.

**PASS — sandbox inventory only:** a read-only shell command returned success and found running kernel 6.18.57, GCC 14.2.0, x86_64, **no matching running-kernel header build tree** and no exact upstream development Linux source/config/symvers. A separate `/lib/modules/6.12.107+deb13-amd64/build` link exists but is incompatible with the running release and with the target source.

**NOT_RUN / BLOCKED — real qualification:** no full exact Linux checkout to execute `git apply --check` against; no `CONFIG_ZSWAP=y/n` generated configs or `Module.symvers`; no real W=1/W=2 kernel build, swapz out-of-tree Kbuild against that built kernel, CFI/modversions/layout check, KUnit split/clone/requeue test, loaded positive/negative provenance test, owned-null_blk stored-entry eviction, byte-exact swap readback, or physical tests. Historical Agent 2 synthetic 18/18 source checks and isolated patch replays in [#116](https://github.com/k1moradi/swapz/issues/116#issuecomment-6890555852) remain **historical fixture evidence only**, not rerun here.

## Recommended Agent 1 decision request for Round 002

**Separate two decisions; do not conflate them.**

**D2.1 — source prototype:** If the objective is to minimize review churn **without claiming a runnable target**, keep the already-audited `c339f4010dea8b0d754f84ace70cd1b089878ef8` as the **conditional standalone source-prototype base**. Its original six-file patch and `swap_io_ctx` transport are version-specific. Agent 2 can then apply/recheck the complete patch on the full exact tree, perform actual kernel builds, and add a fail-closed ABI guard. This is not approval to boot a development tree.

**D2.2 — genuine owner-test integration kernel (still BLOCKED):** Obtain a safe **read-only** owner-host build inventory, with private device/host identities kept out of issue comments: full distro kernel source git/package commit and patchset; actual `uname -r`/`UTS_RELEASE`, arch, kernel page size, `CONFIG_SWAP`, `CONFIG_ZSWAP`, `CONFIG_BLK_DEV_DM`, relevant preempt/THP/BLK_CGROUP configs, generated headers, `Module.symvers`, compiler+tool versions, kernel image digest/source build-id, running image equality, module build inputs/vermagic and module hash; confirm an owner-qualified, test-only 4KiB kernel environment. If such a stable source cannot be obtained, report **HOST_TARGET_UNSELECTED** and qualify only a separately authorized isolated patched-kernel prototype. Do not substitute the runner's Ubuntu 7.0 header for an owner-host kernel.

**Later gates on the selected exact kernel (not Round 001 tasks):**
1. Verify source patch with `git apply --check`, `git diff --check`, source/config identity and full Kbuild `CONFIG_ZSWAP=y` and `n`, W=1/W=2, x86_64/ARM64 only if actually supported; record `sizeof(struct bio)`, scalar offsets and `Module.symvers` compatibility. Do not pretend `modules_prepare` supplies the missing symbol-version table for `CONFIG_MODVERSIONS`.
2. Prove ordinary and verified class in **both merge orders**, null/malformed origin, multiple bvec/large folio, `bio_init`, `bio_reset`, `__bio_clone`, `bio_alloc_clone`, `bio_split`, block split, DM `alloc_io/alloc_tio`, requeue and source-BIO completion/reuse; test an intentional **patched-header / unpatched-running-kernel** mismatch for fail-closed behavior.
3. Build Agent 3's **passive default-unknown** consumer against **the same patched headers/source and booted kernel**, separately confirm stock fallback, and never let origin choose RAW or suppress LZ4/delta64 in Phase A.
4. On a separately qualified owner-authorized RAM-backed test mapper only, prove actual zswap stored-entry eviction/decompression -> homogeneous BIO -> 4KiB swapz admission -> **successful authoritative foreground commit** -> byte-exact readback; correlate source/mapper counters instead of using global `zswpwb` as mapper proof. Agent 5 independently reviews provenance/mismatch and Agent 8 retains the qualification veto.

**End state:** The kernel options and porting boundary are now source-pinned and reviewable, but **no real test kernel has been selected or qualified**. No Phase B bypass or host/storage action was performed.
