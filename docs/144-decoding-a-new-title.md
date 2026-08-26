# Decoding a Gold Box title nobody here has opened

The method, not the facts. How to get from a disk image of a Gold Box title
this project has never touched to a mapper you can believe, in the order that
costs least — and which of the things already known about Pool of Radiance you
may assume and which you must re-measure.

**Every format fact this page needs is somewhere else in `docs/`, and it is
cited rather than repeated.** A second copy of the byte map is exactly the
defect #64 and #76 (*`tools/dosbox.py` holds a third copy of the DOS saved
game's byte map*) were opened for. Where a number appears here it is because
the *method* turns on it.

**This is a decoding checklist, not a test plan.** It says nothing about
whether the shipped features — the editor's tabs, the CLI, the live actions,
Fast Travel, Level Up, the combat log, the commissions panel — work on a title
once it is decoded. Decoding a title is not supporting it. That is
[139-per-title-validation.md](139-per-title-validation.md), the feature × title
matrix.

## Lead with this: most of the format is already solved

**The 580-byte character record transfers, offset for offset, and the games
prove it themselves.** A Pool of Radiance export imported into Curse through
`ADD CHARACTER TO PARTY → POOL` and exported again comes back with 15 of its
580 bytes changed; a Curse record imported into Silver Blades changes **three**,
because twelve of that fifteen were Curse bringing an older record up to the
later engine's shape. What is left is only what is per-title — the race code and
the starting purse. See [116-second-game.md](116-second-game.md) §2.2 and
[121-silver-blades.md](121-silver-blades.md) §4.1 for both diffs, offset by
offset.

**So the first hour on a new title is not analysis, it is aiming the existing
decoders at it.** Point `por/record.py`, `por/geo.py`, `por/items.py` and
`por/savegame.py` at the new game's disks and record what round-trips, what
decodes to sane values, and what does not. What fails is your work list;
everything else is done. Assume the format transfers and make the game disprove
it — the opposite assumption cost this project a re-derivation it did not need.

**Add the new title to `tests/test_second_game.py` rather than forking a
decoder.** It runs the same invariants over every title through the same code
paths, so a change made for one game that moves a field or shifts a base fails
on the other side. `tests/test_silverblades.py` is the third column and it
needed no new decoder.

## What transfers, and what does not

Assume the left column; re-measure the right one every time.

| Transfers — assume it, then check | Does not transfer — re-derive it | Where the fact lives |
|---|---|---|
| The 580-byte record, offset for offset | Every absolute address: save base, export load address, resident bases | [20-character-record.md](20-character-record.md), [40-memory-map.md](40-memory-map.md) |
| The record is four blocks the game saves separately, and an export matches a save in 579 of 580 bytes | Which file the roster block lives in | [30-savegame-layout.md](30-savegame-layout.md) §"Character export vs in-party copy" |
| Base versus current: the record holds base values, the roster block the derived current ones | — | [30-savegame-layout.md](30-savegame-layout.md) |
| The biased encodings — `60 - value`, `48 + value`, `12 - AC` | — | [30-savegame-layout.md](30-savegame-layout.md), [20-character-record.md](20-character-record.md) |
| Classes 0-based, `class_bits` at `0x0EB` the field to prefer; the per-class level array eight wide at `0x0C9` | Which classes the title implements inside those eight slots, and what slot 4 is called (druid in the Realms titles, knight in the Krynn ones) | [20-character-record.md](20-character-record.md) `level_knight` |
| The race byte at `0x072` is a code | **The table it indexes.** Silver Blades drops half-orc and human becomes 6; the Krynn titles are 0-based | `por/games.py`, one list per title |
| Save container geometry, payload-relative | The payload's **base** — but only three values across six titles | `por/games.py`; [116](116-second-game.md), [121](121-silver-blades.md) |
| The spellbook mask is indexed `0x078 + (id >> 3)` and its declared extent is `0x078`-`0x087` | **How many of those bytes a title actually reads** — 7, 13 and 16 for Pool of Radiance, Curse and Silver Blades, each measured in that title's own code | [20-character-record.md](20-character-record.md) `spells_known_high` |
| `GEO` maps: 1024 bytes, four 256-byte planes, 16×16, `x + (y << 4)` | Which `GEO` file is which area — always local, always earned | [88-map-files.md](88-map-files.md) |
| `GEO` ids are **not a range**. Enumerate by directory scan | Which ids a title uses; Silver Blades' high nibble is the disk side | [138-multiple-games.md](138-multiple-games.md) §2 |
| The ECL bytecode VM: opcode table, operand encoding, 6-bit packed strings, the plane-`$200` byte as the script id | The ECL block's base address | [88-map-files.md](88-map-files.md), [128-guide-and-scripting.md](128-guide-and-scripting.md) |
| `ITEMNAMES` as 256 low + 256 high + strings; `ITEMS` as 128 × 16 | Which file stems exist at all — Curse has no `SPELLN00` and keeps its spell names in `COMBAT2` | [85-item-tables.md](85-item-tables.md), [00-overview.md](00-overview.md) |
| D64 container; saves are verbatim uncompressed memory images with no checksum | Screen layout, status-line row, menu wording, disk prompts and side letters | [10-disk-format.md](10-disk-format.md), [70-driving-the-game.md](70-driving-the-game.md) |
| The resident `GEO` block at `$0400` — **three titles measured, so a rule rather than a pattern** | Everything else live | [96-live-memory-automapper.md](96-live-memory-automapper.md), [121](121-silver-blades.md) §5 |

**A later title's new fields land in the earlier title's gaps.** Both of Curse's
extras do, so nothing was displaced — one more reason for a layout table that
tiles the whole record.

**The two things most likely to mislead:** overlay bases, because every overlay
lies about its load address ([00-overview.md](00-overview.md),
[40-memory-map.md](40-memory-map.md)); and which map is which area, because a
map decoded correctly is still a floor plan of nowhere until it is anchored.

## The order of attack

Each step is cheaper than the one below it and produces the ground truth the
next one needs. **Do not skip forward** — the emulator work at the bottom is
serialised, slow, and unfalsifiable without the artefacts above it.

| # | Step | Needs | Artefact | Cheap? |
|---|---|---|---|---|
| 1 | Read the disk directory; walk sector chains | the player's disks | file list with sizes and load addresses | yes |
| 2 | Inventory by stem, size uniformity and entropy | step 1 | which family is maps, which is graphics, which is code | yes |
| 3 | Decode the save: find its load address, diff two saves | one or two saves | base address, party position, area id | yes |
| 4 | Decode the character record with the existing table | one export | a field table that tiles all 580 bytes | **cheapest** |
| 5 | Decode the map files; verify by reciprocity | step 2 | `Geo` objects with a self-check | yes |
| 6 | Read a running game: find the live bases | VICE | resident bases, the party fix | no |
| 7 | Automapper, then validate it by driving the game | 5 and 6 | a mapper whose every claim is asserted | no |

**Why this order.** Steps 1-5 need no emulator and no permission from anyone;
they are reproducible, parallelisable across agents, and every result is a file
you can re-derive. Step 6 costs a single serialised VICE connection — one
binary-monitor client per process, claimed through `tools/instance.py`
([123-parallel-sessions.md](123-parallel-sessions.md)). Step 7 costs a driven
session that can wedge the emulator. **Spending emulator time on a question a
disk read would answer is the commonest way to lose a day here.**

**The three cheapest wins, in order:**

1. **Point the existing record decoder at the new game's export.** A
   byte-identical round trip transfers 580 bytes of layout for free.
2. **Reciprocity on the map files.** The east edge of a square is the west edge
   of its neighbour, so a `GEO` file checks its own parse with **no ground truth
   at all**: a correct decode scores 0.98+, a wrong one about 0.3
   ([88-map-files.md](88-map-files.md); the five failed readings and their scores
   are in [50-experiments.md](50-experiments.md) §"GEO is solved"). Compute it on
   every file, every time — a wrong plane assignment or a corrupt read shows up
   here first.
3. **Two saves either side of one deliberate act.** Save, do exactly one thing,
   save again, diff. This method carried the whole project.

**Triage step 2 by entropy and attack the lowest-entropy undecoded family
first.** The per-family figures and the bands they fall into are in
[50-experiments.md](50-experiments.md) §"WALLDEF is graphics, and entropy puts
GEO back in the frame". Anything above ~6 is compressed or code and will not
yield to statistics. The caution that section paid for: the map family was
written off after three failed readings and a graphics family pointed at
instead. **The failures were failures of reading, not evidence against the
file** — entropy put it back in the frame and the format then fell in one step.

**Blind statistics on 1024 bytes will not name a square.** What settled `GEO`
was somebody's reimplementation of a sibling game found in source, plus a
self-check that needs no ground truth. **Search for a reimplementation before
searching for documentation:** nobody wrote the 1988 format down in prose
anywhere, and it survives only as code.

## Where specimens come from

* **`REMOVE` a character from the party** writes a complete 580-byte file to the
  save disk. Diffing two exports is far cleaner than diffing whole saves,
  because it removes all party-context noise.
* **A varied party beats a before/after pair.** Six characters with different
  races, classes, sexes and alignments identified seven fields in minutes with
  no emulator at all. Compare *different characters* first; fall back to
  before/after diffing only for fields that need a character to *change* —
  experience, level, damage, inventory.
* **Make a boundary pair before searching for the area id**, not after. Save,
  take one step through a doorway into another area, save again. Four attempts
  to find Pool of Radiance's failed first, and one of them failed because every
  save held was in the same area — see the next section.
  [30-savegame-layout.md](30-savegame-layout.md) §"Finding the area id".
* **Outside specimens are worth having and worth distrusting.** A hacked save
  found online had worthless values, but its *structure* bounded the roster at
  one page and settled character level, because it was the only specimen with
  eight slots filled. [90-specimens.md](90-specimens.md).
* **Monsters use the character-record layout**, so the monster files are a free
  corpus of a hundred-plus specimens carrying values a player character never
  has. `0x0E1` reads 10 for every player character, which made it look like a
  constant; the monsters put their real armour class there and match the Monster
  Manual.
* **AD&D 1st edition tables are an external rule, not a correlation.** Saving
  throws, thief skills, THAC0, hit dice and experience thresholds are all
  published. A field matching the published table for every specimen at the right
  class and level is CONFIRMED *by rule*. That is how five saving throws, eight
  thief skills and THAC0 were settled.

## The confidence discipline

Every claim carries `CONFIRMED`, `PROBABLE`, `GUESS` or `UNKNOWN`, and the label
is part of the claim. The definitions are in
[20-character-record.md](20-character-record.md), which generates them from
`por/layout.py`.

**A wrong `CONFIRMED` is worse than an honest `UNKNOWN`.** An `UNKNOWN` invites
work; a wrong `CONFIRMED` stops it, and it propagates into the generated docs,
into the editor, and into whatever the next agent assumes. This project has
demoted claims more than once and each demotion cost more than the original
caution would have.

Four working rules the log paid for:

* **A hypothesis that sparse data agrees with has not been tested.** "`$400` × 6
  slots" survived because every specimen then held at most two characters and
  the bytes between them were zero. One full party disproved it instantly
  ([30-savegame-layout.md](30-savegame-layout.md) §"Correction"). The roster's
  `+0x03`-`+0x05` is the same shape and is still open.
* **A negative needs a negative example.** "No byte in the header identifies the
  map" was reported from ten saves that were all in the same area. The byte was
  `$4BC2`, inside the range that had been scanned.
* **Repeating a wrong assumption is not corroboration.** "Four runs died at the
  training hall" was four runs of one wrong assumption, not four pieces of
  evidence — and the wedge did not exist
  ([70-driving-the-game.md](70-driving-the-game.md)).
* **Make the table tile the whole record.** `por/layout.py` asserts at import
  time that every one of the 580 bytes belongs to exactly one entry, gaps
  included. That makes an edit byte-exact by construction, makes overlaps
  impossible to introduce silently, and makes the coverage figure generated
  rather than claimed. **Never retype the coverage number** — quote
  [20-character-record.md](20-character-record.md), which is generated.

**Being able to read a field is not evidence you can change it.** Every field
located by diffing is read-only knowledge until one edit has been made and
*looked at on the character sheet in the running game*. The acceptance bar is:
change one value, load, confirm the sheet shows it, save, confirm the bytes
survive the round trip.

## Finding live data when you do not know the addresses

**Start from the assumption that the addresses are wrong.** Every absolute
address in `por/memory.py` is Pool of Radiance's. Curse shifts the save image by
`$200` and moves the roster into the same file; nothing promises the next title
is as tidy.

The recipe, in order of decisiveness:

1. **Find the save image in RAM — one step, no inference.** A Gold Box save is a
   *verbatim memory image*. Load a save, leave the party standing still, take a
   256-byte run from the middle of that same save file, and search the machine's
   64K for it. The offset names the base exactly. Read both the `cpu` and the
   `ram` bank and sweep the whole 64K rather than a guessed range — the search
   meant to settle the area question here kept coming back empty because its
   range started one page above the answer. This worked in one step on Curse and
   again on Silver Blades, where the live region differed from the freshly
   written save in 25 bytes, all of them the loaded-file cache.
2. **If that fails, search for a value you know**, best first: a **character
   name** (6+ ASCII letters, NUL-padded, effectively unique in 64K — a hit is
   unambiguous); the **party's coordinates** as a byte pair matching the status
   line (small values, so corroboration rather than discovery); a **hit-point
   total** off the sheet; **money** counted down to a deliberate, unusual figure.
   Engineer the needle where you can.
3. **Corroborate with a second value at a known relative offset.** Having found a
   name at `A`, `A + 0x14` should be strength, `A + 0x76` hit points maximum and
   `A + 0x0EB` the class bitmask. Three sane decodes is a slot base, and the
   stride falls out of where the second character's name sits.
4. **Corroborate again by changing it in game.** This is the step people skip and
   the one that catches a wrong address. Walk one square and x or y moves by one;
   turn on the spot and facing moves but position does not; buy armour and the
   roster's armour-class byte moves while the record's does not; take a wound and
   current hit points fall while the maximum does not; cross a boundary and the
   area byte in the loader cache changes. A byte that moves the way you
   predicted, when you predicted, is the strongest evidence short of reading the
   code.
5. **Then read the code.** Scan every file on the disks for absolute operands
   landing in the region. What *reads and writes* an address tells you what it
   is; correlation only tells you what it correlates with. **In this project the
   code route was the more productive of the two every time it was tried.** Where
   a structure has a fixed base it is devastating: the character record answers
   to a fixed `$6B00` in Pool of Radiance, so an absolute operand inside its
   range *is* a record offset — and that unlocked level drain, the NPC flag, the
   effect list and the last item bytes after months of save-diffing had failed on
   them ([50-experiments.md](50-experiments.md) §"The character record answers to
   a fixed base of `$6B00`").

### The obvious address is not always the live one

Pool of Radiance's `$49C0`/`$49C1`/`$49C2` genuinely are the party's x, y and
facing and genuinely are what reaches the disk — and they **lag a move**. Read
straight after a step they give the previous square. Three rules follow, and
each has a counterexample already:

* **Find which copy is live on *this* title, by moving and watching.** Neither
  source is trustworthy by default. Pool of Radiance's memory copy lags and the
  status line is right; **Silver Blades is the other way round** — the status
  line read `2,0` when every memory copy and the clock said `(3,0)`
  ([121-silver-blades.md](121-silver-blades.md) §5). Two saves either side of one
  step, then the one address in the machine that changed the way the step must.
* **The address the save writes need not be the address the game reads**, and
  the live one need not be inside the save image at all. Curse and Silver Blades
  keep the save's copy at `$4BC0` and the engine's working copy at `$C04B`, and
  `$4BC0` does not move at all while the party walks. "Lags a move" is the mild
  version of this failure and "does not move" the severe one; **for the first
  step they look identical.** `Game.live_position` is measured per title, and a
  title where nobody has measured it gets no fallback rather than a plausible
  wrong square ([96-live-memory-automapper.md](96-live-memory-automapper.md)).
* **A cache has an update rule and you must find it.** Armour class in the roster
  block is refreshed only when *equipment* changes, so editing dexterity leaves
  it stale — which looked for a while like the edit had failed
  ([30-savegame-layout.md](30-savegame-layout.md)).

**And a write that does not stick has found a copy, not a failure.** A live poke
into the item area is reverted, because that region is fed from a master
elsewhere.

**Validate before trust.** Overlays make every address conditional, so read the
region, check it still decodes as a sane party, and refuse to draw or write if
it does not. `automap.target._plausible` and `PartyFix` exist for exactly that,
and for writes the check is mandatory.

## Anchoring a map, and driving the game to prove it

A decoded map is a floor plan of nowhere until it is anchored, and **anchoring
never transfers between titles.** Three routes, best first — the area id in the
save (make a boundary pair to find it), the resident copy at `$0400` byte-matched
against the disk files, or matching a transcribed fan map square by square.
**Report the next-best score alongside the best**; the gap is the result, not the
score. [88-map-files.md](88-map-files.md), and
[50-experiments.md](50-experiments.md) §"Every Phlan city block, matched".

**Do not read the file's own counts as an identification.** It is tempting to
take `indoor` 256/256 for a dungeon and 0/256 for wilderness — and in Pool of
Radiance both pairs come out the other way round: the two most roofed, doorless
files are the *wilderness windows* and the two least roofed are outdoor sites
that are not wilderness. The counts are a parse check. What a file *is* comes
from the script that loads it. [88-map-files.md](88-map-files.md) §"Reading the
table".

Driving the game is the test that catches "live data is not where we thought": a
mapper reading the wrong address does not error, it draws a party walking through
walls and it looks fine until somebody checks. The apparatus — the nested X
server, the input timing, the KERNAL-buffer escape hatch, the disk swap through
the text monitor, the monitor's sharp edges and the full list of what does not
work — is [70-driving-the-game.md](70-driving-the-game.md), with the three
layers as working code in `automap/vice.py`, `tools/session.py` and
`tools/walkrun.py`.

**What the validation asserts**, at every step of a scripted route:

1. **Position and facing agree three ways** — the mapper's fix, the game's own
   status line, and the bytes read back out of the save disk that step wrote. A
   mismatch is logged loudly rather than averaged away.
2. **Every square the party occupies is walkable** in the decoded map.
3. **Every completed step crossed a passable edge.**
4. **Every refused step corresponds to an impassable edge.** The strongest single
   observation available: impassable edges are rare, so **one refusal identifies
   the map** where positive evidence alone needs 111 steps.
5. **Area identification switches on exactly the boundary step**, to the file the
   independent map-matching named for that area.

**The map fact is that the *square* did not change on a forward step, and that
is the only thing to assert.** A refused move costs no time on Curse (four turns
and one refusal at an unchanged clock) or Silver Blades (four bumps at `(3,3)`
left the clock at `0:05`), so "the clock changed" is evidence of neither
movement nor refusal. `automap.state`'s `_refused` infers a one-minute cost and
says in its own docstring that it is inferred; on both later titles it never
fires, and a driver that wants refusals must compare squares.
[120-curse-testing.md](120-curse-testing.md) §4,
[121-silver-blades.md](121-silver-blades.md) §5.

**Contradictions are counted, not obeyed.** An observation that eliminates every
candidate map is not evidence about which map this is — it is evidence that the
*observation* was wrong: a garbled status line, a step across a boundary, or a
bash at a locked door read as a refusal. Keep the last non-empty candidate set
and count the contradiction. `automap.area.Fingerprint._narrow` does this, and
**a rising contradiction count is the signal that an address is wrong**.

## The worked checklist

Top to bottom on a new title. Each line names what it produces; record the
artefact before moving on.

| # | Do | Produces |
|---|---|---|
| 1 | Locate the player's disks behind an env var; accept only a size `por/d64.py` names | a disk finder, and a skip path for machines without the game |
| 2 | List every directory entry and walk the chains by link, terminating on **track 0 only** | full file inventory. Ignore a zero block count — it is not an empty file |
| 3 | Group by stem; record size, uniformity and PRG load address per family | candidate families: uniform size = fixed-size records or maps |
| 4 | Compute Shannon entropy per byte per family | the triage order |
| 5 | Run one exported character through `por.record` unchanged | either 580 bytes of free layout, or a precise list of what moved |
| 6 | Diff that export against the same character inside a save | the slot size, and which record blocks the save splits out |
| 7 | Read the save's PRG load address; try Pool of Radiance's geometry at that base | header size, slot base, item area, roster location |
| 8 | Make **two saves differing by one deliberate act** — one step, one purchase, one wound | party position, clock, the field you moved |
| 9 | Make a **boundary pair**: save, cross into another area, save | the area id — and never search for it without one |
| 10 | Decode the map family as four 256-byte planes; compute reciprocity per file | `Geo` objects, and a number that proves the parse |
| 11 | Inventory the maps: walls, doors, locked, indoor, reciprocity | a parse check per file — **not** an identification |
| 12 | Anchor one map | file-to-area assignment, with a score **and** a next-best score |
| 13 | Decode the item tables and spell ids with the existing readers, changing only base addresses | item names, item types, spell names |
| 14 | Claim a pool slot (`tools/instance.py claim`) and start VICE through it | one connection, held open, on a port that is not a human's |
| 15 | Find the save image in RAM by searching for a run from the save file | the live base, exactly |
| 16 | Confirm the resident map block: search RAM for a copy of the `GEO` you are standing on | `$0400`, in all three titles measured |
| 17 | Build the party fix: measure which copy is live, then `_plausible` on both | a `Fix` with a `source` tag |
| 18 | Drive a scripted route and assert all five validations above | a walk corpus, a manifest, and a mapper you can believe |
| 19 | Write every finding into [50-experiments.md](50-experiments.md) with its evidence **and its failures** | the reasoning, which is the actual product |
| 20 | **Then stop.** Fill in the new column of [139-per-title-validation.md](139-per-title-validation.md) | an honest answer to "does the program work on this game" |

## Hazards that cost time here already

The emulator's own sharp edges are in [70-driving-the-game.md](70-driving-the-game.md)
and the pool rules are in `CLAUDE.md` and
[123-parallel-sessions.md](123-parallel-sessions.md). Four that a cold agent on a
new title keeps rediscovering:

* **A D64 a driven session wrote must be flushed before it is read back** —
  attach something else, or tear the session down cleanly. Otherwise the last
  file written reads as a `*PRG` with a zero block count, which our own reader
  accepts and the 1541 will not open. It cost the first hour of the Silver Blades
  run, answering `CHARACTER NOT FOUND` on a working import.
* **A directory block count of zero is not an empty file.** Follow the sector
  chain and ignore the count: every character Curse exports reports 0 blocks, as
  does every file on the Death Knights of Krynn sides.
* **Two files can share a name.** Curse ships `SAVEAZURE` twice — a 7424-byte
  pre-generated party and a 2030-byte truncated image that ends mid-slot. A
  reader taking the first match gets the wrong one.
* **The disk prompts and the side letters are per-title.** Silver Blades says
  `INSERT SIDE A` where Pool of Radiance uses a digit, and the import and export
  prompts name the *other* game. A driver matching Pool of Radiance's wordings
  answers none of them.

## What must never enter the repository

`CLAUDE.md` §"What must never enter this repository" is the rule and it is not
restated here. The one thing a cold agent on a new title gets wrong: **a slice of
a game file committed as a test fixture is the same copy the rule forbids,
merely renamed** — and it does not feel like a copy while you are adding it.
A new title gets a new finder function in `tests/gamedata.py`, never a new
fixture, and nothing is added to the allowlist in
`tests/test_repository_contents.py`.

## Feeding the method back

**Running this against a new title is worth more to the method than to the
title.** [121-silver-blades.md](121-silver-blades.md) §6 is the model: a
prediction that held gets promoted and names the second corroboration; a
prediction that failed becomes *check, do not assume* with the counterexample
cited by offset — **that is the most valuable outcome and should be treated as a
success**; a step that cost far more or less than budgeted reorders the phases
above; a constant that differed goes in `por/games.py`, not in prose.

**A finding is not closed until this page reads differently, or has been
deliberately left alone with a line in [50-experiments.md](50-experiments.md)
saying why.**
