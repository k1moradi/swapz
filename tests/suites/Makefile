# One shared compile rule for the production-C invariant tests.
ROOT := $(abspath $(CURDIR)/../..)
OUT := $(ROOT)/build/tests/native
NATIVE := $(ROOT)/tests/runtime/native
BENCHMARK := $(ROOT)/tests/runtime/benchmark
KERNEL := $(ROOT)/src/kernel
USERSPACE := $(ROOT)/src/userspace
CODEC := $(KERNEL)/codec.c
AUTH := $(KERNEL)/authority.c
ENGINE := $(KERNEL)/engine.c
CC ?= cc
OBJDUMP ?= objdump
CFLAGS ?= -std=c11 -O1 -g -Wall -Wextra -Werror
ifeq ($(SANITIZE),1)
CFLAGS += -fsanitize=address,undefined -fno-sanitize-recover=all -fno-omit-frame-pointer
endif
ifeq ($(THREAD_SANITIZE),1)
CFLAGS += -fsanitize=thread -fno-omit-frame-pointer
endif
CPPFLAGS += -I$(KERNEL)

.PHONY: test-all test-codec test-mapping test-gc test-lower-io test-concurrency test-predictor test-anon-page-analyzer test-userspace test-replay-helper clean
PROGRAMS := io-replay-native codec-roundtrip extent-geometry anon-page-analyzer zero-write-elision mapping-authority authority-throughput transaction-publication write-verification dead-segment-reclamation raw-discard online-packing randomized-authority gc-forbidden-victim gc-cost-accounting gc-recovery-policy gc-scan-scaling gc-rotation gc-engine-rotation gc-high-occupancy flush-ordering lower-write-aggregation window-policy preparation-slots preparation-codec-result preparation-publication-lifetime lane-gap superblock swapzctl-status swapzctl-format swapzctl-removable-media swapz-primary-policy swapz-primary-mount-namespace

io-replay-native_SRC := $(BENCHMARK)/io-replay-native.c
io-replay-native_LDLIBS := -pthread
codec-roundtrip_SRC := $(NATIVE)/codec/roundtrip.c $(CODEC)
codec-roundtrip_HDR := $(KERNEL)/codec.h $(KERNEL)/authority.h
extent-geometry_SRC := $(NATIVE)/codec/extent-geometry.c
extent-geometry_HDR := $(KERNEL)/codec.h $(KERNEL)/authority.h
PREDICTOR_CORE_OBJ := $(OUT)/predictor-core.o
PREDICTOR_ARCH_OBJS :=
UNAME_M := $(shell uname -m)
ifeq ($(UNAME_M),x86_64)
PREDICTOR_ARCH_OBJS += $(OUT)/predictor-sse2.o $(OUT)/predictor-avx2.o \
	$(OUT)/predictor-avx512.o
endif
ifeq ($(UNAME_M),aarch64)
PREDICTOR_ARCH_OBJS += $(OUT)/predictor-neon.o
endif
zero-write-elision_SRC := $(NATIVE)/mapping/zero-write.c $(ENGINE) $(AUTH) $(CODEC)
mapping-authority_SRC := $(NATIVE)/mapping/authority.c $(AUTH) $(CODEC)
authority-throughput_SRC := $(NATIVE)/mapping/authority-throughput.c $(AUTH) $(CODEC)
transaction-publication_SRC := $(NATIVE)/mapping/transaction-publication.c $(AUTH) $(CODEC)
write-verification_SRC := $(NATIVE)/mapping/write-verification.c $(ENGINE) $(AUTH) $(CODEC)
dead-segment-reclamation_SRC := $(NATIVE)/mapping/dead-segment.c $(AUTH) $(CODEC)
raw-discard_SRC := $(NATIVE)/mapping/raw-discard.c $(AUTH) $(CODEC)
online-packing_SRC := $(NATIVE)/mapping/online-packing.c $(ENGINE) $(AUTH) $(CODEC)
randomized-authority_SRC := $(NATIVE)/mapping/randomized-authority.c $(ENGINE) $(AUTH) $(CODEC)
gc-forbidden-victim_SRC := $(NATIVE)/gc/forbidden-victim.c $(AUTH) $(CODEC)
gc-cost-accounting_SRC := $(NATIVE)/gc/cost-accounting.c $(AUTH) $(CODEC)
gc-recovery-policy_SRC := $(NATIVE)/gc/recovery-policy.c
gc-recovery-policy_HDR := $(KERNEL)/gc-recovery-policy.h
gc-scan-scaling_SRC := $(NATIVE)/gc/scan-scaling.c
gc-scan-scaling_HDR := $(KERNEL)/gc-cost.h $(KERNEL)/authority.h $(KERNEL)/codec.h
gc-rotation_SRC := $(NATIVE)/gc/rotation.c $(AUTH) $(CODEC)
gc-engine-rotation_SRC := $(NATIVE)/gc/engine-rotation.c $(ENGINE) $(AUTH) $(CODEC)
gc-high-occupancy_SRC := $(NATIVE)/gc/high-occupancy.c $(AUTH) $(CODEC)
flush-ordering_SRC := $(NATIVE)/io/flush-ordering.c
lower-write-aggregation_SRC := $(NATIVE)/io/lower-write-aggregation.c $(ENGINE) $(AUTH) $(CODEC)
window-policy_SRC := $(NATIVE)/io/window-policy.c
window-policy_HDR := $(KERNEL)/window-policy.h $(KERNEL)/codec.h
preparation-slots_SRC := $(NATIVE)/io/preparation-slots.c
preparation-slots_HDR := $(KERNEL)/preparation-slots.h $(KERNEL)/codec.h
preparation-slots_LDLIBS := -pthread
preparation-codec-result_SRC := $(NATIVE)/io/preparation-codec-result.c
preparation-codec-result_HDR := $(KERNEL)/preparation-slots.h $(KERNEL)/codec.h
preparation-codec-result_LDLIBS := -pthread
preparation-publication-lifetime_SRC := $(NATIVE)/io/preparation-publication-lifetime.c
preparation-publication-lifetime_HDR := $(KERNEL)/preparation-slots.h $(KERNEL)/codec.h
preparation-publication-lifetime_LDLIBS := -pthread
lane-gap_SRC := $(NATIVE)/io/lane-gap.c
lane-gap_HDR := $(KERNEL)/lane-gap.h $(KERNEL)/codec.h
superblock_SRC := $(NATIVE)/codec/superblock.c
superblock_HDR := $(KERNEL)/superblock.h
swapzctl-status_SRC := $(NATIVE)/userspace/swapzctl-status.c $(USERSPACE)/swapz-primary.c
swapzctl-status_HDR := $(USERSPACE)/swapzctl.c $(USERSPACE)/swapz-primary.h $(KERNEL)/superblock.h
swapzctl-format_SRC := $(NATIVE)/userspace/swapzctl-format.c
swapzctl-format_HDR := $(USERSPACE)/swapzctl.c $(USERSPACE)/swapz-primary.h $(KERNEL)/superblock.h
swapzctl-removable-media_SRC := $(NATIVE)/userspace/swapzctl-removable-media.c
swapzctl-removable-media_HDR := $(USERSPACE)/swapzctl.c $(USERSPACE)/swapz-primary.h $(KERNEL)/superblock.h
swapz-primary-policy_SRC := $(NATIVE)/userspace/swapz-primary-policy.c
swapz-primary-policy_HDR := $(USERSPACE)/swapz-primary.c $(USERSPACE)/swapz-primary.h
swapz-primary-mount-namespace_SRC := $(NATIVE)/userspace/swapz-primary-mount-namespace.c
swapz-primary-mount-namespace_HDR := $(USERSPACE)/swapz-primary.c $(USERSPACE)/swapz-primary.h
anon-page-analyzer_SRC := $(NATIVE)/codec/anon-page-analyzer.c $(ENGINE) $(AUTH) $(CODEC) $(PREDICTOR_CORE_OBJ) $(PREDICTOR_ARCH_OBJS)
anon-page-analyzer_HDR := $(KERNEL)/engine.h $(KERNEL)/predictor-route.h $(KERNEL)/predictor.h $(KERNEL)/predictor-internal.h $(KERNEL)/codec.h
anon-page-analyzer_LDLIBS := -llz4

$(OUT):
	@mkdir -p "$@"

# Consolidate identical compile recipes, not the individual safety assertions.
define BUILD_NATIVE
$(OUT)/$(1): $$($(1)_SRC) $$($(1)_HDR) | $(OUT)
	$$(CC) $$(CPPFLAGS) $$(CFLAGS) $$($(1)_SRC) -o "$$@" $$($(1)_LDLIBS)
endef
$(foreach name,$(PROGRAMS),$(eval $(call BUILD_NATIVE,$(name))))

$(PREDICTOR_CORE_OBJ): $(KERNEL)/predictor.c $(KERNEL)/predictor.h $(KERNEL)/predictor-internal.h | $(OUT)
	$(CC) $(CPPFLAGS) $(CFLAGS) -c $(KERNEL)/predictor.c -o "$@"

$(OUT)/predictor-sse2.o: $(KERNEL)/predictor-sse2.c $(KERNEL)/predictor.h $(KERNEL)/predictor-internal.h $(KERNEL)/predictor-shuffle.h | $(OUT)
	$(CC) $(CPPFLAGS) $(CFLAGS) -msse2 -c $(KERNEL)/predictor-sse2.c -o "$@"

$(OUT)/predictor-avx2.o: $(KERNEL)/predictor-avx2.c $(KERNEL)/predictor.h $(KERNEL)/predictor-internal.h $(KERNEL)/predictor-shuffle.h | $(OUT)
	$(CC) $(CPPFLAGS) $(CFLAGS) -mavx2 -c $(KERNEL)/predictor-avx2.c -o "$@"

$(OUT)/predictor-avx512.o: $(KERNEL)/predictor-avx512.c $(KERNEL)/predictor.h $(KERNEL)/predictor-internal.h $(KERNEL)/predictor-shuffle.h | $(OUT)
	$(CC) $(CPPFLAGS) $(CFLAGS) -mavx512f -c $(KERNEL)/predictor-avx512.c -o "$@"

$(OUT)/predictor-neon.o: $(KERNEL)/predictor-neon.c $(KERNEL)/predictor.h $(KERNEL)/predictor-internal.h $(KERNEL)/predictor-shuffle.h | $(OUT)
	$(CC) $(CPPFLAGS) $(CFLAGS) -c $(KERNEL)/predictor-neon.c -o "$@"

$(OUT)/predictor-qualification: $(NATIVE)/codec/predictor-qualification.c \
		$(KERNEL)/predictor-route.h $(ENGINE) $(AUTH) $(CODEC) \
		$(PREDICTOR_CORE_OBJ) $(PREDICTOR_ARCH_OBJS) | $(OUT)
	$(CC) $(CPPFLAGS) $(CFLAGS) $(NATIVE)/codec/predictor-qualification.c \
		$(ENGINE) $(AUTH) $(CODEC) $(PREDICTOR_CORE_OBJ) $(PREDICTOR_ARCH_OBJS) \
		-o "$@" -llz4

test-codec: $(OUT)/codec-roundtrip $(OUT)/extent-geometry $(OUT)/superblock
	@set -e; "$(OUT)/codec-roundtrip"; "$(OUT)/extent-geometry"; "$(OUT)/superblock"

test-anon-page-analyzer: $(OUT)/anon-page-analyzer
	@python3 -B "$(NATIVE)/codec/anon-page-analyzer-test.py" "$(OUT)/anon-page-analyzer"

test-predictor: $(OUT)/predictor-qualification test-anon-page-analyzer
	@set -e; \
	  python3 -B "$(ROOT)/tests/runtime/benchmark/anon-page-fixture.py" \
	    --output-prefix "$(OUT)/predictor-entropy" --pages 64 --weights entropy=100 >/dev/null; \
	  python3 -B "$(ROOT)/tests/runtime/benchmark/anon-page-fixture.py" \
	    --output-prefix "$(OUT)/predictor-mixed" --pages 64 --weights mixed=100 >/dev/null; \
	  python3 -B "$(ROOT)/tests/runtime/benchmark/anon-page-fixture.py" \
	    --output-prefix "$(OUT)/predictor-medium" --pages 64 --weights medium=100 >/dev/null; \
	  "$(OUT)/predictor-qualification" \
	    "$(OUT)/predictor-entropy.bin" \
	    "$(OUT)/predictor-mixed.bin" \
	    "$(OUT)/predictor-medium.bin"; \
	  if [ "$(UNAME_M)" = x86_64 ]; then \
	    "$(OBJDUMP)" -d "$(OUT)/predictor-sse2.o" | grep -q 'shufpd'; \
	    "$(OBJDUMP)" -d "$(OUT)/predictor-sse2.o" | grep -q 'pslldq'; \
	  fi

test-mapping: $(OUT)/zero-write-elision $(OUT)/mapping-authority $(OUT)/authority-throughput $(OUT)/transaction-publication $(OUT)/write-verification $(OUT)/dead-segment-reclamation $(OUT)/raw-discard $(OUT)/online-packing $(OUT)/randomized-authority
	@set -e; "$(OUT)/zero-write-elision"; "$(OUT)/mapping-authority"; "$(OUT)/authority-throughput"; "$(OUT)/transaction-publication"; "$(OUT)/write-verification"; "$(OUT)/dead-segment-reclamation"; "$(OUT)/raw-discard"; "$(OUT)/online-packing"; "$(OUT)/randomized-authority"

test-gc: $(OUT)/gc-forbidden-victim $(OUT)/gc-cost-accounting $(OUT)/gc-recovery-policy $(OUT)/gc-scan-scaling $(OUT)/gc-rotation $(OUT)/gc-engine-rotation $(OUT)/gc-high-occupancy
	@set -e; "$(OUT)/gc-forbidden-victim"; "$(OUT)/gc-cost-accounting"; "$(OUT)/gc-recovery-policy"; "$(OUT)/gc-scan-scaling"; "$(OUT)/gc-rotation"; "$(OUT)/gc-engine-rotation"; "$(OUT)/gc-high-occupancy"

# Keep the original failed executable's status, not a later Make exit.
test-lower-io: $(OUT)/flush-ordering $(OUT)/lower-write-aggregation $(OUT)/window-policy $(OUT)/preparation-slots $(OUT)/preparation-codec-result $(OUT)/preparation-publication-lifetime $(OUT)/lane-gap
	@set -e; \
	  for native_test in flush-ordering lower-write-aggregation window-policy preparation-slots preparation-codec-result preparation-publication-lifetime lane-gap; do \
	    if "$(OUT)/$$native_test"; then :; else \
	      native_exit_status=$$?; \
	      printf 'FAIL: native test-lower-io binary=%s exit=%s\n' "$$native_test" "$$native_exit_status" >&2; \
	      exit "$$native_exit_status"; \
	    fi; \
	  done

test-concurrency: $(OUT)/preparation-slots $(OUT)/preparation-codec-result $(OUT)/preparation-publication-lifetime
	@set -e; "$(OUT)/preparation-slots"; "$(OUT)/preparation-codec-result"; "$(OUT)/preparation-publication-lifetime"

test-userspace: $(OUT)/swapzctl-status $(OUT)/swapzctl-format $(OUT)/swapzctl-removable-media $(OUT)/swapz-primary-policy $(OUT)/swapz-primary-mount-namespace
	@set -e; "$(OUT)/swapzctl-status"; "$(OUT)/swapzctl-format"; "$(OUT)/swapzctl-removable-media"; "$(OUT)/swapz-primary-policy"; "$(OUT)/swapz-primary-mount-namespace"
	@python3 -B "$(NATIVE)/userspace/swapz-primary-late-race-test.py"

test-replay-helper: $(OUT)/io-replay-native
	@test -x "$(OUT)/io-replay-native"

test-all: test-codec test-predictor test-mapping test-gc test-lower-io test-userspace test-replay-helper

clean:
	@rm -f $(addprefix $(OUT)/,$(PROGRAMS)) $(OUT)/predictor-qualification \
		$(PREDICTOR_CORE_OBJ) $(OUT)/predictor-sse2.o \
		$(OUT)/predictor-avx2.o $(OUT)/predictor-avx512.o \
		$(OUT)/predictor-neon.o \
		$(OUT)/predictor-entropy.bin $(OUT)/predictor-entropy.json \
		$(OUT)/predictor-mixed.bin $(OUT)/predictor-mixed.json \
		$(OUT)/predictor-medium.bin $(OUT)/predictor-medium.json
