"""One bounded courier call derived entirely from an immutable session.

The runner validates the body and connector transport before publishing the
request. It then starts one fresh target process, publishes one final textual
answer, and exits. A failed target leaves the truthful request and no invented
response. There is no retry or implicit history.

A Format 3 session may be a work session: the runner hands the connector's
work builder the session's declared directories and explicit attachments,
publishes the caller's inert note reference and purpose in the request header,
and marks the response with the request sequence it answers. A caller that
asked for lifecycle events gets `started`, periodic `heartbeat` check-ins, and
one `finished` event - the last only after durable publication or an honest
failure, so a broken event pipe can never make an unfinished call look
finished.

When a target's own structured output reports which model and provider
answered, that reported identity is preserved rather than discarded after
validation: the finished event carries it as optional `model` and `provider`
fields, and a Format 3 response record carries it as `Model:` and `Provider:`
header lines. Each half appears only when the tool reported it, never as an
empty placeholder, and the published response body stays the final text alone.

SPDX-License-Identifier: CC0-1.0
"""

from __future__ import annotations

import contextlib
import json
import math
import os
import re
import shutil
import tempfile
from typing import (
    Callable,
    Dict,
    Iterator,
    List,
    NamedTuple,
    Optional,
    Sequence,
    Tuple,
)

from . import connectors, session as session_module
from .connectors import (
    COMMAND_LINE_BODY_LIMIT,
    PeerCommand,
    argument_space_limit,
    argument_space_used,
)
from .errors import BridgeError, Failure, guidance
from .locking import session_lock
from .peer import Deadline, SignalStop, run_bounded

NEUTRAL_PREFIX = "agent-bridge-neutral-"

# Tests may replace the production connector builder only by calling this
# function directly. No command-line, environment, file, or configuration path
# exposes this seam.
CommandBuilder = Callable[[Deadline, str], PeerCommand]
WorkCommandBuilder = Callable[..., PeerCommand]
WarningWriter = Callable[[str], None]
#: Receives one already-serialized event line, newline included.
EventWriter = Callable[[str], None]

# Failure output is useful only when it is safe to show and small enough to
# read. Remove echoed requests and common credential shapes before shortening
# each stream's excerpt and escaping control characters. The byte count still
# describes the original output.
DIAGNOSTIC_EXCERPT_BYTES = 512
_CREDENTIAL_LINE = re.compile(
    r"(?i)(?:(?:api[_-]?key|access[_-]?token|refresh[_-]?token|"
    r"authorization|password|secret|token)[\\\"']*\s*[:=]|bearer\s+\S+|"
    r"(?:sk-[A-Za-z0-9_-]{8,}|gh[pousr]_[A-Za-z0-9]{8,})\b)"
)


def _redact_diagnostic(text: str, body: str) -> str:
    """Suppress raw or JSON-escaped request and credential lines before clipping."""
    fragments = []
    for line in body.splitlines():
        if not line:
            continue
        for fragment in (
            line,
            json.dumps(line, ensure_ascii=True)[1:-1],
            json.dumps(line, ensure_ascii=False)[1:-1],
        ):
            if fragment not in fragments:
                fragments.append(fragment)

    redacted_lines = []
    for line in text.splitlines(keepends=True):
        ending = "\n" if line.endswith("\n") else ""
        if any(fragment in line for fragment in fragments):
            redacted_lines.append("<request body redacted>" + ending)
        elif _CREDENTIAL_LINE.search(line):
            redacted_lines.append("<credential line redacted>" + ending)
        else:
            redacted_lines.append(line)
    return "".join(redacted_lines)


def _diagnostic_excerpt(text: str, body: str) -> str:
    """Describe one stream with a bounded, escaped, redacted excerpt."""
    encoded = text.encode("utf-8")
    redacted = _redact_diagnostic(text, body).encode("utf-8")
    clipped = redacted[:DIAGNOSTIC_EXCERPT_BYTES].decode("utf-8", "replace")
    escaped = json.dumps(clipped, ensure_ascii=True)
    suffix = ", truncated" if len(redacted) > DIAGNOSTIC_EXCERPT_BYTES else ""
    return "{0} bytes{1}, excerpt={2}".format(len(encoded), suffix, escaped)


def _peer_failure_detail(call, command: PeerCommand, body: str) -> str:
    """Keep safe evidence from both streams and any structured failure."""
    parts = ["exit {0}".format(call.returncode)]
    if command.response_parser is not None and call.stdout.strip():
        try:
            command.response_parser(call.stdout)
        except BridgeError as parsed:
            if parsed.failure == Failure.PEER_FAILURE:
                parts.append(
                    "structured stdout failure: {0}".format(
                        _diagnostic_excerpt(parsed.detail or str(parsed), body)
                    )
                )
    parts.extend(
        (
            "stderr: {0}".format(_diagnostic_excerpt(call.stderr, body)),
            "stdout: {0}".format(_diagnostic_excerpt(call.stdout, body)),
        )
    )
    return "; ".join(parts)


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
def _target_directory(project: Optional[str]) -> Iterator[str]:
    """Yield the immutable project, or a task-owned neutral empty directory."""
    if project is not None:
        if not os.path.isdir(project):
            raise BridgeError(
                Failure.SESSION_INVALID,
                detail="the recorded project is not a directory: {0}".format(project),
            )
        yield project
        return
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


def apply_transport(
    command: PeerCommand, body: str
) -> Tuple[Tuple[str, ...], str]:
    """Bind the body to standard input or one qualified final argument."""
    if command.body_argument is None:
        return command.argv, (
            command.stdin_encoder(body)
            if command.stdin_encoder is not None else body
        )
    if "\x00" in body:
        raise BridgeError(
            Failure.USAGE_ERROR,
            detail="the message contains a NUL byte, which this peer's "
            "command-line transport cannot carry; remove it and send the "
            "message again",
        )
    size = len(body.encode("utf-8"))
    if size > COMMAND_LINE_BODY_LIMIT:
        raise BridgeError(
            Failure.USAGE_ERROR,
            detail="the message is {0} bytes and this peer takes it on its "
            "command line, which Agent Bridge caps at {1} bytes; send a "
            "shorter message".format(size, COMMAND_LINE_BODY_LIMIT),
        )
    argv = command.argv + (command.body_argument + body,)
    used = argument_space_used(argv, command.env)
    limit = argument_space_limit()
    if used > limit:
        raise BridgeError(
            Failure.USAGE_ERROR,
            detail="the message, the command and this environment together "
            "come to {0} bytes, more than the {1} the operating system allows "
            "for starting a program once headroom is kept; send a shorter "
            "message or start Agent Bridge with a smaller environment".format(
                used, limit
            ),
        )
    return argv, ""


class TurnResult(NamedTuple):
    request_sequence: int
    response_sequence: int
    response_path: str


class _EventReporter(object):
    """Write lifecycle events as one JSON object per line, surviving a break.

    The events are a view of the turn, not a part of it: if the pipe they are
    written to goes away, the turn runs on and its records decide what is
    true. A write that fails is remembered and nothing further is written, so
    a broken event pipe can neither kill an otherwise healthy call nor - the
    thing that matters - turn an unfinished one into a reported success.
    """

    def __init__(self, writer: Callable[[str], None]) -> None:
        self._writer = writer
        self._broken = False

    def emit(self, event: Dict[str, object]) -> None:
        if self._broken:
            return
        try:
            self._writer(json.dumps(event, ensure_ascii=True) + "\n")
        except OSError:
            self._broken = True


def _attachments_error(path: str, option: str) -> BridgeError:
    if not os.path.isabs(path):
        return BridgeError(
            Failure.USAGE_ERROR,
            detail="{0} must be an absolute path: {1}".format(option, path),
        )
    return BridgeError(
        Failure.USAGE_ERROR,
        detail="{0} is not an existing file: {1}".format(option, path),
    )


def _validate_attachments(
    attachments: Sequence[str],
) -> Tuple[str, ...]:
    """Every attachment must be an absolute existing file, checked in order."""
    checked = []
    for path in attachments:
        if not os.path.isabs(path) or not os.path.isfile(path):
            raise _attachments_error(path, "--attachment")
        checked.append(path)
    return tuple(checked)


def run_turn(
    session_dir: str,
    body: str,
    timeout_seconds: float,
    build_command: Optional[CommandBuilder] = None,
    warning_writer: Optional[WarningWriter] = None,
    max_steps: Optional[int] = None,
    required_model: Optional[str] = None,
    attachments: Sequence[str] = (),
    note_ref: Optional[str] = None,
    purpose: Optional[str] = None,
    event_writer: Optional[EventWriter] = None,
    build_work_command: Optional[WorkCommandBuilder] = None,
    no_timeout: bool = False,
) -> TurnResult:
    """Publish one request and one response for the session's fixed target."""
    try:
        timeout = float(timeout_seconds)
    except (TypeError, ValueError):
        raise BridgeError(Failure.USAGE_ERROR, detail="--timeout must be a number")
    if not math.isfinite(timeout) or timeout <= 0.0:
        raise BridgeError(
            Failure.USAGE_ERROR, detail="--timeout must be greater than zero"
        )
    if not body or not body.strip():
        raise BridgeError(
            Failure.USAGE_ERROR,
            detail="there was no message to send on standard input",
        )

    deadline = Deadline(math.inf if no_timeout else timeout)
    record = session_module.read_session(session_dir)
    has_minimax_options = max_steps is not None or required_model is not None
    if has_minimax_options and record.peer != "minimax":
        raise BridgeError(
            Failure.USAGE_ERROR,
            detail="--max-steps and --require-model are available only for a "
            "session whose recorded target is minimax",
        )

    extended = bool(attachments) or note_ref is not None or purpose is not None
    if extended and record.bridge_format != session_module.FORMAT_3:
        raise BridgeError(
            Failure.USAGE_ERROR,
            detail="--attachment, --note-ref, and --purpose require a Format 3 "
            "session created with an explicit --mode",
        )
    if note_ref is not None:
        session_module.validate_inline_value("--note-ref", note_ref)
    if purpose is not None:
        session_module.validate_inline_value("--purpose", purpose)
    if attachments and record.mode != "work":
        raise BridgeError(
            Failure.USAGE_ERROR,
            detail="--attachment is available only in a work session whose "
            "target has a qualified image route",
        )
    declared_attachments = _validate_attachments(attachments)

    if record.mode == "work":
        connector = connectors.resolve(record.peer)
        capability = connector.CAPABILITIES
        if capability.work != "supported":
            raise BridgeError(
                Failure.USAGE_ERROR,
                detail="work mode is unsupported for {0}: {1}".format(
                    record.peer, capability.work_detail
                ),
            )
        if declared_attachments and capability.image != "supported":
            raise BridgeError(
                Failure.USAGE_ERROR,
                detail="{0} has no qualified image route: {1}".format(
                    record.peer, capability.image_detail
                ),
            )
        if has_minimax_options:
            connector.validate_run_options(max_steps, required_model)
    else:
        if record.project is not None and connectors.is_courier_only(record.peer):
            raise BridgeError(
                Failure.USAGE_ERROR,
                detail="the session records a project for {0}, which is "
                "courier-only; include the needed evidence in the body or "
                "choose a project-capable target".format(record.peer),
            )
        connector = connectors.resolve(record.peer)
        if has_minimax_options:
            connector.validate_run_options(max_steps, required_model)

    events = (
        _EventReporter(event_writer) if event_writer is not None else None
    )
    published_request = None  # type: Optional[str]
    turn_warnings = []  # type: List[str]

    def report(event: Dict[str, object]) -> None:
        if events is not None:
            events.emit(event)

    def heartbeat(phase: str):
        def beat(elapsed: float, child_running: bool) -> None:
            report(
                {
                    "event": "heartbeat",
                    "phase": phase,
                    "elapsed_seconds": round(elapsed, 3),
                    "child_running": bool(child_running),
                }
            )

        return beat

    def finished_failure(exc: BaseException) -> None:
        if isinstance(exc, (SignalStop, KeyboardInterrupt)):
            outcome = "stopped"
            detail = {
                "outcome": outcome,
                "reason": str(exc) or exc.__class__.__name__,
            }
        else:
            outcome = "failure"
            if isinstance(exc, BridgeError):
                reason, next_action = guidance(exc.failure)
                if exc.detail:
                    reason = "{0} ({1})".format(reason, exc.detail)
            else:
                reason = str(exc) or exc.__class__.__name__
                next_action = (
                    "Inspect the session's visible state before deciding "
                    "whether to run the command again."
                )
            detail = {
                "outcome": outcome,
                "reason": reason,
                "next_action": next_action,
            }
        event = {
            "event": "finished",
            "phase": "run",
            "warnings": list(turn_warnings),
        }
        event.update(detail)
        if published_request is not None:
            event["request_path"] = published_request
        report(event)

    try:
        report(
            {
                "event": "started",
                "phase": "run",
                "peer": record.peer,
                "mode": record.mode,
            }
        )
        with session_lock(session_dir):
            with _target_directory(record.project) as cwd:
                deadline.check("composing the peer command")
                deadline.heartbeat = heartbeat("prerequisites")
                if record.mode == "work":
                    builder = (
                        build_work_command
                        if build_work_command is not None
                        else connector.build_work_command
                    )
                    command = builder(
                        deadline,
                        cwd,
                        access_paths=record.access_paths,
                        attachments=declared_attachments,
                        max_steps=max_steps,
                        required_model=required_model,
                    )
                elif has_minimax_options:
                    builder = build_command or connector.build_command
                    command = builder(
                        deadline,
                        cwd,
                        max_steps=max_steps,
                        required_model=required_model,
                    )
                elif build_command is None:
                    command = connector.build_command(deadline, cwd)
                else:
                    command = build_command(deadline, cwd)
                deadline.check("composing the peer command")
                if os.path.abspath(command.cwd) != os.path.abspath(cwd):
                    raise BridgeError(
                        Failure.SESSION_INVALID,
                        detail="the connector did not use the session-derived directory",
                    )
                argv, stdin_text = apply_transport(command, body)

                request_sequence = session_module.next_sequence(session_dir)
                if warning_writer is not None:
                    for warning in command.warnings:
                        warning_writer(warning)
                turn_warnings.extend(command.warnings)
                published_request = session_module.publish(
                    session_module.message_path(
                        session_dir,
                        request_sequence,
                        session_module.INITIATOR_TO_PEER_SUFFIX,
                    ),
                    session_module.initiator_to_peer_text(
                        request_sequence,
                        record.initiator,
                        record.peer,
                        body,
                        note_ref=note_ref,
                        purpose=purpose,
                        attachments=declared_attachments,
                    ),
                )

                deadline.heartbeat = heartbeat("peer-call")
                call = run_bounded(
                    argv=argv,
                    cwd=command.cwd,
                    env=command.env,
                    stdin_text=stdin_text,
                    deadline=deadline,
                )
                if call.returncode != 0:
                    raise BridgeError(
                        Failure.PEER_FAILURE,
                        detail=_peer_failure_detail(call, command, body),
                    )
                response = call.stdout
                provider = None  # type: Optional[str]
                model = None  # type: Optional[str]
                if command.response_parser is not None:
                    try:
                        response = command.response_parser(response)
                    except BridgeError as parsed:
                        raise BridgeError(
                            parsed.failure,
                            detail=_diagnostic_excerpt(
                                parsed.detail or str(parsed), body
                            ),
                        ) from None
                    if isinstance(response, connectors.AttributedText):
                        # The tool's own structured output named which
                        # provider and model answered; keep that reported
                        # identity beside the text instead of discarding it
                        # after validation.
                        provider = response.provider
                        model = response.model
                if not response.strip():
                    raise BridgeError(
                        Failure.EMPTY_RESPONSE, detail=command.argv[0]
                    )

                format_three = (
                    record.bridge_format == session_module.FORMAT_3
                )
                response_sequence = session_module.next_sequence(session_dir)
                response_path = session_module.publish(
                    session_module.message_path(
                        session_dir,
                        response_sequence,
                        session_module.PEER_TO_INITIATOR_SUFFIX,
                    ),
                    session_module.peer_to_initiator_text(
                        response_sequence,
                        record.peer,
                        record.initiator,
                        response,
                        answers=(
                            request_sequence if format_three else None
                        ),
                        model=model if format_three else None,
                        provider=provider if format_three else None,
                    ),
                )
    except SignalStop as stopped:
        finished_failure(stopped)
        raise
    except KeyboardInterrupt as interrupted:
        finished_failure(interrupted)
        raise
    except BaseException as failed:
        finished_failure(failed)
        raise

    finished = {
        "event": "finished",
        "phase": "run",
        "outcome": "success",
        "request_path": published_request,
        "response_path": response_path,
        "warnings": list(turn_warnings),
    }
    if model is not None:
        finished["model"] = model
    if provider is not None:
        finished["provider"] = provider
    report(finished)
    return TurnResult(
        request_sequence=request_sequence,
        response_sequence=response_sequence,
        response_path=response_path,
    )
