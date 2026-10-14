# One shared compile rule for all 14 production-C invariant tests.
ROOT := $(abspath $(CURDIR)/../..)
OUT := $(ROOT)/build/tests/native
NATIVE := $(ROOT)/tests/runtime/native
KERNEL := $(ROOT)/kernel/extent-v3
CODEC := $(KERNEL)/codec.c
AUTH := $(KERNEL)/authority.c
ENGINE := $(KERNEL)/engine.c
CC ?= cc
CFLAGS ?= -std=c11 -O1 -g -Wall -Wextra -Werror
ifeq ($(SANITIZE),1)
CFLAGS += -fsanitize=address,undefined -fno-omit-frame-pointer
endif
CPPFLAGS += -I$(KERNEL)

.PHONY: test-all test-codec test-mapping test-gc test-lower-io clean
PROGRAMS := codec-roundtrip mapping-authority transaction-publication write-verification dead-segment-reclamation raw-discard online-packing randomized-authority gc-forbidden-victim gc-cost-accounting gc-rotation gc-engine-rotation flush-ordering lower-write-aggregation

codec-roundtrip_SRC := $(NATIVE)/codec/roundtrip.c $(CODEC)
mapping-authority_SRC := $(NATIVE)/mapping/authority.c $(AUTH) $(CODEC)
transaction-publication_SRC := $(NATIVE)/mapping/transaction-publication.c $(AUTH) $(CODEC)
write-verification_SRC := $(NATIVE)/mapping/write-verification.c $(ENGINE) $(AUTH) $(CODEC)
dead-segment-reclamation_SRC := $(NATIVE)/mapping/dead-segment.c $(AUTH) $(CODEC)
raw-discard_SRC := $(NATIVE)/mapping/raw-discard.c $(AUTH) $(CODEC)
online-packing_SRC := $(NATIVE)/mapping/online-packing.c $(ENGINE) $(AUTH) $(CODEC)
randomized-authority_SRC := $(NATIVE)/mapping/randomized-authority.c $(ENGINE) $(AUTH) $(CODEC)
gc-forbidden-victim_SRC := $(NATIVE)/gc/forbidden-victim.c $(AUTH) $(CODEC)
gc-cost-accounting_SRC := $(NATIVE)/gc/cost-accounting.c $(AUTH) $(CODEC)
gc-rotation_SRC := $(NATIVE)/gc/rotation.c $(AUTH) $(CODEC)
gc-engine-rotation_SRC := $(NATIVE)/gc/engine-rotation.c $(ENGINE) $(AUTH) $(CODEC)
flush-ordering_SRC := $(NATIVE)/io/flush-ordering.c
lower-write-aggregation_SRC := $(NATIVE)/io/lower-write-aggregation.c $(ENGINE) $(AUTH) $(CODEC)

$(OUT):
	@mkdir -p "$@"

# Consolidate identical compile recipes, not the individual safety assertions.
define BUILD_NATIVE
$(OUT)/$(1): $$($(1)_SRC) | $(OUT)
	$$(CC) $$(CPPFLAGS) $$(CFLAGS) $$^ -o "$$@"
endef
$(foreach name,$(PROGRAMS),$(eval $(call BUILD_NATIVE,$(name))))

test-codec: $(OUT)/codec-roundtrip
	@set -e; "$(OUT)/codec-roundtrip"

test-mapping: $(OUT)/mapping-authority $(OUT)/transaction-publication $(OUT)/write-verification $(OUT)/dead-segment-reclamation $(OUT)/raw-discard $(OUT)/online-packing $(OUT)/randomized-authority
	@set -e; "$(OUT)/mapping-authority"; "$(OUT)/transaction-publication"; "$(OUT)/write-verification"; "$(OUT)/dead-segment-reclamation"; "$(OUT)/raw-discard"; "$(OUT)/online-packing"; "$(OUT)/randomized-authority"

test-gc: $(OUT)/gc-forbidden-victim $(OUT)/gc-cost-accounting $(OUT)/gc-rotation $(OUT)/gc-engine-rotation
	@set -e; "$(OUT)/gc-forbidden-victim"; "$(OUT)/gc-cost-accounting"; "$(OUT)/gc-rotation"; "$(OUT)/gc-engine-rotation"

test-lower-io: $(OUT)/flush-ordering $(OUT)/lower-write-aggregation
	@set -e; "$(OUT)/flush-ordering"; "$(OUT)/lower-write-aggregation"

test-all: test-codec test-mapping test-gc test-lower-io

clean:
	@rm -f $(addprefix $(OUT)/,$(PROGRAMS))
