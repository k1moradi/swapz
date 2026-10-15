# Owner-approved PUBLIC API: only make -j2, make install, make uninstall, make test.
# Subdirectory Kbuild and native-suite make recipes are internal implementation.
.DEFAULT_GOAL := all
KDIR ?= /lib/modules/$(shell uname -r)/build
PREFIX ?= /usr/local
CC ?= cc
.PHONY: all install uninstall test

# Building never loads the module or accesses host swap.
# Kbuild's recursive make inherits the -j2 jobserver.
all:
	$(MAKE) -C kernel/extent-v3 KDIR="$(KDIR)" all
	@mkdir -p build/tests
	$(CC) -std=c11 -O2 -g -Wall -Wextra -Werror tools/device-roundtrip.c -o build/tests/device-roundtrip

# Install only an experimental V3 DKMS module and the owned-device helper.
# Never install retired V2 swapzctl (it invokes swapon/swapoff).
install: all
	@sudo bash tools/package-dkms.sh install "$(PREFIX)"

uninstall:
	@sudo bash tools/package-dkms.sh uninstall "$(PREFIX)"

# Every current test and benchmark, rootless first and then safely owned
# RAM-backed null_blk only. Fail closed on missing sudo/headers/devices.
# Preserve the order even when invoked with -j2.
.NOTPARALLEL: test
test: all
	@bash tools/test-rootless.sh
	@$(MAKE) -C kernel/extent-v3 KDIR="$(KDIR)" W=1 all
	@$(MAKE) -C kernel/extent-v3 KDIR="$(KDIR)" W=2 all
	@sudo -v
	@sudo bash tools/deploy-nullblk.sh
	@sudo bash tools/benchmark-owned-pair.sh --run-owned-ram-pair
	@sudo bash tools/benchmark-owned-pair.sh --run-owned-ram-pair --profile medium
	@sudo bash tools/benchmark-owned-pair.sh --run-owned-ram-pair --profile medium --retain-ms 2
	@sudo bash tools/benchmark-owned-pair.sh --run-owned-ram-pair --profile medium --retain-ms 2 --unpaced
	@sudo bash tools/benchmark-owned-pair.sh --run-owned-ram-pair --profile medium --retain-ms 1 --unpaced
