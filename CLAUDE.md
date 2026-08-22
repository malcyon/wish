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
two emulators, not two connections. `docs/123-parallel-sessions.md` plans the
pool; **until `tools/instance.py` exists, it is still one agent at a time**,
and the brief says which.

**Port 6502 is Donald's.** The pool allocates 6520 and upwards and never
touches 6502 or 6510. Anything on those is a game a human started from the
desktop menu -- do not attach to it, do not probe it, do not kill it.

**Never kill a process by name.** Not `pkill -x x64sc`, not `pkill -x Xephyr`.
Kill only the process group your own slot launched. A slot that looks dead may
be somebody's. The one time this rule was broken, what died was Donald's own
window.

**Never point VICE at Donald's config.** A pooled instance gets its own
`vicerc` seeded from his, with `SaveResourcesOnExit=0`, so nothing an agent
runs can write settings back.

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

**A confirmed bug in the original game goes in `goldbox-bugs.md`.** That file is
the register of defects in SSI's own code and data, and it is the reason to keep
one: a bug found twice is a bug found once too often. Log it when it is
**CONFIRMED** -- reproduced in the running game, or proven from the bytecode
beyond argument. A suspicion goes in `docs/50-experiments.md` until it earns
promotion.

Two rules about that file, both learned the hard way:

* **Ours is not theirs.** Most things that looked like a game bug were our own
  misreading -- a wrong stride, an off-by-one dump, an array read half its
  width. Those belong in the "not their bugs" section as our errors, never in
  the list.
* **Describe the defect, not the bypass.** Copy-protection *research* stays in
  the separate private repository, but a protection routine that computes the
  wrong answer is a bug like any other and is logged. Say what the code does
  wrong and what a player sees; do not publish the tables, the arithmetic or
  anything else that amounts to defeating the check.

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
