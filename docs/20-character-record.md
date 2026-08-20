# Character record

**Generated from `por/layout.py` by `tools/gendocs.py` — do not edit by hand.**

A character record is **580 bytes**. Exported to disk it is a PRG with a 2-byte load address of `$6B00` (582 bytes total). In `SAVEDGAME0` the same 580 bytes sit at the head of each character slot.

## Confidence

| level | meaning |
|---|---|
| `CONFIRMED` | corroborated across specimens, or checked against an external rule (e.g. an AD&D table) |
| `PROBABLE` | consistent with the evidence but not independently verified |
| `GUESS` | a plausible reading that something about the data contradicts |
| `UNKNOWN` | not understood; bytes preserved verbatim |

## Coverage

| level | bytes | share |
|---|---:|---:|
| CONFIRMED | 83 | 14.3% |
| PROBABLE | 38 | 6.6% |
| GUESS | 0 | 0.0% |
| UNKNOWN | 459 | 79.1% |
| **known** | **121** | **20.9%** |

## Known fields

| offset | size | name | type | confidence | notes |
|---|---:|---|---|---|---|
| `0x000` | 20 | `name` | ASCII, NUL-padded | CONFIRMED | NUL-padded; 'BRUTUS' |
| `0x014` | 1 | `strength` | unsigned byte | CONFIRMED | 18 in specimen |
| `0x015` | 1 | `intelligence` | unsigned byte | CONFIRMED | 16 in specimen |
| `0x016` | 1 | `wisdom` | unsigned byte | CONFIRMED | 13 in specimen |
| `0x017` | 1 | `dexterity` | unsigned byte | CONFIRMED | 14 in specimen |
| `0x018` | 1 | `constitution` | unsigned byte | CONFIRMED | 16 in specimen |
| `0x019` | 1 | `charisma` | unsigned byte | CONFIRMED | 13 in specimen |
| `0x01A` | 1 | `exceptional_strength` | unsigned byte | CONFIRMED | 98 -> '18/98' |
| `0x020` | 16 | `spells_memorised` | raw bytes | PROBABLE | a packed list of memorised spell ids, highest spell level first. Ids are CONFIRMED against the game's own SPELLN00 table and against spells Donald memorised on purpose: 1 BLESS, 3 CURE LIGHT WOUNDS, 21 SLEEP. Cleric and magic-user ids fall in disjoint ranges; see por/spells.py. The roster block's +0x03/+0x04/+0x05 were read as a per-level count of this list, because they matched it for all eight characters of npc_party.d64. That reading is RETRACTED: in PORSAVE4 they read 0/0/0 while this list is set, on a save taken after resting. Length is unproven: the most seen in use is 13 bytes, and 0x02D-0x070 is zero in every specimen |
| `0x071` | 1 | `thac0_base` | unsigned byte | PROBABLE | base THAC0, stored as 60 - THAC0, the same encoding the SAVEDGAME1 roster uses for the current value at +0x0E. Matches the AD&D 1st edition table for all twelve of Donald's characters and all six shipped on POOL1; the only three that differ are on the editor-hacked npc_party.d64. This was retired once as 'not THAC0' because MALCYON's sheet shows 20 where the byte reads 39 -- but 39 is 60-21, his base as a level-1 magic-user, and the 20 on screen is the current value after readying a dart. Base and current are different fields in different files |
| `0x072` | 1 | `race` | unsigned byte | CONFIRMED | 1-based: DWARF=1 ELF=2 GNOME=3 HALF-ELF=4 HALFLING=5 HALF-ORC=6 HUMAN=7 MONSTER=8. BRUTUS/ZARRADA=7 human, LARA=2 elf. HALF-ORC is real but NPC-only: it is not on the character-creation menu, and the only two half-orcs in the game are the named NPCs MACE and NORRIS THE GRAY. Two values outside that list matter. **0 is the commonest race in the game**, carried by 75 of the 135 distinct monster records -- every generic creature and some humanoid NPCs -- so it reads as 'not applicable' rather than as a race, and a 0 is not evidence that a record was tampered with. **8 (MONSTER) is used by nothing anywhere**, player or monster: the table enumerates it and the game never instantiates it, the same way it names DRUID, PALADIN, RANGER and MONK |
| `0x073` | 1 | `char_class` | unsigned byte | CONFIRMED | 0-based, standard Gold Box order: CLERIC=0 DRUID=1 FIGHTER=2 PALADIN=3 RANGER=4 MAGIC-USER=5 THIEF=6 MONK=7. 0, 2 and 5 are verified by saving-throw tables; 6 is verified by the monster files, which contain NPCs literally named '1ST LVL THIEF' and '7TH LVL THIEF' carrying code 6. DRUID=1, PALADIN=3, RANGER=4 and MONK=7 appear in NO character anywhere -- not in twenty player characters, not in 108 monster records -- and Donald reports that paladin and ranger were left unfinished in the game data, so those four names rest on the Gold Box convention alone. Codes above 7 are multi-class: 8 = cleric/fighter, 9 = cleric/fighter/magic-user, 10 and 11 = cleric/magic-user, 12 = cleric/thief, 13 = fighter/magic-user, 14 = fighter/thief, 15 = fighter/magic-user/thief, 16 = magic-user/thief. That enumeration is the table the 1989 BASIC editor on poolce.d64 displays, and it agrees with all four multi-class codes we had already read off the bitmask at 0x0EB. Two caveats: the editor lists 3, 4 and 5 all as MAGIC-USER, which is its author's gap rather than the game's, and listing both 10 and 11 as cleric/magic-user looks like a slip in his table. class_bits stays the field to prefer |
| `0x074` | 2 | `age` | 16-bit little endian | CONFIRMED | 16-bit LE; 21 for two humans, 176 for an elf -- long-lived, as expected |
| `0x076` | 2 | `hp_max` | 16-bit little endian | CONFIRMED | 16-bit LE. 11 = 9 rolled + 2 CON. The high byte was long read as filler because no character has yet exceeded 255 hit points; the drain routine in SPELLE02 decrements the pair, which is what settles the width |
| `0x078` | 7 | `spells_known` | raw bytes | CONFIRMED | a bitmask of the spells the character KNOWS, indexed by spell id: bit (id & 7) of byte 0x078 + (id >> 3). Confirmed on every caster we hold -- clerics know every spell of every level they can cast (8 at level 1, 24 at level 6) and magic-users know a subset, which is how AD&D 1st edition works. No cleric has a magic-user id set and no magic-user has a cleric one. MALCYON, a starting mage, knows detect magic, read magic, shield and sleep. Distinct from spells_memorised at 0x020, which is what is currently prepared |
| `0x099` | 1 | `size_small` | unsigned byte | PROBABLE | 1 for a medium character, 0 for a small one. The only byte in the stored 256 that separates dwarves, gnomes and halflings from humans, elves and half-elves -- the AD&D size categories exactly. This is the icon large/small flag the Gold Box Companion exposes. Donald confirmed MAGNUS, a dwarf, shows as small in game, and that the visible difference is the head: a small character's body is the same size and its head is smaller, which is why the icon looks small without being smaller |
| `0x09A` | 1 | `save_paralysis` | unsigned byte | CONFIRMED | fighter 14, cleric 10 -- both match the AD&D 1e L1 tables |
| `0x09B` | 1 | `save_petrification` | unsigned byte | CONFIRMED | fighter 15, cleric 13 |
| `0x09C` | 1 | `save_wands` | unsigned byte | CONFIRMED | fighter 16, cleric 14 |
| `0x09D` | 1 | `save_breath` | unsigned byte | CONFIRMED | fighter 17, cleric 16 |
| `0x09E` | 1 | `save_spell` | unsigned byte | CONFIRMED | fighter 17, cleric 15 |
| `0x09F` | 1 | `movement` | unsigned byte | CONFIRMED | 12 in all three specimens |
| `0x0A0` | 1 | `level` | unsigned byte | PROBABLE | character level. Two independent lines of evidence: the 1989 BASIC editor on poolce.d64 reads and pokes exactly this byte as LEVEL, and across the eight characters of npc_party.d64 it equals the character's per-class level at four distinct values (4, 6, 7, 8). Every earlier specimen was level 1, which is why it long read as a constant 01. Not yet distinguishable from 'the single class's level' -- no multi-class specimen above level 1 has been seen |
| `0x0A1` | 1 | `levels_drained` | unsigned byte | CONFIRMED | how many levels undead have drained, not a second copy of the level. The pair is current-plus-delta, which is why no 'true level' was ever found. SPELLE02 computes hp_max / total levels, loops that many times doing DEC $6B76 / DEC $6BED / INC $6BA2 / DEC $6C19, then INC $6BA1 and DEC $6BC9,X. RESTORATION in SPELLE04 reverses it exactly and prints string 94, which SPELLN00 gives as IS RESTORED |
| `0x0A2` | 1 | `hp_lost_to_drain` | unsigned byte | CONFIRMED | hit points removed by level drain, restored alongside 0x0A1 |
| `0x0A3` | 1 | `turn_class` | unsigned byte | CONFIRMED | which row of the AD&D 1e turning table a creature answers to. Non-zero in exactly 13 specimens, every one undead, and it matches the published table on all of them: skeleton 1, zombie 2, ghoul 3, wight 5, wraith 7, mummy 8, spectre 9, vampire 10, with giant skeleton 8 and juju zombie 9 |
| `0x0A5` | 1 | `thief_pick_pockets` | I8 | CONFIRMED | 30 at L1 |
| `0x0A6` | 1 | `thief_open_locks` | I8 | CONFIRMED | 25 at L1 |
| `0x0A7` | 1 | `thief_find_traps` | I8 | CONFIRMED | 20 at L1 |
| `0x0A8` | 1 | `thief_move_silently` | I8 | CONFIRMED | 20 at L1 |
| `0x0A9` | 1 | `thief_hide_in_shadows` | I8 | CONFIRMED | 10 at L1 |
| `0x0AA` | 1 | `thief_hear_noise` | I8 | CONFIRMED | 10 at L1 |
| `0x0AB` | 1 | `thief_climb_walls` | I8 | CONFIRMED | 85 at L1 |
| `0x0AC` | 1 | `thief_read_languages` | I8 | CONFIRMED | 5 at L1 |
| `0x0AD` | 10 | `item_effects` | raw bytes | PROBABLE | ten slots holding the effect codes of worn magic items -- the same namespace as item byte +14. Three overlays loop LDX #$09 over it, and XAVIER carrying 107 in the first slot and 89 in the tenth proves the extent. GEN $0BF3 seeds it per race from the table [1, 0, 107, 0, 124, 0, 0, 0], so an elf is born with 107 and a half-elf with 124. Those sit immediately below 108 and 125, which are full immunity to sleep and charm, and the table grades other families the same way (64/65/66 are poison by save modifier) -- so 107 and 124 are read as elf and half-elf partial resistance to sleep and charm. PROBABLE. The percentage is not in the byte and could not be: it is a table index |
| `0x0B8` | 1 | `flags_0b8` | unsigned byte | CONFIRMED | bit 7 is the real 'this is an NPC or a monster' flag, and bit 0 records that an ability score was altered at the trainer. npc_party.d64 splits three players from five NPCs exactly on bit 7; the code counts player characters with it and enforces CMP #$06, which is the six-PC party limit in code rather than in anecdote; NPC money is zeroed by it. Bit 0 is set by GEN $155D straight after INC/DEC $6B14,X and cleared again if the change is cancelled. **Nothing anywhere reads bit 0 back**, so the forum rumour that altering a score carries a penalty in play has no code behind it on this port |
| `0x0BB` | 2 | `copper` | 16-bit little endian | CONFIRMED | set to 100 in the edit test and shown in the game (the thirteen-field edit) |
| `0x0BD` | 2 | `silver` | 16-bit little endian | CONFIRMED | 25-26 each after looting orcs, where it was 0 before |
| `0x0BF` | 2 | `electrum` | 16-bit little endian | CONFIRMED | set to 100 in the edit test and shown in the game (the thirteen-field edit) |
| `0x0C1` | 2 | `gold` | 16-bit little endian | CONFIRMED | fell for all six when they bought equipment |
| `0x0C3` | 2 | `platinum` | 16-bit little endian | CONFIRMED | changed for three characters across a shopping trip |
| `0x0C5` | 2 | `gems` | 16-bit little endian | CONFIRMED | set to 10 in the edit test and shown in the game (the thirteen-field edit) |
| `0x0C7` | 2 | `jewelry` | 16-bit little endian | CONFIRMED | set to 10 in the edit test and shown in the game (the thirteen-field edit) |
| `0x0C9` | 1 | `level_magic_user` | unsigned byte | PROBABLE | 1 for every magic-user, 0 otherwise. One entry of the per-class level array -- how dual-classing keeps an old class frozen while a new one advances (the per-class levels) |
| `0x0CA` | 1 | `level_cleric` | unsigned byte | PROBABLE | 1 for every cleric, 0 otherwise. One entry of the per-class level array -- how dual-classing keeps an old class frozen while a new one advances (the per-class levels) |
| `0x0CB` | 1 | `level_thief` | unsigned byte | PROBABLE | 1 for every thief, 0 otherwise. One entry of the per-class level array -- how dual-classing keeps an old class frozen while a new one advances (the per-class levels) |
| `0x0CC` | 1 | `level_fighter` | unsigned byte | PROBABLE | 1 for every fighter, 0 otherwise. One entry of the per-class level array (the per-class levels). Previously guessed to be an exceptional-strength flag, because the only fighters seen then were the only characters with exceptional strength |
| `0x0D5` | 1 | `infravision` | unsigned byte | CONFIRMED | 6 for every dwarf/elf/half-elf, 0 for every human, across 12 specimens -- i.e. 60 feet |
| `0x0D6` | 1 | `sex` | unsigned byte | CONFIRMED | 0 = male, 1 = female. LADY KATHERINE is 1 and confirmed female by Donald; LARA SPELLSWORD and ZARRADA are also 1 |
| `0x0D8` | 1 | `alignment` | unsigned byte | CONFIRMED | 0-based index into the game's own table at $32B3: LAWFUL GOOD=0 LAWFUL NEUTRAL=1 LAWFUL EVIL=2 NEUTRAL GOOD=3 TRUE NEUTRAL=4 NEUTRAL EVIL=5 CHAOTIC GOOD=6 CHAOTIC NEUTRAL=7 CHAOTIC EVIL=8. All six of Donald's characters decode to the alignment he chose |
| `0x0E1` | 1 | `armour_class_base` | unsigned byte | PROBABLE | base armour class, stored as 60 - AC, the same encoding used for THAC0 at 0x071 and for the current AC in the SAVEDGAME1 roster. It is 10 for every player character ever seen -- unarmoured, before dexterity -- which is why it looked like a constant. Monsters use the same record layout and put their real armour class here: kobold 7, orc 6, troll 4, zombie 8, matching the Monster Manual on all eight creatures checked |
| `0x0E2` | 1 | `strength_index` | unsigned byte | PROBABLE | equals STR below 18; 18/80 and 18/81 give 21, 18/98 gives 22 -- the AD&D exceptional-strength bands collapsed to one number |
| `0x0E8` | 3 | `experience` | raw bytes | CONFIRMED | 24-bit LE. After one orc fight the party holds 17 each and LADY KATHERINE 8 -- non-zero and differing, which is what confirms it |
| `0x0EB` | 1 | `class_bits` | unsigned byte | CONFIRMED | magic-user=1 cleric=2 thief=4 fighter=8, OR-ed together. This is how multi-class is really represented: LADY KATHERINE is 5 (magic-user/thief, confirmed by Donald) and LARA SPELLSWORD is 9 (magic-user/fighter -- her name says so). Far more usable than the single char_class code at 0x073 |
| `0x0ED` | 1 | `hp_rolled` | unsigned byte | PROBABLE | 9; +2 CON = hp_max |
| `0x0FE` | 1 | `portrait_head` | unsigned byte | CONFIRMED | index into the HEAD* files on the game disks, in hex: 0x2D is HEAD2D. All eleven values across our exports name a file that exists, and the odds of that happening by chance are negligible -- the ids used include $2D, $43, $44 and $67, not just small numbers. BRUTUS carries the same pair on two unrelated disks, and the two female half-elves share a portrait |
| `0x0FF` | 1 | `portrait_body` | unsigned byte | CONFIRMED | index into the BODY* files, the same way. Head and body are adjacent and independent |
| `0x10E` | 1 | `thac0` | unsigned byte | PROBABLE | current THAC0 including strength and the readied weapon, stored as 60 - THAC0, sitting immediately before the current armour class at 0x10F. Matches the AD&D table on all eleven exports we hold. Like 0x10F it exists only in an export, and it agrees with the SAVEDGAME1 roster's +0x0E for the same character -- so an exported .chr does carry both combat numbers after all, which is worth knowing given the 1989 editor's author reported he could never find either |
| `0x10F` | 1 | `armour_class` | unsigned byte | PROBABLE | current armour class including armour, shield and dexterity, stored as 60 - AC. Present only in an exported .chr -- it lies beyond the 256 bytes a save slot stores -- and it agrees exactly with the SAVEDGAME1 roster's +0x0F for the same character: BRUTUS 9, MALCYON 8, LADY KATHERINE 8. Base and current again, in different places |
| `0x119` | 2 | `hp_current` | 16-bit little endian | CONFIRMED | 16-bit LE, and genuinely current hit points rather than a second copy of the maximum: GEN $0BD0 initialises it from hp_max, and both the trainer and the drain routine move it independently afterwards. It equals hp_max in every specimen only because no wounded character has yet been exported. Note it lies beyond the 256 bytes a save slot holds, so it exists in an export and not in a save |

## Unknown regions that hold data

Regions explicitly declared as candidates because they are non-zero in at least one specimen. Everything not listed here — and not a known field above — is a gap that is all zeroes in every specimen seen so far.

| offset | size | notes |
|---|---:|---|
| `0x0D9` | 8 | 03 02 00 01 00 02 00 00 - byte/zero alternation suggests 16-bit LE words. Shortened by one when 0x0E1 turned out to be the base armour class |
| `0x0E3` | 5 | between strength_index and experience. 0x0E4-0x0E7 is $FF FF FF FF in every NPC. Its first two bytes, 0x0E4-0x0E5, are $00 in every player character and belong to the eight-byte NPC marker -- 0x0B7, 0x0B9, 0x0BA, 0x0D3, 0x0D4, 0x0E4, 0x0E5 and 0x0FB -- which reads $FF in all five NPCs of npc_party.d64 and $00 in all twenty known player characters. 0x0E6-0x0E7 are NOT part of it and were briefly miscounted as such: they hold a non-zero, high-entropy per-character value in every single player character, so they are not a 0/$FF pair. Whether one marker byte is the flag and the rest follow, or all eight are separate 'not applicable' sentinels, is unproven |
| `0x100` | 1 | 01 |
| `0x10D` | 1 | party order? Reads 2, 3, 4 and 5 for ROLAND, SILAS, MAGNUS and BRUTUS, which are exactly the slots they occupied, and 8 -- one past the last slot -- for four characters freshly made and not yet placed. The DOS field catalogue has a marching-order field. Three older exports disagree with their own party order, so this is a candidate and not a finding |
| `0x110` | 9 | a short block ending at hp_current. NOT the item area: in an export the sixteen 16-byte item records start at 0x120 and run to 0x21F, ending exactly where the combat icon begins at 0x220. The 1989 editor scans from 0x110, and its own two loops disagree with each other by sixteen bytes, which is how that error got in here |
| `0x11B` | 1 | 12 in every specimen -- possibly a movement/encumbrance copy |
| `0x220` | 36 | E4 A0 02 6B 04 05 06 07 08 20 A0 0B 20 0D E9 06 10 11 00 0F 08 0E 0E 08 0E 0E 0E 0E 0F 08 0E 0E 00 0E 0E 0E - densest region in the specimen; runs to the final byte of the record |

## Invariant

The table **tiles the whole record**: every one of the 580 bytes belongs to exactly one entry, with gaps generated automatically. That is asserted at import time, so a record can always be decoded and re-encoded byte-for-byte — an edit can never silently drop bytes we do not yet understand.
