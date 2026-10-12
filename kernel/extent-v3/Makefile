# SPDX-License-Identifier: GPL-2.0-only
#
# V3 alpha has two MUTUALLY EXCLUSIVE, independently linked module builds.
# Default builds the actual Device Mapper target; the legacy memory-only
# validation module must be selected explicitly (SV3_BUILD_SMOKE=1).
# Building both from the same .o names emits Kbuild duplicate-object warnings
# and risks ambiguous modpost provenance. Never ship them together.
ifneq ($(KERNELRELEASE),)
ifeq ($(SV3_BUILD_SMOKE),1)
obj-m += swapz_extent_v3.o
swapz_extent_v3-y := codec.o authority.o engine.o smoke.o
else
obj-m += dm-swapz3.o
dm-swapz3-y := dm-target.o codec.o authority.o engine.o
endif
else
KDIR ?= /lib/modules/$(shell uname -r)/build

.PHONY: all clean
all:
	$(MAKE) -C $(KDIR) M=$(CURDIR) SV3_BUILD_SMOKE=$(SV3_BUILD_SMOKE) modules

clean:
	$(MAKE) -C $(KDIR) M=$(CURDIR) clean
endif
