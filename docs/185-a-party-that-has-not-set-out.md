# A Curse party that has not set out, and the area word that says so

A Curse of the Azure Bonds saved game whose area word is 0 is not a party in a
place called 0. It is a party that has been formed and has not yet pressed
`BEGIN ADVENTURING`, and 0 is what the engine's initialiser left there.

This is what `#301 (A DOS Curse save standing in area 0 is refused by the
import, because no row of the area table names area 0)` turned out to be.
`docs/179-loading-a-curse-save.md` is the neighbouring document: how to get a
Curse save disk into the running game at all.

## What a player does to make one

The DOS party-formation menu offers `SAVE CURRENT GAME` to any party with a
character in it, between `REMOVE CHARACTER FROM PARTY` and
`BEGIN ADVENTURING`. So does the C64's -- `GEN $161`, next to
`GEN $151 LOAD SAVED GAME` and `GEN $186 BEGIN ADVENTURING`.

Create a character, add it to the party, save. That is the first five minutes
of the game, and the save it writes names area 0.

The two saved games the DOS archives ship, `SAVGAMA.DAT` and `SAVGAMB.DAT`,
are exactly that: SSI's own ready-made parties, saved from the party menu and
never taken anywhere.

## There is no area 0 in Curse -- CONFIRMED, both ports

| where | ids present | absent |
|---|---|---|
| the six C64 sides, directories read whole | `ECL01 02 03 04 10 11 12 15 1E 20 21 22 23 25 30 31 32 33 35 40 42 43 45 50 51`, and `ECL64`/`ECL65` on every side | `ECL00`, `GEO00` |
| DOS `ECL1.DAX`-`ECL6.DAX` block indexes | 1-4, 16-18, 21, 32-35, 37, 48-51, 53, 64, 66, 67, 69, 80-82 | block 0 |
| DOS `GEO2.DAX`-`GEO6.DAX` block indexes | 1, 3, 4, 16, 17, 21, 32, 33, 37, 50, 51, 53, 64, 66, 67, 69 | block 0, and `GEO1.DAX` does not exist |

Twenty-five scripts and sixteen maps, which is what `goldbox/areas.py`'s
`AREAS_CURSE` holds. **Pool of Radiance's area 0 is New Phlan and Curse's is
nothing**, which is why enumerating a title's areas by counting from zero is
wrong for every Gold Box game after the first.

## The differential: one keypress

Driven under DOSBox on 2026-09-05, one boot, nothing loaded. Create a male
dwarf fighter `ZEROTH`, add to party, `SAVE CURRENT GAME` to slot J. Then
`BEGIN ADVENTURING`, and with the party standing still, `ENCAMP > SAVE` to
slot C.

| | area `$49F2` | map `$49C5` | square | clock | `$49FD` | `$49FE` | `$4FE1` | script buffer |
|---|---|---|---|---|---|---|---|---|
| J, at the party menu | **0** | **0** | 7,13 facing 0 (N) | 00:00 | 00 | 00 | 00 | 12 non-zero of 7700 |
| C, one keypress later | **1** | **1** | 7,13 facing 1 (E) | 00:00 | 0B | 09 | FF | 7222 non-zero of 7700 |

The status line at that moment reads `7,13 E 00:00` over `YOU AWAKEN IN A
SMALL ROOM. LOOKING AROUND, YOU NOTICE THAT ALL YOUR GEAR IS GONE`, which is
area 1's own arrival square and facing.

**The script buffer is the third witness.** A save made at the party menu
carries no area script at all -- 12 non-zero bytes in the 7700-byte buffer,
against 7222 for the same party one keypress later, and the two shipped
containers hold the same 12. `#192 (Convert a Curse of the Azure Bonds DOS
save into a C64 one, which the importer refuses today)` used that buffer to
say *which* area a save was made in; here it says *no area*.

`$4FE1` is one of `dos_savegame.SAVGAM_CONSTANTS`, "255 in every specimen".
It reads 0 in a never-adventured save, so that population is saves made from
inside the world and the constant should not be asserted for one that is not.

### The party menu does not reset the area

The control, same session. `LOAD SAVED GAME` slot H -- an engine-written save
in area 1 at 5,13 facing W, clock 20:32 -- then `SAVE CURRENT GAME` to slot I
without adventuring. Slot I holds area 1, map 1, 5,13 facing W, 20:32. So the
0 in slot J is the initialiser's value rather than something the menu writes,
and `GAME.OVR:0xF95E`, already named in `dos_savegame.position`'s docstring as
the source of the shipped containers' (7, 13, 0), is where it comes from.

### The census

20 distinct 13149-byte Curse containers on this machine, deduplicated on
sha256, out of `work/`, `~/wish-specimens/` and the archives. Five hold area
0 and fifteen hold area 1; nothing holds any other area, because nobody has
played Curse past chapter one here. All five area-0 containers hold map 0,
square (7,13) facing 0 and clock 00:00; not one area-1 container does.

## The C64 holds the same numbers, and cannot enter on them

Read out of the running machine at the party menu, before anything is loaded.
`$4B00` is where `SAVEAZURE` loads, so this page is what `SAVE CURRENT GAME`
would write. Nine boots, identical every time.

| | `$4BF2` area | `$4BC5` map | `$4BE6` indoors | `$4BEE` disk | cache `$4DC0`+25 | clock |
|---|---|---|---|---|---|---|
| C64 party menu | 0 | 0 | 1 | **2** | twenty-five `00` | 00:00 |
| DOS slot J | 0 | 0 | 1 | **2** | -- | 00:00 |

The disk hint of 2 is the useful part: side 2 is where `ECL01` and `GEO01`
live, and that is the first thing the game will want.

**But a C64 save that *names* area 0 cannot be entered.**
`tools/curseareazero.py --doctor --recipe` stamps the never-adventured header
into a copy of an engine-written area-1 save disk, with exactly the cache
`goldbox.dos.apply_file_cache` would write -- `$FF` in all twenty-five, then
slot 2 the map, slot 8 the area and slot 11 `ANIMATE00`, each with bit 7 set.

| disk | changed from the engine's own | `BEGIN ADVENTURING` |
|---|---|---|
| the specimen | nothing | in the world, `W 20:33 5,13` |
| `--zero fdfe` | `+$FD`, `+$FE` = 0 | in the world, `W 20:33 5,13` |
| `--zero cache,fdfe` | plus all twenty-five slots `$FF` | the machine dies |
| `--recipe` | plus `+$F2`, `+$C5` = 0 | frame drawn, view empty, no status line, `INSERT SIDE # 2` for ever |

With the prompt on the screen, `$B7` = 5 and `$BB`/`$BC` = `$42BC`, and the
five bytes there are **`GEO00`** -- with side 2 already in the drive. So the
loader is asking for a file that is on none of the six sides, `LIBRARY
$42A2`'s retry cannot succeed, and the prompt comes back every pass.

## Two negative results

**The crash is not about area 0**, and neither is it about the disk-prompt
patch, which is what it looked like for two runs. Eight boots, one row each:

| disk | `curserun.DISK_PROMPT_PATCHES` | `BEGIN ADVENTURING` |
|---|---|---|
| pristine area 1 | none | in the world |
| area 1, `+$FD`/`+$FE` = 0 | none | in the world |
| area 1, twenty-five `$FF` | none | **crash** |
| area 0, twenty-five `$FF` | at the party menu | **crash** |
| area 0, twenty-five `$FF` | when the prompt was drawn | **crash** |
| area 0, twenty-five `$FF` | none | **crash** |
| area 0, converter's cache | when the prompt was drawn | asks for `GEO00` |
| area 0, converter's cache | when the prompt was drawn | asks for `GEO00` |

Every crash has a cache with nothing resident in any of the twenty-five
slots, whatever area the save names and whether or not the patch went in; the
two runs that carry the patch and a filled cache do not crash. So **a
hand-built all-`$FF` cache is the crasher**, and the first reading -- that
patching `$459A` at the party menu was fatal -- is refuted by the third row
from the bottom, which crashed with no patch at all.

`apply_file_cache` fills three of the twenty-five, so this only appears if
somebody builds a cache by hand.

## What this means for the conversion

`goldbox.dos.apply_file_cache` refuses an area-0 save with `the DOS party is
in area 0, which is not an area of Curse of the Azure Bonds`. **Adding a row
to `AREAS_CURSE` does not fix that**: with a row spliced into `areas.TABLES`
at run time the same save is refused one function later by `_resident_geo`,
because no area of Curse loads `GEO00`. Both refusals are right about the
game; what is missing is a rule for a party that has not set out.

Converting the area word through unchanged is measured to be wrong -- it makes
a save the player loads, presses `BEGIN ADVENTURING` on, and then faces a disk
prompt they can never answer. The shape that matches what the DOS engine
itself does is to convert such a party to the start of area 1: `GEO01`, side
2, the square 7,13 facing east, clock 00:00, and the arriving `ECL01` runs its
own entry on the C64 the same way it does on DOS, so the player gets the
awakening rather than skipping it.

That is a recommendation and not a decision; the choice and any sentence a
player reads about it are Donald's, and `#301 (A DOS Curse save standing in
area 0 is refused by the import, because no row of the area table names area
0)` carries both.

## What is not settled

**Whether the C64's own `SAVE CURRENT GAME` at the party menu produces a save
that can be loaded and begun.** The C64 holds area 0 in RAM there, so a save
taken at that moment would name area 0, and an area-0 save is what the
measurement above says cannot be entered. Either the C64 discriminates on
something outside the payload -- a flag in `GEN`'s own variables saying a
game has been loaded -- or the game has the same defect. The experiment is to
create a character on the C64, `SAVE CURRENT GAME`, reboot,
`LOAD SAVED GAME`, `BEGIN ADVENTURING`, and see whether the party wakes in the
small room or sits in front of `INSERT SIDE # 2`. Nobody has driven C64
character creation here.

**Whether Silver Blades and Pools of Darkness have the same case.** Both have
the same front end and the same `SAVE CURRENT GAME`, and neither has been
checked. Silver Blades' area ids start at `$10`, so 0 is not one of its areas
either.

## Tools

| tool | what it does |
|---|---|
| `tools/curseareazero.py` | boots C64 Curse to the party menu and reads `$4B00`-`$4DDF`; `--save`/`--begin` load a disk and press `BEGIN ADVENTURING`; `--doctor` stamps the never-adventured header into a copy of a save disk, one field at a time with `--zero` |
| `tools/doscurse.py console` | the DOSBox session the DOS half was driven in |
| `tools/daxls.py` | the `ECL`/`GEO` container indexes the "no block 0" row rests on |
