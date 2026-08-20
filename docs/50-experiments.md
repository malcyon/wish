# Experiment log

Append-only. Hypothesis → method → result. Failed experiments stay in; they are the
expensive knowledge.

Each experiment is identified by **name**, not by a number. The rest of the docs cite
them by that name — "the shopping trip", "the thirteen-field edit" — so a reference
says what happened without a lookup. Entries stay in the order they were run.

---

## Reaching VICE's binary monitor
**Hypothesis.** The Flatpak VICE 3.10 supports `-binarymonitor`, but the sandbox's lack of a
`shared=network` permission traps the socket in its own network namespace.

**Method.** `flatpak info --show-permissions net.sf.VICE` to inspect grants; added
`--share=network` to the `flatpak run` line under a `POR_DEBUG=1` guard; launched and polled
`127.0.0.1:6502`.

**Result.** CONFIRMED. Permissions show `shared=ipc` only — no network. With `--share=network`
the port accepts connections **within 1 second** of launch. `-binarymonitor` and
`-remotemonitor` are both compiled into the Flathub build (an earlier `grep` of `-help` missed
them purely because of how context flags grouped the output — the flags were always there).

Applied only in debug mode, so ordinary play keeps the original sandbox permissions.

---

## The desynchronised monitor reads
**Hypothesis.** (Unplanned; found while smoke-testing.) A naive client that reads exactly one
response per request will work.

**Method.** Requested five memory ranges of known sizes in sequence and compared requested
length against returned length.

**Result.** FALSE, and expensively so. Requests returned the *previous* request's data:

```
$4d00-$4d0f  want    16   got    40
$4d00-$4dff  want   256   got     0   (length field garbage: 42523)
$0400-$04ff  want   256   got    16
$e000-$e3ff  want  1024   got   256
```

VICE interleaves **unsolicited events** into the stream — observed type `0x62` (STOPPED) with
`rid=0xffffffff`. They are indistinguishable from replies unless you check the request id in
header bytes 8–11. Matching responses by request id fixed it immediately; all ranges then
returned exact lengths, including a full 7168-byte `$4900–$64FF` read.

**Consequence.** Any hand-rolled monitor client must match by request id. The MCP server
handles this correctly. Failure mode is silent and looks like corrupted memory, not an error.

---

## Attaching to an already-running emulator
**Hypothesis.** `axewater/mcp-vice-emu` can drive a VICE we started ourselves.

**Method.** Built it; inspected `ViceConnection.connect()`.

**Result.** PARTIAL — needed a patch. Upstream always spawns `${emulator}.exe` (Windows-only
path construction) and has no attach mode. Patched to probe the port first and attach when a
monitor is already listening, and to drop `.exe` off-Windows. `cleanup()` only kills
`this.process`, which stays null on the attach path, so it will not kill the user's emulator.

Verified: `vice_connect` → "Connected to VICE x64sc on port 6502"; `vice_memory_read` returns
memory. Note its parameter is `start`, not `address`. Exposes 21 tools, not the 32 the README
claims. This is a local fork at `~/src/mcp-vice-emu`; re-apply if re-cloned.

---

## Delivering keystrokes to the game
**Hypothesis.** The game can be driven programmatically for experiments.

**Method.** Tried, in order: KERNAL keyboard-buffer injection via the monitor
(write `$0277`, set count at `$C6`); `xdotool key --window <id>` (synthetic
XSendEvent); `xdotool windowactivate` + XTEST on the desktop; the same inside a
nested Xephyr server.

**Result.** Only the last works reliably.

| Method | Outcome |
|---|---|
| KERNAL buffer `$0277`/`$C6` | **fails** — the game scans the CIA keyboard matrix directly |
| `xdotool key --window` | **fails** — VICE/GTK ignores synthetic `XSendEvent` |
| `xdotool` + activate, on the desktop | **unreliable** — works only if VICE happens to hold real focus |
| `xdotool` inside Xephyr | **works, always** |

The desktop case is the trap: under Wayland there is no dependable way to focus
an XWayland window. `xdotool windowactivate` returns success, `xdotool
getactivewindow` *and* `_NET_ACTIVE_WINDOW` both report the VICE window, and the
keystrokes still do not arrive. It appears to work right after launch only
because VICE grabs real focus then; it stops working as soon as focus moves —
for instance when the user drags the window to another monitor.

Two consequences beyond convenience:

* Keystrokes sent while VICE lacks focus land in **whatever window does have
  it** — potentially the user's terminal. Running nested removes that hazard
  entirely.
* Inside Xephyr there is no window manager, so `windowactivate` *errors* — and
  that is fine. With no WM the single window holds input focus permanently, so
  XTEST always reaches it. Do not "fix" that error.

Feedback channel is unaffected: screenshots come through the MCP and memory
through the binary monitor, neither of which depends on the display.

Baked into `tools/rungame.sh`.

---

## Does a monitor connection stop the machine?
**Hypothesis.** (Raised after wrongly calling the emulator "frozen".) Reads
taken while a binary-monitor socket is open reflect a *paused* machine.

**Method.** Compared the KERNAL jiffy clock at `$A0-$A2` within a single
connection versus across separate connect/read/close cycles.

**Result.** CONFIRMED. Within one open connection nothing advances. Across
separate connections the clock advanced 62 jiffies in 1.03s of wall time —
exactly real time.

**Consequence.** Connect → read → **close** is the required discipline; holding
a socket open freezes the game. Also: do not infer "stopped" from a constant
`$D012`. Monitor reads with side-effects disabled do not return live VIC counter
values, which is what caused the wrong call in the first place.

---

## Getting past the copy protection
**Hypothesis.** The code-wheel check can be understood well enough to get past
it reliably without a human reading the wheel each boot.

**Result.** SOLVED. Full details are in the separate private repo
`~/src/por-codewheel` (kept out of this repo deliberately). Summary of what
matters here:

* The check lives at `$12C4`-`$12F6` in an overlay resident at `$1000`-`$13FF`.
* The game picks the **answer first** — `$1376` holds the expected word index
  (0-11) and `$1377` the path — and derives the displayed runes from those.
  So the answer can simply be read out of `$1376`.
* One byte-pair patch (`$12D9: D0 04 -> EA EA`) makes any answer pass.
* `work/E003-past-protection.vsf` is a VICE snapshot taken at the
  party-creation menu.

**Warning learned the hard way.** That overlay is *replaced* once the game loads
another side, so `$12D9` later holds unrelated live code. Writing the patch
blind a second time corrupted a running routine (`LDA #$01` -> `NOP NOP`).
**Always read and check the bytes before patching an overlay address.**

---

## The slot stride, first attempt: $400 x 6 (WRONG)
**Hypothesis.** Character slots in `SAVEDGAME0` are either 6 x `$400` or
3 x `$800`; a save containing characters in adjacent slots would distinguish
them.

**Result.** CONFIRMED as **6 slots of `$400`** at
`$4D00 $5100 $5500 $5900 $5D00 $6100`.

**The evidence was already on disk.** `POOL1.D64` ships a **sample save game**
whose `SAVEDGAME0` holds two characters in adjacent slots: `ZARRADA` at `$4D00`
and `LARA SPELLSWORD` at **`$5100`**. `$5100` is slot 1 under a `$400` stride
and does not exist under the `$800` hypothesis. No emulator work was required.

That sample save also gave the project its second and third character specimens,
which settled two further questions (`docs/40-memory-map.md`):

* races are **1-based** (`HUMAN=7`, `ELF=2`), classes **0-based**
  (`CLERIC=0`, `FIGHTER=2`) — the inconsistency flagged earlier is genuine;
* ZARRADA's saving throws are exactly the AD&D 1e L1 **cleric** table
  (10/13/14/16/15) where BRUTUS's are the **fighter** table (14/15/16/17/17),
  independently confirming those offsets and showing the values are
  class-derived;
* `char_class` runs beyond the 6-entry creation menu — LARA, an elf, has 13,
  a multi-class code.

Promoted `race`, `char_class`, `age`, the five saving throws and `movement` from
PROBABLE to CONFIRMED. Coverage 27 -> 37 of 580 bytes CONFIRMED.

Pinned as regression tests in `tests/test_savegame.py::TestSlotStrideE003`,
with `tests/fixtures/pool1_savedgame0.bin` as the specimen.

**Method note — worth remembering.** Considerable time went into driving the
game to create characters, and into trying to make it load a constructed save,
before simply *reading the disks we already had* answered the question outright.
Two dead ends came out of that effort and are recorded below because they still
cost time if rediscovered.

---

## Two dead ends in driving VICE
**1. Character creation stalls at the name prompt.** Race/gender/stats/class/
alignment can all be driven (see the menu helpers), and the name types correctly
into the input buffer at `$9700` — verified both on screen and in memory — but
Return silently clears the field and re-prompts, and no record appears in
`$4D00`+. Ruled out: leftover patches, the disk in the drive, input timing, and
a hung CPU. Cause unknown.

**2. `Alt+N` does not swap disks under XTEST.** `Alt+N` *is* the correct binding
(`fliplist-next-8`, from VICE's own `hotkeys-fliplist.vhk`), but neither
`xdotool key alt+n` nor a properly held chord (Alt down, separate n press, real
gaps) changes the attached image — ten swap-and-retry cycles all returned
`SAVED GAME NOT FOUND!`. `F10` does not open the menu bar and synthetic mouse
clicks do not hit the menus either, while plain keypresses reach the emulated
machine normally. So VICE's GTK input layer is not seeing synthetic modifiers or
clicks, only the emulation canvas is receiving keys.

**Consequence:** an experiment that needs the game to *read* a constructed disk
cannot currently swap that disk in. Options, none yet tried: build a boot disk
that already carries the save files so no swap is needed; or find a runtime
attach route (the binary monitor has no attach command).

---

## The slot stride, corrected: $100 x 8
**The first attempt’s conclusion was wrong.** It recorded 6 slots of `$400`; the truth is
**8 slots of `$100`**, each holding the first 256 bytes of the record.

**What settled it.** Donald created a six-character party, added all six, saved,
and reloaded. Reading that save found all six names at `$100` intervals —
`$4D00 $4E00 $4F00 $5000 $5100 $5200` — and each slot is byte-identical to the
first 256 bytes of that character's own exported `.chr`.

**Why the error survived.** Every specimen until now had at most two characters:

* `PORSAVE.D64` had one live character plus a stale copy outside the slot area.
  The bytes between them were zero, and an exported record is mostly zero too,
  so a contiguous 580-byte record at `$4D00` *appeared* to fit — the celebrated
  "536 of 580 bytes match" was mostly zeroes agreeing with zeroes.
* The `POOL1.D64` sample save has characters at `$4D00` and `$5100`, which I
  took as adjacent `$400` slots. Under the correct model they are slots 0 and 4
  — consistent with **both** hypotheses, so it never was evidence.

**The lesson.** The disproof needed a *fully populated* structure. Two sparse
specimens agreeing with a hypothesis is not the same as testing it, and
"$5100 exists only under a $400 stride" was simply false — I asserted a
uniqueness I had not checked.

Corrected in `por/savegame.py`, with `tests/fixtures/party6_savedgame0.bin` (a
real six-character party) pinned as the regression fixture.

---

## Class encoding and saving throws
Reading Donald's six characters corrected a second error and confirmed the
class table.

* **`char_class` uses the standard Gold Box order**, not the order of the
  6-entry creation menu at `$3288`: `CLERIC=0 DRUID=1 FIGHTER=2 PALADIN=3
  RANGER=4 MAGIC-USER=5 THIEF=6 MONK=7`. Code 5 had been recorded as "monk",
  which produced an "elf monk" — impossible in AD&D, and the tell that something
  was wrong. MALCYON's saving throws are exactly the AD&D 1e L1 **magic-user**
  table, settling it.
* **Saving throws are stored already adjusted for race as well as class.**
  MAGNUS, a dwarf fighter with CON 13, has saves uniformly 3 better than the
  human fighter table — and the dwarf racial bonus is `floor(CON/3.5)` =
  `floor(13/3.5)` = 3. So they are derived values, not raw class-table lookups.
* **Multi-class codes are above 7.** LADY KATHERINE is a female half-elf
  fighter/thief (confirmed by Donald) with code **16**; her saves are the
  best-of thief and magic-user, which does not match fighter/thief and is not
  yet explained. LARA SPELLSWORD, an elf, has code 13. The combination encoding
  is still unknown.

  → **Resolved later.** The 1989 BASIC editor's class table gives 16 =
  magic-user/thief and 13 = fighter/magic-user, and LADY KATHERINE's
  `class_bits` is 5 = magic-user | thief. So her saves were right all along and
  the description was the thing that was wrong — she is a magic-user/thief, not a
  fighter/thief. The full enumeration is in `docs/20-character-record.md`.

---

## The six-character comparison
**Hypothesis.** With enough characters whose attributes we already know, fields
can be identified by comparing records and correlating byte-level variation —
without running the game at all.

**Method.** Donald created a six-character party with deliberately varied races,
classes, sexes and alignments and saved it. Combined with the six on `POOL1.D64`'s
sample save that gives **twelve specimens**. `tools/compare.py` reports, for every
offset, how the value varies across all of them; each varying offset is then
matched against a known attribute or an AD&D rule.

**Result.** Six fields found and one more confirmed afterwards:

| field | offset | how it was established |
|---|---|---|
| class bitmask | `0x0EB` | `magic-user=1 cleric=2 thief=4 fighter=8`, OR-ed. LADY KATHERINE = 5 (magic-user/thief, confirmed by Donald); LARA **SPELLSWORD** = 9 (magic-user/fighter — her name says so) |
| sex | `0x0D6` | 0 male, 1 female; set for the three female characters and no others |
| infravision | `0x0D5` | 6 for every demi-human, 0 for every human, across all twelve |
| thief skills | `0x0A5`–`0x0AC` | 30/25/20/20/10/10/85/5 — exactly the AD&D 1e L1 thief table, non-zero only when the thief bit is set |
| effective STR | `0x0E2` | equals STR below 18; 18/80 and 18/81 both give 21, 18/98 gives 22 |
| current HP | `0x119` | equals `hp_max` in six undamaged specimens |
| **alignment** | `0x0D8` | 0-based index into the game's own table at `$32B3`; Donald supplied all six alignments and every one matched |

Coverage 57 → **71 of 580 bytes**.

**Why the class bitmask matters.** `char_class` at `0x073` is a single code that
cannot express a combination — it is why multi-class values like 13 and 16 were
opaque. The bitmask decodes them directly, and all twelve specimens now read out
correctly, including three multi-class characters from the sample save
(magic-user/fighter, thief/fighter, magic-user/cleric).

**The lesson worth carrying.** This took minutes and needed no emulator, no
disk swapping and no copy-protection work. Every earlier attempt to find fields
by driving the game was slower and less productive than *arranging for varied
data and then comparing it*. Prefer that route whenever a field plausibly
differs between characters.

---

## The shopping trip: the inventory format
**Method.** Donald equipped all six characters and saved to a *second* disk
(`PORSAVE2.D64`), leaving the original untouched. Diffing the two `SAVEDGAME0`
files isolated every byte the purchases changed.

**Result.** The inventory format is fully decoded.

```
$5900 + slot * $100        one $100 block per character slot
16 items of 16 bytes       within each block

+0   name index (usually equals +3; differs for stacked ammunition)
+2   qualifier name index -- MAIL, ARMOR; 0 when absent
+3   primary name index  <- the reliable one
+6   bit 7 = readied / equipped
+8   weight, 16-bit LE, in tenths of a pound
+10  quantity (ammunition)
+11  cost in gold pieces
```

Name indices are **1-based** into the table in the game's `ITEMNAMES` file
(names start at offset `0x201`), and names are **compound**: `BANDED` + `MAIL`.

**What confirmed the field meanings** was that every weight and cost matches the
AD&D 1st edition equipment tables exactly — banded mail 90gp/35lb, long sword
15gp/6lb, short sword 8gp/3.5lb, leather armour 5gp/15lb, dagger 2gp/1lb, short
bow 15gp/5lb. Six independent agreements leave no room for coincidence.

**Also settled by the same diff:**

* **Money is confirmed.** Gold at `0x0C1` fell for all six characters and
  platinum at `0x0C3` changed for three — exactly what a shopping trip and a
  money-pool do. Promoted from PROBABLE.
* **Slots 6 and 7 are not stale, they are scratch.** They previously held a copy
  of BRUTUS and now hold a copy of MALCYON, first name byte zeroed, and their
  item blocks match slot 0's too. They are a working buffer, not party members.
* `$5500`-`$58FF` stays zero even with a fully equipped party. Still unknown.
* Header bytes `$49C7` (7 -> 0) and `$49C8` (2 -> 3) changed; unexplained.

**Method note.** This is the second time comparing *arranged* data beat driving
the game. One shopping trip and a diff produced a complete format.

---

## The combat icons
**Method.** Donald changed every character's combat icon in-game and saved.
Diffing against the previous save isolated the changes.

**Result.** Every changed byte fell inside `$4BE0`-`$4CFF` — nothing else in the
save moved except one byte in a character slot. The table is confirmed as
**8 entries of 36 bytes**, one per character slot, ending exactly at `$4D00`.

Each entry splits cleanly in half:

```
+0  .. +17    18 screen codes  -- shape / pose
+18 .. +35    18 colour values -- one per cell, C64 colours 0-15
```

**What proved the split:** MAGNUS changed **only** bytes 18-35, every one of
them in the range `$00`-`$0F`. A colour-only change, and valid colour codes.
ROLAND and LADY KATHERINE changed both halves. So shape and colour are
independently editable — which is exactly what the Gold Box Companion exposes.

The same 36 bytes appear at record offset `0x220` in an exported `.chr`, which
is why an export carries its icon while a save slot does not.

Not yet found: the **large/small** flag GBC also offers. It is not in these 36
bytes, so it lives elsewhere or is implied by the shape.

---

## The hunt for current hit points
**Question.** LADY KATHERINE was left on 4 of 5 hit points. Where is that
stored?

**Result: nowhere in either save file.** Searched both `SAVEDGAME0`
(`$4900`-`$64FF`) and `SAVEDGAME1` (`$8300`-`$8AFF`) for the party's
current-hp sequence `[4,4,7,9,9,11]` and for the max-hp sequence
`[4,5,7,9,9,11]`. Neither appears. Nor does any lone `4` in her character slot
mean hit points — the four bytes holding 4 or 5 are all accounted for (race,
`hp_max`, a thief skill, alignment, `class_bits`, `hp_rolled`).

The only unexplained byte that moved after combat was `0x0EC` (0 -> 1), and it
moved for **MALCYON and LADY KATHERINE** — precisely the two spellcasters, not
the wounded character. So it is far more likely spell state than damage.

**What this suggests.** The game may simply not persist current hit points, and
restore characters to full on load. That is easy to check and worth doing before
any more searching:

> Reload the save and look at LADY KATHERINE. If she is back to 5, current hp is
> not saved and there is nothing to find. If she is still on 4, it is stored
> somewhere neither file covers — most likely computed from data we have not
> identified.

Until that is answered, `hp_current` at `0x119` stays PROBABLE: it equals
`hp_max` in every specimen, and it lies outside the 256 bytes a save slot
stores, so it has never been observed differing.

---

## The thirteen-field edit: edits CONFIRMED in-game ✅
**Proven: the game accepts an externally edited save.**

**Method.** Donald exported his party with `tools/wish.py --export`, edited
MALCYON in the YAML, imported to a new disk, and loaded it in the game.

Thirteen fields changed at once: all six ability scores to 18, and all five coin
types plus gems and jewelry.

**Result — every edit took.** MALCYON's character sheet reads:

```
MALE ELF AGE 176        STR 18      JEWELRY   10
NEUTRAL GOOD            INT 18      GEMS      10
MAGIC-USER              WIS 18      PLATINUM 100
                        DEX 18      GOLD     102
LEVEL 1  EXP 17         CON 18      ELECTRUM 100
HITPOINTS 4             CHR 18      SILVER   126
AC 8                                COPPER   100
THACO 20  DAMAGE 1D3
```

Unedited fields survived intact — race, sex, age, alignment, class, experience.
**No checksum, no rejection, no silent overwrite.** The editor's central premise
is now demonstrated rather than assumed.

### Two things the character sheet settled for free

**`0x071` is not THAC0.** It was recorded as a GUESS reading 39 for MALCYON and
40 for BRUTUS, with a note that it might be a doubled THAC0. The sheet shows
**THAC0 20**. So the byte is something else entirely; the guess is retired and
the offset returns to unknown. Recording it as a GUESS rather than a fact is
what made this cheap to correct.

**Armour class is a cached derived value, not recomputed on load.** The sheet
shows **AC 8**. MALCYON wears no armour, so AC comes from dexterity: base 10 with
DEX 16 gives −2, i.e. AC 8 — his DEX *before* the edit. The edit raised DEX to
18, which should give −4 and AC 6. The game displayed the stale value.

This is exactly what the ability-score edit was meant to discover, and it matters for the
editor: **AC is stored somewhere we have not found**, and editing DEX alone
leaves it inconsistent. Anything else derived from the ability scores — damage
bonus, to-hit — may be cached the same way. `DAMAGE 1D3` and `THACO 20` on the
sheet are further candidates to check against the raw bytes.

### Still open

*(Answered later; kept as written, with the answers noted.)*

* Where AC is stored. It is not in the fields we have identified.
  → **`SAVEDGAME1` roster block `+0x0F`, as `60 - AC`.** Not in the character
  record at all, which is why nothing here found it. THAC0 turned out to be the
  byte next door.
* Level, and the level-drain pair. The sheet shows `LEVEL 1`.
  → **Level is `0x0A0`**, found once `npc_party.d64` supplied characters above
  level 1. The drain pair is still open.
* `15 DART` on the sheet against the item records, which show dart stacks of 4
  and 24 — the displayed count needs reconciling with the stored quantities.
  → still open.

---

## Per-class levels, and how dual-classing is stored
**Prompted by Donald**, who had earlier used the Gold Box Companion on the DOS
version to change a human thief into a fighter. The game treated it as
**dual-classing**: the character kept his thief skills, his thief level stayed
at 1, and only his fighter level advanced. That behaviour requires a level *per
class*, not a single level.

**Result.** `0x0C9`–`0x0CC` is a four-entry level array, indexed in the same
order as the class bits at `0x0EB`:

| offset | class | bit |
|---|---|---|
| `0x0C9` | magic-user | 1 |
| `0x0CA` | cleric | 2 |
| `0x0CB` | thief | 4 |
| `0x0CC` | fighter | 8 |

Across **all twelve specimens** a byte here is non-zero exactly when the
corresponding class bit is set — including five multi-class characters
(magic-user/thief, magic-user/fighter ×2, thief/fighter, magic-user/cleric).

This also corrects an earlier guess: `0x0CC` was noted as a possible
"exceptional strength" flag, because the only fighters in the specimen set at
the time were also the only characters with exceptional strength. Adding the
sample party broke that coincidence.

**Recorded as PROBABLE, not CONFIRMED.** Every specimen is level 1, so every
value is 1, and "level" is not yet distinguishable from "this class is present".
A single levelled-up character would settle it — and under the dual-class
hypothesis, a dual-classed one would show two *different* numbers, which no
flag interpretation could explain.

**In the editor.** `wish` now exposes this directly:

```yaml
classes: [thief, fighter]
levels: {thief: 1, fighter: 3}
```

which is exactly the state Donald produced with GBC. Adding a class starts it at
level 1; removing one clears its level.

**Note on AD&D rules.** Dual-classing is humans-only, multi-classing is
demi-humans-only. The save format does not appear to distinguish them — both are
just several class bits with several levels — so the game presumably enforces
the rule at character creation rather than in the data. Whether it *re-checks*
on load is untested, and worth knowing before anyone dual-classes an elf.

---

## The eight-character NPC party
**Source.** `npc_party.d64`, a save disk found online (Donald; discussed on
r/c64, "An unusual Pool of Radiance save disk"). Three player characters and
five NPCs. Two things in it cannot have come from ordinary play: PRINCESS
FATIMA's race byte is **0**, outside the 1-8 enumeration character creation
offers, and MAD MAN's experience is exactly **`$FFFFFF`** while the rest of the
party holds 10,200 to 115,311 -- a saturation value, and exactly what the 1989
editor's documented "set XP to the max" writes. So its *values* prove nothing.
Its *structure* proves a great deal.

*Two reasons originally given here were wrong and are withdrawn: that every
character had all-18 abilities (four of the eight have ordinary spreads
including 8s and 9s), and that its item names were garbled (they read correctly
once our own `ITEMNAMES` gap bug was fixed).*

**Result. Four findings, in order of how much they change.**

**1. Eight slots can be occupied, and the roster is exactly one page.** All eight
`SAVEDGAME0` slots are occupied and the `SAVEDGAME1` roster index bytes run 0..7.

*Care with this one.* It proves the **file format** holds eight, which the slot
area and the roster page already implied. It does **not** prove the game lets you
run a party of eight, still less that five of them may be NPCs: this disk has
been through a character editor and has never been loaded in play under
observation. An earlier version of these notes drew "a party can hold eight
characters, up to five of them NPCs" from it. That was induction from one
hacked specimen and is withdrawn.
Eight blocks of `$20` fill `$8300`-`$83FF`, and `$8400` starts a jump table
(`4C xx 84`). The roster section had been written up as six blocks purely because
every save to hand held six characters. See `docs/30-savegame-layout.md`.

**2. Memorised spells, found in two places at once.** Roster bytes `+0x03`,
`+0x04` and `+0x05` hold the number of 1st-, 2nd- and 3rd-level spells memorised;
record offset `0x020` holds the packed list of spell ids, highest level first.
The two agree perfectly: across the fourteen characters for which we hold both
files, the count of non-zero bytes at `0x020` equals the sum of the three roster
counts, every time -- 13 for SIMON, 8 for XAVIER, 0 for all twelve non-casters.
The six sample characters on `POOL1.D64` support the list but cannot test the
agreement, because that disk ships no `SAVEDGAME1`. Two casters sit exactly
on the AD&D 1st edition maximum including Wisdom bonus spells and two sit just
below, which is what a party mid-adventure should look like. GRON has WIS 18 and
no spells, so the counts follow class, not Wisdom.

**3. Character level is at `0x0A0`.** It had been an unknown reading a constant
`01`, because every specimen until now was level 1. Here it reads 4, 6, 7 and 8,
and equals the per-class level array at `0x0C9`-`0x0CC` for all eight. That array
was PROBABLE on the strength of twelve level-1 characters; it now has values that
vary.

**4. NPCs are distinguishable, mechanism unknown.** **Eight** record bytes --
`0x0B7`, `0x0B9`, `0x0BA`, `0x0D3`, `0x0D4`, `0x0E4`, `0x0E5`, `0x0FB` -- read
`$FF` in all five NPCs and `$00` in all twenty player characters we have.
Whether one is a flag and the rest follow, or all eight are "not applicable"
sentinels, is unproven.

*Corrected later.* This was first written up as **ten** bytes, adding
`0x0E6`-`0x0E7`. Those do read `$FF FF` in an NPC, but they are a different
field: every player character has a non-zero, high-entropy value there -- MALCYON
`$E6C3`, BRUTUS `$57D1`, ZARRADA `$5814` -- so they are not a `$00`/`$FF` pair
and reading them as part of the marker was wrong. The error surfaced when the
editor's consistency check fired on a party of ordinary player characters.

**A near-miss, recorded so it is not found again.** Roster byte `+0x0C` is `$80`
for all five NPCs and `$00` for all three player characters here, which looks
exactly like an NPC flag. It is not: MALCYON is a player character whose `+0x0C`
went `$00` to `$80` over a shopping trip.

**Not the export-delta experiment.** The disk also carries three exported `.chr`
files, which looked like a free run at that planned experiment. It is not one --
the exports are the pre-hack originals, so a diff conflates "export versus party
context" with "before versus after an editor". The planned experiment still needs
a clean pair.

---

## The 1989 BASIC editor
**Source.** `poolce.d64` -- "POR EDITOR V5" by Steve Krulewitz, edited by Philipp
Garcia, from CSDb release 68820. A listable C64 BASIC program plus a SEQ
documentation file. It edits an **exported** character at `$6B00`, which is our
`.chr` format exactly.

**Why it is worth more than a normal specimen.** It is a second, independent
reading of the same bytes by someone who had the game and not our tools. Where it
agrees, that is corroboration; where its author gave up, that is a landmark.

**Result.**

* **Every offset it pokes matches ours.** Name at `+0`, STR at `+20`,
  exceptional strength at `+26`, race `+114`, class `+115`, age `+116` (16-bit),
  hit points `+118`, level `+160`, experience `+232` (24-bit), and the seven money
  fields at `+187` through `+199`. The record runs `$6B00`-`$6D44`, 580 bytes.
* **It settles level** at `0x0A0`, which it labels and pokes as LEVEL.
* **It completes the multi-class enumeration** for `char_class`, and agrees with
  all four codes we had already derived from the bitmask at `0x0EB`.
* **Its author never found AC or THAC0**, and reports that hit point changes do
  not appear until you pay for healing at a temple. Both follow from our layout:
  an exported `.chr` is the record alone, and AC and current hit points live in
  `SAVEDGAME1`. He also noticed that setting DEX to 255 moves AC -- consistent
  with AC being recomputed on import while never being recomputed from an ability
  change mid-game.
* **It carries the item name table as BASIC DATA** -- 255 entries, the same table
  and the same order as `ITEMNAMES` on the game disk, hand-copied off the screen
  and full of typos (`GUSARME` for `GUISARME`, `JAVILIN` for `JAVELIN`). Ours is
  parsed from the disk and is the one to trust, but the indices line up, which
  independently validates our parser and our index base.
* **It carries 162 complete 16-byte item records**, including magic items we have
  never seen in play. Its plain `BANDED MAIL` record is byte-for-byte identical to
  the one in our own `PORSAVE2.D64` except for the readied bit, so these are
  genuine specimens of the real format.

**Two fixes to `por/items.py` came straight out of those 162 records:**

* **Cost is 16-bit** (`+11` and `+12`), not one byte. Every price then matches the
  AD&D 1st edition tables -- banded mail 90 gp, bracers of AC 3 21000 gp, cloak of
  displacement 17500 gp. Nothing we had bought in game cost over 255 gp, so the
  high byte had never been anything but zero.
* **An item name is up to three words**, not two: byte `+3` noun, `+2` qualifier,
  `+1` suffix. `CLOAK` `OF` `DISPLACEMENT`; `BANDED` `MAIL` `+1`; `BROAD SWORD`
  `-2` `CURSED`. Byte `+1` is zero for every mundane item, which is why two words
  had been enough for everything bought in a shop.

Byte `+4` is the magic bonus, signed -- `1` for banded mail +1, `254` for a cursed
-2 broad sword, `7` for bracers of AC 3 (10 - 3). Byte `+0` is a category code
that is not a name index; it is still unread.

---

## THAC0, next door to armour class
**Hypothesis.** The character sheet prints THAC0 and AC side by side, and AC
turned out to be roster byte `+0x0F` stored as `60 - AC`. The `SAVEDGAME1`
roster block is where the game keeps derived combat numbers, so THAC0 should be
in it too -- plausibly adjacent, plausibly in the same encoding.

**Method.** Compute each character's AD&D 1st edition THAC0 from class, level
and Strength, and compare against `60 -` each unread roster byte. No emulator.

**Result. CONFIRMED as far as reading goes: `+0x0E`, stored as `60 - THAC0`.**

On Donald's six-character party before anything was readied, all six match
exactly -- 21 for the magic-user and the magic-user/thief, 20 for the plain
fighter, 18 for the three fighters with exceptional Strength. Getting the two
21s right matters: a wrong hypothesis that assumed "20 at level 1" would have
missed both.

On the eight advanced characters of `npc_party.d64` three match the table
exactly and five read *better* by 2 or 3, which is what readied magic weapons
should do. Nothing, anywhere, reads worse than the table predicts. So `+0x0E` is
the **current** THAC0, adjustments included, not a base value.

**One thing it does not explain.** MALCYON's byte improves from 21 to 20 over
the shopping trip, and all he bought was darts. At DEX 16 a readied dart should
be worth nothing. Either the game gives darts a bonus, or something else moved
at the same time.

**Consequence.** Both numbers on the sheet's combat line are now readable, and
the `60 - x` encoding is a pattern rather than a one-off -- worth trying against
any remaining roster byte that ought to hold a small number. Damage is still not
found. Neither byte has been written back and confirmed in game, so both stay
PROBABLE for the purpose that matters.

---

## What Gold Box Explorer gave us
**Source.** `github.com/bsimser/Gold-Box-Explorer`, a C# viewer for the DOS Gold
Box file formats. Its plugins are all **FRUA** — Forgotten Realms Unlimited
Adventures, a later DOS product — so none of its offsets apply to us and its
name table is a *different* table in a different order. It was still worth
reading, for one structural idea.

**The idea.** `FruaItemFile.cs` reads items from **two** files. `ITEM.DAT` holds
the per-item record; each one carries a `Pointer`, and that pointer indexes
`ITEMS.DAT`, a table of item **types** holding location, hands, damage vs large,
rate of fire, protection, weapon class, damage vs medium, range, class usage and
missile type.

That is exactly the shape of the thing we could not explain. Our 16-byte item
record has an unread byte `+0` which is not a name index, and `POOL1.D64` ships a
file called `ITEMS` that is **2048 bytes — 128 records of 16 bytes**.

**Result. CONFIRMED. `+0` is an index into `ITEMS`, and the field order is
FRUA's.** Every weapon decodes to its exact AD&D 1st edition damage:

| Item | vs large | vs medium | AD&D |
|---|---|---|---|
| dagger | 1d3 | 1d4 | 1d4 / 1d3 |
| dart | 1d2 | 1d3 | 1d3 / 1d2 |
| long sword | 1d12 | 1d8 | 1d8 / 1d12 |
| short sword | 1d8 | 1d6 | 1d6 / 1d8 |
| bastard sword | 2d8 | 2d4 | 2d4 / 2d8 |
| two-handed sword | 3d6 | 1d10 | 1d10 / 3d6 |
| mace | 1d6 | 1d6+1 | 1d6+1 / 1d6 |
| sling | 1d6+1 | 1d4+1 | 1d4+1 / 1d6+1 |

**This closes damage**, which stood on the wanted list. `DAMAGE 1D3` on MALCYON's
character sheet is his readied dart's damage-vs-medium, read from this table.

Two more fields fall out, and both are checkable against rules rather than
against a single specimen:

* **Byte `+13` is a class-usage bitmask**, using the same bits as `class_bits`
  (magic-user 1, cleric 2, thief 4, fighter 8). Magic-users are permitted the
  dagger and the dart and nothing else; leather armour permits cleric, thief and
  fighter but **not** magic-user; banded and plate permit cleric and fighter but
  **not** thief. Those are the AD&D restrictions exactly, and they are not the
  sort of thing a wrong reading produces by accident.
* **Byte `+6` is protection.** Body armour reads `$B0` in the high nibble with
  `12 - AC` in the low one -- leather 4 (AC 8), banded 8 (AC 4), plate 9 (AC 3).
  A shield reads `$80` with the AC bonus in the low nibble: 1. That also ties
  back to roster byte `+0x10`, which is `46 +` this nibble.

  One oddity: chain mail reads the same protection as banded, where AD&D makes
  chain AC 5 and banded AC 4. Either the game simplified, or the encoding is not
  exactly `12 - AC`.

**What it did not give us.** Its `NameParts` table is FRUA's own vocabulary and
disagrees with Pool of Radiance's in both content and order -- it drops the
obscure polearms entirely. Do not use it as an item list. It does independently
confirm the *shape*, though: `FruaItem` is constructed from three name codes
concatenated in order, which is the three-word naming we had already worked out.

---

## The item name table has gaps
**Found while building `docs/85-item-tables.md`.** `por/items.py` read
`ITEMNAMES` by walking the strings in order and numbering them as it went. That
is wrong.

`ITEMNAMES` opens with a 512-byte pointer table: 256 **absolute addresses**,
stored as 256 low bytes followed by 256 high bytes. Entry 1 points at `$7101`,
which is precisely where `docs/40-memory-map.md` had recorded "weapon names" in
a running game -- the two observations were the same table all along.

**Three indices have no name: 62, 63 and 168.** A sequential reader closes those
gaps, so every name from 64 up was shifted by one, and everything above 168 by
three. The failure is silent and produces *plausible* results -- index 66 read
`STAVE` instead of `RING` -- which is the worst kind. It went unnoticed because
every item in Donald's own party indexes below 62.

It also means some of the garbled item names blamed on `npc_party.d64` being
editor-hacked were our own bug. The disk is still hacked; we were also wrong.

Fixed by reading through the pointer table. `load_item_names` now returns a
**1-based** mapping keyed by the value an item record actually stores, rather
than a 0-based one the caller had to adjust. Pinned by
`tests/test_items.py::test_name_table_has_gaps`.

---

## One point of damage, and three memorised spells
**Method.** Donald let LADY KATHERINE take a single point of damage, had ROLAND
memorise Cure Light Wounds twice and Bless, and MALCYON and LADY KATHERINE each
memorise Sleep, then saved to `PORSAVE4.D64`. Two long-standing questions in one
save.

**Result 1: current hit points are confirmed.** LADY KATHERINE's `hp_max` is 5
and her roster byte `+0x19` reads 4. Every other character still has the two
equal. This is the first specimen in the project where a current total differs
from a maximum, and it settles `+0x19` beyond the circumstantial. It also leaves
the *record's* `0x119` still unresolved: that byte only exists in an exported
`.chr`, and no wounded character has been exported.

**Result 2: the memorised spell list is confirmed, with names.** The diff
against the previous save is exactly three characters and five bytes:

    MALCYON         0x020        0 -> 21
    LADY KATHERINE  0x020        0 -> 21
    ROLAND          0x020-0x022  0 -> 3, 3, 1

Against the game's own `SPELLN00` table: 21 is SLEEP, 3 is CURE LIGHT WOUNDS,
1 is BLESS. Both mages memorised Sleep and both stored the same id, which is the
check that the ids are global rather than per-character.

**Result 3, unplanned: the per-level counts are not the list length.** The roster
counts at `+0x03`-`+0x05` did **not** move -- they still read `0/0/0` for all
three casters. In `npc_party.d64` the number of ids equals the sum of those
counts for all eight characters, which is what first tied the two together. That
identity is now known to be conditional. The difference between the saves is
**rest**: Donald memorised and did not rest. So `0x020` is plausibly what has
been *chosen* and the roster counts what is currently *castable*. Consistent with
both saves; not yet proven by watching one character across a rest.

**Everything else that moved** was the earlier thirteen-field edit still present
in this save, one platinum on MAGNUS, twenty bytes of party header at
`$49C0`-`$4A07`, and a large scatter through `SAVEDGAME1` above `$86B4` -- all of
which is still unread.

---

## The spell name table
**Result. SOLVED: `SPELLN00`, and it is the same trick as `ITEMNAMES` with one
extra wrinkle.** The file is on every game disk. Its PRG load address (`$2710`)
is a scratch buffer and tells you nothing; the payload is 128 low bytes, then
128 high bytes, forming absolute addresses of the strings as they sit when the
overlay is resident at `$B000`.

**The wrinkle: the strings overlap.** `CURE LIGHT WOUNDS` and `CAUSE LIGHT
WOUNDS` share a single copy of ` LIGHT WOUNDS`, so a reader that splits the text
on NULs in order sees one run of nonsense. Following the pointers is not an
optimisation here, it is the only thing that works. (The same discipline had
already been forced on `ITEMNAMES` for a different reason -- gaps.)

**The ids are structured.** The table runs cleric level 1, magic-user level 1,
cleric level 2, and so on, each group alphabetical with a reversed spell
following the one it reverses:

| Group | Ids |
|---|---|
| cleric 1 | 1-8 |
| magic-user 1 | 9-21 |
| cleric 2 | 22-28 |
| magic-user 2 | 29-35 |
| cleric 3 | 36-44 |
| magic-user 3 | 45-55 |

Every id ever observed in a save falls in the group its caster's class predicts,
including the four casters of `npc_party.d64` whose ids were recorded long before
any name was known. Id 56 is RESTORATION, above anything the game grants a
player, so presumably the temple's.

**From 57 the table stops being spells** and continues with combat message
fragments -- `IS CHARMED`, `AND MISSES...`, `POINTS OF DAMAGE`. Same mechanism,
different meaning. `wish` refuses to write an id above 56 into a spell list.

Full table in [the spell table](86-spell-table.md); reader in `por/spells.py`.

---

## The rest of the item record
**Method.** Group the 1989 editor's 162 item records by kind, then check the
same offsets against the game's own `ITEMFILE*` shop and encounter lists (354
records across the eight disks) and against the magic items in
`npc_party.d64`. No emulator.

**Result 1. CONFIRMED: on a scroll, `+13`, `+14` and `+15` are up to three
spell ids.** This is unambiguous, because the item's own name says how many it
should have and the ids decode through the spell table found earlier the same
day:

| Item | `+13`,`+14`,`+15` | Decodes as |
|---|---|---|
| CLERICAL SCROLL WITH 3 SPELLS | 36, 40, 42 | animate dead, cause disease, prayer -- all cleric 3 |
| CLERICAL SCROLL WITH 3 SPELLS | 27, 25, 1 | snake charm, silence, bless -- all cleric |
| MU SCROLL WITH 3 SPELLS | 47, 33, 34 | fireball, ray of enfeeblement, stinking cloud -- all magic-user |
| MU SCROLL WITH 1 SPELL | 49, 0, 0 | hold person -- one spell, two zeroes |
| CLERICAL SCROLL WITH 2 SPELLS | 36, 37, 0 | animate dead, cure blindness |

Every clerical scroll holds only cleric ids and every magic-user scroll only
arcane ones, across every scroll in the game data. Nothing about that can be
coincidence.

**Result 2. PROBABLE: on a wand, `+13` is charges and `+14` identifies the
wand.** Four copies of WAND OF MAGIC MISSILES across the game data read 20, 15,
3 and 38 in `+13` while `+14` stays 88 on every one. Varying-per-copy with a
constant type code is what charges and an effect code look like.

**A caution about the 1989 editor here.** *Its* wands all read exactly 100 in
`+13`, where the game's own data never does. Its author's documentation calls
the field "charges", so 100 looks like a value he invented for a full wand
rather than one he observed. Take his labels seriously and his *numbers* with
suspicion -- the opposite of the advice that applied to his offsets.

**Result 3. PROBABLE: `+7` bit 7 marks a cursed item.** Set on both cursed items
in the editor's list -- BROAD SWORD -2 CURSED and CURSED NECKLACE -- and on
nothing else among 162. No cursed item has ever appeared in one of our own
saves, so this rests entirely on his data.

**Result 4. `+15` bit 7 is set on permanent magic items** -- rings, cloaks,
gauntlets, magic swords -- and clear on everything with charges. GUESS: it may
separate "does something continuously" from "is used up". Note this conflicts
with `+15` also being a scroll's third spell id, so the two readings cannot both
be unconditional; the game presumably switches on the item type at `+0`.

**Still unread.** `+5` is zero on all 162 editor records and every game record
except one, CURSED NECKLACE, where it is 251. `+6` below its readied bit is zero
throughout the editor's list but reads 4 and 6 on two items in `npc_party.d64`,
which is a hacked disk and so proves little.

---

## The roster block, and what it is not
**Method.** The `PORSAVE`/`PORSAVE2` pair is a controlled before/after: the same
six characters, nothing readied, then armed and armoured. Compare every unread
roster byte across it and against `npc_party.d64`.

**Result: `+0x17` is the damage bonus.** Strength bonus plus the readied
weapon's own, matching the AD&D 1st edition table on all twelve readings:

| Character | Strength | Weapon | Stored |
|---|---|---|---|
| MALCYON | 15 | dart | 0 |
| LADY KATHERINE | 16 | short sword | 1 |
| ROLAND | 15 | **mace (1d6+1)** | **1** |
| SILAS | 18/81 | long sword | 4 |
| MAGNUS | 18/80 | long sword | 4 |
| BRUTUS | 18/98 | long sword | 5 |

ROLAND is the whole argument. He is the only character whose byte changed
between the two saves, 0 to 1, and his strength did not move -- he readied a
mace, which is the one weapon in the party with a damage bonus of its own. A
reading based on strength alone would have called that a contradiction.

**That completes the character sheet's combat line.** AC at `+0x0F`, THAC0 at
`+0x0E`, damage dice from the item type table, damage bonus at `+0x17`.

**Two weaker findings.** `+0x11` is 1 exactly when armour has cut the movement
rate -- banded mail yes, leather no. `+0x15` is 2 with nothing readied and rises
by 1 for a weapon, 2 for a shield and 3 for body armour across all six
characters; what it counts is anyone's guess.

**What the block is not.** Encumbrance is computable from the inventory and runs
0 to 129 lb across the specimens; **no byte tracks it**. `+0x00` and `+0x13` are
1 in every occupied block on every disk -- structural markers, not data. `+0x1C`
and `+0x1E` are zero in all of Donald's saves and non-zero only on the
editor-hacked disk, so nothing can be concluded from them.

---

## Racial traits: a strong lead, not an answer
**Method.** Group nineteen characters from three unrelated saves by race, and
look for bytes constant within a race and different between races -- the method
that has repeatedly beaten before/after diffing on this project.

**Result: `0x0AD` is non-zero only for elves and half-elves.**

| Race | Characters | `0x0AD` |
|---|---|---|
| elf | MALCYON, SHARA THE GRAY, LARA SPELLSWORD, XAVIER | **107** |
| half-elf | LADY KATHERINE, TANARAKIS | **124** |
| dwarf | MAGNUS, HOGARTH, GRON | 0 |
| human | ten characters | 0 |

Elves and half-elves are exactly the races AD&D gives resistance to sleep and
charm and secret-door detection, so the shape is right.

**The class confound is ruled out**, which matters, because this project has
already been caught once by a byte that tracked class while looking like it
tracked something else. GENHEERIS is a **human magic-user** and reads 0 where
MALCYON, an elf magic-user, reads 107. The four elves span three different class
combinations and all read 107; the two half-elves have different classes and both
read 124.

**What it is not known to be.** 107 and 124 are not the AD&D resistance
percentages (90 and 30). As bitmasks they are `0110 1011` and `0111 1100`,
sharing three bits -- suggestive of a trait mask, and no more than suggestive.

**A second, weaker lead: `0x099` is 0 for all three dwarves and 1 for everyone
else.** It sits immediately before the saving-throw block, and dwarves are the
race with a constitution-scaled saving-throw bonus.

**What would settle it.** A gnome, a halfling or a half-orc -- none of the twenty
characters we hold is any of those. Failing that, the experiment Donald already
ran on the DOS version: set a trait, change the race, and see which byte keeps
the trait.

---

## Monsters are characters
**Result. The monster data is 117 files, `MON00` to `MON7C`, one monster each,
480 bytes loading at `$6400` -- and they use the character record layout.**

`MON04` opens with `ORC` in a 20-byte NUL-padded name field, then 10, 6, 10, 10,
10, 10 at `0x014`-`0x019`: six ability scores with the low intelligence an orc
should have. `char_class` is 2 (fighter), `age` 30, `hp_max` 5. Every field lands
where `por/layout.py` already says it should.

That explains something already in the docs and never accounted for: the game's
race table ends `HUMAN=7 MONSTER=8`. Monsters are characters with race 8.

**The best confirmation is `MON21`, which is `MACE`** -- a named boss rather than
a generic creature. Race 6 (half-orc), 25 hit points, and a memorised spell list
at `0x020` reading 2, 1, 1, 4, 4, 23, 23, 23, 23, 23, 36, 42. Through the spell
table found the same day that is curse, bless twice, cause light wounds twice,
hold person five times, animate dead and prayer -- **every one a cleric spell**,
for a character the game presents as an evil cleric. Two independent decodes
agreeing on data neither was derived from.

**And it recovered a field that had been written off.** Monsters put 41 in
`0x071`, and `60 - 41` is 19 -- an orc's THAC0. Checking that against the party:

| Source | Characters | `60 - 0x071` vs the AD&D table |
|---|---|---|
| PORSAVE2 | 6 | all match |
| POOL1 sample | 6 | all match |
| npc_party | 8 | 5 match, 3 differ |

Seventeen of twenty, with every miss on the editor-hacked disk where nothing
derived can be trusted. **`0x071` is base THAC0**, stored as `60 - value`, the
same encoding the roster uses for the current value at `+0x0E`.

It was retired earlier as "not THAC0, because MALCYON's sheet shows 20 where the
byte reads 39". That reasoning was wrong in an instructive way: 39 is `60 - 21`,
MALCYON's base as a level-1 magic-user, and the 20 on screen is his *current*
THAC0 after readying a dart. Base and current live in different files, which is
exactly the twin pattern `docs/60-goldbox-field-checklist.md` warned about before
any of this was decoded.

**Not decoded.** Each monster file is 480 bytes and only about 100 are non-zero,
with a long run of `$FF` from `0x080`. Armour class, hit dice, attack routine and
experience value have not been located; `0x01B` holds 20 for an orc, 24 for a
goblin guard and 28 for a goblin leader and is the obvious experience candidate.
None of the files is compressed.

---

## The spellbook, and a hypothesis that had to go
**Prompted by Donald**, who pointed out that the editor should show what spells a
character *knows*, not only what they have memorised -- and, separately, that he
had **rested** before saving, which demolished the explanation the previous
entry had reached for.

**Result 1. CONFIRMED: `0x078`-`0x07E` is the spellbook.** Seven bytes, a
bitmask indexed by spell id: bit `id & 7` of byte `0x078 + (id >> 3)`.

| Character | Class and level | Knows |
|---|---|---|
| MALCYON | magic-user 1 | detect magic, read magic, shield, sleep |
| ROLAND | cleric 1 | all eight cleric level-1 spells |
| XAVIER | magic-user 6 | 20 spells, all magic-user |
| SIMON | cleric 6 | all 24 cleric spells of levels 1-3 |

Two things make this unarguable. **Clerics know everything and magic-users know
a subset** -- exactly how AD&D 1st edition works, and not something a wrong bit
alignment would produce. And **no cleric has a magic-user id set and no
magic-user has a cleric one**, across every caster we hold, which the spell
table's disjoint id ranges make a very sharp test.

MALCYON's four are the standard Pool of Radiance starting spellbook, and his
memorised spell -- sleep -- is one of them.

**Result 2. RETRACTED: roster `+0x03`-`+0x05` are not spell counts.** They
matched the memorised list length for all four casters on `npc_party.d64`, which
is why they were identified that way. Donald then memorised five spells across
three characters, rested, and saved: the roster page came out **byte-identical**
to the save before it, still reading `0/0/0`.

The previous entry explained that away as "memorised but not yet rested". He had
rested. The explanation was reached for in order to save the hypothesis, which is
the one job an explanation must not do. The bytes are back to unknown and `wish`
exports them as `unknown_03_05`.

**What this cost, and what it bought.** The wrong reading survived because four
characters agreed with it and no specimen contradicted it -- the same failure
mode as the `$400` slot stride, which six characters had agreed with. The rule
this project keeps relearning: *a hypothesis that sparse data agrees with has not
been tested.* Four is sparse.

**How many spells a character may memorise** is not stored anywhere found. It
follows from class, level and Wisdom, and matches on every caster: MALCYON and
LADY KATHERINE one apiece as level-1 magic-users, ROLAND three as a level-1
cleric with Wisdom 16. `por/spells.py` computes it.

---

## Four sweeps: the roster, item bytes, monsters and portraits
**The roster block is finished, and mostly by elimination.** Four bytes were
still non-zero anywhere: `+0x00` and `+0x13` read `1` in every occupied block on
every disk -- structural markers, not data -- and `+0x1C` and `+0x1E` are zero in
all twenty-four blocks across Donald's four saves and non-zero only on the
editor-hacked `npc_party.d64`. Nothing can be concluded from a hacked disk, so
the block is as mapped as our specimens allow. Encumbrance and status had already
been ruled out of it.

**CONFIRMED: `+6`'s low three bits are a hidden-name mask.** Each bit conceals
one name word until the item is identified -- bit 0 the noun at `+3`, bit 1 the
qualifier at `+2`, bit 2 the suffix at `+1`. Applying it to all 163 items on the
game disks produces exactly the names Pool of Radiance shows for unidentified
gear:

| Real name | Mask | Shows as |
|---|---|---|
| BANDED MAIL +1 | 4 | BANDED MAIL |
| LONG SWORD +1 | 6 | LONG SWORD |
| POTION OF HEALING | 6 | POTION |
| CLERICAL SCROLL WITH 2 SPELLS | 6 | CLERICAL SCROLL |
| RING OF FEATHER FALLING | 6 | RING |
| CURSED NECKLACE | 5 | NECKLACE |
| BATTLE AXE | 0 | BATTLE AXE |

CURSED NECKLACE is the one that makes it certain: mask 5 hides the *noun* and
the *suffix* and leaves the qualifier, so a cursed item presents as an innocuous
`NECKLACE`. No other reading of those bits produces that. 124 of the 163 items
are mundane and read 0, and the DOS field catalogue describes the same field --
"the hidden-name byte's low 3 bits control which of the three name components are
concealed until identified" -- which we had recorded and not connected.

Still unread after that: `+5`, which is 0 on 162 of 163 items and 251 on CURSED
NECKLACE alone.

**Monsters: armour class, hit dice and movement.** Monsters use the character
record layout, so the same offsets do the same jobs:

| Monster | `0x0E1` -> AC | Monster Manual | `0x0A0` hit dice | `0x09F` move |
|---|---|---|---|---|
| KOBOLD | 7 | 7 | 0 (1/2 HD) | 6 |
| ORC | 6 | 6 | 1 | 9 |
| SKELETON | 7 | 7 | 1 | 12 |
| HOBGOBLIN | 5 | 5 | 2 | 9 |
| GNOLL | 5 | 5 | 2 | 9 |
| ZOMBIE | 8 | 8 | 2 | 6 |
| OGRE | 5 | 5 | 5 (4+1 HD) | 9 |
| TROLL | 4 | 4 | 7 (6+6 HD) | 12 |

Armour class matches on all eight, hit dice on all eight, and **movement on all
eight** -- kobold 6, troll 12, zombie 6. `0x0A0` is the field we call "level" for
a character, which for a monster is its hit dice, and that is the same idea.

**And it found base armour class for characters.** `0x0E1` reads 10 in every
player character ever seen, which is why it looked like a constant: an
unarmoured human before dexterity is AC 10. Monsters have real values there
because their armour is intrinsic. Checking the export for the current value
turned up `0x10F`, which agrees exactly with the `SAVEDGAME1` roster for the
same character -- BRUTUS 9, MALCYON 8, LADY KATHERINE 8. Base and current again,
in two different places, for the fourth time.

**Portraits: half an answer.** The disks carry 41 `HEAD*` and 21 `BODY*` files,
numbered in hex. Export byte `0x10D` reads 8, 3 and 4 for BRUTUS, MALCYON and
LADY KATHERINE, and `BODY08`, `BODY03` and `BODY04` all exist -- a good
**body-index** candidate on three for three. The neighbouring `0x10E` reads 42,
39 and 39, and neither reading of those as a filename works: `HEAD2A` exists but
`HEAD27` does not, and taking the values as decimal gives `HEAD39` (which exists)
and `HEAD42` (which does not). So the head index is **not** found, and neither is
the icon large/small flag. Three characters is too few; a party with visibly
different portraits would settle it in one save.

---

## BRUTUS was never the anomaly

**Prompted by Donald**, who was about to go into the game and unready BRUTUS's
shield and banded mail to find out why his armour class was one point better
than the rules predicted. The desk check that should have come first answers it.

**All three fighters carry identical, non-magical gear.** SILAS, MAGNUS and
BRUTUS each have banded mail, a shield and a long sword, every one of them with
a `+0` bonus. So the difference was never equipment.

**The dexterity table is the answer, and it is not AD&D's.** Pool of Radiance
gives an armour-class bonus from **DEX 14**; the Players Handbook starts at 15.
`PORSAVE.D64` shows it directly, because nobody in it is wearing anything, so
armour class is 10 minus the dexterity adjustment and nothing else:

| DEX | 12 | 13 | 14 | 15 | 16 |
|---|---|---|---|---|---|
| stored armour class | 10 | 10 | **9** | 9 | 8 |
| AD&D 1st edition | 10 | 10 | **10** | 9 | 8 |

BRUTUS is the only character in twenty with DEX 14, which is why a table error
looked like a fact about him. With the boundary corrected, **every character in
every save comes out consistent**, and the only remaining discrepancy anywhere is
MALCYON's THAC0 improving by one when he readies darts.

**The lesson is about where the anomaly was.** For weeks the notes recorded
"BRUTUS is one point better than the rules predict" as a property of the save.
The save was right; the model was wrong. An anomaly in a comparison always has
two sides and the assumption was never checked, even though the check cost
nothing: it needed no emulator, no new save, and no experiment.

`0x0B8` is still unexplained. BRUTUS remains the only character whose copy went
0 to 1 when the party equipped, and it is now a loose end on its own rather than
a suspected cause of something that has turned out not to exist.

---

## Walking out of the inn

**Method.** Donald loaded `PORSAVE4.D64`, walked outside the inn, and saved to
`PORSAVE5.D64`. One action, nothing else.

**Result: six bytes moved, all of them in the `SAVEDGAME0` party header.**

| Address | Before | After |
|---|---|---|
| `$49C0` | 2 | 3 |
| `$49C2` | 3 | 0 |
| `$49C7` | 7 | 9 |
| `$49F0` | 3 | 2 |
| `$4A07` | 1 | 0 |
| `$4BC6` | `$00` | `$80` |

**And `SAVEDGAME1` is byte-identical.** That is the firmest thing here, and it is
a correction: the automapper design note had `SAVEDGAME1` as "the obvious
candidate" for map coordinates, on the reasoning that it is the other thing a
save contains. Walking does not touch it. **Position lives in the `SAVEDGAME0`
header.**

**Candidates, none confirmed.** `$49C0` rose by one and `$49F0` fell by one,
which is the shape a coordinate pair makes. Both sit as the first byte of a
`xx 0E` pair — `02 0E` and `03 0E` before, exchanged after — and 14 recurring
beside both is suggestive of a map dimension, or of two 16-bit values around
3586 moving in opposite directions. `$4BC6` setting bit 7 looks like a flag
rather than a number, and is a candidate for "the party is outdoors" or for a
first quest flag.

**Why this is not yet an answer.** Walking out of a building is a *transition*,
not a step: it can change position, facing, area and time all at once, and six
bytes is more than one action's worth of information. Nothing here distinguishes
a coordinate from a facing from a step counter.

**What settles it** is three saves and two short walks: save standing still,
walk exactly three steps in one direction and save, then three steps
perpendicular and save. A byte that moves by exactly 3 in the first leg and not
the second is one axis; the byte that does the reverse is the other. Anything
that moves in both is not a coordinate.

---

## Three steps north, three steps west: the party's position

**Method.** Donald took four saves, each one action apart:

| Save | Action |
|---|---|
| `PORSAVE6` | out of camp and back in, no movement (control) |
| `PORSAVE7` | three steps in the direction already faced |
| `PORSAVE8` | turned left to face west, then three steps |
| `PORSAVE9` | turned to face north, no movement |

**Result. SOLVED, and cleanly.** Every value falls out of one diff or another,
and the two legs of the walk cross-check each other:

| Address | Field |
|---|---|
| `$49C0` | **x** |
| `$49C1` | **y** — rises going *south*; north decreases it |
| `$49C2` | **facing**: 0 north, 1 east, 2 south, 3 west |
| `$49F0`, `$49F1` | the square occupied **before the last move** |
| `$49C7`-`$49C9` | a counter, three decimal digits least significant first |

**Why each is certain rather than likely.**

*x and y* isolate each other. Three steps north moved `$49C1` by exactly 3 and
left `$49C0` untouched; three steps west moved `$49C0` by exactly 3 and left
`$49C1` untouched. A counter that merely ticks would have moved in both legs.

*Facing* is confirmed twice over by a save with **no movement at all**. Turning
to north set `$49C2` to 0. Earlier, turning left from north set it to 3, and
`0 - 1 mod 4 = 3` is west, which is the direction he turned. Walking three steps
never changed it.

*The previous square* is one step behind the party along the direction last
moved, in every save. It is genuinely the previous *step*, not the previous
save: at `PORSAVE7` the party stands at (3,11) having walked three squares from
(3,14), and it reads (3,12).

*The counter* rises on everything -- 637, 639, 640, 644, 648, 649 -- and carried
from 9 to 0 with the next digit going 3 to 4, which is what makes it decimal
rather than binary. A turn costs 1. Units unknown, so it is recorded as a
counter and not as a clock.

**Two bytes are still unexplained**, and both moved only when the party left the
inn and never since: `$4A07` (1 to 0) and `$4BC6` (0 to `$80`). Indoors-versus-
outdoors is the obvious guess for a pair that behaves like that, and it is only
a guess.

**The character data is untouched throughout.** The `SAVEDGAME1` roster page is
byte-identical across all six saves. Walking changes the world, not the party.

---

## The tables enumerate more than the game implements

**Prompted by Donald**, who was about to make characters to fill gaps in the
specimen set and pointed out that two of the things asked for cannot be made:
paladin and ranger are reported to exist in the game data in an unfinished
state, and **half-orc is not on the character-creation menu at all**. He
wondered whether half-orc might be NPC-only.

**It is.** The 108 monster records use the character layout, so they can be read
for race and class like any character. Two are half-orcs, and both are named
NPCs: **MACE** (cleric) and **NORRIS THE GRAY** (fighter). Race 6 is real and
used; it is simply not offered to the player.

**Three class codes came free with that check.** The monster files are labelled
with names that state the class outright, which makes them ground truth:

| Code | Evidence |
|---|---|
| 6 | NPCs named `1ST LVL THIEF`, `6TH LVL THIEF`, `7TH LVL THIEF`, and `ROBBER` |
| 9 | `ENVOY` -- consistent with cleric/fighter/magic-user, though the name does not say so |
| 15 | `DRIDER`, and it is race **elf** -- consistent with fighter/magic-user/thief |

Code 6 in particular was an assumption until now: the field table asserted
`THIEF=6` from the Gold Box convention, and only 0, 2 and 5 had been checked
against saving-throw tables. Three NPCs with the word THIEF in their names
settle it.

**And four codes appear nowhere at all.** DRUID=1, PALADIN=3, RANGER=4 and
MONK=7 are absent from twenty player characters *and* from all 108 monster
records. That is consistent with Donald's report and extends it: whatever state
paladin and ranger were left in, no character in the shipped game uses those
codes, and druid and monk look the same.

**The pattern is worth stating on its own.** The game's tables enumerate more
than the game implements, and they do it twice over:

* the **race** table at `$3243` lists eight races; the creation menu offers six,
  and half-orc appears only on NPCs;
* the **class** menu list at `$3288` names CLERIC DRUID FIGHTER MAGIC-USER THIEF
  MONK, and two of those six are never instantiated by anything.

So a name in one of these tables is evidence about what the *format* supports,
not about what the *game* does. That matters for an editor, which can write a
race or class the game never produces. `wish` will happily write `race: monster`
today. Whether the game copes is untested.

**Still missing from every specimen we hold:** gnome and halfling. Neither
appears among the twenty player characters or the 108 monsters, and both are
creatable, which makes them the two most valuable characters anyone could make
for this project -- they are the only way to test whether `0x0AD` is a racial
trait mask.

---

## Four new characters, and the size flag

**Method.** Donald made NYX (gnome thief), DAX (halfling fighter/thief), ASTRID
(half-elf cleric/fighter) and DELILIA (half-elf cleric/fighter/magic-user), and
saved the roster as `PORSAVE10.D64`. It holds no `SAVEDGAME0` at all -- eight
**full 580-byte exports**, which is better, because a save slot stores only the
first 256 bytes.

**Result 1. SOLVED: `0x099` is the size flag** -- 1 for a medium character, 0 for
a small one. It is the **only** byte in the stored 256 that separates dwarves,
gnomes and halflings from humans, elves and half-elves, which are exactly the
AD&D size categories. Five small characters against fifteen medium.

This is the **icon large/small flag** that had been on the wanted list since the
combat icons were decoded, where it was recorded as "not among the 36 icon bytes,
so it lives elsewhere". It does.

Donald supplied what made it findable, and what had made it confusing: MAGNUS is
a dwarf and shows as small in game, but his icon does not *look* smaller. The
difference is the head -- a small character's body is the same size and its head
is smaller, so the icon reads as small without being smaller. Without that we
would have gone looking for a size in the icon bytes, where it is not.

**Result 2. `0x0AD` is not a racial-trait mask.** It reads 107 for elves and 124
for half-elves, and it was the leading candidate for a general trait field.
Gnomes and halflings read **0** -- and both races are rich in AD&D racial traits,
detecting slopes and listening at doors and saving-throw bonuses. Whatever
`0x0AD` is belongs to elves and half-elves specifically. Resistance to sleep and
charm is the trait those two share and the others lack, but 107 and 124 are not
the AD&D percentages (90 and 30), so that is a description of the pattern and not
an identification.

**Result 3. Thief skills are signed.** Our first two thieves. DAX reads 251 in
two of the eight, and 251 as a signed byte is **-5** -- which is exactly the
halfling's read-languages adjustment in AD&D. The layout had them as unsigned,
where a 251% skill is nonsense. They are `I8` now.

**Result 4. Two more class codes, confirmed on player characters.** ASTRID is
cleric/fighter and carries code **8**; DELILIA is cleric/fighter/magic-user and
carries code **9**. Both match the 1989 editor's multi-class table, which now
agrees with six independently obtained values and has never disagreed. Code 9
also matches the NPC `ENVOY` found in the monster files.

**Result 5, from a limitation Donald hit.** The game **refuses a seventh player
character**: six is the maximum, and the remaining two of the eight slots are for
NPCs only. That answers a question this knowledge base got wrong earlier, when
"up to five NPCs" was inferred from a single hacked save and withdrawn. The rule
is **at most six player characters and at most eight in total**, which fits
`npc_party.d64` exactly: three player characters and five NPCs.

**A note for later.** Curse of the Azure Bonds does offer paladins and rangers,
so class codes 3 and 4 are likely to be real there even though nothing in Pool
of Radiance uses them. Gold Box Companion converts a fighter into one. Worth
knowing if `wish` ever grows beyond this game; not worth doing now.

---

## A research sweep: what the new specimens settled

Four questions worked from the desk, using the eight full exports on
`PORSAVE10.D64` and the 108 monster records.

**The two class fields CAN disagree, and the bitmask is the one to trust.**
Across 105 characters, `char_class` and `class_bits` agree everywhere except
four monster records:

| NPC | code | bits |
|---|---|---|
| DWARVEN FIGHTER | 0 (cleric) | fighter |
| ENVOY | 9 | magic-user, fighter |
| DRIDER | 15 | magic-user, fighter |

`DWARVEN FIGHTER` is the telling one: its *name* says fighter, its bits say
fighter, and its code says cleric. Where they part company the bits match
reality. `DRIDER` is a drow, and fighter/magic-user is what a drow should be.

So the pair is **not** redundant, and `wish` forcing them into agreement imposes
a consistency the shipped game does not maintain. Every player character we hold
agrees, so the tool is right about player characters and cannot represent an NPC
the game itself ships.

**`0x0A0` is not a sum.** DELILIA is a three-class character at level 1 and reads
1, not 3; `ENVOY` is magic-user 6 / fighter 6 and reads 6, not 12; `DRIDER` is
7/7 and reads 7. That leaves "the maximum" or "the single class's level", which
coincide in every specimen. It is what `wish` already writes, so the risk flagged
earlier is smaller than it looked. Whether it is *current* level or *highest
level attained* still needs a drained character.

**`0x10E` is the current THAC0**, stored as `60 - THAC0`, immediately before the
current armour class at `0x10F`. Matches the AD&D table on all eleven exports.
Both exist only in an export, and both agree with the `SAVEDGAME1` roster for the
same character -- so an exported `.chr` carries both combat numbers after all.
That is worth recording, because the 1989 editor's author reported he could never
find either, and this is where they were.

**The item area in an export is at `0x120`, not `0x110`.** Sixteen records of
sixteen bytes, running to `0x21F` and ending exactly where the combat icon starts
at `0x220`. Found by searching BRUTUS's export for a known banded-mail record.
The `0x110` figure came from the 1989 editor, whose two item loops disagree with
each other by sixteen bytes -- a discrepancy
`docs/60-goldbox-field-checklist.md` originally flagged and which was later
"resolved" in the editor's favour. That resolution was wrong. Nothing in `wish`
was affected: it reads items out of saves, where the area is at `$5900`.

**Not settled.** `0x10D` reads 2, 3, 4 and 5 for ROLAND, SILAS, MAGNUS and
BRUTUS -- exactly the party slots they occupied -- and 8 for four characters
freshly made. Marching order is the obvious reading and the DOS catalogue has
such a field, but three older exports disagree with their own party order, so it
stays a candidate. The **portrait head index** is still not found; neither
`0x10D` nor `0x10E` is it, and the earlier note calling `0x10D` a good body-index
candidate was near-vacuous -- `BODY01` through `BODY09` all exist, so any small
number "lands".

---

## Monsters, `0x0B8`, and the noise floor in SAVEDGAME1

**Monster experience value: not in the record.** Scanning all 480 bytes of eight
monsters whose AD&D experience values are known -- kobold 7, orc 10, hobgoblin
20, zombie 20, gnoll 35, ogre 90, troll 350, skeleton 16 -- finds **no byte and
no 16-bit word** that matches on all eight. The record's own experience field at
`0x0E8` is zero for every monster. Gold Box games are known to compute a
creature's award from its hit dice and abilities, and this is consistent with
that: there is nothing to find.

Hit dice at `0x0A0`, armour class at `0x0E1` and movement at `0x09F` were already
confirmed. What is still unfound is the attack routine -- how many attacks and
for how much -- which is not in the item area either, because generic monsters
carry no items at all.

**Named NPCs are fully equipped characters; generic monsters are not.** ORC,
TROLL, OGRE carry nothing. KOBOLD carries a short sword. **MACE** carries chain
mail, a shield and a `MACE +1`; **NORRIS THE GRAY** carries chain mail, a shield
and a `LONG SWORD +1`. So the two half-orcs in the game are not just readable
characters, they are equipped ones, and they are a source of magic-item records
that never appear in a shop.

**`0x0B8` remains BRUTUS's alone.** Eight more characters, four of them made
from scratch, all read 0. Twenty-eight characters now, and BRUTUS is the only
one -- 0 before the party equipped, 1 after, and 1 in his roster export. Not
race, not class, not level, not equipment in any way that shows on anyone else.
Still unexplained.

**`SAVEDGAME1` past `$8400` is noisy, and that matters for planning.** Walking
out of the inn left it byte-identical. But every save taken **from camp** rewrites
about 96 bytes of it, spread the same way every time -- roughly 3 bytes in
`$8600`, 43 in `$8800`, 15 in `$8900`, 35 in `$8A00` -- whether the party walked
three steps, turned on the spot, or did nothing at all.

Changing by the same amount regardless of what happened is the signature of
volatile state: a random-number generator, or a scratch buffer that gets written
out incidentally. It is not what game progress looks like.

**Consequence for the quest-flag hunt.** Diffing that region will be noisy, and
the signal is more likely to be in the header, which is where position, facing
and the counter all turned out to live and which moved only six bytes for a
whole walk. It also means the two bytes left over from leaving the inn --
`$4A07` and `$4BC6` -- are better leads than they looked, because they came from
the quiet file.

---

## A losslessness bug, found by taking the NPCs seriously

**Prompted by Donald**, on reading that `char_class` and `class_bits` disagree
in four of the game's own NPC records: if the game ships records like that, an
editor that forces them into agreement cannot represent them.

It was worse than a limitation. Constructing a record with a fighter's bits and
a cleric's code -- the shape `DWARVEN FIGHTER` actually has -- and putting it
through **an export and import that changed nothing**:

    slot 2 ROLAND: char_class 0 -> 2 (kept in step with classes)
    slot 2 ROLAND: cleric level 1 -> 0

Two bytes rewritten by an import that edited nothing, and the disks no longer
byte-identical. That is a direct violation of the property the whole tool rests
on, and every test asserting losslessness passed, because no specimen we had was
in that state.

**Why it happened.** The reconciliation ran unconditionally: on every import,
`char_class` was recomputed from the bitmask, and the per-class level array was
zeroed for any class whose bit was clear. Both are the right thing to do when
somebody *edits* the classes and the wrong thing to do otherwise. The rule was
already understood elsewhere -- `level` uses "follow unless the file says
otherwise" -- and was simply not applied here.

**The fix.** Reconcile only when the classes actually changed. A record that
arrives disagreeing survives untouched. `class_code` is now its own field, so an
NPC-shaped record can be written deliberately, and doing so reports that it does
not match the classes rather than silently allowing it.

**What it says about the test suite.** The losslessness tests exercised real
saves, and every real save we hold has these fields in agreement, so the bug was
invisible to them. The test that catches it now *constructs* the state rather
than looking for it. Worth remembering for the other pairs: a round-trip test
over specimens can only prove losslessness for states the specimens contain.

---

## The portrait indices

**Result. SOLVED: `0x0FE` is the head and `0x0FF` the body**, each an index into
the `HEAD*` and `BODY*` files on the game disks, in hex -- `0x2D` is `HEAD2D`.

Found by scanning eleven full exports for bytes that vary and whose *every*
value names a file that exists. Two adjacent bytes do, one landing entirely in
the 41-strong HEAD set and the other entirely in the 21-strong BODY set. All
twenty-two values name real files.

That is not a small-numbers coincidence: the head ids in use include `$2D`,
`$43`, `$44` and `$67`, which are only meaningful if the set is right. Two more
checks agree -- BRUTUS carries the same pair on two unrelated disks, and the two
female half-elves, LADY KATHERINE and DELILIA, share a portrait.

The pair had been sitting in the notes as "`0x0FE`-`0x0FF`, vary per character
with no pattern identified yet". What made them findable was having eleven
exports rather than three; four of the eleven came from Donald's roster disk.

---

## The map data: found, not yet decoded

**Method.** Inventory every file on the eight disks by name stem, size and load
address, then look for the shape a set of maps would have.

**`GEO*` is the map data.** Twenty-nine files, **every one exactly 1024 bytes**,
all loading at `$0400`. Uniform size across twenty-nine files is what a set of
fixed-size maps looks like, and Pool of Radiance has roughly that many areas.
Nothing else on the disks has that shape: `SQRDATA` has three files of two
sizes, `WALLDEF` nineteen of nineteen sizes, `SECSET` eight of five, `SQRPACI`
three of three.

**It is not compressed.** 44% of the bytes are zero and only 85 distinct values
appear. The project's notes warn that game data may be ByteKiller-compressed;
these files are not.

**The row stride is 16 bytes.** Measured rather than guessed, by scoring how
often a byte equals the byte one stride earlier -- real two-dimensional data
peaks at its true width. `GEO04` and `GEO10` peak hard at 16 (0.47 against a
0.29 baseline); `GEO00` peaks at 32.

**There are walls in it.** Laid out 16 bytes to a row, rectangular structures
appear: horizontal runs of high-nibble `3` terminated at both ends, and vertical
columns of low-nibble `3` running down beside them. `GEO04` has two such
enclosures, spanning rows 4-15 and rows 19-31, with interior values drawn from a
small set (7, 8, 9) that is plainly not noise. Both nibbles carry data.

**What I could not establish**, and where a guess went wrong. The obvious reading
of 1024 bytes was four 16x16 maps, and the rendering seemed to break at rows 16,
32 and 48. It does not survive: the enclosures are not 16-row aligned -- one runs
rows 4 to 15 and the next 19 to 31 -- and the apparent block boundary was an
artefact of splitting the data where I expected a split. The squares-per-byte
question is likewise open: one byte per square with two attributes, or one nibble
per square, both fit what is visible.

**What would settle it in one step.** Match a `GEO` file to an area whose map we
can see. The party's position is now readable from any save, so: stand somewhere
distinctive in a known area, save, and walk a short known route along a wall. The
coordinates give the row and column, and the wall the party cannot walk through
gives a fixed point to align the file against. Without that anchor this is
pattern-matching; with it, it is arithmetic.

---

## The GEO files resist three more attacks

**Donald's suggestion** was that the walls might be the *blank* space -- that zero
means wall and non-zero means floor, the opposite of how it was first rendered --
and that comparing against the fan-made maps on GameFAQs might shake something
loose.

**The fan maps could not be fetched.** GameFAQs returns 403 to an automated
request; both the NES Phlan block maps and the PC slums walkthrough are behind
bot protection. Somebody reading them by eye could still do this comparison, and
it remains a good idea.

**So three tests were run on the data instead. All three came back negative.**

**1. Connectivity, with a null model.** A real map has one connected walkable
region. Measuring the largest connected region under each polarity looked
promising at first -- two files scored above 99% -- until the obvious confound
was controlled for: when 80% of a grid is one class it connects *by default*.
Against shuffled data of identical density, those two files drop to +0.003 and
+0.106, i.e. nothing. Most files score positively under **both** polarities,
which says only that the data has 2D structure, not which reading is right.

**2. The squares the party actually walked.** This is the strongest evidence we
own: seven squares -- (3,14) through (3,11), then (2,11), (1,11), (0,11) -- are
known walkable, from the controlled walk. Requiring all seven to be non-zero at
width 16 leaves exactly one file, `GEO02`. That is **not a result**: about 70% of
its bytes are non-zero, so seven hits have a 1-in-12 chance per file, and across
29 files roughly two should pass by luck. One did. Rendering `GEO02` with the
party's path marked shows no street, no corridor, nothing.

**3. Are they screens rather than grids?** 1024 bytes loading at `$0400` is
exactly C64 screen RAM, so the files could be *pictures* of maps drawn in the
game's own character set -- which would explain why no wall-bit reading works.
Testing that: a tiled picture repeats along its rows, so horizontal runs should
be long. They are not. Average run length is **1.3 to 1.9** at every candidate
width, against 4.5 for the one file that is mostly zeros. These are not screens.

**Where that leaves it.** `GEO` is 29 uniform, uncompressed, spatially structured
1024-byte files -- and that is *all* we can say. The earlier write-up called them
"the map data" with more confidence than the evidence carries: uniform sizing and
visible enclosures are suggestive, not probative, and three independent attempts
to read them as maps have now failed. Other candidates deserve a look before
settling: `WALLDEF` has nineteen files of nineteen different sizes, which is what
*variable-sized* maps would look like.

**Blind analysis has run out.** No amount of statistics on 1024 bytes will name a
square. The anchor experiment is the only way forward: stand somewhere
identifiable, save, walk a known route along a wall, and match the coordinates --
or read a fan map by eye and compare shapes.

---

## WALLDEF is graphics, and entropy puts GEO back in the frame

**`WALLDEF` is not the maps.** Nineteen files of nineteen different sizes looked
like variable-sized maps, which is why it was worth checking. It is wall
*graphics*, exactly as its name says: **80% of its bytes are C64 screen codes**
(`$40`-`$BF`), and it is built of short repeating blocks -- `63 63 63`,
`4C 4C 4C`, `76 75 74 71 72 73` -- which is a tile drawn as a run of characters,
not a floor plan. `WALLSET` beside it is the character shapes.

**`SQRDATA` and `SQRPACI` are not either.** Their names are the most map-like on
the disks, which is why they were checked next. 231 to 247 distinct byte values
and 2% zeros: high entropy, so compressed data or bitmap graphics.

**Then a measurement that settles which files are even candidates.** Shannon
entropy per byte, averaged by family:

| Family | Entropy | What it is |
|---|---|---|
| `SAVEDGAME`, `.chr` | 1.2-1.3 | decoded |
| `MON` | 1.67 | decoded |
| `ITEMS`, `ITEMFILE` | 2.2-2.5 | decoded |
| **`GEO`** | **3.36** | **undecoded** |
| `COMPIC`, `SPRITE`, `CHARSET` | 4.4-4.7 | graphics |
| `WALLDEF`, `SPELLN`, `HEAD` | 4.9-5.2 | graphics and tables |
| `SQRDATA`, `ECL`, `CAMP`, `COMBAT` | 6.2-6.9 | compressed or code |

**`GEO` has the lowest entropy of any undecoded family on the disks**, and it
sits in the same band as the record formats already decoded -- well below the
graphics and far below anything compressed.

**Which is a correction to the previous entry.** After three readings failed,
that entry backed away from calling `GEO` the map data and pointed at `WALLDEF`
instead. That was an over-correction. `WALLDEF` is graphics; `GEO` is the most
structured undecoded data on the eight disks, uncompressed, uniform, and 2D. The
failures were failures of *reading*, not evidence against the file.

**Four readings are now ruled out**, which is worth having written down so nobody
repeats them: walls as set bits in either polarity; a screen picture of tiles
(horizontal runs are 1.3-1.9, far too short); four bytes per square as N/E/S/W
(no assignment makes neighbouring squares agree about the wall between them --
the best scores 0.3 where a correct one would score near 1.0); and the seven
squares the party is known to have walked, which pick out one file at exactly the
rate chance predicts.

**It still needs an anchor.** Nothing statistical will name a square.

---

## The orc left behind at `$5500`

**Hypothesis.** `$5500`-`$58FF` is recorded in two places as "stays zero even
with a fully equipped party", and the same claim reached `por/savegame.py`. One
page between the character slots and the item area, said to be empty in every
save, is exactly the sort of claim that survives because nobody looked twice.

**Method.** Read the page out of every save disk we hold and both save fixtures
in the repo, and compare whatever is there against the game's own files. No
emulator.

**Result. It is not zero, and it holds one record in the character layout.**

| Save | `$5500` | Party experience |
|---|---|---|
| `PORSAVE` | zero | 0 |
| `PORSAVE2`-`PORSAVE9` | **`ORC`**, 79 non-zero bytes | 17 |
| `PORSAVE11` | zero | 45-86 |
| `party6_savedgame0.bin` | zero | before the fight |
| `party6_after_combat.bin` | **`ORC`**, identical to `PORSAVE2`'s | after the fight |
| `savedgame0.bin` (the original single-character save) | **`BRUTUS`**, byte-identical to slot 0 | - |

**The repo already contained the controlled before/after.** `party6_savedgame0`
and `party6_after_combat` are the same party either side of the orc fight that
gave us experience and silver, and the page fills in across it. Nothing had to
be arranged.

**The record is `MON04`.** Of the 256 bytes, 254 are byte-identical to the
`MON04` file on the game disk. Two differ, and both are informative:

| Offset | On disk | In the save |
|---|---|---|
| `0x0E2` `strength_index` | `$FF` | 10, the orc's Strength |
| `0x0FB` | `$FF` | 6 |

So the game does not copy a monster file verbatim: it fills `strength_index` in
from the ability score, which is one more corroboration that `0x0E2` is the
effective-strength field. `0x0FB` is one of the **eight NPC marker bytes**, and
it reads `$FF` on disk and 6 once loaded -- so a loaded monster is not evidence
about the marker, and the marker's `$FF` may be a "not applicable" fill that the
game overwrites for whatever the byte really means.

**What the page is.** One record, immediately after the eight character slots,
holding the last such record the game loaded: a copy of the party's only
character in the earliest save, the encountered monster after a fight. It is a
**staging page**, not storage -- `$5600`-`$58FF` is zero in every save we hold,
so it is one record wide, and `PORSAVE11` has it zero again after later fights,
so nothing accumulates there.

**Two corrections fall out.** The item area begins at `$5900`, not `$5500`, and
one line of `por/savegame.py` said otherwise. And "`$5500`-`$58FF` stays zero
even with a fully equipped party" was written from the shopping-trip diff --
where `PORSAVE2`, one of the two disks being compared, already had the orc in it.

**Not established.** Whether the game reads this page back on load, or simply
dumps `$4900`-`$64FF` and picks up whatever was resident. The second is much
more likely, given `SAVEDGAME0` is a verbatim memory image, and it would make
the page inert for an editor. Nothing here tests it.

---

## The spell counts, and how thin the retraction was

**Prompted by** finding `PORSAVE11.D64` on the disk shelf. No document mentioned
it; it is the latest save of Donald's party and nothing had read it.

**What produced it**, from Donald: the party went into the slums, fought a
couple of random encounters and came out wounded, **ROLAND the cleric died**,
they retreated to town, bought a cure light wounds for ROLAND at the church, and
saved outside it. Everything below is that one sequence, and it matters, because
**nobody memorised a spell and nobody changed a piece of equipment.**

**Hypothesis.** Roster bytes `+0x03`-`+0x05` were read as the number of spells
memorised at levels 1, 2 and 3, then **retracted** when they stayed `0/0/0` on a
save where three characters had spells memorised. Test the reading again against
every roster page we hold, per spell level rather than by sum, including the
save nobody had looked at.

**Method.** For each caster, split the memorised ids at record offset `0x020`
into spell levels through the `SPELLN00` groups, and compare with the three
bytes. No emulator.

**Result 1. Where the reading was checked before, it is stronger than recorded.**
On `npc_party.d64` it was reported that the *sum* of the three bytes equals the
number of ids. It is better than that: the **per-level breakdown matches
exactly**, eight characters for eight, including `GENHEERIS` at 3/2/0 and
`SIMON` at 5/5/3. A sum can agree by luck; three numbers agreeing cannot.

**Result 2. `PORSAVE11` agrees too, it is one of ours, and the count cannot
have come from anywhere else.**

| Character | ids at `0x020`, by level | `+0x03`-`+0x05` |
|---|---|---|
| ROLAND | 3 cleric level-1 spells | **3, 0, 0** |
| MALCYON | none | 0, 0, 0 |
| LADY KATHERINE | none | 0, 0, 0 |

Both magic-users have **empty** memorised lists here, where in every earlier save
they each held `SLEEP`. They cast them in the slums. ROLAND's list is unchanged
from `PORSAVE4` -- the same `[3, 3, 1]` -- and only the roster byte moved, from
0 to 3.

**That is the argument.** ROLAND memorised nothing between the two saves, so a 3
cannot have been counted from anything new. The only three of anything he has is
the three level-1 cleric spells already sitting at `0x020`. The byte was derived
from that list, at some point in this sequence, having read 0 while the same
list sat there for eight previous saves.

**Result 3. The contradicting evidence is one observation, not six.** The roster page is **byte-identical across `PORSAVE2`,
`PORSAVE3`, `PORSAVE4`, `PORSAVE5`, `PORSAVE6`, `PORSAVE7`, `PORSAVE8` and
`PORSAVE9`** -- eight saves spanning a shopping trip, memorising spells, resting,
a point of damage and two walks. The page was written once, when equipment
changed, and then not again until something in `PORSAVE11` rewrote it.

That is the caching behaviour armour class already demonstrates, and it changes
what the retraction means. The reading holds in **every save where the page was
actually written** and fails only where the page is stale. "They read 0/0/0 for a
party with five spells memorised" is true, and it is a statement about a cache
that had not been refreshed since before those spells were chosen.

**Status: still not restored, but only just.** The bytes stay `unknown_03_05`
in `wish` and UNKNOWN in the docs. Two things are missing. The three bytes have
never been seen holding **different** values from each other in one of our own
saves, so "level 1, level 2, level 3" rests on `npc_party.d64` alone; and what
triggers the refresh is not established, so "the cache was stale" is still an
explanation reached for rather than tested. What settles both at once is a save
taken straight after memorising, with a caster who memorises at **two different
spell levels**.

**The stale cache from the thirteen-field edit has refreshed, and it landed
exactly where `wish` predicted.** This is the largest thing in the save.
MALCYON's dexterity was edited 16 to 18 by that experiment; the game went on
showing `AC 8`, the value for his old score, through eight saves. Here it reads
**6** -- precisely what `por/derive.py` has been computing and reporting as
stale all along. His `strength_index` at `0x0E2` did the same thing, sitting at
15 (his pre-edit Strength) until this save and now reading 18.

Two consequences:

* **An edited ability score does reach the game's derived values**, so the
  editor's central premise holds for more than the fields the sheet prints
  directly. This is the second in-game confirmation `wish` has, after the
  thirteen-field edit, and the first for a value the game computes itself.
* **"Recomputed only when equipment changes" is too narrow.** No equipment
  changed here. What did happen is combat, a death, and a temple healing.

**And it explains the last outstanding discrepancy in the project.** MALCYON's
THAC0 improved from 21 to 20 across the shopping trip, where all he acquired was
darts, and no reading accounted for it. Here it improves again, 20 to 18, and
his readied weapon is still a dart. A **readied missile weapon picks up a
dexterity to-hit bonus** -- DEX 16 was worth 1 at the shopping trip, DEX 18 is
worth more now. Two points do not pin the table down, and the project has
already found that Pool of Radiance's dexterity tables are not the book's, so
the shape is left open. `por/derive.py` does not model it and now reports
MALCYON's THAC0 as stale when it is correct.

**Strength 18 with a percentile of 0 is plain 18, not 18/00.** The recomputed
`strength_index` reads **18** beside 21, 21 and 22 for the three fighters with
real exceptional rolls. The AD&D top band would have given 21 or 22. His damage
bonus stayed 0 throughout, where plain Strength 18 should be worth 2 -- either
the game gives no Strength damage to a thrown dart, or `+0x17` was not part of
the refresh.

**Three more observations from the same diff**, weaker than the above:

* **`+0x11` is not a boolean.** It was read as "1 when armour has cut the
  movement rate". MALCYON reads **3** here, wears nothing, and his movement is
  unchanged at 12.
* **Movement responds to encumbrance, not only to armour.** LADY KATHERINE goes
  from 18.7 lb to 122.2 lb of loot and her `+0x1B` falls 12 to 6; SILAS goes to
  230.5 lb and falls 9 to 6, with no change of armour in either case. The
  earlier finding stands as far as it went -- no byte in the block holds the
  carried *weight* -- but the movement byte plainly reacts to it.
* **`+0x0A` and `+0x0B` are non-zero for the first time**, 21 and 8, on ROLAND,
  the one character whose spell count moved. They sit in the run the roster
  section calls "zero in every specimen". Unexplained, and the obvious thing to
  watch on the next save with spells prepared.
* **`0x0EC` went 1 to 3 for MALCYON and moved for nobody else.** It is the byte
  recorded as "probably spell state rather than damage" because it rose for the
  two spellcasters after a fight. LADY KATHERINE cast a sleep here too and hers
  did not move, so whatever it counts, it is not simply spells cast.
* **ROLAND died and was healed, and his record barely noticed.** His slot shows
  silver spent and experience gained and nothing else; his current hit points,
  5 of 7, are in the roster. If the game records having died, or having been
  restored, it is not in the character record.

---

## PRINCESS FATIMA was never impossible

**Prompted by** a sweep of the race byte across the monster files, run for an
unrelated reason. `npc_party.d64` has been described throughout this knowledge
base as editor-hacked on two pieces of evidence, and the first of them is that
`PRINCESS FATIMA`'s race byte is **0**, "outside the 1-8 enumeration character
creation offers".

**Method.** Read the race byte from every distinct monster record on the eight
disks, then match each of `npc_party.d64`'s eight characters against that corpus
byte for byte. No emulator.

**Result 1. Race 0 is the game's own most common value.** Across the 135
distinct records in the 116 `MON*` files:

| Race byte | Records | What they are |
|---|---:|---|
| **0** | **75** | every generic creature — `ORC`, `TROLL`, `KOBOLD`, `WOLF` — and some humanoid NPCs (`ACOLYTE`, `1ST LVL CLERIC`) |
| 7 human | 54 | named and generic humans |
| 1 dwarf | 3 | |
| 2 elf | 1 | `DRIDER` |
| 6 half-orc | 2 | `MACE`, `NORRIS THE GRAY` |
| **8 monster** | **0** | **nothing, anywhere** |

So race 0 is not an impossible value. It is what three quarters of the game's
own character-layout records carry, and reads as "not applicable" rather than
"monster" — `ACOLYTE` and `1ST LVL CLERIC` are plainly people.

**Result 2. This corrects "monsters are characters with race 8".** That was an
inference from the race table ending `HUMAN=7 MONSTER=8`, and it was never
measured. Nothing in the game uses race 8. It is the **same pattern already
documented for classes**: the tables enumerate more than the game instantiates,
exactly as `DRUID`, `PALADIN`, `RANGER` and `MONK` are named and never used.

**Result 3. FATIMA is a shipped record.** She is `MON68`, present on POOL4 and
POOL8, and **252 of the 256 bytes** in her `npc_party.d64` slot are identical to
the file on the game disk — including all six ability scores and her experience,
10,200, which matches the shipped value exactly. Her race byte is the race the
game gave her.

**Result 4. All five "NPCs" are shipped records, and all three player characters
are not.**

| Character | `npc:` | In the monster files |
|---|---|---|
| GENHEERIS | true | `MON58`, 241 of 256 identical |
| MAD MAN | true | `MON19`, 240 of 256 |
| PRINCESS FATIMA | true | `MON68`, 252 of 256 |
| DIRTEN | true | `MON6B`, 230 of 256 |
| SKULLCRUSHER | true | `MON1B`, 249 of 256 |
| XAVIER, SIMON, GRON | false | not present |

Five for five and three for three. The `npc:` flag `wish` exports is reading
something real.

**Result 5, and it is the structural one. The eight "NPC marker" bytes are
`$FF` in the shipped file itself.** `0x0B7`, `0x0B9`, `0x0BA`, `0x0D3`, `0x0D4`,
`0x0E4`, `0x0E5` and `0x0FB` all read `$FF` in `MON58`, `MON19`, `MON68`,
`MON6B` and `MON1B` on the game disk, before any save is involved.

That changes what the marker *is*. It is not a flag the game sets when an NPC
joins the party: it is **residue of the `$FF` fill a shipped record carries**,
which survives being loaded into a slot. A player character, created by the
game, has zero there because nothing ever wrote `$FF`. Which would explain the
question nobody could answer — *which* of the eight the game tests — with
"possibly none of them".

The loading is only partial, and the pattern is the same one the orc at `$5500`
showed: of FATIMA's 33 differing bytes, 29 are `$FF` on disk and something else
in the save, including the whole `0x080`-`0x097` run and `strength_index` at
`0x0E2`, filled in from her Strength. The eight marker bytes are among the ones
*not* cleared. In the orc's case `0x0FB` alone was overwritten, leaving seven of
eight — so a record loaded for combat would trip the half-set-marker warning
`wish` implements, which is one more reason nothing should read `$5500`.

**Result 6. What survives as evidence that the disk was edited.** One thing, and
it is stronger than before:

* **MAD MAN's experience.** The shipped `MON19` holds **0**. His slot holds
  `$FFFFFF`. That cannot have come from play, and it is exactly what the 1989
  editor's "set XP to the max" writes.
* The other four NPCs' experience has risen **plausibly** from its shipped
  value — GENHEERIS 64,000 to 71,584, DIRTEN 19,800 to 57,803, SKULLCRUSHER
  11,200 to 11,687, FATIMA unchanged at 10,200 — and their ability scores match
  their shipped records byte for byte. Nobody edited them.
* The three characters with scores above 18 — XAVIER's DEX 19, GRON's CON 20 —
  are precisely the three **player** characters. That observation was withdrawn
  earlier because the game's own trainer alters scores, and it stays withdrawn;
  it is recorded here only because the split is so clean.

**What this costs.** Two claims have to go: that FATIMA's race is impossible,
and that monsters are race 8. What it buys is better: the disk's NPC records are
*genuine shipped data that has been played with*, so their structure is worth
more than "hacked, values worthless" allowed. The one hacked field we can point
at is MAD MAN's experience.

**Still unknown.** Whether the game ever *tests* an NPC marker byte, and
therefore whether `wish` writing `npc: true` on a player character does anything
at all. The `$FF`-fill reading predicts it does not, and predicts that the
game's own NPC-versus-PC decision is made somewhere we have not looked.

---

## SAVEDGAME1 past the roster is code, not state

**Question.** `$8400`–`$8AFF` — 1792 bytes, densely populated, never read. It was
the standing candidate for the journal, the quest flags and the explored-squares
bitmap an automapper needs. What is in it?

**Method.** Diff every specimen against every other: the nine save disks, plus
`npc_party.d64`, a foreign hacked playthrough with a different party at levels
4–8 somewhere else entirely in the game.

**Result. CONFIRMED — none of it is save data.**

| Range | Size | Contents |
|---|---|---|
| `$8400`–`$8753` | 852 | the on-disk file `ANIMATE00`, 6502 code: a 7-entry jump table (`4C xx 84`) then a VIC bitmap blitter |
| `$8754`–`$882F` | 220 | zero in all 15 specimens |
| `$8830`–`$8AFF` | 720 | C64 multicolour bitmap scratch |

Five things settle it, and the third alone would be enough:

1. Only **107 of 1792** bytes ever vary.
2. Those 107 form exactly **three classes**, and membership ignores chronology —
   `PORSAVE4`, `5` and `7` are one class, `PORSAVE6` and `8` another, interleaved
   in time. State does not behave like that.
3. `npc_party.d64` is **byte-identical** to `PORSAVE`, `2`, `3`, `6` and `8` over
   the whole region. A different party, at different levels, in a different part
   of the game, cannot share its state bytes with ours.
4. `$8400`–`$8753` matches `ANIMATE00` — which ships on every `POOL1`–`POOL8` and
   on `POOLBOOT` — in **829 of 852** bytes.
5. Of the 23 differences, 20 are identical in every save: loader-patched `$FF` /
   `$00` placeholders. The three that vary (`$86B4`, `$86B5`, `$86E4`) are
   **self-modified operands**. `$86D6` is `8D E4 86` — `STA $86E4` — rewriting
   the immediate of the `LDA #` at `$86E3`; `$86B4`/`$86B5` is a source pointer
   taking the values `$90C1`, `$8FBB` and `$8EBE`.

The loader fixups locate the graphics too: `$862B` is `LDA $8A55,Y : STA $D700,Y`
and `$865C` is `LDA $8B1D,X`, so the animator's data begins near `$8A55` and runs
**past `$8AFF`**. The dump caught its leading edge, nothing more.

The `EUD` / `PTTP` / `DQP` / `DPU` "short uppercase ASCII runs" that
`30-savegame-layout.md` flagged as a possible journal are `45 55 44` and
`50 54 54 50` — pixel patterns.

**What it costs us.** The explored-squares bitmap is not here, and neither is
anything else. Every remaining piece of world state has to fit in the header at
`$4900`–`$4BDF`, which is `$2E0` bytes. It is also possible the C64 version
simply does not save some of what we have been looking for.

**Where the state does move.** `PORSAVE4` → `PORSAVE11` spans a change of city
block, two random encounters, two sleep spells, damage, a heal from 0 hit points,
XP and loot. It moves **34 header bytes** and nothing in `SAVEDGAME1` but
animator scratch. Three of the 34 are six-wide per-character arrays, all zero
before the fights:

| Address | PORSAVE4 | PORSAVE11 |
|---|---|---|
| `$497A`–`$497F` | 0×6 | 15 19 14 11 9 8 |
| `$49BA`–`$49BF` | 0×6 | 4 3 4 5 4 5 |
| `$4BBA`–`$4BBF` | 0×6 | 1 1 1 1 1 1 |

None matches current hit points (`4 4 5 6 9 6`), armour class, THAC0 or movement,
so they are not a roster copy. GUESS: last-combat scratch — initiative, or which
characters took part. Also moved: `$49FD` 11→8, `$4A07` 1→0, `$4A80` 1→3,
`$4ABB` 1→3, `$4BC1` `$81`→`$E4`, `$4BC6` 0→`$80`, `$4BC7` `$E4`→`$81`, `$4BCA`
`$84`→`$80`, `$4BCE` `$AD`→`$96`, `$4BD7` `$84`→`$82`. `$4BC1` and `$4BC7`
**swapped values with each other**.

**One specimen is not what the notes assumed.** `PORSAVE10.D64` holds no
`SAVEDGAME0` and no `SAVEDGAME1` — it is eight standalone character files
(`NYX`, `DAX`, `ASTRID`, `DELILIA`, `BRUTUS`, `MAGNUS`, `SILAS`, `ROLAND`), and
`MALCYON` and `LADY KATHERINE` are not on it. It is a roster disk in the literal
sense and cannot be used for header diffs.

## Party strength is probably computed, not stored

**Claim under test.** The game manual says "From the moment the party begins its
adventures in Phlan, the clock is ticking. The longer it takes a party to
complete a mission, the harder it becomes." A slums walkthrough adds that
encounters scale on a *party strength* value and that killing the fortune teller
or entering the old rope guild maxes it.

**What the community actually says.** On the Gold Box forums, Null Null: Pool of
Radiance "scales the enemy size to party strength in many encounters", the
graveyard increments some encounters by missions completed, and the game does
**not** track time spent resting. Set encounters never change; only random ones
do. Players on `r/goldbox` add that the scaling responds to **ability scores**
as well as levels — editing a party to all-18 stats is reported to produce
bigger random encounters.

**Why that matters to us.** If party strength moves when you change a stat, it is
being **derived from the party on demand**, not stored and updated. That predicts
no party-strength byte exists in the save at all, and it is consistent with the
`SAVEDGAME1` result above: there is nowhere left for one but `$2E0` bytes of
header.

Status: the manual's time claim is **almost certainly false** — three independent
sources say encounter size tracks party strength, not elapsed time. The
fortune-teller experiment is still worth running, because it is a controlled
single action and a diff showing nothing is also informative, but expect nothing.

## GEO is solved: four planes, and a wall is not a barrier

**Five readings of `GEO` had failed.** All five made the same mistake, and it is
worth naming because it is a general one: they assumed **one field per edge**,
so that "there is a wall here" and "you cannot walk through here" were the same
bit. They are two independent fields, stored in different planes.

**The source. CONFIRMED.** `github.com/simeonpilgrim/coab` is a C#
reimplementation of *Curse of the Azure Bonds*, reversed from the DOS overlays.
`Classes/GeoBlock.cs` parses the block literally; `ovr031`, `ovr015` and `ovr029`
supply the semantics. The DOS block is `0x402` bytes — a two-byte prefix and
1024. **Our C64 files are that same 1024 with no prefix.** Dungeon Craft
(`github.com/grannypron/uaf`) corroborates the nibble scheme through FRUA's
later six-byte-per-cell format.

**The layout.** Four 256-byte planes over a 16×16 grid, indexed
`x + (y << 4)` — row-major, y southward, origin top-left.

| Plane | Offset | Content |
|---|---|---|
| 0 | `$000` | high nibble = wall art **north**, low nibble = **east** |
| 1 | `$100` | high nibble = **south**, low nibble = **west** |
| 2 | `$200` | square attributes; **bit 7 = roofed / indoor** |
| 3 | `$300` | passability, **two bits per direction**: N = bits 0-1, E = 2-3, S = 4-5, W = 6-7 |

A wall nibble of 0 means no wall; otherwise `wallset = (v-1)/5` and
`slice = (v-1)%5` index `WALLDEF` — which is why `WALLDEF` reads as graphics.
It is.

The passability field is **only consulted when the wall nibble is non-zero**:

| value | meaning |
|---|---|
| 0 | solid |
| 1 | passable — an opening or an open door |
| 2 | locked door |
| 3 | wizard-locked door |

**Verified against our own 29 files**, independently of the source:

| check | result |
|---|---|
| `$300` reciprocity between adjacent squares | **13793 / 13920 = 0.991** |
| best of all 24 nibble-to-direction permutations | the DOS assignment, 0.845 against 0.652 for the next |
| non-zero passability flags sitting on an edge that has wall art | 97.2% — they are doors |
| flag histogram | 26590 solid, 2962 open, 130 locked, 14 wizard-locked |
| plane `$200` | dominated by `$00` / `$80` |

The 0.991 reciprocity is the decisive number. The best any previous reading
reached was about 0.3, which is chance. And it needs no ground truth at all: the
east edge of a square is the west edge of its neighbour, so the file checks
itself.

`GEO1B` and `GEO04` render as 16×16 floor plans with complete outer boundary
walls and doors.

**Still open:** bits 0-6 of plane `$200`. In the DOS engine the ECL script VM
reads this plane as location `0x04`, which makes a per-square trigger or zone id
the obvious candidate. PROBABLE, not confirmed.

**A negative worth recording.** Nobody has written the 1988 `GEO` format down in
prose anywhere. It survives only as code, in `coab`. The FRUA "Hacking UA" board
at `ua.reonis.com` is dead — 404, including its indexed topic "GEO#.DAX format
(and all GB/FRUA formats)" — with no Wayback capture found. Gold Box Explorer
still has no `GEO` parser. Had the search stopped at documentation it would have
found nothing; it succeeded by reading somebody's reimplementation.

## Every Phlan city block, matched to its GEO file

**Question.** The format was decoded, but nothing said which of the 29 files was
which place. Without that a map is a floor plan of nowhere.

**Method.** Transcribe the nine city blocks off the fan-drawn NES map
(`work/maps/phlan-block-maps-nes.jpg`) into 16×16 wall grids, then score every
file against every block. The blocks' dimensions were **measured, not assumed**:
215 px at 13.4375 px per cell is 16 exactly, on both axes, for all nine.

**Result. CONFIRMED. Nine blocks, nine files, every one a mutual best match.**

| Block | File | φ | Disk | Next-best file |
|---|---|---|---|---|
| Slums | `GEO14` | 0.992 | POOL2 | 0.154 |
| Stojanow Gate | `GEO09` | 0.965 | POOL2 | 0.112 |
| Podol Plaza | `GEO12` | 0.924 | POOL1 | 0.316 |
| Sokol Keep | `GEO15` | 0.912 | POOL4 | 0.100 |
| Kuto's Well Catacombs | `GEO20` | 0.869 | POOL8 | 0.156 |
| Cadorna Textile House | `GEO02` | 0.818 | POOL4 | 0.155 |
| Mendor's Library | `GEO0F` | 0.768 | POOL2 | 0.199 |
| Kuto's Well | `GEO1D` | 0.762 | POOL8 | 0.108 |
| **New Phlan** | **`GEO00`** | **0.733** | POOL3 | 0.164 |

261 file × block comparisons, mean φ 0.046, standard deviation 0.169. The nine
hits span 0.733–0.992; **the highest score anywhere else in the matrix is
0.316**, so there is nothing in the gap. `CMP_GEO14_Slums.png` is wall-for-wall
identical to the drawn map.

The two lowest scores, New Phlan and Kuto's Well, are the two blocks with large
water bodies — which the fan map draws as outlined rectangles that transcribe as
walls with nothing to match in `GEO`. Not a decode fault.

**`$49C0` is x, `$49C1` is y.** Settled at last, and it matters beyond the maps:
`GEO00` read as `(x, y)` scores 0.737 and the transposed reading of the same
file scores 0.129. The index is `x + (y << 4)`.

**Two anchors inside `GEO00` confirm the alignment independently.** `PORSAVE4` at
`(2,14)` sits on the only run of roofed squares in the bottom rows, and the fan
map draws its inn glyph at exactly `(2,14)`. Square `(3,14)` — `PORSAVE5`, where
Donald "walked out of the inn" — carries a **door flag on its west edge**. That
is the inn door. Shifting the alignment by ±1 or ±2 in x or y drops the score
from 0.705 to 0.146 or less.

**The format was rediscovered independently, before the research landed.** An
exhaustive affine-layout search — `unit[base + x*sx + y*sy]` over
unit ∈ {byte, high nibble, low nibble}, `sx`, `sy` ∈ ±{1…128}, base 0–1023, all
29 files, **1,029,312 layouts** — scored against the fan-map transcription and
returned, in order: plane 0 high = north, plane 0 low = east, plane 1 high =
south, plane 1 low = west, `sx = +1`, `sy = +16`. That is the `coab` layout
exactly, recovered from a fan-drawn NES map and the C64 bytes alone, 18 standard
deviations above the population mean. The DOS source and our own data now agree
by two routes that share no evidence.

**Other findings from the same pass**

* **No area id exists in the save.** All of `$4900`–`$4BDF` was scanned for a
  byte constant across the six New Phlan saves and different elsewhere. There is
  none. The game does not record which `GEO` is loaded, so a save-file
  automapper has to infer the area from the walls around the party.
* **`$49C7`–`$49C9` is a turn counter**, incrementing once per step *and* once
  per turn in place: 640 → 644 over three steps plus one action, 648 → 649 over
  a single turn. It is not "three decimal digits" as previously recorded —
  `PORSAVE11` carries `$10` in the top byte.
* `GEO1C` is listed **twice** on `POOL6.D64`, byte-identical: 30 directory
  entries, 29 files. No two files are near-identical otherwise.
* Names run `GEO00`–`GEO20` in hex with `08`, `0B`, `0C` and `13` absent — 33
  slots, 29 present.
* **No header in the payload.** Zero bytes of common prefix; the planes land at
  `$000`/`$100`/`$200`/`$300` unadjusted. The DOS block's two-byte prefix is not
  in the C64 file.
* Plane `$200`, bits 0-4: **PROBABLE a 5-bit zone or trigger id**. Values are
  densely allocated from 1 in every file, and a square with a door edge carries
  a non-zero id 42.4% of the time against 17.2% without — 2.5× enrichment. Bit 6
  is used by six files and bit 5 by seven, almost all the same family, which is
  the dungeon-floor group.
* `GEO19` and `GEO1B` are PROBABLE dungeon mazes: 255-256 roofed squares, **zero**
  doors, wall set 1 only, largest connected region just 24%. `GEO10` and `GEO11`
  are PROBABLE wilderness: 0 and 13 roofed squares, with 222-336 walk-through
  edges.

.

## Planned, not yet run

Named, not numbered — the name is how they get referred to elsewhere in the docs.

- **The export delta.** Which of the 44 bytes that differ between an exported `.chr`
  and the same character in a save slot are party context, and which are real fields?
- **The checksum probe.** Largely answered by the thirteen-field edit, which the
  game accepted without complaint. A dedicated corruption probe would only add
  the case of a byte in a region nothing reads, and nothing depends on it.
- **The two class fields, separated.** `char_class` (`0x073`) and `class_bits`
  (`0x0EB`) encode the same classes twice, and agree in every player character
  we hold, so nothing yet says which one the game reads. (They *can* disagree:
  four of the game's own NPC records do.) Set them to disagree deliberately —
  give a fighter `class_bits` of fighter|cleric while leaving `0x073` at 2 — and
  try to ready a mace. `wish` keeps the two in step when you edit `classes:`, so
  the split has to be made by setting `class_code:` yourself. If the character can then wield
  clerical gear, `class_bits` is the field the game tests, and it is very likely
  what Gold Box Companion's four "can wield" checkboxes edit. If nothing changes,
  `0x073` is the real class and `0x0EB` is a cache. Either answer is worth having,
  and the experiment costs one edit. Use a throwaway party: this deliberately
  writes an inconsistent record.
- **The fortune teller in the slums.** A guide reports that talking to her
  raises the difficulty of random encounters in the slums. Split this in two,
  because the halves are wildly different in cost:
  * **Does the game record the conversation?** Save outside, talk to her, save
    again, diff. Decisive either way and takes minutes. A byte or a bit moving in
    the header or in `SAVEDGAME1` past `$8400` would be the **first quest flag
    we have located**, and those regions are otherwise entirely unread.
  * **Does it actually make encounters harder?** Much more expensive — random
    encounters need a lot of samples before a difficulty change is
    distinguishable from luck, and "harder" is not defined. Not worth attempting
    unless the first half finds something, and even then it is a claim about
    behaviour rather than about the file.
  Note the first half is worth running **whatever the guide got right**: it is a
  controlled single action, and a diff that shows nothing at all is also
  informative.
- **The trainer's ability-score change.** Save, alter exactly one ability score
  at the trainer, save again, diff. Cheap, isolated, and it answers two things
  at once: whether the game keeps a second copy of the score or a flag saying it
  was altered, and whether a forum rumour — that an original developer said
  altering scores carries negative effects in play — has anything behind it. If
  the diff shows only the one byte moving, the rumour has nowhere to live in the
  save file and can be set aside. If it shows more, we have found a field.
- **The racial-traits hunt.** Gold Box Companion on the DOS version exposes an editable
  trait list — and a trait survives a race change, so it is stored per character rather
  than derived from race. Find that field. `0x0AD` was the leading candidate and
  is ruled out: gnomes and halflings read 0. See `docs/80-fields-wanted.md`.
- **The remaining item-effect byte.** `+5` is 0 on 162 of the 163 items on the
  game disks and 251 on CURSED NECKLACE alone. Everything else in the 16 is
  read. Finding a magical weapon in play would also let the effect bytes be
  checked against an item we watched arrive, rather than against the 1989
  editor's synthesised records.
- **The monster attack routine.** The monster files otherwise decode: they use
  the character record layout, with hit dice at `0x0A0`, armour class at `0x0E1`
  and movement at `0x09F`. How many attacks a creature makes, and for how much,
  is not located, and the experience award is not stored at all.
