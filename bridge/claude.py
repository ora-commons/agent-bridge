"""Calling Claude Code with its strongest practical read-only posture, and its normal work posture.

Claude Code is Anthropic's own command-line program for its coding agent. This
module is the whole of what Agent Bridge knows about it: which program to start,
which switches must be on it, and how to tell - without spending a model turn -
whether starting it would work at all.

There are three operations here and nothing else. `check` answers whether Claude
Code could be used right now. `build_command` composes the one fixed argument
vector a review turn runs. `build_work_command` composes the normal `--print`
route a work turn runs. All of them do the same inexpensive prerequisites first,
and the work ones skip every review-only gate and fact - the managed-MCP source,
the endpoint-policy and doctor readings, and the review switch set - proving the
work vector's own switches instead, because a work turn passes none of the
review switches and discards both policy readings; a turn that skipped the rest
would find out about a missing sign-in or a renamed switch in the middle of real
work, with the peer already running.

**How the answer comes back.** `--print` with no prompt argument reads the
prompt from standard input, and `--output-format text` puts the final answer,
and only the final answer, on standard output; everything the program has to say
about itself goes to the error stream. That separation is what lets the runner
publish what it captured as the peer's reply, word for word.

**The switches, and why none of them is decoration.**

`--restricted` is the one that carries most of the weight. It takes away the
built-in tools that run commands or code, and WebFetch with them, unless
`--tools` names them back - which this connector never does. It ignores the
user's, the project's and the local settings files, so a turn is not shaped by
whatever happens to be configured on the machine. It confines the file tools to
the working directory the process was started in. And it refuses the
permission mode that would bypass permission checks altogether.
Administrator-managed endpoint and remote policy deliberately survive this
mode, so the connector observes their presence or uncertainty without opening
policy values and reports that boundary as a warning. The exact
``managed-mcp.json`` source is different: this CLI exits when strict MCP is
combined with it, so its presence or an unreadable pathname is refused before
request publication.

`--strict-mcp-config` says to use only the MCP servers named by `--mcp-config`.
No `--mcp-config` is passed, so that set is empty: the turn reaches no MCP
server at all, whatever is configured elsewhere.

`--tools Read,Glob,Grep` says which of the built-in tools survive. Reading files,
finding them by name, and searching inside them are all a peer needs to inspect a
repository and answer about it. Everything that edits, runs, fetches, publishes
or messages is simply not there.

`--permission-mode plan` is the harness's own enforced read-only posture, put on
top of the three above rather than instead of them. Defaults are never trusted
here: every one of these is passed on every call, even though some of them
overlap.

Five switches are deliberately never passed. `--dangerously-skip-permissions`
and `--allow-dangerously-skip-permissions` undo the boundary outright.
`--continue` and `--resume` would carry a previous conversation into this turn,
and every call Agent Bridge makes is a fresh one - the session record on disk is
the memory, not the harness's own history. `--bare` is the surprising one: it
sounds like less, but it abandons subscription sign-in and insists on an API
key instead, which is the opposite of leaving the harness's own authentication
where it already lives.

**There is no working-directory switch, and none is needed.** Claude Code works
in the directory its process was started in, so that directory is the mechanism,
and `--restricted` is what confines the file tools to it.

**What readiness costs.** Nothing. Four cheap questions for a review turn, no
model turn among them: where the program is, `claude --version`, `claude auth
status --json`, and `claude --help`, with `claude doctor` read once for the
remote-policy fact. A work-mode check asks three of the four - where the
program is, the version, and the sign-in - and then proves the work vector's
own switches from the help, skipping the doctor question and the policy
readings alike, because the boundary they describe is the review call's and
work mode discards their answers. The sign-in answer is JSON, so it is read
rather than guessed at: being signed in is required, and how - by subscription
rather than by an API key - is reported as an observed fact and gates nothing,
because choosing providers is not this project's business.

SPDX-License-Identifier: CC0-1.0
"""

from __future__ import annotations

import errno
import json
import os
import pwd
from typing import List, Optional, Sequence, Tuple

from . import connectors
from .errors import BridgeError, Failure
from .peer import CompletedCall, Deadline

#: The identifier this connector answers to, out of the six.
HARNESS_ID = "claude"

#: What this connector has actually been tested against, declared in source and
#: never inferred from the machine it is running on. `restrictions` names the
#: exact switches the vector below passes to hold the boundary: restricted mode,
#: no MCP servers, a named set of read-only tools, and the harness's own
#: enforced planning posture.
QUALIFICATION = connectors.Qualification(
    cli_identity="claude",
    versions=("2.1.251",),
    os_family="Darwin",
    os_major_versions=("26",),
    architectures=("arm64",),
    restrictions=(
        "--restricted",
        "--strict-mcp-config",
        "--tools",
        "--permission-mode",
    ),
)

#: The built-in tools a peer keeps: read a file, find files by name, search
#: inside them. Passed as one comma-separated value so the option cannot go on
#: swallowing the switches that follow it.
READ_ONLY_TOOLS = "Read,Glob,Grep"

#: What this connector offers beyond its restricted review call. Work is the
#: normal `claude --print` route with no permission flag at all - whatever the
#: user's own settings and Claude Code's ordinary default permission behavior
#: allow is what the call may do. Images have no attachment switch on this
#: CLI; the one qualified route is Claude Code's own file-reading tool, which
#: presents an image to the model when the request body names its path.
CAPABILITIES = connectors.Capabilities(
    work="supported",
    work_detail=(
        "work uses the normal claude --print route with no permission flag, "
        "so the user's settings and Claude Code's ordinary default permission "
        "behavior decide what the call may do; --add-dir widens tool access "
        "to declared access directories"
    ),
    image="supported",
    image_detail=(
        "images travel by Claude Code's own file-reading tool: the request "
        "body must name the attached image's absolute path, and the model "
        "reads the pixels with it"
    ),
)

#: The switches a work turn relies on, verified against the installed
#: program's own help before any request is published: the one-shot route and
#: the switch that isolates the final answer on standard output. The
#: review-only restriction set is not a work prerequisite - a work vector
#: passes none of those switches, so their absence cannot make a work call
#: unusable - and neither is `--add-dir` unless the session declares an
#: access directory, because a plain work turn never passes it.
WORK_RESTRICTIONS = ("--print", "--output-format")
WORK_ACCESS_RESTRICTIONS = ("--add-dir",)

WORK_WARNING = (
    "Claude Code work runs on its normal route: user, project, and local "
    "settings files apply (the review call's --restricted ignored them), "
    "administrator-managed and remote policy can still add hooks or other "
    "external effects, and no permission flag is passed, so the permission "
    "behavior is whatever the user's own configuration and Claude Code's "
    "default headless policy make it. In a --print call nobody can answer an "
    "interactive permission prompt, so a tool the configuration does not "
    "allow is denied rather than asked about."
)

IMAGE_ROUTE_WARNING = (
    "This attachment reaches the model only through Claude Code's "
    "file-reading tool, so the request body must name the image's absolute "
    "path; recording the attachment alone does not deliver pixels."
)

# Claude Code 2.1.251's own policy loader and current official documentation
# agree on these macOS sources. Restricted mode deliberately keeps the
# administrator tier, so their presence is a boundary fact rather than a user
# preference Agent Bridge may override.
MANAGED_DIRECTORY = "/Library/Application Support/ClaudeCode"
MANAGED_SETTINGS = os.path.join(MANAGED_DIRECTORY, "managed-settings.json")
MANAGED_DROP_INS = os.path.join(MANAGED_DIRECTORY, "managed-settings.d")
MANAGED_MCP = os.path.join(MANAGED_DIRECTORY, "managed-mcp.json")
MANAGED_PREFERENCES_DIRECTORY = "/Library/Managed Preferences"
MANAGED_PREFERENCES_DOMAIN = "com.anthropic.claudecode.plist"

REMOTE_STATUS_PREFIX = "Managed settings (remote): "
REMOTE_STATUS_WITHOUT_POLICY = (
    "none configured for this organization",
    "not fetched \u2014 requires an Enterprise or Team subscription",
)


def _managed_source_paths() -> Tuple[str, str, str, str, str]:
    """The endpoint-managed paths this exact macOS CLI probes.

    The user name comes from the operating-system account database, matching
    the CLI's own ``userInfo().username`` lookup rather than an environment
    variable a caller could replace.
    """
    username = pwd.getpwuid(os.getuid()).pw_name
    return (
        MANAGED_SETTINGS,
        MANAGED_DROP_INS,
        MANAGED_MCP,
        os.path.join(
            MANAGED_PREFERENCES_DIRECTORY,
            username,
            MANAGED_PREFERENCES_DOMAIN,
        ),
        os.path.join(
            MANAGED_PREFERENCES_DIRECTORY,
            MANAGED_PREFERENCES_DOMAIN,
        ),
    )


def _require_managed_mcp_absent() -> None:
    """Refuse the exact managed MCP source that strict mode cannot override.

    Claude Code 2.1.251 exits when ``--strict-mcp-config`` is combined with
    this source. Presence therefore makes the fixed call unusable rather than
    merely less confined. ``lstat`` establishes presence without following a
    link or opening policy contents; uncertainty must fail for the same reason.
    """
    managed_mcp = _managed_source_paths()[2]
    try:
        os.lstat(managed_mcp)
    except OSError as exc:
        if exc.errno in (errno.ENOENT, errno.ENOTDIR):
            return
        raise BridgeError(
            Failure.RESTRICTIONS_UNAVAILABLE,
            detail=(
                "the managed MCP source at {0} could not be safely inspected "
                "without opening it ({1}); Claude Code's strict MCP call "
                "cannot be relied on"
            ).format(managed_mcp, exc.__class__.__name__),
        )
    raise BridgeError(
        Failure.RESTRICTIONS_UNAVAILABLE,
        detail=(
            "the managed MCP source is present at {0}; Claude Code exits when "
            "--strict-mcp-config is used, so no request was published; policy "
            "contents were not opened"
        ).format(managed_mcp),
    )


def _endpoint_managed_settings_fact() -> str:
    """Describe the other endpoint policy sources without opening values."""
    settings, drop_ins, _managed_mcp, user_plist, device_plist = (
        _managed_source_paths()
    )

    unknown = []  # type: List[str]

    def present_or_unknown(path: str) -> bool:
        try:
            os.lstat(path)
        except OSError as exc:
            if exc.errno in (errno.ENOENT, errno.ENOTDIR):
                return False
            unknown.append(
                "{0} ({1})".format(path, exc.__class__.__name__)
            )
            return False
        return True

    present = []
    for path in (settings, user_plist, device_plist):
        if present_or_unknown(path):
            present.append(path)

    if present_or_unknown(drop_ins):
        if not os.path.isdir(drop_ins):
            present.append(drop_ins)
        else:
            try:
                names = os.listdir(drop_ins)
            except OSError as exc:
                unknown.append(
                    "{0} ({1})".format(drop_ins, exc.__class__.__name__)
                )
            else:
                present.extend(
                    os.path.join(drop_ins, name)
                    for name in sorted(names)
                    if name.endswith(".json") and not name.startswith(".")
                )

    facts = []
    if present:
        facts.append(
            "endpoint-managed policy sources are present at {0}".format(
                ", ".join(present)
            )
        )
    else:
        facts.append("no endpoint-managed policy source was observed")
    if unknown:
        facts.append("inspection was inconclusive at {0}".format(", ".join(unknown)))
    facts.append("policy values were not opened")
    return "; ".join(facts)


def _remote_managed_settings_fact(
    program: str, deadline: Deadline, cwd: str
) -> str:
    """Describe Claude's no-turn remote-policy status, or its uncertainty."""
    try:
        report = connectors.probe((program, "doctor"), cwd, deadline)
    except BridgeError as error:
        return (
            "claude doctor could not inspect remote managed settings ({0}); "
            "their state is unknown"
        ).format(error.failure.value)
    if report.returncode != 0:
        return (
            "claude doctor exited {0}, so remote managed-settings state is "
            "unknown"
        ).format(report.returncode)
    states = [
        line[len(REMOTE_STATUS_PREFIX) :].strip()
        for line in report.stdout.splitlines()
        if line.startswith(REMOTE_STATUS_PREFIX)
    ]
    if len(states) == 1 and states[0]:
        return "claude doctor reports remote managed settings: {0}".format(
            states[0]
        )
    return (
        "claude doctor did not print one readable remote managed-settings "
        "status, so their state is unknown"
    )


def _signed_in(status: CompletedCall) -> str:
    """Read Claude Code's own answer about who is signed in, and say it plainly.

    Being signed in is the requirement, and it is taken from the harness's own
    JSON rather than inferred from anything. How the sign-in was made is
    reported alongside it - the method, the provider, and the subscription when
    there is one - because that is what tells a reader the harness is on its
    subscription rather than on an API key. None of it decides anything: this
    project chooses no provider, no model and no plan.

    An answer that cannot be read at all is treated as not being signed in. It
    is not literally the same thing, but the one useful next action is: sign in
    with the harness's own command and look again.
    """
    if status.returncode != 0:
        raise BridgeError(
            Failure.AUTHENTICATION_REQUIRED,
            detail="claude auth status exited {0}".format(status.returncode),
        )
    try:
        answer = json.loads(status.stdout)
    except ValueError as exc:
        raise BridgeError(
            Failure.AUTHENTICATION_REQUIRED,
            detail="claude auth status printed no readable JSON: {0}".format(
                exc
            ),
        )
    if not isinstance(answer, dict) or answer.get("loggedIn") is not True:
        raise BridgeError(
            Failure.AUTHENTICATION_REQUIRED,
            detail="claude auth status does not report being logged in",
        )
    described = "signed in through {0} on {1}".format(
        answer.get("authMethod") or "an unnamed method",
        answer.get("apiProvider") or "an unnamed provider",
    )
    subscription = answer.get("subscriptionType")
    if subscription:
        described += " with a {0} subscription".format(subscription)
    return described


def _prerequisites(
    deadline: Deadline, cwd: str, work: bool = False, access_paths: Sequence[str] = ()
) -> Tuple[str, str, str, str, Tuple[str, ...]]:
    """Everything that has to be true before starting Claude Code is worth doing.

    A review turn asks its questions in order, each one cheap and none of them
    a model turn: is the program here, is the exact managed MCP source absent
    (a review-call requirement only, because the strict-MCP switch that cannot
    be combined with it is a review switch), is its version one this connector
    was tested against, is this computer one it was tested on, is somebody
    signed in, what does `claude doctor` say about remote managed settings,
    and does the installed version still have every review switch the vector
    relies on. A work turn asks the first five and stops there: it proves the
    work vector's own switches - `--print`, `--output-format`, and `--add-dir`
    when the session declares an access directory - and asks neither the
    doctor question nor the endpoint-policy readings, because both describe
    the review call's boundary and work mode discards their answers. Any
    failing question raises, so nothing further happens.

    Returns the four facts a readiness report needs and a turn uses: where the
    program is, which version answered, how this computer describes itself, and
    how the sign-in was made.
    """
    warnings = []  # type: List[str]
    program = connectors.executable(QUALIFICATION.cli_identity)
    if not work:
        _require_managed_mcp_absent()
    version = connectors.qualified_version(
        connectors.probe((program, "--version"), cwd, deadline).stdout,
        QUALIFICATION,
        warnings,
    )
    described = connectors.qualified_platform(QUALIFICATION, warnings)

    account = _signed_in(
        connectors.probe(
            (program, "auth", "status", "--json"), cwd, deadline
        )
    )

    remote_policy = None
    if not work:
        remote_policy = _remote_managed_settings_fact(program, deadline, cwd)
    help_call = connectors.probe((program, "--help"), cwd, deadline)
    if work:
        switches = WORK_RESTRICTIONS
        if access_paths:
            switches += WORK_ACCESS_RESTRICTIONS
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
        endpoint_policy = _endpoint_managed_settings_fact()
        connectors.qualified_restrictions(help_call, QUALIFICATION)
        warnings.append(
            "Claude Code's --restricted, strict empty MCP, read-only tool, and "
            "planning posture still keeps administrator-managed endpoint and "
            "remote policy, which can add hooks or other external effects; "
            "{0}; {1}.".format(
                endpoint_policy, remote_policy
            )
        )
    return (
        program,
        version,
        described,
        account,
        tuple(warnings),
    )


def check(
    deadline: Deadline, cwd: str, mode: str = "review"
) -> connectors.CheckResult:
    """Report whether Claude Code could be used right now, spending no turn.

    `cwd` is a neutral directory made for this command, so the questions below
    are asked somewhere with nothing in it. No real project is touched, nothing
    is installed, nobody is logged in, no model or provider is chosen, and
    nothing is written down for next time. A work-mode check proves the work
    vector's own switches exist on the installed version and asks none of the
    review-only questions, whose answers work mode discards.
    """
    program, version, described, account, warnings = _prerequisites(
        deadline, cwd, work=(mode == "work")
    )
    return connectors.readiness(
        HARNESS_ID, program, version, described, account, warnings
    )


def build_command(deadline: Deadline, cwd: str) -> connectors.PeerCommand:
    """The fixed argument vector for one turn, prerequisites confirmed first.

    The runner calls this inside the turn's own deadline, which is why the
    prerequisites are repeated here rather than trusted from an earlier
    readiness check: readiness may have been established days ago, or never.

    `cwd` is the directory the peer may read - the project named on the command
    line, or the neutral empty directory a turn without a project gets. It is
    both where the program is started and, because of `--restricted`, the limit
    of what its file tools can reach. It comes from the command line only.
    Nothing under a message's `## Body` heading is read anywhere in Agent
    Bridge, so no text a peer or a plan wrote can name a directory here.
    """
    program, _version, _described, _account, warnings = _prerequisites(
        deadline, cwd
    )
    return connectors.PeerCommand(
        argv=(
            program,
            "--print",
            "--restricted",
            "--strict-mcp-config",
            "--tools",
            READ_ONLY_TOOLS,
            "--permission-mode",
            "plan",
            "--output-format",
            "text",
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
    """The normal `claude --print` route, with no permission flag passed.

    None of the review call's restrictions travel into a work turn: not the
    restricted mode, not the empty strict MCP set, not the read-only tool
    list, not the planning permission mode. What the call may do is exactly
    what the user's own settings and Claude Code's ordinary default headless
    permission behavior allow - headless calls cannot answer an interactive
    prompt, so a tool the configuration does not permit is denied rather than
    asked about. `--add-dir` widens tool access to each declared access
    directory. An attached image has no switch on this CLI: it reaches the
    model through Claude Code's file-reading tool when the request body names
    its path, so that truth is warned about whenever one is attached.
    """
    program, _version, _described, _account, warnings = _prerequisites(
        deadline, cwd, work=True, access_paths=access_paths
    )
    argv = [program, "--print", "--output-format", "text"]
    for path in access_paths:
        argv.extend(("--add-dir", path))
    if attachments:
        warnings = tuple(warnings) + (IMAGE_ROUTE_WARNING,)
    return connectors.PeerCommand(
        argv=tuple(argv),
        cwd=cwd,
        env=connectors.environment(),
        warnings=warnings,
    )
