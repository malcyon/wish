# Knowledge base

Reverse-engineering notes for Pool of Radiance (Commodore 64), supporting the
library in `por/` and the `wish` editor in `tools/`.

| document | contents |
|---|---|
| [PLAN.md](PLAN.md) | the project plan; kept current as phases land |
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

`20-character-record.md` is generated — run `python3 tools/gendocs.py` after
changing `por/layout.py`. `85-item-tables.md` and `86-spell-table.md` are generated too — run
`python3 tools/genitems.py`, `python3 tools/genspells.py`,
`python3 tools/gentemplates.py` and `python3 tools/genmaps.py`, which need a
game disk. Everything else is
written by hand.


## Where things stand

**Settled**

* D64 container read/write, including byte-exact in-place rewrites.
* `SAVEDGAME0` is a verbatim image of `$4900`–`$64FF`: a party header, a
  combat-icon table at `$4BE0`, **8 character slots of `$100`** at `$4D00`, and
  an item area from `$5900`. **Eight** slots exist structurally, the roster
  confirms the same count, and the game itself refuses a seventh *player*
  character — so the rule is at most six player characters and at most eight
  in total, the remaining two being NPC-only.
* `SAVEDGAME1` opens with **eight 32-byte roster blocks** filling `$8300`–`$83FF`
  exactly. They hold the derived combat numbers the character record does not:
  armour class, THAC0, current hit points, movement and the damage bonus.
  Three bytes at `+0x03`–`+0x05` are still unread.
* **The two files divide three ways, not two:** `SAVEDGAME0` holds the eight
  character slots *and* a header carrying the party's place in the world;
  `SAVEDGAME1` opens with the roster of derived combat values. Base values live
  in the record, current ones in the roster — THAC0, movement, hit points and
  armour class each exist in both. See
  [30-savegame-layout.md](30-savegame-layout.md).
* **The party's position** — x, y and facing in the `SAVEDGAME0` header, with
  the previous square and the game clock beside them.
* **The page at `$5500`** — one record in the character layout, holding whatever
  the game loaded there last. After a fight it is the monster, byte-identical to
  its `MON*` file bar two derived bytes.
* **Spells** — the spellbook at `0x078`–`0x07E` (what a character knows) and the
  memorised list at `0x020` (what is prepared), both readable by name.
* **105 of 580 record bytes known** — name, six abilities,
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

* **The level-drain pair**, now testable at last: specimens above level 1 exist.
* **Racial traits** — known to exist from the Gold Box Companion on the DOS
  version. No candidate left in the record.
* **Item byte `+5`** — the last unread byte of the 16, and the rest of the
  effect bytes are only as good as the 1989 editor's synthesised records.
* **Roster `+0x03`–`+0x05`** — read as per-level spell counts, retracted when
  one save contradicted it, and since found to agree with two saves *level by
  level* while the contradicting page turns out to be a stale cache. Still
  unknown, but for a better reason than before.
* **Whether `0x0A0` is "level" or "highest level attained"**, and whether
  `0x073` and `0x0EB` really say the same thing. Every pair of fields we have
  understood turned out to be base-versus-current rather than a duplicate.
* What `0x0AD` is — non-zero only for elves and half-elves, and not the racial
  trait mask it looked like.
* ~82% of each record remains unidentified, as does everything in
  `SAVEDGAME1` past its first page.

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
  levels 4 to 8. Hacked, so its values are worthless; its *structure* bounded
  the roster at one page and settled character level. See
  [90-specimens.md](90-specimens.md).
* **`poolce.d64`** — a listable 1989 BASIC character editor. Every offset it
  pokes matches ours, it carries the item name table and 162 complete item
  records, and the things its author could *not* find corroborate our layout.
