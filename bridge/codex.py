"""Calling Codex with its strongest practical read-only posture, and its ordinary work posture.

Codex is OpenAI's own command-line program for its coding agent. This module is
the whole of what Agent Bridge knows about it: which program to start, which
switches must be on it, and how to tell - without spending a model turn -
whether starting it would work at all.

There are three operations here and nothing else. `check` answers whether Codex
could be used right now. `build_command` composes the one fixed argument vector
a review turn runs. `build_work_command` composes the ordinary configured
`codex exec` a work turn runs. All of them do the same inexpensive
prerequisites first (the work ones adding the work vector's own switches),
because a turn that skipped them would find out about a missing sign-in or a
renamed switch in the middle of real work, with the peer already running.

**How the answer comes back.** `codex exec` puts its banner, the prompt it was
handed, its warnings and its errors on the error stream, and puts only the final
agent message on standard output. That separation is what lets the runner
publish what it captured as the peer's reply, word for word, without editing
anything out of it. The prompt travels the other way, on standard input, and the
lone `-` says so out loud: with no prompt argument Codex would read standard
input anyway, and naming it is what makes the handover deliberate rather than
incidental.

**The switches, and why none of them is decoration.**

`--ignore-user-config` skips `$CODEX_HOME/config.toml`, including any model or
effort defaults stored only there. It does not suppress trusted-project
`.codex/config.toml` files and project hooks or rules, system configuration,
`managed_config.toml`, `requirements.toml`, cloud-delivered requirements,
macOS MDM preferences, or separately sourced user/global hooks and rules. The
fixed vector therefore overrides every compatible high-risk route it can name,
and the connector reports the surviving configuration boundary rather than
claiming that the flag removes it. Signing in survives because authentication
is read from `CODEX_HOME` rather than from that file.

`--sandbox read-only` is Codex's own enforced sandbox, not a request to be
careful. A shell may still exist inside the turn; what it cannot do is write.
It is passed by the review vector only: a work turn passes no sandbox switch at
all, because the sandbox the user configured is part of the ordinary posture a
work call exists to preserve, and a switch of Bridge's choosing - widening or
narrowing - would silently replace it. `--skip-git-repo-check` is there because
the neutral directory a turn without a project runs in is not a Git repository,
and Codex otherwise refuses to start outside one. `--cd` names the working
root, and it is given the very directory the process is started in, so the two
cannot drift apart.

Four switches are deliberately never passed, and the reason is the same each
time: every one of them hands back something the switches above have just taken
away. Three are self-evident - `--ephemeral`,
`--dangerously-bypass-approvals-and-sandbox` and
`--dangerously-bypass-hook-trust`. The fourth, `--ignore-rules`, is the subtle
one: it drops the user's *own* execution-policy rules, so despite the sound of
it, it is a loosening.

**What readiness costs.** Nothing. Four cheap questions, no model turn among
them: where the program is, `codex --version`, `codex login status`, and
`codex exec --help`. The sign-in answer is read from the exit status rather
than from the words, because Codex prints `Logged in using ChatGPT` on the error
stream along with everything else it has to say about itself.

SPDX-License-Identifier: CC0-1.0
"""

from __future__ import annotations

import os
import re
from typing import List, Optional, Sequence, Tuple

from . import connectors
from .errors import BridgeError, Failure
from .peer import Deadline

#: The identifier this connector answers to, out of the six.
HARNESS_ID = "codex"

#: What this connector has actually been tested against, declared in source and
#: never inferred from the machine it is running on. `restrictions` names the
#: exact switches the vector below passes to hold the boundary: skip the main
#: user config, override compatible high-risk routes, use the enforced read-only
#: sandbox, work outside a Git repository, and name the working root.
QUALIFICATION = connectors.Qualification(
    cli_identity="codex",
    versions=("0.147.0",),
    os_family="Darwin",
    os_major_versions=("26",),
    architectures=("arm64",),
    restrictions=(
        "--ignore-user-config",
        "-c",
        "--disable",
        "--sandbox",
        "--skip-git-repo-check",
        "--cd",
    ),
)

WARNING = (
    "--ignore-user-config skips only $CODEX_HOME/config.toml, including any "
    "model and effort defaults stored there; Agent Bridge supplies no "
    "replacement. Trusted-project .codex/config.toml files and project hooks "
    "or rules, system configuration, managed_config.toml, requirements.toml, "
    "cloud-delivered requirements, macOS MDM preferences, and separately "
    "sourced user/global hooks or rules can still apply. Those layers can add "
    "settings the fixed vector does not override, while managed defaults or "
    "MDM can override CLI options. The fixed scalar controls disable known "
    "web search, notify, "
    "hooks, apps, plugins, Codex Apps MCP, and agent routes, but named MCP "
    "servers, plugins, hooks, network, telemetry, or other integrations from "
    "surviving configuration may still retain external-effect routes outside "
    "the read-only shell sandbox."
)

#: What this connector offers beyond its restricted review call. The work
#: route is the ordinary configured `codex exec` with no sandbox switch: the
#: effective sandbox is whatever codex itself resolves from the user's
#: configuration or its own default, and an effective read-only posture - the
#: out-of-box default - is refused before publication with the terminal route.
#: The image route is Codex's native `-i/--image` attachment.
CAPABILITIES = connectors.Capabilities(
    work="supported",
    work_detail=(
        "work uses the ordinary configured codex exec (the user's own model, "
        "effort, and configuration) with no sandbox switch of Bridge's "
        "choosing: the effective sandbox is the one codex resolves from "
        "sandbox_mode in $CODEX_HOME/config.toml or its own default, and a "
        "work call under an effective read-only posture is refused before "
        "publication with the limitation and the terminal route; --add-dir "
        "adds writable roots under a writable posture"
    ),
    image="supported",
    image_detail=(
        "images travel as native codex exec -i/--image attachments"
    ),
)

#: The switches beyond the review set that a work turn relies on, verified
#: against the installed program's own help before any request is published.
WORK_RESTRICTIONS = (
    "--add-dir",
    "--image",
)

#: The sandbox postures `codex exec` accepts, and the posture it runs in when
#: nothing configures a wider one. The default is the vendor's own documented
#: sentence for non-interactive mode: "By default, `codex exec` runs in a
#: read-only sandbox."
SANDBOX_MODES = ("read-only", "workspace-write", "danger-full-access")
DEFAULT_SANDBOX = "read-only"
DEFAULT_SANDBOX_ORIGIN = (
    "codex's own default: codex exec runs read-only when nothing configures "
    "a wider sandbox"
)

#: One top-level `sandbox_mode = "..."` line in codex's config.toml. Matched
#: only before the first table header, so a `[projects."..."]` table or any
#: other section cannot be misread as the user's sandbox posture.
_SANDBOX_LINE = re.compile(
    r"""sandbox_mode\s*=\s*["']([A-Za-z0-9_-]+)["']"""
)


def _effective_sandbox() -> Tuple[str, str]:
    """The sandbox posture codex itself would run a work turn under.

    Codex resolves its sandbox from a `--sandbox` switch first (a work vector
    passes none), then `sandbox_mode` at the top of `$CODEX_HOME/config.toml`
    (the same file `--ignore-user-config` names, whose default home is
    `~/.codex`), then its own built-in default, which is read-only for exec.
    That order and that default were established on the installed program:
    `codex debug prompt-input` renders the effective policy through codex's
    own configuration pipeline and reported read-only under an empty home,
    exactly the configured value under each of the three settings, and the
    vendor's non-interactive documentation states the default in the same
    words. Only the one scalar is read here, and anything that cannot be
    resolved - an unreadable file, an unrecognized value - is returned
    unresolved rather than guessed at, because a wrong guess is how a posture
    comes to be silently replaced.

    Returns the posture (empty when unresolved) and where it came from, in
    words, for the warning that names it. What this cannot see - profiles,
    a trusted-project `.codex/config.toml`, `managed_config.toml`,
    `requirements.toml`, cloud or MDM policy - can change what codex actually
    enforces, and codex enforces its own resolution at run time whatever this
    returns; the work warning says so.
    """
    home = os.environ.get("CODEX_HOME") or os.path.expanduser(
        os.path.join("~", ".codex")
    )
    path = os.path.join(home, "config.toml")
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as stream:
            lines = stream.readlines()
    except FileNotFoundError:
        return DEFAULT_SANDBOX, DEFAULT_SANDBOX_ORIGIN
    except OSError as error:
        return "", "{0} could not be read ({1})".format(path, error)
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("["):
            break
        if stripped.startswith("#"):
            continue
        matched = _SANDBOX_LINE.match(stripped)
        if matched is not None:
            value = matched.group(1)
            if value in SANDBOX_MODES:
                return value, "sandbox_mode set in {0}".format(path)
            return "", (
                "{0} sets a sandbox_mode this connector does not recognize "
                "({1!r})".format(path, value)
            )
    return DEFAULT_SANDBOX, DEFAULT_SANDBOX_ORIGIN


def _sandbox_limits(posture: str) -> str:
    """What the named posture confines, in the posture's own words."""
    if posture == "workspace-write":
        return (
            "Codex's workspace-write sandbox confines writes to the working "
            "directory and any declared --add-dir directory; codex exec "
            "cannot ask for an interactive approval, so a command the "
            "sandbox refuses fails rather than prompts."
        )
    if posture == "danger-full-access":
        return (
            "Under danger-full-access codex itself reports no filesystem "
            "sandboxing and network access enabled: writes are not "
            "confined. Passing no switch is what preserves that configured "
            "choice rather than silently narrowing it."
        )
    return (
        "codex exec cannot write the files authorized work needs under a "
        "read-only sandbox and has no interactive approver to escalate to, "
        "so a work call under it is refused before publication; run codex "
        "in its own terminal for this work, where its approval flow can ask "
        "you directly, or set sandbox_mode in codex's own configuration to "
        "a posture that permits the authorized work."
    )


def _work_warning(posture: str, origin: str) -> str:
    """The concrete boundary of one work call under the resolved posture."""
    if posture in SANDBOX_MODES:
        return (
            "Codex work runs with the user's ordinary configuration: model, "
            "effort, hooks, MCP servers, plugins, and network settings the "
            "user or surviving policy layers configure all apply, and none "
            "of the review call's feature disables are inherited. No "
            "sandbox switch is passed: the effective sandbox is {0} ({1}). "
            "{2} External effects that configuration makes available (web "
            "search, notify, network, telemetry) remain possible and are "
            "the caller's responsibility to authorize. Layers this warning "
            "cannot read - a trusted-project .codex/config.toml, "
            "managed_config.toml, requirements.toml, cloud or MDM policy - "
            "can change the posture codex actually enforces.".format(
                posture, origin, _sandbox_limits(posture)
            )
        )
    return (
        "Codex work runs with the user's ordinary configuration and no "
        "sandbox switch of Bridge's choosing, but the effective sandbox "
        "posture could not be resolved: {0}. Codex's own enforced posture "
        "at run time governs; its built-in default is read-only, under "
        "which headless work cannot write, so the call may fail inside "
        "codex if nothing wider is configured. External effects that "
        "configuration makes available (web search, notify, network, "
        "telemetry) remain possible and are the caller's responsibility "
        "to authorize.".format(origin)
    )


def _prerequisites(
    deadline: Deadline, cwd: str, work: bool = False
) -> Tuple[str, str, str, Tuple[str, ...]]:
    """Everything that has to be true before starting Codex is worth doing.

    Five questions in order, each one cheap and none of them a model turn: is
    the program here, is its version one this connector was tested against, is
    this computer one it was tested on, is somebody signed in, and does the
    installed version still have every switch the turn relies on - the review
    set, plus the work set when a work turn is being composed. Any of them
    failing raises, so nothing further happens.

    Returns the three facts a readiness report needs and a turn uses: where
    the program is, which version answered, and how this computer describes itself.
    """
    warnings = []  # type: List[str]
    program = connectors.executable(QUALIFICATION.cli_identity)
    version = connectors.qualified_version(
        connectors.probe((program, "--version"), cwd, deadline).stdout,
        QUALIFICATION,
        warnings,
    )
    described = connectors.qualified_platform(QUALIFICATION, warnings)

    signed_in = connectors.probe((program, "login", "status"), cwd, deadline)
    if signed_in.returncode != 0:
        raise BridgeError(
            Failure.AUTHENTICATION_REQUIRED,
            detail="codex login status exited {0}".format(
                signed_in.returncode
            ),
        )

    help_call = connectors.probe((program, "exec", "--help"), cwd, deadline)
    connectors.qualified_restrictions(help_call, QUALIFICATION)
    if work:
        connectors.qualified_restrictions(
            help_call,
            connectors.Qualification(
                cli_identity=QUALIFICATION.cli_identity,
                versions=QUALIFICATION.versions,
                os_family=QUALIFICATION.os_family,
                os_major_versions=QUALIFICATION.os_major_versions,
                architectures=QUALIFICATION.architectures,
                restrictions=WORK_RESTRICTIONS,
            ),
        )
        posture, origin = _effective_sandbox()
        warnings.append(_work_warning(posture, origin))
    else:
        warnings.append(WARNING)
    return program, version, described, tuple(warnings)


def check(
    deadline: Deadline, cwd: str, mode: str = "review"
) -> connectors.CheckResult:
    """Report whether Codex could be used right now, spending no model turn.

    `cwd` is a neutral directory made for this command, so the questions below
    are asked somewhere with nothing in it. No real project is touched, nothing
    is installed, nobody is logged in, no model or provider is chosen, and
    nothing is written down for next time. A work-mode check also proves the
    work vector's own switches exist on the installed version.
    """
    program, version, described, warnings = _prerequisites(
        deadline, cwd, work=(mode == "work")
    )
    return connectors.readiness(
        HARNESS_ID, program, version, described, "signed in", warnings
    )


def build_command(deadline: Deadline, cwd: str) -> connectors.PeerCommand:
    """The fixed argument vector for one turn, prerequisites confirmed first.

    The runner calls this inside the turn's own deadline, which is why the
    prerequisites are repeated here rather than trusted from an earlier
    readiness check: readiness may have been established days ago, or never.

    `cwd` is the directory the peer may read - the project named on the command
    line, or the neutral empty directory a turn without a project gets. It comes
    from the command line only. Nothing under a message's `## Body` heading is
    read anywhere in Agent Bridge, so no text a peer or a plan wrote can name a
    directory here.
    """
    program, _version, _described, warnings = _prerequisites(deadline, cwd)
    return connectors.PeerCommand(
        argv=(
            program,
            "exec",
            "--ignore-user-config",
            "-c",
            "web_search=disabled",
            "-c",
            "notify=[]",
            "--disable",
            "hooks",
            "--disable",
            "apps",
            "--disable",
            "plugins",
            "-c",
            "orchestrator.mcp.enabled=false",
            "-c",
            "agents.enabled=false",
            "--disable",
            "multi_agent_v2",
            "--sandbox",
            "read-only",
            "--skip-git-repo-check",
            "--cd",
            cwd,
            "-",
        ),
        cwd=cwd,
        env=connectors.environment(),
        warnings=warnings,
    )


def build_work_command(
    deadline: Deadline,
    cwd: str,
    access_paths: Sequence[str] = (),
    attachments: Sequence[str] = (),
    max_steps: Optional[int] = None,
    required_model: Optional[str] = None,
) -> connectors.PeerCommand:
    """The ordinary configured `codex exec`, under the user's own sandbox.

    Everything the review vector passes to keep the target read-only is left
    out here: no `--ignore-user-config`, so the user's own model, effort, and
    configuration apply exactly as an interactive Codex session would read
    them, and none of the review feature disables are inherited. No sandbox
    switch is passed either, for the same reason: the sandbox the user
    configured - or codex's own default when they have not - is part of the
    ordinary posture a work call exists to preserve, and any switch of
    Bridge's choosing would silently replace it, widening a read-only
    configuration or narrowing a full-access one. `--add-dir` still names
    each access directory, which codex makes writable under a
    workspace-confining posture, and `-i` is how an attached image reaches
    the model as real input.

    One posture cannot do this work headlessly, and it is refused here,
    before anything is published: read-only, whether the user set it or
    codex's out-of-box default applies it, because `codex exec` under it
    cannot write the files authorized work needs and has no interactive
    approver to escalate to. The refusal names the posture, its origin, and
    the terminal route. An unresolvable configuration is not guessed at -
    the call proceeds under codex's own enforcement with that stated in its
    warning, since passing a switch to resolve the doubt is the replacement
    this builder exists not to perform.
    """
    program, _version, _described, warnings = _prerequisites(
        deadline, cwd, work=True
    )
    posture, origin = _effective_sandbox()
    if posture == "read-only":
        raise BridgeError(
            Failure.WORK_POSTURE_UNAVAILABLE,
            detail=(
                "codex's effective sandbox posture is read-only ({0})".format(
                    origin
                )
            ),
        )
    argv = [
        program,
        "exec",
        "--skip-git-repo-check",
        "--cd",
        cwd,
    ]
    for path in access_paths:
        argv.extend(("--add-dir", path))
    for attachment in attachments:
        argv.extend(("--image", attachment))
    argv.append("-")
    return connectors.PeerCommand(
        argv=tuple(argv),
        cwd=cwd,
        env=connectors.environment(),
        warnings=warnings,
    )
