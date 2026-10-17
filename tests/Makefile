ROOT := $(abspath $(CURDIR)/..)

.PHONY: all test test-native clean
all: test-native

test-native:
	$(MAKE) -C suites test-all

test: test-native

clean:
	$(MAKE) -C suites clean
