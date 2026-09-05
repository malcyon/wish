# Only Pool of Radiance draws a sheet portrait

Of the three C64 Gold Box titles this project converts, **one draws a face on
the character sheet.** Curse of the Azure Bonds and Secret of the Silver
Blades do not, and the reason is a step earlier than the art: their
character-sheet routine never asks for a portrait, so no id in a record and
no file on a disk could make one appear.

That answers `#300 (A Curse or Silver Blades party imported to the C64
arrives with no sheet portrait, because the creation menu is read only off a
POOL<n>.D64)`, and it changes what the ticket is: a Curse or Silver Blades
party arriving without a face has lost nothing, because there is nothing on
that side for it to have.

**The picture**, which is the evidence a reader can check without a
disassembly: `work/issue300/three-sheets.png` -- one character sheet from
each title, same harness, same window. Pool of Radiance draws a face in a
framed box on the right; Curse leaves that side of the screen blank; Silver
Blades draws a framed panel there and puts the character's money in it.
(Lost when `work/` next goes; `tools/portraitdraw.py` and the run recipe
below rebuild it.)

## What Pool of Radiance does

`LIBRARY $48A4`, twenty instructions, is the portrait step. `LIBRARY` runs
at `$2C48` (`docs/40-memory-map.md`, CONFIRMED), and every address here is
that base.

```
$48A4  LDA $49EB / BNE $48D6      the arriving script's scratch: non-zero, skip
$48A9  LDA $49FF / BPL $48D6      the save's own switch at +$0FF: bit 7 clear, skip
$48AE  LDX #$0B  / JSR $4222      loaded-files slot 11, ANIMATE: mark for reload
$48B3  LDA $6BFE / LDX #$0E / JSR $4225    record 0x0FE -> slot 14, HEAD<xx>
$48BB  LDA $6BFF / LDX #$0D / JSR $4225    record 0x0FF -> slot 13, BODY<xx>
$48C3  LDA #$D7  / LDX #$48 / JSR $3C12
$48CA  JSR $8406 / JSR $8403 / JSR $8409 / JSR $8403
$48D6  RTS
```

`$4222` and `$4225` are the loader's two entries and `$6BFE`/`$6BFF` are
`portrait_head` and `portrait_body` in the live character record
(`docs/140-loaded-files-cache.md`). `$8406` and `$8409` are two of
`ANIMATE00`'s seven jump-table entries: both draw at screen `$CC44`, which is
the right-hand box on the sheet, `$8406` from the `BODY` slot's load address
and `$8409` from the `HEAD` slot's, with frame kind 1 -- the five-row
portrait of `docs/181-curse-picture-buffer.md`.

Three callers: `LIBRARY $4435`, which is the sheet screen itself (its menu
string is at `$4486` and reads `VIEW: ITEMS SPELLS TRADE DROP EXIT`);
`DUNGEON $0D4B`, a tail `JMP`; and `GEN` on `POOL3`, the front end's own
sheet. So both routes to a sheet -- the party-formation menu and `VIEW` in
the world -- go through it.

## What the other two do instead

| measurement | Pool of Radiance | Curse | Silver Blades |
|---|---|---|---|
| sides searched | 9 (`POOL*.[dD]64`) | 6 | 6 |
| files searched | 984 | 558 | 571 |
| `LIBRARY` runs at | `$2C48` | `$2DC8` | `$2DC8` |
| loader calls from `LIBRARY` | 3: slot 11, slot 14, slot 13 | **0** | **0** |
| files calling `ANIMATE +$6` (body at `$CC44`) | 2: `LIBRARY`, `POOLRB` | **0** | **0** |
| files calling `ANIMATE +$9` (head at `$CC44`) | 2: `LIBRARY`, `POOLRB` | **0** | **0** |
| files calling `ANIMATE +$0`/`+$3`/`+$C` (the view window) | 4 / 6 / 2 | 5 / 4 / 3 | 3 / 3 / 2 |
| the sheet routine | `LIBRARY $4435`, menu `VIEW: ITEMS SPELLS TRADE DROP EXIT` | `LIBRARY $4600`, menu `ITEMS SPELLS TRADE DROP CURE HEAL EXIT` | present, same shape |
| `LIBRARY` naming the save's `+$0FF` | yes, the `BPL` above | no | no |

`tools/portraitdraw.py` prints that table off the player's own disks. It
finds each overlay's load address by scoring its own `JSR`/`JMP` targets for
legal opcodes, finds the loader's two entries by their code, and takes
`ANIMATE`'s run address out of that title's own load-address table, so
nothing in it is a remembered constant.

`POOLRB` is one of the cracked booter's blobs on `POOLBOOT.D64` and carries
copies of `GEN`'s and `LIBRARY`'s code; it is not a second implementation.

**Grade: CONFIRMED.** Every file on every side of all three titles, and the
routine read in full.

## Watched in the running game

Pool slot 3 (Curse) and slot 5 (Silver Blades), 2026-09-05, both parties
engine-written specimens out of `~/wish-specimens/por-c64/`.

| title | sheet reached by | cache slot 13 | slot 14 |
|---|---|---|---|
| Curse | `VIEW CHARACTER` at the party menu (`GEN`) | `$FF` | `$FF` |
| Curse | `VIEW` on the world bar (`LIBRARY`) | `$FF` | `$FF` |
| Silver Blades | `VIEW CHARACTER` at the party menu | `$FF` | `$FF` |

`$FF` in a loaded-files slot is the only value that means "never filled", so
no `HEAD<xx>` or `BODY<xx>` was asked for. The cache is at `$7F13` in both
later titles against `$6E13` in Pool of Radiance, and
`#57 (Convert the character portrait across ports)` read `$08`/`$07` and
`$09`/`$02` out of those two slots on a Pool of Radiance sheet.

**And the ids being zero is not the reason.** Every Curse and Silver Blades
record holds `portrait_head = portrait_body = 0`, which on its own would
leave a game that draws nothing for a zero pair indistinguishable from a game
with no portrait step. So `$41` -- `HEAD41` and `BODY41`, both of which exist
on `CURSE_B` -- was written into `+$0FE` and `+$0FF` of every record in
memory with the sheet closed, and the sheet re-opened: the sheet is
unchanged, both cache slots are still `$FF`, and the live record window at
`$7CFE` reads `41 41`, so the game did read the record. The same on Silver
Blades, which ships no `HEAD<xx>` or `BODY<xx>` file at all.

The recipe, for anyone repeating it: boot with `tools/curserun.py --pool N
--disks <dir> --save <d64>` or `tools/ssbrun.py --pool N --save <d64>`, then
through `tools/porcmd` -- walk the party menu with `key Down` and answer with
`kernal 0D` in Curse or `key Return 0.25 0.3` in Silver Blades, `VIEW
CHARACTER`, then the character. `peek 7F13 25` is the cache and `peek 7CFE 2`
is the displayed character's pair. For the world sheet in Curse, `BEGIN
ADVENTURING`, `poke 459A EAEA` and `poke 459F EAEA` for the side prompt
(`tools/curserun.py` explains those two), then `bar VIEW`.

## The machinery both later titles still carry, and why the disks mislead

Everything except the caller survived into Curse and Silver Blades, which is
why their disks look as though the feature is there.

* **`ANIMATE00` is the same routine, relocated.** Curse's `$6809` entry still
  sets frame kind 1 and still points itself at `$7300` -- which is exactly
  where **Curse's own loader table** puts a `HEAD<xx>` file. Correctly
  relocated and never called.
* **The loader still has 25 slots** with `BODY` at 13 and `HEAD` at 14 in all
  three, and both later titles still carry the stem strings `BODY00` and
  `HEAD00` -- Curse's inside `LIBRARY`, Silver Blades' inside `ITEMNAMES`.
  Silver Blades has the stems and no such file on any side.
* **Curse's `HEAD<xx>`/`BODY<xx>` files are encounter art, not creation art.**
  Their ids track the *area* each side carries -- `HEAD10`-`HEAD18` beside
  `GEO10`, `ECL10` and `MON10` on `CURSE_C`, `HEAD20`-`HEAD26` beside `GEO20`
  on `CURSE_D` -- and what loads them is `POST.COM`'s picture routine, which
  composites body then head into the **view window** at `$CC7B` through
  `ANIMATE`'s `+$0` and `+$C` entries. That is the talking head in an
  encounter, and Pool of Radiance draws it from the same routine.

So a search for Pool of Radiance's 14-head, 12-body creation menu in Curse's
`GEN` finds nothing not because the table moved but because that menu does
not exist in Curse. The first pass on
`#300 (A Curse or Silver Blades party imported to the C64 arrives with no
sheet portrait, because the creation menu is read only off a POOL<n>.D64)`
had already found that, permissively, across all six sides; this is the
mechanism behind it.

## What a conversion should do

**Nothing, and say nothing.** A Curse or Silver Blades character arriving on
the C64 without a portrait is a character arriving correct: the destination
does not draw one for any character, including one the engine made itself.
`.claude/rules/conversions.md`'s first reason -- the destination has no such
field -- is met here in its strongest form, established by reading the
destination's own code and then watching it, rather than assumed.

`goldbox/dos.py` already encodes this for the C64-to-DOS direction:
`draws_portrait = shape is POOL_OF_RADIANCE`, with the comment that the pair
is zero in all 32 Curse and all 44 Silver Blades records the project holds.
The import direction has no such gate, so a Curse or Silver Blades import
reports four lines about a portrait it could not read. Those lines describe a
loss that does not exist and are the defect
`#300 (A Curse or Silver Blades party imported to the C64 arrives with no
sheet portrait, because the creation menu is read only off a POOL<n>.D64)`
should close on.

## Corrections this made to what was written down

* **`goldbox/dos.py` cites the portrait routine as `LIBRARY $2C5C`.** It is
  `LIBRARY $48A4`. `$2C5C` is the file offset added to the PRG header's
  `$1000`, and `docs/40-memory-map.md` says in its first paragraph that a
  header on these disks is a family stamp rather than a load address. The
  arithmetic proves itself: the loader entry `$4225`, which every other
  overlay reaches by an absolute `JSR`, is past the end of a 7,350-byte file
  loaded at `$1000`, and lands correctly with `LIBRARY` at `$2C48`. The
  instructions quoted beside that address are right; only the address is
  wrong.
* **`goldbox/c64_save.py` calls save offset `0xFF` the `portrait_switch` for
  all three titles.** In Pool of Radiance that is right -- `LIBRARY $48A9`
  tests its bit 7. In Curse the byte is named eight times and never by
  `LIBRARY`: `CAMP $09BC` reads **bit 0** to choose between two menu labels
  and `CAMP $09D3` flips it with `EOR #$01`. So in Curse `+$0FF` is a camp
  toggle that happens to share an offset. Writing `$81` there stays correct,
  because Curse's own `INIT` writes `$81` and both engine-written specimens
  hold it; the value is right and the name is wrong.
* **`tools/absrefsweep.py` prints every overlay address two bytes high**,
  because it maps the PRG header to `$0800` rather than the byte after it.
  Both `CAMP` addresses above came out of it and have had the two subtracted;
  `#312 (Every overlay address absrefsweep prints is two bytes high, because
  it maps the PRG header to $0800)` is the ticket.

## What is still unmeasured

* **Whether DOS Curse and DOS Silver Blades draw a sheet portrait.** This
  page is about the C64 destination. All 12 shipped Curse `CHRDAT*.SAV`
  records in the archives read `portrait_head = portrait_body = 0`, which
  fits "neither port has one" and does not prove it. The experiment: open a
  Curse character sheet in DOSBox with `tools/dosbox.py` and look, then set
  `0x0BB`/`0x0BC` of that record to 1 and look again.
* **What Curse's `+$0FF` bit 0 actually toggles.** `CAMP $09BC` picks between
  message `$FD` and message `$FE`; nobody has read the two strings or watched
  the menu. It matters only to naming the field.
* **Where Curse's character-creation portrait choice went.** Curse's `GEN`
  has no 14/12 menu table anywhere and its records hold a zero pair, so the
  likely answer is that the creation screens never offer one -- but nobody
  has driven Curse's `CREATE NEW CHARACTER` to the end and watched. That is
  the run that would settle it.
