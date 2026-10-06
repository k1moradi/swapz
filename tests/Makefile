CXX ?= g++
CXXFLAGS ?= -std=c++23 -O2 -Wall -Wextra -Wpedantic -Wconversion -Wshadow
LDLIBS ?= -llz4

.PHONY: all test clean
all: swapz-model-tests

swapz-model-tests: swapz_model.cpp
	$(CXX) $(CXXFLAGS) -o $@ $< $(LDLIBS)

test: swapz-model-tests
	./swapz-model-tests

clean:
	rm -f swapz-model-tests
