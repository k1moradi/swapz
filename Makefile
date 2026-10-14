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
	bash -n tools/deploy-nullblk.sh
	@grep -Fq -- 'dmsetup create "$$DMNAME" --uuid "$$UUID"' tools/deploy-nullblk.sh
	@grep -Fq -- 'memory_backed' tools/deploy-nullblk.sh
	@grep -Fq -- 'dmsetup remove "$$DMNAME"' tools/deploy-nullblk.sh
	@printf 'PASS: V3 production C, replay, preflight shell contracts\n'

build/tests/device-roundtrip: tools/device-roundtrip.c
	@mkdir -p build/tests
	$(CC) -std=c11 -O2 -g -Wall -Wextra -Werror $< -o $@

# All unprivileged gates must pass BEFORE privileged deployment.
deploy: verify v3 build/tests/device-roundtrip
	@printf 'Loading V3 ONLY onto a fresh owned RAM-backed null_blk.\n'
	@printf 'This will never swapon/swapoff, reboot or touch physical storage.\n'
	sudo bash tools/deploy-nullblk.sh
