#!/usr/bin/env python3
"""Export and restore a bounded, self-contained shallow Git source checkout."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

COMMIT = "c339f4010dea8b0d754f84ace70cd1b089878ef8"
TREE = "7494ea078a05b0b824c3f263260e45c1f78bcfd3"
REQUIRED = ("Makefile", "init/main.c", "arch/x86/Kconfig", "mm/zswap.c",
            "mm/swapfile.c", "mm/Makefile", "block/bio.c", "drivers/md/dm.c",
            "drivers/md/Makefile", "include/linux/swap.h", "include/linux/bio.h",
            "include/linux/device-mapper.h")
CHUNK = 16 * 1024 * 1024
MAX_CHUNKS = 32
ENV = dict(os.environ, GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
           GIT_NO_REPLACE_OBJECTS="1", GIT_NO_LAZY_FETCH="1", GIT_TERMINAL_PROMPT="0")


def require(condition, reason):
    if not condition:
        raise RuntimeError(reason)


def git(root, *args, **kwargs):
    return subprocess.check_output(["git", "-C", str(root), *args], env=ENV, **kwargs)


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def inspect(root, commit, tree, required, minimum):
    require(git(root, "rev-parse", "HEAD").decode().strip() == commit, "HEAD mismatch")
    require(git(root, "rev-parse", "HEAD^{tree}").decode().strip() == tree, "tree mismatch")
    require(git(root, "rev-parse", "--show-object-format").strip() == b"sha1", "object format")
    require(git(root, "rev-parse", "--is-shallow-repository").strip() == b"true", "not shallow")
    require((root / ".git/shallow").read_text().splitlines() == [commit], "shallow boundary")
    require(not (root / ".git/objects/info/alternates").exists(), "alternate objects")
    require(not list((root / ".git/objects/pack").glob("*.promisor")), "promisor objects")
    config = git(root, "config", "--local", "--list").decode().lower()
    require(not any(key in config for key in ("partialclone", "promisor", "sparsecheckout=true")),
            "partial or sparse checkout")
    require(not git(root, "status", "--porcelain", "--untracked-files=all"), "dirty checkout")
    tracked = git(root, "ls-files", "-z").split(b"\0")[:-1]
    flags = git(root, "ls-files", "-v", "-z").split(b"\0")[:-1]
    require(len(tracked) >= minimum and len(flags) == len(tracked) and
            all(row.startswith(b"H ") for row in flags), "incomplete tracked checkout")
    hashes = {}
    for name in required:
        path = root / name
        require(path.is_file() and not path.is_symlink(), "required source missing: " + name)
        hashes[name] = {"bytes": path.stat().st_size, "sha256": sha(path)}
    git(root, "fsck", "--full", "--no-reflogs", "--connectivity-only")
    objects = len(git(root, "rev-list", "--objects", "--no-object-names", commit).splitlines())
    return {"tracked": len(tracked), "reachable_objects": objects, "files": hashes}


def export(root, output, commit=COMMIT, tree=TREE, required=REQUIRED, minimum=50000):
    identity = inspect(root, commit, tree, required, minimum)
    output.mkdir(mode=0o700)
    pack = output / "source.pack"
    with pack.open("xb") as stream:
        subprocess.run(["git", "-C", str(root), "pack-objects", "--revs", "--stdout"],
                       input=(commit + "\n").encode(), stdout=stream, env=ENV, check=True)
    size = pack.stat().st_size
    require(0 < size <= CHUNK * MAX_CHUNKS, "pack exceeds transfer bound")
    chunks = []
    with pack.open("rb") as stream:
        while data := stream.read(CHUNK):
            name = f"chunk-{len(chunks):02d}.packpart"
            (output / name).write_bytes(data)
            chunks.append({"name": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
    manifest = dict(identity, commit=commit, tree=tree, pack_bytes=size, pack_sha256=sha(pack),
                    chunks=chunks, shallow=[commit], schema=1)
    pack.unlink()
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest


def restore(source, root, commit=COMMIT, tree=TREE, required=REQUIRED, minimum=50000):
    manifest = json.loads((source / "manifest.json").read_text())
    require(manifest["schema"] == 1 and manifest["commit"] == commit and manifest["tree"] == tree and
            manifest["shallow"] == [commit], "manifest identity")
    chunks = manifest["chunks"]
    require(0 < len(chunks) <= MAX_CHUNKS and 0 < manifest["pack_bytes"] <= CHUNK * MAX_CHUNKS,
            "manifest transfer bound")
    require(not root.exists(), "restore destination exists")
    for index, item in enumerate(chunks):
        require(item["name"] == f"chunk-{index:02d}.packpart" and
                0 < item["bytes"] <= CHUNK and (index == len(chunks) - 1 or item["bytes"] == CHUNK),
                "chunk sequence or size")
        path = source / item["name"]
        require(path.is_file() and not path.is_symlink() and path.stat().st_size == item["bytes"] and
                sha(path) == item["sha256"], "chunk integrity: " + item["name"])
    require(sum(item["bytes"] for item in chunks) == manifest["pack_bytes"], "pack size mismatch")
    root.mkdir(mode=0o700)
    git(root, "init", "--quiet", "--template=", "--initial-branch=main")
    (root / ".git/shallow").write_text(commit + "\n")
    pack = root / ".git/source.pack"
    with pack.open("xb") as stream:
        for item in chunks:
            with (source / item["name"]).open("rb") as part:
                shutil.copyfileobj(part, stream, 1024 * 1024)
    require(sha(pack) == manifest["pack_sha256"], "pack digest mismatch")
    with pack.open("rb") as stream:
        git(root, "index-pack", "--stdin", "--strict", stdin=stream)
    pack.unlink()
    git(root, "-c", "core.hooksPath=/dev/null", "checkout", "--quiet", "--detach", commit)
    identity = inspect(root, commit, tree, required, minimum)
    require(all(identity[key] == manifest[key] for key in identity), "restored source census mismatch")
    counts = dict(line.split(": ", 1) for line in git(root, "count-objects", "-v").decode().splitlines())
    require(int(counts["in-pack"]) == identity["reachable_objects"] and int(counts["count"]) == 0,
            "pack object census mismatch")
    require(not git(root, "remote") and not git(root, "for-each-ref"), "unexpected remote or ref")
    return dict(identity, commit=commit, tree=tree, pack_sha256=manifest["pack_sha256"],
                packed_objects=int(counts["in-pack"]), status="PASS_SOURCE_RESTORE_ONLY")


def main():
    os.umask(0o077)
    mode, source, destination = sys.argv[1:]
    require(mode in ("export", "restore"), "unknown mode")
    result = (export if mode == "export" else restore)(Path(source), Path(destination))
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        print("R119_SOURCE_TRANSPORT_FIRST_ERROR", str(error).splitlines()[0][:240], file=sys.stderr)
        sys.exit(1)
