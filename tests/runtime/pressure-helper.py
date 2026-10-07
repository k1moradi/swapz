import os, random, signal, sys
from pathlib import Path
size_mib = int(sys.argv[1])
marker_dir = Path(sys.argv[2])
size = size_mib * 1024 * 1024
page_size = 4096
pages = size // page_size
seed = 0x5A7A2026 + size_mib
buf = bytearray(size)
view = memoryview(buf)
def page_data(page):
    return random.Random(seed ^ (page * 0x9E3779B1)).randbytes(page_size)
for page in range(pages):
    data = page_data(page)
    start = page * page_size
    view[start:start + page_size] = data
del data
(marker_dir / 'filled').write_text(str(os.getpid()))
os.kill(os.getpid(), signal.SIGSTOP)
order = list(range(pages))
for pass_number in range(4):
    random.Random(seed + pass_number).shuffle(order)
    for page in order:
        data = page_data(page)
        start = page * page_size
        if view[start:start + page_size] != data:
            raise SystemExit(f'readback mismatch at pass={pass_number} page={page}')
(marker_dir / 'verified').write_text(str(os.getpid()))
os.kill(os.getpid(), signal.SIGSTOP)
print(f'bounded swap pressure readback: PASS size_mib={size_mib} pages={pages} passes=4', flush=True)
