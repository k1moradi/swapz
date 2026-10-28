# SPDX-License-Identifier: GPL-2.0-only
ifneq ($(KERNELRELEASE),)
obj-m += dm-swapz.o
dm-swapz-y := dm-target.o codec.o authority.o engine.o predictor.o

# dm-io's unsupported-operation bitmap/callback argument was backported by
# some distributions before its upstream kernel version. Probe the installed
# build header instead of guessing from LINUX_VERSION_CODE.
ifneq ($(shell grep -q 'sync_unsup_bits' "$(srctree)/include/linux/dm-io.h" 2>/dev/null && echo y),)
CFLAGS_dm-target.o += -DSWAPZ_DM_IO_HAS_UNSUPPORTED_BITS
endif

ifeq ($(CONFIG_X86_64),y)
dm-swapz-y += predictor-sse2.o predictor-avx2.o predictor-avx512.o
CFLAGS_predictor-sse2.o += $(CC_FLAGS_FPU)
CFLAGS_REMOVE_predictor-sse2.o += -mno-sse -mno-sse2
CFLAGS_predictor-avx2.o += $(CC_FLAGS_FPU) -mavx2
CFLAGS_REMOVE_predictor-avx2.o += -mno-sse -mno-sse2 -mno-avx
CFLAGS_predictor-avx512.o += $(CC_FLAGS_FPU) -mavx512f
CFLAGS_REMOVE_predictor-avx512.o += -mno-sse -mno-sse2 -mno-avx -mno-avx2 -mno-avx512f
endif

ifeq ($(CONFIG_ARM64),y)
ifeq ($(CONFIG_KERNEL_MODE_NEON),y)
dm-swapz-y += predictor-neon.o
CFLAGS_predictor-neon.o += $(CC_FLAGS_FPU)
CFLAGS_REMOVE_predictor-neon.o += $(CC_FLAGS_NO_FPU)
endif
endif
else
KDIR ?= /lib/modules/$(shell uname -r)/build
SWAPZ_ROOT := $(abspath $(CURDIR)/../..)
ifeq ($(W),1)
SWAPZ_STAGE := $(SWAPZ_ROOT)/build/kernel/w1
else ifeq ($(W),2)
SWAPZ_STAGE := $(SWAPZ_ROOT)/build/kernel/w2
else
SWAPZ_STAGE := $(SWAPZ_ROOT)/build/kernel/experimental
endif
.PHONY: all clean
all:
	@mkdir -p "$(SWAPZ_STAGE)"
	@set -e; for src in "$(CURDIR)/Makefile" "$(CURDIR)"/*.c "$(CURDIR)"/*.h; do \
		dst="$(SWAPZ_STAGE)/$${src##*/}"; \
		if ! cmp -s "$$src" "$$dst"; then cp -f "$$src" "$$dst"; fi; \
	done
	@set -e; version="$$(cat "$(CURDIR)/VERSION")"; \
	  printf '%s\n' "$$version" | grep -Eq '^3[.]0[.]0-alpha[.][0-9]+$$' || \
	    { echo "BLOCKED: invalid canonical VERSION" >&2; exit 1; }; \
	  header="$(SWAPZ_STAGE)/swapz-version.h"; \
	  if ! printf '#define SWAPZ_ALPHA_VERSION "%s"\n' "$$version" | cmp -s - "$$header"; then \
	    printf '#define SWAPZ_ALPHA_VERSION "%s"\n' "$$version" > "$$header"; \
	  fi
	$(MAKE) -C "$(KDIR)" M="$(SWAPZ_STAGE)" modules

clean:
	@if test -d "$(SWAPZ_STAGE)" && test -f "$(KDIR)/Makefile"; then \
	  $(MAKE) -C "$(KDIR)" M="$(SWAPZ_STAGE)" clean; \
	fi
endif
