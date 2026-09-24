---
paths:
  - "goldbox/**"
---

# Testing a conversion

## Refusing a save is not a fix

Refusing a valid save is a conversion bug, not a solution to one. Missing
mappings, unknown fields, unimplemented effects, and differences in
representation are work for Wish to resolve. Do not close their tickets, claim
conversion support, or call them fixed because Wish now detects the problem and
refuses the save.

A regression test for a conversion fix must demonstrate successful conversion
of the formerly failing save or condition and the preserved player behavior.
A test proving that Wish refuses the save can document an outstanding defect;
it cannot serve as the acceptance test for fixing that defect. Renaming an
error, hiding a route, or passing only the specimens we have does not
prove completion either.

No available specimen is not proof that a player cannot reach a condition.
Establish unreachability from the game's behavior or code; otherwise keep the
investigation open and name the experiment that would settle it. Closing work
and retaining ownership of unfinished defects follow
`.claude/rules/issues.md`.

## Test a disputed port difference before asking Donald

When a proposed conversion depends on one port allowing an action that another
port cannot perform, test that action in the running games before asking Donald
to decide how the player should handle the difference or approve interface
text for it. Include a control that shows the command works on an item or state
it does support, capture what the player sees, and read the game-written save
when the result persists there. Code analysis can identify the expected branch;
synthetic tests and saves Wish wrote do not establish what the game does.

The run must exercise the disputed action itself. Loading a converted save and
seeing two separate scrolls, for example, does not establish whether the
destination game's JOIN command can combine them. Also establish that the
source game can write the state that would require the proposed player choice.
If either run cannot be made, name the missing step, keep the claim provisional,
and continue work that does not depend on Donald's decision. Once the limit is
verified, the capacity rule below already settles the behavior: let the player
choose what fits. Ask Donald to approve the wording and appearance only then.

A verified destination capacity limit requires a way to complete the
conversion. Let the player resolve what fits. One name needing shortening must
not condemn the entire party.

Do not replace refusal with silent loss. During development, checks may prevent
writing output known to be wrong, and incomplete routes remain behind their
feature flags. Those protections do not discharge the obligation to finish the
conversion.

Keep protections against corrupt input, destructive overwrites, missing
required files, and failed writes. Diagnose the actual failure; never classify
a valid game state as corrupt merely because Wish does not understand it.

## Between two ports of one title

**A conversion is between two ports of the same title, and never between
titles.** A Curse character is never converted into a Pool character. **The
title is fixed and the port is what changes**: a DOS Curse save converts to a
C64 Curse save or to an Amiga Curse save, and to nothing else.

So the six directions -- every pair of DOS, C64 and Amiga, each way -- are six
pairs of *ports*, each carrying whichever titles both ends can read -- not a
grid of every title against every other.

**The player still gets from one title to the next, and the game does it.** A
player beats Secrets of the Silver Blades on the C64, loads the save into Wish
and converts it to an Amiga save, then loads that save into Amiga Pools of
Darkness, and the game itself converts it into an Amiga Pools of Darkness
save. That path is what this rule protects: it avoids a whole class of bugs
that come with converting saves from one game into another.

So the division of labour is settled: **Wish changes the port, the game changes
the title.** Every Gold Box title reads the previous one's finished party, that
transfer is the engine's own feature, and it knows what an item id and an area
number mean on both sides -- which Wish would have to reinvent per pair, per
port, for every combination. A tool that writes a party of one title into
another title's save is doing the game's job with none of the game's knowledge.

`editor/convert.py` builds it that way -- a direction's destination is
`c64_port.by_key(deltas.key)`, the same title on the other port -- and this
rule is here to stop somebody adding the other thing. It also settles a
question that would otherwise keep coming back: **a character who cannot exist
in the destination title is not a case the conversion has to handle**, because
that conversion is never offered. Pool of Radiance has no druids, and no Curse
druid is ever asked to become one.

**The standard is a perfect conversion, and the player is never told about a
drop, because a route that drops something is not offered.** Anything short of
perfect stays behind a feature flag until it is.

**Never write a sentence to the player in place of fixing the thing it
describes.** Finding a condition the conversion cannot handle and reporting it
is how a defect turns into furniture: the sentence ships, the bug does not get
fixed, and the next agent reads the sentence as the design. If a condition
cannot be fixed in the session that found it, **file it and send the line to
the debug log** -- the evidence stays, the excuse does not.

**And the same game on two platforms is the same game.** Both ports run the
same rules on the same content, so a magic-user memorises the same number of
spells on the C64 as in DOS, and a title's spellbook holds the same spells on
both. **A difference between the platforms in what a character may hold is our
table being wrong until the engine's own code says otherwise** -- read the
code, do not reason from a record, and do not encode the difference as a limit
to warn about.

So there are exactly two states a conversion may be in. **Perfect and
offered**: its drop list is empty, and there is nothing to say. **Imperfect
and behind a flag**: `.claude/rules/feature-flags.md` governs, and the flag
comes off when the list empties. There is no third state where a route ships
and apologises, and the Convert dialog carries no log of what did not survive.

**The drop list itself stays, as our accounting, and goes to the debug log.**
It is what a test reads to prove a conversion is perfect rather than assumed,
what the driven tools print, and what says on a player's own machine why a
character came out wrong -- `wish/debuglog.py`, off unless `WISH_DEBUG` is
set. `.claude/rules/gui-text.md` exempts that log from approval by name,
which is the whole reason it is the right destination: *"it is read by whoever
is debugging."* **A drop line is therefore never a string Donald words.**

**The tables account for every field.** Every field in the neutral vocabulary
must be accounted for by every writer: each has a `field_disposition()` naming
every field as direct, transformed or dropped, and a test goes red the day a
field exists in `goldbox/neutral.py` and a writer has never heard of it
(`tests/amiga/test_amiga.py`, and `goldbox/c64_codec.py`'s own docstring: *"this
catches a name the writer has never been taught, which is the failure that rots
silently"*). That is what proves a conversion perfect.

**What the tables cannot see is a field nothing has named** -- something in a
save that no reader was ever taught to read. It is in no vocabulary and no
disposition table, and it is the standing reason decoding work continues. It
shrinks only by reading the record.

So the one rule that protects the claim: **an entry leaves a drop list when the
field converts, never when it stops being counted.**

**Do not propose a full byte-coverage audit of every save file on every
platform.** An unnamed byte only costs anything when a writer has to produce a
container it did not receive, which is cross-platform writing alone -- editing
a save in place carries opaque regions through untouched, and reading simply
shows what can be named. The audit would enlarge the backlog before it improved
any conversion. Measuring the unnamed bytes of one region, when a ticket needs
it, is ordinary work; the audit as a programme of work is not.

Reporting a dropped field internally is the minimum; it is not permission to
drop it, and "the destination has no such field" is not an ending either.
Dropping anything when converting a save is a bug, and the feature flag cannot
be lifted until it is not. A converted character wearing a Ring of Fire
Resistance has to resist fire on the other side.

So the list below sorts why a field is not converted **yet** -- it is not a
licence, and a drop list is not a state a conversion is allowed to rest in.
Only a field the destination derives on load, or holds at a measured constant,
loses nothing; the rest is open work. "The destination has no such field" is
a description of the destination as we currently understand it rather than
permission to stop: if the destination has no home for a value, finding it one
is the work. **Every entry on every drop list has an issue.**

**The standard is every direction, not only the DOS-to-C64 import.** A player
who finds things missing from a converted character calls the feature buggy,
and converting only half of a character's stats is no solution. The program
keeps six more lists of the same kind -- `dos.WRITE_DROPPED`,
`WRITE_UNSOURCED`, `WRITE_DEFAULTS`, `c64_codec.READ_DROPPED`,
`amiga_pod.POD_WRITE_DROPPED` and `amiga_later.LATER_DROPPED`. **They are all
covered.** A list is not exempt because its direction is the less travelled
one, and the Amiga lists are not exempt because they are the longest.

**A destination with nowhere to put a value is not a place to stop.** It is
work for Wish to resolve: find where the destination engine keeps the
equivalent, or, for a verified capacity limit, let the player resolve what
fits. A field left unconverted is an open defect, never an accepted end state
-- whether we have not yet found its home, the home is inconvenient, or the
value is one we guess a player would not miss. The identity byte is the worked
example: Curse and Silver Blades on the C64 never write the pair and nothing
reads it, which looks like nowhere to put it, and it is **written anyway**
because the bytes are there and a later conversion back to DOS then
returns the player's own number instead of inventing one. The player is not
told about it.

Two things that are **not** drops and must not be counted as though they were:
a field the destination recomputes on load, and a constant of the format. Both
have their own lists (`dos_codec.DERIVED`, `dos_codec.CONSTANTS`,
`dos_codec.WRITE_DERIVED`, `dos_codec.WRITE_CONSTANTS`) and each row carries
the run that demonstrated it. When a long drop list is read against this rule,
sort it before costing it -- much of a long list is derived fields and
constants, which are not losses.

**A small table of numbers read out of the game is a measurement, not a data
file.** `AGENTS.md` forbids committing the game's data files -- maps, tables,
scripts, records -- as committed bytes. That ban is about redistributing the
game, and a handful of integers with a note saying where they were read from
is the thing the sentence after it asks for: *describe, cite, measure and
generate*. It is the same class of thing as the byte offsets, field addresses
and constants committed all through `docs/`. The fourteen head and twelve body
art ids the DOS-to-C64 portrait conversion needs are such a table.

**The line is drawn by what the thing is, not by its size.** Numbers and their
provenance are a measurement. A block of the game's own bytes is a copy
however short, and a sprite, a map, a script or a record stays banned at any
length -- including as a test fixture. If a table cannot be written as
numbers a reader could check against the game, it is the wrong side of the
line.

**Say "converted", not "carried".** The word is in this file, in
`field_disposition` prose and in drop lines a player reads.

**The one exception, and it covers every field alike: a destination that
genuinely holds fewer things than the source.** If a limit is truly part of
the platform's design, inform the player during the convert about the limit
and offer a choice of which to keep and which to discard. It is a limit of the
platform, not something we did not feel like fixing.

The two rules are not in tension, because they are different situations. A
**field** we do not convert is our failure, the player is never told, and the
answer is to convert it. A **thing that does not fit** is the destination
telling the truth about itself, and then the player is entitled both to know
and to choose which of their own things goes.

**The test is whether the limit is the platform's or ours.** Sixteen item
slots in a C64 record and ten trait slots are the machine's design, and no
amount of work on our side makes an eleventh trait slot exist. A field we
have not decoded, a value we have nowhere to put yet, an effect whose bytes
nobody has read -- those are ours, and they get fixed rather than announced.

**So it is one mechanism, not one per field.** Items, trait slots and anything
else with a hard count are all written the same way: say what will not fit, and let
the player pick which of them to keep. Do not design a chooser for items and
a different one for effects.

**And do not build it until a measurement says it is needed** -- a capacity
limit is verified when it has been measured, and not before. Known limits and
what is measured about reaching them:

| | the ceiling | can it be reached? |
|---|---|---|
| C64 items | 16 slots in the record | DOS and Amiga refuse a seventeenth head item (`docs/173-carrying-limits.md`); Silver Blades can join scrolls under one head, but a game-written bundle that exceeds the C64 slots has not been tested in the running games |
| C64 trait slots | 10, shared between racial effects and item grants | racial ids are 0-4 by race, CONFIRMED (human 0, elf 1, half-elf 1, halfling 2, dwarf 4, gnome 4), so it needs a dwarf or gnome with **seven or more effect-granting items readied at once** -- **UNMEASURED** |

Measure per title before designing anything: Curse's items are 67 bytes where
the other titles' are 63, so this family is not uniform.

**"Nobody has measured it" is not "it cannot be done", and saying so is how an
agent gives up in a sentence that sounds like a finding.** An UNKNOWN in a
conversion is a measurement somebody has to go and take, named in numbers --
how many colours each side stores, how many pixels, which file the art is in --
and never a reason to stop.

**Never tell a player something untrue about their own game to make a drop
line shorter.** "DOS has no combat art" is untrue: DOS has combat art. What it
does not have is the C64's **encoding** of it -- 18 `CHARPIC00` screen codes
plus 18 colours out of the C64's own character set -- and the converter needs a
route between the two. Compressing "no equivalent encoding" into "none" reads
as a claim about the game the player owns.

Two reasons lose nothing:

* the destination **derives it** on load, so writing it is pointless -- and that
  has been *demonstrated in the running game*, not argued from plausibility.
  That is conversion: the destination rebuilds the value, and it is reported
  as derived, not dropped;
* the destination format holds it at a **measured constant** -- a
  `WRITE_CONSTANTS` row, or the zero the engine itself writes because it
  rebuilds the field (`WRITE_UNSOURCED`, below). That value is written, not
  lost.

Two are open work, never legitimate reasons:

* the destination format **has no such field** -- established by reading its
  layout, not assumed -- and the work is to find where the destination engine
  keeps the equivalent, or, for a verified capacity limit, to let the player
  resolve what fits;
* we **do not understand the bytes well enough to write them** -- a blocker to
  be read, with a settling experiment. While it is open, a development-time
  check stops Wish writing output known or suspected to be wrong, and the
  investigation continues and has an owner. That check is not the fix, and
  never a reason to stop working the conversion or to accept the refusal.

Both are bugs that have not been filed yet. Treat them that way.

**A template is not one of these reasons, and "the template supplies it" is
not an answer.** Building a converted save on top of a save the engine wrote
means every byte nobody has decoded silently keeps a value belonging to a
different party in a different place -- wrong data that looks right, and
invisible because the file loads. Do not use a template; do not write the
output until the field is understood, and keep working to understand what is
needed.

So **an undecoded field blocks the output, not the work: it is not a gap the
template fills and not a reason to accept refusing the save.** When the
conversion needs a byte nobody has attributed, the work is to go and measure
it, and the ticket says so.

**Zero written because the engine rebuilds the field is not plugged-in data.**
Most of `WRITE_UNSOURCED` is live heap pointers and combat state where the
engine itself writes zero, measured both with items and without. The
distinction that matters is **measured versus inherited**: a value we
established is fine at any number, and a value we inherited from somebody
else's save is not.

**"Reported as dropped" is not a resting state.** Every entry in a drop list
carries the experiment that would remove it, and a drop list that has not
shrunk in months is a list of unfiled bugs.

**Test the empty and the extreme case, not only the typical one.** A drop list
measured survivable for a character carrying items says nothing about a
character carrying none, where a converted character can arrive with a corrupt
sheet.

**Round-trip byte for byte, and mask by the declared list rather than by the
diff.** Masking by whatever happened to differ makes the test agree with the
code by construction. `tests/convert/test_doswriter.py` masks by `WRITE_UNSOURCED` and
`WRITE_DEFAULTS`, which are the lists the writer declares, so a new difference
fails.

**A conversion is not proven until it runs.** Bytes matching is necessary and
not sufficient: load it in the game, walk the party, and look at the sheet.
Faults that pass every byte-level check and show on the sheet include an AC of
9 displayed as 51, a dropped combat tail, and a garbage weapon line.

Why these rules exist, and the incidents behind them:
`docs/160-why-these-rules.md`, "Testing a conversion".
