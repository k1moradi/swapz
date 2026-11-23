# Round074 — correct staffing: reuse SIX existing agents 2–7, no new identities

[Issue #191](https://github.com/k1moradi/swapz/issues/191) · [immutable frozen contract](frozen-contract.md) · [Agent1 standing scheduler](../agent1-scheduling-policy.md) · [GitHub evidence delivery](../evidence-policy.md) · [notification](notification.md).

| Existing worker | Independent, exclusive task | CI cost |
| --- | --- | --- |
| **Agent2** | [Original native DM strict-prototype first-error P0](agent2-original-dm-native-prototype-p0.md) | One source-host + original native requalification only after code fix |
| **Agent3** | [Original zswap source provenance standards EOF P0](agent3-original-source-preflight-p0.md) | First source-host, dependent existing native only once qualified |
| **Agent4** | [Pool/RCU lease stage negative HOST](agent4-pool-lifetime-stage-negative.md) | Host-only while Round072 original native still queued |
| **Agent5** | [Owned compressed source→BIO payload lifetime HOST](agent5-source-copy-ownership-host.md) | Host-only while Round072 joined native still queued |
| **Agent6** | [Natural MM eviction source lease and no-second-reclaim HOST](agent6-natural-eviction-lock-budget.md) | Host-only; no Agent11 DM queue overlap |
| **Agent7** | [Real RAW_4096 uncompressed fallback and wrong original codec refusal HOST](agent7-original-compressed-vs-raw-fallback.md) | Host-only; no repeat Round072 codec CI or Agent10 decoder |

Agent1 is management only. Agents8–11 finish **existing Round073 #190 CI/evidence** and aren't assigned new Round074 source tasks. Both prior issues #189 (Round072) and #190 (Round073) stay OPEN while exact CI nonterminal/failed; new independent work need not wait for CI, only shared remote main *publication* is serialized nonforce expected-head. All start together after authoritative Round074 `message: ROUND_OPEN` #191. Every worker commits exactly two mandatory round-scoped GitHub files `agentN-evidence.md`, `agentN-results.json` and posts GitHub issue links; no owner as file courier or periodic checks. Host modeled work never establishes source AUTH or physical durability.
