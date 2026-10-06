# Validation performed in the build environment

Date: 2026-10-06

The environment did not provide Linux 7.0.x headers or permission to boot/load a matching test kernel, so kernel runtime validation remains outstanding.

Completed successfully:

```text
Kernel module GCC build:
  Linux headers: Debian 6.12.96+deb13-amd64
  flags: W=1
  result: PASS, no compiler warnings emitted

Kernel module Clang build:
  Linux headers: Debian 6.12.96+deb13-amd64
  flags: W=1 LLVM=1
  result: PASS, no compiler warnings emitted

swapzctl:
  C++23, -O2 -Wall -Wextra -Wpedantic -Wconversion -Wshadow
  result: PASS, no compiler warnings emitted

Allocator/storage model:
  C++23 + liblz4
  deterministic tests: PASS
  randomized 5,000-operation rewrite/read/discard test: PASS
  forced arena rotation tests: PASS

Sanitizers:
  AddressSanitizer + UndefinedBehaviorSanitizer
  allocator/storage model: PASS

Shell scripts:
  bash -n: PASS
```

Linux 7.0 source review confirmed that the public interfaces this target is designed around are present there, including Device Mapper per-BIO data, `discards_supported`, `dm_set_target_max_io_len`, `dm-io`, and the kernel LZ4 interface.  An exact 7.0.x module build is still a required first gate on the real test systems.