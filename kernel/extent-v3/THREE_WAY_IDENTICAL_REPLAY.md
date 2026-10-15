# Historical three-arm replay — retired benchmark method

**Not an active testing protocol.** V2.2 has been retired as a performance
comparison and V3 is now the only active kernel development target on
`main`. See [benchmark.md](../../docs/benchmark.md) for the binding
**two-arm off versus V3** benchmark and
[testing_standards.md](../../docs/testing_standards.md) for source and host
safety gates.

Use `tests/runtime/io-replay.py`, not deleted
`threeway-swap-replay.py`. The original three-way historical method
and rationale are preserved in prior Git commits for traceability.
There is no authorization to run old host-swap or physical-media
benchmarks.
