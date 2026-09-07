# Three things Amiga Pool of Radiance does, watched

One WinUAE session on 2026-09-07 answered three questions that had each been
waiting for somebody to look at a running Amiga game: whether the character
sheet draws a portrait, what the engine does with a space in a name, and
whether the game's own `Add Character` picker lists a `.pc` file this project
wrote. `tools/amigashots.py` drove it and photographed every keystroke;
`docs/143-winuae-debugger.md` is how the emulator is reached and
`docs/182-amiga-por-in-the-running-game.md` §7 is the route from a cold VM to a
loaded slot.

## 1. The character sheet draws no portrait, and no box for one

`#322 (Nobody has looked at an Amiga Pool of Radiance character sheet to see
whether it draws a portrait at all)`.

The disk was built the way that issue asked for -- a C64 party whose records
carry portrait ids, so `goldbox.amiga.new_por_savegame` wrote `$49FF` = 3:

```sh
tools/toamigapor.py work/3q/por1.adf --to B --out work/3q/por1-B.adf \
    --data-disk work/3q/por2.adf \
    --c64 ~/wish-specimens/por-c64/WISH-SPEC-por-party-twin-pair.d64
```

Read back at `por_word_offset(0x49FF)` = `0x1FE`, the built `savgamB.dat` holds
`00 03`, the same value the disk's own shipped `savgamA.dat` holds. Booted,
`LOAD SAVED GAME`, path `SAVE/`, slot `B`, `VIEW`:

```
BRUTUS
MALE HUMAN AGE 21
NEUTRAL GOOD
FIGHTER

STR 18(98)      GOLD 120
INT 16
...
AC 10   THAC0 18     ENCUMBRANCE 120
HP 11   DAMAGE 1D2+5     MOVEMENT 12

STATUS OKAY
```

**The text runs the full width of the frame and there is no picture and no
empty box anywhere on the screen.** Where the C64 and DOS put a face -- the
right-hand third of the same screen -- this port puts `GOLD`, `ENCUMBRANCE` and
`MOVEMENT`. Seven sheets have now been drawn on this port, one here and the six
of `#354 (Wish has never opened a converted character's sheet in the Amiga game
it wrote it for)`, and not one drew a face.

So the second half of the question does not arise: **there is no portrait for
`$49FF` to gate**, and building the disk twice more with the word forced to 0
and to 3 would compare two identical pictures. The word's entry in
`goldbox.amiga.POR_SAVGAM_MEASURED` opens by calling it "the word that gates
the sheet portrait", which this run makes untrue on this port; 3 is still the
right value to write, because every engine-written Amiga saved game holds it,
so the entry belongs beside the unsourced ones with that as its reason.

**What this does not say** is that Amiga Pool of Radiance has no portrait art
anywhere. The character sheet is what was opened; the game's own
character-creation screens were not.

## 2. The engine strips every space out of every name it saves

`#308 (Does Amiga Pool of Radiance drop the space out of a character's name
when it saves?)`.

You type `MARY SUE` into the game's own `NEW NAME FOR BRUTUS` box. The box
draws `MARY SUE` and so does the party panel. You camp, `SAVE`, pick a slot --
and the panel reads `MARYSUE` before you have reloaded anything.

Four names were typed through the character sheet's `RENAME` and saved to four
fresh slots. The bytes are the 16-byte name field at offset `0x000` of the
288-byte `CHRDAT<slot>1.sav` the engine wrote:

| slot | typed in | the engine's record | read back as |
|---|---|---|---|
| C | `MARY SUE` (8, one space) | `4d 41 52 59 53 55 45 00 …` | `MARYSUE` (7) |
| D | `MARY SUE FOX` (12, two spaces) | `4d 41 52 59 53 55 45 46 4f 58 00 78 00 00 00 00` | `MARYSUEFOX` (10) |
| E | `ABCDEFGHIJKLMNO` (15, no space) | `41 42 43 44 45 46 47 48 49 4a 4b 4c 4d 4e 4f 00` | `ABCDEFGHIJKLMNO` (15) |
| F | `ABCDEFG HIJKLMN` (15, one space) | `41 42 43 44 45 46 47 48 49 4a 4b 4c 4d 4e 00 00` | `ABCDEFGHIJKLMN` (14) |

**Slot E is what rules truncation out.** Fifteen characters with no space came
through whole and fifteen with a space came through as fourteen; a field that
cut would have lost E's last letter too. `MARY SUE FOX` lost two characters,
one per space, so every space goes rather than the first.

**Fifteen is the field's width**, measured: twenty letters were typed and the
box took `ABCDEFGHIJKLMNO` and ignored `P` through `T`. The record's field is
16 bytes and always keeps at least one NUL.

Two things the issue was unsure about:

* **The game's own name entry takes a space happily**, so this is not a name
  the Amiga would never make and refusing or folding it in our writer would
  take away a name the game itself offers a player. The box was `RENAME` rather
  than `CREATE NEW CHARACTER`; it is the same prompt shape and a run that uses
  creation as well is cheap now.
* **It happens to a converted name on every save, not only the first.**
  `LADY KATHERINE` went in as `4c 41 44 59 20 4b 41 54 48 45 52 49 4e 45 00 00`
  and slots C, D, E and F all hold `LADYKATHERINE` with three NULs.

Sample: 4 typed names and 6 converted characters across 4 engine saves, 5 slots
of records read. 9 of 9 names holding a space lost every space; 0 of 26 names
without one changed at all.

Nothing our writer can do prevents it, so the writer should keep writing the
player's name with its space -- the game draws it correctly until the first
save. What is left is a sentence in the messages pane, which is Donald's to
word and `.claude/rules/gui-text.md`'s to govern.

The disk the engine wrote all four of those slots onto is
`~/wish-specimens/por-amiga/WISH-SPEC-por-amiga-name-spaces`, copied out of the
emulator slot before it went. The `work/` paths above are the run's own scratch
and the command at the top of §1 rebuilds them.

**Read a name to the first NUL, not to 16 bytes.** Slot D's field is
`… 4f 58 00 78 00 …`: a lowercase `x` one byte past the terminator, because the
engine does not clear the field behind it. `goldbox.amiga` already stops at the
NUL.

## 3. Pools of Darkness lists what `File > Export > Amiga...` writes

`#317 (Does the Amiga game's Add Character menu list a character Wish exported
into the pool drawer?)`.

`tools/toamiga.py` is the command-line half of the same
`goldbox.amiga.export_party` the menu item calls, so this exercises the menu
item's writer:

```sh
tools/toamiga.py ~/wish-specimens/por-c64/WISH-SPEC-ssb-d-engine-resave.D64 \
    -o work/3q/pcexport
```

Six 484-byte files -- `DOMINIC.pc`, `EPONA.pc`, `GUYDEVAL.pc`, `MALACHIT.pc`,
`MORGAINE.pc`, `PAINE.pc` -- written into the `Save` drawer of a copy of Pools
of Darkness disk 3 with `goldbox.amiga_adf.AmigaDisk.write_file`. **New
directory entries with their own names**, which is what §2.5 of
`docs/124-amiga-port.md` could not do: that run got a `.pc` into the game by
overwriting `Save/TROND.pc`'s bytes, so it proved the record and not the
drawer. The disk verified clean, 79 free blocks down to 67, and the twelve
genuine `.pc` files were left in place as a control.

`PLAY` -> `ADD CHARACTER` -> `POOLS` listed **all eighteen**, each drawn from
the name inside the record rather than from the file name:

```
TROND        PAINE          MAGIC JHONSON   KRISTIN
BJORK        MALACHITE      CLERIC          IN RANGE
KILL KILL    FRODE          TRIPEL TURBO    GUY DE VALOIS
TURBO K      ?T             MORGAINE        EPONA
JORILD       DOMINIC
```

`GUYDEVAL.pc` draws as `GUY DE VALOIS`, so the eight-character stem is a file
name and nothing more. Cursor down to `PAINE`, `ADD`: no `DISK READ ERROR`, and
the row came back `* PAINE`, the asterisk that marks a name matching a party
member. `VIEW CHARACTER` drew `MALE 22 YEARS`, `LAWFUL GOOD HUMAN`, `RANGER`,
`LEVEL 8`, `HIT POINTS 74/74`, `EXPERIENCE: 202750`,
`STR 18(51) INT 17 WIS 16 DEX 18 CON 16 CHA 16`.

Every ability is the bytes the writer put in `PAINE.pc` -- `18 18 17 17 16 16
18 18 16 16 16 16` as base/current pairs from `0x70`, exceptional strength
`0x33` = 51 at `0x7C`, hit points `0x4A` = 74 at `0x81`, level 8 in the fifth
class slot at `0x9D`. The three derived fields came out **computed rather than
copied**: the writer wrote the unarmoured 10 and PoD applied dexterity 18 for
`ARMOR CLASS 6`, `THAC0 12` is an eighth-level ranger's 13 less the 18/51
strength's 1, and `DAMAGE 1D2+3` is unarmed `1d2` plus that strength's damage
bonus.

So the drawer is the pool, `editor/exports.py`'s `AmigaPlan` docstring is
right, and a player who uses that menu item gets characters the Amiga game
offers them.

**Where the disk has to be.** The `Save` drawer of **disk 3**, and disk 3 in
**DF1** -- with it in DF2 the game sat on `INSERT DISK 3 AND PRESS A KEY` and
took no key at all, and moving it to DF1 went straight through to
`PLAY DEMO QUIT`. Disk 3 cannot go in DF0 instead, because Kickstart 1.3 will
not boot it: its bootblock's checksum longword reads `44 4f 53 01`, which is
the text `DOS\x01` rather than a checksum, so the machine sits on the
insert-disk hand.

**Adding a character wrote nothing to the pool disk.** The ADF came back off
the guest byte for byte identical to the one that went in, and WinUAE does
write ADFs back in this harness -- the Pool of Radiance disk in the same
session came back carrying four new save slots. `docs/124-amiga-port.md` §2.4
says "PoD writes the character back to the save disk when it is added", from an
FS-UAE session where a `THIEFTEST.pc` appeared one probe after THIEFTEST
joined; that did not reproduce here, so whatever wrote it was something later
in that session rather than `ADD`.

What this run did not do: only PAINE was taken into the party, the other five
were listed and left; and no drawer other than `Save` on disk 3 was tried.

## 4. Driving notes, for the next run

* **`RENAME` is on the character sheet's own bar**, `VIEW SPELLS TRADE DROP
  RENAME EXIT`, and it is far cheaper than creating a character when what is
  wanted is a name in the engine's own hands.
* **The sheet does not redraw its name after a rename.** It still says the old
  one; the party panel behind it has the new one immediately. A run that judges
  a rename by the sheet in front of it reads the wrong answer.
* **`ENCAMP > SAVE > <letter>` is followed by `QUIT TO WORKBENCH  YES  NO`**, so
  `N` keeps the game up and a second save can follow in the same boot. Four
  saves to four slots came out of one boot that way.
* **The cursor keys move the party** in Amiga Pool of Radiance as they do in the
  later titles, `DOWN` being about-face, so they are not a way to pick another
  party member on the adventuring bar. Nothing found here selects one: `VIEW`
  enters on the first character, from the bar and from camp alike, which is
  what `docs/182-amiga-por-in-the-running-game.md` §6 already said.
* **`E` on the Pools of Darkness party menu is `EXIT FROM GAME`**, not the
  picker's `EXIT`, so two `E`s in a row out of the picker put `QUIT GAME? YES
  NO` on screen. `docs/124-amiga-port.md` §2.4 already said so and it still
  cost a step here.
* **The cursor keys move the Pools of Darkness picker's cursor.** They could
  not under FS-UAE, which is why §2.4 says the payload has to go in the file
  the picker lists first; under WinUAE with `KEYEVENTF_EXTENDEDKEY` one `DOWN`
  moved from `TROND` to `PAINE`, so any row can be reached now.
* **The emulator's screen is 720x568 inside a 1920x1080 grab.**
  `tools/amigashots.py crop` cuts it out by finding WinUAE's status bar rather
  than by remembering where the window sat. Kickstart's insert-disk screen is
  the one that breaks a lazy version of that search: it is white to the client
  area's last row, so "walk up while the row is light" walks seven rows into
  the picture. `tests/test_amigashots.py` holds that case.
