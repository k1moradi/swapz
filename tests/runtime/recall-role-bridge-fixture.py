#!/usr/bin/env python3
"""Standalone rootless Bash-coprocess fixture for the injected five-role bridge.

Always creates private temporary regular files and uses a synthetic client.
Accepts no arguments, device names, paths, subprocess-launch switches or
environment configuration. It CANNOT enable real mapper/dd I/O.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import sys
import tempfile


HERE = Path(__file__).resolve().parent


def load(name, filename):
    specification = importlib.util.spec_from_file_location(name, HERE / filename)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    return module


def main():
    if len(sys.argv) != 1:
        print("ROOTLESS_ROLE_PRESERVE: unexpected arguments", file=sys.stderr)
        return 2
    bridge_module = load("swapz_role_coproc_bridge", "recall-control-bridge.py")
    fixtures = load("swapz_role_coproc_fixtures", "recall-role-bridge-test.py")
    with tempfile.TemporaryDirectory(prefix="swapz-role-coproc-") as directory:
        fixture = Path(directory) / "fixture"
        fixture.mkdir(mode=0o700)
        directory_fd = os.open(
            fixture, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        )
        reference = b"".join(
            bytes(((page * 23 + index) % 256) for index in range(4096))
            for page in range(9)
        )
        client = fixtures.SyntheticRoleService(fixture, directory_fd, reference)
        try:
            process = fixtures.SyntheticProcess()
            adapter = bridge_module.adapter_module.RecallRoleIPCAdapter(
                client, process, verify_role_result=client.verify_role,
            )
            bridge = bridge_module.RootlessRoleBridge(
                client=client, process=process, adapter=adapter,
            )
            bridge_module._print_reply(bridge._reply(None, "rootless_role_bridge_ready"))
            try:
                while not bridge.finished:
                    raw = sys.stdin.buffer.readline(bridge_module.MAX_LINE_BYTES + 1)
                    if not raw:
                        print("ROOTLESS_ROLE_PRESERVE: controller disconnected", file=sys.stderr)
                        return 2
                    request = None
                    try:
                        request = bridge_module._decode(raw)
                        response = bridge.dispatch(request)
                    except Exception as exc:
                        bridge.failed = True
                        print(f"ROOTLESS_ROLE_PRESERVE: {str(exc)[:160]}", file=sys.stderr)
                        request_id = (request.get("id") if isinstance(request, dict)
                                      and type(request.get("id")) is int else None)
                        bridge_module._print_reply(bridge._reply(
                            request_id, "preserve_backing",
                            error="rootless role safety gate failed",
                        ))
                        return 2
                    bridge_module._print_reply(response)
                return 0 if bridge.finalized and not bridge.failed else 2
            finally:
                if not bridge.finalized or bridge.failed:
                    bridge.best_effort_preserve()
        finally:
            client.close_outputs()
            os.close(directory_fd)


if __name__ == "__main__":
    raise SystemExit(main())
