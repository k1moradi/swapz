# Round071 — five independent workers, opening by issue #188 only

[Official issue #188](https://github.com/k1moradi/swapz/issues/188) • [frozen contract](frozen-contract.md) • [Round070 administrative PARTIAL closeout](../round070/round-report.md) • [notification](notification.md).

| Worker | Independent task and exclusive artifact |
| --- | --- |
| **Agent2** | [Original current DM upper BIO once-only owner](agent2-original-dm-upper-owner.md) — staged original Linux, source/ACK negative admission |
| **Agent3** | [Original zswap STORED source provenance](agent3-original-zswap-source-provenance.md) — genuine swapcache prerequisite and tested fail-closed negative, no fabricated AUTH |
| **Agent4** | [Original zswap source-pool/decoder lifetime](agent4-original-pool-retirement-decoder.md) — genuine pinned Linux pool retirement attempt plus reader leasing |
| **Agent5** | [Joined source-copy → native BIO → actual authority → decoder](agent5-joined-source-bio-authority-decoder.md) — first fix prior native reader-pin/GC 3/4 with same-codec exact-byte relocation |
| **Agent6** | [Natural pressure / no recompression scheduling](agent6-natural-pressure-scheduling.md) — host-only deterministic source-linked cooperation/fairness/negative controls |

**Engineering baseline before this task update:** `73446b1a5f88ec8d3ba1e45e623825fd5fed2880`; earlier Round071 planning contract commit `4e4fc67fd83fcf651b2489a25a3b31d60a4a3d2a`. The only authoritative final task SHA is named by a unique `message: ROUND_OPEN` on #188. Until then, prepare but do not claim implementation is started.

Round070's newest pinned-original KUnit actually ran 4 cases: **3 PASS / 1 FAIL**; source-host green. It is administratively CLOSED **PARTIAL** and the P0 is Agent5's first Round071 task. This does NOT weaken any test gate. Agent4, Agent2, Agent3 and Agent6 are *not blocked* on Agent5's P0 and require no new peer API.

All own distinct files, can develop/test simultaneously, and post to #188 separately. One remote main writer at a time (fresh HEAD, exactly one parent, non-force expected-head fast forward, verify remote). No branch/PR/fork/worktree, no suppressing warnings, no duplicate CI. All product import/activation OFF and source-auth=0, Phase A BLOCKED. Linux MM alone owns zswap compressed RAM and natural memory-pressure eviction; swapz owns only lower disk packing/GC; the future **volatile tagged passthrough** may store already-compressed original bytes without recompressing, but ordinary `RAW_4096` is still full original UNCOMPRESSED 4096. First SWAPSPACE2 4096-byte header, UUID/signature, partition table and map format remain intact.
