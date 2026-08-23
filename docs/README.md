# Knowledge base

Reverse-engineering notes for Pool of Radiance (Commodore 64), supporting the
`por/` library, the `wish` editor and the automapper.

| document | contents |
|---|---|
| [00-overview.md](00-overview.md) | the game's disks, how a session boots, overlay structure |
| [10-disk-format.md](10-disk-format.md) | 1541 D64 container: geometry, directory, sector chains, safe in-place writes |
| [20-character-record.md](20-character-record.md) | **generated** field table for the 580-byte record, with confidence levels |
| [30-savegame-layout.md](30-savegame-layout.md) | `SAVEDGAME0`/`SAVEDGAME1`, the `$100`×8 slot layout, the party header, the icon table and the roster blocks |
| [40-memory-map.md](40-memory-map.md) | live addresses and the game's own race/class/alignment/item tables |
| [41-memory-regions.md](41-memory-regions.md) | **generated** every named address, from `por/memory.py` |
| [50-experiments.md](50-experiments.md) | append-only experiment log, including the failures |
| [60-goldbox-field-checklist.md](60-goldbox-field-checklist.md) | research pass: what fields *ought* to exist, and which online claims are unreliable |
| [70-driving-the-game.md](70-driving-the-game.md) | how to automate the game under VICE, and what does not work |
| [80-fields-wanted.md](80-fields-wanted.md) | the target field list for the editor, and what is known about each |
| [85-item-tables.md](85-item-tables.md) | **generated** word table and item-type table, read off a game disk |
| [86-spell-table.md](86-spell-table.md) | **generated** spell id -> name table, read off a game disk |
| [87-item-templates.md](87-item-templates.md) | **generated** every item on the game disks, for use as `template:` |
| [88-map-files.md](88-map-files.md) | **generated** the `GEO` map format and an inventory of all 29 files |
| [89-level-tables.md](89-level-tables.md) | **generated** experience thresholds, THAC0, hit dice and spells per class |
| [90-specimens.md](90-specimens.md) | every character record we have, with independently-known attributes |
| [95-wish-cli.md](95-wish-cli.md) | the `wish` save editor: usage, safety properties, what can be edited |
| [101-combat-view.md](101-combat-view.md) | the combat map, inside the automapper — **built**, on the automapper tab |
| [100-live-view.md](100-live-view.md) | a live read-only view of the running game — **built**, on the automapper tab |
| [99-one-window.md](99-one-window.md) | the `wish` window: the editor and the automapper in two tabs, one live connection, and the backend registry |
| [98-automap-notes.md](98-automap-notes.md) | typed note-taking on the automap — built |
| [97-editor.md](97-editor.md) | the PyQt6 character editor: the `.ui` form, the read-only rules, and the icon editor |
| [96-live-memory-automapper.md](96-live-memory-automapper.md) | the live automapper in `automap/`: how it reads a running game, draws the map and shows the party |
| [102-live-actions.md](102-live-actions.md) | buttons that change the running game — built |
| [103-commissions-panel.md](103-commissions-panel.md) | a quest log from the ledger at `$4AA6` — built |
| [104-debug-log.md](104-debug-log.md) | an opt-in local log for bug reports — planned |
| [105-content-audit.md](105-content-audit.md) | what the repository must not carry, and what still does |
| [106-releases.md](106-releases.md) | versioning, PyInstaller packaging and GitHub Actions — planned |
| [107-roster-and-notes.md](107-roster-and-notes.md) | the automapper's roster cards, note tooltips and the icons — built |
| [108-purge-history.md](108-purge-history.md) | removing the game's files from the git history — planned |
| [109-icon-choices.md](109-icon-choices.md) | icon candidates to choose between, and where icons earn their place |
| [110-combat-log.md](110-combat-log.md) | capturing the game's combat messages before it paints over them |
| [111-map-shading.md](111-map-shading.md) | darker walls and Dyson-style hatching |
| [112-test-harness.md](112-test-harness.md) | the suite opens real windows, and an intermittent findChild segfault |
| [114-party-strength.md](114-party-strength.md) | what makes a random encounter bigger, term by term |
| [113-world-map.md](113-world-map.md) | the overland travel map, which is the combat engine on other data |
| [115-review-the-scripts.md](115-review-the-scripts.md) | the thirty decoded ECL scripts, waiting for a human read |
| [116-second-game.md](116-second-game.md) | Curse of the Azure Bonds: the same 580-byte record, what differs, and the import routine that proves it |
| [117-save-conversion.md](117-save-conversion.md) | converting characters between the DOS and C64 versions — planned |
| [118-debug-mode.md](118-debug-mode.md) | `WISH_DEBUG=1`, Fast Travel, and what an area change actually is — built |
| [119-test-party.md](119-test-party.md) | getting a levelled, varied party for the specimens still wanted |
| [120-curse-testing.md](120-curse-testing.md) | testing the second game |
| [121-silver-blades.md](121-silver-blades.md) | Secret of the Silver Blades, the third title |
| [122-release-testing.md](122-release-testing.md) | what a release has to pass before it goes out |
| [123-parallel-sessions.md](123-parallel-sessions.md) | running several agents in one tree without collisions |
| [124-amiga-port.md](124-amiga-port.md) | porting a C64 party into Amiga Pools of Darkness: the `.pc` record, decoded by writing one and reading the sheet |
| [125-bug-notes.md](125-bug-notes.md) | the bugs no player sees, our own misreadings, and the community rumours |
| [126-forum-findings.md](126-forum-findings.md) | what the Gold Box forums have that we do not — playtester mode, DOS area tables, tooling |
| [127-community-formats.md](127-community-formats.md) | the community format spreadsheets: saving throws solved, the DOS record against ours |
| [128-guide-and-scripting.md](128-guide-and-scripting.md) | the DOS guide and the Unlimited Adventures files: the GBVM address list, the area names, the ECL semantics |
| [129-one-binary.md](129-one-binary.md) | folding `wish-cli` into the one `wish` executable — planned |
| [130-preferences.md](130-preferences.md) | `File > Preferences…` (`Ctrl+,`): where the game disks are, which live backend, the debug log — built |
| [131-fastloader.md](131-fastloader.md) | whether answering the fastloader prompt Y or N changes anything — measured; it does not |
| [134-commissions.md](134-commissions.md) | the council's ledger, its progress markers, the offer board and the byte two scripts share |
| [135-levelling.md](135-levelling.md) | what the training hall writes, routine by routine, and the button that does it without walking there |
| [136-condition-badges.md](136-condition-badges.md) | which spell effects earn a badge on the roster card, measured at 13 px — a decision sheet for Donald |
| [137-wilderness-automap.md](137-wilderness-automap.md) | why the automapper is blank outdoors, and what to draw the terrain with |
| [138-multiple-games.md](138-multiple-games.md) | fast travel for more than one Gold Box title: what is per-title today, what data the other games have, and the dialog |
| [TASKS.md](TASKS.md) | the open task list, one code per task, retired when the task closes |

`20-character-record.md` is generated — run `python3 tools/gendocs.py` after
changing `por/layout.py`. `85-item-tables.md` and `86-spell-table.md` are generated too — run
`python3 tools/genitems.py`, `python3 tools/genspells.py`,
`python3 tools/gentemplates.py` and `python3 tools/genmaps.py`, which need a
game disk. Everything else is
written by hand.


## How the code is laid out

Split along the **packaging** boundary, so a build takes the app without
dragging in throwaway discovery scripts.

| package | what it is |
|---|---|
| `por/` | the file formats: D64, the 580-byte character record, the save games, the item and spell tables. **Transport-free** — no sockets, nothing that knows a machine is running |
| `editor/` | the PyQt6 character editor, over `por/` alone |
| `automap/` | everything that reads a *running* machine, quarantined here so the first decision below is structural rather than a convention |
| `wish/` | the one window: two tabs, the single shared live connection, the backend registry, and `File > Preferences…`. See [99-one-window.md](99-one-window.md) and [130-preferences.md](130-preferences.md) |
| `ui/` | drawing code both the editor and the map need, owned by neither |
| `designer/` | the Qt Designer `.ui` forms, loaded at runtime |
| `packaging/` | the PyInstaller entry points and the Windows console-stream repair |
| `tools/` | discovery scripts — dumps, diffs, generators, experiment runners. Two entry points live here, `wish-cli` (`tools/wish.py`) and `tools.genui`, so the package ships even though the rest of it is scaffolding; [129-one-binary.md](129-one-binary.md) plans to fold the CLI into `wish` itself |
| `skills/goldbox/` | the transferable method, for a cold agent starting on a new title |
| `work/` | scratch disk copies — `.gitignore`d, and where every disk image belongs |

**Two decisions shape all of it, and both still hold.**

1. **The editor is a file tool with zero emulator dependency.** It opens a
   `.D64`, edits the save, writes it back, and never talks to VICE. `editor/`
   imports nothing from `automap/`, `por/` stays transport-free, and the whole
   file path works on a machine with no emulator on it.
   `tests/test_wish.py` asserts both halves: the editor tab is never handed the
   live target, and no file under `editor/` mentions `automap`.
2. **Live memory is a discovery technique, not something the editor promises.**
   A watchpoint on "whatever stores to the strength byte" beats reading
   disassembly, so the project reads the running game heavily while reverse
   engineering. That grew into the automapper, which *is* a shipped feature —
   and it lives in `automap/` precisely so the first decision survives it.

`por/layout.py` is the single source of truth for the record: a declarative
table, every field carrying `CONFIRMED` / `PROBABLE` / `GUESS`, asserting at
import that all 580 bytes belong to exactly one entry.
[20-character-record.md](20-character-record.md) is generated from it, so the
documentation cannot drift from the code — and it has **exactly one owner at a
time**, because several agents appending to it independently would fragment the
schema and reintroduce the drift it exists to prevent.

## Where things stand

**Settled**

* D64 container read/write, including byte-exact in-place rewrites.
* `SAVEDGAME0` is a verbatim image of `$4900`–`$64FF`: a party header, a
  combat-icon table at `$4BE0`, **12 character slots of `$100`** at `$4D00`, and
  an item area from `$5900`. Slots 0–7 are the party and 8–11 are used only in
  combat; the roster and the icon table both count **eight**, and the game
  itself refuses a seventh *player* character — so the rule is at most six
  player characters and at most eight in total, the remaining two being
  NPC-only.
* `SAVEDGAME1` opens with **eight 32-byte roster blocks** filling `$8300`–`$83FF`
  exactly. They hold the derived combat numbers the character record does not:
  armour class, THAC0, current hit points, movement and the damage bonus.
  Three bytes at `+0x03`–`+0x05` are still unread.
* **The two files divide three ways, not two:** `SAVEDGAME0` holds the twelve
  character slots *and* a header carrying the party's place in the world;
  `SAVEDGAME1` opens with the roster of derived combat values. Base values live
  in the record, current ones in the roster — THAC0, movement, hit points and
  armour class each exist in both. See
  [30-savegame-layout.md](30-savegame-layout.md).
* **The party's position** — x, y and facing in the `SAVEDGAME0` header, with
  the previous square and the game clock beside them.
* **The page at `$5500`** — **slot 8**, the first of the four slots combat uses.
  After a fight it holds the monster, byte-identical to its `MON*` file bar two
  derived bytes. It was long read as a scratch "staging page"; it is not
  scratch.
* **Spells** — the spellbook at `0x078`–`0x07E` (what a character knows) and the
  memorised list at `0x020` (what is prepared), both readable by name.
* **Most of the record is still unread.** The current count lives in
  [20-character-record.md](20-character-record.md), which is generated from
  `por/layout.py` — a number retyped here goes stale the moment a field is
  named, and has. Name, six abilities,
  exceptional strength, race, class, class bitmask, sex, alignment, age, five
  saving throws, movement, infravision, thief skills, hit points, all seven
  money types, experience, character level, per-class levels, the portrait
  head and body, the size flag, and the memorised spell list.
* **Inventory format** — 16-byte item records, verified against the AD&D 1st
  edition price and weight tables. Names are three word indices into the game's
  own table; cost is 16-bit; byte `+4` is the magic bonus; byte `+0` indexes a
  second table, `ITEMS`, holding damage, armour class, hands, range and class
  usage. Items can be edited, added and removed.
* **Combat icons** — 18 screen codes plus 18 colours, independently editable.
* **The game accepts externally edited saves.** Thirteen fields were changed at
  once and every one appeared in the game. No checksum, no validation.

**Working tool**

`tools/wish.py` exports a party to YAML and imports an edited YAML onto a new
disk, losslessly. See [95-wish-cli.md](95-wish-cli.md).

**What the tool can now do**

`wish` reads and writes both save files. The `SAVEDGAME1` roster blocks are
editable, so armour class, THAC0, current hit points, movement and the damage
bonus can all be changed — as can character level, which is kept in step with
the per-class array, and the class code, which is kept in step with the class
bitmask.

**The roster blocks are now proven writable.** MALCYON's armour class and current
hit points were edited to 1 and 11 — a two-byte change to `SAVEDGAME1`, with
`SAVEDGAME0` byte-identical — and the game showed `AC 1` and `HITPOINTS 11` on
both the party list and the character sheet, then wrote the same bytes back when
it saved. So the game reads that cache and does not recompute over it.

**The caveat that still stands:** everything *else* found since the thirteen-field
edit is written on the strength of reading it correctly, which is not the same as
having been written back and confirmed in game.

**Open**

* **The level-drain pair as a specimen** — `0x0A1`/`0x0A2` are read and named
  from the drain and restoration routines, but no character of ours has been
  drained in play.
* **Roster `+0x03`–`+0x05`** — read as per-level spell counts, retracted when
  one save contradicted it, and since found to agree with two saves *level by
  level* while the contradicting page turns out to be a stale cache. Still
  unknown, but for a better reason than before.
* **How the C64 applies racial modifiers to thief skills.** The progression
  table is the DOS one and a dwarf thief matches base plus the published dwarf
  row in all eight columns; a gnome, a halfling and a half-elf do not, and no
  dexterity adjustment reconciles them. The C64's own modifier table, wherever
  it is on the disks, would settle it in one read.
  See [127-community-formats.md](127-community-formats.md).
* **Whether `spells_memorised` is 21 bytes rather than 16.** DOS allots 21 and
  21 is the C64 ceiling; the most anybody has used is 13, so nothing we hold
  contradicts either width.
* **Whether `0x100` is a status enum.** Four sources now disagree about it and
  the newest weakens rather than strengthens the case; `roster_in_use` stays
  PROBABLE. One specimen reading other than 1 settles it.
* **The save path itself has never been disassembled.** `LOAD/SAVE` is on the
  disk and the tooling for reading it is proven; nothing has ever needed it,
  because a save is a verbatim memory image and diffing two of them answers
  more than the routine would.
* Most of each record remains unidentified; see
  [20-character-record.md](20-character-record.md) for how much.
  `SAVEDGAME1` past its first page is not open at all — it is resident code
  and a graphics buffer, not save data.

**Closed since this list was written**

* **Character traits** are `0x0AD`–`0x0B6`, ten trait slots holding codes from
  the same namespace as the save's active effects — but not that list
  seeded per race — which is also what `0x0AD` is.
* **Item byte `+5`** is a signed saving-throw bonus. Every byte of the 16 is
  read.
* **`0x0A0` is the current level**, with drain state in its own pair at
  `0x0A1`/`0x0A2`; there is no "highest level attained".
* **`0x073` and `0x0EB` are different fields**, proved by building a save where
  they disagree: `0x073` is what the sheet prints, `0x0EB` is what the game ANDs
  against an item's class-usage byte.
* **The saving throws are derived by a known rule** — the class table row for
  the character's level, best number in each column across every class held,
  minus the constitution bonus for a dwarf, gnome or halfling. 78 of 79 records
  satisfy it exactly.

**No longer abandoned**

Both of these were written off and both now work; see
[70-driving-the-game.md](70-driving-the-game.md).

* **Watchpoints via the VICE monitor** — they do work, and they settled the
  character-creation question in one run. The trick is to keep the connection
  open and `resume()` rather than close it: VICE re-enters the monitor on the
  connection that was live when it stopped.
* **Driving the game to create characters** — solved. The name prompt rejects
  any byte `>= $5B` and `xdotool` was sending capitals as Shift+letter, i.e.
  `$D7` for `W`. Type lowercase.
* **Disk swapping**, which blocked every experiment needing the game to read a
  disk we built — solved through VICE's *text* monitor `attach` command.
* **The roster blocks are writable.** An edited armour class and hit-point
  total appeared on the character sheet and survived a save, so the caveat
  above about `SAVEDGAME1` never having been written back is now discharged for
  the combat block.

## Two outside sources worth knowing about

Neither is one of our own controlled experiments, and both earned their place:

* **`npc_party.d64`** — a save found online with three PCs and five NPCs at
  levels 4 to 8. Better described as genuine play with one edited field than as
  "hacked": five of its eight records are the game's own `MON*` files and the
  one value that cannot have come from play is MAD MAN's saturated `$FFFFFF`
  experience. It bounded the roster at one page, settled character level, and
  seven of its eight records satisfy a saving-throw rule derived without them.
  See [90-specimens.md](90-specimens.md).
* **`poolce.d64`** — a listable 1989 BASIC character editor. Every offset it
  pokes matches ours, it carries the item name table and 162 complete item
  records, and the things its author could *not* find corroborate our layout.
