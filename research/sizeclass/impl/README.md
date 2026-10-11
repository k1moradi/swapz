# Corrected rootless allocator (Issue #33)

Research-only, single-worker Python model. No kernel changes, privileged execution, production swap, GC, or durability claims.

Serialized compressed extent: 8-byte little-endian header (u32 magic, u16 version, u16 record count), 8-byte descriptors (u32 logical slot, u16 payload offset, u16 length), then packed payloads. Aligned extent classes: 4/8/16/64 KiB. Raw page fallback writes one 4 KiB extent without metadata.

Mapping authority begins only on whole-extent successful completion. Failed or torn writes preserve previous mappings. Explicit bounds limit staged records, outstanding extents and physical bytes. Generations prevent late old completions from overwriting newer mappings. This is a rootless prototype, not a proposed production format; no GC or power-loss recovery is modeled.

Run: `python3 -B research/sizeclass/impl/test_allocator.py -v`.
