# Read the ECL scripts — task for Donald

**Status: waiting on a human. Nothing blocks on it, and it is the highest-value
reading left in the project.**

Every one of the game's thirty area scripts is now disassembled with a decoder
that reaches **100% of every byte** — `work/ecl-scripts/`, thirty files, one per
`ECL` per disk. `work/analysis6/ecl6.py` regenerates them.

## Why a person has to read them

The decode is complete; the *understanding* is not. A machine can tell you that
`ECL08` writes 255 to `$4AA6+13`. Only a reader who knows the game can tell you
that this is the Council paying for the Stojanow river, and that the flag it
sets is the same one the wilderness map consults before it lets you sail.

Two findings from tonight came out of exactly that kind of reading rather than
from any automated pass: that the commission ledger's index *is* the quest, and
that clearing the pollution swaps an impassable-terrain table.

## What to look for

* **Anything that reads or writes a byte we have not named.** 374 distinct
  addresses are touched; far fewer are understood. `work/reports/ecl-opcodes.md`
  has the cross-reference.
* **The `$4A20`-`$4AFF` flags nobody has attributed.** The commission ledger and
  eight appointment flags are named; the rest of the region is not.
* **Anything that contradicts a doc.** Two corrections already came from a
  careful read, and there are likely more.
* **Encounters that are not what they look like** — `ECL00` shifts the monster
  *type* on party strength rather than the count, and nothing suggests it is the
  only script doing something like that.

## Where things are

| | |
|---|---|
| the scripts | `work/ecl-scripts/dis_POOLn__ECLnn.txt` |
| the decoder | `work/analysis6/ecl6.py` |
| the opcode table and cross-reference | `work/reports/ecl-opcodes.md` |
| the quest flags | `work/reports/quest-flags.md` |
| encounters | `work/reports/encounters.md` |

All under `work/`, which is gitignored — these are derived from the game's own
files and **must not be committed**. See "What must never enter this repository"
in `CLAUDE.md`.

## A caution when reading

The operand-count table in the game disagrees with two of its own handlers
(`SETUPMON`, `ENCMENU`). No script triggers it, but if a listing ever looks like
nonsense after a conditional, that is the first thing to suspect rather than a
decoder bug.
