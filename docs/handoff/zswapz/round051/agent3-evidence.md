# Round051 Agent3 — real Device Mapper negative C and native source-policy repair

**Scope.** Own-only modifications to the existing Round050 real-product-C host
fixture, source-extraction verifier, its CI step name, and a substantive
same-source-commit append to the complete canonical testing standards.

The native repo-policy first RED on the older engineering SHA
`d98aa016682275fa9f18fd9debd6553870a8a5a2` was
`SOURCE_CONTRACT_MISMATCH`: the modified negative C fixture lacked a
non-whitespace same-commit `docs/testing_standards.md` change. Do not
erase or rewrite that historical red. New commit must qualify independently.

The previously executed 53 x 3 = 159 real C cases grow to 56 x 3 = 168
negative exact-errno cases on each GCC and Clang. New fault 53 carries a
3568-byte exact cap and matching fabricated source/table claims, still
returning `-EOPNOTSUPP`; fault 54 breaks only the observed CRC, requiring
`-EBADMSG`; fault 55 reports only observed lower callback `-EIO`,
requiring `-EAGAIN`. Both two synthetic reports are test input only.
The 22 actual genuine helper C mutations remain compiler-executed
for GCC and Clang (44 distinct hostile executions), with strict
`-Werror`, ASan and UBSan on the real extracted production C.

The fixture is rootless and cannot mint genuine Linux swap counted slot
ownership, current Device Mapper table SRCU lifetime/GC/dtr ownership,
durable lower I/O, mapping publication or real upper BIO ACK. The real
product guard remains default-undefined; normal `swapz_map` continues
to deliver full ORIGINAL UNCOMPRESSED 4096-byte RAW_4096; codec
reuse and compressed handoff remain disabled. The first physical 4096
SWAPSPACE2 header and UUID remain immutable. No pressure/physical/loaded
or owner `make test`/`make fast_test` testing is authorized.

**GitHub acceptance.** Only source-bound terminal successful workflow
jobs and exact SHA count as evidence; native repository-policy plus
original real-C GCC/Clang workflow must both be verified after publish.
At document-creation time new-SHA results have NOT yet been observed;
report their actual terminal states separately on issue #168. Original
pinned kernel ancestor UML 57/57 and GPL matched module results cannot
be automatically claimed for this SHA. `SOURCE_MAPPED_AUTHENTICATED=0`,
`PHASE_A=BLOCKED`.
