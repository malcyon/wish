# What the Gold Box community forums have that we do not

The whole of <https://forums.goldbox.games> board 8, "Hacking UA" — **all 296
threads**, every post on every page — plus the "Gold Box games bugs" and
playtester-mode threads from the general board, and the 455 external URLs those
threads cite. Everything here is a **third-party claim about a port that is
usually not ours**. Where it disagrees with something we measured, our
measurement wins and the disagreement is recorded rather than resolved.

Bug and exploit reports are logged separately, as rumours, in
[`125-bug-notes.md`](125-bug-notes.md). Nothing from the forums goes in
`goldbox-bugs.md`.

Method and the full 296-row thread index: `work/reports/forum-sweep.md`. Raw
captures are `work/forums/print/<topic>.html` and `.txt` — the forum's own
`action=printpage` rendering returns every page of a thread in one document, so
there is never a reason to walk `.20`, `.40` by hand. Fetched non-forum
material is under `work/forums/ext/`. All of `work/` is `.gitignore`d.

**What the board is.** 50 threads of the 296 are useful; 246 are *Forgotten
Realms Unlimited Adventures* module hacking — byte edits to `CKIT.EXE` to change
a spell, a class, a wall. Different product, different machine. **The C64 is
essentially absent**: across roughly four megabytes of text, "C64" or
"Commodore" appears in six threads, five of them as hardware nostalgia. One
thread ([4138](https://forums.goldbox.games/index.php?topic=4138.0)) tried to
read a C64 save and never finished. Every format claim on this board is DOS,
Amiga or FRUA.

---

## Lead: what came out of it

| # | Finding | Where | Outcome |
|---|---|---|---|
| 1 | **`github.com/simeonpilgrim/coab` is a primary source, not a footnote.** It holds the DOS record for *both* our titles — `PoolRadPlayer.cs` (285 bytes, named fields), `Player.cs` (422 bytes, 81 machine-readable `[DataOffset]` attributes) — and `engine/ovr017.cs::ConvertPoolRadPlayer`, **the routine the game runs when it imports a Pool of Radiance character into Curse**. | [2332](https://forums.goldbox.games/index.php?topic=2332.0), [1048](https://forums.goldbox.games/index.php?topic=1048.0), [1073](https://forums.goldbox.games/index.php?topic=1073.0) | Mined in full. **The conclusions live in [`117-save-conversion.md`](117-save-conversion.md)**, which is where the conversion work is. They account for 12 of the 15 bytes our own Pool→Curse import changed. |
| 2 | **The DOS builds ship a second cheat mode, on the command line: `start.exe STING` for Pool of Radiance, `start.exe STING Wooden` for Curse**, then Alt+X. | [1082](https://forums.goldbox.games/index.php?topic=1082.0) | Probed on the C64 and **the answer is no** — §2. Closed. |
| 3 | **The playtester "magic values" are not magic.** David Knott's `SAVGAM.TXT` names save offset 18 *current module* and 21 *initiated flag*; Ishad Nha's Death Knights notes name 198 *current `GEO`* and 243 *current `ECL`*. | [1034](https://forums.goldbox.games/index.php?topic=1034.0), [1919](https://forums.goldbox.games/index.php?topic=1919.0) | Ours confirmed and sharpened: the playtester trick is **writing an area id into the save's current-area field** — our FastTravel To, performed offline. §2. |
| 4 | **The `GEO` wall nibble decomposes**: `wallset = (n−1)/5`, `slice = (n−1)%5`, from the Curse code — and marainein's WALLDEF decode gives the 156-byte, ten-view structure it indexes into. | [1255](https://forums.goldbox.games/index.php?topic=1255.0), [2532](https://forums.goldbox.games/index.php?topic=2532.0) | Extends `goldbox/geo.py`: the nibble is structured, not opaque. A prediction, not a measurement — §4. |
| 5 | **Two DOS area-id tables for our two titles**, and **the DOS 63-byte `.ITM` record** field by field. | [1912](https://forums.goldbox.games/index.php?topic=1912.0), [1048](https://forums.goldbox.games/index.php?topic=1048.0) | §5 and §6. One conflict between two DOS sources over Valjevo Castle remains unsettled and is cheap to decide. |

---

## 1. What corroborates our own work

Each of these was reached by us independently, from the C64 bytecode or the C64
disks. An outside report agreeing is real evidence.

| our finding | outside report | strength |
|---|---|---|
| `$4ABB` is the Slums encounter counter: `ADD 1` at `$B6A4`, latches to 254 at 25 fights (`quest-flags.md`) | marainein, 2013, from the **DOS** build: "Has it been less than 25 fights? … `0xb6b5: SAVE byte : 254, ptr : 0x4abb`" ([2519](https://forums.goldbox.games/index.php?topic=2519.0)) | **strong** — same address, same value, same instruction address |
| `$4ACA` set to 255 at `$9E6D` after the orc encounter in the Slums | same post: `0x9e6d: SAVE byte : 255, ptr : 0x4aca` | **strong** |
| `$4AD9` (`ECL14`, the Slums) tested against 255 | Joonas Hirvonen's ECL-Monitor screenshots, DOS ([4110](https://forums.goldbox.games/index.php?topic=4110.0)) | **strong** |
| The DOS Pool of Radiance record is **285 bytes** | `PoolRadPlayer.StructSize = 0x11D`, from the disassembly; and marainein, [1912](https://forums.goldbox.games/index.php?topic=1912.0), "the 285 byte data structure … no greater than `0x11C`" | **strong**, two ways |
| The DOS Curse record is **422 bytes** | `Player.StructSize = 0x1A6` | **strong** — the second number `docs/117` was missing |
| The `60 − stored` bias on THAC0 and armour class | Simeon Pilgrim, publishing `PARTYSTRENGTH` as C# from the Curse disassembly: "the display values are (60-stored)" ([3002](https://forums.goldbox.games/index.php?topic=3002.0)) | **strong** — third party, in code, different port |
| Spell id **36 is ANIMATE DEAD** (`docs/86`) | `coab`'s own enum: `animate_dead = 0x24` | **strong** |
| The money block is seven `u16le` in the order copper, silver, electrum, gold, platinum, gems, jewelry | `coab`'s `MoneySet.cs`: `Copper = 0 … Jewelry = 6`, same order | **strong** |
| `ITEMNAMES` has **no name at indices 62 and 63** (`docs/125`) | marainein's DOS name-component list has two empty strings in exactly that position, between `Arrow` and `Potion` | **strong** — same table in both ports |
| Monsters use the character record (`goldbox/record.py` parses `MON*`) | Nol Drek: "The monsters use the same data structure as the characters"; "every monster has maximum HP, current HP, and pre-drain HP" — our `0x076` / `0x119` / the drain pair at `0x0A1`–`0x0A2` | moderate |
| Paladin, ranger, druid and monk are named and never instantiated in Pool of Radiance (`docs/20`, `0x073`) | GBC users who forced those classes report no sweep attack, and that level drain then restoration cycles the gender byte and awards 10,000,000 XP ([1913](https://forums.goldbox.games/index.php?topic=1913.0)) | moderate — behavioural, DOS |
| `ECL0B` is the **training hall**, not the arena (`work/reports/analysis-batch.md`: `$9BB0` prints `THE ROOM IS FILLED WITH DUELING PAIRS.`) | Ishad Nha's DOS list: "`POOLRAD\ECL3.DAX` Record 11: Training Hall", and Stephen S. Lee's guide independently: "Civilized Area (Training Hall)" | **strong**, three ways. `docs/118` and `goldbox/areas.py` both corrected (P61) |
| The disk grouping is a real constraint: `GEO<n>`, `ECL<n>`, `WALLDEF<n>`, `MON<n>CHA` all belong to floppy *n*, and a map may only use monsters and walls from its own disk | reported the same way for the DOS build; it is why the Cadorna Textile House is full of undead | moderate — our `$6E12` disk byte is the same constraint from the inside |

On our bug 2 — Sokol Keep's dead elf returning on every re-entry — **the forums
do not report that specific bug**. They report the same *class* of defect four
times in other titles: Gargath Keep's front-gate troops in Champions, the
salamanders under Hap in Curse, Kalistes' Parlor encounters and the regenerating
village loot in Pools of Darkness. An encounter whose "cleared" flag is not
latched is a habitual Gold Box fault. That is corroboration of the pattern, not
of the entry.

---

## 2. The two debug facilities, and what the C64 has

The DOS builds carry **two unrelated things**, and the board conflates them.

### The playtester jumper — an `ECL` script, in four of eleven titles

Thread: [Official SSI Playtester Mode](https://forums.goldbox.games/index.php?topic=1034.0),
Ishad Nha, 2010–2011, 26 posts.

It is **an ordinary `ECL` script stored under an area number the shipped game
never travels to** — not a key combination and not code in the executable.
Ishad Nha found it by porting maps and noticing a `GEO1.DAX` town record with no
game area behind it. Its menu offers `JUMP` (name an `ECL` in decimal, name a
disk side, optionally set the party's x,y), `ARENA`, `TREAS`, `BPIC`/`SETUP`
(show a monster's picture, by `MON1CHA.DAX` index), `CMD`, `EXP`, `STORE` (any
of the eleven shops, one of which never appears in play), `ANPC`/`DNPC` — an
added hostile NPC attacks you once combat starts.

| game | how to reach it |
|---|---|
| Pools of Darkness | hex-edit `savgam@.pty` (`@` = `A`…`J`), set offsets **18, 21, 197** to **1** |
| Dark Queen of Krynn | the same three offsets, set to **2** |
| Gateway to the Savage Frontier | `ECL5` records 98 and 99; swapping 99 over 19 (Sundabar) triggered the menus but every jump then demanded a disk the loader refused |
| Buck Rogers: Matrix Cubed | playtester text at `ECL` 2; never made to run |
| Secret of the Silver Blades, Treasures of the Savage Frontier | **no spare area id in either `GEO` or `ECL`** — searched exhaustively |
| Pool of Radiance, Curse, Champions, Death Knights, Silver Blades | never reported |

Ishad Nha found it in four of eleven titles and does not claim the other seven
lack it. In Dark Queen the menu is unstable: asking for a picture that does not
exist locks the machine. `Ctrl+C` or `Ctrl+2` exits a DOS Gold Box game
immediately, and that is the only key combination in the thread.

**Those three offsets are not magic.** David Knott's `SAVGAM.TXT` (in
`hackdocs.zip`, the FRUA documentation the board quotes constantly) names save
offset **18 = current module** and **21 = initiated flag**; Ishad Nha's own
Death Knights notes name **198 = current `GEO`** and **243 = current `ECL`**.
The trick is writing an area id into the save's current-area field. It is our
FastTravel To performed offline, on the same door with a different handle.

**Nothing changes for us.** Pool of Radiance has no unreferenced playtester
script: our `ECL` decode is exhaustive — thirty scripts, 16,233 instructions,
zero derailments — and there is exactly **one** script nothing fasttravels to,
`ECL1E` (area 30), which `docs/50` P20 fasttraveled into and got the attract-mode
demo, with marketing copy and a self-driving party. CONFIRMED. Curse does the
same: `ECL1.dax` in the DOS build is documented on the forum as record 082
"Demo text". The engine ships its attract mode as a script; that is the family
habit, not a debug mode. And even where the jumper exists it is a **save-file
edit**, not a runtime hook — on the C64 that would be a save-disk write, which
the automapper does not do and should not start doing.

**Worth carrying to a later title**: if we take Pools of Darkness or Dark Queen,
the first cheap probe is an area id with an `ECL` record and no `NEWECL`
pointing at it, and the smallest `ECL` records in the file — Ishad Nha reports
the playtester scripts are among the smallest, 1–2 KB. `work/analysis6/`
answers both without an emulator.

### The command-line cheat — `start.exe STING` — and the C64 verdict: **absent**

Simeon Pilgrim, [topic 1082](https://forums.goldbox.games/index.php?topic=1082.0),
2010, extended by Ishad Nha in 2017 with a GOG recipe. A **second** facility, in
the executable rather than in a script, reached by an argument the program tests
at startup; Alt+X then produces "the gods intervene".

| title | invocation |
|---|---|
| Pool of Radiance | `start.exe STING` |
| Curse of the Azure Bonds | `start.exe STING Wooden` |
| Secret of the Silver Blades | `start.exe Hoop Gem` |
| Pools of Darkness, Treasures of the Savage Frontier | `game.exe 2 2 Helm` |
| Champions of Krynn | `start.exe Woof Helm` |
| Death Knights of Krynn | `start.exe anything Helm` |
| Gateway to the Savage Frontier | a patched `game.exe`, then `game.exe Super Wooden` |

Simeon notes the two Buck Rogers games are built on the Pool of Radiance code
base **with the cheat removed**, and that Dark Queen and FRUA answer Alt+X with
"That doesn't work".

**It is in our two titles, so it was worth an hour.** The C64 has no argument
vector, but the family habit is to ship the same code and reach it differently,
so the literals might have survived with nothing reaching them.

**They did not.** Every file on all nine Pool of Radiance sides and all six
Curse sides was searched for `STING`, `WOODEN`, `GODS`, `INTERVENE`, `HOOP`,
`HELM`, `WOOF`, `SUPER`, `GEM`, `PLAYTEST`, `DEBUG` and `CHEAT`, in six
encodings — ASCII/PETSCII upper, lower, shifted PETSCII, screen codes, reverse
screen codes, and the VM's four-characters-in-three-bytes 6-bit packing at all
four phase alignments — with a word-boundary test on every hit, and against the
raw sector images as well as the file payloads so that nothing outside a file
could hide.

| literal | every hit is | verdict |
|---|---|---|
| `STING`, ASCII | `CASTING`, 42 times, in `CAMP`, `SPELLN00` and Curse's `COMBAT2` — the spell menus. Plus one `PLAYTESTING` in Curse's `INIT`, which is the credits screen (`PLAYTESTING:` above six names) | substring, not a cheat |
| `STING`, 6-bit packed | `INTERESTING`, `RUSTING`, `TWISTING`, `RESTING`, `BURSTING`, `DISGUSTING` — ECL prose | substring |
| `WOODEN` | the `ITEMNAMES` component `WOODEN`, and ECL prose: `A WOODEN CABINET`, `WOODEN STAIRS LEAD INTO A PIT`, `AN ANCIENT KOBOLD ON A WOODEN THRONE` | ordinary game text |
| `GODS`, `INTERVENE` | ECL prose: `THE GODS HAVE NOTED YOUR ACTIONS`, `GOD OF GODS`, `DIRECTLY INTERVENE, BUT I CAN OFFER INFORMATION` | ordinary game text. **The phrase "the gods intervene" appears nowhere** |
| `HELM`, `GEM` | `ITEMNAMES` entries, `GEMS` on the money screen in `POST.COM` and `LIBRARY`, and `THE HELM OF DRAGONS` in Curse's ECL | ordinary game text |
| `SUPER` | `THE SUPERNATURAL SCIENCES` in the library text | substring |
| `PLAYTEST`, `DEBUG`, `CHEAT` | `PLAYTESTING:` in the credits; `CHEATING` in Curse ECL prose (`THIS PROVES HIS CHEATING`); `DEBUG` nowhere at all | nothing |

**CONFIRMED negative: the C64 builds of Pool of Radiance and Curse of the Azure
Bonds carry no trace of the DOS command-line cheat** — not the literals, not the
message, not a dead comparison. It was compiled out for the port, as it was for
Buck Rogers. Method, every hit, and the limit of the claim:
`work/reports/sting-search.md`. Asserted in `tests/test_coabsource.py` so nobody
looks again.

A second, unrelated original-game patch from the same corner of the board:
[topic 2103](https://forums.goldbox.games/index.php?topic=2103.0) gives five
bytes in Champions of Krynn's `GAME.OVR` (`D39E`–`D3A2`, all to `90`) that
disable the password check at save time.

---

## 3. Where the forums contradict us, or each other

| claim | our position |
|---|---|
| Caldor, [4138](https://forums.goldbox.games/index.php?topic=4138.0): "So that must make the C64 use Big Endian I guess" | **Wrong, and now demonstrably so from his own source.** `GoldBoxEditor`'s `GameMaps.cs` defines exactly three offset maps — `getDQK_DOS_Map`, `getDQK_Amiga_Map`, `getDKK_DOS_Map` — and sets `bigEndian = true` only for the *Amiga*. **There is no C64 map and never was**, which confirms from the code what this page had recorded as "intended and never finished". The 6502 is little-endian and every multi-byte field we decode is LE: age at `0x074`, hit points at `0x076`, the seven money words at `0x0BB`, experience as `u24le` at `0x0E8` |
| Ishad Nha, [1912](https://forums.goldbox.games/index.php?topic=1912.0): `GEO6.DAX` record **19** is the "Silver Dragon Den" | **Resolved: the same place.** Stephen S. Lee's guide lists script 19 as *Silver Dragon Lair*, and Diogenes **is** the silver dragon. `work/reports/world-map.md`'s "Cave of Diogenes" is not in conflict |
| The same list gives `GEO` record **30** "Lizard Man Catacombs" and **31** "Wealthy Area" | 30 is agreed by everyone: `GEO1E` is Lizardman Keep's catacombs, and our *script* 30 (`ECL1E`) is a different thing — the attract-mode demo, in a slot DOS's single numbering space left free. **Record 31 is an open conflict between two third-party DOS sources** — §5 |
| Simeon Pilgrim, 2013: the Pool of Radiance ECL "command offset is `0x6700` compared to `0x8000` used in Curse" — while marainein's listings of the same game print addresses from `0x9800` up | Irreconcilable as stated, and neither is ours: the C64 `ECL` block is at **`$9900`** with its flag page at `$4A00`, which is what the addresses in the listings behave like. Take the *addresses in the listings*, not the prose |
| The `coab` opcode table's `$3E DUMP`, `$3F FINDSPECIAL`, `$40 DESTROYITEMS` | **Do not exist in Pool of Radiance.** The dispatch tables at `$15A9`/`$15E7`/`$1625` are 62 entries, `$00`–`$3D` (`work/reports/ecl-opcodes.md`, CONFIRMED). Curse's DOS build having three more is a difference between titles, not an error in either |
| Nol Drek: FRUA's combat limits are memory partitioning — 50 monsters, 3 items each, 100 events, 24×24 maps | About FRUA, a later DOS product. Nothing here constrains the C64 engine. Draxinusom's 2026 measurements ([4677](https://forums.goldbox.games/index.php?topic=4677.0)) put FRUA's real ceiling at ~480 items live at combat start, sharing storage with the party's memorised spells. Interesting engineering, wrong engine |
| marainein: the aggregation wall scheme exists "because they had to support architectures like the Commodore 64 and Apple II" | Plausible and unevidenced. Recorded as his speculation, not as a finding |

---

## 4. Walls — the best format work on the board

Two threads ten years apart, and between them they close the wall question for
the whole early family.

**marainein, [2532](https://forums.goldbox.games/index.php?topic=2532.0), 2013.**
Two wall storage schemes exist: **overlay** (Dark Queen, FRUA — two images
stacked) and **aggregation** (everything earlier, Pool and Curse included — a
grid of 8×8 tiles). A wall is **156 bytes**: ten views, being three distances ×
three angles plus a tenth far-straight view, each a rows × columns array of tile
indices, at offsets `0, 2, 6, 10, 22, 38, 54, 110, 132, 154` — the near-straight
view being 7 columns × 8 rows at offset 54. Walls are grouped **five to a set,
780 bytes**; a `DAX` block holds one, two or three sets and you tell which by
dividing its length by 780. For Pool, Curse and Silver Blades the tile indices
are load order, not file position: a universal group of 45 tiles (block 203)
loads first, then one group of 70 per wallset, whose block ids are
`(walldef block id) × 10 + 1, 2, 3` with block 0 treated as 10. Later games drop
the universal group and use one block of 255 or 256.

**Simeon Pilgrim, [1255](https://forums.goldbox.games/index.php?topic=1255.0),
2010, from the Curse code.** `ws = (wt − 1) / 5; s = (wt − 1) % 5` turns a `GEO`
wall value into a wallset and a slice. "Wall types are the first 512 bytes of
the file" — two bytes per square over 16×16. At run time Curse holds five tile
blocks: 0 and 4 permanent, 1–3 loaded by the `ECL` script's `LOAD PIECES`
command, with indices re-based as each set loads.

**What it gives us.** `goldbox/geo.py` reads the C64 wall art as *nibbles* — high
north / low east at `$000`, south / west at `$100` — two bytes per square, which
is Simeon's 512 exactly. A nibble holds 0–15; apply his arithmetic and `1..15`
becomes **three wallsets of five walls**, precisely the three dynamically loaded
blocks. So the C64 nibble is not an opaque art index: it is
`wallset × 5 + slice + 1`, and `0` is "no wall". **A testable prediction, not a
measurement** — it belongs to whoever owns `work/reports/walldef.md`.

Related, smaller: [3108](https://forums.goldbox.games/index.php?topic=3108.0) —
a door is a non-zero wall slot whose type field is not "blocked", and **a secret
door cannot be distinguished from a normal one without looking at the art**.
Both marainein and Ishad Nha agree there is no programmatic test. That is the
same wall-versus-barrier separation `goldbox/geo.py` documents, arrived at
independently on the DOS side.

---

## 5. The DOS area-id tables

Third-party, DOS, unverified by us. Recorded because `docs/118` carries five
PROBABLEs and one UNKNOWN that these would resolve, and `docs/115` is blocked on
the same question.

### Pool of Radiance — Ishad Nha, [1912](https://forums.goldbox.games/index.php?topic=1912.0)

Numbers are `GEO` record ids. Only the rows that add something to `docs/118`:

| id | forum name | `docs/118` today |
|---|---|---|
| 3 | Valjevo Castle, **North West** | "a floor", PROBABLE |
| 4 | Valjevo Castle, **North East** | "a floor", PROBABLE |
| 5 | Valjevo Castle, **South East** | "a floor", PROBABLE |
| 6 | Valjevo Castle, **South West** | "a floor", PROBABLE |
| 7 | Valjevo Castle, **Upper Level** | "the pool", PROBABLE |
| 19 | Silver Dragon Den | Cave of Diogenes — the same place, §3 |
| 25 | "Unknown Lair" | wilderness, west window |
| 26 | "Unknown Zone" — *Ruined Huts is its lower part* | wilderness, middle window |
| 27 | "Unknown Lair" — *Dark Cave is its lower left* | wilderness, east window |
| 30 | Lizard Man Catacombs | `GEO1E`, shared with `ECL10` |
| 31 | Wealthy Area | `GEO1F`, shared with `ECL18` |
| 32 | Kuto's Well Catacombs | `GEO20`, shared with `ECL1D` |
| — | `ECL3` record 8 City Hall, record **11 Training Hall** | both `docs/118` and `goldbox/areas.py` now say training hall (P61) |

### Two DOS sources, two different castles — unsettled

Stephen S. Lee's guide (`docs/128` §"The area table") names the same ids from the
other end, and **it and Ishad Nha's list disagree on three rows**. Both are
third-party and DOS; neither is ours; nothing here settles it.

| id | Ishad Nha | Stephen S. Lee | verdict |
|---|---|---|---|
| 3 | Valjevo Castle, **North West** | Valjevo Castle (**Northwest and Southeast**) | partial — the guide has one script covering two quadrants |
| 5 | Valjevo Castle, **South East** | Valjevo Castle **Hedge Maze** | **flat contradiction** |
| 7 | Valjevo Castle, Upper Level | Valjevo Castle Inner Tower | no conflict; two names for one floor, and `goldbox/areas.py`'s "the pool" is a third |
| 31 (`GEO1F`) | **Wealthy Area** | script 24's second map, and script 24 **is** the Wealthy Area — so `GEO1F` is the **Temple of Bane** | **flat contradiction**, and exactly the pair `goldbox/areas.py` holds as `("GEO18", "GEO1F")` under the name *Temple of Bane* |

They agree on 4 (Northeast) and 6 (Southwest). **`docs/128` states the guide's
side as settled** — "ours names the wrong one of its two maps" of id 24 —
without recording that a second third-party DOS list says the opposite; the note
belongs on that page too.

**The experiment that decides it, and it is cheap:** fasttravel to each of 3–7 in
turn, match `$0400` against the disk `GEO` with `ResidentGeo`, and read the
floor plan. A hedge maze is not a castle quadrant and will not be mistaken for
one, so id 5 falls out in one look. The same run settles `GEO1F` by fasttraveling to
24 and stepping onto its second map. Until then both readings are PROBABLE and
`goldbox/areas.py` should not be changed to either.

### Curse of the Azure Bonds — Ishad Nha and manikus, [1048](https://forums.goldbox.games/index.php?topic=1048.0)

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
Curse `GEO` decode finds fewer maps than the cluebook has dungeons, that is why.
It is also the most plausible cause of the Teshwave rumour in `docs/125` — id 69
is exactly one of the three.

Per-title area tables also exist on the board for Champions
([1918](https://forums.goldbox.games/index.php?topic=1918.0)), Death Knights
([1919](https://forums.goldbox.games/index.php?topic=1919.0)), Silver Blades
([991](https://forums.goldbox.games/index.php?topic=991.0)), Pools of Darkness
([1033](https://forums.goldbox.games/index.php?topic=1033.0)), Dark Queen
([981](https://forums.goldbox.games/index.php?topic=981.0)), Gateway
([1120](https://forums.goldbox.games/index.php?topic=1120.0)) and Treasures
([1068](https://forums.goldbox.games/index.php?topic=1068.0)). None is for a
title we work on; all are `GEO`/`ECL` record numbers, so they map straight onto
ours if we ever take one of those titles.

---

## 6. Items, three ports deep

Nothing here overturns `goldbox/items.py`, but three sources now bracket it.

**marainein, [1912](https://forums.goldbox.games/index.php?topic=1912.0), 2013**
— **63 bytes** per `.ITM` record in DOS Pool of Radiance, of which 45 is the
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
otherwise field 3 = 0 means "activated by USE", field 2 the effect number and
field 1 the charges; field 3 ≥ 128 means "activated by readying", field 2
carrying the detail. The first 56 effect numbers are the spell ids.

**This is the same shape as ours, minus the string.** The C64 packs an item into
16 bytes and keeps the name in `ITEMNAMES` as three component indices — the plus
at `+4` and the quantity at `+10` in `goldbox/items.py` line up with his `0x31` and
`0x38`. Two things transferred: **"save bonus" is signed** — done, item byte
`+5` is a signed saving-throw bonus and every byte of the 16 is read — and
**spell ids 1–56 double as effect ids**, which matches `0x0AD`'s note in
`docs/20` that the effect slots share storage with item byte `+14` but not its
meaning.

His name-component list and our `docs/85` table agree entry for entry, including
the two blanks at 62 and 63 that our own reader once closed. They diverge at
three later slots where he has blanks and we have `STONE` (135), `MIRROR` (144)
and one more. Either the C64 table fills gaps the DOS one leaves, or his
transcription dropped them. **GUESS**; one grep of `ITEMNAMES` settles it and
nobody needs to hurry.

**David Knott's FRUA records** ([726](https://forums.goldbox.games/index.php?topic=726.0),
[727](https://forums.goldbox.games/index.php?topic=727.0)) — the item *instance*
(18 bytes: pointer to the class record, **three name-component bytes read
backwards, byte 3 to byte 1**, encumbrance in coins at 10 to the pound, price in
platinum, magic bonus, a secondary code, readied, an identify-concealment
bitmask, cursed, bundle count, charges, effect code, and an interpretation byte
saying whether the effect is a spell, a special ability or one of three named
items) and the item *class* (16 bytes: carry location, hands required, damage
dice versus large and versus small/medium, rate of fire per two rounds,
**protection as `188 − base AC` for armour and `AC bonus + 128` for a shield**,
cutting/blunt code, melee usability, range, class-use bitmask, missile
bitfield).

**jhirvonen's `info.txt`** (recovered from the Internet Archive) — the same two
records for the *real* Gold Box games rather than FRUA, as an annotated column
diagram: the item record is 63 bytes with `0x2E`–`0x3E` carrying base type,
three name components, bonus, save bonus, readied, cursed, weight, value,
amount, special properties, hands and slot; the properties record is 16 bytes
and the same shape as Knott's. Gateway to the Savage Frontier is the exception,
with 24-byte property records.

Three things transfer:

1. **The identify-concealment bitmask is the same field in all three ports** —
   bits 0–2 hide name components 1–3. This page already had it from the DOS
   `0x34`; it is now confirmed independently in the FRUA documentation.
2. **`188 − base AC` and `AC bonus + 128`** are two more biased encodings of the
   same family as our `60 − value` and `12 − AC`. The bias constant is
   port-specific; the habit is not.
3. **The plus is encoded in the first name component.** jhirvonen shows Plate
   Mail +2 as `A3 30 3A`; Null Null gives Plate Mail +3 as `A4 30 3A` in both
   Pool and Curse. Two consecutive codes for two consecutive pluses, the other
   two components unchanged — an easy check against `ITEMNAMES`.

Also here: [4070](https://forums.goldbox.games/index.php?topic=4070.0), Null
Null's exhaustive test of every value of the missile bitfield with the observed
behaviour of each. It is FRUA, but it is the most careful empirical decode of a
single field on the board, and it concludes the field is **not** a clean
bitfield — the engine runs a cascade of tests and the first match wins.

---

## 7. `PARTYSTRENGTH`, and how many monsters you get

[Topic 3002](https://forums.goldbox.games/index.php?topic=3002.0). Simeon
Pilgrim answers "how does Pool of Radiance decide the enemy party size" by
posting `CMD_PartyStrength` (`sub_272A9`) from his reimplementation. Per
character: current hit points; armour class less 60, floored at 0; hit bonus
less 39, floored at 0; cleric level; magic-user level. The contribution is
`(cleric×4 + hp + ac×5 + hitbonus×5 + magic×8) / 10`, summed over the party into
a byte and stored to the operand address.

**Opcode `$1E` has semantics**, not just a name; `work/reports/ecl-opcodes.md`
can promote it. He names two neighbours — `$0B` LOAD MONSTER, `$0C` SETUP
MONSTER — and gives the DOS dispatch site as `ovr004:32DF`. The player-facing
consequence, which Null Null spotted immediately: **unreadying your armour
before an encounter reduces the size of the enemy party.**

---

## 8. Smaller findings, one line each

* **Container formats.** The `DAX` table of contents is a two-byte length then
  9-byte entries — record number, three-byte offset, allocation, size
  ([1073](https://forums.goldbox.games/index.php?topic=1073.0)). The `GLB` table
  used by Dark Queen and FRUA is different: a 16-byte header with the record
  count at 7–8 and `DATA` at 12–15, then N+2 four-byte offsets, then a first
  record mapping slots to records; `GLB` has no RLE
  ([1053](https://forums.goldbox.games/index.php?topic=1053.0)).
* **Word-list obfuscation.** SSI stores copy-protection words backwards, each
  byte biased by the length of the phrase, zero-terminated
  ([1152](https://forums.goldbox.games/index.php?topic=1152.0)). Topic
  [1133](https://forums.goldbox.games/index.php?topic=1133.0) gives the offsets
  of those tables in seven DOS executables and notes the per-title alphabet
  offset varies — Death Knights uses eight different alphabets across its fifty
  passwords.
* **Text packing.** Every Gold Box game packs its strings **four characters into
  three bytes**, six bits each, with the compressed length in the byte before
  the string ([997](https://forums.goldbox.games/index.php?topic=997.0),
  [981](https://forums.goldbox.games/index.php?topic=981.0)). The C64 `ECL`
  strings use exactly this packing — `work/analysis6/ecl6.py::unpack` is the
  VM's `$150A` unpacker, and it is what read every string quoted in §2's table.
* **No file names a map.** Simeon Pilgrim, flatly: "there is no data in the game
  that names the `GEO` blocks"
  ([1272](https://forums.goldbox.games/index.php?topic=1272.0)). Area names are
  always earned locally, which is what the project's skill card already says.
* **Save-file area fields, per title.** Death Knights `.PTY`: 198 current `GEO`,
  243 current `ECL`, 2561/2562 party x,y. FRUA: 18 current module, 21 initiated,
  133 initiation. Pools of Darkness and Dark Queen: 18, 21, 197. The same three
  ideas at title-specific offsets.
* **The wedge wall encoding** used by Silver Blades — north/east halves in one
  group, south/west in another, with a run-length shorthand `253, x, #` for
  repeats that Dark Queen drops
  ([991](https://forums.goldbox.games/index.php?topic=991.0)).
* **How Gold Box Companion works:** it finds the DOSBox window, opens the
  process, and reads and writes its memory — no breakpoints at all
  ([1913](https://forums.goldbox.games/index.php?topic=1913.0)). marainein asked
  in 2015 for an `ECL` opcode that would halt the VM so a debugger could inspect
  it; it was never built. Our VICE watchpoints make that whole line of work
  unnecessary, which is worth knowing when comparing the two tools.
* **Amiga Pool of Radiance is still unsolved.**
  [4053](https://forums.goldbox.games/index.php?topic=4053.0), 2022: the Amiga
  build uses unified `.dax` files that neither Gold Box Companion nor Gold Box
  Explorer parses, and nobody in the thread had cracked them. Ours is the only
  port project that has read Amiga `ecl.dax` at all.
* **An original-game defect nobody diagnosed:** a Curse save that loads the
  previous dungeon's map under Zhentil Keep's events, reproducible for the
  reporter and never explained
  ([1340](https://forums.goldbox.games/index.php?topic=1340.0)). Same class as
  the Sokol Keep elf: state that should have been reset was not. Rumour only,
  and it is in `docs/125`.
* **A dated original-game bug, documented:** in the FRUA engine, when the year
  counter passes 99 and wraps to zero, **every character in the party ages one
  year** (`SAVGAM.TXT`, David Knott). Whether the earlier engines share it is
  unknown.

---

## 9. Tooling and sources, and what survives today

455 distinct external URLs appear in the 296 threads, across 132 hosts. The
extracted list with citing threads is `work/forums/board8_external_urls.txt`;
a per-thread index with authors and post counts is
`work/forums/board8_triage.txt`.

### Live, and worth having

| resource | what it holds |
|---|---|
| **`github.com/simeonpilgrim/coab`** | The Curse reimplementation, and **the most valuable thing the board points at**. `Classes/PoolRadPlayer.cs` and `Classes/Player.cs` are the DOS records for our two titles; `engine/ovr017.cs::ConvertPoolRadPlayer` is the import routine; `engine/ovr025.cs` and `ovr026.cs` recompute the derived fields; `Classes/GeoBlock.cs`, `EclBlock.cs`, `Item.cs`, `engine/VmOpp.cs` and `ovr0NN.cs` are the ECL VM. Mined in [`117`](117-save-conversion.md); fetched to `work/forums/ext/`. Simeon notes **no repacker exists** — modifying a DOS `.DAX` in place is still hand work |
| **`gbc.zorbus.net`** | Gold Box Companion, **ECL-Tool**, **ECL-Monitor** (a live ECL disassembler over a running DOSBox game, following the script PC and *editing* flags and operands — the closest existing thing to `wish`, on the other port), `savefiles_compared.txt` (already in `docs/60`), `formats.zip` |
| **`frua.rosedragon.org`** | The FRUA archive; 137 of the 151 links resolve under `/pc/`. `pc/uashell/hackdocs.zip`, 202 KB, holds 56 text files including `SAVGAM.TXT`, `CCHFORM.TXT`, `GEOGRIDS.TXT`, `GEOEVENT.TXT`, `ITEM.TXT`/`ITEMS.TXT`, `VOCAB.TXT`, `SPECAB.TXT`, `VAULT.TXT`, `TLBFORM.TXT`. All FRUA, but it is the primary source most of the board is quoting |
| **`github.com/simeonpilgrim/goldboxexplorer`**, **`github.com/bsimser/Gold-Box-Explorer`** | Gold Box Explorer, C# `DAX`/`GEO`/`ECL`/`GLB` plugins; version 1.2 added ECL decoding for most games, search, and a first-person map view ([3089](https://forums.goldbox.games/index.php?topic=3089.0)). The CodePlex original is gone. Its own users report it mis-sorts image resources and its PNG export is unreliable |
| **`github.com/kblood/GoldBoxEditor`** | Caldor's cross-port character converter. Three offset maps, no C64 map — §3 |
| **`simeonpilgrim.com/blog`** | The cheat-code and code-wheel write-ups behind topics 1082 and 1133 |
| **`web.archive.org`** | Carries `personal.inet.fi/koti/jhirvonen/gbc/` in full; `items/info.txt` (23 KB) and `items/por_items.txt` (99 KB) recovered — §6 |
| **Blackthorn's DOS disassembly**, [4605](https://forums.goldbox.games/index.php?topic=4605.0), 2025– | A full DOS Pool of Radiance disassembly in progress, down to the Turbo Pascal v4–v6 libraries, feeding a revision of his GameFAQs guide; an unofficial bugfix build is the stated next step. Active, serious, and the only other person doing this on any port. He notes **v1.0 and v1.3 differ** in random item generation — a version axis we have not considered |
| **Draxinusom's format documentation**, [4677](https://forums.goldbox.games/index.php?topic=4677.0), 2026– | Character/monster, effects, items, vault, `GEO` and FRUA `SCRIPT.GLB` formats normalised across ten games, with ImHex `.hexpat` patterns being submitted to ImHex's official library. On OneDrive and 403 without a Microsoft sign-in — **but obtained by Donald and written up in [`127`](127-community-formats.md) and [`128`](128-guide-and-scripting.md)**: the patterns confirmed our four-plane `GEO` decode outright, `GB_FileFormat.xlsx`'s `CHR_01` covers all 285 DOS bytes, and `EXE_Offset` closed the saving-throw question |
| **Stephen S. Lee's GameFAQs guides** ([73869](https://gamefaqs.gamespot.com/pc/564785-pool-of-radiance/faqs/73869), [78365](https://gamefaqs.gamespot.com/pc/564786-curse-of-the-azure-bonds/faqs/78365)) | 403 to a fetch, **obtained by Donald**; `docs/128` works from `por-guide.txt` v2.00. Its §12.3.3 lists the same 62 ECL opcodes we derived from the VM's own dispatch tables, with semantics we had not; §12.4.1 names 229 script flags against our 172 addresses; §12.2.3 enumerates 127 effect ids, the namespace `goldbox/traits.py` now carries |

### Dead, and what replaces them

| resource | state | replacement |
|---|---|---|
| `rewiki.regengedanken.de/wiki/.DAX` — cited six times as *the* `DAX` reference | **host gone, and the page was never archived.** `List_of_file_formats` survives at a 2018 snapshot and links to `.DAX`, but the target has no capture | topic [1073](https://forums.goldbox.games/index.php?topic=1073.0) and `Classes/DaxFiles/` in `coab` cover the same ground |
| `personal.inet.fi/koti/jhirvonen/gbc/` — 20 links | host gone (Finnish ISP personal pages retired) | `gbc.zorbus.net` for the tools; the Internet Archive for the `items/*.txt` tables, which are *not* on the new site |
| `goldbox.codeplex.com` (9 links), `code.google.com/p/coab` (9 links) | shut down | the GitHub mirrors; the `coab` paths still map (`trunk/Classes/Player.cs` → `Classes/Player.cs`) |
| `ishadnha.webs.com` | gone | Ishad Nha's spreadsheets survive as forum attachments only |
| `img169.imageshack.us`, `oi40.tinypic.com`, photobucket albums | mostly gone — marainein's four WALLDEF diagrams in 2532 no longer render | the *text* of 2532 carries the whole table, so nothing essential is lost |
| `frua.isgreat.org`, the Yahoo groups, `home.earthlink.net/~uashell`, `gnba.netdemons.com`, `icestorm9999.com`, `bunnzy.org`, `nwnserver.net`, `rhwiii.info`, `csved.sjfrancke.nl`, `annarchive.com`, `rpg.rem.uz`, `robertsnet.homenet.org`, 13 Dropbox shares | gone or 404 | nothing lost that bears on formats — module archives, mailing lists, utility mirrors, art uploads |

**Not fetched, deliberately:** forum attachments (`action=dlattach`) — Ishad
Nha's spreadsheets duplicate `docs/127`, and the ready-made playtester saves and
the Gold Box password lists are game data we must not keep.
`weekendwastemonster.net`'s copy-protection word lists are game documentation
and of no research value here; its linked `.xls` files 404 anyway. `gbc_beta.zip`
is a 14 MB Windows binary. The `docs.google.com` spreadsheet from
[1912](https://forums.goldbox.games/index.php?topic=1912.0) is a live 261 KB
export of area and monster tables of the kind `docs/127` already covers. SMF's
own search needs a POST and a session and was not attempted — the board index is
15 pages and reading it was cheaper.

---

## 10. Method, for whoever sweeps a board next

* Fetching was **sequential, one connection, ~4 s between requests**, from a
  single process. The board sits behind a proof-of-work bot challenge that plain
  `curl` and `WebFetch` cannot pass; pages were loaded through a real browser
  session and the printer-friendly rendering requested from inside it. 296
  threads, **zero failures**, no sign of throttling. An earlier attempt failed
  because three agents hit the same host from one address at once — one agent
  pacing itself is enough and does not annoy anybody.
* `action=printpage;topic=N.0` returns the entire thread, all pages, headers and
  post authors included.
* The board index is 15 pages of 20 (`board=8.0` … `board=8.280`, the last
  holding 16); `board=8.300` redirects back to `.280`, which is why an earlier
  count said 16 pages.
* Nothing on any page addressed a reader as an agent, claimed authority, or
  asked for an action. Nothing was executed. Every external fetch was a plain
  read; the only archives opened were `hackdocs.zip` and two recovered `.txt`
  files.
* The threads worth re-reading in full are **2532, 1255, 3002, 1082, 726, 727**
  and the `coab` source.
