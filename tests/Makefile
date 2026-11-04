ROOT := $(abspath $(CURDIR)/..)

.PHONY: all test test-native test-metadata-ram test-anon-page-fixture clean
all: test-native

test-native:
	$(MAKE) -C suites test-all

test-metadata-ram:
	@python3 -B "$(ROOT)/tests/runtime/benchmark/metadata-ram-evidence-test.py" -v

test-anon-page-fixture:
	@python3 -B "$(ROOT)/tests/runtime/benchmark/anon-page-fixture-test.py" -v

test: test-metadata-ram test-anon-page-fixture test-native

clean:
	$(MAKE) -C suites clean
