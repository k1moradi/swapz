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
    authority_source = (ROOT / "src/kernel/authority.c").read_text(encoding="utf-8")
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
    finish = authority_source.split("int swapz_finish(", 1)[1].split(
        "\nint swapz_finish_raw(", 1)[0]
    kernel_guard = finish.index("#ifdef __KERNEL__")
    legacy_validator = finish.index("swapz_validate_metadata_crc")
    require(
        kernel_guard < legacy_validator and
        "if (!data_only) {" in finish[kernel_guard:legacy_validator] and
        "error = -EUCLEAN;" in finish[kernel_guard:legacy_validator],
        "Kernel publication must reject legacy serialized extent metadata before "
        "the userspace-fixture validator can run")
    require(
        "swapz_read_authoritative_payload(" in engine and
        "swapz_peek(" not in engine and
        "swapz_lookup_validated" not in engine,
        "Production engine reads must use RAM descriptors, never serialized "
        "lower-media metadata lookup")
    require("_Static_assert(sizeof(struct swapz_map) == 20" in authority,
            "Capacity accounting requires the 20-byte RAM mapping record")
    require("static u64 swapz_authority_metadata_ram_bytes(" in target and
            "sizeof(struct swapz_map) + 2U * sizeof(swapz_u32)" in target and
            "sizeof(swapz_u16) + 2U * sizeof(swapz_u8)" in target and
            "8U * sizeof(swapz_u32) + sizeof(swapz_u16) +" in target,
            "Production must expose the exact geometry-scaled RAM authority footprint")
    require("authority_metadata_ram=%llu" in target and
            "read_payload_cache_ram=%llu" in target,
            "Runtime status must expose cached authority and payload-cache RAM bytes")
    require(
        "swapz_linux_swap_header_parse(block, device_bytes, &layout)" in target and
        "swapz_configure_linux_swap_layout(ctx, block, &layout)" in target,
        "Physical backing must parse the full ordinary SWAPSPACE2 layout into RAM")
    require(
        "swapz_backing_range_valid(ctx, block, blocks)" in target and
        "ctx->segment_backing_pages" in target,
        "Lower I/O must remain segment-contained for sparse clean-segment mapping")
    require(
        "swapz_primary_run_mkswap(mkswap_fd, mapper_fd)" in primary and
        "swapz_primary_run_mkswap(mkswap_fd, target_fd)" not in primary,
        "mkswap must remain mapper-only and must never target the raw SWAPSPACE2 fd")
    physical_probe = (ROOT / "tests/tools/physical-swap-probe.py").read_text(
        encoding="utf-8")
    require(
        '_run(["mkswap", "--", mapper], timeout=30)' in physical_probe and
        '_run(["mkswap", "--", target[' not in physical_probe and
        'SWAP_SIGNATURE = b"SWAPSPACE2"' in physical_probe,
        "Physical test must format only the owned mapper and require SWAPSPACE2")

    # A null or invalid asynchronous write slot must be rejected before
    # its lower-image pointer is read while building the dm_io request.
    async_write = target.split("static int swapz_submit_inflight_write(", 1)[1]
    validation = async_write.index("if (!inflight ||")
    image_binding = async_write.index("req.mem.ptr.vma = inflight->run.bytes;")
    require(
        image_binding > validation and
        "inflight->run.bytes" not in async_write[:validation],
        "Async lower WRITE must validate slot before dereferencing its image")

    # Reject an invalid read-slot block range before forming a pointer
    # outside the slot's allocated scratch image.
    async_read = target.split("static int swapz_submit_read_slot_range(", 1)[1]
    read_validation = async_read.index("if (!blocks || first_block >=")
    read_binding = async_read.index("req.mem.ptr.vma = slot->engine.read_scratch +")
    require(
        read_binding > read_validation and
        "slot->engine.read_scratch +" not in async_read[:read_validation],
        "Async lower READ must validate block range before scratch offset")

    disk_identity = target.index('is_nullb = !strncmp(')
    io_client = target.index("ctx->io_client = dm_io_client_create();", disk_identity)
    disk_classification = target[disk_identity:io_client]
    require("ctx->backing->bdev->bd_disk->disk_name + 5" in disk_classification
            and "if (!*disk_suffix)" in disk_classification
            and "*disk_suffix < '0' || *disk_suffix > '9'" in disk_classification,
            "Synthetic null_blk classification must require a decimal index")
    require(
        "if (!is_nullb && !bdev_is_partition(ctx->backing->bdev)) {" in
            disk_classification,
        "Real SWAPSPACE2 backing must be a partition, not a whole disk")
    # Native Linux swap headers live at the kernel base-page boundary. A
    # 4KiB payload-only mapper must never qualify on a different PAGE_SIZE.
    require("#if PAGE_SIZE != SWAPZ_BLOCK_BYTES" in target and
            '#error "swapz requires 4KiB PAGE_SIZE"' in target,
            "Kernel must reject non-4KiB native swap-page geometry at build time")
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

    # Mutable lifecycle ownership is same-boot RAM state. Persistent storage
    # may retain signed qualification evidence, but it must not become a
    # physical-parent admission dependency or swapz on-partition metadata.
    require(
        "#define SWAPZ_PRIMARY_RUNTIME_STATE_BASE \\\n"
        "\tSWAPZ_PRIMARY_EXECUTION_RUNTIME_DIRECTORY" in primary,
        "Production lifecycle state must stay under the /run runtime directory")
    require(
        "report_fd = swapz_primary_recovery_base_open(\n"
        "\t\tSWAPZ_PRIMARY_QUALIFICATION_BASE, 0);" in primary,
        "Persistent qualification evidence must use a descriptor separate from "
        "volatile runtime state without pinning a legacy recovery-path name")
    require(
        "return (unsigned long)type == TMPFS_MAGIC;" in primary,
        "Production lifecycle state must require a RAM-backed tmpfs filesystem")
    require(
        "int state_fd, int lock_fd, int report_fd" in primary,
        "Qualification import must keep state and persistent evidence descriptors separate")
    for obsolete_recovery_gate in (
        "separate-physical-recovery-parent",
        "target-recovery-parent-separation",
        "swapz_primary_recovery_parent_separation_valid",
    ):
        require(
            obsolete_recovery_gate not in primary,
            f"Obsolete physical recovery-disk gate remains: {obsolete_recovery_gate}")

    runtime_preflight = primary.split(
        "static int swapz_primary_recovery_preflight(", 1)[1].split(
        "\nstatic int swapz_primary_mutation_lock_at(", 1)[0]
    require(
        "swapz_primary_runtime_state_base_open" not in runtime_preflight and
        "SWAPZ_PRIMARY_RUNTIME_STATE_BASE" in runtime_preflight,
        "Read-only runtime-state preflight must inspect without creating /run state")

    require(
        "runtime_state_missing = 1;" in runtime_preflight and
        "swapz_primary_runtime_state_parent_open()" in runtime_preflight and
        "No state directory means no ownership marker can exist yet." in
        runtime_preflight,
        "First-use plan must safely admit an absent /run/swapz without creating it")
    require(
        "#define SWAPZ_PRIMARY_EXECUTION_RUNTIME_PARENT \"/run\"" in primary,
        "Runtime-state parent identity must stay fixed at /run")

    # DM property consumers must see the allocated lower data range, not
    # the reserved SWAPSPACE2 header or discarded segment-alignment tail.
    iterator = target.split("static int swapz_iterate_devices(", 1)[1].split(
        "\nstatic void swapz_io_hints(", 1)[0]
    require("swapz_backing_data_sector(ctx, 0)" in iterator and
            "(sector_t)ctx->physical_blocks * SWAPZ_SECTORS" in iterator,
            "iterate_devices must report data-start and data-length separately")
    require("(ctx->data_start_block + ctx->physical_blocks)" not in iterator,
            "iterate_devices must exclude the protected swap header")
    require("ctx->backing_last_page" not in iterator and
            "while (segment < ctx->segment_count)" in iterator and
            "ctx->segment_backing_pages[segment - 1U]" in iterator and
            "(sector_t)(segment - start_segment) *" in iterator,
            "Sparse iterate_devices must report only contiguous clean runs")

    # Every submitted lower data I/O must widen the protected-page offset
    # before adding a data block. A cast after u32 addition could silently
    # wrap large address spaces back to physical block zero.
    require(
        "return ((sector_t)ctx->data_start_block + data_block) * "
        "SWAPZ_SECTORS;" in target,
        "The shared backing-data sector helper must widen before addition")
    require(
        target.count("region.sector = swapz_backing_data_sector(ctx,") == 4,
        "Synchronous, async WRITE, parallel READ and async READ must use "
        "the same protected-page sector conversion")
    discard = target.split("static int swapz_discard_dead_segment(", 1)[1].split(
        "\nstatic int swapz_parallel_lower_read(", 1)[0]
    require("start_sector = swapz_backing_data_sector(" in discard,
            "GC DISCARD must retain the same protected-page address translation")
    require(
        "(sector_t)(ctx->data_start_block +" not in target,
        "Never add 32-bit protected-page offsets before widening")

    print("PASS: RAM-only production metadata and protected SWAPSPACE2 data range")


if __name__ == "__main__":
    main()
