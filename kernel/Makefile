# Kbuild source, executed when included by the kernel build system.
ifneq ($(KERNELRELEASE),)
obj-m += dm-swapz.o
else
KDIR ?= /lib/modules/$(shell uname -r)/build
# Stage exact source copies inside the ONE persistent repository build tree.
# This works even with older kernels that do not support Kbuild MO=.
SWAPZ_ROOT := $(abspath $(CURDIR)/..)
SWAPZ_STAGE := $(SWAPZ_ROOT)/build/kernel/stable

.PHONY: all clean
all:
	@mkdir -p "$(SWAPZ_STAGE)"
	@cp -f "$(CURDIR)/Makefile" "$(CURDIR)/dm-swapz.c" "$(SWAPZ_STAGE)/"
	$(MAKE) -C "$(KDIR)" M="$(SWAPZ_STAGE)" modules

clean:
	@if test -d "$(SWAPZ_STAGE)" && test -f "$(KDIR)/Makefile"; then \
	  $(MAKE) -C "$(KDIR)" M="$(SWAPZ_STAGE)" clean; \
	fi
endif
