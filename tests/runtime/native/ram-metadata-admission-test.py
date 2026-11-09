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
    engine = (ROOT / "src/kernel/engine.c").read_text(encoding="utf-8")
    append = engine.split("static int swapz_append_page(", 1)[1].split(
        "\nstatic int swapz_page_valid(", 1)[0]
    require(append.count("swapz_page_valid(page)") == 1 and
            append.index("swapz_page_valid(page)") <
            append.index("page->payload_crc32c_valid") and
            append.count("swapz_ram_extent_append_prehashed(") == 1,
            "Both hashed and prehashed unique-page appends must revalidate "
            "engine page semantics before copying compressed payloads")
    require("swapz_u32 payload_crc32c;" in authority,
            "Compressed payload CRC must remain authoritative volatile RAM state")
    require("_Static_assert(sizeof(struct swapz_map) == 20" in authority,
            "Capacity accounting requires the 20-byte RAM mapping record")
    require("swapz_linux_swap_header_valid(block, device_bytes)" in target,
            "Ordinary SWAPSPACE2 validation must remain the physical header contract")

    disk_identity = target.index('is_nullb = !strncmp(')
    io_client = target.index("ctx->io_client = dm_io_client_create();", disk_identity)
    require("module_param_named(physical_ram_metadata_qualified" in target,
            "Physical RAM qualification must be an immutable module-load token")
    require("if (!is_nullb && !swapz_physical_ram_metadata_qualified) {" in
            target[disk_identity:io_client],
            "Real backing must retain the loaded-qualification interlock")

    lifecycle = primary.index("static int swapz_primary_run_mutating_action(")
    mutation_lock = primary.index(
        "mutation_lock_fd = swapz_primary_mutation_lock();", lifecycle)
    require("SWAPZ_PHYSICAL_RAM_METADATA_QUALIFIED" not in
            primary[lifecycle:mutation_lock],
            "Primary lifecycle must not depend on a source-mutating qualification flag")
    loader = primary.index("int swapz_primary_load_qualified_module(")
    loader_end = primary.index("\nstatic int swapz_primary_manifest_equal(", loader)
    loader_scope = primary[loader:loader_end]
    require(
        "allow_physical_backing=1 physical_ram_metadata_qualified=1" in
        loader_scope and
        "/sys/module/dm_swapz/parameters/physical_ram_metadata_qualified" in
        loader_scope,
        "Qualified primary loading must set and verify the runtime token")

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
