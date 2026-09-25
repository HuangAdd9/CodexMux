import fcntl
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import select
import signal
import socket
import struct
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock
from types import SimpleNamespace


BIN = Path(os.environ.get("CODEX_TEST_BIN", Path(__file__).resolve().parents[1] / "bin"))
HELPER = BIN / "codex-session-sync"
SESSION = "11111111-1111-4111-8111-111111111111"
PARENT = "22222222-2222-4222-8222-222222222222"
LOADER = importlib.machinery.SourceFileLoader("session_sync", str(HELPER))
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
SYNC = importlib.util.module_from_spec(SPEC)
LOADER.exec_module(SYNC)


class SessionSyncTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="codex-sync-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.shared = self.root / ".codex"
        self.accounts = self.root / ".codex-accounts"
        self.target = self.accounts / "target"
        self.other = self.accounts / "other"
        for home in (self.shared, self.target, self.other):
            home.mkdir(parents=True)
            (home / "auth.json").write_text("{}")
        self.locks = self.root / "locks"
        self.fake = self.root / "fake-codex"
        self.fake.write_text(
            "#!/usr/bin/env python3\n"
            "import json, os, sys, time\n"
            "from pathlib import Path\n"
            "Path(os.environ['TEST_LAUNCHED']).write_text(json.dumps({"
            "'home': os.environ.get('CODEX_HOME'), 'args': sys.argv[1:], "
            "'wrapped': os.environ.get('CODEX_ACCOUNT_WRAPPED')}))\n"
            "time.sleep(float(os.environ.get('TEST_SLEEP', '0')))\n"
            "sys.exit(int(os.environ.get('TEST_EXIT', '0')))\n"
        )
        self.fake.chmod(0o700)
        self.environment = dict(os.environ)
        for name in ("CODEX_HOME", "CODEX_ACCOUNT_WRAPPED"):
            self.environment.pop(name, None)
        self.environment.update(
            HOME=str(self.root),
            PATH=str(BIN) + os.pathsep + os.environ["PATH"],
            CODEX_SHARED_HOME=str(self.shared),
            CODEX_ACCOUNTS_HOME=str(self.accounts),
            CODEX_ACCOUNT_LOCK_HOME=str(self.locks),
            CODEX_SESSION_SYNC_BIN=str(HELPER),
            CODEX_ACCOUNT_BIN=str(BIN / "codex-account"),
            CODEX_REAL_BIN=str(self.fake),
            TEST_LAUNCHED=str(self.root / "launched.json"),
        )

    def rollout(self, home, session=SESSION, suffix="", parent=None, provider="openai", parent_end=None):
        path = home / "sessions/2026/09/09" / f"rollout-test-{session}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"id": session, "model_provider": provider}
        if parent:
            payload["history_base"] = {"thread_id": parent}
            if parent_end is not None:
                payload["history_base"].update(end_byte_offset=parent_end, end_ordinal_exclusive=1)
        path.write_text(json.dumps({"type": "session_meta", "payload": payload}) + "\n" + suffix)
        return path

    def structured_rollout(self, home, records, session=SESSION, history_mode="legacy"):
        path = home / "sessions/2026/09/09" / f"rollout-test-{session}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        metadata = {
            "type": "session_meta",
            "payload": {"id": session, "history_mode": history_mode},
        }
        lines = [metadata, *records]
        path.write_text("".join(json.dumps(item) + "\n" for item in lines))
        return path

    @staticmethod
    def response(identifier, text, include_null_content=False, ordinal=None):
        payload = {"id": identifier, "type": "message", "text": text}
        if include_null_content:
            payload["content"] = None
        item = {"type": "response_item", "payload": payload}
        if ordinal is not None:
            item["ordinal"] = ordinal
        return item

    @staticmethod
    def turn_event(event_type, turn_id):
        return {
            "type": "event_msg",
            "payload": {"type": event_type, "turn_id": turn_id},
        }

    def command(self, target=None, session=SESSION, action="resume", execute=None):
        result = [str(HELPER), "--lock-home", str(self.locks),
                  "--session-action", action, session, str(target or self.target),
                  str(self.shared), str(self.target), str(self.other)]
        if execute:
            result += ["--", *execute]
        return result

    def run_sync(self, **kwargs):
        return subprocess.run(self.command(**kwargs), text=True, capture_output=True, timeout=10)

    def wait_for(self, predicate):
        deadline = time.monotonic() + 5
        while not predicate():
            if time.monotonic() >= deadline:
                self.fail("timed out waiting for child")
            time.sleep(0.02)

    def stop(self, process):
        if process.poll() is None:
            process.terminate()
        process.communicate(timeout=5)

    def test_largest_target_still_detects_divergence(self):
        self.rollout(self.target, suffix="new branch much longer\n")
        self.rollout(self.shared, suffix="old branch\n")
        result = self.run_sync()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("divergent copies", result.stderr)

    def test_equal_size_divergence(self):
        self.rollout(self.target, suffix="aaa\n")
        self.rollout(self.shared, suffix="bbb\n")
        self.assertIn("divergent copies", self.run_sync().stderr)

    def test_prefix_import_and_noop(self):
        source = self.rollout(self.shared, suffix="one\ntwo\n")
        target = self.rollout(self.target, suffix="one\n")
        self.assertEqual(self.run_sync().returncode, 0)
        self.assertEqual(source.read_bytes(), target.read_bytes())
        identity = SYNC.file_identity(target)
        self.assertEqual(self.run_sync().returncode, 0)
        self.assertEqual(identity, SYNC.file_identity(target))
        for home in (self.shared, self.target, self.other):
            self.assertEqual(list((home / "thread-writer-locks").glob(f"{SESSION}.lock")), [])

    def test_logical_superset_reconciles_different_history_formats(self):
        shared_records = [
            self.response(f"item-{index}", f"text-{index}", ordinal=10**50 + index)
            for index in range(12)
        ]
        target_compaction = {
            "type": "compacted",
            "payload": {
                "compaction_response_id": "compaction-one",
                "guardian_history": [{"type": "reasoning", "content": None}],
            },
        }
        source_compaction = {
            "type": "compacted",
            "payload": {
                "compaction_response_id": "compaction-one",
                "guardian_history": [{"type": "reasoning"}],
            },
        }
        target = self.structured_rollout(
            self.target,
            [
                self.turn_event("task_started", "turn-one"),
                *shared_records,
                target_compaction,
                self.turn_event("task_complete", "turn-one"),
            ],
            history_mode="paginated",
        )
        source = self.structured_rollout(
            self.other,
            [
                self.response("ancestor-item", "ancestor"),
                self.turn_event("task_started", "turn-one"),
                *[
                    self.response(f"item-{index}", f"text-{index}", include_null_content=True)
                    for index in range(12)
                ],
                source_compaction,
                self.turn_event("task_complete", "turn-one"),
                self.turn_event("task_started", "turn-two"),
                self.response("continuation-item", "continued"),
                self.turn_event("task_complete", "turn-two"),
            ],
            history_mode="legacy",
        )
        self.assertGreater(target.stat().st_size, source.stat().st_size)

        result = self.run_sync()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(target.read_bytes(), source.read_bytes())

    def test_logically_equivalent_formats_keep_target_copy(self):
        target = self.structured_rollout(
            self.target,
            [self.response("item-one", "same", ordinal=123)],
            history_mode="paginated",
        )
        self.structured_rollout(
            self.other,
            [self.response("item-one", "same", include_null_content=True)],
            history_mode="legacy",
        )
        identity = SYNC.file_identity(target)

        result = self.run_sync()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(identity, SYNC.file_identity(target))

    def test_independent_logical_branches_are_rejected(self):
        self.structured_rollout(
            self.target,
            [self.response("shared", "same"), self.response("left", "left branch")],
        )
        self.structured_rollout(
            self.other,
            [self.response("shared", "same"), self.response("right", "right branch")],
        )

        result = self.run_sync()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("divergent copies", result.stderr)

    def test_shared_record_payload_mismatch_is_rejected(self):
        self.structured_rollout(self.target, [self.response("shared", "left")])
        self.structured_rollout(self.other, [self.response("shared", "right")])

        result = self.run_sync()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("divergent copies", result.stderr)

    def test_symlink_source(self):
        source = self.rollout(self.shared)
        (self.other / "sessions").symlink_to(self.shared / "sessions", target_is_directory=True)
        self.assertEqual(self.run_sync().returncode, 0)
        self.assertEqual(source.read_bytes(), SYNC.find_rollout(self.target / "sessions", SESSION).read_bytes())

    def test_lineage_conflict_does_not_partially_import(self):
        self.rollout(self.shared, parent=PARENT)
        self.rollout(self.shared, session=PARENT, suffix="left\n")
        self.rollout(self.other, session=PARENT, suffix="right\n")
        self.assertIn("divergent copies", self.run_sync().stderr)
        self.assertIsNone(SYNC.find_rollout(self.target / "sessions", SESSION))

    def test_lineage_import(self):
        self.rollout(self.shared, parent=PARENT)
        self.rollout(self.shared, session=PARENT)
        self.assertEqual(self.run_sync().returncode, 0)
        self.assertIsNotNone(SYNC.find_rollout(self.target / "sessions", PARENT))

    def test_missing_parent_does_not_import_child(self):
        self.rollout(self.shared, parent=PARENT)
        self.assertIn("missing lineage", self.run_sync().stderr)
        self.assertIsNone(SYNC.find_rollout(self.target / "sessions", SESSION))

    def test_complete_local_parent_can_remain_locked(self):
        parent = self.rollout(self.target, session=PARENT, suffix='{"text":"old"}\n')
        boundary = parent.stat().st_size
        child = self.rollout(self.target, parent=PARENT, parent_end=boundary)
        self.rollout(self.other, session=PARENT, suffix='{"text":"old"}\n{"text":"unrelated tail"}\n')
        snapshots = {path: SYNC.file_identity(path) for path in (parent, child)}
        with SYNC.session_lock(self.locks, PARENT), SYNC.native_writer_lock(self.target, PARENT):
            result = self.run_sync()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("local_parent_prefix=", result.stderr)
        self.assertEqual(snapshots, {path: SYNC.file_identity(path) for path in snapshots})

    def test_incomplete_local_parent_still_requires_lock(self):
        for missing in (False, True):
            with self.subTest(missing=missing):
                parent = self.rollout(self.target, session=PARENT)
                self.rollout(self.shared, session=PARENT, suffix='{"text":"needed"}\n')
                child = self.rollout(self.target, parent=PARENT, parent_end=parent.stat().st_size + 18)
                if missing:
                    parent.unlink()
                original = child.read_bytes()
                with SYNC.session_lock(self.locks, PARENT):
                    result = self.run_sync()
                self.assertIn("already in use", result.stderr)
                self.assertEqual(child.read_bytes(), original)

    def test_imported_child_keeps_parent_migration_checks(self):
        parent = self.rollout(self.target, session=PARENT)
        self.rollout(self.shared, parent=PARENT, parent_end=parent.stat().st_size)
        with SYNC.session_lock(self.locks, PARENT):
            result = self.run_sync()
        self.assertIn("already in use", result.stderr)
        self.assertIsNone(SYNC.find_rollout(self.target / "sessions", SESSION))

    def test_legacy_parent_reference_still_requires_lock(self):
        self.rollout(self.target, session=PARENT)
        self.rollout(self.target, parent=PARENT)
        with SYNC.session_lock(self.locks, PARENT):
            self.assertIn("already in use", self.run_sync().stderr)

    def test_nested_local_parent_prefixes_can_remain_locked(self):
        ancestor_id = "33333333-3333-4333-8333-333333333333"
        ancestor = self.rollout(self.target, session=ancestor_id)
        parent = self.rollout(self.target, session=PARENT, parent=ancestor_id,
                              parent_end=ancestor.stat().st_size)
        self.rollout(self.target, parent=PARENT, parent_end=parent.stat().st_size)
        with SYNC.session_lock(self.locks, PARENT), SYNC.session_lock(self.locks, ancestor_id):
            result = self.run_sync()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr.count("local_parent_prefix="), 2)

    def test_parent_prefix_change_detection_allows_only_append(self):
        for change in ("append", "edit", "truncate", "replace"):
            with self.subTest(change=change):
                parent = self.rollout(self.target, session=PARENT, suffix='{"text":"old"}\n')
                self.rollout(self.target, parent=PARENT, parent_end=parent.stat().st_size)
                args = SimpleNamespace(session_id=SESSION, target_home=self.target,
                    source_homes=[self.shared], lock_home=self.locks, log_prefix="test")
                original_snapshot = SYNC.prefix_snapshot
                calls = 0

                def inspect_and_change(path, length):
                    nonlocal calls
                    snapshot = original_snapshot(path, length)
                    calls += 1
                    if calls == 1:
                        content = path.read_bytes()
                        if change == "append":
                            with path.open("ab") as handle:
                                handle.write(b'{"in_progress":')
                        elif change == "edit":
                            path.write_bytes(content.replace(b"old", b"new"))
                        elif change == "truncate":
                            path.write_bytes(content[:-1])
                        else:
                            replacement = self.root / "replacement"
                            replacement.write_bytes(content)
                            replacement.replace(path)
                    return snapshot

                with mock.patch.object(SYNC, "prefix_snapshot", side_effect=inspect_and_change):
                    if change == "append":
                        SYNC.synchronize(args)
                    else:
                        with self.assertRaises(SYNC.SyncError):
                            SYNC.synchronize(args)

    def test_parent_reference_must_end_on_record_boundary(self):
        parent = self.rollout(self.target, session=PARENT, suffix='{"text":"old"}\n')
        self.rollout(self.target, parent=PARENT, parent_end=parent.stat().st_size - 1)
        self.assertIn("not a record boundary", self.run_sync().stderr)

    def test_parent_metadata_id_must_match_reference(self):
        parent = self.rollout(self.target, session=PARENT)
        parent.write_text(parent.read_text().replace(PARENT, SESSION))
        self.rollout(self.target, parent=PARENT, parent_end=parent.stat().st_size)
        self.assertIn("metadata does not match", self.run_sync().stderr)

    def test_invalid_parent_bound_is_rejected(self):
        self.rollout(self.target, session=PARENT)
        for boundary in (True, -1, "100"):
            with self.subTest(boundary=boundary):
                self.rollout(self.target, parent=PARENT, parent_end=boundary)
                self.assertIn("invalid history_base.end_byte_offset", self.run_sync().stderr)

    def test_active_native_writer_rejected(self):
        self.rollout(self.shared)
        directory = self.other / "thread-writer-locks"
        directory.mkdir()
        with (directory / f"{SESSION}.lock").open("a+b") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            result = self.run_sync()
        self.assertIn("active native writer", result.stderr)
        self.assertIsNone(SYNC.find_rollout(self.target / "sessions", SESSION))

    def test_cross_account_lock_and_different_session_concurrency(self):
        self.rollout(self.shared)
        self.rollout(self.shared, session=PARENT)
        marker = self.root / "running"
        process = subprocess.Popen(self.command(execute=[sys.executable, "-c",
            f"from pathlib import Path; import time; Path({str(marker)!r}).touch(); time.sleep(20)"]),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(self.stop, process)
        self.wait_for(marker.exists)
        result = self.run_sync(target=self.other)
        self.assertIn("already in use", result.stderr)
        self.assertEqual(self.run_sync(target=self.other, session=PARENT).returncode, 0)
        with (self.shared / "thread-writer-locks" / f"{SESSION}.lock").open("a+b") as handle:
            with self.assertRaises(BlockingIOError):
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with (self.target / "thread-writer-locks" / f"{SESSION}.lock").open("a+b") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        process.terminate()
        process.communicate(timeout=5)
        self.assertEqual(process.returncode, 128 + signal.SIGTERM)
        self.assertEqual(self.run_sync(target=self.other).returncode, 0)

    def test_descendant_does_not_inherit_locks(self):
        self.rollout(self.shared)
        child_pid = self.root / "child.pid"
        program = ("import subprocess; from pathlib import Path; "
                   "child = subprocess.Popen(['sleep', '15'], close_fds=False, "
                   "stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); "
                   f"Path({str(child_pid)!r}).write_text(str(child.pid))")
        result = self.run_sync(execute=[sys.executable, "-c", program])
        self.assertEqual(result.returncode, 0, result.stderr)
        try:
            self.assertEqual(self.run_sync(target=self.other).returncode, 0)
        finally:
            os.kill(int(child_pid.read_text()), signal.SIGTERM)

    def test_fork_releases_source_lock_before_launch(self):
        self.rollout(self.shared)
        result = self.run_sync(action="fork", execute=self.command(target=self.other))
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_account_wrapper_preserves_arguments_and_exit_status(self):
        self.rollout(self.shared)
        environment = dict(self.environment, TEST_EXIT="7")
        result = subprocess.run([str(BIN / "codex-account"), "target", "exec", "resume",
            SESSION, "space separated prompt", "-c", 'model_provider="example_provider"'],
            env=environment, text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 7, result.stderr)
        launch = json.loads((self.root / "launched.json").read_text())
        self.assertEqual(launch["home"], str(self.target))
        self.assertIn("space separated prompt", launch["args"])
        self.assertIsNone(launch["wrapped"])

    def test_shared_resume_imports_newer_account_copy(self):
        self.rollout(self.shared, suffix="old\n")
        source = self.rollout(self.other, suffix="old\nnew\n")
        result = subprocess.run([str(BIN / "codex"), "resume", SESSION],
            env=self.environment, text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(source.read_bytes(), SYNC.find_rollout(self.shared / "sessions", SESSION).read_bytes())

    def test_explicit_home_is_preserved_and_synchronized(self):
        self.rollout(self.shared)
        environment = dict(self.environment, CODEX_HOME=str(self.target))
        result = subprocess.run([str(BIN / "codex"), "resume", SESSION],
            env=environment, text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads((self.root / "launched.json").read_text())["home"], str(self.target))

    def test_provider_routing_is_preserved(self):
        self.rollout(self.other)
        result = subprocess.run([str(BIN / "codex"), "resume", SESSION, "-c", 'model_provider="example_provider"'],
            env=self.environment, text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads((self.root / "launched.json").read_text())["home"], str(self.shared))

    def test_openai_missing_shared_imports_into_main_account(self):
        self.rollout(self.other)
        result = subprocess.run([str(BIN / "codex"), "resume", SESSION, "-c", 'model_provider="openai"'],
            env=self.environment, text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        launch = json.loads((self.root / "launched.json").read_text())
        self.assertEqual(launch["home"], str(self.shared))
        self.assertIn('model_provider="openai"', launch["args"])
        self.assertIsNotNone(SYNC.find_rollout(self.shared / "sessions", SESSION))
        self.assertEqual((self.shared / "auth.json").read_text(), "{}")

    def test_plain_resume_does_not_choose_source_account(self):
        self.rollout(self.other)
        (self.other / "auth.json").write_text('{"test_account": "other"}')
        result = subprocess.run([str(BIN / "codex"), "resume", SESSION],
            env=self.environment, text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        launch = json.loads((self.root / "launched.json").read_text())
        self.assertEqual(launch["home"], str(self.shared))
        self.assertNotIn("routed_account=", result.stderr)
        self.assertEqual((self.shared / "auth.json").read_text(), "{}")

    def test_session_picker_uses_main_home(self):
        result = subprocess.run([str(BIN / "codex"), "resume", "-c", 'model_provider="openai"'],
            env=self.environment, text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads((self.root / "launched.json").read_text())["home"], str(self.shared))

    def test_router_prefers_newest_codex_candidate(self):
        old_bin = self.root / "old-bin"
        new_bin = self.root / "new-bin"
        old_bin.mkdir()
        new_bin.mkdir()
        for directory, version in ((old_bin, "100.0.0"), (new_bin, "101.0.0")):
            executable = directory / "codex"
            executable.write_text(
                "#!/bin/sh\n"
                f"echo 'codex-cli {version}'\n"
            )
            executable.chmod(0o700)

        environment = dict(self.environment)
        environment.pop("CODEX_REAL_BIN")
        environment["PATH"] = os.pathsep.join(
            [str(old_bin), str(new_bin), "/usr/bin", "/bin"]
        )
        result = subprocess.run(
            [str(BIN / "codex"), "--version"],
            env=environment,
            text=True,
            capture_output=True,
            timeout=10,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "codex-cli 101.0.0")

    def start_daemon(self, home, acquire_writer=True, provider="openai", status="idle", ignore_override=False):
        program = """
import base64, fcntl, hashlib, json, socket, struct, sys
from pathlib import Path
home = Path(sys.argv[1])
provider, status, ignore_override = sys.argv[4:7]
directory = home / 'thread-writer-locks'
directory.mkdir(exist_ok=True)
if sys.argv[3] == 'True':
    handle = (directory / (sys.argv[2] + '.lock')).open('a+b')
    fcntl.flock(handle, fcntl.LOCK_EX)
endpoint = home / 'app-server-control/app-server-control.sock'
endpoint.parent.mkdir(exist_ok=True)
with socket.socket(socket.AF_UNIX) as listener:
    listener.bind(str(endpoint))
    listener.listen(8)
    print('ready', flush=True)
    while True:
        connection, address = listener.accept()
        with connection:
            def read_exactly(length):
                data = bytearray()
                while len(data) < length:
                    chunk = connection.recv(length - len(data))
                    if not chunk:
                        raise EOFError()
                    data.extend(chunk)
                return bytes(data)
            try:
                header = bytearray()
                while not header.endswith(b'\\r\\n\\r\\n'):
                    header.extend(read_exactly(1))
                key = next(line.split(b':',1)[1].strip() for line in header.split(b'\\r\\n')
                           if line.lower().startswith(b'sec-websocket-key:'))
                accept = base64.b64encode(hashlib.sha1(key + b'258EAFA5-E914-47DA-95CA-C5AB0DC85B11').digest())
                connection.sendall(b'HTTP/1.1 101 Switching Protocols\\r\\nUpgrade: websocket\\r\\n'
                                   b'Connection: Upgrade\\r\\nSec-WebSocket-Accept: ' + accept + b'\\r\\n\\r\\n')
                while True:
                    first, second = read_exactly(2)
                    length = second & 127
                    if length == 126:
                        length = struct.unpack('!H', read_exactly(2))[0]
                    elif length == 127:
                        length = struct.unpack('!Q', read_exactly(8))[0]
                    mask = read_exactly(4)
                    payload = read_exactly(length)
                    request = json.loads(bytes(value ^ mask[index % 4] for index, value in enumerate(payload)))
                    with (home / 'rpc.jsonl').open('a') as log:
                        log.write(json.dumps(request) + '\\n')
                    if 'id' not in request:
                        continue
                    result = {}
                    if request['method'] == 'thread/read':
                        result = {'thread':{'status':{'type':status},'modelProvider':'old_metadata'}}
                    if request['method'] == 'thread/resume':
                        if ignore_override != 'True':
                            provider = request['params'].get('modelProvider', provider)
                        result = {'modelProvider':provider, 'thread':{'status':{'type':status},'modelProvider':'old_metadata'}}
                    payload = json.dumps({'id':request['id'],'result':result}).encode()
                    prefix = b'\\x81' + (bytes([len(payload)]) if len(payload)<126 else b'\\x7e'+struct.pack('!H',len(payload)))
                    connection.sendall(prefix + payload)
            except (EOFError, ConnectionError):
                pass
"""
        process = subprocess.Popen(
            [sys.executable, "-u", "-c", program, str(home), SESSION, str(acquire_writer),
             provider, status, str(ignore_override), "app-server"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        self.addCleanup(self.stop, process)
        self.assertTrue(select.select([process.stdout], [], [], 5)[0])
        self.assertEqual(process.stdout.readline().strip(), "ready")
        return process

    def test_daemon_probe_requires_same_process_to_own_writer(self):
        daemon = self.start_daemon(self.target, acquire_writer=False)
        lock = self.target / "thread-writer-locks" / f"{SESSION}.lock"
        with lock.open("a+b") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            self.assertIsNone(SYNC.local_daemon_writer(self.target, SESSION))
        self.stop(daemon)

    def test_daemon_probe_matches_owner(self):
        daemon = self.start_daemon(self.target)
        owner, endpoint = SYNC.local_daemon_writer(self.target, SESSION)
        self.assertEqual(owner, daemon.pid)
        self.assertEqual(endpoint, self.target / "app-server-control/app-server-control.sock")

    def test_resume_command_detection(self):
        prefix = ["env", "CODEX_HOME=/tmp/example", "codex", "-c", 'model_provider="openai"']
        self.assertEqual(SYNC.interactive_resume_index(prefix + ["resume", SESSION]), len(prefix))
        self.assertIsNone(SYNC.interactive_resume_index(prefix + ["exec", "resume", SESSION]))
        self.assertIsNone(SYNC.interactive_resume_index(prefix + ["fork", SESSION]))
        self.assertIsNone(SYNC.interactive_resume_index(prefix + ["resume", SESSION, "--remote", "unix://"]))
        self.assertIsNone(SYNC.interactive_resume_index(prefix + ["resume", SESSION, "--remote=unix://"]))
        self.assertIsNone(SYNC.interactive_resume_index(["codex", "--", "resume", SESSION]))

    def test_shared_daemon_reattach_preserves_all_history(self):
        target = self.rollout(self.shared, suffix="running daemon branch\n")
        other = self.rollout(self.other, suffix="different archived branch\n")
        snapshots = {path: SYNC.file_identity(path) for path in (target, other)}
        daemon = self.start_daemon(self.shared)
        result = subprocess.run(
            [str(BIN / "codex"), "resume", SESSION, "-c", 'model_provider="openai"'],
            env=self.environment, text=True, capture_output=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"daemon_pid={daemon.pid}", result.stderr)
        launch = json.loads((self.root / "launched.json").read_text())
        self.assertEqual(launch["args"][:3], ["resume", "--remote",
            f"unix://{self.shared}/app-server-control/app-server-control.sock"])
        self.assertIn('model_provider="openai"', launch["args"])
        self.assertEqual(snapshots, {path: SYNC.file_identity(path) for path in snapshots})
        self.assertIsNotNone(SYNC.local_daemon_writer(self.shared, SESSION))

    def test_account_daemon_reattach(self):
        self.rollout(self.target)
        self.start_daemon(self.target)
        result = subprocess.run(
            [str(BIN / "codex-account"), "target", "resume", SESSION],
            env=self.environment, text=True, capture_output=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        launch = json.loads((self.root / "launched.json").read_text())
        self.assertEqual(launch["home"], str(self.target))
        self.assertIn(f"unix://{self.target}/app-server-control/app-server-control.sock", launch["args"])

    def test_daemon_does_not_bypass_another_wrapper(self):
        self.rollout(self.target)
        self.start_daemon(self.target)
        with SYNC.session_lock(self.locks, SESSION):
            result = self.run_sync(execute=[str(self.fake), "resume", SESSION])
        self.assertIn("already in use by another wrapper", result.stderr)

    def test_daemon_does_not_allow_exec_or_fork(self):
        self.rollout(self.target)
        self.start_daemon(self.target)
        for command, action in ((["exec", "resume"], "resume"), (["fork"], "fork")):
            with self.subTest(action=action):
                result = self.run_sync(action=action, execute=[str(self.fake), *command, SESSION])
                self.assertIn("active native writer", result.stderr)

    def test_other_home_daemon_prevents_migration(self):
        self.rollout(self.shared)
        self.start_daemon(self.shared)
        result = self.run_sync(execute=[str(self.fake), "resume", SESSION])
        self.assertIn("active native writer", result.stderr)
        self.assertIsNone(SYNC.find_rollout(self.target / "sessions", SESSION))

    def test_daemon_reattach_rejects_second_home_writer(self):
        self.rollout(self.target)
        self.start_daemon(self.target)
        with SYNC.native_writer_lock(self.other, SESSION):
            result = self.run_sync(execute=[str(self.fake), "resume", SESSION])
        self.assertIn("active native writer", result.stderr)

    def test_provider_override_parsing(self):
        command = ["env", "CODEX_HOME=/example", "codex", "-c", 'model_provider="openai"', "resume", SESSION]
        self.assertEqual(SYNC.requested_model_provider(command), "openai")
        self.assertEqual(SYNC.requested_model_provider(command + ["--config=model_provider='example_provider'"]), "example_provider")
        self.assertEqual(SYNC.requested_model_provider(command + ["-cmodel_provider=alternate_provider"]), "alternate_provider")
        self.assertIsNone(SYNC.requested_model_provider(["codex", "resume", SESSION, "--", "-cmodel_provider=openai"]))

    def test_idle_daemon_provider_switch_is_verified(self):
        self.rollout(self.shared, provider="example_provider")
        self.start_daemon(self.shared, provider="example_provider")
        result = subprocess.run(
            [str(BIN / "codex"), "resume", SESSION, "-c", 'model_provider="openai"'],
            env=self.environment, text=True, capture_output=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("verified_runtime_provider=openai", result.stderr)
        requests = [json.loads(line) for line in (self.shared / "rpc.jsonl").read_text().splitlines()]
        resumes = [request for request in requests if request["method"] == "thread/resume"]
        self.assertEqual(len(resumes), 2)
        self.assertEqual(resumes[0]["params"]["modelProvider"], "openai")
        self.assertNotIn("modelProvider", resumes[1]["params"])
        self.assertNotIn("turn/start", [request["method"] for request in requests])

    def test_ignored_provider_override_refuses_launch(self):
        self.rollout(self.shared, provider="example_provider")
        self.start_daemon(self.shared, provider="example_provider", ignore_override=True)
        result = subprocess.run(
            [str(BIN / "codex"), "resume", SESSION, "-c", 'model_provider="openai"'],
            env=self.environment, text=True, capture_output=True, timeout=10,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Refusing to launch with the wrong provider", result.stderr)
        self.assertFalse((self.root / "launched.json").exists())

    def test_active_turn_provider_change_refuses_launch(self):
        self.rollout(self.shared, provider="example_provider")
        self.start_daemon(self.shared, provider="example_provider", status="active")
        result = subprocess.run(
            [str(BIN / "codex"), "resume", SESSION, "-c", 'model_provider="openai"'],
            env=self.environment, text=True, capture_output=True, timeout=10,
        )
        self.assertIn("cannot change provider", result.stderr)
        self.assertFalse((self.root / "launched.json").exists())
        requests = [json.loads(line) for line in (self.shared / "rpc.jsonl").read_text().splitlines()]
        self.assertFalse(any("modelProvider" in request.get("params", {}) for request in requests))

    def test_daemon_transport_fragmentation_and_ping(self):
        connection, server = socket.socketpair()
        self.addCleanup(connection.close)
        self.addCleanup(server.close)
        client = SYNC.DaemonClient(Path("unused"), os.getpid())
        client.connection = connection
        client.deadline = time.monotonic() + 2
        server.sendall(b'\x01\x05{"id"' + b'\x89\x01x' + b'\x80\x03:1}')
        self.assertEqual(client.receive_message(), {"id": 1})
        pong = server.recv(32)
        self.assertEqual(pong[0], 0x8A)
        self.assertEqual(pong[1], 0x81)
        self.assertEqual(pong[-1] ^ pong[2], ord("x"))

    def test_verified_subscription_survives_tui_handoff(self):
        self.rollout(self.target)
        self.start_daemon(self.target)
        args = SimpleNamespace(
            session_id=SESSION, target_home=self.target, source_homes=[self.shared, self.other],
            lock_home=self.locks, session_action="resume", log_prefix="test",
            command=[str(self.fake), "resume", SESSION, "-c", 'model_provider="openai"'],
        )
        with mock.patch.object(SYNC, "DaemonClient") as factory:
            client = factory.return_value.__enter__.return_value
            client.request.return_value = {"modelProvider": "openai", "thread": {"status": {"type": "idle"}}}

            def launch(command):
                factory.return_value.__exit__.assert_not_called()
                self.assertIn("--remote", command)
                return 0

            with mock.patch.object(SYNC, "run_command", side_effect=launch) as runner:
                self.assertEqual(SYNC.synchronize_and_run(args), 0)
                runner.assert_called_once()
            factory.return_value.__exit__.assert_called_once()
            requests = client.request.call_args_list
            self.assertEqual(requests[0].args[0], "thread/read")
            self.assertEqual(requests[1].args[1]["modelProvider"], "openai")

    def test_provider_verification_exception_closes_subscription(self):
        with mock.patch.object(SYNC, "DaemonClient") as factory:
            client = factory.return_value.__enter__.return_value
            client.request.return_value = {"modelProvider": "example_provider", "thread": {"status": {"type": "idle"}}}
            with self.assertRaisesRegex(SYNC.SyncError, "Refusing to launch"):
                with SYNC.ensure_daemon_provider(Path("unused"), 1, SESSION, "openai"):
                    self.fail("must not yield on provider mismatch")
            factory.return_value.__exit__.assert_called_once()

    def test_daemon_transport_rejects_oversized_response(self):
        connection, server = socket.socketpair()
        self.addCleanup(connection.close)
        self.addCleanup(server.close)
        client = SYNC.DaemonClient(Path("unused"), os.getpid())
        client.connection = connection
        client.deadline = time.monotonic() + 2
        server.sendall(b'\x81\x7f' + struct.pack('!Q', SYNC.MAX_DAEMON_MESSAGE + 1))
        with self.assertRaisesRegex(SYNC.SyncError, "exceeds size limit"):
            client.receive_message()


if __name__ == "__main__":
    unittest.main()
