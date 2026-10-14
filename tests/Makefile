# Reuse the repository's one build root for native and C++ outputs.
CXX ?= g++
CXXFLAGS ?= -std=c++23 -O2 -Wall -Wextra -Wpedantic -Wconversion -Wshadow
LDLIBS ?= -llz4
ROOT := $(abspath $(CURDIR)/..)
BUILD := $(ROOT)/build/tests/model
MODEL := $(BUILD)/swapz-model-tests

.PHONY: all test test-model test-native clean
all: $(MODEL)

$(BUILD):
	@mkdir -p "$@"

$(MODEL): swapz_model.cpp | $(BUILD)
	$(CXX) $(CXXFLAGS) -o "$@" "$<" $(LDLIBS)

test-model: $(MODEL)
	"$(MODEL)"

test-native:
	$(MAKE) -C suites test-all

test: test-model test-native

clean:
	@rm -f "$(MODEL)"
	$(MAKE) -C suites clean
