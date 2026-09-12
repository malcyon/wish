# The byte beside an Amiga effect id, and why nothing means anything by it

`#387 (The Amiga Silver Blades effect node keeps a byte DOS has not got, and
a converted character loses it)`. An Amiga *Curse of the Azure Bonds* or
*Secret of the Silver Blades* effect node is ten bytes where DOS's `.FX` or
`.SFX` record is nine, and the extra one sits at offset 1, between the effect
id and the duration word. Three of the five nodes in the party SSI shipped on
Silver Blades disk 1 hold `0x2E`, `0x6D` and `0x64` there; every other node
anybody has read holds zero.

**CONFIRMED — no instruction in either executable writes it, and none reads
it.** It is the alignment pad a C compiler leaves in front of the `UWORD`
duration, in memory the game allocates without `MEMF_CLEAR` and never
clears. The three values are whatever the Amiga's public memory held under
the first three slots of the pool during the session SSI saved that party
in, copied faithfully from file to file ever since.

So the byte carries nothing a player could lose, `goldbox.amiga_later.write_later`
may write anything, and zero is proven in the running game.

## 1. The node

| offset | width | what | how it is known |
|---|---|---|---|
| `0x0` | 1 | effect id | the constructor's first store; the effects display indexes a `char *` table with it (`/Secret 0x00FCC`) |
| **`0x1`** | 1 | **nothing** | §2 to §4 below |
| `0x2` | 2 | duration, big-endian | the constructor's `move.w`; the routine at `/Secret 0x02B2E` tests it, compares it against a count and subtracts it |
| `0x4` | 1 | two nibbles, `0xFF` for none | `/Secret 0x3528C` tests it against `0xFF`, `0x35296` takes `andi.b #$f` and `0x354E4` takes `divs.w #$10` |
| `0x5` | 1 | expiry-action flag | `/Secret 0x11E78` `tst.b $5(a2)`, and only then dispatches the per-effect handler |
| `0x6` | 4 | `next`, a live heap address | cleared by the constructor, walked everywhere |

`goldbox/amiga_por.py`'s `amiga_por_effect_to_dos` maps the other nine bytes onto
DOS's, and the DOS twins of the three characters carrying the odd values read
`08 00 00 FF 00`, `69 00 00 FF 00` and `2F 00 00 FF 00` — zero where the
Amiga has `0x2E`, `0x6D` and `0x64`, three of three.

## 2. Every node is a slot in one pool, and the pool is never cleared

Both titles keep effect nodes in a **fixed-size pool**: a descriptor in the
SAS/Lattice small-data segment holding the slot count, the element size, the
base pointer and then an allocation bitmap. The allocator finds the first
byte of the bitmap that is not `0xFF`, the first clear bit in it, sets that
bit and hands back `base + slot * size`. It does not touch the slot's
contents.

| | Curse (`/Curse`) | Silver Blades (`/Secret`) |
|---|---|---|
| pool descriptor | `g5b1e` | `g7618` |
| element size, written at set-up | `0x0A` at `0x1C4BE` | `0x0A` at `0x1BFA0` |
| allocator | `0x02C5A0` | `0x02F30E` |
| free | `0x02C64C` | `0x02F39A` |
| the pool's own memory | `0x040BCC` | `0x04573C` |

The last row is the finding under the finding. Both are the same C runtime
routine compiled twice: `AvailMem(MEMF_PUBLIC|MEMF_LARGEST)` for the check,
then

```
pea.l   $1.w                    ; requirements = MEMF_PUBLIC
move.l  d0, -(a7)               ; size + 8
jsr     <AllocMem>              ; exec -198, through SysBase
```

`MEMF_CLEAR` is `0x10000` and is not in that `1`. So the pool's memory
arrives holding whatever was in the machine, and nothing in either game
writes offset 1 of a slot afterwards.

The base pointer is written once at set-up and read only by the allocator and
the free routine — `g761c` has exactly one reference in `/Secret` and it is
the store. No code reaches into the pool except through a node pointer the
allocator handed out.

## 3. Every writer, counted

A pool descriptor is named by exactly one instruction per allocation or free,
so the references to it are the complete list of places a node pointer can be
born. `tools/amiganodefields.py pool` prints them: **eleven in `/Secret`, ten
in `/Curse`**, every one asking for `#$a` = 10 bytes, one of each being the
descriptor's own set-up.

| `/Secret` | what it does | what it writes |
|---|---|---|
| `0x11EC0`, `0x127A8`, `0x1BD00` | free | — |
| `0x12DB8` | **the constructor** | offsets 0, 2-3, 4, 5, 6-9 |
| `0x1E38C`, `0x1E3BE` | party-add | all ten bytes, two `move.l` and a `move.w` |
| `0x26AE2`, `0x26B30` | the saved-game loader | all ten bytes, read from the file |
| `0x2753A`, `0x275CA` | the `MON<n>SPC` unpacker | offsets 0, 2-3, 4-5, 6-9 |
| `0x1BF9C` | set-up | — |

The constructor is `/Curse 0x00F176` and `/Secret 0x012DAC`, the same routine
compiled twice. It takes five arguments — character, id, duration, and two
bytes — appends the node to the tail of the chain, and ends with five stores:

```
clr.l   $6(a0)              ; next
move.b  $d(a5), (a0)        ; id
move.w  $e(a5), $2(a0)      ; duration
move.b  $13(a5), $5(a0)
move.b  $11(a5), $4(a0)
```

There is no sixth argument and no store at offset 1. It has **33 callers** in
`/Secret`, which is every way an effect comes into being in play.

The `MON<n>SPC` unpacker expands the 9-byte packed DOS record the port kept
on disk: one byte to offset 0, two to offsets 2-3 and then byte-swapped, two
to offsets 4-5, `clr.l` at 6, stride 9. Offset 1 is skipped there too — which
is the whole reason the tenth byte exists.

## 4. Every reader, counted

`tools/amiganodefields.py fields` walks forward from **every** load of the
record's chain-head field, marks the address registers that hold a node,
runs to a fixed point, and prints each displacement anything touches through
one. It over-approximates deliberately: it ignores control flow and keeps a
register marked until something overwrites it, so a displacement it does
*not* report is one no instruction downstream of a chain-head load can reach.

| | `/Curse` | `/Secret` |
|---|---|---|
| chain-head loads | 42 | 39 |
| offset 0 | read, 11 sites | read, 15 sites |
| **offset 1** | **0 sites** | **0 sites** |
| offset 2 | read 3, written 1 | read 5, written 1 |
| offset 4 | read 4 | read 4 |
| offset 6 | read 21, written 5 | read 25, written 6 |

Three things the census does not cover, chased by hand:

* **A routine handed a node as an argument.** The removal routine
  (`/Secret 0x11E46`) reads offsets 0, 5 and 6 and nothing else.
* **The per-effect expiry handlers.** `/Secret 0x120DC` dispatches through a
  table of 112 slots filled at start-up from `0x16BD6` to `0x16F52`, passing
  the node itself to each — the shape of reference the earlier search could
  not see. **0 of the 97 distinct handlers contains a `$1(aN)` access.**
* **Anything called while a node pointer was live**: 24 distinct callees
  across 51 call sites, **0 of 24** containing a `$1(aN)` access.
* **Indexed addressing**, `(aN, dM.w)`, which would reach offset 1 with a
  register holding 1 and name no displacement at all: **0 instructions in
  either binary** index through a register the walk marks as holding a node.

For completeness: the whole 312KB `/Secret` code hunk contains **81**
candidate accesses at a positive displacement of 1 on `a0`-`a4` or `a6`,
decoded at every word alignment, and none of them is on a
register that ever held a node. That grep is what the first pass at `#387 (The Amiga Silver Blades effect node keeps a byte DOS has not got, and a converted character loses it)`
ran, and finding nothing in it proves nothing on its own; what settles the
question is that there is no writer.

## 5. What the specimens look like, and why they look like memory

Each node's own heap address is in the saved game — the record's chain head,
then each node's `next` — so the pool slot each node sat in can be read off
the file. In every Silver Blades saved game the five nodes are five
consecutive ten-byte slots, and:

| pool slot | character | effect id | offset 1 |
|---|---|---|---|
| 0 | Guy de Valois | `0x08` | `0x2E` |
| 1 | PAINE | `0x69` | `0x6D` |
| 2 | MALACHITE | `0x2F` | `0x64` |
| 3 | MALACHITE | `0x1A` | `0x00` |
| 4 | MALACHITE | `0x61` | `0x00` |

The non-zero bytes are the first three slots of the pool and nothing else,
in party order, whichever characters and whichever effect ids those are.
Stale memory under the first 25 bytes of a fresh block looks exactly like
that; a field with a meaning does not stop at the third node in party order.
Corroborating it: `0x1A` and `0x61` carry zero as MALACHITE's fourth and
fifth-slot nodes here, and Curse's HOLLAND and SUNDRA carry the same two ids
with zero as well.

The pool base moves between sessions — `0xC875B8` in the shipped save,
`0xC6E880` and `0xC6E858` in ours — and the values travel with the data
regardless, because a load copies all ten bytes.

**The corpus: 77 nodes across 13 saved games**, being the two shipped on the
game disks (read twice, from two copies of each disk) and nine
engine-written saves in `$WISH_SPECIMENS`. 24 of the 77 are non-zero, which
is the same three bytes in each of the eight saved games of a party the
engine itself made. The other two Silver Blades saves are §6's converted
party. All 27 Curse nodes read zero.

## 6. The control, from the running game

`#384 (Write an Amiga Curse or Silver Blades character, so a C64 or DOS party
has an Amiga to arrive on)` put a converted party — the same six people, from
the C64 save the C64 engine itself wrote — in front of Amiga Silver Blades
under WinUAE on 2026-09-07, with `goldbox.amiga_later.write_later`'s zero at offset
1 of all five nodes. The engine loaded it, drew an ITEMS screen, ran the
opening scene, camped, and wrote the party back twice
(`WISH-SPEC-ssb-amiga-converted-menu-resave` and
`WISH-SPEC-ssb-amiga-converted-items-drawn`). **All five nodes came back with
zero still there**, in the same pool slots 0 to 4 that hold `0x2E`, `0x6D`
and `0x64` in the shipped party.

So the reading of the code arrives from the other side as well: a byte the
engine never writes is a byte the engine does not miss.

## 7. What it means for the conversion

`.claude/rules/conversions.md` allows three reasons for not converting a
field, the third being "we do not understand the bytes well enough to write
them", which is a defect with a settling experiment rather than an exemption.
This was that experiment, and it comes out the other way: there is nothing to
convert.

Recommended, and **not done here** — `goldbox/amiga_later.py` belongs to another
agent:

* `AMIGA_LATER_EFFECT_UNKNOWN`'s comment says the value is UNKNOWN and names
  the two experiments that would settle it. Both are done; it should say
  what §2 to §4 say, and that writing zero is right.
* `LATER_EFFECT_WRITE_UNSOURCED[0]`'s text says writing zero is "wrong for 3
  of the 5 Silver Blades nodes anybody has ever seen". It is not wrong; it
  is a byte nothing computes and nothing consults. The entry stays — the
  byte genuinely has no neutral source — but as a pad rather than a loss.
* `LATER_EFFECT_UNKNOWN_PLAYER_TEXT` is a line in the drop pane telling the
  player that "nobody has worked out what it holds, so it is left empty".
  Nobody loses anything, so there is nothing to tell them, and it should go.

## 8. Negative results

* **It is not a copy of anything in the character's record.** Recorded on
  `#387 (The Amiga Silver Blades effect node keeps a byte DOS has not got, and a converted character loses it)` before this work and re-checked: `0x2E` appears at no offset of Guy
  de Valois' 340 bytes, `0x6D` at none of PAINE's, `0x64` at none of
  MALACHITE's.
* **It is not an item field.** All three characters carry no items at all in
  the shipped save, so the values cannot be an item id, a slot or a charge
  count.
* **Stability across a resave says nothing**, and neither does stability
  across a walk or a camp: the party-add routine and the loader copy all ten
  bytes without looking at any.
* **Grepping the binary for `$1(aN)` answers nothing either way.** 81 sites
  in `/Secret`, 0 of them a node — a null result the first pass at `#387 (The Amiga Silver Blades effect node keeps a byte DOS has not got, and a converted character loses it)`
  already had, and which is not evidence on its own.

## 9. Re-running it

```sh
tools/amiganodefields.py --adf <silver-blades-1.adf> --exe /Secret \
    pool --global 7618
tools/amiganodefields.py --adf <silver-blades-1.adf> --exe /Secret \
    fields --chain 96 --size 10
tools/amiganodefields.py --adf <curse-1.adf> --exe /Curse \
    fields --chain f2 --size 10
```

`tests/test_amiganodefields.py` runs all of it, plus the tool's own logic
against a program built in the test so it can be shown to fail, plus the
specimen shape in §5 and the control in §6. 14 tests, and they skip rather
than fail on a machine with no Amiga disks.
