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
  addresses are touched; far fewer are understood. The cross-reference that
  established this, `work/reports/ecl-opcodes.md`, is lost.
* ~~**The `$4A20`-`$4AFF` flags nobody has attributed.**~~ **Largely done, and
  by machine rather than by reading.** Every
  one of the 352 bytes has a disposition: 172 named by a direct ECL operand, 7 more
  as the interior of a proven table, and **135 shown not to be flag storage at
  all** — the region ends at `$4AF8`, not `$4AFF`, and `$4A00`-`$4A1F` is
  per-script scratch that `DUNGEON $202A` wipes on every area change. What is
  left for a human is the *meanings*: the DOS guide names 229 of these addresses
  in English (`docs/128` §"The script-flag map"), and merging its names onto our
  addresses is a cheap, high-value job for whoever next touches
  `goldbox/commissions.py` or the quest panel.
* **Anything that contradicts a doc.** Several corrections have already come
  from a careful read, and there are likely more.
* **Encounters that are not what they look like** — `ECL00` shifts the monster
  *type* on party strength rather than the count, and nothing suggests it is the
  only script doing something like that.

## Where things are

| | |
|---|---|
| the scripts | `work/ecl-scripts/dis_POOLn__ECLnn.txt` — not currently present |
| the decoder | `work/analysis6/ecl6.py` — not currently present |
| the opcode table and cross-reference | lost — was `work/reports/ecl-opcodes.md` |
| the quest flags | lost — was `work/reports/quest-flags.md`; the counts are restated above |
| encounters | lost — was `work/reports/encounters.md`; the finding survives in `docs/50-experiments.md`, "Does the game scale random encounters to the party?" |

All under `work/`, which is gitignored — these are derived from the game's own
files and **must not be committed**. See "What must never enter this repository"
in `CLAUDE.md`. `work/ecl-scripts/` and `work/analysis6/` are gone along with
`work/reports/`; the decode this document asks a human to read does not
currently exist on disk and would need regenerating before the task is doable.

## A caution when reading

**A false `IF` fails to skip eight opcodes**, so if a listing ever looks like
nonsense after a conditional, that is the first thing to suspect rather than a
decoder bug. No shipped script triggers it — nothing puts an `IF*` immediately
before any of the eight.

The eight are the union of two independent derivations. Ours came from `$1625`,
the VM's own operand-count table, which disagrees with its own handlers for
`SETUPMON`, `ENCMENU` and `ADDNPC`. The DOS guide's came from the other side and
lists `SETUPMON`, `VERTMENU`, `ONGOTO`, `ONGOSUB`, `HORIZMENU` and `ADDNPC` — its
four extras being the variable-length opcodes, whose length the skip routine
cannot know at all. The lists overlap on two entries and are otherwise
complementary. Logged in `docs/125-bug-notes.md`.

Two other things worth knowing before reading a listing:

* **`$1F` is unimplemented.** Our table called it `ADDRESSOF`, a name inherited
  from the `coab` opcode table. No Pool of Radiance script references it — our
  own sweep counts zero — so the name was a guess and is withdrawn (P57). The
  opcode table itself, `work/reports/ecl-opcodes.md`, is lost, but it left
  `$1F` unnamed before it went.
* **`ECL1E` is not an area script.** It is the attract-mode demo, in a slot DOS
  left free: DOS numbers maps and scripts in one space and has no script 30 at
  all, so the C64 port put one there. Thirty files, twenty-nine of them areas.
