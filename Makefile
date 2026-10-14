# Unified reusable build root: all artifacts remain inside ./build/.
KDIR ?= /lib/modules/$(shell uname -r)/build

.PHONY: all kernel experimental-kernel userspace test test-codec test-mapping test-gc test-lower-io clean
all: kernel userspace

kernel:
	$(MAKE) -C kernel KDIR="$(KDIR)" all

experimental-kernel:
	$(MAKE) -C kernel/extent-v3 KDIR="$(KDIR)" all

userspace:
	$(MAKE) -C userspace all

test:
	$(MAKE) -C tests test

test-codec test-mapping test-gc test-lower-io:
	$(MAKE) -C tests/suites $@

clean:
	$(MAKE) -C tests clean
	$(MAKE) -C userspace clean
	$(MAKE) -C kernel KDIR="$(KDIR)" clean
	$(MAKE) -C kernel/extent-v3 KDIR="$(KDIR)" clean
