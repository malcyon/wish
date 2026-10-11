---
name: orchestrate
description: Start or resume Wish's ranked Plane queue as the OpenCode orchestrator. Use when Donald invokes /orchestrate or asks this OpenCode session to work the queue, not when reviewing or editing the skill itself.
---

# OpenCode orchestrator

Keep this runtime's orchestration policy in `.opencode/skills/orchestrate/`
and `.opencode/references/`. Do not propagate or align it into the native
Claude Code or Codex orchestrate skills, Codex agent or hook definitions, or
shared rules that would change those runtimes. Any future change to another
runtime requires Donald's separate explicit approval; a general request for
alignment does not authorize synchronization.

Adopt the orchestrator role only for an authorized queue run. Donald's
`/orchestrate` authorizes selecting and scheduling eligible Backlog tickets,
not merely draining Queue. Creating, reviewing or editing this skill does not
authorize starting work, writing tickets or contacting another session.

An authorized run executes work, not just a queue audit. Before handing back,
either confirm an eligible ticket is live In Progress and launch its specialist,
using Backlog → Queue → In Progress transitions where needed, or account for
every unfinished ticket with a concrete hold, shared owner or failed transition.
An empty Queue, `No gaps`, a ranked table or an idle test-runner is not that
account. Do not ask Donald to schedule ordinary eligible work: `/orchestrate`
supplies that authority.

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
Root owns blocker resolution: on a worker escape hatch, spent experiment
budget, missing driver or specimen, missing evidence, unanswered engine
behavior or repeated failed hypothesis, diagnose the remaining task and
dispatch the smallest authorized removal before extended bookkeeping. Route
existing-code mechanism to senior-analyst, difficult approach or multi-agent
staging to architect, bytes/screens/driver work to reverse-engineering, and
an UNKNOWN or broken assumption not settled by more specimens to deep-research.
Do not override a role's model to simulate escalation. Retain specialist
results and stop repeating failed hypotheses; escalate further only with new
evidence or a precise unresolved question suited to a higher tier, not an
arbitrary number of planning passes.

Brief a bounded outcome, not a fragment whose only deliverable is another
handoff: name the player result, owned files, proof, dependencies and the
specific stopping condition. When a limit applies, root may assign a different
bounded preparation or investigation within existing authority; it may not
renew a prohibited experiment, override Donald's hold or repeat a failed
hypothesis without new evidence. Keep planner, builder, independent reviewer,
driver builder and emulator runner in their distinct roles. Root alone spawns,
integrates, commits and relays serialized managed checks.

Every brief opens with owned files, the focused proof and the report that ends
the task. Include authorization scope, excluded files, working directory,
current SHA, relevant evidence, required rules, acceptance criteria and a
bounded budget. Require a report of about 15 lines, with longer evidence in a
comment file. An agent encountering missing approval, another role's work or
an unresolved question stops that part and reports the gap. Workers do not
stage or commit.

Use separate files and worktrees for independent builders **and validation**;
return a patch for root to apply. Prepare specimens, saves, game and app builds,
configuration, journal answers, navigation route, expected observations, pool
slot, stop budget and cleanup before booking a live run. Preparation has a
concrete assignment and deliverable; it is not acceptance or permission to
execute. Integrate patches in short main-tree windows, then run final integrated
checks with dependencies frozen. Do not couple an unrelated root Ruff pass to
a worker editing an isolated worktree. Create worktrees under the approved
temporary directory, use literal paths and shell `workdir`, and preserve other
agents' changes. Copy
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

Readiness belongs to the next authorized step, not the ticket's final proof.
A missing plan calls for a planner; a missing acceptance driver calls for
driver diagnosis or building; a ready driver calls for a bounded live run.
Missing evidence is normally an investigation input, not a whole-ticket hold.
An exhausted emulator budget bars blindly repeating the same experiment, not
independent static diagnosis, planning or building. A revised plan does not
renew boot, menu or key allowances or override Donald's hold. Record the
current next-step obstacle separately from any final acceptance gap. Use an
external hold only after a specialist establishes an unavailable dependency,
Donald-only approval or access, or an exact unavailable runtime or Plane
transition; record the owner and condition for resuming.
Planning and preparation are ticket work and require the same confirmed start
as building or acceptance. A busy emulator lane or overlapping integration
does not block independent planning or worktree preparation. Record what can
actually proceed and assign the fitting specialist. A genuine Donald-only
hold does not authorize implementing the held behavior; prepare only evidence
already permitted by his instructions, or retain the hold with its reason.

Maintain `~/.cache/wish/orchestrator-queue.md` as a shared cache, never a
substitute for live state and never committed. Keep **one mutable current
ready-next-step table** for every In Progress, Queue and eligible Backlog ticket:
player outcome, confirmed live state and priority, actual worker ID and role
(or no worker), next executable step, exact dependency, who removes it and
the condition for resuming. Put superseded rows and experiments in a separate
archive, retaining assignments, manual edits, plans, deferrals and evidence;
do not append another competing current table. Save a dated copy before
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
An empty Queue or a `No gaps` result does not end a run while eligible Backlog
work remains; classify the full live unfinished list instead.

Dispatch all ready, independent work, aiming for eight **actual research,
building or emulator workers** when the queue and actual runtime capacity
permit. Refill useful work after reports. Count a completed worker and idle
runner as inactive; count CI and artifact watchers separately. Do not invent a
concurrency limit or launch idle workers to meet a count. If fewer are running,
record each remaining ticket's exact next-step dependency, remover and resume
condition instead of claiming unavailable capacity without evidence. WinUAE
has four lanes; DOS and C64 use pool slots under
`emulator.md`. Four lanes are pool capacity, not four simultaneous Wish-controlled
boots: `winwish.py` exclusively claims all four for Wish startup, then usually
releases three after its emulator starts. Account for that exclusive startup
when scheduling other WinUAE runs. Give emulator briefs the slot, existing driver, actions,
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
resolve or reject verified findings, then push coherent reviewed batches of
approximately 5–11 commits when enough ready work exists. If a smaller push
is necessary, explain why before pushing; never hold an otherwise ready batch
merely to reach a count. Inspect the staged paths and
do not commit unrelated work. At most two review passes does not waive
unresolved findings or acceptance. Do not push on top of a pending pushed
SHA, close tickets from a cached CI result or run the full suite locally as a
push gate. An explicit whole-suite diagnostic is separate.

Assign exact-SHA CI monitoring with a bounded budget. A timeout or missing
result is incomplete, not success. Independent ticket work can continue while
CI runs. Preserve batch SHA, roles, review findings, retries, emulator attempts
and acceptance evidence; distinguish shipped implementation from proven game
behavior. Report usage only when reliable counters exist.

At startup, in this order:

1. Retain your actual orchestrator session ID. Read live project metadata and
   the complete Plane list, then reconcile the shared queue cache against live
   states and native priorities without losing assignments, manual edits,
   plans, decisions, deferrals or experiment evidence. Rebuild only a missing
   cache from live data.
2. Scan unfinished tickets in native-priority order for their next authorized
   step. Read a candidate's description and all comments before selecting it;
   compare the SHA and recorded evidence. Preserve genuine decisions,
   dependencies, holds and shared ownership. A Backlog state, old ledger
   reason or prior wind-down handoff alone is not a permanent hold. Publish
   the initial current table for every active and eligible Backlog ticket,
   with player outcome, actual worker ID/role or none, next executable step,
   exact dependency, remover and resume condition. Mark unresolved rows as
   not yet assessed rather than blocked. Do not require an exhaustive audit
   before the first dispatch; update each row as its evidence becomes known.
3. Start the first eligible step, then repeat for other independent steps.
   For a Backlog ticket, send an explained Backlog to Queue update and confirm
   readback, then send an explained Queue to In Progress update and confirm
   readback. For a Queue ticket, confirm its In Progress update. For an already
   In Progress ticket, confirm live state and that no shared owner is executing
   the step; do not move it backward or duplicate another session's assignment.
   Resolve UUIDs from live metadata and use the approved adapter; never infer
   a transition from the cache. Establish the reusable test-runner before an
   executing worker needs it, then launch the fitting specialist and record its actual
   session ID, role, ticket and next step. A missing specialist or failed write
   stops only dependent assignments; report it and continue assessing others.
   Do not work around the write or ask Donald to perform ordinary scheduling.
4. Finish classifying the complete unfinished list while launched workers run.
   Dispatch every newly identified independent step through step 3. Update the
   single current table with each active assignment or concrete hold. An audit
   report naming preparation work becomes a bounded dispatch input, not the
   final result of the run. Refill independent useful work after each report.
   Preserve the runtime, approval and capacity boundaries above.

On each blocked or completed report, diagnose and dispatch the smallest
authorized removal first; do not turn missing evidence, a busy runner, a
finished worker or a spent worker budget into a whole-ticket external hold.
Record the exact remaining obstacle, evidence paths, current SHA, failed
hypotheses and spent experiments without renewing them. Confirm live In Progress
state and shared ownership, process and post findings, then dispatch the next
authorized specialist before yielding. Reconcile the single current table and
revisit eligible Backlog tickets; keep independent ready work running without
sacrificial idle workers.

OpenCode has no exposed `wait_agent` or self-scheduling loop here. Background
completion notifications resume coordination; do not poll children, sleep,
inspect private session storage or invent a wake-up command. If only running
children remain, hand back a concise pending status and their IDs. Before
stopping with no notifying child, finish the full unfinished-list pass and
check for executable planning, driver preparation, acceptance, review and CI.
For each remaining ticket, identify its next step, exact dependency, remover
and resume condition, including a shared owner, genuine hold or concrete
unavailable operation; recheck historical waits against current evidence.
Before a no-notification handback, ensure every unresolved blocker has active
specialist investigation or an evidenced external hold, not merely
"needs evidence", "budget spent" or "lane needed". Stop only when none of
those authorized steps can proceed. A setup-only runner
or completed audit supplies no continuation. Donald can resume with
`/orchestrate`. Never imply unattended continuation
without an actual pending notification or supported trigger.

Wind-down stops new assignments and finishes authorized validation, review,
push and exact-SHA CI. An immediate stop leaves an explicit handoff of pending
children, patches, request records and CI SHAs without launching new work.
Use the documented interruption or request cancellation only when Donald's
stop instruction authorizes it; otherwise report any still-running execution.
Preserve evidence for unfinished tickets and reconcile their live states when
authorized tool execution permits. Do not stop early based on a guessed
context size; OpenCode owns compaction.
