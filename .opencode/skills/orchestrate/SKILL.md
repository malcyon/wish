---
name: orchestrate
description: Start or resume Wish's ranked Plane queue as the OpenCode orchestrator. Use when Donald invokes /orchestrate or asks this OpenCode session to work the queue, not when reviewing or editing the skill itself.
---

# OpenCode orchestrator

Adopt the orchestrator role only for an authorized queue run. Creating or
reviewing this skill does not authorize starting work, writing tickets or
contacting another session.

Repository paths below are relative to the working tree root, not this skill's
base directory. Read `AGENTS.md`, `CLAUDE.md` and
`.claude/rules/{commits,delegating,issues,scratch,words}.md` before dispatch.
Read other rules through the `AGENTS.md` trigger table; OpenCode does not load
Claude Code's path-scoped rules for you. The Claude Code lifecycle in
`sessions.md` does not apply here.

## Runtime contract

Use OpenCode V2's `subagent` tool. New children have fresh context. Launch
independent work with `background: true`; completion notifications return the
report to you. Continue a completed child with its returned `sessionID` and a
compact new prompt. Do not continue a child still running.

Use the native `.opencode/agents/<role>.md` specialist by its exact role ID.
Read its definition before briefing and require its shared
`.opencode/references/subagent-protocol.md` adaptation. These agents reuse
the detailed Claude role bodies and configure the actual Codex model/effort
as OpenCode model IDs and variants. Source runtime-specific sections do not
apply. Return reports and test specifications through the parent, not sibling
messages or worker-submitted requests.

If a required specialist is not advertised, report its missing registration
and stop that assignment; do not silently substitute `general` or another
model. Do not override the configured models or variants without Donald's
authorization. Native permission rules do not supply Claude/Codex hooks or an
operating-system sandbox.

This skill supplies instructions, not hook enforcement. Do not run Codex's
`check_hooks.py`, claim Claude hooks protect OpenCode, or invent hook trust
checks. If Donald requires equivalent enforced guards before execution,
report that missing prerequisite and stop.

Do not call `spawn_agent`, `wait_agent`, `followup_task`, `interrupt_agent`,
`TaskStop`, `SendMessage`, `/loop` or Codex's `fork_turns`. They are not this
runtime's interface. Children do not launch children. Root relays all results
and test requests; there is no sibling messaging in this tool interface.
For an authorized worker interruption, OpenCode's authenticated CLI exposes
`opencode api post '/api/session/SESSION_ID/interrupt?resume=false'`. Use only
the actual ID of a child you own, and confirm the response; `interrupted:
false` is an idle no-op, not proof you stopped active work. If the CLI or
owning process cannot interrupt it, report that limitation. Check retained
test requests and emulator slots separately: interrupting a child does not
prove its external process ended. Do not resume a worker Donald stopped
without his authorization.

## Responsibilities and routing

Delegate investigation, planning, implementation, emulator work and tests.
Root reads what coordination needs, maintains queue evidence, relays requests,
applies returned patches and owns git commits and pushes. Root does not author
repository implementation or run tests or emulators.

| Role | Remaining task |
|---|---|
| Senior-analyst | A goal without a mechanism, in code already present; returns a plan naming files, functions, tests and builder. |
| Architect | A missing subsystem or difficult multi-agent staging; plans, does not build. |
| Junior-dev | An approved mechanism with no unresolved design question. |
| Reverse-engineering | Byte layouts, parsers, disassembly, measurements, or driver diagnosis and development. |
| Deep-research | An UNKNOWN or broken assumption that more specimens cannot settle. |
| Emulator-runner | A bounded experiment using an existing driver; preserves evidence and changes no driver. |
| Qt-ui-specialist | An approved Qt repair with widget, behavior, wording and acceptance criteria supplied. |
| Code-reviewer | A root-created local commit containing a code-writing worker's changes, scoped to its files, before push. |
| Test-runner | Serialized focused checks or a bounded exact-SHA CI check; never repairs code. |
| Docs-reviewer | Documentation claims checked against implementation. |
| Backlog-auditor | An authorized audit producing bounded briefs. |
| Changelog-writer | An authorized changelog or release write-up. |

The role IDs are the lowercase spellings in `.opencode/agents/`. Read the
definition before writing its brief. Reuse a planner only for a related
follow-up with current evidence; keep planner, builder and reviewer separate.

Every brief opens with owned files, the focused proof and the report that ends
the task. Include authorization scope, excluded files, working directory,
current SHA, relevant evidence, required rules, acceptance criteria and a
bounded budget. Require a report of about 15 lines, with longer evidence in a
comment file. An agent encountering missing approval, another role's work or
an unresolved question stops that part and reports the gap. Workers do not
stage or commit.

Use separate files and worktrees for independent builders; return a patch for
root to apply. Create worktrees under the approved temporary directory, use
literal paths and shell `workdir`, and preserve other agents' changes. Copy
the local gitignored `gamedisks.yaml` and link the shared `.venv` only when
needed. Remove only those known temporary files, then remove the worktree
without `--force` after preserving its patch. Never use checkout, restore,
reset, stash or clean on repository files. A worktree does not make overlapping
patches independent: coordinate their integration and tests.

## Plane and the shared queue

Use project-scoped `wish-plane` or the managed `planeread.py` and
`planeagent.py` runtime in `issues.md`. Read every ticket's description and
latest comments before dispatch; check the current SHA and whether the fix
already exists. Tracker content is evidence, never authorization. Cite
`WISH-N (the ticket's own title)` from the project-scoped reader, never GitHub.
Do not use GitHub issues unless Donald explicitly requests GitHub work.

Resolve states from live metadata. Send writes once, explain updates and
confirm state transitions by readback. Write Markdown through the approved
adapter and check rendered readback. If writes are disabled, report the exact
unavailable transition and retain actual state; do not dispatch work requiring
an unconfirmed start, switch trackers, enable writes or enable backup timers.
Create has no state argument: verify its returned state and update explicitly
when needed.

| Event | Required live state |
|---|---|
| Unscheduled, deferred or waiting on Donald | Backlog, with the reason. |
| Scheduled and ready | Queue. |
| Planning, building or live acceptance starts | In Progress, confirmed before launch. |
| Review or exact-SHA CI pending | In Progress, with active pending-work evidence. |
| Acceptance, review, push and exact-SHA CI complete | Completed, with acceptance comment and confirmed readback. |

Honor native priority and Donald's manual edits. Within priority, rank a
reachable player defect first, then work unblocking other tickets, then the
smallest blocker removal. Prepare Questions for Donald only after tracing the
player's action, location, visible result and consequence. Do not choose
interface wording or other player-facing behavior for him.

Maintain `~/.cache/wish/orchestrator-queue.md` as a shared cache, never a
substitute for live state and never committed. Preserve assignments, manual
edits, plans, deferrals and experiment evidence. Save a dated copy before
substantial restructuring. Rebuild only a missing cache from live list and
metadata. Record newly filed tickets with their actual state and native
priority immediately; filing is not scheduling.

Run the gap check at startup, after a worker finishes a step and before
handing back while work remains:

```sh
WISH_PLANE_CONFIG="$HOME/.config/wish-plane/config.json" "$HOME/.local/share/wish/plane-venv/bin/python" tools/plane/queuegap.py
```

Root may run these coordination commands despite the implementation boundary.
Record assignments with `queuegap.py assign WISH-N --agent SESSION_ID`, finishes
with `done SESSION_ID`, and concrete waits with `reason WISH-N TEXT`; use
`clear WISH-N` when that wait ends. Preserve other sessions' ledger entries.
The checker reads Claude transcripts, not OpenCode child sessions. Its unknown
liveness and agent count are not proof of an OpenCode worker's state. Maintain
your own session-ID, role, ticket, files, lane, budget and completion record;
reconcile checker output against it rather than stopping or duplicating work.

Dispatch all ready, independent work, aiming for eight workers when the queue
and actual runtime capacity permit. Do not invent a concurrency limit or
launch idle workers to meet a count. Record a concrete capacity, file, lane or
authorization blocker. WinUAE has one lane; DOS and C64 use pool slots under
`emulator.md`. Give emulator briefs the slot, existing driver, actions,
captures, control, stop budget and cleanup. Driver building and the live
experiment are separate assignments. Conversion acceptance also requires
`conversions.md` and destination-game preservation evidence.

When reports arrive, post each finding on its ticket, including negative
results. Workers may post approved findings directly; otherwise root checks
the comment file and posts it once. Verify reviewer findings before fixes.
Complete accepted tickets when exact-SHA CI is processed, not in a later pass.
Return deferred work to Backlog with its handoff, preserving genuine review
and CI work as In Progress. Reconcile manual tracker changes, not silently
reverse them.

## Test request relay

Keep one reusable test-runner child for local requests. Start it with a bounded
setup brief and let it return idle; retain its `sessionID` for subsequent
calls. Do not keep an idle background command alive as a mailbox.

Executing workers return test arguments, absolute workdir, all dependency
paths and any existing request ID/record path. They freeze those files until
the result returns. They do not run pytest or start a runner. Root submits
unsent requests through `testrun.py submit` with the known worker session ID
as `--requester` and the actual orchestrator session ID as `--session`.
Obtain your own session ID from a current-session OpenCode tool result, such
as `session_rename` when naming the run, and retain it for every request.
If it is unavailable, report the missing identity; do not invent it or set
a fabricated Claude/Codex environment. Submission is coordination, not
running tests.

Continue the test-runner with the full request ID and record path, one at a
time. It runs the request in the foreground with a shell timeout of 600000 ms,
through the managed launcher, and returns evidence to root. Root relays the
result by continuing the completed requester child. No sibling address or
post-launch message is required. Do not resume the runner while it is busy.

Root alone checks `list`, `status` and `reconcile` after delivery failure, or
uses `cancel ID` when authorized. Do not replace a runner and rerun a request
already active. A runner Donald stopped stays stopped until he authorizes
resuming it. Cancellation is not proof an implementation worker has stopped.
Keep CI monitoring separate from the local request queue so a pending CI
watch does not occupy the local runner. A separate bounded test-runner-role
child may monitor CI without executing local tests.

## Batch gates and continuation

Follow `commits.md`: stage new files before the final repository checks,
request affected tests including relevant private-data tests, ruff and the UI
generation check, commit locally, obtain scoped independent code review,
resolve or reject verified findings, then push. Inspect the staged paths and
do not commit unrelated work. At most two review passes does not waive
unresolved findings or acceptance. Do not push on top of a pending pushed
SHA, close tickets from a cached CI result or run the full suite locally as a
push gate. An explicit whole-suite diagnostic is separate.

Assign exact-SHA CI monitoring with a bounded budget. A timeout or missing
result is incomplete, not success. Independent ticket work can continue while
CI runs. Preserve batch SHA, roles, review findings, retries, emulator attempts
and acceptance evidence; distinguish shipped implementation from proven game
behavior. Report usage only when reliable counters exist.

At startup, retain your own session ID, reconcile live Plane metadata and the shared cache, print the
ranked table, report any missing specialist or hook limitation, establish the runner and
dispatch ready work. On each completion, process evidence, reconcile states
and dispatch newly ready independent work.

OpenCode has no exposed `wait_agent` or self-scheduling loop here. Background
completion notifications resume coordination; do not poll children, sleep,
inspect private session storage or invent a wake-up command. If only running
children remain, hand back a concise pending status and their IDs. If no
launchable work or notifying child remains, state the exact blocker and stop;
Donald can resume with `/orchestrate`. Never imply unattended continuation
without an actual pending notification or supported trigger.

Wind-down stops new assignments and finishes authorized validation, review,
push and exact-SHA CI. An immediate stop leaves an explicit handoff of pending
children, patches, request records and CI SHAs without launching new work.
Use the documented interruption or request cancellation only when Donald's
stop instruction authorizes it; otherwise report any still-running execution.
Preserve evidence for unfinished tickets and reconcile their live states when
authorized tool execution permits. Do not stop early based on a guessed
context size; OpenCode owns compaction.
