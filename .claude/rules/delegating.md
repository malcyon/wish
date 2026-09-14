# Delegating to subagents

**The default is to delegate.** Reading a lot of files, running a long
experiment, disassembling, driving the emulator, writing something up -- all of
it goes to a subagent. The main window coordinates and answers questions.

The reason is context, and context is the scarce resource. A subagent's tool
output never enters the main window: a long grep out there costs nothing that a
long grep in here does.

Stays in the main window: Donald's questions, short edits, and anything where
writing the brief costs more than doing the work.

## Choosing the agent

One definition, `.claude/agents/<name>.md`, drives both tools -- Claude Code
reads it directly, and `tools/gencodex.py` generates Codex's
`.codex/agents/<name>.toml` from it. Only the model differs, since a Claude
model name has no Codex counterpart: the two columns below record each tool's
configured model, not the same decision spelled two ways.

| agent | Claude | Codex | when |
|---|---|---|---|
| `reverse-engineering` | Opus | `gpt-5.6-sol` | byte layouts, checksums, encodings, and the parsers that prove they were read right -- including a disassembly read. |
| `deep-research` | **Fable** | `gpt-6-astra` | the hardest reverse engineering, where rigorous analysis is the whole job -- a question more specimens will not answer |
| `architect` | **Fable** | `gpt-6-astra` | a plan for another agent to execute, when working out how to do the work is harder than doing it. Writes the plan, does not build it. |
| `senior-dev-reviewer` | Opus | `gpt-5.6-sol` | an issue that names a goal and not its mechanism, when the code it touches is already in the tree: reads the issue and the code, posts a plan naming files, functions and tests, and says which agent builds it. Writes the plan, does not build it. |
| `junior-dev` | Sonnet | `gpt-5.6-terra` | the issue's "What would fix it" names the **mechanism**: a port, a deduplication, narrowing a check. Never anything with a design decision left in it |
| `general-purpose` | inherits | unset -- inherits | everything else, including work that looks like reverse engineering and is not |
| `code-reviewer` | Sonnet | `gpt-5.6-terra` | after **every** subagent that wrote code, on the local commit, before it is pushed. Scope it to the files it owns |
| `qt-ui-specialist` | Sonnet | `gpt-5.6-terra` | approved Qt repairs and platform layout diagnosis, with widget/state, exact strings, and acceptance criteria already supplied |
| `emulator-runner` | Sonnet | `gpt-5.6-terra` | a bounded, specified emulator experiment through the instance pool; captures and preserves evidence without interpreting unknown fields |
| `docs-reviewer` | Sonnet | `gpt-5.6-terra` | when documentation may have drifted from the code. Scope it to the files it owns |
| `backlog-auditor` | Sonnet | `gpt-5.6-terra` | before a refinement pass, or when the backlog has grown unwieldy; it reports audits and bounded briefs only |
| `changelog-writer` | Sonnet | `gpt-5.6-terra` | after a batch of work lands, and before cutting a release |
| `test-runner` | **Haiku** | `gpt-5.6-luna` | the whole suite before a push, or a scoped run on named files. **The one agent that may run everything**, because it exists so that one run does not block the window Donald is asking questions in. It reports and fixes nothing |

**Cost is not the filter on `deep-research` and `architect`; fit is.** Donald,
2026-09-04, of Fable, Claude Code's name for the tier behind both (Codex runs
the same two agents on its own top tier, `gpt-6-astra`): *"consider
deep-research and architect as available options to use when necessary. I
don't want to waste tokens where another agent could do the job. But I don't
think using Fable will run us out of tokens anytime soon."* So the question to
ask is the same one the table asks of every row -- does this agent's
definition already describe the work? -- and not whether the budget can stand
it. Sending a measurement to `deep-research` is still waste, because a
`reverse-engineering` agent would do it as well; sending it a question that
more specimens cannot answer is what it is for.

**What earns `deep-research`** is an assumption that broke. On
2026-09-04 the project had been reading a `.SPC` effect's duration of zero as
"permanent", and SILAS turned up carrying two running spells at duration zero
-- so the discriminator is not in the bytes anybody has been reading, and no
number of further specimens says what it is. Reading the engine's own expiry
routine does. That is the test: **would another hour of measuring answer it?**
If yes, it is not this agent's work.

**Widened on 2026-09-05: an issue whose remaining obstacle is an UNKNOWN goes
here by default.** Donald: *"Honestly, just use the deep-research agent to
figure out the unknowns. That should help a lot. You can't use it for
everything, but you could use it for the hardest tickets."* So the broken
assumption above is a **sufficient** reason to route here rather than the only
one, and a ticket that has sat because nobody could say what some bytes hold is
this agent's work now. What still does not come here is ordinary building and
ordinary measuring: a `reverse-engineering` agent does those as well, and
sending them to `deep-research` or `architect` buys nothing.

**`senior-dev-reviewer` sits between `architect` and `junior-dev`, and the
split is where the difficulty lives.** Donald, 2026-09-14: an orchestrator
that finds a bug and files it needs a higher model to turn the ticket into a
plan, and `architect` on Fable was doing that for bugs that did not need an
expert. So: when the code that must change is already in the tree and the
question is which lines, which helper already does it and what the test
asserts, it goes to `senior-dev-reviewer`, which posts the plan on the issue
and names the builder. When working out *how* is the hard part -- an unknown
in the bytes, a subsystem that does not exist, stages across several agents
-- it goes to `architect`, or to `deep-research` if the obstacle is an
UNKNOWN. A `senior-dev-reviewer` that finds it is holding `architect`'s work
stops and says so, and that is a completed task.

**`junior-dev`'s filter is a property of the issue body** -- does it name the
mechanism, or only the goal? `#71 (Character draws on top of itself when the header is squeezed to its floor)`
looked like ordinary work and took nine rounds and a `QTableView` subclass.
`#73 (The DOSBox-X harness refuses to start without DOSBox 0.74, which it never runs)` named the two candidate approaches and said
which was smaller, and that is what made it assignable.

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

**Tell the agent to run its own test files, not the suite.** `pytest` on what
it touched, plus `ruff` and `genui.py --check`. The whole suite runs once,
before the push -- `.claude/rules/commits.md`. Six agents each running all
3,190 tests is six copies of Qt on one machine, and on 2026-09-04 that cost a
reviewer its run. Tell it to run in the **foreground with a timeout** as well:
a backgrounded `pytest` here has come back `killed` rather than with a result,
and five agents ended turns that day waiting on runs that never reported.

**`test-runner` is the exception, and it is the only one.** That one run may go
to it rather than being made in the main window, because a four-minute run in
here is four minutes Donald cannot ask anything. It is the reason that agent
exists. Everything above still binds it: foreground, explicit timeout, never
backgrounded. **Never start two.**

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
oracle -- it has reported a deliberate lever with a test and a docstring as
dead code. Check the claim, then fix or reject it, and rejecting it is a normal
outcome rather than a failure of the review.

Why these rules exist, and the incidents behind them:
`docs/160-why-these-rules.md`, "Delegating".
