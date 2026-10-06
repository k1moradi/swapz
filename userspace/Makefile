CXX ?= g++
CXXFLAGS ?= -std=c++23 -O2 -Wall -Wextra -Wpedantic -Wconversion -Wshadow
PREFIX ?= /usr/local

.PHONY: all clean install
all: swapzctl

swapzctl: swapzctl.cpp
	$(CXX) $(CXXFLAGS) -o $@ $<

install: swapzctl
	install -Dm0755 swapzctl $(DESTDIR)$(PREFIX)/sbin/swapzctl

clean:
	rm -f swapzctl
