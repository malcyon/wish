# records

Tests for the character record and the tables and rules around it: field layouts, derived values, level tables, per-title tables and the census tools under `tools/records/`.

| file | purpose |
|---|---|
| `test_abilitypair.py` | Checks which of the later C64 titles' two ability arrays the engine treats as current, through the carrying-capacity index it writes back. |
| `test_abilitypaircross.py` | Checks that a crossed DOS ability pair keeps its permanent and in-force halves apart converting to the neutral record, to the C64 and back. |
| `test_amigathac0.py` | Checks Curse's and Silver Blades' guarded and unguarded THAC0 recompute loops against the player's own Amiga executables and representative engine-written records, skipping without them. |
| `test_backstab.py` | Checks the DOS Curse and Silver Blades backstab gates, multiplier arithmetic and dual-class regain helper against the player's own executables, skipping without them. |
| `test_backstab_multiplier.py` | Checks `goldbox/backstab.py` against each title's and port's multiplier table at levels 1 to 20, the level and multiplier caps, the regained and unregained former thief level beside a current one, the race read in the record's own table, a record with no game, and the refusal of a title and port with no measured rule, with no game data. |
| `test_c64backstab.py` | Checks the C64 Curse and Silver Blades thief-level gate, multiplier arithmetic, damage multiply, class-mask table and dual-class regain path against the player's own disks, including the missing-disk result. |
| `test_boundary.py` | Checks that the boundary characters from `tools/records/boundarychars.py` write and read back whole in DOS, that every scalar the DOS writer takes holds its width and is clamped or refused one past it in all four titles, that hit points are the only field wider in the C64 than in DOS, that every legal Curse and Silver Blades character writes to DOS, and that no DOS item becomes anything but sixteen C64 bytes, and that every value the writer narrows is on `losses` while a reader's warning never is. |
| `test_boundary_amiga.py` | Runs the Pool of Radiance boundary cases and every legal Curse and Silver Blades character through the two Amiga re-cuts and checks the name, experience, insertions, item and effect nodes and chain heads, that a name cut to fifteen is on `losses`, and that a reader's warning never is. |
| `test_boundary_c64.py` | Checks that the boundary characters from `tools/records/boundarywidths.py` and `tools/records/laterchars.py` write and read back whole through the C64 writer in all three titles, that a value past a field's width is refused or stops at the ceiling, and that every class combination Curse's and Silver Blades' own menus offer keeps its levels and its bitmask, and that every value the writer narrows is on `losses` while a reader's warning never is. |
| `test_carryceiling.py` | Checks that `tools/records/carryceiling.py` counts what a character carries against the C64's item and trait-slot ceilings. |
| `test_coabsource.py` | Checks that the `STING` cheat string sits on the C64 disks only inside other words and that the `coab` decompilation's DOS record sizes and import behaviour match ours. |
| `test_communityformats.py` | Checks that saving throws, castable spells, damage type and armour protection decode the way a community spreadsheet said. |
| `test_controlbyte.py` | Checks that `tools/records/controlbyte.py` derives each DOS title's control-byte offset from the record layout and reads a value the way the engine does. |
| `test_corrections.py` | Checks corrections to the level ceilings, the promoted effect names and the armour rule against the player's own disks rather than a third-party document. |
| `test_derive.py` | Checks that `goldbox/derive.py` recomputes the values the game caches, including THAC0 with a ranged weapon readied. |
| `test_dualclass_c64.py` | Checks that the C64 reader and writer find a dual-classed character's former class by its name and read an ordinary record as having none. |
| `test_dualclass_dos.py` | Checks that the later DOS titles' former-class level array reads as a named former class, and that the Amiga reader agrees. |
| `test_dualclassregain.py` | Checks the rule a DOS engine uses to decide a dual-classed human has got his old class back, and what the record holds when he has. |
| `test_effects.py` | Checks `goldbox/effects.py`: the effect-array offsets, writing and clearing an effect, the ECL65 spell-effect table, and how much time a duration byte has left at a time of day, and which byte the closest-duration rule picks, against the three engines' own camp ageing routines, and the neutral `RunningEffect` record's reading, writing and refusals. |
| `test_effectcrosswalk.py` | Re-reads C64 duration packing and Pool's DOS/C64 effect-value rules from the player's engine files, checks clock-dependent representability, and rejects unproven strength encodings. |
| `test_enccensus.py` | Checks that `tools/records/enccensus.py` counts an encumbrance failure only where a record's items are known, and that the C64 record has no encumbrance field. |
| `test_fieldcensus.py` | Checks that `tools/records/fieldcensus.py` picks a title's specimen disks by title rather than by directory and tallies every value it reads. |
| `test_fieldnames.py` | Checks corrections to field names against the player's disks: the effect-id table, the roster block's readied-weapon die and the armour-protection encoding. |
| `test_gametables.py` | Checks the per-title race, class-bit and item-name tables on each `Game` descriptor, and how a title's disks are found through the registry. |
| `test_geoports.py` | Checks which of Curse's maps differ between the C64 and Amiga disks and that `ResidentGeo` still names an area when it holds the other port's map. |
| `test_infravision.py` | Checks where infravision comes from on each port and what a conversion does with it. |
| `test_innateeffects.py` | Checks each title's set of innate effect ids and that a converted paladin's or ranger's innate effect reaches the DOS `.SPC` file. |
| `test_items.py` | Checks `goldbox/items.py` against a save taken after the party bought equipment. |
| `test_levels.py` | Checks the level table in `goldbox/levels.py` against the game's own files. |
| `test_liveparty.py` | Checks `goldbox/levels.py` against the values the game's training hall wrote over twenty-nine level-ups. |
| `test_pairs.py` | Checks that a value the save holds twice survives export and import unchanged even when its two halves disagree. |
| `test_pod_spells.py` | Checks Pools of Darkness' spell-slot rows, spell groups, spellbook ceiling and creation menus in `goldbox/spells.py` against the game's own DOS engine, and pins the committed table with no game data. |
| `test_record.py` | Checks `goldbox/record.py` against the committed `brutus.chr`: field decoding, byte-exact round trips, and that setting a field changes only its bytes. |
| `test_ringoffire.py` | Checks the two Ring of Fire Resistance records the C64 ships and which one Wish hands out. |
| `test_second_game.py` | Checks that Curse of the Azure Bonds reads through Pool of Radiance's decoders, over both games' records, roster block, maps and item tables. |
| `test_silverslots.py` | Checks that Secret of the Silver Blades' spell-slot rows in `goldbox/spells.py` match the game's own `ECL65` and reach a converted caster's DOS and Amiga records. |
| `test_spellbookcensus.py` | Checks the geometry and the three engine sites behind `tools/records/spellbookcensus.py`'s answer on whether a character can hold Pool of Radiance's spell id 56. |
| `test_strength.py` | Checks that `goldbox/strength.py` sums party strength term by term the way `DUNGEON $1BE8` does. |
| `test_thac0census.py` | Checks that each DOS title's THAC0 rows start with a real THAC0 rather than a zero sentinel, that the recompute's own rule therefore floors every stored byte at 20, and that every DOS record on this machine reproduces from that rule with each exception named. |
| `test_thiefskillcensus.py` | Checks the relationship between the C64's and DOS's thief-skill tables, read off the player's own files. |
| `test_titles.py` | Checks `goldbox/titles.py`: that Pools of Darkness is a `Title` with no C64 `Game`, and that the DOS and C64 race tables agree except where a measured exception says otherwise. |
| `test_titletables.py` | Checks the tables a title keeps outside the character record: level ceilings, experience thresholds, racial class limits, spell names and item names. |
| `test_traitnames.py` | Checks that `tools/records/traitnames.py`'s headline numbers are what its own counting produces off Curse of the Azure Bonds' disks. |
| `test_turning.py` | Checks the C64's turning-undead byte and what a conversion writes for a DOS cleric or paladin that has none. |
| `test_uascript.py` | Checks community decodes of monster and item fields against the C64 `MON*`, `ITEMS` and `SPELLN00` files. |
| `test_xpceiling.py` | Checks, from each DOS engine's own `GAME.OVR`, that experience is a 32-bit running total nothing caps below the C64 record's three bytes, and that a record past that width is clamped to `0xFFFFFF` with a loss line by the conversion rather than wrapped or refused. |
