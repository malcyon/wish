# How many items a character can carry, per port and per title

Asked under `#52 (File ▸ Import and File ▸ Export for every direction the
library supports)`, whose plan lists "seventeen items" among the cases a
conversion might have to refuse. It cannot arise: **Pool of Radiance, Curse
of the Azure Bonds and Secret of the Silver Blades refuse a character a
seventeenth item, on DOS and on the Amiga alike, which is the same sixteen
the C64 record has slots for.** Pools of Darkness, which no C64 machine ever
ran, has one exemption and is the last section here.

| port | title | ceiling | grade | routine | the compare |
|---|---|---|---|---|---|
| DOS | Pool of Radiance | 16 | CONFIRMED | `GAME.OVR` `0x023795` | `0x0237AD` |
| DOS | Curse of the Azure Bonds | 16 | CONFIRMED | `GAME.OVR` `0x02A2A8` | `0x02A2C0` |
| DOS | Secret of the Silver Blades | 16 | CONFIRMED | `GAME.OVR` `0x02AA8B` | `0x02AAA3` |
| DOS | Pools of Darkness | 16, **with one exemption** | CONFIRMED | `GAME.OVR` `0x026661` | `0x02679A` |
| Amiga | Pool of Radiance | 16 | CONFIRMED | `/program` `0x01CB64` | `0x01CB7A` |
| Amiga | Curse of the Azure Bonds | 16 | CONFIRMED | `/Curse` `0x023774` | `0x023788` |
| Amiga | Secret of the Silver Blades | 16 | CONFIRMED | `/Secret` `0x024B3C` | `0x024B50` |
| Amiga | Pools of Darkness | 16, **with one exemption** | PROBABLE | `Pools of Darkness` `0x0239EE` | `0x023AB0` |

Every grade above is CONFIRMED except the last, and the difference is what
the displacement is known to be rather than what the code does. Amiga Pools
of Darkness's `0x0C7` is the offset the one-`0x0F`-plus-four-`0x10`
signature lands on, and no shape in `goldbox/amiga.py` covers that title's
record, so calling it `item_count` is an inference from the signature and
from the routine's shape. The other seven compares sit at exactly the
`item_count` offset `goldbox/dos_layout.py` or `goldbox/amiga.py` already
gives that title.

The C64 needs no such routine: its record **has** sixteen item slots of
sixteen bytes and no seventeenth to fill, which is
`goldbox/c64_codec.py`'s `ITEM_SLOTS` and `ITEM_SIZE` inside the 580-byte
record (CONFIRMED from the layout). Whether the C64 engine also refuses in
words has not been read, and it cannot change the number.

Nothing here needed WinUAE: `tools/amiga68k.py` reads the Amiga executables
off the disk images, and `tools/dosovrmap.py` resolves the DOS overlays.

## The routine

One function decides it, and it is the same function in all eight binaries --
same order, same constants, only the record offsets and the call targets
differ. Pool of Radiance's DOS copy:

```
023795  push bp; mov bp,sp; sub sp,4
02379b  push [bp+0xc]; push [bp+0xa]      ; the character, far
0237a1  lcall 0xba:0x0bb8                 ; recount from the item chain
0237a6  mov byte [bp-2], 0                ; refuse = false
0237aa  les di, [bp+0xa]
0237ad  cmp byte ptr es:[di+0xc7], 0x0f   ; item_count > 15?
0237b3  jbe +4
0237b5  mov byte [bp-2], 1                ; refuse = true
0237b9  ...                               ; weight x quantity vs capacity + 1500
02380a  mov al, [bp-2]; retf 8
```

and Curse's Amiga copy, which differs only in the shape of the machine:

```
023774  movem.l d2-d6/a2-a3/a6, -(a7)
023778  movea.l $24(a7), a3               ; the character
02377c  movea.l $28(a7), a6               ; the item
023782  jsr -$7db8(a4)      -> 01a45c     ; recount from the item chain
023786  moveq #0, d4
023788  cmpi.b #$f, $150(a3)              ; item_count > 15?
023790  bls.b +2
023792  moveq #1, d4
0237ac  addi.w #$5dc, d0                  ; capacity + 1500
```

Three things about it:

* **It recounts first**, so the byte it compares is the length of the chain at
  that instant rather than a stored number an editor could have lied about.
  The recount is `START.EXE` image `0x178D`-`0x17CC` on DOS Pool of Radiance
  and `GAME.OVR` `0x0382FA`/`0x038339` in Curse -- `item_count` zeroed, then
  incremented once per node while `encumbrance` accumulates.
* **The compare displacement is `item_count`'s offset for that title**:
  `0x0C7`, `0x14C`, `0x160`, `0x1A6` on DOS, exactly
  `goldbox/dos_layout.py`'s; `0x0C9`, `0x150`, `0x0FC`, `0x0C7` on the Amiga,
  the first three exactly `goldbox/amiga.py`'s shift maps. Amiga Pools of
  Darkness's `0x0C7` is the exception graded above.
* **One flag, two tests.** The same boolean carries "sixteen already" and
  "`encumbrance + weight x quantity` above carrying capacity plus 1500", so
  the game's refusal does not say which stopped it.

## Pools of Darkness relaxes it, and only Pools of Darkness

Both ports of Pools of Darkness walk the character's chain *before* the
compare, looking for an item already held whose bytes `0x3D` and `0x3E` --
effect and power -- match the incoming one's, and skip the count test when
they find one:

```
02679a  cmp byte ptr es:[di+0x1a6], 0x0f
0267a0  jbe +10
0267a2  cmp byte ptr [bp-9], 0            ; a matching item already carried?
0267a6  jne +4
0267a8  mov byte [bp-2], 1
```

The three earlier titles have no such branch. **SPECULATIVE: whether this can
put a seventeenth *record* on a Pools of Darkness character, or only lets a
full one top up a stack it already has.** What would settle it: give a Pools
of Darkness character sixteen items of which one is a quiver of arrows, offer
it more arrows, and read the `.THG` file's length afterwards -- 17 x 63 says
a seventeenth record, 16 x 63 with a raised quantity says a merge. Nothing in
this project reads Pools of Darkness saved games yet, so it has not been run.

## What the player sees at the limit

**The word `Overloaded`, and nothing else.** Watched in the running game:
`tools/dositemcap.py` had `WISHFTR` offer a sling by `TRADE` to a character
holding sixteen, and 11 of 300 rapid captures caught `OVERLOADED` across the
bottom bar before the screen redrew. The string is `0A 'Overloaded'` at
`GAME.OVR` `0x022763` (Pool of Radiance), `0x02916E` (Curse) and `0x028FAD`
(Silver Blades), each sitting immediately after `Trade with Whom?`; the
take-and-buy path uses `0A 'OverLoaded'`, capital L, at `0x006F02`, `0x007A3C`
and `0x008838`.

**There is no message anywhere in any of the three files saying a character is
carrying too many items.** The same word appears when the character is merely
too heavy.

**Two commands disappear instead of refusing.**

* `HALVE` is left out of the item bar at sixteen -- `cmp ..., 0x10` then `jae`
  past the `pstrcat` of `" Halve"` at `GAME.OVR` `0x0220AC`. Confirmed on
  screen: a character holding sixteen slings shows
  `READY USE TRADE DROP JOIN EXIT`, and after one `DROP` the same character at
  fifteen shows `READY USE TRADE DROP HALVE JOIN EXIT`.
* Appraising a **gem or a jewel** offers `Sell Keep` under sixteen and only
  `Sell` at sixteen (`0x0269DE` and `0x026D31`; the two strings are at
  `0x026609` and `0x02660E`). A full character can sell a gem and cannot keep
  it.

## The measurement in the running game

`tools/dositemcap.py`, three boots on 2026-09-05, on
`WISH-SPEC-por-party-l1-intown` -- six characters this project rolled from
creation, saved by the game's own `SAVE CURRENT GAME`. The item lists are
**our input**: sixteen copies of the game's own `Sling` template
(`ITEM1.DAX` block 53, entry 12) written into `.ITM` files with `item_count`
and `encumbrance` to match. What the engine wrote back is the measurement.

**The boundary, one action apart, one character.** `WISHFTR` offered a sling
to `WISHCLE`, who held fifteen: accepted. `WISHFTR` then offered the identical
sling to `WISHMAG`, who held sixteen: refused. The engine's own save to a
fresh slot:

| character | before | after |
|---|---|---|
| WISHFTR | 2 items, 126-byte `.ITM`, encumbrance 144 | 1 item, 63 bytes, 142 |
| WISHCLE | 15 items, 945 bytes, encumbrance 140 | **16 items**, 1008 bytes, 142 |
| WISHMAG | 16 items, 1008 bytes, encumbrance 102 | **16 items**, 1008 bytes, 102 |

**Weight is excluded, not assumed away.** The character that refused was
carrying *less* than the one that accepted -- 102 against 140 -- and every
item in the experiment weighs two tenths of a pound against a limit no
character is within 1500 units of. `WISH-SPEC-por-item-cap-16` is the save.

## The ceiling is on acquisition only

**A `.ITM` file longer than sixteen records loads, draws and saves back
intact.** A character given twenty slings and `item_count` 20 came up with
encumbrance 180 -- 140 gold plus 20 x 2 tenths, the engine's own recount --
drew them across two pages of an item screen that grew a `NEXT`/`PREV` pair
the sixteen-item list does not have, and the game's own save wrote 1260 bytes
= 20 x 63 with `item_count` still 20. `WISH-SPEC-por-item-twenty` is that
save.

So the loaders are the exception, which the twenty-item load confirms
directly. The six places that build a character's chain from a file allocate
a node each and none of them has a compare against sixteen in front of it
(Pool of Radiance `GAME.OVR` `0x0013AC`/`0x001404`, `0x0090E3`/`0x009138`,
`0x01ECA8`, `0x01F1A3`) -- PROBABLE from the code on its own, since an
absent instruction is weaker evidence than a present one, and CONFIRMED by
the twenty that loaded. **Nothing in the shipped game can write such a
file** -- but a character editor can, and
`.claude/rules/testing.md` already treats a save off a player's disk as
untrusted for exactly this class of reason.

## What it settles for a conversion

**A DOS or Amiga save a player made cannot overflow the C64's sixteen slots**,
so decision 13 of `#52 (File ▸ Import and File ▸ Export for every direction
the library supports)` has nothing to decide about items: the case is
unreachable from a saved game the game itself wrote. What remains is our own
input validation -- a `.ITM` an editor lengthened past sixteen is the only way
a seventeenth item reaches the converter, and
`goldbox/c64_codec.py` already reports the overflow rather than writing past
the sixteenth slot.

## Where this came from

Tools: `tools/dositemcap.py` (the running-game half),
`tools/dosovrmap.py` (DOS overlay units and disassembly),
`tools/amiga68k.py` (the Amiga executables). Specimens:
`WISH-SPEC-por-party-l1-intown` as the base,
`WISH-SPEC-por-item-cap-16` and `WISH-SPEC-por-item-twenty` as the results.
