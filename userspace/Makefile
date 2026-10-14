# No binaries in source directories. All builds reuse ../build/.
CXX ?= g++
CXXFLAGS ?= -std=c++23 -O2 -Wall -Wextra -Wpedantic -Wconversion -Wshadow
PREFIX ?= /usr/local
ROOT := $(abspath $(CURDIR)/..)
BIN := $(ROOT)/build/userspace/swapzctl

.PHONY: all clean install
all: $(BIN)

$(ROOT)/build/userspace:
	@mkdir -p "$@"

$(BIN): swapzctl.cpp | $(ROOT)/build/userspace
	$(CXX) $(CXXFLAGS) -o "$@" "$<"

install: $(BIN)
	install -Dm0755 "$(BIN)" "$(DESTDIR)$(PREFIX)/sbin/swapzctl"

clean:
	@rm -f "$(BIN)"
