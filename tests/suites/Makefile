# One shared compile rule for the production-C invariant tests.
ROOT := $(abspath $(CURDIR)/../..)
OUT := $(ROOT)/build/tests/native
NATIVE := $(ROOT)/tests/runtime/native
KERNEL := $(ROOT)/src/kernel
CODEC := $(KERNEL)/codec.c
AUTH := $(KERNEL)/authority.c
ENGINE := $(KERNEL)/engine.c
CC ?= cc
CFLAGS ?= -std=c11 -O1 -g -Wall -Wextra -Werror
ifeq ($(SANITIZE),1)
CFLAGS += -fsanitize=address,undefined -fno-omit-frame-pointer
endif
CPPFLAGS += -I$(KERNEL)

.PHONY: test-all test-codec test-mapping test-gc test-lower-io test-predictor clean
PROGRAMS := codec-roundtrip zero-write-elision mapping-authority transaction-publication write-verification dead-segment-reclamation raw-discard online-packing randomized-authority gc-forbidden-victim gc-cost-accounting gc-scan-scaling gc-rotation gc-engine-rotation flush-ordering lower-write-aggregation window-policy

codec-roundtrip_SRC := $(NATIVE)/codec/roundtrip.c $(CODEC)
PREDICTOR_CORE_OBJ := $(OUT)/predictor-core.o
PREDICTOR_ARCH_OBJS :=
UNAME_M := $(shell uname -m)
ifeq ($(UNAME_M),x86_64)
PREDICTOR_ARCH_OBJS += $(OUT)/predictor-sse2.o $(OUT)/predictor-avx2.o
endif
ifeq ($(UNAME_M),aarch64)
PREDICTOR_ARCH_OBJS += $(OUT)/predictor-neon.o
endif
zero-write-elision_SRC := $(NATIVE)/mapping/zero-write.c $(ENGINE) $(AUTH) $(CODEC)
mapping-authority_SRC := $(NATIVE)/mapping/authority.c $(AUTH) $(CODEC)
transaction-publication_SRC := $(NATIVE)/mapping/transaction-publication.c $(AUTH) $(CODEC)
write-verification_SRC := $(NATIVE)/mapping/write-verification.c $(ENGINE) $(AUTH) $(CODEC)
dead-segment-reclamation_SRC := $(NATIVE)/mapping/dead-segment.c $(AUTH) $(CODEC)
raw-discard_SRC := $(NATIVE)/mapping/raw-discard.c $(AUTH) $(CODEC)
online-packing_SRC := $(NATIVE)/mapping/online-packing.c $(ENGINE) $(AUTH) $(CODEC)
randomized-authority_SRC := $(NATIVE)/mapping/randomized-authority.c $(ENGINE) $(AUTH) $(CODEC)
gc-forbidden-victim_SRC := $(NATIVE)/gc/forbidden-victim.c $(AUTH) $(CODEC)
gc-cost-accounting_SRC := $(NATIVE)/gc/cost-accounting.c $(AUTH) $(CODEC)
gc-scan-scaling_SRC := $(NATIVE)/gc/scan-scaling.c
gc-scan-scaling_HDR := $(KERNEL)/gc-cost.h $(KERNEL)/authority.h $(KERNEL)/codec.h
gc-rotation_SRC := $(NATIVE)/gc/rotation.c $(AUTH) $(CODEC)
gc-engine-rotation_SRC := $(NATIVE)/gc/engine-rotation.c $(ENGINE) $(AUTH) $(CODEC)
flush-ordering_SRC := $(NATIVE)/io/flush-ordering.c
lower-write-aggregation_SRC := $(NATIVE)/io/lower-write-aggregation.c $(ENGINE) $(AUTH) $(CODEC)
window-policy_SRC := $(NATIVE)/io/window-policy.c
window-policy_HDR := $(KERNEL)/window-policy.h $(KERNEL)/codec.h

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

$(OUT)/predictor-sse2.o: $(KERNEL)/predictor-sse2.c $(KERNEL)/predictor.h $(KERNEL)/predictor-internal.h | $(OUT)
	$(CC) $(CPPFLAGS) $(CFLAGS) -msse2 -c $(KERNEL)/predictor-sse2.c -o "$@"

$(OUT)/predictor-avx2.o: $(KERNEL)/predictor-avx2.c $(KERNEL)/predictor.h $(KERNEL)/predictor-internal.h | $(OUT)
	$(CC) $(CPPFLAGS) $(CFLAGS) -mavx2 -c $(KERNEL)/predictor-avx2.c -o "$@"

$(OUT)/predictor-neon.o: $(KERNEL)/predictor-neon.c $(KERNEL)/predictor.h $(KERNEL)/predictor-internal.h | $(OUT)
	$(CC) $(CPPFLAGS) $(CFLAGS) -c $(KERNEL)/predictor-neon.c -o "$@"

$(OUT)/predictor-qualification: $(NATIVE)/codec/predictor-qualification.c \
		$(ENGINE) $(AUTH) $(CODEC) $(PREDICTOR_CORE_OBJ) $(PREDICTOR_ARCH_OBJS) | $(OUT)
	$(CC) $(CPPFLAGS) $(CFLAGS) $(NATIVE)/codec/predictor-qualification.c \
		$(ENGINE) $(AUTH) $(CODEC) $(PREDICTOR_CORE_OBJ) $(PREDICTOR_ARCH_OBJS) \
		-o "$@" -llz4

test-codec: $(OUT)/codec-roundtrip
	@set -e; "$(OUT)/codec-roundtrip"

test-predictor: $(OUT)/predictor-qualification
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
	    "$(OUT)/predictor-medium.bin"

test-mapping: $(OUT)/zero-write-elision $(OUT)/mapping-authority $(OUT)/transaction-publication $(OUT)/write-verification $(OUT)/dead-segment-reclamation $(OUT)/raw-discard $(OUT)/online-packing $(OUT)/randomized-authority
	@set -e; "$(OUT)/zero-write-elision"; "$(OUT)/mapping-authority"; "$(OUT)/transaction-publication"; "$(OUT)/write-verification"; "$(OUT)/dead-segment-reclamation"; "$(OUT)/raw-discard"; "$(OUT)/online-packing"; "$(OUT)/randomized-authority"

test-gc: $(OUT)/gc-forbidden-victim $(OUT)/gc-cost-accounting $(OUT)/gc-scan-scaling $(OUT)/gc-rotation $(OUT)/gc-engine-rotation
	@set -e; "$(OUT)/gc-forbidden-victim"; "$(OUT)/gc-cost-accounting"; "$(OUT)/gc-scan-scaling"; "$(OUT)/gc-rotation"; "$(OUT)/gc-engine-rotation"

test-lower-io: $(OUT)/flush-ordering $(OUT)/lower-write-aggregation $(OUT)/window-policy
	@set -e; "$(OUT)/flush-ordering"; "$(OUT)/lower-write-aggregation"; "$(OUT)/window-policy"

test-all: test-codec test-predictor test-mapping test-gc test-lower-io

clean:
	@rm -f $(addprefix $(OUT)/,$(PROGRAMS)) $(OUT)/predictor-qualification \
		$(PREDICTOR_CORE_OBJ) $(OUT)/predictor-sse2.o \
		$(OUT)/predictor-avx2.o $(OUT)/predictor-neon.o \
		$(OUT)/predictor-entropy.bin $(OUT)/predictor-entropy.json \
		$(OUT)/predictor-mixed.bin $(OUT)/predictor-mixed.json \
		$(OUT)/predictor-medium.bin $(OUT)/predictor-medium.json
