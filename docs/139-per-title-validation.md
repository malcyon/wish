# Validating every feature on every title we claim

`README.md` promises Pool of Radiance, Curse of the Azure Bonds and Secret of
the Silver Blades. This document says, feature by feature, what that promise is
actually backed by — and what it would take to back the rest.

## 0. The four answers, up front

| question | answer | grade |
|---|---|---|
| Does a test plan for this exist? | **No.** `docs/120` and `docs/121` are *decoding* plans for a second and third title; `docs/122` is packaging. Nothing enumerates the shipped features against a title | CONFIRMED, read |
| Is `skills/goldbox/SKILL.md` that plan? | **No.** It is the recipe for decoding a title the project has not done yet. Its nineteen steps end at "a mapper you can believe" and never mention the editor, the CLI, the live actions, Fast Travel or Level Up | CONFIRMED, read |
| How much of the README promise is verified? | **49 features. Pool of Radiance 47 verified, Curse 23, Silver Blades 15.** §2 | CONFIRMED, cited per row |
| Where is the promise thinnest? | **The live actions.** The *reader* is per-title now (#29): `automap/live.py` takes every address from the `Game` descriptor and `automap/target.py` reads the engine's measured `$C04B` triple. `automap/actions.py` was not threaded with it, so the five buttons still write Pool of Radiance's `$4900`/`$8300` on every title — not refusing, writing it | CONFIRMED, `automap/actions.py:151`, `:482`, `:742` |

The honest one-line version: **the file path works on three titles, the live
*reader* now works on three, and the live *writes* work on one.**

## 1. How far out of date `docs/120` and `docs/121` are

Both are sound about what they cover. Both cover a much smaller program than
the one that now ships.

| | `docs/120` (Curse) | `docs/121` (Silver Blades) |
|---|---|---|
| written against | the editor, the CLI and the automapper's map | the same, plus `por/games.py` |
| "the editor" means | the character sheet, inventory, icons, YAML | the shipped party decoding |
| "the automapper" means | `Geo`, `ResidentGeo`, `party_fix`, `Fingerprint` | the same five |
| never mentions | Fast Travel, Level Up, the commissions panel, the combat log, the combat view, condition badges, the quickfight badge, map notes, the roster cards, the live actions (heal, store/restore spells, identify), Preferences, the debug log, the DOS converter | all of the same, plus the whole editor UI |

Ten shipped features are absent from both documents. `docs/120`'s tier 4 is a
five-row table of the automapper; the automapper tab today has fifteen rows in
§2 below.

Two specific corrections they already earned and have not had:

* `docs/120` tier 4 listed the memory fallback as "does not transfer" and left
  it there, so it shipped as a defect on two titles. **Closed by #29**: the
  triple is `Game.live_position`, measured per title, and a title where it is
  unmeasured refuses instead of guessing.
* `docs/121` §6 lists eight edits the run owes `SKILL.md` and says they were
  not made because the file was another agent's. Seven of the eight are still
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
| A6 | saving throws satisfy the derived rule | V | V | **U** | `test_curselevels.py::test_curse_matches_ssis_own_pregenerated_party`; `por/levels.py` has no Silver Blades tables at all |
| A7 | experience thresholds, ceilings, THAC0, hit dice | V | V | **U** | `test_curselevels.py::test_curse_experience_is_the_games_own_table` and six neighbours; nothing for SSB |
| A8 | the seven money fields | V | V (gold only) | **U** | `docs/120` §5.2 — gold `0` → `777` read back off the game's own sheet; the other six purses untested on any title but PoR |
| A9 | spellbook width | V | **U** | V | `test_silverblades.py::test_a_silver_blades_caster_writes_past_pool_of_radiances_spellbook`; `docs/120` blockers — no Curse specimen writes past `0x07C` |
| A10 | spell names resolve | V | V | **U** | `test_curselevels.py::test_curse_reads_its_names_out_of_combat2`; SSB's two tables are inventoried (`test_silverblades.py::test_silver_blades_ships_two_spell_name_tables`) and never resolved |
| A11 | item names resolve | V | V | V | `test_titletables.py::test_every_title_names_its_first_item_battle_axe` — all six titles |
| A12 | item **types** (`ITEMS`) decode to damage/AC/usage | V | V | **U** | `test_second_game.py::test_curse_item_types_are_the_same_table_with_ranger_added`; SSB is shape-only (`test_silverblades.py::test_the_item_table_is_a_whole_number_of_sixteen_byte_records`) |
| A13 | inventory edit, add, remove | V | **U** | **U** | `docs/120` blockers: "no Curse save from a *played* party with inventory … no Curse item record has ever been seen" |
| A14 | combat icon editor and its charset | V | **U** | **U** | `por/icons.py:95` reads `CHARPIC00`; nothing has checked that file exists, or is the same charset, on either later title |
| A15 | character traits panel (`0x0AD`–`0x0B6`) | V | **U** | **U** | trait codes were read on PoR; `docs/121` §4.1 shows the SSB import re-seeding `0x0AD` from **its own** per-race table, so the codes are per-title |
| A16 | active effects panel | V | **U** | **U** | `docs/133`; the effect arrays were read at `$4900` in PoR and never looked for elsewhere |
| A17 | an unchanged save writes back byte-identically | V | V | **U** | `test_curse.py::test_the_editor_writes_a_curse_save_back_unchanged`; no SSB equivalent |
| A18 | YAML export → import → byte-identical disk | V | V | **U** | `test_curse.py::test_a_curse_save_disk_survives_yaml_byte_for_byte`; SSB has no save disk in the tests, only the shipped `SAVEDBASH` party |
| A19 | a save of one title refuses to import into another | V | V | **U** | `test_curse.py::test_a_curse_party_will_not_import_into_a_pool_of_radiance_disk` and its mirror; SSB in neither direction |
| A20 | an edited field appears in the running game | V | V | **U** | `docs/120` §5.2 — name, gold and current hit points, all three read off Curse's own screens |

### B. The DOS converter

| # | feature | PoR | COAB | SSB | evidence |
|---|---|---|---|---|---|
| B1 | read a DOS save | V | — | — | `test_dossave.py`, `test_dosconvert.py`; `docs/117` narrowed the goal to DOS Pool of Radiance, one direction |
| B2 | convert a DOS save into a C64 one | V | — | — | issue #6, closed: the converted disk loads and the party walks |

### C. The automapper — needs a live machine

| # | feature | PoR | COAB | SSB | evidence |
|---|---|---|---|---|---|
| C1 | `GEO` decode, verified by reciprocity | V | V | V | `test_curse.py::test_every_curse_map_decodes_through_the_unmodified_decoder`, `test_silverblades.py::test_all_seventeen_maps_decode_through_the_unmodified_decoder` |
| C2 | resident map block at `$0400` | V | V | V | `test_curselive.py::test_the_resident_map_block_is_at_0400_in_curse_too`, `docs/121` §5 |
| C3 | party fix from the status line | V | V | V | `test_curselive.py::test_the_status_line_reads_through_the_unchanged_party_fix`; `docs/121` §5 — and it **lags** on SSB |
| C4 | party fix from memory (the fallback) | V | V | V | `test_automap.py::test_the_memory_fallback_reads_the_engines_own_triple` — `Game.live_position`, `$C04B` measured on all three (`docs/120` §4, `docs/121` §5). An unmeasured title refuses: `…::test_a_title_whose_live_triple_is_unmeasured_gets_no_fallback` |
| C5 | `Fingerprint` narrows the map from a walk | V | V | V | `test_curselive.py::test_the_walked_route_fits_geo01_and_narrows_sixteen_maps_to_two`, `test_ssblive.py::test_every_step_the_party_completed_crossed_a_passable_edge` |
| C6 | area identification across a boundary | V | **U** | **U** | `docs/120` tier 3 — no boundary was crossed, the area byte stays PROBABLE; `docs/121` §5 — the party never left `GEO10` |
| C7 | map drawing, reveal, exploration | V | **U** | **U** | pure `Geo`, so it ought to transfer; nothing has drawn a Curse or SSB map in the shipped window |
| C8 | area names on the map | V | — | — | `por/areas.py:334` — `GEO_NAMES` is empty for Curse on purpose and absent for SSB; `area_name` degrades to `"area 15"`. Correct behaviour, no content |
| C9 | map notes and exploration, persisted | V | V | V | `test_automap.py::test_a_note_on_one_titles_geo15_is_absent_from_anothers` — the path is `{data dir}/maps/{title}/{GEO id}.json` (#30), three distinct paths for one map id. Pre-split files migrate: `…::test_a_flat_notes_file_is_still_readable_after_the_split` |
| C10 | combat view | V | **U**, expected broken | **U**, expected broken | `automap/combat.py` holds `$6E11`, `$0600`, `$A380` — PoR's combat overlay. Curse ships no `SQRPACI`/`SQRDATA` at all (`docs/120` tier 1.1) |
| C11 | combat log | V | **U**, expected broken | **U**, expected broken | `automap/combatlog.py` is built on `COMBAT $2983`, a PoR address in a PoR overlay |
| C12 | live roster cards (HP, XP, AC, THAC0, readied) | V | **U** | **U** | the addresses are right now — `test_automap.py::test_a_curse_machine_is_read_at_4b00_and_not_4900` and `…::test_curses_roster_comes_from_6700_inside_the_payload` (#29). No real Curse or SSB roster has ever been read through it; that is G6 |
| C13 | condition badges | V | **U** | **U** | rides C12 |
| C14 | quickfight badge | V | **U** | **U** | rides C12 |
| C15 | commissions panel | V | — | — | `por/commissions.py:67` is the Council of Phlan's ledger at `$4A20`; the other titles have no such thing |
| C16 | heal party | V | **X** | **X** | `automap/actions.py` was not threaded through the descriptor with `live.py`: `Member.record_base`/`roster_base`/`item_base` are `$4D00`/`$8300`/`$5900` and `read_party` calls `live.read_blocks(target)` with no game. It reads and **writes** Pool of Radiance's addresses on every title |
| C17 | store / restore spells | V | **X** | **X** | rides C16 |
| C18 | identify items | V | **X** | **X** | rides C16 — `live.BLOCKS[0][0]` at `automap/actions.py:482` |
| C19 | clear quickfight, and the watcher | V | **X** | **X** | rides C16 — `QUICKFIGHT` is built on `SAVE1_LOAD_ADDRESS`, `automap/actions.py:742` |
| C20 | **Level Up** | V | **R** | **R** | `test_levels.py::test_only_pool_of_radiances_trainer_has_been_measured`, `test_actions.py` line 296, `test_debugmode.py` line 782. Closed by #16 |
| C21 | **Fast Travel** and Travel Back | V | **R** | **R** | `test_debugmode.py` lines 789–795 — `warp_bar.has_areas` is true for PoR and false for Curse. Closed by #14 |
| C22 | the *running* title is identified from the machine | **X** | **X** | **X** | issue #21 — it is guessed from the open save, then a preference, then a default. Both refusals above are only as good as that guess |

### D. The application shell

| # | feature | PoR | COAB | SSB | evidence |
|---|---|---|---|---|---|
| D1 | Preferences: disks folder, and the report of what was found | V | **U** | **U** | one folder setting is shared by all six titles — issue #22 |
| D2 | Preferences: the Fast Travel tick table | V | — | — | built straight off `por/areas.py:AREAS`, which is PoR's alone |
| D3 | backend selection, VICE | V | V | V | title-independent; exercised by every live test |
| D4 | backend, Commodore 64 Ultimate | **U** | **U** | **U** | `wish/ultimate.py` — "UNVERIFIED. Nobody on this project has the hardware", and `Backend.verified` is False |
| D5 | debug log and debug mode | V | V | V | title-independent — `test_debuglog.py`, `test_debugmode.py` |

### Headline

| | features | V | R | U | X | — |
|---|---|---|---|---|---|---|
| Pool of Radiance | 49 | **47** | 0 | 1 | 1 | 0 |
| Curse of the Azure Bonds | 49 | **23** | 2 | 14 | 5 | 5 |
| Secret of the Silver Blades | 49 | **15** | 2 | 22 | 5 | 5 |

Curse and Silver Blades each gained two `V` (C4, C9) and turned three `X` into
`U` (C12–C14) when #29 and #30 landed. The five `X` left on each are the four
live actions and C22, and all five are `automap/actions.py` or the title guess
it depends on.

Pool of Radiance's one `U` is the Ultimate backend, which nobody can test, and
its one `X` is C22, which is everyone's.

### What the README is promising that is not backed

Read against the feature list in `README.md` itself:

| the README says | for Curse | for Silver Blades |
|---|---|---|
| "Reveals the area map as you explore" | holds — the status line and `$0400` both transfer | holds |
| "Pin notes to the map" | holds — the file is `{data dir}/maps/{title}/{GEO id}.json` (C9) | holds |
| "Combat view that shows the whole battlefield" | **not backed** — PoR overlay addresses (C10) | **not backed** |
| "Party stats. HP, XP, AC, THAC0, readied items" | reads the right memory now, and nobody has looked at the result on a running Curse (C12) | same |
| "Quest log. Shows what commissions you have from the council" | **not applicable** — Phlan's council only (C15) | **not applicable** |
| "Update your stats … Spells … Inventory … Combat Icon Editor" | mostly holds; inventory and the icon charset unverified (A13, A14) | holds for the sheet; **the write-back path itself is unverified** (A17, A18) |

One of the five automapper bullets is still wrong for two of the three titles
named in the same file — the live *actions* under "Party stats" — and a third
does not exist for them.

## 3. How the unverified cells would be tested, grouped

Grouped by what they share, so each group is one sitting.

### G1 — a cold read of the Curse and Silver Blades disks · no emulator

Closes A9 for Curse; A6, A7, A10 and A12 for Silver Blades; A14, A15 and A16
for both.

* `CHARPIC00`: is it on a Curse and a Silver Blades side, and is it byte-identical to Pool of Radiance's? One directory walk. If it differs, the icon editor draws the wrong glyphs and A14 becomes an `X`.
* `ITEMS`: decode SSB's 128 records and assert the same fields land in range as Curse's — a copy of `test_second_game.py::test_curse_item_types_are_the_same_table_with_ranger_added` with a third column.
* Spell names: find SSB's table the way Curse's was found in `COMBAT2` — `test_curselevels.py::test_curse_reads_its_names_out_of_combat2` is the recipe.
* Curse's spellbook width: the `GEN` clear-loop scan that settled it for SSB (`docs/121` §3), run against Curse's `GEN`.
* Trait codes: the per-race seed table each title indexes at `0x0AD`. SSB's is partly known already — elf 95, half-elf 18 (`docs/121` §4.1).
* SSB's level tables: experience, THAC0, hit dice, saving throws, ceilings, off the disks. Closes A6 and A7 and is the prerequisite for ever measuring SSB's trainer.

All of it is disk reading, all of it skips cleanly when the player has no disks,
and none of it needs a machine.

### G2 — thread the save geometry into the live reader · code, no emulator

**Done (#29)**, for the reader. `live.memory_blocks(game)` and `party_fix(read,
game)` take every address from the `Game` descriptor, and the live party triple
is `Game.live_position` — `$C04B`, measured on Pool of Radiance, Curse and
Silver Blades and None on the other three, which refuse rather than guess.
Closed C4 and moved C12–C14 from `X` to `U`.

**Not done: `automap/actions.py`.** It reads and writes `$4D00`, `$5900` and
`$8300` as module constants and takes no game, so the five live buttons are
still Pool of Radiance's (C16–C19). Same shape of work, on `Member` and
`read_party` instead of on `live.py`, and it is the last thing between here and
G6.

### G3 — namespace the notes by title · code, no emulator

**Done (#30)**, closing C9. `AutomapState.notes_path` is
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

### G5 — one Silver Blades session: the whole file path

Closes A17, A18, A19, A20 for SSB — four of its nineteen `U`s, and the four
that matter most, because they are the ones the README's editor bullets rest on.

Everything SSB has today comes from `SAVEDBASH`, a *shipped demo party*, not a
save the game wrote. So: save the game, export to YAML, re-import to a new disk
byte-identically, edit one field of each kind (name, gold, current hit points —
the same three `docs/120` §5.2 chose, and for the same reason), load it and read
the answers off the game's screens. The session directory from the `p9` run
already proved the disk-flush hazard; `docs/121` §5 has the list.

### G6 — one Curse and one Silver Blades session for the live tab · needs G2

Closes C6, C7, C12–C19 for both titles — twenty cells between them, and they
share one prerequisite and one kind of run. C12–C14 are ready for it; C16–C19
are not, because G2's second half — `automap/actions.py` — is not done, and
those four buttons **write**.

Attach to each title in turn and, in one pass: draw the map (C7), cross an area
boundary and read the area byte either side (C6 — the negative example `docs/120`
tier 3 says is missing), then check the roster panel shows the party, the badges
match the sheet, and each of the five live actions does what it says. Two
sittings, one per title, after G2 has landed.

### G7 — decide what the combat features mean on a later title

C10, C11, C15. Curse ships no `SQRPACI`/`SQRDATA` and its `COMBAT` is a
different build, so re-deriving those addresses is a project, not a check —
`docs/120` "Out of scope" already ruled it out and that ruling still looks
right. The work here is therefore **labelling, not measuring**: the combat view,
the combat log and the commissions panel should say which title they are for and
show nothing rather than garbage on the others, the way Fast Travel now does.

### G8 — already tracked elsewhere

| cell | issue |
|---|---|
| C22, the running title read from the machine | #21 |
| C20 for Curse, the trainer measurement | #18 |
| C21 for SSB, an area table | #20 |
| C21 for Curse, whether the mechanism exists at all | #19 |
| D1, a disks folder per title | #22 |
| D4, the Ultimate backend | needs hardware nobody here has |

## 4. What this document is not

* **Not a release checklist.** `docs/122` is that, and it is per-platform.
* **Not a decoding plan.** `docs/120` and `docs/121` are those, per title, and
  they remain correct about what they cover.
* **Not a promise to support the other three titles.** `por/games.py` carries
  Champions of Krynn, Death Knights of Krynn and Gateway to the Savage Frontier
  because the geometry table is cheaper complete than partial. `README.md` does
  not name them and this document does not either.
* **Not a plan to reverse-engineer the later titles' combat.** G7 is the
  decision to label rather than measure, and it is deliberate.
