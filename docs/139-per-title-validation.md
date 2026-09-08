# Validating every feature on every title we claim

`README.md` promises Pool of Radiance, Curse of the Azure Bonds and Secret of
the Silver Blades. This document says, feature by feature, what that promise is
actually backed by — and what it would take to back the rest.

## 0. The four answers, up front

| question | answer | grade |
|---|---|---|
| Does a test plan for this exist? | **No.** `docs/120` and `docs/121` are *decoding* plans for a second and third title; `docs/122` is packaging. Nothing enumerates the shipped features against a title | CONFIRMED, read |
| Is `docs/144-decoding-a-new-title.md` that plan? | **No.** It is the recipe for decoding a title the project has not done yet. Its nineteen steps end at "a mapper you can believe" and never mention the editor, the CLI, the live actions, Fast Travel or Level Up | CONFIRMED, read |
| How much of the README promise is verified? | **49 features. Pool of Radiance 48 verified, Curse 39, Silver Blades 37.** §2 | CONFIRMED, cited per row |
| Where is the promise thinnest? | **The six purses beyond gold on either later title**, A8, and it is the only unverified cell left that anybody here can reach: C10 and C11 are ruled out by G7, D4 needs hardware nobody on this project has, and D1 needs a live machine. An inventory edit was the answer until 2026-09-08, when `tools/inventorycheck.py` took A13 to `V` on both later titles; the editor's write-back path on Silver Blades was the answer the day before that, and the live tab the day before that (`docs/212-the-live-tab-per-title.md`) | CONFIRMED, cited per row |

The honest one-line version: **the file path works on three titles, and so
does the live tab -- reader, map, badges and all five action buttons, watched
in the running game on each.** What is left is the six purses beyond gold, and
the combat view and log, which are ruled out by G7. The editor writing a Silver
Blades save back was on that list until 2026-09-08, and an inventory edit on
either later title came off it the same day.

## 1. How far out of date `docs/120` and `docs/121` are

Both are sound about what they cover. Both cover a much smaller program than
the one that now ships.

| | `docs/120` (Curse) | `docs/121` (Silver Blades) |
|---|---|---|
| written against | the editor, the CLI and the automapper's map | the same, plus `goldbox/games.py` |
| "the editor" means | the character sheet, inventory, icons, YAML | the shipped party decoding |
| "the automapper" means | `Geo`, `ResidentGeo`, `party_fix`, `Fingerprint` | the same five |
| never mentions | Fast Travel, Level Up, the Quest Log, the combat log, the combat view, condition badges, the quickfight badge, map notes, the roster cards, the live actions (heal, store/restore spells, identify), Preferences, the debug log, the DOS converter | all of the same, plus the whole editor UI |

Ten shipped features are absent from both documents. `docs/120`'s tier 4 is a
five-row table of the automapper; the automapper tab today has fifteen rows in
§2 below.

Two specific corrections they already earned and have not had:

* `docs/120` tier 4 listed the memory fallback as "does not transfer" and left
  it there, so it shipped as a defect on two titles. **Closed by #29 (The live reader uses Pool of Radiance's addresses on every title)**: the
  triple is `Game.live_position`, measured per title, and a title where it is
  unmeasured refuses instead of guessing.
* `docs/121` §6 lists eight edits the run owes the decoding checklist -- then
  `skills/goldbox/SKILL.md`, now `docs/144-decoding-a-new-title.md` -- and says
  they were not made because the file was another agent's. Seven of the eight are still
  not made. §4.

## 2. The matrix

**V** verified, with the citation beside it · **U** unverified · **X** known
not to work · **R** refuses, correctly, and the refusal is tested · **—** not
applicable.

### A. The file path — no emulator

| # | feature | PoR | COAB | SSB | evidence |
|---|---|---|---|---|---|
| A1 | title identified from the disk | V | V | V | `test_curse.py::test_a_pool_of_radiance_disk_identifies_itself`, `…test_a_curse_disk_identifies_itself`, `test_pertitle_ui.py::test_a_silver_blades_save_shows_its_own_races` |
| A2 | save geometry: header, slots, items, icon table, roster | V | V | V | `test_curse.py::test_the_curse_roster_is_the_last_page_of_the_save`, `test_silverblades.py::test_the_save_file_is_curses_geometry_under_a_different_name` |
| A3 | 580-byte record decodes to sane fields | V | V | V | `test_curse.py::test_every_curse_character_parses_with_fields_a_person_would_recognise`, `test_silverblades.py::test_the_shipped_party_decodes_with_fields_a_person_would_recognise` |
| A4 | record round-trips byte-identically | V | V | V | `test_curse.py::test_a_curse_character_export_round_trips_byte_for_byte`, `test_silverblades.py::test_every_slot_round_trips_byte_identically` |
| A5 | race, class, alignment named in the sheet | V | V | V | `test_pertitle_ui.py::test_the_race_table_follows_the_title`, `…test_a_silver_blades_save_shows_its_own_races` |
| A6 | saving throws satisfy the derived rule | V | V | V | `test_curselevels.py::test_curse_matches_ssis_own_pregenerated_party`. **Built (#187 (Silver Blades characters are shown Pool of Radiance's level progression))**: `GEN $1148` and `$115C` give the level-1 rows and a two-bit-per-level improvement mask, `$11C0` takes 2 off every column for a paladin and `$11D8` takes `constitution * 2 / 7` off columns 0, 2 and 4 for race 3 alone, all in `goldbox/levels.py:SECRET_OF_THE_SILVER_BLADES`. Reproduces all six shipped characters' stored saves — `test_coldread.py::test_silver_blades_saving_throws_reproduce_ssis_own_party` and `…test_silver_blades_saves_match_the_modules_own_table` — and the sheet now shows them, via `automap/live.py:_classes` |
| A7 | experience thresholds, ceilings, THAC0, hit dice | V | V | V | `test_curselevels.py::test_curse_experience_is_the_games_own_table` and six neighbours. **Built (#187 (Silver Blades characters are shown Pool of Radiance's level progression))**: experience `GEN $162D` (6 x 19 x 3, big-endian, reproducing Curse's 61 overlapping thresholds), ceilings `$17D0`, THAC0 `$106F`/`$107F`/`$108F` with the fighter group computed `21 - fighting level`, hit dice `$1845`/`$184D`/`$1855`, all in `goldbox/levels.py:SECRET_OF_THE_SILVER_BLADES` — `test_coldread.py` and `test_ssblevels.py` |
| A8 | the seven money fields | V | V (gold only) | V (gold only) | `docs/120` §5.2 — gold `0` → `777` read back off Curse's own sheet; SSB's gold `0` → `4321` read back off its sheet on 2026-09-08 for #33 (One Silver Blades session, for the whole editor path). The other six purses are untested on any title but PoR |
| A9 | spellbook width | V | V | V | `test_silverblades.py::test_a_silver_blades_caster_writes_past_pool_of_radiances_spellbook`; **Curse is 13 and the game's own code says so** — `CAMP $2A25` walks spell ids to 100 and reads `LDA $7C78,X` with X at 12, `test_curse.py::test_camp_reads_curses_mask_as_far_as_spell_one_hundred`. No Curse specimen writes past `0x07C` and none has to (#31 (Cold-read Curse and Silver Blades for the fields the editor shows)) |
| A10 | spell names resolve | V | V | V | `test_curselevels.py::test_curse_reads_its_names_out_of_combat2`; **SSB's are resolved** — `goldbox/spells.py:SECRET_OF_THE_SILVER_BLADES`, `COMBAT2` at `$E000`, 194 entries, spells to 117, with `test_silverblades.py::test_silver_blades_keeps_its_spell_names_in_combat2_like_curse` and `…::test_ids_one_to_fifty_six_mean_the_same_spell_but_for_heal_and_harm` |
| A11 | item names resolve | V | V | V | `test_titletables.py::test_every_title_names_its_first_item_battle_axe` — all six titles |
| A12 | item **types** (`ITEMS`) decode to damage/AC/usage | V | V | V | `test_second_game.py::test_curse_item_types_are_the_same_table_with_ranger_added`; **SSB decodes to AD&D on 42 of 43 named items**, 30 weapons and 13 armour, through the unmodified decoder against its own `ITEM<nn>` lists — `test_coldread.py::test_a_titles_item_types_decode_to_the_rulebooks_numbers`. The exception is the hammer's damage against large opponents, which SSB stores as 1d4+1 where the other two store the rulebook's 1d4; both are sane dice out of the same three bytes, so it is a data difference and not a misread offset |
| A13 | inventory edit, add, remove | V | V | V | **Closed on 2026-09-08 on both**, VICE pool slot 7, `tools/inventorycheck.py`. All three verbs on one character, made through the editor's own handlers, then read off the game's own `EQUIPPED ITEM` screen with the unedited specimen run through the same code as the control. Curse, `WISH-SPEC-curse-party-with-items`: ten rows became seven, `SILVER MIRROR` went from seven copies to three with a `9` in front of one, `TWO-HANDED SWORD` appeared, and the readied `YES 1 FLASK OF OIL` stayed put. Silver Blades, `WISH-SPEC-ssb-d-engine-resave`: twelve rows became ten, `30 ARROW +1` became `9 ARROW +1`, `CANARY` appeared, and `LONG SWORD +1`, `SHIELD +2` and `PLATE MAIL +1` were gone. `test_inventorycheck.py`, nine tests, including that every byte an edit moves is inside that character's own item page and that a save with no edit writes the payload back byte for byte. **The row's old blocker was out of date twice over**: `#32 (One Curse session, to get a party with items)` made the Curse specimen on 2026-09-04, and `WISH-SPEC-ssb-d-engine-resave` has always carried twelve items on Guy de Valois |
| A14 | combat icon editor and its charset | V | V | V | `CHARPIC00` is on all twenty sides of the three titles, 2030 bytes every time. **Curse's is Pool of Radiance's byte for byte** (only the PRG load address moves, `$8000` → `$3000`) and **Silver Blades redraws three glyphs of 253** — 132, 133 and 207 — which its own eight-bytes-per-glyph reading takes unchanged. `test_curse.py::test_the_combat_icon_charset_is_pool_of_radiances_byte_for_byte`, `test_silverblades.py::test_the_combat_icon_charset_is_pool_of_radiances_but_for_three_glyphs`. The editor reads the open title's own disks: `editor/window.py:_disk_candidates` globs on `game.disk_glob` |
| A15 | character traits panel (`0x0AD`–`0x0B6`) | V | V | V | The seed tables are found by the read that uses them — `LDX <race> / LDA <table>,X / STA <slot>` — and the number of slots seeded is per title: Pool of Radiance one (`GEN $0BF3`), Curse three (`$24EA`), Silver Blades two (`$0C4B`). **Curse's codes are Pool of Radiance's**, every one landing on the race its name demands. **Silver Blades' are not**: its elf is seeded 95 and its half-elf 18, which read as "fights on from -6 to 0 hit points" and a gnome's bonus against kobolds. **Closed by #186 (The character sheet gives a Silver Blades elf a Pool of Radiance ability)**: `goldbox/traits.py` is a table per title now, Curse pointing at Pool of Radiance's and Silver Blades carrying its own — six of its nine seeded codes named by pointing the existing wording at this title's number, and 7, 92 and 105 showing their number because nobody has read what they mean. `test_coldread.py`, six tests, corroborated on the shipped party; `test_pertitle_ui.py`, seven more, on a record built with an elf in it because the shipped party is all humans and dwarves |
| A16 | the four active-effect arrays are read | V | V | V | **This row said "active effects panel" and marked it V for Pool of Radiance; there is no such panel in the program for any title.** `docs/133-active-effects.md` opens "A plan, not a record of work", and the box that carried that title is now `Character Traits`, which is A15. What exists is `automap/live.py:active_effects`, feeding the combat view and the condition badges — and its four payload offsets `$000`, `$040`, `$080`, `$280` and its 64 slots are now measured on all three titles: `CAMP`'s owner-renumber loop is instruction for instruction the same in each with `LDX #$3F`, and `DUNGEON`'s duration tick likewise. `test_coldread.py::test_the_effect_arrays_sit_where_the_save_image_puts_them` and `…::test_camp_renumbers_sixty_four_effect_owners_in_every_title`. **What an id *means* on a later title is not settled** and A15 is a reason to doubt it — see C13 |
| A17 | an unchanged save writes back byte-identically | V | V | V | `test_curse.py::test_the_editor_writes_a_curse_save_back_unchanged`; **SSB closed by #33 (One Silver Blades session, for the whole editor path)** — `test_ssbeditorpath.py::test_the_editor_writes_a_silver_blades_save_back_unchanged`, on `WISH-SPEC-ssb-d-engine-resave`, the C64 engine's own `ENCAMP > SAVE` |
| A18 | YAML export → import → byte-identical disk | V | V | V | `test_curse.py::test_a_curse_save_disk_survives_yaml_byte_for_byte`; **SSB closed by #33 (One Silver Blades session, for the whole editor path)** — `test_ssbeditorpath.py::test_a_silver_blades_save_disk_survives_yaml_byte_for_byte`. The row's old reason, that SSB had no save disk in the tests, stopped being true on 2026-09-05 when `#193 (Convert a Secret of the Silver Blades DOS save into a C64 one, which the importer refuses today)` left six engine-written Silver Blades disks in the specimen tree |
| A19 | a save of one title refuses to import into another | V | V | V | `test_curse.py::test_a_curse_party_will_not_import_into_a_pool_of_radiance_disk` and its mirror; **SSB closed by #33 (One Silver Blades session, for the whole editor path)** in both directions — `test_ssbeditorpath.py::test_a_silver_blades_party_will_not_import_into_a_pool_of_radiance_disk` and `…test_a_pool_of_radiance_party_will_not_import_into_a_silver_blades_disk`, each asserting the refusal names both titles |
| A20 | an edited field appears in the running game | V | V | V | `docs/120` §5.2 — name, gold and current hit points, all three read off Curse's own screens. **SSB closed by #33 (One Silver Blades session, for the whole editor path)** on 2026-09-08, VICE pool slot 3: MORGAINE renamed to `BRIGHID`, gold 0 → 4321 and strength 17 → 12 through `EditorBinding`, and the game drew `BRIGHID` on the party-formation panel and in the `VIEW WHICH CHARACTER?` list, `STR 12` and `GOLD          4321` on the sheet. `tools/ssbedit.py` is the run |

### B. The DOS converter

| # | feature | PoR | COAB | SSB | evidence |
|---|---|---|---|---|---|
| B1 | read a DOS save | V | — | — | `test_dossave.py`, `test_dosconvert.py`; `docs/117` narrowed the goal to DOS Pool of Radiance, one direction |
| B2 | convert a DOS save into a C64 one | V | — | — | issue #6 (Convert a DOS save into a C64 save), closed: the converted disk loads and the party walks |

### C. The automapper — needs a live machine

| # | feature | PoR | COAB | SSB | evidence |
|---|---|---|---|---|---|
| C1 | `GEO` decode, verified by reciprocity | V | V | V | `test_curse.py::test_every_curse_map_decodes_through_the_unmodified_decoder`, `test_silverblades.py::test_all_seventeen_maps_decode_through_the_unmodified_decoder` |
| C2 | resident map block at `$0400` | V | V | V | `test_curselive.py::test_the_resident_map_block_is_at_0400_in_curse_too`, `docs/121` §5 |
| C3 | party fix from the status line | V | V | V | `test_curselive.py::test_the_status_line_reads_through_the_unchanged_party_fix`; `docs/121` §5 — and it **lags** on SSB |
| C4 | party fix from memory (the fallback) | V | V | V | `test_automap.py::test_the_memory_fallback_reads_the_engines_own_triple` — `Game.live_position`, `$C04B` measured on all three (`docs/120` §4, `docs/121` §5). An unmeasured title refuses: `…::test_a_title_whose_live_triple_is_unmeasured_gets_no_fallback` |
| C5 | `Fingerprint` narrows the map from a walk | V | V | V | `test_curselive.py::test_the_walked_route_fits_geo01_and_narrows_sixteen_maps_to_two`, `test_ssblive.py::test_every_step_the_party_completed_crossed_a_passable_edge` |
| C6 | area identification across a boundary | V | V | V | **Measured on all three (`docs/212-the-live-tab-per-title.md`, 2026-09-08, `tools/livecheck.py`)**: `automap.actions.FastTravel` carried the party across, the block at `$0400` changed to the arriving area's map and `AutomapState.area` followed it — `GEO00`→`GEO01`, `GEO01`→`GEO03`, `GEO10`→`GEO20`. The **save image's own area byte does not follow**, on any of the three, twenty seconds after the arrival: the resident image is a copy the engine rewrites when it saves, which is why the mapper identifies an area from `$0400` and not from the header |
| C7 | map drawing, reveal, exploration | V | V | V | **Drawn from a running machine on all three (`docs/212-the-live-tab-per-title.md`, 2026-09-08, `tools/livecheck.py`)**, which nothing had done for Curse or Silver Blades. `Automapper.poll()` identified the area by an exact byte match of `$0400` against the disks, `title_check` came back `ours`, and the marker followed a four-key walk — 4 of 4 steps agreeing with the game's own status line on the square and the facing, on each title. The drawn map goes out as SVG through `automap.render.to_svg`, whole and explored-only |
| C8 | area names on the map | V | — | — | `goldbox/areas.py:334` — `GEO_NAMES` is empty for Curse on purpose and absent for SSB; `area_name` degrades to `"area 15"`. Correct behaviour, no content |
| C9 | map notes and exploration, persisted | V | V | V | `test_automap.py::test_a_note_on_one_titles_geo15_is_absent_from_anothers` — the path is `{data dir}/maps/{title}/{GEO id}.json` (#30 (Notes and explored squares leak between titles)), three distinct paths for one map id. Pre-split files migrate: `…::test_a_flat_notes_file_is_still_readable_after_the_split` |
| C10 | combat view | V | **U**, expected broken | **U**, expected broken | `automap/combat.py` holds `$6E11`, `$0600`, `$A380` — PoR's combat overlay. Only the first of those is known for the later titles (`$7F11`, #29 (The live reader uses Pool of Radiance's addresses on every title)), and it is deliberately **not** threaded through here: making the view open on Curse would only let it draw the other two addresses' garbage. Curse ships no `SQRPACI`/`SQRDATA` at all (`docs/120` tier 1.1) |
| C11 | combat log | V | **U**, expected broken | **U**, expected broken | `automap/combatlog.py` is built on `COMBAT $2983`, a PoR address in a PoR overlay |
| C12 | live roster cards (HP, XP, AC, THAC0, readied) | V | V | V | **Crossed against the file on all three** (`docs/212-the-live-tab-per-title.md`, 2026-09-08): every card `live.read_snapshot` built was compared with the same save read cold through `goldbox.savegame.load_save` -- name, maximum hit points and experience, 18 of 18 fields on each title, 0 disagreements. A matching name from one reader is the reader agreeing with itself. `test_automap.py::test_a_curse_machine_is_read_at_4b00_and_not_4900` and `…::test_curses_roster_comes_from_6700_inside_the_payload` (#29 (The live reader uses Pool of Radiance's addresses on every title)) — **and both have now been read for real**: Curse's BRUTUS/MAGNUS/LADY KATHERINE and Silver Blades' six, names and hit point maxima matching each game's own panel (`docs/120` tier 3, `docs/121` §4). One hazard fell out: while a full-screen picture is up the roster page is scrap and the cards read zeroes — issue #82 (The live roster reads graphics data while a full-screen picture is up on Silver Blades). **This row said V for XP on all three and was wrong for two classes**: `automap/live.py:_classes` walked the classic four, so a Curse paladin and a Silver Blades ranger got no class name and no experience bar at all -- `#197 (A Curse or Silver Blades paladin or ranger has no class and no experience bar on its roster card)`, fixed by walking `Game.class_bits` instead. The abbreviations `MU/F/C/T` have no counterpart for paladin, ranger or knight, so those show the class's own name until Donald chooses letters. `test_pertitle_live.py` |
| C13 | condition badges | V | V | **R** | rides C12. **A badge has now been drawn (`docs/212-the-live-tab-per-title.md`, 2026-09-08, `tools/livecheck.py`)**: no save this project holds, on any title, has a spell running, so one effect row was staged into the four arrays the way the game writes one — effect 39, hasted, the one glyph covering exactly one id — and Pool of Radiance and Curse each drew `running-ninja` on the card. **Silver Blades drew none and the id turned up in `Character.unbadged_effects`**, which is the refusal below measured rather than assumed. **Closed by #196 (The automapper's condition badges name a Silver Blades trait with Pool of Radiance's meaning)**: `badges()` called `traits.describe(i)` with no title, so a Silver Blades card named Pool of Radiance's spell -- and the badge *groups* were Pool of Radiance's ids besides, which is the same error one level up. `automap/live.py:BADGE_TABLES` is per title now: Curse keeps Pool of Radiance's, because it keeps its trait table (this row rides A15), and **Silver Blades draws none** -- sixteen of the seventeen badged ids are unnamed in its own table, so a glyph there would assert a meaning nobody has read. R rather than U for SSB: the refusal is deliberate and tested, and `Snapshot.unbadged_party_effects` still puts every one of them in the debug log. `test_pertitle_live.py`, eight badge tests of fifteen. `docs/136-condition-badges.md` |
| C14 | quickfight badge | V | V | V | rides C12. `quickfight_flag` resolved to `$670C` on both live machines (#29 (The live reader uses Pool of Radiance's addresses on every title)) and nobody was ever on quickfight, so the bit had never been seen set. **Staged and read on all three (`docs/212-the-live-tab-per-title.md`, 2026-09-08, `tools/livecheck.py`)**: roster `+0x0C` bit 7 written from outside, `Character.quickfight` reading it back True — which is the badge a card draws — and `ClearQuickfight` putting it out again |
| C15 | the Quest Log | V | — | — | `goldbox/commissions.py:67` is the Council of Phlan's ledger at `$4A20`; the other titles have no such thing |
| C16 | heal party | V | V | V | Addresses and gate both done (#29 (The live reader uses Pool of Radiance's addresses on every title)). `Member.record_base`/`item_base`/`roster_base` come off the descriptor -- `test_actions.py::test_every_address_a_curse_action_would_write_is_curses_own` -- and `Game.mode_flag` is `$7F11` on both later titles, `…::test_curses_gate_is_read_at_its_own_linker_byte_and_not_pool_of_radiances`. **V for Silver Blades because it was done to a real party**: `HealParty` wrote `$6719`/`$6739` on a live machine and MORGAINE and MALACHITE came back to 35/35 and 58/58 (`docs/121` §4). On Curse the same call ran and legitimately had nothing to heal, so the write half is untried there. The combat gate was exercised for real on Silver Blades: `1` -> `4` -> `2` on a wandering encounter, `heal` legal, `identify` refused |
| C17 | store / restore spells | V | V | V | rides C16. **Done on all three (`docs/212-the-live-tab-per-title.md`, 2026-09-08, `tools/livecheck.py`)**: `StoreSpells` saved the list, the span was zeroed first so a matching read-back could not be the store's own copy coming home, and `RestoreSpells` put it back byte for byte. Curse's party carries no memorised spell at all, so one id was staged into the span — neither action goes through the engine, so an id put there from outside is the input a night's rest leaves |
| C18 | identify items | V | V | V | rides C16; the payload offset comes off `Game.save_load_address` and the gate is measured (#29 (The live reader uses Pool of Radiance's addresses on every title)). **Done on all three (`docs/212-the-live-tab-per-title.md`, 2026-09-08, `tools/livecheck.py`)**, an item's hidden-name bits staged and then cleared by the action, and the byte read again four seconds of emulated time later through `live.read_blocks` — the write stuck on every title, which the action's own docstring said was not certain |
| C19 | clear quickfight, and the watcher | V | V | V | rides C16 and C14; `actions.quickfight_flag(game)` builds the address from `Game.roster_base` and read `$670C` on both live machines -- `test_actions.py::test_the_quickfight_flag_follows_the_roster_page`. **A staged bit was cleared by the button on all three (`docs/212-the-live-tab-per-title.md`, 2026-09-08, `tools/livecheck.py`)**. The *watcher* -- `QuickfightWatcher.poll` firing on the edge -- is still untried on any title |
| C20 | **Level Up** | V | V | **R** | **This row said `R` for Curse and that stopped being true when #18 (Measure Curse's trainer so Level Up works there) closed**: `goldbox.levels.trainer_measured` answers True for Curse now and `test_debugmode.py` asserts `curse.roster.levelling`, so the button is built and offered there. Silver Blades still refuses, and the refusal was **measured rather than assumed** (`docs/212-the-live-tab-per-title.md`, 2026-09-08, `tools/livecheck.py`): the action answers *legal*, because `Action.legality` only asks the loader's mode flag, and what refuses is `level_up_blockers` inside `run` -- so the check ran it and read back `levelling MORGAINE would write fields we cannot derive, so it writes nothing`, 0 writes. `test_levels.py::test_only_pool_of_radiances_trainer_has_been_measured` is stale in its name rather than its content. Closed for Curse by #16 (Level Up assumes Pool of Radiance, and silently corrupts a Curse character) and #18 (Measure Curse's trainer so Level Up works there) |
| C21 | **Fast Travel** and Travel Back | V | V | V | **This row said `R` for both later titles and no longer holds.** `fasttravel_bar.has_areas` is true for all three now -- #19 (Can Curse be fast-travelled at all, or is the mechanism Pool of Radiance's alone?) and #20 (Build an area table for Silver Blades) built the tables, and `test_debugmode.py:1145` asserts it for Curse. **Watched on all three (`docs/212-the-live-tab-per-title.md`, 2026-09-08, `tools/livecheck.py`)**: `FastTravel.apply` carried a party across a boundary in each, and C6 is the reading either side. Travel Back itself is still untried on any title. Closed by #14 (Fast Travel offers Pool of Radiance's areas in a Curse session) |
| C22 | the *running* title is **checked against** the machine | V | V | V | issue #21 (The running game is guessed from a preference, so both title safeguards can fail open), closed. `ResidentGeo.verdict` asks whether the block at `$0400` is one of the believed title's own maps; a Gold Box map that is none of them takes Level up, Fast Travel and every live-action button off and says so. `tests/test_wronggame.py` — the thresholds are re-measured off the player's own disks, and C2 is what makes the ingredient V on all three |

### D. The application shell

| # | feature | PoR | COAB | SSB | evidence |
|---|---|---|---|---|---|
| D1 | Preferences: disks folder, and the report of what was found | V | **U** | **U** | `#22 (A disk folder setting per game, not one shared by all six)`: Curse and Silver Blades each have their own folder row now, on the Game disks tab, and the report reuses the shared box's own wording -- built and tested in `tests/test_preferences.py`, not yet exercised against a live machine on either title, which is what keeps this U. The shared box itself is gone: `#357 (The automapper reads the shared Game disks folder, so setting a title's own folder does not make it map that title)` removed it, since it could still answer for the wrong title with no save open |
| D2 | Preferences: the Fast Travel tick table | V | — | — | built straight off `goldbox/areas.py:AREAS`, which is PoR's alone |
| D3 | backend selection, VICE | V | V | V | title-independent; exercised by every live test |
| D4 | backend, Commodore 64 Ultimate | **U** | **U** | **U** | `wish/ultimate.py` — "UNVERIFIED. Nobody on this project has the hardware", and `Backend.verified` is False |
| D5 | debug log and debug mode | V | V | V | title-independent — `test_debuglog.py`, `test_debugmode.py` |

### Headline

| | features | V | R | U | X | — |
|---|---|---|---|---|---|---|
| Pool of Radiance | 49 | **48** | 0 | 1 | 0 | 0 |
| Curse of the Azure Bonds | 49 | **38** | 0 | 6 | 0 | 5 |
| Secret of the Silver Blades | 49 | **36** | 2 | 6 | 0 | 5 |

**These numbers are counted from the rows above and the previous ones were
not.** Counting `V (gold only)` under A8 and the two `U, expected broken`
cells under C10 and C11 as `U`, which is what they are, every row is in
exactly one column and each title's five add to 49.

**`#34 (Validate the live automapper tab per title)` moved ten cells for
Curse and seven for Silver Blades** on 2026-09-08 -- C6, C7, C13, C14 and
C16-C19 to `V` on both, plus C20 and C21 for Curse and C21 for Silver Blades
where the rows were stale. `docs/212-the-live-tab-per-title.md` is the run;
`tools/livecheck.py` is how it is re-taken. Two of Curse's and both of Silver
Blades' `R` cells before that were **stale rather than wrong at the time**:
`#18 (Measure Curse's trainer so Level Up works there)` closed C20 for Curse,
and `#19 (Can Curse be fast-travelled at all, or is the mechanism Pool of
Radiance's alone?)` and `#20 (Build an area table for Silver Blades)` closed
C21 for both, with nobody returning to these rows.

**What is left is five cells for Curse and five for Silver Blades**, and they
are not the live tab: A8 (the six purses beyond gold), C10 and C11 (the combat
view and log, ruled out by G7), D1 (Preferences against a live machine) and
D4 (the Ultimate backend, which nobody can test).

**A13 was the sixth until 2026-09-08**, when `tools/inventorycheck.py` staged a
remove, an edit and an add on one character of each later title and read all
three off the game's own `EQUIPPED ITEM` screen. Its stated blocker had been
out of date for four days on Curse and had never been true on Silver Blades:
`WISH-SPEC-curse-party-with-items` was made on 2026-09-04 by
#32 (One Curse session, to get a party with items), and Guy de Valois on
`WISH-SPEC-ssb-d-engine-resave` has carried twelve items since that specimen
was made on 2026-09-05.

**A17-A20 were on that list until 2026-09-08**, when
#33 (One Silver Blades session, for the whole editor path) took all four on
`WISH-SPEC-ssb-d-engine-resave` — the C64 engine's own save — and §3 G5's
premise went with them: the blocker it named, "a save the game itself wrote",
had already been met on 2026-09-05 by
#193 (Convert a Secret of the Silver Blades DOS save into a C64 one, which the
importer refuses today), and nobody had returned to the row.

#31 (Cold-read Curse and Silver Blades for the fields the editor shows) moved eight of them, all by reading files this project already opens:
A9 and A14 to `V` for Curse, A10, A12 and A14 to `V` for Silver Blades, A15 to
`V` for Curse, and A16 to `V` for both after the row was corrected to say what
it is about. A6 and A7 stayed `U` for Silver Blades at that point, with every
number they need measured and written down but no `LevelTables` in
`goldbox/levels.py` to show it from; #187 (Silver Blades characters are shown Pool of Radiance's level progression) built one and moved both to `V`.

Curse and Silver Blades each gained two `V` (C4, C9) and turned three `X` into
`U` (C12–C14) when #29 (The live reader uses Pool of Radiance's addresses on every title) and #30 (Notes and explored squares leak between titles) landed, and a third when #21 (The running game is guessed from a preference, so both title safeguards can fail open) closed C22. The
second half of #29 (The live reader uses Pool of Radiance's addresses on every title) turned the last four `X` -- the live actions -- into `R`:
every address they write is the descriptor's now, and the one address that
cannot be derived, the loader's mode flag, is unmeasured on both titles, so the
buttons refuse and say so.

**Silver Blades briefly had one `X` again** -- A15's trait codes are not Pool
of Radiance's, so the character sheet named four of its six races' abilities
wrongly all along and nobody had looked. #186 (The character sheet gives a Silver Blades elf a Pool of Radiance ability) closed it with a table per title,
and the three codes nobody has read show their number rather than another
title's sentence. Curse has none. Pool of Radiance's one `U` is the Ultimate
backend, which nobody can test.

**C22 was never what made the live actions safe.** It covers the case the
window has the title *wrong* -- a machine running a game the disks folder does
not name loses those buttons entirely. What made them safe on a machine
correctly identified as Curse is C16-C19 above: the addresses follow the
descriptor, and the missing gate is a refusal rather than a guess.

### What the README is promising that is not backed

Read against the feature list in `README.md` itself:

| the README says | for Curse | for Silver Blades |
|---|---|---|
| "Reveals the area map as you explore" | holds — the status line and `$0400` both transfer | holds |
| "Pin notes to the map" | holds — the file is `{data dir}/maps/{title}/{GEO id}.json` (C9) | holds |
| "Combat view that shows the whole battlefield" | **not backed** — PoR overlay addresses (C10) | **not backed** |
| "Party stats. HP, XP, AC, THAC0, readied items" | holds — six cards read off a running Curse and crossed against the same save read cold, 18 of 18 fields (C12) | holds, on the same reading |
| "Quest log. Shows what commissions you have from the council" | **not applicable** — Phlan's council only (C15) | **not applicable** |
| "Update your stats … Spells … Inventory … Combat Icon Editor" | mostly holds; inventory and the icon charset unverified (A13, A14) | holds for the sheet; **the write-back path itself is unverified** (A17, A18) |

**Four of the five automapper bullets hold on all three titles now.** The
live actions under "Party stats" were the one that did not, and they were
watched on each title on 2026-09-08 (C16-C19,
`docs/212-the-live-tab-per-title.md`). What is left in this table is the
combat view, which G7 rules out, and the Quest Log, which is Phlan's council
and does not exist in the other two.

## 3. How the unverified cells would be tested, grouped

Grouped by what they share, so each group is one sitting.

### G1 — a cold read of the Curse and Silver Blades disks · no emulator

**Done (#31 (Cold-read Curse and Silver Blades for the fields the editor shows)), six cells of the eight.** `tools/coldread.py` is what it produced
and `tests/test_coldread.py` is what keeps it true; the six answers are below,
with the two that did not close.

* `CHARPIC00` — **on all twenty sides of the three titles**, 2030 bytes every
  time. Curse's is Pool of Radiance's byte for byte and Silver Blades redraws
  three glyphs of 253. A14 for both.
* `ITEMS` — **Silver Blades decodes to AD&D on 42 of 43 named items**, against
  its own `ITEM<nn>` template lists rather than another title's indices, which
  are renumbered. A12.
* Spell names — **already done** in `goldbox/spells.py` when this was written,
  with four tests. A10.
* Curse's spellbook width — **13, and not from a `GEN` clear loop**, which
  Curse does not have. `CAMP $2A25` walks spell ids to 100 and indexes the mask
  at byte 12. A9.
* Trait codes — **the seeding is per title and so is the namespace.** Curse's
  codes are Pool of Radiance's; Silver Blades' are not, which made A15 an `X`
  for that title and #186 (The character sheet gives a Silver Blades elf a Pool of Radiance ability) a bug a user could see. Closed: the table is per
  title now, and a Silver Blades code nobody has read shows its number.
* The effect arrays — **all four at the same payload offsets in all three**,
  from `CAMP`'s and `DUNGEON`'s own loops rather than from a shipped party,
  which is all zeroes. A16, whose row also needed correcting.

**A6 and A7, closed by #187 (Silver Blades characters are shown Pool of
Radiance's level progression).** Every Silver Blades table those cells need
was read and written into the matrix rows above during #31 (Cold-read Curse and Silver Blades for the fields the editor shows), and the
saving-throw rule reproduces all six shipped characters; what was missing was
a `LevelTables` for the title in `goldbox/levels.py`, which #187 (Silver Blades characters are shown Pool of Radiance's level progression) built --
`SECRET_OF_THE_SILVER_BLADES`, checked row by row against `GEN` in
`tests/test_coldread.py` and `tests/test_ssblevels.py`. Its trainer stays
unread (thief-skill racial adjustment, constitution hit-point bonus, wisdom
bonus spells, turning table), so `levels.trainer_measured` and
`goldbox/levelup.py:plan` still refuse it.

### G2 — thread the save geometry into the live reader · code, no emulator

**Done (#29 (The live reader uses Pool of Radiance's addresses on every title))**, for the reader. `live.memory_blocks(game)` and `party_fix(read,
game)` take every address from the `Game` descriptor, and the live party triple
is `Game.live_position` — `$C04B`, measured on Pool of Radiance, Curse and
Silver Blades and None on the other three, which refuse rather than guess.
Closed C4 and moved C12–C14 from `X` to `U`.

**Also done (#29 (The live reader uses Pool of Radiance's addresses on every title)): `automap/actions.py`.** `Member` and `read_party` take the
descriptor, so the slot area, the item area and the roster page all follow
`save_load_address`; `live.BLOCKS` is gone with its last caller. `ActionBar`
takes a game and the window hands it the one it resolved, alongside the Fast
Travel row and the Level up button.

**One address in that file does not follow the save image, and it used to stop
the buttons.** The flag every action reads before it writes, because `2` is
combat, is a byte of `LINKER`'s own resident page. It is now measured on three
titles: `$6E11` in Pool of Radiance, **`$7F11` in Curse and Silver Blades**,
read out of `LINKER`'s own first instruction and confirmed live at `$2D00` in
both (#29 (The live reader uses Pool of Radiance's addresses on every title)). Their overlay name tables are the same table entry for entry, so
`2` is COMBAT in all three. `Game.mode_flag` is None only on the three
Krynn-era titles now, and an action whose title has None still refuses rather
than write with no way to see a fight.

### G3 — namespace the notes by title · code, no emulator

**Done (#30 (Notes and explored squares leak between titles))**, closing C9. `AutomapState.notes_path` is
`{data dir}/maps/{title}/{GEO id}.json`, keyed by `Game.key`, and the fog-of-war
record moved with it because it is in the same file.

`state.migrate_flat_notes` moves what already exists, **attributed rather than
assumed**: a flat file is filed under Pool of Radiance only if its stem is one
of the twenty-nine maps Pool of Radiance ships, it never overwrites a file
already there, and anything it cannot attribute is left exactly where it is
under no title at all.

### G4 — one Curse session: a played party with an inventory

Closes A13 for Curse, and the Curse half of `docs/120`'s remaining blockers.

Play far enough to pick something up, save, then: open the save in the editor,
read the item records, add one, remove one, write back, load it in the game and
read the inventory off the game's own screen. One emulator sitting. This is the
only thing that will ever produce a Curse item specimen.

### G5 — one Silver Blades session: the whole file path · **done 2026-09-08**

Closed A17, A18, A19, A20 for SSB — four of its nineteen `U`s, and the four
that matter most, because they are the ones the README's editor bullets rest on.
`#33 (One Silver Blades session, for the whole editor path)` is the ticket and
carries the runs.

**Its premise was already out of date when it was written here.** This section
said everything SSB had came from `SAVEDBASH`, a shipped demo party, so the
work had to start by playing far enough to save. It did not:
`#193 (Convert a Secret of the Silver Blades DOS save into a C64 one, which the
importer refuses today)` left `WISH-SPEC-ssb-d-engine-resave` in the specimen
tree on 2026-09-05 — the C64 engine's own `ENCAMP > SAVE` — and `#344 (A
converted Silver Blades dwarf, gnome or halfling keeps DOS's saving throws,
because that title's racial bonus has never been watched in the game)` left a
second on 2026-09-06. Six engine-written Silver Blades disks were there before
anybody started.

What was run, on that specimen:

* **A17 and A18 with no emulator** — `EditorBinding.save` on an untouched save
  says `no changes` and moves no byte, and a YAML export re-imported comes back
  a byte-identical disk. `tests/test_ssbeditorpath.py`.
* **A19 in both directions**, each refusal naming both titles.
* **A20 in VICE, pool slot 3.** Three fields of different kinds edited through
  the editor — name `MORGAINE` → `BRIGHID`, gold 0 → 4321, strength 17 → 12 —
  and all three read off the game's own screens. `docs/120` §5.2's third field
  was current hit points; Silver Blades keeps that in the roster block rather
  than the 256-byte save slot, so an ability score took its place.
  `tools/ssbedit.py` is the run.

**One thing came out of it that is not a Silver Blades finding.** Curse and
Silver Blades keep the party's names again at payload `+$C00`, and the editor's
save path writes only the 256 bytes of each slot — so a rename leaves that
table holding the old name. The party panel, the `VIEW WHICH CHARACTER?` list
and the sheet all drew the new one, so nothing a player was shown was wrong;
`#435 (A rename in Wish leaves the C64 name table holding the old name on Curse
and Silver Blades, and nobody knows what reads it)` carries the four `GEN` code
sites that do read it and the experiment that would say whether it ever shows.

### G6 — one Curse and one Silver Blades session for the live tab · needs G2

Closes C6, C7, C12–C19 for both titles — twenty cells between them, and they
share one prerequisite and one kind of run.

**Part of it is done (#29 (The live reader uses Pool of Radiance's addresses on every title)).** The mode flag — the loader's dispatch byte, which
is what the five action buttons gate on — is `$7F11` on both later titles, and
it did not need a differential read at all: it is the absolute operand of
`LINKER`'s own first instruction and can be taken off the disk. With it in
`goldbox/games.py` the four `R` cells stop refusing, and one sitting per title read
a real party through the shipped code, which is C12. Silver Blades' heal was
done to a real wounded party, which is C16 for that title.

**Done, on 2026-09-08 (`docs/212-the-live-tab-per-title.md`).** One driven
session per title through `tools/livecheck.py`, which calls the tab's own code
rather than reproducing it: ten checks each, thirty passes, no failures. The
map drew and the marker followed a walk (C7); Fast Travel carried the party
across a boundary and the block at `$0400` and `AutomapState.area` both
followed while the save image's own area byte did not (C6); a staged effect
lit a badge on Pool of Radiance and Curse and correctly lit none on Silver
Blades (C13); the quickfight bit was staged and cleared on all three (C14,
C19); and Heal party, Save/Restore spells and Identify each did their work and
were read back (C16-C18).

**What made three of those reachable was staging the situation**, because the
corpus does not carry it: no save here has a character on quickfight, an
unidentified item, or a spell running. The staged byte is the input and the
button's own code is what is measured -- the alternative is a run that reports
"nothing to do" and calls it a pass.

The gate is done for Silver Blades — a wandering encounter 228 steps out of
New Verdigris took the flag `1` → `4` → `2` and the three combat-illegal
actions refused as they should. Curse has still never been watched in a fight;
three sessions of walking and camp resting produced none, and a Pool of
Radiance run that walked out of the Slums found one in four steps, which is
where the ordering of `tools/livecheck.py`'s checks came from.

### G7 — decide what the combat features mean on a later title

C10, C11, C15. Curse ships no `SQRPACI`/`SQRDATA` and its `COMBAT` is a
different build, so re-deriving those addresses is a project, not a check —
`docs/120` "Out of scope" already ruled it out and that ruling still looks
right. The work here is therefore **labelling, not measuring**: the combat view,
the combat log and the Quest Log should say which title they are for and
show nothing rather than garbage on the others, the way Fast Travel now does.

### G8 — already tracked elsewhere

| cell | issue |
|---|---|
| C20 for Curse, the trainer measurement | #18 (Measure Curse's trainer so Level Up works there) |
| C21 for SSB, an area table | #20 (Build an area table for Silver Blades) |
| C21 for Curse, whether the mechanism exists at all | #19 (Can Curse be fast-travelled at all, or is the mechanism Pool of Radiance's alone?) |
| D1, a disks folder per title | #22 (A disk folder setting per game, not one shared by all six) |
| D4, the Ultimate backend | needs hardware nobody here has |

## 4. What this document is not

* **Not a release checklist.** `docs/122` is that, and it is per-platform.
* **Not a decoding plan.** `docs/120` and `docs/121` are those, per title, and
  they remain correct about what they cover.
* **Not a promise to support the other three titles.** `goldbox/games.py` carries
  Champions of Krynn, Death Knights of Krynn and Gateway to the Savage Frontier
  because the geometry table is cheaper complete than partial. `README.md` does
  not name them and this document does not either.
* **Not a plan to reverse-engineer the later titles' combat.** G7 is the
  decision to label rather than measure, and it is deliberate.
