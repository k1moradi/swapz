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
    target = (ROOT / "src/kernel/dm-target.c").read_text(encoding="utf-8")
    declarations = re.findall(
        r"(?m)^#define SWAPZ_CODEC_METADATA_ON_MEDIA ([01])U$", codec
    )
    require(declarations == ["1"], "Legacy in-band codec must retain its physical interlock")
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

    print("PASS: in-band codec cannot admit real physical backing (source contract)")


if __name__ == "__main__":
    main()
