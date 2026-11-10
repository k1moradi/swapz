#!/usr/bin/env python3
"""Private creation-proof recovery for abandoned benchmark RAM resources.

This never adopts legacy PID/name-only sessions, formats storage, kills holders,
or deletes scratch evidence. Qualification success is a separate protocol.
"""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import time

RECORD = ".swapz-benchmark-resources"
SESSION = re.compile(r"swapz-benchmark\.[A-Za-z0-9]{8}\Z")
DISK = re.compile(r"nullb-swapz-[a-f0-9]{16}\Z")
SHA = re.compile(r"[a-f0-9]{40}\Z")
MAX_RECORD = 8192


class Refused(RuntimeError):
    pass


def require(condition, reason):
    if not condition:
        raise Refused(reason)


def identity(value):
    return [value.st_dev, value.st_ino]


def file_identity(value):
    return (value.st_dev, value.st_ino, value.st_mode, value.st_uid,
            value.st_nlink, value.st_size, value.st_mtime_ns, value.st_ctime_ns)


def secure_read(directory, name, limit=MAX_RECORD, uid=0):
    fd = os.open(name, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW |
                 os.O_NONBLOCK, dir_fd=directory)
    try:
        before = os.fstat(fd)
        require(stat.S_ISREG(before.st_mode) and before.st_uid == uid and
                stat.S_IMODE(before.st_mode) == 0o600 and before.st_nlink == 1
                and before.st_size <= limit and mount_id(fd) == mount_id(directory),
                "record-metadata")
        data = os.read(fd, limit + 1)
        require(len(data) == before.st_size and
                os.pread(fd, limit + 1, 0) == data and
                file_identity(before) == file_identity(os.fstat(fd)),
                "record-changed")
        return data, before
    finally:
        os.close(fd)


def mount_id(fd):
    rows = [v.split()[1] for v in Path(f"/proc/self/fdinfo/{fd}").read_text().splitlines()
            if v.startswith("mnt_id:")]
    require(len(rows) == 1, "mount-identity")
    return rows[0]


def open_session(root, name, uid=0):
    require(SESSION.fullmatch(name), "session-name")
    fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW |
                 os.O_CLOEXEC, dir_fd=root)
    try:
        value = os.fstat(fd)
        require(value.st_uid == uid and stat.S_IMODE(value.st_mode) == 0o700
                and mount_id(fd) == mount_id(root), "session-metadata-or-mount")
        return fd
    except BaseException:
        os.close(fd)
        raise


def process_start(pid):
    try:
        record = Path(f"/proc/{pid}/stat").read_text()
    except FileNotFoundError:
        return None
    fields = record.rsplit(") ", 1)[1].split()
    require(len(fields) >= 20 and fields[19].isdecimal(), "process-identity")
    return int(fields[19])


def unique_object(pairs):
    value = {}
    for key, item in pairs:
        require(key not in value, "duplicate-record-key")
        value[key] = item
    return value


def swap_identity(data):
    rows = data.decode("utf-8").splitlines()
    require(rows and rows[0].split() == ["Filename", "Type", "Size", "Used", "Priority"],
            "swap-inventory-header")
    result = []
    for line in rows[1:]:
        fields = line.split()
        require(len(fields) == 5 and fields[0].startswith("/") and
                fields[1] in ("partition", "file") and fields[2].isdecimal() and
                fields[3].isdecimal() and 0 <= int(fields[3]) <= int(fields[2]) and
                re.fullmatch(r"-?[0-9]+", fields[4]), "swap-inventory-row")
        result.append([fields[0], fields[1], fields[2], fields[4]])
    require(len({r[0] for r in result}) == len(result), "duplicate-swap-row")
    return sorted(result)


def parse_claim(data, session_identity, owner):
    claim = json.loads(data, object_pairs_hook=unique_object)
    require(isinstance(claim, dict), "record-object")
    require(set(claim) == {"schema", "boot", "pid", "start", "source",
                          "session", "devices", "mapper", "module", "host_swaps"}, "record-fields")
    require(claim["schema"] == "swapz-owned-ram-v1" and isinstance(claim["boot"], str) and
            re.fullmatch(r"[a-f0-9-]{36}", claim["boot"]) and
            type(claim["pid"]) is int and 0 < claim["pid"] < 1 << 31 and
            type(claim["start"]) is int and claim["start"] > 0 and
            isinstance(claim["source"], str) and SHA.fullmatch(claim["source"])
            and claim["session"] == session_identity, "record-owner-identity")
    require(owner == f"pid={claim['pid']}\nsource_sha={claim['source']}\n".encode(),
            "owner-marker-mismatch")
    devices = claim["devices"]
    require(isinstance(devices, list) and len(devices) == 2 and
            all(isinstance(d, dict) and isinstance(d.get("name"), str) and
                DISK.fullmatch(d["name"]) for d in devices) and
            devices[0]["name"] != devices[1]["name"], "record-device-scope")
    mapper = claim["mapper"]
    require(isinstance(mapper, dict) and isinstance(mapper.get("name"), str) and
            re.fullmatch(r"swapz-demo-[a-f0-9]{16}", mapper["name"]) and
            mapper.get("uuid") == "SWAPZ-TEST-" + mapper["name"][-16:],
            "record-mapper-scope")
    require(claim["module"] is None or isinstance(claim["module"], dict),
            "record-module-scope")
    def inode(value):
        return (isinstance(value, list) and len(value) == 2 and
                all(type(n) is int and n > 0 for n in value))
    def devno(value):
        return isinstance(value, str) and re.fullmatch(r"[1-9][0-9]*:(0|[1-9][0-9]*)", value)
    for device in devices:
        require(set(device) == {"name", "config", "memory_backed", "size",
                                "blocksize", "queue_mode", "power", "index", "devno", "block"}
                and inode(device["config"]) and inode(device["block"])
                and all(type(device[k]) is int for k in
                        ("memory_backed", "size", "blocksize", "queue_mode", "power", "index"))
                and [device[k] for k in ("memory_backed", "size", "blocksize", "queue_mode", "power")]
                == [1, 64, 4096, 2, 1] and device["index"] >= 0 and devno(device["devno"]),
                "record-device-proof")
    require(devices[0]["config"] != devices[1]["config"] and
            devices[0]["devno"] != devices[1]["devno"], "duplicate-device-proof")
    require(set(mapper) == {"name", "uuid", "devno", "block", "kernel", "table", "slaves", "target"}
            and inode(mapper["block"]) and devno(mapper["devno"])
            and re.fullmatch(r"dm-[0-9]+", mapper["kernel"])
            and re.fullmatch(r"[a-f0-9]{64}", mapper["table"])
            and mapper["slaves"] == [devices[1]["devno"]], "record-mapper-proof")
    require(mapper["target"] == ("swapz" if claim["module"] is not None else "linear"),
            "record-target-scope")
    if claim["module"] is not None:
        require(set(claim["module"]) == {"identity", "source"} and
                inode(claim["module"]["identity"]) and
                isinstance(claim["module"]["source"], str) and
                SHA.fullmatch(claim["module"]["source"]), "record-module-proof")
    require(isinstance(claim["host_swaps"], list) and
            all(isinstance(row, list) and len(row) == 4 and
                all(isinstance(v, str) for v in row) for row in claim["host_swaps"]),
            "record-swap-proof")
    return claim


class Linux:
    def command(self, *args):
        result = subprocess.run(args, check=False, capture_output=True,
                                text=True, timeout=15)
        require(result.returncode == 0, "resource-command-failed")
        return result.stdout.strip()

    def device(self, name):
        require(DISK.fullmatch(name), "device-name")
        config = Path("/sys/kernel/config/nullb") / name
        try:
            value = config.lstat()
        except FileNotFoundError:
            return None
        require(stat.S_ISDIR(value.st_mode) and value.st_uid == 0 and
                not value.st_mode & 0o022, "config-identity")
        def number(field):
            path = config / field
            require(not path.is_symlink(), "config-attribute-symlink")
            metadata = path.stat()
            require(stat.S_ISREG(metadata.st_mode) and metadata.st_uid == 0 and
                    not metadata.st_mode & 0o022, "config-attribute-owner")
            text = path.read_text().strip()
            require(re.fullmatch(r"0|[1-9][0-9]*", text), "config-attribute-value")
            return int(text)
        result = {"name": name, "config": identity(value),
                  "memory_backed": number("memory_backed"), "size": number("size"),
                  "blocksize": number("blocksize"), "queue_mode": number("queue_mode"),
                  "power": number("power")}
        require([result[k] for k in ("memory_backed", "size", "blocksize", "queue_mode")]
                == [1, 64, 4096, 2] and result["power"] in (0, 1), "not-qualified-ram")
        block = Path("/sys/block") / name
        if result["power"] == 0:
            require(not block.exists(), "powered-off-device-still-present")
            return result
        result["index"] = number("index")
        result["devno"] = (block / "dev").read_text().strip()
        major, minor = [int(v) for v in result["devno"].split(":")]
        block_devices = Path("/proc/devices").read_text().split("Block devices:\n", 1)[1]
        require(f"{major} nullb" in block_devices.splitlines() and
                minor == result["index"] and
                block.resolve() == Path("/sys/devices/virtual/block") / name and
                Path("/sys/dev/block", result["devno"]).resolve() == block.resolve()
                and (block / "size").read_text().strip() == "131072", "ram-block-identity")
        node = os.lstat("/dev/" + name)
        require(stat.S_ISBLK(node.st_mode) and
                (os.major(node.st_rdev), os.minor(node.st_rdev)) == (major, minor),
                "ram-node-identity")
        result["block"] = identity(block.stat())
        result["holders"] = sorted(p.name for p in (block / "holders").iterdir())
        return result

    def mapper(self, name, uuid):
        found = []
        for path in Path("/sys/block").glob("dm-*"):
            actual_name = (path / "dm/name").read_text().strip()
            actual_uuid = (path / "dm/uuid").read_text().strip()
            if actual_name == name or actual_uuid == uuid:
                require((actual_name, actual_uuid) == (name, uuid), "mapper-substitution")
                found.append(path)
        require(len(found) <= 1, "ambiguous-mapper")
        if not found:
            return None
        path = found[0]
        table = self.command("dmsetup", "table", "--showkeys", "--uuid", uuid)
        require(len(table) <= 1024 and "\n" not in table, "mapper-table-bound")
        return {"name": name, "uuid": uuid, "devno": (path / "dev").read_text().strip(),
                "block": identity(path.stat()), "kernel": path.name,
                "table": hashlib.sha256(table.encode()).hexdigest(), "target": table.split()[2],
                "slaves": sorted((p / "dev").read_text().strip()
                                 for p in (path / "slaves").iterdir()),
                "opens": int(self.command("dmsetup", "info", "-c", "--noheadings",
                                          "-o", "open", "--uuid", uuid))}

    def module(self):
        path = Path("/sys/module/dm_swapz")
        if not path.exists():
            return None
        return {"identity": identity(path.stat()),
                "source": (path / "parameters/build_source_sha").read_text().strip()}

    def unused(self, claim):
        require(swap_identity(Path("/proc/swaps").read_bytes()) == claim["host_swaps"],
                "host-swap-identity-changed")
        wanted = {d["devno"] for d in claim["devices"]} | {claim["mapper"]["devno"]}
        inspected = 0
        for process in Path("/proc").iterdir():
            if not process.name.isdecimal():
                continue
            try:
                for task in (process / "task").iterdir():
                    for fd in (task / "fd").iterdir():
                        inspected += 1
                        require(inspected <= 1048576, "process-reference-bound")
                        try:
                            value = fd.stat()
                        except (FileNotFoundError, ProcessLookupError):
                            continue
                        require(not (stat.S_ISBLK(value.st_mode) and
                                f"{os.major(value.st_rdev)}:{os.minor(value.st_rdev)}" in wanted),
                                "device-process-reference")
                    for line in (task / "mountinfo").read_text().splitlines():
                        fields = line.split()
                        require(len(fields) >= 10 and fields[2] not in wanted,
                                "device-mount-reference")
            except (FileNotFoundError, ProcessLookupError):
                continue
        for line in Path("/proc/swaps").read_text().splitlines()[1:]:
            fields = line.split()
            require(len(fields) == 5, "swap-inventory")
            path = re.sub(r"\\([0-7]{3})", lambda m: chr(int(m[1], 8)), fields[0])
            value = os.stat(path)
            require(not (stat.S_ISBLK(value.st_mode) and
                    f"{os.major(value.st_rdev)}:{os.minor(value.st_rdev)}" in wanted),
                    "device-active-swap")

    def remove_mapper(self, mapper):
        self.command("dmsetup", "remove", "--uuid", mapper["uuid"])

    def remove_device(self, device):
        require(self.device(device["name"]) == device, "ram-changed-at-mutation")
        path = Path("/sys/kernel/config/nullb") / device["name"]
        fd = os.open(path, os.O_PATH | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            require(identity(os.fstat(fd)) == device["config"], "config-changed-before-mutation")
            if device["power"]:
                power = os.open("power", os.O_WRONLY | os.O_NOFOLLOW, dir_fd=fd)
                try:
                    require(os.write(power, b"0\n") == 2, "short-poweroff")
                finally:
                    os.close(power)
            deadline = time.monotonic() + 5
            while (Path("/sys/block") / device["name"]).exists() and time.monotonic() < deadline:
                time.sleep(0.05)
            require(not (Path("/sys/block") / device["name"]).exists(), "poweroff-incomplete")
            require(identity(path.stat()) == device["config"], "config-substituted")
            os.rmdir(path)
        finally:
            os.close(fd)

    def remove_module(self, expected):
        path = Path("/sys/module/dm_swapz")
        require((path / "refcnt").read_text().strip() == "0" and
                not list((path / "holders").iterdir()), "module-still-used")
        require(self.module() == expected, "module-changed-at-mutation")
        self.command("rmmod", "dm_swapz")


def recover_claim(claim, backend):
    """Only complete creation proofs authorize mutations; absent objects are idempotent."""
    expected_module = claim["module"]
    if expected_module is not None and backend.module() is not None:
        require(backend.module() == expected_module, "module-substitution")
    mapper = backend.mapper(claim["mapper"]["name"], claim["mapper"]["uuid"])
    if mapper is not None:
        require(expected_module is None or backend.module() == expected_module,
                "owned-module-missing")
        require({k: v for k, v in mapper.items() if k != "opens"} == claim["mapper"]
                and mapper["opens"] == 0, "mapper-changed-or-busy")
    def check_device(expected, current, holders):
        keys = ("name", "config", "memory_backed", "size", "blocksize", "queue_mode")
        require(all(current[k] == expected[k] for k in keys), "ram-config-substitution")
        if current["power"]:
            require(all(current[k] == expected[k] for k in ("index", "devno", "block")),
                    "ram-device-substitution")
            require(current["holders"] == holders, "foreign-device-holder")
    for expected in claim["devices"]:
        current = backend.device(expected["name"])
        if current is not None:
            holders = [mapper["kernel"]] if mapper and expected == claim["devices"][1] else []
            check_device(expected, current, holders)
    backend.unused(claim)
    if mapper is not None:
        again = backend.mapper(mapper["name"], mapper["uuid"])
        require(again == mapper, "mapper-changed-before-removal")
        backend.remove_mapper(mapper)
        require(backend.mapper(mapper["name"], mapper["uuid"]) is None, "mapper-remains")
    for expected in reversed(claim["devices"]):
        current = backend.device(expected["name"])
        if current is None:
            continue
        check_device(expected, current, [])
        backend.unused(claim)
        backend.remove_device(current)
        require(backend.device(expected["name"]) is None, "ram-remains")
    if expected_module is not None and backend.module() is not None:
        require(backend.module() == expected_module, "module-changed-before-unload")
        backend.remove_module(expected_module)
        require(backend.module() is None, "module-remains")


def save_claim(directory, claim):
    data = (json.dumps(claim, sort_keys=True) + "\n").encode()
    require(len(data) <= MAX_RECORD, "record-bound")
    # The root-only session is already pinned and checked by the caller.
    name = ".resource-" + os.urandom(8).hex()
    fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                 0o600, dir_fd=directory)
    try:
        require(os.write(fd, data) == len(data), "short-record-write")
        os.fsync(fd)
    finally:
        os.close(fd)
    os.rename(name, RECORD, src_dir_fd=directory, dst_dir_fd=directory)
    os.fsync(directory)


def register(session, pid, source, mapper_name, mapper_uuid, owns_module, module_source, names):
    require(os.path.dirname(session) == "/tmp" and os.getppid() == pid and
            SHA.fullmatch(source), "creator-call-context")
    root = os.open("/tmp", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    directory = open_session(root, os.path.basename(session))
    try:
        owner, _ = secure_read(directory, ".swapz-benchmark-owner", 128)
        require(owner == f"pid={pid}\nsource_sha={source}\n".encode(), "creator-marker")
        require(not os.path.lexists(Path(session, RECORD)), "claim-already-exists")
        backend = Linux()
        devices = [backend.device(name) for name in names]
        mapper = backend.mapper(mapper_name, mapper_uuid)
        require(mapper is not None and all(d and d["power"] for d in devices), "creation-incomplete")
        mapper.pop("opens")
        for device in devices:
            device.pop("holders")
        module = backend.module() if owns_module else None
        # Report-only HEADs differ from the embedded executable source SHA.
        # Bind the loaded module to the exact image the producer inserted.
        require(not owns_module or (module is not None and SHA.fullmatch(module_source)
                                   and module["source"] == module_source),
                "created-module-unproven")
        initial_swaps, _ = secure_read(directory, ".swapz-benchmark-swaps")
        host_swaps = swap_identity(initial_swaps)
        require(host_swaps == swap_identity(Path("/proc/swaps").read_bytes()), "host-swap-changed-before-proof")
        claim = {"schema": "swapz-owned-ram-v1", "boot": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
                 "pid": pid, "start": process_start(pid), "source": source,
                 "session": identity(os.fstat(directory)), "devices": devices,
                 "mapper": mapper, "module": module, "host_swaps": host_swaps}
        parse_claim(json.dumps(claim).encode(), identity(os.fstat(directory)), owner)
        save_claim(directory, claim)
    finally:
        os.close(directory)
        os.close(root)


def abandoned(claim, boot, start):
    require(claim["boot"] == boot, "boot-mismatch")
    if start == claim["start"]:
        return False
    require(start is None, "creator-pid-reused")
    return True


def cleanup_abandoned():
    root = os.open("/tmp", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        value = os.fstat(root)
        require(value.st_uid == 0 and stat.S_IMODE(value.st_mode) == 0o1777, "temporary-root")
        entries = os.listdir(root)
        require(len(entries) <= 100000, "root-entry-bound")
        examined = 0
        for name in entries:
            if not SESSION.fullmatch(name):
                continue
            try:
                candidate = os.stat(name, dir_fd=root, follow_symlinks=False)
            except FileNotFoundError:
                continue
            if not (stat.S_ISDIR(candidate.st_mode) and candidate.st_uid == 0 and
                    stat.S_IMODE(candidate.st_mode) == 0o700):
                continue
            directory = open_session(root, name)
            try:
                try:
                    data, before = secure_read(directory, RECORD)
                except FileNotFoundError:
                    continue  # No retroactive authority for legacy sessions.
                examined += 1
                require(examined <= 256, "session-bound")
                owner, _ = secure_read(directory, ".swapz-benchmark-owner", 128)
                claim = parse_claim(data, identity(os.fstat(directory)), owner)
                if not abandoned(claim, Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
                                 process_start(claim["pid"])):
                    continue  # Active producer owns its ordinary teardown.
                require(identity(os.lstat("/tmp")) == identity(os.fstat(root)) and
                        identity(os.stat(name, dir_fd=root, follow_symlinks=False)) == claim["session"],
                        "root-or-session-substituted")
                recover_claim(claim, Linux())
                current, after = secure_read(directory, RECORD)
                require(current == data and file_identity(before) == file_identity(after),
                        "claim-changed-during-recovery")
                require(identity(os.stat(name, dir_fd=root, follow_symlinks=False)) == claim["session"],
                        "session-substituted")
                os.unlink(RECORD, dir_fd=directory)
                os.fsync(directory)
                print("PASS: abandoned owned RAM resources released; failed-run evidence retained")
            finally:
                os.close(directory)
    finally:
        os.close(root)


def main():
    require(os.geteuid() == 0, "root-required")
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    record = commands.add_parser("record")
    record.add_argument("session")
    record.add_argument("pid", type=int)
    record.add_argument("source")
    record.add_argument("mapper")
    record.add_argument("uuid")
    record.add_argument("owns_module", type=int, choices=(0, 1))
    record.add_argument("module_source")
    record.add_argument("names", nargs=2)
    commands.add_parser("recover")
    args = parser.parse_args()
    if args.command == "record":
        register(args.session, args.pid, args.source, args.mapper,
                 args.uuid, args.owns_module, args.module_source, args.names)
    else:
        # Serialize recovery processes. This lock grants no resource ownership;
        # every candidate must still carry its producer's complete proof.
        lock = os.open("/run/lock/swapz-ram-recovery.lock", os.O_RDWR | os.O_CREAT |
                       os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        try:
            value = os.fstat(lock)
            require(stat.S_ISREG(value.st_mode) and value.st_uid == 0 and
                    stat.S_IMODE(value.st_mode) == 0o600 and value.st_nlink == 1,
                    "recovery-lock-metadata")
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            cleanup_abandoned()
        finally:
            os.close(lock)


if __name__ == "__main__":
    try:
        main()
    except Refused as error:
        print("BLOCKED: owned RAM resource recovery reason=" + str(error) +
              "; retain evidence", file=sys.stderr)
        raise SystemExit(1)
    except (OSError, ValueError, KeyError, TypeError, IndexError, subprocess.SubprocessError) as error:
        print("BLOCKED: owned RAM resource proof or cleanup incomplete "
              f"class={type(error).__name__} errno={getattr(error, 'errno', 'unavailable')}; "
              "retain evidence", file=sys.stderr)
        raise SystemExit(1)
