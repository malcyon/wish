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

**All five phases below have landed, and the scope has grown past what this plan
scoped.** The editor and the automapper are one PyQt6 window; the CLI is a
separate command; `por/games.py` carries six titles rather than one; the `GEO`
maps, the `ECL` bytecode VM and the persistent quest flags are all decoded,
none of which a character editor needs. This document is kept as the plan it
was — the reasoning, and the errors it records on purpose — but
**[README.md](README.md) is the current statement of where things stand**, and
the per-topic docs 96 through 128 are where live work is written up.

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
- The sandbox once had **no `shared=network`**, so a host-side client could not reach
  `127.0.0.1:6502`; the fix was `--share=network` on the `flatpak run` line in
  `~/.local/bin/pool-of-radiance`. **`shared=network` is now granted to the app**, so that
  gotcha is history. The flatpak also grants `filesystems=home`, which is why a config or a
  disk copy under `/home/donald/src/wish/work/` is visible inside it.
- `c1541` works from the Flatpak (`flatpak run --command=c1541 net.sf.VICE`) and reaches
  `/mnt/media` (it is in the Flatpak's filesystem grants).
- `/home/donald/src/wish` is an empty repo already seeded with the standard Python `.gitignore`.
- Python 3.12; `uv` and `pipx` available; no PyQt yet; no 6502 toolchain.
- **VICE is configured with JiffyDOS.** At launch the game asks whether to disable its own
  fastloader — the correct answer on this machine is **`Y`** (JiffyDOS does the fast loading).
  Every scripted launch and every written repro step must answer this prompt, or the symptom
  looks like a corrupt disk image rather than a loader conflict.

**Safety rule for the whole project:** never write to
`/home/donald/c64/Pool of Radiance Disks/*` — which is the spelling `CLAUDE.md` and the code
use for the same directory `/mnt/media/roms/c64/Pool of Radiance Disks/` names through a
symlink. Copy disks into `work/` first. `POOL1.D64.orig`
is the pristine side-1 image — `POOL1.D64` has already been modified by the game (it has a
`.brutus` written to it), so diff against `.orig`, not against `POOL1.D64`.

---

## Repository layout

One repo, split along the **packaging** boundary so PyInstaller bundles the editor without
dragging in throwaway discovery scripts. Cheap now, irritating to retrofit later.

As planned:

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

**The boundary held; the package count did not.** `por/` is still transport-free
and still the single source of truth, and `editor/` still never imports
`automap/`. What was added:

| package | why it is not in the plan above |
|---|---|
| `automap/` | Phase 5. Quarantined so the "editor never talks to VICE" promise is structural rather than a convention |
| `wish/` | the tabbed window, the single shared live connection, the backend registry — see [99-one-window.md](99-one-window.md) |
| `packaging/` | PyInstaller entry point and the Windows console-stream repair |
| `skills/goldbox/` | the transferable method, for a cold agent on a new title |

`tools/wish.py` breaks the "never ships" rule for `tools/` deliberately: the CLI
is `wish-cli` and it is in the wheel. Everything else under `tools/` is still
discovery.

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
   **Still registered, and no longer the only client.** The project grew its own
   monitor client, `automap/vice.py`, because the shipped tool cannot hold a
   connection open across a session and the whole automapper depends on that. Use
   the MCP for one-off probes; use `automap/vice.py` for anything that walks. Both
   must match responses **by request id** — see the protocol gotcha under
   Verification — and only one of them may be attached at a time.
5. `uv init` the repo; add `pytest`. PyQt6 is not installed until Phase 4.

Not installing **RetroDebugger**: it has no Linux AppImage or .deb (CMake source build via
`build-linux.sh`), so it means maintaining a second VICE build, and its real-time memory view is
already covered by the MCP's `vice_memory_read` plus watchpoints. Revisit only if we hit
something those cannot show us.

## Phase 1 — The library and the knowledge base  ✅ COMPLETE

Build `por/d64.py`, `por/layout.py`, `por/record.py`, `por/savegame.py` and the `tools/` scripts.
No emulator involvement in any of this code.

**Knowledge base** — written as we go, not at the end. The eight documents this
phase planned all exist and have been joined by forty more;
**[README.md](README.md) is the index** and is the only place that lists them
all, because a second list is a list that goes stale. Three of them carry rules
rather than findings and are worth naming here:

- `docs/50-experiments.md` — append-only log: hypothesis, method, result, date. Failed
  experiments stay in; they are the expensive knowledge, and this is the only
  document that gets length.
- `docs/20-character-record.md` — **generated** from `por/layout.py` by
  `tools/gendocs.py`, so it cannot drift from the code. `85`, `86`, `87`, `88`
  and `89` are generated too, and need a game disk.
- `docs/README.md` — index, plus an honest settled / open / blocked summary.

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
4. ~~**Watchpoints, via the MCP.**~~ ~~❌ Abandoned — they never worked.~~
   ✅ **They work, and the abandonment was wrong.** Repeated early attempts either
   reported no hits on bytes that were unquestionably read, or fired and left the
   machine stopped because the hit was never acknowledged. The cause was not the
   `CHECKPOINT_SET` encoding: it is that **the connection must be held open and
   `resume()`d rather than closed** — VICE re-enters the monitor on the connection
   that was live when it stopped, and with that socket gone the emulator freezes.
   Held open, watchpoints settled the character-creation question in one run. See
   `docs/70-driving-the-game.md`. The corollary is the hazard: **never leave a
   checkpoint armed when a socket closes**, and delete every checkpoint at the end
   of every experiment.
5. **Disassemble the save path only.** ⏳ *Still not started for `LOAD/SAVE`* — the
   tooling is proven and it has simply never been needed for save data.
   **The rest of this item is superseded.** "No whole-game disassembly — the
   overlay data is out of scope for a character editor" was right about the
   editor and wrong about the project: `ECL*` is decoded to 100% of every byte
   across thirty scripts, `GEO*` is decoded and every Phlan city block matched to
   its file, `MON*` parses through the character record, and static scans of
   `DUNGEON`, `COMBAT`, `CAMP`, `GEN`, `LIBRARY` and `SPELLE*` are what named the
   level-drain pair, the NPC flag, the effect list and the class ceilings after
   months of save-diffing had failed on them. Reading the code turned out to be
   the cheapest technique in the project, not the most expensive.
6. **The fields still unfound.** The list this item carried has almost entirely
   closed. `0x0AD` is not a racial trait mask with "no decoded meaning" — it is a
   ten-slot list of **active effect codes**, seeded per race by `GEN $0BF3` from a
   table indexed by the race byte, and its 129-code namespace is named (44
   CONFIRMED, 84 PROBABLE) in `por/traits.py`. The level-drain pair is `0x0A1`/
   `0x0A2`, read off the drain and restoration routines. Every one of the sixteen
   item bytes is read. The portrait pair, the size flag, THAC0, damage and the
   party's map coordinates at `$49C0`/`$49C1`/`$49C2` were already found when this
   was written.
   The full list with its evidence lives in
   `docs/80-fields-wanted.md` §Still wanted — that file is the source of truth and
   this list is deliberately not a copy of it.
7. **The rest of the `SAVEDGAME1` roster block.** Its extent is settled — eight
   blocks filling `$8300`–`$83FF` — and about nineteen of the thirty-two bytes per
   block are still unread. THAC0 turned out to be `+0x0E`, stored as `60 - THAC0`
   exactly as AC is at `+0x0F`, which makes **damage** the next thing to look for
   and `60 - x` the first encoding to try. Roster byte `+0x0C` is a specific open
   question: `$80` for every NPC in one save and for one player character in
   another.
8. ~~**Record byte `0x0B8`** — an unexplained equipment-linked byte with nothing
   pinned to it.~~ ✅ **Explained, and it was never equipment-linked.**
   **Bit 7 is the "this is an NPC or a monster" flag** — the byte the game itself
   tests, in every overlay, and the one the party-count routine tallies player
   characters with under a `CMP #$06` that is the six-PC limit in code rather
   than in anecdote. **Bit 0 records that an ability score was altered at the
   trainer**: `GEN $155D` sets it straight after `INC`/`DEC $6B14,X` and clears it
   again if the change is cancelled — and *nothing anywhere reads it back*, which
   is the answer to the forum rumour that altering a score is penalised in play.
   BRUTUS's 0 → 1 was bit 0, not equipment. The DOS record additionally reads
   bits 0–6 as morale, which is PROBABLE here.
9. ~~**Item effect bytes.**~~ ✅ **Done. `+5` is a signed saving-throw bonus** —
   which is why CURSED NECKLACE alone reads 251, i.e. −5. Every one of the
   sixteen bytes is read: `+0` indexes the `ITEMS` type table, `+6`'s low bits are
   the hidden-name mask, `+7` bit 7 is cursed, `+13`–`+15` are a scroll's spells
   or a wand's charges, and `+14` is an effect id or a spell id according to
   `+15` bit 7.
10. ~~**What marks an NPC.**~~ ✅ **`0x0B8` bit 7** (see item 8), and `wish` writes
    that bit alone. The eight `$FF` bytes this item pointed at are **fill
    residue**: they already read `$FF` in the shipped `MON*` files, before any
    save exists. `wish` leaves them untouched.
11. ~~**The spell id table.**~~ ✅ **DONE.** `SPELLN00`, read through its pointer
    table because the strings overlap. Six class/level groups, ids 1-55. See
    `docs/86-spell-table.md`.
12. ~~**Decode the `GEO` map files.**~~ ✅ **DONE.** Four 256-byte planes over a
    16×16 grid: wall art as a nibble per edge in planes 0 and 1, square
    attributes in plane 2, and passability as **two bits per edge** in plane 3.
    A wall and a barrier are separate fields, which is why five readings failed.
    Confirmed against `simeonpilgrim/coab` and verified on our own 29 files at
    0.991 edge reciprocity, and independently against the community's ImHex
    `GB_GEO` pattern, which parses the same four planes for all ten titles. See
    [GEO is solved](50-experiments.md).
    Both remainders have closed: **which file is which area** — nine Phlan city
    blocks matched at φ 0.733 to 0.992 with nothing else above 0.316, and the
    area id is `$4BC2` — and **bits 0-6 of plane 2**, which are a per-square
    **script id**: the area's own ECL does `AND <mask>, ATTR, [v]` then
    `ONGOTO idx=[v]`. The mask is the area's, not ours: eighteen scripts mask
    `$7F`, the dungeon-floor family masks `$1F`, and in that family alone the two
    freed bits suppress a random encounter and halve its rate.
13. ~~**The monster table.**~~ ✅ **Done.** 117 files, `MON00`-`MON7C`,
    one monster each, using the **character record layout** — which is why the
    race table ends `MONSTER=8`. The three that did not decode when this was
    written now do: **armour class** is `0x0E1` as `60 - AC`, **hit dice** is the
    attack block at `0x0D9`-`0x0E0`, and **experience value** is `0x0F7`-`0x0F8`
    with a per-hit-point bonus at `0x0F9` — proven from `POST.COM $09BB` and
    checked against the published AD&D 1e awards (GOBLIN GUARD 10, HOBGOBLIN 20,
    OGRE 90). `0x0D7` is the creature type, and `0x10C` the combat behaviour.

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

6. ~~**Armour class** (`SAVEDGAME1` `+0x0F`, as `60 - AC`)~~ ✅ **DONE, and the
   roster blocks are writable.** MALCYON was edited to armour class 1 and 11 hit
   points — two bytes, `$830F` and `$8319`, with `SAVEDGAME0` byte-identical —
   booted, and the game showed `AC 1` and `HITPOINTS 11` on both the party list
   and the character sheet, then wrote the same page back when it saved. **The
   game reads that cache and does not recompute over it.** Everything living only
   in the roster is editable for real.
7. ~~**Current hit points** (`+0x19`)~~ ✅ done in the same edit. **Movement**
   (`+0x1B`) is still unwritten.
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
14. ~~**A hand-built item.**~~ ✅ **DONE — the game accepts a constructed item.**
    See [a constructed item is accepted by the game](50-experiments.md). And the
    1989 editor's 162 hand-made records are no longer the source: `template:`
    copies any of the **163 real records off the game's own disks**, which brings
    the bytes we do not understand with it. `docs/87-item-templates.md` lists them.

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
   * ~~**The level-drain pair** — expect a current and a "true" level, a pair per
     class.~~ **Found, and it is not that shape.** `0x0A0` is the current level
     and `0x0A1`/`0x0A2` are how many levels and hit points the drain took — a
     current-plus-delta pair, not current-and-true, which is why no "true level"
     was ever found and why there is only one pair rather than one per class. Read
     off the routines: `SPELLE02` loops `DEC $6B76 / DEC $6BED / INC $6BA2 /
     DEC $6C19` then `INC $6BA1`, and `RESTORATION` in `SPELLE04` reverses it
     exactly. What is still wanted is a **specimen** — no character of ours has
     been drained in play.
9. **Prove a level edit in game.** Changing level without touching experience
   also answers whether the game re-derives one from the other on load, which
   decides whether the editor must write both.
10. **Every value the save holds twice.** Take each pair in
   `docs/80-fields-wanted.md` §"Values the save appears to hold twice" and find
   the circumstance that separates it. Every pair already understood turned out
   to be **base versus current** or **potential versus actual** — none was a
   redundant copy — so the two still marked ASSUMED are more likely to be hiding
   a field than to be duplicates. The concrete experiment this item proposed —
   drain a character and see whether `0x0A0` and the per-class array part company,
   making `0x0A0` "highest level attained" — has been answered the other way, and
   without the emulator: **there is no "highest level attained"** (item 8 above).
   The saving throws have gone the same way: they looked like a stored value with
   no derivation and turned out to be **derivable exactly** — the class-table row
   for the level, best number in each column across every class held, minus the
   AD&D constitution bonus for a dwarf, gnome or halfling, satisfied by 78 of 79
   records.
11. ~~**Racial traits, properly.** `0x0AD` … remains unexplained and specific to
    elves and half-elves.~~ ✅ **Explained, and by reading the code rather than by
    flipping bits.** `GEN $0BF3` seeds the list from `[1, 0, 107, 0, 124, 0, 0, 0]`
    **indexed by the race byte itself**, which is 1-based: elf is race 2 and is
    born with 107, half-elf is race 4 and is born with 124, and every other race
    is born with an empty block. That is exactly the "specific to elves and
    half-elves" pattern, with the reason.
    It is not a trait *mask* at all: it is **ten slots of active effect codes**,
    written by spells and readied items as well as by birth, and sharing storage
    (but not meaning) with item byte `+14`. The namespace is named — 129 codes,
    44 CONFIRMED off `MON*` carriers and the *Monster Manual*, 84 PROBABLE from
    the DOS guide. `por/traits.py`.
    * ~~**Get specimens of the missing races.**~~ ✅ Done — `PORSAVE10.D64` has
      a gnome and a halfling, and half-orc turns out to be NPC-only and readable
      from the monster files.
    * ~~**Change one bit of `0x0AD` at a time** on a throwaway elf.~~ No longer
      the only way to map code to meaning, and it was never going to be a *bit*
      map — each slot holds a whole code.
    * ~~**Check `0x099`.**~~ ✅ Done, and it is not a trait at all: gnomes and
      halflings read 0 with the dwarves, which makes it the **size** flag
      (small versus large) and the icon large/small flag the editor wanted.
12. ~~**The two class fields — partly answered.**~~ ✅ **Answered.** They are
    **different fields, not two copies of one**, proved by building a save where
    they disagree and looking at what the game did with it: **`0x073` is what the
    character sheet prints, and `0x0EB` is what the game ANDs against an item's
    class-usage byte.** So "which one does the game read" has no single answer —
    each is read for its own purpose, which is why the shipped `DWARVEN FIGHTER`
    can carry a fighter's bits and a cleric's code without being broken.
    `class_bits` remains the field to prefer for anything about capability.
13. **What the trainer does to an ability score.** ✅ **Largely answered from the
    code.** `GEN $155D` sets **bit 0 of `0x0B8`** immediately after the
    `INC`/`DEC $6B14,X` that moves the score, and clears it again if the change is
    cancelled. **Nothing anywhere reads that bit back**, which is as close as a
    static read gets to disposing of the forum rumour that altering scores is
    penalised in play. No second "true score" array was found beside the six
    bytes — but note that *Curse* fills a second seven-byte ability array at
    `0x065` which Pool of Radiance leaves at zero, and which of the two that game
    treats as current is still NOT FOUND (`docs/116` §2.2). One trainer
    before-and-after diff would still be worth having.
14. ~~**Find the first quest flag.**~~ ✅ **Done, and then the whole region.** The
    prediction held: it is in the header, and `$4A20`–`$4AF8` is the persistent
    block. `work/reports/quest-flags.md` gives all 352 bytes of `$4A20`–`$4B7F` a
    disposition — 172 named by a direct ECL operand, 7 more as proven table
    interiors, **135 shown not to be flag storage at all**, and 38 unreferenced
    gaps. `$4A00`–`$4A1F` is per-script scratch that `DUNGEON $282E` zeroes on
    every area change, which fixes the lower boundary exactly. The DOS guide
    independently names 229 of the same addresses in English and agrees on both
    boundaries and on all five unreferenced gaps. `por/commissions.py` reads the
    26-entry quest ledger at `$4AA6` and the editor draws it as a quest panel.
15. **Prove losslessness for states no specimen contains.** The class-field bug
    was invisible to every round-trip test, because all of them run over real
    saves and every real save has those fields in agreement. A round-trip test
    over specimens can only prove losslessness for states the specimens hold.
    Each remaining pair in `docs/80-fields-wanted.md` §"Values the save appears
    to hold twice" wants a test that **constructs** a disagreeing record and
    round-trips it: `level` against the per-class array, `hp_max` against the
    roster's current, the base and current THAC0 and armour class. The one for
    the class fields exists and is the template.
16. ~~**Explain record byte `0x0B8`.**~~ ✅ Done — see Phase 2 item 8. It does not
    track equipment; bit 7 is the NPC flag and bit 0 is the trainer's
    score-altered marker.

## Phase 4 — GUI character editor  ✅ BUILT

`wish`, on the Character Editor tab of the one window; `python -m editor` still
opens it alone. A PyQt6 front end over the same `por/` library.

**PyInstaller packaging is built too** — `wish.spec`, a `packaging/` entry point
that repairs the Windows console streams, and a `release.yml` that runs the whole
suite before it builds anything and asserts on `wish.exe --version`. What has not
happened is a **tag**: nothing below has been run against a real release page.
See [106-releases.md](106-releases.md) and [122-release-testing.md](122-release-testing.md).

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
map as the party walks, and swaps to a combat view while a fight is on. **VICE is
the only backend anyone has run.** A Commodore 64 Ultimate backend is written, in
`wish/ultimate.py`, and is **unverified** because nobody on the project has the
hardware; it is offered only when `$POR_ULTIMATE` names a device that answers.

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
`$83FF` is **resident code and a graphics buffer**, not save data at all.
`GEO*` is decoded and every Phlan city block is matched to its file, so a map can
be drawn today. **Which map a save is on is `$4BC2`**, so a save-file automapper is
complete: position, facing, walls, doors and area all decode. See
[the area id](50-experiments.md).

Two live findings this plan could not have predicted. **`$49C0` lags a move** —
read straight after a step it gives the previous square — so the mapper reads the
game's own status line first and falls back to memory, tagging each fix with its
source. And **the running game leaves the whole `GEO` at `$0400`**: the file is a
PRG loading there and the loader does not relocate it, so in the world (where the
screen has moved to `$CC00`) the map is simply sitting in RAM to be read.

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
  now a hard rule rather than a caution: VICE serves **one** binary-monitor connection
  *per process* — it accepts a second TCP connection and then silently ignores it — and
  closing the text monitor deafens every monitor including the binary one.
  **The limit is per process, not per machine**, so the way out is a pool of
  emulators rather than a queue of agents; that is costed in
  [123-parallel-sessions.md](123-parallel-sessions.md) and **nothing is built**,
  so the one-instance rule stands until it is.
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
  `--share=network` was the missing piece at the time; the MCP attaches to the already-running emulator
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
