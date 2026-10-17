# SPDX-License-Identifier: GPL-2.0-only
# Actual Device Mapper target and research smoke are NEVER linked together.
ifneq ($(KERNELRELEASE),)
ifeq ($(SWAPZ_BUILD_SMOKE),1)
obj-m += swapz_extent.o
swapz_extent-y := codec.o authority.o engine.o smoke.o
else
obj-m += dm-swapz.o
dm-swapz-y := dm-target.o codec.o authority.o engine.o
endif
else
KDIR ?= /lib/modules/$(shell uname -r)/build
SWAPZ_ROOT := $(abspath $(CURDIR)/../..)
ifeq ($(SWAPZ_BUILD_SMOKE),1)
SWAPZ_STAGE := $(SWAPZ_ROOT)/build/kernel/research
else ifeq ($(W),1)
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
	$(MAKE) -C "$(KDIR)" M="$(SWAPZ_STAGE)" SWAPZ_BUILD_SMOKE="$(SWAPZ_BUILD_SMOKE)" modules

clean:
	@if test -d "$(SWAPZ_STAGE)" && test -f "$(KDIR)/Makefile"; then \
	  $(MAKE) -C "$(KDIR)" M="$(SWAPZ_STAGE)" clean; \
	fi
endif
