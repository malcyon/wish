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
* **`$49C7`–`$49C9` is the clock, and it reads HH:MM**: units of a minute, tens
  of a minute, then the **hour**. `DUNGEON $09F7` prints `$49C9`, a colon,
  `$49C8`, `$49C7`. It advances a minute per step and per turn in place.

  **Three readings of these three bytes were wrong before this one**, which is
  worth recording because each looked fine at the time:

  | reading | `PORSAVE4` | why it survived, and what killed it |
  |---|---|---|
  | 24-bit little-endian turn counter | 393991 | never checked against the bytes; nonsense on sight |
  | three decimal digits | 637 | the top byte holds 16 in `PORSAVE11`, so not a digit |
  | minutes, `d0 + 10*d1 + 100*d2` | 637 = 10:37 | plausible across `PORSAVE4`–`9`; but `PORSAVE11` gives 1647, i.e. 27:27 |
  | **HH:MM** | **6:37** | the game's own print routine, and every specimen is a real time |

  The middle reading survived longest because 637 through 649 across the walk
  saves counts up believably either way, and 1647 was explained away as
  "minutes modulo a day". `PORSAVE12` and `PORSAVE13` settle it beyond argument:
  16:58 and 16:59, one minute apart across one step.
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


## The character record answers to a fixed base of `$6B00`

**The technique that unlocked the rest of this page.** The overlays address the
resident character record at a **fixed absolute base of `$6B00`** — the same
address an exported `.chr` carries as its load address. So `LDA $6BA0` *is*
record offset `0x0A0`.

Scanning every absolute operand in `$6B00`–`$6D44` across every file on the nine
disks yields a map of which offsets the game's own code touches, and the routines
can then be read out directly. Four independent checks fix the base against
`por/layout.py`: `$6B14` is strength, `$6BD8` alignment, `$6BEB` class_bits,
`$6C19` current hit points.

Comparing saves was the wrong tool for these fields, and had been failing on them
for weeks. The item buffer has the same property: it is at `$6D7C`, with its
`ITEMS` type record at `$6D8C`, so every read of `item+N` is found by scanning
for `AD/AE/AC (7C+N) 6D`.


## Level drain, status, and the byte the game really tests

### Level drain: `0x0A1` and `0x0A2`. CONFIRMED

There is **no second copy of the level**. The pair is **current plus delta**,
which is why a "true level" was never found:

| offset | meaning |
|---|---|
| `0x0A1` | levels currently drained |
| `0x0A2` | hit points lost to draining |

`SPELLE02` computes `hp_max / total levels`, loops that many times doing
`DEC $6B76 / DEC $6BED / INC $6BA2 / DEC $6C19`, then `INC $6BA1`,
`DEC $6BC9,X`, and writes the character level down from the per-class array. If a
class level reaches 0 it sets level 0 and hit points 0. `RESTORATION` in
`SPELLE04` reverses it exactly and prints string 94 — which `SPELLN00`
independently gives as **`IS RESTORED`**. Two separately derived tables agreeing
on the same index is about as good as this gets.

**This settles `0x0A0` as the current level**, and it settles a design question
too: `wish` keeping `0x0A0` in step with `0x0C9`–`0x0CC` is exactly what the game
does.

### Status: solved as a negative

`LIBRARY` holds the strings. Indices 42–48 are
`OK GONE DEAD DYING UNCONSIOUS RUNNING STONED` — the game's own misspelling, and
"fled" is `RUNNING`. **Nothing on any of the nine disks references indices
42–48.** All 64 call sites into the string printer were disassembled.

The C64 party list prints name, armour class and hit points only, colouring hit
points when current is below maximum. **Status is derived, not stored**, and it
can be: hit points turn out to be **16-bit** — `0x076`/`0x077` maximum,
`0x119`/`0x11A` current — which is enough to separate unconscious from dying from
dead by rule. The ROLAND diff between `PORSAVE4` and `PORSAVE11` agrees: three
bytes moved, all of them money and experience.

`0x119` is therefore **genuinely current hit points**, not a copy of the maximum.
`GEN $0BD0` initialises it from `hp_max`, and both the trainer and the drain
routine move it independently afterwards. The old caveat can go.

### `0x0AD` is the first slot of an effect list. PROBABLE

`0x0AD`–`0x0B6` is a **ten-slot list of active effect codes**, in the same
namespace as item byte `+14`. Three overlays loop `LDX #$09` over it, and XAVIER
— carrying 107 in the first slot and 89 in the tenth — proves the extent
independently.

`GEN $0BF3` seeds it per race from the table `[1, 0, 107, 0, 124, 0, 0, 0]`, so
an elf is born with 107 and a half-elf with 124. Codes decoded against Gold Box
Companion's generated monster manual: **85 = drain one level** (wight, wraith),
**86 = drain two levels** (spectre, vampire), 64 = poison, **108 = immunity to
sleep and charm**, 110 = immunity to cold, 125 = combined immunity, and fifteen
more.

107 and 124 sit **immediately below 108 and 125**, and the table grades other
families the same way — 64, 65 and 66 are poison by save modifier. So they read
as elf and half-elf *partial* resistance to sleep and charm. PROBABLE.

Note what this closes: the resistance **percentage is not in the byte and could
not be**. It is a table index. The earlier attempt to find 90 and 30 in it was
looking for something that was never there.

### `0x0B8` is the NPC flag, and it also answers the trainer rumour. CONFIRMED

**Bit 7 is "this is an NPC or a monster".** Every read of `$6BB8` in the overlays
tests bit 7; the party-count routine tallies player characters with it and
enforces `CMP #$06` — **the six-character party limit exists in code**, not just
in the error message Donald hit; NPC money is zeroed on it. `npc_party.d64`
splits its three players from its five NPCs exactly here.

The eight `$FF` bytes `wish` had been exposing as `npc:` really are fill residue,
as the notes suspected. `wish` now writes bit 7 and leaves them alone.

**Bit 0 records that an ability score was altered at the trainer.** `GEN $155D`
sets it immediately after `INC`/`DEC $6B14,X`, and clears it again if the change
is cancelled. That is the flag the base-versus-current hunt predicted.

**And nothing reads it back.** Every read of `$6BB8` anywhere in the game tests
bit 7. The forum rumour — that an original developer said altering scores carries
negative effects in play — **has no code behind it on this port**. The prediction
was right that the game would have to remember; it remembers, and then never
looks. `wish` writing `0x014`–`0x019` directly is safe.

### Also out of the same reading

* **`0x0A3` is the undead turning class.** Non-zero in exactly 13 specimens,
  every one undead, matching the AD&D 1e turning table on all of them: skeleton
  1, zombie 2, ghoul 3, wight 5, wraith 7, mummy 8, spectre 9, vampire 10, with
  giant skeleton 8 and juju zombie 9.
* `0x0E6`–`0x0E7` are two calls to the RNG at `GEN $0C01`. Not a checksum.
* `0x0E1` is written as `LDA #$32 ; STA $6BE1` — the `60 - AC` encoding, read
  straight off a literal.
* **Correction, and it exonerates the 1989 editor.** Paladin and ranger really do
  display as `MAGIC-USER`: pointer entries 13, 14 and 15 all hold `$329D`. The
  editor was copying the game, not making a mistake. Race 0 prints as `MONSTER`
  (`LIBRARY $3508`), which explains PRINCESS FATIMA.


## Every remaining item byte

Two sources broke this open, both cheap and both previously unused. First, **the
`MON*` files carry item records** — every monster file is a character record, and
bytes `0x120`–`0x1DF` are twelve item slots. That is **132 more distinct item
records**, holding the magic the shop lists never do: `WAND OF PARALYZATION`,
`NECKLACE OF MISSILES`, `JAVELIN OF LIGHTNING`, a giant's `BOULDER`, and a `RING
OF PROTECTION +1` that differs from the shop's copy in exactly the byte under
investigation. Second, the disassembly technique above.

| byte | finding | confidence |
|---|---|---|
| `+5` | **bonus to saving throws**, signed | CONFIRMED |
| `+6` bits 3-6 | unused | CONFIRMED negative |
| `+7` bit 7 | cursed | CONFIRMED (was PROBABLE) |
| `+7` bits 0-6 | unused | CONFIRMED negative |
| `+13` | charges | CONFIRMED |
| `+14` | the spell or effect carried | CONFIRMED |
| `+15` | bit 7 = passive; low bits select a handler | CONFIRMED |

**`+5` is the good one.** The single read of it accumulates into `$6DA7`, and
`$6DA7` is consumed in exactly one place: added to a d20 saving-throw roll.
`RING OF PROTECTION +1` from `MON6E` carries `+4` = 1 **and `+5` = 1**. That is
the AD&D 1st edition ring exactly — +1 to armour class and +1 on saves, from two
bytes. `CURSED NECKLACE` carries -5 in both.

The negatives are worth as much. The only masks applied to `+6` or `+7` anywhere
in the game are `$80`, `$7F`, `$07` and `$F8` — and `$F8` is *identify*. So the
four spare bits of `+6` are not charges, which had been the standing guess, and
the low seven bits of `+7` hold nothing.

**`+13` charges** decrement per use. At zero the game spends one of the quantity
at `+10`; when that runs out it zeroes `+0` and the item is gone.

**`+14` is one namespace with two ranges.** At or below 56 it is a real spell id.
From 80 it is an item-only effect stored **23 above** its true id, so 80–90 mean
57–67; both `CAMP` and `COMBAT` do the `SBC #$17`. `POTION OF SPEED` carries 80
and `WAND OF MAGIC MISSILES` 88.

**`+15` selects a handler**, from a dispatch table in `ECL65` relocated to
`$9900`, covering `$80`–`$88` plus `$8A` and `$8B`. Three are named in
`SPELLE04` at `$A700`:

* **`$83`** sets strength to **18/100** (`LDX #$12 / LDA #$64`) — `GAUNTLETS OF
  OGRE POWER`. A second rules-level confirmation.
* **`$84`** is an **alignment-locked sword**: `+14 & $0F` against record `0x0D8`,
  and on a mismatch it un-readies itself and takes `+14 >> 4` off current hit
  points. `LONG SWORD +2` is `$F0` — alignment 0, 15 damage; `LONG SWORD +3` is
  `$52` — alignment 2, 5 damage. `COMBAT` also tests `CPX #$84` and zeroes the
  damage roll.
* **`$87`** requires **strength 19 or better** — the giant's boulder.

**When `+15` is non-zero, `+14` is that handler's argument, not an effect.**
`TWO-HANDED SWORD +1 +3 VS UNDEAD` carries `+15` = `$88` with `+14` = 3, and the
3 is its bonus against undead. Reading it as spell id 3 would be nonsense. Two
values on the disks, 34 and 42, fall outside the dispatch table and are
unexplained.

**A bonus: `ITEMS` type byte `+0` is the body location** — 0 weapon, 1 shield, 2
body, 3 hands, 5 neck, 7 back, 8 feet, 9 finger, 10 carried, 11 and 12 scrolls,
14 and above usable magic. It is what decides whether `+13`–`+15` read as three
spell ids or as charges plus effect plus handler.

### What `PORSAVE11` gave, and did not

21 new items, **every one mundane**: `+5`, `+7`, `+13`–`+15` and all of `+6` bar
the readied bit are zero in all of them. A clean negative — but two mechanics
fell out anyway:

* **Loot is copied byte for byte out of the dead monster's own `MON*` item
  slot.** That is why the looted shield is worth 0 gp and the looted scale mail
  15 rather than the shop's 45.
* The game **clears `+6` bit 7 in the copy** and merges quantities: three orcs'
  20 arrows each became one stack of 60.


## The emulator stops being a wall

Three things that had each been recorded as impossible turned out not to be. All
three were solved in one pass; the method notes are in
[driving the game](70-driving-the-game.md).

### Disk swapping works — through the *text* monitor

`Alt+N` was the right binding and was never going to work, because VICE's GTK
layer does not see synthetic modifiers. But the **text** monitor has
`attach "<path>" 8`, and both monitor servers can run at once.

Three rules, each learned by wedging the emulator:

1. The text monitor never breaks in on connect and sends no banner. It answers
   only while the machine is **already stopped** — which is what connecting the
   binary monitor does. Open binary, then talk text.
2. VICE serves **one** text-monitor connection per run. Close it and every
   monitor goes deaf, binary included, and the emulator freezes. So the driver
   must be one long-lived process.
3. Never send `x` on the text socket. Resuming is the binary monitor's job.

Same class of trap on the binary side: **never close the connection while a
checkpoint is armed.** VICE re-enters the monitor on whichever socket was live
when it stopped, and with that socket gone only a kill recovers it.

### R1: the roster blocks are writable. CONFIRMED

The acceptance bar for `wish` writing `SAVEDGAME1` at all, and it is met.

MALCYON was edited to armour class 1 and 11 hit points — **two bytes**, `$830F`
and `$8319`, with `SAVEDGAME0` untouched. The game shows `MALCYON 1 11` on the
party list and `HITPOINTS 11 / AC 1 / THACO 18` on his sheet, then writes the
identical roster page back when the game is saved.

Everything that lives only in the roster — current THAC0, current armour class,
damage bonus, current hit points, movement — is now editable in a way that has
been seen to work.

### Character creation: the name prompt, solved

`$0C46` is `CMP #$5B / BCS` — it rejects any name byte at or above `$5B`. And
`xdotool key W` sends **Shift+w**, which is `$D7`.

So the name typed *correctly*, the screen showed it, `$9700` held it, and the
validator threw the whole field away. Type lowercase and the character is
created: `\x01WYVERN`, 582 bytes, load address `$6B00`, written to disk under
script. The dead end recorded across two earlier sessions was a shift key.

### A walk corpus, and what it confirms

`work/drive/walks/` holds 20 saves the game itself wrote, one step apart, each
position verified against the disk and against the game's own status line.
Checked against the decoded `GEO00`: **7 adjacent steps, 7 legal, 0
contradicted**, and none of the occupied squares is sealed. Independent of the
fan-map matching that identified `GEO00` in the first place.

### The training-hall hang corroborates the zone id

One route died reproducibly: stepping **east into (6,2)** prints `THE ROOM IS
FILLED WITH DUELING PAIRS.`, stops redrawing the command bar, and from then on
every key is consumed and dropped. It is not an input fault — a store watchpoint
on `$C6` shows the KERNAL buffering the key and the game taking it at `$2E5E`,
and a single-step trace from `$10E3` shows it dispatched through `$306D`-`$30BA`
and discarded. Four runs died there; routes avoiding (6,2) complete.

`GEO00` explains where it is, and the agreement is exact:

| square | roofed | zone id | east edge | west edge |
|---|---|---|---|---|
| (4,2) | no | 0 | 0/0 | 0/0 |
| (5,2) | no | 0 | **12/1** | 0/0 |
| (6,2) | **yes** | **10** | 3/1 | **12/1** |
| (7,2) | yes | 14 | 0/0 | 3/1 |

(6,2) is the first **roofed** square on that line, it is entered **through a
door** — wall art 12 with barrier 1, reciprocal on both sides — and it carries a
**non-zero zone id**. That is the training hall interior, and the message is a
script firing on entry.

This is the best evidence yet that **plane `$200` bits 0-4 are a trigger or zone
id**: a square whose id is non-zero ran a script. 68 of `GEO00`'s 256 squares
carry one, and the ids run 1-31 with no gaps. Still PROBABLE — one observation
does not make a rule, and what wedges the game afterwards is a separate question
— but it is a prediction that came true rather than a correlation found after
the fact.


## The area id must exist, and the search for it was invalid

**Status: OPEN. This is the highest-priority unsolved question in the project.**

### Why the negative was wrong

It was reported that no byte in `$4900`–`$4BDF` identifies the map, on the
grounds that nothing there is "constant across the six New Phlan saves and
different in the others". Donald caught the flaw immediately, and it is
fundamental: **the game must record the area, or loading a save could not put
the party back where it was.**

The search had **no negative example**. Every save we hold is in New Phlan:

| disk | position | area |
|---|---|---|
| `PORSAVE` | (9,13) | New Phlan |
| `PORSAVE2`, `PORSAVE3` | (7,0) | New Phlan |
| `PORSAVE4` | (2,14) | New Phlan — in the inn |
| `PORSAVE5`, `PORSAVE6` | (3,14) | New Phlan |
| `PORSAVE7` | (3,11) | New Phlan |
| `PORSAVE8`, `PORSAVE9` | (0,11) | New Phlan |
| `PORSAVE11` | (4,2) | New Phlan — walked to the slums and **back** before saving |

`PORSAVE11` is the near miss: the party fought two encounters in the slums and
returned before saving. Ten disks, one area, nothing to contrast against.

The only foreign specimen, `npc_party.d64`, is useless for this: it is a
different party at levels 4-8 somewhere else entirely, and **218 header bytes**
differ between it and ours. No signal survives that much noise.

### The decisive experiment, and it is cheap

**One save inside a different area.** Save in New Phlan, walk into the slums,
save again. Two disks differing by one deliberate act, and the diff is the answer.

This is now runnable without Donald, because `tools/walkrun.py` drives the game
end to end and `work/drive/walks/` already holds a corpus generated that way. The
route out of New Phlan into the slums is longer than anything driven so far, and
the training-hall trigger at (6,2) has to be avoided, but neither is a blocker.

Do the same for a third area if the first pair is ambiguous — a value that moves
between two areas could be a counter; one that takes three distinct values
matching three areas is an id.

### The code route, which is sharper

`LIBRARY` carries a table of data-file name stems. **Both figures given for it
here earlier were wrong**, and the corrected one is this.

Its declared load address of `$1000` is a lie, as all the overlays' are.
`docs/40-memory-map.md` records the stem table live at **`$40EA`**, and
`GDRIVE00` sits at payload `+0x14A3`, which fixes the resident base at
**`$2C47`**:

| stem | live |
|---|---|
| `GDRIVE00` | `$40EA` |
| `SQRPACI00` | `$40F2` |
| **`GEO00`** | **`$40FB`** |
| `SECSET00` | `$4100` |
| `SQRDATA00` | `$4108` |
| `PIC00` | `$4111` |

So `GEO`'s two placeholder digits are at **`$40FE` and `$40FF`** — not `$24B7`
and `$24B8`, which was this entry's earlier arithmetic and was `$1C47` out.

**And nothing writes to them.** Scanning every file on all nine disks for any
store landing anywhere in `$40E0`–`$4150` returns two hits, both inside sprite
graphics. The stems are not patched in place at all: the loader must copy a stem
into a scratch buffer and assemble the filename there.

That kills this route as stated. What is left, in order of promise:

* **Find the scratch buffer.** Whatever assembles `GEO` plus two digits writes
  those digits somewhere, and the byte it converts from is the area id.
* **Find how a stem is selected.** There is no pointer table into the stems — no
  16-bit table anywhere contains two consecutive stem addresses — and no caller
  passes one as an immediate pair. So selection indexes variable-length strings,
  which means a length table or terminators exist somewhere. Find those and the
  caller falls out.
* **Stop chasing the filename.** The question is which area the party is in; the
  filename is only one expression of it. A save-diff across two different areas
  answers it directly and needs no disassembly.


Then the second half: **is that value saved, or recomputed?**

This is the `$6B00` technique that solved level drain, the NPC flag, `0x0AD` and
every remaining item byte. It reads the game's intent instead of guessing at
correlations, and it has been the more productive of the two routes every time.

### Keep derivation open

Donald's own caution: it may not be a stored byte at all. Candidates worth
holding in mind, roughly in order of how much they would explain:

* **A stored area index** somewhere not yet scanned. The scan covered
  `$4900`–`$4BDF` only. Not covered: `$4BE0`–`$4CFF` (nominally the eight
  36-byte combat icons, but a party under eight leaves unused slots), and the
  slot area `$4D00`–`$64FF` outside the eight character records — including the
  `$5500` staging page and `$5600`–`$58FF`, which is zero in every save we hold.
* **The active ECL script.** Each area has its own encounter/event script. If the
  save records which `ECL` is live, the map follows from it and there is no
  separate map id at all. This would also explain why a plain byte scan finds
  nothing shaped like a small area index.
* **A coarse world coordinate.** Phlan's blocks tile a city. If the save holds a
  block coordinate as well as the 0-15 square coordinates, the `GEO` file is a
  lookup, not a stored id.
* **Nothing is stored, and the load path asks.** Least likely, since the game
  restores position silently, but it should be ruled out rather than assumed
  away.

Whatever the answer, record how it was distinguished from the others. The
mistake this entry exists to correct was reporting an absence that the evidence
could not have detected.


## The combat icon is two poses, in multicolour

**Question.** `por/icons.py` had the 36 bytes -- 18 screen codes then 18 colours
-- but nothing that could *draw* them. Three things were missing: the cell grid,
the glyphs, and the colours.

**The grid is 3 wide by 6 tall, and it is two 3x3 poses stacked.** Rendering
MALCYON at 3x6, 6x3, 2x9 and 9x2, only 3x6 produced a figure -- and it produced
*two*, one above the other. They are two frames: a standing stance and an
attacking one.

**The glyphs are `CHARPIC00`.** 2030 bytes loading at `$8000`, about 253 glyphs.
It has to be this file: icon shape codes reach 233, and the only other charset on
the disks, `CHARSET`, holds 64.

**It is multicolour, and `COM.PREP` supplies the shared colours.** Every colour
byte in the specimen is at or above 8, and bit 3 of a C64 colour nibble is what
selects multicolour for a cell -- so a cell row is four double-width pixels, not
eight, and three of the four colours come from VIC registers that no save file
holds.

They were found by static analysis, not by running anything. `COM.PREP` -- the
combat-preparation overlay, byte-identical on all eight disks -- contains:

```
+0C6A  LDX #$0C
+0C6C  STX $D020        ; border          12  grey
+0C6F  DEX
+0C70  STX $D021        ; background      11  dark grey   -> bit pair 00
+0C73  DEX
+0C74  STX $D022        ; multicolour 1   10  light red   -> bit pair 01
+0C77  LDA #$00
+0C79  STA $D023        ; multicolour 2    0  black       -> bit pair 10
```

Bit pair 11 takes the cell's own colour, low three bits.

**Result. CONFIRMED by rendering.** The party's six icons come out as
recognisable little fighters -- blonde hair, blue and red tunics, swords raised
-- in two poses each. A wrong reading does not produce that by accident.

`por/icons.py` grew `icon_pixels()`, which returns the whole thing as a grid of
C64 colour indices with no image library involved, so the editor, a PNG dump and
a terminal preview all share one implementation.

**What this closes.** The editor plan had this as its one piece of genuine
research, to be done by peeking `$D021`-`$D023` in a running game. It did not
need the emulator: the same read-the-game's-own-code technique that solved level
drain, the NPC flag and the item bytes solved this too, in one search for
`STA $D02x`.

## The area id: `$4BC2`, and it was in the header all along

**SOLVED.** `$4BC2` — `SAVEDGAME0` offset `+$2C4` — is the `GEO` file number,
the map the party is standing on.

**How it works.** `$4BC0`–`$4BD8` is the loader's *"what is currently loaded"*
cache: 25 entries, one per data-file type, saved verbatim.

* `LIBRARY $4225` is the universal "ensure file number A of type X is loaded",
  and keeps the cache at `$6E13,X` in a running game.
* `CAMP $0D00`: `LDX #$18 / LDA $6E13,X / STA $4BC0,X` — all 25 copied into the
  header when the game saves.
* `GEN $25DE`: `LDA $4BC0,X / ORA #$80 / STA $6E13,X` — copied back on load,
  **bit 7 set to force a reload**. That bit is a dirty marker, not data. Mask it.

**Verified on every specimen.** All ten of Donald's saves read `$00` = `GEO00` =
New Phlan — which independently agrees with the wall-matching that identified
`GEO00` as New Phlan at φ 0.733, by completely different evidence. The one
foreign save, `npc_party.d64`, reads `$0D`; `GEO0D` is roofed on all 256 squares,
a dungeon interior, which is where somebody else's level 4–8 party would be.

Other entries decode too: `ECL` moves in step with `GEO` (both `0D` in the
foreign save), and the type→load-address table includes `MON` at `$6B00` — the
character-record base — and `ECL` at `$9900`.

**Why it took four attempts.** The first three all chased the *filename*: find
what patches the digits in `LIBRARY`'s `GEO00` stem, and trace its argument back.
Every step of that was wrong in an instructive way.

1. The stem's address was computed as `$24B4`, which was `$1C47` out.
2. Corrected to `$40FB` — and **nothing writes there**, because the stems are
   templates copied elsewhere, not patched in place.
3. A buffer at `$03D0` looked like where the filename is assembled. It is the
   **number-to-decimal buffer for printing on screen**: its entry `$2F29` has 122
   call sites and is handed things like `LDA $6BA0`, the character's level.

The answer was never in the filename. It was a plain byte in the header, in the
`$2E0` bytes that were already the only place left, and the thing that found it
was scanning for what *reads and writes* the header rather than reasoning
forwards from the filename.

**Two corrections that fall out.**

* `LIBRARY` loads at **`$2C48`**, not the `$2C47` derived here earlier from the
  stem table. Three independent patch sites fix it — `CAMP`'s `STA $301C` and
  `STA $301E`, and two vector patches in `COMBAT` — all of which land one byte
  early at `$2C47`. So `GEO00` is at `$40FC` and its digits at `$40FF`/`$4100`.
* **A stem pointer table does exist**, contrary to the note that none does. It is
  split into parallel low and high tables at `$4196` and `$41AA`, with lengths at
  `$4182`. The search that missed it looked for consecutive 16-bit addresses,
  which a split table does not contain.

`por/savegame.py` exposes it as `SaveGame0.area` and `.area_file`, with
`.loaded_files` for the whole cache.

**Confirmed by observation, not only by code.** Donald made the boundary pair:

| disk | area byte | reads as | position |
|---|---|---|---|
| `PORSAVE12` | `$00` | `GEO00`, New Phlan | (0, 4) facing west |
| `PORSAVE13` | `$14` | `GEO14`, **Slums** | (15, 4) facing west |

Two saves either side of one step through the New Phlan / slums doorway: the
west edge of New Phlan at `(0,4)` and the east edge of the slums at `(15,4)`,
the same row. The byte changed from `$00` to `$14`, and `$14` is the file the
wall-matching had independently identified as the Slums at φ 0.992 — the highest
score in that whole matrix. Two unrelated methods, same answer.

## The square attribute is a script id, and the ECL bytecode decodes

**SOLVED.** Plane `$200`, bits 0-6, is a **per-square script id**: the area's own
`ECL` script does `AND <mask>, ATTR, [v]` then `ONGOTO idx=[v]`, so the id
indexes a jump table.

The way in was the bytecode, not the maps. `coab` gives the DOS VM — opcode
table, operand encoding, and a variable window in which **`$C04F` is the
plane-`$200` byte of the party's square**. The C64 files are the same bytecode
with the block based at **`$9900`** rather than `$8000`: five entry-point words
in the first `$14` bytes, and coab's 6-bit string unpacker turns the `80`
operands into clean English. `ECL00` decodes linearly from `$9914` to its last
byte and lands on every entry point and jump target. Disassembler at
`work/analysis/ecl.py`.

**The training-hall prediction closes exactly**, which is the proof:

| step | value |
|---|---|
| `GEO00` (6,2) attribute | `$8A` |
| `& $7F` | 10 |
| `ECL00` jump table entry 10 (`$9B4C`) | `$A22D` |
| `$A22D` | `NEWECL 11` |
| `ECL0B` `$9BB0` | `THE ROOM IS FILLED WITH DUELING PAIRS.` |

That message is what the game prints when you step there, and it is what wedged
four automated runs. Predicted from the map bytes, confirmed in the script.

**14 of 22 `GEO<nn>`/`ECL<nn>` pairs have a jump table exactly `max id + 1`
long** — covering `0…max` with nothing spare. The pairing is independently
confirmed by the scripts' own text: `ECL14` is the Slums, `ECL1D` Kuto's Well,
`ECL0F` Mendor's Library, matching the wall-match results exactly.

Ids are 63% single-square triggers and 37% multi-square regions — shopfronts and
rooms — so both readings guessed earlier are true, per id.

**Bits 5 and 6 control wandering monsters, but only in some areas. CONFIRMED.**
Byte-identical code in `ECL03`, `ECL04`, `ECL06` and `ECL09`, immediately before
the zone dispatch, tests **bit 6 to suppress a random encounter** on that square
and **bit 5 to double the RNG range**, halving the rate. Those scripts then mask
the id with `$1F`.

**The mask is the area's, not ours**: `$7F` in eighteen areas, `$1F` in the
dungeon-floor family, `$3F` in `ECL17`. So outside that family bits 5 and 6 are
simply part of the id, and reading them as encounter control would be wrong.
Across all 29 files bit 6 is set on 114 squares and bit 5 on 517, of 7424.

Loose end: `GEO05` sets bit 5 on 126 squares and `ECL05` never tests it.

This also gives the encounter-rate question a home. Community sources say Pool
of Radiance scales encounters to party strength; here is the *other* half, a
per-square rate the map itself carries.


## `CHARPIC00` is eight bytes a glyph, and truncated by two

**SOLVED**, and the ragged end is harmless.

No header: splitting the file into 8-byte groups at every phase, **phase 0 is the
only one with a blank glyph anywhere meaningful, and that blank is index 32** —
the screen code for space, which real icons use. `CHARSET` (514 = 2 + 64 x 8) has
no header either.

The payload is 2030 bytes, six past the end of glyph 252, so the file **stops two
bytes into glyph 253**. `2032 = 8 x 254` is the most an eight-block PRG can
carry; a full 2048-byte charset would need a ninth block. Glyph 253's present
bytes are `00 00 00 00 3C F4`, and glyphs 81 and 251 are the only ones matching
those six — so the lost tail is `D4 D4`.

**Nothing touches it.** The highest shape code across thirteen sources is **243**
(the earlier note said 233, which was one specimen short), ending 72 bytes clear
of the truncation, and glyphs 244-252 are non-blank so the file is not
blank-padded. The clamp in `por/icons.py` never fires. One `CHARPIC` exists,
byte-identical on all eight disks.


## The effect list shares storage with item `+14`, not meaning

**A standing PROBABLE, corrected.** `docs/80-fields-wanted.md` and `por/layout.py`
both said record `0x0AD`-`0x0B6` used "the same namespace as item byte `+14`".
They share the *slots*, not the vocabulary.

`SPELLE04 $ADD4` copies a readied passive item's `+14` verbatim into a free slot.
But `85` is `POTION OF HEALING` as an item and **drains one level** on a wight. A
passive item's `+14` is its handler's argument — the gauntlets carry 38, the
cloak 89, the ring 61 — and those land in the same array as monster traits.

**Sixty-one monster records enumerated**, about forty codes with confidence
levels. The self-proving ones are the ones to trust, because each lands on
exactly the creatures the *Monster Manual* says it should:

| code | on exactly |
|---|---|
| 83 | the two petrifiers |
| 119 | the five monsters needing a magic weapon to hit |
| 109 | the four level-drainers |
| 120 | the two boulder-throwing giants |
| 100 / 101 | troll regeneration |
| 64-67 | a graded poison family |

The `+15` handler table is located exactly: `ECL65`, resident at `$9900`, three
parallel arrays at `$9AD5`/`$9AEE`/`$9B06`, 24 entries, handlers all inside
`SPELLE04` at `$A700`. `$ADD4` is the shared default for eight of eleven item
codes — and it is the same routine reached independently from the `$6BAD` scan.

A new save region falls out: `$4900`-`$493F` is 64 party-wide active-effect
codes, `$4940`-`$497F` the owner (bit 7 = whole party), `$4B80`-`$4BBF` a third
parallel array, from `LIBRARY $3FE0` and `CAMP $131F`. Zero in all eleven saves —
an out-of-combat party, not a refutation.


## `LIBRARY` is at `$2C48`

Two agents reached it independently and both beat the `$2C47` derived here from
the stem table. Three patch sites fix it — `CAMP`'s `STA $301C` and `STA $301E`,
and two vector patches in `COMBAT` — all landing one byte early otherwise; and
fitting by JSR-target alignment scores 359 of 522 at `$2C48` against 290 at
`$2C47`, with `JSR $3FE1` only decoding at all under `$2C48`.

So `GEO00` is at `$40FC` with its digits at `$40FF`/`$4100`. It no longer
matters — the area id is `$4BC2` — but the base is used for every other
`LIBRARY` address in this log.

Also established and reusable: **every game overlay loads at `$0800`**, not the
`$1000` its header claims. `COMBAT`, `DUNGEON`, `CAMP`, `POST.COM`, `COM.PREP`,
`GEN` and `INIT` all score 480-550 internal call targets there and near zero
elsewhere. `SPELLE04` is at `$A700`, `ECL*` at `$9900`, `MON*` at `$6B00`.

## The live map: the game leaves it at `$0400`

**CONFIRMED.** The `GEO` block the game is drawing sits at **`$0400`**, and the
game does not relocate it at all. The file is a PRG loading at `$0400` — screen
memory at boot — but in the world the screen has moved to `$CC00`, so the page is
free and the loader simply leaves the map there.

`$0400`–`$07FF` was byte-identical to `GEO00` with 480/480 reciprocity, and a
sweep of all 64K in both the `cpu` and `ram` banks found no second copy.

**This is why the search that was meant to settle the area question kept coming
back empty.** `automap/area.py` shipped with `SEARCH_RANGES = ((0x0800, 0xCFFF),)`
— one page too high, and mine. The live map now names its area on the first poll,
before the party moves, by matching those 1024 bytes against the disk copies.

`FilenameDigits` is dead as a strategy: `$24B4` reads `50 55 5A 5F 20 87`.

One thing nobody has taken, and it is cheap: `Fingerprint` needs **111 steps** to
identify New Phlan from positive evidence alone, because a square being walkable
rules out very little. **One refused step would settle it instantly** — and the
status line already carries the clock, so *clock advanced + square unchanged +
facing unchanged* is a refused step. `Fingerprint.refused()` exists and nothing
calls it.


## Polling does not stall the emulator. It speeds it up

**The premise was wrong, and it was mine.** `docs/96` said a live map that polled
would "stutter the game visibly", and the whole `resume()`-instead-of-reconnect
design was built to avoid a stall. Measured against the KERNAL jiffy clock at
`$A0`–`$A2`, with idle windows either side reading 1.000 and 1.002:

| polling | emulated seconds per wall second |
|---|---|
| flat out | **3.048** |
| every 100 ms | 1.129 |
| every 200 ms (the default) | **1.068** |
| every 500 ms | 1.028 |

Each `fix()` hands the emulation about **14.3 ms of *extra* emulated time**. The
monitor does not pause the machine on balance — it lets it run unthrottled while
the socket is serviced. So the risk was never a stall; it is the game running
**fast**.

The cost is **per `resume()`, not per byte**: a 7168-byte read costs the same as
one `peek`, and four peeks with four resumes cost 45.9 ms against 14.4 ms for the
same work batched. That vindicates the "read `$4900`–`$64FF` in one call" advice
for a reason opposite to the one given.

**Keep 200 ms.** Seven per cent fast is imperceptible in a game whose clock
advances per move, and the 715 ms that would buy a 2% error makes the marker lag
behind the party.

Negative result worth having: **VICE never serves a second binary-monitor
connection while the first is open.** It accepts the TCP connection and then
ignores it. So `automap` and `tools/session.py` cannot both be live.


## There is no training-hall wedge, and it was never (6,2)

**Withdrawn.** `docs/70-driving-the-game.md` recorded that stepping east into
(6,2) consumes every keypress thereafter and that only a kill recovers it. Four
runs "died there". None of that is true.

Stepping *into* (6,2) is harmless. Stepping **(6,2) → (7,2)** prints `THE ROOM IS
FILLED WITH DUELING PAIRS.` and row 24 becomes **`PRESS <RETURN> OR BUTTON TO
CONTINUE`**. Press Return, wait about **25 seconds** of loading, and the arena
master asks two `YES NO` questions. Answer them and you walk back out.

Three compounding mistakes made an ordinary encounter look fatal:

1. **The status line keeps reading `6,2` for the whole encounter**, because the
   step does not complete until the questions are answered. So the driver
   concluded the move had failed.
2. **`$306D` is the *menu* key reader**, not the world one. It accepts `<`, `,`,
   the four cursor keys, `$0D`, `$5F` and the joystick. `I`/`J`/`K`/`M` fall out
   at `$30B6` and are *correctly* discarded. The single-step trace that showed
   keys "dispatched and discarded" was watching the right code do the right
   thing.
3. **`leave_move()` gives up after 8 x 0.6 s** — five seconds, against a 25-second
   load.

Sampling the PC 300 times at (6,2) gives a distribution identical to before
entry: the ordinary `$10C2` key-wait loop.

The lesson is the one this log keeps relearning. "Four runs died there" was four
runs of the same wrong assumption, not four pieces of evidence.


## A constructed item is accepted by the game

**CONFIRMED.** A `LONG SWORD +4` — no such item ships on any disk — built from
word indices, type, bonus, cost and weight with no template copied:

```
24 00 a5 24 04 00 00 00 3c 00 00 10 27 00 00 00
```

Seven bytes changed at `$5A90`–`$5A9C`; `SAVEDGAME1` untouched. On booting and
readying it:

| | before | after |
|---|---|---|
| weapon | `SHORT SWORD` | **`LONG SWORD +4`** |
| THAC0 | 21 | **17** |
| damage | `1D6+1` | **`1D8+5`** |

−4 on THAC0 is byte `+4`; `1d8` comes from the type table via byte `+0`; `+5` is
strength +1 plus the item's +4. Only slot 1's roster block changed, and `SAVE
CURRENT GAME` wrote the record back verbatim.

Weight is **PROBABLE** only — slot 1's movement fell 6 → 3 and nobody else's did.
Cost is **UNVERIFIED**; neither is printed on the C64 sheet.

The attempt to make weight decisive failed and turned up something better:
**poking `$5A98` to 150 lb was reverted by the game**, so the item area at
`$5900`+ is a *copy* fed from a master elsewhere, and live pokes there do not
stick. That is a new fact about the format and a trap for any future live edit.

Incidental: the game **silently** refuses to ready a second weapon — no message
at all. Un-ready the first.

## Combat: the mode flag, and where the combatants are

Both halves of the combat research landed.

### `$6E11` is the mode flag. CONFIRMED

**`$6E11` holds the number of the overlay currently running, and `2` is
combat.** Not a screen to scrape — the game's own dispatcher.

`LINKER` is a **136-byte resident at `$2B80`** (its declared `$1000` is the usual
lie) and it is the entire outer loop: `LDA $6E11`, index the name table at
`$2BBB`, load that overlay at `$0800`, `JSR $0800`, repeat. An overlay sets
`$6E11` to whatever should run next and returns.

| `$6E11` | 0 | 1 | 2 | 3 | 4 | 5 | 8 | 9 |
|---|---|---|---|---|---|---|---|---|
| | `GEN` | `DUNGEON` | **`COMBAT`** | `INIT` | `COM.PREP` | `POST.COM` | `FINAL` | `CAMP` |

Every write agrees: `COM.PREP $0936` writes 2, `COMBAT $090C` writes 5,
`INIT $09D8` writes 1, `DUNGEON $10B1` writes 9. Sampled live across one driven
session: menu `00`, New Phlan `01`, combat map drawn `02`, post-fight `05`, back
in the world `01`. `04` was never seen live — that row is disassembly only.

`$6E11` sits in the loader's resident page beside the file cache at `$6E13`, so
no overlay moves it.

**The loaded-files cache does not work for this**, which was the first thing to
try and is a clean negative: `COMPIC` read `$82` before a fight, `$8B` during and
`$8B` after — populated in the world and never cleared — and `MON` stayed `$FF`
throughout.

### The combatant table

| what | where |
|---|---|
| who is fighting, and their combat stats | **`$8300 + i*32`** — the `SAVEDGAME1` roster block, simply continued past `$83FF` |
| where they stand | **`$8B00 + i*4`** = `x, y, i*4 \| pose, 0`; `$FF $FF` means off the map |
| which record is theirs | roster `+0x0D` names the record slot |

`i` runs 0–63, with 0–7 the party **in save-slot order** and 8 upward the
monsters — exactly the encoding the effects owner byte at `$4940` already used.
That lead paid off.

The chain: `COMBAT $28CB` → `LIBRARY $4415` → `JSR $3189` (`$8300 + i*32` into
`$6C00`), `LDA $6C0D`, `JMP $315A` (slot into `$6B00`).

`COM.PREP $08B6` fills `$8B00`–`$8BFF` with `$FF` before every fight, which fixes
the table at one page. Observed in two duels:

* BRUTUS, save slot 5, at `$8B14` = `19 0D 14 00` — (25,13) — then `18 0C 16 00`,
  then `19 0B 14 00` as he moved.
* The monster at `$8B20` = `1E 0D 22 00` — (30,13); on death `FF FF 22 00`, with
  its roster `+0x00` going `$01` → `$84`.
* Every other entry `FF FF FF FF`.

x reached 30, so **the combat map is at least 32 squares wide** — bigger than the
16×16 `GEO` grids, as expected.

**`$A380 + i` is the initiative array.** `COMBAT $08BE` scans it for the maximum
with ties broken randomly, and the round ends when all 64 are zero (`$090C`, then
`$6E11 = 5`). `COM.PREP $1663` clears seven such arrays with `LDX #$3F` — which
is where the 64-combatant limit comes from.

### A long-standing reading corrected: there are twelve record slots, not eight

`LIBRARY $312B` computes **both** `$4D00 + n*$100` and `$5900 + n*$100`, and the
arithmetic only closes at twelve:

```
records  $4D00 + 12 * $100 = $5900   <- exactly where the item area begins
items    $5900 + 12 * $100 = $6500   <- exactly where SAVEDGAME0 ends
```

At eight slots there is an unexplained gap. So **`$5500` is slot 8**, not the
"staging page" it has been called since early in this project, and `$5600`–`$58FF`
are slots 9, 10 and 11 rather than dead space. The orc found at `$5500` after a
fight was a combatant occupying a real slot.

`SLOT_COUNT` in `por/savegame.py` stays **8** deliberately: that is the *party*,
which the game enforces at six player characters and eight total. The extra four
are combat scratch and must not appear in a party list.

### Limitations, stated plainly

* **One monster, observed twice.** Both fights were training-hall duels with a
  single opponent at index 8. Monsters at 9, 10, 11 and slot sharing follow from
  the code, not from observation. A multi-monster fight is the next check.
* `$6E11 == 4` was never sampled live.
* Position byte `+3` is always 0 and unexplained; `+2 = i*4 | pose` is PROBABLE
  on three samples.
* The combat map's terrain format is untouched. `SQRPACI01` loads at `$0400`–
  `$07FF` during combat — verified against RAM — but contains 6502 code, so it is
  the square *renderer*, not the map.
* **Gate any reader on the flag.** `$8B00` reads all **zero** in the world, not
  `$FF`, so an ungated reader would happily draw 64 combatants stacked at (0,0).

## What Curse of the Azure Bonds gave Pool of Radiance

A survey of what a second game would cost turned up two findings about *this*
game, both confirmed here directly.

### The roster block is record bytes `0x100`-`0x11F`. CONFIRMED

A 580-byte record is **four blocks the game saves separately**:

| record | size | where it goes in a save |
|---|---|---|
| `0x000`-`0x0FF` | 256 | `$4D00 + N*$100`, the character slot |
| `0x100`-`0x11F` | 32 | **`$8300 + N*$20`, the `SAVEDGAME1` roster block** |
| `0x120`-`0x21F` | 256 | `$5900 + N*$100`, the item area |
| `0x220`-`0x243` | 36 | `$4BE0 + N*$24`, the icon table |

Two agents reached this independently — one from `LIBRARY $3189`/`$319A`, which
copies `$8300 + N*$20` in and out, the other from matching exports against saves
by name. Checked here on `PORSAVE.D64`: an exported `.chr` and the roster page
agree in **31 of 32 bytes for all six characters**, differing only at `0x10D`.

**So there was never a 44-byte "export delta."** That figure came from reading
580 contiguous bytes from `$4D00` and running off the end of a `$100` slot into
zeroed neighbours. The real difference between an export and a save is one byte:
`0x10D`, which is marching order in an export and the record slot index in a
roster block.

Renamed accordingly: `region_100` → `roster_in_use`, `region_10d` →
`party_order`, `region_110` → `roster_tail`, `region_11b` → `roster_movement`.
That last one was recorded as "12 in every specimen", which held only because
every specimen was the same six characters — `PORSAVE10`'s exports read 9 in
banded mail.

### `0x0EE`-`0x0F3` is spells castable per level. CONFIRMED

The docs had this down as not stored anywhere. It is six bytes, one per spell
level, **nibble-packed: cleric in the high nibble, magic-user in the low**.

| character | class, level, wisdom | `0x0EE` | reads as |
|---|---|---|---|
| ROLAND | cleric 1, WIS 16 | `$30` | 3 cleric — one base plus two for wisdom |
| MALCYON | magic-user 1 | `$01` | 1 magic-user |
| LADY KATHERINE | magic-user/thief 1 | `$01` | 1 magic-user |
| SILAS, MAGNUS, BRUTUS | fighters | `$00` | none |

ROLAND's 3 is exactly what his sheet allows, and it is what
`docs/50-experiments.md` recorded when he memorised spells. The editor no longer
has to compute capacity from class, level and wisdom — the game already did.

### Where it came from

The Curse disks are on this machine, and pointing `por/` at them worked: `geo.py`
decodes all 16 of Curse's `GEO` files unchanged, `items.py` reads its `ITEMNAMES`
after changing one address, and Pool of Radiance's record offsets read Curse's
own pre-generated party correctly — abilities, race, age, saves, money, levels,
class bits, experience. Paladin and ranger turn out to fit *existing* slots: the
per-class array at `0x0C9` is eight wide, not four.

Full survey in `work/reports/coab-research.md`; a proposed plan in
`work/reports/coab-plan.md`.

## A real fight, and what it settles

Donald walked `PORSAVE13` around the slums until a random encounter started and
left the machine sitting in it. Live memory read at `$6E11 = 2`, no actions
taken. This is the multi-monster case the earlier combat research explicitly
did not have.

**Fifteen combatants:**

| index | who | record slot | position | hp | AC |
|---|---|---|---|---|---|
| 0-5 | the party, in save-slot order | 0-5 | (25-29, 13-14) | | |
| 8-15 | **eight `GOBLIN GUARD`s** | **8, all of them** | (23-28, 11-12) | 4 | 6 |
| 16 | `GOBLIN LEADER` | 9 | (23,11) | 7 | 4 |

**Monsters share one record slot per *type*.** Eight goblins, one record. That
was written up as "follows from the code, not from observation"; it is observed
now. It also explains why twelve slots is enough for a fight with twenty-five
creatures in it.

**Correction: position byte `+2` is `record_slot * 4 | pose`, not
`index * 4 | pose`.** Indices 9 and 15 both read 32, which `index * 4` would
make 36 and 60. The party carries pose 2 and the monsters pose 0. The earlier
reading was taken from a duel where index and slot happened to be equal, so the
two were indistinguishable — exactly the trap a single-specimen inference sets.

**`$0400` is not the combat map**, and scoring it as a `GEO` reciprocates
137/480 = 0.285, which is chance — but it is not merely "the square renderer"
either. `SQRPACI01` is a mixed page: a tile remap at `$0580`, **the combat-view
parameter block at `$0600`**, and code from `$0680`. The parameter block is what
finds the map; see "The combat map is at `$8C00`" below.

The map reaches x=29 and y=14, so it is at least 30 wide.

One number worth a second look: the walkthrough for the slums gives `GOBLIN
GUARD` as AC 7, and the roster says 6. **Resolved: the shield.** `MON02`'s own
record says AC 7 (`0x0E1` = `0x10F` = 53) and its item block holds a readied
`STUDDED LEATHER ARMOR` (protection `$B5`, AC 12-5 = 7) *and* a readied `SHIELD`
(protection `$81`, -1). `0x0E1` is the unequipped base — 10 for every player
character — and the roster's `+0x0F` is recomputed from readied equipment when
the record is loaded into a combat slot. The C64 does not differ from the PC.


## The combat map is at `$8C00`, and the shape is in `SQRPACI`

**Question.** Where is the combat terrain, and what shape is it? The last
unknown blocking `docs/101-combat-view.md`.

**Answer.** `map[x, y] = peek($8C00 + y * 56 + x)`, 56 x 26, bit 7 meaning "a
combatant stands here". CONFIRMED.

### Method: follow the renderer, not the data

Blind statistics on candidate regions had already failed on `GEO`, so this went
at the problem from the drawing code.

1. A **store checkpoint on `$CE81`** — one character cell inside the combat map
   window — hit at `PC $C0FC`, inside `GDRIVE00`'s resident page.
2. `$C082` is a 3 x 3 glyph blitter. It reads the square through `LDA ($07),Y`,
   remaps it through `$0580`, multiplies by 18 (9 screen codes + 9 colours) and
   adds a glyph base held at `$0600`/`$0601`.
3. An **exec checkpoint at `$C084`**, reading `$07`/`$08` on every hit, printed
   the whole redraw: **49 pointers, 7 x 7, exactly `$38` = 56 apart.**
4. Three pointers matched squares whose coordinates were known from `$8B00` —
   `$8DDC` = (28,8), `$8E13` = (27,9), `$8E4B` = (27,10) — and all three solve
   to base `$8C00`, stride 56.

### The parameter block, which gives the rest

`$0600`-`$0613`, read live in combat:

| address | value | meaning |
|---|---|---|
| `$0600`/`$0601` | `$91B0` | tile glyph table, 18 bytes a tile |
| `$0602`/`$0603` | `$8C00` | **the map** |
| `$0604`/`$0605` | `$8B00` | the position table |
| `$0606` | `$40` | 64 combatants |
| `$0607` | `$38` | **row stride, 56** |
| `$0610`/`$0611` | 49, 19 | maximum camera origin |
| `$0612`/`$0613` | 55, 25 | **maximum square x and y** |
| `$037E`/`$037F` | | the window's top-left square |

`COM.PREP $08C6` derives the clamps and proves the reading — `LDA #$07 /
STA $061A`, then `LDA $0612,X / SEC / SBC $061A / CLC / ADC #$01 /
STA $0610,X`. The view is 7 squares, so `55 - 6 = 49`. `$037E`/`$037F` read
(26,4) while the acting character stood at (29,7), dead centre.

**And the size closes arithmetically:** 56 x 26 = 1456 = `$5B0`, so the map runs
`$8C00`-`$91AF` and ends exactly where the glyph table at `$91B0` begins.

### `SQRPACI<nn>` is where the block comes from

`POOL1__SQRPACI01`, 1024 bytes loading at `$0400`, holds the `$0580` remap at
`+0x180`, **the `$0600` block at `+0x200`** and the code at `+0x280` — all three
byte-identical to live memory. So the page is table, parameters and code
together, which is why reading it as a map scored at chance.

**The geometry is per-file and must be read at runtime.** `POOL6__SQRPACI00`
carries a different block: glyph base `$8E88`, stride **20**, bounds 17 and 35.
Stride and width are separate fields.

### Bit 7 is occupancy

`$C086 BPL` skips the glyph lookup when bit 7 is set and draws the combatant
instead. Seen twice:

| when | `$80` squares | `$8B00` says |
|---|---|---|
| a duel's first frame | (25,13), (30,13) | the same two |
| a slums encounter | sixteen squares at x 25-30, y 11-15 | the same sixteen |

So mask `& $7F` for terrain, and `& $80` is a free cross-check on `$8B00`.

### Two maps, and what is still open

The training-hall arena and a slums random encounter differ in 246 of the 1456
bytes and read as plainly different floor plans, both with the same parameter
block. Terrain values run 0-7, 0 being floor: glyph 48 is nine spaces.

**Where the bytes come from is not established.** `$8C00` is LIBRARY's file
staging buffer, so the map is most likely loaded and decompressed into it at
fight setup. What is ruled out:

* **`SQRDATA`.** Its loader-cache slot read `$FF` — never loaded — in *both*
  fights. The file with the most map-like name on the disks is not it.
* **A verbatim file.** 32-byte probes from both maps match nothing on any
  `POOL*.D64`.

`GEO` differed between the two fights (`$80` = GEO00, `$94` = GEO14) and so did
the map, which fits "derived from the area" and fits "a per-area backdrop file"
equally well. The decisive experiment is a **store checkpoint on
`$8C00`-`$91AF` armed while a fight starts**; both fights here were already
running by the time one could be armed.

## The two class fields, separated at last

**Question.** `char_class` (`0x073`) and `class_bits` (`0x0EB`) say the same
thing twice and agree in all twenty specimens. Which does the game read?

**Answer: both, for different things.** `0x073` names the character; `0x0EB`
decides what they may use. CONFIRMED.

**Method.** `wish-cli` built a save from a copy of `PORSAVE13` with one byte
changed — SILAS `class_code 2 -> 5` — leaving `classes: [fighter]`. The game
loaded it **without reconciling**: `$5073` = `05`, `$50EB` = `08`.

| test | result | so |
|---|---|---|
| the sheet's class line | `MAGIC-USER` | `0x073` is what is displayed |
| un-ready then re-ready his `LONG SWORD` (thief/fighter) | allowed | `0x0EB` is what is tested |
| control: LADY KATHERINE (`0x0EB` = 5) readying `SCALE MAIL` (cleric/fighter) | refused | the check is real |

The control is the point. "It readied" alone would be equally consistent with
the game never checking.

**The code agrees.** `LIBRARY $465A`:

```
$465A  ad 99 6d  LDA $6D99      ; the item type's class-usage byte
$465D  2d eb 6b  AND $6BEB      ; class_bits
$4660  d0 07     BNE $4669      ; overlap -> allowed
$4662  a9 ad     LDA #$AD       ; else $46AD = "WRONG CLASS."
```

`$6D8C` is the resident item's `ITEMS` record and the usage byte is its 13th, so
`$6D99` is exactly that field. `CAMP $167D` runs the same test. A scan of every
overlay for the two addresses splits them cleanly: `$6BEB` is only ever `AND`ed
(`COMBAT $1EE8`/`$202A`, `CAMP $167D`, `LIBRARY $465D`), while `$6B73` is only
ever an index (`POST.COM $123F`/`$15E3` `LDX`; `LIBRARY $31E1`-`$320D` `LDY`
into three parallel class-name tables joined with `/`).

## Planned, not yet run


- ~~**The export delta.**~~ **There is none.** A record is four blocks the game
  saves separately -- 256 to the slot, 32 to the roster page, 256 to the item
  area, 36 to the icon table -- and an export matches a save in 579 of 580
  bytes. The "44 differing bytes" came from reading 580 contiguous bytes from
  `$4D00` and running off the end of a `$100` slot into zeroed neighbours. The
  one real difference is `0x10D`: marching order in an export, record slot in a
  roster block.

- **The checksum probe.** Largely answered by the thirteen-field edit, which the
  game accepted without complaint. A dedicated corruption probe would only add
  the case of a byte in a region nothing reads, and nothing depends on it.
- ~~**The two class fields, separated.**~~ **Run, and both fields are real.**
  `0x073` is what the sheet prints; `0x0EB` is what the game ANDs against an
  item's class-usage byte to decide whether it may be readied. Written up below.
- **The fortune teller in the slums.** A guide reports that talking to her
  raises the difficulty of random encounters in the slums. Split this in two,
  because the halves are wildly different in cost:
  * **Does the game record the conversation?** Save outside, talk to her, save
    again, diff. Decisive either way and takes minutes. A byte or a bit moving in
    the header `$4900`–`$4BDF` would be the **first quest flag we have located**.
    `SAVEDGAME1` past `$8400` is no longer a candidate — it is code.
  * **Does it actually make encounters harder?** Much more expensive — random
    encounters need a lot of samples before a difficulty change is
    distinguishable from luck, and "harder" is not defined. Not worth attempting
    unless the first half finds something, and even then it is a claim about
    behaviour rather than about the file.
  Note the first half is worth running **whatever the guide got right**: it is a
  controlled single action, and a diff that shows nothing at all is also
  informative.
- ~~**The trainer's ability-score change.**~~ **Answered without running it.**
  `0x0B8` bit 0 is set by `GEN $155D` right after `INC`/`DEC $6B14,X` and
  cleared if the change is cancelled — so the game does remember. And every
  read of `$6BB8` anywhere tests bit 7, the NPC flag: **nothing reads bit 0
  back**. The rumour has no code behind it on this port, and `wish` writing
  the six ability bytes directly is safe.

- ~~**The racial-traits hunt.**~~ **Found:** `0x0AD`–`0x0B6`, a ten-slot list
  of active effect codes seeded per race by `GEN $0BF3` from
  `[1, 0, 107, 0, 124, 0, 0, 0]`. That is why `0x0AD` was non-zero only for
  elves and half-elves.

- ~~**The remaining item-effect byte.**~~ **Found: `+5` is a signed
  saving-throw bonus.** Its single read accumulates into `$6DA7`, which is
  consumed in exactly one place — added to a d20 saving throw. `RING OF
  PROTECTION +1` from `MON6E` carries `+4` = 1 and `+5` = 1, the AD&D ring
  exactly.

- ~~**The monster attack routine.**~~ **Found.** `0x0D9`-`0x0E0`: attacks per
  round stored **doubled** so AD&D's 3/2 works out, two attack forms, dice
  count, die size and a signed modifier. Twenty creatures match the *Monster
  Manual*. And the experience award **is** stored after all -- `0x0F7`/`0x0F8`
  base plus `0x0F9` per hit point, times `hp_max`. The earlier "not stored at
  all" failed because AD&D's award is two numbers, not one.

- ~~**What icons the game can actually make.**~~ **Found, and it is small.**
  `SPELLN64` (disk 3, `$AF00`, entry `$AF24`) is the icon editor: `ICON: PARTS
  COLOR SIZE EXIT`, then `PARTS: WEAPON HEAD EXIT`. Its data file `SPELLE64`
  holds four option tables — 35 weapons and 23 heads for one size, 28 and 14
  for the other — with counts at `$B0DA` and pointers at `$B0DE`, both read
  rather than assumed by `por/iconparts.py`.

  The reachable set is **15328 shapes**, not the 805 + 392 that "one weapon
  times one head" predicts, because a weapon change *preserves* cells 0, 1, 9
  and 10 (`$B26F`/`$B29B`) and because SIZE is never written back to `0x099`,
  so the two table pairs can be mixed in one session. Both matter: of the 11
  distinct icons on our disks only **6** come from a single (weapon, head)
  pair, and all **11** are in the closure. A product model would have called
  five real icons impossible.

  Colour is constrained too: `colour[cell] = C[class(glyph)] | (8 if the glyph's
  class byte has bit 7)`, seven values 0–7, one per part class. It reproduces
  **103 of 104** icon slots cell for cell; the exception is SHARA THE GRAY on
  the shipped `POOL1` party, hand-authored with `$0F` in two cells. Cells
  holding no part are *not* governed — a space has class `$0F` and its colour
  byte is residue, and computing one anyway is what first made the rule
  disagree with all eight icons in a save.

  `HEAD*`/`BODY*` are the **portrait**, a different overlay writing `0x0FE` and
  `0x0FF`; `GEN` offers 14 heads and 12 bodies there. Unrelated to the icon.
