"""The working mode: what it adds, and what it must never change.

A work session is an explicit alternative to the restricted review call. It
is created by naming a mode, it records its directories, its connector gets a
separate ordinary-permission work vector, and its records carry the caller's
inert metadata. These checks cover the finite list of behaviors that makes
that true without reproducing the whole original suite: legacy versus
explicit creation, the immutable Format 3 fields and request/reply pairing,
exact bodies and inert metadata, readiness certainty and honestly unsupported
routes, heartbeat and final-event ordering, separate code and document
directories, real image bytes reaching a tool, the ordinary-permission work
vectors of the four connectors that have them, and a failed or stopped call
retaining its records without inventing success.

The work-mode readiness checks are qualified here against each connector's
real source: a work check proves the work vector's own switches and never the
review-only switches, gates nothing on the review call's policy facts, and
for a target with no work vector performs no switch qualification at all.

Two platform twins are exercised here too, both simulated, because no Windows
machine is part of this repository's qualification: the `msvcrt.locking` twin
of the session lock, and the taskkill and kill-on-close job twins of
process-group cleanup, each driven through its Windows branch with the
platform's own primitive stood in for - including the parent-exits-first case
where the tree walk has no root to walk from and the job is the only owner
left standing. Event lines and the terminal response-path line being flushed
as they are written is checked as well, because a caller watching a pipe sees
nothing until a flush.

The lifecycle fixtures are the repository's own fake peer; no real target is
called here.

SPDX-License-Identifier: CC0-1.0
"""

from __future__ import annotations

import ctypes
import hashlib
import io
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from bridge import (  # noqa: E402
    claude,
    cli,
    codex,
    connectors,
    hermes,
    locking,
    minimax,
    peer,
    qwen,
    record,
    runner,
    session,
    zcode,
)
from bridge.connectors import PeerCommand  # noqa: E402
from bridge.errors import BridgeError, Failure  # noqa: E402
from bridge.peer import CompletedCall  # noqa: E402
from tests.test_fake_peer import FAKE_PEER  # noqa: E402

#: How the fake peer reports the two processes a cleanup has to end.
PID_LINE = re.compile(r"^(PEER|CHILD) (\d+)$", re.MULTILINE)


def _wait_until_gone(pid, timeout=10.0):
    """Whether one process ended within the wait, asked of the pid itself."""
    limit = time.monotonic() + timeout
    while time.monotonic() < limit:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        time.sleep(0.02)
    return False


def _await_reported_pids(pid_path, timeout=10.0):
    """Both process ids the fixture writes, waited for rather than guessed."""
    limit = time.monotonic() + timeout
    while time.monotonic() < limit:
        if os.path.exists(pid_path):
            with open(pid_path, encoding="utf-8") as stream:
                found = dict(
                    (kind, int(number))
                    for kind, number in PID_LINE.findall(stream.read())
                )
            if len(found) == 2:
                return found
        time.sleep(0.05)
    raise AssertionError("the fixture never reported both process ids")


#: A `run_bounded` caller on the simulated Windows branch, in a process of
#: its own so a check can signal the thing doing the waiting rather than the
#: check itself. It patches the platform switch and stands in for taskkill
#: with a function that force-terminates the same tree the real command's
#: /T walk would reach, and for the kill-on-close job with a release that
#: terminates the same members the kernel's close would, is stopped from
#: outside while it waits, and exits 3 when it leaves as the stop it was.
#: Its arguments are the fake peer's mode and the file the fixture writes its
#: process ids into.
WINDOWS_SIGNAL_DRIVER = (
    "import os, signal, sys\n"
    "sys.path.insert(0, sys.argv[1])\n"
    "from bridge import peer\n"
    "pid_file = sys.argv[4]\n"
    "def tree_pids(pgid):\n"
    "    pids = [pgid]\n"
    "    with open(pid_file, encoding='utf-8') as stream:\n"
    "        for line in stream:\n"
    "            parts = line.split()\n"
    "            if len(parts) == 2 and parts[0] == 'CHILD':\n"
    "                pids.append(int(parts[1]))\n"
    "    return pids\n"
    "def terminate(pids):\n"
    "    found = False\n"
    "    for pid in pids:\n"
    "        try:\n"
    "            os.kill(pid, signal.SIGKILL)\n"
    "            found = True\n"
    "        except ProcessLookupError:\n"
    "            pass\n"
    "    return found\n"
    "def taskkill(pgid):\n"
    "    return not terminate(tree_pids(pgid))\n"
    "def own_tree(process):\n"
    "    return ('job', process.pid)\n"
    "def release(job):\n"
    "    terminate(tree_pids(job[1]))\n"
    "peer.WINDOWS = True\n"
    "peer.CLEANUP_GRACE_SECONDS = 0.2\n"
    "peer.ESCALATION_GRACE_SECONDS = 0.5\n"
    "peer._windows_taskkill = taskkill\n"
    "peer._windows_own_tree = own_tree\n"
    "peer._windows_release_job = release\n"
    "try:\n"
    "    peer.run_bounded(\n"
    "        argv=(sys.executable, sys.argv[2], sys.argv[3], sys.argv[4]),\n"
    "        cwd=sys.argv[1],\n"
    "        env=tuple(os.environ.items()),\n"
    "        stdin_text='Start something and then stop answering.\\n',\n"
    "        deadline=peer.Deadline(60.0),\n"
    "    )\n"
    "except (peer.SignalStop, KeyboardInterrupt):\n"
    "    sys.exit(3)\n"
)


class WorkModeRecords(unittest.TestCase):
    """Legacy creation, explicit creation, and the strict Format 3 reader."""

    def setUp(self):
        self.temp = tempfile.mkdtemp(prefix="agent-bridge-work-records-")

    def tearDown(self):
        shutil.rmtree(self.temp, ignore_errors=True)

    def _read(self, path):
        with open(path, encoding="utf-8") as stream:
            return stream.read()

    def test_legacy_creation_writes_format_2_and_explicit_mode_writes_format_3(self):
        legacy = os.path.join(self.temp, "legacy")
        record.record(
            legacy,
            "session-create",
            "A legacy courier conversation.\n",
            initiator="gear-3",
            peer="claude",
            project=self.temp,
        )
        self.assertEqual(
            self._read(session.session_file(legacy)),
            "# Session\n\nBridge-Format: 2\nInitiator: gear-3\nPeer: claude\n"
            "Project: {0}\n\n## Body\n\n"
            "A legacy courier conversation.\n".format(self.temp),
        )
        legacy_record = session.read_session(legacy)
        self.assertEqual(legacy_record.bridge_format, "2")
        self.assertEqual(legacy_record.mode, "review")
        self.assertEqual(legacy_record.access_paths, ())

        code = os.path.join(self.temp, "code")
        os.mkdir(code)
        for index, mode in enumerate(("review", "work")):
            explicit = os.path.join(self.temp, "explicit-{0}".format(index))
            record.record(
                explicit,
                "session-create",
                "An explicit {0} session.\n".format(mode),
                initiator="vibe-coder",
                peer="codex",
                mode=mode,
            )
            text = self._read(session.session_file(explicit))
            self.assertIn("Bridge-Format: 3\n", text)
            self.assertIn("Mode: {0}\n".format(mode), text)
            parsed = session.read_session(explicit)
            self.assertEqual(parsed.bridge_format, "3")
            self.assertEqual(parsed.mode, mode)
            self.assertIsNone(parsed.project)

        # A work session may also name a project and access directories, and
        # an access path without an explicit mode is refused before anything
        # is written.
        docs = os.path.join(self.temp, "docs")
        os.mkdir(docs)
        working = os.path.join(self.temp, "working")
        record.record(
            working,
            "session-create",
            "Code here, documents there.\n",
            initiator="vibe-coder",
            peer="codex",
            project=code,
            mode="work",
            access_paths=[docs],
        )
        parsed = session.read_session(working)
        self.assertEqual(parsed.project, code)
        self.assertEqual(parsed.access_paths, (docs,))

        refused = os.path.join(self.temp, "refused")
        with self.assertRaises(BridgeError) as caught:
            record.record(
                refused,
                "session-create",
                "No mode, no access paths.\n",
                initiator="vibe-coder",
                peer="codex",
                access_paths=[docs],
            )
        self.assertEqual(caught.exception.failure, Failure.USAGE_ERROR)
        self.assertFalse(os.path.exists(session.session_file(refused)))

        # A neutral note still works on a Format 3 session.
        note = record.record(working, "note", "Paired user answer.\n")
        self.assertTrue(note.endswith("0001-initiator-record.md"))

    def test_the_format_3_reader_is_strict_about_its_own_fields(self):
        variants = {
            "format 2 with a mode": (
                "# Session\n\nBridge-Format: 2\nInitiator: app\nPeer: claude\n"
                "Mode: work\n\n## Body\n\nMixed.\n"
            ),
            "format 3 without a mode": (
                "# Session\n\nBridge-Format: 3\nInitiator: app\nPeer: claude\n"
                "\n## Body\n\nModeless.\n"
            ),
            "format 3 with a bad mode": (
                "# Session\n\nBridge-Format: 3\nInitiator: app\nPeer: claude\n"
                "Mode: yolo\n\n## Body\n\nBad mode.\n"
            ),
            "format 2 with an access path": (
                "# Session\n\nBridge-Format: 2\nInitiator: app\nPeer: claude\n"
                "Access-Path: /tmp\n\n## Body\n\nMixed.\n"
            ),
            "repeated access path": (
                "# Session\n\nBridge-Format: 3\nInitiator: app\nPeer: claude\n"
                "Mode: work\nAccess-Path: /tmp\nAccess-Path: /tmp\n\n"
                "## Body\n\nRepeated.\n"
            ),
            "unknown field": (
                "# Session\n\nBridge-Format: 3\nInitiator: app\nPeer: claude\n"
                "Mode: work\nStatus: ready\n\n## Body\n\nUnknown.\n"
            ),
        }
        for index, (name, text) in enumerate(variants.items()):
            with self.subTest(case=name):
                directory = os.path.join(self.temp, "invalid-{0}".format(index))
                os.makedirs(session.messages_dir(directory))
                with open(
                    session.session_file(directory), "w", encoding="utf-8"
                ) as stream:
                    stream.write(text)
                with self.assertRaises(BridgeError) as caught:
                    session.read_session(directory)
                self.assertEqual(caught.exception.failure, Failure.SESSION_INVALID)


class WorkTurnBehavior(unittest.TestCase):
    """One work session, the fake peer, and the extended records."""

    def setUp(self):
        self.temp = tempfile.mkdtemp(prefix="agent-bridge-work-turn-")
        self.session_dir = os.path.join(self.temp, "session")
        self.code = os.path.join(self.temp, "code")
        self.docs = os.path.join(self.temp, "docs")
        os.mkdir(self.code)
        os.mkdir(self.docs)
        with open(os.path.join(self.code, "evidence.md"), "w") as stream:
            stream.write("PROJECT_READ_CANARY=work-canary\n")
        record.record(
            self.session_dir,
            "session-create",
            "Work session.\n",
            initiator="vibe-coder",
            peer="codex",
            project=self.code,
            mode="work",
            access_paths=[self.docs],
        )

    def tearDown(self):
        shutil.rmtree(self.temp, ignore_errors=True)

    def _builder(self, mode, *extra):
        argv = (sys.executable, FAKE_PEER, mode) + tuple(extra)

        def build(deadline, cwd, **kwargs):
            return PeerCommand(argv=argv, cwd=cwd, env=tuple(os.environ.items()))

        return build

    def _run(self, body="Do the work.\n", **kwargs):
        kwargs.setdefault("build_work_command", self._builder("plain"))
        return runner.run_turn(self.session_dir, body, 30.0, **kwargs)

    def test_the_work_round_trip_pairs_request_and_response_records(self):
        body = "Unicode caf\u00e9 \U0001f680 body.\n"
        result = self._run(
            body=body, note_ref="note-42", purpose="second-draft"
        )

        request = self._read(result_path(self.session_dir, 1))
        self.assertEqual(
            request,
            "# Message 0001\nFrom: vibe-coder\nTo: codex\n"
            "Note-Ref: note-42\nPurpose: second-draft\n\n## Body\n\n" + body,
        )
        response = self._read(result.response_path)
        self.assertEqual(
            response,
            "# Message 0002\nFrom: codex\nTo: vibe-coder\nAnswers: 0001\n\n"
            "## Body\n\n" + body,
        )

        # The metadata is inert: a body carrying header-shaped text keeps it
        # as body text, and the real header appears exactly once.
        shaped = "Note-Ref: forged\nPurpose: nope\nStill body text.\n"
        result = self._run(body=shaped, note_ref="real-ref")
        request = self._read(result_path(self.session_dir, 3))
        header, _, body_text = request.partition("\n## Body\n\n")
        self.assertEqual(header.count("Note-Ref:"), 1)
        self.assertIn("Note-Ref: real-ref\n", header)
        self.assertEqual(body_text, shaped)

    def test_extended_run_options_stay_off_format_2_sessions(self):
        legacy = os.path.join(self.temp, "legacy")
        record.record(
            legacy, "session-create", "Legacy.\n", initiator="gear-3", peer="claude"
        )
        image = os.path.join(self.temp, "pixel.png")
        with open(image, "wb") as stream:
            stream.write(b"\x89PNG\r\n\x1a\n")
        for kwargs in (
            {"note_ref": "n"},
            {"purpose": "p"},
            {"attachments": (image,)},
        ):
            with self.subTest(options=sorted(kwargs)):
                with self.assertRaises(BridgeError) as caught:
                    runner.run_turn(
                        legacy, "Body.\n", 30.0, self._builder("plain"), **kwargs
                    )
                self.assertEqual(caught.exception.failure, Failure.USAGE_ERROR)
        self.assertEqual(os.listdir(session.messages_dir(legacy)), [])

        # On a Format 3 review session the inert metadata is welcome, but an
        # attachment still needs a work session.
        review = os.path.join(self.temp, "review")
        record.record(
            review,
            "session-create",
            "Explicit review.\n",
            initiator="gear-3",
            peer="claude",
            mode="review",
        )
        runner.run_turn(
            review,
            "Review body.\n",
            30.0,
            self._builder("plain"),
            note_ref="note-7",
            purpose="gear-3-check",
        )
        request = self._read(result_path(review, 1))
        self.assertIn("Note-Ref: note-7\nPurpose: gear-3-check\n", request)
        with self.assertRaises(BridgeError) as caught:
            runner.run_turn(
                review, "Review body.\n", 30.0, self._builder("plain"),
                attachments=(image,),
            )
        self.assertEqual(caught.exception.failure, Failure.USAGE_ERROR)
        with self.assertRaises(BridgeError) as caught:
            runner.run_turn(
                self.session_dir,
                "Work body.\n",
                30.0,
                build_work_command=self._builder("plain"),
                attachments=(os.path.join(self.temp, "missing.png"),),
            )
        self.assertEqual(caught.exception.failure, Failure.USAGE_ERROR)
        self.assertEqual(
            os.listdir(session.messages_dir(self.session_dir)), []
        )

    def test_the_work_builder_receives_the_code_and_document_directories(self):
        observed = {}

        def build(deadline, cwd, access_paths=(), attachments=(), **kwargs):
            observed["cwd"] = cwd
            observed["access_paths"] = access_paths
            script = (
                "import os, sys\n"
                "target = os.path.join(sys.argv[2], 'authorized.md')\n"
                "with open(target, 'w', encoding='utf-8') as stream:\n"
                "    stream.write(sys.argv[1])\n"
                "sys.stdout.write(sys.argv[1])\n"
            )
            return PeerCommand(
                argv=(sys.executable, "-c", script, "WORK_DOC: done", self.docs),
                cwd=cwd,
                env=tuple(os.environ.items()),
            )

        result = runner.run_turn(
            self.session_dir, "Edit the authorized document.\n", 30.0,
            build_work_command=build,
        )
        self.assertEqual(observed["cwd"], self.code)
        self.assertEqual(observed["access_paths"], (self.docs,))
        self.assertTrue(
            os.path.isfile(os.path.join(self.docs, "authorized.md"))
        )
        self.assertEqual(os.listdir(self.code), ["evidence.md"])
        self.assertIn("Answers: 0001", self._read(result.response_path))

    def test_actual_image_bytes_reach_the_tool(self):
        payload = bytes(bytearray((red % 251 for red in range(1024))))
        image = os.path.join(self.temp, "distinctive.bin")
        with open(image, "wb") as stream:
            stream.write(payload)
        observed = {}

        def build(deadline, cwd, access_paths=(), attachments=(), **kwargs):
            observed["attachments"] = attachments
            script = (
                "import hashlib, sys\n"
                "with open(sys.argv[1], 'rb') as stream:\n"
                "    data = stream.read()\n"
                "sys.stdout.write('SHA256 ' + hashlib.sha256(data).hexdigest())\n"
            )
            argv = [sys.executable, "-c", script]
            argv.extend(attachments)
            return PeerCommand(
                argv=tuple(argv), cwd=cwd, env=tuple(os.environ.items())
            )

        result = runner.run_turn(
            self.session_dir, "Hash the attachment.\n", 30.0,
            build_work_command=build, attachments=(image,),
        )
        self.assertEqual(observed["attachments"], (image,))
        request = self._read(result_path(self.session_dir, 1))
        self.assertIn("Attachment: {0}\n".format(image), request)
        response = self._read(result.response_path)
        self.assertIn(
            "SHA256 {0}".format(hashlib.sha256(payload).hexdigest()),
            response,
        )

    def test_lifecycle_events_order_heartbeats_before_one_final_result(self):
        events = []
        with mock.patch.object(peer, "HEARTBEAT_SECONDS", 0.05):
            result = runner.run_turn(
                self.session_dir,
                "Answer after a short wait.\n",
                30.0,
                build_work_command=self._builder("delay-echo", "0.35"),
                event_writer=events.append,
            )
        parsed = [json.loads(line) for line in events]
        kinds = [event["event"] for event in parsed]
        self.assertEqual(kinds[0], "started")
        self.assertEqual(kinds[-1], "finished")
        self.assertEqual(kinds.count("finished"), 1)
        self.assertIn("heartbeat", kinds)
        first_heartbeat = kinds.index("heartbeat")
        self.assertLess(first_heartbeat, kinds.index("finished"))
        self.assertTrue(
            all(
                event["phase"] == "peer-call"
                for event in parsed
                if event["event"] == "heartbeat"
            )
        )
        finished = parsed[-1]
        self.assertEqual(finished["outcome"], "success")
        self.assertEqual(finished["response_path"], result.response_path)
        self.assertTrue(finished["request_path"].endswith("0001-initiator-to-peer.md"))

        # A timed-out work call reports failure, keeps its request, and never
        # reports success.
        events = []
        with self.assertRaises(BridgeError) as caught:
            runner.run_turn(
                self.session_dir,
                "Never answer in time.\n",
                0.6,
                build_work_command=self._builder("hang"),
                event_writer=events.append,
            )
        self.assertEqual(caught.exception.failure, Failure.TIMEOUT)
        parsed = [json.loads(line) for line in events]
        finished = parsed[-1]
        self.assertEqual(finished["outcome"], "failure")
        self.assertNotIn("response_path", finished)
        self.assertTrue(finished["request_path"].endswith("0003-initiator-to-peer.md"))
        self.assertEqual(
            sorted(os.listdir(session.messages_dir(self.session_dir))),
            ["0001-initiator-to-peer.md", "0002-peer-to-initiator.md",
             "0003-initiator-to-peer.md"],
        )

    def test_a_failed_work_call_keeps_its_records_without_false_success(self):
        class FailingWorkConnector:
            CAPABILITIES = connectors.Capabilities(
                work="supported",
                work_detail="fake",
                image="supported",
                image_detail="fake",
            )

            @staticmethod
            def build_work_command(
                deadline, cwd, access_paths=(), attachments=(), **kwargs
            ):
                return PeerCommand(
                    argv=(sys.executable, FAKE_PEER, "fail"),
                    cwd=cwd,
                    env=tuple(os.environ.items()),
                )

        stderr = io.StringIO()
        output = io.StringIO()
        with mock.patch.object(
            runner.connectors, "resolve", return_value=FailingWorkConnector
        ):
            with mock.patch("sys.stderr", stderr), mock.patch("sys.stdout", output):
                with mock.patch("sys.stdin", io.StringIO("Please fail.\n")):
                    status = cli.main(
                        [
                            "run",
                            "--session",
                            self.session_dir,
                            "--events-jsonl",
                            "--note-ref",
                            "note-9",
                        ]
                    )
        self.assertEqual(status, 1)
        self.assertIn("deliberate failure", stderr.getvalue())
        parsed = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(
            [event["event"] for event in parsed], ["started", "finished"]
        )
        self.assertEqual(parsed[-1]["outcome"], "failure")
        self.assertTrue(
            parsed[-1]["request_path"].endswith("0001-initiator-to-peer.md")
        )
        self.assertIn(
            "peer harness's program exited with a failure", parsed[-1]["reason"]
        )
        self.assertEqual(
            os.listdir(session.messages_dir(self.session_dir)),
            ["0001-initiator-to-peer.md"],
        )

        # A broken event pipe can mask the reports, never the truth: the call
        # fails, the request stays, and no success exists anywhere.
        def broken_writer(line):
            raise OSError("broken pipe")

        with mock.patch.object(
            runner.connectors, "resolve", return_value=FailingWorkConnector
        ):
            with self.assertRaises(BridgeError) as caught:
                runner.run_turn(
                    self.session_dir,
                    "Fail again.\n",
                    30.0,
                    event_writer=broken_writer,
                )
        self.assertEqual(caught.exception.failure, Failure.PEER_FAILURE)
        self.assertEqual(
            sorted(os.listdir(session.messages_dir(self.session_dir))),
            ["0001-initiator-to-peer.md", "0002-initiator-to-peer.md"],
        )

    def test_event_lines_and_the_response_path_line_are_flushed_as_written(self):
        """A caller watching a pipe sees nothing until a flush.

        Python buffers standard output when it is a pipe, so an unflushed
        event line would sit in the buffer until the process ended - which
        for a long turn is the whole turn. Every lifecycle event, and the
        one response-path line a flag-free run prints, must be pushed out at
        the moment it is written.
        """

        class _CountingFlush(io.StringIO):
            def __init__(self):
                super().__init__()
                self.flushes = 0

            def flush(self):
                self.flushes += 1
                return super().flush()

        class _EchoWorkConnector:
            CAPABILITIES = connectors.Capabilities(
                work="supported",
                work_detail="fake",
                image="supported",
                image_detail="fake",
            )

            @staticmethod
            def build_work_command(
                deadline, cwd, access_paths=(), attachments=(), **kwargs
            ):
                return PeerCommand(
                    argv=(sys.executable, FAKE_PEER, "plain"),
                    cwd=cwd,
                    env=tuple(os.environ.items()),
                )

        with mock.patch.object(
            runner.connectors, "resolve", return_value=_EchoWorkConnector
        ):
            events = _CountingFlush()
            with mock.patch("sys.stdout", events), mock.patch(
                "sys.stdin", io.StringIO("Answer me.\n")
            ):
                status = cli.main(
                    ["run", "--session", self.session_dir, "--events-jsonl"]
                )
            self.assertEqual(status, 0)
            kinds = [
                json.loads(line)["event"]
                for line in events.getvalue().splitlines()
            ]
            self.assertEqual(kinds, ["started", "finished"])
            self.assertEqual(
                events.flushes,
                len(kinds),
                "each event line must be flushed as it is written",
            )

            plain = _CountingFlush()
            with mock.patch("sys.stdout", plain), mock.patch(
                "sys.stdin", io.StringIO("Answer again.\n")
            ):
                status = cli.main(["run", "--session", self.session_dir])
            self.assertEqual(status, 0)
            self.assertTrue(
                plain.getvalue().strip().endswith("0004-peer-to-initiator.md")
            )
            self.assertEqual(plain.flushes, 1)

    def _read(self, path):
        with open(path, encoding="utf-8") as stream:
            return stream.read()


def result_path(session_dir, sequence):
    return session.message_path(
        session_dir, sequence, session.INITIATOR_TO_PEER_SUFFIX
    )


class ReadinessAndSupport(unittest.TestCase):
    """The JSON readiness result and honestly unsupported work routes."""

    def setUp(self):
        self.temp = tempfile.mkdtemp(prefix="agent-bridge-work-readiness-")

    def tearDown(self):
        shutil.rmtree(self.temp, ignore_errors=True)

    def _check_json(self, peer, mode, connector):
        output = io.StringIO()
        with mock.patch.object(connectors, "resolve", return_value=connector):
            with mock.patch("sys.stdout", output):
                status = cli.main(
                    ["check", "--peer", peer, "--mode", mode, "--json"]
                )
        return status, json.loads(output.getvalue())

    def test_json_readiness_reports_facts_and_capability_states(self):
        class UnknownAuthConnector:
            CAPABILITIES = connectors.Capabilities(
                work="supported",
                work_detail="route: work vector",
                image="unknown",
                image_detail="no evidence either way",
            )

            @staticmethod
            def check(deadline, cwd, mode="review"):
                return connectors.CheckResult(
                    "unconfirmed",
                    ("one warning",),
                    executable="/fake/peer",
                    version="9.9.9",
                    platform="Darwin 26 arm64",
                    authentication_confirmed=False,
                )

        status, result = self._check_json(
            "codex", "work", UnknownAuthConnector
        )
        self.assertEqual(status, 0)
        self.assertEqual(
            result,
            {
                "peer": "codex",
                "mode": "work",
                "ready": True,
                "executable": "/fake/peer",
                "version": "9.9.9",
                "platform": "Darwin 26 arm64",
                "authentication": "unknown",
                "work": "supported",
                "image": "unknown",
                "warnings": ["one warning"],
            },
        )

        class ConfirmedConnector(UnknownAuthConnector):
            @staticmethod
            def check(deadline, cwd, mode="review"):
                return connectors.CheckResult(
                    "confirmed",
                    (),
                    executable="/fake/peer",
                    version="9.9.9",
                    platform="Darwin 26 arm64",
                    authentication_confirmed=True,
                )

        _status, result = self._check_json("codex", "review", ConfirmedConnector)
        self.assertEqual(result["authentication"], "confirmed")
        self.assertEqual(result["mode"], "review")

        class UnauthenticatedConnector:
            CAPABILITIES = UnknownAuthConnector.CAPABILITIES

            @staticmethod
            def check(deadline, cwd, mode="review"):
                raise BridgeError(
                    Failure.AUTHENTICATION_REQUIRED, detail="login status exited 1"
                )

        status, result = self._check_json("codex", "work", UnauthenticatedConnector)
        self.assertEqual(status, 1)
        self.assertEqual(result["ready"], False)
        self.assertEqual(result["authentication"], "required")
        self.assertIn("login status exited 1", result["reason"])
        self.assertTrue(result["next_action"])

    def test_unsupported_work_routes_are_refused_with_the_real_reason(self):
        for connector, peer_id in ((hermes, "hermes"), (qwen, "qwen")):
            with self.subTest(peer=peer_id):
                self.assertEqual(connector.CAPABILITIES.work, "unsupported")
                self.assertIn("terminal", connector.CAPABILITIES.work_detail)
                session_dir = os.path.join(self.temp, peer_id)
                record.record(
                    session_dir,
                    "session-create",
                    "A work session this target cannot serve.\n",
                    initiator="vibe-coder",
                    peer=peer_id,
                    mode="work",
                )
                captured = io.StringIO()
                with mock.patch.object(
                    runner.connectors,
                    "resolve",
                    return_value=connector,
                ):
                    with mock.patch("sys.stderr", captured), mock.patch(
                        "sys.stdin", io.StringIO("Please work.\n")
                    ):
                        status = cli.main(["run", "--session", session_dir])
                self.assertEqual(status, 1)
                self.assertIn("work mode is unsupported", captured.getvalue())
                self.assertIn("terminal", captured.getvalue())
                self.assertEqual(
                    os.listdir(session.messages_dir(session_dir)), []
                )


class OrdinaryPermissionWorkVectors(unittest.TestCase):
    """The four work vectors, composed against their real connector source."""

    def setUp(self):
        self.temp = tempfile.mkdtemp(prefix="agent-bridge-work-vectors-")
        # A hermetic codex home, so the posture the work builder resolves is
        # the fixture's and never this machine's real configuration.
        self.codex_home = os.path.join(self.temp, "codex-home")
        os.makedirs(self.codex_home)

    def tearDown(self):
        shutil.rmtree(self.temp, ignore_errors=True)

    def _codex_config(self, text=None):
        """Write an optional fixture config and patch CODEX_HOME to it."""
        if text is not None:
            with open(
                os.path.join(self.codex_home, "config.toml"),
                "w",
                encoding="utf-8",
            ) as stream:
                stream.write(text)
        return mock.patch.dict(os.environ, {"CODEX_HOME": self.codex_home})

    def test_codex_work_preserves_the_configured_sandbox_posture(self):
        prerequisite = (
            "/fake/codex",
            "0.147.0",
            "Darwin 26 arm64",
            (codex._work_warning("workspace-write", "fixture"),),
        )
        with self._codex_config('sandbox_mode = "workspace-write"\n'):
            with mock.patch.object(
                codex, "_prerequisites", return_value=prerequisite
            ):
                command = codex.build_work_command(
                    peer.Deadline(60.0),
                    self.temp,
                    access_paths=("/access/one",),
                    attachments=("/img/a.png", "/img/b.png"),
                )
        self.assertEqual(
            command.argv,
            (
                "/fake/codex",
                "exec",
                "--skip-git-repo-check",
                "--cd",
                self.temp,
                "--add-dir",
                "/access/one",
                "--image",
                "/img/a.png",
                "--image",
                "/img/b.png",
                "-",
            ),
        )
        self.assertIsNone(command.body_argument)
        joined = " ".join(command.argv)
        self.assertNotIn("--ignore-user-config", joined)
        self.assertNotIn("--disable", joined)
        self.assertNotIn("--sandbox", joined)
        warning = " ".join(command.warnings)
        self.assertIn("sandbox switch is passed", warning)
        self.assertIn("workspace-write", warning)

    def test_codex_work_proceeds_with_a_warning_under_an_apparent_read_only_posture(self):
        """A partial posture reading never rejects a configured work route.

        Both origins of an apparent read-only posture - the user's own
        configuration naming read-only, and codex's out-of-box default when
        nothing configures a wider sandbox - proceed the same way: no
        sandbox switch, a warning that names the posture as apparent rather
        than effective, and codex's own run-time enforcement left to govern,
        because layers this connector does not read can make the effective
        posture writable. A call the enforced posture cannot serve fails
        inside codex with codex's own error, which the runner surfaces with
        its reason and next action after the request is published.
        """
        postures = {
            "configured read-only": 'sandbox_mode = "read-only"\n',
            "codex default read-only": "# no sandbox_mode configured\n",
        }
        for name, config in postures.items():
            with self.subTest(origin=name):
                with self._codex_config(config):
                    apparent, origin = codex._apparent_sandbox()
                    self.assertEqual(apparent, "read-only")
                    self.assertTrue(origin)
                    prerequisite = (
                        "/fake/codex",
                        "0.147.0",
                        "Darwin 26 arm64",
                        (codex._work_warning(apparent, origin),),
                    )
                    with mock.patch.object(
                        codex, "_prerequisites", return_value=prerequisite
                    ):
                        command = codex.build_work_command(
                            peer.Deadline(60.0), self.temp
                        )
                self.assertEqual(
                    command.argv,
                    (
                        "/fake/codex",
                        "exec",
                        "--skip-git-repo-check",
                        "--cd",
                        self.temp,
                        "-",
                    ),
                )
                self.assertNotIn("--sandbox", command.argv)
                warning = " ".join(command.warnings)
                self.assertIn("apparent posture", warning)
                self.assertIn("read-only", warning)
                self.assertIn(
                    "codex itself resolves and enforces", warning
                )
                self.assertIn("trusted project", warning)
                self.assertIn("managed_config.toml", warning)
                self.assertIn("fails inside codex", warning)

        # The same posture through a real work session: the call is not
        # refused before publication. It runs under no posture flag, and a
        # genuinely read-only effective posture fails inside codex with
        # codex's own error, surfaced with its reason and next action, while
        # the record keeps the request that was published.
        refusing = os.path.join(self.temp, "codex-refuses-headless-work")
        with open(refusing, "w", encoding="utf-8") as stream:
            stream.write(
                "#!/bin/sh\n"
                "echo 'codex exec: the sandbox is read-only; work that "
                "writes cannot run headlessly' >&2\n"
                "exit 1\n"
            )
        os.chmod(refusing, 0o755)
        session_dir = os.path.join(self.temp, "apparent-readonly-session")
        record.record(
            session_dir,
            "session-create",
            "A work session under an apparent read-only posture.\n",
            initiator="vibe-coder",
            peer="codex",
            project=self.temp,
            mode="work",
        )
        with self._codex_config('sandbox_mode = "read-only"\n'):
            with mock.patch.object(
                codex,
                "_prerequisites",
                return_value=(
                    refusing,
                    "0.147.0",
                    "Darwin 26 arm64",
                    (codex._work_warning("read-only", "fixture"),),
                ),
            ):
                with self.assertRaises(BridgeError) as caught:
                    runner.run_turn(session_dir, "Please work.\n", 30.0)
        self.assertEqual(caught.exception.failure, Failure.PEER_FAILURE)
        self.assertIn("sandbox is read-only", caught.exception.detail)
        self.assertIn("Next action:", str(caught.exception))
        self.assertEqual(
            os.listdir(session.messages_dir(session_dir)),
            ["0001-initiator-to-peer.md"],
        )

    def test_claude_work_carries_no_review_only_restriction_or_flag(self):
        prerequisite = (
            "/fake/claude",
            "2.1.251",
            "Darwin 26 arm64",
            "signed in through claude.ai",
            (claude.WORK_WARNING,),
        )
        with mock.patch.object(claude, "_prerequisites", return_value=prerequisite):
            command = claude.build_work_command(
                peer.Deadline(60.0), self.temp, access_paths=("/access/docs",)
            )
        self.assertEqual(
            command.argv,
            ("/fake/claude", "--print", "--output-format", "text",
             "--add-dir", "/access/docs"),
        )
        joined = " ".join(command.argv)
        for review_only in (
            "--restricted",
            "--strict-mcp-config",
            "--tools",
            "--permission-mode",
        ):
            self.assertNotIn(review_only, joined)
        with mock.patch.object(claude, "_prerequisites", return_value=prerequisite):
            with_image = claude.build_work_command(
                peer.Deadline(60.0), self.temp, attachments=("/img/a.png",)
            )
        self.assertTrue(
            any("file-reading tool" in warning for warning in with_image.warnings)
        )

    def test_zcode_work_is_edit_mode_with_its_real_tool_set(self):
        prerequisite = (
            "/fake/node /fake/zcode.cjs",
            "0.16.5",
            "Darwin 26 arm64",
            "minimum local configuration is present",
            (zcode.WORK_WARNING,),
        )
        with mock.patch.object(zcode, "_program", return_value=("/n", "/z")):
            with mock.patch.object(
                zcode, "_prerequisites", return_value=prerequisite
            ):
                command = zcode.build_work_command(
                    peer.Deadline(60.0),
                    self.temp,
                    attachments=("/img/a.png",),
                )
        self.assertEqual(
            command.argv,
            ("/n", "/z", "--mode", "edit", "--cwd", self.temp,
             "--attach", "/img/a.png", "--output-format", "text"),
        )
        self.assertEqual(command.body_argument, zcode.BODY_ARGUMENT)
        self.assertNotIn("--disallowed-tools", command.argv)
        self.assertIn(zcode.WORK_WARNING, command.warnings)

    def test_minimax_work_drops_the_one_step_assumption_and_attaches_files(self):
        prerequisite = (
            "/fake/mcode",
            "0.2.7",
            "Darwin 26 arm64",
            "authentication not confirmed",
            (minimax.WORK_WARNING,),
        )
        with mock.patch.object(minimax, "_prerequisites", return_value=prerequisite):
            command = minimax.build_work_command(
                peer.Deadline(60.0), self.temp, attachments=("/img/a.png",)
            )
            bounded = minimax.build_work_command(
                peer.Deadline(60.0), self.temp, max_steps=4
            )
        self.assertEqual(
            command.argv,
            (
                "/fake/mcode",
                "exec",
                "--input",
                "-",
                "--input-format",
                "text",
                "--cwd",
                self.temp,
                "--timeout",
                "60000ms",
                "--file",
                "/img/a.png",
                "--output-format",
                "text",
            ),
        )
        self.assertNotIn("--max-steps", command.argv)
        self.assertEqual(
            bounded.argv[bounded.argv.index("--max-steps") + 1], "4"
        )
        self.assertNotIn("--permission", " ".join(command.argv))
        self.assertIn(minimax.WORK_WARNING, command.warnings)

    def test_review_vectors_are_unchanged_by_the_work_additions(self):
        codex_prerequisite = ("/fake/codex", "0.147.0", "Darwin 26 arm64", ())
        with mock.patch.object(codex, "_prerequisites", return_value=codex_prerequisite):
            review = codex.build_command(peer.Deadline(60.0), self.temp)
        self.assertIn("read-only", review.argv)
        self.assertIn("--ignore-user-config", review.argv)


class WorkModeCheckQualifications(unittest.TestCase):
    """A work-mode check qualifies the work vector, never the review vector.

    Each check below drives one connector's real prerequisite code with a
    probe stand-in. The help text the stand-in returns names only the work
    vector's own switches - a program that had dropped every review-only
    switch - and the work-mode check must succeed on it, while the review
    check on the same program must still refuse. Authentication and the
    executable, version, and platform facts stay prerequisites in both modes.
    """

    def setUp(self):
        self.temp = tempfile.mkdtemp(prefix="agent-bridge-work-checks-")

    def tearDown(self):
        shutil.rmtree(self.temp, ignore_errors=True)

    @staticmethod
    def _probed(fake, recording):
        def probe(argv, cwd, deadline, env=None):
            argv = tuple(argv)
            recording.append(argv)
            return fake(argv)

        return probe

    def test_claude_work_check_skips_the_review_gates_and_policy_facts(self):
        auth = (
            '{"loggedIn": true, "authMethod": "claude.ai", '
            '"apiProvider": "firstParty"}'
        )
        work_help = (
            "Usage: claude\n  -p, --print\n  --output-format <format>\n"
            "  --add-dir <directories...>\n"
        )
        probed = []

        def fake(argv):
            if argv[-1] == "--version":
                return CompletedCall(0, "claude 2.1.251\n", "")
            if argv[-1] == "--json":
                return CompletedCall(0, auth, "")
            return CompletedCall(0, work_help, "")

        with mock.patch.object(
            claude.connectors, "executable", return_value="/fake/claude"
        ), mock.patch.object(
            claude.connectors, "qualified_platform",
            return_value="Darwin 26 arm64",
        ), mock.patch.object(
            claude.connectors, "probe", side_effect=self._probed(fake, probed)
        ):
            checked = claude.check(peer.Deadline(30.0), self.temp, mode="work")
            command = claude.build_work_command(peer.Deadline(60.0), self.temp)

        # No doctor question and no policy fact: the boundary they describe
        # is the review call's, and work mode discards both readings.
        self.assertEqual(
            probed[:3],
            [
                ("/fake/claude", "--version"),
                ("/fake/claude", "auth", "status", "--json"),
                ("/fake/claude", "--help"),
            ],
        )
        self.assertNotIn("/fake/claude doctor", " ".join(map(" ".join, probed)))
        self.assertEqual(checked.warnings, (claude.WORK_WARNING,))
        self.assertEqual(
            command.argv, ("/fake/claude", "--print", "--output-format", "text")
        )

        # The help names no review switch, and the review check refuses it.
        with mock.patch.object(
            claude.connectors, "executable", return_value="/fake/claude"
        ), mock.patch.object(
            claude.connectors, "qualified_platform",
            return_value="Darwin 26 arm64",
        ), mock.patch.object(
            claude.connectors, "probe", side_effect=self._probed(fake, [])
        ):
            with self.assertRaises(BridgeError) as caught:
                claude.check(peer.Deadline(30.0), self.temp)
        self.assertEqual(caught.exception.failure, Failure.RESTRICTIONS_UNAVAILABLE)

        # --add-dir is a prerequisite only when an access directory exists.
        no_add_dir = work_help.replace("  --add-dir <directories...>\n", "")

        def fake_without(argv):
            if argv[-1] == "--version":
                return CompletedCall(0, "claude 2.1.251\n", "")
            if argv[-1] == "--json":
                return CompletedCall(0, auth, "")
            return CompletedCall(0, no_add_dir, "")

        with mock.patch.object(
            claude.connectors, "executable", return_value="/fake/claude"
        ), mock.patch.object(
            claude.connectors, "qualified_platform",
            return_value="Darwin 26 arm64",
        ), mock.patch.object(
            claude.connectors, "probe", side_effect=self._probed(fake_without, [])
        ):
            claude.build_work_command(peer.Deadline(60.0), self.temp)
            with self.assertRaises(BridgeError) as caught:
                claude.build_work_command(
                    peer.Deadline(60.0), self.temp, access_paths=("/access/docs",)
                )
        self.assertEqual(caught.exception.failure, Failure.RESTRICTIONS_UNAVAILABLE)

    def test_codex_work_check_qualifies_the_work_switches_only(self):
        work_help = (
            "Usage: codex exec\n  --skip-git-repo-check\n  --cd <DIR>\n"
        )
        probed = []

        def fake(argv):
            if argv[-1] == "--version":
                return CompletedCall(0, "codex-cli 0.147.0\n", "")
            if tuple(argv)[1:] == ("login", "status"):
                return CompletedCall(0, "", "Logged in using ChatGPT")
            return CompletedCall(0, work_help, "")

        with mock.patch.object(
            codex.connectors, "executable", return_value="/fake/codex"
        ), mock.patch.object(
            codex.connectors, "qualified_platform",
            return_value="Darwin 26 arm64",
        ), mock.patch.object(
            codex.connectors, "probe", side_effect=self._probed(fake, probed)
        ), mock.patch.dict(os.environ, {"CODEX_HOME": self.temp}):
            checked = codex.check(peer.Deadline(30.0), self.temp, mode="work")
            codex.build_work_command(peer.Deadline(60.0), self.temp)

        # The exec subcommand is proved by the help probe that carries the
        # switches; the login status is still a prerequisite; the help names
        # no review-only switch and the work check proceeds on it.
        self.assertEqual(
            probed[:3],
            [
                ("/fake/codex", "--version"),
                ("/fake/codex", "login", "status"),
                ("/fake/codex", "exec", "--help"),
            ],
        )
        self.assertEqual(len(checked.warnings), 1)
        self.assertIn("apparent", checked.warnings[0])

        with mock.patch.object(
            codex.connectors, "executable", return_value="/fake/codex"
        ), mock.patch.object(
            codex.connectors, "qualified_platform",
            return_value="Darwin 26 arm64",
        ), mock.patch.object(
            codex.connectors, "probe", side_effect=self._probed(fake, [])
        ):
            with self.assertRaises(BridgeError) as caught:
                codex.check(peer.Deadline(30.0), self.temp)
        self.assertEqual(caught.exception.failure, Failure.RESTRICTIONS_UNAVAILABLE)

        # A refused sign-in still stops a work turn before anything starts.
        def signed_out(argv):
            if argv[-1] == "--version":
                return CompletedCall(0, "codex-cli 0.147.0\n", "")
            return CompletedCall(1, "", "not logged in")

        with mock.patch.object(
            codex.connectors, "executable", return_value="/fake/codex"
        ), mock.patch.object(
            codex.connectors, "qualified_platform",
            return_value="Darwin 26 arm64",
        ), mock.patch.object(
            codex.connectors, "probe", side_effect=self._probed(signed_out, [])
        ):
            with self.assertRaises(BridgeError) as caught:
                codex.check(peer.Deadline(30.0), self.temp, mode="work")
        self.assertEqual(caught.exception.failure, Failure.AUTHENTICATION_REQUIRED)

        # --add-dir and --image are prerequisites only when they travel.
        def fake_without(argv):
            if argv[-1] == "--version":
                return CompletedCall(0, "codex-cli 0.147.0\n", "")
            if tuple(argv)[1:] == ("login", "status"):
                return CompletedCall(0, "", "Logged in using ChatGPT")
            return CompletedCall(0, work_help, "")

        with mock.patch.object(
            codex.connectors, "executable", return_value="/fake/codex"
        ), mock.patch.object(
            codex.connectors, "qualified_platform",
            return_value="Darwin 26 arm64",
        ), mock.patch.object(
            codex.connectors, "probe",
            side_effect=self._probed(fake_without, []),
        ), mock.patch.dict(os.environ, {"CODEX_HOME": self.temp}):
            codex.build_work_command(peer.Deadline(60.0), self.temp)
            for requested in ({"access_paths": ("/access",)},
                              {"attachments": ("/img/a.png",)}):
                with self.subTest(requested=sorted(requested)):
                    with self.assertRaises(BridgeError) as caught:
                        codex.build_work_command(
                            peer.Deadline(60.0), self.temp, **requested
                        )
                    self.assertEqual(
                        caught.exception.failure,
                        Failure.RESTRICTIONS_UNAVAILABLE,
                    )

    def test_minimax_work_check_requires_no_review_permission_switch(self):
        work_help = (
            "Usage: mcode exec\n  --input <text>\n  --input-format <format>\n"
            "  --cwd <dir>\n  --output-format <format>\n  --timeout <ms>\n"
            "  --file <path>\n  --max-steps <n>\n"
        )
        probed = []

        def fake(argv):
            if argv[-1] == "--version":
                return CompletedCall(0, "mcode 0.2.7\n", "")
            return CompletedCall(0, work_help, "")

        with mock.patch.object(
            minimax.connectors, "executable", return_value="/fake/mcode"
        ), mock.patch.object(
            minimax.connectors, "qualified_platform",
            return_value="Darwin 26 arm64",
        ), mock.patch.object(
            minimax.connectors, "probe", side_effect=self._probed(fake, probed)
        ):
            checked = minimax.check(peer.Deadline(30.0), self.temp, mode="work")
            command = minimax.build_work_command(
                peer.Deadline(30.0), self.temp, attachments=("/img/a.png",)
            )

        # Two probes only, no provider probe: authentication stays honestly
        # unconfirmed, and the help names no --permission switch.
        self.assertEqual(
            probed[:2],
            [("/fake/mcode", "--version"), ("/fake/mcode", "exec", "--help")],
        )
        self.assertTrue(
            all("provider" not in " ".join(call) for call in probed)
        )
        self.assertIn(minimax.WORK_WARNING, checked.warnings)
        self.assertTrue(
            any("unconfirmed" in warning for warning in checked.warnings)
        )
        self.assertIn(("--file", "/img/a.png"), tuple(zip(command.argv, command.argv[1:])))

        # The review check still requires the review set, --permission
        # included, from the same switchless help.
        with mock.patch.object(
            minimax.connectors, "executable", return_value="/fake/mcode"
        ), mock.patch.object(
            minimax.connectors, "qualified_platform",
            return_value="Darwin 26 arm64",
        ), mock.patch.object(
            minimax.connectors, "probe", side_effect=self._probed(fake, [])
        ):
            with self.assertRaises(BridgeError) as caught:
                minimax.check(peer.Deadline(30.0), self.temp)
        self.assertEqual(caught.exception.failure, Failure.RESTRICTIONS_UNAVAILABLE)

        # The optional switches are prerequisites only when the vector
        # emits them; the native timeout stops being one when the deadline
        # is past what the program's own timer domain accepts.
        optional_free = work_help.replace("  --file <path>\n", "").replace(
            "  --max-steps <n>\n", ""
        )

        def fake_without(argv):
            if argv[-1] == "--version":
                return CompletedCall(0, "mcode 0.2.7\n", "")
            return CompletedCall(0, optional_free, "")

        with mock.patch.object(
            minimax.connectors, "executable", return_value="/fake/mcode"
        ), mock.patch.object(
            minimax.connectors, "qualified_platform",
            return_value="Darwin 26 arm64",
        ), mock.patch.object(
            minimax.connectors, "probe", side_effect=self._probed(fake_without, [])
        ):
            minimax.build_work_command(peer.Deadline(30.0), self.temp)
            for requested in ({"attachments": ("/img/a.png",)},
                              {"max_steps": 4}):
                with self.subTest(requested=sorted(requested)):
                    with self.assertRaises(BridgeError) as caught:
                        minimax.build_work_command(
                            peer.Deadline(30.0), self.temp, **requested
                        )
                    self.assertEqual(
                        caught.exception.failure,
                        Failure.RESTRICTIONS_UNAVAILABLE,
                    )

            no_timeout = optional_free.replace("  --timeout <ms>\n", "")

            def fake_untimed(argv):
                if argv[-1] == "--version":
                    return CompletedCall(0, "mcode 0.2.7\n", "")
                return CompletedCall(0, no_timeout, "")

            with mock.patch.object(
                minimax.connectors, "probe",
                side_effect=self._probed(fake_untimed, []),
            ):
                astronomical = minimax.build_work_command(
                    peer.Deadline(1e308), self.temp
                )
            self.assertNotIn("--timeout", astronomical.argv)

    def test_zcode_work_check_drops_the_review_deny_list_requirement(self):
        help_text = (
            "  -p, --prompt <text>\n  --mode <mode>\n  --cwd <path>\n"
            "  --attach <path>\n  --disallowed-tools <tools...>\n"
        )
        probed = []

        def fake(argv):
            if argv[2] == "--version":
                return CompletedCall(0, "zcode 0.16.5\n", "")
            if argv[2] == "plugins":
                return CompletedCall(0, "[]", "")
            if argv[2] == "version":
                return CompletedCall(0, "zcode 0.16.5\n", "")
            return CompletedCall(0, help_text, "")

        with mock.patch.object(
            zcode, "_program", return_value=("/fake/node", "/fake/zcode.cjs")
        ), mock.patch.object(
            zcode.connectors, "qualified_platform",
            return_value="Darwin 26 arm64",
        ), mock.patch.object(
            zcode, "_sign_in_facts", return_value="sign-in observed"
        ), mock.patch.object(
            zcode.connectors, "probe", side_effect=self._probed(fake, probed)
        ):
            checked = zcode.check(peer.Deadline(30.0), self.temp, mode="work")
            command = zcode.build_work_command(peer.Deadline(60.0), self.temp)

        # The no-model parser check passes the work switches and no
        # --disallowed-tools, because the work vector never carries one.
        parser_probes = [call for call in probed if call[2] == "version"]
        self.assertEqual(len(parser_probes), 2)
        for parser_probe in parser_probes:
            self.assertEqual(
                parser_probe,
                (
                    "/fake/node", "/fake/zcode.cjs", "version",
                    "--mode", "edit", "--cwd", self.temp,
                    "--output-format", "text",
                ),
            )
        self.assertIn(zcode.WORK_WARNING, checked.warnings)
        self.assertEqual(
            command.argv,
            (
                "/fake/node", "/fake/zcode.cjs",
                "--mode", "edit", "--cwd", self.temp,
                "--output-format", "text",
            ),
        )

        # A help text without the review deny-list switch serves a work turn
        # and refuses a review one; the review parser check still carries
        # the deny switch the review vector passes.
        no_deny_list = help_text.replace(
            "  --disallowed-tools <tools...>\n", ""
        )

        def fake_without(argv):
            if argv[2] == "--version":
                return CompletedCall(0, "zcode 0.16.5\n", "")
            if argv[2] == "plugins":
                return CompletedCall(0, "[]", "")
            if argv[2] == "version":
                return CompletedCall(0, "zcode 0.16.5\n", "")
            return CompletedCall(0, no_deny_list, "")

        with mock.patch.object(
            zcode, "_program", return_value=("/fake/node", "/fake/zcode.cjs")
        ), mock.patch.object(
            zcode.connectors, "qualified_platform",
            return_value="Darwin 26 arm64",
        ), mock.patch.object(
            zcode, "_sign_in_facts", return_value="sign-in observed"
        ), mock.patch.object(
            zcode.connectors, "probe", side_effect=self._probed(fake_without, [])
        ):
            zcode.check(peer.Deadline(30.0), self.temp, mode="work")
            with self.assertRaises(BridgeError) as caught:
                zcode.check(peer.Deadline(30.0), self.temp)
        self.assertEqual(caught.exception.failure, Failure.RESTRICTIONS_UNAVAILABLE)

        review_probes = []
        with mock.patch.object(
            zcode, "_program", return_value=("/fake/node", "/fake/zcode.cjs")
        ), mock.patch.object(
            zcode.connectors, "qualified_platform",
            return_value="Darwin 26 arm64",
        ), mock.patch.object(
            zcode, "_sign_in_facts", return_value="sign-in observed"
        ), mock.patch.object(
            zcode.connectors, "probe",
            side_effect=self._probed(fake, review_probes),
        ):
            zcode.check(peer.Deadline(30.0), self.temp)
        self.assertEqual(
            [call for call in review_probes if call[2] == "version"],
            [
                (
                    "/fake/node", "/fake/zcode.cjs", "version",
                    "--disallowed-tools", "Edit", "--mode", "plan",
                    "--cwd", self.temp, "--output-format", "text",
                )
            ],
        )

        # --attach is a prerequisite only when an attachment travels.
        no_attach = help_text.replace("  --attach <path>\n", "")

        def fake_unattached(argv):
            if argv[2] == "--version":
                return CompletedCall(0, "zcode 0.16.5\n", "")
            if argv[2] == "plugins":
                return CompletedCall(0, "[]", "")
            if argv[2] == "version":
                return CompletedCall(0, "zcode 0.16.5\n", "")
            return CompletedCall(0, no_attach, "")

        with mock.patch.object(
            zcode, "_program", return_value=("/fake/node", "/fake/zcode.cjs")
        ), mock.patch.object(
            zcode.connectors, "qualified_platform",
            return_value="Darwin 26 arm64",
        ), mock.patch.object(
            zcode, "_sign_in_facts", return_value="sign-in observed"
        ), mock.patch.object(
            zcode.connectors, "probe",
            side_effect=self._probed(fake_unattached, []),
        ):
            zcode.build_work_command(peer.Deadline(60.0), self.temp)
            with self.assertRaises(BridgeError) as caught:
                zcode.build_work_command(
                    peer.Deadline(60.0), self.temp, attachments=("/img/a.png",)
                )
        self.assertEqual(caught.exception.failure, Failure.RESTRICTIONS_UNAVAILABLE)

    def test_unsupported_work_needs_no_switch_qualification(self):
        """Hermes and Qwen: work is reported unsupported from source-grounded
        reasons, and no review switch is a prerequisite of that report."""
        for connector, peer_id in ((hermes, "hermes"), (qwen, "qwen")):
            with self.subTest(peer=peer_id):
                probed = []

                def fake(argv):
                    argv = tuple(argv)
                    if argv[-1] == "--version":
                        version = {
                            "hermes": "hermes 0.18.2\n",
                            "qwen": "qwen 0.23.0\n",
                        }[peer_id]
                        return CompletedCall(0, version, "")
                    if peer_id == "hermes":
                        return CompletedCall(
                            0,
                            "logged in\nusing Nous as inference provider\n",
                            "",
                        )
                    return CompletedCall(0, "", "")

                with mock.patch.object(
                    connector.connectors, "executable",
                    return_value="/fake/{0}".format(peer_id),
                ), mock.patch.object(
                    connector.connectors, "qualified_platform",
                    return_value="Darwin 26 arm64",
                ), mock.patch.object(
                    connector.connectors, "probe",
                    side_effect=self._probed(fake, probed),
                ):
                    checked = connector.check(
                        peer.Deadline(30.0), self.temp, mode="work"
                    )
                    # The work-mode check asked its version and
                    # authentication questions and no switch question at
                    # all; its sentence claims no switch verification
                    # nobody performed.
                    expected = [("/fake/{0}".format(peer_id), "--version")]
                    if peer_id == "hermes":
                        expected.append(("/fake/hermes", "portal", "info"))
                    self.assertEqual(probed, expected)
                    self.assertIn("{0} ".format(peer_id), checked.message)
                    self.assertNotIn("fixed-vector switch", checked.message)

                    # The same switchless program still fails a review
                    # check, which alone qualifies the review switches.
                    with self.assertRaises(BridgeError) as caught:
                        connector.check(peer.Deadline(30.0), self.temp)
                self.assertEqual(
                    caught.exception.failure, Failure.RESTRICTIONS_UNAVAILABLE
                )
                self.assertEqual(
                    probed[-1], ("/fake/{0}".format(peer_id), "--help")
                )


class WindowsLockingTwins(unittest.TestCase):
    """The msvcrt lock twin: the same one-holder contract, simulated.

    No Windows machine is part of this repository's qualification, so the
    Windows branch of the session lock is driven by standing in for the
    `msvcrt` module itself, with the lock file, the descriptors, and the
    contention all real. The POSIX twin is checked on this platform directly,
    and the cross-process flock behavior it keeps is covered by the
    compatibility selection's own contention checks.
    """

    def setUp(self):
        self.temp = tempfile.mkdtemp(prefix="agent-bridge-work-winlock-")

    def tearDown(self):
        shutil.rmtree(self.temp, ignore_errors=True)

    class _FakeMsvcrt(object):
        """A stand-in for the Windows lock module.

        The real `msvcrt.locking` refuses a second `LK_NBLCK` on the same
        byte range and refuses to unlock a range the caller does not hold;
        the stand-in does both, keyed on the file the descriptor names, and
        records every call's mode, length, and the position it was made at.
        """

        LK_NBLCK = 2
        LK_UNLCK = 0

        def __init__(self):
            self.locked = set()
            self.calls = []

        def locking(self, fd, mode, nbytes):
            status = os.fstat(fd)
            key = (status.st_dev, status.st_ino)
            self.calls.append(
                (fd, mode, nbytes, os.lseek(fd, 0, os.SEEK_CUR))
            )
            if mode == self.LK_NBLCK:
                if key in self.locked:
                    raise OSError(13, "Permission denied")
                self.locked.add(key)
            elif mode == self.LK_UNLCK:
                if key not in self.locked:
                    raise OSError(22, "unlock of an unheld region")
                self.locked.discard(key)

    def test_the_windows_twin_locks_unlocks_and_refuses_a_second_holder(self):
        fake = self._FakeMsvcrt()
        with mock.patch.object(locking, "msvcrt", fake):
            with locking.session_lock(self.temp) as path:
                self.assertEqual(path, locking.lock_path(self.temp))
                self.assertEqual(len(fake.locked), 1)
                # A second acquirer is refused at once, and nothing is ever
                # written into the lock file.
                with self.assertRaises(BridgeError) as caught:
                    with locking.session_lock(self.temp):
                        self.fail("the lock was granted twice")
                self.assertEqual(caught.exception.failure, Failure.BUSY_SESSION)
                with open(path, "rb") as stream:
                    self.assertEqual(stream.read(), b"")
            # The holder's exit gives the lock back.
            self.assertEqual(fake.locked, set())

        # Every call locked or unlocked one byte, at the start of the file:
        # the take, the refused second take, the refused second take's stray
        # release, and the holder's release.
        self.assertEqual(
            [(mode, nbytes, position) for _fd, mode, nbytes, position in fake.calls],
            [
                (fake.LK_NBLCK, 1, 0),
                (fake.LK_NBLCK, 1, 0),
                (fake.LK_UNLCK, 1, 0),
                (fake.LK_UNLCK, 1, 0),
            ],
        )

    def test_the_posix_twin_is_flock_and_its_release_is_the_close(self):
        with mock.patch.object(locking, "msvcrt", None):
            handle = os.open(
                locking.lock_path(self.temp), os.O_RDWR | os.O_CREAT, 0o600
            )
            second = os.open(locking.lock_path(self.temp), os.O_RDWR)
            try:
                # Closing the descriptor has always been the release on
                # POSIX, so the release twin does nothing there.
                self.assertIsNone(locking._release(handle))
                locking._acquire(handle)
                with self.assertRaises(OSError):
                    locking._acquire(second)
            finally:
                os.close(handle)
                os.close(second)


class WindowsProcessCleanup(unittest.TestCase):
    """The taskkill and job cleanup branch, simulated: the owned tree ends.

    No Windows machine is part of this repository's qualification, so the
    Windows branch of process cleanup is driven by patching the platform
    switch and standing in for `taskkill /T /F` with a function that
    force-terminates the same processes the real command's own tree walk
    would reach, and for the kill-on-close job with a release that
    terminates the same members the kernel's close would. Everything else in
    each check is real: the spawn, the deadline, the signal delivery, the
    reaping, and the processes that must be gone afterwards - including the
    one case where the root exits before cleanup and the tree walk has
    nothing to walk from. The Unix branch of the same cleanup is the
    compatibility selection's own orphan and stop checks.
    """

    def setUp(self):
        self.temp = tempfile.mkdtemp(prefix="agent-bridge-work-winclean-")

    def tearDown(self):
        shutil.rmtree(self.temp, ignore_errors=True)

    def _child_pids(self, pid_path):
        """The descendant pids the fixture reported, read from its file."""
        with open(pid_path, encoding="utf-8") as stream:
            return [
                int(number)
                for kind, number in PID_LINE.findall(stream.read())
                if kind == "CHILD"
            ]

    def _tree_killer(self, pid_path):
        """A stand-in for `taskkill /T /F` on one root pid.

        The real command walks the descendant tree and force-terminates each
        process it names; the stand-in terminates the root and the descendant
        the fixture reported, which is the same set, and answers the
        emptiness question the same way: nothing found means already gone.
        """

        def taskkill(pgid):
            pids = [pgid] + self._child_pids(pid_path)
            found = False
            for pid in pids:
                try:
                    os.kill(pid, signal.SIGKILL)
                    found = True
                except ProcessLookupError:
                    pass
            return not found

        return taskkill

    def _walk_from_root_killer(self, pid_path):
        """A stand-in for `taskkill /T /F` faithful to where the walk starts.

        The real command's `/T` walk begins at the root pid: a root that has
        already exited turns the whole command into one not-found report that
        names no descendant and empties nothing, and a live root names the
        whole tree. The stand-in does exactly that and nothing more, which is
        what makes it the right simulation for the parent-exits-first case:
        it cannot reach an orphan even by accident.
        """

        def taskkill(pgid):
            try:
                os.kill(pgid, signal.SIGKILL)
            except ProcessLookupError:
                return True
            for pid in self._child_pids(pid_path):
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            return False

        return taskkill

    def _owned_job(self, pid_path, order=None):
        """Stand-ins for the kill-on-close job's assignment and release.

        The real release is the kernel's: closing the last handle to the job
        terminates every member, root or descendant, alive at the close. The
        stand-in terminates the same set the tree killer would, which is what
        makes it faithful to the one case the correction is about - the root
        already gone and a descendant still running.
        """

        def own_tree(process):
            if order is not None:
                order.append(("own", process.pid))
            return ("job", process.pid)

        def release(job):
            if order is not None:
                order.append(("release", job[1]))
            for pid in [job[1]] + self._child_pids(pid_path):
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass

        return own_tree, release

    def test_a_windows_timeout_terminates_the_whole_owned_tree(self):
        pid_path = os.path.join(self.temp, "timeout-pids.txt")
        own_tree, release = self._owned_job(pid_path)
        with mock.patch.object(peer, "WINDOWS", True), mock.patch.object(
            peer, "CLEANUP_GRACE_SECONDS", 0.2
        ), mock.patch.object(
            peer, "ESCALATION_GRACE_SECONDS", 0.5
        ), mock.patch.object(
            peer, "_windows_taskkill", side_effect=self._tree_killer(pid_path)
        ), mock.patch.object(
            peer, "_windows_own_tree", side_effect=own_tree
        ), mock.patch.object(
            peer, "_windows_release_job", side_effect=release
        ):
            with self.assertRaises(peer.PeerTimeout) as caught:
                peer.run_bounded(
                    argv=(
                        sys.executable, FAKE_PEER,
                        "write-pids-then-hang", pid_path,
                    ),
                    cwd=self.temp,
                    env=tuple(os.environ.items()),
                    stdin_text="Start something and then stop answering.\n",
                    deadline=peer.Deadline(0.8),
                )
        pids = _await_reported_pids(pid_path)
        self.assertEqual(caught.exception.pid, pids["PEER"])
        self.assertTrue(
            _wait_until_gone(pids["PEER"]),
            "the peer is still there after the Windows cleanup",
        )
        self.assertTrue(
            _wait_until_gone(pids["CHILD"]),
            "the process the peer started is still there",
        )

    def test_a_windows_stop_terminates_the_whole_owned_tree(self):
        pid_path = os.path.join(self.temp, "stop-pids.txt")
        driver = subprocess.Popen(
            (
                sys.executable, "-c", WINDOWS_SIGNAL_DRIVER,
                REPO_ROOT, FAKE_PEER, "write-pids-then-hang", pid_path,
            ),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        def end_driver():
            driver.stdin.close()
            if driver.poll() is None:
                driver.kill()
            driver.wait(timeout=10.0)
            driver.stdout.close()
            driver.stderr.close()

        self.addCleanup(end_driver)
        pids = _await_reported_pids(pid_path)

        os.kill(driver.pid, signal.SIGTERM)
        driver.wait(timeout=10.0)
        self.assertEqual(driver.returncode, 3, driver.stderr.read())
        self.assertTrue(
            _wait_until_gone(pids["PEER"]),
            "the peer is still there after the Windows stop",
        )
        self.assertTrue(
            _wait_until_gone(pids["CHILD"]),
            "the process the peer started is still there after the stop",
        )

    def test_a_windows_root_that_exits_first_still_ends_its_descendants(self):
        """The parent-exits-first case: the root is gone before cleanup, a
        descendant is alive, and the corrected ownership still ends it.

        A tree walk that starts at the root can confirm nothing once the root
        has exited - `taskkill`'s not-found report names no descendant - so
        the ownership is the kill-on-close job, whose release terminates
        every member, root or no root. The two stand-ins are faithful to
        exactly that split: this taskkill walks only from a live root and
        kills nothing when the root is gone, so the release is the only
        thing that can reach the orphan, and the run must finish clean.
        """
        pid_path = os.path.join(self.temp, "orphan-pids.txt")
        order = []
        own_tree, release = self._owned_job(pid_path, order)
        walk = self._walk_from_root_killer(pid_path)

        def taskkill(pgid):
            order.append(("taskkill", pgid))
            return walk(pgid)

        with mock.patch.object(peer, "WINDOWS", True), mock.patch.object(
            peer, "CLEANUP_GRACE_SECONDS", 0.2
        ), mock.patch.object(
            peer, "ESCALATION_GRACE_SECONDS", 0.5
        ), mock.patch.object(
            peer, "_windows_taskkill", side_effect=taskkill
        ), mock.patch.object(
            peer, "_windows_own_tree", side_effect=own_tree
        ), mock.patch.object(
            peer, "_windows_release_job", side_effect=release
        ):
            completed = peer.run_bounded(
                argv=(
                    sys.executable, FAKE_PEER,
                    "write-pids-then-exit", pid_path,
                ),
                cwd=self.temp,
                env=tuple(os.environ.items()),
                stdin_text="Start something, leave it behind, and go.\n",
                deadline=peer.Deadline(30.0),
            )
        pids = _await_reported_pids(pid_path)
        self.assertEqual(completed.returncode, 0)
        # The job was taken out at spawn and closed before any confirming
        # walk, which is the order that makes a not-found report an honest
        # emptiness answer for the descendants the walk never reached.
        self.assertEqual(order[0], ("own", pids["PEER"]))
        self.assertEqual(order[1], ("release", pids["PEER"]))
        self.assertEqual(order[2][0], "taskkill")
        self.assertTrue(
            _wait_until_gone(pids["PEER"]),
            "the peer is still there after the Windows cleanup",
        )
        self.assertTrue(
            _wait_until_gone(pids["CHILD"]),
            "the descendant that outlived its root is still there",
        )

    def test_a_windows_spawn_refused_ownership_ends_what_it_started(self):
        """A platform that refuses the kill-on-close job does not get to run.

        The refusal is the answer rather than a degraded run: what was just
        started is terminated at once, while its root is alive and the tree
        walk can still reach whatever it started, and no cleanup runs
        afterwards because the responsibility has already been taken.
        """
        order = []

        def refusing_own_tree(process):
            order.append(("own", process.pid))
            raise BridgeError(
                Failure.CLEANUP_FAILURE,
                detail="the platform refused the kill-on-close job",
            )

        def release(job):
            order.append(("release", job))

        def taskkill(pgid):
            try:
                os.kill(pgid, signal.SIGKILL)
            except ProcessLookupError:
                order.append(("taskkill-missing", pgid))
                return True
            order.append(("taskkill-terminated", pgid))
            return False

        with mock.patch.object(peer, "WINDOWS", True), mock.patch.object(
            peer, "_windows_own_tree", side_effect=refusing_own_tree
        ), mock.patch.object(
            peer, "_windows_release_job", side_effect=release
        ), mock.patch.object(
            peer, "_windows_taskkill", side_effect=taskkill
        ):
            with self.assertRaises(BridgeError) as caught:
                peer.run_bounded(
                    argv=(sys.executable, FAKE_PEER, "hang"),
                    cwd=self.temp,
                    env=tuple(os.environ.items()),
                    stdin_text="Start something and then stop answering.\n",
                    deadline=peer.Deadline(30.0),
                )
        self.assertEqual(caught.exception.failure, Failure.CLEANUP_FAILURE)
        self.assertIn(
            "refused the kill-on-close job", caught.exception.detail
        )
        # The refused run ended the program it had started through the live
        # root, in that order, and no job was ever released because none was
        # taken.
        root = order[0][1]
        self.assertEqual(
            order,
            [("own", root), ("taskkill-terminated", root)],
            "the started program must be terminated while its root is live",
        )
        self.assertTrue(
            _wait_until_gone(root),
            "the refused program is still running",
        )

    def test_the_kill_on_close_job_structure_matches_the_api_layout(self):
        """The ctypes declaration is the layout `SetInformationJobObject`
        expects, measured rather than trusted, carrying the one limit flag
        and nothing else. The measurement runs on this platform because a
        byte layout is a fact about the declaration, not the machine; the
        only platform-dependent part is the pointer width, which the Windows
        build shares with the one running here.
        """
        information = peer._windows_job_information()
        self.assertEqual(
            information.BasicLimitInformation.LimitFlags,
            peer._JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
        )
        counters = type(information.IoInfo)
        self.assertEqual(
            ctypes.sizeof(counters), 48, "IO_COUNTERS is six quadwords"
        )
        # JOBOBJECT_BASIC_LIMIT_INFORMATION: two quadwords, a dword, two
        # pointer-sized fields, a dword, a pointer-sized affinity, and two
        # dwords, with the platform's own alignment.
        pointer = ctypes.sizeof(ctypes.c_void_p)
        expected_basic = 64 if pointer == 8 else 48
        self.assertEqual(
            ctypes.sizeof(information.BasicLimitInformation), expected_basic
        )
        # The extended structure is the basic one, the counters exactly
        # where the basic one ends, and four pointer-sized limits.
        self.assertEqual(
            ctypes.sizeof(information),
            expected_basic + 48 + 4 * pointer,
        )
        self.assertEqual(type(information).IoInfo.offset, expected_basic)

    class _WindowsSignals(object):
        """A stand-in for the Windows signal module.

        Windows CPython defines no `SIGKILL`, so neither does the stand-in:
        any code on the Windows path that names `signal.SIGKILL` fails the
        check below exactly the way it would fail on Windows itself, with an
        `AttributeError` raised before any cleanup could run. The signals
        that platform really defines and the Windows branches read are kept,
        with their real Windows values.
        """

        SIGINT = 2
        SIGTERM = 15
        CTRL_C_EVENT = 0
        CTRL_BREAK_EVENT = 1

    def test_the_windows_cleanup_never_names_a_signal_windows_does_not_have(self):
        """The whole Windows cleanup runs against a signal module without
        SIGKILL, so a missing attribute is a failure here rather than one
        discovered only on a Windows machine nobody has.

        The escalation sentinel is re-resolved from the stand-in exactly as
        the module resolves it at import, the escalation phase - the job
        handle's close - is reached with every platform primitive the branch
        touches stood in for, so the check is about the one thing that
        broke: the resolved values, and a code path that never reaches for
        an attribute the platform's own signal module does not define.
        """
        windows = self._WindowsSignals()
        resolved = getattr(windows, "SIGKILL", None)
        self.assertIsNone(
            resolved,
            "the escalation sentinel must resolve to None on a signal "
            "module without SIGKILL",
        )
        process = mock.Mock(pid=4321)
        job = ("job", 4321)
        kills = []
        releases = []
        taskkills = []

        def fake_kill(pid, number):
            kills.append((pid, number))

        def fake_release(handle):
            releases.append(handle)

        def fake_taskkill(pgid):
            taskkills.append(pgid)
            return True

        with mock.patch.object(peer, "WINDOWS", True), mock.patch.object(
            peer, "signal", windows
        ), mock.patch.object(
            peer, "_SIGKILL", resolved
        ), mock.patch.object(
            peer, "_CTRL_BREAK_EVENT", windows.CTRL_BREAK_EVENT
        ), mock.patch.object(
            peer.os, "kill", side_effect=fake_kill
        ), mock.patch.object(
            peer, "_windows_taskkill", side_effect=fake_taskkill
        ), mock.patch.object(
            peer, "_windows_release_job", side_effect=fake_release
        ), mock.patch.object(
            peer, "_reap", lambda waited, grace: None
        ), mock.patch.object(
            peer, "_await_group_gone", side_effect=[True]
        ):
            # Reaching the end at all is the first assertion: naming
            # signal.SIGKILL anywhere on this path raises AttributeError
            # against the stand-in, as it would against the real module.
            peer._cleanup_group(process, 4321, job)

        # The polite phase was the console break alone and the forced phase
        # was the job handle's close: no signal Windows does not have was
        # named, sent, or needed to empty the owned tree.
        self.assertEqual(
            kills, [(4321, windows.CTRL_BREAK_EVENT)]
        )
        self.assertEqual(releases, [job])
        self.assertEqual(taskkills, [])

        # A tree that will not confirm emptiness fails visibly rather than
        # pretending, still without naming any signal Windows lacks.
        with mock.patch.object(peer, "WINDOWS", True), mock.patch.object(
            peer, "signal", windows
        ), mock.patch.object(
            peer, "_SIGKILL", resolved
        ), mock.patch.object(
            peer, "_CTRL_BREAK_EVENT", windows.CTRL_BREAK_EVENT
        ), mock.patch.object(
            peer.os, "kill", side_effect=fake_kill
        ), mock.patch.object(
            peer, "_windows_taskkill", side_effect=fake_taskkill
        ), mock.patch.object(
            peer, "_windows_release_job", side_effect=fake_release
        ), mock.patch.object(
            peer, "_reap", lambda waited, grace: None
        ), mock.patch.object(
            peer, "_await_group_gone", side_effect=[False]
        ):
            with self.assertRaises(BridgeError) as caught:
                peer._cleanup_group(process, 4321, job)
        self.assertEqual(caught.exception.failure, Failure.CLEANUP_FAILURE)

        # Without the job, no missing root is an emptiness answer: the
        # cleanup says it cannot confirm descendants instead of returning a
        # clean verdict on a report that named nothing.
        with mock.patch.object(peer, "WINDOWS", True), mock.patch.object(
            peer, "signal", windows
        ), mock.patch.object(
            peer, "_CTRL_BREAK_EVENT", windows.CTRL_BREAK_EVENT
        ), mock.patch.object(
            peer.os, "kill", side_effect=fake_kill
        ), mock.patch.object(
            peer, "_reap", lambda waited, grace: None
        ):
            with self.assertRaises(BridgeError) as caught:
                peer._cleanup_group(process, 4321, None)
        self.assertEqual(caught.exception.failure, Failure.CLEANUP_FAILURE)
        self.assertIn("kill-on-close job", caught.exception.detail)

    def test_taskkill_is_one_fixed_vector_with_three_honest_answers(self):
        run = mock.Mock(
            return_value=subprocess.CompletedProcess((), 0, b"", b"SUCCESS")
        )
        with mock.patch.object(peer.subprocess, "run", run):
            self.assertFalse(
                peer._windows_taskkill(4321),
                "a terminated tree is not an already-empty one",
            )
        self.assertEqual(
            run.call_args[0][0], ("taskkill", "/T", "/F", "/PID", "4321")
        )

        with mock.patch.object(
            peer.subprocess,
            "run",
            return_value=subprocess.CompletedProcess(
                (), 128, b"", b'ERROR: The process "4321" not found.'
            ),
        ):
            self.assertTrue(
                peer._windows_taskkill(4321),
                "the not-found report, read after the job's close has "
                "terminated every member, is the emptiness answer",
            )

        with mock.patch.object(
            peer.subprocess,
            "run",
            return_value=subprocess.CompletedProcess(
                (), 1, b"", b"ERROR: Access is denied."
            ),
        ):
            with self.assertRaises(BridgeError) as caught:
                peer._windows_taskkill(4321)
        self.assertEqual(caught.exception.failure, Failure.CLEANUP_FAILURE)
        self.assertIn("Access is denied", caught.exception.detail)
        self.assertIn("4321", caught.exception.detail)


if __name__ == "__main__":
    unittest.main()
