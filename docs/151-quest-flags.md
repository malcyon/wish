# The quest-flag page, and what writes it

**Generated** by `tools/eclflags.py doc` -- do not edit. Nothing here is
transcribed by hand, and no line of it is the game's own text.

`$4A00`-`$4AF8` is where the game records what the party has done.
`$4A00`-`$4A1F` is a scratch page the engine zeroes on every area change and
`$4A20`-`$4AF8` survives one ([`41`](41-memory-regions.md)). This is every
reference the thirty area scripts make to either half.

It replaces `work/reports/quest-flags.md`, which is lost (`#136 (Thirty-two cited write-ups are gone, because the knowledge base pointed into gitignored scratch)`), and was
rebuilt for `#158 (Track the quests the game itself forgets, starting with
Ohlo's potion)`.

## How to read it

`w` and `r` count the operands that write the byte and that read it. `values
written` is what a write stores when the source is a constant; `computed`
means at least one write stores a variable. `+1` is `ADD`, `|n` is `OR` --
a counter and a bit flag respectively. A `*` in the `s` column means a
printed string sits in the same basic block as one of the writes, which is
usually the speech that names the event.

The last column is **our own words**, joined from `goldbox/commissions.py` at
generation time; a blank means this project has not attributed the byte yet.

## The counts

| | |
|---|---:|
| bytes in `$4A20`-`$4AF8` | 217 |
| named by an operand | 172 |
| reached only through a table | 7 |
| **named, either way** | **179** |
| never referenced | 38 |
| operand references | 1415 |
| of those, writes | 497 |
| addresses written somewhere | 166 |
| read and never written | 6 |
| a printed string in the block that writes it | 104 |
| bytes in the scratch page `$4A00`-`$4A1F` | 32 |
| of those, named by an operand | 32 |
| scratch-page references | 920 |

**What names an event.** The lost report said 158 of the named bytes had "a printed string at the write site", and the rule it used for *at* is not recorded. No rule tried here produces 158. This is how many written bytes have a printed string within N statements before one of their writes, so a reader can judge:

| statements back | addresses |
|---:|---:|
| 1 | 48 |
| 2 | 74 |
| 4 | 98 |
| 8 | 128 |
| 16 | 150 |
| 32 | 163 |

**The gaps** -- bytes no script names and no table reaches:

`$4A20`, `$4A2B-$4A2C`, `$4A33`, `$4A40`, `$4A53-$4A58`, `$4A5B-$4A5C`, `$4A6E-$4A71`, `$4A76`, `$4A79-$4A7B`, `$4A82`, `$4A84`, `$4A86`, `$4A8A`, `$4A9D`, `$4AA3-$4AA5`, `$4AC3`, `$4AC9`, `$4ADA`, `$4ADC-$4ADF`, `$4AE8-$4AE9`.

**The table bases** -- an address a `GETTABLE` or `SAVETABLE` indexes off, so the bytes above it are written by a script that never names them:

* `$4A39`-`$4A3F` -- ECL08 $9C4A, index bounded at $9CA3 (ECL08)
* `$4A8F`-`$4A95` -- ECL08 $9C54, index bounded at $9CA3 (ECL08)
* `$4AA6`-`$4ABF` -- ECL08 $9D12, the reward ledger (ECL08)
* `$4AEA`, length not established -- ECL0E $9F77, index bound not established (ECL0E)

## The persistent block

Survives an area change.

| addr | w | r | values written | s | scripts | what we call it |
|---|---:|---:|---|---|---|---|
| `$4A20` | | | | | | *never referenced* |
| `$4A21` | 1 | 4 | 255 |  | ECL15 |  |
| `$4A22` | 2 | 5 | 255, +1 |  | ECL1D |  |
| `$4A23` | 5 | 12 | |1, |16, |2, |4, |8 | * | ECL1D |  |
| `$4A24` | 2 | 5 | 255, computed | * | ECL1D |  |
| `$4A25` | 0 | 1 | - |  | ECL15 |  |
| `$4A26` | 2 | 5 | 255, computed | * | ECL15 |  |
| `$4A27` | 1 | 1 | 255 | * | ECL15 |  |
| `$4A28` | 1 | 1 | 255 |  | ECL15 |  |
| `$4A29` | 1 | 1 | 255 |  | ECL15 |  |
| `$4A2A` | 2 | 2 | 1, computed |  | ECL18 |  |
| `$4A2B` | | | | | | *never referenced* |
| `$4A2C` | | | | | | *never referenced* |
| `$4A2D` | 3 | 7 | |2, |4, computed |  | ECL18 |  |
| `$4A2E` | 7 | 13 | |1, |16, |2, |32, |4, |8, computed | * | ECL18 |  |
| `$4A2F` | 10 | 17 | 0, 1, |1, |16, |2, |32, |4, |64, |8, computed | * | ECL0F, ECL1E |  |
| `$4A30` | 1 | 3 | +1 | * | ECL0F |  |
| `$4A31` | 8 | 14 | |1, |128, |2, |32, |64, computed | * | ECL08, ECL0F |  |
| `$4A32` | 2 | 3 | 1, +1 | * | ECL0F |  |
| `$4A33` | | | | | | *never referenced* |
| `$4A34` | 4 | 10 | 0, 10, 64, +1 |  | ECL12 |  |
| `$4A35` | 9 | 19 | 0, 254, 255, computed | * | ECL12 |  |
| `$4A36` | 2 | 4 | +1, computed | * | ECL12 |  |
| `$4A37` | 4 | 3 | 1, 2, 3, computed | * | ECL12 |  |
| `$4A38` | 3 | 2 | 1, 2, computed | * | ECL12 |  |
| `$4A39` | 5 | 13 | 249, +5, computed |  | ECL08, ECL0A |  |
| `$4A3A` | 5 | 11 | 249, +5, computed |  | ECL0A |  |
| `$4A3B` | 6 | 14 | 249, +5, computed |  | ECL0A |  |
| `$4A3C` | 5 | 5 | +1, +2, +5, computed |  | ECL0A |  |
| `$4A3D` | 1 | 1 | +1 |  | ECL0A |  |
| `$4A3E` | 1 | 1 | +1 |  | ECL0A |  |
| `$4A3F` | 1 | 1 | +1 |  | ECL0A |  |
| `$4A40` | | | | | | *never referenced* |
| `$4A41` | 2 | 7 | 250, 255 |  | ECL0A |  |
| `$4A42` | 6 | 9 | 250, 255, +1, +2, computed | * | ECL0A |  |
| `$4A43` | 1 | 2 | 251 | * | ECL0A |  |
| `$4A44` | 2 | 4 | |1, |2 |  | ECL18 |  |
| `$4A45` | 4 | 12 | +1, +15, computed |  | ECL0E |  |
| `$4A46` | 4 | 8 | |8, computed | * | ECL0E |  |
| `$4A47` | 5 | 9 | |32, computed | * | ECL0E |  |
| `$4A48` | 4 | 8 | |1, |2, |4, |8 | * | ECL0E |  |
| `$4A49` | 1 | 1 | 255 |  | ECL0A |  |
| `$4A4A` | 1 | 1 | 255 |  | ECL0A |  |
| `$4A4B` | 2 | 5 | |128, computed | * | ECL16 |  |
| `$4A4C` | 1 | 5 | computed |  | ECL16 |  |
| `$4A4D` | 10 | 16 | &254, |1, |2, computed | * | ECL16, ECL17 |  |
| `$4A4E` | 1 | 4 | computed |  | ECL16 |  |
| `$4A4F` | 1 | 4 | computed |  | ECL17 |  |
| `$4A50` | 1 | 3 | computed | * | ECL17 |  |
| `$4A51` | 8 | 16 | |1, |128, |16, |2, |32, |4, |64, |8 | * | ECL17 |  |
| `$4A52` | 10 | 16 | &254, |1, |128, |2, |4, |64, computed | * | ECL10, ECL17 |  |
| `$4A53` | | | | | | *never referenced* |
| `$4A54` | | | | | | *never referenced* |
| `$4A55` | | | | | | *never referenced* |
| `$4A56` | | | | | | *never referenced* |
| `$4A57` | | | | | | *never referenced* |
| `$4A58` | | | | | | *never referenced* |
| `$4A59` | 1 | 0 | 1 | * | ECL1C |  |
| `$4A5A` | 1 | 2 | 1 | * | ECL1C |  |
| `$4A5B` | | | | | | *never referenced* |
| `$4A5C` | | | | | | *never referenced* |
| `$4A5D` | 1 | 4 | computed |  | ECL10 |  |
| `$4A5E` | 1 | 3 | computed |  | ECL10 |  |
| `$4A5F` | 1 | 2 | computed |  | ECL10 |  |
| `$4A60` | 4 | 7 | 255, |1, computed | * | ECL10 |  |
| `$4A61` | 5 | 9 | |1, |2, |4, |8, computed | * | ECL10 |  |
| `$4A62` | 5 | 9 | computed | * | ECL03, ECL04, ECL05, ECL06, ECL09 |  |
| `$4A63` | 5 | 5 | computed | * | ECL03, ECL04, ECL05, ECL06, ECL09 |  |
| `$4A64` | 11 | 31 | 0, +1, computed | * | ECL03, ECL04, ECL05, ECL06, ECL09 |  |
| `$4A65` | 19 | 46 | &254, |1, |128, |16, |2, |32, |4, |64, |8, computed | * | ECL03, ECL04, ECL05, ECL06, ECL09 |  |
| `$4A66` | 12 | 23 | &128, |128, |16, |2, |32, |4, |64, |8, computed | * | ECL03, ECL04, ECL05 |  |
| `$4A67` | 11 | 19 | &127, |1, |16, |2, |32, |4, |64, |8, computed | * | ECL03, ECL04, ECL05, ECL06 |  |
| `$4A68` | 2 | 1 | 1, 2 |  | ECL04 |  |
| `$4A69` | 8 | 15 | |1, |128, |16, |2, |32, |4, |64, |8 | * | ECL05, ECL06 |  |
| `$4A6A` | 8 | 29 | |1, |16, |2, |32, |4, |8, computed | * | ECL03, ECL04, ECL05, ECL06, ECL07 |  |
| `$4A6B` | 6 | 11 | |128, |16, |32, |64, |8, computed | * | ECL03, ECL05, ECL08 |  |
| `$4A6C` | 5 | 12 | |16, |32, |64, |8, computed | * | ECL03, ECL07 |  |
| `$4A6D` | 7 | 15 | &252, |1, |2, |4, |8, computed | * | ECL07 |  |
| `$4A6E` | | | | | | *never referenced* |
| `$4A6F` | | | | | | *never referenced* |
| `$4A70` | | | | | | *never referenced* |
| `$4A71` | | | | | | *never referenced* |
| `$4A72` | 1 | 0 | |16 |  | ECL07 |  |
| `$4A73` | 5 | 2 | 128, 255, computed | * | ECL02 |  |
| `$4A74` | 3 | 2 | 1, 2, computed | * | ECL02 |  |
| `$4A75` | 1 | 5 | 255 |  | ECL02 |  |
| `$4A76` | | | | | | *never referenced* |
| `$4A77` | 10 | 32 | |1, |12, |16, |2, |3, |32, |4, |64, |8, computed | * | ECL09 |  |
| `$4A78` | 7 | 5 | 1, 2, 3, computed | * | ECL09 |  |
| `$4A79` | | | | | | *never referenced* |
| `$4A7A` | | | | | | *never referenced* |
| `$4A7B` | | | | | | *never referenced* |
| `$4A7C` | 9 | 30 | &254, |1, |2, |4, |5, |8, computed | * | ECL11, ECL1A |  |
| `$4A7D` | 5 | 2 | 0, 1, 2, 3, computed | * | ECL11 |  |
| `$4A7E` | 3 | 3 | 1, computed |  | ECL11 |  |
| `$4A7F` | 1 | 2 | computed |  | ECL11 |  |
| `$4A80` | 3 | 6 | 0, +1, computed | * | ECL14 | slums: won wandering fights, capped at 15 |
| `$4A81` | 3 | 4 | 250, 255, computed | * | ECL14 | Ohlo's potion: 250 = the potion has been collected from the booth; 255 = Ohlo dealt with: the potion delivered, or he was killed |
| `$4A82` | | | | | | *never referenced* |
| `$4A83` | 1 | 1 | 255 |  | ECL14 |  |
| `$4A84` | | | | | | *never referenced* |
| `$4A85` | 1 | 1 | 255 | * | ECL14 |  |
| `$4A86` | | | | | | *never referenced* |
| `$4A87` | 3 | 6 | |1, |128, |2 | * | ECL13 |  |
| `$4A88` | 1 | 1 | 255 |  | ECL0A |  |
| `$4A89` | 1 | 1 | 255 |  | ECL0A |  |
| `$4A8A` | | | | | | *never referenced* |
| `$4A8B` | 2 | 2 | 128, 255 | * | ECL01 |  |
| `$4A8C` | 1 | 3 | 255 | * | ECL08, ECL19 | marker: the Bivant commission |
| `$4A8D` | 7 | 13 | 1, 2, 3, 4, 5, 6, 7 | * | ECL0D |  |
| `$4A8E` | 3 | 6 | 1, 2, computed | * | ECL0D |  |
| `$4A8F` | 1 | 1 | computed |  | ECL08 |  |
| `$4A90` | 0 | 0 | - |  |  | table interior: $4A8F + 1, ECL08 $9C54, index bounded at $9CA3 |
| `$4A91` | 0 | 0 | - |  |  | table interior: $4A8F + 2, ECL08 $9C54, index bounded at $9CA3 |
| `$4A92` | 0 | 0 | - |  |  | table interior: $4A8F + 3, ECL08 $9C54, index bounded at $9CA3 |
| `$4A93` | 0 | 0 | - |  |  | table interior: $4A8F + 4, ECL08 $9C54, index bounded at $9CA3 |
| `$4A94` | 0 | 0 | - |  |  | table interior: $4A8F + 5, ECL08 $9C54, index bounded at $9CA3 |
| `$4A95` | 0 | 0 | - |  |  | table interior: $4A8F + 6, ECL08 $9C54, index bounded at $9CA3 |
| `$4A96` | 1 | 1 | 255 | * | ECL08 | marker: the graveyard commission |
| `$4A97` | 2 | 5 | 254, 255 | * | ECL02, ECL08 | summons: Councilman Cadorna's chambers |
| `$4A98` | 3 | 4 | 254, 255, computed | * | ECL08, ECL19 | summons: Cadorna's envoy mission |
| `$4A99` | 2 | 1 | 254, 255 | * | ECL08 | summons: Lord Urslingen, the Stojanow Gate briefing |
| `$4A9A` | 4 | 3 | 1, 254, 255, computed | * | ECL08, ECL1A | summons: the special council meeting |
| `$4A9B` | 1 | 2 | 254 | * | ECL00, ECL08 | summons: the Bishop of Tyr |
| `$4A9C` | 2 | 3 | 128, 255 | * | ECL00 |  |
| `$4A9D` | | | | | | *never referenced* |
| `$4A9E` | 6 | 9 | 0, 255, computed |  | ECL19, ECL1A, ECL1B |  |
| `$4A9F` | 1 | 1 | 1 |  | ECL1A |  |
| `$4AA0` | 2 | 6 | |2, computed |  | ECL1B |  |
| `$4AA1` | 2 | 2 | 1, 255 | * | ECL19 |  |
| `$4AA2` | 1 | 3 | 255 |  | ECL1A |  |
| `$4AA3` | | | | | | *never referenced* |
| `$4AA4` | | | | | | *never referenced* |
| `$4AA5` | | | | | | *never referenced* |
| `$4AA6` | 2 | 1 | 254, 255 |  | ECL08, ECL1D | ledger: Norris the Gray killed |
| `$4AA7` | 2 | 5 | 254, computed | * | ECL00, ECL08, ECL15 | ledger: Sokal Keep cleared |
| `$4AA8` | 1 | 3 | 254 |  | ECL18 | ledger: area by the evil temple cleared |
| `$4AA9` | 6 | 15 | 1, 128, 254, 255, computed | * | ECL01, ECL08, ECL19 | ledger: Bivant heir rescued |
| `$4AAA` | 1 | 1 | 254 | * | ECL0F | ledger: library book: discourses |
| `$4AAB` | 1 | 1 | 254 | * | ECL0F | ledger: library book: descriptions |
| `$4AAC` | 1 | 1 | 254 | * | ECL0F | ledger: library book: maps |
| `$4AAD` | 1 | 1 | 254 | * | ECL0F | ledger: library book: histories |
| `$4AAE` | 1 | 1 | 254 | * | ECL0F | ledger: library book: records |
| `$4AAF` | 1 | 1 | 254 | * | ECL0F | ledger: library book: of small value |
| `$4AB0` | 3 | 2 | 1, 254, computed | * | ECL08, ECL12 | ledger: Podal Plaza auction |
| `$4AB1` | 1 | 1 | 254 |  | ECL08, ECL0A | ledger: graveyard menace ended |
| `$4AB2` | 1 | 4 | 254 |  | ECL08, ECL0E | ledger: Kovel Mansion thieves |
| `$4AB3` | 1 | 8 | 254 |  | ECL00, ECL08, ECL17, ECL1A, ECL1B | ledger: Stojanow river pollution |
| `$4AB4` | 4 | 6 | 1, 253, 254, computed | * | ECL08, ECL19, ECL1C | ledger: Cadorna's diplomatic mission |
| `$4AB5` | 2 | 3 | 254, computed |  | ECL08, ECL10 | ledger: lizardmen stopped |
| `$4AB6` | 1 | 2 | 254 | * | ECL08, ECL0D, ECL1B | ledger: kobolds stopped |
| `$4AB7` | 1 | 2 | 254 |  | ECL08, ECL11 | ledger: nomads stopped |
| `$4AB8` | 2 | 2 | 254, 255 | * | ECL00, ECL02, ECL08 | ledger: Cadorna's textile treasure handed in |
| `$4AB9` | 1 | 3 | 254 | * | ECL08, ECL09 | ledger: Stojanow Gate taken |
| `$4ABA` | 1 | 6 | 254 |  | ECL00, ECL07, ECL08 | ledger: Tyranthraxus defeated - the quest is over |
| `$4ABB` | 2 | 8 | 254, +1 |  | ECL08, ECL14 | ledger: slums cleared |
| `$4ABC` | 0 | 0 | - |  |  | table interior: $4AA6 + 22, ECL08 $9D12, the reward ledger |
| `$4ABD` | 1 | 7 | 254 |  | ECL08, ECL12, ECL18 | ledger: Temple of Bane |
| `$4ABE` | 3 | 7 | 254, computed | * | ECL04, ECL08 | ledger: Cadorna exposed as a traitor |
| `$4ABF` | 1 | 0 | 254 | * | ECL03 | ledger: Cadorna killed |
| `$4AC0` | 4 | 10 | 0, 1, computed | * | ECL00, ECL08, ECL0B |  |
| `$4AC1` | 10 | 13 | +1, computed | * | ECL00, ECL08 | count of major commissions paid |
| `$4AC2` | 1 | 2 | 255 | * | ECL08 | marker: the book bounty |
| `$4AC3` | | | | | | *never referenced* |
| `$4AC4` | 3 | 3 | 0, computed | * | ECL00 |  |
| `$4AC5` | 1 | 2 | 1 |  | ECL00 |  |
| `$4AC6` | 1 | 0 | 1 | * | ECL00 |  |
| `$4AC7` | 3 | 3 | 0, 2, 255 | * | ECL0D, ECL1B |  |
| `$4AC8` | 5 | 4 | 1, 128, 255, computed | * | ECL00, ECL02, ECL08 |  |
| `$4AC9` | | | | | | *never referenced* |
| `$4ACA` | 1 | 1 | 255 | * | ECL14 |  |
| `$4ACB` | 1 | 1 | 255 | * | ECL14 |  |
| `$4ACC` | 1 | 1 | 255 |  | ECL14 |  |
| `$4ACD` | 1 | 1 | 255 | * | ECL14 |  |
| `$4ACE` | 2 | 2 | 250, 255 | * | ECL14 |  |
| `$4ACF` | 1 | 1 | 255 | * | ECL14 |  |
| `$4AD0` | 1 | 1 | 255 | * | ECL14 |  |
| `$4AD1` | 2 | 1 | 0, 1 |  | ECL10 |  |
| `$4AD2` | 1 | 1 | 1 |  | ECL11, ECL1A |  |
| `$4AD3` | 2 | 1 | 1, computed | * | ECL0D |  |
| `$4AD4` | 4 | 2 | 1, computed | * | ECL0D |  |
| `$4AD5` | 1 | 1 | 255 | * | ECL0A |  |
| `$4AD6` | 1 | 1 | 255 | * | ECL14 |  |
| `$4AD7` | 1 | 1 | 255 |  | ECL15 |  |
| `$4AD8` | 1 | 1 | 255 | * | ECL14 |  |
| `$4AD9` | 1 | 1 | 255 | * | ECL14 |  |
| `$4ADA` | | | | | | *never referenced* |
| `$4ADB` | 6 | 1 | 0, 1, 2, computed | * | ECL1D |  |
| `$4ADC` | | | | | | *never referenced* |
| `$4ADD` | | | | | | *never referenced* |
| `$4ADE` | | | | | | *never referenced* |
| `$4ADF` | | | | | | *never referenced* |
| `$4AE0` | 2 | 1 | 0, 1 | * | ECL07 |  |
| `$4AE1` | 1 | 1 | 255 |  | ECL02 |  |
| `$4AE2` | 1 | 1 | 255 | * | ECL02 |  |
| `$4AE3` | 1 | 1 | 255 |  | ECL02 |  |
| `$4AE4` | 1 | 4 | +1 |  | ECL02 |  |
| `$4AE5` | 1 | 1 | 1 | * | ECL0D |  |
| `$4AE6` | 2 | 3 | 254, 255 | * | ECL02, ECL08 |  |
| `$4AE7` | 2 | 3 | 254, 255 | * | ECL08, ECL12 |  |
| `$4AE8` | | | | | | *never referenced* |
| `$4AE9` | | | | | | *never referenced* |
| `$4AEA` | 6 | 4 | 0, 1, 2, 3, computed | * | ECL0E |  |
| `$4AEB` | 1 | 3 | 1 | * | ECL0E |  |
| `$4AEC` | 1 | 3 | 1 | * | ECL0E |  |
| `$4AED` | 0 | 2 | - |  | ECL0E |  |
| `$4AEE` | 0 | 1 | - |  | ECL0E |  |
| `$4AEF` | 0 | 1 | - |  | ECL0E |  |
| `$4AF0` | 0 | 1 | - |  | ECL0E |  |
| `$4AF1` | 0 | 1 | - |  | ECL0E |  |
| `$4AF2` | 2 | 4 | +1, +10 |  | ECL0A |  |
| `$4AF3` | 2 | 4 | +1, +10 |  | ECL0A |  |
| `$4AF4` | 2 | 5 | +1, +10 |  | ECL0A |  |
| `$4AF5` | 1 | 2 | +1 |  | ECL0A |  |
| `$4AF6` | 1 | 2 | +1 |  | ECL0A |  |
| `$4AF7` | 1 | 2 | +1 |  | ECL0A |  |
| `$4AF8` | 1 | 2 | +1 | * | ECL0A |  |

## The scratch page

Zeroed by the `NEWECL` handler at `DUNGEON $202A`-`$2032` whenever the resident script changes, so a byte here means something only while the party is still in the area that wrote it.

| addr | w | r | values written | s | scripts | what we call it |
|---|---:|---:|---|---|---|---|
| `$4A00` | 53 | 66 | 0, 1, 2, 3, 4, 5, 6, 7, 8, 10, 255, +1, |1, computed | * | ECL01, ECL03, ECL04, ECL07, ECL08, ECL09, ECL0A, ECL0B, ECL0E, ECL0F, ECL11, ECL14, ECL15, ECL16, ECL19, ECL1A, ECL1B, ECL1C |  |
| `$4A01` | 26 | 33 | 0, 1, 2, 3, 4, 255, +1, |1, |2, computed | * | ECL00, ECL01, ECL07, ECL08, ECL09, ECL0A, ECL0B, ECL0D, ECL12, ECL15, ECL18, ECL19, ECL1A, ECL1B |  |
| `$4A02` | 16 | 23 | 0, 1, 8, 11, 255, +1, computed | * | ECL02, ECL07, ECL08, ECL0A, ECL0B, ECL0D, ECL12, ECL15, ECL18, ECL19, ECL1A, ECL1B |  |
| `$4A03` | 22 | 25 | 0, 1, 2, 4, 26, 255, +1, computed | * | ECL00, ECL01, ECL08, ECL0A, ECL0B, ECL0D, ECL0E, ECL12, ECL15, ECL18 |  |
| `$4A04` | 11 | 19 | 0, 1, 2, 250, 255, +1, computed | * | ECL01, ECL08, ECL0D, ECL0F, ECL12, ECL14 | Ohlo's potion: 250 = the errand has been accepted |
| `$4A05` | 16 | 23 | 0, 1, 2, 255, +1, +9, computed | * | ECL00, ECL01, ECL02, ECL08, ECL0A, ECL0B, ECL0D, ECL0F, ECL12, ECL15 |  |
| `$4A06` | 11 | 14 | 0, 1, 255, +1, computed | * | ECL02, ECL08, ECL0A, ECL0B, ECL0E, ECL0F, ECL15, ECL1A |  |
| `$4A07` | 10 | 14 | 0, 1, 250, computed | * | ECL00, ECL08, ECL0A, ECL0B, ECL0E, ECL0F, ECL14, ECL15 |  |
| `$4A08` | 10 | 11 | 0, 1, 250, 255, computed | * | ECL02, ECL0A, ECL0B, ECL0D, ECL0E, ECL0F, ECL12, ECL14, ECL15 |  |
| `$4A09` | 12 | 21 | 0, 1, 2, 255, computed | * | ECL00, ECL01, ECL02, ECL0A, ECL0B, ECL0F, ECL15 |  |
| `$4A0A` | 7 | 10 | 1, 2, 255, computed | * | ECL01, ECL0A, ECL0D, ECL12, ECL14, ECL18 |  |
| `$4A0B` | 6 | 7 | 1, 2, 251, 255, computed | * | ECL0A, ECL0D, ECL12, ECL14, ECL15 |  |
| `$4A0C` | 2 | 2 | 1, 255 | * | ECL02, ECL0F |  |
| `$4A0D` | 6 | 7 | 0, 1, +1, +128, computed | * | ECL00, ECL0A, ECL15, ECL1A |  |
| `$4A0E` | 11 | 18 | 0, 1, 255, +1, computed | * | ECL01, ECL0A, ECL0D, ECL12, ECL15, ECL18, ECL1A, ECL1C |  |
| `$4A0F` | 15 | 14 | 0, 1, 2, 250, 255, +1, computed | * | ECL00, ECL01, ECL02, ECL0B, ECL0D, ECL14, ECL15, ECL18, ECL19, ECL1A, ECL1C, ECL1D |  |
| `$4A10` | 12 | 18 | 0, 1, 8, 255, +1, computed | * | ECL00, ECL01, ECL0A, ECL0B, ECL15, ECL19, ECL1C, ECL1D |  |
| `$4A11` | 8 | 7 | 0, 1, 255, computed | * | ECL00, ECL01, ECL0B, ECL0D, ECL15, ECL19, ECL1B |  |
| `$4A12` | 3 | 4 | 1, 255, +1 | * | ECL0A, ECL0D, ECL1D |  |
| `$4A13` | 33 | 62 | 0, 1, 2, 255, &32, +1, |1, |128, |16, |2, |32, |4, |64, |8, computed | * | ECL00, ECL01, ECL0A, ECL0D, ECL0E, ECL15, ECL19, ECL1A, ECL1B, ECL1C, ECL1D |  |
| `$4A14` | 10 | 13 | 0, 3, 255, +1, +20, |1, |2, computed | * | ECL0A, ECL14, ECL19, ECL1A, ECL1C, ECL1D |  |
| `$4A15` | 11 | 10 | 0, 1, +1, computed | * | ECL0A, ECL0E, ECL19, ECL1A, ECL1B |  |
| `$4A16` | 11 | 8 | 30, 40, 50, 60, 70, 255, +15, +5, computed | * | ECL0A, ECL0E, ECL14, ECL1A |  |
| `$4A17` | 9 | 8 | 1, 255, +1, computed | * | ECL00, ECL02, ECL14, ECL1A, ECL1C |  |
| `$4A18` | 23 | 15 | 0, 1, 2, 4, 6, 8, 10, 11, 12, 13, 15, 128, +1, computed | * | ECL00, ECL0A, ECL0D, ECL14, ECL15, ECL18, ECL19, ECL1A, ECL1B, ECL1C |  |
| `$4A19` | 29 | 17 | 0, 1, 2, 3, 6, 9, 13, 15, 255, +1, +2, computed | * | ECL00, ECL01, ECL0E, ECL12, ECL14, ECL15, ECL18, ECL19, ECL1A, ECL1B, ECL1C, ECL1D |  |
| `$4A1A` | 9 | 12 | 0, 1, 4, 200, 255, +1, computed | * | ECL01, ECL0E, ECL12, ECL19, ECL1C, ECL1D |  |
| `$4A1B` | 8 | 14 | 0, 1, computed | * | ECL01, ECL0A, ECL18, ECL1C |  |
| `$4A1C` | 3 | 3 | 0, 1, +1 |  | ECL0A, ECL0E, ECL1C |  |
| `$4A1D` | 3 | 4 | 0, 1, +1 | * | ECL14, ECL18, ECL1C |  |
| `$4A1E` | 4 | 3 | 0, 1, +1, computed |  | ECL1A, ECL1C |  |
| `$4A1F` | 3 | 2 | 0, 200, 255 | * | ECL14, ECL1D |  |
