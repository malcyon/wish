# Where a DOS innate effect id comes from

`#395 (A Curse cleric carries the ranger's innate effect and a human carries
the elf's, in the specimen both ids were graded from)` asked two questions
about Curse of the Azure Bonds' effect ids 134 and 107, and both are answered
here. `tools/innateids.py` is the reader; `tests/test_innateids.py` pins it.

**The short answer.** 134 is Curse's ranger id and 107 is its elf id, and this
is now read out of the engine's own character creation rather than out of a
saved game. The specimen that raised the question is innocent: the poke
`tools/dualclassagain.py` makes touches two bytes of the saved game's
container on a staged copy and no character record at all, and the two
anomalous records exist with the same ids in the archives' own copy of the
same party, which that tool never met. What is *not* settled is how those two
records came to hold an id the engine would not have seeded for their stored
class and race; §4 has the two candidates and the experiment that separates
them.

## 1. The engine's own creation tables

DOS Gold Box character creation writes a character's innate effects by calling
one routine — `add_affect(id, duration, data, flag)`, `docs/162-spc-permanence.md`'s
name for it — once per effect, with all four arguments constant. Two switches
feed it: one on the record's **race** byte and one on its **class** byte. The
nine-byte `.SPC`/`.FX`/`.SFX` record the engine later writes is the id
followed by those three values, so reading the switch reads the file.

`tools/innateids.py seed` finds all three by shape rather than by address —
`add_affect` is the far call a race switch reaches with four constant pushes,
and a switch is a read of the race or class byte into `al` followed by
`cmp al` — so one run works on any of the three titles.

| | Pool of Radiance | Curse of the Azure Bonds | Secret of the Silver Blades |
|---|---|---|---|
| `add_affect` | `lcall 00B0:0052` | `lcall 00E3:0057` | `lcall 0145:004D` |
| race switch | `GAME.OVR:0x1A12A` | `0x1E244` and `0x20989` | `0x1DF47` |
| class switch | **none** | `0x20D9E` | `0x1E345` |
| constant call sites | 18 | 28 of 51 | 20 |

**By race**, every branch pushing `(id, 0, 0xFF, 0)` — duration zero and
`goldbox.dos.INNATE_PAYLOAD` in bytes 1 to 4:

| race | Pool of Radiance | Curse | Silver Blades |
|---|---|---|---|
| dwarf | 90, 97, 26, 47 | 97, 26, 47 | 47, 26, 97 |
| elf | 107 | 107 | 95 |
| gnome | 97, 18, 47, 48 | 97, 18, 47, 48 | 48, 7, 97 |
| half-elf | 124 | 124 | 18 |
| halfling | 90, 97 | 97 | 97 |
| human, half-orc | nothing | nothing | nothing |

**By class**, which is the half `#388 (A converted paladin or ranger loses his
innate effect on the way to DOS, because the writer filters through Pool of
Radiance's id list)` is about:

| class byte | Curse | Silver Blades |
|---|---|---|
| 3, paladin | 8 | 8 |
| 4, ranger | **134** | **105** |
| 10, cleric/ranger | 134 | 105 |
| every other class | nothing | nothing |

Pool of Radiance has no class switch at all, and never pushes 8, 105 or 134
anywhere: it instantiates neither a paladin nor a ranger, which is why
`goldbox.dos.INNATE_EFFECTS`' default set needs no class ids and why
`#388 (A converted paladin or ranger loses his innate effect on the way to
DOS, because the writer filters through Pool of Radiance's id list)` was a
later-titles defect.

**Curse's two class ids are pushed at exactly two constant sites each in the
whole overlay**, both inside that switch — 134 at `GAME.OVR:0x20E2D` and
`0x20EBA`, 8 at `0x20E06`; 107 at `0x1E352` and `0x20A93`, both inside a
race-2 branch. CONFIRMED. The limit, and it is real: 23 of Curse's 51
`add_affect` sites take a computed id — a spell, an item, a monster's attack —
so the enumeration is exhaustive over the *constant* sites only.

This corroborates `docs/121-silver-blades.md` from a second, independent
route. That document derives Curse's ranger 134 and Silver Blades' ranger 105
from the two engines' **C64** seed tables, `GEN $2515` and `GEN $0FF0` —
reproducible with `tools/coldread.py traits curse-of-the-azure-bonds`, which
prints `class ranger -> 134`.

**The two ports side by side, every seeded id, both titles.** The C64 column
is each engine's own `GEN` and the DOS column the switches above.

| | C64 Curse `GEN $2515`/`$24EA` | DOS Curse `0x1E244`/`0x20D9E` | C64 Silver Blades `GEN $0FF0`/`$0C4B` | DOS Silver Blades `0x1DF47`/`0x1E345` |
|---|---|---|---|---|
| paladin | **45** | **8** | **45** | **8** |
| ranger | 134 | 134 | 105 | 105 |
| dwarf | 26, 47, 97 | 97, 26, 47 | 26, 47 | 47, 26, **97** |
| elf | 107 | 107 | 95 | 95 |
| gnome | 18, 48, 97 | 97, 18, 47, 48 | 48, 7 | 48, 7, **97** |
| half-elf | 124 | 124 | 18 | 18 |
| halfling | **nothing** | **97** | **92** | **97** |
| human | nothing | nothing | nothing | nothing |

An earlier version of this paragraph said the two ports *agree on every racial
id* and disagree only on the paladin. **That is wrong on four racial rows**,
and it was written from the ids the two ports have in common rather than from
a row-by-row reading.
`#484 (Does C64 Silver Blades seed a paladin's Protection from Evil as trait
45, the way Curse does, so that direction loses it converting to DOS too?)`
disassembled both `GEN` overlays instruction by instruction. What actually
disagrees:

* **the Silver Blades halfling**, C64 92 against DOS 97 — a different id, not
  a missing one;
* **the Silver Blades dwarf and gnome**, each given 97 by DOS and not by the
  C64;
* **the Curse halfling**, given 97 by DOS and nothing at all by the C64;
* **the Curse gnome**, given 47 by DOS and not by the C64.

The counts explain most of it: the C64 seeds two trait slots per race in
Silver Blades and three in Curse, where the DOS switch calls `add_affect` as
often as it likes — four times for Pool of Radiance's dwarf. An id past the
count has nowhere to go. The halfling's 92 is not that, and is the one row
where the two ports use different numbers for the same thing.

So an id is per port as well as per title, and 45 and 8 are not two names for
one thing. The paladin is the disagreement both titles share.

## 2. The Curse corpus, character by character

`tools/innateids.py census --title curse --by-id` over the specimen tree, the
archives and `work/`: 69 distinct 422-byte records, 42 with an effect file.
Every carrier of each class or race id:

| id | carriers | exceptions |
|---|---|---|
| 8 | 13 records, all human, 11 paladins | MATHEW and DEMELTINA, each **after** Curse's own `HUMAN CHANGE CLASSES` dual-classed them out of paladin, both with `former_class_levels[paladin] = 5` |
| 26, 47, 97 | 8 records each, all dwarves | none |
| 107 | 15 records, 13 elves | BRYTWYN, a human magic-user, in two copies of one party |
| 134 | 6 records, 4 rangers | FLORENTZ, a human cleric, in two copies of the same party |

The two dual-classed paladins are not exceptions to anything: the engine keeps
an effect a character already has when his class changes, which the same
census shows from both ends — the record says so, and `WISH-SPEC-curse-234-engine-resave`
is the engine writing one of them back.

**Every Curse record on this machine carrying 134 belongs to one six-character
party** — the archives' `games/CURSE/Default files/Saves` slot B, and the
engine's re-save of it that is `WISH-SPEC-curse-234-party-dualclassed`. That
party has two rangers who carry 134 and one cleric who also does.

**A trap the census hit first, recorded so nobody re-treads it.** Gateway to
the Savage Frontier's `.GUY` exports are 422 bytes, which is Curse's record
size, so `dos_layout.shape_for` reads them through Curse's table. The first
sweep counted TARLREN, a Gateway human ranger carrying 134, as a Curse
carrier. He is not; a fifth title reading the same numbers is a separate
finding and not evidence about this one. `tools/innateids.py` now skips 24
Gateway and 28 Treasures of the Savage Frontier records by directory and says
how many it skipped.

## 3. The specimen is innocent

`#395 (A Curse cleric carries the ranger's innate effect and a human carries
the elf's, in the specimen both ids were graded from)` asked whether
`tools/dualclassagain.py`'s poke could have disturbed trait seeding for
characters it was not aimed at. It could not, four ways:

1. **The code.** `install()` copies each `CHRDAT<slot><n>.*` byte for byte
   into the emulator instance's own save directory and changes exactly one
   16-bit word, `SAVGAM<slot>.DAT+0xD51`, the training hall's maximum level.
   No character record and no effect file is written at all.
2. **The direction.** The specimen's files were collected from
   `work/curse/234-curse-dualclassed`, which is the run's **input**. Nothing
   is written back there.
3. **A shared byte-for-byte record.** The specimen's `CHRDATD1.SAV` hashes
   `352f508395065c91443e4e314a29f20564dfdf1af681c2078607fe6c822ec801`, which
   is `WISH-SPEC-curse-234-dualclassed`'s own `CHRDATD1.SAV` — a specimen made
   on `#234 (A dual-classed Curse or Silver Blades character converted to DOS
   loses the class he trained out of)` by a different tool.
4. **The same anomalies upstream.** FLORENTZ and BRYTWYN carry 134 and 107 in
   the archives' `games/CURSE/Default files/Saves/CHRDATB4` and `CHRDATB6`,
   which no tool of ours has touched.

That fourth comparison is also a measurement of what the DOS Curse engine does
with an effect file it did not seed. Loading the archives' slot B party and
saving it back changed, per character:

| record | bytes changed |
|---|---|
| `CHRDAT?1` (DEMELTINA, dual-classed in the game during the run) | 34 |
| `CHRDAT?2` to `?5` | 2 each: `effect_chain+2` and `heap_104+2` |
| `CHRDAT?6` | 1: `effect_chain+2` |

Both are heap addresses. The `.FX` files came back identical except for the
four-byte far pointer the engine rebuilds, which `goldbox.dos.EFFECT_NEXT_NULL`
already records. **So the engine neither re-seeds nor strips an innate effect
on a load and save**: FLORENTZ went in a cleric carrying 134 and came out a
cleric carrying 134. CONFIRMED, six records. The C64 does the opposite —
`GEN $2515` removes 45 and 134 from the trait slots at every recompute and
re-adds them by level (`docs/172-curse-trainer.md`) — so this is a difference
between the ports rather than a shared rule.

## 4. What produced those two records, which is not settled

Everything else in both records agrees with the class the record stores.
Computed through `goldbox.levels` for Curse:

| | stored saves | a cleric 5 | a ranger 5 | a magic-user 5 | `thac0_base` |
|---|---|---|---|---|---|
| FLORENTZ | 9, 12, 13, 15, 14 | **9, 12, 13, 15, 14** | 11, 12, 13, 13, 14 | 14, 13, 11, 15, 12 | 42 |
| ARGORA (ranger) | 11, 12, 13, 13, 14 | | **11, 12, 13, 13, 14** | | 44 |
| BRYTWYN | 14, 13, 11, 15, 12 | | | **14, 13, 11, 15, 12** | 40 |

And `former_class_levels` is all zero in both, so Curse's own
`HUMAN CHANGE CLASSES` did not make them — that route writes the former array,
which is exactly what DEMELTINA and MATHEW show.

Two things the party does say. Every single-class member holds exactly 25,000
experience and the multi-class ones 12,500 and 8,333, which is not a coincidence:
**Curse's character creation writes 25,000 experience**, at `GAME.OVR:0x20D65`,
and its multi-class branches write 12,500 and 8,333 — 25,000 divided by the
number of classes. Both shipped parties in that directory hold those numbers,
so both are freshly created Curse characters who have earned nothing. Yet
FLORENTZ's effect file also holds three records with running durations (45 at
duration 47, 17 at duration 2, and 75) and BRYTWYN's holds 17 at duration 2 —
which a character who has never adventured cannot have. **The effect files and
the records do not belong to the same moment.**

Two candidates, and neither can be told from the other by reading these bytes:

* **A stale effect file.** If the engine writes `CHRDAT<slot><n>.FX` only for
  a character who has effects and never deletes one, a slot whose occupant is
  replaced inherits the previous character's file, and the next load makes it
  the new character's own. That would be a defect in the game.
  **The experiment**: under DOSBox, load a Curse save whose character 4 has
  effects, remove that character, add a freshly created cleric in the same
  slot, save to the same letter, and read `CHRDAT?4.FX`. Old ids still there
  confirms it; an empty or absent file refutes it.
* **An edit.** A character editor that changed the class and recomputed the
  derived fields but not the effect file produces the same bytes. That
  directory is a download and has no chain of custody
  (`.claude/rules/testing.md`), so this cannot be excluded.

SPECULATIVE either way. Nothing a player sees turns on it, and no conversion
does either: `goldbox.dos`'s per-title sets only ever *add* ids, so a record
carrying 134 is classified innate and converted whoever holds it.

## 5. What this changes

Nothing in the code. The fix on `#388 (A converted paladin or ranger loses his
innate effect on the way to DOS, because the writer filters through Pool of
Radiance's id list)` is right, and its two class ids are right —
they are now read from the engine as well as from records. What it changes is
the **evidence** behind one grade: 134 was graded CONFIRMED over ARGORA and
RWELLYN, and those two are one party, alongside a third character in the same
party who carries 134 without being a ranger. The engine's own switch is the
stronger source and does not depend on that party at all.
