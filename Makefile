# Exactly four public root Make goals; never add aliases or extra targets.
.DEFAULT_GOAL := all
# The internal default target is not an additional user-visible alias.
# Disallow explicitly specifying it or combining supported goals.
ifneq ($(strip $(MAKECMDGOALS)),)
ifeq ($(filter $(MAKECMDGOALS),install uninstall test),)
$(error Only make, make install, make uninstall, make test are supported)
endif
ifneq ($(words $(MAKECMDGOALS)),1)
$(error Specify exactly one supported Make command)
endif
endif

KDIR ?= /lib/modules/$(shell uname -r)/build
PREFIX ?= /usr/local
CC ?= cc

.PHONY: all install uninstall test
.PHONY: build/kernel/experimental/dm-swapz.ko
# Make can compile independent outputs concurrently (make test -j2).
# The module recipe always checks running-kernel Kbuild; Kbuild's own
# incremental dependency logic avoids unchanged .o recompilation.
all: build/kernel/experimental/dm-swapz.ko build/tests/device-roundtrip build/userspace/swapz3ctl

build/kernel/experimental/dm-swapz.ko:
	$(MAKE) -C kernel/extent-v3 KDIR="$(KDIR)" all

build/tests/device-roundtrip: tools/device-roundtrip.c Makefile
	@mkdir -p build/tests
	$(CC) -std=c11 -O2 -g -Wall -Wextra -Werror $< -o $@

build/userspace/swapz3ctl: userspace/swapz3ctl.c kernel/extent-v3/VERSION Makefile
	@mkdir -p build/userspace
	$(CC) -std=c11 -O2 -g -Wall -Wextra -Werror '-DSWAPZ_VERSION="$(shell cat kernel/extent-v3/VERSION)"' $< -o $@

install: all
	@sudo bash tools/package-dkms.sh install "$(PREFIX)"

uninstall:
	@sudo bash tools/package-dkms.sh uninstall "$(PREFIX)"

# Do not use .NOTPARALLEL here: it disables parallel compilation too.
# A single recipe is an ordered gate: rootless tests, W=1, W=2, then
# privileged isolated devices. Each command must succeed before the next.
test: all
	@+bash tools/test-rootless.sh
	@$(MAKE) -C kernel/extent-v3 KDIR="$(KDIR)" W=1 all
	@$(MAKE) -C kernel/extent-v3 KDIR="$(KDIR)" W=2 all
	@bash tools/test-loaded.sh
