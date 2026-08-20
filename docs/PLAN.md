# Pool of Radiance (C64) — Reverse Engineering & Character Editor

## Context

You want a Gold Box Companion equivalent for the **C64** version of Pool of Radiance, starting
with a character editor. GBC works by scanning DOSBox memory for the DOS game's character
records; nothing equivalent exists for the C64 release, so the record layout has to be
established from scratch. The model is `s-macke/weltendaemmerung` — reverse engineer to
*understand*, not to port; the output is documentation plus an assistant app.

The work is staged deliberately: tools → discovery → one small proven change at a time →
(eventually) a PyQt editor. Nothing about the editor gets built until the record layout is
proven by controlled experiment.

**Two decisions that shape everything below:**

1. The shipped editor is a **file tool with zero emulator dependency** — it opens a `.D64`,
   edits the save, writes it back. It never talks to VICE.
2. **Live memory access is a discovery technique, not an app feature.** Setting a watchpoint on
   "whatever stores to the STR byte" is far faster than reading disassembly, so we use it
   heavily while reverse engineering — through an off-the-shelf MCP server, nothing we build or
   ship.

### What is already established (verified this session, read-only)

This is much further along than a cold start. The C64 save data is **uncompressed and directly
readable** — no ByteKiller unpacking needed for save data, unlike the game's static data files.

`/mnt/media/roms/c64/Pool of Radiance Disks/PORSAVE.D64` contains three PRG files:

| File | Size (payload) | PRG load addr | Covers |
|---|---|---|---|
| `.BRUTUS` (`$01`+`BRUTUS`) | 580 B (`$244`) | `$6B00` | standalone character export |
| `SAVEDGAME1` | 2048 B (`$800`) | `$8300` | `$8300–$8AFF` — eight party roster blocks fill `$8300–$83FF`; the rest is the resident `ANIMATE00` overlay and a bitmap buffer, not save data |
| `SAVEDGAME0` | 7168 B (`$1C00`) | `$4900` | `$4900–$64FF` — party |

`SAVEDGAME0` is a **raw memory image**: the game dumps `$4900–$64FF` verbatim. Non-zero page map:

```
$4900:  8   $4A00:  2   $4B00: 52   $4C00:255   <- party/global header ($400 bytes)
$4D00: 41   ...zero...  $5500: 41   ...zero...  <- character slots
```

`BRUTUS` appears at `$4D00` and `$5500`. Leading hypothesis: **6 character slots of `$400`
bytes** at `$4D00, $5100, $5500, $5900, $5D00, $6100`, ending exactly at `$64FF`; slots 0 and 2
occupied. Competing hypothesis: 3 slots of `$800`. Resolving this is experiment #1.

> **Both were wrong**, and a two-character save could not tell them apart. It is
> **8 slots of `$100`** at `$4D00`. Left as written because the error is the
> point — see Phase 2 below and
> [the slot stride, corrected](50-experiments.md).

Confirmed field offsets inside the 580-byte character record:

```
0x00..0x13  name, ASCII, NUL-padded (20 bytes)
0x14  STR=18   0x15 INT=16   0x16 WIS=13
0x17  DEX=14   0x18 CON=16   0x19 CHA=13
0x1A  exceptional STR percentile = 98   ->  "18/98"
```

The record at `$4D00` matches the `.BRUTUS` export in **536 of 580 bytes**; the 44 differing
bytes are party-context state and are a high-value early target.

Note: published Gold Box hex-editing offsets (STR at 0x70, class at 0x75) are for the **DOS**
record and do **not** apply — the C64 layout is its own thing. DOS docs are useful only as a
checklist of *which fields exist*.

### Environment facts that shape the plan

- VICE 3.10 Flatpak **does** have `-binarymonitor` / `-binarymonitoraddress` compiled in.
- But `flatpak info --show-permissions net.sf.VICE` shows **no `shared=network`** — the sandbox
  has its own network namespace, so a host-side client cannot reach `127.0.0.1:6502`.
  Fix: add `--share=network` to the `flatpak run` line in `~/.local/bin/pool-of-radiance`.
- `c1541` works from the Flatpak (`flatpak run --command=c1541 net.sf.VICE`) and reaches
  `/mnt/media` (it is in the Flatpak's filesystem grants).
- `/home/donald/src/wish` is an empty repo already seeded with the standard Python `.gitignore`.
- Python 3.12; `uv` and `pipx` available; no PyQt yet; no 6502 toolchain.
- **VICE is configured with JiffyDOS.** At launch the game asks whether to disable its own
  fastloader — the correct answer on this machine is **`Y`** (JiffyDOS does the fast loading).
  Every scripted launch and every written repro step must answer this prompt, or the symptom
  looks like a corrupt disk image rather than a loader conflict.

**Safety rule for the whole project:** never write to
`/mnt/media/roms/c64/Pool of Radiance Disks/*`. Copy disks into `work/` first. `POOL1.D64.orig`
is the pristine side-1 image — `POOL1.D64` has already been modified by the game (it has a
`.brutus` written to it), so diff against `.orig`, not against `POOL1.D64`.

---

## Repository layout

One repo, split along the **packaging** boundary so PyInstaller bundles the editor without
dragging in throwaway discovery scripts. Cheap now, irritating to retrofit later.

```
wish/
  por/          # shared library — SHIPS
    d64.py         # D64 read/write: dir parse, file chain, PRG load-addr strip/add
    layout.py      # THE single source of truth: field table
    record.py      # CharacterRecord: decode/encode against layout.py
    savegame.py    # SAVEDGAME0/1 <-> list[CharacterRecord] + header blob
    petscii.py     # name encode/decode
  editor/       # PyQt app — SHIPS (Phase 4, not before)
  tools/        # discovery only — NEVER ships
    dump.py        # annotated hex dump of a D64 / char file
    diff.py        # diff two D64s, report changed offsets with field names
    mkparty.py     # build test parties for experiments
  docs/         # knowledge base
  work/         # scratch disk copies — gitignored
  tests/
```

- `d64.py` reuses the sector geometry already validated this session
  (tracks 1–17: 21 sectors, 18–24: 19, 25–30: 18, 31–35: 17; directory chain from 18/1).
- `layout.py` is a **declarative table**, not offsets sprinkled through code. Every field carries
  a confidence level: `CONFIRMED` / `PROBABLE` / `GUESS`. `record.py`, the ImHex `.hexpat`, and
  `docs/20-character-record.md` are all generated from or checked against this one table — so
  the documentation cannot drift from the code.
- `record.py` decodes a plain `bytes` object and does not care where it came from. That is the
  only concession to a possible future live mode, and it costs nothing.

## Phase 0 — Tools  ✅ COMPLETE

All verified working. Results are recorded inline below.

1. `sudo apt install cc65 radare2` — `da65` for 6502 disassembly of the save-path overlays,
   `r2` if `da65` proves insufficient.
2. `flatpak install --user flathub net.werwolv.ImHex` — its pattern language gives us a
   `.hexpat` for the character record that doubles as documentation you can eyeball.
3. Edit `~/.local/bin/pool-of-radiance`: add `--share=network`, and when `POR_DEBUG=1` also
   append `-binarymonitor -binarymonitoraddress 127.0.0.1:6502`. Normal launches stay
   byte-for-byte as they are today.
4. Install **axewater/mcp-vice-emu** at `~/src/mcp-vice-emu`, registered in `.mcp.json`.
   It needed a **local patch** to be usable here: upstream `connect()` unconditionally spawns
   `${emulator}.exe` (Windows-only) and has no attach-to-running mode. The patch adds an
   `isMonitorListening()` probe so that when a monitor is already on the port it attaches
   instead of spawning, and drops the `.exe` suffix off-Windows. `cleanup()` only kills
   `this.process`, which stays null when attaching, so it will not kill your emulator.
   This is a local fork — re-apply the patch if it is ever re-cloned or updated upstream.
   Exposes 21 tools (the README's "32" is stale).
5. `uv init` the repo; add `pytest`. PyQt6 is not installed until Phase 4.

Not installing **RetroDebugger**: it has no Linux AppImage or .deb (CMake source build via
`build-linux.sh`), so it means maintaining a second VICE build, and its real-time memory view is
already covered by the MCP's `vice_memory_read` plus watchpoints. Revisit only if we hit
something those cannot show us.

## Phase 1 — The library and the knowledge base  ✅ COMPLETE

Build `por/d64.py`, `por/layout.py`, `por/record.py`, `por/savegame.py` and the `tools/` scripts.
No emulator involvement in any of this code.

**Knowledge base** — written as we go, not at the end:

- `docs/PLAN.md` — this document. Lives in the repo and is kept current as phases land;
  it is the project's living plan, not a snapshot.
- `docs/00-overview.md` — the game's disk/overlay structure, how a session loads.
- `docs/10-disk-format.md` — D64 geometry, PoR's file naming, the `$01`-prefixed character files.
- `docs/20-character-record.md` — the field table, **generated** from `por/layout.py`
  by `tools/gendocs.py`, so it cannot drift from the code.
- `docs/30-savegame-layout.md` — `SAVEDGAME0`/`SAVEDGAME1` structure, slot map, header region.
- `docs/40-memory-map.md` — live addresses, which overlay owns what.
- `docs/70-driving-the-game.md` — how to automate the game under VICE, and what does
  not work. Written after the input layer cost significant time.
- `docs/README.md` — index, plus an honest settled / open / blocked summary.
- `docs/50-experiments.md` — append-only log: hypothesis, method, result, date. Failed
  experiments stay in; they are the expensive knowledge.

## Phase 2 — Discovery

Scripted, repeatable experiments; each appends to `docs/50-experiments.md`.

### Diff saves to locate fields

1. ~~**Resolve the slot stride.**~~ ✅ **DONE — `$100` × 8** ([the slot stride, corrected](50-experiments.md)).
   The first attempt concluded `$400` × 6 and **that was wrong**: every specimen then had
   at most two characters, so the zero bytes between them fitted either model. A
   real six-character party disproved it immediately. **Lesson: a hypothesis that
   sparse data agrees with has not been tested.**
2. ~~**Map the `.BRUTUS`-vs-in-save 44-byte delta.**~~ ✅ **Largely done.** Most of it is
   the 36-byte combat icon at record offset `0x220`, which the party keeps in a shared
   table at `$4BE0` instead; the remainder is item-area bytes.
3. ~~**Differential save scanning**~~ ✅ **DONE, and it carried the project.** The
   core technique, needing no emulator hooks at all:
   save, change exactly one thing in-game, save again, diff with `tools/diff.py`. Drives out
   gold/gems/XP/HP/AC/class/race/level/spell memorisation.
   **Partly superseded by something cheaper:** comparing *different characters*
   rather than *the same character before and after*. A party with varied races,
   classes, sexes and alignments identified seven fields in minutes with no
   emulator at all ([the six-character comparison](50-experiments.md)). Use `tools/compare.py` first; fall back to
   before/after diffing only for fields that need a character to *change*
   — experience, level, damage, inventory. Between them the two methods produced
   the inventory format ([the shopping trip](50-experiments.md)), experience and the coin fields, the combat icons
   ([the combat-icon edits](50-experiments.md)), and seven fields from one varied party ([the six-character comparison](50-experiments.md)).
4. ~~**Watchpoints, via the MCP.**~~ ❌ **Abandoned — they never worked.** Repeated
   attempts either reported no hits on bytes that were unquestionably read, or fired
   and left the machine stopped because the hit was never acknowledged (see [the two dead ends in driving VICE](50-experiments.md) and
   the copy-wheel notes). Either the `CHECKPOINT_SET` encoding or the hit-count offset
   is wrong, and it was never worth the time to find out: comparing saved data proved
   faster than watching the game read it. Revisit only if a field resists every
   diffing approach.
5. **Disassemble the save path only.** ⏳ *Not started for `LOAD/SAVE`.* The tooling is proven; it simply has not been needed for save data. `LOAD/SAVE`, `CAMP` and `INIT` on POOL1.D64 are the PRGs
   that matter (each carries its load address in its first two bytes, so `da65` gets correct
   addressing for free). No whole-game disassembly — the overlay data (`ECL*`, `GEO*`, `PIC*`,
   `MON*`) is out of scope for a character editor.
6. **The fields still unfound.** The level-drain pair and the remaining item
   effect bytes. The portrait pair (`0x0FE`/`0x0FF`) and the size flag
   (`0x099`) are both found. The party's
   **map coordinates are found** — `$49C0`/`$49C1`, with facing at `$49C2`. Racial traits have a strong candidate at `0x0AD` but no
   decoded meaning. THAC0 and damage are both found — THAC0 as a base in the
   record and a current value in the roster, damage in the item-type table. The full list with its evidence lives in
   `docs/80-fields-wanted.md` §Still wanted — that file is the source of truth and
   this list is deliberately not a copy of it. Level and memorised spells came off
   that list via `npc_party.d64`.
7. **The rest of the `SAVEDGAME1` roster block.** Its extent is settled — eight
   blocks filling `$8300`–`$83FF` — and about nineteen of the thirty-two bytes per
   block are still unread. THAC0 turned out to be `+0x0E`, stored as `60 - THAC0`
   exactly as AC is at `+0x0F`, which makes **damage** the next thing to look for
   and `60 - x` the first encoding to try. Roster byte `+0x0C` is a specific open
   question: `$80` for every NPC in one save and for one player character in
   another.
8. **Record byte `0x0B8`** — BRUTUS is the only character whose copy changed,
   0 to 1, when the party equipped. It was suspected of causing his extra point
   of armour class; that turned out to be our dexterity table, so `0x0B8` is now
   an unexplained equipment-linked byte with nothing pinned to it.
9. **Item effect bytes.** Mostly settled: `+0` indexes the `ITEMS` type table,
   `+6`'s low bits are the hidden-name mask, `+7` bit 7 is cursed, and
   `+13`–`+15` are a scroll's spells or a wand's charges. Only `+5` is left --
   0 on 162 of 163 game items and 251 on CURSED NECKLACE alone.
10. **What marks an NPC.** Eight record bytes read `$FF` for every NPC and `$00`
    for every player character; `wish` reads and writes them as `npc:`. Which one
    the game tests is unknown, so the flag has never been proven writable.
11. ~~**The spell id table.**~~ ✅ **DONE.** `SPELLN00`, read through its pointer
    table because the strings overlap. Six class/level groups, ids 1-55. See
    `docs/86-spell-table.md`.
12. ~~**Decode the `GEO` map files.**~~ ✅ **DONE.** Four 256-byte planes over a
    16×16 grid: wall art as a nibble per edge in planes 0 and 1, square
    attributes in plane 2, and passability as **two bits per edge** in plane 3.
    A wall and a barrier are separate fields, which is why five readings failed.
    Confirmed against `simeonpilgrim/coab` and verified on our own 29 files at
    0.991 edge reciprocity. See [GEO is solved](50-experiments.md).
    What remains is **which file is which area**, and bits 0-6 of plane 2.
13. ~~**The monster table.**~~ ✅ **Largely done.** 117 files, `MON00`-`MON7C`,
    one monster each, using the **character record layout** — which is why the
    race table ends `MONSTER=8`. Names, abilities, class, age and hit points all
    decode; armour class, hit dice and experience value do not yet.

### Prove one change at a time through edits

Strictly one variable per experiment, each verified by loading the game and *looking at the
character sheet*. Order chosen so failures are cheap and unambiguous:

1. ~~**Platinum.**~~ ✅ **DONE, and then some — [the thirteen-field edit](50-experiments.md).** Thirteen fields were changed
   at once — all six ability scores and all seven money types — and every one showed
   up in the game. No checksum, no rejection.
2. ~~**An ability score (STR).**~~ ✅ **DONE, and it found the cache.** All six abilities
   were set to 18. The sheet then showed **AC 8**, the value for his *old* DEX of 16.
   That located a real caching rule: **armour class is cached, not recomputed on load.**
   The cache was later found in the `SAVEDGAME1` roster blocks (`+0x0F`, stored as
   `60 - AC`), and the game only refreshes it when *equipment* changes. Editing an
   ability score alone leaves derived values stale.
3. ~~**A checksum probe.**~~ ✅ **Answered incidentally.** Thirteen edited bytes were
   accepted without complaint, so the game does not validate the save. A dedicated
   corruption probe is no longer needed.

Each proof is committed with its `docs/50-experiments.md` entry and a regression test that
round-trips the record through `record.py` unchanged.

**Still to prove.** Everything above was proven by [the thirteen-field edit](50-experiments.md) or earlier. Every field found
since was located by diffing and has *never been written back and confirmed in
game* — being able to read a field is not evidence we can change it. Each of
these is one edit and one look at the character sheet:

6. **Armour class** (`SAVEDGAME1` `+0x0F`, as `60 - AC`) — the first real test of
   whether the roster blocks are writable at all, and whether the game trusts the
   cache or recomputes over it.
7. **Current hit points** (`+0x19`) and **movement** (`+0x1B`), same blocks.
8. **Experience**, and whether the game re-derives level from it on load.
9. **Class, race, alignment and sex** — all decoded, none ever edited. Race and
   class are the likeliest to be rejected or to corrupt a character, so prove
   them on a throwaway party.
10. **Combat icons** (`$4BE0`) and **inventory** — found by diffing, never written.
11. **A field the game recomputes.** If AC turns out to be recomputed from
    equipment on load, the editor must write equipment rather than the cache, and
    that changes the design. There is outside evidence that it does recompute on
    *import*: the author of the 1989 BASIC editor found that setting DEX to 255 in
    an exported character brought its AC down to about −58 once imported.
12. **Level** (`0x0A0`) and the **per-class array** (`0x0C9`–`0x0CC`) — read from
    `npc_party.d64`, never written. Changing level without changing experience is
    also the cheapest probe of whether the game re-derives one from the other.
13. **A memorised spell and a spellbook entry.** Change an id at `0x020`, and
    separately set a bit in the spellbook at `0x078`, and see whether the spell
    appears in camp. Both are decoded and named now, so this tests writing rather
    than reading — including whether the game accepts a memorised spell the
    character does not know.
14. **A hand-built item.** Copy one of the 1989 editor's 162 records into an empty
    inventory slot and see whether the game accepts it. That is the whole of
    "constructing an item", and it is one edit away.

## Phase 3 — CLI character editor

**Landed, and in use.** `tools/wish.py` exports a party to YAML and imports an
edited YAML onto a new disk. Donald changed thirteen fields at once and confirmed
every one in the game ([the thirteen-field edit](50-experiments.md)). See `docs/95-wish-cli.md`.

Remaining, in rough order of value:

1. ~~**Read and write `SAVEDGAME1`.**~~ ✅ **DONE.** `por/savegame.py` grew a
   `RosterBlock` view over the eight roster blocks, and the YAML carries a
   `combat:` block per character: armour class, THAC0, current hit points,
   movement and the damage bonus. Writes go through the live view, so
   the nineteen unread bytes per block are never disturbed — asserted by a test
   that an armour-class edit moves exactly one byte.
2. ~~**Expose the fields found since.**~~ ✅ **DONE.** `level` (`0x0A0`) is in the
   YAML and kept in step with the per-class array, and the memorised spell list
   is exported by id with its name beside it and can be edited. Ids above 56 are
   refused, because there the table stops being spells.
3. ~~**Show items properly.**~~ ✅ **DONE.** The YAML carries `bonus`,
   `weight_lb` and `type`, with the type-table entry summarised beside it —
   damage, armour class and which classes may use the item. `por/items.py` grew
   `ItemType` and `load_item_types`.
4. ~~**Construct items**, rather than only editing existing ones.~~ ✅ **DONE**,
   including the template library: `template:` copies any of the 163 records on
   the game's own disks, which is better than the 1989 editor's hand-made ones
   and reproducible from disks we have. Removing an entry deletes the item.
   Ambiguous words, unknown templates and over-long inventories are refused.
5. ~~**Map the rest of the 32-byte roster block.**~~ ✅ **As done as our
   specimens allow.** `+0x00` and `+0x13` are `1` in every occupied block
   everywhere; `+0x1C` and `+0x1E` are zero in all twenty-four blocks of
   Donald's saves and non-zero only on the editor-hacked disk. Encumbrance and
   status are ruled out of the block.
6. ~~**Handle NPCs deliberately.**~~ ✅ **DONE** as far as reading and writing
   the marker goes. `npc:` is exported from the eight-byte fingerprint and can
   be written, with the caveat reported in the change list, and a half-set
   marker is a warning. **What the game actually permits is unknown** — see
   "how big a party is" below.
7. ~~**How big a party is, and how many NPCs it may hold.**~~ ✅ **ANSWERED.**
   The game refuses a seventh **player** character: six is the maximum, and the
   remaining two of the eight slots are NPC-only. Donald hit the limit while
   making test characters. That fits `npc_party.d64` exactly — three player
   characters and five NPCs, eight in total — and it settles a question this
   plan had two wrong answers to.
8. **Levels — what is left.** Two of the four parts are done: `level` is in the
   YAML, and editing `levels:` now carries `0x0A0` with it. Remaining:
   * **What `0x0A0` holds for a multi-class character is unknown.** Every
     specimen is single-class, where it simply equals the class level. `wish`
     currently writes the highest of the per-class levels and says so in its
     change list. Sum, maximum, or first class — no evidence either way. A
     multi-class character above level 1 settles it, and nothing else will.
   * **The level-drain pair** — undead drain levels, so the game should track a
     current and a "true" level to restore to. Expect a pair per class. Testable
     at last, now that specimens above level 1 exist.
9. **Prove a level edit in game.** Changing level without touching experience
   also answers whether the game re-derives one from the other on load, which
   decides whether the editor must write both.
10. **Every value the save holds twice.** Take each pair in
   `docs/80-fields-wanted.md` §"Values the save appears to hold twice" and find
   the circumstance that separates it. Every pair already understood turned out
   to be **base versus current** or **potential versus actual** — none was a
   redundant copy — so the two still marked ASSUMED are more likely to be hiding
   a field than to be duplicates. Concretely: get a character **level-drained by
   undead** and see whether `0x0A0` and the per-class array part company, which
   would make `0x0A0` "highest level attained" and give us the drain pair in the
   same stroke.
11. **Racial traits, properly.** `0x0AD` was the strongest candidate and is now
    **ruled out as a general trait mask**: gnomes and halflings read 0, and both
    races are rich in AD&D traits. It remains unexplained and specific to elves
    and half-elves. What is left:
    * ~~**Get specimens of the missing races.**~~ ✅ Done — `PORSAVE10.D64` has
      a gnome and a halfling, and half-orc turns out to be NPC-only and readable
      from the monster files.
    * **Repeat Donald's Gold Box Companion experiment on the C64.** Set a trait,
      change the race, save, and see which byte keeps the trait. That is what
      showed traits are stored per character rather than derived from race.
    * **Change one bit of `0x0AD` at a time** on a throwaway elf and look for a
      trait appearing or disappearing in play — the only way to map bit to
      meaning.
    * ~~**Check `0x099`.**~~ ✅ Done, and it is not a trait at all: gnomes and
      halflings read 0 with the dwarves, which makes it the **size** flag
      (small versus medium) and the icon large/small flag the editor wanted.
12. **The two class fields — partly answered.** They **can** disagree: four NPC
    records in the shipped game do, and where they part company the bitmask
    matches reality (`DWARVEN FIGHTER` has a fighter's bits, a fighter's name and
    a cleric's code). So they are not duplicates. What is still unknown is which
    one the *game reads*, and the experiment below is unchanged.
    `char_class` (`0x073`) and `class_bits` (`0x0EB`)
   encode the same thing twice and agree in all twenty specimens, so nothing says
   which the game reads. `class_bits` shares its bit order with the item-type
   usage mask, which makes it the likely answer to "what may this character
   wield" — and the likely target of Gold Box Companion's four checkboxes.
   `wish` now keeps the two in step, so separating them needs a deliberate hex
   edit rather than falling out of a `classes:` change.
13. **What the trainer does to an ability score.** One save, one score altered
    at the trainer, one save, one diff. It settles whether the game keeps a true
    score beside the current one — the pattern every other pair here has turned
    out to follow — and it is the only way to test the forum rumour that altering
    scores is penalised in play. Also the cheapest safety check available for
    `wish`, which writes those six bytes directly.
14. **Find the first quest flag.** The header `$4900`–`$4BDF` is now the only
    candidate — `SAVEDGAME1` past `$8400` turned out to be code — so whatever
    the game remembers about the world fits in `$2E0` bytes, if it is saved at
    all. The walk experiment already opened the header —
    position, facing and a counter came out of it — and left two bytes behind,
    `$4A07` and `$4BC6`, that moved only when the party left the inn. Those are
    the first candidates for indoors/outdoors or for a location flag. The
    fortune teller in the slums is the next isolated action worth diffing.
15. **Prove losslessness for states no specimen contains.** The class-field bug
    was invisible to every round-trip test, because all of them run over real
    saves and every real save has those fields in agreement. A round-trip test
    over specimens can only prove losslessness for states the specimens hold.
    Each remaining pair in `docs/80-fields-wanted.md` §"Values the save appears
    to hold twice" wants a test that **constructs** a disagreeing record and
    round-trips it: `level` against the per-class array, `hp_max` against the
    roster's current, the base and current THAC0 and armour class. The one for
    the class fields exists and is the template.
16. **Explain record byte `0x0B8`.** Unready and re-ready BRUTUS's armour,
    saving at each step, and watch whether it tracks equipment. His armour class
    is no longer a puzzle, but this byte still is.

## Phase 4 — GUI character editor  ✅ BUILT

`python -m editor [SAVE.D64]`. A PyQt6 front end over the same `por/` library.
PyInstaller packaging is still to do.

The library is already the right shape for this: `por/` holds the file formats and
`por/layout.py` is a declarative field table, so a GUI can render its widgets from
the table rather than hard-coding a form. Nothing in `por/` imports the CLI.

The gate is Phase 3 rather than any GUI work: a form that shows a character sheet
is only worth building once the fields behind it are known and writable.

**The design is in [`docs/97-editor.md`](97-editor.md).** In short: the form is a
Qt Designer `.ui` file loaded at runtime, widgets bind to `por/layout.py` fields
by `objectName` so rearranging the form needs no code change, read-only state is
derived from `por/derive.py` and the confidence levels rather than hand-listed,
and the combat icon gets a real pixel-art editor with a sixteen-colour palette.

Worth a look before designing anything: **Gold Box Explorer**
(`github.com/bsimser/Gold-Box-Explorer`). It targets the DOS games and is
probably Windows-only, so it is a reference rather than a dependency — but it is
someone else's answer to "what is worth showing about a Gold Box game's files",
and that is exactly the question a GUI has to answer.

## Phase 5 — Live memory and an automapper  ✅ BUILT (VICE only)

The `automap/` package: a PyQt6 window that reads a running game and draws the
map as the party walks. **VICE only** so far; the Commodore 64 Ultimate backend
is the reason `Target` is two methods wide and nothing else.

It is a **separate top-level package** on purpose. Decision 1 at the top of this
plan says the shipped editor is a file tool that never talks to VICE, so
everything that does is quarantined in `automap/`; `por/` and `editor/` do not
import it.

`por/` is already transport-agnostic, so this costs nothing to defer. The design
is in `docs/96-live-memory-automapper.md`.

**The map coordinates are found**, and they are not where this plan first
guessed: they are in the `SAVEDGAME0` header at `$49C0` (x), `$49C1` (y) and
`$49C2` (facing), established by walking known distances and diffing. Walking
leaves `SAVEDGAME1` byte-identical, which rules it out. Its first eight 32-byte
blocks are the party roster (see `docs/30-savegame-layout.md`); everything past
`$83FF` is still unread. `GEO*` is decoded and every Phlan city block is matched to its file, so a map can
be drawn today. **Which map a save is on is `$4BC2`**, so a save-file automapper is
complete: position, facing, walls, doors and area all decode. See
[the area id](50-experiments.md).

---

## Parallelism and subagents

Worth being specific, because most of this project is *not* parallelisable and pretending
otherwise would corrupt the results.

**Genuinely independent — good subagent tasks, safe to run concurrently:**

- **A.** `por/d64.py` + round-trip tests. Container format only; knows nothing about records.
- **B.** `por/layout.py` + `por/record.py` + `por/petscii.py`, developed against a checked-in
  580-byte `.BRUTUS` fixture. Needs no disk image and no emulator.
- **C.** Static disassembly of `LOAD/SAVE`, `CAMP`, `INIT` (`da65`) feeding
  `docs/40-memory-map.md`. Pure static analysis of files we already have.
- **D.** Research pass: build the DOS/Amiga Gold Box field checklist ("which fields should
  exist") to direct the diffing in Phase 2. Read-only, web + docs.

A and B converge at `por/savegame.py`, which is written once both have landed.

**Deliberately serial — do not fan out:**

- **Anything touching the emulator.** One VICE instance, one port 6502. Concurrent agents
  would fight over the monitor socket and over the game's single save disk. This is
  now a hard rule rather than a caution: VICE serves **one** text-monitor connection
  per run, and closing it deafens every monitor including the binary one.
- **Phase 2 differential experiments.** "Change exactly one thing, then diff" *is* the method;
  running experiments concurrently destroys the attribution that makes the results mean
  anything.
- **`por/layout.py` has exactly one owner.** It is the single source of truth for every field
  offset; several agents appending to it independently would fragment the schema and silently
  reintroduce the drift the design exists to prevent.

---

## Verification

- **Phase 0 — done, observed:** `da65` and `r2` installed; ImHex installed
  (`net.werwolv.ImHex`); with `POR_DEBUG=1` port 6502 opens within 1s, confirming
  `--share=network` was the missing piece; the MCP attaches to the already-running emulator
  (`vice_connect` -> "Connected to VICE x64sc on port 6502") and `vice_memory_read`
  (parameter is `start`, not `address`) returns memory.
  **Protocol gotcha, cost an hour if rediscovered:** VICE interleaves *unsolicited* events into
  the binary-monitor stream (type `0x62` STOPPED, `rid=0xffffffff`). A client that reads one
  response per request silently desyncs and returns the *previous* request's data. Responses
  must be matched by request id. The MCP handles this; anything hand-rolled must too.
- **Phase 1:** `pytest` — round-trip every file on `PORSAVE.D64` through `d64.py` and assert
  byte-identical output; assert `record.py` decodes BRUTUS as
  `STR 18/98, INT 16, WIS 13, DEX 14, CON 16, CHA 13`.
- **Phase 2, diffing:** each experiment is a script under `tools/` reproducing its documented
  result from checked-in "before"/"after" disk copies in `work/`.
- **Phase 2, edits:** the real test is visual — launch via the existing wrapper, load the
  edited save, confirm the character sheet shows the changed value. A change that survives a
  save/reload cycle unchanged is the acceptance bar.
