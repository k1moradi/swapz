ROOT := $(abspath $(CURDIR)/..)

.PHONY: all test test-native test-metadata-ram clean
all: test-native

test-native:
	$(MAKE) -C suites test-all

test-metadata-ram:
	@python3 -B "$(ROOT)/tests/runtime/benchmark/metadata-ram-evidence-test.py" -v

test: test-metadata-ram test-native

clean:
	$(MAKE) -C suites clean
