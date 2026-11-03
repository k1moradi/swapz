#!/usr/bin/env python3
"""Fail-closed primary-swap lifecycle manager for systemd.

The service prepares and verifies the mapper; a native systemd .swap unit
performs swapon and swapoff. The manager never formats backing storage during
boot and refuses to remove a mapper that systemd has not deactivated.
"""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
import subprocess
import sys
import time

DEVICE = Path('/dev/sda4')
UUID_PATH = Path('/dev/disk/by-uuid/728b4c06-44b0-46ee-91ec-560ab1bad358')
PARTUUID_PATH = Path('/dev/disk/by-partuuid/7fb9401d-04')
DEVICE_ID = (8, 4)
DEVICE_BYTES = 17179869184
ORIGINAL_HEADER_SHA256 = (
    'ace016a7a3ecd22b0aca05946a305aef2113bc50439452756ae68909010f0afe')
PAGE_BYTES = 4096
BLOCK_BYTES = 4096
SEGMENT_BLOCKS = 256
MIN_RESERVE_BLOCKS = 2 * SEGMENT_BLOCKS
STATE_DIR = Path('/var/lib/swapz/primary')
STATE_PATH = STATE_DIR / 'state.json'
BACKUP_PATH = STATE_DIR / 'block0.bin'
LOCK_PATH = Path('/run/lock/swapz-primary.lock')
MAPPER_NAME = 'swapz-primary'
MAPPER_UUID = 'SWAPZ-PRIMARY'
SWAP_PRIORITY = -1
SWAPZ_MAGIC = b'SWAPZ001'
BLKGETSIZE64 = 0x80081272
# Keep production activation and teardown disabled until the durable
# provisioning/recovery state machine and its live-host gates are qualified.
PRIMARY_EXECUTION_ENABLED = False


def maximum_logical_pages(physical_blocks):
    if type(physical_blocks) is not int or physical_blocks <= 0:
        raise ValueError('physical block count must be positive')
    low, high = 0, physical_blocks
    while low < high:
        candidate = (low + high + 1) // 2
        reserve = max((candidate + 7) // 8, MIN_RESERVE_BLOCKS)
        aligned = ((physical_blocks - reserve) // SEGMENT_BLOCKS) * SEGMENT_BLOCKS
        if reserve < physical_blocks and candidate <= aligned:
            low = candidate
        else:
            high = candidate - 1
    return low


PHYSICAL_BLOCKS = ((DEVICE_BYTES // BLOCK_BYTES - 1) // SEGMENT_BLOCKS) * SEGMENT_BLOCKS
LOGICAL_PAGES = maximum_logical_pages(PHYSICAL_BLOCKS)
LOGICAL_BYTES = LOGICAL_PAGES * PAGE_BYTES
LOGICAL_SECTORS = LOGICAL_BYTES // 512


class ManagerError(RuntimeError):
    pass


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ManagerError(f'duplicate JSON key: {key}')
        result[key] = value
    return result


def load_unique_json(path):
    flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, 'O_NOFOLLOW', 0)
    fd = os.open(path, flags)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or \
                info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != 0o600:
            raise ManagerError(f'unsafe state file: {path}')
        chunks = []
        while True:
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            chunks.append(chunk)
            if sum(map(len, chunks)) > 1024 * 1024:
                raise ManagerError('state file exceeds 1 MiB')
    finally:
        os.close(fd)
    try:
        return json.loads(b''.join(chunks), object_pairs_hook=_unique_pairs)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ManagerError('state JSON is malformed') from exc


def durable_json(path, value):
    path = Path(path)
    encoded = (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()
    temporary = path.with_name(f'.{path.name}.{os.getpid()}.{secrets.token_hex(8)}')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                 os.O_CLOEXEC | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    try:
        view = memoryview(encoded)
        while view:
            count = os.write(fd, view)
            if count <= 0:
                raise ManagerError('short write to durable state')
            view = view[count:]
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(temporary, path)
    dirfd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        os.fsync(dirfd)
    finally:
        os.close(dirfd)


def block_identity(path):
    info = os.stat(path)
    if not stat.S_ISBLK(info.st_mode):
        raise ManagerError(f'{path} is not a block device')
    return (os.major(info.st_rdev), os.minor(info.st_rdev))


def read_block_zero(path=DEVICE):
    fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC)
    try:
        info = os.fstat(fd)
        if not stat.S_ISBLK(info.st_mode) or \
                (os.major(info.st_rdev), os.minor(info.st_rdev)) != DEVICE_ID:
            raise ManagerError('opened backing identity is not 8:4')
        size = bytearray(8)
        fcntl.ioctl(fd, BLKGETSIZE64, size, True)
        if int.from_bytes(size, sys.byteorder) != DEVICE_BYTES:
            raise ManagerError('backing device size changed')
        block = os.pread(fd, PAGE_BYTES, 0)
        if len(block) != PAGE_BYTES:
            raise ManagerError('short block-zero read')
        return block
    finally:
        os.close(fd)


def valid_swz_header(block):
    return len(block) == PAGE_BYTES and \
        block[0:8] == SWAPZ_MAGIC and \
        int.from_bytes(block[8:12], 'little') == 1 and \
        int.from_bytes(block[12:16], 'little') == PAGE_BYTES and \
        int.from_bytes(block[16:24], 'little') == DEVICE_BYTES and \
        any(block[24:40]) and not any(block[40:])


def parse_dm_info(text):
    if text.strip() == 'No devices found':
        return []
    if not text.strip():
        raise ManagerError('Device Mapper inventory is blank')
    rows = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        fields = stripped.split(':') if ':' in stripped else stripped.split()
        fields = [field.strip() for field in fields]
        if len(fields) != 5 or not fields[0] or not fields[1] or \
                any(not re.fullmatch(r'[0-9]+', value) for value in fields[2:]):
            raise ManagerError('malformed Device Mapper info record')
        rows.append((fields[0], fields[1], *map(int, fields[2:])))
    return rows


def expected_table():
    return ['0', str(LOGICAL_SECTORS), 'swapz', '/dev/sda4',
            '0', '64', '0', '2', '0', '1', '0', '0']


def require_owned_mapper_for_stop(state, row):
    """Refuse cleanup unless this boot's service can prove mapper ownership."""
    if state.get('stage') == 'REQUIRES_REVIEW':
        raise ManagerError('recovery is marked REQUIRES_REVIEW')
    if state.get('module_loaded_by_service') is not True:
        raise ManagerError('service does not own the loaded swapz module')
    if not isinstance(row, (tuple, list)) or len(row) != 5:
        raise ManagerError('mapper inventory row is malformed')
    expected = (state.get('dm_major'), state.get('dm_minor'))
    actual = (row[2], row[3])
    if any(type(value) is not int or value < 0 for value in expected) or \
            actual != expected:
        raise ManagerError('mapper major:minor differs from durable ownership state')


def require_stopped_state_is_unambiguous(state, module_loaded, mapper_swaps):
    """Permit an absent mapper to become STOPPED only after a clean proof."""
    if state.get('stage') == 'REQUIRES_REVIEW':
        raise ManagerError('recovery is marked REQUIRES_REVIEW')
    if module_loaded or mapper_swaps:
        raise ManagerError('mapper is absent while module or active mapper swap remains')


def validate_table(text):
    fields = text.split()
    expected = expected_table()
    if len(fields) != len(expected) or fields[:3] != expected[:3] or \
            fields[4:] != expected[4:] or fields[3] not in {'/dev/sda4', '8:4'}:
        raise ManagerError('Device Mapper table differs from maximum-capacity policy')
    return True


def parse_swaps(text):
    lines = text.splitlines()
    if not lines or lines[0].split()[:5] != ['Filename', 'Type', 'Size', 'Used', 'Priority']:
        raise ManagerError('/proc/swaps header is malformed')
    rows = []
    for line in lines[1:]:
        fields = line.split()
        if len(fields) != 5:
            raise ManagerError('malformed /proc/swaps row')
        try:
            size, used, priority = map(int, fields[2:])
        except ValueError as exc:
            raise ManagerError('malformed /proc/swaps numeric field') from exc
        rows.append({'path': fields[0], 'type': fields[1], 'size_kib': size,
                     'used_kib': used, 'priority': priority})
    return rows


def device_is_mounted():
    try:
        target = (Path('/sys/dev/block/8:4/dev')).read_text().strip()
        if target != '8:4':
            raise ManagerError('sysfs backing identity changed')
        for line in Path('/proc/self/mountinfo').read_text().splitlines():
            fields = line.split()
            if len(fields) < 10:
                raise ManagerError('malformed mountinfo row')
            if fields[2] == '8:4':
                return True
        return False
    except OSError as exc:
        raise ManagerError('cannot verify mount/identity state') from exc


def device_has_holders():
    try:
        holders = list(Path('/sys/dev/block/8:4/holders').iterdir())
    except OSError as exc:
        raise ManagerError('cannot verify backing-device holders') from exc
    return bool(holders)


def root_uses_target():
    try:
        result = subprocess.run(
            ['findmnt', '-rn', '-o', 'MAJ:MIN', '--target', '/'],
            capture_output=True, text=True, timeout=5, check=False)
        if result.returncode:
            raise ManagerError('cannot identify root filesystem backing')
        fields = result.stdout.split()
        if len(fields) != 1 or not re.fullmatch(r'[0-9]+:[0-9]+', fields[0]):
            raise ManagerError('root filesystem major:minor is malformed')
        pending = [fields[0]]
        seen = set()
        while pending:
            identity = pending.pop()
            if identity in seen:
                continue
            seen.add(identity)
            if identity == '8:4':
                return True
            slaves = Path('/sys/dev/block', identity, 'slaves')
            for slave in slaves.iterdir():
                dev = (slave / 'dev').read_text().strip()
                if not re.fullmatch(r'[0-9]+:[0-9]+', dev):
                    raise ManagerError('root backing chain has malformed identity')
                pending.append(dev)
        return False
    except OSError as exc:
        raise ManagerError('cannot inspect root backing chain') from exc


def persistent_state_storage():
    if not STATE_DIR.exists():
        return False, 'state directory is absent'
    try:
        info = STATE_DIR.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or \
                stat.S_IMODE(info.st_mode) != 0o700:
            return False, 'state directory is not root-owned mode 0700'
        result = subprocess.run(
            ['findmnt', '-rn', '-o', 'FSTYPE,SOURCE', '-T', str(STATE_DIR)],
            capture_output=True, text=True, timeout=5, check=False)
        if result.returncode:
            return False, 'findmnt cannot identify recovery storage'
        fields = result.stdout.split()
        if len(fields) != 2 or fields[0] in {'tmpfs', 'ramfs', 'zram', 'overlay'}:
            return False, 'recovery storage is not an accepted persistent filesystem'
        try:
            source_id = block_identity(fields[1])
        except (OSError, ManagerError):
            return False, 'recovery storage source is not an identifiable block device'
        if source_id == DEVICE_ID:
            return False, 'recovery storage is on the partition under test'
        return True, f'{fields[0]} on {source_id[0]}:{source_id[1]}'
    except OSError as exc:
        return False, f'cannot inspect recovery storage: {exc}'


class LinuxOps:
    def command(self, argv, timeout=30, check=True):
        try:
            result = subprocess.run(list(map(str, argv)), capture_output=True,
                                    text=True, timeout=timeout, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ManagerError(f'command failed to run: {argv[0]}') from exc
        if check and result.returncode:
            raise ManagerError(f'{argv[0]} exited {result.returncode}: '
                               f'{(result.stderr or result.stdout)[-500:]}')
        return result

    def dm_rows(self):
        result = self.command([
            'dmsetup', 'info', '-c', '--noheadings', '--separator', ':',
            '-o', 'name,uuid,major,minor,open'], check=False)
        if result.returncode and result.stdout.strip() != 'No devices found':
            raise ManagerError('cannot enumerate Device Mapper devices')
        return parse_dm_info(result.stdout)

    def module_loaded(self):
        return Path('/sys/module/dm_swapz').is_dir()

    def active_swap_rows(self):
        try:
            return parse_swaps(Path('/proc/swaps').read_text())
        except OSError as exc:
            raise ManagerError('cannot read active swap inventory') from exc

    def boot_id(self):
        value = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
        if not re.fullmatch(r'[0-9a-f-]{36}', value):
            raise ManagerError('kernel boot id is malformed')
        return value

    def status(self, name):
        return self.command(['dmsetup', 'status', name]).stdout

    def table(self, name):
        return self.command(['dmsetup', 'table', '--showkeys', name]).stdout

    def verify_status(self, text):
        fields = {}
        for token in text.split():
            if '=' not in token:
                continue
            key, value = token.split('=', 1)
            if key in fields or not value.isdigit():
                raise ManagerError('malformed swapz status counters')
            fields[key] = int(value)
        for key in ('failed', 'error', 'flush_err', 'segment_discards_failed'):
            if fields.get(key, 0) != 0:
                raise ManagerError(f'swapz reports nonzero {key}')
        if not fields:
            raise ManagerError('swapz status lacks key/value counters')

    def verify_mapper(self, *, allow_open):
        matching = [row for row in self.dm_rows()
                    if row[0] == MAPPER_NAME or row[1] == MAPPER_UUID]
        if len(matching) != 1 or matching[0][:2] != (MAPPER_NAME, MAPPER_UUID):
            raise ManagerError('primary mapper identity is absent, duplicated or substituted')
        _name, _uuid, major, minor, opened = matching[0]
        sysfs = Path(f'/sys/dev/block/{major}:{minor}')
        try:
            actual_name = (sysfs / 'dm/name').read_text().strip()
            actual_uuid = (sysfs / 'dm/uuid').read_text().strip()
            sectors = int((sysfs / 'size').read_text().strip())
            lower = [(Path(p) / 'dev').read_text().strip()
                     for p in (sysfs / 'slaves').iterdir()]
        except (OSError, ValueError) as exc:
            raise ManagerError('cannot independently inspect mapper sysfs identity') from exc
        if (actual_name, actual_uuid, sectors, lower) != (
                MAPPER_NAME, MAPPER_UUID, LOGICAL_SECTORS, ['8:4']):
            raise ManagerError('mapper sysfs name, UUID, geometry or lower device differs')
        validate_table(self.table(MAPPER_NAME))
        self.verify_status(self.status(MAPPER_NAME))
        if opened < 0 or (opened != 0 and not allow_open):
            raise ManagerError('mapper has unexpected open references')
        node = Path(f'/dev/mapper/{MAPPER_NAME}')
        if block_identity(node) != (major, minor):
            raise ManagerError('mapper device node identity differs')
        size = bytearray(8)
        fd = os.open(node, os.O_RDONLY | os.O_CLOEXEC)
        try:
            fcntl.ioctl(fd, BLKGETSIZE64, size, True)
        finally:
            os.close(fd)
        if int.from_bytes(size, sys.byteorder) != LOGICAL_BYTES:
            raise ManagerError('mapper node capacity differs')
        return major, minor


class PrimaryManager:
    def __init__(self, ops=None):
        self.ops = ops or LinuxOps()

    def load_state(self):
        self.validate_state_directory()
        state = load_unique_json(STATE_PATH)
        if not isinstance(state, dict) or state.get('schema') != 'swapz-primary-v1':
            raise ManagerError('primary state schema is invalid')
        expected = {'device': '/dev/sda4', 'major': 8, 'minor': 4,
                    'partuuid': '7fb9401d-04', 'size_bytes': DEVICE_BYTES,
                    'logical_pages': LOGICAL_PAGES, 'dm_name': MAPPER_NAME,
                    'dm_uuid': MAPPER_UUID}
        if any(state.get(k) != v for k, v in expected.items()):
            raise ManagerError('primary state is not bound to exact /dev/sda4 maximum')
        backup_fd = os.open(BACKUP_PATH, os.O_RDONLY | os.O_CLOEXEC |
                            getattr(os, 'O_NOFOLLOW', 0))
        try:
            info = os.fstat(backup_fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or \
                    info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != 0o600:
                raise ManagerError('original header backup is unsafe')
            backup = os.read(backup_fd, PAGE_BYTES + 1)
        finally:
            os.close(backup_fd)
        if len(backup) != PAGE_BYTES or hashlib.sha256(backup).hexdigest() != \
                state.get('original_header_sha256') or \
                state.get('original_header_sha256') != ORIGINAL_HEADER_SHA256:
            raise ManagerError('original block-zero backup does not match state')
        header = read_block_zero()
        if not valid_swz_header(header) or hashlib.sha256(header).hexdigest() != \
                state.get('swz_header_sha256'):
            raise ManagerError('physical SWZ header differs from durable state')
        if not re.fullmatch(r'[0-9a-f]{64}', str(state.get('module_sha256', ''))):
            raise ManagerError('qualified module hash is missing')
        if state.get('stage') not in {
                'PREPARED', 'STOPPED', 'MODULE_LOAD_PENDING', 'MODULE_LOADED',
                'MAPPER_CREATE_PENDING', 'MAPPER_CREATED', 'MKSWAP_PENDING',
                'MAPPER_READY', 'REQUIRES_REVIEW'}:
            raise ManagerError('primary lifecycle stage is unknown')
        return state

    @staticmethod
    def validate_state_directory():
        try:
            info = STATE_DIR.lstat()
        except OSError as exc:
            raise ManagerError('primary state directory is missing') from exc
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or \
                stat.S_IMODE(info.st_mode) != 0o700:
            raise ManagerError('primary state directory is not root-owned mode 0700')

    def plan(self):
        gates = {}
        try:
            gates['uuid_path'] = os.path.realpath(UUID_PATH) == str(DEVICE)
            gates['partuuid_path'] = os.path.realpath(PARTUUID_PATH) == str(DEVICE)
            gates['block_identity'] = block_identity(DEVICE) == DEVICE_ID
            gates['byte_size'] = len(read_block_zero(DEVICE)) == PAGE_BYTES
            gates['not_mounted'] = not device_is_mounted()
            gates['no_holders'] = not device_has_holders()
            gates['root_not_on_target'] = not root_uses_target()
            gates['persistent_state_storage'], storage = persistent_state_storage()
            gates['state'] = None
            if STATE_PATH.exists():
                state = self.load_state()
                gates['state'] = state.get('stage')
                gates['state_valid'] = state.get('stage') in {'PREPARED', 'STOPPED'}
                gates['max_capacity'] = state.get('logical_pages') == LOGICAL_PAGES
                gates['module_file_hash'] = self.module_file_hash() == state['module_sha256']
            else:
                gates['state_valid'] = False
                gates['max_capacity'] = False
                gates['module_file_hash'] = False
            gates['active_swaps'] = self.ops.active_swap_rows()
            gates['module_absent'] = not self.ops.module_loaded()
            matching = [r for r in self.ops.dm_rows()
                        if r[0] == MAPPER_NAME or r[1] == MAPPER_UUID]
            gates['mapper_absent'] = not matching
            gates['storage'] = storage
            gates['status'] = 'PASS' if all(
                v is True for k, v in gates.items()
                if k not in {'state', 'active_swaps', 'storage'}) and \
                not gates.get('active_swaps') else 'BLOCKED'
        except (OSError, ManagerError, ValueError) as exc:
            gates['status'] = 'BLOCKED'
            gates['error'] = str(exc)
        return {'schema': 'swapz-primary-plan-v1', 'logical_pages': LOGICAL_PAGES,
                'logical_bytes': LOGICAL_BYTES,
                'linux_swap_kib': LOGICAL_BYTES // 1024 - PAGE_BYTES // 1024,
                'gc_reserve_blocks': (LOGICAL_PAGES + 7) // 8,
                'gates': gates}

    def module_file_hash(self):
        path = self.ops.command(['modinfo', '-n', 'dm_swapz']).stdout.strip()
        info = os.stat(path)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or \
                info.st_mode & 0o022:
            raise ManagerError('installed module file is not root-controlled')
        digest = hashlib.sha256()
        with open(path, 'rb') as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(chunk)
        return digest.hexdigest()

    def start(self):
        if not PRIMARY_EXECUTION_ENABLED:
            raise ManagerError('primary-swap execution is not qualified and remains disabled')
        if os.geteuid() != 0:
            raise ManagerError('start requires root')
        lock = self.lock()
        try:
            state = self.load_state()
            if state.get('stage') not in {'PREPARED', 'STOPPED'}:
                if state.get('boot_id') != self.ops.boot_id():
                    if state.get('stage') not in {'MAPPER_READY', 'ACTIVE', 'STOPPING'}:
                        raise ManagerError('previous boot state requires review')
                    if self.ops.active_swap_rows() or self.ops.module_loaded() or \
                            any(r[0] == MAPPER_NAME or r[1] == MAPPER_UUID
                                for r in self.ops.dm_rows()):
                        raise ManagerError('cold-boot stale state has live resources')
                    state.setdefault('events', []).append({
                        'event': 'cold_boot_lost_volatile_authority',
                        'previous_boot_id': state.get('boot_id'),
                        'at': time.time()})
                else:
                    raise ManagerError('same-boot mapper lifecycle is not stopped')
            if os.path.realpath(UUID_PATH) != str(DEVICE) or \
                    os.path.realpath(PARTUUID_PATH) != str(DEVICE) or \
                    block_identity(DEVICE) != DEVICE_ID or device_is_mounted() or \
                    device_has_holders() or root_uses_target():
                raise ManagerError(
                    'live device identity, root chain, mount or holder preflight failed')
            if self.ops.active_swap_rows():
                raise ManagerError('another swap area is active before mapper start')
            if self.ops.module_loaded() or any(
                    r[0] == MAPPER_NAME or r[1] == MAPPER_UUID
                    for r in self.ops.dm_rows()):
                raise ManagerError('unowned module or mapper already exists')
            storage_ok, why = persistent_state_storage()
            if not storage_ok:
                raise ManagerError('recovery state is not on persistent storage: ' + why)
            if self.module_file_hash() != state['module_sha256']:
                raise ManagerError('installed module differs from qualified module hash')
            state['boot_id'] = self.ops.boot_id()
            state['stage'] = 'MODULE_LOAD_PENDING'
            state['module_loaded_by_service'] = False
            state['updated_at'] = time.time()
            durable_json(STATE_PATH, state)
            loaded = self.ops.command(['modprobe', 'dm_swapz', 'allow_physical_backing=1'],
                                      check=False)
            if loaded.returncode:
                if self.ops.module_loaded():
                    state['stage'] = 'REQUIRES_REVIEW'
                    state['error'] = 'modprobe returned failure but module is present'
                    durable_json(STATE_PATH, state)
                raise ManagerError('qualified dm_swapz module load failed')
            param = Path('/sys/module/dm_swapz/parameters/allow_physical_backing')
            if not self.ops.module_loaded() or param.read_text().strip() not in {'Y', '1'}:
                state['stage'] = 'REQUIRES_REVIEW'
                state['error'] = 'physical-backing opt-in was not effective'
                durable_json(STATE_PATH, state)
                raise ManagerError(state['error'])
            state['module_loaded_by_service'] = True
            state['stage'] = 'MODULE_LOADED'
            durable_json(STATE_PATH, state)
            state['stage'] = 'MAPPER_CREATE_PENDING'
            durable_json(STATE_PATH, state)
            table = ' '.join(expected_table())
            created = self.ops.command([
                'dmsetup', 'create', MAPPER_NAME, '--uuid', MAPPER_UUID,
                '--table', table], check=False)
            if created.returncode:
                state['stage'] = 'REQUIRES_REVIEW'
                state['error'] = 'dmsetup create returned failure; mapper identity requires review'
                durable_json(STATE_PATH, state)
                raise ManagerError(state['error'])
            state['stage'] = 'MAPPER_CREATED'
            durable_json(STATE_PATH, state)
            dm_major, dm_minor = self.ops.verify_mapper(allow_open=False)
            state['dm_major'] = dm_major
            state['dm_minor'] = dm_minor
            if hashlib.sha256(read_block_zero()).hexdigest() != \
                    state['swz_header_sha256']:
                raise ManagerError('physical SWZ header changed while mapper was created')
            state['stage'] = 'MKSWAP_PENDING'
            durable_json(STATE_PATH, state)
            self.ops.command(['mkswap', '--', f'/dev/mapper/{MAPPER_NAME}'])
            self.ops.verify_mapper(allow_open=False)
            if hashlib.sha256(read_block_zero()).hexdigest() != \
                    state['swz_header_sha256']:
                raise ManagerError('mkswap changed physical SWZ authorization header')
            state['stage'] = 'MAPPER_READY'
            state['updated_at'] = time.time()
            durable_json(STATE_PATH, state)
            return state
        finally:
            os.close(lock)

    def mapper_swap_rows(self, major, minor):
        rows = []
        for row in self.ops.active_swap_rows():
            if row['type'] == 'file':
                continue
            try:
                identity = block_identity(row['path'])
            except (OSError, ManagerError) as exc:
                raise ManagerError('cannot identify active swap device') from exc
            if identity == (major, minor):
                rows.append(row)
        return rows

    def stop(self):
        if not PRIMARY_EXECUTION_ENABLED:
            raise ManagerError('primary-swap execution is not qualified and remains disabled')
        if os.geteuid() != 0:
            raise ManagerError('stop requires root')
        lock = self.lock()
        try:
            state = self.load_state()
            if state.get('boot_id') != self.ops.boot_id():
                raise ManagerError('state belongs to another boot; automatic teardown refused')
            matching = [r for r in self.ops.dm_rows()
                        if r[0] == MAPPER_NAME or r[1] == MAPPER_UUID]
            if not matching:
                try:
                    require_stopped_state_is_unambiguous(
                        state, self.ops.module_loaded(), self.mapper_swap_rows(
                            state.get('dm_major'), state.get('dm_minor')))
                except ManagerError as exc:
                    state['stage'] = 'REQUIRES_REVIEW'
                    state['error'] = str(exc)
                    durable_json(STATE_PATH, state)
                    raise
                state['stage'] = 'STOPPED'
                state['updated_at'] = time.time()
                durable_json(STATE_PATH, state)
                return state
            if len(matching) != 1:
                state['stage'] = 'REQUIRES_REVIEW'
                state['error'] = 'multiple matching mapper identities exist'
                durable_json(STATE_PATH, state)
                raise ManagerError(state['error'])
            try:
                require_owned_mapper_for_stop(state, matching[0])
            except ManagerError as exc:
                state['stage'] = 'REQUIRES_REVIEW'
                state['error'] = str(exc)
                durable_json(STATE_PATH, state)
                raise
            dm_major, dm_minor = self.ops.verify_mapper(allow_open=True)
            if self.mapper_swap_rows(dm_major, dm_minor):
                state['stage'] = 'REQUIRES_REVIEW'
                state['error'] = (
                    'systemd has not deactivated the mapper swap; '
                    'mapper and module deliberately retained')
                durable_json(STATE_PATH, state)
                raise ManagerError(state['error'])
            self.ops.verify_mapper(allow_open=False)
            state['stage'] = 'MAPPER_REMOVE_PENDING'
            durable_json(STATE_PATH, state)
            self.ops.command(['dmsetup', 'remove', '--', MAPPER_NAME])
            if any(r[0] == MAPPER_NAME or r[1] == MAPPER_UUID
                   for r in self.ops.dm_rows()):
                raise ManagerError('primary mapper remains after removal')
            state['stage'] = 'MAPPER_REMOVED'
            durable_json(STATE_PATH, state)
            if state.get('module_loaded_by_service') and self.ops.module_loaded():
                refcount = int(Path('/sys/module/dm_swapz/refcnt').read_text().strip())
                if refcount:
                    state['stage'] = 'REQUIRES_REVIEW'
                    state['error'] = 'dm_swapz still has module users; module retained'
                    durable_json(STATE_PATH, state)
                    raise ManagerError(state['error'])
                self.ops.command(['rmmod', 'dm_swapz'])
            if self.ops.module_loaded():
                state['stage'] = 'REQUIRES_REVIEW'
                state['error'] = 'dm_swapz remains loaded after owned unload'
                durable_json(STATE_PATH, state)
                raise ManagerError(state['error'])
            state['stage'] = 'STOPPED'
            state['module_loaded_by_service'] = False
            state['updated_at'] = time.time()
            durable_json(STATE_PATH, state)
            return state
        finally:
            os.close(lock)

    def mem_available_kib(self):
        for line in Path('/proc/meminfo').read_text().splitlines():
            key, _, rest = line.partition(':')
            if key == 'MemAvailable':
                fields = rest.split()
                if fields:
                    return int(fields[0])
        raise ManagerError('MemAvailable is unavailable')

    @staticmethod
    def lock():
        LOCK_PATH.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
        fd = os.open(LOCK_PATH, os.O_RDWR | os.O_CREAT | os.O_CLOEXEC |
                     getattr(os, 'O_NOFOLLOW', 0), 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fd


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('plan', 'start', 'stop'))
    args = parser.parse_args(argv)
    manager = PrimaryManager()
    try:
        if args.action == 'plan':
            value = manager.plan()
            print(json.dumps(value, sort_keys=True, indent=2))
            return 0 if value['gates']['status'] == 'PASS' else 2
        state = manager.start() if args.action == 'start' else manager.stop()
        print(json.dumps({'action': args.action, 'stage': state['stage']}, sort_keys=True))
        return 0
    except (OSError, ManagerError, ValueError, subprocess.SubprocessError) as exc:
        print(f'BLOCKED: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
