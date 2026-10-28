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
# Make can compile independent outputs concurrently. The private test reporter
# chooses a bounded CPU-aware job count automatically when no parent jobserver
# exists; an explicit inherited GNU Make jobserver still takes precedence.
# The module recipe always checks running-kernel Kbuild; Kbuild's own
# incremental dependency logic avoids unchanged .o recompilation.
all: build/kernel/experimental/dm-swapz.ko build/tests/device-roundtrip build/userspace/swapzctl

build/kernel/experimental/dm-swapz.ko:
	$(MAKE) -C src/kernel KDIR="$(KDIR)" all
	@bash packaging/sign-module.sh "$@"

build/tests/device-roundtrip: tests/tools/device-roundtrip.c Makefile build/tests/direct-write-probe
	@mkdir -p build/tests
	$(CC) -std=c11 -O2 -g -Wall -Wextra -Werror $< -o $@

build/tests/direct-write-probe: tests/tools/direct-write-probe.c Makefile
	@mkdir -p build/tests
	$(CC) -std=c11 -O2 -g -Wall -Wextra -Werror $< -o $@

build/userspace/swapzctl: src/userspace/swapzctl.c src/kernel/VERSION src/kernel/superblock.h Makefile
	@mkdir -p build/userspace
	$(CC) -std=c11 -O2 -g -Wall -Wextra -Werror '-DSWAPZ_VERSION="$(shell cat src/kernel/VERSION)"' $< -o $@

install: all
	@sudo bash packaging/package-dkms.sh install "$(PREFIX)"

uninstall:
	@sudo bash packaging/package-dkms.sh uninstall "$(PREFIX)"

# The only public test goal: all stages are run by the private,
# bounded reporter, which replaces one XZ result on PASS/FAIL/BLOCKED.
# The + preserves GNU Make jobserver FDs for parallel compilation;
# the reporter completes each stage before starting the next.
test:
	@+python3 -B tests/tools/run-tests.py --kdir "$(KDIR)"
