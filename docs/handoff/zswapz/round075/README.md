# Round075 — three existing agents repair exactly three newly terminal CI failures

[Official issue #192](https://github.com/k1moradi/swapz/issues/192) · [frozen contract](frozen-contract.md) · [independent first-error checkpoint](agent1-ci-checkpoint.md) · [copy notification](notification.md) · [mandatory evidence policy](../evidence-policy.md).

| Reused worker | Exact exclusive first failure | Full GitHub prompt | New CI |
| --- | --- | --- | --- |
| **Agent5** | Round072 original native: inherited Round069 mm/zswap.c staged SHA checked after Round072 append; Python assertion before KUnit | [Source postimage stage-order P0](agent5-original-native-postimage-order-p0.md) | One scoped original UML native only after source-stage repair + host preflight |
| **Agent9** | Round073 geometry host: nonunique `2U * SWAPZ_SEGMENT_BLOCKS` header mutant anchor | [Source-aware geometry mutation P0](agent9-geometry-unique-mutant-anchor-p0.md) | Host-only GCC/Clang strict sanitizers and executed C mutants |
| **Agent11** | Round073 fairness host: mutant-gcc-06 C compile error; no executed mutant | [Valid compiler-clean fairness mutant P0](agent11-dm-fairness-compiler-clean-mutants-p0.md) | Host-only GCC/Clang strict sanitizers and executed C mutants |

**Optimal scheduling:** exactly three assigned workers (excluding Agent1) because there are three actual newly verified source-CI failures in their existing independent scopes. Reusing other agents to create new unrelated tests would compete for the GitHub Actions queue with pending Round074 six jobs and original Round073 Agent10. Other agents retain their previous round duties. No new worker IDs, periodic CI watches, new branches/PRs or duplicated unchanged CI runs. All three may begin simultaneously; only direct remote main FF publication is single-writer. Evidence is committed directly to GitHub with two files per agent and #192 comment. Keep all source-auth/Phase-A/opaque compressed handoff activation OFF; no real swap device or physical KUnit workaround.
