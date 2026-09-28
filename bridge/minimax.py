"""The hand-written MiniMax Code courier connector.

MiniMax Code 0.2.7 has a stable headless ``mcode exec`` transport, but no
headless permission mode that confines its tools. Agent Bridge therefore gives
its review calls only a task-owned neutral directory and reports the remaining
tool and configuration authority instead of presenting ``smart`` as a sandbox.
Work calls use the same ``exec`` under the program's own ordinary defaults and
with no permission policy selected by Bridge: the workspace comes from
``--cwd``, and the review-only one-step bound is not imposed.

SPDX-License-Identifier: CC0-1.0
"""

from __future__ import annotations

import json
import math
from typing import List, Optional, Sequence, Tuple

from . import connectors
from .errors import BridgeError, Failure
from .peer import Deadline

HARNESS_ID = "minimax"
COURIER_ONLY = True

QUALIFICATION = connectors.Qualification(
    cli_identity="mcode",
    versions=("0.2.7",),
    os_family="Darwin",
    os_major_versions=("26",),
    architectures=("arm64",),
    restrictions=(
        "--input",
        "--input-format",
        "--cwd",
        "--permission",
        "--timeout",
        "--max-steps",
        "--output-format",
    ),
)

#: What this connector offers beyond its restricted review call. Work is the
#: ordinary `mcode exec` invocation with no permission policy of Bridge's
#: choosing: the program's own headless default governs (read from its source,
#: an absent `--permission` is fixed at `smart`, and no runtime configuration
#: can change the permission mode of a headless run), `ask` needs an
#: interactive host and is rejected by `mcode exec` itself, while `full` and
#: `off` are approval bypasses Bridge never selects. Images have a native
#: attachment switch; mcode's source turns image MIME types into model image
#: content.
CAPABILITIES = connectors.Capabilities(
    work="supported",
    work_detail=(
        "work uses mcode exec with the caller's project as --cwd and no "
        "permission policy selected by Bridge: the program's own headless "
        "default (smart) governs, ask cannot run headless and is rejected "
        "by mcode exec itself, and full and off are approval bypasses "
        "Bridge never selects; no assistant-step bound is imposed unless "
        "--max-steps names one"
    ),
    image="supported",
    image_detail=(
        "images travel as native mcode exec --file attachments, which mcode "
        "classifies by MIME type and hands to the model as image content "
        "(at most 10 files and 100 MB per run)"
    ),
)

#: The switches a work turn relies on, verified against the installed
#: program's own help before any request is published. The `exec` subcommand
#: itself is proved by the help probe that carries these switches: a program
#: without it would not answer `mcode exec --help`. The review-only
#: `--permission` switch is not a work prerequisite - the work vector passes
#: no permission policy at all - and the three optional switches are required
#: only when the work vector actually emits them.
WORK_RESTRICTIONS = ("--input", "--input-format", "--cwd", "--output-format")
WORK_TIMEOUT_RESTRICTION = ("--timeout",)
WORK_ATTACHMENT_RESTRICTIONS = ("--file",)
WORK_STEPS_RESTRICTIONS = ("--max-steps",)

WORK_WARNING = (
    "MiniMax Code work runs with the program's ordinary headless defaults "
    "and no permission policy selected by this vector: mcode exec's own "
    "default governs, which its source fixes at smart when --permission is "
    "absent, and no runtime configuration can change the permission mode of "
    "a headless run. smart is a discretionary permission mode, not a "
    "sandbox, so the model's tool use is governed by MiniMax's own policy "
    "engine and by surviving user/provider configuration; ask is interactive "
    "and rejected by mcode exec, which names the TUI or ACP as its route, "
    "and full and off are approval bypasses Bridge never selects. No "
    "assistant-step bound is imposed unless --max-steps names one, so the "
    "turn deadline is the only outer bound. Writes are confined by nothing "
    "except that policy; treat the working and access directories as "
    "writable."
)

WARNING = (
    "MiniMax Code is courier-only and receives a task-owned neutral directory. "
    "--permission smart is a discretionary permission mode, not a sandbox: "
    "ask is interactive and rejected by mcode exec, while full bypasses and "
    "off disables permission checks, so the fixed vector uses none of those "
    "modes. By default, --max-steps=1 limits assistant steps; an explicitly "
    "requested positive bound may permit more. Neither form creates confinement, "
    "and a step bound does not disable tools within any permitted step. Smart "
    "does not categorically "
    "confine file writes, shell or Git "
    "commands, MCP tools, network access, or surviving user/provider "
    "configuration."
)

MAX_NATIVE_TIMEOUT_MILLISECONDS = 2_147_483_647


def _invalid_result(detail: str) -> BridgeError:
    return BridgeError(Failure.PEER_FAILURE, detail=detail)


def validate_run_options(
    max_steps: Optional[int], required_model: Optional[str]
) -> None:
    """Validate the two MiniMax-only per-run controls before prerequisites."""
    if max_steps is not None and (type(max_steps) is not int or max_steps <= 0):
        raise BridgeError(
            Failure.USAGE_ERROR,
            detail="--max-steps must be a positive integer",
        )
    if required_model is not None:
        valid_model = isinstance(required_model, str) and (
            required_model == required_model.strip()
            and len(required_model) <= 256
            and required_model.count("/") == 1
            and all(required_model.split("/", 1))
            and not any(ord(character) < 32 for character in required_model)
        )
        if not valid_model:
            raise BridgeError(
                Failure.USAGE_ERROR,
                detail="--require-model must name one exact nonempty provider/model",
            )


def parse_response(output: str, required_model: str) -> str:
    """Final text, carrying the reported identity, after strict validation.

    The validation is unchanged: a schema-version-1 successful `exec.result`
    whose `providerId/modelId` is byte-for-byte the required model. The
    return is that validated identity's own final output text, returned as
    `AttributedText` so the provider and model MiniMax itself reported -
    the exact pair just validated - travel with the answer instead of being
    discarded. To every reader that compares, publishes, or parses it, the
    value is the plain final output string.
    """
    try:
        result = json.loads(output)
    except (TypeError, ValueError) as exc:
        raise _invalid_result("minimax returned invalid JSON: {0}".format(exc))
    if not isinstance(result, dict):
        raise _invalid_result("minimax JSON output was not an object")
    schema_is_valid = type(result.get("schemaVersion")) is int and result["schemaVersion"] == 1
    if not schema_is_valid or result.get("type") != "exec.result" or result.get("status") != "succeeded":
        raise _invalid_result(
            "minimax JSON output did not report a successful schema-version-1 "
            "exec.result"
        )
    text = result.get("output")
    if not isinstance(text, str):
        raise _invalid_result("minimax successful JSON result contained no string output")
    model = result.get("model")
    provider_id = model.get("providerId") if isinstance(model, dict) else None
    model_id = model.get("modelId") if isinstance(model, dict) else None
    if not all(isinstance(value, str) and value for value in (provider_id, model_id)):
        raise _invalid_result(
            "minimax successful JSON result contained no runtime model identity"
        )
    actual_model = "{0}/{1}".format(provider_id, model_id)
    if actual_model.encode("utf-8") != required_model.encode("utf-8"):
        detail = "minimax runtime model {0!r} did not exactly match required model {1!r}"
        raise _invalid_result(detail.format(actual_model, required_model))
    return connectors.AttributedText(
        text, provider=provider_id, model=model_id
    )


def _prerequisites(
    deadline: Deadline,
    cwd: str,
    work: bool = False,
    attachments: Sequence[str] = (),
    max_steps: Optional[int] = None,
) -> Tuple[str, str, str, str, Tuple[str, ...]]:
    """Readiness facts and the switches the selected mode's vector relies on.

    A review turn proves the review vector's whole switch set, `--permission`
    included, because that vector passes them all. A work turn proves only
    what the work vector passes: the standard-input, format, and
    working-directory switches always; `--timeout` when the deadline is one
    the vector can hand to the program; `--file` when an attachment travels;
    and `--max-steps` when the caller names a bound. The review-only switches
    are not work prerequisites, because a work call passes none of them.
    Authentication stays honestly unconfirmed in both modes: MiniMax has no
    state-free noninteractive authentication check, and none is invented here.
    """
    warnings = []  # type: List[str]
    program = connectors.executable(QUALIFICATION.cli_identity)
    version = connectors.qualified_version(
        connectors.probe((program, "--version"), cwd, deadline).stdout,
        QUALIFICATION,
        warnings,
    )
    described = connectors.qualified_platform(QUALIFICATION, warnings)
    help_call = connectors.probe((program, "exec", "--help"), cwd, deadline)
    if work:
        switches = WORK_RESTRICTIONS
        if deadline.seconds <= MAX_NATIVE_TIMEOUT_MILLISECONDS / 1000.0:
            switches += WORK_TIMEOUT_RESTRICTION
        if attachments:
            switches += WORK_ATTACHMENT_RESTRICTIONS
        if max_steps is not None:
            switches += WORK_STEPS_RESTRICTIONS
        connectors.qualified_restrictions(
            help_call,
            connectors.Qualification(
                cli_identity=QUALIFICATION.cli_identity,
                versions=QUALIFICATION.versions,
                os_family=QUALIFICATION.os_family,
                os_major_versions=QUALIFICATION.os_major_versions,
                architectures=QUALIFICATION.architectures,
                restrictions=switches,
            ),
        )
        warnings.append(WORK_WARNING)
    else:
        connectors.qualified_restrictions(help_call, QUALIFICATION)
        warnings.append(WARNING)
    warnings.append(
        "MiniMax has no state-free noninteractive authentication check: "
        "provider list can initialize its runtime and refresh or invalidate "
        "OAuth state, so Agent Bridge does not run it. Live authentication "
        "remains unconfirmed until the selected bounded call."
    )
    return (
        program,
        version,
        described,
        "no state-free noninteractive authentication-status command is available",
        tuple(warnings),
    )


def check(
    deadline: Deadline, cwd: str, mode: str = "review"
) -> connectors.CheckResult:
    program, version, described, account, warnings = _prerequisites(
        deadline, cwd, work=(mode == "work")
    )
    return connectors.readiness(
        HARNESS_ID,
        program,
        version,
        described,
        account,
        warnings,
        authentication_confirmed=False,
    )


def build_command(
    deadline: Deadline,
    cwd: str,
    max_steps: Optional[int] = None,
    required_model: Optional[str] = None,
) -> connectors.PeerCommand:
    validate_run_options(max_steps, required_model)
    program, _version, _described, _account, warnings = _prerequisites(
        deadline, cwd
    )
    # MiniMax starts this timer after Bridge's deadline. Rounding up means the
    # native timer cannot win; above Node's timer domain it is omitted so a
    # valid Bridge timeout is never rejected or shortened by the child.
    native_timeout = (
        (
            "--timeout",
            "{0}ms".format(
                max(1, int(math.ceil(deadline.seconds * 1000.0)))
            ),
        )
        if deadline.seconds
        <= MAX_NATIVE_TIMEOUT_MILLISECONDS / 1000.0
        else ()
    )
    return connectors.PeerCommand(
        argv=(
            program,
            "exec",
            "--input",
            "-",
            "--input-format",
            "text",
            "--cwd",
            cwd,
            "--permission",
            "smart",
        )
        + native_timeout
        + (
            "--max-steps",
            str(max_steps if max_steps is not None else 1),
            "--output-format",
            "json" if required_model is not None else "text",
        ),
        cwd=cwd,
        env=connectors.environment(),
        warnings=warnings,
        response_parser=(
            (lambda output: parse_response(output, required_model))
            if required_model is not None
            else None
        ),
    )


def build_work_command(
    deadline: Deadline,
    cwd: str,
    access_paths: Sequence[str] = (),
    attachments: Sequence[str] = (),
    max_steps: Optional[int] = None,
    required_model: Optional[str] = None,
) -> connectors.PeerCommand:
    """The ordinary `mcode exec` work invocation, review-only bounds removed.

    The workspace is the session's working directory, named by `--cwd` as the
    program itself expects. No permission policy is selected: the vector
    passes no `--permission`, so the effective policy is mcode exec's own,
    which its source fixes at `smart` when the switch is absent - the same
    posture an ordinary headless `mcode exec` runs under, with no runtime
    configuration able to change the permission mode of a headless run.
    `ask` cannot run headless and is rejected by `mcode exec` itself with
    the TUI or ACP named as its route, and `full` and `off` are approval
    bypasses Bridge never selects, so there is no configured posture this
    vector could be silently replacing. The review call's one-assistant-step
    bound is not imposed: `--max-steps` is passed only when the caller names
    a bound, and otherwise MiniMax's own default governs the run inside
    Bridge's deadline. Each attachment becomes one `--file`, which mcode
    hands to the model as image content. Declared access directories are
    recorded in the session and stay reachable as ordinary same-user paths;
    mcode has no per-call switch that widens its workspace.
    """
    validate_run_options(max_steps, required_model)
    program, _version, _described, _account, warnings = _prerequisites(
        deadline, cwd, work=True, attachments=attachments, max_steps=max_steps
    )
    native_timeout = (
        (
            "--timeout",
            "{0}ms".format(
                max(1, int(math.ceil(deadline.seconds * 1000.0)))
            ),
        )
        if deadline.seconds
        <= MAX_NATIVE_TIMEOUT_MILLISECONDS / 1000.0
        else ()
    )
    argv = [
        program,
        "exec",
        "--input",
        "-",
        "--input-format",
        "text",
        "--cwd",
        cwd,
    ]
    argv.extend(native_timeout)
    for attachment in attachments:
        argv.extend(("--file", attachment))
    if max_steps is not None:
        argv.extend(("--max-steps", str(max_steps)))
    argv.extend(
        ("--output-format", "json" if required_model is not None else "text")
    )
    return connectors.PeerCommand(
        argv=tuple(argv),
        cwd=cwd,
        env=connectors.environment(),
        warnings=warnings,
        response_parser=(
            (lambda output: parse_response(output, required_model))
            if required_model is not None
            else None
        ),
    )
