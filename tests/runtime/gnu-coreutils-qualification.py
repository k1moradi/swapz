#!/usr/bin/env python3
"""Verify one GNU source release and build a static, reviewable dd artifact.

This is an offline qualification tool, not a production credential installer.
It accepts release artifacts from local paths, verifies the exact release
checksum and detached GNU signing key, and builds two clean copies with one
fixed recipe. It never writes the production GNU manifest or signing key.
"""

from __future__ import annotations

import argparse
import base64
import errno
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import stat
import struct
import subprocess
import sys
import tarfile
import tempfile
from typing import Any


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RELEASES: dict[str, dict[str, Any]] = {
    "9.11": {
        "archive_name": "coreutils-9.11.tar.xz",
        "archive_sha256_b64": "OUAk7aCllVIXztqc0SAeZdyPo6opwpURNaSVIdV8PMM=",
        "signer_fingerprint": "6C37DC12121A5006BC1DB804DF6FD971306037D9",
        "signer_keyid": "DF6FD971306037D9",
        "release_commit": "c01fd163a47468a8296fb369f5233853bb551bb6",
        "signature_epoch": 1776693733,
        "source_date_epoch": 1776693733,
        "announcement": "https://lists.gnu.org/archive/html/coreutils-announce/2026-04/msg00000.html",
        "archive_url": "https://ftp.gnu.org/gnu/coreutils/coreutils-9.11.tar.xz",
        "signature_url": "https://ftp.gnu.org/gnu/coreutils/coreutils-9.11.tar.xz.sig",
    },
}
MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
MAX_SIGNATURE_BYTES = 16 * 1024
MAX_KEYRING_BYTES = 32 * 1024 * 1024
MAX_BINARY_BYTES = 128 * 1024 * 1024
BUILD_CONFIGURE_ARGS = ("--disable-nls", "--disable-acl", "--without-selinux")
BUILD_JOBS = 2


class QualificationError(RuntimeError):
    """A source, build, or executable qualification check failed."""


def _read_regular(path: Path, *, maximum: int) -> tuple[bytes, os.stat_result]:
    flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise QualificationError(f"cannot open regular input {path}: {exc}") from exc
    try:
        before = os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or before.st_size <= 0
                or before.st_size > maximum or before.st_mode & (stat.S_ISUID | stat.S_ISGID)):
            raise QualificationError(f"input is not a bounded, ordinary regular file: {path}")
        chunks: list[bytes] = []
        offset = 0
        while offset < before.st_size:
            chunk = os.pread(fd, min(1024 * 1024, before.st_size - offset), offset)
            if not chunk:
                raise QualificationError(f"input changed or was truncated while reading: {path}")
            chunks.append(chunk)
            offset += len(chunk)
        after = os.fstat(fd)
        identity = lambda st: (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns)
        if identity(before) != identity(after):
            raise QualificationError(f"input changed while being read: {path}")
        return b"".join(chunks), after
    finally:
        os.close(fd)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _parse_valid_signature(status: str, expected_fingerprint: str) -> dict[str, str]:
    valid = []
    for line in status.splitlines():
        if line.startswith("[GNUPG:] VALIDSIG "):
            fields = line.split()
            if len(fields) < 12:
                raise QualificationError("GPG returned a malformed VALIDSIG status")
            valid.append(fields)
    if len(valid) != 1:
        raise QualificationError("GPG did not report exactly one valid detached signature")
    fields = valid[0]
    signer = fields[2].upper()
    primary = fields[-1].upper()
    if signer != expected_fingerprint and primary != expected_fingerprint:
        raise QualificationError("GNU source signature came from an unapproved signing key")
    if primary != expected_fingerprint:
        raise QualificationError("GNU release signature is not rooted in the pinned primary key")
    try:
        timestamp = int(fields[4], 10)
    except ValueError as exc:
        raise QualificationError("GPG returned an invalid signature timestamp") from exc
    if timestamp <= 0:
        raise QualificationError("GPG returned a nonpositive signature timestamp")
    return {"signer_fingerprint": signer, "primary_fingerprint": primary,
            "signature_epoch": str(timestamp)}


def _run_gpg(archive_bytes: bytes, signature_bytes: bytes,
             keyring_bytes: bytes, spec: dict[str, Any]) -> dict[str, str]:
    with tempfile.TemporaryDirectory(prefix="swapz-gnu-gpg-") as temp_name:
        temp = Path(temp_name)
        home = temp / "gnupg"
        home.mkdir(mode=0o700)
        archive = temp / spec["archive_name"]
        signature = temp / (spec["archive_name"] + ".sig")
        keyring = temp / "gnu-keyring.gpg"
        archive.write_bytes(archive_bytes)
        signature.write_bytes(signature_bytes)
        keyring.write_bytes(keyring_bytes)
        for path in (archive, signature, keyring):
            path.chmod(0o600)

        base = ["/usr/bin/gpg", "--batch", "--no-options", "--homedir", str(home),
                "--no-default-keyring", "--keyring", str(keyring)]
        try:
            key_result = subprocess.run(
                base + ["--with-colons", "--fingerprint", spec["signer_keyid"]],
                check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                timeout=30, env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
            )
            key_text = key_result.stdout.decode("utf-8", errors="replace")
            fingerprints = [line.split(":")[9].upper() for line in key_text.splitlines()
                            if line.startswith("fpr:") and len(line.split(":")) > 9]
            if key_result.returncode != 0 or spec["signer_fingerprint"] not in fingerprints:
                raise QualificationError("provided GNU keyring lacks the pinned release key")

            result = subprocess.run(
                base + ["--status-fd=1", "--verify", str(signature), str(archive)],
                check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                timeout=30, env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise QualificationError(f"cannot run bounded GPG verification: {exc}") from exc
        status = result.stdout.decode("utf-8", errors="replace")
        if result.returncode != 0:
            detail = result.stderr.decode("utf-8", errors="replace")[:512]
            raise QualificationError(f"GNU detached signature verification failed: {detail}")
        return _parse_valid_signature(status, spec["signer_fingerprint"])


def _check_tar_layout(archive_bytes: bytes, version: str) -> dict[str, str]:
    expected_root = f"coreutils-{version}"
    roots: set[str] = set()
    configure_text: str | None = None
    tarball_version: str | None = None
    news_text: str | None = None
    try:
        import io
        with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:xz") as bundle:
            for member in bundle.getmembers():
                path = PurePosixPath(member.name)
                if (path.is_absolute() or not path.parts
                        or any(part in {"", ".", ".."} for part in path.parts)):
                    raise QualificationError("signed GNU archive contains an unsafe path")
                roots.add(path.parts[0])
                if member.issym() or member.islnk():
                    link = PurePosixPath(member.linkname)
                    if link.is_absolute() or ".." in link.parts:
                        raise QualificationError("signed GNU archive contains an escaping link")
                elif not (member.isfile() or member.isdir()):
                    raise QualificationError("signed GNU archive contains a special file")
                if member.name == f"{expected_root}/configure.ac":
                    stream = bundle.extractfile(member)
                    if stream is None:
                        raise QualificationError("signed GNU archive has no readable configure.ac")
                    configure_text = stream.read(1024 * 1024).decode("utf-8", errors="strict")
                elif member.name == f"{expected_root}/.tarball-version":
                    stream = bundle.extractfile(member)
                    if stream is None:
                        raise QualificationError("signed GNU archive has no release version marker")
                    tarball_version = stream.read(128).decode("ascii", errors="strict").strip()
                elif member.name == f"{expected_root}/NEWS":
                    stream = bundle.extractfile(member)
                    if stream is None:
                        raise QualificationError("signed GNU archive has no NEWS file")
                    news_text = stream.read(1024 * 1024).decode("utf-8", errors="strict")
    except (tarfile.TarError, OSError, UnicodeError) as exc:
        if isinstance(exc, QualificationError):
            raise
        raise QualificationError(f"cannot inspect signed GNU source archive: {exc}") from exc
    if roots != {expected_root} or configure_text is None or news_text is None:
        raise QualificationError("archive layout does not match the pinned GNU release")
    if "AC_INIT([GNU coreutils]," not in configure_text or tarball_version != version:
        raise QualificationError("signed source tree configure metadata has the wrong release identity")
    if not re.search(r"release " + re.escape(version) + r" \(", news_text[:8192]):
        raise QualificationError("signed GNU NEWS release heading has the wrong version")
    return {"top_level_directory": expected_root, "configure_identity": f"GNU coreutils {version}"}


def verify_source_archive(archive_path: Path, signature_path: Path, keyring_path: Path,
                          version: str = "9.11") -> dict[str, Any]:
    spec = RELEASES.get(version)
    if spec is None:
        raise QualificationError("release is not in the independently reviewed release allowlist")
    archive, _ = _read_regular(archive_path, maximum=MAX_ARCHIVE_BYTES)
    signature, _ = _read_regular(signature_path, maximum=MAX_SIGNATURE_BYTES)
    keyring, _ = _read_regular(keyring_path, maximum=MAX_KEYRING_BYTES)
    digest = _sha256(archive)
    expected_digest = base64.b64decode(spec["archive_sha256_b64"], validate=True).hex()
    if digest != expected_digest:
        raise QualificationError("source archive SHA-256 differs from the GNU release announcement")
    layout = _check_tar_layout(archive, version)
    signature_result = _run_gpg(archive, signature, keyring, spec)
    if int(signature_result["signature_epoch"]) != spec["signature_epoch"]:
        raise QualificationError("GPG signature timestamp differs from the pinned release signature")
    return {
        "schema": "swapz.gnu-coreutils-source.v1",
        "release": version,
        "archive_name": spec["archive_name"],
        "archive_sha256": digest,
        "signature_sha256": _sha256(signature),
        "gnu_keyring_sha256": _sha256(keyring),
        "gpg_verifier": _tool_identity("/usr/bin/gpg"),
        "published_sha256_base64": spec["archive_sha256_b64"],
        "release_signer_fingerprint": spec["signer_fingerprint"],
        "release_signature_epoch": int(signature_result["signature_epoch"]),
        "release_commit": spec["release_commit"],
        "source_authentication": "GNU detached signature verified; full key fingerprint pinned",
        "archive_layout": layout,
        "release_announcement": spec["announcement"],
        "archive_url": spec["archive_url"],
        "signature_url": spec["signature_url"],
        "trust_note": "This authenticates the GNU release source archive, not any locally built binary or production application key.",
    }


def _parse_static_elf(fd: int, size: int) -> dict[str, Any]:
    header = os.pread(fd, 64, 0)
    if (len(header) != 64 or header[:4] != b"\x7fELF"
            or header[4] != 2 or header[5] != 1 or header[6] != 1):
        raise QualificationError("candidate is not a valid little-endian ELF64 executable")
    elf_type, machine = struct.unpack_from("<HH", header, 16)
    if elf_type not in {2, 3}:
        raise QualificationError("candidate ELF type is not executable")
    supported = {"x86_64": (62, "x86_64"), "aarch64": (183, "aarch64")}
    host = platform.machine().lower()
    if host not in supported or machine != supported[host][0]:
        raise QualificationError("candidate ELF architecture is unsupported or mismatched")
    phoff = struct.unpack_from("<Q", header, 32)[0]
    phentsize, phnum = struct.unpack_from("<HH", header, 54)
    if phnum and (phentsize < 56 or phnum > 1024 or phoff > size
                  or phentsize * phnum > size - phoff):
        raise QualificationError("candidate ELF program header table is malformed")
    for index in range(phnum):
        raw = os.pread(fd, 4, phoff + index * phentsize)
        if len(raw) != 4:
            raise QualificationError("candidate ELF program header is truncated")
        program_type = struct.unpack("<I", raw)[0]
        if program_type == 3:
            raise QualificationError("candidate is dynamically linked (PT_INTERP present)")
        if program_type == 2:
            raise QualificationError("candidate has a PT_DYNAMIC segment")
    return {"elf_class": "ELF64", "endianness": "little", "machine": supported[host][1],
            "elf_type": "ET_EXEC" if elf_type == 2 else "ET_DYN", "static": True}


def _inspect_binary(path: Path, expected_version: str,
                    expected_sha256: str | None = None) -> dict[str, Any]:
    flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise QualificationError(f"cannot pin candidate GNU dd: {exc}") from exc
    try:
        before = os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or before.st_size <= 0
                or before.st_size > MAX_BINARY_BYTES
                or before.st_mode & (stat.S_ISUID | stat.S_ISGID | 0o022)):
            raise QualificationError("candidate executable metadata is unsafe")
        try:
            caps = os.getxattr(fd, "security.capability")
        except OSError as exc:
            if exc.errno not in {getattr(errno, "ENODATA", 61),
                                 getattr(errno, "ENOATTR", 61)}:
                raise QualificationError(f"cannot inspect candidate file capabilities: {exc}") from exc
        else:
            if caps:
                raise QualificationError("candidate executable has file capabilities")
        digest = hashlib.sha256()
        offset = 0
        while offset < before.st_size:
            chunk = os.pread(fd, min(1024 * 1024, before.st_size - offset), offset)
            if not chunk:
                raise QualificationError("candidate executable changed or truncated during hashing")
            digest.update(chunk)
            offset += len(chunk)
        actual_sha256 = digest.hexdigest()
        if expected_sha256 is not None and actual_sha256 != expected_sha256:
            raise QualificationError("candidate executable digest differs from its build record")
        elf = _parse_static_elf(fd, before.st_size)
        executable = f"/proc/self/fd/{fd}"
        try:
            result = subprocess.run(
                [executable, "--version"], executable=executable, pass_fds=(fd,), close_fds=True,
                env={"PATH": "/usr/bin:/bin", "LC_ALL": "C", "TZ": "UTC"},
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                timeout=5, check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise QualificationError(f"pinned candidate --version failed: {exc}") from exc
        version_text = (result.stdout + result.stderr).decode("utf-8", errors="replace")[:4096]
        if result.returncode != 0 or not re.search(
                r"\bdd \(coreutils\) " + re.escape(expected_version) + r"(?:\s|$)",
                version_text):
            raise QualificationError("candidate does not identify as the expected GNU coreutils dd build")
        after = os.fstat(fd)
        path_after = os.stat(path, follow_symlinks=False)
        identity = lambda st: (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns)
        if (identity(before) != identity(after)
                or (path_after.st_dev, path_after.st_ino) != (before.st_dev, before.st_ino)):
            raise QualificationError("candidate executable changed during identity qualification")
        return {
            "sha256": actual_sha256, "size": before.st_size,
            "mode": format(stat.S_IMODE(before.st_mode), "04o"),
            "version_output": version_text.strip(), "elf": elf,
            "setid_bits": False, "file_capabilities": False,
            "pinned_descriptor_path_rechecked": True,
        }
    finally:
        os.close(fd)


def _tool_version(path: str) -> str:
    result = subprocess.run([path, "--version"], check=False, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            timeout=10, env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"})
    if result.returncode:
        raise QualificationError(f"cannot record build tool version: {path}")
    return result.stdout.splitlines()[0] if result.stdout else "unknown"


def _tool_probe(path: str, *arguments: str) -> str:
    result = subprocess.run([path, *arguments], check=False, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            timeout=10, env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"})
    if result.returncode:
        raise QualificationError(f"cannot record build tool property: {path} {arguments}")
    return result.stdout.strip()


def _tool_identity(path: str) -> dict[str, Any]:
    resolved = Path(path).resolve(strict=True)
    content, info = _read_regular(resolved, maximum=MAX_BINARY_BYTES)
    if (info.st_uid not in {0, os.geteuid()} or info.st_mode & 0o022
            or info.st_mode & (stat.S_ISUID | stat.S_ISGID)):
        raise QualificationError(f"build tool is not owner-controlled and nonwritable: {resolved}")
    try:
        caps = os.getxattr(resolved, "security.capability", follow_symlinks=False)
    except OSError as exc:
        if exc.errno not in {getattr(errno, "ENODATA", 61), getattr(errno, "ENOATTR", 61)}:
            raise QualificationError(f"cannot inspect build tool capabilities: {resolved}: {exc}") from exc
    else:
        if caps:
            raise QualificationError(f"build tool has file capabilities: {resolved}")
    return {"requested_path": path, "resolved_path": str(resolved),
            "sha256": _sha256(content), "size": info.st_size,
            "mode": format(stat.S_IMODE(info.st_mode), "04o"), "owner_uid": info.st_uid,
            "version": _tool_version(path)}


def _extract_signed_source(archive_fd: int, archive_bytes: bytes,
                           destination: Path, version: str) -> Path:
    _check_tar_layout(archive_bytes, version)
    destination.mkdir(mode=0o700)
    result = subprocess.run(
        ["/usr/bin/tar", "--extract", "--no-same-owner", "--no-same-permissions",
         "--file", f"/proc/self/fd/{archive_fd}", "--directory", str(destination)],
        check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60,
        env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"}, close_fds=True,
        pass_fds=(archive_fd,),
    )
    if result.returncode:
        detail = result.stderr.decode("utf-8", errors="replace")[:512]
        raise QualificationError(f"cannot extract authenticated GNU source archive: {detail}")
    source = destination / f"coreutils-{version}"
    if not source.is_dir() or source.is_symlink():
        raise QualificationError("extracted GNU source tree identity is invalid")
    return source


def _build_once(source: Path, build_dir: Path, source_date_epoch: int) -> tuple[Path, dict[str, str]]:
    build_dir.mkdir(mode=0o700)
    configure_log = build_dir / "configure.log"
    build_log = build_dir / "build.log"
    env = {
        "PATH": "/usr/bin:/bin", "LC_ALL": "C", "LANG": "C", "TZ": "UTC",
        "SOURCE_DATE_EPOCH": str(source_date_epoch), "CC": "/usr/bin/gcc",
        "CFLAGS": f"-O2 -g0 -ffile-prefix-map={source}=.", "LDFLAGS": "-static",
        "CONFIG_SHELL": "/bin/bash",
    }
    with configure_log.open("wb") as output:
        configure = subprocess.run(
            [str(source / "configure"), *BUILD_CONFIGURE_ARGS], cwd=source,
            env=env, stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT,
            check=False, timeout=900,
        )
    if configure.returncode:
        tail = configure_log.read_text(errors="replace")[-3000:]
        raise QualificationError(f"GNU coreutils configure failed:\n{tail}")
    with build_log.open("wb") as output:
        build = subprocess.run(
            ["/usr/bin/make", f"-j{BUILD_JOBS}"], cwd=source, env=env,
            stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT,
            check=False, timeout=1800,
        )
    if build.returncode:
        tail = build_log.read_text(errors="replace")[-5000:]
        raise QualificationError(f"GNU coreutils build failed:\n{tail}")
    binary = source / "src" / "dd"
    if not binary.is_file() or binary.is_symlink():
        raise QualificationError("build did not produce the expected src/dd executable")
    flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(binary, flags)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_nlink != 1:
            raise QualificationError("built dd is not a private, singly-linked regular file")
        # Some developer hosts use umask 0002, and GNU make preserves that in
        # its linked output. Normalize the executable to an explicit safe mode
        # through the pinned descriptor before trust inspection.
        os.fchmod(fd, 0o755)
    finally:
        os.close(fd)
    return binary, {"configure_log_sha256": _sha256(configure_log.read_bytes()),
                    "build_log_sha256": _sha256(build_log.read_bytes())}


def build_static(archive_path: Path, signature_path: Path, keyring_path: Path,
                 output_dir: Path, version: str = "9.11") -> dict[str, Any]:
    source_record = verify_source_archive(archive_path, signature_path, keyring_path, version)
    archive_bytes, _ = _read_regular(archive_path, maximum=MAX_ARCHIVE_BYTES)
    spec = RELEASES[version]
    output_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
    archive_copy = output_dir / spec["archive_name"]
    copy_fd = os.open(archive_copy, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600)
    try:
        offset = 0
        while offset < len(archive_bytes):
            written = os.write(copy_fd, archive_bytes[offset:offset + 1024 * 1024])
            if written <= 0:
                raise QualificationError("short write copying authenticated source archive")
            offset += written
        os.fsync(copy_fd)
    finally:
        os.close(copy_fd)
    archive_fd = os.open(archive_copy, os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0))
    try:
        copied = os.fstat(archive_fd)
        if (not stat.S_ISREG(copied.st_mode) or copied.st_size != len(archive_bytes)
                or _sha256(os.pread(archive_fd, copied.st_size, 0)) != source_record["archive_sha256"]):
            raise QualificationError("private build archive copy failed identity verification")
        build_results = []
        for index in (1, 2):
            copy_root = output_dir / f"copy-{index}"
            copy_root.mkdir(mode=0o700)
            source = _extract_signed_source(archive_fd, archive_bytes, copy_root / "source", version)
            binary, logs = _build_once(source, copy_root / "build", spec["source_date_epoch"])
            binary_record = _inspect_binary(binary, version)
            build_results.append({"binary": str(binary), "binary_record": binary_record,
                                  "logs": logs, "source_path_map": "<source-tree> -> ."})
    finally:
        os.close(archive_fd)
    digests = [item["binary_record"]["sha256"] for item in build_results]
    record = {
        "schema": "swapz.gnu-coreutils-dd-build.v1",
        "qualification": "source authenticated; two same-host clean builds compared",
        "source": source_record,
        "build_recipe": {
            "configure": ["./configure", *BUILD_CONFIGURE_ARGS],
            "make": ["/usr/bin/make", f"-j{BUILD_JOBS}"],
            "environment": {
                "CC": "/usr/bin/gcc", "CFLAGS": "-O2 -g0 -ffile-prefix-map=<source-tree>=.",
                "LDFLAGS": "-static", "LC_ALL": "C", "LANG": "C", "TZ": "UTC",
                "SOURCE_DATE_EPOCH": str(spec["source_date_epoch"]),
            },
            "install_or_system_changes": False,
        },
        "toolchain": {
            "python": sys.version.split()[0], "architecture": platform.machine(),
            "host_platform": platform.platform(), "kernel_release": platform.release(),
            "gcc": _tool_identity("/usr/bin/gcc"),
            "make": _tool_identity("/usr/bin/make"),
            "linker": _tool_identity("/usr/bin/ld"),
            "assembler": _tool_identity("/usr/bin/as"),
            "archiver": _tool_identity("/usr/bin/ar"),
            "ranlib": _tool_identity("/usr/bin/ranlib"),
            "tar": _tool_identity("/usr/bin/tar"),
            "compiler_target": _tool_probe("/usr/bin/gcc", "-dumpmachine"),
            "static_libc_archive": _tool_probe("/usr/bin/gcc", "-print-file-name=libc.a"),
        },
        "binary": build_results[0]["binary_record"],
        "rebuild_comparison": {
            "build_count": 2, "sha256_by_build": digests,
            "same_host_byte_identical": len(set(digests)) == 1,
            "independent_builder_reproduction": "not performed",
        },
        "build_logs": [item["logs"] for item in build_results],
        "worker_seccomp_execution": "NOT RUN by build command",
        "production_manifest_or_key_installed": False,
    }
    _write_json(output_dir / "qualification-record.json", record)
    return record


def _write_json(path: Path, value: dict[str, Any]) -> None:
    payload = (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()
    temp = path.with_name(path.name + ".tmp")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600)
    try:
        offset = 0
        while offset < len(payload):
            written = os.write(fd, payload[offset:])
            if written <= 0:
                raise OSError("short qualification record write")
            offset += written
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(temp, path)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="operation", required=True)
    for operation in ("verify-source", "build-static"):
        command = sub.add_parser(operation)
        command.add_argument("--archive", type=Path, required=True)
        command.add_argument("--signature", type=Path, required=True)
        command.add_argument("--keyring", type=Path, required=True,
                             help="locally obtained GNU keyring; exact signer fingerprint is pinned")
        command.add_argument("--version", choices=tuple(RELEASES), default="9.11")
        if operation == "verify-source":
            command.add_argument("--record", type=Path, required=True)
        else:
            command.add_argument("--output-dir", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.operation == "verify-source":
            record = verify_source_archive(args.archive, args.signature, args.keyring, args.version)
            _write_json(args.record, record)
            print(json.dumps(record, sort_keys=True))
        else:
            record = build_static(args.archive, args.signature, args.keyring,
                                  args.output_dir, args.version)
            print(json.dumps(record, sort_keys=True))
    except (QualificationError, OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"UNQUALIFIED: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
