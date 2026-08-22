# Working notes for Claude

## Conciseness

Say the thing once, in as few words as carry it. Length is not thoroughness.

Cut: preamble, restating the request, summarising what you just did in the same
breath as doing it, hedging, and "as you can see". Keep: offsets, byte values,
exact error strings, the reason a choice was made.

If a sentence would survive deletion without the reader losing anything, delete
it.

## Delegating to subagents

**The default is to delegate.** Reading a lot of files, running a long
experiment, disassembling, driving the emulator, writing something up -- all of
it goes to a subagent. The main window coordinates and answers questions.

The reason is context, and context is the scarce resource. A subagent's tool
output never enters the main window: a long grep out there costs nothing that a
long grep in here does.

**Give each agent its own files.** Several agents in one working tree will
collide. Assign non-overlapping areas, and say which in the brief.

**Subagents do not commit.** As things stand the main window makes the commits,
so nothing races the index.

**Emulator work goes through the instance pool.** VICE serves exactly one
binary-monitor connection *per process*, so running two things at once means
two emulators, not two connections. `tools/instance.py claim` hands back a
binary-monitor port, a text-monitor port, a command port, an X display, a work
directory and a `vicerc`, and holds the lease for as long as your process
lives. `Session(disk, slot=slot)` takes it from there; `POR_HEADLESS=1` keeps
the window off Donald's desktop. Say in the brief which slot the agent has.
Two instances have been proven to coexist -- `docs/123-parallel-sessions.md` §0.

**Port 6502 is Donald's.** The pool allocates 6520 and upwards and never
touches 6502, 6510 or 6600. Anything on those is a game a human started from
the desktop menu -- do not attach to it, do not probe it, do not kill it.

**Never kill a process by name.** Not `pkill -x x64sc`, not `pkill -x Xephyr`.
Kill only the process group your own slot launched -- `Session.terminate()`, or
`slot.teardown()`. Reclaim another slot only when `tools/instance.py reap` says
its lease is unheld; a slot whose lease is held is somebody's, however dead it
looks. The one time this rule was broken, what died was Donald's own window.

**The pool owns the lifecycle.** Allocate, launch, tear down. Do not attach to
an emulator you did not launch, and do not launch one outside the pool -- an
instance nobody leased cannot be told from a human's.

**Never point VICE at Donald's config.** Every pooled instance gets its own
`vicerc` seeded from his, with `SaveResourcesOnExit=0`, so nothing an agent
runs can write settings back. His file is read as a template and never opened
for writing.

**The brief carries the standing constraints**, because a subagent starts cold:
never write to `/home/donald/c64/Pool of Radiance Disks/`, never commit the
game's code, art or data ("What must never enter this repository"), and
leave the VICE configs alone.

Stays in the main window: Donald's questions, short edits, and anything where
writing the brief costs more than doing the work.

## Commits

**Keep a commit message to one sentence.** That is the whole rule, and it
exists to stop the assistant writing an essay in every message. Reasoning
belongs in `docs/50-experiments.md`, which exists for exactly that.

One commit per finding, where that is practical. Three findings in one commit
is worse for future archaeology than three commits, even when the files
overlap -- but do not spend longer splitting a commit than the split is worth.

```
Find the staging page at $5500
```

## What must never enter this repository

This is a reverse-engineering project. It documents a game it does not ship.

**Never commit, in any form:**

* the game's **art, music, or sound** -- sprites, tilesets, portraits, SID
  tunes, sampled audio;
* the game's **manuals, cluebooks, maps or journal entries**, scanned,
  transcribed or retyped;
* the game's **executable code**, whole or in part -- overlays, PRG files, boot
  images, or any extract of them;
* **disassembly of that code** as a listing. Quoting as much of it as a finding
  actually needs -- an address, a handful of instructions, the shape of a
  handler with its operands left as placeholders -- is commentary and is fine.
  A dump of a routine is not.
* the game's **data files** -- maps, tables, scripts, character records -- as
  committed bytes, including as test fixtures.

Disk images are already ignored; keep them under `work/`, which is
`.gitignore`d, and read them at run time from wherever the player keeps theirs.

**Tests get their data from the player's own disks, not from the repository.**
`tests/gamedata.py` is how: `game_file("GEO04")` reads it off whichever `POOL*`
disk carries it and skips when there are none, and `synthetic_geo()` builds a
well-formed map from the format we documented for the cases that only need
*a* file rather than a specific one. A fixture that is a slice of a game file
is the same copy the rule forbids, merely renamed.

`tests/fixtures/` holds the player's own saved games and nothing else. Its
contents are on an allowlist in `tests/test_repository_contents.py`, which
fails the build if anything else appears there or if a disk image, executable,
image or audio file is committed anywhere. **Do not add to that allowlist** --
if a test needs game data, read it from the disks or generate it.

**Citing is not copying.** Quoting the code a finding rests on is exactly what
`docs/50-experiments.md` is for and is encouraged. It does not have to be two
or three instructions: Donald has ruled that a short block is fine, so do not
agonise over the length of a citation that carries evidence. A dump of a
routine is not.

Describe, cite, measure, and generate. Do not copy.

## Documentation

`docs/50-experiments.md` is the only place that gets length, because the whole
project is the reasoning. Everything else is a lookup table: state the finding,
give the evidence in one clause, link the experiment by name.

Prune when a claim changes. A doc that accretes corrections without deleting the
superseded text is how the contradictions got in.

**Leave the top-level `README.md` alone** unless Donald asks for it by name. It
is the page a stranger reads first and it is his, not a scratchpad the assistant
tidies in passing. A finding goes in `docs/`; if it belongs in the README too,
say so and wait to be asked.

**`docs/TASKS.md` is the open task list, and it is kept current.** Close a task in
the same commit that finishes it; add one when the work is agreed, not when it
starts. Every task has a code, and **a code belongs to one task for life** --
when a task closes its code retires with it and new work takes the next free
number, so `P44` means the same thing in a conversation three weeks apart.
Never renumber to close a gap. Donald refers to tasks by code, so a code that
moved is worse than no code at all.

**A confirmed bug in the original game goes in `goldbox-bugs.md`** -- but only
if a player can run into it. That file is written for a human who wants to read
something interesting, not for completeness, and it is the shortest document in
the project on purpose.

The test is one question: **what does the player see?** If the honest answer is
"nothing", it is not going in the front-door file. Latent defects, cosmetic
faults, duplicated labels, flags written and never read -- all real, none
interesting -- go in `docs/125-bug-notes.md` instead, numbered `N1` upwards so
the two lists cannot be confused.

Four rules about the front-door file, all learned the hard way:

* **It is for bugs.** Not for unfinished features, not for cut content, not for
  spelling mistakes, and not for the record of our own errors. Those are
  interesting in their own way and they all live in `docs/125-bug-notes.md`.
* **Ours is not theirs.** Most things that looked like a game bug were our own
  misreading -- a wrong stride, an off-by-one dump, an array read half its
  width. They go in the notes file, as ours, never in the list.
* **Log it when it is CONFIRMED** -- reproduced in the running game, or proven
  from the bytecode beyond argument. A suspicion stays in
  `docs/50-experiments.md` until it earns promotion.
* **Describe the defect, not the bypass.** Copy-protection *research* stays in
  the separate private repository, but a protection routine that computes the
  wrong answer is a bug like any other and is logged. Say what the code does
  wrong and what a player sees; do not publish the tables, the arithmetic or
  anything else that amounts to defeating the protection.

**Name the consequence, not the mechanism.** A title and a summary line say
what goes wrong for the player; the mechanism is what the entry is *for*.
"Sokol Keep's dead elf comes back every time you return" is the bug. "The dead
elf is guarded on an address nothing writes" is the cause, and it means nothing
to somebody who has not read the entry yet. Call things by their ordinary
names, too: it is copy protection and a code wheel, not a verification check.

Each entry says what the game does, what it should do, the evidence, and what
the player sees. Keep the addresses to what carries the evidence -- the entry
has to make sense to somebody who has never read a disassembly.

## Code comments

Comment the *why*, and only when it is not obvious. A field note that carries
evidence — "10 for every player character; monsters carry their real AC here" —
earns its lines. Restating the code does not.

`por/layout.py` is the exception: its notes are the field documentation and are
generated into `docs/20-character-record.md`. They can be long. Run
`python3 tools/gendocs.py` after touching them.

## Replies

Lead with the answer. Findings before method. Tables over prose for anything
with more than three data points. No closing summary of a reply the user just
read.

Report failures with the shortest decisive line of output, not the whole log.
