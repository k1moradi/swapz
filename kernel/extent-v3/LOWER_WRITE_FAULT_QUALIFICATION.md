# Alpha.7: isolated pre-submission lower WRITE fault gate

**Evidence class:** kernel-loaded, target-local **synthetic** failure on a
test-owned, `memory_backed=1` `null_blk`. This is not a device-originated
failure, torn-write simulation, power-loss test, or permission to use SD/SSD/HDD.

The optional **ninth** positional constructor token is
`test_fail_write_nth`, an integer 0..65535 (default 0, disabled):

```text
<owned_ram_nullb> [read_cap 0..3] [window 1..64] [verify 0|1]
 [gc 0..2] [coalesce_ms 0..4] [test_fail_flush_nth 0..64]
 [lower_bulk 0|1|2] [test_fail_write_nth 0..65535]
```

With nonzero `test_fail_write_nth=N`, the Nth attempted **lower WRITE**
through the common serialized `sv3_lower()` adapter returns `-EIO`
**before** calling `dm_io`. This includes foreground compressed extents,
raw fallback, mixed/combined lower runs, and GC relocation writes. The
already staged mixed group is rejected by the normal engine callback
without publishing any mapping in its unsuccessful run. Its reservations
are quarantined and the upper target fails closed. An earlier completed
run may have published an exact logical prefix. This injection cannot
test physical partial completions; actual media error propagation remains
an independent, unqualified requirement.

Info status includes `write_fault_nth`, `write_fault_calls`,
`write_fault_injected`. `write_fault_calls` counts attempted lower writes **only while the test
injector is armed** (and stays zero when disabled); `write_fault_injected` counts
pre-submission synthetic rejections. Existing `write_submitted_reqs`
and `physical_write_reqs` **exclude** these rejections; compare backing
`/sys/block/<owned-nullb>/stat` after confirmed drain. Neither target-side
submission counter is a substitute for block-layer request statistics.

## Independent loaded test plan

Perform all tests on fresh uniquely owned RAM null_blk / DM instances.
Pin exact source SHA, compiled module SHA-256, vermagic, DM target/UUID,
null_blk major:minor, inputs, and upper completion result; do not reuse a
fail-closed target. Protect `/dev/sdb1`, `/swapfile`, all active swap,
other mappings/devices, and do not reboot.

1. **No-injection control:** same 819 compressed / 205 raw 1,024-page
   fixture, `lower_bulk=1`, `test_fail_write_nth=0`. Full 1,024-page
   byte-exact readback; expected 16 combined runs on the **historical**
   57B compressed-page fixture only, not all possible fixtures.
2. **First-run rejection:** fresh target, `lower_bulk=1`, set
   `test_fail_write_nth=1`. The first mixed run must return EIO,
   no affected upper write may report success, and no new physical
   lower write should be submitted for that first failed attempt.
   Check `failed=1,error=-5`, `write_fault_calls>=1`,
   `write_fault_injected=1`, and no active pending snapshots
   before ordinary teardown. Do **not** continue reads on the failed
   target.
3. **Later-run rejection:** fresh target, `lower_bulk=1`, set
   `test_fail_write_nth=2`. Verify the first run's upper completions
   were reported once only **after** full lower success, and the second
   run's upper writes failed. Assert `write_fault_calls>=2`,
   `write_fault_injected=1`, independent backing requests equal the
   true successful submitted prefix, and no false successful completion
   for the rejected run. Do not assume a fixed number of committed
   upper pages without recording actual worker window boundaries.
   Do not perform post-error reads on that failed target.
4. Repeat first/later rejection with `lower_bulk=0` (serialized
   control), `lower_bulk=2` (padding control), and deterministic
   compressed-only and raw-only windows. Compare attempted/actual
   counters, type-specific completed BIOs, and fail-closed behavior.
5. **GC relocation failure:** use a fresh target with an identified,
   safely bounded Nth lower WRITE corresponding to GC relocation.
   Check unchanged reserve-role rotation count on rejection; no
   falsely acknowledged foreground write; normal owned-resource
   teardown with no outstanding callbacks. If the trigger cannot
   be placed deterministically, mark the scenario BLOCKED.
6. Run the existing exact-production-C short/torn-write and failed
   overwrite mapping-preservation tests. This target-local injector
   **cannot** replace those tests or simulate device-side partial I/O.

For all failed-target probes, capture the status and relevant kernel
messages **before** teardown, without assuming post-failure data I/O
is safe. A synthetic injected EIO intentionally cannot demonstrate
that the old data remains readable through a failed production mapping.
The source exact-C authority tests provide that distinct evidence.

## Independent performance interpretation

The standalone `write_fault_nth=0` branch must be requalified for
steady-state p95/p99, lower reads/bytes/requests including GC, achieved
IOPS and CPU. Codex's [alpha.7 PR #56](https://github.com/k1moradi/swapz/pull/56)
proved a large request/byte win **only** for one 1,024-write fixture
with 819 compressed pages of ~57B each, rather than typical 1–3KiB
compressed lengths. Its grouped trial order, missing sustained tests,
and inability to inject an actual lower-device error remain limitations.
No physical-device test is authorized.
