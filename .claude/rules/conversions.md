---
paths:
  - "goldbox/**"
---

# Testing a conversion

**A conversion is between two ports of the same title, and never between
titles.** Donald, 2026-09-05: *"the user should not be able to convert a Curse
character into a Pool character. The conversion is meant to be for the same
title."* **The title is fixed and the port is what changes**: a DOS Curse save
converts to a C64 Curse save or to an Amiga Curse save, and to nothing else.
Donald, 2026-09-05: *"A DOS Curse save would be able to be converted into a
C64 Curse save or an Amiga Curse save."*

So the six directions of
`#51 (Every permutation of DOS, C64 and Amiga, in both directions)` are six
pairs of *ports*, each carrying whichever titles both ends can read -- not a
grid of every title against every other.

`editor/convert.py` already builds it that way -- a direction's destination is
`games.by_key(shape.key)`, the same title on the other port -- so this rule is
here to stop somebody adding the other thing rather than to describe a defect.
It also settles a question that
would otherwise keep coming back: **a character who cannot exist in the
destination title is not a case the conversion has to handle**, because that
conversion is never offered. Pool of Radiance has no druids, and no Curse
druid is ever asked to become one.

**The standard is a perfect conversion.** Reporting a dropped field is the
minimum; it is not permission to drop it, and "the destination has no such
field" is not an ending either. Donald, 2026-09-04: *"We should not be
dropping anything when converting a save. Anything less is a bug, and the
feature flag cannot be lifted until that is true."* Told separately that a
ring's effect could not reach the C64 and that the drop was therefore
legitimate: *"everything must work."* A converted character wearing a Ring of
Fire Resistance has to resist fire on the other side.

So the three reasons below explain why a field is not converted **yet** --
they are not a licence, and a drop list is not a state a conversion is allowed
to rest in. The first of them, "the destination has no such field," is a
description of the destination as we currently understand it rather than
permission to stop: if the destination has no home for something a player
would notice, finding it one is the work. **Every entry on every drop list has
an issue**, and `WISH_EXPERIMENTAL_DOS_IMPORT` does not come off while any of
them is open.

**Say "converted", not "carried".** Donald, 2026-09-04: *"When you say
'carried', you must mean 'converted'. I don't think carried means what you
think."* The word is in this file, in `field_disposition` prose and in drop
lines a player reads.

**What a player would notice decides what a player is told.** Two things are
silent for two different reasons, and only one of them is a measurement.

* A field the destination **derives** on load needs no line, and that
  derivation has to be *demonstrated in the running game* first.
* A field a player **would not care about** needs no line either. Donald,
  2026-09-04, of the quickfight setting: *"The player will not care if
  Quickfight isn't converted. Don't bother alerting on that."*

The second is his judgement rather than anybody's finding, so **it is not a
licence to silence anything else** -- propose and leave it in place. The same
instinct applied to a character's status would have hidden a dead character
arriving alive, which is what `#235` turned out to be.

**Silent is about the pane, not about the work.** Asked whether quickfight
should therefore come off `#131`'s list, Donald, 2026-09-04: *"I agree, we
should try to convert it. We just shouldn't tell the player about
quickfight."* So a field nobody would miss still gets converted; it just does
not get a line.

**And a silent drop is still a drop.** It stays in `field_disposition` and in
the accounting; `#131` is blocked on it either way. Only the line in the pane
goes.

**No player ever sees a dropped-field message.** Donald, 2026-09-05: *"I don't
want the player to EVER see a message saying any field was dropped. The
conversion needs to be perfect."* So the drop list is **our accounting**, and
the pane that shows it to a player is a temporary state rather than a feature
-- what it is for is telling us the flag cannot come off yet. Rewording an
entry is worth less than removing it, and an agent polishing a drop line is
usually an agent working on the wrong half of the problem.

**The one exception, and it covers every field alike: a destination that
genuinely holds fewer things than the source.** Donald, 2026-09-05: *"If a
limit is truly part of the platform's design, inform the user during the
convert about the limit. Offer them a choice on which to keep and which to
discard. It would be a limit of the platform, not something we just didn't
feel like fixing."*

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
else with a hard count all take the same shape: say what will not fit, and let
the player pick which of them to keep. Do not design a chooser for items and
a different one for effects.

**And do not build it until a measurement says it is needed.** Donald, same
day: *"we shouldn't build that unless we are sure it is necessary."* Known
limits and what is measured about reaching them:

| | the ceiling | can it be reached? |
|---|---|---|
| C64 items | 16 slots in the record | DOS keeps a one-byte `item_count` and its items in a sibling `.ITM`, so the format allows far more -- **what the DOS game itself allows is UNMEASURED** |
| C64 trait slots | 10, shared between racial effects and item grants | racial ids are 0-4 by race, CONFIRMED (`#84`: human 0, elf 1, half-elf 1, halfling 2, dwarf 4, gnome 4), so it needs a dwarf or gnome with **seven or more effect-granting items readied at once** -- **UNMEASURED** |

Measure per title before designing anything: `#113 (Play DOS Curse far enough
to save a party with items)` proved this family is not uniform, its items
being 67 bytes where the others are 63.

**"Nobody has measured it" is not "it cannot be done", and saying so is how an
agent gives up in a sentence that sounds like a finding.** Donald, 2026-09-05,
on the combat icon: *"We absolutely can figure out how to convert combat
icons. They are not that complex. What is the problem, exactly? Are there
differing amounts of colors? Are there differing amounts of pixels? We can
figure it out. Don't give up so easily."* So an UNKNOWN in a conversion is a
measurement somebody has to go and take, named in numbers -- how many colours
each side stores, how many pixels, which file the art is in -- and never a
reason to stop.

**Never tell a player something untrue about their own game to make a drop
line shorter.** Proposed for the combat-icon line on 2026-09-05 and rejected:
*"DOS has no combat art"*. DOS has combat art. What it does not have is the
C64's **encoding** of it -- 18 `CHARPIC00` screen codes plus 18 colours out of
the C64's own character set -- and the converter has no route between the two
yet, which is `#130 (A converted DOS party arrives with six identical combat
figures, not its own)`. Donald, 2026-09-05: *"DOS absolutely does have combat
art. What does that mean?"* Compressing "no equivalent encoding" into "none"
reads as a claim about the game the player owns.

Three reasons are legitimate:

* the destination format **has no such field** -- and that has been established
  by reading its layout, not assumed;
* the destination **derives it** on load, so writing it is pointless -- and that
  has been *demonstrated in the running game*, not argued from plausibility;
* we **do not understand the bytes well enough to write them**, in which case
  the entry is a defect with a settling experiment, not a permanent exemption.

The third kind is a bug that has not been filed yet. Treat it that way.

**A template is not one of the three reasons, and "the template supplies it" is
not an answer.** Building a converted save on top of a save the engine wrote
means every byte nobody has decoded silently keeps a value belonging to a
different party in a different place -- wrong data that looks right, and
invisible because the file loads. Donald, 2026-08-26: *"We should not be using
a template at all. We should block on not understanding everything and go back
and understand what we need to. No more plugging in fake data to make it
work."*

So **an undecoded field is a blocker, not a gap the template fills.** When the
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
measured survivable for a character carrying items said nothing about a
character carrying none, which is where
`#62 (A converted character who owns nothing gets a corrupt sheet, and DOS then
invents a garbage item)` was found -- after the conversion had been declared
proven.

**Round-trip byte for byte, and mask by the declared list rather than by the
diff.** Masking by whatever happened to differ makes the test agree with the
code by construction. `tests/test_doswriter.py` masks by `WRITE_UNSOURCED` and
`WRITE_DEFAULTS`, which are the lists the writer declares, so a new difference
fails.

**A conversion is not proven until it runs.** Bytes matching is necessary and
not sufficient: load it in the game, walk the party, and look at the sheet.
Three faults this project shipped -- an AC of 9 displayed as 51, a dropped
combat tail, and a garbage weapon line -- passed every byte-level check that
existed.

Why these rules exist, and the incidents behind them:
`docs/160-why-these-rules.md`, "Testing a conversion".
