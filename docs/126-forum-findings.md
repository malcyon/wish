# What the Gold Box community forums have that we do not

A pass over <https://forums.goldbox.games> — the "Gold Box games bugs" thread,
the playtester-mode thread, and the "Hacking UA" board. Everything here is a
**third-party claim about a port that is usually not ours**. Where it disagrees
with something we measured, our measurement wins and the disagreement is
recorded rather than resolved.

Bug and exploit reports from the same pass are logged separately, as rumours,
in [`125-bug-notes.md`](125-bug-notes.md) — "Rumours from the community
forums". Nothing from the forums goes in `goldbox-bugs.md`.

Raw captures: `work/forums/*.txt` (SMF `action=printpage` renderings, converted
by `work/forums/totext.py`). `work/forums/board8_topics.txt` is the full
296-thread index of the Hacking UA board.

---

## Lead: five things worth acting on

| # | Finding | Why it matters here |
|---|---|---|
| 1 | **The playtester "jumper" exists in Pools of Darkness and Dark Queen of Krynn, and is a normal `ECL` script at an unreachable area id.** | It is the same mechanism class as our Warp To, not a better one — and the search that found it is the search we already ran. See below. |
| 2 | **The DOS `ECL` bytecode is at the same addresses as ours, flag for flag.** A 2013 DOS-side walkthrough of the Slums quotes `$4ACA`, `$4ABB`, `$9E6D`, `$B6A4`, `$B6B5` — every one of them ours, with the same values. | Independent corroboration of `work/reports/quest-flags.md` and of `docs/117`'s claim that the bytecode is one artefact shared by every port. |
| 3 | **A DOS-side area-id → name table for Pool of Radiance names the five Valjevo Castle floors** and identifies `GEO1E`, `GEO1F`, `GEO20`. | `docs/118` has four of those as PROBABLE and one as UNKNOWN; `docs/115` is waiting on a human for exactly this. |
| 4 | **A DOS-side area-id → name table for Curse of the Azure Bonds**, including which three ids are the shared "modular" dungeon blocks. | `docs/120` needs area names for the second game. |
| 5 | **The DOS 63-byte `.ITM` record, field by field, plus the item-name-component table.** | Cross-checks `por/items.py` and `docs/85`; the C64 name table fills two of the gaps the DOS one leaves. |

---

## 1. The SSI playtester mode

Thread: [Official SSI Playtester Mode](https://forums.goldbox.games/index.php?topic=1034.0),
Ishad Nha, 2010–2011, 26 posts. Every detail below is his or Null Null's,
about the **DOS** builds.

### What it is

A **jumper**: a menu-driven debug script that lets you name an `ECL` number and
be dropped into it, fight arbitrary monsters, view arbitrary pictures, and dump
treasure on the party. It is not a key combination and not code in the
executable — **it is an ordinary `ECL` script stored under an area (town) number
the shipped game never travels to.** Ishad Nha found it by porting maps and
noticing a `GEO1.DAX` town record with no game area behind it.

> "Instead of entering the town I found I had activated the SSI playtester
> mode!" — Ishad Nha, [topic 1034](https://forums.goldbox.games/index.php?topic=1034.0)

### How it is reached

| game | how | magic value |
|---|---|---|
| Pools of Darkness | hex-edit `savgam@.pty` (`@` = `A`…`J`), set offsets **18, 21, 197** to **1**, load the save | area 1 |
| Dark Queen of Krynn | same three offsets | **2** |
| Gateway to the Savage Frontier | `ECL5` records **98** and **99** are playtester records; swapping record 99 over record 19 (Sundabar) triggered the menus, but every jump then demanded a disk the loader would not accept | — |
| Buck Rogers: Matrix Cubed | playtester text at `ECL` **2**; never made to run | — |
| Secret of the Silver Blades | **no spare area id in either `GEO` or `ECL`** — searched exhaustively, nothing found | — |
| Treasures of the Savage Frontier | same: no spare ids; ~15 town numbers crash instead | — |
| Pool of Radiance, Curse, Champions, Death Knights, Silver Blades | **never reported** | — |

Ishad Nha's own summary is that he found it in **four of eleven** titles, and
he does not claim the other seven lack it.

### The menu tree (Pools of Darkness)

```
"Do you want to start from scratch or use the jumper?"  -> Jumper
"Where do you wish to go?"   Jump / Arena / Camp / Treas / Demo / Prv / Nxt
"What ECL do you wish to go to? (In decimal)"
"Which Disk side?"           (a floppy side number; wrong answers get corrected on screen)
   then: confirm the ECL number, optionally set the party's initial x,y,
         optionally set party variables
```

Other verbs on the same menu, from Null Null: `BPIC` and `SETUP` show the
picture for a monster id, `CMD` plays the intro/outro animations, `EXP` grants
experience, `ARENA` fights chosen monsters on chosen walls and dimensions,
`TREAS` dumps treasure, `STORE` opens any of the game's eleven shops including
one that does not appear in play, `ANPC`/`DNPC` add and remove NPCs — and an
added hostile NPC attacks you once combat starts. Monsters are numbered in
`MON1CHA.DAX` order. In Dark Queen the same menu is unstable: asking for a
picture that does not exist locks the machine.

`Ctrl+C` or `Ctrl+2` exits a DOS Gold Box game immediately. That is the only
key combination in the thread and it is not a debug feature.

### What it means for our Warp To

**Nothing changes.** Three reasons, in order of weight:

1. **The mechanism is the one we already use.** The jumper's "jump" verb is a
   script executing the engine's own area-change opcode with an operand the
   player typed. Our warp writes the same five values and enters the tail of
   `NEWECL` at `$2034` (`docs/118`). Same door, different handle.
2. **Pool of Radiance has no unreferenced playtester script.** Our `ECL` decode
   is exhaustive — thirty scripts, 16,233 instructions, zero derailments — and
   there is exactly **one** script nothing warps to, `ECL1E` (area 30). It is
   not a playtester: `docs/50` P20 warped into it and got the attract-mode
   demo, with marketing copy and a self-driving party. CONFIRMED. So the search
   Ishad Nha ran is the search we ran, and the answer for this title is no.
   (Curse does the same thing: `ECL1.dax` in the DOS build is documented on the
   forum as "Demo and World Map", record 082 "Demo text". The engine ships its
   attract mode as a script; that is the family habit, not a debug mode.)
3. **Even where the jumper exists, it is a save-file edit** — a magic value at
   three offsets — not a runtime hook. On the C64 that would be a save-disk
   write, which the automapper does not do and should not start doing.

**Worth carrying forward to a later title**: if we ever take on Pools of
Darkness or Dark Queen of Krynn, the first cheap probe is to look for an area
id with an `ECL` record and no `NEWECL` pointing at it, and for the smallest
`ECL` records in the file — Ishad Nha reports the playtester scripts are among
the smallest, 1–2 KB. Our `work/analysis6/` tooling answers both questions
without an emulator.

---

## 2. Corroborations of our own work

Each of these was reached by us independently, from the C64 bytecode or the C64
disks. An outside report agreeing is real evidence.

| our finding | outside report | strength |
|---|---|---|
| `$4ABB` is the Slums encounter counter: `ADD 1` at `$B6A4`, latches to 254 at 25 fights (`quest-flags.md`) | marainein, 2013, from the **DOS** build: "Has it been less than 25 fights? … `0xb6b5: SAVE byte : 254, ptr : 0x4abb`" ([topic 2519](https://forums.goldbox.games/index.php?topic=2519.0)) | **strong** — same address, same value, same instruction address |
| `$4ACA` set to 255 at `$9E6D` after the orc encounter in the Slums | same post: `0x9e6d: SAVE byte : 255, ptr : 0x4aca`, and "checks if the party has triggered this event before" | **strong** |
| `$4AD9` (`ECL14`, the Slums) tested against 255 | Joonas Hirvonen's ECL-Monitor screenshots, DOS: "The script for that event checks if the event has already been triggered (flag `$4AD9` is 255)" ([topic 4110](https://forums.goldbox.games/index.php?topic=4110.0)) | **strong** |
| The DOS character record is **285 bytes** (`docs/117`) | marainein, [topic 1912](https://forums.goldbox.games/index.php?topic=1912.0): "the 285 byte data structure that gets saved as `CHRDAT.SAV` and `CHA` files … no greater than `0x11C`" | moderate |
| `ITEMNAMES` has **no name at indices 62 and 63** (`docs/125`, "things that look like bugs and are not") | marainein's DOS name-component list has two empty strings in exactly that position, between `Arrow` and `Potion` | **strong** — and it is the same table in both ports |
| Monsters use the character record (`por/record.py` parses `MON*`) | Nol Drek: "The monsters use the same data structure as the characters"; and "every monster has maximum HP, current HP, and pre-drain HP" — our `0x076` / `0x119` / the drain pair at `0x0A1`–`0x0A2` | moderate |
| Paladin, ranger, druid and monk are named and never instantiated in Pool of Radiance (`docs/20`, `0x073`) | GBC users who forced those classes report **no sweep attack**, and that level drain followed by restoration cycles the gender byte and awards 10,000,000 XP ([topic 1913](https://forums.goldbox.games/index.php?topic=1913.0)) | moderate — behavioural, DOS |
| `ECL0B` is the **training hall**, not the arena (`work/reports/analysis-batch.md`: `$9BB0` prints `THE ROOM IS FILLED WITH DUELING PAIRS.`) | Ishad Nha's DOS list: "`POOLRAD\ECL3.DAX` Record 11: Training Hall" | **strong**, and it means `docs/118`'s area table has the wrong name on id 11 |

On our bug 2 — Sokol Keep's dead elf returning on every re-entry — **the forums
do not report that specific bug**. What they do report, four times over, is the
same *class* of defect in other titles: Gargath Keep's front-gate troops in
Champions, the salamanders under Hap in Curse, Kalistes' Parlor encounters in
Pools of Darkness, and the regenerating village loot in the same game. An
encounter whose "cleared" flag is not latched is a habitual Gold Box fault, so
our finding is normal for the engine rather than exotic. That is corroboration
of the pattern, not of the entry.

---

## 3. Where the forums contradict us, or each other

| claim | our position |
|---|---|
| Caldor, [topic 4138](https://forums.goldbox.games/index.php?topic=4138.0): "So that must make the C64 use Big Endian I guess" | **Wrong.** The 6502 is little-endian and every multi-byte field we decode is LE — age at `0x074`, hit points at `0x076`, the seven money words at `0x0BB`, experience as `u24le` at `0x0E8`. He was reasoning from the Mac's 68000 and got the wrong machine. Anyone using his `GoldBoxEditor` mapping tables for C64 work should check this. |
| Ishad Nha, [topic 1912](https://forums.goldbox.games/index.php?topic=1912.0): `GEO6.DAX` record **19** is the "Silver Dragon Den" | We have area 19 as `ECL13`, POOL6, no map of its own, and `work/reports/world-map.md` calls it the Cave of Diogenes. Both are wilderness sites on the same disk. Unresolved; the forum entry is a `GEO` record and ours is an `ECL` script, so they may not even be the same thing. |
| The same list gives area **30** as "Lizard Man Catacombs" and **31** as "Wealthy Area" | Consistent with us once you notice his list numbers **`GEO` records**, not scripts. `docs/118` has `ECL10` (lizardman keep) loading `GEO10` **and `GEO1E`**, and `ECL18` (Temple of Bane) loading `GEO18` **and `GEO1F`** — so `GEO1E` = the catacombs and `GEO1F` = the Wealthy Area, and his "I suspect Temple of Bane and the Wealthy Area are found in the same Ecl" is confirmed by our decode. Our *script* 30 (`ECL1E`) is a different thing entirely: the demo. |
| Simeon Pilgrim, 2013: the Pool of Radiance ECL "command offset is `0x6700` compared to `0x8000` used in Curse" — while marainein's listings of the same game print addresses from `0x9800` up | The two are irreconcilable as stated and neither is ours: the C64 `ECL` block is at **`$9900`** and its flag page at `$4A00`, which is what the addresses in the listings actually behave like. Take the *addresses in the listings*, not the prose. |
| The `coab` opcode table's `$3E DUMP`, `$3F FINDSPECIAL`, `$40 DESTROYITEMS` | **Do not exist in Pool of Radiance.** The dispatch tables at `$15A9`/`$15E7`/`$1625` are 62 entries, `$00`–`$3D` (`work/reports/ecl-opcodes.md`, CONFIRMED). Curse's DOS build having three more is a difference between titles, not an error in either. |
| Nol Drek: FRUA's combat limits are memory partitioning — 50 monsters, 3 items each, 100 events, 24×24 maps | About FRUA, a later DOS product. Nothing here constrains the C64 engine and none of those numbers should be carried over. Draxinusom's 2026 measurements ([topic 4677](https://forums.goldbox.games/index.php?topic=4677.0)) put FRUA's real ceiling at ~480 items live at combat start, sharing storage with the party's memorised spells. Interesting engineering, wrong engine. |

---

## 4. The DOS area-id tables

Third-party, DOS, unverified by us. Recorded because `docs/118` carries five
PROBABLEs and one UNKNOWN that these would resolve, and `docs/115` is blocked on
the same question.

### Pool of Radiance — Ishad Nha, [topic 1912](https://forums.goldbox.games/index.php?topic=1912.0)

Numbers are `GEO` record ids. Only the rows that add something to `docs/118`:

| id | forum name | `docs/118` today |
|---|---|---|
| 3 | Valjevo Castle, **North West** | "a floor", PROBABLE |
| 4 | Valjevo Castle, **North East** | "a floor", PROBABLE |
| 5 | Valjevo Castle, **South East** | "a floor", PROBABLE |
| 6 | Valjevo Castle, **South West** | "a floor", PROBABLE |
| 7 | Valjevo Castle, **Upper Level** | "the pool", PROBABLE |
| 19 | Silver Dragon Den | Cave of Diogenes — conflict, see above |
| 25 | "Unknown Lair" | wilderness, west window |
| 26 | "Unknown Zone" — *Ruined Huts is its lower part* | wilderness, middle window |
| 27 | "Unknown Lair" — *Dark Cave is its lower left* | wilderness, east window |
| 30 | Lizard Man Catacombs | `GEO1E`, shared with `ECL10` |
| 31 | Wealthy Area | `GEO1F`, shared with `ECL18` |
| 32 | Kuto's Well Catacombs | `GEO20`, shared with `ECL1D` |
| — | `ECL3` record 8 City Hall, record **11 Training Hall** | id 11 is labelled "the arena" — ours is wrong |

Confidence on the castle floors: **PROBABLE**, and cheap to promote. Warp to
each of 3–7 in turn and match `$0400` against the disk `GEO` (`ResidentGeo`),
then read the floor plan against the compass names.

### Curse of the Azure Bonds — Ishad Nha and manikus, [topic 1048](https://forums.goldbox.games/index.php?topic=1048.0)

| id | area | id | area |
|---|---|---|---|
| 1 | Tilverton streets | 35 | Zhentil Keep courtroom and arena |
| 2 | Thieves' Guild under Tilverton | 37 | Dagger Falls Dungeon (Oxam's Tower) |
| 3 | Tilverton sewers | 48 | outside Haptooth |
| 4 | Fire Knife hideout | 49 | Haptooth streets |
| 16 | Yulash streets | 50 | Dracolich cave |
| 17 | Pit of Moander | 51 | Dracandros' Tower |
| 18 | Pit of Moander, second level | 53 | **shared blocks**: Ashabenford, Essembra, Shadowdale dungeons |
| 21 | **shared blocks**: Voonlar, Phlan dungeons | 64 | Myth Drannor — Burial Glen |
| 32 | Zhentil Keep streets | 66 | Ruins of Myth Drannor |
| 33 | Temple of Bane | 67 | Myth Drannor — Ruined Temple |
| 34 | Cave of the Beholder | 69 | **shared blocks**: Hillsfar, Teshwave dungeons |
| — | `ECL1`: 80/81 world map, **82 demo text** | | |

The three "shared blocks" ids are the interesting ones: several named dungeons
are built out of one 16×16 map plus heavy use of party-movement events. If our
Curse `GEO` decode finds fewer maps than the cluebook has dungeons, that is the
reason. It is also the most plausible cause of the Teshwave rumour in
`docs/125` — id 69 is exactly one of the three.

---

## 5. The DOS item record, and the item-name table

marainein, [topic 1912](https://forums.goldbox.games/index.php?topic=1912.0),
2013. **63 bytes** per `.ITM` record in DOS Pool of Radiance, of which 45 is the
inventory description string:

| off | field | off | field |
|---|---|---|---|
| `0x00` | description length | `0x33` | readied flags |
| `0x01` | description, 44 bytes | `0x34` | hidden-name flags (bits 0–2 hide name components 1–3) |
| `0x2D` | item type | `0x35` | cursed |
| `0x2E`–`0x30` | name components 1–3 | `0x36` | weight, 2 bytes |
| `0x31` | item bonus (the "+3") | `0x38` | stack size |
| `0x32` | save bonus (signed: a cursed necklace holds 255 = −1) | `0x39` | price, 2 bytes |
| | | `0x3B`–`0x3D` | three effect fields |

Effect-field semantics, his reading: on a scroll the three hold spell codes;
otherwise, field 3 = 0 means "activated by USE", field 2 the effect number and
field 1 the charges; field 3 ≥ 128 means "activated by readying", field 2
carrying the detail. The first 56 effect numbers are the spell ids.

**This is the same shape as ours, minus the string.** The C64 packs an item into
16 bytes and keeps the name in `ITEMNAMES` as three component indices — the plus
at `+4` and the quantity at `+10` in `por/items.py` line up with his `0x31`
bonus and `0x38` stack size. Two things transfer:

* **"save bonus" is signed.** Our `docs/85`/`por/items.py` should read `0xFF` as
  −1 rather than 255 wherever that field appears. Worth a check.
* **Spell ids 1–56 double as effect ids** — which matches the skill card's
  "spell ids 1-56" transfer row, and matches `0x0AD`'s note in `docs/20` that
  the effect slots share storage with item byte `+14` but not its meaning.

His name-component list and our `docs/85` table agree entry for entry, including
the two blanks at 62 and 63 that our own reader once closed. They diverge at
three later slots: he has blanks where we have `STONE` (135), `MIRROR` (144) and
one more. Either the C64 table fills gaps the DOS one leaves, or his
transcription dropped them. **GUESS**; one grep of `ITEMNAMES` settles it and
nobody needs to hurry.

---

## 6. Tooling and sources worth knowing about

Everything in `docs/60-goldbox-field-checklist.md` §6 still stands. New since
that pass:

| thing | what | use to us |
|---|---|---|
| **ECL-Monitor** (Joonas Hirvonen, in the GBC beta, `gbc.zorbus.net/gbc_beta.zip`) | live ECL disassembler over a running DOSBox game: follows the script PC, shows and **edits** flags and command operands | The closest existing thing to what `wish` does, on the other port. Its screenshots are a free cross-check of our flag decode — see §2. Its parser credits Stephen S. Lee's GameFAQs guides. |
| **Blackthorn's Pool of Radiance disassembly**, [topic 4605](https://forums.goldbox.games/index.php?topic=4605.0), 2025– | a full DOS PoR disassembly in progress, down to the Turbo Pascal v4–v6 libraries, feeding a revision of his GameFAQs guide; an unofficial bugfix build is the stated next step | Active, serious, and the only other person doing this on any port. He notes **v1.0 and v1.3 differ** in random item generation — a version axis we have not considered. |
| **Draxinusom's format documentation**, [topic 4677](https://forums.goldbox.games/index.php?topic=4677.0), 2026– | character/monster, effects, items, vault, `GEO` and FRUA `SCRIPT.GLB` formats normalised across ten games; ImHex `.hexpat` pattern files, being submitted to ImHex's official library | Newest and best-organised cross-game format catalogue. **Hosted on OneDrive and unreachable to us** — see §8. |
| **Caldor's GoldBoxEditor**, [topic 4138](https://forums.goldbox.games/index.php?topic=4138.0), <https://github.com/kblood/GoldBoxEditor> | C# cross-port character converter, driven by per-game offset maps; Amiga↔DOS working for the Krynn games, C64 intended and never finished | The only other attempt at cross-port character conversion. Its offset maps are worth reading against `docs/117`; its endianness claim is wrong (§3). |
| **`gbc.zorbus.net/savefiles_compared.txt`** | the cross-game character-offset table, twelve games in columns | Already in `docs/60` as part of `formats.zip`; refetched to `work/forums/savefiles_compared.txt`. Nothing new. |
| **Simeon Pilgrim's `coab`** and `DaxDump` | the DOS Curse reimplementation and the RLE unpacker everyone else builds on | Already known. Note his remark that no repacker exists — modifying a DOS `.DAX` in place is still hand work. |
| **Gold Box Explorer**, <https://github.com/bsimser/Gold-Box-Explorer> | .NET DAX/GEO/ECL browser | Already known; the forum's own users report it mis-sorts image resources and its PNG export is unreliable. |

One free observation from the same threads: the DOS engine's per-disk grouping
is the same one we see on the C64 — `GEO<n>`, `ECL<n>`, `WALLDEF<n>`,
`MON<n>CHA` all belong to floppy *n*, and a map may only use monsters and walls
from its own disk. That is why the Cadorna Textile House is full of undead. Our
`$6E12` disk byte in `docs/118` is the same constraint from the inside.

---

## 7. Threads not opened

Board 8 ("Hacking UA") has **296 threads**; I opened **24**, listed at the head
of each section above. The selection rule was: anything naming Pool of Radiance,
Curse, a save or character record, the `ECL` engine, `GEO` maps, or a
cross-port tool. Everything skipped is FRUA/Unlimited Adventures module hacking,
Krynn- or Buck-Rogers-specific mechanics, or art extraction.

Full index with titles: `work/forums/board8_topics.txt`.

The ones most likely to repay a second visit, in order:

| topic | title | why |
|---|---|---|
| 2532 | How the walldef files work | we have `work/reports/walldef.md`; this is the DOS-side account |
| 1255 | Drawing/Decoding `WALLDEF*.DAX` files | same |
| 3148 | Hacking and rebuilding DAX-files | the repacker question |
| 1073 | GoldBox `.DAX` graphic file format | the base container |
| 1053 | Glb Files — Table of Contents | container, later games |
| 3108 | How to detect doors in FRUA's GEO-files | wall-vs-barrier, the thing our reciprocity check turns on |
| 2060 | Dungeons and Combat Icons | the 36-byte icon block |
| 1828 | Is There A Way Of Getting Random Encounter Information From Gold Box Games? | `work/reports/encounters.md` has questions open |
| 726 / 727 / 700 | David Knott's `item.dat` / `items.dat` format posts | the primary sources behind GBC's item notes |
| 3922 | Items and item pointers between games | cross-title item id mapping, relevant to Curse |
| 991 / 1033 / 981 / 1918 / 1919 / 1068 / 1101 | per-game "Hub" threads (Silver Blades, Pools of Darkness, Dark Queen, Champions, Death Knights, Savage Frontier, Buck Rogers) | each is the `1912`-shaped thread for its title: area lists, monster ids, format notes |
| 4000 | fun with `.cch` hexediting | DOS character-file edits |
| 1692 | CTL format, what is it? | an undocumented container |
| 3413 | Wall Textures from Goldbox Games | |
| 1344 | MS-Dos Edit File Compare command notes | the save-diff method, their version of ours |

---

## 8. What needed a browser, and what a browser would buy

| source | state | worth |
|---|---|---|
| `gamefaqs.gamespot.com` — Stephen S. Lee's Pool of Radiance and Curse guides ([73869](https://gamefaqs.gamespot.com/pc/564785-pool-of-radiance/faqs/73869), [78365](https://gamefaqs.gamespot.com/pc/564786-curse-of-the-azure-bonds/faqs/78365)) | **403, anti-bot.** Not retried. | **High.** Cited by both Joonas Hirvonen (as the source of ECL-Monitor's parser) and Blackthorn (as the guide he is now revising from a disassembly). It is the closest thing to a published DOS engine reference. |
| `1drv.ms` — Draxinusom's format documentation, ImHex patterns, executable-table offsets | **redirects to a Microsoft login wall.** Not retried. | **High and current** (2026). The only normalised ten-game format catalogue, and the `GEO` and character patterns overlap directly with `por/geo.py` and `por/layout.py`. |
| SMF's own search | needs a POST and a session; not attempted | Low. The board index is only 16 pages and reading it was cheaper. |
| Attachments on `forums.goldbox.games` (Ishad Nha's spreadsheets, the two ready-made playtester saves, the Gold Box password list) | `action=dlattach` links; not fetched — they are binaries, several are game data, and none is needed for anything above | Low, and two of them are things we must not commit anyway. |

Nothing on any page attempted to instruct a reader, and nothing was followed
beyond the four fetch targets and `gbc.zorbus.net/savefiles_compared.txt`.
