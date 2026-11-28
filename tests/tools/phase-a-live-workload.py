#!/usr/bin/env python3
"""Owner-local live ordinary workload binding; rootless preparation only.

The synchronous observer is trusted, cooperative code, not a sandbox. One
exclusive owner, no concurrent callers, reentry, external commands, mapping
access or native observation. Python private fields are not security barriers.
The callback receives only an expiring metadata handle; no fd, mmap, view or
callback result escapes through this API. Tokens are not native identities.
"""
from collections import namedtuple
from contextlib import contextmanager
import hashlib
import importlib.util
import os
from pathlib import Path
import re
import secrets
import stat
import tempfile

SPEC = importlib.util.spec_from_file_location(
    "workload_plan", Path(__file__).resolve().with_name("phase-a-workload-plan.py"))
producer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(producer)
pressure = producer.pressure
PAGE_BYTES = producer.PAGE_BYTES
MAPPING_NAME = "workload-mapping-plan.json"
MAX_MAPPING_BYTES = 8192
BACKINGS = ("anonymous", "file-backed-tmpfs")
Binding = namedtuple("Binding", "logical object_token offset backing")
require = producer.require
canonical = producer.canonical


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def token_valid(token):
    return (type(token) is str and re.fullmatch(r"[0-9a-f]{32}", token) is not None
            and token != "0" * 32)


def mapping_plan(commitment, tokens):
    """Build independent logical/object/offset metadata, before mapping."""
    require(len(tokens) == 2 and all(token_valid(token) for token in tokens) and
            tokens[0] != tokens[1], "object_tokens")
    count = len(commitment["plan"]["pages"]) // 2
    require(2 <= count <= 8 and len(commitment["plan"]["pages"]) == 2 * count,
            "mapping_bounds")
    plan = dict(schema="swapz-live-mapping-plan", version=1,
                scope=dict(commitment["scope"]),
                objects=[dict(backing=backing, object_token=token)
                         for backing, token in zip(BACKINGS, tokens)],
                pages=[dict(logical=cohort * count + index + 1,
                            object_token=tokens[cohort], offset=index * PAGE_BYTES,
                            backing=BACKINGS[cohort])
                       for cohort in range(2) for index in range(count)])
    return dict(mapping_plan=plan, mapping_sha256=digest(plan))


def validate_mapping_plan(envelope, commitment):
    """Structural validation against the trusted v2 commitment, not a witness."""
    require(type(envelope) is dict and envelope.keys() == {"mapping_plan", "mapping_sha256"},
            "mapping_envelope")
    plan = envelope["mapping_plan"]
    require(type(plan) is dict and type(plan.get("objects")) is list and
            len(plan["objects"]) == 2 and all(type(obj) is dict and
            obj.keys() == {"backing", "object_token"} for obj in plan["objects"]),
            "mapping_objects")
    expected = mapping_plan(commitment, [obj["object_token"] for obj in plan["objects"]])
    # Canonical equality rejects bool/int aliases, extras, swapped offsets,
    # duplicate rows, wrong scope, mismatched digest and noncanonical ordering.
    require(canonical(envelope) == canonical(expected), "mapping_plan_mismatch")
    return tuple(Binding(**row) for row in plan["pages"])


@contextmanager
def retained_artifacts(directory, artifacts):
    """Exclusive private files; retain on success, remove only owned inodes on failure.

    Retention here is same-process file readback, not a media durability claim.
    No explicit flush or extra lower-device operation is requested.
    """
    records = []
    first_error = None
    try:
        for name, encoded, limit in artifacts:
            require(len(encoded) <= limit, "artifact_size")
            require(producer.private_dir(os.fstat(directory)), "private_directory_required")
            fd = os.open(name, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         0o600, dir_fd=directory)
            record = [name, fd, None, encoded]
            records.append(record)
            record[2] = producer.identity(os.fstat(fd))
            os.fchmod(fd, 0o600)
            require(producer.private_regular(os.fstat(fd)), "private_artifact_required")
            offset = 0
            while offset < len(encoded):
                written = os.write(fd, memoryview(encoded)[offset:])
                require(written > 0, "artifact_write")
                offset += written

        def verify():
            require(producer.private_dir(os.fstat(directory)), "private_directory_required")
            for name, fd, identity, encoded in records:
                info = os.fstat(fd)
                named = os.stat(name, dir_fd=directory, follow_symlinks=False)
                require(producer.private_regular(info) and producer.private_regular(named) and
                        producer.identity(info) == identity == producer.identity(named) and
                        os.pread(fd, len(encoded) + 1, 0) == encoded, "artifact_changed")

        verify()
        yield verify
        verify()
    except BaseException as error:
        first_error = error
        raise
    finally:
        # Close each descriptor exactly once, even if another close fails.
        for record in reversed(records):
            name, fd, identity, _ = record
            try:
                os.close(fd)
            except OSError as error:
                if first_error is None:
                    first_error = producer.PlanError("artifact_close_failed")
                else:
                    first_error.add_note("artifact_close_failed")
        if first_error is not None:
            for name, _, identity, _ in reversed(records):
                try:
                    named = os.stat(name, dir_fd=directory, follow_symlinks=False)
                    require(identity is not None and producer.identity(named) == identity,
                            "artifact_replaced")
                    os.unlink(name, dir_fd=directory)
                except (OSError, producer.PlanError):
                    first_error.add_note("artifact_cleanup_failed")
            # On a successful body with a failed close, fail rather than return.
            raise first_error


@contextmanager
def owned_backing():
    """Preserve callback/verification failure if closing the owner fd fails."""
    backing = tempfile.TemporaryFile(dir="/dev/shm")
    first_error = None
    try:
        yield backing
    except BaseException as error:
        first_error = error
        raise
    finally:
        try:
            backing.close()
        except OSError:
            if first_error is None:
                raise producer.PlanError("backing_close_failed") from None
            first_error.add_note("backing_close_failed")
        else:
            if not backing.closed:
                if first_error is None:
                    raise producer.PlanError("backing_close_failed")
                first_error.add_note("backing_close_failed")


class LiveHandle:
    """Private metadata only; valid exclusively within the single callback."""
    __slots__ = ("__bindings", "__nonce", "__digest", "__check")

    def __init__(self, bindings, nonce, mapping_digest, check):
        self.__bindings = bindings
        self.__nonce = nonce
        self.__digest = mapping_digest
        self.__check = check

    def _expire(self):
        self.__check = None

    def _require_active(self):
        require(self.__check is not None, "observation_closed")
        self.__check()

    @property
    def bindings(self):
        self._require_active()
        return self.__bindings

    @property
    def run_nonce(self):
        self._require_active()
        return self.__nonce

    @property
    def mapping_sha256(self):
        self._require_active()
        return self.__digest

    def validate(self, binding, run_nonce, mapping_sha256):
        self._require_active()
        require(type(run_nonce) is str and run_nonce == self.__nonce and
                type(mapping_sha256) is str and mapping_sha256 == self.__digest,
                "binding_scope")
        require(type(binding) is Binding and type(binding.logical) is int and
                1 <= binding.logical <= len(self.__bindings) and
                type(binding.offset) is int and type(binding.object_token) is str and
                type(binding.backing) is str and binding == self.__bindings[binding.logical - 1],
                "binding_mismatch")
        return True


def run_live_workload(private_directory, request, observe):
    """Run one bounded synchronous mock observation; return redacted counts only.

    The owner must not mutate/rename the private directory or inspect/mutate
    helper state during the callback. No concurrency or native/pressure actions.
    A callback exception remains the first error; verification and cleanup are
    attempted afterwards. Any failure removes only artifacts created by us.
    """
    require(os.geteuid() != 0, "unprivileged_required")
    require(callable(observe), "observer_required")
    producer.validate_request(request)
    request = dict(request, scope=dict(request["scope"]))
    commitment = producer.build_commitment(request)
    envelope = mapping_plan(commitment, (secrets.token_hex(16), secrets.token_hex(16)))
    bindings = validate_mapping_plan(envelope, commitment)
    count, hot = request["page_count"], request["hot_page_count"]
    length = count * PAGE_BYTES
    artifacts = ((producer.ARTIFACT_NAME, canonical(commitment) + b"\n", producer.MAX_ARTIFACT_BYTES),
                 (MAPPING_NAME, canonical(envelope) + b"\n", MAX_MAPPING_BYTES))
    with producer.open_private_directory(private_directory) as directory:
        with retained_artifacts(directory, artifacts) as verify_artifacts:
            with owned_backing() as backing:
                fd = backing.fileno()
                pressure._require_private_tmpfs(fd)
                backing_identity = producer.identity(os.fstat(fd))
                with pressure.prepare_matched_cold_workload(page_count=count, hot_page_count=hot,
                                                           seed=request["seed"], tmpfs_fd=fd) as work:
                    # Frozen helper's private map references are intentionally
                    # pinned for owner-local object identity, not raw addresses.
                    anonymous, shmem = work._anonymous, work._shmem

                    def check_live():
                        info = os.fstat(fd)
                        require(work._usable and anonymous is not shmem and
                                work._anonymous is anonymous and work._shmem is shmem and
                                not anonymous.closed and not shmem.closed and
                                len(anonymous) == len(shmem) == length and
                                work.backing_kind == BACKINGS[1] and
                                work.logical_bytes_per_mapping == length and
                                work.hot_pages == range(hot) and work.cold_pages == range(hot, count),
                                "mapping_not_live")
                        require(producer.identity(info) == backing_identity and
                                stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid() and
                                stat.S_IMODE(info.st_mode) == 0o600 and info.st_nlink == 0 and
                                info.st_size == length, "backing_changed")

                    def verify_pages(indices):
                        for index in indices:
                            offset = index * PAGE_BYTES
                            for cohort, mapping in enumerate((anonymous, shmem)):
                                expected = bytes.fromhex(commitment["plan"]["pages"][cohort * count + index]["expected_page"])
                                require(mapping[offset:offset + PAGE_BYTES] == expected,
                                        "committed_page_mismatch")

                    check_live()
                    for _ in range(request["touch_count"]):
                        work.touch_hot()
                    verify_pages(range(hot))  # No cold read before observation.
                    verify_artifacts()
                    handle = LiveHandle(bindings, commitment["scope"]["run_nonce"],
                                        envelope["mapping_sha256"], check_live)
                    first_error = None
                    try:
                        observe(handle)  # Ignore the result; no mapping or fd is exported.
                    except BaseException as error:
                        first_error = error
                        raise
                    finally:
                        handle._expire()  # End observation BEFORE reading cold pages.
                        try:
                            check_live()
                            work.verify()
                            verify_pages(range(count))
                        except BaseException:
                            if first_error is None:
                                raise
                            first_error.add_note("final_verification_failed")
                require(anonymous.closed and shmem.closed and os.fstat(fd).st_size == 0 and
                        producer.identity(os.fstat(fd)) == backing_identity, "mapping_cleanup")
            require(backing.closed, "backing_close")
    return dict(status="ROOTLESS_LIVE_PREPARATION_ONLY", pages=2 * count, cohorts=2,
                hot_touches=request["touch_count"], callbacks=1, byte_exact=True,
                precommit_retained=True, mapping_cleanup=True, **producer.GATES)
