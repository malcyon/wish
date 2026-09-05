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

| agent | model | when |
|---|---|---|
| `reverse-engineering` | Opus | byte layouts, checksums, encodings, and the parsers that prove they were read right -- including a disassembly read. |
| `deep-research` | **Fable** | the hardest reverse engineering, where rigorous analysis is the whole job -- a question more specimens will not answer |
| `architect` | **Fable** | a plan for another agent to execute, when the shape of the work is the hard part. Writes the plan, does not build it. Also Fable |
| `junior-dev` | Sonnet | the issue's "What would fix it" names the **mechanism**: a port, a deduplication, narrowing a check. Never anything with a design decision left in it |
| `general-purpose` | inherits | everything else, including work that looks like reverse engineering and is not |
| `code-reviewer` | Sonnet | after **every** subagent that wrote code, on the local commit, before it is pushed. Scope it to the files it owns |
| `docs-reviewer` | Sonnet | when documentation may have drifted from the code. Scope it to the files it owns |
| `backlog-auditor` | Sonnet | before a refinement pass, or when the backlog has grown unwieldy. **It owns the issues**, including the banned-words sweep of titles, bodies and comments |
| `changelog-writer` | Sonnet | after a batch of work lands, and before cutting a release |

**Cost is not the filter on the two Fable agents; fit is.** Donald, 2026-09-04:
*"consider deep-research and architect as available options to use when
necessary. I don't want to waste tokens where another agent could do the job.
But I don't think using Fable will run us out of tokens anytime soon."* So the
question to ask is the same one the table asks of every row -- does this
agent's definition already describe the work? -- and not whether the budget can
stand it. Sending a measurement to `deep-research` is still waste, because a
`reverse-engineering` agent would do it as well; sending it a question that
more specimens cannot answer is what it is for.

**The shape that earns `deep-research`** is an assumption that broke. On
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
sending them to Fable buys nothing.

**`junior-dev`'s filter is a property of the issue body** -- does it name the
mechanism, or only the goal? `#71 (Character draws on top of itself when the header is squeezed to its floor)`
looked like ordinary work and took nine rounds and a `QTableView` subclass.
`#73 (The DOSBox-X harness refuses to start without DOSBox 0.74, which it never runs)` named the two candidate shapes and said
which was smaller, and that is what made it assignable.

**Send work to the agent whose definition already describes it.** Each
`.claude/agents/*.md` says what its agent is for, and that sentence is the
routing rule. The cost of reaching past a specialist is not only the model: a
specialist has read its own domain's rules, and a general-purpose agent has to
be told them in the brief -- whatever the brief forgets is what goes wrong.
**Before writing a brief, read the definitions and ask which one already owns
this.**

## Writing the brief

**Give each agent its own files.** Several agents in one working tree will
collide. Assign non-overlapping areas, and say which in the brief.

**And do not edit a file you have assigned to an agent.** If you must touch
one, say so in a message to the agent, and prefer a targeted edit -- putting
back the one hunk you changed -- to restoring the whole file you remember.

**Tell the agent to run its own test files, not the suite.** `pytest` on what
it touched, plus `ruff` and `genui.py --check`. The whole suite is the main
window's, once, before the push -- `.claude/rules/commits.md`. Six agents each
running all 3,190 tests is six copies of Qt on one machine, and on 2026-09-04
that cost a reviewer its run. Tell it to run in the **foreground with a
timeout** as well: a backgrounded `pytest` here has come back `killed` rather
than with a result, and five agents ended turns that day waiting on runs that
never reported.

**The brief carries the standing constraints**, because a subagent starts cold:
never write to the player's disk directory, never commit the game's code, art
or data, never run the git commands that revert a file, and leave the VICE
configs alone. Name the emulator slot the agent has, if it needs one.

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

**Scope a reviewer explicitly when more than one agent is in the tree.** A
`code-reviewer` starts with `git diff`, and with three agents working that diff
is three people's work. Name the files it owns and name the ones it must
ignore, or it will report another agent's half-finished change as a finding
against the one you are reviewing.

**Verify a finding before acting on it.** The reviewer is a reader, not an
oracle -- it has reported a deliberate lever with a test and a docstring as
dead code. Check the claim, then fix or reject it, and rejecting it is a normal
outcome rather than a failure of the review.

Why these rules exist, and the incidents behind them:
`docs/160-why-these-rules.md`, "Delegating".
