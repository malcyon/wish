# por

The game's formats, decoded — character records, save games, maps, items,
spells. No Qt, no emulator, no transport: everything here is bytes in and bytes
out, so it can be driven from a `.D64`, from a live memory read, or from a
test's own array.

| file | purpose |
|---|---|
| `__init__.py` | Empty. |
| `amiga.py` | Amiga *Pools of Darkness* `Save/NAME.pc` character files, big-endian, and the writer that turns a `NeutralCharacter` into one. Every offset was read off the screen by writing probe payloads onto a copy of disk 3; the record holds base values only, because the game rederives THAC0, encumbrance and movement on load. |
| `areas.py` | The single source of truth for the thirty Pool of Radiance areas, keyed by **area id** rather than by map file — `ECL0C` does not exist, and four areas never put a `GEO` on the screen at all. |
| `c64_codec.py` | The C64 codec: a `NeutralCharacter` becomes 580 C64 bytes and back again. Every byte written is justified as sourced, computed by a named rule, or a documented constant; the reader takes the roster block and the item page separately, because a save slot holds only 256 of the 580. |
| `commissions.py` | The City Council's reward ledger, offer board and summons, read out of the 224 persistent flag bytes at `$4A20`. No transport, so it works from a save file or a live read alike. |
| `d64.py` | Commodore 1541 `.D64` reader and writer. Deliberately has no block allocation: files are only ever rewritten in place over their existing sector chain, so nothing ever needs allocating or freeing. |
| `derive.py` | Recomputes armour class, THAC0 and the damage bonus from the AD&D rules so a value the game cached and never refreshed can be reported as stale. Writes nothing. |
| `dos.py` | The DOS Pool of Radiance codec, both directions: reads a DOS save into the neutral record, and since #26 writes one back — the record, its `.ITM`, and a whole save over a template's `SAVGAM`. A field with no home on the other side is *reported* rather than dropped silently. |
| `dos_layout.py` | The 285-byte DOS character record as the same declarative `Field` / `Confidence` table `layout.py` uses, measured against 24 real specimens. Both directions of `dos.py` read it; the player's own files are never written to. |
| `dos_savegame.py` | The DOS `SAVGAM?.DAT` saved game mapped (#59, #60): the VM word array indexed by ECL address, the clock, the party size, the wallset triple and the live ECL script buffer — accessors over any save's bytes, and the writers the retarget recipe is made of, including enough of the `.DAX` container to lift the target area's script out of it. |
| `encoding.py` | The three biased fields in one place — THAC0 and armour class stored as `60 - value`, the armour bonus as `48 + value`. Functions rather than a constant to subtract by hand, because every caller that forgot was off by a lot and in the wrong direction. |
| `games.py` | Which Gold Box title a save came from, as a table of numbers rather than a class hierarchy. Six C64 titles share one engine and one 580-byte record; what differs is the file names, the load addresses, whether the roster is a second file, and the race and class tables every codec resolves an index through. |
| `geo.py` | The GEO map format: four 256-byte planes over a 16x16 grid, with wall art and passability as two **independent** fields — conflating them is what made five earlier readings of GEO fail. |
| `iconparts.py` | The icons the game can actually *make* — a weapon and a head, chosen in pairs by size — read out of the `SPELLE64` / `SPELLN64` icon editor, as against the 10^43 an 18-cell free choice would offer. |
| `icons.py` | The eight 36-byte combat icons at `$4BE0` in `SAVEDGAME0`: 18 screen codes then 18 colours, established by diffing in-game icon edits. |
| `items.py` | Inventory — the sixteen 16-byte item records per character at `$5900 + slot * $100`, and the word table the game assembles item names from. Weights are in tenths of a pound. |
| `layout.py` | The 580-byte C64 character record as a declarative table of fields, each with a confidence grade. Nothing else in the project may hard-code an offset; bytes no entry claims become UNKNOWN regions at import time, so overlaps and gaps are impossible to introduce silently. Its field notes are **generated** into `docs/20-character-record.md` by `tools/gendocs.py`. |
| `levels.py` | Experience thresholds, saving throws, turning and spell progression, per title — read off the player's own disks and cross-checked against AD&D 1st edition rather than taken from either alone. |
| `levelup.py` | Reproduces, field by field, what the training hall writes at a level-up, with each step traced to the `GEN` routine that performs it. |
| `memory.py` | The game's memory map *outside* a character record — party header, loader caches, combat tables — as a purely descriptive table with confidences, so "what is at `$4BC2`" stops being a grep. **Generates** `docs/41-memory-regions.md` via `tools/genmemory.py`. |
| `monster.py` | The two attack forms and the experience award, read off any 580-byte record — a goblin and a level-1 fighter are the same structure. Reads `0x0D9`–`0x0E0` and never the working copies at `0x111`. |
| `neutral.py` | The port-neutral character record every conversion passes through, where each value carries its provenance and not just a number, plus the `Writer` every writer inherits the take-refuse-report protocol from. A codec per format around one record instead of a converter per pair. |
| `petscii.py` | C64 text, keeping the two string conventions apart: NUL-padded ASCII inside a character record, shifted-space-padded PETSCII in a 1541 directory entry. |
| `record.py` | `CharacterRecord` — bytes in, bytes out, with every field read and written *through* `layout.py`. That makes a decode/encode cycle byte-exact by construction, so the bytes whose meaning is still unknown can never be dropped or zeroed in passing. |
| `savegame.py` | The save container in both its shapes: Pool of Radiance's two files (`SAVEDGAME0`, a raw `$4900`–`$64FF` memory image, plus `SAVEDGAME1`), and the single 7426-byte file every later title writes. |
| `spells.py` | The spell name table per title, and what the packed list of spell ids at record offset `0x020` means. The names live on the game disk, and *where* is the one thing that does not transfer between titles. |
| `strength.py` | Recomputes PARTYSTRENGTH, the number twelve area scripts size random encounters from. Nothing stores it, so this walks the roster the way `DUNGEON $1BE8` does — using the biased THAC0 and armour class bytes as stored, not as decoded. |
| `traits.py` | The ten trait slots at `0x0AD` — racial abilities, monster specials, item powers — as one 1–139 namespace shared with the DOS port, 66 entries confirmed against the player's own disks. |
| `yaml_io.py` | The YAML codec: writes a `NeutralCharacter` out as plain data and imports a document back into a save, losslessly. Only understood fields are editable, and the header, the roster tail and the majority of each record still unidentified are carried through byte for byte. |
