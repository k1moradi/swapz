# Exactly four public root Make goals; never add aliases or extra targets.
.DEFAULT_GOAL := all
# The internal default target is not an additional user-visible alias.
# Disallow explicitly specifying it or combining supported goals.
ifneq ($(strip $(MAKECMDGOALS)),)
ifeq ($(filter $(MAKECMDGOALS),install uninstall test),)
$(error Only make -j2, make install, make uninstall, make test are supported)
endif
ifneq ($(words $(MAKECMDGOALS)),1)
$(error Specify exactly one supported Make command)
endif
endif
KDIR ?= /lib/modules/$(shell uname -r)/build
PREFIX ?= /usr/local
CC ?= cc
.PHONY: all install uninstall test

all:
	$(MAKE) -C kernel/extent-v3 KDIR="$(KDIR)" all
	@mkdir -p build/tests build/userspace
	$(CC) -std=c11 -O2 -g -Wall -Wextra -Werror tools/device-roundtrip.c -o build/tests/device-roundtrip
	$(CC) -std=c11 -O2 -g -Wall -Wextra -Werror '-DSWAPZ_VERSION="$(shell cat kernel/extent-v3/VERSION)"' userspace/swapz3ctl.c -o build/userspace/swapz3ctl

install: all
	@sudo bash tools/package-dkms.sh install "$(PREFIX)"

uninstall:
	@sudo bash tools/package-dkms.sh uninstall "$(PREFIX)"

.NOTPARALLEL: test
test: all
	@bash tools/test-rootless.sh
	@$(MAKE) -C kernel/extent-v3 KDIR="$(KDIR)" W=1 all
	@$(MAKE) -C kernel/extent-v3 KDIR="$(KDIR)" W=2 all
