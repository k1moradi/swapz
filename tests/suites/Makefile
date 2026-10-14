# Reusable meaningful names, directly exercising existing production C.
# Version-specific filenames remain compatibility paths, not suite API names.
ROOT := $(abspath $(CURDIR)/../..)
OUT := $(ROOT)/build/tests/native
CC ?= cc
CFLAGS ?= -std=c11 -O1 -g -Wall -Wextra -Werror
ifeq ($(SANITIZE),1)
CFLAGS += -fsanitize=address,undefined -fno-omit-frame-pointer
endif
CPPFLAGS += -I$(ROOT)/kernel/extent-v3

.PHONY: test-all test-codec test-mapping test-gc test-lower-io clean
PROGRAMS := codec-roundtrip mapping-authority transaction-publication write-verification dead-segment-reclamation raw-discard online-packing randomized-authority gc-forbidden-victim gc-cost-accounting flush-ordering gc-rotation gc-engine-rotation lower-write-aggregation

$(OUT):
	@mkdir -p "$@"

$(OUT)/codec-roundtrip: $(ROOT)/tests/runtime/extent-v3-codec-test.c $(ROOT)/kernel/extent-v3/codec.c | $(OUT)
	$(CC) $(CPPFLAGS) $(CFLAGS) $^ -o "$@"

$(OUT)/mapping-authority: $(ROOT)/tests/runtime/extent-v3-authority-test.c $(ROOT)/kernel/extent-v3/authority.c $(ROOT)/kernel/extent-v3/codec.c | $(OUT)
	$(CC) $(CPPFLAGS) $(CFLAGS) $^ -o "$@"

$(OUT)/transaction-publication: $(ROOT)/tests/runtime/extent-v3-tx-snapshot-test.c $(ROOT)/kernel/extent-v3/authority.c $(ROOT)/kernel/extent-v3/codec.c | $(OUT)
	$(CC) $(CPPFLAGS) $(CFLAGS) $^ -o "$@"

$(OUT)/write-verification: $(ROOT)/tests/runtime/extent-v3-write-verify-test.c $(ROOT)/kernel/extent-v3/engine.c $(ROOT)/kernel/extent-v3/authority.c $(ROOT)/kernel/extent-v3/codec.c | $(OUT)
	$(CC) $(CPPFLAGS) $(CFLAGS) $^ -o "$@"

$(OUT)/dead-segment-reclamation: $(ROOT)/tests/runtime/extent-v3-dead-segment-test.c $(ROOT)/kernel/extent-v3/authority.c $(ROOT)/kernel/extent-v3/codec.c | $(OUT)
	$(CC) $(CPPFLAGS) $(CFLAGS) $^ -o "$@"

$(OUT)/raw-discard: $(ROOT)/tests/runtime/extent-v3-raw-discard-test.c $(ROOT)/kernel/extent-v3/authority.c $(ROOT)/kernel/extent-v3/codec.c | $(OUT)
	$(CC) $(CPPFLAGS) $(CFLAGS) $^ -o "$@"

$(OUT)/online-packing: $(ROOT)/tests/runtime/extent-v3-engine-test.c $(ROOT)/kernel/extent-v3/engine.c $(ROOT)/kernel/extent-v3/authority.c $(ROOT)/kernel/extent-v3/codec.c | $(OUT)
	$(CC) $(CPPFLAGS) $(CFLAGS) $^ -o "$@"

$(OUT)/randomized-authority: $(ROOT)/tests/runtime/extent-v3-randomized-engine-test.c $(ROOT)/kernel/extent-v3/engine.c $(ROOT)/kernel/extent-v3/authority.c $(ROOT)/kernel/extent-v3/codec.c | $(OUT)
	$(CC) $(CPPFLAGS) $(CFLAGS) $^ -o "$@"

$(OUT)/gc-forbidden-victim: $(ROOT)/tests/runtime/extent-v3-gc-forbidden-test.c $(ROOT)/kernel/extent-v3/authority.c $(ROOT)/kernel/extent-v3/codec.c | $(OUT)
	$(CC) $(CPPFLAGS) $(CFLAGS) $^ -o "$@"

$(OUT)/gc-cost-accounting: $(ROOT)/tests/runtime/extent-v3-gc-cost-test.c $(ROOT)/kernel/extent-v3/authority.c $(ROOT)/kernel/extent-v3/codec.c | $(OUT)
	$(CC) $(CPPFLAGS) $(CFLAGS) $^ -o "$@"

$(OUT)/flush-ordering: $(ROOT)/tests/runtime/extent-v3-flush-test.c | $(OUT)
	$(CC) $(CPPFLAGS) $(CFLAGS) $^ -o "$@"

$(OUT)/gc-rotation: $(ROOT)/tests/runtime/extent-v3-gc-rotation-test.c $(ROOT)/kernel/extent-v3/authority.c $(ROOT)/kernel/extent-v3/codec.c | $(OUT)
	$(CC) $(CPPFLAGS) $(CFLAGS) $^ -o "$@"

$(OUT)/gc-engine-rotation: $(ROOT)/tests/runtime/extent-v3-gc-engine-rotation-test.c $(ROOT)/kernel/extent-v3/engine.c $(ROOT)/kernel/extent-v3/authority.c $(ROOT)/kernel/extent-v3/codec.c | $(OUT)
	$(CC) $(CPPFLAGS) $(CFLAGS) $^ -o "$@"

$(OUT)/lower-write-aggregation: $(ROOT)/tests/runtime/extent-v3-bulk-io-test.c $(ROOT)/kernel/extent-v3/engine.c $(ROOT)/kernel/extent-v3/authority.c $(ROOT)/kernel/extent-v3/codec.c | $(OUT)
	$(CC) $(CPPFLAGS) $(CFLAGS) $^ -o "$@"

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
