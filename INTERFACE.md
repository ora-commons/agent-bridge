# Agent Bridge — Courier and Work-Mode Interface

**Status:** Release 1 courier contract, approved September 3, 2026. All six targets have passed real calls on macOS 26 arm64, including Qwen's corrected stream transport. The exercised CLI versions are listed in the README. The opt-in working mode (Format 3 sessions, JSON readiness, lifecycle events, per-connector work vectors and image routes) was added September 27, 2026 under the authorized work-mode plan; its live qualification evidence is in section 8a. Qualification does not by itself complete the release finish line in section 12.

This is the controlling boundary for the shared runner, six target connectors, and thin initiating adapters. It replaces the former exactly-four-target rule and the former rule that incomplete confinement stopped release.

SPDX-License-Identifier: CC0-1.0

---

## 1. Purpose and boundary

Agent Bridge is a standalone one-to-many Markdown courier. Any application or coding-agent harness may initiate a session and make one bounded call at a time to a supported target whose vendor CLI is installed, signed in, and qualified.

Agent Bridge owns:

- target readiness;
- one request and one response per foreground call;
- an ordered, human-readable Markdown record;
- the selected CLI's strongest practical restriction posture and clear warnings about what it cannot guarantee;
- one lock per session, atomic publication, deadlines, and cleanup; and
- plain failures with one useful next action when a call cannot work.

It does not plan, coordinate, choose targets, combine answers, schedule work, judge a response, run a Programming Loop, approve anything, manage Git, or enforce an application workflow. It has no model API layer, database, daemon, task ledger, plugin discovery, application registry, or dynamic connector registry.

Applications own the meaning of what they send. Ora Vibe Coder or any other caller may put plans, commits, reviews, decisions, or state in the Markdown body. To Agent Bridge those remain inert text.

### Same-user trust boundary

Agent Bridge treats each target CLI as a trusted program running under the user's operating-system account. It does not claim to stop that program reading other files the account can read, and is not a confidentiality boundary against a malicious harness or prompt injection.

A target given a project may load its `AGENTS.md`, `CLAUDE.md`, or equivalent instructions. Agent Bridge does not suppress them. Target CLIs may also keep plaintext transcripts; Agent Bridge neither deletes nor hides them.

Repository instructions and message text cannot alter the connector's fixed invocation, grant Bridge authority, or become a Bridge command. Users should call only harnesses they trust and should not use Bridge when same-user read access is unacceptable.

Bridge states remaining limits as warnings during `check` and immediately before a warned `run` publishes its request. Warnings are informational: they do not stop an otherwise usable call, ask for acknowledgment, require an approval switch, or create persistent consent.

---

## 2. Runtime and safe text transport

One standard-library Python implementation serves every initiator and target. Python 3.9 is the floor; release evidence names the tested operating-system versions and architectures.

Every child starts from a fixed argument vector with no shell. A connector uses standard input when its CLI has a stable one-shot input path. Otherwise it may bind the complete body into one vendor option value only when qualification proves:

1. Leading hyphens cannot become options.
2. The body is one argument in a directly executed vector, never a shell fragment.
3. NUL input and a body too large for the platform argument block are refused before request publication, never truncated or split.
4. Documentation states that command-line text may be visible to same-user processes and system or vendor logs.

The runner never creates a private prompt file. The canonical request records the original exactly and the connector passes it unchanged.

Qwen's connector internally encodes that body as one stream-JSON user frame whose decoded content is the original string, then closes standard input. It supplies no initial query, prompt argument, control request, history, or additional frame. This avoids Qwen's text-input conversion into its sandbox shell arguments. The public body remains plain Markdown; only the connector translates framing. Qwen's stream reader has no text-mode 8 MiB cutoff; no unlimited-memory guarantee is implied.

Adapters start Bridge as a fixed vector:

```text
python3 -m bridge <command> ...
```

---

## 3. Initiators and targets

### Initiators

Any application or harness may initiate. It supplies one inert ASCII slug beginning with a letter or digit and continuing with letters, digits, periods, underscores, or hyphens.

The label appears in `SESSION.md` and message headers. It is not authentication, authority, routing, discovery, registration, or proof that the initiator is callable. Examples include `ora`, `gear-3`, `vibe-coder`, `codex`, and `my-app`.

Supporting another initiator never requires a Bridge code change or release.
The initiator starts the existing fixed command vectors from the checkout root,
supplies complete Markdown through standard input, keeps standard output,
standard error, and exit status distinct, and reads a response only after exit
0. For example, Vibe Coder may use `vibe-coder` as the label and pass its
prepared handoff to a user-selected existing target. Vibe's lifecycle and
approval behavior remain Vibe's; no `vibe-coder` connector belongs here.

### Callable targets

Release 1 has exactly six target identifiers:

```text
codex   claude   zcode   hermes   minimax   qwen
```

They are literal source entries resolved by a branch-local six-way switch. Each branch matches its identifier before importing that connector. There is no eager import, name-derived import, search, registry, generator, marketplace, provider fallback, or attempt to try another target.

For `check` and `run`, every unselected connector remains completely inert: no import, inspection, probe, process, project access, login, network call, or fallback. Target validation during `record` imports no connector.

An initiator label may equal a target identifier, but that neither calls anything nor grants target status. Only the immutable `Peer:` session field selects a connector.

One session has one initiator and one target. An application reaches several targets through separate sessions; Bridge does not fan out or coordinate them. Codex, Claude Code, and ZCode are project-capable. Hermes Agent, MiniMax Code, and Qwen Code are courier-only and receive a task-owned neutral directory with no project path.

---

## 4. Commands

```text
python3 -m bridge check --peer <target-id>
                 [--mode review|work] [--json]

python3 -m bridge run --session <session-directory>
                 [--timeout <seconds>]
                 [--max-steps <positive-integer>]
                 [--require-model <provider/model>]
                 [--events-jsonl]
                 [--attachment <absolute-image-path>]...
                 [--note-ref <id>] [--purpose <label>]

python3 -m bridge record --session <session-directory>
                    --kind session-create
                    --initiator <label>
                    --peer <target-id>
                    [--project <project-directory>]
                    [--mode review|work]
                    [--access-path <directory>]...

python3 -m bridge record --session <session-directory>
                    --kind note
```

Run these commands from the absolute checkout root. Source installation creates no `agent-bridge` console executable.

Omitting every extended option keeps the original Format 2 behavior byte for byte: the same records, the same stdout, the same review vectors. Each extension below is opt-in.

### `check`

`check` determines whether a target can be used now. Without a model call it finds the documented CLI, reads version and platform, checks authentication as far as the CLI safely permits, and confirms that the switches needed for fixed input, output, foreground control, and the connector's strongest practical posture still exist. `--mode work` additionally proves the work vector's own switches exist and reports the connector's work and image capability facts; it changes nothing else.

It runs in a task-owned neutral directory and never touches a real project, installs, signs in, selects a model or provider, or writes qualification state. Success writes one readiness sentence followed by any applicable `Warning:` lines to standard output, leaves standard error empty, and exits 0; warnings do not change that status. A hard failure writes one reason and next action to standard error and exits nonzero. No other connector is imported or examined.

#### `check --json`

`--json` replaces the prose with exactly one JSON object on standard output, one line, no schema version. Success and failure alike produce one object; a failure still exits nonzero.

```json
{"peer": "codex", "mode": "work", "ready": true,
 "executable": "/usr/local/bin/codex", "version": "0.155.1",
 "platform": "Darwin 26 arm64",
 "authentication": "confirmed",
 "work": "supported", "image": "supported",
 "warnings": ["...one concrete warning per line..."]}
```

| Field | Values and meaning |
|---|---|
| `peer`, `mode` | The selected target and the posture checked (`review` or `work`). |
| `ready` | Whether the selected mode's call mechanics are usable now. A successful local check does not prove the selected model will answer or that every future permission is available. |
| `executable`, `version`, `platform` | Observed facts about the installed program, or `null` when a failure happened before they could be read. |
| `authentication` | `confirmed` (the CLI reported a sign-in), `required` (the CLI reported none; the object carries the reason), or `unknown` (this CLI offers no safe no-turn check; unknown is not failure when the route is usable). |
| `work`, `image` | `supported` (a route is implemented and its switches verified present), `unsupported` (a genuine vendor limitation, named in `warnings` with the terminal route), or `unknown`. Supported means transport support; whether the model accepted a live work call or image is stated in `warnings`, which distinguish verified evidence from unverified acceptance. |
| `warnings` | The same concrete non-blocking warnings the prose interface prints, plus the capability-detail sentence for any `unsupported` value. |
| `reason`, `next_action` | Present when `ready` is false: what happened and the one useful next action. |

### `run`

`run` reads the session's initiator, target, and optional project, then reads one nonempty Markdown body from standard input. It resolves only that target, repeats cheap prerequisites, validates transport, and determines current warnings. It writes any `Warning:` lines to standard error immediately before publishing the request, then starts exactly one bounded target CLI invocation, captures its final text, and atomically publishes the response.

Warnings never prompt, wait for acknowledgment, read an approval flag, or persist consent. A readable version outside exercised evidence may proceed with a warning when every required switch and the fixed one-shot transport remain usable.

Every run starts a fresh vendor context. Bridge neither resumes a vendor session nor sends earlier Bridge messages. An application needing history includes it in the current body.

`--max-steps` and `--require-model` are run-only MiniMax controls and are
refused for every other recorded target before request publication. An explicit
positive step bound replaces MiniMax's default of one assistant step for that
call only. A required model changes MiniMax's internal output to JSON; Bridge
accepts only a successful schema-version-1 `exec.result` whose reported
`providerId/modelId` is byte-for-byte identical, then publishes only the final
string output. This validates runtime identity and does not select a provider or
model. Omitting both controls preserves the existing one-step plain-text call.
In a work session, `--max-steps` is forwarded when given and omitted otherwise,
so the review-only one-step assumption does not apply to work.

`--timeout` is one deadline for prerequisites, target execution, and response capture, defaulting to 900 seconds. Cleanup has a separate bounded grace period. There is no retry.

A courier-only project session cannot run in review mode: Bridge refuses before connector import or request publication and tells the application to include evidence in the body or choose a project-capable target. A work session runs against the connector's work vector (section 4a); a work session whose target declares work unsupported is refused the same way, with the real limitation and the terminal route in the message.

`--note-ref` and `--purpose` store two inert single-line strings in a Format 3 request header: an opaque pairing with a caller note and a name for the request's purpose. Bridge records them without interpreting them or using them to choose authority, files, or workflow. They are refused on a Format 2 session so legacy records never change shape.

`--attachment` names an absolute image file to deliver with the request. It is repeatable, recorded as one `Attachment:` header line per file, accepted only for a Format 3 **work** session whose target has a qualified image route, and validated to exist before anything is published. The exact request body is never modified to mention an attachment; where the route needs the path in the text (Claude), the caller's body must name it and the run warning says so. Missing files, unsupported formats, tool limitations, and model rejection are reported as real failures; the caller owns and retains the original images.

`--events-jsonl` replaces the response-path line on standard output with one JSON object per line describing the turn's lifecycle (section 4b). Standard error remains diagnostics.

Success without `--events-jsonl` writes only the response path to standard output and exits 0. With `--events-jsonl`, standard output carries only event lines and the final `finished` event carries the response path. If a target fails after request publication, the request remains as an honest record, no response is invented, and Bridge writes the failure and next action to standard error and exits nonzero.

### `record`

`record` is the only local writer besides `run`. It creates a session or adds an application-neutral note without calling a target, using the shared validation, numbering, lock, envelope, and atomic writer. Outside session records, the only local write is the ZCode connector's pair of launcher links in `~/Library/Caches/agent-bridge/zcode-launcher`, which `check` and `run` may create or repair when the installed ZCode needs them to start at all (see README).

Its substantive text comes from standard input. Empty or whitespace-only input is a usage error. Success prints the canonical path.

`--mode review|work` creates a Format 3 session (section 6): an explicit, immutable working mode. `--access-path` records additional existing absolute directories the request needs; it is repeatable, requires an explicit `--mode`, and is refused with repeats. A work session may omit `--project` when no code directory exists yet. A note accepts none of the session-creation options.

---

## 4a. The working mode

A work session is an explicit alternative to the restricted review call, created by `record --kind session-create --mode work`. Its mode, target, working directory, and declared access directories are immutable from creation; message text cannot change them. A work request can read the supplied project material and perform the work the request authorizes through the target's ordinary capabilities, under the target's own normal permissions. The code directory and document directories may differ (`--project` plus `--access-path`); a project can be discussed before code exists (omit `--project`).

Work mode is not a security override. Bridge selects no permission bypass, no `--dangerously-skip-permissions`, no `yolo`, no `full`/`off` policy, and no automatic approval mode to make a headless call succeed. It equally selects no permission posture of its own to replace the user's: a work vector passes no policy flag that would override the tool's effective configured posture, and where that posture itself cannot perform the authorized work noninteractively (Codex under an effective read-only sandbox, whether configured or the tool's out-of-box default), the call is refused before anything is published, naming the posture, its origin, and the terminal route. Where a target cannot do non-interactive work under its ordinary permissions at all, Bridge reports work unsupported with the real diagnostic and the terminal route (open that tool's own terminal interface) rather than quietly weakening anything. Selecting work mode is not blanket permission for publication, purchases, login, destructive operations, or unrelated effects; normal project instructions and the user's tool configuration still apply, and the surviving-boundary warnings of section 8 continue to name what is not confined.

Each connector ships a separate work vector beside its review vector; the review vectors are unchanged and review calls made without the new options behave exactly as before. The four supported work routes and the two honest unsupported ones are in section 8a.

Each call still starts a fresh native context. A successful work call returns the complete final answer, including an AI clarification question when that is the answer; the caller supplies all continuity in a later request. A failed call leaves truthful records: the request is retained, no response is invented, and if the invocation might have edited files before failing, the failure says so.

### `run --events-jsonl`

With `--events-jsonl`, standard output carries one JSON object per line — lifecycle events, periodic check-ins, and exactly one final result — and nothing else; the response path arrives inside the final event. Standard error remains diagnostics, warnings included. Every event object has an `event` field (`started`, `heartbeat`, or `finished`) and a `phase` field.

```json
{"event": "started", "phase": "run", "peer": "codex", "mode": "work"}
{"event": "heartbeat", "phase": "prerequisites", "elapsed_seconds": 30.001, "child_running": true}
{"event": "heartbeat", "phase": "peer-call", "elapsed_seconds": 60.002, "child_running": true}
{"event": "finished", "phase": "run", "outcome": "success",
 "request_path": "/…/messages/0001-initiator-to-peer.md",
 "response_path": "/…/messages/0002-peer-to-initiator.md",
 "warnings": ["...the same warnings standard error carried..."]}
```

A heartbeat means Bridge is alive and can report whether its child process is still running; it is not progress and carries no percentages. Heartbeats arrive while prerequisite probes or the peer call are waiting (`phase` says which), about every 30 seconds, and both bounded waits share the turn's one deadline. The final `finished` event carries `outcome` (`success`, `failure`, or `stopped`), `request_path` and `response_path` when published, the warnings, and — for `failure` — a plain `reason` and `next_action`; internal exception names stay internal. A `success` event follows durable response publication. A failed call still exits nonzero. If the event pipe breaks, the turn runs on and its records decide the truth: a broken pipe can never turn an unfinished call into a reported success.

Stop signals, `--timeout`, interruption, cleanup, and the single deadline behave exactly as for any other run; there is no separate cancellation daemon or command service.

---

## 5. Neutral local records

`record` accepts exactly two kinds:

| Kind | Required arguments | Optional | Result |
|---|---|---|---|
| `session-create` | `--initiator <label>`, `--peer <target-id>` | `--project <dir>`, `--mode review\|work`, repeatable `--access-path <dir>` (with `--mode`) | Creates `SESSION.md`; allocates no message number |
| `note` | none beyond session and kind | none | Creates one numbered initiator record |

The session body describes the session; a note may hold any application information. Bridge does not classify or interpret either.

`record` never invokes a target; creates, approves, replaces, or seals a plan; interprets workflow, review, repository, or Git state; changes the session's initiator; or creates application-specific headers.

Typed events belong in the application's Markdown body or its own state. Bridge does not grow an application record-kind registry.

---

## 6. Session record

```text
<session>/
  SESSION.md
  messages/
    0001-initiator-to-peer.md
    0002-peer-to-initiator.md
    0003-initiator-record.md
  .lock
```

`.lock` holds no canonical state. A session contains no `PLAN.md`, workflow status, approval state, task ledger, provider record, or application database. Sessions normally live under `~/.agent-bridge/sessions/` outside Git and cloud synchronization.

`SESSION.md` is written once:

```markdown
# Session

Bridge-Format: 2
Initiator: ora
Peer: claude
Project: /absolute/path

## Body

<application-supplied description>
```

`Project:` is omitted when absent. A project path must be absolute, exist at creation, and never come from a peer message. It is immutable with the initiator and target.

The session carries no provider or model, harness version, qualification receipt, mutable status, usage, cost, authority, or workflow field. Format 2 distinguishes this courier shape from unreleased construction sessions with workflow fields. An unsupported format is rejected, not guessed or silently migrated.

A session created with an explicit `--mode` is Format 3:

```markdown
# Session

Bridge-Format: 3
Initiator: vibe-coder
Peer: codex
Mode: work
Project: /absolute/code/path
Access-Path: /absolute/document/path

## Body

<application-supplied description>
```

`Mode:` is required and one of `review` or `work`; `Access-Path:` lines are optional, repeatable, each an absolute directory that exists at creation, and may not repeat. `Project:` may be omitted in a work session when no code directory exists yet. Both formats keep their own strict parsers: a Format 2 file carrying a Format 3 field, or the reverse, is rejected rather than reconciled, and no file is ever migrated. Format 2 sessions always read as review mode with no access paths. Successful runs never delete retained history.

Numbers increase within the session while the lock is held and are never reused. A failed target call may leave a request as the final message; that is an incomplete exchange, not corruption.

---

## 7. Envelope and Bridge-inert body

The runner writes every header. Initiators and targets supply only body text.

Request (Format 2, unchanged):

```markdown
# Message 0001
From: ora
To: claude

## Body

<request copied unchanged>
```

Response (Format 2, unchanged):

```markdown
# Message 0002
From: claude
To: ora

## Body

<final answer copied unchanged>
```

A Format 3 request may additionally carry the caller's inert metadata, and a Format 3 response names the request it answers:

```markdown
# Message 0001
From: vibe-coder
To: codex
Note-Ref: note-42
Purpose: second-draft
Attachment: /absolute/path/image.png

## Body

<request copied unchanged>
```

```markdown
# Message 0002
From: codex
To: vibe-coder
Answers: 0001

## Body

<final answer copied unchanged>
```

`Note-Ref:` and `Purpose:` appear once each when given; `Attachment:` appears once per attached file; `Answers:` carries the request's four-digit sequence. None of it is appended to or read from the body, which stays byte-exact under `## Body`.

Neutral note:

```markdown
# Message 0003
Record: note
From: ora

## Body

<note copied unchanged>
```

Header-shaped text below `## Body` remains body text. It cannot change Bridge identity, target, project, mode, number, kind, restrictions, authority, routing, or become a Bridge command. Bridge extracts no plan, commit, approval, review result, or instruction.

Filenames describe direction rather than repeating caller labels. A response is the next message published while the same run holds the lock; in Format 3 its `Answers:` header is the correlation, read from the record itself.

### The readable Format 3 record surface

A caller may read everything it needs from the retained records alone, in plain Markdown:

- From `SESSION.md`: the session's working `Mode:` and every declared `Access-Path:` directory, beside the immutable initiator, target, and project.
- From each request file: its sequence in the title line, its exact body below `## Body` (byte-exact, never modified), and its `Note-Ref:`, `Purpose:`, and `Attachment:` header lines when the caller supplied them.
- From each response file: its path, its body below `## Body`, and the request sequence it `Answers:`.

Headers are always the block between the title line and the first blank line; everything below `## Body` is inert text. Bridge owns this surface and will keep it readable.

---

## 8. Connectors, warnings, and qualification

Each target connector is a small source-controlled translation for one official vendor CLI. It declares:

- CLI identity and exact tested version or evidence-backed set;
- tested operating system, major versions, and architecture when relevant;
- authentication evidence available without a model turn, including limits when live authentication cannot be confirmed;
- fixed one-shot arguments and body transport;
- strongest practical enforced restrictions and concrete residual warnings;
- project-capable or courier-only posture; and
- final-response extraction.

A connector does not choose a model, effort, provider, endpoint, or credential; install, update, or sign in; resume vendor sessions; or fall back to an API, private desktop endpoint, browser, or UI automation.

`run` repeats cheap prerequisites. Missing software, reported missing authentication or minimum local authentication state, unusable one-shot input or final output, an absent required switch, or inability to control the foreground child stops before a real target call. Version or platform drift alone warns and proceeds when those mechanics remain usable.

### Strongest practical restrictions

Each connector applies every compatible vendor-native control available for project writes, Git changes, shell effects, browser or web access, MCP, messaging, credentials, publication, deployment, delegation, and other external effects.

A connector may remove tools, use an enforced sandbox, withhold the project, or combine them. When the vendor cannot completely guarantee confinement, Bridge names the remaining limitation and proceeds without an acknowledgment mechanism. The target's connection to its configured model provider is outside this restriction.

| Target | Project posture | Strongest practical posture | Required warning emphasis |
|---|---|---|---|
| Codex | Project-capable | Skip only `$CODEX_HOME/config.toml`, disable known high-risk routes, use the read-only sandbox, set the working directory explicitly | Skipped file's model/effort defaults; surviving project, system, cloud/managed/MDM configuration and possible hooks, MCP, or other external effects |
| Claude Code | Project-capable | Restricted mode, empty strict MCP set, Read/Glob/Grep, planning mode | Administrator-managed or remote policy can survive and add effects |
| ZCode | Project-capable | Planning mode, explicit directory, known dangerous tools removed | Plugin/direct-MCP limits, indirect OAuth evidence, visible body argument |
| Hermes Agent | Courier-only | Neutral directory, safe mode, smallest harmless toolset | Read cannot be separated from write, memory remains, visible body argument |
| MiniMax Code | Courier-only | Neutral directory, `exec` with standard input, `--permission smart`, one assistant step by default or an explicit positive bound, native timeout within its supported range; optional exact returned-model validation | Smart is discretionary, not a sandbox; a step bound does not disable tools; no state-free authentication check |
| Qwen Code | Courier-only | Neutral directory, safe and plan modes, pinned native macOS sandbox selection/profile, zero model tool calls, one input frame and turn, compatible time and pre-model command limits | Input preprocessing below; settings/.env may bypass sandbox or launch a detached proxy; profile permits same-user reads, some writes, process launches, and network; no safe no-turn authentication confirmation |

For Codex, `--ignore-user-config` does only what its name understates: it skips `$CODEX_HOME/config.toml`. It does not suppress trusted-project `.codex/config.toml` files and project hooks or rules, system configuration, `managed_config.toml`, `requirements.toml`, cloud-delivered requirements, macOS MDM preferences, or separately sourced user/global hooks and rules. Those surviving layers can add settings the fixed vector does not override, and managed defaults or MDM can override CLI options. Hooks, MCP servers, plugins, network or telemetry settings, and other integrations from surviving configuration may therefore retain routes to external effects outside the read-only shell sandbox. Bridge names that limit in its non-blocking warning. The skipped file's model and effort defaults are also lost, and Bridge does not replace them.

**Claude Code 2.1.251 managed MCP prerequisite.** The exact source `/Library/Application Support/ClaudeCode/managed-mcp.json` is incompatible with the fixed `--strict-mcp-config` invocation: the CLI exits when they are combined. If that path is present or its absence cannot be established, `check` fails and `run` fails before request publication. Bridge observes the path without opening policy contents. This is an unusable-command prerequisite, not a refusal over incomplete confinement. Other administrator-managed endpoint and remote policy may survive restricted mode; their presence or uncertainty remains a warning, not this hard failure.

**Qwen Code 0.23.0 input exception.** Selected Qwen may interpret recognized leading `/` commands or unescaped `@` references before the model. It may alter or replace the effective prompt, read and append readable file or resource content, fail in preprocessing, or handle a command without a model call. Both supported headless input modes share this; safe mode cannot disable it and no lossless escape or raw switch exists. Bridge records and passes the original exactly, gives Qwen a task-owned neutral directory with no project, and requires `--max-tool-calls=0`: no model-initiated tool call can execute, and the first such attempt aborts the run. Input preprocessing happens before that budget, so the limit does not stop it. Bridge warns during `check` and before publication without blocking or acknowledgment. The other five prompts remain lossless and unselected Qwen inert. An official raw mode would make the exception removable after qualification.

The Qwen vector disables `/bug`, `/config`, `/update`, `/import-config`, `/language`, `/effort`, `/model`, and `/doctor` because those pre-model command families can cause external or persistent effects. Other recognized preprocessing remains. Qwen retains the user's existing authentication and provider setup; Bridge adds no selection or credential handling.

For both readiness and runs, Bridge clears inherited `QWEN_CODE_RELAUNCH_ARGS` so it cannot replace the fixed startup arguments. It pins nonempty `QWEN_SANDBOX=sandbox-exec` and `SEATBELT_PROFILE=restrictive-open`, and removes inherited `SANDBOX` and `QWEN_SANDBOX_PROXY_COMMAND`. Safe mode still loads settings and `.env` values, which can refill missing or empty variables: restored `SANDBOX` can bypass the sandbox, and a restored proxy command can launch a detached shell outside both the sandbox and Bridge's process group. Empty strings cannot disable those routes reliably. Bridge names these surviving routes as non-blocking warnings; it does not inspect or alter the user's configuration or add a confinement gate.

### Disposable qualification

Before real project use, a task-owned synthetic Git repository proves:

1. A project-capable target reads supplied evidence; a courier-only target receives no project.
2. Local create, modify, delete, Git-ref, and repository-configuration attempts occur only in that disposable repository, whose tracked content, untracked files, `HEAD`, refs, configuration, and clean status are compared afterwards.
3. No `.git` lock or task-owned child remains.
4. No prompt deliberately attempts browser or web access, messaging, MCP service calls, credential access or change, publication, deployment, login, purchase, or another real-world effect. Those routes are described from the fixed vector, safe no-turn metadata, and uninvoked tool inventory.
5. The exact record and CLI transport preserve leading hyphens, Unicode, multiline text, and the complete response. Qwen uses non-triggering content and claims no raw prompt.
6. The temporary parent is removed on every exit path.

The test uses no real project, secret, message, production service, or publication. Same-user reads outside the project are not claimed to be confined.

Qualification is source evidence, not mutable runtime state. There is no last-passed stamp, cache, receipt, database, or third connector operation. A CLI outside declared evidence warns when the required mechanics still work; qualification updates source rather than granting per-user approval.

---

### 8a. Work vectors and image routes

Each connector's work vector is a separate builder beside its review vector, reusing the same fixed-vector transport, output parsing, bounded execution, deadline, and cleanup. Work vectors preserve ordinary user model/configuration choices and the tool's normal permission policy; Bridge passes no approval bypass of any kind. Access directories are recorded in the session and reach the vector where the tool has a matching switch; otherwise they remain ordinary same-user paths, which is a declaration of need, not an isolation boundary.

| Target | Work | Image route | Basis |
|---|---|---|---|
| Codex | Supported: `codex exec --cd <project>` (+ `--add-dir` per access path) with **no sandbox switch** — the effective sandbox is the one codex itself resolves from `sandbox_mode` in `$CODEX_HOME/config.toml` or its own default, which is read-only for exec; no `--ignore-user-config` and no review feature disables, so the user's ordinary configured model and effort apply; headless exec cannot ask for approval, so what the sandbox refuses fails; an effective read-only posture — configured or the out-of-box default — cannot perform authorized work headlessly, and the call is refused before publication, naming the posture, its origin, and the terminal route | Native `-i/--image` attachment | Switches verified on the installed 0.155.1 `codex exec --help`; default posture and config precedence established with `codex debug prompt-input` under controlled `CODEX_HOME` fixtures (read-only by default; each `sandbox_mode` value governs; a trusted-project `.codex/config.toml` can override) and the vendor's non-interactive documentation; re-live-qualified under the corrected vector (see the re-qualification note below) |
| Claude Code | Supported: normal `claude --print --output-format text` (+ `--add-dir` per access path) with no permission flag — the user's settings and the ordinary default headless permission behavior decide; the review-only managed-MCP gate does not apply because work passes no `--strict-mcp-config` | File-reading route: Claude Code's own read tool presents the image when the request body names its absolute path | Live probe on 2.1.278 confirmed default-mode headless file creation; live-qualified |
| ZCode | Supported: `--mode edit` with the real tool set (no review deny list) — edit mode allows workspace file edits; every other approval-needing tool is denied by the deny broker a headless prompt uses; the `--prompt` default `yolo` is never used | Native `--attach`, which the bundle reads and hands to the model as inline image content | Mode and deny-broker behavior read from the installed 0.16.9 bundle source; `--attach` pipeline verified in source; live-qualified |
| MiniMax Code | Supported: `mcode exec --cwd <project>` with **no permission policy selected** — the program's own headless default governs: its source fixes an absent `--permission` at `smart`, and no runtime configuration can change a headless run's permission mode (`ask` needs a TUI and is rejected by `mcode exec` itself; `full`/`off` are approval bypasses never selected); `--max-steps` only when the caller names one, `--file` per attachment | Native `--file` attachment, classified by MIME type into model image content (≤10 files, ≤100 MB) | Read from the installed 0.2.7 source; re-live-qualified under the corrected vector (see the re-qualification note below) |
| Hermes Agent | Unsupported: one-shot `-z` auto-bypasses approvals by design (its own help says "approvals are auto-bypassed") and no other non-interactive route offers ordinary approvals | Unsupported: no attachment switch; the one-shot body is command-line text | Read from the installed 0.21.3 `hermes --help`; terminal route: run `hermes` in its own terminal |
| Qwen Code | Unsupported: the ordinary approval mode (`default`) requires manual approval for file edits and shell commands and a headless run cannot ask (text mode cancels the call; stream-json would ask the calling host to approve, making Bridge the permission authority), while `auto-edit`/`auto`/`yolo` are automatic approvals Bridge will not select | Unsupported: the stream-json reader stringifies every non-text content block as JSON text rather than pixels, and there is no attachment switch | Read from the installed 0.23.0 bundle source; terminal route: run `qwen` in its own terminal |

The `/` and `@` preprocessing exception of section 8 applies to every Qwen input, work included; no work route exists to carry it, and the finding above is the whole of Qwen's work story. Capability facts in `check --json` state these same truths, and a work session for an unsupported target is refused before request publication with the limitation and terminal route in the message.

**Live work qualification, September 27, 2026, macOS 26 arm64.** One `qualify --mode work` run per supported route, each in a disposable fixture: a synthetic Git repository as the code directory, an `authorized-docs` access directory outside it, and one distinctive attachment image whose content appeared nowhere in the request text. Every run proved the production work vector, code reading from the code directory, a reversible document edit written inside the access directory only, the synthetic repository unchanged afterwards (tracked hashes, untracked set, HEAD, refs, config, clean status, no Git locks), released session locks, and full cleanup. Codex 0.155.1 identified a solid-magenta attachment from its pixels (`--image`); Claude Code 2.1.278 identified the same magenta image through its file-reading tool with the path named only in the request body (`--add-dir` widened access); ZCode 0.16.9 read block digits "3174" from a `--attach` image; MiniMax Code 0.2.7 read the same digits from a `--file` image. No work qualification is claimed for Hermes Agent or Qwen Code.

**Re-qualification after the permission-posture correction, September 28, 2026.** The Codex and MiniMax Code work vectors were corrected to stop selecting a permission posture of Bridge's own (Codex no longer passes `--sandbox workspace-write`; MiniMax no longer passes `--permission smart`), because a selected policy silently replaced the user's effective configured posture — widening a configured read-only Codex to writable. Each corrected vector was re-live-qualified once in a fresh disposable fixture with the same checks as above. The Codex run proceeded under this machine's effective configured posture (`sandbox_mode = "danger-full-access"` read from `~/.codex/config.toml`; an effective read-only posture is refused before publication instead), and the MiniMax run under the program's own headless default (`smart`). Claude Code (no permission flag) and ZCode (`--mode edit`, which narrows the `yolo` default and replaces no user-configurable posture) were audited for the same problem and found clean.

---

## 9. Locking, publication, and cleanup

One foreground turn holds a process-scoped advisory lock from sequence allocation through response publication or cleanup. Contention changes no canonical file. There is no lease, heartbeat, stale-lock service, or lock stealing.

Each canonical file is completed in a temporary file in its destination directory, flushed, and atomically renamed. A partial file is never published. An uncertain rename reports the exact canonical path and requires inspection before another run.

Each child belongs to the turn's process group. Timeout, interrupt, termination, and hangup terminate and reap it, remove task-owned temporary files, and release the lock. Cleanup failure visibly names what remains.

`SIGKILL` and power loss cannot clean up. A child that escapes its process group fails qualification if observed. Outside the main thread, the surrounding program's signal behavior applies because handlers cannot be installed. Storage failure can still make publication uncertain.

There is no automatic retry. Retrying an uncertain provider call is an application decision.

---

## 10. Internal failures

The core owns this internal list; connectors map vendor behavior into it. The names are not a public compatibility surface.

| Failure | Meaning and next action |
|---|---|
| `MISSING_CLI` | Target CLI absent; install its official program and check again. |
| `AUTHENTICATION_REQUIRED` | Supported sign-in not observed; sign in through the harness. |
| `UNREPORTABLE_VERSION` | Version unreadable; inspect the vendor command. |
| `UNQUALIFIED_VERSION` | Retained internal diagnostic; current connectors warn on readable version drift when required mechanics remain usable. |
| `UNQUALIFIED_PLATFORM` | Retained internal diagnostic; current connectors warn on platform drift when required mechanics remain usable. |
| `RESTRICTIONS_UNAVAILABLE` | A required fixed-vector, input, output, or foreground switch is absent; the promised call cannot be made. |
| `QUALIFICATION_UNSAFE_OR_INCONCLUSIVE` | Retained internal diagnostic, not a current runtime confinement gate; residual limits are warnings. |
| `BUSY_SESSION` | Another turn owns the lock; wait. |
| `TIMEOUT` | Deadline expired; inspect visible state before deciding whether to retry. |
| `PEER_FAILURE` | Vendor CLI failed; correct the harness-side problem. |
| `EMPTY_RESPONSE` | No final text; check the target directly. |
| `CLEANUP_FAILURE` | A task-owned process or path remains; remove the named item. |
| `USAGE_ERROR` | Argument, label, body, target/project combination, or transport invalid; correct it. |
| `UNKNOWN_HARNESS` | Target is not one of the six fixed identifiers; name one. |
| `CONNECTOR_UNAVAILABLE` | Incomplete build lacks a fixed target's connector; use complete source. All six ship in Release 1. |
| `UNKNOWN_RECORD_KIND` | Kind is not `session-create` or `note`; use one of them. |
| `SESSION_NOT_FOUND` | Session absent; create it or correct the path. |
| `SESSION_INVALID` | Session unreadable, inconsistent, or unsupported; inspect it or start again. |
| `SESSION_EXISTS` | Session already exists; continue it or choose an empty path. |
| `PUBLICATION_FAILURE` | Nothing published; correct storage and retry only when safe. |
| `PUBLICATION_NOT_FLUSHED` | File exists but directory entry was not forced to disk; treat as unfinished. |
| `PUBLICATION_UNCERTAIN` | Rename outcome unknown; inspect the exact path before anything else. |

Every command reports failures on standard error and exits nonzero. A failure avoids false success, cleans what the turn owns when possible, and supplies one next action.

---

## 11. Initiating adapters

An adapter may be a harness skill, local application wrapper, or server-side integration running where target CLIs and vendor sign-ins exist. It:

1. Supplies an inert initiator label and fixed target.
2. Creates or reuses the one-initiator, one-target session.
3. Hands one complete Markdown body to `run`.
4. Reads the returned response path.
5. Adds a neutral note when needed.
6. Reports readiness, warnings, and failures without hiding them.

The adapter owns its UI, target-selection policy, multi-target work, context assembly, plans, approvals, reviews, corrections, Git behavior, retry decisions, and response interpretation. Those remain application responsibilities even inside a harness package.

The six harness packages expose courier, readiness, and neutral-record entry points through host conventions. They contain no planning, Programming Loop, or review product, never find or call each other, and invoke the one shared Bridge.

### Adding an initiating host

To be a target, a harness itself needs no Bridge adapter package. Its official
CLI and vendor sign-in must exist where Bridge runs, and Bridge must have a
qualified connector. A host that will initiate Bridge needs only documentation,
a skill, or a launcher implementing the six adapter steps above. It must use
the source checkout as the runtime, leave target choice with the caller, pass
the complete body, surface warnings and failures, retain the saved response,
and wait for cleanup. It must not add a target branch, register itself, or make
its application state part of Format 2.

Focused initiating-host evidence uses a disposable session and fake target. It
shows exact body preservation, one selected target, readiness and warning
presentation, nonzero failure, complete response retrieval, neutral notes, and
no surviving process. This does not qualify a vendor CLI or model.

### Adding a target

A new target requires one hand-written connector module and literal edits to
`HARNESS_IDS` and `_switch`; add it to `is_courier_only` when it cannot receive
a project. The connector implements the existing `check` and `build_command`
surface with an official stable CLI, a fixed no-shell vector, standard-input
transport where the CLI supports it, exact final-response extraction, the
strongest practical restrictions, and specific residual warnings. It neither
selects a model/provider nor installs, signs in, retries, or falls back.

Focused target evidence must cover the fixed Format 2 request, response, and
note records; immutable session identity; literal dispatch; every unselected
connector remaining inert; warning and failure reporting; timeout,
publication, and process cleanup; and every initiating adapter that offers the
new identifier. Qualification declarations name only the CLI versions and
platforms actually exercised. Without a separately authorized disposable real
call, the connector may be described as implemented and untested, never tested.

This procedure is intentionally not a registry, generator, SDK, marketplace,
discovery engine, provider fallback, automatic target selector, or all-pairs
test requirement.

---

## 12. Release 1 conformance

Release 1 conforms only when evidence proves:

1. Targets are exactly `codex`, `claude`, `zcode`, `hermes`, `minimax`, and `qwen`; another target fails, new valid initiator labels work without registration, and all five unselected connectors stay inert.
2. Each connector reports accurate readiness and concrete non-blocking warnings without a model turn, then completes one distinctive Markdown round trip.
3. Safe disposable qualification proves declared posture, transport, local state, and cleanup without deliberately attempting a real-world effect; courier-only targets refuse projects before connector import and publication.
4. A fake target proves both record kinds, inert bodies, immutable sessions, numbering, atomic publication, contention, timeout, failures, interruption, child termination, and no orphan.
5. Each of six harness adapters and one arbitrary application adapter can create, check, send, receive, record a note, and report warnings and failures.
6. Inspection finds no model API, dynamic registry, pair bridge, coordinator, router, scheduler, database, daemon, workflow engine, Git gate, plan store, approval or acknowledgment mechanism, review protocol, or Programming Loop.
7. Documentation matches the tested implementation, platform, and versions.

The complete authorized commands are:

```text
/usr/bin/python3 -m unittest -v tests.test_fake_peer
python3 -m unittest -v tests.test_work_mode
python3 -m tests.release_conformance inspect
python3 -m tests.release_conformance adapters
python3 -m tests.release_conformance qualify --peer codex
python3 -m tests.release_conformance qualify --peer claude
python3 -m tests.release_conformance qualify --peer zcode
python3 -m tests.release_conformance qualify --peer hermes
python3 -m tests.release_conformance qualify --peer minimax
python3 -m tests.release_conformance qualify --peer qwen
```

The work-mode extension added one focused selection over the unchanged
compatibility classes (`tests.test_fake_peer.FormatTwoRecords`,
`.SixTargetConnectorBehavior`, `.CommandLineBody`, and the eleven listed
`TurnBehavior` methods), the `tests.test_work_mode` module, and one live work
qualification per route declared supported:

```text
python3 -m tests.release_conformance qualify --peer codex  --mode work
python3 -m tests.release_conformance qualify --peer claude --mode work
python3 -m tests.release_conformance qualify --peer zcode  --mode work
python3 -m tests.release_conformance qualify --peer minimax --mode work
```

Hermes and Qwen declare no supported work route, so no work qualification is
run or claimed for them.

Each qualification includes readiness and one distinctive real model call. The approved transport correction's one additional Qwen-only qualification passed after local checks and independent review. No full suite, build, benchmark, all-pairs test, other repeated qualification, deliberate external-effect attempt, or duplicate reassurance pass is part of the ceiling. Application behavior is outside this boundary.

Release finishes only after accepted source is committed, pushed, reviewed in a pull request, merged to `main`, and the existing repository is public. The installed Claude adapter is updated from merged source, anonymous repository installation is verified, task-owned resources are removed, and the Ora task receives the actual merged commit and invocation path. Bridge itself installs no target CLI and signs no user in.
