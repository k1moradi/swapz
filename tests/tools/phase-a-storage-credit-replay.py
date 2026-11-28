#!/usr/bin/env python3
"""Offline single-service storage ledger. No reclaim, device, clock or native hook.

One record per fixed-class extent (RAW 4096 separate, zero no extent). This
intentionally pessimistic model does not pack multiple records or relocate GC
victims. External events only: reserve -> claim -> dispatch -> complete, or
cancel before claim. Read pins last from enqueue to completion; invalidate
then GC returns space only on success. Quarantine holds the entire reservation.
Queue: write reservations consume one of Q-2 slots; one each for read/GC.
A single active service and round-robin dispatch bound control starvation in
service opportunities, not time. Owner retries deferred work explicitly.
"""
import hashlib
import json
import os
import stat
import sys
from collections import deque
from dataclasses import dataclass

PAGE = 4096
CAP = 3568
CLASSES = (4096, 8192, 16384)
MAX_PAGES = 224
MAX_EVENTS = 32768
SOURCE = "ca98c75e68a92ba456cd450aaaaab60b02995783"
PROJECTION = "f6b361912819dc219d98a54566a03bc5d999ff6d"
MODES = ("ordinary", "eligible_always", "conservative")
KINDS = ("write", "read", "gc")
GATES = dict(auth=0, phase_a="BLOCKED", native_qualification="BLOCKED",
             observation="UNKNOWN", compressed_handoff=False, forced_raw=False,
             import_enabled=False, physical="NO_GO", actual_route="ORDINARY",
             actual_preserve_permission=False)


class Invalid(ValueError):
    """Fixed reason codes only."""


def require(condition, reason):
    if not condition:
        raise Invalid(reason)


def integer(value, low, high):
    return type(value) is int and low <= value <= high


@dataclass(frozen=True, slots=True)
class Metadata:
    codec: int
    length: int
    version: int = 1
    dictionary: int = 0
    stored: bool = True
    compatible: bool = True
    hypothetical_authority: bool = True


def select(meta, pressure, likelihood, depth, free, mode):
    """Frozen R115 thresholds, without the comparator's oracle eligibility.

    Missing/invalid prerequisites never select preservation. Actual capacity
    admission is separate and applies to ALL modes, including ordinary.
    """
    if (type(meta) is not Metadata or mode not in MODES or mode == "ordinary" or
            not integer(meta.codec, 1, 2) or not integer(meta.length, 1, CAP) or
            not integer(meta.version, 1, 1) or not integer(meta.dictionary, 0, 0) or
            not all(v is True for v in (meta.stored, meta.compatible, meta.hypothetical_authority)) or
            not integer(pressure, 0, 1000) or not integer(likelihood, 0, 1000) or
            not integer(depth, 0, 64) or not integer(free, PAGE, 64 * PAGE) or depth >= 48):
        return False
    return mode == "eligible_always" or (meta.codec == 1 and 128 <= meta.length <= 768 and
                                         pressure >= 750 and likelihood <= 100 and depth <= 16)


@dataclass(slots=True)
class Record:
    meta: Metadata
    phase: str = "deferred"
    allocated: int = 0
    length: int = 0
    pin: bool = False
    attempt: bool = False
    ever_deferred: bool = False
    token: int = 0


@dataclass(slots=True)
class Job:
    logical: int
    kind: str
    size: int = 0
    selected: bool = False
    baseline: int = 0
    queued_at: int = 0


class Ledger:
    """Single owner, serial external events; deliberately not thread safe."""
    def __init__(self, capacity, depth, extent, mode):
        require(type(extent) is int and extent in CLASSES and
                integer(capacity, extent, 64 * PAGE) and capacity % PAGE == 0 and
                integer(depth, 3, 64) and mode in MODES, "configuration")
        self.capacity, self.depth, self.extent, self.mode = capacity, depth, extent, mode
        self.records, self.jobs = {}, {}
        self.queues = {kind: deque() for kind in KINDS}
        self.active = None
        self.turn = self.events = self.serial = self.occupied = 0
        self.stats = dict(reserved_bytes=0, returned_bytes=0, peak_space=0, peak_queue=0,
                          peak_reserved=0, peak_live=0, deferrals=0, unique_deferred=0, queue_deferrals=0,
                          space_deferrals=0, retries=0, cancellations=0, attempts=0,
                          preclaim_fallbacks=0, selected=0, ordinary=0, write_acks=0,
                          read_acks=0, gc_acks=0, failed_writes=0, failed_reads=0,
                          failed_gc=0, payload_bytes=0, baseline_bytes=0, write_bytes=0,
                          read_bytes=0, gc_released_bytes=0, quarantined_bytes=0,
                          dispatches=0, max_read_wait_dispatches=0, max_gc_wait_dispatches=0,
                          missed_reads=0, missed_gc=0, service_opportunities=0)

    def event(self):
        require(self.events < MAX_EVENTS, "event_limit")
        self.events += 1

    def count(self, kind):
        return sum(job.kind == kind for job in self.jobs.values())

    def audit(self):
        reserved = sum(r.allocated for r in self.records.values() if r.phase in ("reserved", "claimed"))
        live = sum(r.allocated for r in self.records.values() if r.phase in ("live", "retired", "reclaiming"))
        quarantine = sum(r.allocated for r in self.records.values() if r.phase == "quarantine")
        require(0 <= self.occupied == reserved + live + quarantine <= self.capacity and
                self.occupied == self.stats["reserved_bytes"] - self.stats["returned_bytes"], "space_conservation")
        require(len(self.jobs) <= self.depth and self.count("write") <= self.depth - 2 and
                self.count("read") <= 1 and self.count("gc") <= 1, "queue_conservation")
        scheduled = [token for queue in self.queues.values() for token in queue]
        if self.active is not None:
            scheduled.append(self.active)
        pending = [r.token for r in self.records.values() if r.phase == "reserved"]
        require(len(scheduled + pending) == len(set(scheduled + pending)) and
                set(scheduled + pending) == self.jobs.keys(), "job_conservation")
        for record in self.records.values():
            require(integer(record.allocated, 0, self.extent) and
                    (record.allocated == self.extent if record.phase in ("reserved", "claimed", "quarantine") else
                     record.allocated == 0 if record.phase in ("deferred", "released") else
                     record.allocated in (0, PAGE, self.extent)), "record_allocation")
            require((record.token in self.jobs) if record.token else
                    (record.phase not in ("reserved", "claimed", "reclaiming") and not record.pin), "record_binding")
        for token, job in self.jobs.items():
            record = self.records[job.logical]
            require(record.token == token and
                    (record.phase in ("reserved", "claimed") if job.kind == "write" else
                     record.phase == "live" and record.pin if job.kind == "read" else
                     record.phase == "reclaiming"), "job_binding")
        require(sum(r.pin for r in self.records.values()) == self.count("read"), "pin_conservation")
        self.stats["peak_space"] = max(self.stats["peak_space"], self.occupied)
        self.stats["peak_queue"] = max(self.stats["peak_queue"], len(self.jobs))
        self.stats["peak_reserved"] = max(self.stats["peak_reserved"], reserved)
        self.stats["peak_live"] = max(self.stats["peak_live"], live)

    def new_job(self, logical, kind):
        self.serial += 1
        token = self.serial
        self.jobs[token] = Job(logical, kind, queued_at=self.stats["dispatches"])
        self.records[logical].token = token
        return token

    def reserve(self, logical, meta, pressure, likelihood, retry=False):
        require(integer(logical, 0, MAX_PAGES-1) and type(meta) is Metadata and
                integer(meta.codec, 1, 255) and integer(meta.length, 1, 8192) and
                integer(meta.version, 0, 255) and integer(meta.dictionary, 0, 65535) and
                all(type(v) is bool for v in (meta.stored, meta.compatible, meta.hypothetical_authority)) and
                integer(pressure, 0, 1000) and integer(likelihood, 0, 1000) and type(retry) is bool, "arrival_shape")
        record = self.records.get(logical)
        require((record is None and not retry) or
                (retry and record is not None and record.phase == "deferred" and record.meta == meta), "arrival_order")
        self.event()
        if record is None:
            record = self.records[logical] = Record(meta)
        self.stats["retries"] += int(retry)
        free = self.capacity - self.occupied
        # Worst case: one whole class, even if eventual ordinary is zero/RAW.
        # No outcome length or label can influence admission or route selection.
        if self.count("write") >= self.depth-2 or free < self.extent:
            self.stats["deferrals"] += 1
            self.stats["unique_deferred"] += int(not record.ever_deferred)
            record.ever_deferred = True
            self.stats["queue_deferrals"] += int(self.count("write") >= self.depth-2)
            self.stats["space_deferrals"] += int(free < self.extent)
            self.audit()
            return None
        record.attempt = select(meta, pressure, likelihood, len(self.jobs), free, self.mode)
        record.phase, record.allocated = "reserved", self.extent
        self.occupied += self.extent
        self.stats["reserved_bytes"] += self.extent
        token = self.new_job(logical, "write")
        self.audit()
        return token

    def reserved(self, token):
        require(integer(token, 1, self.serial) and token in self.jobs, "stale_token")
        job = self.jobs[token]
        record = self.records[job.logical]
        require(job.kind == "write" and record.phase == "reserved", "reservation_order")
        return job, record

    def release(self, record, size):
        require(integer(size, 0, record.allocated), "release_mismatch")
        record.allocated -= size
        self.occupied -= size
        self.stats["returned_bytes"] += size

    def cancel(self, token):
        _, record = self.reserved(token)
        self.event()
        self.release(record, record.allocated)
        record.phase, record.token = "deferred", 0
        del self.jobs[token]
        self.stats["cancellations"] += 1
        self.audit()

    def claim(self, token, ordinary, label):
        job, record = self.reserved(token)
        require(integer(ordinary, 0, PAGE) and integer(label, 0, 1) and
                (not label or (record.meta.codec in (1, 2) and record.meta.length <= CAP and ordinary > 0)), "outcome_bounds")
        self.event()
        # Diagnostic eligibility is an outcome oracle only, before claim.
        job.selected = record.attempt and label == 1
        self.stats["attempts"] += int(record.attempt)
        self.stats["preclaim_fallbacks"] += int(record.attempt and not job.selected)
        record.length = record.meta.length if job.selected else ordinary
        job.baseline = ordinary
        job.size = 0 if record.length == 0 else PAGE if record.length == PAGE else self.extent
        record.phase = "claimed"
        job.queued_at = self.stats["dispatches"]
        self.queues["write"].append(token)
        self.audit()

    def control(self, logical, kind):
        require(integer(logical, 0, MAX_PAGES-1) and kind in ("read", "gc") and
                logical in self.records, "control_shape")
        record = self.records[logical]
        require(not record.pin and record.phase == ("live" if kind == "read" else "retired") and
                self.count(kind) == 0 and len(self.jobs) < self.depth, "control_order_or_credit")
        self.event()
        token = self.new_job(logical, kind)
        if kind == "read":
            record.pin = True
            self.jobs[token].size = record.allocated
        else:
            record.phase = "reclaiming"
        self.queues[kind].append(token)
        self.audit()
        return token

    def invalidate(self, logical):
        require(integer(logical, 0, MAX_PAGES-1) and logical in self.records and
                self.records[logical].phase == "live" and not self.records[logical].pin, "invalidate_order")
        self.event()
        self.records[logical].phase = "retired"
        self.audit()

    def dispatch(self):
        require(self.active is None, "active_service")
        self.event()
        for offset in range(len(KINDS)):
            index = (self.turn + offset) % len(KINDS)
            kind = KINDS[index]
            if not self.queues[kind]:
                continue
            self.active = self.queues[kind].popleft()
            self.turn = (index + 1) % len(KINDS)
            job = self.jobs[self.active]
            if kind != "write":
                wait = self.stats["dispatches"] - job.queued_at
                require(wait <= 2, "control_starvation")
                name = "max_" + kind + "_wait_dispatches"
                self.stats[name] = max(self.stats[name], wait)
            self.stats["dispatches"] += 1
            break
        self.audit()
        return self.active

    def complete(self, token, status, size):
        require(integer(token, 1, self.serial) and token == self.active and token in self.jobs, "completion_order")
        job = self.jobs[token]
        require(integer(status, 0, 1) and integer(size, 0, self.extent) and
                size == (job.size if status == 0 else 0), "completion_size_or_status")
        self.event()
        record = self.records[job.logical]
        if job.kind == "write":
            if status:
                # No postclaim fallback; uncertain allocation remains quarantined.
                record.phase = "quarantine"
                self.stats["failed_writes"] += 1
                self.stats["quarantined_bytes"] += record.allocated
            else:
                self.release(record, record.allocated-job.size)
                record.phase = "live"
                self.stats["write_acks"] += 1
                self.stats["selected"] += int(job.selected)
                self.stats["ordinary"] += int(not job.selected)
                self.stats["payload_bytes"] += record.length
                self.stats["baseline_bytes"] += job.baseline
                self.stats["write_bytes"] += size
        elif job.kind == "read":
            record.pin = False
            self.stats["failed_reads" if status else "read_acks"] += 1
            self.stats["read_bytes"] += size
        elif status:
            record.phase = "retired"
            self.stats["failed_gc"] += 1
        else:
            self.stats["gc_released_bytes"] += record.allocated
            self.release(record, record.allocated)
            record.phase = "released"
            self.stats["gc_acks"] += 1
        record.token = 0
        del self.jobs[token]
        self.active = None
        self.audit()

    def cleanup(self):
        self.audit()
        require(not self.jobs and not self.occupied and
                all(r.phase == "released" for r in self.records.values()), "cleanup_debt")
        require(self.stats["write_acks"] == self.stats["gc_acks"] == len(self.records) ==
                self.stats["selected"] + self.stats["ordinary"], "ack_conservation")
        logical = self.stats["write_acks"]*PAGE
        return dict(self.stats, events=self.events, outstanding=0, occupied=0,
                    logical_write_bytes=logical,
                    modeled_write_per_logical_ppm=self.stats["write_bytes"]*10**6//logical if logical else None,
                    modeled_write_per_payload_ppm=self.stats["write_bytes"]*10**6//self.stats["payload_bytes"]
                    if self.stats["payload_bytes"] else None)


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate_key")
        result[key] = value
    return result


def load(raw):
    require(type(raw) is bytes and 2 <= len(raw) <= 16384, "input_bounds")
    digest = hashlib.sha1(f"blob {len(raw)}\0".encode("ascii") + raw).hexdigest()
    require(digest == PROJECTION, "input_identity")
    data = json.loads(raw, object_pairs_hook=unique_object)
    require(type(data) is dict and data.keys() == {"source_blob", "rows"} and data["source_blob"] == SOURCE, "input_shape")
    rows = data["rows"]
    require(type(rows) is list and len(rows) == 2, "codec_count")
    for group in rows:
        require(type(group) is list and len(group) == MAX_PAGES, "page_count")
        for logical, row in enumerate(group):
            require(type(row) is list and len(row) == 5, "row_shape")
            stratum, ident, original, ordinary, label = row
            require(integer(stratum, 0, 6) and stratum == (logical % 6 if logical < 192 else 6) and
                    integer(ident, logical, logical) and integer(original, 1, 8192) and
                    integer(ordinary, 0, PAGE) and integer(label, 0, 1) and
                    (not label or (original <= CAP and ordinary > 0)), "row_bounds")
    require(all(a[3] == b[3] for a, b in zip(*rows, strict=True)), "ordinary_mismatch")
    return rows


# External workload schedule: no page selection by the ledger. All modes and
# backing twins receive the same opportunities, even if a requested page is
# not live yet. Recovery passes are predeclared, not an unbounded retry loop.
WINDOWS = ((850, 50), (850, 800), (300, 50), (850, 50), (850, 800), (300, 50), (850, 50))
CONFIGS = ((8*PAGE, 6, PAGE), (8*8192, 6, 8192), (8*16384, 6, 16384))


def replay_one(rows, codec, mode, config):
    ledger = Ledger(*config, mode)

    def arrival(row, retry):
        _, logical, original, ordinary, label = row
        token = ledger.reserve(logical, Metadata(codec, original), *WINDOWS[logical//32], retry=retry)
        if token is not None:
            ledger.claim(token, ordinary, label)

    def pulse(count):
        for _ in range(count):
            ledger.stats["service_opportunities"] += 1
            if ledger.active is None:
                ledger.dispatch()
            else:
                ledger.complete(ledger.active, 0, ledger.jobs[ledger.active].size)

    def offer(logical, kind):
        record = ledger.records[logical]
        if record.phase != "live" or record.pin or ledger.count(kind):
            ledger.stats["missed_reads" if kind == "read" else "missed_gc"] += 1
            return
        if kind == "gc":
            ledger.invalidate(logical)
        ledger.control(logical, kind)

    for index, row in enumerate(rows):
        arrival(row, False)
        if index % 8 == 7:
            pulse(4)
            offer(index-7, "read")
            offer(index-6, "gc")
    pulse(2*ledger.depth)
    # A bounded owner-driven retry/drain schedule, not storage-driven reclaim.
    for _ in range(2):
        for row in rows:
            logical = row[1]
            if ledger.records[logical].phase == "deferred":
                arrival(row, True)
            pulse(2*ledger.depth)
            offer(logical, "read")
            pulse(2)
            offer(logical, "gc")
            pulse(2)
    return ledger.cleanup()


def replay(rows):
    results = {}
    for config in CONFIGS:
        by_codec = {}
        for codec, group in enumerate(rows, 1):
            by_mode = {}
            for mode in MODES:
                anonymous = replay_one(group, codec, mode, config)
                shmem = replay_one(group, codec, mode, config)
                require(anonymous == shmem, "matched_backing")
                by_mode[mode] = anonymous
            by_codec[str(codec)] = by_mode
        results[str(config[2])] = by_codec
    return dict(status="OFFLINE_MODEL_ONLY", verdict="NO_GO", results=results,
                configs=CONFIGS, windows=WINDOWS, matched_backing=True, **GATES)


def read_input(path):
    before = os.lstat(path)
    require(stat.S_ISREG(before.st_mode), "regular_file_required")
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as stream:
        info = os.fstat(stream.fileno())
        require(stat.S_ISREG(info.st_mode) and (info.st_dev, info.st_ino) == (before.st_dev, before.st_ino) and
                2 <= info.st_size <= 16384, "input_bounds")
        raw = stream.read(16385)
        after = os.fstat(stream.fileno())
        require(len(raw) == info.st_size and (after.st_size, after.st_mtime_ns, after.st_ctime_ns) ==
                (info.st_size, info.st_mtime_ns, info.st_ctime_ns), "input_changed")
        return raw


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    try:
        require(len(argv) == 1, "arguments")
        raw = read_input(argv[0])
        result = replay(load(raw))
        result.update(input_git_blob=PROJECTION, source_report_git_blob=SOURCE, input_sha256=hashlib.sha256(raw).hexdigest())
    except Invalid as error:
        result = dict(status="BLOCKED", reason=str(error), **GATES)
    except (OSError, ValueError, TypeError, KeyError, OverflowError, RecursionError):
        result = dict(status="BLOCKED", reason="invalid_input", **GATES)
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    return 0 if result["status"] == "OFFLINE_MODEL_ONLY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
