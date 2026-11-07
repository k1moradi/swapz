# SPDX-License-Identifier: GPL-2.0-only
ifneq ($(KERNELRELEASE),)
obj-m += dm-swapz.o
dm-swapz-y := dm-target.o codec.o authority.o engine.o predictor.o

# dm-io's unsupported-operation bitmap/callback argument was backported by
# some distributions before its upstream kernel version. Probe the installed
# build header directly instead of inferring this ABI from a release number.
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
# Root builds pass a generated header; direct compile-only Kbuild may use unknown/0.
SWAPZ_EXPLICIT_BUILD_INFO := $(if $(filter undefined,$(origin SWAPZ_BUILD_INFO)),,1)
SWAPZ_BUILD_INFO ?= $(SWAPZ_ROOT)/build/source-build-info.h
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
# Keep the staged tree source-exact while preserving Kbuild-generated files.
	@set -eu; \
	fail_stage() { \
		status="$$1"; phase="$$2"; \
		rm -f "$(SWAPZ_STAGE)/dm-swapz.ko" || true; \
		printf 'FAIL_KERNEL_STAGE phase=%s exit=%s\n' "$$phase" "$$status" >&2; \
		exit "$$status"; \
	}; \
	invalidate_candidate() { \
		rm -f "$(SWAPZ_STAGE)/dm-swapz.ko" || \
			fail_stage "$$?" candidate-invalidate; \
	}; \
	for staged in "$(SWAPZ_STAGE)"/*.c "$(SWAPZ_STAGE)"/*.h; do \
		test -e "$$staged" || continue; \
		staged_name="$${staged##*/}"; \
		case "$$staged_name" in \
			*.mod.c|swapz-build-info.h|swapz-version.h) continue ;; \
		esac; \
		if ! test -f "$(CURDIR)/$$staged_name"; then \
			invalidate_candidate; \
			rm -f "$$staged" || fail_stage "$$?" source-prune; \
		fi; \
	done; \
	for src in "$(CURDIR)/Makefile" "$(CURDIR)"/*.c "$(CURDIR)"/*.h; do \
		staged_name="$${src##*/}"; \
		case "$$staged_name" in swapz-build-info.h) continue ;; esac; \
		dst="$(SWAPZ_STAGE)/$$staged_name"; \
		if ! cmp -s "$$src" "$$dst"; then \
			invalidate_candidate; \
			cp -f "$$src" "$$dst" || fail_stage "$$?" source-copy; \
		fi; \
	done; \
	if test "$(SWAPZ_EXPLICIT_BUILD_INFO)" = 1; then \
		build_info_source="$(SWAPZ_BUILD_INFO)"; \
		if ! test -f "$$build_info_source"; then \
			echo "BLOCKED_KERNEL_STAGE: missing generated source-build-info.h: $$build_info_source" >&2; \
			fail_stage 1 build-info; \
		fi; \
	else \
		build_info_source="$(CURDIR)/swapz-build-info.h"; \
		if ! test -f "$$build_info_source"; then \
			echo "BLOCKED_KERNEL_STAGE: missing build info header: $$build_info_source" >&2; \
			fail_stage 1 build-info; \
		fi; \
	fi; \
	if ! cmp -s "$$build_info_source" "$(SWAPZ_STAGE)/swapz-build-info.h"; then \
		invalidate_candidate; \
		cp -f "$$build_info_source" "$(SWAPZ_STAGE)/swapz-build-info.h" || \
			fail_stage "$$?" build-info-copy; \
	fi; \
	version="$$(cat "$(CURDIR)/VERSION")" || fail_stage "$$?" version-read; \
	printf '%s\n' "$$version" | grep -Eq '^3[.]0[.]0-alpha[.][0-9]+$$' || \
		{ echo "BLOCKED: invalid canonical VERSION" >&2; \
		  fail_stage 1 version-validate; }; \
	header="$(SWAPZ_STAGE)/swapz-version.h"; \
	if ! printf '#define SWAPZ_ALPHA_VERSION "%s"\n' "$$version" | cmp -s - "$$header"; then \
		invalidate_candidate; \
		printf '#define SWAPZ_ALPHA_VERSION "%s"\n' "$$version" > "$$header" || \
			fail_stage "$$?" version-write; \
	fi
	@$(MAKE) -C "$(KDIR)" M="$(SWAPZ_STAGE)" modules || { \
		status=$$?; rm -f "$(SWAPZ_STAGE)/dm-swapz.ko"; \
		printf 'FAIL_KERNEL_BUILD phase=Kbuild exit=%s\n' "$$status" >&2; \
		exit "$$status"; \
	}

clean:
	@if test -d "$(SWAPZ_STAGE)" && test -f "$(KDIR)/Makefile"; then \
	  $(MAKE) -C "$(KDIR)" M="$(SWAPZ_STAGE)" clean; \
	fi
endif
