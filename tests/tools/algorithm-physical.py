#!/usr/bin/env python3
"""Single-consent physical algorithm trial, after all five RAM stages pass.

The unprivileged selector never writes devices. Only the already-hardened,
source-bound private probe receives the exact confirmed USB swap partition.
"""
import importlib.util
import json
import os
from pathlib import Path
import platform
import re
import shutil
import stat
import struct
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
PARTUUID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{0,71}")
UUID_PATTERN = re.compile(r"[a-fA-F0-9][a-fA-F0-9-]{7,71}")


def _eligible_partitions(lsblk_output: dict, *,
                         virtual_device_only=False) -> list[dict]:
    """Classify exact swap partitions; bare metal remains USB-only."""
    disks = lsblk_output.get("blockdevices")
    if not isinstance(disks, list):
        raise ValueError("lsblk did not report canonical block devices")
    candidates = []
    for disk in disks:
        if not isinstance(disk, dict) or disk.get("type") != "disk":
            continue
        transport = disk.get("tran")
        if virtual_device_only:
            if (not isinstance(transport, str) or
                    re.fullmatch(r"[A-Za-z0-9_.-]{1,32}", transport) is None):
                continue
        elif transport != "usb":
            continue
        children = disk.get("children")
        # Discovery is read-only. A shared-root USB disk may contain one
        # authorized swap partition without authorizing any sibling partition
        # or allowing the current private physical writer to use that disk.
        if (not isinstance(children, list) or not children or
                any(not isinstance(partition, dict) for partition in children)):
            continue
        child_paths = [partition.get("path") for partition in children]
        if (any(not isinstance(path, str) or not path.startswith("/dev/")
                for path in child_paths) or len(child_paths) != len(set(child_paths))):
            continue
        for partition in children:
            if not isinstance(partition, dict) or \
                    partition.get("type") != "part" or \
                    partition.get("fstype") != "swap":
                continue
            # lsblk uses [SWAP] for an active swap area; it is not a
            # filesystem mount. Cross-check it against /proc/swaps below.
            if partition.get("mountpoints") not in (
                    None, [], [None], ["[SWAP]"]):
                continue
            partuuid = partition.get("partuuid")
            swap_uuid = partition.get("uuid")
            path = partition.get("path")
            size = partition.get("size")
            if not isinstance(disk.get("path"), str) or \
                    not disk["path"].startswith("/dev/") or \
                    not isinstance(partuuid, str) or \
                    PARTUUID_PATTERN.fullmatch(partuuid) is None or \
                    (swap_uuid is not None and (
                        not isinstance(swap_uuid, str) or
                        UUID_PATTERN.fullmatch(swap_uuid) is None)) or \
                    not isinstance(path, str) or not path.startswith("/dev/") or \
                    type(size) is not int or size < 64 * 1024 * 1024:
                continue
            candidates.append({
                "path": path, "partuuid": partuuid,
                "uuid": swap_uuid, "size_bytes": size,
                "parent": disk.get("path"),
                "parent_transport": transport,
                "parent_has_other_partitions": len(children) != 1,
                "lsblk_active_swap": partition.get("mountpoints") == ["[SWAP]"],
                "virtual_device_only": virtual_device_only,
            })
    return candidates


def _select_swap_partition(candidates: list[dict]) -> dict | None:
    """Select one identified partition, without authorizing any write."""
    if not candidates:
        raise ValueError("no identifiable swap partition")
    # The swap UUID can be intentionally cleared or duplicated. Stable
    # partition-table identities, not swap signatures, select the target.
    for key in ("path", "partuuid"):
        identities = [candidate[key].lower() for candidate in candidates]
        if len(set(identities)) != len(identities):
            raise ValueError("duplicate USB swap partition identity")
    if len(candidates) == 1:
        return candidates[0]
    label = ("VM swap partitions" if candidates[0].get("virtual_device_only")
             else "USB swap partitions")
    print(f"Identifiable {label} (selection is not authorization):")
    for number, candidate in enumerate(candidates, start=1):
        print(f"  {number}. {candidate['path']}  Parent: {candidate['parent']}  "
              f"PARTUUID: {candidate['partuuid']}  "
              f"Bytes: {candidate['size_bytes']}")
    try:
        selection = input(
            f"Select swap partition [1-{len(candidates)}, Enter to cancel]: ")
    except EOFError:
        return None
    if not selection:
        return None
    if (not selection.isascii() or not selection.isdecimal() or
            int(selection) not in range(1, len(candidates) + 1)):
        raise ValueError("swap partition selection is invalid")
    return candidates[int(selection) - 1]


def _selected_swap_inventory(partition: dict, swap_lines: list[str]) -> dict:
    """Observe exact active swap identity, never authorize a swapoff.

    The root-controlled worker must recheck every observation before mutation.
    """
    try:
        selected_stat = os.stat(partition["path"])
    except OSError as error:
        raise ValueError("cannot stat selected swap partition") from error
    if not stat.S_ISBLK(selected_stat.st_mode):
        raise ValueError("selected swap partition is not a block device")
    matching = []
    unrelated = 0
    unrelated_swapfiles = 0
    unrelated_partitions = 0
    for line in swap_lines[1:]:
        fields = line.split()
        if len(fields) != 5:
            raise ValueError("swap inventory row is malformed")
        swap_path, swap_kind, capacity, used, priority = fields
        if (not swap_path.startswith("/") or
                swap_kind not in {"partition", "file"}):
            raise ValueError("swap inventory type or path is invalid")
        try:
            capacity_kib = int(capacity)
            used_kib = int(used)
            priority_number = int(priority)
        except ValueError as error:
            raise ValueError("swap inventory numeric field is invalid") from error
        if (not capacity.isdecimal() or not used.isdecimal() or
                capacity_kib < 1 or used_kib < 0 or used_kib > capacity_kib or
                not -32768 <= priority_number <= 32767):
            raise ValueError("swap inventory capacity or priority is invalid")
        if swap_kind == "file":
            unrelated += 1
            unrelated_swapfiles += 1
            continue
        try:
            active_stat = os.stat(swap_path)
        except OSError as error:
            raise ValueError("cannot identify active block swap") from error
        if not stat.S_ISBLK(active_stat.st_mode):
            raise ValueError("active swap entry is not a block device")
        if active_stat.st_rdev == selected_stat.st_rdev:
            matching.append({"used_kib": used_kib,
                             "priority": priority_number,
                             "capacity_kib": capacity_kib})
        else:
            unrelated += 1
            unrelated_partitions += 1
    if len(matching) > 1:
        raise ValueError("duplicate active swap entries for selected partition")
    active = matching[0] if matching else None
    if partition.get("lsblk_active_swap") and active is None:
        raise ValueError("lsblk swap marker disagrees with active swap inventory")
    return {
        "active_swap": active,
        "other_active_swap_count": unrelated,
        "other_active_swapfile_count": unrelated_swapfiles,
        "other_active_partition_count": unrelated_partitions,
    }


def _require_development_linux_abi() -> None:
    """Reject unsupported kernel page geometry before inspecting storage."""
    if platform.system() != "Linux" or platform.machine() not in (
            "x86_64", "aarch64"):
        raise ValueError("physical trial requires Linux x86_64 or aarch64")
    if (struct.calcsize("P") != 8 or sys.byteorder != "little" or
            os.sysconf("SC_PAGE_SIZE") != 4096):
        raise ValueError("physical trial requires little-endian 64-bit Linux with 4096-byte pages")


def _require_bare_metal_host(*, allow_virtual=False) -> bool:
    """Only an explicitly labeled development trial may admit a verified VM."""
    detector = shutil.which("systemd-detect-virt")
    if detector is None:
        raise ValueError("systemd-detect-virt is required for physical admission")
    virtual_machine = False
    for mode in ("--vm", "--container"):
        result = subprocess.run(
            [detector, mode], check=False, capture_output=True,
            text=True, timeout=10)
        detected = result.stdout.strip()
        if result.returncode == 0:
            if mode == "--vm" and allow_virtual and re.fullmatch(
                    r"[A-Za-z0-9_.-]{1,32}", detected):
                virtual_machine = True
                continue
            kind = mode[2:]
            value = detected if re.fullmatch(r"[A-Za-z0-9_.-]{1,32}", detected) else "detected"
            raise ValueError(
                f"physical trial is not admitted in a {kind}: {value}")
        if result.returncode != 1 or detected not in {"", "none"}:
            raise ValueError(
                f"cannot verify bare-metal {mode[2:]} status")
    return virtual_machine


class PendingRecoveryError(ValueError):
    """Root-owned same-boot cleanup must finish before another trial."""


def _recover_pending_algorithm_trial() -> None:
    """Finish any exact same-boot owned trial before new device discovery."""
    sudo = shutil.which("sudo")
    if sudo is None:
        raise ValueError("sudo is required for prior-trial cleanup preflight")
    command = [
        # sudo may request authentication on the operator's controlling TTY.
        # Only the root helper can inspect the protected /run ownership state.
        sudo, "--", sys.executable, "-I", "-B",
        str(ROOT / "tests/tools/physical-swap-probe.py"),
        "recover-pending",
    ]
    # The root helper owns same-boot cleanup and its bounded child operations.
    # Do not terminate it while it is proving mapper/swap/module ownership.
    result = subprocess.run(command, cwd=ROOT, check=False)
    if result.returncode == 3:
        raise PendingRecoveryError(
            "owned swap cleanup remains unresolved; inspect same-boot state")
    if result.returncode != 0:
        raise ValueError("cannot verify pending physical cleanup status")


def _require_read_only_preflight() -> dict | None:
    if os.geteuid() == 0:
        raise ValueError("algorithm confirmation must run unprivileged")
    _require_development_linux_abi()
    virtual_device_only = _require_bare_metal_host(allow_virtual=True)
    _recover_pending_algorithm_trial()
    # Mirror the kernel's real-partition gate before consent or swapoff.
    # Pending cleanup above remains available on unsupported architectures.
    if platform.machine() not in ("x86_64", "aarch64"):
        raise ValueError("kernel partition backing requires x86_64 or ARM64")
    if Path("/sys/module/dm_swapz").exists():
        raise ValueError("dm_swapz is already loaded; foreign module ownership")
    try:
        swap_lines = Path("/proc/swaps").read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as error:
        raise ValueError("cannot read current swap inventory") from error
    if not swap_lines or swap_lines[0].split() != [
            "Filename", "Type", "Size", "Used", "Priority"]:
        raise ValueError("swap inventory header is malformed")
    # JSON children[] is absent unless NAME is selected or --tree is used.
    # PATH is the identity-bearing column here; preserve it and request the
    # hierarchy explicitly so USB partition children cannot disappear.
    block_info = subprocess.run([
        "lsblk", "--json", "--tree", "--bytes", "--output",
        "PATH,TYPE,FSTYPE,UUID,PARTUUID,SIZE,TRAN,MOUNTPOINTS"],
        capture_output=True, text=True, check=False, timeout=15)
    if block_info.returncode != 0 or len(block_info.stdout) > 1024 * 1024:
        raise ValueError("cannot identify an exact candidate partition")
    try:
        candidates = _eligible_partitions(
            json.loads(block_info.stdout),
            virtual_device_only=virtual_device_only)
    except (ValueError, TypeError, RecursionError) as error:
        raise ValueError("invalid or ambiguous block inventory") from error
    selected = _select_swap_partition(candidates)
    if selected is None:
        return None
    selected.update(_selected_swap_inventory(selected, swap_lines))
    selector = Path("/dev/disk/by-partuuid") / selected["partuuid"]
    if not selector.is_symlink() or \
            os.path.realpath(selector) != os.path.realpath(selected["path"]):
        raise ValueError("partition PARTUUID link does not match the candidate")
    return {**selected, "selector": str(selector),
            "virtual_device_only": virtual_device_only}


def _algorithm_ram_evidence_arguments() -> list[str]:
    """Forward only the exact private evidence path created by make test."""
    path = os.environ.get("SWAPZ_ALGORITHM_RAM_EVIDENCE")
    nonce = os.environ.get("SWAPZ_ALGORITHM_RAM_NONCE")
    if path is None and nonce is None:
        return []
    expected = str(ROOT / "build/tests/algorithm-ram-evidence.json")
    if (path != expected or nonce is None or
            re.fullmatch(r"[0-9a-f]{32}", nonce) is None):
        raise ValueError("algorithm RAM evidence environment is malformed")
    return ["--algorithm-ram-evidence", path,
            "--algorithm-ram-nonce", nonce]


def _emit_private_untracked_checkout_inventory(probe) -> None:
    """Retain exact Git-untracked names for the owner, never for GitHub.

    Only source-defined counts and a fixed relative private log location are
    printed. The inventory grants no cleanup or physical admission authority.
    """
    try:
        # NUL delimiters are essential: Git filenames can contain newlines.
        raw_names = probe._git_result(
            "ls-files", "--others", "--exclude-standard", "-z").stdout
        if (not isinstance(raw_names, str) or
                len(raw_names) > 65536 or not raw_names.endswith("\0")):
            raise ValueError("untracked inventory is missing or oversized")
        untracked_names = raw_names[:-1].split("\0")
        if (not 1 <= len(untracked_names) <= 1024 or
                any(not name for name in untracked_names)):
            raise ValueError("untracked inventory is malformed")
        private_directory = ROOT / "build/tests"
        if private_directory.is_symlink() or not private_directory.is_dir():
            raise ValueError("private build directory is unavailable")
        # tempfile creates a new 0600 file. build/ is Git-ignored, so this
        # diagnostic does not itself alter the source admission verdict.
        with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=private_directory,
                prefix="source-untracked-", suffix=".private.json",
                delete=False) as diagnostic_file:
            json.dump({
                "schema": "swapz-private-untracked-inventory-v1",
                "total_count": len(untracked_names),
                "paths": untracked_names[:64],
                "truncated": len(untracked_names) > 64,
            }, diagnostic_file, ensure_ascii=True, sort_keys=True)
            diagnostic_file.write("\n")
            filename = Path(diagnostic_file.name).name
        print("  Untracked checkout inventory: "
              f"build/tests/{filename} (owner-only mode 0600; "
              f"total={len(untracked_names)})")
    except (OSError, RuntimeError, TypeError, ValueError, UnicodeError):
        # Missing diagnostics never turn a refused physical gate into PASS.
        print("  Untracked checkout inventory unavailable; inspect read-only "
              "with git ls-files --others --exclude-standard")


def _canonical_source_preflight(algorithm_ram_evidence: list[str]) -> str | None:
    """Authenticate this RAM-qualified source before asking for swap consent.

    The privileged probe repeats this exact check before any device mutation.
    This early, unprivileged refusal avoids a misleading consent prompt when
    canonical main advanced during the lengthy five-stage RAM qualification.
    """
    if not algorithm_ram_evidence:
        # The direct standalone path has no make-test evidence to reuse;
        # the root-owned probe still owns mandatory source admission.
        return None
    try:
        specification = importlib.util.spec_from_file_location(
            "physical_swap_source_preconsent",
            ROOT / "tests/tools/physical-swap-probe.py")
        if specification is None or specification.loader is None:
            return "canonical_source_verification_unavailable"
        probe = importlib.util.module_from_spec(specification)
        specification.loader.exec_module(probe)
        if probe._git("symbolic-ref", "--quiet", "--short", "HEAD") != "main":
            return "local_checkout_not_main"
        if probe._git("status", "--porcelain"):
            # Reuse the authoritative helper's finite, identity-free audit.
            # A generated report or untracked file is not code, but the
            # physical mutation gate still requires the whole tree clean.
            kinds = probe._development_dirty_worktree_kinds()
            if "untracked" in kinds.split(","):
                _emit_private_untracked_checkout_inventory(probe)
            return "local_checkout_changed_kind_" + kinds.replace(",", "_")
        head = probe._git("rev-parse", "HEAD")
        if head != probe._git("rev-parse", "origin/main"):
            return "local_tracking_main_mismatch"
        source = probe._development_code_source_sha(head)
        probe._read_algorithm_ram_development_evidence(
            Path(algorithm_ram_evidence[1]), os.getuid(), head,
            source, algorithm_ram_evidence[3])
        probe._require_development_canonical_main(head, source)
    except (OSError, RuntimeError, TypeError, ValueError, AttributeError) as error:
        # Child Git failures may contain remote URLs or authentication output.
        # Only publish an exact, source-defined classification, never str(error).
        if str(error) == "canonical main contains changed source after qualification":
            return "canonical_source_advanced"
        if str(error) == "canonical main advanced during source verification":
            return "canonical_source_raced"
        return "canonical_source_verification_unavailable"
    return None


def main() -> int:
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        print("PHYSICAL_ALGORITHM_REAL_SWAP=NOT_RUN reason=noninteractive")
        return 2
    try:
        selected = _require_read_only_preflight()
    except PendingRecoveryError as error:
        print("PHYSICAL_ALGORITHM_REAL_SWAP=RECOVERY_REQUIRED " + str(error))
        return 3
    except (OSError, subprocess.SubprocessError, ValueError) as error:
        print("PHYSICAL_ALGORITHM_REAL_SWAP=BLOCKED " + str(error))
        return 2
    if selected is None:
        print("PHYSICAL_ALGORITHM_REAL_SWAP=NOT_RUN reason=selection_declined")
        return 2
    print("Physical algorithm trial (disposable swap data):")
    print(f"  Partition: {selected['path']}  Parent: {selected['parent']}")
    print(f"  PARTUUID: {selected['partuuid']}  Bytes: {selected['size_bytes']}")
    if selected.get("virtual_device_only"):
        print("  VIRTUAL_DEVICE_ONLY: verified VM with an exact guest swap "
              "partition; never physical qualification")
    active_swap = selected.get("active_swap")
    if active_swap is not None:
        print(f"  Swap status: ACTIVE; used={active_swap['used_kib']} KiB, "
              f"priority={active_swap['priority']}")
    else:
        print("  Swap status: inactive")
    blockers = []
    if selected.get("other_active_partition_count", 0):
        blockers.append("unrelated_active_partition_not_supported")
    if blockers:
        # A Yes/No answer must never bypass a missing privileged safety gate.
        print("PHYSICAL_ALGORITHM_REAL_SWAP=BLOCKED reason=" +
              ",".join(blockers))
        return 2
    if selected.get("parent_has_other_partitions"):
        if selected.get("virtual_device_only"):
            print("  VM shared-disk candidate: the privileged helper must prove "
                  "the selected partition is not the root partition")
        else:
            print("  Shared-root candidate: privileged admission requires the "
                  "protected host-scope record; trial state remains in /run")
    try:
        algorithm_ram_evidence = _algorithm_ram_evidence_arguments()
    except ValueError as error:
        print("PHYSICAL_ALGORITHM_REAL_SWAP=BLOCKED " + str(error))
        return 2
    source_refusal = _canonical_source_preflight(algorithm_ram_evidence)
    if source_refusal is not None:
        # The official runner captures stderr privately while leaving stdout
        # attached to the operator TTY. Send only this source-defined refusal
        # over that channel for inclusion in the published JSON report.
        print("PHYSICAL_ALGORITHM_SOURCE_ADMISSION=" + source_refusal,
              file=sys.stderr, flush=True)
        print("PHYSICAL_ALGORITHM_REAL_SWAP=BLOCKED "
              f"reason={source_refusal} phase=before_consent")
        print("  Source admission: RAM-qualified source no longer has "
              "verified canonical-main binding; new trial NOT RUN.")
        if source_refusal == "canonical_source_advanced":
            print("  Next: synchronize main and rerun make test to qualify "
                  "the newer source before requesting physical consent.")
        elif source_refusal.startswith("local_checkout_changed_kind_"):
            print("  Next: inspect the reported checkout change class "
                  "read-only; preserve owner edits and the generated report. "
                  "Reconcile it on main before a new exact-source test.")
        elif source_refusal == "local_tracking_main_mismatch":
            print("  Next: reconcile local main and origin/main without "
                  "rewriting evidence, then rerun exact-source make test.")
        else:
            print("  Next: restore verifiable local/canonical Git source "
                  "identity, then rerun exact-source make test.")
        return 2
    print("  After confirmation, the privileged helper records root-only "
          "same-boot ownership in /run, checks memory headroom, and calls "
          "ordinary swapoff on active swap before using its data area.")
    print("  The original Linux swap header remains unchanged; "
          "only the temporary mapper may be formatted")
    # A no-newline input() prompt can disappear from line-oriented SSH logs.
    # Publish the exact Yes/No question before waiting for operator input.
    print(f"  Run bounded swapz Linux swap trial on {selected['path']} "
          f"(PARTUUID {selected['partuuid']})? [y/N]", flush=True)
    print("  Enter y/yes to authorize; n/no or Enter declines:", flush=True)
    try:
        confirmed = input()
    except EOFError:
        confirmed = ""
    if confirmed.lower() not in {"y", "yes"}:
        print("PHYSICAL_ALGORITHM_REAL_SWAP=NOT_RUN reason=declined")
        return 2
    sudo = shutil.which("sudo")
    if sudo is None:
        print("PHYSICAL_ALGORITHM_REAL_SWAP=BLOCKED reason=no_sudo")
        return 2
    command = [
        # Consent is already explicit; permit sudo to authenticate on the
        # controlling TTY rather than depending on a cached credential.
        sudo, "--", sys.executable, "-I", "-B",
        str(ROOT / "tests/tools/physical-swap-probe.py"),
        "run", "--device", selected["selector"],
        "--confirm-device", selected["selector"],
        "--development-only", "--algorithm-real-swap",
        *(["--virtual-device-only"] if selected.get("virtual_device_only") else []),
        *algorithm_ram_evidence,
    ]
    # The root helper owns mapper/swap cleanup and its bounded child timeouts.
    # Do not SIGKILL it merely because this parent reached a wall clock.
    try:
        result = subprocess.run(command, cwd=ROOT, check=False)
    except OSError:
        print("PHYSICAL_ALGORITHM_REAL_SWAP=BLOCKED reason=helper_unavailable")
        return 2
    return result.returncode if result.returncode in (0, 1, 2, 3) else 2


if __name__ == "__main__":
    raise SystemExit(main())
