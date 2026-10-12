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
# V3 uses the established production module artifact name.  The V2.2
# module with the same basename exists ONLY in its separate kernel/ build;
# these are alternative implementations, not loadable side by side.
obj-m += dm-swapz.o
dm-swapz-y := dm-target.o codec.o authority.o engine.o
endif
else
KDIR ?= /lib/modules/$(shell uname -r)/build

.PHONY: all clean
all:
	$(MAKE) -C $(KDIR) M=$(CURDIR) SV3_BUILD_SMOKE=$(SV3_BUILD_SMOKE) modules

clean:
	$(MAKE) -C $(KDIR) M=$(CURDIR) clean
endif
