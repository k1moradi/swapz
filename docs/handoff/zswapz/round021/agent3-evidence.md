# Round 021 Agent 3 — fixed-host read-only source/loaded qualification

Official source: https://github.com/k1moradi/swapz/issues/138#issuecomment-6924146448

The Round020 candidate parser and exact-one upper ACK/full 4096-byte offline
readback comparator remain fail-closed. A candidate manifest, successful
modified Linux KUnit y/n or linked external dm-swapz.ko build cannot certify
the actual boot image, loaded bytes or a genuine stored-entry eviction.

This round adds fixed /proc and /sys **read-only** inspection to the existing
candidate script: nofollow bounded regular-file reads, stable descriptor
identity, strict boot-id/release format, real dm_swapz initstate=live and
structural checking of its GNU ELF build-ID note. New --inspect-host is
nonmutating, suppresses host identifiers and ALWAYS refuses with exit 2,
LOADED_STORED_ENTRY=NOT_RUN, 4096_READBACK=NOT_RUN and Phase A BLOCKED,
including when the host metadata is internally consistent. A sysfs note
does NOT independently authenticate actual loaded module bytes, exact Linux
source, owner authority or RAM-only backing; owner-provided witness and
verified loaded module byte identity remain unavailable. Rootless test cases
use disposable module/boot fixtures, not a kernel or device.

No cgroup pressure, actual zswap stored-entry, MM/BIO write, module load,
RAM swapin, physical swap or disk modification was authorized or performed.
Historical KUnit y/n 5/5 and matched source-linked Kbuild remain evidence
of SOURCE/BUILD only, not loaded/physical Phase A. Current swapz RAW = original
uncompressed 4096-byte page; Phase B forced RAW bypass and direct compressed
handoff DISABLED.
