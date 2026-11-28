# Round113 Agent4 — matched anonymous and file-backed tmpfs cohort preparation

[Assignment](agent4-cold-workload-p0.md) · [Binding contract](frozen-contract.md) · [Issue #231](https://github.com/k1moradi/swapz/issues/231).

## Source and scope

Frozen engineering `7f671268776eb38e9bb0d4621333af2b4660ad6d`, tree `16ed202e11d53560896b07d500fe264b0f306e89`; task `ddeae7fa5e291ae677fb7ef0e8a723567a45ff5b`. Exact frozen resource-pressure.py blob `b6532c51b7c246df54a83224296672e615b95ef8` reproduced locally and verified by git hash-object. The R112 terminal checkpoint exists at task commit, not engineering freeze; read it from task. [Source/test commit 4186cc07944bd162366d0b74931ae9a8b0e71f75](https://github.com/k1moradi/swapz/commit/4186cc07944bd162366d0b74931ae9a8b0e71f75), sole parent `ddeae7fa5e291ae677fb7ef0e8a723567a45ff5b`. Source blob `9f2529912a2cb47f4b20bb733903c25d65d97dda`, focused test blob `55855622dd2e4a382228678b4ca0f397a270952f`; both exactly match tested local bytes. Standards append staged from exact parent `e4c88ef49b16a65696aad089d72fb5fc15a2256b` to `1a8cf1dc7adb3b157779f53dc7fc185c2e064071`, byte-prefix verified. Only these owned files and R113 reports; no A2 dependencies, no workflows/kernel/caller changes. The legacy source is byte-exact when the inserted opt-in block is excluded.

**Publication state:** source/test and report candidate Git objects prepared on a sole-parent main lineage, no ref move until Agent1's serialized publication turn. These objects are not on main until the expected-HEAD non-force update succeeds; Agent1 may integrate by fresh expected-HEAD update or reconstruct atop an intervening main parent. Source qualification is distinct from publication.

## Implementation

`prepare_matched_cold_workload(*, page_count, hot_page_count, seed, tmpfs_fd)` returns a context manager. Linux host must use 4096-byte pages. Both mappings together capped at the existing 768 MiB ceiling (tests use at most 128 KiB combined). Caller retains exclusive empty private unlinked 0600 read-write regular file. Duplicate fd is checked against /proc/self/fdinfo mnt_id and the exact unique /proc/self/mountinfo row and fstat device, including tmpfs filesystem type; no path-based guess, no memfd fallback. Reserve capacity with posix_fallocate before mappings (ordinary anonymous private mmap and actual file-backed shared mmap). Caller retains the original fd; context owns both mappings and duplicate, restores length zero at normal exit, closes on partial reserve/map/fill failure. If close fails, invalidate workload and do not truncate a live mapping. Preserve body/setup first error with bounded cleanup note; no names, IDs or raw bytes in diagnostics. Exclusive caller ownership, no concurrency or exported views. Existing CLI/main/pressure behavior is unchanged and no caller is wired to new helper.

Per-page 512-byte seed/index SHAKE-256 patterns repeated across 4096 bytes, forced nonuniform prefix; deterministic compressible synthetic data, not production corpus. Explicit stable contiguous hot prefix and cold suffix, both nonempty. Initial population writes both identically; controlled touch toggles first byte of hot pages only. Verify full pages against regenerated expected bytes after observation, outside timing (verification itself reads cold pages and must not be interleaved with observation). No timing claims or residency assertions: unchanged bytes alone do not prove MM page temperature, eviction or reclaim. No background reclaim, timer, CPU burner, pressure workload, pageout or storage activity.

## Actual rootless execution

Local Python 3.13.5, executed as unprivileged user (container starts UID0; used runuser to drop to an unprivileged test process, no privileged workload). Exact tested source/test blob hashes above. No full repo checkout: GitHub DNS unavailable in container, frozen resource-pressure.py transferred from connector and exact hash verified; new source/test blobs independently compared to local. Commands from isolated source-layout directory:

```text
runuser -u oai -- python3 -B tests/runtime/native/phase-a-cold-workload-test.py
Ran 10 tests in 1.313s
OK
runuser -u oai -- python3 -B cleanup-ownership-selected.py
Ran 1 test in 0.017s
OK
```

All 10 focused methods PASS, 0 skips. Existing actual tmpfs file-backed mapping plus anonymous mapping, 16 pages each (five hot, eleven cold), 32 pages / 131072 bytes combined max simultaneous. Full expected and matched bytes, hot parity, seed reproducibility/difference, cold last-byte corruption refusal, invalid bounds, pipe and non-tmpfs file rejection (no resize), named/nonempty/read-only and unlisted mount rejection, actual memfd refusal, injected partial reserve/map/fill cleanup with real acquired mappings, actual mmap.close BufferError negative test and preserved first body error on injected reset failure. FD count restored in tested cleanup paths, caller fd kept. Legacy --help and invalid --memory-mib 1 output, stderr and return codes independently compared byte-for-byte against exact frozen file under same basename; no valid pressure CLI invocation. Two actual tiny mappings, no resource-pressure or native kernel workload.

Relevant existing cleanup ownership regression `test_pinned_directory_identity_detects_same_path_replacement`: selected exact test method, setUp, shell_function and run_simple_shell from frozen `tests/runtime/native/resource-pressure-cleanup-ownership-test.py` blob `338f681d990b830ea4243a237bc9fccb2fdc3426`; actual two shell functions from frozen qualifier blob `7d0e3aa4337c2810bde20f8fec5edba0589d0af6`. Reconstructed selected harness hash `044b26d79701b3fc4592f114d37a3bf3fac8059f` and shell excerpt `030c90ea86035a538ca3cf72a7af433d10484aec` independently recreated from frozen connector content, match local. The selected method ran actual shell/stat and synthetic temp directories, not a mock of the helper. Entire existing 72KB test/92KB qualifier suite NOT_RUN: full checkout unavailable; this is extracted selected-method regression, not whole-suite success. No actual failure in final focused/selected executions, first error null.

## Decision

Evidence -> Goal implication -> Verdict: exact locally executed matched cohort helper and verified real tmpfs plus negative ownership tests -> permits future explicitly authorized matched anon/shmem workload setup with no cold touches during hot loop -> **ROOTLESS PREPARATION PASS ONLY**. Future measurement must separately attribute anon and shmem reclaim, fault p95/p99, CPU/page, zswap pool changes and storage congestion; no native results, no perf generalization. Phase A remains UNKNOWN/BLOCKED. AUTH=0, compressed handoff/forced RAW/import OFF, physical NO_GO. Agent1 acceptance only.
