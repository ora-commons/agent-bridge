"""The frozen Format 2 and Format 3 command line and uniform failure rendering.

`check` asks whether one fixed target is ready without spending a model turn,
prose by default or one JSON object with `--json`. `run` reads target, mode,
and directories only from its immutable session. `record` creates that session
or writes a neutral note. Substantive Markdown always arrives on standard
input. Omitting every extended option keeps the original Format 2 behavior
byte for byte.

SPDX-License-Identifier: CC0-1.0
"""

from __future__ import annotations

import argparse
import contextlib
import json
import shutil
import sys
import tempfile
from typing import Iterator, Optional, Sequence

from . import connectors, record as record_module, runner
from .errors import BridgeError, Failure, guidance
from .peer import DEFAULT_TIMEOUT_SECONDS, Deadline, SignalStop

PROGRAM = "agent-bridge"
NEUTRAL_PREFIX = "agent-bridge-neutral-"


class _Parser(argparse.ArgumentParser):
    def __init__(self, *args, **kwargs):
        kwargs["allow_abbrev"] = False
        super().__init__(*args, **kwargs)

    def error(self, message: str) -> None:  # type: ignore[override]
        raise BridgeError(Failure.USAGE_ERROR, detail=message)


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(
        prog=PROGRAM,
        description="Send one bounded Markdown message to a supported target.",
    )
    subcommands = parser.add_subparsers(dest="command")

    check = subcommands.add_parser(
        "check", help="report whether a target can be used right now"
    )
    check.add_argument("--peer", required=True)
    check.add_argument("--mode", choices=("review", "work"))
    check.add_argument("--json", action="store_true")

    run = subcommands.add_parser(
        "run", help="perform one call for an existing session"
    )
    run.add_argument("--session", required=True)
    timing = run.add_mutually_exclusive_group()
    timing.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    timing.add_argument("--no-timeout", action="store_true",
                        help="wait for the peer until it answers or the caller stops the run")
    run.add_argument("--max-steps", type=int)
    run.add_argument("--require-model")
    run.add_argument("--events-jsonl", action="store_true")
    run.add_argument("--attachment", action="append")
    run.add_argument("--note-ref")
    run.add_argument("--purpose")

    record = subcommands.add_parser(
        "record", help="create a session or add one neutral note"
    )
    record.add_argument("--session", required=True)
    record.add_argument("--kind", required=True)
    record.add_argument("--initiator")
    record.add_argument("--peer")
    record.add_argument("--project")
    record.add_argument("--mode", choices=("review", "work"))
    record.add_argument("--access-path", action="append")

    return parser


def _read_body() -> str:
    return sys.stdin.read()


def _write_stdout(text: str) -> None:
    """Write one piece of standard output and push it out of the buffer now.

    Python buffers standard output when it is a pipe, and a caller watching a
    run's event stream is watching a pipe: an unflushed write would sit in
    the buffer until the process ended, which for a long turn is the whole
    turn. Every line this command means to deliver as it happens - the
    lifecycle events, and the terminal response-path line - goes through
    here, so each one is flushed the moment it is written.
    """
    sys.stdout.write(text)
    sys.stdout.flush()


def _remove_neutral(path: str, during: Optional[BaseException]) -> None:
    try:
        shutil.rmtree(path)
    except OSError as failed:
        if during is not None:
            raise BridgeError(
                Failure.CLEANUP_FAILURE,
                detail="the neutral working directory {0} could not be removed "
                "after the command failed ({1}): {2}".format(
                    path, during, failed
                ),
            )
        raise BridgeError(
            Failure.CLEANUP_FAILURE,
            detail="the neutral working directory {0} could not be removed: "
            "{1}".format(path, failed),
        )


@contextlib.contextmanager
def _check_directory() -> Iterator[str]:
    try:
        neutral = tempfile.mkdtemp(prefix=NEUTRAL_PREFIX)
    except OSError as exc:
        raise BridgeError(
            Failure.USAGE_ERROR,
            detail="no neutral working directory could be made: {0}".format(exc),
        )
    try:
        yield neutral
    except BaseException as exc:
        _remove_neutral(neutral, exc)
        raise
    _remove_neutral(neutral, None)


def _check(args: argparse.Namespace) -> connectors.CheckResult:
    connector = connectors.resolve(args.peer)
    mode = args.mode or "review"
    with _check_directory() as cwd:
        if mode == "work":
            return connector.check(Deadline(DEFAULT_TIMEOUT_SECONDS), cwd, mode="work")
        return connector.check(Deadline(DEFAULT_TIMEOUT_SECONDS), cwd)


def _check_json(args: argparse.Namespace) -> int:
    """One machine-readable readiness result, success or failure alike.

    The object carries the selected peer and mode, usability, the
    executable/version/platform facts, tri-state authentication and work/image
    capability, and warnings. It deliberately names no schema version: the
    field set is the contract. A hard failure still exits nonzero, with the
    reason and next action inside the object rather than on standard error.
    """
    mode = args.mode or "review"
    result = {
        "peer": args.peer,
        "mode": mode,
        "ready": False,
        "warnings": [],
    }  # type: dict
    try:
        checked = _check(args)
        result.update(
            {
                "ready": True,
                "executable": checked.executable,
                "version": checked.version,
                "platform": checked.platform,
                "authentication": (
                    "confirmed"
                    if checked.authentication_confirmed
                    else "unknown"
                ),
            }
        )
        capability = connectors.resolve(args.peer).CAPABILITIES
        result["work"] = capability.work
        result["image"] = capability.image
        result["warnings"] = list(checked.warnings)
        if capability.work == "unsupported":
            result["warnings"].append(capability.work_detail)
        if capability.image == "unsupported":
            result["warnings"].append(capability.image_detail)
    except BridgeError as error:
        reason, next_action = guidance(error.failure)
        if error.detail:
            reason = "{0} ({1})".format(reason, error.detail)
        result["reason"] = reason
        result["next_action"] = next_action
        if error.failure == Failure.AUTHENTICATION_REQUIRED:
            result["authentication"] = "required"
    sys.stdout.write(json.dumps(result, ensure_ascii=True) + "\n")
    return 0 if result["ready"] else 1


def _run(args: argparse.Namespace) -> Optional[str]:
    event_writer = None
    if args.events_jsonl:
        event_writer = _write_stdout
    result = runner.run_turn(
        session_dir=args.session,
        body=_read_body(),
        timeout_seconds=args.timeout,
        no_timeout=args.no_timeout,
        warning_writer=lambda warning: sys.stderr.write(
            "Warning: {0}\n".format(warning)
        ),
        max_steps=args.max_steps,
        required_model=args.require_model,
        attachments=tuple(args.attachment or ()),
        note_ref=args.note_ref,
        purpose=args.purpose,
        event_writer=event_writer,
    )
    if args.events_jsonl:
        # The finished event already carried the response path; the line a
        # flag-free run prints would only duplicate it on the event stream.
        return None
    return result.response_path


def _record(args: argparse.Namespace) -> str:
    return record_module.record(
        session_dir=args.session,
        kind=args.kind,
        body=_read_body(),
        initiator=args.initiator,
        peer=args.peer,
        project=args.project,
        mode=args.mode,
        access_paths=tuple(args.access_path) if args.access_path else None,
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(list(argv) if argv is not None else None)
        if not getattr(args, "command", None):
            raise BridgeError(
                Failure.USAGE_ERROR, detail="name a command: check, run, record"
            )
        if args.command == "check":
            if args.json:
                return _check_json(args)
            checked = _check(args)
            sys.stdout.write(checked.message + "\n")
            for warning in checked.warnings:
                sys.stdout.write("Warning: {0}\n".format(warning))
            return 0
        elif args.command == "run":
            written = _run(args)
        else:
            written = _record(args)
    except SignalStop as stopped:
        sys.stderr.write(str(stopped) + "\n")
        return 1
    except BridgeError as error:
        sys.stderr.write(str(error) + "\n")
        return 1
    if written is not None:
        _write_stdout(written + "\n")
    return 0
