KDIR ?= /lib/modules/$(shell uname -r)/build

.PHONY: all kernel userspace test clean
all: kernel userspace

kernel:
	$(MAKE) -C kernel KDIR=$(KDIR)

userspace:
	$(MAKE) -C userspace

test:
	$(MAKE) -C tests test

clean:
	$(MAKE) -C kernel KDIR=$(KDIR) clean || true
	$(MAKE) -C userspace clean
	$(MAKE) -C tests clean
