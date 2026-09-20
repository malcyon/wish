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

## The nineteen

Every reading is CONFIRMED from the code. The creature column is the 70
`MON*` templates `#561` censused, and in each case it is what the *Monster
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

**73 is the correction.** `#561` kept Pool of Radiance's wording for 71, 73
and 109 on the grounds that nothing in Curse contradicted them. Curse's own
handler for 73 does: it is the fourth member of the immunity family, where
112 tests bit 0, 110 bit 1, 135 bit 2 and 73 bit 5, all four ending in
`$1530`. Silver Blades calls its own 73 the same thing. A rear claw rake it
is not. 71 and 109 keep Pool of Radiance's wording, and the reason is
unchanged: no Curse creature carries either, the only spell row writing them
has an unset name pointer, and each shares its handler with another id.

## Negative results, and readings not acted on

* **A structural match against Silver Blades' handlers is not a route.**
  Matching each Curse routine's opcode-and-immediate sequence against every
  Silver Blades routine named 2 of the 19 and both of those were traps: 81's
  two instructions match Silver Blades' 42, which is `slowed` there and
  halves a different variable, and 138 matches Silver Blades' 108, which is
  right but only because the routine is the same code. A two-instruction
  routine collides with anything. Each id was read on its own after that.
* **Six more of Curse's inherited names are wrong or doubtful**, found while
  reading around the nineteen and **not changed**, because `#567` names the
  eighteen and a name deserves the same evidence each. Each needs one more
  read before it goes in the table:

  | id | what `NAMES_CURSE` says today | what Curse's handler does |
  |---|---|---|
  | 50, 54 | mummy rot, blocking healing; repulsed (bronze dragon) | one element doubles the damage and the other halves it and adds 2 on the save -- Silver Blades' 50 and 54 exactly, on the same two lists |
  | 94 | half damage from blunt or piercing weapons | `RTS`. 88 and 120 are bare `RTS` handlers too |
  | 106 | 85% magic resistance | 105's percentile routine with **15**, not 85 |
  | 122 | mummy: vulnerable to fire | enters 67's melee paralysis with a zero duration |
  | 123 | hit only by magical weapons; silver does half | 2d10 of cold at the other combatant unless it has 50 or 10 |

* **`editor/effects.py` warns about Curse's 54 as having no handler.**
  `NO_HANDLER_BY_GAME["curse-of-the-azure-bonds"]` is `{54}`, and 54's Curse
  handler is the elemental pair above. Not ours to change here; it is a
  second file.
* **Three ids Curse honours are still unnamed and no creature carries them**:
  134, 137 and 145, along with 144, which is 96's partner and does the
  hugging. 144 is readable from the same pass -- it is the crush each round,
  and its message index is 68, `HUGS` -- and it is left out because nothing
  in `#567`'s list asked for it.
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
separates edged from blunt, the one template named `BLESSED`, and the three
fire-resistance ids the salamander asks about. Thirty tests, all skipping
with no disks.
