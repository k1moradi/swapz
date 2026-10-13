obj-m += sv3-read-bypass-probe.o
obj-m += sv3-queue-probe.o
obj-m += sv3-barrier-probe.o
KDIR ?= /lib/modules/$(shell uname -r)/build
all:
	$(MAKE) -C $(KDIR) M=$(CURDIR) modules
clean:
	$(MAKE) -C $(KDIR) M=$(CURDIR) clean
