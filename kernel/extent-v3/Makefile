# SPDX-License-Identifier: GPL-2.0-only
# Actual Device Mapper target and research smoke are NEVER linked together.
ifneq ($(KERNELRELEASE),)
ifeq ($(SV3_BUILD_SMOKE),1)
obj-m += swapz_extent_v3.o
swapz_extent_v3-y := codec.o authority.o engine.o smoke.o
else
obj-m += dm-swapz.o
dm-swapz-y := dm-target.o codec.o authority.o engine.o
endif
else
KDIR ?= /lib/modules/$(shell uname -r)/build
SWAPZ_ROOT := $(abspath $(CURDIR)/../..)
ifeq ($(SV3_BUILD_SMOKE),1)
SWAPZ_STAGE := $(SWAPZ_ROOT)/build/kernel/research
else
SWAPZ_STAGE := $(SWAPZ_ROOT)/build/kernel/experimental
endif
.PHONY: all clean
all:
	@mkdir -p "$(SWAPZ_STAGE)"
	@cp -f "$(CURDIR)/Makefile" "$(CURDIR)"/*.c "$(CURDIR)"/*.h "$(SWAPZ_STAGE)/"
	$(MAKE) -C "$(KDIR)" M="$(SWAPZ_STAGE)" SV3_BUILD_SMOKE="$(SV3_BUILD_SMOKE)" modules

clean:
	@if test -d "$(SWAPZ_STAGE)" && test -f "$(KDIR)/Makefile"; then \
	  $(MAKE) -C "$(KDIR)" M="$(SWAPZ_STAGE)" clean; \
	fi
endif
