# V3 is the active development head. Building does not load a module or touch swap.
KDIR ?= /lib/modules/$(shell uname -r)/build
.PHONY: all kernel v3 experimental-kernel v3-smoke legacy-v22 userspace-legacy test test-codec test-mapping test-gc test-lower-io clean
all: v3
kernel v3 experimental-kernel:
	$(MAKE) -C kernel/extent-v3 KDIR="$(KDIR)" all
v3-smoke:
	$(MAKE) -C kernel/extent-v3 KDIR="$(KDIR)" SV3_BUILD_SMOKE=1 all
# Historical source only; not a required benchmark or default build.
legacy-v22:
	$(MAKE) -C kernel KDIR="$(KDIR)" all
userspace-legacy:
	$(MAKE) -C userspace all
test:
	$(MAKE) -C tests test
test-codec test-mapping test-gc test-lower-io:
	$(MAKE) -C tests/suites $@
clean:
	$(MAKE) -C tests clean
	$(MAKE) -C kernel/extent-v3 KDIR="$(KDIR)" clean
	$(MAKE) -C kernel/extent-v3 KDIR="$(KDIR)" SV3_BUILD_SMOKE=1 clean
	$(MAKE) -C kernel KDIR="$(KDIR)" clean
	$(MAKE) -C userspace clean

# Automated rootless and isolated loaded-kernel development loop.
# "deploy" is EPHEMERAL: it may load V3 only against newly owned RAM null_blk.
CC ?= cc
.PHONY: verify deploy
verify: test
	python3 -B tests/runtime/native/source-contract-test.py -v
	python3 -B tests/runtime/benchmark/io-replay-test.py -v
	bash -n tools/deploy-nullblk.sh tools/quiet-lower-io.sh tools/benchmark-owned-pair.sh tools/nullblk-identity.sh tests/runtime/native/nullblk-identity-test.sh tests/runtime/native/quiet-lower-io-test.sh tests/runtime/benchmark/owned-pair-preflight-test.sh
	bash tests/runtime/native/nullblk-identity-test.sh
	bash tests/runtime/native/quiet-lower-io-test.sh
	bash tests/runtime/benchmark/owned-pair-preflight-test.sh
	@grep -Fq -- 'dmsetup create "$$DMNAME" --uuid "$$UUID"' tools/deploy-nullblk.sh
	@grep -Fq -- 'memory_backed' tools/deploy-nullblk.sh
	@grep -Fq -- 'dmsetup remove' tools/deploy-nullblk.sh
	@grep -Fq -- 'PASS_ZERO_WRITE_LOWER_IO=' tools/deploy-nullblk.sh
	@grep -Fq -- 'zero_writes == 9' tools/deploy-nullblk.sh
	@grep -Fq -- 'lower_write_bytes == target_write_bytes' tools/deploy-nullblk.sh
	@grep -Fq -- 'lower_read_bytes != target_read_bytes' tools/deploy-nullblk.sh
	@grep -Fq -- 'swapz_capture_quiescent_io' tools/deploy-nullblk.sh
	@grep -Fq -- 'UNATTRIBUTED_LOWER_READ=' tools/deploy-nullblk.sh
	@grep -Fq -- 'PASS_ORACLE_LOWER_READ=' tools/deploy-nullblk.sh
	@grep -Fq -- 'close_total == window_delta' tools/deploy-nullblk.sh
	@grep -Fq -- 'PASS_WINDOW_CLOSE_REASONS=' tools/deploy-nullblk.sh
	@printf 'PASS: V3 production C, replay, preflight shell contracts\n'

build/tests/device-roundtrip: tools/device-roundtrip.c
	@mkdir -p build/tests
	$(CC) -std=c11 -O2 -g -Wall -Wextra -Werror $< -o $@

# Ordered one-command pipeline: never parallelize safety checks and loading.
# "run" deploys ephemerally only on a fresh owned memory-backed null_blk;
# it never installs a persistent module or changes the system swap.
.PHONY: run check
check: verify

run:
	@$(MAKE) --no-print-directory verify
	@$(MAKE) --no-print-directory -C kernel/extent-v3 KDIR="$(KDIR)" W=1 all
	@$(MAKE) --no-print-directory -C kernel/extent-v3 KDIR="$(KDIR)" W=2 all
	@$(MAKE) --no-print-directory build/tests/device-roundtrip
	@printf 'All checks passed; attempting isolated RAM-backed V3 deployment.\n'
	@sudo bash tools/deploy-nullblk.sh

# Backwards-compatible spelling for the same ordered isolated test.
deploy: run

# Separate explicitly authorized RAM-only paired performance pilot.
.PHONY: bench-pair
bench-pair:
	@$(MAKE) --no-print-directory verify
	@$(MAKE) --no-print-directory -C kernel/extent-v3 KDIR="$(KDIR)" W=1 all
	@$(MAKE) --no-print-directory -C kernel/extent-v3 KDIR="$(KDIR)" W=2 all
	@sudo bash tools/benchmark-owned-pair.sh --run-owned-ram-pair
