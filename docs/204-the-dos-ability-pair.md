# The DOS ability pair: which byte is the score in force

`#401 (Which byte of a DOS ability pair is the current score, now that the
C64's two arrays are named)`.

From Curse of the Azure Bonds onward a DOS character record keeps every ability
**twice, side by side**: strength at `0x010` and `0x011`, intelligence at
`0x012` and `0x013`, wisdom at `0x014`/`0x015`, dexterity at `0x016`/`0x017`,
constitution at `0x018`/`0x019`, charisma at `0x01A`/`0x01B`, and the
exceptional-strength percentile at `0x01C`/`0x01D`. Pool of Radiance keeps one
byte apiece and has no pairs at all.

**No saved game can answer this, and that is not for want of a corpus.** Every
422-, 439- and 510-byte record under the archives and the specimen tree -- 200
of them, 74 Curse-shaped, 74 Silver-Blades-shaped and 52 Pools-of-Darkness-
shaped, 52 distinct by name and abilities -- holds all seven of its pairs with
the two bytes equal: 1400 pairs, 0 differing. The answer had to come out of the
engine.

**And the answer is not the same for all seven pairs**, which is the whole
reason this page exists.

| record bytes | what it is | the C64 byte it answers to |
|---|---|---|
| `0x010`, `0x012`, `0x014`, `0x016`, `0x018`, `0x01A` | the **permanent** score | `0x065`-`0x06A` |
| `0x011`, `0x013`, `0x015`, `0x017`, `0x019`, `0x01B` | the score **in force** | `0x014`-`0x019` |
| `0x01C` | the percentile **in force** | `0x01A` |
| `0x01D` | the **permanent** percentile | `0x06B` |

So the six abilities are a `(base, current)` pair and the seventh is
`(current, base)`. `docs/201-the-two-ability-arrays.md` has the C64 half, where
the split is by array rather than by byte and is uniform across all seven:
`0x065` permanent, `0x014` in force.

Graded **CONFIRMED**: read out of five shipped DOS engines and then measured in
the running game, six crossings, each ability crossed both ways.

## Read out of the engine

The record is reached through a far pointer, so the compiler emits
`es:[di+<record offset>]` and a displacement *is* a record offset. Offsets
below are into Curse's shipped `GAME.OVR`; `tools/dosabilitypair.py sites`
finds the same six signatures in Silver Blades, Pools of Darkness, Gateway to
the Savage Frontier and Treasures of the Savage Frontier, and in none of Pool
of Radiance.

### The recompute, which is the whole mechanism

`GAME.OVR:0x368FB` takes a character and an ability index and rebuilds one
score from the character's items and running spells. It is the DOS twin of the
C64's `ECL65 $913B`:

    55 89 e5 83 ec 14         push bp / mov bp,sp / sub sp,0x14
    26 8b 85 4d 01            mov ax, es:[di+0x14D]     ; the item chain
    8a 46 06 98 d1 e0         al = the ability index, doubled
    c4 7e 08 03 f8
    26 8a 45 10               mov al, es:[di+0x10]      ; seed: the LOWER byte
    88 46 ff
    c4 7e 08 26 8a 45 1d      mov al, es:[di+0x1D]      ; and the HIGHER percentile

then it walks the item chain applying each item's affect, asks `find_affect`
for a running `Strength` spell, folds the girdle-and-gauntlets ladder in, and
finishes:

    8a 46 ff c4 7e 08 26 88 45 11    mov es:[di+0x11], al   ; the HIGHER byte
    8a 46 fd c4 7e 08 26 88 45 1c    mov es:[di+0x1C], al   ; the LOWER percentile

The other five abilities have the same tail, storing to `0x13`, `0x15`, `0x17`,
`0x19` and `0x1B` at `0x36E72`, `0x36EB6`, `0x36ED8`, `0x36DED` and `0x36F15`.
**A value recomputed from the other is the derived one.**

Corroborating the direction from the other end: no engine of the five ever
stores a *computed* value -- one held in a local and put into the record -- into
a pair's lower byte. The shape `mov al,[bp+var] / les di,[bp+player] /
mov es:[di+0x11],al` appears once or twice in each; the same shape into `0x10`
appears nought times in all five. `tests/test_dosabilitypair.py` asserts it.

### The three routines that name the permanent byte

| routine | Curse file offset | what it does |
|---|---|---|
| the end of character creation | `0x2241B` | a six-iteration loop copying `[0x11 + 2i]` onto `[0x10 + 2i]`, and then at `0x22437` `0x01C` onto `0x01D`. The rolled score becomes the permanent one -- and the percentile's copy runs the other way, which is the asymmetry stated twice in twenty-eight bytes |
| the Pool of Radiance import | `0x1CC8E`-`0x1CFE9` | reads the Pool record's single copy, writes it to `[0x10 + 2i]`, and clamps **that** byte between the race-and-sex minimum and maximum. A racial limit belongs on a permanent score, and the C64's importer clamps `$7C65` in the same place |
| "is this stronger than his own" | `0x3674A` | `cmp al, es:[di+0x10]` … `cmp al, es:[di+0x1D]` in four instructions -- the `(score, percentile)` pair the engine calls the character's own is `(0x10, 0x1D)`, one lower byte and one higher one. The only place in the file where those two comparisons appear together |

### The drain says the same thing from the other side

`weaken` at `0x10F45` adds an affect with a duration of 60 ticks, tests
`cmp es:[di+0x11],3` and then `dec byte es:[di+0x11]`. A temporary weakening
moves the byte in force and leaves the permanent one alone -- and
`cure_wounds` recomputes intelligence and wisdom immediately after removing the
`feeble` affect, which is what a permanent byte is for.

## Measured in the running game

DOSBox, one boot, 2026-09-07.
`~/wish-specimens/coab-dos/WISH-SPEC-curse-52-dialog-converted-resave` staged
by `tools/dosabilitypair.py stage` so that one pair per character disagrees,
loaded through DOS Curse's own `LOAD SAVED GAME`, and every sheet photographed
by `tools/dossheetread.py`.

| who | pair staged | lower / higher | the sheet drew |
|---|---|---|---|
| SHARA | strength | 9 / 17 | **STR 17**, `DAMAGE 1D2+1` |
| PHILIPPE | strength | 18 / 9 | **STR 9** |
| TRAVIS | wisdom | 15 / 7 | **WIS 7** |
| LEDERA | wisdom | 7 / 15 | **WIS 15** |
| MATHEW | exceptional strength, at 18/18 | 0 / 100 | **STR 18**, `DAMAGE 1D2+2` |
| MARK | exceptional strength, at 18/18 | 100 / 0 | **STR 18(00)**, `DAMAGE 1D2+6` |

Six of six, and nothing on either side of a crossing: each ability is crossed
both ways, so "it drew the larger one" is excluded.

**Two of the six are the engine's own arithmetic rather than a screenshot.**
SHARA's `DAMAGE 1D2+1` is AD&D's bonus for strength 17, and strength 9 carries
none, so the damage line is computed from her higher byte. MARK and MATHEW have
identical strength bytes and only the percentile crossed between them, and the
`+6` against `+2` is the 18/00 bonus against a plain 18's -- computed from
`0x01C`.

### The negative results from the same run

* **The engine rewrote neither byte.** All six crossings came back byte for
  byte in the engine's own `ENCAMP ▸ SAVE` after the load and a two-square
  walk; the only bytes that moved in any record were `0x199`, `0x1A2` and
  `0x1A5`. The recompute is not on the load path or the walk path -- the same
  shape `#367` found on the C64, whose training hall does not resynchronise the
  arrays either -- so a DOS character whose pair disagrees keeps it
  disagreeing. Making the engine *use* the permanent byte in play needs a
  girdle readied or a `Strength` cast, and nobody has done that yet.
* **DOS's racial level cap reads the score in force**, at `ovr025:317F`
  onwards, testing `es:[di+0x11]` against 17 and 18 race by race. The C64's
  reads the permanent array (`GEN $156B`, `$7C65`). That is a difference
  between two ports of the same game, not a defect in either, and no conversion
  can do anything about it.
* **The community naming is not evidence, and its own halves disagree.**
  `simeonpilgrim/coab`'s IDA struct calls `0x10` `tmp_str` and `0x11`
  `strenght`, while its C# reads the weight allowance and the damage bonus from
  the byte it calls `full`, which is `0x11`. Its *usage* matches the engine and
  its *names* are the opposite way round. `goldbox/dos_layout.py`'s
  "(base, current)" was taken from that naming and happened to be right for the
  six; it could not have been evidence for either answer.

## What it means for the conversion

`goldbox.dos._ability_pair` sends the pair's **first** byte to the neutral
ability, which `goldbox.c64_codec.write` puts at C64 `0x014` -- the score in
force. For the six abilities that is inverted, and
`#404 (A converted Curse or Silver Blades character keeps a temporary strength
boost or drain for good, because the two halves of the DOS ability pair are
crossed)` carries it. For exceptional strength the existing code is right, so
the fix is not a blanket swap.

**The round trip cannot see it.** DOS to C64 and back crosses twice and comes
home byte for byte, which is why `tests/test_doswriter.py` is green with both
halves wrong. What a player would see is a character with a Girdle of Giant
Strength, a running `Strength` spell or a shadow's drain: he arrives on the
other port with the number he should not have kept, and the next thing that
recomputes his score makes it permanent.

`goldbox/amiga.py`'s later-title reader copies the same `(first, second)`
pairing, so it is presumably crossed in the same way -- an inference from the
DOS engine rather than a measurement of the Amiga one, and it needs its own
evidence.

## The specimens

* `~/wish-specimens/coab-dos/WISH-SPEC-curse-401-crossed-ability-pairs` -- DOS
  Curse's own save of the crossed party, slot E, all six crossings intact. The
  first DOS save anywhere whose ability pair halves differ. Its party came from
  this project's own converter, so it is evidence about what the engine does
  with the pair and not about what a shipped record holds.
* `~/wish-specimens/coab-c64/WISH-SPEC-curse-367-crossed-abilities-resave.D64`
  is the C64 counterpart, from `#367`.

## The tools

`tools/dosabilitypair.py` -- `sites`, `census`, `read`, `stage`.
`tools/abilitypair.py` is the C64 one. `tools/dossheetread.py` boots a staged
save and photographs every sheet.
