# Naming Curse of the Azure Bonds' effect codes from their handlers

`#561 (A Curse of the Azure Bonds character's traits are named from Pool of
Radiance's table, which disagrees with Curse's own data about eight codes)`
gave Curse a table of its own and left eighteen codes with no name at all:
ten where the creature carrying the code refuses Pool of Radiance's name
without saying what the right one is, and eight above `NAMES`'s reach that a
Curse creature carries and nothing names. `#567 (Twelve of Curse of the Azure
Bonds' own effect codes have no name at all, only a refusal of Pool of
Radiance's wrong one)` named all eighteen, and corrected a nineteenth, by
reading the routine each id dispatches -- the fifth route in
`docs/171-c64-trait-slots.md`'s table, run against Curse's own addresses.
`#609 (Six of Curse of the Azure Bonds' inherited effect names disagree with
its own combat handlers)` then read the eight inherited names that first pass
had found doubtful and left alone.

Nothing here needs an emulator or a save. Every line is
`tools/c64/traitquery.py curse-of-the-azure-bonds --handlers <id>` and the
disks the registry points at, read-only.

## The dispatch, and Curse's own anchors

The ask at `COMBAT $12C3` parks the matched id in `$7F6E` and reads the pair
of tables at `$EE2A`/`$EEBC`, indexed by **the id itself**, so a handler
address is a routine inside `COMBAT`, which runs at `$0800`. The namespace is
146 ids, the gap between the two tables.

`docs/171-c64-trait-slots.md`'s anchor table is Silver Blades'. Curse is a
different build and shares none of the addresses, so each one below is
re-derived from a Curse code whose name Curse's own spell table already
CONFIRMED -- which is what the section in 171 does for Silver Blades, and is
why it is not a lookup.

| where | what | pinned by |
|---|---|---|
| `$945F` | the damage | 20 Resist Fire is `LDA #$01 / AND $A904 / BEQ / LSR $945F`, and 10 Resist Cold enters it two bytes earlier with `#$02` |
| `$A904` | the damage type: bit 0 fire, 1 cold, 2 electricity, 3 magic, 4 acid, 5 a breath weapon | the same pair for bits 0 and 1; 80 melee acid and 121 acid squirt both store `$10`; 90 and 128, the two handlers that print `BREATHES...`, are the only two that set bit 5 |
| `$1530` | zero the damage and the effect being applied | `LDA #$00 / STA $A902 / STA $945F`, the tail every immunity ends in |
| `$152B` | the same, only when the effect being applied is A | the five bytes in front of `$1530`; 108 immune to sleep and charm is two calls to it, with 53 and 11 |
| `$A903` | the saving-throw d20 | `$0FD3` rolls it, and Resist Fire's `INC $A903` is the +1 |
| `$A93B` | the save byte: bits 2-4 the column, bits 5-7 the modifier, bits 0-1 what a made save does | `$0FD3` indexes `$7C9A` -- record `0x09A`, `save_paralysis` -- with bits 2-4; 83 petrifying gaze sets column 1, and 121's acid and 131's fire breath set column 3 |
| `$A905`, `$A913` | the rolled damage and the number of dice | `$1407` is Nd6 and `$140B` Nd4: 80 is `LDA #$01 / JSR $140B`, "1d4", and 121 is `LDA #$08`, "8d4" -- both names the census had already |
| `$1539` | a d100 under A, carry clear | 107 elf loads 90, 124 half-elf loads 30, and both names were already CONFIRMED |
| `$138F` | print combat message A, which is name-table entry `101 + n` | 83's `LDX #$14` is `GAZES...` and 121's `LDX #$24` is `SPITS ACID` |
| `$1383` | print name-table entry X directly | the pair of `LDA $E884,X / LDY $E7DA,X` behind both, and `goldbox/spells.py`'s own base for Curse |
| `$11B0`, `$1231`, `$123F` | write an effect into the 64-entry array: id in `$A902`, owner `$945D`, duration, flags | 101 troll regeneration applies 59 through `$123D`, and 56 applies 25 for twelve turns |
| `$945C`, `$945D` | the attacker and the target | `$263E` swaps them to put an effect on the attacker instead |
| `$7C76`, `$7D19`, `$7D0C` | record `0x076` hit-point maximum, `0x119` hit points now, `0x10C` combat side | `goldbox/layout.py`; the staged record is `$7C00`, which the predicate's own `$7CAD` fixes |
| `$034F` | how far away the target is | 126 the avoidable gaze refuses above 5, 121's acid squirt above 6, 128's breath above 9 |
| `$A940` | the round, counted up in `COMBAT2` | 90 and 128 refuse above 4, 132 above 3 |
| `$9462` | hits landed this round | `ECL64` zeroes it before an attack sequence and increments it on a hit; 104 missile evasion decrements it when it takes a missile away |
| `$25A6` | **the attack d20**, patched into 96's own first instruction | `ECL64 +0x04e5` is `LDY #$14 / JSR $2F6A / STA $25A6`, the same d20 roller `$0FD3` uses for a save |
| `$4B00`, `$4B40`, `$4B80`, `$4D80` | the 64-entry effect array: id, owner, duration, magnitude | `$11BB` writes all four in order from `$A902`, `$945D`, `$A900` and `$A90E`, and `LIBRARY $409F` -- the predicate every check list asks through -- searches the first two |
| `$A938` -> `$A900` | the duration a handler asks for, and the byte written | `$1175` is `LDA $A938 / AND #$3F / ADC $A90D`, where `$A90D` is `LIBRARY $2FB9`'s 8x8 product of `$A939` and the level; every handler here leaves `$A939` zero, so the byte written is the one asked for |
| `$26DB` | roll d100 under A and negate the effect when it comes in under | 105 enters it with `LDA #$32` and the table already CONFIRMED that as 50%; `$F185` is the eleven-entry ladder that adds 5% a caster level below 11 |
| `$2F46` | a random number 0 to Y | `$1539` is `STA $1542 / LDY #$63 / JSR $2F46 / CMP #imm`, the `#imm` patched with A |

## The nineteen

Every reading is CONFIRMED from the code. The creature column is the 70
`MON*` templates the census of `#561 (A Curse of the Azure Bonds character's
traits are named from Pool of Radiance's table, which disagrees with Curse's
own data about eight codes)` read, and in each case it is what the *Monster
Manual* would have predicted; the list column is Curse's own check lists,
which say what question the engine is asking when it reaches the id.

| id | handler | what it does | carried by | list |
|---|---|---|---|---|
| 57 | `$1F13` | after two hits in a round: `ENGULFS ITS FOE`, which gets 58 `immobile` and 13 for 2d4, while the engulfer gets 139 pointing back at it | BIT O' MOANDER, SHAMBLING MOUND | 2, the attacker's melee specials |
| 73 | `$2719` | the breath-weapon bit: zero the damage | nothing | 4 |
| 81 | `$22C3` | `LSR $945F` and return -- half the weapon damage, the instruction 60 reaches on its own halving arm | ALIAS, BIT O' MOANDER, DRAGONBAIT, SHAMBLING MOUND | 5, target, weapon damage |
| 82 | `$2417` | cold only: halve the damage, and if a made save did anything make it negate | BIT O' MOANDER, SHAMBLING MOUND | 12 and 20, the saving throw and after a failed one |
| 84 | `$248B` | electricity: zero the damage and add 1d8 to the hit points, capped at the maximum | BIT O' MOANDER, SHAMBLING MOUND | 6, target of spell damage |
| 85 | `$24A1` | the weapon's `ITEMS` type byte `+7` bit 0: the damage becomes 1 | LG VEGEPYGMY, SM VEGEPYGMY | 5 |
| 86 | `$276B` | within range, 30 in 100: `SPITS ACID` for its own hit-point maximum, save on the breath column, then 121's acid tail | GIANT SLUG | 14, the monster's ranged form |
| 87 | `$24E4` | three of seven ranged attacks a round, each picking its own target | BEHOLDER | 14 |
| 90 | `$256A` | `BREATHES...` for its hit-point maximum, damage type acid and a breath | BLACK DRAGON | 14 |
| 96 | `$25A5` | on an attack d20 of 18 or better, `HUGS`: the victim gets 58 `immobile` and the hugger 144, which does the crushing each round | OWL BEAR | 2 |
| 103 | `$2692` | +1d6 on its own weapon damage unless the other combatant has 54, 61 or 20 | SALAMANDER | 4, attacker, weapon damage |
| 128 | `$283C` | `BREATHES...` for its hit-point maximum, damage type fire and magic and a breath | DRACOLICH | 14 |
| 129 | `$2700` | 105's routine with 100 rather than 50 | BEHOLDER, RAKSHASA | 6 and 9 |
| 130 | `$286C` | when the weapon's name word `+3` is 135: the damage becomes its own hit points plus 10 | RAKSHASA | 5 |
| 131 | `$288F` | at close range, `BREATHES...` for seven points of fire, save on the breath column | HELL HOUND | 14 |
| 132 | `$28AD` | `THROWS A LIGHTNING BOLT` | TYRANTHRAXUS | 14 |
| 133 | `$28CA` | cancels 142 Fear, 29 Ray of Enfeeblement and 68 Feeblemind, and zeroes anything whose save byte names column 0 | DRACOLICH | 6 and 9, spell damage and immunities |
| 135 | `$2715` | the electricity bit: zero the damage | DRACOLICH, LG VEGEPYGMY, SM VEGEPYGMY, TYRANTHRAXUS | 6 and 9 |
| 138 | `$2902` | target := self, then apply 25 `invisible` silently and with no duration | ALIAS, DRACANDROS, DRAGONBAIT | 8, every combatant at the start |

Four of them are corroborated a second and third way beyond the carrier.

* **130 is the rakshasa's one vulnerability.** The name word it compares is
  135, and Curse ships exactly one item template whose `+3` word is 135:
  `BLESSED QUARREL(S)`. A rakshasa is the *Monster Manual* creature a blessed
  crossbow bolt kills outright.
* **85 is the vegepygmy's.** `ITEMS` byte `+7` splits the weapon types in
  two and nothing carries both bits: 18 types have bit 0 -- the swords, the
  daggers, the spears and every bow, crossbow and sling -- and 13 have bit 7,
  which is the blunt set Silver Blades' 90 reads. A weapon that cuts or
  pierces doing one point is the vegepygmy's own line.
* **87 is the beholder's eyes, by name.** Seven parallel entries at `$2549`:
  four are spell ids cast at caster level 10 -- 55 `SLOW`, 10 `CHARM PERSON`,
  84 `FEAR`, 66 `CAUSE SERIOUS WOUNDS` -- and three are combat message
  indices with their own save byte and status, 6 `TURNS TO STONE` on the
  petrification column, 46 `IS KILLED` on the paralysis/death column and 67
  `DISAPPEARS` on the spell column. Seven of the ten eye rays, and 10 HD is a
  beholder.
* **96 is the owl bear's hug, to the rule.** The immediate it compares is
  patched with the attack d20 and the constant is 18, which is when an owl
  bear hugs.

**73 is the correction.** `#561 (A Curse of the Azure Bonds character's traits
are named from Pool of Radiance's table, which disagrees with Curse's own data
about eight codes)` kept Pool of Radiance's wording for 71, 73
and 109 on the grounds that nothing in Curse contradicted them. Curse's own
handler for 73 does: it is the fourth member of the immunity family, where
112 tests bit 0, 110 bit 1, 135 bit 2 and 73 bit 5, all four ending in
`$1530`. Silver Blades calls its own 73 the same thing. A rear claw rake it
is not. 71 and 109 keep Pool of Radiance's wording, and the reason is
unchanged: no Curse creature carries either, the only spell row writing them
has an unset name pointer, and each shares its handler with another id.

## The eight inherited names the handlers contradict

Not codes with no name: codes carrying Pool of Radiance's name, which Curse's
own routine says is somebody else's. No creature carries 50, 54, 88, 94 or
120; the dracolich carries 122 and 123 and Tyranthraxus carries 106
(`tools/records/traitnames.py curse-of-the-azure-bonds --monsters`).

| id | handler | what it does | was called | list |
|---|---|---|---|---|
| 50 | `$2283` | fire doubles the damage; cold halves it and adds 2 to the saving throw | mummy rot, blocking healing | 12 and 20 |
| 54 | `$2289` | the same routine entered two bytes in, with the elements the other way round | repulsed (bronze dragon; the handler is unimplemented) | 12 and 20 |
| 88 | `$2556` | `RTS` | electrical breath weapon | 14 |
| 94 | `$25A4` | `RTS` | half damage from blunt or piercing weapons | 5 |
| 106 | `$26FC` | `LDA #$0F` into 105's percentile routine: 15, not 85 | 85% magic resistance | 6 and 9 |
| 120 | `$276A` | `RTS` | boulder evasion, 50% | 5 |
| 122 | `$236A` | enters 67's paralysis four bytes in, past its 2d8, so the duration written is zero | mummy: vulnerable to fire | 2 |
| 123 | `$27D0` | 2d10 of cold at the one it hits, unless that one holds 50 or 10 | hit only by magical weapons; silver does half | 2 |

**50 and 54 are one routine with two entry points, and Silver Blades already
names it.** `$2283` loads the fire bit and keeps the cold bit in X; `$2289` is
the same two instructions the other way round; from `$228D` they share
everything. The element in A doubles the damage (`ASL $945F`); the element in
X reaches `$22A2`, which halves it and rewrites the save byte's bottom two
bits to 1, and then `$1EC4`, which is `INC $A903` twice. Secret of the Silver
Blades builds the identical routine at `$27DC`/`$27E2` and `#497 (The trait
picker offers a Secret of the Silver Blades character six names, and nobody
has ruled on whether it should offer Pool of Radiance's 129)` CONFIRMED it
there as "vulnerable to fire, resistant to cold" and its partner.

Which way round each one goes is corroborated twice from elsewhere in Curse's
own `COMBAT`, and neither reading depends on the other title: the salamander's
103 skips its heat when the other combatant holds one of the three ids at
`$F182` -- **54**, 61 and 20, where 61 is the Ring of Fire Resistance and 20 is
Resist Fire -- and 123 skips its cold when the other combatant holds one of
the two at `$27F3` -- **50** and 10, where 10 is Resist Cold. So 54 is the
fire resistance and 50 the cold, which is the direction the handler bits give.

**106 is 15%, not 85%.** `$26FC` is `LDA #$0F / BNE $26DB`, and `$26DB` is
105's own routine two bytes past its `LDA #$32`. The four percentiles the
table already CONFIRMED -- 50 for the drow, 90 for the elf, 30 for the
half-elf, 100 for 129 -- all reach the same instruction, and each is the
chance the effect is negated, since `$26F3`'s `BCS` skips `$1530` when the
d100 comes in at or above A.

**122 is 67's paralysis with the duration taken out.** `$236A` is `LDX #$00 /
BEQ $2354`, and `$2354` is four bytes into 67's handler, past the `JSR $13FD /
TAX` that rolls 2d8 into X. Everything after that is shared: save byte 1
(column 0, `save_paralysis`), effect id 52 -- Curse's own `held or paralysed`
-- and X as the duration. So the byte written to `$4B80` is zero, and a zero
duration never runs out. Curse's own per-round sweep at `COMBAT2 $FA77` reads
the id, reads the duration and branches away on either being zero before it
reaches `DEC $4B80,X`; `$118E` goes further and refuses to overwrite a slot
whose duration is already zero with any other value, which is the engine
treating zero as longer than anything else. `docs/133-active-effects.md` has
the same finding from Pool of Radiance's three ageing routines.

**123 is 79's melee touch in cold.** `$27D0` stages the target (`ECL64
$89FD`), walks the two ids at `$27F3` through the trait-slot predicate, and
returns if either is there. Otherwise it is `LDA #$02 / JSR $13F5` -- 2d10,
the Nd10 entry beside the `$1407` and `$140B` the anchors table already pins
-- and then `LDA #$0A / JSR $23F7`, where `$23F7` is the instruction 79 falls
into after its own `LDA #$09`. The two damage-type bytes differ in bit 0
against bit 1, fire against cold, and share bit 3, magic. Both ids sit on
check list 2, the attacker's melee specials, beside 57's engulf, 79's fire
touch, 80's acid and 96's hug.

**88, 94 and 120 do nothing, and that is the name.** Each dispatches to a
single `RTS` at an address of its own, rather than to the fourteen-id filler
at `$1E48` that the unimplemented ids share, and each is on a check list --
88 on 14, the monster's ranged form; 94 and 120 on 5, the target's weapon
damage. So the engine does reach them and they return at once. A name
describing a breath weapon or a dodged boulder tells a player the game does
something it does not.

## Negative results, and readings not acted on

* **A structural match against Silver Blades' handlers is not a route.**
  Matching each Curse routine's opcode-and-immediate sequence against every
  Silver Blades routine named 2 of the 19 and both of those were traps: 81's
  two instructions match Silver Blades' 42, which is `slowed` there and
  halves a different variable, and 138 matches Silver Blades' 108, which is
  right but only because the routine is the same code. A two-instruction
  routine collides with anything. Each id was read on its own after that.
* **The structural match against Silver Blades is still not a route, and 50
  and 54 are not a counter-example.** They are named here from Curse's own
  bits and from the two id tables Curse's own handlers index, and the Silver
  Blades wording is the third line rather than the first. A routine that
  matches is evidence only when it is long enough to be one routine.
* **`ECL64 $89FD` was read only as far as 123 needs.** It stages the combatant
  in `$945D`, which is what makes the two-id walk read the *target's* trait
  slots, and `$8F43` puts the attacker's staging back. Its second half at
  `$8A08` picks a combatant by direction out of a table and was not read.
* **Whether a zero-duration effect survives the end of a fight was not
  traced.** Nothing ages it, nothing clears its id, and `$118E` will not
  overwrite it -- that is enough for "never wears off" inside the fight. A
  sweep somewhere outside `COMBAT` that empties the array between battles
  would narrow it to the fight, and the experiment is
  `tools/c64/effectdrive.py`'s: write 52 with a zero duration into a copy of a
  save, fight, and read the array afterwards.
* **`editor/effects.py` no longer warns about Curse's 54.**
  `NO_HANDLER_BY_GAME["curse-of-the-azure-bonds"]` was `NO_HANDLER - {63}`,
  which left `{54}`, so the picker told a Curse player "The game has no answer
  for this one" about a code the game answers at `$2289`. It is
  `frozenset()` now.
* **Three ids Curse honours are still unnamed and no creature carries them**:
  134, 137 and 145, along with 144, which is 96's partner and does the
  hugging. 144 is readable from the same pass -- it is the crush each round,
  and its message index is 68, `HUGS` -- and it is left out because nothing
  in the list of `#567 (Twelve of Curse of the Azure Bonds' own effect codes
  have no name at all, only a refusal of Pool of Radiance's wrong one)` asked
  for it.
* **The `IS SMOTHERED TO DEATH` message (index 57) was not traced to a
  handler.** 57's engulf prints `ENGULFS ITS FOE` and applies the pair, and
  139, the partner it parks on the engulfer, is a long routine that was not
  read to the end. What kills the victim is therefore read from 139 and not
  from 57.

## What re-derives it

`tests/curse_of_the_azure_bonds/test_curtraitnames.py` re-derives every name
above off the player's own disks: the damage-type bit each immunity tests,
the percentile each resistance rolls, the message each ranged form prints and
the entry that message resolves to, the ray table, the `ITEMS` bit that
separates edged from blunt, the one template named `BLESSED`, the three
fire-resistance ids the salamander asks about, the two cold ones 123 asks
about, the four bytes 122 skips over and the sweep that will not age a zero.
Thirty-nine tests, all skipping with no disks.
