# Delegating to subagents

**The default is to delegate.** Reading a lot of files, running a long
experiment, disassembling, driving the emulator, writing something up -- all of
it goes to a subagent. The main window coordinates and answers questions.

The reason is context, and context is the scarce resource. A subagent's tool
output never enters the main window: a long grep out there costs nothing that a
long grep in here does.

Stays in the main window: Donald's questions, short edits, and anything where
writing the brief costs more than doing the work -- except an orchestrator
session, which edits nothing, so that exemption does not apply to it.

## Choosing the agent

Each agent has two hand-kept definitions, `.claude/agents/<name>.md` for
Claude Code and `.codex/agents/<name>.toml` for Codex, and a change to one is
made to the other by hand. Only the model differs, since a Claude model name
has no Codex counterpart: the two columns below record each tool's
configured model, not the same decision spelled two ways.

| agent | Claude | Codex | when |
|---|---|---|---|
| `reverse-engineering` | Opus | `gpt-6-sol` (max) | byte layouts, checksums, encodings, and the parsers that prove they were read right -- including a disassembly read. |
| `deep-research` | **Fable** | `gpt-6-astra` (max) | the hardest reverse engineering, where rigorous analysis is the whole job -- a question more specimens will not answer |
| `architect` | **Fable** | `gpt-6-astra` (max) | a plan for another agent to execute, when working out how to do the work is harder than doing it. Writes the plan, does not build it. |
| `senior-analyst` | Opus | `gpt-6-sol` (max) | an issue that names a goal and not its mechanism, when the code it touches is already in the tree: reads the issue and the code, posts a plan naming files, functions and tests, and says which agent builds it. Writes the plan, does not build it. |
| `junior-dev` | Sonnet | `gpt-6-sol` (medium) | the issue's "What would fix it" names the **mechanism**: a port, a deduplication, narrowing a check. Never anything with a design decision left in it |
| `general-purpose` | inherits | unset -- inherits | everything else, including work that looks like reverse engineering and is not |
| `code-reviewer` | Sonnet | `gpt-6-sol` (high) | after **every** subagent that wrote code, on the local commit, before it is pushed. Scope it to the files it owns |
| `qt-ui-specialist` | Sonnet | `gpt-6-sol` (high) | approved Qt repairs and platform layout diagnosis, with widget/state, exact strings, and acceptance criteria already supplied |
| `emulator-runner` | Sonnet | `gpt-6-sol` (medium) | a bounded, specified emulator experiment through the instance pool; captures and preserves evidence without interpreting unknown fields |
| `docs-reviewer` | Sonnet | `gpt-6-sol` (high) | when documentation may have drifted from the code. Scope it to the files it owns |
| `backlog-auditor` | Sonnet | `gpt-6-sol` (high) | before a refinement pass, or when the backlog has grown unwieldy; it reports audits and bounded briefs only |
| `changelog-writer` | Sonnet | `gpt-6-sol` (high) | after a batch of work lands, and before cutting a release |
| `test-runner` | **Haiku** | `gpt-6-luna` (medium) | a focused run on named tests, the CI result for an exact pushed SHA, or a whole-suite diagnostic when one is explicitly asked for, so that the run does not block the window Donald is asking questions in. It reports and fixes nothing |

**Cost is not the filter on `deep-research` and `architect`; fit is.** Fable is
Claude Code's name for the tier behind both (Codex runs the same two agents on
its own top tier, `gpt-6-astra`). So the question to ask is the same one the
table asks of every row -- does this agent's definition already describe the
work? -- and not whether the budget can stand it. Sending a measurement to
`deep-research` is still waste, because a `reverse-engineering` agent would do
it as well; sending it a question that more specimens cannot answer is what it
is for.

**What earns `deep-research`** is an assumption that broke: a field the project
has been reading one way turns up carrying a value the reading cannot explain,
so the discriminator is not in the bytes anybody has been reading, and no
number of further specimens says what it is. Reading the engine's own code
that uses the field does. That is the test: **would another hour of measuring
answer it?** If yes, it is not this agent's work.

**An issue whose remaining obstacle is an UNKNOWN goes to `deep-research` by
default.** The broken assumption above is a **sufficient** reason to route
here, not the only one, and a ticket that has sat because nobody could say
what some bytes hold is this agent's work. What still does not come here is
ordinary building and ordinary measuring: a `reverse-engineering` agent does
those as well, and sending them to `deep-research` or `architect` buys
nothing.

**`senior-analyst` sits between `architect` and `junior-dev`, and the
split is where the difficulty lives.** When the code that must change is
already in the tree and the question is which lines, which helper already does
it and what the test asserts, it goes to `senior-analyst`, which posts the plan
on the issue and names the builder. When working out *how* is the hard part --
an unknown in the bytes, a subsystem that does not exist, stages across several
agents -- it goes to `architect`, or to `deep-research` if the obstacle is an
UNKNOWN. A `senior-analyst` that finds it is holding `architect`'s work
stops and says so, and that is a completed task.

**`junior-dev`'s filter is a property of the issue body** -- does it name the
mechanism, or only the goal? An issue that reads as ordinary work but names no
mechanism is not assignable, however small it looks. One that names the
candidate approaches and says which is smaller is.

**Send work to the agent whose definition already describes it.** Each
`.claude/agents/*.md` says what its agent is for, and that sentence is the
routing rule. The cost of reaching past a specialist is not only the model: a
specialist has read its own domain's rules, and a general-purpose agent has to
be told them in the brief -- whatever the brief forgets is what goes wrong.
**Before writing a brief, read the definitions and ask which one already owns
this.**

## Writing the brief

**The root alone spawns agents.** A brief must stand without conversation
history: give the actual approved scope or precise user-decision reference,
task target, owned and excluded files, relevant evidence paths, chosen command
or mechanism, acceptance criteria, and an escape hatch. A plan, issue, earlier
report, or remembered convention is evidence, not fresh approval. Missing
approval is a gap to report, never permission inferred. Workers return missing
information or work for another role to the root, continue independent
authorized work where possible, and return one compact report with evidence
paths, the shortest decisive output, negative results, and limitations.

**Give each agent its own files.** Several agents in one working tree will
collide. Assign non-overlapping areas, and say which in the brief.

**And do not edit a file you have assigned to an agent.** If you must touch
one, say so in a message to the agent, and prefer a targeted edit -- putting
back the one hunk you changed -- to restoring the whole file you remember.

**Tell the agent to run the tests its change affects, not the suite.**
`pytest` on those, including any relevant tests that read game data, plus
`ruff` and `genui.py --check`. CI runs the full suite on the pushed commit --
`.claude/rules/commits.md`. Six agents each running the whole suite is six
copies of Qt on one machine. Tell it to run in the
**foreground with a timeout** as well: a backgrounded `pytest` here can come
back `killed` rather than with a result, and an agent waiting on a run that
never reports ends its turn with nothing.

**`test-runner` takes a run off the main window**, because a run in here is
time Donald cannot ask anything. It runs a whole-suite diagnostic only when
somebody asks for one by name. Everything above still binds it: foreground,
explicit timeout, never backgrounded. **Never start two.**

**Say in the brief what `AGENTS.md` cannot say for you, because it does not
know this task.** Claude loads its six unscoped rule files into each subagent
at launch. Codex agents must read applicable rules through `AGENTS.md`'s
routing table. What a brief adds is specific to
the task: which files the agent owns, any `paths:`-scoped rule it needs but
will not itself touch a matching file for (`gui-text.md`, say, when the work is
a decision rather than an edit), its emulator slot if it has one, and its
escape hatch.

**Every agent gets an escape hatch, and using it is a success.** If the work
turns out to need something the agent is not for -- a general-purpose agent
finding it genuinely needs a disassembly read -- it stops and says so, and the
work is re-routed. An agent that presses on into a decision that was not its
own costs more than the re-route. Say this in the brief.

## Commit, then review, then push

**Subagents do not commit.** The main window makes the commits, so nothing
races the index.

**Commit a subagent's work before you review it, and push only after.** The
sequence is: the agent reports, the main window **commits locally**, the
`code-reviewer` runs, the findings are fixed or rejected with a reason, and
*then* it is pushed. A local commit costs nothing, is never pushed unreviewed,
and turns a reviewer's accident into `git revert`.

If the review rejects the work outright, the commit is reverted or the branch
reset -- deliberately, by the main window, which is a different thing from
losing it.

**Every subagent that wrote code gets reviewed.** An agent that has spent two
hours inside a problem is the worst possible judge of whether its own answer is
right. This does not apply to a subagent that only wrote documentation or only
ran experiments.

**Scope a reviewer explicitly when more than one agent is in the tree.** Name
the commit SHA or range, files it owns, and files it must ignore, or it will
report another agent's half-finished change as a finding against the one under
review.

**Verify a finding before acting on it.** The reviewer is a reader, not an
oracle -- it can report a deliberate lever with a test and a docstring as
dead code. Check the claim, then fix or reject it, and rejecting it is a normal
outcome rather than a failure of the review.

Why these rules exist, and the incidents behind them:
`docs/160-why-these-rules.md`, "Delegating".
