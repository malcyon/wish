# The DOS experience award, and the Silver Blades scroll bundle

Two runs of bytes `goldbox/dos_layout.py` called gaps, named from the six
shipped DOS engines rather than from a saved game.
`#254 (Two DOS gaps the Amiga port gives a shape to: a 16-bit field in
gap_13c, and a pointer at the end of the Silver Blades item)` asked for both;
the Amiga port gave each a shape and the DOS code settles them.
`tools/dosxpaward.py` and `tools/dosscrollbundle.py` are the instruments, and
`tests/test_dosxpaward.py` and `tests/test_dosscrollbundle.py` pin what they
found.

Neither needed the Curse shopping trip the issue named as its dependency:
`#113 (Play DOS Curse far enough to save a party with items)` closed long ago,
and a finding taken from the engine's own instructions cannot be poisoned by
an edited save.

## 1. The run before the portrait is what killing a creature is worth

| title | record | base award, `u16le` | per hit point, `u8` | called |
|---|---|---|---|---|
| Pool of Radiance | 285 | `0x0B8` | `0x0BA` | `gap_0b8`, 3 bytes |
| Curse of the Azure Bonds | 422 | `0x13C` | `0x13E` | `gap_13c`, 3 bytes |
| Gateway to the Savage Frontier | 422 | `0x13C` | `0x13E` | `gap_13c`, 3 bytes |
| Secret of the Silver Blades | 439 | `0x14E` | `0x150` | `gap_14e`, 3 bytes |
| Pools of Darkness | 510 | `0x198` | none | `gap_198`, 2 bytes |
| Treasures of the Savage Frontier | 510 | `0x198` | none | `gap_198`, 2 bytes |

**CONFIRMED**, on four routes that agree and one measurement.

**The arithmetic.** One routine per title accumulates a 32-bit total of
`base + hp_rolled × per_hp` over a chain of records, pooling each one's seven
money words into a global as it goes — which is AD&D 1st edition's own way of
writing an experience value, "so much, plus so much per hit point".
`SECRET GAME.OVR 0x6B4A`-`0x6B7E`, `CURSE 0x5D7B`-`0x5DAF`,
`POOLRAD 0x564E`-`0x5676`. The base is widened with `xor dx, dx`, so it is
unsigned. In `DARKNESS 0x4813` the multiply is gone and the base is added
alone, and the money loop runs three slots rather than seven — which is what
`goldbox/dos_layout.py` already says about that title's money block.

**Which chain it walks is PROBABLE and does not matter to the naming**: its
two callers in Silver Blades (`0x7169`, `0x737A`) sit beside `The party has
won.` and `Each character receives … experience points.`, and it clones each
record's items into a global chain, which is what pooling a defeated party's
treasure looks like. Settling it means watching the global at `DS:0x7D3C` in
DOSBox-X during a fight.

**The name comes from the script property dispatcher.** Each `GAME.OVR`
carries a chain of

```
cmp ax, <id> / jne / mov ax,[bp+6] / les di,[<the current character>]
mov es:[di+<record offset>], ax
```

and **the ids are C64 record offsets**: `0x0BB` copper, `0x0C1` gold, `0x0C5`
gems, `0x119` hit points current. **17 of 17 arms whose id names a C64 field
land on the DOS field of that name** — five in Pool of Radiance, five in
Curse, seven in Silver Blades, none in Gateway — with no counter-example, and
the only two ids that fall inside a C64 gap are `0x0F7` (a word) and `0x0F9`
(a byte). `docs/80-fields-wanted.md` already had C64 `0x0F7`-`0x0F8` and
`0x0F9` as **experience awarded, and per hit point, CONFIRMED**, from GOBLIN
GUARD 10 with 1 per hit point.

The pattern matches nothing in Pools of Darkness or Treasures of the Savage
Frontier. That is a fact about the pattern rather than about their records:
their award is at `0x198` and their creature files prove it.

**The engine's own importers copy the word as a word.** `CURSE 0x1D423` reads
Pool of Radiance `[0xB8]` with `mov ax` into Curse `[0x13C]`, then `[0xBA]` as
a byte into `[0x13E]`, then `[0xBB]` into `[0x13F]`, which is `portrait_head`
on both sides. `SECRET 0x252D0` does the same from Curse `0x13C` to Silver
Blades `0x14E`. That is the DOS side of the byte-swap
[`166-amiga-records-from-the-code.md`](166-amiga-records-from-the-code.md)
found in both Amiga unpackers.

**And the shipped creatures carry the published numbers.** DOS Pool of
Radiance's `MON1CHA.DAX`, at the offsets above: GOBLIN GUARD 10 and 1,
HOBGOBLIN 20 and 2, OGRE 90 and 5 — the C64's numbers exactly. Silver Blades
reads BLACK DRAGON 4250 and 16, STORM GIANT 5850 and 20, PURPLE WORM 4900 and
20. `tools/dosxpaward.py monsters --game SECRET` prints them.

### Zero in every player, which is why nobody could place it

`tools/dosxpaward.py census` swept **474 DOS character records** — 238 Pool of
Radiance, 110 of the Curse and Gateway shape, 74 Silver Blades, 52 of the
Pools of Darkness and Treasures shape — across the specimen tree and the
player's archives. **Two paths carry a non-zero award and they are one
record**: OUGO in Treasures of the Savage Frontier's `Default files/Saves`,
base 20000, found under two paths. Nothing else is non-zero, and no shape
carries a non-zero per-hit-point byte.

**What a player loses today: nothing.** Both bytes belong to a creature, they
are zero in every player record anywhere, and the C64 keeps the same pair at
`0x0F7`/`0x0F9`, so a conversion in either direction copies zero onto zero.
What the naming buys is three bytes off the unknown list and a `u16le` where
`goldbox/dos_layout.py` has three loose bytes.

## 2. The Silver Blades item's last four bytes are a chain

Silver Blades' item is **67** bytes where the other five DOS engines' is 63,
and `0x03F`-`0x042` is a **far pointer to another 67-byte item node**.
**CONFIRMED.**

* **It is loaded as a far pointer.** `SECRET GAME.OVR` has 41
  `les reg, es:[di+0x3f]` and 19 `mov es:[di+0x3f],ax` / `mov es:[di+0x41],dx`
  store pairs, and NULLs it as a pair of words. The five 63-byte titles load a
  far pointer from that displacement **zero** times. (Treasures makes fifteen
  byte comparisons there, belonging to some other structure — read the
  far-pointer column, not the raw count.)
* **One item type uses it: `type_index` `0x49`.** Every walk is gated on
  `cmp byte ptr es:[di+0x2e], 0x49`, 31 times in `SECRET`, and there is
  exactly **one** store of that type into an item in the whole family:
  `SECRET 0x2951B`, the JOIN routine, which sets `quantity` to 1, zeroes the
  head's own three spell bytes and hangs the joined scroll off `0x03F`.
* **A plain scroll is a different type.** The engine tests `0x27`, `0x28` and
  `0x49` together four times over, and the shipped `ITEM<n>.DAX` templates
  carry 39 (`0x27`) on every `Mage Scroll` and 40 (`0x28`) on every
  `Cler Scroll` — 210 templates, and **not one is a bundle**, because a bundle
  is made in the game. A plain scroll keeps its ids in its own `charges`,
  `effect` and `power` at `0x03C`-`0x03E`.
* **The chain is `quantity` long**, and each node carries three more spell ids
  in its own `0x03C`-`0x03E`, the top bit being a flag of the engine's own
  (`SECRET 0x1B2AA` and `0x2C0C8` both mask with `0x7F`).

This **corrects** the Amiga reading in
[`166-amiga-records-from-the-code.md`](166-amiga-records-from-the-code.md),
which had `0x49` as "a scroll". It is the joined bundle; a scroll is `0x27` or
`0x28`. The Amiga keeps DOS's item numbering, so the same distinction is
PROBABLE there and would be settled by reading what `/Secret` compares against
before it walks `0x42`.

### The chain is written into the file, and `item_count` does not count it

The `.STF` **writer**, `SECRET GAME.OVR 0x24B29`:

```
p := character^.item_chain            ; record + 0x161
while p <> nil do
    BlockWrite(f, p^, 0x43)           ; 67 bytes
    if p^.type_index = 0x49 then
        q := p
        for i := 1 to p^.quantity do  ; 0x39
            q := q^.chain             ; 0x3F
            BlockWrite(f, q^, 0x43)
    p := p^.next                      ; 0x2A
```

The **reader** at `0x258D5` mirrors it: 67-byte records to end of file, and
after a record of type `0x49` it allocates and reads `quantity` more, hanging
each off `0x3F`. **`item_count` at record `0x160` counts head items only** —
the routine that recomputes it (`SECRET 0x3A2C7`) walks `next` at `0x02A` and
never `0x03F`.

So a file holding a bundle has more 67-byte records than `item_count` says,
and `goldbox.dos_codec.read_character`, which takes the first `item_count` of them,
would read the bundle's spell pages as items and lose that many real items off
the end of the pack. That is
`#432 (A joined scroll in a DOS Silver Blades save shifts everything after it
out of the character's pack)`; `tools/dosscrollbundle.py`'s `walk()` is the
engine's loop and `slice_naively()` is the other one.

**Nothing anybody holds is misread today.**
`tools/dosscrollbundle.py census` walked **140 item files** across the
specimen tree and the archives: **0 scroll bundles**, 0 files whose record
count disagrees with `item_count`, and 18 with an `item_count` of zero, which
is an export beside a stale item file and is what `goldbox.dos_codec` documents. The
defect is reachable in the game and unexercised by the corpus, which is why
`#432 (A joined scroll in a DOS Silver Blades save shifts everything after it out of the character's pack)` carries a recipe rather than a specimen.

## What a following agent needs

* **Name the fields in `goldbox/dos_layout.py`**: `experience_award` (`u16le`)
  and `experience_per_hit_point` (`u8`) in the four earlier shapes,
  `experience_award` alone in the two later ones. `tools/dosxpaward.py` looks
  those names up first and falls back to the gap, so it moves with the rename;
  `tests/test_dosxpaward.py` asserts the offsets either way. The C64 side is
  `0x0F7`-`0x0F8` and `0x0F9`, inside `gap_0f4` in `goldbox/layout.py`, and
  naming it there closes the pair.
* **They convert as themselves, not as a drop.** Both ports hold both fields,
  so the conversion copies them; every record either side has zero in them,
  and a player is told nothing because there is nothing to tell.
* **The Silver Blades item chain is `#432 (A joined scroll in a DOS Silver Blades save shifts everything after it out of the character's pack)`'s**, and its hard part is not the
  reading — `walk()` is done — but the destination: the C64's sixteen 16-byte
  slots have three spell bytes per item and no chain, so a bundle of four
  scrolls is a thing that does not fit, and
  `.claude/rules/conversions.md` makes that the player's choice rather than a
  silent drop.
