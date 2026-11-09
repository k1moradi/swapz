#!/usr/bin/env python3
"""Source-only contract for RAM-only production metadata and SWAPSPACE2 backing.

This is not loaded or physical-media qualification. It prevents regression to
an in-band production metadata format while checking the protected lower range.
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
    require(declarations == ["0"],
            "Production kernel compressed extents must keep metadata off media")
    require("swapz_u32 payload_crc32c;" in authority,
            "Compressed payload CRC must remain authoritative volatile RAM state")
    require("_Static_assert(sizeof(struct swapz_map) == 20" in authority,
            "Capacity accounting requires the 20-byte RAM mapping record")
    require("swapz_linux_swap_header_valid(block, device_bytes)" in target,
            "Ordinary SWAPSPACE2 validation must remain the physical header contract")

    disk_identity = target.index('is_nullb = !strncmp(')
    io_client = target.index("ctx->io_client = dm_io_client_create();", disk_identity)
    require("if (!is_nullb && SWAPZ_CODEC_METADATA_ON_MEDIA) {" not in
            target[disk_identity:io_client],
            "Production physical admission must not retain the obsolete metadata lockout")

    lifecycle = primary.index("static int swapz_primary_run_mutating_action(")
    mutation_lock = primary.index(
        "mutation_lock_fd = swapz_primary_mutation_lock();", lifecycle)
    require("if (SWAPZ_CODEC_METADATA_ON_MEDIA &&" not in
            primary[lifecycle:mutation_lock],
            "Primary PREPARE/START must not block the RAM-only production codec")

    # DM property consumers must see the allocated lower data range, not
    # the reserved SWAPSPACE2 header or discarded segment-alignment tail.
    iterator = target.split("static int swapz_iterate_devices(", 1)[1].split(
        "\nstatic void swapz_io_hints(", 1)[0]
    require("(sector_t)ctx->data_start_block * SWAPZ_SECTORS" in iterator and
            "(sector_t)ctx->physical_blocks * SWAPZ_SECTORS" in iterator,
            "iterate_devices must report data-start and data-length separately")
    require("(ctx->data_start_block + ctx->physical_blocks)" not in iterator,
            "iterate_devices must exclude the protected swap header")

    print("PASS: RAM-only production metadata and protected SWAPSPACE2 data range")


if __name__ == "__main__":
    main()
