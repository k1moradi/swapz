# SPDX-License-Identifier: GPL-2.0-only
# Independent module; never linked to the existing dm-swapz.ko target.
ifneq ($(KERNELRELEASE),)
obj-m += swapz_extent_v3.o
swapz_extent_v3-y := codec.o authority.o smoke.o
else
KDIR ?= /lib/modules/$(shell uname -r)/build

.PHONY: all clean
all:
	$(MAKE) -C $(KDIR) M=$(CURDIR) modules

clean:
	$(MAKE) -C $(KDIR) M=$(CURDIR) clean
endif
