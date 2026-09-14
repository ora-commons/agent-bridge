"""The hand-written MiniMax Code courier connector.

MiniMax Code 0.2.7 has a stable headless ``mcode exec`` transport, but no
headless permission mode that confines its tools. Agent Bridge therefore gives
it only a task-owned neutral directory and reports the remaining tool and
configuration authority instead of presenting ``smart`` as a sandbox.

SPDX-License-Identifier: CC0-1.0
"""

from __future__ import annotations

import json
import math
from typing import List, Optional, Tuple

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
    """Return final text only after strict MiniMax ExecResult validation."""
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
    return text


def _prerequisites(
    deadline: Deadline, cwd: str
) -> Tuple[str, str, str, str, Tuple[str, ...]]:
    warnings = []  # type: List[str]
    program = connectors.executable(QUALIFICATION.cli_identity)
    version = connectors.qualified_version(
        connectors.probe((program, "--version"), cwd, deadline).stdout,
        QUALIFICATION,
        warnings,
    )
    described = connectors.qualified_platform(QUALIFICATION, warnings)
    connectors.qualified_restrictions(
        connectors.probe((program, "exec", "--help"), cwd, deadline),
        QUALIFICATION,
    )
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


def check(deadline: Deadline, cwd: str) -> connectors.CheckResult:
    program, version, described, account, warnings = _prerequisites(deadline, cwd)
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
