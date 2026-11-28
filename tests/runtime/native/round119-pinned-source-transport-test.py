#!/usr/bin/env python3
"""Real disposable shallow Git pack roundtrip and fail-closed controls."""
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

PATH = Path(__file__).resolve().parents[2] / "tools/round119-pinned-source-transport.py"
if not PATH.is_file():
    PATH = Path(__file__).with_name("round119-pinned-source-transport.py")
spec = importlib.util.spec_from_file_location("transport", PATH)
transport = importlib.util.module_from_spec(spec)
spec.loader.exec_module(transport)


class TransportTest(unittest.TestCase):
    def test_roundtrip_and_rejections(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            original = base / "original"
            original.mkdir()
            git = transport.git
            git(original, "init", "--quiet", "--initial-branch=main")
            git(original, "config", "user.name", "Fixture")
            git(original, "config", "user.email", "fixture@example.invalid")
            (original / "Makefile").write_text("first\n")
            git(original, "add", ".")
            git(original, "commit", "-qm", "first")
            (original / "Makefile").write_text("second\n")
            (original / "source.c").write_bytes(bytes(range(256)) * 16)
            git(original, "add", ".")
            git(original, "commit", "-qm", "second")
            source = base / "shallow"
            subprocess.run(["git", "clone", "--quiet", "--depth=1", original.as_uri(), str(source)],
                           check=True, env=transport.ENV)
            commit = git(source, "rev-parse", "HEAD").decode().strip()
            tree = git(source, "rev-parse", "HEAD^{tree}").decode().strip()
            args = (commit, tree, ("Makefile", "source.c"), 2)
            transport.CHUNK = 128
            output = base / "pack"
            manifest = transport.export(source, output, *args)
            self.assertGreater(len(manifest["chunks"]), 1)
            result = transport.restore(output, base / "restored", *args)
            self.assertEqual(result["status"], "PASS_SOURCE_RESTORE_ONLY")
            self.assertEqual(result["files"], manifest["files"])
            self.assertEqual(result["reachable_objects"], result["packed_objects"])
            part = output / manifest["chunks"][0]["name"]
            data = part.read_bytes()
            part.write_bytes(bytes([data[0] ^ 1]) + data[1:])
            with self.assertRaisesRegex(RuntimeError, "chunk integrity"):
                transport.restore(output, base / "corrupt", *args)
            part.unlink()
            with self.assertRaisesRegex(RuntimeError, "chunk integrity"):
                transport.restore(output, base / "missing", *args)
            part.write_bytes(data)
            changed = dict(manifest, pack_sha256="0" * 64)
            (output / "manifest.json").write_text(json.dumps(changed))
            with self.assertRaisesRegex(RuntimeError, "pack digest"):
                transport.restore(output, base / "wrong-pack", *args)
            (output / "manifest.json").write_text(json.dumps(manifest))
            with self.assertRaisesRegex(RuntimeError, "manifest identity"):
                transport.restore(output, base / "wrong-pin", "0" * 40, *args[1:])
            (source / "Makefile").write_text("dirty\n")
            with self.assertRaisesRegex(RuntimeError, "dirty checkout"):
                transport.export(source, base / "dirty", *args)


if __name__ == "__main__":
    unittest.main(verbosity=2)
