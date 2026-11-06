# Exactly five public root Make goals; never add aliases or extra targets.
# make fast_test is a development-only decision loop; make test alone qualifies.
.DEFAULT_GOAL := all
# The internal default target is not an additional user-visible alias.
# Disallow explicitly specifying it or combining supported goals.
ifneq ($(strip $(MAKECMDGOALS)),)
ifeq ($(filter $(MAKECMDGOALS),install uninstall test fast_test),)
$(error Only make, make install, make uninstall, make test, make fast_test are supported)
endif
ifneq ($(words $(MAKECMDGOALS)),1)
$(error Specify exactly one supported Make command)
endif
endif

KDIR ?= /lib/modules/$(shell uname -r)/build
PREFIX ?= /usr/local
CC ?= cc

SWAPZ_BUILD_SOURCE_SHA := $(shell git log -1 --format=%H HEAD -- . ':(exclude)test_results.json' 2>/dev/null | grep -E '^[0-9a-f]{40}$$' | head -n 1)
ifeq ($(strip $(SWAPZ_BUILD_SOURCE_SHA)),)
SWAPZ_BUILD_SOURCE_SHA := unknown
SWAPZ_BUILD_SOURCE_CLEAN := 0
else
SWAPZ_BUILD_SOURCE_CLEAN := $(shell \
	if test -z "$$(git status --porcelain --untracked-files=all -- \
		src/kernel src/userspace Makefile packaging 2>/dev/null)"; \
	then echo 1; else echo 0; fi)
endif

.PHONY: build/source-build-info-force
build/source-build-info.h: build/source-build-info-force
	@set -eu; mkdir -p build; tmp="$@.tmp.$$$$"; \
	  printf '%s\n' '#define SWAPZ_BUILD_SOURCE_SHA "$(SWAPZ_BUILD_SOURCE_SHA)"' \
		'#define SWAPZ_BUILD_SOURCE_CLEAN $(SWAPZ_BUILD_SOURCE_CLEAN)' \
		'#define SWAPZ_BUILD_SOURCE_CLEAN_STRING "$(SWAPZ_BUILD_SOURCE_CLEAN)"' > "$$tmp"; \
	  if ! cmp -s "$$tmp" "$@"; then mv -f "$$tmp" "$@"; \
	  else rm -f "$$tmp"; fi

.PHONY: all install uninstall test fast_test
.PHONY: build/kernel/experimental/dm-swapz.ko
# Make can compile independent outputs concurrently. The private test reporter
# chooses a bounded CPU-aware job count automatically when no parent jobserver
# exists; an explicit inherited GNU Make jobserver still takes precedence.
# The module recipe always checks running-kernel Kbuild; Kbuild's own
# incremental dependency logic avoids unchanged .o recompilation.
all: build/kernel/experimental/dm-swapz.ko build/tests/device-roundtrip build/userspace/swapzctl
	@chmod 0644 build/source-build-info.h build/kernel/experimental/dm-swapz.ko
	@chmod 0755 build/tests/device-roundtrip build/userspace/swapzctl

build/kernel/experimental/dm-swapz.ko: build/source-build-info.h
	$(MAKE) -C src/kernel KDIR="$(KDIR)" SWAPZ_BUILD_INFO="$(abspath build/source-build-info.h)" all
	@bash packaging/sign-module.sh "$@"

build/tests/device-roundtrip: tests/tools/device-roundtrip.c Makefile build/tests/direct-write-probe build/tests/direct-read-probe
	@mkdir -p build/tests
	$(CC) -std=c11 -O2 -g -Wall -Wextra -Werror -pthread $< -o $@

build/tests/direct-write-probe: tests/tools/direct-write-probe.c Makefile
	@mkdir -p build/tests
	$(CC) -std=c11 -O2 -g -Wall -Wextra -Werror $< -o $@

build/tests/direct-read-probe: tests/tools/direct-read-probe.c Makefile
	@mkdir -p build/tests
	$(CC) -std=c11 -O2 -g -Wall -Wextra -Werror $< -o $@

build/userspace/swapzctl: src/userspace/swapzctl.c src/userspace/swapz-primary.c src/userspace/swapz-primary.h src/kernel/VERSION src/kernel/authority.h src/kernel/codec.h src/kernel/superblock.h src/kernel/swapz-build-info.h build/source-build-info.h Makefile
	@mkdir -p build/userspace
	$(CC) -std=c11 -O2 -g -Wall -Wextra -Werror -include build/source-build-info.h '-DSWAPZ_VERSION="$(shell cat src/kernel/VERSION)"' src/userspace/swapzctl.c src/userspace/swapz-primary.c -o $@

# Installation is admission-only: preserve the exact artifacts and provenance
# already qualified by make test instead of rebuilding after a report-only commit.
install:
	@sudo bash packaging/package-dkms.sh install "$(PREFIX)"

uninstall:
	@sudo bash packaging/package-dkms.sh uninstall "$(PREFIX)"

# The only public test goal: all stages are run by the private,
# bounded reporter, which replaces one JSON report on PASS/FAIL/BLOCKED.
# The + preserves GNU Make jobserver FDs for parallel compilation;
# the reporter completes each stage before starting the next.
test:
	@+python3 -B tests/tools/run-tests.py --kdir "$(KDIR)"

# Development-only K=1 profiling loop: build, native/replay checks and three
# paired owned-null_blk repeats for sata-mixed, nvme4-mixed, nvme5-mixed,
# fast-mixed, fast-w4 and fast-w8, with raw/swapz and critical-path tables.
# SCENARIOS=nvme5-stripes (or sata-stripes) runs the mixed N=1/2/4
# independent-target experiment; fast-stripes-w4/fast-stripes-w8 exercise
# sustained WRITE QD4/QD8 with the same unchanged production K=1 target.
# All emulated-device scenarios use the production delta64 + DELTA64_SHUF8
# 8-byte byte-plane shuffle (not bit-level bitshuffle) + LZ4 stack; no
# delta64-off benchmark selector. SUBMITTER_PREPARE=0 selects the existing
# opt-out in ordinary fast_test pairs. HAND_RECORDS=8|16|64 selects the
# null_blk-only work-conserving hand
# threshold (8 is the unchanged production default). HOST_LOAD_PROFILE=
# browser-video-144p labels background-load results without relaxing screens.
# RESUME=1 reuses only matching private native/replay checkpoints;
# product build and environment-dependent loaded preflight always rerun.
# It accepts dirty trees, honors the noise screen, never writes
# test_results.json and never qualifies a source. Override with
# SCENARIOS=... and/or REPEAT=1..10 when narrowing a follow-up.
# MIXED_OPS=65536 extends ordinary mixed-only development traces; the default
# remains 16384. It changes neither make test nor the performance screens.
fast_test:
	@+python3 -B tests/tools/fast-test.py
