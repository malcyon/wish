# Two Rings of Fire Resistance, and which one Wish handed out

`#285 (The C64's Ring of Fire Resistance grants nothing, and Wish should repair
it on conversion and on an editor save)` was filed against the game. The game is
mostly innocent: **Pool of Radiance's C64 disks carry five Ring of Fire
Resistance records and four of them work.** The reading that said otherwise was
ours -- `goldbox.items.load_item_templates` kept the first record it met for a
printed name, and the one flattened copy sits on a side that sorts first.

Grades follow `docs/50-experiments.md`'s scale.

## The five records

Every 16-byte record in every item list on all eight sides, plus a raw search of
the four identifying bytes `45 CD A7 42` through each disk image. **CONFIRMED**;
the search finds no sixth copy anywhere on the eight sides.

| where | `+14` | `+15` | readied | name words hidden |
|---|---|---|---|---|
| `POOL3` `ITEMFILE17` record 3 | 0 | `$00` | no | none |
| `POOL4` `ITEMFILE1D` record 2 | **61** | **`$81`** | no | two |
| `POOL5` `MON56` +306 | **61** | **`$81`** | yes | two |
| `POOL6` `MON32` +354 | **61** | **`$81`** | yes | two |
| `POOL6` `MON56` +306 | **61** | **`$81`** | yes | two |

`+15` bit 7 is the whole of the gate: `CAMP $10B5` reads it and only then
dispatches through `ECL65`'s power table to the handler that copies `+14` into a
free trait slot (`docs/171-c64-trait-slots.md`). Four of the five have it.

**And `$81` reaches the same handler as `$80`.** `ECL65`'s table at `$9AD5` is
24 power codes -- `04 26 0c 0e 16 22 32 80 81 82 83 84 85 86 87 88 8a 8b 07 2b
2c 39 3e 0f` -- followed by 24 handler low bytes and 24 high bytes. Aligning the
low table one byte past the code table's end reproduces four facts established
separately (`$80`, `$85` and `$88` to `$ADD4`, `$83` to `$AE2D`, `$84` to the
alignment-lock handler), and on that alignment `$81` is `$ADD4` too --
the grant. **CONFIRMED from the table, cross-checked four ways.**

## The flattened one grants nothing, watched

`work/issue285/ring-shipped/`. `ITEMFILE17`'s record staged readied into
ROLAND's inventory on a copy of a save, booted, and READY pressed three times
from ENCAMP > VIEW > ITEMS with the whole 256-byte character record and the
768 bytes of the effect arrays read before and after each press:

| press | bytes that changed in the record | in the effect arrays | trait slots after |
|---|---|---|---|
| 1 | none | none | `[0] * 10` |
| 2 | none | none | `[0] * 10` |
| 3 | none | none | `[0] * 10` |

**CONFIRMED.**

## The working one grants 61, and takes it back, watched

`work/issue285/ring-81/` and `work/issue285/ring-81c/`, two runs agreeing byte
for byte. The same drive with `ITEMFILE1D`'s record staged in the same slot of
the same save -- one item differing from the control by two bytes:

| press | the ring | bytes that changed in the record | trait slots after |
|---|---|---|---|
| 1 | readied to un-readied | none | `[0] * 10` |
| 2 | un-readied to readied | **one**: `$4FB6`, slot 9 of ROLAND's block, `00` to `3D` | `[0]*9 + [61]` |
| 3 | readied to un-readied | **one**: `$4FB6`, `3D` to `00` | `[0] * 10` |

Nothing in the 768 bytes of the effect arrays moved on any press, so the grant
is the trait slot and nothing else. The first press had nothing to revoke,
because load does not derive a slot from a readied item.

The second run also caught the stores themselves. `tr exec` on `$AE0D`, the
grant's `STA`, and `$AE27`, the revoke's, printed

```
ready1: grant at $AE0D A=61 X=9
ready2: revoke at $AE27 A=0 X=9
```

-- the effect id in A and the slot index in X, which is the same slot the
record diff names.

**CONFIRMED**, and it settles three things at once: `$81` reaches `$ADD4` in
the running machine and not only in `ECL65`'s table; the grant is one byte;
and `SPELLE04 $AE13` takes the id back out when the ring comes off, which
`#285 (The C64's Ring of Fire Resistance grants nothing, and Wish should
repair it on conversion and on an editor save)` had as PROBABLE with nobody
having watched it.

With `#252 (Does a C64 trait slot apply an item-granted effect id, or only the
ones its own READY routine wrote?)`, which watched a fire spell's damage path
ask the slots about 61 and dispatch handler `$A9EE` on a match, the whole chain
from the ring's bytes to the handler is now CONFIRMED end to end. What the
handler then subtracts is the one link still unmeasured.

## The working one is DOS's, byte for byte

`ITEMFILE1D` on POOL4 is DOS `ITEM4.DAX` block 29 record for record -- Plate
Mail +2, Long Sword +2, this ring, Shield +1 and four two-spell clerical
scrolls. Two independent DOS installs (`/home/donald/dos_por_play/` and the copy
in the Forgotten Realms archives) have byte-identical `ITEM4.DAX`.

Stronger still: `tools.dosbox.item_to_c64` applied to the DOS ring produces
`ITEMFILE1D`'s sixteen bytes exactly, and the count of C64 records the DOS
projection reproduces byte for byte rose from 157 to 159 when the reader started
preferring the working copy (`tests/test_dosbox.py`). **CONFIRMED.**

## The port comparison, in full

The C64's `ITEMFILE<hh>` suffix is the DOS `ITEM*.DAX` block number in hex.
On that mapping 39 of the C64's 43 item lists hold exactly the same (type, name
words, effect, power) set as their DOS block; the four that do not are
`ITEMFILE17` (DOS has no block 23 at all), `ITEMFILE19`, `ITEMFILE1E` and
`ITEMFILE33`.

Across all 163 C64 templates against all 352 DOS item records, matched by the
four identifying bytes, 162 match a DOS record and exactly **two** disagree
about whether the item grants anything:

| item | C64 `+14`/`+15` | DOS effect/power |
|---|---|---|
| RING OF FIRE RESISTANCE | 0 / `$00` in `ITEMFILE17` | 61 / `$81` |
| LONG SWORD +2 | 0 / `$00` in `ITEMFILE17` | 240 / `$84` |

Both live in `ITEMFILE17`, which holds four items -- Long Sword +2, Shield +1,
Plate Mail +2, Ring of Fire Resistance -- all with their special bytes zeroed
and all fully identified. **`$84` is the alignment lock**, which takes hit
points off a character of the wrong alignment, so making the sword match its DOS
twin would take something away from a player rather than give it. That is the
answer to "is this one item or a class": it is one, and the only other candidate
is a curse.

## Can a player hold the flattened ring?

`TREASURE`'s last operand names the item file
(`docs/177-a-load-that-goes-wrong.md`). Across the thirty area scripts there are
77 `TREASURE` statements resolving to 35 distinct files, and **`ITEMFILE17` is
not one of them**; the ring a player is given comes from `ECL0A $AD17`, operand
29, which is `ITEMFILE1D`. Three `TREASURE` statements take the number from a
variable (`ECL08 $9F1A`, `ECL10 $AE21`, `ECL18 $AA34`), and no literal `23` or
`151` is stored into any of those variables anywhere in the thirty scripts.

**PROBABLE** that `ITEMFILE17` is unreachable. What would refute it: an `OP$2A`
table read filling one of those three variables with 23 -- the tables were not
enumerated -- or an item list loaded by something other than `TREASURE`. Eight
of the 43 item lists are named by no literal, so being unnamed is not by itself
unusual.

## What Wish did wrong, and what it does now

`load_item_templates` walked the sides in sorted order and did
`out.setdefault(name, raw)`, so POOL3's flattened ring beat POOL4's working one.
Every reading of "the shipped template" went through that function, and so did
the editor's Add Item: **a player who gave a character a Ring of Fire Resistance
in Wish got one that does nothing in the game.**

Two changes:

* `load_item_templates` prefers a record that grants an effect where two records
  print the same name. Nineteen of the 163 names have more than one distinct
  record and only the two above disagree about granting, so the rule decides two
  names and moves nothing else.
* `repair_ring_of_fire_resistance` writes `61` and `$81` -- `ITEMFILE1D`'s own
  bytes rather than a value of ours -- and still fires only when `+15` bit 7 is
  clear. What it is for now is a save that already holds a ring an older Wish
  handed out.

**A DOS-to-C64 conversion needs no repair at all**: the DOS ring's own bytes are
already `61`/`$81` and `item_to_c64` copies them across.

## What is not settled

* **How much damage the effect actually takes off.** `docs/171-c64-trait-slots.md`
  names the Fireball experiment -- spell 47, 5d6 at level 5, at a ring-wearer
  against a control -- and it has not been run. Burning Hands at level 1 cannot
  show it: `$ADB0` never takes the damage below the dice count.
* **Nothing, on the grant.** Six drives were started and three of them failed
  at `begin_adventuring` before reaching the world, across both `$80` and `$81`
  stagings and on three different pool slots -- the boot being flaky rather
  than anything about the item, which a first guess ("the two `$80` runs
  failed") would have got wrong. Of the three that got in, one is the control
  and two are the working ring, and the two agree byte for byte.
* **What `+4 = 3` on the working ring is for.** Its type (69) has bit 7 of the
  type table's protection byte clear, where RING OF PROTECTION's type (93) has
  it set, so it is not an armour-class bonus. UNKNOWN.

## Corrections this makes to the knowledge base

`docs/125-bug-notes.md` U4 and `docs/171-c64-trait-slots.md` both describe the
flattened record as "the shipped template" and conclude the ring is inert on the
C64. That is true of one of five records. Both have been narrowed to point here.
