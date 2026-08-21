# The save game

## A save is a verbatim memory image

The game dumps a range of RAM to disk with no header, no packing and no
checksum. Thirteen edited fields were accepted without complaint, so nothing
validates it.

Three consequences, all load-bearing:

1. **Live addresses and file offsets differ only by the base.** Anything you
   learn about the file applies to the running machine, and vice versa.
2. **You can find the base in RAM in one step** by searching for a run of bytes
   taken from the file. See `live-memory.md`.
3. **You must be able to produce every byte** if you ever want to *generate* a
   save rather than edit one. Naming a region is not the same as being able to
   fill it.

## The shape, and how to port it to a new title

Pool of Radiance's geometry, which Curse reproduces at `+$200` up to the slots:

```
header / party globals        $400 bytes
combat icon table             8 entries of 36 bytes, ending exactly at the slots
character slots               $100 each
item area                     one $100 block per slot, 16 items of 16 bytes
roster                        8 blocks of 32 bytes
```

**The arithmetic is what proves the slot count**, not the icon table. The loader
computes both `slots_base + n*$100` and `items_base + n*$100`, and in Pool of
Radiance the arithmetic only closes at **twelve** slots: `$4D00 + 12*$100 =
$5900`, exactly where the item area starts, and `$5900 + 12*$100 = $6500`,
exactly where the file ends. At eight there is an unexplained `$400` gap. Slots
0-7 are the party; 8-11 are filled during combat by whatever is fighting.

The icon table has eight entries, which is what first suggested eight slots.
That match is real but it counts the *party*, not the slot array.

**Nothing outside combat should read the combat slots.** A monster loaded there
carries most of the residue bytes that mark a record as not-a-player, so it
reads as a half-marked NPC.

Curse does not simply shift this: it has no twelve-slot array (a 16-byte-per
character name table sits where slot 8 would be), and its roster lives one page
past the item area in the same file rather than in a second file.

## The split between files is not "characters here, world there"

That reading is wrong and was assumed here for a while. In Pool of Radiance:

* the **first file** holds the character slots *and* a header carrying the
  party's place in the world — position, facing, the clock, the area id;
* the **second file** holds the roster of derived combat values and **nothing
  about the world at all**. Walking six saves' worth leaves it byte-identical.

Only the second file's *first page* is even save data. Everything past it is
resident code and a graphics buffer that happened to be in memory when the range
was dumped. **Check that before theorising about a large trailing region:** a
jump table (`4C xx xx` repeating) is the giveaway.

## The header

The header is where the world lives, and it is where things hide.

| What | Note |
|---|---|
| party x, y, facing | facing 0 north, 1 east, 2 south, 3 west. **x, y lags a move** |
| game clock | six bytes, **not three**: units of a minute, tens, the hour, then day and month. Read the game's own print routine before deciding |
| previous square | the square occupied before the last move |
| the loader's "what is currently loaded" cache | one entry per data-file type — **this is where the area id is** |
| four parallel effect arrays | id, owner, duration, magnitude, 64 entries each. Owner: 0-7 a party member, 8+ a monster, `$FF` the whole party |
| per-script scratch, zeroed on area change | nothing here survives leaving an area |
| persistent flags | survives an area change; largely unread |

**The clock cost three wrong readings** — a 24-bit turn counter, three decimal
digits, and minutes — each of which fitted the specimens available at the time.
The game's own print routine settled it. When a multi-byte field has several
plausible readings, find the code that prints it.

## Finding the area id

**The area id is inside the loader's file cache**, not in a filename and not in
a field of its own. One entry per data-file type; the map entry names the map
file. Bit 7 is a dirty/reload marker set on load — **mask it off**.

Four attempts failed before this, and each failure is instructive:

1. **Chasing the filename.** Find what patches the two digits into the map file's
   name stem, and trace the argument back. The stem table's address was computed
   wrong twice, and when it was finally right, **nothing writes there** — the
   stems are templates copied into a scratch buffer, not patched in place.
2. **A buffer that looked like where the filename is assembled** turned out to be
   the number-to-decimal buffer for printing on screen.
3. **A byte scan reported that no such field exists.** It had no negative
   example: every save held was in the same area. *The game must record the area,
   or loading a save could not put the party back where it was.*

**So: make a boundary pair before searching.** Save, take one step through a
doorway into another area, save again. Two disks differing by one deliberate act,
and the diff is the answer. Do a third area if the first pair is ambiguous — a
value that moves between two areas could be a counter; one that takes three
distinct values matching three areas is an id.

**And prefer scanning for what reads and writes the header over reasoning
forward from the filename.** The technique that found it was looking for the
code that copies the cache in and out at save and load time.

## Caches have update rules

The derived combat values in the roster block are **cached, not recomputed on
load**. The game refreshes them only when *equipment* changes. Edit a
character's dexterity and their armour class does not follow, which for a while
looked like the edit had failed.

An editor that writes only the character file cannot touch armour class, THAC0,
current hit points or the damage bonus at all — none of them is in the record.
That is why the author of a 1989 hobbyist editor reported he could never find AC
or THAC0: he was editing an export, which has no roster block. (An export
*does* carry them, at `0x10E`/`0x10F` — beyond the 256 bytes a save slot holds.)

**The roster blocks are writable.** An edited armour class and hit-point total
appeared on the character sheet and were written back unchanged when the game
saved, so the game reads that cache and does not recompute over it.

## Being able to read a field is not evidence you can change it

Every field located by diffing is read-only knowledge until one edit has been
made and *looked at on the character sheet in game*. Keep that distinction in
the documentation. The acceptance bar is: change one value, load the game,
confirm the sheet shows it, save, and confirm the bytes survive the round trip.
