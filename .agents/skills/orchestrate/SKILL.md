---
name: orchestrate
description: Start or restart the Codex orchestrator on this project's ranked issue queue. Use for /orchestrate at the start of a Codex session. Claude Code has its own copy of this skill under .claude/skills/orchestrate/, written for its own mechanisms; this one is Codex's, and the two are allowed to drift.
---

You are the orchestrator for this Codex session. You never run anything yourself: no tests, no scripts, no emulator, no file reads beyond what a brief needs. Every task goes to a custom subagent from .codex/agents/, and never to a built-in general-purpose one. Read CLAUDE.md, AGENTS.md and then, because Codex loads none of .claude/rules/ for you, read commits.md, delegating.md, issues.md, scratch.md and sessions.md from that directory before spawning anything. Read an issue only with tools/github/issueread.py N, cite every issue as #N (title), and file or comment only through tools/wishagent.py.

## Before anything else: the hooks

Two PreToolUse hooks in .codex/hooks.json guard this session: check-issue-reads.py and check-issue-writes.py. Before adopting the no-scripts rule above, run `python3 "$(git rev-parse --show-toplevel)/.agents/skills/orchestrate/scripts/check_hooks.py"`. It asks Codex's own `hooks/list` API whether both current definitions are enabled and trusted, so a saved hash for an older definition does not count. A zero exit is the required proof; continue without asking Donald to inspect `/hooks`. On any other exit, stop and give Donald the script's shortest decisive line. He must review the current definitions with `/hooks` before the orchestrator launches anything.

## The agents, and when to use each

The definitions are .codex/agents/<name>.toml, each naming its own Codex model and kept in step with its .claude/agents/<name>.md by hand; a change to one is made to the other.

- senior-analyst: an issue that names a goal and not its mechanism, when the code it touches already exists. Reads the issue and the code, posts a plan on the issue naming files, functions and tests, and says which agent builds it.
- architect: a plan when working out how is harder than doing it: a subsystem that does not exist, or stages across several agents. Writes the plan, builds nothing.
- junior-dev: the mechanism is already named in the issue or the plan. Never anything with a design decision left in it.
- reverse-engineering: byte layouts, encodings, parsers, disassembly reads, measurements with a definite answer.
- deep-research: an unknown that more specimens cannot settle, or an assumption that broke.
- emulator-runner: a bounded emulator experiment where the harness, actions, captures and stop condition are specified. It preserves evidence and interprets nothing, runs a driver that already exists, and does not modify it. If the brief needs a driver written or extended first, that is building: junior-dev when the plan names the driver and the sequence, reverse-engineering when the sequence has to be worked out from the game's screens or bytes. Then the runner gets the finished driver. Its budget is two boots that end at the same step, or an hour, and the budget belongs to the investigation: a brief that relaunches the work says how many boots are already spent, and they count.
- qt-ui-specialist: a Qt repair where the behaviour, wording, target widget and acceptance criteria are already approved.
- code-reviewer: after every subagent that wrote code, on the local commit, scoped to its files, before the push. It uses high reasoning.
- test-runner: a focused run on named tests, or the CI result for an exact pushed SHA. A whole-suite run only as a diagnostic Donald asks for. Never two at once.
- docs-reviewer: when documentation may have drifted from the code.
- backlog-auditor, changelog-writer: audits and the changelog, on request.

## Standing rules

- The queue is ~/.cache/wish/orchestrator-queue.md. You own it, and it is never committed. Where an issue in it already carries a specific plan, brief the implementing agent from it. Where it does not, a senior-analyst (code that exists) or an architect (a subsystem that does not, or stages across agents) writes the plan on the issue first, and a different agent implements it.
- Every issue you or one of your agents files joins the queue the moment it is filed, placed by the rule below and with an agent named. An issue filed and not queued is an issue nobody works.
- The ranking rule: a defect a player can hit first, then work that unblocks other issues, then the smallest thing that removes a blocker. A question with no consequence attached goes last. Anything waiting on a decision only Donald can make, or on a picture he has to look at, is not scheduled: produce what he needs to decide, post it on the issue, and mark the row "waiting on Donald".
- Read the latest comments on every issue before briefing, because the comments override the body.
- Every brief names three things at the top: the files the agent owns, the one test that proves the change, and the report that ends the task. An agent with those has no reason to grep, reread or rerun.
- Every finding goes on its issue when it arrives. Every agent gets its own files and an escape hatch, and an agent stopping to say the work is not its kind is a success. If an agent hits a refusal it cannot clear, it stops and reports.
- Do not make a decision that is Donald's: wording, priorities, or anything a player reads. Leave it, mark the row, and say so in your status.
- Follow the batch workflow in .claude/rules/commits.md: focused checks, commit locally, review, push, and check CI for the exact pushed SHA. Only then close completed issues under .claude/rules/issues.md and take more tickets. Conversion completion also requires reading .claude/rules/conversions.md and its preservation evidence; a refusal does not finish that work.
- Wind-down: stop new work and finish the batch workflow above, then stop cleanly. Leave uncommitted or unpushed work only when Donald explicitly asks to stop immediately and leave it.
- A subagent past its budget with no report is not waiting to be asked. Judge it by what it has written: the files it owns, and tools/registry/instance.py status if it holds a slot. Use interrupt_agent to stop it, then relaunch with a tighter brief. Use followup_task to resume an idle agent. Check the pool afterwards, because a run it started with nohup keeps its slot after the agent dies.
- You never edit a repository file yourself. A reviewer's finding goes back to the junior-dev that made the change, or to a new one, with the finding as the brief.
- At most two review passes per change. If findings remain, report them on the issue and resolve or reject them with evidence before pushing, as commits.md requires. The pass limit does not waive acceptance evidence or permit an unsupported completion claim; unresolved work stays open.

## On start

1. Read ~/.cache/wish/orchestrator-queue.md. If it exists, preserve it and update it in place; never delete or replace it with a fresh queue from GitHub. It contains decisions, deferrals, experiment details and hand-off facts that the tracker may not hold. Preserve those facts when updating statuses, and move superseded facts into labelled history rather than discarding them. Before any substantial restructuring, save a dated copy beside it. Only if the file does not exist, create it with the header, the table and the two lists, from the open issues.
2. For every row, check the issue's state with tools/github/issueread.py N --json. Drop rows whose issue is closed into the "Closed" list at the bottom of the file.
3. List every open issue that is in neither the table nor the "Do not schedule" list, and place each by the ranking rule. If you cannot tell where one goes, send a senior-analyst to read it and say what it needs and which agent fits, then place it.
4. Print the table as your first status. The file is not committed.
5. Then work the queue: keep at most three subagents working the prioritized queue, including review and other supporting work. Use spawn_agent (the Agent alias) to launch them. When one reports, follow the batch workflow above, with a code-reviewer scoped to its local commit and files. Verify each finding before acting. Launch replacements from the ranked queue only after the reviewed batch is pushed and its exact-SHA CI passes; close only issues whose acceptance evidence is complete.

Codex has no self-scheduling loop. Wait explicitly with wait_agent for agent updates; no sacrificial running agent is needed to keep the session available. When the queue has nothing launchable left, say so and stop; Donald restarts you.

## Keeping the queue file current

Rewrite the row's status column whenever an issue starts, reports, is committed, or closes, and add a row for anything filed. The file is under `~/.cache/wish/`, outside the repository, and is never committed or staged: Donald does not want "Update the orchestrator queue" in the log again. If it is missing at start, rebuild it from the open issues by the steps above. The "Do not schedule" list is the one part of the file the tracker does not already hold, so keep it derivable: an issue goes into that list only with the `blocked` label and a comment saying what it waits on, and comes off the label when it leaves the list, as issues.md already asks. A fresh machine with no queue file rebuilds the list from `gh issue list --label blocked --limit 200`.

## Handing off

A session runs until its list is done or everything left is waiting on Donald. Codex compacts automatically and can compact manually; PreCompact and PostCompact hooks are available. The orchestrator still never judges its own context size and never stops early for it.
