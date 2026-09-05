# A converted party in Amiga Pool of Radiance

What the game does with character files our own code wrote, measured on the
screen and in the bytes it wrote back. Four runs under WinUAE on 2026-09-05
for `#105 (Write an Amiga Pool of Radiance character, not just a Pools of
Darkness one)`; `docs/143-winuae-debugger.md` §1 is the procedure and
`work/issue105/` holds the screenshots.

The short version, and it is the answer `#105 (Write an Amiga Pool of
Radiance character, not just a Pools of Darkness one)` had been waiting for
since 2026-08-26: **the ITEMS screen draws an item whose 42-byte display line is
entirely NUL in the file, and it writes the render it drew back into that
line.** So `goldbox.amiga.amiga_por_item_from_dos` leaving the buffer NUL is
right, and nothing in the writer has to change.

## 1. What was loaded

| slot | party | who wrote it |
|---|---|---|
| `A` | GARWAN and five others | the game, shipped on disk 1 |
| `F` | the same six, Amiga -> neutral -> Amiga | `goldbox.amiga.write_por_slot`, for `#109 (A save slot written onto an Amiga disk is not offered by the game's picker)` on 2026-09-01 |
| `B` | MALCYON, TWIN, ROLAND, LADY KATHERINE, MAGNUS, BRUTUS | `tools/toamigapor.py --c64`, from the C64 specimen `por-party-twin-pair` |
| `C` | the same six | **the engine**, saved from slot `B` in camp |
| `D` | THRENDER GRONE | `tools/toamigapor.py --dos`, from the DOS specimen `por-item-granted` |
| `E` | THRENDER GRONE | **the engine**, saved from slot `D` after the ITEMS screen was opened |

Every party was put in front of `LOAD SAVED GAME`, path `SAVE/`, and the picker
offered every slot: `A B C D F` on the first disk and `A B C D E` on the
second. The saved game around each converted party is the disk's own
`savgamA.dat` with its character table pointed at the new slot, so the place
is the game's and the party is ours.

## 2. The item display line: composed at draw time, cached back

**CONFIRMED.** GARWAN's three item nodes in slot `F` hold 42 NUL bytes each,
and slot `A`'s copies of the same three items hold `Long Sword \0word
\0          15\0`, `Banded Mail \0Mail \0         90\0` and ` Yes  Shield
\0              15\0`. His ITEMS screen off slot `F` reads:

```
READY ITEM
YES    LONG SWORD
YES    BANDED MAIL
YES    SHIELD
```

Nothing on those rows can have come from the file. The name comes from
`name1`, `name2` and `name3` at `0x02F`-`0x031`, the ready column from
`readied` at `0x034`; a converted DOS character in slot `D` drew `YES FLAIL`
and `YES BANDED MAIL` off two nodes that were equally NUL.

**And the engine writes the render back**, which is what makes the buffer a
cache rather than a coincidence. Slot `D`'s two nodes went in NUL; the engine
loaded them, drew ITEMS, camped and saved to slot `E`, and the same two nodes
came back holding:

```
Flail \0lail \0
Banded Mail \0Mail \0
```

The second string is the tail of a longer, earlier render of the same item,
and the arithmetic is exact: `' Yes  Flail '` is twelve characters and
`'Flail \0'` is seven, so what survives from index 7 is `'lail '`; `' Yes
Banded Mail '` is eighteen against thirteen, leaving `'Mail '`. That is the
same structure the game's own shipped nodes have, and it means the line is
composed at least twice, once with the ready column and once without.
`docs/124-amiga-port.md` §1.9's reading of the tails is confirmed by watching
one being made.

The earlier measurement that the engine "did not compose it on load and did
not compose it on save" (17 nodes of 17 through a load, a camp and a save,
the disk of `#109 (A save slot written onto an Amiga disk is not offered by
the game's picker)`) is not contradicted: that run never opened ITEMS. **The
composer runs when a screen needs the line, and not before.**

The price column -- `          15` in the game's own nodes -- did not appear in
slot `E`, so it is written by some third screen, presumably a shop. Nothing
here says which.

## 3. Two ports arriving

**A C64 party runs.** Slot `B`'s six drew on the party panel as MALCYON 8/4,
TWIN 8/4, ROLAND 10/7, LADY KATHERINE 8/5, MAGNUS 9/9, BRUTUS 9/11, and every
hit-point figure is the C64 record's own. MALCYON's sheet reads `MALE ELF AGE
176`, `NEUTRAL GOOD`, `MAGIC-USER`, `STR 15 INT 17 WIS 15 DEX 16 CON 13 CHA
15`, `GOLD 60`, `LEVEL 1 EXP 0`, `AC 8 THAC0 20 ENCUMBRANCE 60`, `HP 4 DAMAGE
1D2 MOVEMENT 12`, `STATUS OKAY` -- and each of the eleven values the C64
record carries matches it exactly.

**A DOS character runs, with his items.** THRENDER GRONE drew `MALE DWARF AGE
52`, `LAWFUL GOOD`, `FIGHTER`, `STR 17 INT 12 WIS 12 DEX 17 CON 16 CHA 15`,
`PLATINUM 2 SILVER 144`, `LEVEL 1 EXP 48`, `AC 1 THAC0 19 ENCUMBRANCE 646`,
`HP 11 DAMAGE 1D6+2 MOVEMENT 9`, `WEAPON FLAIL`, `ARMOR BANDED MAIL`.

**A character who owns nothing gets a coherent sheet and no ITEMS entry.**
MALCYON carries no items, and his sheet's menu row is `VIEW TRADE DROP RENAME
EXIT` where an equipped character's reads `VIEW ITEMS TRADE DROP RENAME EXIT`.
That is the Amiga's answer to the shape of
`#62 (A converted character who owns nothing gets a corrupt sheet, and DOS then
invents a garbage item)`: the entry is not offered rather than drawn wrong. It
is one character on one run, so PROBABLE as a rule about the engine.

## 4. What the engine changed, byte by byte

The whole value of a party the engine re-saved is that every difference is
either a field it derives or a field we got wrong, and there is no third kind.
`tools/porslotdiff.py` is the reader.

**Slot `B` against slot `C`: 57 bytes of 1728 differ**, and outside the two
live-heap fields the list is short.

| character | field | ours | the engine's |
|---|---|---|---|
| all six | `effect_chain` `0x081`-`0x083`, `heap_104` `0x107`-`0x109` | NULL | live Amiga heap |
| five of six | `party_order` `0x0C1` | 0 | 1, 2, 3, 4, 5 by position |
| MALCYON, TWIN, LADY KATHERINE | `thac0_base` `0x02D` | 39 | 40 |
| MALCYON | `attack_level` `0x06B`, `thac0_current` `0x112` | 0, 39 | 1, 40 |
| LADY KATHERINE | five `thief_*` at `0x077`-`0x07E` | 30, 25, 20, 10, 5 | 40, 20, 15, 15, 0 |
| MAGNUS | five `save_*` at `0x06D`-`0x071` | 11, 12, 13, 14, 14 | 14, 15, 16, 17, 17 |
| LADY KATHERINE | `name_text` `0x004`-`0x00D` | `LADY KATHERINE` | `LADYKATHERINE` -- §5 |

**Slot `D` against slot `E`: 19 bytes of 288**, all of them `item_chain`,
`effect_chain`, `hands_used` (0 to 1) and the same name change.

Three things follow.

* **`goldbox.dos.WRITE_UNSOURCED`'s three pointer fields are the engine's, on
  this port too.** Our NULLs went in, the engine's own addresses came out, and
  the party played. `hands_used`, which the conversion reports as not
  converted because it is "set again the next time the character fights", was
  set by the engine without a fight -- so writing zero is right.
* **The Amiga engine recomputes the same derived block the DOS engine does.**
  `#191 (A converted dwarf loses his constitution bonus to saving throws)`
  measured, on the DOS engine and from a C64 party of the same characters out
  of `PORSAVE13`, `thac0_base` 39 to 40 for LADY KATHERINE and MALCYON, all
  five `thief_*` for LADY KATHERINE, the five saving throws for MAGNUS the
  dwarf, and `armour_class` 2 to 3 for BRUTUS. **The first three recur here,
  on the same characters, with the same numbers.** The fourth does not, and
  the reason is the specimen rather than the port: this party owns nothing, so
  BRUTUS's stored armour class is already the unarmoured 9 the engine would
  compute. Two engines agreeing on three of three testable fields means a
  conversion need not get a derived field right, because the engine replaces
  it either way.
* **The fix in `#191 (A converted dwarf loses his constitution bonus to
  saving throws)` reaches the Amiga for free, and the dwarf keeps his
  bonus.**
  MAGNUS's `.spc` went in holding effect ids 90, 97, 26 and 47 -- the four
  `goldbox.dos.RACE_COMBAT_EFFECTS` writes for a dwarf -- and the engine's own
  save holds all four, in the same order, with only the chain pointers moved.
  So the arrangement a converted Amiga dwarf ends in is the one `#191 (A
  converted dwarf loses his constitution bonus to saving throws)` established
  is right on DOS: the plain class row in the record, the
  constitution bonus in the effect records beside it. CONFIRMED that the four
  records survive; PROBABLE that the bonus is therefore intact, because no
  dwarf the Amiga made itself exists to compare with and Pool of Radiance's
  sheet does not print saving throws.

`party_order` is the one field this run adds to the derived list. The C64
record has no marching order to convert -- `goldbox/layout.py`'s `0x10D` entry
says the C64's order is the slot arrangement rather than a byte -- so the
writer emits zero for everybody, and the engine numbered them 0 to 5 in the
order the saved game's character table names them. The panel drew them in the
right order before the save as well, so nothing was ever wrong on screen.

## 5. A name loses its space

**CONFIRMED, two characters from two source ports.** `LADY KATHERINE` came
back from the engine as `LADYKATHERINE` and `THRENDER GRONE` as
`THRENDERGRONE`, each three NULs longer. Loading the engine's own slot draws
the stripped name on the party panel, so it is what a player sees. It is not a
truncation -- 14 characters became 13, not the first 13 of 14 -- and the field
takes a space happily otherwise, since Curse of the Azure Bonds' own pregens
hold `BJORN DARKSTONE` and `TEUT HALF-ELFIN` at the same offset of the same
record. The DOS engine keeps the space: `por-item-granted`'s engine-written
`CHRDATD1.SAV` holds a count byte of `0x0E` and then `THRENDER GRONE`.

`#308 (Does Amiga Pool of Radiance drop the space out of a character's name
when it saves?)` carries the two experiments that would name the rule. Amiga
Pool of Radiance ships no character with a space in its name, so nothing on
the disk says whether the engine does this to a name it made itself.

## 6. What this run did not establish

* **Whether the Amiga applies a dwarf's constitution bonus at the moment of a
  saving throw**, which is what would turn §4's PROBABLE into a measurement.
  The sheet does not print saving throws and the run took no fight.
* **What draws the price column** into the item display line. It is absent
  from every node the engine wrote here and present in the game's own.
* **A quantity or an unreadied item on the ITEMS screen.** MELCAR's ` No   60
  Darts ` node was never opened, because the character-sheet screen offers no
  way to move to another party member -- `VIEW` re-draws the same sheet, the
  arrow keys do nothing, and camp's `VIEW` enters on the first character too.
  Whatever selects a party member on this port has not been found, and it is
  what a run wanting a second character's sheet needs.
* **Any Amiga title but Pool of Radiance.** Nothing here is evidence about
  Curse or Silver Blades, whose writers `docs/167-amiga-neutral-and-party-
  writing.md` describes and which have still never been loaded in their own
  game.

## 7. Reproducing it

`tools/toamigapor.py` builds the disk and `tools/amigadrive.py` types at the
game; `tools/porslotdiff.py` reads the answer back out. The whole route from a
cold VM is about four minutes of waiting and twenty keystrokes:

```sh
export SSH_ASKPASS_REQUIRE=never
winvm acquire wish105
ps='powershell -NoProfile -ExecutionPolicy Bypass -File C:\Amiga\winuae.ps1'
winvm ssh "$ps claim -Holder por105"
tools/toamigapor.py work/por1.adf --to B --out work/por1-B.adf \
    --c64 ~/wish-specimens/por-c64/WISH-SPEC-por-party-twin-pair.d64
winvm scp work/por1-B.adf 'donald@192.168.123.50:C:/Amiga/Disks/por/x.adf'
winvm ssh "$ps start -Holder por105 -log -f C:\Amiga\configs\goldbox-a500.uae \
    -s floppy0=C:\Amiga\Disks\por\x.adf -s floppy1=C:\Amiga\Disks\por\por2.adf"
# RET at the code wheel, RET at the title, then:
tools/amigadrive.py --holder por105 keys L S A V E SLASH RET B
tools/amigadrive.py --holder por105 keys V I      # sheet, then ITEMS
tools/amigadrive.py --holder por105 shot work/items.png
```

Three things cost time on the way and are worth knowing.

* **A key pressed while the disk is loading is swallowed with no sign.** Take a
  screenshot after every step rather than batching a sequence across a load.
  The three loads that need waiting out are the code wheel to the title
  (about 55 seconds), the title to the menu (about 45) and the slot to the
  adventure screen (about 25).
* **`E` is `EXIT` on the sheet and the ITEMS screen and `ENCAMP` on the
  adventure screen**, so three `E`s in a row walk out of ITEMS and into camp.
* **Delete the images you copied into the guest and release both leases.**
  `winuae.ps1 release -Holder <id>` gives back the lane and `winvm release
  <tag>` shuts the VM down when the last lease goes; a lease left held is a
  lease nobody else can take.
