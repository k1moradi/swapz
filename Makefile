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
