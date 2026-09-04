---
paths:
  - "docs/**"
  - "**/README.md"
  - "INDEX.md"
---

# Documentation

**A write-up's permanent home is `docs/`, never `work/`.** `work/` holds the
game's own bytes and anything derived byte for byte from them, and it is
gitignored, so nothing in it survives. The *reasoning* about those bytes is not
game data: a write-up that argues from evidence to a conclusion belongs in
`docs/`, cited by a path that survives. **A tool that regenerates an artefact
belongs in `tools/`.**

If a working file under `work/` would take more than a session to reproduce,
write its findings into a `docs/` page **before** the working file is deleted.
`tests/test_repository_contents.py` fails the build on a new `work/` path cited
from `docs/` or a package unless the file exists or its own text says it is
lost -- 32 write-ups were lost that way in
`#136 (Thirty-two cited write-ups are gone, because the knowledge base pointed
into gitignored scratch)`.

**A new file means a new row in that directory's `README.md`.** Every package
directory carries one -- a table of `file` and `purpose`, one line each -- and
`INDEX.md` at the top level says what each directory is for. Add the row in the
same change that adds the file: a table that is only mostly true is worse than
no table, because the gap is invisible. The same goes for a file that moves or
is deleted.

**The row says what the file is *for*, not what it is named.** "Character record
layout" is worthless beside a file called `layout.py`; "the 580-byte character
record as a declarative table of fields, each with a confidence grade" earns its
place. If a file is generated, or generates something, the row says so.

**`docs/50-experiments.md` is the only place that gets length**, because the
whole project is the reasoning. Everything else is a lookup table: state the
finding, give the evidence in one clause, link the experiment by name.

**A wrong document gets corrected, not escalated.** Donald, 2026-09-01: *"If you
find something wrong in a document, you can just update the document. You don't
need to block on me. Use your best judgement."* Fix it in the same session you
find it; do not open an issue for it. Two things a correction owes:

* **Delete the superseded text rather than layering on it.** A page that
  accretes corrections without pruning is how the contradictions got in.
* **Say why it changed**, in a sentence, where the claim was. A correction with
  no reason is the same trap with the values swapped.

If the wrong claim held up a *conclusion* rather than a detail, say what the
conclusion should be now rather than quietly fixing the line.

**Leave the top-level `README.md` alone** unless Donald asks for it by name. It
is the page a stranger reads first and it is his. A finding goes in `docs/`; if
it belongs in the README too, say so and wait to be asked.

**The open work list is GitHub issues.** `docs/TASKS.md` and its `P` codes are
retired; do not cite a P-code in new work.

## The two bug files

**A confirmed bug in the original game goes in `goldbox-bugs.md`** -- but only
if a player can run into it. It is written for a human who wants to read
something interesting, and it is the shortest document in the project on
purpose. The test is one question: **what does the player see?** If the honest
answer is "nothing", it goes in `docs/125-bug-notes.md` instead, numbered `N1`
upwards so the two lists cannot be confused.

Four rules about the front-door file:

* **It is for bugs.** Not unfinished features, not cut content, not spelling
  mistakes, and not the record of our own errors -- those all live in
  `docs/125-bug-notes.md`.
* **Ours is not theirs.** Most things that looked like a game bug were our own
  misreading -- a wrong stride, an off-by-one dump, an array read half its
  width. They go in the notes file, as ours.
* **Log it when it is CONFIRMED** -- reproduced in the running game, or proven
  from the bytecode beyond argument. A suspicion stays in
  `docs/50-experiments.md` until it earns promotion.
* **Describe the defect, not the bypass.** A protection routine that computes
  the wrong answer is a bug like any other and is logged. Say what the code does
  wrong and what a player sees; do not publish the tables, the arithmetic or
  anything else that amounts to defeating the protection.

**Name the consequence, not the mechanism.** "Sokol Keep's dead elf comes back
every time you return" is the bug; "the dead elf is guarded on an address
nothing writes" is the cause, and it means nothing to somebody who has not read
the entry yet. Call things by their ordinary names: it is copy protection and a
code wheel, not a verification check. Keep the addresses to what carries the
evidence -- the entry has to make sense to somebody who has never read a
disassembly.

**Two things every bug entry needs and most bug reports never have.**

**How a player ends up there.** Not the trigger in memory -- the situation.
"You save on the road within sight of a place you have not found yet, and
reload" is how somebody arrives at bug 10; "the paint runs on entry and not on
load" is why it happens. Both belong in the entry and they are not the same
sentence. Write the first one even when it is unflattering: **"no player can
reach this" is an answer**, and it is the answer that moves an entry out of
`goldbox-bugs.md` and into `125-bug-notes.md`.

**The steps, in the game's own terms.** A numbered path a person can follow with
a joystick, naming the menus and commands the game shows -- `VIEW`, `ITEMS`,
`QUICK` -- and no addresses at all. If the only route is editing the files out
from under the engine, **say so in those words**, because that is the sentence
that tells the next reader it is not a bug a player hits.

## Code comments

Comment the *why*, and only when it is not obvious. A field note that carries
evidence -- "10 for every player character; monsters carry their real AC here"
-- earns its lines. Restating the code does not.

`goldbox/layout.py` is the exception: its notes are the field documentation and
are generated into `docs/20-character-record.md`. They can be long. Run
`python3 tools/gendocs.py` after touching them.

Why these rules exist, and the incidents behind them:
`docs/160-why-these-rules.md`, "Documentation".
