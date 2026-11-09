#!/usr/bin/env python3
"""Source-only contract for payload-only production extents and RAM authority.

This is not loaded, physical-media, or live-swap qualification. It prevents the
production engine from regressing to serialized SWZ descriptors while retaining
ordinary SWAPSPACE2 backing and the fail-closed physical admission path.
"""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[3]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    codec_header = (ROOT / "src/kernel/codec.h").read_text(encoding="utf-8")
    engine = (ROOT / "src/kernel/engine.c").read_text(encoding="utf-8")
    authority = (ROOT / "src/kernel/authority.c").read_text(encoding="utf-8")
    authority_header = (ROOT / "src/kernel/authority.h").read_text(encoding="utf-8")
    target = (ROOT / "src/kernel/dm-target.c").read_text(encoding="utf-8")

    declarations = re.findall(
        r"(?m)^#define SWAPZ_CODEC_METADATA_ON_MEDIA ([01])U$", codec_header
    )
    require(declarations == ["0"],
            "Production compressed extents must be payload-only")
    require("swapz_ram_extent_begin(" in engine and
            "swapz_ram_extent_seal(" in engine and
            "swapz_mark_compressed_data_only(" in engine,
            "Production writes must seal data-only extents from volatile RAM")
    require("swapz_begin(&builder" not in engine and
            "swapz_seal(&builder" not in engine,
            "Production engine must not call the legacy in-band builder")
    require("compressed_data_only" in authority_header,
            "Transaction identity must include the data-only representation")
    require("if (data_only)" in authority and
            "swapz_read_authoritative_payload(" in authority,
            "Publication and reads must use volatile descriptor authority")
    require("swapz_u32 payload_crc32c;" in authority_header and
            "_Static_assert(sizeof(struct swapz_map) == 20" in authority_header,
            "Compressed CRC and compact mapping authority must remain in RAM")
    require("swapz_linux_swap_header_valid(block, device_bytes)" in target,
            "Ordinary SWAPSPACE2 validation must remain the backing contract")

    disk_identity = target.index('is_nullb = !strncmp(')
    physical_gate = target.index(
        "if (!is_nullb && SWAPZ_CODEC_METADATA_ON_MEDIA) {", disk_identity
    )
    require(disk_identity < physical_gate <
            target.index("ctx->io_client = dm_io_client_create();", disk_identity),
            "Defensive metadata gate must remain before lower-I/O admission")

    iterator = target.split("static int swapz_iterate_devices(", 1)[1].split(
        "\nstatic void swapz_io_hints(", 1)[0]
    require("(sector_t)ctx->data_start_block * SWAPZ_SECTORS" in iterator and
            "(sector_t)ctx->physical_blocks * SWAPZ_SECTORS" in iterator,
            "iterate_devices must report data-start and data-length separately")
    require("(ctx->data_start_block + ctx->physical_blocks)" not in iterator,
            "iterate_devices must exclude the protected SWAPSPACE2 header")

    print("PASS: production extents are payload-only with RAM descriptor authority")


if __name__ == "__main__":
    main()
