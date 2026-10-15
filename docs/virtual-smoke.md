# Legacy V2.2 virtual smoke — safety compatibility handoff

This retained note exists because rootless compatibility tests verify that
the archived V2.2 virtual smoke contract continues to state every relevant
authorization and cleanup constraint. It is **not** an active V3 benchmark,
permission to load a V2 module or authorization to test the owner's PC.
All privileged V2.2 work requires a separate authorized operation. V3
remains experimental and null_blk-only. There is no implicit sudo step in
`make test`; no physical swap, mount, swapoff/swapon, or host reboot is
permitted by this document.

## Historical disposable-VM prerequisites

The operator must independently confirm disposable VM ownership, the
matching exact source/module digests, and kernel support for
`modprobe dm-delay`. The former harness used only a newly owned
32 MiB tmpfs image, not an existing block device. Its 32 MiB image
is **65,536 sectors** (512-byte accounting sectors), or
**32 complete 1 MiB segments**. The reserve bound was
the larger of 25% of the one-page logical size or two segments.
Only the swapz logical table is one page (`0 8` sectors).
A one-page V2.2 target is NOT a 32 MiB logical data volume.

The operator-supplied VM label is an untrusted string: the test
cannot authenticate the operator-supplied VM label. Explicit authorization
must match the VM label and immutable exact source and module SHA-256.
The former runtime relied on two separate aligned 4 KiB reads:
the first while the lower write is outstanding, the second
after ordinary suspend/resume drain. Tests must verify byte identity
and the one-owner completion invariant. Unexpected holders or incomplete
lower callbacks make ordinary cleanup unsafe: forensic cleanup or VM reset needs a new operator decision and must not be automated.

This literal authorization template is retained only for the source
contract; do not execute it on an owner's machine:

```bash
AUTH="I AUTHORIZE swapz V2.2 smoke only on disposable VM $VM_ID with source $SOURCE_SHA and module SHA-256 $MODULE_SHA256; permitted operations are one /dev/shm-backed loop device, one dm-delay target, one swapz target, one aligned 4 KiB write, two separate aligned 4 KiB reads (one while the lower write is outstanding and one after ordinary suspend/resume drain), ordinary suspend and resume, ordinary removal of resources positively created by this run, and insmod/rmmod of only the selected dm-swapz module; no swap activation, mount, physical storage, forced removal, or host reboot."
```

The current `tests/runtime/virtual-smoke-test.py` verifies only the
compatibility and safety statements; that rootless gate does not load any
kernel module and does not establish live kernel or device correctness.
