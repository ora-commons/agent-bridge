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

The lifecycle fixtures are the repository's own fake peer; no real target is
called here.

SPDX-License-Identifier: CC0-1.0
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
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
from tests.test_fake_peer import FAKE_PEER  # noqa: E402


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

    def test_codex_work_refuses_a_read_only_effective_posture(self):
        """The one posture ordinary work cannot run under headlessly.

        Both origins of that posture refuse the same way: the user's own
        configuration naming read-only, and codex's out-of-box default when
        nothing configures a wider sandbox. The refusal happens inside the
        work builder, which the runner calls before anything is published.
        """
        postures = {
            "configured read-only": 'sandbox_mode = "read-only"\n',
            "codex default read-only": "# no sandbox_mode configured\n",
        }
        for name, config in postures.items():
            with self.subTest(origin=name):
                prerequisite = (
                    "/fake/codex",
                    "0.147.0",
                    "Darwin 26 arm64",
                    (codex._work_warning("read-only", "fixture"),),
                )
                with self._codex_config(config):
                    with mock.patch.object(
                        codex, "_prerequisites", return_value=prerequisite
                    ):
                        with self.assertRaises(BridgeError) as caught:
                            codex.build_work_command(
                                peer.Deadline(60.0), self.temp
                            )
                self.assertEqual(
                    caught.exception.failure,
                    Failure.WORK_POSTURE_UNAVAILABLE,
                )
                self.assertIn("read-only", caught.exception.detail)
                self.assertIn(
                    "Next action:", str(caught.exception)
                )

        # The same refusal through a real work session: the builder raises
        # inside the turn, before the request is published, so the session
        # keeps no record of a call that never ran.
        session_dir = os.path.join(self.temp, "refused-session")
        record.record(
            session_dir,
            "session-create",
            "A work session this posture cannot serve.\n",
            initiator="vibe-coder",
            peer="codex",
            project=self.temp,
            mode="work",
        )
        with self._codex_config('sandbox_mode = "read-only"\n'):
            with mock.patch.object(
                codex,
                "_prerequisites",
                return_value=("/fake/codex", "0.147.0", "Darwin 26 arm64", ()),
            ):
                with self.assertRaises(BridgeError) as caught:
                    runner.run_turn(session_dir, "Please work.\n", 30.0)
        self.assertEqual(
            caught.exception.failure, Failure.WORK_POSTURE_UNAVAILABLE
        )
        self.assertEqual(os.listdir(session.messages_dir(session_dir)), [])

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


if __name__ == "__main__":
    unittest.main()
