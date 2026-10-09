#!/usr/bin/env python3
"""Linux-only, fail-closed lifetime restrictions for one fixed rootless mock.

This is NOT a production security boundary for NBD. It uses PR_SET_PDEATHSIG
and a narrow seccomp deny list to prevent descendants or executable
replacement in a fixed synthetic child. Unsupported ABIs/kernels deny READY.
"""

from __future__ import annotations

import ctypes
import errno
import os
import platform
import signal

PR_SET_PDEATHSIG = 1
PR_SET_NO_NEW_PRIVS = 38
PR_SET_SECCOMP = 22
SECCOMP_MODE_FILTER = 2
BPF_LD_W_ABS = 0x20
BPF_JMP_JEQ_K = 0x15
BPF_JMP_JSET_K = 0x45
BPF_RET_K = 0x06
SECCOMP_RET_KILL_PROCESS = 0x80000000
SECCOMP_RET_ERRNO = 0x00050000
SECCOMP_RET_ALLOW = 0x7FFF0000

# Architecture values from Linux audit.h and syscall tables. Explicit
# rejects preserve the no-descendant property on unknown architectures.
ARCHITECTURES = {
    "x86_64": (0xC000003E, (56, 57, 58, 59, 322, 435)),
    "aarch64": (0xC00000B7, (220, 221, 281, 435)),
}


class Filter(ctypes.Structure):
    _fields_ = [("code", ctypes.c_ushort), ("jt", ctypes.c_ubyte),
                ("jf", ctypes.c_ubyte), ("k", ctypes.c_uint32)]


class Program(ctypes.Structure):
    _fields_ = [("len", ctypes.c_ushort),
                ("filter", ctypes.POINTER(Filter))]


class ContainmentDenied(RuntimeError):
    """Child has no reliable parent death / spawn containment."""


def _libc_prctl():
    libc = ctypes.CDLL(None, use_errno=True)
    proc = libc.prctl
    proc.restype = ctypes.c_int
    proc.argtypes = [ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong,
                     ctypes.c_ulong, ctypes.c_ulong]
    return proc


def _prctl(proc, option: int, arg: int) -> None:
    ctypes.set_errno(0)
    if proc(option, arg, 0, 0, 0) != 0:
        raise ContainmentDenied(
            f"Linux prctl {option} failed with errno {ctypes.get_errno()}"
        )


def arm_parent_death(expected_parent_pid: int) -> None:
    """Register death signal before checking the parent's original PID.

    Even a parent killed before this executes cannot bypass the post-arming
    getppid check. This PID is used ONLY for comparison, never signaling.
    """
    if (type(expected_parent_pid) is not int or expected_parent_pid <= 1
            or expected_parent_pid == os.getpid()):
        raise ContainmentDenied("invalid fixed synthetic parent identity")
    if os.getppid() != expected_parent_pid:
        raise ContainmentDenied("synthetic owner already disappeared")
    _prctl(_libc_prctl(), PR_SET_PDEATHSIG, int(signal.SIGKILL))
    if os.getppid() != expected_parent_pid:
        raise ContainmentDenied("synthetic owner disappeared while binding PDEATHSIG")


def deny_descendants_and_exec() -> None:
    """Block fork/vfork/clone/clone3 and execve/execveat post-startup.

    Linux seccomp BPF checks the architecture before syscall numbers;
    x86_64's x32 ABI is rejected. No allowlist of production syscalls is
    claimed. This only restricts a fixed, already-executing mock worker.
    """
    ident = platform.machine().lower()
    if ident not in ARCHITECTURES:
        raise ContainmentDenied("unsupported Linux syscall architecture")
    arch, disallowed = ARCHITECTURES[ident]
    # LOAD seccomp_data.arch, JEQ expected (skip KILL on match), KILL,
    # LOAD syscall number, deny x32 ABI when x86_64, then deny each
    # process-creation/executable-replacement operation.
    blocks = [
        Filter(BPF_LD_W_ABS, 0, 0, 4),
        Filter(BPF_JMP_JEQ_K, 1, 0, arch),
        Filter(BPF_RET_K, 0, 0, SECCOMP_RET_KILL_PROCESS),
        Filter(BPF_LD_W_ABS, 0, 0, 0),
    ]
    refusal = SECCOMP_RET_ERRNO | errno.EPERM
    if ident == "x86_64":
        blocks.extend((
            Filter(BPF_JMP_JSET_K, 0, 1, 0x40000000),
            Filter(BPF_RET_K, 0, 0, refusal),
        ))
    for syscall_nr in disallowed:
        blocks.extend((
            Filter(BPF_JMP_JEQ_K, 0, 1, syscall_nr),
            Filter(BPF_RET_K, 0, 0, refusal),
        ))
    blocks.append(Filter(BPF_RET_K, 0, 0, SECCOMP_RET_ALLOW))
    program_type = Filter * len(blocks)
    program_bytes = program_type(*blocks)
    program = Program(len(blocks), program_bytes)
    proc = _libc_prctl()
    _prctl(proc, PR_SET_NO_NEW_PRIVS, 1)
    ctypes.set_errno(0)
    ptr = ctypes.cast(ctypes.pointer(program), ctypes.c_void_p).value
    if ptr is None or proc(PR_SET_SECCOMP, SECCOMP_MODE_FILTER, ptr, 0, 0) != 0:
        raise ContainmentDenied(
            f"Linux seccomp process-containment install failed: {ctypes.get_errno()}"
        )


__all__ = ["arm_parent_death", "deny_descendants_and_exec", "ContainmentDenied"]
