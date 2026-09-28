"""Calling ZCode with its strongest practical read-only posture.

ZCode is Z.AI's coding agent. Its command-line program is not installed on
`PATH`: it is a JavaScript bundle shipped inside the desktop application, run by
a Node runtime, so a call is `node /Applications/ZCode.app/Contents/Resources/glm/zcode.cjs ...`,
or, on a desktop build that ships a file the bundle needs somewhere the bundle
does not look, `node` handed a link to that same bundle in a small launcher
folder, described next.
This module is the whole of what Agent Bridge knows about it: where those two
pieces are, which switches hold the boundary, how the message gets in, how the
answer comes back, and how to tell - without spending a model turn - whether
starting it would work at all.

**Why the bundle is sometimes started through a launcher folder.** Before it
answers a prompt, the bundle loads a built-in provider file, and it works out
where to look from the path it was started under - the path Node was handed,
not the place its code really lives. It tries `provider/zcode-builtin.json`
in the folder of that path, then `config/provider/zcode-builtin.json` in the
folder five levels above it. ZCode 3.14.1, whose command-line program reports
0.16.9, ships the file in `Contents/Resources/config/provider/`, which neither
lookup reaches from `Contents/Resources/glm/`, so every turn stops at once
with an error naming both places while the commands that spend no turn still
work. `ZCODE_BUILTIN_PROVIDER_BUNDLED_CONFIG_FILE` and
`ZCODE_BUILTIN_PROVIDER_CONFIG_FILE` were tried and are not consulted by that
lookup, so no variable can point it elsewhere. So when the file is missing
from where the bundle looks but present where the application ships it, this
connector starts the bundle through an owner-only launcher folder in the
user's cache directory that holds exactly two symbolic links: `zcode.cjs` to
the real bundle, and `provider/zcode-builtin.json` to the application's own
file. Node follows the first link to load the code from the real bundle, but
the path the bundle sees is the link's, so its first lookup lands on the
second link. Nothing is copied and nothing of the vendor's is changed. The
folder and its provider subfolder are refused if either is itself a link or
belongs to another account, and the two links are checked on every call, a
missing or wrong one being replaced in one atomic step. Should the vendor
restore the layout the bundle expects, the bundle is started directly again;
should the application's own file be absent too, it is started directly and
left to report its own error.

There are three operations here and nothing else. `check` answers whether ZCode
could be used right now. `build_command` composes the one fixed argument vector
a review turn runs. `build_work_command` composes the edit-mode prompt a work
turn runs. All of them do the same inexpensive prerequisites first, because a
turn that skipped them would find out about a missing runtime, a renamed switch
or a newly enabled plugin in the middle of real work, with the peer already
running.

**How the message gets in, and why this connector is the declared exception.**
Agent Bridge sends the outgoing body on standard input wherever a harness has
one. ZCode 0.16.5 has none for a one-shot prompt, and that was established by
probe, not by reading documentation: `--prompt` with no value is a parse error
before anything is read; `--prompt -` sends a literal dash, as the model's own
reply confirmed; `--attach /dev/stdin` hands the model a path that its file tool
refuses as a device file; and the complete headless option table, read out of
the installed bundle, names nothing else for a prompt. The plan therefore lets
this connector take the body as the final command-line argument, under three
conditions the runner enforces before anything is started or published: no byte
of the body may be able to begin a new argument, a body over 524288 bytes is
refused rather than truncated or spilled to a file, and the vector is passed to
the program directly with no shell.

The first condition is met by binding the body to the prompt option as one
argument, `--prompt=<body>`, and not by a bare `--`. Node's own argument parser,
run with ZCode's exact option table, settles that: a bare `--` makes whatever
follows it a positional, which ZCode reads as its command name and rejects with
"Unknown command"; `--prompt` followed by a body that begins with a hyphen is
refused as "argument is ambiguous"; `--prompt=<body>` comes back byte for byte,
with a body that began `---` and contained `--mode yolo`, `-p`, an `=` sign and
a line beginning `--disallowed-tools=`, the one pattern ZCode's own pre-parser
strips. Binding asks nothing of the parser: there is no new argument for a byte
of the body to begin. The runner adds the other two refusals, a NUL byte, which
no argument can carry, and an argument list that with the inherited environment
would not fit the operating system's limit.

One consequence is stated in the user documentation and repeated here: a
command line is visible to other processes under the same account and may be
captured by crash reporters and vendor telemetry, so a body carried this way can
reach logs outside the user's control. Standard input has no such exposure, and
is used everywhere it exists.

**How the answer comes back.** `--output-format text` puts the final answer,
and only the final answer, on standard output; on success the error stream is
empty, and on failure the program writes `Error: ...` there and exits nonzero.
ZCode prepends a reminder of its own about plan mode to what the model sees, so
the peer reads the body after a short block of the harness's text; the body
itself arrives whole.

**The switches, and what they really are.**

`--disallowed-tools <names>` is hard-enforced: each name is removed from the
tool set when the session is built, so a removed tool does not exist for the
model to call, and the same list is handed to every subagent the model starts.
Two facts about it, from the installed program, matter to anyone extending
this. An entry is reduced to the name before any opening parenthesis, so
`Bash(git *)` removes the whole Bash tool, not a pattern of commands. And a tool
from an MCP server is removed only by its exact name, `mcp__<server>__<tool>`,
known only once that server has started. The list this connector passes removes
every built-in tool that writes, runs, reaches out, delegates, schedules, asks
a person, or reads other sessions; what remains is Read, Glob, Grep and the
session's own to-do list.

`--mode plan` is ZCode's own enforced read-only posture, put on top of the
removed tools rather than instead of them. Its rules, read from the program,
allow a tool that is read-only and not destructive, deny everything else that
reaches them, and allow any MCP tool whose server does not mark it destructive.
That last rule is why the plugin check below exists.

`--cwd <path>` names the working directory, and it is given the very directory
the process is started in, so the two cannot drift apart. It comes from the
command line only; nothing under a message's `## Body` heading is read anywhere
in Agent Bridge.

Four switches that `--help` advertises do not exist on 0.16.5: `--settings`,
`--max-turns`, `--allowed-tools` and `--permission-mode` are each rejected as
an unknown option, on a subcommand and in prompt mode alike, and the bundle's
strict parser has no entry for them. On this build `--help` is not a reliable
description of the program. So readiness proves the switches it relies on by
passing them to a subcommand that spends no turn, not only by reading the help.

**Persistent configuration, reported before every call.** No switch on this
build sheds the user's enabled plugins or MCP servers for one call, and plan
mode admits non-destructive MCP tools; a probe on this machine showed a peer
under plan mode and the full deny list still holding nineteen iOS-simulator
tools from an enabled plugin. Both operations therefore read ZCode's own
`plugins list --json`, which spends no turn, and report any enabled plugin that
declares or resolves an MCP server or carries a hook. Unreadable inventory is
also reported rather than treated as proof that none exists. Skills and slash
commands do not become model-callable routes here: the Skill tool is in the
deny list, and a slash command is not something the model can call. What this
check cannot see is an MCP server configured directly in the user's
configuration file rather than by a plugin: ZCode lists those only inside a
session, at the cost of a turn, and the file itself holds the sign-in key and
is never opened here. The warning states that uncertainty plainly.

**Authentication, and what can honestly be said about it.** ZCode has no command
that reports sign-in without a model turn. `zcode login` is not a status check:
it unconditionally starts a fresh Z.AI OAuth flow, opens a browser, waits for
the callback, writes the OAuth tokens to a shared credential store, then
exchanges the access token over the network for a coding-plan key and rewrites
the program's own configuration file with that key, replacing whatever key was
there. What the program itself treats as "signed in" is that configuration file
holding a coding-plan provider with a non-empty key; the OAuth store is not
consulted for that, and a headless turn authenticates with the configured key.
That was shown without opening anything: `ZCODE_DATA_BASE_DIR` is the one
variable that relocates the credential store, so it was pointed at an empty
directory and a headless turn was run; the turn succeeded, which it could not
have done had the store been what authenticates it.

That has a consequence worth stating plainly. A key placed in that file by hand
and a key minted by the sanctioned login are the same field, put to the same
use, and nothing in the program tells them apart. The sanctioned and
unsanctioned arrangements differ only in provenance, and provenance is
established by write history: a completed login writes the credential store and
then, a second or two later, the configuration file. That pair of timestamps is
the one thing readiness can observe without opening either file, and it is
reported as an observation about provenance, never as proof of a working
sign-in. It is also an observation about a moment: the configuration file is
rewritten by ordinary settings changes too, such as enabling or disabling a
plugin, and after one of those the pair no longer lines up, which says nothing
about where the key came from. Nothing here opens, prints, copies or compares a credential; only file
names and modification times are looked at. Readiness therefore reports what is
observable - which files are present, whether their last writes have the
login's order and spacing, and whether an API-key environment variable is set -
and says outright that sign-in itself is not confirmed.

**What readiness costs.** Nothing. Where the runtime is, whether the bundle is
at its documented place, whether it can find its provider file (and, only when
it cannot, the launcher's two links, checked and if need be remade),
`--version`, `--help`, `version` with the switches the turn relies on,
`plugins list --json`, and the modification times of two files. No model turn
among them.

SPDX-License-Identifier: CC0-1.0
"""

from __future__ import annotations

import json
import os
import stat
import uuid
from typing import List, Optional, Sequence, Tuple

from . import connectors
from .errors import BridgeError, Failure
from .peer import Deadline

#: The identifier this connector answers to, out of the six.
HARNESS_ID = "zcode"

#: The runtime the bundle needs. Found on PATH like any other program; ZCode's
#: own diagnostics report the Node it was started with, and that is the one used.
RUNTIME = "node"

#: Where the desktop application keeps the command-line program. There is no
#: `zcode` on PATH to find; this is the documented location of the bundle.
SCRIPT = "/Applications/ZCode.app/Contents/Resources/glm/zcode.cjs"

#: Where the bundle first looks for its built-in provider file, relative to the
#: folder of the path it was started under. Found there, the bundle is started
#: directly, as it always was.
PROVIDER_FILE = os.path.join("provider", "zcode-builtin.json")

#: Where the desktop application itself ships that provider file. ZCode 3.14.1
#: puts it here, where neither of the bundle's own lookups reaches from `SCRIPT`.
BUILTIN_PROVIDER = (
    "/Applications/ZCode.app/Contents/Resources/config/provider/"
    "zcode-builtin.json"
)

#: The per-user folder the bundle is started from when its provider file is
#: only at `BUILTIN_PROVIDER`: two symbolic links and nothing else. It is under
#: the macOS cache directory because the application exists only on macOS.
LAUNCHER = os.path.join("~", "Library", "Caches", "agent-bridge", "zcode-launcher")

#: What this connector has actually been tested against, declared in source and
#: never inferred from the machine it is running on. `restrictions` names the
#: exact switches the vector below passes to hold the boundary: remove the tools that
#: could write or reach out, run under the enforced planning posture, and take
#: the working root from the command line.
QUALIFICATION = connectors.Qualification(
    cli_identity="zcode",
    versions=("0.16.5",),
    os_family="Darwin",
    os_major_versions=("26",),
    architectures=("arm64",),
    restrictions=(
        "--disallowed-tools",
        "--mode",
        "--cwd",
    ),
)

#: What this connector offers beyond its restricted review call. Work is
#: ZCode's own `edit` permission mode - never `yolo`, which is the mode a bare
#: `--prompt` defaults to and which auto-approves everything. Images have a
#: native attachment switch that feeds the model real inline image content.
CAPABILITIES = connectors.Capabilities(
    work="supported",
    work_detail=(
        "work uses zcode --mode edit, ZCode's own permission mode in which "
        "workspace file edits are allowed and every other approval-needing "
        "tool is denied by the deny broker a headless prompt uses; yolo is "
        "never selected"
    ),
    image="supported",
    image_detail=(
        "images travel as native --prompt attachments via --attach, which "
        "ZCode reads and hands to the model as inline image content"
    ),
)

#: The switches a work turn relies on, looked for in the help text this build
#: prints reliably for them and proven together by the no-turn parser probe
#: below, which passes them to a subcommand that spends no model turn.
#: `--attach` is required only when an attachment travels, because a plain
#: work turn never passes it. The review-only `--disallowed-tools` switch is
#: not a work prerequisite: the work vector never passes it, so the work-mode
#: parser probe does not pass it either.
WORK_RESTRICTIONS = ("--prompt", "--mode", "--cwd")
WORK_ATTACHMENT_RESTRICTIONS = ("--attach",)

WORK_WARNING = (
    "ZCode work runs in edit mode: workspace file edits are allowed "
    "automatically, and any other tool that would need approval is denied, "
    "because a headless prompt has no approver and ZCode's default broker "
    "denies rather than asks. The review call's tool deny list is not "
    "applied, so the ordinary tool set is available under those rules, and "
    "enabled plugins and directly configured MCP servers keep whatever routes "
    "they already had. The prompt default for --prompt is yolo; this vector "
    "overrides it with edit on every call."
)

#: The prefix the body is bound to as the final argument. One argument, so no
#: byte of the body can begin another; see the module docstring for why a bare
#: `--` cannot do this job on ZCode's parser.
BODY_ARGUMENT = "--prompt="

#: How the answer is asked for: the final response alone, on standard output.
#: Not printed by `--help`, so it is proven by the no-turn probe rather than
#: looked for in the help text.
OUTPUT_FORMAT = ("--output-format", "text")

#: The built-in tools removed from the peer, as one comma-separated value so the
#: option cannot go on swallowing the switches that follow it. Everything that
#: writes, runs, reaches out, delegates, schedules, changes mode, asks a person
#: or reads other sessions. Read, Glob and Grep stay, because a peer that cannot
#: read the project cannot answer about it.
DENIED_TOOLS = ",".join(
    (
        "Write",
        "Edit",
        "ApplyPatch",
        "NotebookEdit",
        "Bash",
        "WebFetch",
        "WebSearch",
        "Agent",
        "Task",
        "TaskOutput",
        "TaskStop",
        "Skill",
        "Workflow",
        "SendMessage",
        "RespondToCoordinator",
        "AskUserQuestion",
        "EnterPlanMode",
        "ExitPlanMode",
        "TodoWrite",
        "ReadSessionContext",
        "CronCreate",
        "CronList",
        "CronUpdate",
        "CronDelete",
        "js",
        "js_reset",
        "js_add_node_module_dir",
        "mcp__node_repl__js",
        "mcp__node_repl__js_reset",
        "mcp__node_repl__js_add_node_module_dir",
    )
)

#: The program's own configuration file - the place its sign-in test looks.
CONFIG_FILE = os.path.join("~", ".zcode", "cli", "config.json")

#: The shared credential store the login writes, relative to a base directory
#: that is the home directory unless this variable names another.
CREDENTIALS_FILE = os.path.join(".zcode", "v2", "credentials.json")
DATA_BASE_DIR_VARIABLE = "ZCODE_DATA_BASE_DIR"

#: An environment variable the program would take an API key from.
API_KEY_VARIABLE = "ZCODE_API_KEY"

#: How far apart the login's two writes may be and still read as one login.
LOGIN_PAIR_SECONDS = 60.0


def _program() -> Tuple[str, str]:
    """Where the runtime is and what path the bundle is started under.

    The runtime is looked up on PATH the way every other harness program is.
    The bundle is looked for at its one documented place; nothing is searched
    for, and nothing is installed or put on PATH. Either missing is
    `MISSING_CLI` naming which. The second value is the path handed to Node:
    `SCRIPT` itself, or the launcher's link to it, as `_entry` decides.
    """
    runtime = connectors.executable(RUNTIME)
    if not os.path.isfile(SCRIPT):
        raise BridgeError(
            Failure.MISSING_CLI,
            detail="the ZCode desktop application's command-line bundle is "
            "not at {0}".format(SCRIPT),
        )
    return runtime, _entry()


def _entry() -> str:
    """The bundle itself, or its link in the launcher folder, made safe first.

    The bundle is started directly when its provider file is where its own
    first lookup lands - the layout a vendor fix would restore - and also when
    the application's own copy at `BUILTIN_PROVIDER` is absent, so that what a
    person then sees is the bundle's own error rather than one of ours. Only in
    between, with the file shipped where the application keeps it and nowhere
    the bundle looks, is the launcher made or repaired and its link returned.
    A launcher that cannot be made or trusted is `MISSING_CLI` naming the folder
    and the reason, raised here and so before any request is published.
    """
    if os.path.isfile(os.path.join(os.path.dirname(SCRIPT), PROVIDER_FILE)):
        return SCRIPT
    if not os.path.isfile(BUILTIN_PROVIDER):
        return SCRIPT
    launcher = os.path.expanduser(LAUNCHER)
    entry = os.path.join(launcher, os.path.basename(SCRIPT))
    try:
        _private_folder(launcher)
        _private_folder(os.path.join(launcher, os.path.dirname(PROVIDER_FILE)))
        _link(entry, SCRIPT)
        _link(os.path.join(launcher, PROVIDER_FILE), BUILTIN_PROVIDER)
    except OSError as error:
        raise BridgeError(
            Failure.MISSING_CLI,
            detail="the ZCode bundle does not look for its built-in provider "
            "file at {0}, where the application ships it, and the launcher "
            "folder at {1} that lets it find the file could not be prepared: "
            "{2}".format(BUILTIN_PROVIDER, launcher, error),
        )
    return entry


def _private_folder(path: str) -> None:
    """Make `path` an owner-only folder of this account's, or refuse it.

    Created, with any missing parents, if it is absent. It is refused, not
    repaired, if it is itself a symbolic link or anything but a folder, or
    belongs to another account, because either would let something other than
    this account decide what Node runs. One of this account's own whose
    permissions have been opened up is closed to owner-only again.
    """
    os.makedirs(path, mode=0o700, exist_ok=True)
    status = os.lstat(path)
    if not stat.S_ISDIR(status.st_mode):
        raise OSError(
            "{0} is a symbolic link or something other than a folder".format(
                path
            )
        )
    if status.st_uid != os.getuid():
        raise OSError("{0} belongs to another account".format(path))
    if stat.S_IMODE(status.st_mode) != 0o700:
        os.chmod(path, 0o700)


def _link(path: str, target: str) -> None:
    """Make `path` a symbolic link to `target`, replacing whatever is there.

    Left alone when it already is exactly that link. Otherwise the new link is
    made under a name no other call can choose, in the same folder, and renamed
    over `path` in one step, so two calls repairing it at once each leave a
    whole link behind and neither can see a half-made one. A link that cannot be
    put in place is removed again before the error goes on.
    """
    try:
        if os.readlink(path) == target:
            return
    except OSError:
        pass  # Absent, or not a link: replaced below either way.
    temporary = os.path.join(
        os.path.dirname(path),
        ".{0}.{1}.tmp".format(os.path.basename(path), uuid.uuid4().hex),
    )
    os.symlink(target, temporary)
    try:
        os.replace(temporary, path)
    except OSError:
        try:
            os.remove(temporary)
        except OSError:
            pass
        raise


def _modified(path: str) -> Optional[float]:
    """When a file was last written, by metadata only; None if it is absent."""
    try:
        return os.stat(path).st_mtime
    except OSError:
        return None


def _sign_in_facts() -> str:
    """What can be observed about sign-in without a turn and without reading.

    ZCode's own sign-in test is a coding-plan key inside its configuration
    file, so a missing configuration file is not signed in by the program's own
    rule and is reported as `AUTHENTICATION_REQUIRED`. Beyond that, only
    presence and modification times are looked at: whether the shared credential
    store is there, whether the two files were last written in the order and
    spacing of the login routine, and whether an API-key variable is set. The
    sentence says outright that sign-in is not confirmed, because it is not.
    """
    config = os.path.expanduser(CONFIG_FILE)
    config_written = _modified(config)
    if config_written is None:
        raise BridgeError(
            Failure.AUTHENTICATION_REQUIRED,
            detail="ZCode's own sign-in test is a coding-plan key in {0}, "
            "which is absent".format(config),
        )
    base = os.environ.get(DATA_BASE_DIR_VARIABLE) or os.path.expanduser("~")
    credentials = os.path.join(base, CREDENTIALS_FILE)
    credentials_written = _modified(credentials)

    parts = ["its configuration file is present at {0}".format(config)]
    if credentials_written is None:
        parts.append(
            "the shared credential store at {0} is absent".format(credentials)
        )
    else:
        gap = config_written - credentials_written
        if 0.0 <= gap <= LOGIN_PAIR_SECONDS:
            parts.append(
                "the shared credential store at {0} is present and the two "
                "were last written in the order and spacing of ZCode's own "
                "login routine (the store first, the configuration file "
                "{1:.1f}s later)".format(credentials, gap)
            )
        else:
            parts.append(
                "the shared credential store at {0} is present but the two "
                "were not last written as one login writes them (the "
                "configuration file is also rewritten by ordinary settings "
                "changes, such as enabling or disabling a plugin)".format(
                    credentials
                )
            )
    if os.environ.get(API_KEY_VARIABLE):
        parts.append(
            "{0} is set in this environment, which ZCode would use as an API "
            "key rather than a login".format(API_KEY_VARIABLE)
        )
    parts.append(
        "sign-in itself is not confirmed, because ZCode offers no command "
        "that reports it without spending a model turn"
    )
    return "; ".join(parts)


def _names(value: object) -> List[str]:
    """The strings in a list the program printed, and nothing else."""
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]


def _plugin_fact(
    runtime: str, script: str, deadline: Deadline, cwd: str
) -> str:
    """Describe exposed plugin routes without turning uncertainty into refusal.

    The listing is read in either of the two shapes ZCode has printed it in:
    an object whose `plugins` entry is the list, as 0.16.5 prints it, or the
    list on its own, as 0.16.9 does. Each plugin in it is handled the same way
    whichever shape carried it.
    """
    try:
        listing = connectors.probe(
            (runtime, script, "plugins", "list", "--json"), cwd, deadline
        )
    except BridgeError as error:
        return (
            "the plugin inventory could not be inspected ({0}), so enabled "
            "plugin hooks and MCP servers are unknown"
        ).format(error.failure.value)
    parsed = None
    if listing.returncode == 0:
        try:
            parsed = json.loads(listing.stdout)
        except ValueError:
            parsed = None
    plugins = parsed.get("plugins") if isinstance(parsed, dict) else parsed
    if not isinstance(plugins, list):
        return (
            "zcode plugins list --json could not be read (exit {0}: {1}), "
            "so enabled plugin hooks and MCP servers are unknown"
        ).format(
                listing.returncode,
                (listing.stderr or listing.stdout).strip()[:160],
        )

    enabled = 0
    exposing = []
    for plugin in plugins:
        if not isinstance(plugin, dict) or plugin.get("enabled") is not True:
            continue
        enabled += 1
        servers = []  # type: List[str]
        for name in _names(plugin.get("declaredMcpServerNames")) + _names(
            plugin.get("mcpServerNames")
        ):
            if name not in servers:
                servers.append(name)
        hooks = plugin.get("hookDetails")
        hook_count = len(hooks) if isinstance(hooks, list) else 0
        if not servers and not hook_count:
            continue
        what = []
        if servers:
            what.append("MCP server {0}".format(", ".join(servers)))
        if hook_count:
            what.append("{0} hook(s)".format(hook_count))
        exposing.append(
            "{0} ({1})".format(
                plugin.get("id") or plugin.get("name") or "an unnamed plugin",
                "; ".join(what),
            )
        )
    if exposing:
        return (
            "enabled plugins expose routes ZCode has no per-call switch to "
            "shed: {0}"
        ).format("; ".join(exposing))
    return (
        "no enabled plugin declares an MCP server or a hook ({0} of {1} "
        "installed plugins enabled)".format(enabled, len(plugins))
    )


def _prerequisites(
    deadline: Deadline,
    cwd: str,
    work: bool = False,
    attachments: Sequence[str] = (),
) -> Tuple[str, str, str, str, Tuple[str, ...]]:
    """Everything that has to be true before starting ZCode is worth doing.

    Seven questions in order, each cheap and none a model turn: is the runtime
    here, is the bundle here, is its version one this connector was tested
    against, is this computer one it was tested on, what can be observed about
    sign-in, does any enabled plugin expose what no switch can remove, and are
    the switches the turn relies on really accepted - proven by passing them to
    a subcommand that spends no turn, because this program's help text lists
    switches its parser rejects. The switch set is the vector's own: a review
    turn proves the review switches, deny list included, and a work turn
    proves the work switches - `--prompt`, `--mode edit`, `--cwd`,
    `--output-format`, and `--attach` when an attachment travels - without the
    review deny list, which a work call never passes. Missing software,
    minimum local sign-in state, or required mechanics raises; plugin exposure
    or uncertainty and the lack of live OAuth evidence are returned as
    warnings.

    Returns the four facts a readiness report needs and a turn uses: the
    program as it is started, which version answered, how this computer
    describes itself, and what was observed about sign-in and plugins.
    """
    warnings = []  # type: List[str]
    runtime, script = _program()
    version = connectors.qualified_version(
        connectors.probe((runtime, script, "--version"), cwd, deadline).stdout,
        QUALIFICATION,
        warnings,
    )
    described = connectors.qualified_platform(QUALIFICATION, warnings)
    sign_in = _sign_in_facts()
    plugins = _plugin_fact(runtime, script, deadline, cwd)

    help_call = connectors.probe((runtime, script, "--help"), cwd, deadline)
    if work:
        switches = WORK_RESTRICTIONS
        if attachments:
            switches += WORK_ATTACHMENT_RESTRICTIONS
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
        parser_switches = ("--mode", "edit", "--cwd", cwd)
        parser_names = ("--mode", "--cwd") + OUTPUT_FORMAT[:1]
    else:
        connectors.qualified_restrictions(help_call, QUALIFICATION)
        parser_switches = ("--disallowed-tools", "Edit", "--mode", "plan", "--cwd", cwd)
        parser_names = QUALIFICATION.restrictions + OUTPUT_FORMAT[:1]
    accepted = connectors.probe(
        (runtime, script, "version") + parser_switches + OUTPUT_FORMAT,
        cwd,
        deadline,
    )
    if accepted.returncode != 0 or version not in accepted.stdout:
        raise BridgeError(
            Failure.RESTRICTIONS_UNAVAILABLE,
            detail="zcode rejected {0} on a subcommand that spends no turn: "
            "{1}".format(
                ", ".join(parser_names),
                (accepted.stderr or accepted.stdout).strip()[:160],
            ),
        )
    mode = "edit" if work else "plan"
    if work:
        warnings.append(WORK_WARNING)
    warnings.append(
        "ZCode cannot shed enabled plugins or directly configured MCP "
        "servers per call, and {0} mode may admit non-destructive MCP tools; "
        "{1}. {2}.".format(mode, plugins, sign_in)
    )
    warnings.append(
        "ZCode receives the complete message in one --prompt argument, which "
        "may be visible to other processes under the same account or to logs."
    )
    return (
        "{0} {1}".format(runtime, script),
        version,
        described,
        "minimum local configuration needed to attempt a call is present",
        tuple(warnings),
    )


def check(
    deadline: Deadline, cwd: str, mode: str = "review"
) -> connectors.CheckResult:
    """Report whether ZCode could be used right now, spending no model turn.

    `cwd` is a neutral directory made for this command, so the questions are
    asked somewhere with nothing in it. No real project is touched, nothing
    is installed, nobody is logged in, no model or provider is chosen, and
    nothing is written down for next time. The one thing that may be written is the
    launcher's pair of links, when the bundle needs them to be started at all;
    they hold no state and are checked again by every call. A work-mode check
    proves the work vector's own switches - and, in the no-turn parser probe,
    passes no review deny-list switch the work command never carries.
    """
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


def build_command(deadline: Deadline, cwd: str) -> connectors.PeerCommand:
    """The fixed argument vector for one turn, prerequisites confirmed first.

    The runner calls this inside the turn's own deadline, which is why the
    prerequisites are repeated here rather than trusted from an earlier
    readiness check: readiness may have been established days ago, or never,
    and a plugin may have been enabled since.

    `cwd` is the directory the peer may read - the project named on the command
    line, or the neutral empty directory a turn without a project gets. It is
    both where the program is started and what `--cwd` names. The body is not
    here: the runner binds it to `BODY_ARGUMENT` as the final argument, after
    its own refusals, and sends nothing on standard input.
    """
    runtime, script = _program()
    _program_name, _version, _described, _account, warnings = _prerequisites(
        deadline, cwd
    )
    return connectors.PeerCommand(
        argv=(
            runtime,
            script,
            "--mode",
            "plan",
            "--cwd",
            cwd,
            "--disallowed-tools",
            DENIED_TOOLS,
        )
        + OUTPUT_FORMAT,
        cwd=cwd,
        env=connectors.environment(),
        body_argument=BODY_ARGUMENT,
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
    """The ordinary ZCode prompt in `edit` mode, with its real tool set.

    Two things from the review vector are deliberately absent: the tool deny
    list, because work needs the ordinary tool set, and `plan` mode. The mode
    a bare `--prompt` would get is `yolo`, which auto-approves everything, so
    the vector names `edit` on every call: workspace file edits are allowed,
    and anything else that would need an approval is denied - a headless
    prompt has no approver, and ZCode's default broker denies rather than
    asks. Declared access directories are recorded in the session and stay
    reachable as ordinary same-user paths; ZCode has no per-call switch that
    widens its working root. Each attachment becomes one `--attach`, which
    ZCode reads and hands to the model as inline image content.
    """
    runtime, script = _program()
    _program_name, _version, _described, _account, warnings = _prerequisites(
        deadline, cwd, work=True, attachments=attachments
    )
    argv = [runtime, script, "--mode", "edit", "--cwd", cwd]
    for attachment in attachments:
        argv.extend(("--attach", attachment))
    argv.extend(OUTPUT_FORMAT)
    return connectors.PeerCommand(
        argv=tuple(argv),
        cwd=cwd,
        env=connectors.environment(),
        body_argument=BODY_ARGUMENT,
        warnings=warnings,
    )
