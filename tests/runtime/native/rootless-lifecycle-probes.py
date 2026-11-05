#!/usr/bin/env python3
"""Rootless independent subprocess/pipe lifecycle probes, not the repository test suite."""
import errno
import io
import json
import os
import select
import signal
import socket
import subprocess
import sys
import tempfile
from unittest import mock


def launch(script, *, new_session=False, stderr=subprocess.DEVNULL):
    return subprocess.Popen([sys.executable, '-I', '-c', script],
                            start_new_session=new_session,
                            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=stderr)


def stop_owned(process):
    try:
        if process.poll() is None:
            process.kill()  # exact Popen handle, not os.kill(guessed_pid)
        process.wait(timeout=5)
    finally:
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is not None:
                stream.close()


def main():
    assert os.geteuid() != 0, 'rootless only'
    result = {}
    for attempt in range(5):
        # Early abnormal exit remains observable via the Popen identity.
        process = launch('import sys; sys.exit(7)')
        try:
            assert process.wait(timeout=5) == 7
        finally:
            stop_owned(process)
        # A silent listener timeout may not authorize any connection.
        with tempfile.TemporaryDirectory(prefix='swapz-timeout-') as directory:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
                listener.bind(directory + '/admission.sock')
                listener.listen(1)
                listener.settimeout(0.01)
                try:
                    listener.accept()
                except socket.timeout:
                    pass
                else:
                    raise AssertionError('unexpected connection')
        # Partial terminal JSON cannot form a complete line.
        process = launch("import sys; sys.stdout.buffer.write(b'ORACLE_VERIFIED={\\\"pid\\\":'); sys.stdout.flush()")
        try:
            data = process.communicate(timeout=5)[0]
            assert process.returncode == 0 and not data.endswith(b'\n')
        finally:
            stop_owned(process)
        # Successful-looking terminal text followed by exit 7 must remain a failure.
        process = launch("import sys; print('ORACLE_VERIFIED={}',flush=True); sys.exit(7)")
        try:
            data, _ = process.communicate(timeout=5)
            assert b'ORACLE_VERIFIED={}' in data and process.returncode == 7
        finally:
            stop_owned(process)
        # Interrupting wait leaves a launched isolated child running unless
        # the production caller has a BaseException-aware ownership finalizer.
        process = launch('import time; time.sleep(60)', new_session=True)
        try:
            with mock.patch.object(process, 'wait', side_effect=KeyboardInterrupt):
                try:
                    process.wait(timeout=45)
                except KeyboardInterrupt:
                    pass
                else:
                    raise AssertionError('expected interrupted wait')
            assert process.poll() is None
        finally:
            stop_owned(process)
        # A failure in stderr collection is not a valid verification record.
        process = launch('import sys; sys.exit(4)', stderr=subprocess.PIPE)
        try:
            assert process.wait(timeout=5) == 4
            process.stderr.close()
            try:
                process.stderr.read(4097)
            except ValueError:
                pass
            else:
                raise AssertionError('expected failed stderr collection')
        finally:
            stop_owned(process)
        # Unrelated children with the same file basename are unrelated owners.
        with tempfile.TemporaryDirectory(prefix='swapz-unrelated-') as directory:
            first = os.path.join(directory,'one'); second = os.path.join(directory,'two')
            os.mkdir(first, 0o700); os.mkdir(second, 0o700)
            same_name = 'primary-real-swap-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.json'
            with open(os.path.join(first, same_name), 'x') as writer: writer.write('FAIL\n')
            with open(os.path.join(second, same_name), 'x') as writer: writer.write('PASS\n')
            assert open(os.path.join(first,same_name)).read() == 'FAIL\n'
        # Group-wide kill is allowed only while the actual session leader's
        # PID remains reserved by the parent-child ownership relationship.
        process = launch('import time; time.sleep(60)', new_session=True)
        try:
            assert process.poll() is None
            assert os.getpgid(process.pid) == process.pid
            os.killpg(process.pid, signal.SIGTERM)
            assert process.wait(timeout=5) == -signal.SIGTERM
        finally:
            stop_owned(process)
    result = {'iterations':5,'early_child_death':'observed',
              'listener_timeout':'observed', 'partial_terminal':'incomplete',
              'post_verification_nonzero_exit':'observed',
              'interrupted_wait_without_finalizer':'child_remained_live',
              'failed_stderr_collection':'observed',
              'same_named_foreign_path':'not_owner',
              'owned_process_group_cleanup':'session_leader_only',
              'privileged_execution':False}
    print(json.dumps(result,sort_keys=True))

if __name__=='__main__':
    main()
