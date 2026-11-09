#!/usr/bin/env python3
"""Source-only lockout regression for the pre-migration compressed extent codec.

This is not a loaded, physical-media or swap-lifecycle qualification test.
The lockout must remain until compressed descriptors and CRCs reside in RAM.
"""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[3]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    codec = (ROOT / "src/kernel/codec.h").read_text(encoding="utf-8")
    authority = (ROOT / "src/kernel/authority.h").read_text(encoding="utf-8")
    target = (ROOT / "src/kernel/dm-target.c").read_text(encoding="utf-8")
    primary = (ROOT / "src/userspace/swapz-primary.c").read_text(encoding="utf-8")
    declarations = re.findall(
        r"(?m)^#define SWAPZ_CODEC_METADATA_ON_MEDIA ([01])U$", codec
    )
    require(declarations == ["1"], "Legacy in-band codec must retain its physical interlock")
    require("swapz_u32 payload_crc32c;" in authority,
            "Compressed payload CRC must remain authoritative volatile RAM state")
    require("_Static_assert(sizeof(struct swapz_map) == 20" in authority,
            "Capacity accounting requires the 20-byte RAM mapping record")
    require("swapz_linux_swap_header_valid(block, device_bytes)" in target,
            "Ordinary SWAPSPACE2 validation must remain the physical header contract")

    disk_identity = target.index('is_nullb = !strncmp(')
    physical_gate = target.index(
        "if (!is_nullb && SWAPZ_CODEC_METADATA_ON_MEDIA) {", disk_identity
    )
    gate_end = target.index("\n\t}", physical_gate)
    gate = target[physical_gate:gate_end]
    require('error = -EOPNOTSUPP;' in gate and 'goto fail;' in gate
            and 'ti->error =' in gate,
            "Real physical backing must fail closed while codec emits in-band metadata")
    require(disk_identity < physical_gate <
            target.index("ctx->io_client = dm_io_client_create();", disk_identity),
            "Physical interlock must precede lower I/O client admission")
    require(physical_gate < target.index("if (is_nullb) {", physical_gate),
            "Synthetic null_blk must remain separate from physical interlock")

    # A physical lifecycle cannot swapoff the original partition and only
    # discover the codec incompatibility during mapper construction.
    lifecycle = primary.index("static int swapz_primary_run_mutating_action(")
    primary_gate = primary.index("if (SWAPZ_CODEC_METADATA_ON_MEDIA &&", lifecycle)
    mutation_lock = primary.index("mutation_lock_fd = swapz_primary_mutation_lock();", lifecycle)
    blocked_scope = primary[lifecycle:mutation_lock]
    require(lifecycle < primary_gate < mutation_lock,
            "Primary PREPARE/START must reject in-band metadata before mutation")
    require("SWAPZ_PRIMARY_MUTATING_PREPARE" in blocked_scope and
            "SWAPZ_PRIMARY_MUTATING_START" in blocked_scope and
            "errno = EOPNOTSUPP;" in blocked_scope and
            "return -1;" in blocked_scope,
            "Primary physical lifecycle must fail closed before swapoff")

    # DM property consumers must see the allocated lower data range, not
    # the reserved SWAPSPACE2 header or discarded segment-alignment tail.
    iterator = target.split("static int swapz_iterate_devices(", 1)[1].split(
        "\nstatic void swapz_io_hints(", 1)[0]
    require("(sector_t)ctx->data_start_block * SWAPZ_SECTORS" in iterator and
            "(sector_t)ctx->physical_blocks * SWAPZ_SECTORS" in iterator,
            "iterate_devices must report data-start and data-length separately")
    require("(ctx->data_start_block + ctx->physical_blocks)" not in iterator,
            "iterate_devices must exclude the protected swap header")

    print("PASS: physical metadata lockout and lower data range (source contract)")


if __name__ == "__main__":
    main()
