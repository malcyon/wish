# A party that has not set out, and how the import places it

A Gold Box saved game whose area word is 0 may be a party that has been
formed and has not yet pressed `BEGIN ADVENTURING`, with 0 being what the
engine's initialiser left there. On Curse of the Azure Bonds and Secret of
the Silver Blades that is the only thing area 0 can be; on Pool of Radiance
area 0 is also New Phlan, a real place a party spends much of the game in.
So the state has to be read off the container, never off the area word.

This is what `#301 (A DOS Curse save standing in area 0 is refused by the
import, because no row of the area table names area 0)` and
`#326 (A Pool of Radiance save made before the party began adventuring is
refused, because the initialiser left $49E6 at 0 and New Phlan is indoors)`
turned out to be, and since 2026-09-06 `goldbox/dos.py` converts such a
save to the start of the story on the two titles whose start is measured.
`docs/179-loading-a-curse-save.md` is the neighbouring document: how to get
a Curse save disk into the running game at all.

## What a player does to make one

The DOS party-formation menu offers `SAVE CURRENT GAME` to any party with a
character in it, between `REMOVE CHARACTER FROM PARTY` and
`BEGIN ADVENTURING`. So does the C64's -- `GEN $161`, next to
`GEN $151 LOAD SAVED GAME` and `GEN $186 BEGIN ADVENTURING`.

Create a character, add it to the party, save. That is the first five minutes
of the game, and the save it writes holds the initialiser's world state.

The saved games the DOS archives ship are exactly that on all three titles:
Curse's `SAVGAMA.DAT` and `SAVGAMB.DAT`, Silver Blades' `SAVGAMA.DAT` and
`SAVGAMB.DAT`, and Pool of Radiance's `SAVGAMB.DAT` -- ready-made parties,
saved from the party menu and never taken anywhere. Pool of Radiance's
`SAVGAMA.DAT` is the contrast: a party in New Phlan at 16:58.

## There is no area 0 in Curse -- CONFIRMED, both ports

| where | ids present | absent |
|---|---|---|
| the six C64 sides, directories read whole | `ECL01 02 03 04 10 11 12 15 1E 20 21 22 23 25 30 31 32 33 35 40 42 43 45 50 51`, and `ECL64`/`ECL65` on every side | `ECL00`, `GEO00` |
| DOS `ECL1.DAX`-`ECL6.DAX` block indexes | 1-4, 16-18, 21, 32-35, 37, 48-51, 53, 64, 66, 67, 69, 80-82 | block 0 |
| DOS `GEO2.DAX`-`GEO6.DAX` block indexes | 1, 3, 4, 16, 17, 21, 32, 33, 37, 50, 51, 53, 64, 66, 67, 69 | block 0, and `GEO1.DAX` does not exist |

Twenty-five scripts and sixteen maps, which is what `goldbox/areas.py`'s
`AREAS_CURSE` holds. Silver Blades' lowest id is `$04`, so it has no area 0
either. **Pool of Radiance's area 0 is New Phlan and the other two titles'
is nothing**, which is why enumerating a title's areas by counting from zero
is wrong for every Gold Box game after the first.

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

### The party menu does not reset the area

The control, same session. `LOAD SAVED GAME` slot H -- an engine-written save
in area 1 at 5,13 facing W, clock 20:32 -- then `SAVE CURRENT GAME` to slot I
without adventuring. Slot I holds area 1, map 1, 5,13 facing W, 20:32. So the
0 in slot J is the initialiser's value rather than something the menu writes,
and `GAME.OVR:0xF95E`, already named in `dos_savegame.position`'s docstring as
the source of the shipped containers' (7, 13, 0), is where it comes from.

## The census: all three titles, and the words that tell the two states apart

114 distinct DOS containers on this machine, deduplicated on sha256, out of
the archives, `work/`, `~/wish-specimens/` and `/home/donald/dos_por_play/`,
swept by `tools/neveradventured.py` on 2026-09-06. Grouped by whether the
staged area script (bytes 5121-12800 of the container) is all zero:

| title | containers | never adventured | area word there | is 0 a place in this title? |
|---|---|---|---|---|
| Pool of Radiance | 99 | 7 | 0 | **yes** -- New Phlan, `GEO00`, side 3 |
| Curse of the Azure Bonds | 8 | 4 | 0 | no |
| Secret of the Silver Blades | 7 | 2 | 0 | no |

| | never adventured (13) | in the world (101) |
|---|---|---|
| `$4FE1` | **0 in 13 of 13** | 255 in 57, 16 in 41, 8 in 3 -- **never 0** |
| `$49FD` | 0 in 13 of 13 | 11, 8 or 0 |
| `$49FE` | 0 in 13 of 13 | 10, 9 or 0 |
| script buffer | all zero | 1954-7222 non-zero bytes |
| clock | 00:00 in 13 of 13 | 00:00 in 5 of 101 -- **not a discriminator on its own** |
| square | (15,1,3) Pool of Radiance, (7,13,0) Curse and Silver Blades | 21 distinct in Pool of Radiance alone |
| `$49E6` | **0** in Pool of Radiance's 7, **1** in Curse's and Silver Blades' 6 | 1 indoors, 0 on the travel grid |

**Thirteen Pool of Radiance containers hold area 0 and a staged script.**
They are parties standing in New Phlan, and a rule reading "area 0 means the
party has not set out" would move every one of them to the arrival square
and reset its clock. The archives' own `POOLRAD/Default files/Saves/SAVGAMA.DAT`
is one of them.

**Two readings separate the states, and they agree on all 107 containers
where both can be taken.** The empty script buffer has a mechanism behind it
-- a party in the world always has its area's script staged there -- and is
what the import uses on Pool of Radiance and Curse. `$4FE1` needs no buffer,
which matters because Silver Blades' 5469-byte container stages no script;
Curse's `GAME.OVR:0x832F` stores `$FF` into it and three sites compare
against `$FF` (`goldbox.dos.LATER_BEGUN_WORD`), while what Pool of
Radiance's 255, 16 and 8 mean is unread, so for that title the word is a
census result rather than a reading of the engine. `goldbox.dos.never_adventured`
takes the buffer where the shape has one and the word where it does not, and
`tools/neveradventured.py --by rule` sweeps with exactly that.

**The initialisers disagree about `$49E6`.** Pool of Radiance's seven
never-adventured containers hold 0 there and Curse's and Silver Blades' six
hold 1 -- PROBABLE, from the containers, neither initialiser read for this
word. It is why each title was refused by a different check, and why a fix
tested on Curse alone would not have found `#326 (A Pool of Radiance save
made before the party began adventuring is refused, because the
initialiser left $49E6 at 0 and New Phlan is indoors)`:

| title | area word | which check refused it, until 2026-09-06 |
|---|---|---|
| Pool of Radiance | 0, and 0 is a real row | the `$49E6` indoors/outdoors compare: 0 reads as outdoors, New Phlan is indoors |
| Curse of the Azure Bonds | 0, no row | `area_in` -> `NOT_AN_AREA` |
| Secret of the Silver Blades | 0, no row | `area_in` -> `NOT_AN_AREA` |

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

## What the import does now

Donald decided on 2026-09-05, on `#301 (A DOS Curse save standing in area 0
is refused by the import, because no row of the area table names area 0)`:
**a party that has not set out is converted to the start of the first area**,
which is what the DOS engine itself does with the same save on
`BEGIN ADVENTURING`. The arriving script runs its own entry on the C64 the
same way, so the player gets the awakening rather than skipping it. He chose
it over refusing, on the reading that the player loses nothing -- there was
nothing to lose yet -- and that refusing would leave somebody who saved
straight after making their characters unable to move them at all.

`goldbox/areas.py`'s `STARTS` says where each title's story begins, and
`goldbox/dos.py` applies it:

| title | `STARTS` | what a never-adventured save converts to |
|---|---|---|
| Pool of Radiance | `Start(0x00, Arrival(15, 1, 3))`, CONFIRMED from the seven containers, agreeing with `AREAS`' driven arrival for New Phlan | area 0, `GEO00`, side 3, `15,1` facing west, `$49E6` = 1 -- what the save already holds, except that `$49E6` is now written from the row instead of compared against the initialiser's 0 |
| Curse of the Azure Bonds | `Start(0x01, Arrival(7, 13, 1))`, CONFIRMED in the running DOS game above | area 1, `GEO01`, side 2, `7,13` facing east, clock 00:00 |
| Secret of the Silver Blades | **no row**, deliberately | refused with `goldbox.dos.NotSetOutError`, whose sentence is marked `(NOT APPROVED)` |

The mechanics, in `goldbox/dos.py`:

* `never_adventured(savgam, shape)` is the test, off the container and never
  off the area word;
* `_where_the_party_is` hands `apply_file_cache` and `convert_save` the start
  row when it is true and the save's own `$49F2` row otherwise;
* `apply_file_cache` writes the start row's own map into slot 2 and `$49C5`
  -- the save's `$49C5` is the initialiser's 0, which is `GEO00`, New Phlan's
  map on one title and a file on none of the sides on the other -- and writes
  `$49E6` from the row rather than comparing it;
* `apply_position` writes the `Start`'s arrival square rather than the
  square the save holds, because the engine's own answer one keypress later
  differs from it on Curse (`7,13` N in the save, `7,13` E in the world);
* `convert_save` puts `NOT_SET_OUT` -- Donald's approved sentence, *"Your
  party had not set out yet, so it starts at the beginning of the story."*
  -- on `C64SaveReport.messages`, and `summary()` prints it. **The messages
  pane does not show `messages` yet**: `editor/dosimport.py` shows only the
  dropped list, and wiring the line in is the one piece of this left to do.

A party standing in New Phlan with the clock running is untouched: the
staged script says it has set out, and its own square, clock and map are
written as before. `tests/test_dosconvert.py`,
`tests/test_curseconvert.py` and `tests/test_ssbconvert.py` hold a test per
title, and the one that matters most --
`test_a_party_standing_in_new_phlan_is_left_exactly_where_it_is` -- pins the
regression the naive fix would cause.

## The converted disk enters the world -- CONFIRMED, 2026-09-06

`WISH-SPEC-curse-234-party-dualclassed` slot D -- the DOS engine's own
`SAVE CURRENT GAME` at the party menu, six characters, area 0 -- converted
by `tools/cursedisk.py` and driven on pool slot 1 by
`tools/curseareazero.py --save CURSE-D-notsetout.D64 --begin --side 2`:

| moment | area | map | disk hint | cache |
|---|---|---|---|---|
| party menu, before the load | 0 | 0 | 2 | twenty-five `00` |
| after `LOAD SAVED GAME` | **1** | **1** | 2 | `FF FF 81 ... 81 ... 80 ...` -- the converter's three slots |
| after `BEGIN ADVENTURING` | the view drawn, all six listed, status line **`E 0:00 7,13`**, command bar `MOVE VIEW CAST AREA ENCAMP SEARCH LOOK` | | | |

No side prompt was drawn at all, because side 2 was in the drive; the
`INSERT SIDE # 2` loop the area-0 disk sat in for ever did not appear. The
square, the facing and the clock are the ones the DOS run photographed one
keypress after the same save. Whether the awakening text was shown is not
in the record: the harness answers prompts on its way to the status line, and
the message window was clear by the time it read it.

## What is not settled

**Where Secret of the Silver Blades begins.** Its two never-adventured
containers hold the same area 0 and `7,13` facing north that Curse's do, its
table's lowest id is `$04`, and all five of its played containers stand in
area `$10` (`GEO10`, side 1, arrival 15,8 W) -- which is suggestive and is not
the measurement. The experiment is the one that settled Curse: boot DOS
Silver Blades, create one character, add it to the party, `SAVE CURRENT
GAME` to a free slot, then `BEGIN ADVENTURING` and save again with the party
standing still. Area `$10` in the second save confirms `$10`; `$04` confirms
`$04`. Until then `STARTS` has no row and the import refuses.

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

**`dos_savegame.SAVGAM_CONSTANTS` still calls `$4FE1` "255 in every
specimen".** The census reads 255 in 57 played containers, 16 in 41 and 8 in
3, so the constant is what a conversion writes rather than what every save
holds; the part the discriminator rests on -- never 0 once the party has been
in the world -- is unaffected.

## Tools

| tool | what it does |
|---|---|
| `tools/neveradventured.py` | the census above: every distinct container on the machine, per title, split by the staged script (`--by buffer`), by `$4FE1` (`--by word`) or by the rule the import applies (`--by rule`) |
| `tools/curseareazero.py` | boots C64 Curse to the party menu and reads `$4B00`-`$4DDF`; `--save`/`--begin` load a disk and press `BEGIN ADVENTURING`; `--doctor` stamps the never-adventured header into a copy of a save disk, one field at a time with `--zero` |
| `tools/doscurse.py console` | the DOSBox session the DOS half was driven in |
| `tools/daxls.py` | the `ECL`/`GEO` container indexes the "no block 0" row rests on |
