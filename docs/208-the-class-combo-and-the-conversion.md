# The Class combo and the conversion agree, and why

`#393 (A dual-classed Curse character may show one class in the editor and
convert as another, and no specimen exists to tell)` asked whether two parts of
Wish can give different answers for a Curse of the Azure Bonds character who
trained out of one class into another. **They cannot, on the C64, and the
reason is the engine rather than the two call sites being the same.**

The two call sites, both reaching `goldbox.classcode.repair`:

| where | what it passes | what it answers |
|---|---|---|
| `editor/window.py`'s `_char_class_shown`, behind the Class combo | `class_bits` alone | the code the mask names |
| `goldbox.c64_codec.read`, which a conversion goes through | `class_bits`, `levels` and `former_levels` | for a dual-classed character, the code the **level array** names |

Those differ only when a record's stored `class_bits` differs from the mask its
level array implies. **No C64 record can hold that state**, so the two answers
are the same answer.

## The measurement

PHILIPPE, on `WISH-SPEC-curse-dualclass-trained`, is the only character
anywhere in this project's corpus who has passed the level she left her old
class at. She is a human magic-user 6 who took `HUMAN CHANGE CLASSES` to
fighter and was then trained to fighter 8 at Curse's own hall, one press at a
time, with nothing written between presses but her experience
(`docs/192-curse-dual-class.md`). Her three engine-written states:

| state | `char_class` 0x073 | `dual_class_level` 0x0BA | `level_magic_user` 0x0C9 | `level_fighter` 0x0CC | `class_bits` 0x0EB | combo | conversion |
|---|---|---|---|---|---|---|---|
| magic-user 6, before the change | 0 | 0 | 6 | 0 | `$01` | 5 | 5 |
| one action after `HUMAN CHANGE CLASSES` | 6 | 6 | 0 | 1 | `$08` | 2 | 2 |
| after seven trainings, fighter 8 | 6 | 6 | **6** | 8 | **`$09`** | 13 | 13 |

The stored code is 6 in the last two, which the table calls a thief; neither
part of Wish shows it, because Curse's trainer stores the wrong CPU register
and leaves it stale (`#310`, `docs/187-the-class-code-byte.md`).

**Corpus, `tools/classcombocheck.py`, 0 disagreements everywhere:**

| corpus | records | dual-classed | combo against conversion |
|---|---|---|---|
| C64, specimen tree (three titles) | 132 | 3 | 0 disagree |
| DOS, specimen tree, converted to C64 first (three titles) | 228 | 9 | 0 disagree |
| C64, `work/` (three titles) | 1,482 | 14 | 0 disagree |
| C64 Pool of Radiance, the player's own save disks | 150 | 0 | 0 disagree |

Only one of those dual-classed records is past the regain threshold, and it is
PHILIPPE at fighter 8; every other one is a character read one action after the
change, whose mask carries the new class alone.

## Why the mask and the level array cannot disagree

Every instruction on the six Curse sides that could store into `class_bits`
(`$7CEB`) or into the eight-byte level array (`$7CC9`) was swept for --
`STA`, `STX`, `STY`, `INC`, `DEC`, the shift-in-place forms, absolute and
indexed. **558 files, five sites, and every one keeps the two in step:**

| site | what it does |
|---|---|
| `GEN $0B40` | character creation: stores the class's mask, then **derives** the eight level slots from it bit by bit |
| `GEN $153B` | the trainer's `INC $7CC9,X`, on a class the eligibility check at `$1553` has already allowed -- one the character holds |
| `GEN $18A4` | walks the array setting every **non-zero** slot to 1, so the set of classes it names does not move |
| `GEN $20A3` | the regain: `LDA $7CBA / BEQ` then `CMP $7CA0 / BCS`, and under those two tests both `STA $7CC9,X` and `ORA $7CEB / STA $7CEB` -- no branch between them |
| `SPELLE20 $0C5A` | **derives** the mask from the array, rolling a bit in for each non-zero slot |

`PIC78 $0BC4` decodes as an `INC $7CEB` and is inside a picture file;
`tools/d6502.py`'s own caveat covers it -- a byte pattern is not a routine.

So the two writes at `GEN $20A3` are what makes the fighter-8 row above look
the way it does: the old class's level and the old class's bit come back at the
same press, which `docs/192-curse-dual-class.md` measured from the other end
(flat at `$08` and 0 for fighter 2 through 6, both moving at fighter 7).

## Three claims this corrects

* `goldbox/c64_codec.py`'s note beside the regain rule says *"no C64 save this
  project holds has ever passed that point"* and grades the rule PROBABLE.
  `WISH-SPEC-curse-dualclass-trained` passed it on 2026-09-05, the same day the
  note was written, and the rule is **CONFIRMED**: `current_level > level` is
  what the record on disk shows, fighter 8 against a magic-user 6.
* `goldbox/layout.py`'s `dual_class_slot` note, and the generated
  `docs/20-character-record.md` row with it, still says *"Still open: what
  `$20A3` does once the new class passes the old level"*. It is not open.
* `goldbox.classcode.code_for`'s docstring says a dual-classed character's
  *"level array holds exactly the class he is now, because the old class's slot
  is zeroed at the change and stays zero"*. That is true on DOS, where the slot
  stays zero for good and the engine derives the answer at read time
  (`GAME.OVR 0x3C031`), and **false on the C64**, where `$20A3` puts the level
  back. It does not change the answer -- with the slot restored, the level
  array implies the same mask the record stores -- but the reason given for the
  rule is not the reason it holds.

## What would refute this

A C64 Curse record whose `class_bits` differs from the mask its level array
implies. `tools/classcombocheck.py` prints both numbers for every record it
reads and counts the disagreements, so pointing it at a new disk is the check.
The state nobody has produced, and the one that would make the Class combo and
a conversion part company, is a dual-classed character with the old class's bit
in the mask and the old class's level slot still zero -- which no site in the
table above can write.
