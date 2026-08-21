---
name: goldbox
description: Reverse engineer a Commodore 64 SSI Gold Box game — Pool of Radiance, Curse of the Azure Bonds or a successor title. Use when decoding a Gold Box D64, save-game or character-record format, matching GEO map files to areas, reading a running game's memory, or building or validating an automapper for a title the project has not done yet. Carries the order of attack, the shared-format facts that transfer between titles, the confidence discipline, and the recipe for locating live data whose addresses are unknown.
---

# Reverse engineering a C64 Gold Box game

## Lead with this: most of the format is already solved

**Curse of the Azure Bonds uses the same 580-byte character record as Pool of
Radiance, at the same offsets.** That is the single most valuable transferable
fact in this project, and it is the first thing to exploit on any new title.

The evidence is the game's own arithmetic, not a diff of two specimens: a Pool
of Radiance export was imported into Curse through `ADD CHARACTER TO PARTY →
POOL`, exported again, and **15 of its 580 bytes had changed**. Name,
abilities, race, age, hit points, saving throws, level, experience, per-class
levels, class bits, alignment, spellbook and the 36-byte combat icon all
survived byte for byte. `por.record.CharacterRecord` parses a Curse export and
round-trips it byte-identically with no code change; `por.geo` decodes all
sixteen Curse `GEO` files with no change at all.

**So the first hour on a new title is not analysis, it is aiming the existing
decoders at it.** Point `por/record.py`, `por/geo.py`, `por/items.py` and
`por/savegame.py` at the new game's disks and record what round-trips, what
decodes to sane values, and what does not. What fails is your actual work list;
everything else is done. Assume the format transfers and make the game
disprove it — the opposite assumption cost this project a re-derivation it did
not need.

## What transfers, and what does not

| Transfers — assume it, then check | Does not transfer — re-derive it every time |
|---|---|
| 580-byte character record, offset for offset | Every absolute address: save base, export load address, resident bases |
| The record is four blocks the game saves separately: `0x000`-`0x0FF` slot, `0x100`-`0x11F` roster, `0x120`-`0x21F` items, `0x220`-`0x243` icon | How many files a save disk holds, and their names |
| Biased encodings: `60 - value` (THAC0, armour class), `48 + value` (armour bonus), `12 - AC` (item protection nibble) | The character-file marker byte (`$01` vs `$02`) |
| Race 1-based, class 0-based, `class_bits` the field to prefer; per-class level array eight wide at `0x0C9` | Which classes the title implements inside those eight slots |
| Base-versus-current: the record holds base values, the roster block holds the derived current ones | Which file the roster block lives in |
| `GEO` maps: 1024 bytes, four 256-byte planes, 16×16, indexed `x + (y << 4)` | Which `GEO` file is which area — always local, always earned |
| The ECL bytecode VM: opcode table, operand encoding, 6-bit packed strings, plane-`$200` byte as the script id | The ECL block's base address (`$9900` in C64 Pool of Radiance, `$8000` in DOS) |
| `ITEMNAMES` as 256 low + 256 high + strings; `ITEMS` as 128 × 16; 16-byte item records | The file stems present at all — Curse has no `SPELLN`; its spell names live in `COMBAT2` |
| D64 container; saves are verbatim uncompressed memory images with no checksum | Screen layout, status-line row, menu wording |
| Spell ids 1-56 | Spell ids past 56, and the number of character slots |

The two things most likely to mislead: **overlay bases**, because every overlay
lies about its load address, and **which map is which area**, because a map
decoded correctly is still a floor plan of nowhere until it is anchored.

Detail: [references/transfer.md](references/transfer.md).

## The order of attack

Each step is cheaper than the one below it and produces the ground truth the
next one needs. Do not skip forward — the emulator work at the bottom is
serialised, slow, and unfalsifiable without the artefacts above it.

| # | Step | Needs | Artefact | Cheap? |
|---|---|---|---|---|
| 1 | Read the disk directory; walk sector chains | the player's disks | file list with sizes and load addresses | yes |
| 2 | Inventory by stem, size uniformity and entropy | step 1 | which family is maps, which is graphics, which is code | yes |
| 3 | Decode the save game: find its load address, diff two saves | one or two saves | base address, party position, area id | yes |
| 4 | Decode the character record with the existing table | one export | a field table that tiles all 580 bytes | **cheapest** |
| 5 | Decode the map files; verify by reciprocity | step 2 | `Geo` objects with a self-check | yes |
| 6 | Read a running game: find the live bases | VICE | resident bases, the party fix | no |
| 7 | Automapper, then validate it by driving the game | steps 5 and 6 | a mapper whose every claim is asserted | no |

**Why this order.** Steps 1-5 need no emulator and no permission from anyone;
they are reproducible, parallelisable across agents, and every result is a file
you can re-derive. Step 6 costs a single serialised VICE connection. Step 7
costs a driven session that can wedge the emulator. Spending emulator time on a
question a disk read would answer is the most common way to lose a day here.

**The three cheapest wins, in order:**

1. **Point the existing record decoder at the new game's export.** If it
   round-trips byte-identically, 580 bytes of layout just transferred for free.
2. **Reciprocity on the map files.** The east edge of a square is the west edge
   of its neighbour, so a `GEO` file checks its own parse with no ground truth
   at all: a correct decode scores 0.98+, a wrong one scores about 0.3.
3. **Two saves either side of one deliberate act.** Save, do exactly one thing,
   save again, diff. This method carried the whole project.

## Load addresses and overlays

**An address is only meaningful while the overlay that owns it is resident.**
The game loads code and data on demand; the same bytes hold different routines
five minutes apart. Patching an address blind a second time corrupted a live
routine in this project.

Three rules that fall out:

* **Every overlay lies about its load address.** In Pool of Radiance every
  overlay declares `$1000` in its PRG header and every one actually runs at
  `$0800`. `LIBRARY` is at `$2C48`, `SPELLE04` at `$A700`, `ECL*` at `$9900`,
  `MON*` at `$6B00`. None of that is in a header.
* **Establish a resident base by fitting, not by reading.** This project fixed
  `$0800` by scoring internal `JSR` targets — 480 to 550 land inside the file at
  `$0800` and near zero elsewhere — and fixed `LIBRARY` at `$2C48` against
  `$2C47` by three independent patch sites plus JSR-target alignment (359 of 522
  against 290). Two independent methods agreeing is the bar.
* **Some bases are fixed and that is the whole technique.** The character record
  answers to a fixed `$6B00` in Pool of Radiance, so `LDA $6BA0` *is* record
  offset `0x0A0`. Scanning every absolute operand in `$6B00`-`$6D44` across every
  file on the disks yields a map of which offsets the game's own code touches —
  and that unlocked level drain, the NPC flag, the effect list and the last item
  bytes after months of save-diffing had failed on them.

**Read and check the bytes before every write.** Every time.

More: [references/live-memory.md](references/live-memory.md).

## The confidence discipline

Every claim carries one of four labels, and the label is part of the claim.

| Label | Means | Promoted by |
|---|---|---|
| `CONFIRMED` | corroborated across specimens, or checked against an external rule (an AD&D table, the game's own code, the game's own printed output) | a second independent line of evidence, or a write-back that appears in game |
| `PROBABLE` | consistent with all evidence held, not independently verified | finding the code that reads it, or a specimen that could have contradicted it and did not |
| `GUESS` | a plausible reading that something about the data contradicts | usually nothing — guesses are demoted more often than promoted |
| `UNKNOWN` | not understood; bytes preserved verbatim | any of the above |

**A wrong `CONFIRMED` is worse than an honest `UNKNOWN`.** An `UNKNOWN` invites
work; a wrong `CONFIRMED` stops it, and it propagates into generated docs, into
the editor, and into whatever the next agent assumes. This project has demoted
claims more than once and each demotion cost more than the original caution
would have.

Four working rules the log paid for:

* **A hypothesis that sparse data agrees with has not been tested.** "`$400` × 6
  slots" survived because every specimen then held at most two characters and the
  bytes between them were zero. One full party disproved it instantly.
* **A negative needs a negative example.** "No byte in the header identifies the
  map" was reported from ten saves that were all in the same area. The byte was
  `$4BC2`, in the range that had been scanned.
* **Repeating a wrong assumption is not corroboration.** "Four runs died at the
  training hall" was four runs of one wrong assumption, not four pieces of
  evidence.
* **Make the table tile the whole record.** `por/layout.py` asserts at import
  time that every one of the 580 bytes belongs to exactly one entry, gaps
  included. That makes an edit byte-exact by construction and makes overlaps
  impossible to introduce silently.

## Finding live data when you do not know the addresses

**Assume live data is not where you think it is.** The addresses in
`por/memory.py` are Pool of Radiance's. Curse shifts the whole save image by
`$200`, and no rule says the next title shifts by anything so tidy.

The recipe, in order of decisiveness:

1. **Find the save image in RAM.** A Gold Box save is a *verbatim memory
   image*, so take the save payload, take a 256-byte run from the middle of it,
   and search the machine's 64K for that run. The offset names the base
   exactly, in one step, with no inference. Do it with the same save loaded that
   you searched with.
2. **If that fails, search for a value you know.** Best candidates, in order:
   a **character name** (a 6+ letter ASCII run, NUL-padded, effectively unique);
   the **party's coordinates** as a byte pair matching what the status line
   shows; a **hit-point total** you can read off the character sheet. Names are
   worth trying first because a hit is unambiguous.
3. **Corroborate with a second value at a known relative offset.** Having found
   a name at some address `A`, `A + 0x14` should be strength, `A + 0x76` hit
   points maximum, `A + 0x0EB` the class bitmask. If three of those decode
   sanely, `A` is a slot base. The stride falls out of the second character's
   name.
4. **Corroborate again by changing it.** Walk one square and watch x or y
   change; buy armour and watch the roster's `+0x0F` byte move; take a wound and
   watch current hit points fall. A byte that moves the way you predicted, when
   you predicted, is the strongest single piece of evidence available short of
   reading the code.
5. **Then read the code.** Scan every file on the disks for absolute operands
   landing in the region. What reads and writes an address tells you what it is;
   correlation only tells you what it correlates with.

### The `$49C0` lesson: the obvious address is not always the live one

`$49C0`/`$49C1`/`$49C2` genuinely are the party's x, y and facing, and they
genuinely are what reaches the disk. **They also lag a move**: read straight
after a step, they give the *previous* square. The game's own status line —
`E 16:48  5,2`, facing, clock, x, y — is correct the moment the screen settles.

So the automapper reads the status line first and falls back to memory only
when the status line is not on screen (camp, combat, a menu), and it tags each
fix with its `source`. Two consequences worth carrying to any title:

* **Prefer the value the game displays over the value you believe it stores**,
  then confirm the two agree at rest. Where they disagree, the display is the
  live truth and the memory copy is a cache with its own update rule.
* **A cache has an update rule and you must find it.** Armour class in the
  roster block is not recomputed on load — it is refreshed only when *equipment*
  changes. Editing dexterity leaves it stale, which looked for a while like the
  edit had failed.

And always **validate before trust**: because of overlays, read the region,
check it still decodes as a sane party, and refuse to draw or write if it does
not. `automap.target._plausible` and `PartyFix` exist for exactly this.

Full recipe with the monitor's sharp edges:
[references/live-memory.md](references/live-memory.md).

## Driving the game to validate the automapper

This is the test that catches "live data is not where we thought". A mapper
reading the wrong address does not error — it draws a party walking through
walls, and it looks fine until somebody checks.

**The harness.** Three layers, all present in this repository as working
examples:

| Layer | What it does | Example |
|---|---|---|
| Monitor client | one held-open binary-monitor connection; responses matched by request id; `resume()` after each burst | `automap/vice.py` |
| Session | boots the game, answers the disk prompts, loads a save, gets into the world, walks, saves | `tools/session.py` |
| Runner | walks a scripted route, records position before and after every step, writes one save disk per step and a manifest | `tools/walkrun.py` |

**The route is scripted in the game's own letters** — `I` forward, `J` turn
left, `K` turn right, `M` step backward — and every step records the square
before and after. A forward step whose square did not change is a **wall**, and
that is the whole point of the corpus.

**What the validation asserts**, at every step of the route:

1. **Position and facing.** The mapper's fix equals the machine's — status line
   and memory agreeing at rest — and equals the `$49C0`/`$49C1`/`$49C2` bytes
   read back out of the save disk written at that step.
2. **Every square the party occupies is walkable** in the decoded map.
3. **Every step the party completed crossed a passable edge** in the decoded map.
4. **Every step the game refused corresponds to an impassable edge.** This is
   the strongest single observation available: impassable edges are rare, so one
   refusal identifies the map where 111 successful steps would be needed to do it
   from positive evidence alone.
5. **Area identification switches when the party crosses an area boundary.**
   The Pool of Radiance boundary pair is the model: `(0,4)` facing west in New
   Phlan and `(15,4)` facing west in the Slums, one step apart, with the area
   byte going `$00` → `$14` — and `GEO14` is independently the file the
   wall-matching identified as the Slums at φ 0.992.

**Contradictions are counted, not obeyed.** An observation that eliminates
every candidate map is not evidence about which map this is; it is evidence
that the observation was wrong — a garbled status line, a step across a
boundary, a "refused" step that was really a bash at a locked door. Keep the
last non-empty candidate set and count the contradiction.
`automap.area.Fingerprint._narrow` does this, and a rising contradiction count
is your signal that an address is wrong.

**A bump advances the clock**, so "the clock changed" is not evidence of
movement. The map fact is that the *square* did not change on a forward step.

### Hazards — read these before connecting

* **Never leave a checkpoint armed when the socket closes.** VICE re-enters the
  monitor on the connection that was live when it stopped; with that socket gone
  the emulator freezes and only `pkill` recovers it. Delete every checkpoint at
  the end of every experiment. The automapper offers no checkpoints at all for
  this reason.
* **One binary-monitor connection at a time.** VICE accepts a second TCP
  connection and then never answers it. A stray GUI holding port 6502 makes the
  game look frozen. **Check `ss -tnp | grep 6502` before connecting**, and never
  kill a process holding the monitor without knowing what it is — that has
  killed a human's window here once already.
* **Closing the text-monitor connection kills the binary monitor too.** Open it
  once, never close it, never send `x` on it.
* **Batch reads.** The cost is per `resume()`, not per byte: a 7168-byte read
  costs the same as one `peek`, and four peeks with four resumes cost 45.9 ms
  against 14.4 ms batched. Polling does not stall the machine — it makes it run
  *fast*, about 7% at a 200 ms interval.
* Verify every driven action **by effect**. The command bar is not always
  redrawn, and the first input burst after a screen change is reliably swallowed.

Detail and the full list of what does not work:
[references/driving.md](references/driving.md), plus this project's
`docs/70-driving-the-game.md`.

## What must never enter the repository

This is reverse-engineering documentation of a game it does not ship. A cold
agent working on a new title will otherwise commit map bytes as a test fixture,
because a fixture does not feel like a copy while you are adding it. It is one.

**Never commit, in any form:** the game's art, music or sound; its manuals,
cluebooks, maps or journal text, scanned or retyped; its executable code,
overlays, PRG files or boot images; a **disassembly listing** of that code; or
its data files — maps, tables, scripts, character records — as committed bytes,
**including as test fixtures**.

Naming an address and the two or three instructions at it, as evidence for a
finding, is commentary and is fine and is encouraged. A dump of a routine is
not.

**Tests get their data from the player's own disks.** `tests/gamedata.py` is
the pattern: `game_file("GEO04")` reads it off whichever disk carries it and
`pytest.skip`s when there are none; `synthetic_geo()` builds a well-formed map
from the documented format for the cases that only need *a* file rather than a
specific one; `curse_file()` does the same for the second game behind its own
`$COAB_DISKS`. A new title gets a new finder function, never a new fixture.
`tests/test_repository_contents.py` fails the build if a disk image, executable,
image or audio file appears anywhere, or if anything new appears in
`tests/fixtures/` — **do not add to that allowlist**.

Disk images live under `work/`, which is `.gitignore`d.

Describe, cite, measure, and generate. Do not copy.

## The worked checklist

Top to bottom on a new title. Each line names what it produces; stop and record
the artefact before moving on.

| # | Do | Produces |
|---|---|---|
| 1 | Locate the player's disks behind an env var; refuse anything that is not a plain 174848-byte image | a disk finder, and a skip path for machines without the game |
| 2 | List every directory entry: name, type, first sector, block count. Walk chains by link, terminate on **track 0 only** | full file inventory |
| 3 | Group by stem; record size, uniformity and PRG load address per family | candidate families: uniform size = fixed-size records or maps |
| 4 | Compute Shannon entropy per byte per family | triage: ~1.2-2.5 record-shaped, ~3.4 structured-undecoded, 4.4-5.2 graphics, 6.2+ compressed or code |
| 5 | Take one exported character; run it through `por.record` unchanged | either 580 bytes of free layout, or a precise list of what moved |
| 6 | Diff that export against the same character inside a save | the slot size, and which record blocks the save splits out |
| 7 | Read the save's PRG load address; try Pool of Radiance's geometry at that base | header size, slot base, item area, roster location |
| 8 | Make **two saves that differ by one deliberate act**: one step, one purchase, one wound | party position, clock, the field you moved |
| 9 | Make a **boundary pair**: save, cross into another area, save | the area id — and never search for it without one |
| 10 | Decode the map family as four 256-byte planes; compute reciprocity per file | `Geo` objects, and a number that proves the parse |
| 11 | Inventory the maps: walls, doors, locked, indoor, reciprocity | indoor 256/256 = dungeon, 0/256 = wilderness, mid = town block |
| 12 | Anchor one map: match a square you have stood on, or match transcribed fan maps square by square | file-to-area assignment, with a score and a next-best score |
| 13 | Decode the item tables and spell ids with the existing readers, changing only base addresses | item names, item types, spell names |
| 14 | Start the emulator with the binary monitor; check `ss -tnp \| grep 6502` first | one connection, held open |
| 15 | Find the save image in RAM by searching for a run from the save file | the live base, exactly |
| 16 | Confirm the resident map block: search RAM for a copy of the `GEO` you are standing on | the live map address (`$0400` in Pool of Radiance — the loader does not relocate it) |
| 17 | Build the party fix: status line first, memory as fallback, `_plausible` on both | a `Fix` with a `source` tag |
| 18 | Drive a scripted route and assert all five validations above | a walk corpus, a manifest, and a mapper you can believe |
| 19 | Write every finding into the experiment log with its evidence **and its failures** | the reasoning, which is the actual product |

## References

| File | Contents |
|---|---|
| [references/transfer.md](references/transfer.md) | what is shared across the family, what is not, and the Pool of Radiance ↔ Curse constant table |
| [references/disks-and-files.md](references/disks-and-files.md) | D64 container, directory quirks, safe in-place writes, the entropy triage |
| [references/character-record.md](references/character-record.md) | the 580-byte record, the four blocks, biased encodings, base-versus-current, the layout-table discipline |
| [references/save-layout.md](references/save-layout.md) | the save as a memory image, header, slots, roster, item area, the area id |
| [references/maps.md](references/maps.md) | the `GEO` four-plane format, reciprocity, wall-versus-barrier, the script-id plane and the ECL VM |
| [references/live-memory.md](references/live-memory.md) | the search recipe, overlays and resident bases, the monitor's sharp edges |
| [references/driving.md](references/driving.md) | the driven session, input timing, disk swapping, what does not work, and the automapper validation |

In this repository, `docs/50-experiments.md` is the reasoning log and the place
new findings go — including the failures, which are most of its value.
