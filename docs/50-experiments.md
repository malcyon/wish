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

Baked into `tools/porlaunch.sh`, which the instance pool launches. It was
`tools/rungame.sh` until that script was deleted for killing every emulator
on the machine by name (#143).

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

Corrected in `goldbox/savegame.py`, with `tests/fixtures/party6_savedgame0.bin` (a
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

**Two fixes to `goldbox/items.py` came straight out of those 162 records:**

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
**Found while building `docs/85-item-tables.md`.** `goldbox/items.py` read
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

Full table in [the spell table](86-spell-table.md); reader in `goldbox/spells.py`.

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
where `goldbox/layout.py` already says it should.

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
cleric with Wisdom 16. `goldbox/spells.py` computes it.

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
with a fully equipped party", and the same claim reached `goldbox/savegame.py`. One
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
one line of `goldbox/savegame.py` said otherwise. And "`$5500`-`$58FF` stays zero
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
**6** -- precisely what `goldbox/derive.py` has been computing and reporting as
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
the shape is left open. `goldbox/derive.py` does not model it and now reports
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

  *Superseded, and withdrawn. The scan had no negative example — every save it
  looked at was in New Phlan, so "constant here" proved nothing. See "The area
  id must exist, and the search for it was invalid" for why, and "The area id:
  `$4BC2`, and it was in the header all along" for the answer: `$4BC2`, inside
  the very range this scan swept.*
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
`goldbox/layout.py`: `$6B14` is strength, `$6BD8` alignment, `$6BEB` class_bits,
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

### `0x0AD` is ten trait slots, in the effect namespace. CONFIRMED

`0x0AD`–`0x0B6` is **ten trait slots** carrying codes in the same
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

**Status: SOLVED — see "The area id: `$4BC2`, and it was in the header all
along" below.** It stood open as the highest-priority unsolved question in the
project, and the reasoning below is what reopened it.

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

**Question.** `goldbox/icons.py` had the 36 bytes -- 18 screen codes then 18 colours
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

`goldbox/icons.py` grew `icon_pixels()`, which returns the whole thing as a grid of
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

`goldbox/savegame.py` exposes it as `SaveGame0.area` and `.area_file`, with
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
blank-padded. The clamp in `goldbox/icons.py` never fires. One `CHARPIC` exists,
byte-identical on all eight disks.


## The effect list shares storage with item `+14`, not meaning

**A standing PROBABLE, corrected.** `docs/80-fields-wanted.md` and `goldbox/layout.py`
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
in the world `01`. `04` was never seen live *in this title* — that row was
disassembly only until Silver Blades' `$7F11` was watched sitting on `4` while
`COM.PREP` loaded (see "the later titles' mode flag is `$7F11`" below), which is
the same dispatch table and settles the meaning.

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

`SLOT_COUNT` in `goldbox/savegame.py` stays **8** deliberately: that is the *party*,
which the game enforces at six player characters and eight total. The extra four
are combat scratch and must not appear in a party list.

### Limitations, stated plainly

* **One monster, observed twice.** Both fights were training-hall duels with a
  single opponent at index 8. Monsters at 9, 10, 11 and slot sharing follow from
  the code, not from observation. A multi-monster fight is the next check.
* `$6E11 == 4` was never sampled live *here*. Its counterpart `$7F11 == 4` was, on Silver Blades — see "the later titles' mode flag is `$7F11`".
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

The Curse disks are on this machine, and pointing `goldbox/` at them worked: `geo.py`
decodes all 16 of Curse's `GEO` files unchanged, `items.py` reads its `ITEMNAMES`
after changing one address, and Pool of Radiance's record offsets read Curse's
own pre-generated party correctly — abilities, race, age, saves, money, levels,
class bits, experience. Paladin and ranger turn out to fit *existing* slots: the
per-class array at `0x0C9` is eight wide, not four.

The full survey and the plan it proposed, `work/reports/coab-research.md` and
`work/reports/coab-plan.md`, are lost; `docs/116-second-game.md` §7 corrects
the plan's open questions against what was later confirmed.

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

## The quickfight bit is roster `+0x0C`, and the live writes work

Two questions in one session: does a live write reach the game at all, and
where is the bit the combat menu's QUICK sets.

### The setup

`work/drive/SLUMS.D64`, six characters at (15,4) in the slums. VICE launched
into its own Xephyr on `:8` — **not** `tools/porlaunch.sh`, which `pkill`s
unconditionally — and shut down through `CMD_QUIT` and the two process ids it
started, so nothing else on the machine was touched.

### Healing, live

`HealParty` wrote roster `+0x19` for the four wounded characters at the party
menu. The game's own list, redrawn by stepping into `VIEW CHARACTER` and back,
then read **11 9 9 7 5 4** against maxima of 11 9 9 7 5 4 — every hit point
back, and the numbers came from the game, not from our own decode. Repeated
mid-fight at `$6E11 = 2`: SILAS 8 → 9, no complaint from the game. That is the
"legal anywhere" claim exercised where it matters.

### The bit

Four steps out of (15,4) walked into an orc ambush. With the game sitting on
MALCYON's command bar, `$4D00`–`$58FF`, `$8300`–`$8AFF`, `$8B00`–`$8BFF` and
COMBAT at `$0800`–`$27FF` were captured **twice** — 13568 bytes, and **zero of
them differ**. A machine waiting for input is perfectly still, which is what
made a one-byte diff readable.

Then QUICK, from the bar `MOVE VIEW AIM USE QUICK DONE`, and capture again:

| address | before | after | what |
|---|---|---|---|
| `$830C` | `00` | `80` | **roster block 0, `+0x0C`, bit 7** — MALCYON |
| `$0A97`–`$0A98` | `08 0E` | `37 14` | COMBAT's own scratch |

Three bytes in 13568. Repeated on MAGNUS, slot 4: `$838C` went to `$80` and
block 0 stayed set — two characters, two blocks, one bit each.

### It survives the fight, and the player's own disks say so

The roster page is saved in `SAVEDGAME1`, which is why thirteen *record* diffs
never found it: step 1 of the search order in `docs/80-fields-wanted.md` was
right, and the answer was one file over.

| disks | `+0x0C` across the eight blocks |
|---|---|
| `PORSAVE2`–`PORSAVE9` | `80 00 00 00 00 00 00 00` — **MALCYON alone** |
| `PORSAVE`, `PORSAVE11`, `12`, `13` | all zero |

Eight save disks, taken out of combat in ordinary play, carry the bit set for
exactly one character. Nothing clears it when combat ends.

### What it is not, yet

The complaint the field was wanted for is that quickfight *sticks* — that the
character is still not yours in the next fight. This bit does not behave that
way in the two tests that bear on it:

* Driving QUICK repeatedly, the bit **sets while the computer plays the action
  and clears when the action resolves**, and the same character's command bar
  comes straight back. It is not held for the rest of the fight.
* **Setting it out of band did nothing.** `$834C` was poked to `$80` for ROLAND
  mid-fight; the game cleared it and asked ROLAND for orders anyway.

So on the evidence the bit reads as "the computer is playing this character's
action" — written by QUICK, left behind when a fight ends while it is set, and
not consulted to decide whether to ask for orders. What is still untested is
whether **COMBAT reads it at the start of a fight**, which is the one place a
leftover could do the harm the complaint describes; the fight in hand never
ended, so that experiment is still open and is written up in
`docs/80-fields-wanted.md`.

`automap/actions.py` clears it all the same. Clearing restores the byte every
clean save has, so the write cannot hurt; the action says plainly that its
effect on the next fight is unproven.


## Does the save know where the party has been

**No.** One area has a first-entry flag and it is the area every game starts in,
so nothing in `SAVEDGAME0` distinguishes a party that has seen Sokol Keep from
one that has not.

The question came from Fast Travel: Donald asked whether the dropdown could
offer only the areas the party has already visited, and whether the game itself
records that anywhere. If it did, the save would be the authority and wish's own
map files a supplement. It does not, and it is the other way round.

**Method.** Every area script has five entry points in its first `$14` bytes,
and entry 4 is area initialisation — CONFIRMED, `LOADFILES`/`LOADPIECES` in the
first fourteen instructions of 26 of 30 scripts
(the write-up, `work/reports/ecl-opcodes.md`, is lost). Walking each script from entry 4 and looking
for a write into the persistent-flag region `$4A20`-`$4AF8` asks exactly the
right question: what does a party set by *arriving*? The walk was then repeated
from every entry with any of `PRINT`, a menu, a fight, an item search or a
random roll treated as "the player did something", so that only the
interaction-free paths counted.

**Result — four scripts write a flag at all, and none of them is a visit
record.**

| script | area | write | is arrival enough? |
|---|---|---|---|
| `ECL00` | New Phlan | `$B06E SAVE 1, [$4AC5]`, guarded by `$9B40 COMPARE [$4AC5], 1 / IF<` | **yes** — a genuine first-entry flag. Useless as a discriminator: New Phlan is where the game starts, so it is 1 on all thirteen played saves and 0 only on the shipped one |
| `ECL00` | New Phlan | `$9AF2 SAVE 0, [$4AC4]` | no — a clear on every entry |
| `ECL07` | Valjevo Castle, the Pool | `$A8FE SAVE 0, [$4AE0]` | no — clears "the castle has been left after the win" |
| `ECL12` | Podol Plaza | `$9998/$999E` and `$99AC/$99B2`, setting `$4A34`/`$4A35` | no — the auction state machine, and one branch writes 0, which is what an unvisited area reads |
| `ECL1D` | Kuto's Well | `$995F SAVE 0, [$4ADB]` on street-level squares, `$99CC SAVE 1` after the climb | no — a level register. Street level writes 0, indistinguishable from never having been |
| `ECL1C` | Zhentil Keep Outpost | `$993C SAVE 253, [$4AB4]` on the leave-the-map entry | no — a ledger entry, gated |
| `ECL03`-`ECL06`, `ECL09` | Valjevo Castle | `SAVE 0, [$4A64]`, `AND [$4A67], 127` | no — the alarm timer lapsing and a per-level one-shot being cleared |
| `ECL1A` | Wilderness, middle | `$AF35 SAVE 255, [$4AA2]`, `$AF3B SAVE 255, [$4A9A]` | no — a wilderness site and an appointment, both gated |
| the other **twenty-one** area scripts | — | nothing | no flag write on any interaction-free path from any entry |

`$4A9E` looks like a candidate and is not: identical code in `ECL19`/`ECL1A`/
`ECL1B` sets it 255 on entering a wilderness site and 0 on leaving, so it is
current state, not history. `$4BC0`-`$4BD8` is the loader's file cache, also
current state. The 44 one-shot "already happened" flags (write-up lost,
`work/reports/quest-flags.md` §3.4) are each tied to a *scene*, not to arrival.

**What this means for the feature.** The visited list has to be wish's own
record — one `GEO*.json` per area with a non-empty `seen` — which covers only
what the automapper watched. That is a real limitation and the reason the filter
is a checkbox that disables itself when there is no record, rather than a rule.
See [`118-debug-mode.md`](118-debug-mode.md) §2.1.

**Worth knowing for Curse.** The same question will come up, and the same method
answers it: the ECL bytecode is one artefact shared by every port, absolute
address operands included (write-up lost, `work/reports/quest-flags.md` §7), so a Curse script
can be walked from its entry 4 exactly as these were. Whether Curse's scripts
happen to carry arrival flags is not settled by this — only that Pool of
Radiance's do not.

Scratch: `work/analysis6/ecl6.py` and the extracted scripts in
`work/amiga/c64ecl/`.


## The trainer's own routine, and the end of the level-up blockers

**The question.** `automap.actions.LevelUp` refused, and named five fields it
could not derive: the hit-die roll, the saving-throw modifiers, the cleric's
wisdom bonus, a thief skill table the project did not have, and whatever else
the trainer touched that nobody had measured. Twenty-nine trainings had already
been driven through the game's own school (`docs/119-test-party.md`), so the
*effects* were known; what was missing was the rule behind each one.

**What was done.** Not another emulator run: `GEN` is a file on `POOL3.D64` and
the trainer is in it. `GEN $1B8C` is the fourteen-call sequence a level-up
runs, and every routine it calls was read. The tables are all in
`docs/135-levelling.md`; the five that closed the blockers are these.

**Hit points are two fields and only one of them is a die.** `GEN $2037` rolls
one die of the class's own size — `$20A7` holds `04 08 06 0A` in class-bit
order — divides it by how many classes the character has (`$20AB`, indexed by
`char_class` at `0x073`, which holds 1 for a single class and 2 or 3 for the
multi-class codes), and never returns less than 1. Then:

```
$205A  CMP #$04
$205C  BCS  $2067
$205E  LDX  $6BEB        ; class_bits
$2061  CPX  #$08         ; fighter, and nothing else
$2063  BNE  $2067
$2065  LDA  #$04
```

so **a single-class fighter never rolls below 4 on its d10**. SILAS's eight
trainings gained 10, 5, 7, 8, 10, 8 and 4 — no number under 4, which had looked
like luck. `$2079` then writes `hp_max = hp_rolled + level x constitution
bonus`, from the AD&D table at `$247B` for anyone with a fighter bit and `$2486`
for everyone else, consulted only from 15 up. That is why MALCYON, an
18-constitution *magic-user*, gets 2 a level and not 4.

**There are no saving-throw modifiers on the character.** `GEN $1F44` fills all
five columns with 20, then for each class the character holds walks a level-1
row at `$1FA2` and two per-column bitmasks at `$1FB6` and `$1FCA`, subtracting
one for every set bit in either mask among the low `level - 1` bits, and keeps
whichever class gives the lower number. Then `$2359`:

```
$2359  LDX  $6B72        ; race
$235C  LDA  $2380,X      ; dwarf, gnome, halfling
$235F  BEQ  $2380
$2361  LDA  $6B18 / ASL A ; constitution * 2
$236F  JSR  $3F04        ; / 7
$2374  LDA $6B9A,X / SEC / SBC $4C / STA $6B9A,X   ; all five columns
```

`26 // 7` is 3, which is exactly why the dwarf MAGNUS read three lower than the
human SILAS at every level. The "modifiers nobody has measured" were one
division and a three-byte race flag.

**And the two masks settle P76.** The fighter's fourth column carries mask
`$0C` where its other four carry `$08`, so that column improves twice by level 4
and once elsewhere: the game's own table gives a breath save of **15** at
fighter 4 where AD&D 1st edition gives 16. `goldbox/levels.py` was wrong, not the
game. `goldbox/derive.py` had the same species of error next door — its fighter
THAC0 row was AD&D's grouped `20 20 18 18 …` where `GEN $1F1F` runs
`20 19 18 17 …`, so every even fighter level was one out.

**The thief table is race and nothing else.** `GEN $1FEC` copies eight bytes
from `$102E + (level - 1) * 8` and then adds eight from `$1076 + (race - 1) * 8`.
No ability score is read. `docs/119` had recorded LADY KATHERINE's ladder as
"race and dexterity are in them"; only race is, and her numbers are the level
rows plus the half-elf row `0 0 0 5 0 0 0 5` exactly.

**The wisdom bonus is a table and a stack of shifts**, at `$10AD` and `$2108`,
and it applies only where the class table already grants a slot at that spell
level. ROLAND, wisdom 16, stores `50 50 20` at cleric 6 — `3,3,2` plus
`+2,+2,0`. The table itself starts a point low against the rulebook; that is
`docs/125-bug-notes.md` N13.

**A magic-user chooses; it does not roll.** `GEN $215A` walks the 32-byte
spellbook copy, keeps every id 1-55 it does not know whose level at `$268E` is
at or below `(level + 1) // 2` and whose flag at `$226B` is 0 (magic-user
rather than cleric), and puts the survivors on a menu. `$1FDE` has already
written the *new* per-class level by then, so a magic-user reaching 3 is offered
second-level spells at that same training — which is what a first replay got
wrong. A cleric needs no menu: `$20CF` ORs its whole new spell level in.

**The verification.** `goldbox/levelup.py` was written from the routines and then
replayed against the thirty-four before/after record pairs in `work/p18b/`,
each one a 580-byte read either side of a real training. Given the roll the
game made, **every pair comes out byte-identical** on every field except the
three the action deliberately does not do: the 1000-gold fee and the platinum
conversion, the heal to full, and the movement recompute.

`tests/test_levels.py` now re-expands every table off the player's own `GEN`
rather than trusting the longhand rows, which is the check that would have
caught P76 the day it was typed.


## The slums fortune teller comes back, and the wandering cap with her

**Claim under test.** `$4A0B` is the fortune teller's one-shot flag and it sits
in `$4A00`-`$4A1F`, the scratch page `DUNGEON $202A` zeroes on every area
change; so she is alive again on every fresh visit, the "gods have noted your
actions" penalty goes with her, and `$4A80`, the fifteen-fight cap on the
slums' wandering monsters, can be reset without limit because `ECL14 $A749`
does `SAVE 0, [$4A80]` when she dies. Issue 12, PROBABLE on the addresses.

**All four halves confirmed.** `goldbox-bugs.md` #9.

**Read first.** Two corrections to how the project had been reading `ECL14`
came out of this and both matter beyond it.

* **The square-script dispatcher is 0-based.** `ECL14 $99A2` seeds `$9800` with
  **0** and walks it up to 20 against the square's `AND 127, ATTR`, so
  `ONGOTO [$9800], 21, …` sends script id 0 to the *first* pointer. The fortune
  teller is id **8**, the single square `(3, 5)`, and not id 9 — and she proves
  it herself: her LEAVE branch writes `mapX` 3, `mapY` 4, the square directly
  north of her. Ohlo's LEAVE writes `(14, 10)`, next door to his own id-3 block
  at x 11-13, y 9-10. Driven: stepping onto `(3, 5)` ran `$A63A`.
* **Script id 21 is unreachable.** `$99B4 COMPARE [$9800], 20 / IF> / EXIT`
  caps the walk at 20, so the thirteen `GEO14` squares whose attribute is 21 —
  `(1,0) (2,0) (3,0) (0,1) (1,1)` and `(8,5) (6,6) (7,6) (8,6) (6,7) (7,7)
  (8,7) (7,8)`, two building-shaped blocks — match nothing and fall through the
  `ONGOTO` into whatever follows it. PROBABLE; nobody stood on one.

**The zero fill, read out of the running machine.** `$2011` onward is
`LDA $6E1B / AND #$7F / STA $49F2 … LDX #$1F / LDA #$00 / STA $4A00,X / DEX /
BPL` at `$202A`-`$2032`, exactly as `docs/41` has it. Every `NEWECL` clears
`$4A0B`.

**Method.** Instance-pool slot 4, headless, from `PORSAVE13.D64` — Donald's own
save one step inside the slums at `(15, 4)`, `$4A0B` = 0, `$4A80` = `$4ABB` = 3.
Two harness decisions, both of which touch what was being measured:

* **the party was moved between steps by writing `$C04B`-`$C04D`**, the live
  square, which is what the fasttravel harness does before `NEWECL` minus the
  `NEWECL`, so it never goes near `$4A00`-`$4A1F`. Every step the party
  actually took was the game's own, and every area change was a real walk off
  the edge of a map.
* **`$4A80` was held at 15 for the walking.** `$9B32 COMPARE [$4A80], 15 /
  IF>= / EXIT` is the wandering roll's own off switch, and after the murder the
  roll is five points likelier — the first attempt at this run was eaten by
  three consecutive wandering fights and a party wipe. The murder's write to
  `$4A80` was read **before** the harness put it back, which is the whole point
  of watching it.

**What happened.**

| step | printed | `$4A0B` | `$4A80` |
|---|---|---|---|
| step onto `(3, 5)` | the greeting, `ATTACK LEAVE PAY` | 251 | 3 |
| ATTACK | `YOU EASILY MURDER THE OLD WOMAN… THE GODS HAVE NOTED YOUR ACTIONS.` | 255 | **0** |
| step off and back onto `(3, 5)` | nothing; the square is inert | 255 | — |
| walk east off `(15, 4)` | New Phlan, `ECL00`, `GEO00` | **0** | held 15 |
| walk west off `(0, 6)` | `YOU HAVE ENTERED THE MONSTER-CRAWLING SLUMS…` | 0 | held 15 |
| step onto `(3, 5)` | the greeting again, word for word | 251 | 15 |
| ATTACK | the murder again | 255 | **0** |

**`$4ABB` never moved** — 3 throughout, across two murders. So the City Hall
commission is not farmable and `$4ABB` and `$4A80` can be **out of step**, which
is worth knowing because `docs/134` observes that every specimen we hold has
them equal. They are equal in specimens because nothing in ordinary play
separates them; the murder does, and so does a lost wandering fight.

**Two side observations, both weaker.**

* **The penalty is real while it lasts.** With `$4A0B` = 255 the first run took
  two wandering fights in three ordinary steps, against one in twenty before
  the murder. That is the `+5` at `$9B50` on a `RANDOM 13` that has to beat 12.
  Suggestive rather than measured — six steps is not a sample.
* **`$6DD2`/`$6DD3` read `00 00` throughout**, so `ECL14`'s entry 2 — the block
  at `$9A0E` that writes 24 into both when `$4A0B` is 255 and 0 otherwise —
  never fired while the flag was set. What calls entry 2 is not known; the
  encounter-frequency reading of that block stays GUESS.

**The east doorway works and the west one does not.** Walking east off the
slums' `(15, 4)` reached New Phlan, and walking west off New Phlan's `(0, 6)`
came back. Walking west off New Phlan's `(0, 4)` — the square `PORSAVE12` was
saved on, facing west, one step before `PORSAVE13` — was refused four times,
with `$6DD5` still 0 afterwards, so the engine never treated it as a boundary
crossing. Both squares are edge exits in `GEO00` with the same barrier bits.
Unexplained, and the difference is not `ECL00`, whose entry 0 is an
unconditional `NEWECL 20`.


## Every overlay's PRG header is a stamp, not a load address

`DUNGEON` running at `$0800` where its header says `$1000` is not one file's
quirk, and it is not a family-wide `$800` either. **Every code overlay that
declares `$1000` runs somewhere else, and the offsets range from `-$0800` to
`+$9F00`.** The header is a number stamped per family by whatever built the
disks; the twenty-three stems that declare `$1000` run at eight different
bases.

The distribution gives it away. Across the 983 files on the eight sides there
are 34 distinct header values, and four of them cover more than half the disk:
206 files say `$5000`, 170 say `$6400`, 115 say `$1000`, 106 say `$1388`. A
per-file load address does not cluster like that.

### Measured in the running game — CONFIRMED

Slot 3, `P18PARTY.D64`, headless. Five 32-byte runs are taken from each file on
the disks and the machine's 64K is searched for them; a run found once names the
base with no inference at all. Three states were dumped — walking in the world,
in camp, and in character generation.

| file | header | runs at | the header is | evidence |
|---|---|---|---|---|
| `GEO00` | `$0400` | `$0400` | **right** | 5/5 probes, in the world |
| `DUNGEON` | `$1000` | `$0800` | `$0800` high | 5/5, in the world |
| `CAMP` | `$1000` | `$0800` | `$0800` high | 5/5, in camp |
| `GEN` | `$1000` | `$0800` | `$0800` high | 9078 of its 9083 bytes, in character generation |
| `LINKER` | `$1000` | `$2B80` | `$1B80` low | 5/5 |
| `LIBRARY` | `$1000` | `$2C48` | `$1C48` low | 5/5 |
| `SECSET00` | `$3A00` | `$6500` | `$2B00` high | 5/5 |
| `ITEMNAMES` | `$6F00` | `$6F00` | **right** | 5/5 |
| `DUNGEON2` | `$1000` | `$7A00` | `$6A00` low | 5/5 |
| `COMBAT3` | `$1000` | `$7AC0` | `$6AC0` low | 5/5 |
| `ITEMS` | `$7600` | `$7B00` | `$0500` low | **2048 of 2048 bytes** |
| `ANIMATE00` | `$1000` | `$8400` | `$7400` low | 3/5, and the file's own `4C xx 84` table |
| `BODY01` | `$5000` | `$8C00` | `$3C00` low | 5/5 |
| `HEAD10` | `$5000` | `$9000` | `$4000` low | 5/5 |
| `ECL0B` | `$1388` | `$9900` | `$8578` low | 5/5 |
| `SPELLN64` | `$1000` | `$AF00` | `$9F00` low | 5/5 |
| `FAST1.O` | `$B700` | `$B700` | **right** | 5/5 |
| `MDRIVER` | `$BA00` | `$BA00` | **right** | 5/5 |
| `SOUNDFX` | `$BA00` | `$BA00` | **right** | 5/5 |
| `GDRIVE01` | `$1388` | `$C000` | `$AC78` low | 3/5 |

Seventeen of the twenty are wrong, three are right, and the three that are right
are the three that declare something other than a family stamp.

The dumps also settle the page above the roster, which now tiles without a gap:
`$7A00` `DUNGEON2`, `$7AC0` `COMBAT3`, `$7B00`-`$82FF` `ITEMS`, `$8300` the
roster blocks, `$8400` `ANIMATE00`.

`MON04` sits at `$5500` in all three dumps, 467 of its 480 bytes matching — a
monster record with its run-time fields moved. Its header says `$6400`.
PROBABLE, and worth saying because the `goldbox` skill records `MON*` at
`$6B00`; `$6B00` is where a record is *worked on*, not where the file lands.

### Fitted rather than measured

For an overlay nothing in a session made resident, the base is fitted: linear
sweep for instruction starts, then score every candidate base by the `JSR`/`JMP`
targets that land inside the file, `+1` at an instruction start and `-1`
elsewhere. A wrong base scatters its targets, so the penalty separates the true
base from near-misses.

| file | header | fitted | hit / miss | runner-up | grade |
|---|---|---|---|---|---|
| `COMBAT` | `$1000` | `$0800` | 482 / 6 | `$07FD`, 246 | CONFIRMED (below) |
| `POST.COM` | `$1000` | `$0800` | 245 / 38 | `$2BF3`, 128 | PROBABLE |
| `COM.PREP` | `$1000` | `$0800` | 97 / 6 | `$08EE`, 53 | PROBABLE |
| `INIT` | `$1000` | `$0800` | 54 / 3 | `$090F`, 41 | PROBABLE |
| `FINAL` | `$1000` | `$0800` | 31 / 4 | `$0683`, 29 | GUESS — the fit is a tie and only the family says `$0800` |
| `SPELLE01` | `$1000` | `$A700` | 45 / 1 | `$2362`, 38 | PROBABLE |
| `SPELLE02` | `$1000` | `$A700` | 21 / 0 | `$A4DD`, 19 | PROBABLE |
| `SPELLE04` | `$1000` | `$A700` | 99 / 5 | `$A559`, 57 | PROBABLE |
| `SPELLE00` | `$1000` | `$A700` | 33 / 0 | `$99BF` scores higher on recall | GUESS |
| `SECSET64` | `$1000` | `$6500` | 37 / 0 | `$64FD`, 19 | PROBABLE, and `SECSET00` is measured there |
| `ECL64` | `$1000` | `$9900` | 15 / 1 | `$98ED`, 12 | PROBABLE, and `ECL0B` is measured there |
| `GDRIVE00` | `$C000` | `$C000` | 139 / 3 | `$BD0C`, 54 | PROBABLE |

`LOAD_SAVE`, `BOOT` and the `POOLR*` boot files have too few internal targets to
fit and were never resident in a dump. UNKNOWN, and nothing cites them.

`COMBAT` is CONFIRMED without a dump, by the file's own arithmetic: `$0969` is
`LDA #$70 / LDX #$09 / JMP $485A`, which builds the address `$0970` out of two
immediates, and `$0970` — file offset `$0170` — holds `17 27 01 17`, the message
window that was poked live to `17 1E 01 11` while `COMBAT` was resident and made
the window small (`docs/110-combat-log.md`). Only base `$0800` puts those four
bytes at that address.

`GEN` is separately CONFIRMED by external rule: at `$0800` the AD&D tables land
byte-exact. `$102E` is `30 25 20 15 10 10 85 0`, the level-1 thief row; `$20A7`
is `4 8 6 10`, the four hit dice; `$1FA2` is four consecutive level-1
saving-throw rows — `14 13 11 15 12` magic-user, `10 13 14 16 15` cleric,
`13 12 14 16 15` thief, `14 15 16 17 17` fighter — every number the book's.

### The audit of what we already cite

107 distinct `OVERLAY $XXXX` citations across `docs/`, `goldbox/`, `automap/`,
`tools/` and `tests/` were checked against the measured bases. **Every one is
inside the overlay it names.** The handful the checker flagged are all
explained: a linear sweep desynchronises over an embedded table, so `GEN $102E`,
`$1F44` and `$2228` "are not instructions" because they are the thief-skill,
saving-throw and spell-slot tables; `GEN $136E` and `$15A9` are *Curse's* `GEN`,
cited in `goldbox/levels.py` beside Pool of Radiance's; and `CAMP $301C` is an
address *in* `LIBRARY` that a sentence about `CAMP` mentions.

So `$282E` was the only one. The reason nothing else slipped is that `$282E` is
the only address in the log that was ever *computed* rather than found — every
other citation came from reading the file at a base somebody had already fixed.

### One correction

**`ITEMS` loads at `$7B00`, not the `$7600` its PRG header claims.**
`docs/85-item-tables.md` used to say `$7600`; the string was hardcoded in
`tools/genitems.py` and the document is generated, so the fix went there --
done, with the header clause that reconciles the two addresses.
Nothing depends on it — `goldbox/items.py` indexes the file by record number and
never by address — but it is the same mistake `$282E` was, still sitting in the
knowledge base. `docs/125-bug-notes.md` R51's "the DOS file even carries the
same `$7600` load address" is a statement about the two files' headers and stays
true.

Scripts: `work/p17/` (gitignored) — `fit2.py` the base fit, `cites.py` the
citation audit, `dumpsearch.py` the RAM search, `run.py` the pooled session.


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

- ~~**The racial-traits hunt.**~~ **Found:** `0x0AD`–`0x0B6`, ten trait slots
  carrying effect codes, seeded per race by `GEN $0BF3` from
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
  rather than assumed by `goldbox/iconparts.py`.

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

- ~~**The quickfight flag.**~~ **Found, and now fully closed: roster `+0x0C`,
  bit 7.** The live diff found it — `$830C` went `00` to `80` when QUICK was
  chosen for MALCYON, the only byte to move in 13568 captured across the record
  slots, the roster, the combatant table and COMBAT's own page. What that
  experiment could not settle was whether the bit does anything after the fight
  it was set in, because the fight never ended.

  `PORSAVE14` settles it. Donald enabled quickfight on MALCYON during a random
  orc encounter, finished the fight, saved, and walked into a second and
  unrelated fight — where MALCYON was **still** under computer control. The save
  reads `+0x0C = 80` for MALCYON and `00` for the other five.

  That also explains the result that looked like a refutation. Poking the bit on
  for ROLAND mid-fight did not stop the game asking him for orders, and driving
  QUICK repeatedly showed the bit setting and clearing around each action. Both
  follow if **`COMBAT` reads the flag when the fight starts** and works from its
  own copy for the rest of it: a mid-fight write is simply too late, in either
  direction. It is why the only escape the player found was pressing space at
  the exact moment a turn begins.

  So the complaint that started this is exactly right — the game never clears it,
  and the next fight can be a dangerous one. `automap/actions.py` clears the bit,
  which restores the byte every clean save has.

- ~~**Does the game scale random encounters to the party?**~~ **It does, and
  the routine has a name.** `PARTYSTRENGTH`, ECL opcode `$1D`, implemented at
  `DUNGEON $1BE8`. Twelve of the thirty area scripts call it, and in every one
  the result becomes the **count operand of `LOADMON`** — literally how many
  monsters are placed.

  Per living roster slot, summed and then divided by ten:

  * `5 * (THAC0 field - 39)`, the field being stored as `60 - THAC0`
  * hit points **maximum**
  * `5 * (AC field - 60)` when the AC field is at least 60
  * `4 * level` for a cleric, `8 * level` for a magic-user

  Slots that are empty, or have bit 7 of `0x100` set, are skipped.

  **Checked against Donald's own disks, and re-implemented twice
  independently.** `PORSAVE` sums to 115, strength 11; `PORSAVE11` to 130,
  strength 13 — MALCYON 27, LADY KATHERINE 13, ROLAND 16, SILAS 24, MAGNUS 24,
  BRUTUS 26. The slums count is `(strength / 3) * 2`, so **buying kit took
  every later random slums encounter from six monsters to eight**, with nobody
  gaining a level or a point of experience.

  **Correction: it was not the armour.** An earlier version of this entry said
  "armour makes the game harder". The AC term needs the field at 60 or more,
  which means **AC 0 or better** — and the best anyone in the party reaches is
  2. Measured across the shopping trip, ROLAND went AC 10 to 4, SILAS 10 to 3,
  MAGNUS and BRUTUS 9 to 2, and all four contributed the *same* number before
  and after: 12, 24, 24, 26. The whole `+5` was MALCYON readying a dart —
  THAC0 21 to 20. The later `+10` was MALCYON again, dexterity edited to 18 for
  the missile bonus, THAC0 down to 18.

  So the observation stands and the mechanism was wrong: **weapons and THAC0
  drive it, not armour.** A low-level party can only move this number by
  arming, by gaining hit points, or by levelling a cleric or magic-user.

  **Rate and size are separate systems.** Four scripts honour the per-square
  `NO_ENCOUNTER` and `HALF_ENCOUNTER_RATE` bits *and* do not scale: their
  wandering monster is a fixed patrol, identical at level 1 and level 8.

  **Two accounts disagree on the count and it is not yet settled.** The
  encounter work found four such scripts; the full ECL decode, which reaches
  100% of every script, finds the bit-6 test in **six** — `ECL05` at `$9BE2`
  and `ECL0F` at `$99F8` as well. Both can be true if those two honour the bit
  *and* scale, which would mean the two systems are not as cleanly split as the
  first account suggests. **Check before relying on either.** Dungeon rate is 1 in 21, halved on a bit-5 square; the
  slums 1 in 14; the wilderness 1 in 20.

  **There is no encounter-table file.** Each `ECL` carries its own parallel byte
  tables read with `GETTABLE`. `ECL00` scales the monster *type* rather than the
  count, shifting an index at two strength thresholds.

  Negatives worth keeping: no party-strength byte is stored anywhere, which
  closes that open question; nothing in the encounter path reads experience, an
  ability score, the clock or the commissions completed. Party size counts only
  as the number of terms in the sum.

- ~~**Where the overland map lives.**~~ **Not a `GEO` at all — it is the combat
  square engine pointed at other data.** `SQRPACI00` describes it, `SQRDATA04`,
  `05` and `06` hold the terrain as **18 x 36, one byte a square**, followed by
  120 tile glyphs; `SECSET04`-`06` are the charset. `ECL19`, `ECL1A` and `ECL1B`
  drive them, and `LOADFILES` dispatches on `$49E6` to pick a `GEO` or a
  `SQRDATA`.

  The three files are **overlapping windows on one world, thirteen columns
  apart**, west to east: the data agrees at 179 of 180 squares in the overlap
  and the edge-crossing arithmetic closes exactly. The playable world is
  **40 x 32**. Travel position is `$49C3`/`$49C4`, a **separate pair** from
  `$49C0`/`$49C1`, which is why walking into a site and out again puts you back
  on the square you left. Travel is eight-way.

  **Sites are hidden by painting plain terrain over them**, so the travel map is
  never saved: it is rebuilt from the file plus a handful of flag bytes. And
  clearing the Stojanow pollution swaps `ECL1A`'s impassable-terrain table,
  dropping the twelve river tiles — the river opens to travel.

- ~~**The combat map's row stride.**~~ **`$0612 + 1`, not `$0607`.**
  `GDRIVE00 $C3AF` is `LDX $0612 / INX / STX $4B`. In a fight the two agree at
  56 and the difference never shows, which is why the wrong one was written down
  and a test pinned it. `SQRPACI00` has `$0607` = 20 against a true 18, and
  18 x 36 = 648 is exactly the grid in front of the glyph table in a `SQRDATA`.
  Reading `$0607` outdoors would shear every row two squares along.

- ~~**The ECL instruction set.**~~ **Decoded whole: 62 opcodes, and every byte
  of every script accounted for.** The VM is in `DUNGEON`, entry `$1581`,
  dispatch at `$1590`, with three 62-entry tables end to end — handler low
  `$15A9`, handler high `$15E7`, operand-set count `$1625` — and the operand
  evaluator at `$1663`. `DUNGEON` is byte-identical on all eight disks and is
  the only file of 983 carrying the count table.

  **178,035 bytes across all 30 scripts, 0 derails, 0 unresolved.** Everything
  is either reached by traversal, referenced by an operand, a well-formed dead
  island (182 bytes in total, each parsing cleanly), or one trailing `$00`.

  Three opcodes we had — `$3E DUMP`, `$3F FINDSPECIAL`, `$40 DESTROYITEMS` —
  **do not exist in this game.** They came from *Curse of the Azure Bonds*. No
  script uses one, so nothing was corrupted by carrying them.

  **One of our operand counts was wrong and two of the game's own are:**

  | opcode | we said | `$1625` says | the handler fetches |
  |---|---|---|---|
  | `$36 ADDNPC` | 1 | 1 | **2** — ours was the bug; `ECL1E` decoded at 7% |
  | `$0C SETUPMON` | 3 | **2** | 3 |
  | `$29 ENCMENU` | 14 | **13** | 14 |

  `$1625` is read at exactly one place, the false-`IF` skip at `$1BB5`. So an
  `IF` immediately before one of those three would desync the VM and everything
  after it would be garbage — **a latent engine bug in the shipped game.** A
  sweep of all 16,233 instructions finds no script that does it, so it never
  fires. SSI got away with it.

  The evaluator also validates nothing: operand codes `$04`-`$7F` fall through
  to the `03` path and `$82`-`$FF` to `$81`. A decoder that raises on those
  derails where the game does not, which is what sank `ECL0B`, `ECL0F` and
  `ECL10` in the previous attempt.

  Memory: 374 distinct addresses. `$6E79`-`$6E82` are a script's private
  registers, referenced by no overlay. `$9800`-`$98FF` is a string workspace
  where monster-group names are composed. `$49F2` is the current ECL id, read
  by 14 scripts. And `ECL01` and `ECL11` test attribute **bit 7**, which nobody
  had noticed.

- ~~**The `WALLDEF` slice geometry, and the 3D renderer.**~~ **Both found. The
  geometry was never a rectangle, which is why every attempt to find its width
  failed.**

  A 156-byte slice is **nine sub-pictures packed end to end**, one per distance
  and side:

  | offset | w x h | piece |
  |---|---|---|
  | 0 | 1x2 | distance 2, facing |
  | 2 / 6 | 1x4 | distance 2, left / right |
  | 10 | 3x4 | distance 1, facing |
  | 22 / 38 | 2x8 | distance 1, left / right |
  | 54 | 7x8 | **distance 0, facing** |
  | 110 / 132 | 2x11 | distance 0, left / right |
  | 154 | 1x2 | far-wall filler column |

  2+4+4+12+16+16+56+22+22+2 = 156 exactly.

  **This retro-explains the evidence that made 13x12 look right.** The earlier
  pass found runs of seven identical bytes at absolute offset 54-60 in 49 of 90
  slices and read them as a row artefact. They are the **7-wide distance-0
  facing wall**, which begins at offset 54. The anomaly was the answer.

  **The renderer is `GDRIVE01`**, resident at `$C000`-`$CA00`, loaded into
  `LIBRARY` slot 0 by `DUNGEON $134F`; `$C003` draws the view into an 11 x 11
  cell viewport at `$CC7B`. `$C48A` computes a slice base as `(nibble - 1) *
  156`, and 23 draw steps walk tables at `$C215`/`$C22C`/`$C243` and
  `$C586`-`$C5E2`, back to front.

  **`$7A00` is not the renderer** — it is the general RLE expander, and its
  encoding is **count-then-value**. The earlier `WALLDEF` colour decode had it
  the other way round: 548 of 780 bytes wrong.

  **The boot images unpack, and that is worth more than this task.**
  `POOLRB`/`POOLRC` are sparse memory images: a table of 5-byte records
  `(word A, fill byte, word B)` naming runs that are *not* stored, with literal
  data following in address order. It closes exactly for both — 20395 + 10325
  and 10507 + 20213, each 30720. `POOLRB` is the resident code, and `LIBRARY`
  sits inside it at `$2C48`, which independently confirms the container. Every
  resident routine is now reachable.

  **Verified by rendering.** `work/analysis8/view.py` reimplements the view and
  draws `GEO00` at (4,2) facing east — the square a VICE capture was taken on,
  its status line reading `E 16:47 4,2`, matching `PORSAVE11`. **The geometry
  agrees cell for cell**: the same wall, the same two windows in the same
  places, the same ground plane and left-edge wedge.

  **What does not agree is colour.** Ours draws the pattern without the palette
  the game applies, and `$D022`/`$D023` during the 3D view are unexplained:
  static analysis finds exactly two writers, `GDRIVE01`'s init and
  `DUNGEON $0A7B`, and neither accounts for the brick red on screen. **Open**,
  and one breakpoint after `LIBRARY $407B` reading `$D020`-`$D023`,
  `$49FD`-`$49FE` and `$6DDB` would settle it.

- ~~**The effect and status system at `$4900`.**~~ **Decoded, and the game names
  its own effects.** This is the finding that unblocks status icons, and it
  turned on locating a table rather than on collecting specimens.

  **`ECL65` loads at `$9900`, and its first 469 bytes are 67 records of 7.**
  One per spell id 1-56, then eleven item-only effects 57-67 (item byte `+14` =
  80-90). `CAMP $1429` computes `$9900 + (id - 1) * 7` and copies the record to
  `$28C7`:

  | byte | meaning |
  |---|---|
  | `+0` | duration: bits 0-5 the count, bits 6-7 the unit |
  | `+1` | duration per caster level |
  | `+2` | non-zero if castable outside combat |
  | `+3` | **effect id** in the low 7 bits; **bit 7 marks a cleric spell** |
  | `+4` | message index, `+ 57` into `SPELLN00` |
  | `+5`, `+6` | the out-of-combat handler |

  `SPELLN00` from index 57 holds the game's **own status wordings** — `IS
  BLESSED`, `IS ENLARGED`, `IS HASTED`, `IS SILENCED`. So the names are the
  game's, not ours. **40 ids named**, most CONFIRMED. `SPELLE04 $A79F` writes a
  slot, `ECL64 $9A0D` is its combat twin, and `LIBRARY $3FE4` is the lookup: `A`
  the id, `X` the owner, `A = 0` meaning "find a free slot".

  **Confirmed live.** BLESS wrote six slots, id 1, one per party member,
  duration `$06` — byte for byte the table's record 1. ENLARGE on BRUTUS wrote
  id 12, owner 5, duration `$0A`, and magnitude **`$E2` = `$80 | 98`**, BRUTUS
  being strength 18/**98**: the magnitude is the strength to put back. CURE
  LIGHT WOUNDS wrote nothing, its `+3` being `$80`, id 0.

  **Two of our own claims were wrong.** `$4B80` is *not* zero in every save --
  `PORSAVE13` carries six slots with magnitude 1 that nobody had looked at. And
  the clock is **six digits**, `$49C6`-`$49CB`, limits `0A 0A 06 18 1E 0C` from
  `$A83C`: the three we knew are minutes, tens of minutes and the hour, and the
  day and month follow. Expiry clears only `$4900,X`, leaving the other three
  arrays as residue — which is exactly what that save is.

  **Effect ids and trait codes are separate vocabularies.** They meet only at
  `LIBRARY $4028` and the `$9AD5` dispatch. Ids run 1-71, item `+15` codes take
  `$80`-`$8B`, monster traits 64-139; the single overlap is 71 and no monster
  carries it. **`goldbox/traits.py` must not be reused for the live panel** -- which
  independently confirms what the combat-view work suspected.

  Still unnamed: ids 49, 54, 58, 59, 60, 95 and 102, all combat-only, set by
  literals in `SPELLE00`/`SPELLE01` with no name anywhere in the data.

- **The combat log's two defects, found in a slums fight.** Donald reported
  "readable data, but also a lot of garbage" and suspected he had opened the
  editor while another task was rewriting it. He had not: both defects are in
  `automap/combatlog.py` and both reproduce off a captured fight.

  **The instrument.** `work/combatlog/fight.py` drives one fight and records
  every poll — the four window bytes, the cursor, `$49FC`, the jiffy clock and
  all 1000 screen codes — and folds each frame through `CombatLog` at the same
  instant, so the log's output can be set against the screen it came from.
  1428 frames at ~0.18 s, six characters against a pack of orcs at (14,0) in
  the Slums. `work/combatlog/replay.py` re-runs the file through the reader,
  which is how both fixes were checked without a second fight.

  **Defect one: `$03F2`-`$03F5` are not always the message window.** The
  command bar sets them to `00 28 18 19` — columns 0 to 39, row 24 — every
  time it prints `GUARDING`, `MOVE VIEW` or `YOUR TEAMMATE IS DYING`, and
  `plausible_window` accepted that as readily as the real thing. `band` then
  sliced **whole rows 10 to 24**: the combat map, drawn in the game's own
  glyphs, plus the border and the command bar. 29 of the 1428 frames carried
  `00 28 18 19` and four of them reached the log, each as one "message" that
  begins `$   &'(   /01         $                $$   )*+   234` and runs for
  520 characters. That is the garbage, and it is character for character what
  the screen's lower left holds.

  The columns were never in doubt — `COMBAT $0970` is `17 27 01 17` on all
  eight sides — so `message_window` now takes them from `COMBAT_WINDOW`
  whenever the live bytes describe some other window, clamps the bottom to row
  22, and returns `top` as **None**, because `$03F4` then belongs to that other
  window and reading it would put a false row into the split and fire the
  restart edge on a command-bar print.

  **Defect two, two ways.** Every killing blow was logged twice. `$29BA` puts
  a follow-up under what is already showing and `$29B7` clears from the
  follow-up's own top, so an eight-row block goes back to being the five rows
  it grew from; that shorter frame was "anything else", which committed the
  block and made the residue a new one, and the next clear committed its first
  message again. `_shrank` now recognises a block losing its bottom rows as
  the same block. The second way is `$03F4` = 1 — `$0970`'s own top, restored
  when the game repaints the acting character's panel at the end of a turn —
  which looked like `$2983` running and fired the restart edge; `top` below
  row 10 is now discarded.

  With both fixed the same 1428 frames yield **58 messages, no garbage and no
  duplicates**, against 24 messages and four garbage blocks in the first 649.

  **The decisive comparison.** Frame 1408, `$03F2`-`$03F5` = `17 27 0F 17`:
  screen rows 10-14 of columns 23-38 read `SILAS` / `ATTACKS` / `ORC` / `AND
  HITS FOR 8` / `POINTS OF DAMAGE`, and the log line is `SILAS ATTACKS ORC AND
  HITS FOR 8 POINTS OF DAMAGE`. Identical.

  **And one correction to `docs/110`.** Rows 1-9 of the same band are not the
  party panel; they are the **acting combatant's** panel — name, `HIT POINTS
  n`, `AC n`, the readied weapon. The party panel is the world screen's.

- **How long a combat message lives: 60 jiffies, measured.** `$49FC` read 2
  for the whole fight, as `INIT $09AC` sets it. Timing the window from first
  text to clear against the KERNAL jiffy clock over 49 messages: **60-62
  jiffies** for a block with no follow-up (exactly the second the delay loop
  predicts), 72-74 where a follow-up was added, and 156-169 or 336 for a block
  whose follow-ups came in sequence. So the minimum a poller has to catch is
  **one second of emulated time**, and at 200 ms that is five frames.

  The log does not stall the fight; it speeds it up. Polling at 0.178 s
  through a short-lived monitor connection ran the machine at **1.121× real
  time** — 17471 emulated jiffies in 259.8 s — which is the 14.3 ms per resume
  of "The binary monitor", plus the connect.

- **Keys do not reach the game while a binary-monitor client holds the
  socket.** Thirty XTEST `Right` presses through a `ViceTarget` moved nothing;
  the first press after it closed moved the highlight. So a driver that both
  watches and types must **connect, read, close** for every poll, the way
  `tools/session.py` does — which is also why `automap` and a driving script
  cannot be the same process. Two smaller ones, both of which cost an hour:
  a `press any key` prompt needs a **0.25 s hold**, not the 0.10 s the menus
  take; and answering `INSERT SIDE # n` needs the image **re-attached even
  when it is already in the drive**, because the 1541 only notices a disk
  *change*. Without the re-attach the game asks again for ever.

- **`work/drive/SLUMS.D64` cannot be loaded.** Not a game fact, a warning: the
  party comes up, `BEGIN ADVENTURING` prints `OUTWARD BOUND ...`, and the
  loader then asks for side 3 in a loop, requesting **`WALLSET00`** — a file
  that exists on none of the eight sides. `PORSAVE14` in the same area loads
  in one go. Use the player's own saves for driving work.

- **P15: entering `NEWECL`'s tail at `$2034` is safe. CONFIRMED.** The
  experiment `docs/118-debug-mode.md` says the whole FastTravel To plan rests on.
  From the Slums at (14,0), the five writes of section 3 and `PC = $2034`:
  the game loaded, asked for the disk, and came up in **New Phlan**.
  `ResidentGeo.identify()` returned **`GEO00`** — an exact 1024-byte match
  against the disk copy — with `$6E1B` = 0 and `$6E15` = 0. The party then
  walked (7,7) → (8,7), so the arrival is a real square and not a wall.

  Done twice. The PC when the writes were made was `$2E4E` the first time —
  the key fetcher, called *from* the key-wait loop — and `$10CA` the second,
  the loop itself. Both worked, which is `$203A`'s `LDX $03BF / TXS` doing
  exactly what the plan predicted: the call depth being interrupted does not
  matter.

- **P16: `$C04B` survives the overlay restart. CONFIRMED.** `07 07 01` was
  written before the fasttravel and read back unchanged afterwards, with `$49C0`
  flushed to match by the `JSR $1A3C` at `$2034` and the status line reading
  `E 21:41 7,7`. So the arrival square is written **before** the load, as
  section 3 has it, and no second stop on a checkpoint is needed.

  **But `$49F2` does not survive.** Write 3 put the departing area (20) there;
  after the fasttravel it read **0**, the *target*. Whatever sets it runs after
  `$2034` — `$2011`-`$2016` is skipped by construction, so it is something on
  the `$0809` restart path. The consequence is worth having: entry 4's
  `COMPARE [$49F2], <own id> / IF= / EXIT` will always compare **equal**, so
  the arriving script takes its "re-entry from itself" branch and never writes
  its own arrival square. Case 1 of "Where the party lands" — *the arriving
  script sets it, write nothing* — therefore does not apply to a fasttravel:
  **the fasttravel must always supply the square.** PROBABLE, on one observation
  and the script shape.

- **P17: the loader prompts. CONFIRMED**, where `docs/118` had it PROBABLE.
  With POOL2 in drive 8 and `$6E12` = 3, the fasttravel printed **`INSERT SIDE # 3,
  AND PRESS ANY KEY.`** on row 24 and waited there indefinitely. So a fasttravel
  harness needs a disk step, and it can be a plain text-monitor `attach` — but
  see the re-attach rule above.

- **P20: `ECL1E` is the demo.** Area 30, POOL1, no map, no name, and no static
  `NEWECL 30` anywhere — because nothing in the game fasttravels to it. FastTraveling to
  it was, as `docs/118` guessed, the cheapest way to find out: the screen came
  up with two extra characters in the roster (`RESTAL` and `TARRAN`, AC 2, 30
  hp), a picture, and marketing copy in the message area — `SEE EVERY CITY,
  CASTLE, CAMP, AND DUNGEON IN BEAUTIFUL 3D POINT OF VIEW.` It then walked
  itself into `GEO12` and started a fight. It is the attract mode the credits
  screen starts when it is left alone, and it runs on the same ECL VM and the
  same area machinery as the game. CONFIRMED.

- **P43: `$49F2` *does* survive the overlay restart. REFUTED, and the reason
  the first reading said otherwise is worth more than the answer.**

  The claim was that the fasttravel writes the departing area to `$49F2` and the
  arriving script reads back the *target*, so entry 4's
  `COMPARE [$49F2], <own id>` always compares equal and FastTravel To must always
  supply an arrival square. Four fasttravels across three areas say it does not.

  | fasttravel | `$49F2` written | read during the load | read once the area settled |
  |---|---|---|---|
  | 20 → 21 Sokol Keep | `$14` | `$14` | `$15` |
  | 21 → 20 the Slums | `$15` | `$15` | `$14` |
  | 20 → 21 again | `$14` | `$14` | `$15` |
  | 23 → 26 wilderness | `$17` | — | `$1A` |

  So it holds the departing id right through the load and turns into the
  arriving id afterwards. **Nothing in the bytecode writes it** — 16
  references across all thirty scripts and every one is a `COMPARE`. Scanning
  the resident `DUNGEON` window for `F2 49` finds exactly two stores, and the
  second is the culprit: `$19E1` is `LDX #$03 / JSR $19FC / LDA $6E1B /
  AND #$7F / STA $49F2 / RTS` — the same three instructions as `$2011`-`$2016`
  but run *after* `$6E1B` has been updated. A snapshot taken when the party is
  standing in the new area therefore always reads the current id, whatever the
  fasttravel wrote, which is precisely the observation P43 was built on.

  **The decisive test was `ECL16`.** Area 22's entry reads
  `COMPARE [$49F2], 22 / IF= / EXIT` then `LOADFILES 22` then
  `COMPARE [$49F2], 23 / IF= / EXIT` then `SAVE 15, mapX / SAVE 0, mapY /
  SAVE 2, mapDir` — that is, "came from myself, do nothing", "came up from the
  lower pyramid, keep the square", "came from anywhere else, stand at the
  entrance". FastTraveled into area 22 with `$49F2` forced to 23 and the arrival
  square set to (3,3) facing south, the party stood at **(3,3) facing south**.
  The 23 branch fired. The arriving script read the value the fasttravel wrote.
  CONFIRMED.

  Consequences, all the other way round from the prediction: entry 4 works as
  designed under a fasttravel, an arriving script *will* place the party if it has a
  rule for it, and `newecl_writes()` needs no change. `automap/actions.py`'s
  note on `FASTTRAVEL_FROM` now carries the story.

- **P43 corollary: the arriving script's placement can be suppressed, and that
  is how to fasttravel onto a chosen square.** `ECL15`'s entry gates on `$4A02`, not
  on `$49F2`: `COMPARE [$4A02], 0 / IF<> / EXIT`, then `SAVE 1, [$4A02]` and
  `SAVE 8, mapX / SAVE 14, mapY`. `$4A02` is inside the `$4A00`-`$4A1F` scratch
  page the fasttravel zeroes, so it is always 0 on arrival and the party is always
  put on (8,14). Writing `$4A02 = 1` *after* the zero fill and before the jump
  left the party on the square the fasttravel asked for — twice, at (7,13) — and the
  square's own script fired on arrival. So a fasttravel harness that wants a specific
  square needs one extra byte per area, not a general mechanism.

- **P41: the Sokol Keep dead elf is a shipped bug. CONFIRMED, in game.**

  `ECL15` guards the elf on two flags: `$4A25`, which **no instruction in the
  game writes**, and `$4A00`, which `$9C92` sets to 255 when you choose ATTACK
  and which `DUNGEON $202A` zeroes on every area change. Predicted: the
  encounter comes back every time you re-enter the keep.

  Driven, at (6,13) in `GEO15` — the one square in that map whose script id is
  1, and `$99E6`'s `ONGOTO` sends id 1 to `$9ADF`:

  | step | what the game printed | `$4A00` |
  |---|---|---|
  | first entry, step onto (6,13) | `THE SKELETON OF A LONG-DEAD ELF LIES HIDDEN BY ROCKS AND REEDS…` then `WHAT DO YOU DO? LEAVE SEARCH ATTACK TALK` | `00` |
  | chose ATTACK | `YOU HACK THE BODY TO BITS.` | `FF` |
  | stepped off and back on | `YOU SEE THE PITIFUL REMAINS OF A DEAD ELF.` | `FF` |
  | fasttraveled out to the Slums and back in, stepped onto (6,13) | `THE SKELETON OF A LONG-DEAD ELF LIES HIDDEN BY ROCKS AND REEDS…` again | `00` |

  So the quest-flag split is exactly as `docs/41` has it, and SSI put this
  guard on the wrong side of it. Note that SEARCH — taking the scroll — writes
  no flag at all, so it never suppresses the encounter even within one visit.
  This is a clean end-to-end confirmation of the scratch-versus-persistent
  work: the flag that survives is the one in `$4A20`-`$4AF8`, and `$4A25` is in
  that range but dead.

- **P36: both constants pinned, and one of them was wrong. CONFIRMED.**

  `CMD_REGISTERS_AVAILABLE` (`0x83`) **is** served by this VICE build. The
  claim that it is not has been in `automap/actions.py` and `automap/vice.py`
  for months and is simply false. It answers with `A`=0, `X`=1, `Y`=2,
  **`PC`=3** (16 bits), `SP`=4, `FL`=5, plus `LIN`, `CYC`, `00` and `01`. So
  `PC_REGISTER = 3` was right, and `pc_register()` now asks instead of
  believing.

  `KEY_WAIT`'s upper bound was a guess taken from `$10EE`. 400 PC samples of an
  idle party in the world land on nine addresses in the loop and nothing above
  them:

  | address | share | | address | share |
  |---|---|---|---|---|
  | `$10C2` | 5.8% | | `$2E4E` | 9.0% |
  | `$10C5` | 8.8% | | `$2E51` | 6.0% |
  | `$10C8` | 7.2% | | `$2E53` | 4.5% |
  | `$10CA` | 4.0% | | `$2E56` | 4.5% |
  | `$10CC` | 5.8% | | `$2E58` | 4.8% |
  | `$10CF` | 5.2% | | `$2E65` | 5.8% |
  | `$10D1` | 5.5% | | `$2E67` | 4.8% |
  | `$10D3` | 2.2% | | `$2E6A` | 5.5% |
  | `$10D6` | 7.5% | | KERNAL IRQ | 2.2% |

  The code agrees. `$10E0` is the `JMP $10C2` that closes the loop,
  `$10E3`-`$10EB` is its own exit tail (`LDA #$01 / STA $2B79 / LDA $03CB /
  RTS`), and `$10EC` starts a different routine — `LDA #$00 / STA $6DD5`. So
  the window is `$10C2`-`$10EB`, written `(0x10C2, 0x10EC)`.

  **And the fetcher needed adding.** `$2E4E`-`$2E6A` is the key reader the loop
  calls: `LDA $DC00 / AND #$1F / STA $03F0` for the CIA row, then `LDA $C6` and
  the KERNAL buffer at `$0277` into `$03CB`, `RTS`; `$2E65` is the no-key path
  writing `$FF`. Half the idle samples are in it, so refusing it made FastTravel To
  fail about half the times it was pressed — measured, five refusals across
  seven attempts in this session. It is called *from* the loop, so `$203A`'s
  `LDX $03BF / TXS` discards exactly the same nothing, and P15 had already
  fasttraveled successfully from `$2E4E`. `KEY_FETCH = (0x2E4E, 0x2E6B)` is now
  accepted alongside `KEY_WAIT`.

- **P20: the overland map fasttravels like everything else. CONFIRMED.** FastTraveled from
  area 23 to area 26 with no arrival square at all. The load ran, `$6E1B` came
  up `$1A`, **`$49E6` went 1 → 0 by itself** — the arriving script sets it, the
  fasttravel does not — the status line read `OUTDOORS 21:35 0,0` and the command bar
  `1-8, RETURN OR BUTTON`. `$C04B` afterwards held `4C 2F C5`, i.e. not a
  square at all: outdoors `GDRIVE00` is not the resident overlay and the travel
  position is `$49C3`/`$49C4`. So writing an arrival square for areas 25-27 is
  not merely unnecessary, it writes over somebody else's code.

- **P20: `$6DD5` is not "a step was taken", or not only that. Demoted to
  GUESS.** A store watchpoint on `$6DD5`, with the move key injected through
  the KERNAL buffer so the held monitor connection could not swallow it, caught
  **one** write per keypress and always the same one: `$10EE`, `STA $6DD5` with
  A = 0, i.e. the flag being *cleared* as the key is fetched. The write at
  `$0B05` — which is real, `A5 B0 / 8D D5 6D` sitting between `JSR $C027` and
  `JSR $19CA` in the resident `DUNGEON` — **did not execute**, on either

  * an ordinary forward step, (3,3) → (2,3) in `GEO16`, script id 0, or
  * a step that fired a square script, (7,1) → (6,1), script id 17, which
    printed `AS YOU MOVE THROUGH THE ROOM THERE IS A FLASH, AND YOU SUDDENLY
    FIND YOURSELVES ELSEWHERE.` and moved the party to area 23.

  and `$6DD5` read `00` before and after both. Fifteen seconds of emulated
  running were allowed after each hit. So either `$0AF0`'s dispatch block
  belongs to a mover we did not exercise, or the eighteen scripts that open
  with `COMPARE [$6DD5], 0 / IF= / EXIT` always take that `EXIT`. The second
  reading is not absurd — `ECL15`'s `$9918` gate is the "do you want to take a
  boat back to Phlan?" prompt, and it did not appear on any of the three
  arrivals in Sokol Keep — but it is a large claim on one area's evidence and
  it stays a guess until the mover is found. The two writers are not
  symmetrical and the old note that "`$0B05`/`$10EE` write it" hides that:
  `$0B05` sets it from zero page `$B0`, `$10EE` clears it.

- **P19 item 7: a second fight, and still no block past row 22. Still
  UNKNOWN.** 1050 frames at 0.18 s over a six-character fight in Sokol Keep,
  logged the way `work/combatlog/watch.py` does it. `$03F2`-`$03F5` held
  `17 27 01 17` (the acting combatant's panel) for 661 frames, `17 27 0A 17`
  for 135, `17 27 0F 17` for 48 and the command bar's `00 28 18 19` for 206 —
  the last of which is defect one still being caught correctly. The deepest row
  any message block reached was **17**; the cursor row after a message was 13,
  14 or 17 and never more. Three frames showed non-blank text as far as row 22
  and all three were the combat map's own glyphs under a stale window, not a
  message. So whether the region scrolls or overwrites is still open, and the
  fight to settle it needs to be one with long messages — spell descriptions,
  a `PARLAY`, or a death-and-experience sequence — rather than simply a long
  one. This one stalled into `GUARDING` and produced 16 messages in 1050
  frames.

- **P18: experience is writable live and survives the game's own save.
  CONFIRMED. The level-up diff is not taken — the trainer is somewhere else.**

  `0x0E8` written into the running machine at `$4D00 + slot*$100 + 0x0E8`,
  three bytes little-endian, for all six of Donald's characters (2000 to 5002,
  each past its class's level-2 threshold in `goldbox/levels.py`). `ENCAMP → SAVE →
  SAVE GAME` onto a copy of the save disk, and `SAVEDGAME0` read back off that
  disk carries the new values. So the half of route (b) that this project
  controls works end to end.

  **The trainer does not.** `docs/119-test-party.md` says "drive to the training
  hall, `7,2` in New Phlan"; `7,2` carries script id 14 and `ECL00`'s `ONGOTO`
  sends 14 to `$AE6A`, which does nothing. The training schools are inside
  **area 11, `ECL0B`**, one of the four mapless areas, along with the duelling
  arena — `'WE TRAIN ONLY <class> HERE. DO YOU WANT TO TRAIN?'` at `$A0DD`.
  `GEO00` reaches it from script id 10 at `(6,1)` and `(6,2)` and from id 17 at
  `(9,0)`, both ending in `NEWECL 11`.

  **And a fasttravel cannot get in.** `ECL0B`'s entry reads `$6E82` — set from the
  departing square's attribute byte by `AND 127, ATTR, [$6E82]` — and walks
  `$9800` from 10 to 18 against it to choose a school. FastTraveled in three times,
  once with `$6E82` forced to 10: every time `$6E1B` went `$8B` → `$0B` → `$00`
  inside eight seconds and the party was back in New Phlan. This is the first
  area found that a fasttravel cannot enter, and the reason is instructive — the
  target reads state the *departure* was supposed to leave behind, which is
  exactly the class of assumption `FastTravel`'s standing warning is about.

  A save with the boosted party is at `work/drive/LVBEFORE.D64`, in New Phlan,
  including a live **magic-user/thief** (LADY KATHERINE, `class_bits` 5, two
  non-zero entries in `0x0C9`-`0x0CC`) — the multi-class specimen
  `docs/90-specimens.md` wants. Next session needs only to get one character
  through `ECL0B`'s menu.

- **A fasttravel out of an overland area into an indoors one wedges the loader.**
  Area 26 → area 0 with `$49E6` left at 0: the game asked `INSERT SIDE # 3` and
  went on asking for ever, `PC` in the KERNAL serial routines at `$EEAx`, no
  KERNAL filename to read because the loader is the game's own. Re-attaching,
  attaching a different image first, and poking `$49E6` back to 1 after the
  load had started all failed. The same fasttravel made from an indoors area (20 →
  0) worked first time. So `$49E6` has to be right **before** `$2034`, and
  `FastTravel`'s existing "`$49E6` is 0, so LOADFILES will ask for a SQRDATA" warning
  is describing a hang rather than an inconvenience.

- **P51: Amiga Pools of Darkness accepts a C64 Pool of Radiance export as a
  character file. CONFIRMED, and it deletes the premise of
  `docs/124-amiga-port.md` §2.2.**

  Method, one FS-UAE session on the untagged three-disk rip, Kickstart 1.3.
  `work/amiga/adfedit.py` replaced the contents of two of disk 3's twelve
  `Save/*.pc` files in place — `KILLKILL.pc` = `tests/fixtures/brutus.chr`
  verbatim (582 bytes, `$6B00` load address included), `INRANGE.pc` = the same
  with the load address stripped (580) — leaving the other ten genuine.
  `PLAY → ADD CHARACTER → POOLS`.

  **The picker listed all twelve**, the two C64 files as blank names, and
  `ADD` put one of them in the party: `NAME` empty, `AC 60`, `HP 0`, and a full
  character sheet — `MALE`, `0 YEARS`, `LAWFUL GOOD`, `ELF`, `CLERIC`,
  `LEVEL 15/16/17/17/12/1`, `HIT POINTS 0/0`, `STR 0 INT 40 WIS 2 DEX 0 CON 0
  CHA 0`, `ARMOR CLASS 60`, `THAC0 4`, `DAMAGE 0D0`. So there is **no length
  check and no signature check** on the `Pools` import path. The control (a
  genuine `.pc`, TROND) added normally in the same session, so the picker was
  working.

  **Which of the two loaded is decidable from the sheet.** `INT 40 WIS 2` are
  `brutus.chr` file offsets `0x73` and `0x75`; the 580-byte variant would put
  `40` in STR. So the party member is the **582-byte** file, and the six
  abilities are read as base/current pairs at `.pc` offset `0x70` with the
  *second* byte of each pair displayed — `docs/124` §1.5's reading, now
  confirmed against a controlled input rather than twelve maxed specimens.

  Two more offsets fall out of the same sheet, both from `brutus.chr`, both
  PROBABLE: **name is 15 characters at `0x60`, NUL-terminated at `0x6F`**, and
  **per-class levels are six or more bytes from `0x9D`** (`0f 10 11 11 0c 01` =
  the displayed 15/16/17/17/12/1). The name was re-confirmed by a second probe
  whose `0x60`-`0x6E` were `` ` `` through `n`: the list drew
  `` `ABCDEFGHIJKLMN ``.

  **That probe also found the one check the loader does make.** Its bytes from
  `0x70` to the end were the ascending sequence `i & 0xFF`; the picker read the
  name off it happily and `ADD` then failed with **`DISK READ ERROR`**. Putting
  the genuine `TROND.pc` back — written by the same `adfedit.replace()` — made
  it load again, so the failure is the file's content, not the media and not
  our writer. The likeliest cause is a count inside the record driving a read
  of appended variable-length data past end-of-file, which is also why the C64
  export works: its counts are zero.

  What this does **not** show is a usable import. The sheet is garbage and
  `HP 0/0` is a corpse. The value is that `docs/124`'s blockers 3 and 4 are
  largely gone: the loader tolerates a 582-byte file where the real ones are
  484-524, and it tolerates C64 record bytes sitting where the twelve genuine
  specimens keep Amiga heap addresses (`0x00`-`0x5F`), so **those longwords are
  don't-care on load**. And the whole of phase 4 can now be done by *writing*
  `.pc` files and reading the sheet, which is far cheaper than differential
  saves.

  Session notes for whoever repeats it: FS-UAE's arrow keys never reach the
  Amiga, so the picker's cursor cannot be moved — put the payload in the entry
  the `*` starts on, which is the first row. `*` in that list marks a name that
  matches a party member, not the cursor. The `INSERT INTO DF0` submenu opens
  with the *current* image highlighted, which is what `work/amiga/pod/swap.sh`
  now assumes. Editing the ADF while it is inserted is fine as long as the
  eject-and-reinsert happens afterwards.

- **P18: the level-up diff, taken. CONFIRMED, live and on disk.** The blocker
  was never the trainer; it was the route. Area 11 is entered by *walking* onto
  a square whose `GEO00` script id is 10 or 17 — `ECL00`'s table sends only
  those two to `NEWECL 11` — and the fastest of them is **`(9,0)`**, which is
  also the thieves' school, so one square both enters the area and opens the
  trainer.

  **The map of area 11**, from `ECL0B`'s `AND 127, ATTR, [$6E82]` and its
  `ONGOTO [$9800], 9` after `SUB 10`. Area 11 has no `GEO` of its own: it reuses
  `GEO00`, so these are New Phlan's own squares wearing a second script.

  | attr | `GEO00` square(s) | what it is |
  |---|---|---|
  | 10 | (6,1), (6,2) | the lobby: "…MAGIC USERS AND CLERICS TO GO NORTH AND FIGHTERS AND 'ROGUES' TO GO EAST." |
  | 11 | (6,0) | sign: magic users east, clerics west |
  | 12 | (5,0) | **clerics' school** |
  | 13 | (7,0) | **magic users' school** |
  | 14 | (7,1), (7,2), (8,2), (9,2) | the duelling arena, and the NPC-for-hire offer |
  | 15 | (8,1) | sign: 'FIGHTERS' |
  | 16 | (8,0) | **fighters' school** |
  | 17 | (9,0) | **thieves' school** |
  | 18 | (9,1) | sign: 'ROGUES' |

  Each school writes a class filter into `$6DA8` — `0x71` magic users, `0x72`
  clerics, `0x74` thieves, `0x78` fighters. The low nibble is exactly
  `goldbox.games.CLASS_BITS_CLASSIC`, which is a free corroboration of that table
  and of the fact that the trainer tests `class_bits` at `0x0EB`.

  **The run.** `work/drive/LVBEFORE.D64`, party at (15,1) in New Phlan.
  Route `(15,1) (14,1) (13,1) (12,1) (11,1) (11,2) (10,2) (10,1) (10,0) (9,0)`
  — a Dijkstra over `GEO00` that costs a scripted square ten steps, so it takes
  the two harmless ones (id 2 fires only facing north, id 3 only prints the
  passenger-dock line) and avoids every other. Stepping onto `(9,0)` runs
  `NEWECL 11`; stepping off and back on opens
  `'WE TRAIN ONLY THIEVES HERE. DO YOU WANT TO TRAIN?'`.

  `LOW EXPERIENCE OR WRONG CLASS` is the *class* refusal — the boosted
  "thieves" in this party carry `class_bits` 8, which is **fighter**. The one
  who qualifies is LADY KATHERINE, `class_bits` 5 = magic-user + thief. Then
  `YOU NEED 1000 GP TO TRAIN`; gold was poked to 5000 at `$4EC1` (slot 1 of the
  `$4D00 + slot*$100` staging area) and at `$6BC1` (the loaded record).
  `LADY KATHERINE WILL BE A 2ND LEVEL THIEF` → TRAIN.

  **The diff, 580 bytes read at `$6B00` immediately before and after.**
  Nineteen bytes, sixteen fields:

  | offset | field | before | after |
  |---|---|---|---|
  | `0x076` | hp_max | 5 | 6 |
  | `0x0A0` | level | 1 | 2 |
  | `0x0A5` | thief pick pockets | 30 | 35 |
  | `0x0A6` | thief open locks | 25 | 29 |
  | `0x0A7` | thief find/remove traps | 20 | 25 |
  | `0x0A8` | thief move silently | 20 | 26 |
  | `0x0A9` | thief hide in shadows | 10 | 15 |
  | `0x0AA` | thief hear noise | 10 | **10** |
  | `0x0AB` | thief climb walls | 85 | 86 |
  | `0x0AC` | thief read languages | 5 | **5** |
  | `0x0BD` | silver | 137 | 0 |
  | `0x0C1` | gold | 5000 | 0 |
  | `0x0C3` | platinum | 15 | 816 |
  | `0x0CB` | level_thief | 1 | 2 |
  | `0x0E8` | experience | 5002 | 2500 |
  | `0x0ED` | hp_rolled | 5 | 6 |
  | `0x119` | hp_current (roster) | 5 | 6 |
  | `0x11B` | movement (roster) | 6 | 3 |

  Five things worth carrying away.

  * **`0x0A0` follows the class being trained, not a total.** She is
    magic-user 1 / thief 1 and both `0x0A0` and `0x0CB` went to 2 while
    `0x0C9` stayed at 1.
  * **The per-class array is in class-bit order.** `0x0C9` magic-user,
    `0x0CA` cleric, `0x0CB` thief, `0x0CC` fighter — the trainer moved
    `0x0CB` for a thief level, which is the first *behavioural* evidence for
    that ordering rather than an inference from one specimen.
  * **Two thief skills do not improve at level 2**: hear noise and read
    languages. That matches the AD&D table and is a check on the field names.
  * **Experience is spent, not accumulated.** 5002 → 2500, a drop of **2502**,
    which is exactly twice the thief's level-2 threshold of 1251 — the price of
    one level for a **two**-class character. PROBABLE on one specimen; a
    single-class trainee would settle it in one more visit.
  * **`0x11B` movement is an artefact of the money edit, not of the level.**
    She went from 153 coins to 816, and the roster's movement is recomputed
    from encumbrance. Read the money rows the same way: the fee is 1000 gp, but
    4999 of the gold was poked in.

  The same sixteen slot-block bytes appear on `work/drive/LVAFTER.D64`, and
  **no other character's record changed at all**; `0x119`/`0x11B` live in the
  roster block and so are live-only here.

  One more fact fell out of the save: the header says **area 0, position (9,0)**
  — area 11 does not change the save's area byte, because it is `GEO00` with a
  different script — and the status line read `10,0` for the whole encounter
  while the party was really on `(9,0)`. Same lag as the arena note in
  `docs/70-driving-the-game.md`, now measured against the disk.

  **XTEST stopped reaching the game partway through this session** with no
  monitor client connected — `key Return` did nothing, `kernal 0D` worked
  immediately. Everything after the fifth step was driven through the KERNAL
  buffer: `$49`/`$4A`/`$4B`/`$4D` for I/J/K/M, `$11` for cursor-down in a
  vertical menu, `$0D` to select, `$20` for a `press any key`. That is a
  complete driving vocabulary that does not need XTEST at all, and it is worth
  preferring — it is the only thing that works while a monitor client is held
  open, and here it was the only thing that worked at all.

- **P53: Sokol Keep's dead elf cannot be farmed. The SEARCH branch grants no
  item. CONFIRMED from the bytecode.** `ECL15`'s menu dispatches
  `ONGOTO [$6E79], 4, [$AE0A], [$9B90], [$9C7B], [$9C56]`, so SEARCH is
  `$9B90`, and `$9B90`-`$9C13` is `PRINTCLEAR` of the pouch text, three
  `PROTECTION` calls against `$AF20`/`$AF27`/`$AF36`, "...THE LAST PART IS
  EATEN AWAY", and a `LOADPIECES`. **There is no `TREASURE`, no `FINDITEM` and
  no `ADDNPC` anywhere in it** — the three `TREASURE` opcodes in `ECL15` are at
  `$A19A`, `$A597` and `$A937` and belong to other encounters. The scroll is
  read, not taken; what it carries is the keep's password, which the script
  later compares against at `$9E8D`. So the repeat is text, and only text.

- **P44: nothing in the code limits `spells_known` to seven bytes. The spell id
  is a full byte and the bitmap is indexed `id >> 3`. CONFIRMED, from the
  game's own code.** Scanning every file on the eight sides for the absolute
  operand `$6B78` finds code in exactly one place — `CAMP` — and three sites in
  it, all index-generic:

  ```
  $162B  LDA $29BF        ; the spell id, a whole byte
  $162F  AND #$07         ; Y = id & 7
  $1633  LSR A ×3         ; X = id >> 3
  $1637  LDA $6B78,X
  $163A  AND $165A,Y      ; test
  ...
  $1E9C  LDA $6B78,X
  $1E9F  ORA $165A,Y
  $1EA2  STA $6B78,X      ; set
  ```

  and an enumerator that is the decisive one:

  ```
  $29C5  LDX #$20
  $29C7  ROR $6B78,X
  $29CA  DEX
  $29CB  BPL $29C7        ; 33 bytes, $6B78-$6B98
  $29CD  BCC ...          ; the bit that fell out
  $29CF  LDA $29BC        ; its index
  $29D2  STA $9700,Y      ; emitted as a spell id
  $29D6  INC $29BC
  $29D9  BNE $29C5        ; ids 0..255
  ```

  So the reader sweeps **33 bytes and 256 ids**, not seven and fifty-six. Seven
  is simply what Pool of Radiance *uses*: its highest spell id is 56, which is
  bit 55, which is byte 6. `$6B7F` — the candidate eighth byte — has **no
  absolute operand anywhere on the disks**; the only way anything reaches it is
  through this indexing, which is why save-diffing never moved it.

  Two consequences. **Do not widen the field in `goldbox/layout.py`** — 7 is
  correct for this title and the width is a property of the id space, not of
  the record. And `gap_07f`, the unallocated 25 bytes at `0x07F`-`0x097`, is
  **exactly the rest of the region the enumerator sweeps**, which makes it very
  likely to be spellbook storage held in reserve for a larger id space rather
  than a gap. PROBABLE, and worth checking first on Curse and Silver Blades,
  whose id spaces do run past 56.

---

## Retiring the plan

**What it was.** The project opened with a plan document: five phases — tools,
the library and the knowledge base, discovery by diffing, a CLI editor, a GUI —
written before a single byte of the record was confirmed. All five landed, the
scope grew well past it, and the file was deleted once everything still true in
it had moved to the document that owns the subject. Recorded here is what it got
wrong, because the plan kept its own errors on purpose and they are the part
worth carrying.

**Two decisions survived unchanged** and are now in [README.md](README.md): the
editor is a file tool with zero emulator dependency, and live memory is a
discovery technique rather than something the editor promises. The second is the
one that bent — live memory became a shipped feature, the automapper — and it
held anyway, because the plan had quarantined everything that talks to VICE in
its own package before there was anything to put in it. A boundary drawn early
cost nothing and survived a feature nobody had planned.

**What it got wrong:**

1. **The slot stride.** Both candidates — `$400` × 6 and `$800` × 3 — were
   wrong: it is `$100`, twelve slots, eight of them the party. Every specimen at
   the time held at most two characters, so the zeros between them fitted either
   model. *A hypothesis that sparse data agrees with has not been tested.*
2. **The 44-byte delta** between the exported character and the same character
   inside a save, which the plan called a high-value early target. There was no
   delta: it was an artefact of reading 580 contiguous bytes out of a 256-byte
   slot and running off the end into a zeroed neighbour. A "finding" that is a
   property of how you read the file, not of the file.
3. **Watchpoints, written off as "they never worked".** They work. The fault was
   closing the monitor socket instead of holding it open and `resume()`ing;
   held open, they settled the character-creation question in one run.
4. **"No whole-game disassembly — the overlay data is out of scope."** Right
   about the editor and wrong about the project. Reading the code turned out to
   be the *cheapest* technique here rather than the most expensive: thirty `ECL`
   scripts decoded to the byte, and the level-drain pair, the NPC flag, the
   effect list at `0x0AD` and the class ceilings all named from static scans
   after months of save-diffing had failed on them.
5. **How big a party is** — two wrong answers before the right one. Six player
   characters, eight slots, the last two NPC-only, and the limit is a `CMP #$06`
   in the code rather than a message.
6. **Two field readings.** `0x0B8` was "an unexplained equipment-linked byte"
   and is the NPC flag in bit 7 with the trainer's score-altered marker in bit 0;
   `0x0AD` was "a racial trait mask" and is ten trait slots carrying effect codes,
   seeded per race by `GEN $0BF3`.

**What it got right, and would be worth repeating on a new title:** staging the
work so nothing was built on an unproven layout; making `goldbox/layout.py` a
declarative table with a confidence level per field and generating the
documentation from it; splitting the packages along the packaging boundary
before it cost anything to do; and the one method that carried everything —
save, change exactly one thing, save again, diff. That was later beaten, for
every field that does not need a character to *change*, by comparing six
different characters against each other at once.

---

## The loaded-files cache decodes, and a save needs two entries of it

**Hypothesis.** The 25 bytes at `$4BC0` are one entry per data-file kind, and if
the slot-to-filename mapping can be read, a converted save no longer needs a
template standing in the same area.

**Method.** Static first. `LIBRARY $4225` was already known to be "ensure file
number `A` of kind `X` is loaded"; disassembling it forwards gave
`LDY $4209,X / LDX $4196,Y / LDX $41AA,Y / LDX $4182,Y` — a 25-entry slot→kind
map, then a split low/high stem-pointer table and a length table, 20 entries
each. Reading them at `LIBRARY`'s base `$2C48` tiles the block `$40EB`-`$4181`
into exactly twenty NUL-free stems with no byte left over. Then the emulator, on
slot 2, twice.

**Result. CONFIRMED, and the table is in
[`140-loaded-files-cache.md`](140-loaded-files-cache.md).** Slot index is the
file kind: 0 `GDRIVE`, 1 `SQRPACI`, **2 `GEO`**, 3 `SECSET`, 4 `SQRDATA`,
5 `PIC`, 6 `SPELLN`, 7 `SPELLE`, **8 `ECL`**, 9 `WALLS`, 10 `SPRITE`,
11 `ANIMATE`, 12 `MON`, 13 `BODY`, 14 `HEAD`, 15-17 `WALLSET`, 18-20 `WALLDEF`,
21-22 `CHARPIC`, 23 `COMPIC`, 24 `ITEMFILE`. The byte in the slot is the stem's
two hex digits.

**Six independent checks, all of which could have failed:**

1. The four slots already attributed by other routes — `GEO` at 2, `SQRDATA` at
   4, `SPELLN` at 6, `ECL` at 8 — land where the table puts them.
2. The load-address table at `$41BE`/`$41D7,X` gives `MON` `$6B00`, `ECL`
   `$9900`, `SPELLE` `$A700`, `SPELLN` `$AF00` and `GEO` `$0400`: five addresses
   this project had already fixed by unrelated evidence.
3. The three `WALLSET` slots load 400 bytes apart at `$6650`, `$67E0`, `$6970`,
   and every `WALLSET` file on the disks is exactly 400 bytes. The third ends at
   `$6B00`, where `MON` begins.
4. `LIBRARY $48B3`-`$48C2` loads `HEAD` from `$6BFE` and `BODY` from `$6BFF` —
   character-record offsets `0x0FE` and `0x0FF`, which `goldbox/layout.py`
   independently calls `portrait_head` and `portrait_body`.
5. Across about sixty specimen saves, **every** non-empty entry names a file that
   exists on Donald's disks. Nothing unresolved.
6. `PORSAVE13`'s wall entries read `02 04 01` and `82 84 81` — the `WALLSET` and
   `WALLDEF` triples carrying the same three numbers, which is what
   `LOADPIECES` (`DUNGEON $28DC`) writes from one operand per piece.

**Two corrections to earlier entries in this log.**

* "The stems are not patched in place at all: the loader must copy a stem into a
  scratch buffer" — **wrong, and the reason is instructive.** They *are* patched
  in place, at `LIBRARY $425A`/`$4265`, through `STA ($4C),Y`. The scan that
  concluded otherwise looked for *absolute* stores landing in `$40E0`-`$4150`
  and an indirect store has no such operand. A negative from an operand scan only
  rules out the addressing modes the scan understood.
* `CHARPIC00` "loading at `$8000`" was read off the file's own PRG header, which
  like every overlay's is a lie. The loader puts it at `$9900` (slot 21) or
  `$8C00` (slot 22). Nothing depends on it — `goldbox/icons.py` reads the disk file.

**Why `$FF` is the value that matters.** `GEN $25DE` is
`LDA $4BC0,X / ORA #$80 / STA $6E13,X` for all 25 entries, so **the reload bit a
save carries is discarded and set unconditionally on load**. Setting bit 7 in a
converted save therefore changes nothing whatever, which is why that attempt
hung exactly as the zeroed one did. `$FF` is the only value the load path leaves
alone: `LIBRARY $4225` opens `CMP #$FF / BEQ` and returns without loading.
Zeroing asks for `stem00` of all twenty kinds across eight disks — and
`WALLSET00`, `WALLDEF00` and `ITEMFILE00` do not exist on any disk, so three of
those requests can never be satisfied at all. That is the 105-prompt hang.

**The two entries a save actually needs, tested in the running game.**

*Test A.* `PORSAVE13`, the Slums, with its cache replaced by `$FF` everywhere
except slot 2 = `$14` and slot 8 = `$14`. It loaded, prompted once for POOL2,
drew the view, and put the status line at `W 21:15 15,4` — `PORSAVE13`'s own
square. `$0400`-`$07FF` came back byte-identical to `GEO14`. Walking `KKI`
crossed east into New Phlan at `(0,4)` and printed the gateway text, the cache
following to `GEO00`/`ECL00`/`SECSET00`/`WALLS00`. The engine had refilled

```
01 ff 14 02 ff ff ff ff 14 ff ff ff ff ff ff 02 04 01 02 04 01 ff ff ff ff
```

which matches the genuine save in every slot the arriving script owns; what is
still `$FF` is the lazy half — pictures, sprites, portraits, spell tables, the
icon charset — loaded when something first asks.

*Test B, the one that answers the issue.* `PORSAVE`, a **New Phlan** save,
rewritten to stand in **Sokol Keep** instead: cache `$FF` except slots 2 and
8 = `$15`, plus `$49C0`-`$49C2` = 8,14,0, `$49C5` = `$15`, `$49E6` = 1. It
loaded, ran `ECL15`'s
own arrival — "THE BOAT DISEMBARKS YOU AT SOKAL KEEP." — settled at `(8,14)`
facing north with `$0400`-`$07FF` byte-identical to `GEO15`, and walked. The
cache had refilled itself to `GDRIVE01`, `GEO15`, `SECSET02`, `ECL15` and the
wall triple `01 05 09`. **A template from a different area is no longer needed.**

**A negative to record about test B:** it cannot say whether the arriving script
re-placed the party, because `(8,14)` is both the square written into the save
and Sokol Keep's own arrival square, so the two hypotheses predict the same
result. `$49F2` was set to the target's own id, which `118-debug-mode.md`'s
`COMPARE [$49F2], <own id> / IF= / EXIT` reading says should suppress the
placement — and the boat message printed anyway, which is consistent with
`ECL15 $9A92` gating on the scratch flag `$4A02` instead. The experiment that
settles it is the same save with `$49C0`-`$49C2` = `(8,12)`, a walkable Sokol
Keep square test B reached: coming up at `(8,12)` means the save's square
survives, `(8,14)` means the script placed it.

**One thing test B found that test A could not: `$49EA` is the disk hint.**
`GEN $08BD` is `LDA $49EA / STA $6E12`, and `$6E12` is the `POOL` side the loader
asks for. Test B's template was a New Phlan save, so `$49EA` was `3`, and the
game sat on `INSERT SIDE # 3` looking for `ECL15`, which is on POOL4. Poking
`$6E12 = 4` freed it immediately. Checked against the specimens afterwards: all
eleven New Phlan saves carry `$49EA = 03` and both Slums saves carry `02`,
matching `ECL00` on POOL3 and `ECL14` on POOL2. So `$49EA` is a third byte a
converter has to set, and `docs/117`'s field table currently lists
`$49EA`-`$49EF` among the unattributed gaps.

The build scripts and the driven session are `work/p24/`.

## The travel grid's cache entries, and the outdoor form of the recipe

**Hypothesis.** Outdoors the two-entry recipe holds with **slot 4 (`SQRDATA`)**
in place of slot 2 (`GEO`) — read off `LIBRARY $4209`'s slot→kind map but never
observed — and something has to be said about `$49EA` and whether `$49E6` = 0
puts the engine in travel mode from a cold load.

**Method.** Differential first: the seven game-written wilderness saves
(`work/p3/W1`–`W7`, `docs/90-specimens.md`) against the fourteen indoor
specimens, which localises every byte before any theory. Then two live runs on
pool slot 1, `work/p47/`.

**What the specimens say, before the emulator was touched.** All seven outdoor
saves, areas 26 (`$1A`, window `SQRDATA05`) and 27 (`$1B`, `SQRDATA06`):

| byte | indoors | outdoors (W set) |
|---|---|---|
| cache slot 2 (`GEO`) | the map number, clean | `$80` — the stale indoor map, dirty |
| cache slot 4 (`SQRDATA`) | `$FF` | `$85`/`$86` — the window, dirty |
| cache slot 1 (`SQRPACI`) | varies | `$00` clean |
| cache slot 0 (`GDRIVE`) | `$01` | `$00` |
| `$49C5` | the `GEO` number | **the `SQRDATA` number** — `05`/`06`, not the id and not a `GEO` |
| `$49E6` | 1 | 0 |
| `$49EA` | the area's disk | **7 for area 26, 8 for area 27** — the disk carrying `ECLnn`, as indoors |
| position | `$49C0`-`$49C2` | `$49C3`/`$49C4`, with `$49C0`-`$49C2` left stale |

**Result. CONFIRMED, both live tests.** The recipe generalises with slot 4 in
slot 2's role and nothing else new.

*Test C, the minimal cache on a genuine outdoor save.* `W1.D64` — at rest on
window `1A`, square (5,2) — with the cache cut to `$FF` × 25 except slot 4 =
`$05` and slot 8 = `$1A`. It loaded, prompted for SIDE 7 (the disk hint doing
its job), came up **`OUTDOORS 21:15 5,2`**, and travel-stepped east to (6,2) and
back. `$8C00` read back byte-identical to `SQRDATA05` in **648 of 648**.

*Test D, moving an indoor save outdoors.* `PORSAVE13` — the Slums, indoors —
given the outdoor recipe wholesale: cache `$FF` × 25 with slot 4 = `$05` and
slot 8 = `$1A`,
`$49E6` = 0, `$49EA` = 7, `$49C5` = `$05`, `$49F2` = `$1A`, `$49C3`/`$49C4` =
(5,2), and `$49C0`-`$49C2` left at the template's own indoor square, exactly as
every genuine outdoor save leaves them. From a cold boot it loaded, drew the
travel window, put the party at **(5,2)** — the square the save carried — and
walked. So `$49E6` = 0 *is* sufficient from a cold load, and slot 2 never needs
writing: the refilled live cache read `GDRIVE00`, `SQRPACI00`, slot 2 still
`$FF`, `SECSET05`, `SQRDATA05`, `ECL1A`, which is `LOADFILES`' outdoor branch
exactly as `140-loaded-files-cache.md` reads it.

**The placement question is settled outdoors, unlike test B indoors.** A fasttravel
with `$49C3`/`$49C4` = (0,0) came up at (0,0) (write-up lost, `work/reports/p20-arrivals.md`);
test D with (5,2) came up at (5,2). Two different values, both honoured — on a
load the arriving script does not re-place an outdoor party, and a converter's
square survives.

**A loose end worth recording: the hidden-site paint did not happen on either
load.** The write-up, `work/reports/p3-saves.md`, is lost; it measured the walk-in case at 647/648, the
one difference being the nomad camp square (12,11) painted `$39` over the
disk's `$37` while its flag is clear. Both p47 loads read **648/648 — no square
painted**, on the same flag bytes (test C is W1's own flags verbatim).
SPECULATIVE, mechanism unknown: perhaps the forced reload of a dirty slot 4
runs after the script's paint and clobbers it, in which case loading an outdoor
save shows undiscovered sites until the next repaint — a player-visible bug
candidate. The experiment: load the unmodified `W1.D64`, read `$8C00`; if it
too is 648/648 the cache edit is exonerated, and walking the party within sight
of (12,11) says whether the player is actually shown the camp.

**What this leaves for the converter.** The C64 side is closed: the refusal in
`goldbox.dos.apply_file_cache` for areas 25–27 can be replaced by the recipe above
(slot 4 = the `SQRDATA` number, slot 8 = the id, `$49C5` = the `SQRDATA`
number, `$49E6` = 0, disk from `goldbox/areas.py`, position into `$49C3`/`$49C4`).
The **DOS side is not**: none of the three DOS specimen saves is outdoors, so
where a DOS save keeps the travel square is unmeasured. PROBABLE by the
variable-array mapping that already carried `$49C5` and `$49F2`, it is
`goldbox.dos_savegame.word` at `$49C3`/`$49C4` (it was `savgam_word` when this
was written; #64 renamed it); the experiment is one DOS save made on the
overland map, its words at those addresses against the on-screen position.

Build scripts, runner, logs and screenshots: `work/p47/`.

## Does the arriving script re-place the party? Yes, when it means to

**Hypothesis.** #24's test B could not say whether `ECL15` placed the moved
party or the saved square survived, because `(8,14)` was both. The clean test is
the same build carrying `(8,12)` — a walkable square that is neither.

**Method.** `work/p24/build2.py`'s save-moved-to-Sokol-Keep rebuilt with
`$49C0`-`$49C2` = `(8,12,0)` and one benign extra, `$49EA` = 4, so the run does
not sit on the disk-hint hang test B had to poke through. `$4A02` — the scratch
flag `118-debug-mode.md` reads as the gate on `ECL15 $9A92`'s message-and-place
branch — is 0 in the built save, so the branch is armed. One session on pool
slot 1; `work/p46/`.

**Result. CONFIRMED: `ECL15` placed the party at `(8,14)` and the saved
`(8,12)` was ignored.** The boat message printed, `$4A02` went 0 → 1, and
after arrival the live position `$C04B`-`$C04D` read `08 0e 00` — Sokol Keep's
own square, facing north — while `$49C0`-`$49C2` still held the save's
`08 0c 00`. The party then walked north twice, `(8,13)` and `(8,12)`, `$C04B`
following each step and `$49C0` never moving.

So the two indoor cases are now separated:

* **a script with a deliberate arrival** — a boat landing, gated on its own
  flag — overwrites the saved square when the gate is open. CONFIRMED, this
  run. With the gate closed (`$4A02` = 1 in a save made inside Sokol Keep) the
  branch is skipped, which is why an ordinary same-area reload never sees the
  boat.
* **a script with no placing arrival** leaves the saved square alone —
  PROBABLE, one run: the #24 DOS conversion came up at `(4,3)`, the DOS square,
  where New Phlan's own arrival is `(15,1)`. The settling experiment for a
  second area: move a save onto the Slums (`ECL14`) with a square that is
  neither the template's nor an arrival, and read `$C04B`.

**What a converter should conclude:** `$49C0`-`$49C2` is not decoration — it
seeds the live position on load and is what a non-placing area uses — but it is
also not always final. A converter that zeroes the script scratch (ours does)
arms every deliberate-arrival gate, so a placer area runs its arrival and puts
the party on its own square, which is legal by construction. The failure mode
the issue feared — a wrong square inside a wall — belongs only to non-placer
areas, where the square written must be walkable.

**The mechanism question, settled as two mechanisms.** Indoors the live
position is `$C04B`-`$C04D` in the `GDRIVE01` overlay page: before BEGIN
ADVENTURING it still read `fe 7f 10` (the same bytes p20 saw in the attract
demo), it was seeded during arrival, and it moved with every step while
`$49C0`-`$49C2` sat still — the save bytes are a shadow, written back at save
time. Outdoors there is no overlay copy: `$49C3`/`$49C4` is itself the live
variable, leading the status line in the p3 walk logs. CONFIRMED — same store
twice per fact, live reads here plus p20 and the p3 logs.

Build, runner, log and screenshots: `work/p46/`.

## The hidden-site paint does not survive a reload, and the player can see it

**Hypothesis.** The #47 loose end — walk-in `$8C00` at 647/648 against the disk,
load at 648/648, same flag bytes — is the hidden-site paint being lost on load,
and it reaches the screen. The alternative was timing: the walk-in capture was
taken at a different moment in the arrival.

**Method.** It has to end at pixels, and the issue's literal protocol has a
trap: after a *load* the paint may already be gone, so "load, screenshot, save,
reload, screenshot" could show the site in both shots and read as a no. The
painted control state was manufactured first — a seam bounce, east into window
`1B` and back, so `ECL1A`'s entry runs as a genuine walk-in. Start from
`W7.D64` at `(14,8)`, two squares from the camp at `(12,11)`, rather than the
issue's `W1.D64` at `(5,2)`, sixteen squares away — every travel step risks a
random encounter and the run took none. One session, pool slot 1, `work/p49/`.

**Result. CONFIRMED at the screen; `goldbox-bugs.md` #10.** The camp byte
`$8CD2` (= `$8C00` + 11·18 + 12):

| stage | byte |
|---|---|
| after loading `W7.D64` | `$37` — disk value, unpainted |
| after the seam bounce, a fresh walk-in | **`$39` — painted** |
| at `(13,10)`, camp on screen, before saving | `$39`; screenshot `PRE.png` shows **plain grass** |
| after saving there and cold-reloading | **`$37`**; screenshot `POST.png` shows **the camp's ring of tents**, same square |

`PRE.png` and `POST.png` differ in exactly the camp tile — status line
`OUTDOORS 22:23 13,10` against `22:24 13,10`, party still, flags identical by
construction (the save between them is the only event). The timing explanation
is dead: the walk-in paint was reproduced live in the same session that showed
two loads without it, and the byte has now read `$37` after all four cold loads
across p47 and p49, `$39` after every fresh entry.

**Not established, and named as such.** *Where* in the load path the paint is
lost — whether entry 4's paint runs and the forced reload of dirty slot 4
clobbers it after, or the paint branch never runs on a load — is SPECULATIVE
either way; a write-watchpoint on `$8CD2` through a load would say. The other
three hidden sites (all on window `1B`) reload revealed by the same one-shot
paint — PROBABLE, measured painted together on walk-in (write-up lost,
`work/reports/p3-saves.md`) but not carried to a screenshot. Whether the reveal
survives riding around the window is PROBABLE (nothing repaints between
entries); a step-and-redump would confirm.

Runner, log, `PRE.png`/`POST.png` and the phase-2 `$8C00` dump: `work/p49/`.

## Why the converted C64 character reached DOS with no items (#56)

**Hypothesis.** #26's converted character arrived in DOS owning nothing either
because the C64 party used had nothing, or because the
`write_dos_save` → `items_for_slot` → `item_from_c64` path drops items.

**Result 1. The fixture owned nothing; the path drops nothing. Both
CONFIRMED.** The character in #26's end-to-end run was `savedgame0.bin`'s
BRUTUS, and both places a C64 save can hold his items are all zero: the
`$5900` item area's slot-0 block (0 non-zero bytes of 256) and the record's
own inventory at `0x120`–`0x21F` (0 of 256). `party6_savedgame0.bin` is the
same for all six slots. He arrived naked because he left naked.

**Result 2. A played save crosses intact, measured three ways.**
`PORSAVE4.D64` — six characters, 25 items, counts [7, 3, 2, 3, 7, 3] —
through `write_dos_save`:

| check | result |
|---|---|
| `.ITM` files vs the C64 item area, offline | 25 of 25 records byte-identical through `item_to_c64(item_from_c64(x))`, per-slot counts and order exact |
| in the game, MALCYON's item list | `NO DAGGER`, five `NO 4 DARTS`, `YES 15 DARTS` — count, order, quantities and the one readied flag all right; sheet reads `WEAPON 15 DARTS`, `DAMAGE 1D3` |
| the engine's own resave to slot D | all six characters' `.ITM` re-emitted, 25 of 25 still byte-identical in the shared fields |

The resave is the check that covers slots 2–6, which the view screen would
not show: no key tried (map digits, camp arrows, slow arrows) moves the
viewed character off slot 1, so the engine rewriting every chain correctly
is the evidence that it read every chain correctly.

**Result 3. The garbage no-items sheet is NOT the game's display for any
character who owns nothing — it needs a record whose bytes disagree with the
empty list.** #26 run 4 said "the game's own behaviour for a character who
owns nothing"; two in-game controls narrow that:

* a character freshly rolled in the DOS game, viewed before buying anything,
  shows a **clean** sheet — no `WEAPON` line at all, `DAMAGE 1D2+1`,
  `THAC0 20`, sane encumbrance (`work/p56/shots/h6_next.png`);
* MALCYON with every item dropped **in the game** (unready the darts, then
  DROP each with its `GONE FOREVER` confirmation) is also clean — the
  `ITEMS` command even disappears from the VIEW bar
  (`work/p56/shots/k3_list.png`).

So a player cannot reach the garbage unaided by either route. What does show
it, reproduced today under the current writer: the zero-item fixture BRUTUS
converted and loaded reads `WEAPON 254 PASSS`, `DAMAGE 0D8-128`, `THAC0 148`,
`ENCUMBRANCE 60540` (`l1_sheet.png`, identical to #26's `exp3_view.png`) —
and the #26 control (a native character whose `.ITM` was emptied by hand)
showed the same. Both are records that imply gear the item list does not
carry; the engine's own no-item encoding differs from ours somewhere.

**The engine invents an item for him.** Resaving the converted BRUTUS wrote
a **63-byte `.ITM`** — one record of heap garbage (name byte `0xFE` = 254,
the `254 PASSS` on the sheet) — and touched only bytes `0xC8`, `0xCA`,
`0xCB` of the `.SAV`, the chain-head pointer. With `item_count` = 0 and an
empty `.ITM` on disk, the engine still built a one-item chain at load.
Which of our bytes makes it do that is **SPECULATIVE** — candidates are
`hands_used` (`0x100`, we write 0; native fighters carry 2) and the combat
tail's attack-form bytes. Settling experiment: create a fresh character
in the DOS game, save him into a slot so the engine writes his `.SAV`,
diff it against `work/p56/dos-out-fixture/CHRDATA1.SAV` over `0x0C0`–`0x11C`,
then flip the differing bytes in our output one at a time and re-view.
Practical weight is low — a played C64 party's characters all carry items —
but a converted naked character grows a garbage item on his first resave.

Conversions, resaves, runner scripts and screenshots: `work/p56/`.

**Answered by "A converted character who owns nothing (#62)" below: no record
byte triggers it. The trigger is the zero-length `.ITM` file beside it.**

## A converted character who owns nothing (#62)

**Hypothesis.** The converted zero-item record differs from the engine's own
somewhere the sheet's derived lines read — candidates `hands_used` at `0x100`
and the attack-form tail, both written zero because nothing sources them.

**Result 1. No byte of the record is wrong. CONFIRMED, and the hypothesis is
refuted.** There was no engine-written specimen of a character carrying
nothing, so one was made: the shipped slot A party loaded, saved to C as a
baseline, character 1's nine items dropped in play, saved again to D
(`work/p62/run_n.py`, artefacts in `work/p62/truth/`). The same character
before and after, in one session, differs at exactly these bytes:

| offset | field | 9 items | 0 items |
|---|---|---|---|
| `0x0C7` | `item_count` | 9 | **0** |
| `0x0C8`–`0x0D7` | `item_chain` | four live far pointers | **all zero** |
| `0x100` | `hands_used` | 2 | **0** |
| `0x102` | `encumbrance` | 1241 | 486 |
| `0x110`–`0x119` | `thac0_current`, `armour_class`, `roster_tail` | armed | unarmed |

`item_count` 0, `item_chain` NULL and `hands_used` 0 are **exactly what the
writer already produced**. The combat tail comes from the C64 roster, which
carries the C64's own unarmed numbers. So the record was right all along.

**Result 2. The trigger is the `.ITM` file's existence. CONFIRMED, one
variable.** The engine wrote **no `CHRDATD1.ITM` at all** for the emptied
character — every other character in the slot got one. Our writer wrote a
zero-length file. Six variants of the same converted BRUTUS rode as the six
characters of one save slot, judged by the `.ITM` each grew on the engine's
own resave (`work/p62/run_o.py`, `work/p62/out-v1/`):

| n | record | `.ITM` given | `.ITM` after the engine's resave |
|---|---|---|---|
| 1 | ours, unchanged | absent | **absent** |
| 2 | ours, unchanged | zero-length | 63 bytes of heap |
| 3 | `hands_used` = 2 | zero-length | 63 bytes of heap |
| 4 | `hands_used` = 2 | absent | **absent** |
| 5 | ours, unchanged | absent | **absent** |
| 6 | ours, unchanged | zero-length | 63 bytes of heap |

The file separates them and `hands_used` does not. Character 1's sheet, the
identical 285 bytes that read `WEAPON 254 PASSS`, `DAMAGE 0D8-128`,
`THAC0 148`, `ENCUMBRANCE 60540` with the empty file beside them
(`work/p56/shots/l1_sheet.png`), reads clean with no file: no `WEAPON` line,
`DAMAGE 1D2+5`, `THAC0 18`, `ENCUMBRANCE 120`, and no `ITEMS` in the VIEW bar
(`work/p62/out-v1/v1_sheet.png`).

**What the engine is doing** is SPECULATIVE and does not need settling to fix
this: a zero-length file opens successfully where a missing one does not, and
the loader ends up with a chain of one record it never read — the 63 bytes it
then saves are font-shaped heap, `quantity` `0xFE`, which is the `254` on the
sheet. Settling it would need the overlay disassembled, and nothing turns on
it.

**The fix**, `goldbox.dos.write_dos_save`: write the `.ITM` only when the
character carries something, and remove a stale one, the way the stale `.SPC`
already was (`goldbox.dos.ITM_OMITTED_WHEN_EMPTY`). Verified by conversion,
not by hand-edit: the fixture converted by the fixed writer loads, views
clean and resaves without inventing anything (`work/p62/out-fixed/`).

**The lesson, applied to the rest of the list.** `WRITE_UNSOURCED` had been
measured survivable on characters *carrying items* only. Four of its seven
entries are now measured against a character carrying none as well —
`item_chain` and `hands_used` are the values the engine itself writes, and
`effect_chain`, `unnamed_0ab`, `icon_colours` and `heap_104` are carried
through a resave unread in both cases. The portrait ids remain a known
cosmetic drop.

**Two of those names were wrong and are corrected here (#57).** What this
paragraph called `heap_0c1` is `icon_colours`, the combat icon's six colour
pairs; what it called `icon_choice` is four bytes, `portrait_head` and
`portrait_body` for the sheet portrait and `icon_head` and `icon_body` for the
combat icon. "Carried through a resave unread" is still the measurement — but
for `icon_colours` it is now evidence of a **defect** rather than of safety,
because the engine not rewriting them means a converted character's icon keeps
whatever colour index 0 draws as. `#112 (A converted DOS character's combat
icon has no colours)`.

Runner scripts, conversions, resaves and screenshots: `work/p62/`.

## Mapping the DOS saved game (#59)

**Hypothesis.** `SAVGAM?.DAT`'s 8016 unattributed bytes can be mapped the way
the C64 save was: differential analysis, one known in-game change at a time,
then bisection with hand-built saves the game is made to load.

**Specimens.** Donald's slots A (New Phlan, area 0), B (Sokol Keep, 21) and
J (the Slums, 20); four saves taken one action apart (run 1); two engine
resaves of converted parties from #56; and nine hand-built variants V1-V12.
All artefacts in `work/p59/`. `docs/141-dos-savegame.md` is the resulting
layout; `goldbox/dos_savegame.py` reads it.

**Result 1. The file is five fixed regions**, and the biggest is the
current area's ECL script — **live, not dead weight**. Bytes 5121-12800 are
byte-identical to the area's `ECL<n>.DAX` block **from interior offset 2
on**: every block on all three specimens opens `88 13` (`u16le` 5000), and
the save carries everything after it. What first read as a floating image
at "shift 5082/4973/5093" was one fixed buffer at 5121, differently sized
scripts, and stale bytes of longer previous scripts past the end.

**This section originally said the engine reloads the script from the DAX
on every load, and that is refuted** — see Result 4. The offsets 39/148/28
it gave for K were the blocks' parsed-out headers, not what the save
carries. What is true is that the engine's *own resave* writes the current
script: run 9's resave is 0 mismatches over 7511 bytes against `ECL2:20`.

**Result 2. One action, one delta** (run 1, saves C/D/E/F, screenshots for
ground truth):

| pair | action | file delta |
|---|---|---|
| C→D | save again | display 10:02→10:02; no state byte moved — only CHRDAT slot letters, heap pointers, rendered-text scratch |
| D→E | turn right | 12803: 0→2 — facing, doubled |
| E→F | one step | 12801: 4→5 (x); word `$49C7`: 2→3 as the display moved 10:02→10:03 |

The clock is the C64's, at the C64's addresses: digit words `$49C6`-`$49CB`,
sub-minute / units / tens / hour / day / month. A=10:02 day 16, B=1:22,
J=10:56, all as loaded. Saving costs no time on DOS (it costs a minute on
the C64). **#58's decode is done**: carry the six words like the flags.

**Result 3. Party size is `$503E` and byte 12808, twice each.** The one word
the engine changed when a six-member template carried a one-member party was
`$503E` (6→1), with byte 12808 alongside; Curse's and Secret's six-member
defaults both read 6. Not a C64 address — C64 saves hold 0 there.

**Result 4. The naive #60 recipe is refuted; the real one is nine
writes, and this bisection found seven of them.** Header byte + `$49C5` +
`$49F2` + square dies with `Unable to load geo in Load3DMap.` and an exit to
DOS. Bisection (V1-V12, one boot per pair):

| variant | carried from the target save | result |
|---|---|---|
| V1 | everything (J's file verbatim) | loads — and loads **J's party**: the engine reads the `CHRDAT` filenames from the save's own table at 12809, not the slot letter |
| V2 | naive fields + ECL buffer | `Unable to load geo` — the buffer alone does not close the gap. **Read at the time as "the buffer is not needed", which does not follow and is wrong** |
| V4 | naive + whole word array | works |
| V6 | naive + words `$4B80`-`$58FF` | `Unable to load wallset in LoadWallSet.` — the geo gate is in this half, the wallset gate elsewhere |
| V7 | V6 + words `$4AFA`-`$4AFF` | **works** |
| V11 | naive + `$4AFA`-`$4AFF` + `$5012` | **works — the minimal set** |
| V12 | naive + `$4AFA`-`$4AFF` + `$5200`-`$520F` | `Unable to load geo` — so the geo gate is `$5012` alone |

`$5012` holds the DAX container number (3/4/2 in A/B/J — numerically the
C64 disk side); the header byte alone does not satisfy `Load3DMap`.
`$4AFA`-`$4AFC` are the wallset triple — `WALLDEF<n>.DAX`/`8X8D<n>.DAX`
block ids, `$FFFF` empty — and the cross-port check is exact: C64
`PORSAVE13` (the Slums) carries cache slots 15-17 = (2,4,1), byte-identical
to DOS slot J's triple, so **a converter can source the triple from the C64
save**. Run 9 played the party that had been moved to the new area and let
the engine resave it:
dax 2, area 20, `$5012` = 2, triple (2,4,1), CHRDAT letters rewritten,
buffer refilled. CONFIRMED for area 0 → area 20; a second pair would firm
the general claim.

**The blind spot, found by #60 on 2026-08-25.** Every one
of V1-V12 was built on slot J and carried **J's** ECL buffer — 0 bytes
differ over 5121-12800 in all twelve, against 7439 differing from A. So the
buffer was never a variable in this bisection and no variant could have
shown it mattered; V11 stood in the Slums with the *Slums'* script staged,
not area 0's. The control this run lacked is `work/p60/run2` X1 — slot A,
all seven writes above, its own buffer left alone — which dies in
`Load3DMap`. The buffer is write **7** of nine, and #60 was implemented
against the seven and its first attempt to move a save onto a fresh template
died exactly there. The recipe as it stands is in `docs/141-dos-savegame.md`
"The recipe for moving a save to a different area (#60)", formatted from
`goldbox.dos_savegame.RETARGET_WRITES`.

**Result 5. The variable array is sparse and the tail is mostly not state.**
2407 of 2560 words are zero in all nine specimens. `$5227`+ is the
encounter-message buffer, one ASCII character per word ("YOU SPY A GROUP OF
SEEDY-LOOKING GOBLINS."). The 32 bytes after each CHRDAT filename and
everything past 13055 are heap and rendered-text scratch — the "+1 per save"
counters that first looked like state were the slot letter in `CHRDATC1` →
`CHRDATD1` and the ASCII digits of the drawn status line.

**Negative results, named.** The C64's 25-slot cache addresses (`$4BC0`+)
are zero words on DOS — the cache's DOS descendants are `$4AFA`-`$4AFF` +
`$5012`. No GEO image is stored in the save. No pointer to the ECL buffer
exists in the file (none needed; the buffer is at a fixed offset).
`tools/dosbox.py`'s `dax_unpack` IndexErrored on `ECL2.DAX` block 9 during
this run and the block was skipped — since diagnosed and fixed (#65: two
real faults in the reader, zero failures over 11 654 blocks after; the block
itself was always well-formed).

**Left open.** ~30 live words unnamed (`$49F0`, `$49FC`-`$49FF`,
`$4FC0`-`$4FD3`, `$5200`-`$520F`), bytes 12804-12807, outdoor saves
(no specimen at the time — see the next entry), #57's portrait path.

## The DOS saved game outdoors (#59, the outdoor half)

**Hypothesis.** A DOS save made on the overland travel map differs from an
indoor one the way the C64's does (#47): `$49E6` = 0, the square in
`$49C3`/`$49C4`, and some analogue of the SQRDATA substitution in whatever
the DOS load path keys on.

**Getting there, without a fasttravel.** The DOS engine has no debug fasttravel, so the
party went by play. The route was read out of `ECL00` (the DOS `ECL3.DAX`
block 0 — the DOS blocks still carry the C64's `$9900` base internally, so
`work/analysis/ecl.py` disassembles them unchanged): the harbor master at
(11,1), entered heading north with quest word `$4AA7` ≥ 254, offers
`HORIZMENU [$4AC4]`: SOKAL / EAST / WEST / BAY / NONE; any purchase sets
`$4A01` = 1; boarding at the pier end (15,1) then runs, for WEST,
`SAVE 7,[$49C3] / SAVE 29,[$49C4] / SAVE 7,[$6E12] / NEWECL 26`. Slot A
stands at (4,3) with `$4AA7` = 255, and a BFS over `GEO00`'s own
passability gives the walk. Two traps, both read off screenshots: the fare
wants `WHO WILL PAY? SELECT` answered (Return does), and the WEST landing
square, world (20,29), is the overland's own "boat back to Phlan" event,
whose TAKE BOAT / STAY menu ignores Return and wants the letter.

**Specimens.** `work/p59-outdoor/`: SAVGAMC (at the landing, screen
`20,29 E 10:15`), SAVGAMD (one step north, `20,28 N 22:15`), SAVGAME (one
step east, `21,28 E 10:15` next day), with the engine's `CHRDAT` files, the
screenshots and `run1.py`. `run2.py` is the DOSBox-X debugger pass on save
D; `run2.log` its output.

**Result 1. The travel square is `$49C3`/`$49C4`, window-local — the #50
blocker, settled.** (7,29) → (7,28) → (8,28) against the three screens;
world x = local x + 13 for window 26, y unchanged, exactly the C64 seam
arithmetic. Live corroboration: `BPM` on `$49C3`'s low byte, one east step,
`07 -> 08`, writer `2E33:095E`. Meanwhile file bytes 12801/12802 sit at the
pier square (15,1) in all three — stale — while the facing byte 12803 stays
live (2/0/2 = E/N/E, matching the screen). The C64's stale-copy
relationship, mirrored.

**Result 2. `$49E6` is the indoors flag, now CONFIRMED both ways.** 1 in
A/B/J, 0 in C/D/E, and the boat back to Phlan was caught writing it 0 → 1
live (writer `30F6:0CA1`), with `$5200` written 1 → 0 → 1 by `30F6:0CF2` in
the same transition.

**Result 3. `$49C5` is 0 outdoors — the C64 analogy breaks here.** The C64
carries the SQRDATA number (5, for window 26); DOS carries 0. The DOS
game directory has no SQRDATA files at all — the windows are ordinary GEO
blocks 25-27 in `GEO6`-`GEO8.DAX` — so there may be nothing for `$49C5`
to name. Header byte 0 and `$5012` hold the DAX number (7) and `$49F2` the
area id (26), the indoor mechanism unchanged.

**Result 4. The ECL buffer rule holds outdoors, and the tail-fill claim
falls.** C's buffer is `ECL7.DAX` block 26 from byte 2 on, 6567 of 6567.
Past the script's end the buffer is *all zeros* — and re-checking A/B/J
found their remnants (209/1972/3 bytes) all zero too, refuting
`docs/141`'s "stale remnants of longer previous scripts". 6 of 6 zero-fill.

**Result 5. New correlations in the unnamed bytes.** File byte 12805
equals VM word `$5200` in all six specimens (26/0/0/1/1/1). File byte
12806 is 1 in the three indoor saves and 3 in the three outdoor ones —
PROBABLE view-mode byte. One overland step costs 12 hours.

**Negative results, named.** `$49F0` moved 14 → 15 on the C→D step and
then sat still through two watched steps (`BPM` armed, no hit in 45 s
each; live 15 indoors and out) — not a step counter. `$507A` held the
travel y in C and D but did not track x in E. `$49FC`-`$49FF` are
(6,11,10,3) in five specimens, (4,11,9,3) in J — constant across modes, so
not mode state. And the file tail 12801-12817 (stale square + `CHRDATD1`)
exists nowhere in the first megabyte of the running game — `find` and
`count` both 0 — so the save writer assembles it from scattered state and
bytes 12804-12807 have no single live address to watch.

**Left open.** The wallset triple outdoors reads (0,$FFFF,$FFFF) but the
departure template's was the same, so live-versus-stale needs a sail from
Sokol Keep (triple 1,5,9). Moving an outdoor save to a new area has not been
driven; #50 owns the converter form. `$49F0`, `$5079`-`$507D`, 12804/12805/12807
remain unnamed.

## The later titles' mode flag is `$7F11`, and their LINKER is Pool of Radiance's

**`$7F11` is the loader's dispatch byte in Curse of the Azure Bonds and in
Secret of the Silver Blades, and `2` is COMBAT there exactly as `$6E11 = 2` is
in Pool of Radiance.** CONFIRMED for Curse, PROBABLE for Silver Blades. It is
the last address `automap/actions.py` needed and the reason all five live
action buttons refused on both titles (#29).

**It is not derivable and it was never going to be.** The save image moved
`$4900` → `$4B00` between the two games; the flag moved `$6E11` → `$7F11`,
which is `+$1100`. `LINKER` is its own resident and owes nothing to where the
save loads.

**Where it came from: the loader's own first instruction.** `LINKER` on
`CURSE_A.D64` is 146 bytes and begins `AD 11 7F` — `LDA $7F11`. That operand is
absolute, so it says what the flag is **without anyone having to work out where
`LINKER` runs**, and it can be read off the disk with no emulator at all. The
same file on `SILVER-1.D64` is 149 bytes and begins with the same three bytes.
Pool of Radiance's is 136 bytes and begins `AD 11 6E`. The rest of the routine
is the same outer loop in all three: index a name table by the flag, load that
overlay at `$0800`, `JSR $0800`, `JMP` back to the top.

**The name table is the same table, entry for entry**, which is what settles
`2`:

| index | 0 | 1 | 2 | 3 | 4 | 5 | 6, 7 | 8 | 9 |
|---|---|---|---|---|---|---|---|---|---|
| | `GEN` | `DUNGEON` | **`COMBAT`** | `INIT` | `COM.PREP` | `POST.COM` | dead | `FINAL` | `CAMP` |

Pool of Radiance pads the two dead slots with `@@` inside the string pool;
Curse and Silver Blades leave their pointers aimed at `FINAL` with lengths that
run past it. Different padding, identical indices — so `automap.actions.COMBAT`
stays one constant for the family and only the address is per title.

**Live corroboration, on Curse, one driven session on pool slot 2.** The same
code is resident at `$2D00` (Pool of Radiance's `LINKER` is at `$2B80`), the
name table at `$2D42`, and `$7F11` was sampled across four overlay changes:

| when | `$7F11` | predicted first? |
|---|---|---|
| party in Tilverton, `MOVE VIEW CAST …` on screen | `1` `DUNGEON` | — |
| `ENCAMP` | `9` `CAMP` | yes |
| `EXIT` back to the world | `1` | yes |
| answered `DO YOU WANT TO TRAIN?` with YES | `0` `GEN` | no |
| `BEGIN ADVENTURING` | `1` | yes |

And the writer is where Pool of Radiance's is: `LDA #$09 / STA $7F11` at
`$100E` in the resident `DUNGEON`, against `DUNGEON $10B1` writing `9` in Pool
of Radiance. The live cache sits two bytes above it at `$7F13`, the same
`+2` as Pool of Radiance's `$6E11`/`$6E13`, and `$7F15` read `01` for a machine
with `GEO01` resident at `$0400` — which is the loaded-files cache's slot 2
saying which map is loaded, and is a second, independent fix on the loader's
resident page.

**Silver Blades then gave the fight, and the whole chain with it.** One driven
session on the shipped `SAVEDBASH` party, 228 steps out of New Verdigris, and
the flag went

    1 DUNGEON  ->  4 COM.PREP  ->  2 COMBAT

with `MOVE VIEW AIM TURN QUICK DONE` on the command bar at `2`. `COM.PREP` held
for at least twenty samples while it loaded, which is **the first live sighting
of `4` in any title** — the Pool of Radiance row above says of it "never
sampled live; that row is disassembly only", and it can come off that footing
now. The gate was exercised in the same breath: `actions.in_combat` answered
True, `heal` stayed legal and `identify`, `store-spells` and `restore-spells`
all refused with "refused during a fight (`$7F11` is 2)".

**Curse did not give one**, and that is the one thing this pair of sittings did
not get. About 250 driven steps through Tilverton produced scripted text, a
locked door and the training hall; five days of camp rest produced `YOUR REST
IS RUDELY INTERRUPTED!` twice and both times the flag went `9` → `1` and the
party was handed back to the world with no combat. So `2` on Curse rests on the
dispatch table alone. It is the same table as the one Silver Blades has now
been watched running, which is why this is a footnote and not a blocker.

**What this is worth to the program.** `Game.mode_flag` is `$7F11` for both
later titles, so the five live actions no longer refuse there and
`docs/139`'s C16–C19 leave `R`. The three Krynn-era titles keep `None`: their
`LINKER` has not been read, and a title with no gate must refuse rather than
read somebody else's byte and call whatever it finds "not combat".

## Measured versus inherited: the DOS saved game's last unnamed bytes (#59)

Donald's ruling — no template, block on not understanding — turns every
undecoded byte of `SAVGAM?.DAT` into a blocker, so the question stopped being
"what is this byte for" and became "may a converter write it, and on what
evidence". A file-level pass over the whole corpus answered most of it.

**Two specimens nobody had counted.** The archives ship a second copy of the
save directory at `games/POOLRAD/Default files/Saves/`, and its `SAVGAMA.DAT`
and `SAVGAMB.DAT` are **not** the files in Donald's `SavesDir` (`GAME/POOLRAD/
SAVE/` is byte-identical to his; `Default files` is not). The A there is a
genuine engine-written Slums save at the entrance square (15,4) with the
right wallset triple — a twelfth specimen for nothing. The B is a stub, ECL
buffer all zeros and nine live words, and is excluded from every count.

**Byte 12805 is a copy of `$5200`, 13 of 13** — including two files where the
pair moved together (26→0 on one indoor step; 26→1 across the boat) and the
engine's own resave. Byte 12807 is 2 in all twelve genuine files. Byte 12806
is 1 indoors and 3 outdoors, but it is *perfectly* correlated with `$49E6`,
so the corpus cannot separate "view mode" from a second encoding of the
indoors flag; either way a converter writes it from a value it already has.

**Byte 12804 resisted, and the negative result is the useful part.** An
exhaustive search — 13 files × 13137 byte offsets and all 2560 VM words —
found no field carrying its value vector and none even sharing its
*partition*. Refuted: `$49F0`, `$49F1`, `$49FE`, `$4AC4`, and any step
counter (it is flat across a turn, an indoor step and two overland steps).
The only structure in the vector is that its 14 appears in exactly the two
lineages that arrived by boat. It does not block a conversion, because the
engine writes it: a hand-built save carrying 0 came back from the engine's
resave holding 9.

**The boundary that reorganised the rest.** Grepping every bracketed address
out of the thirty ECL disassemblies in `work/ecl-scripts` gives 2544 distinct
addresses and **not one at or above `$4AF9`**. So the shared, cross-port ECL
variable space is `$4900`-`$4AF8` and no further — and on the C64 `$4D00`
upwards is the twelve character slots, so the DOS VM array above `$4AF8` has
no C64 counterpart at all. That splits the unnamed words into "could be
copied from the C64" and "must be measured on DOS", and it is why the
addresses that look tempting (`$4FC0`, `$5079`, `$5200`) can never be sourced
from a C64 save.

**Two words fell to the scripts themselves.** Every area's ECL opens by
writing `$49FD` and `$49FE`: `ECL00` does `SAVE 10,[$49FE]`, `ECL14` does
`SAVE 9,[$49FE]`, and Sokol Keep's `ECL15` writes neither — which is exactly
why slot B stands in Sokol Keep still holding New Phlan's 10. Both ports
agree save for save. The engine rewrote 10→9 by itself after loading a save
retargeted into the Slums, so the prologue runs on load and these are
rebuilt, not carried. `$49EB` and `$4A00` read the same way on both ports too
(`$4A00` = 255 in both Slums saves, 0 in both New Phlan ones).

The inherit list this leaves — three groups with an experiment against each,
and the byte count — is the table in `141-dos-savegame.md`. Scripts:
`work/p59-vars/corr.py`, `partition.py`, `inherit.py`, `crossport.py`.

## What the C64 engine writes when a character is dropped (#104)

**There is no party count. A slot is empty exactly when the first byte of its
record is zero, and dropping a character writes that one byte.**

The question mattered because a DOS save holds six characters and a C64 save
eight, so every conversion leaves at least two of the template's slots
unwritten — and `#104` could not be fixed until somebody knew what "unwritten"
should look like. Writing zeros over the whole slot was the obvious guess, and
`CLAUDE.md`'s conversion standard forbids exactly that guess.

### The static half: no header byte holds a count

190 `.d64` images under `work/` carry a readable `SAVEDGAME0` — party sizes 1,
2, 6 (×187) and 8. For every byte of the 1024-byte header `$4900`-`$4CFF`,
none equals the party size in all 190; nor the size minus one, nor the highest
occupied slot index, nor twice the size. `$49FC` behaves as `#104` says: 2 in
the one-character save, 2 in the six-character ones, 6 in the two-character
one.

Against the rule *"the record's first byte is non-zero"*, `looks_occupied`
agrees on **1520 of 1520 slots**. Half of that is trivial — a zero first byte
fails the `A`-`Z` test by construction — and the half that is not is the
finding: no slot anywhere has a live first byte and fails the ability check, so
the engine never leaves a half-scrubbed record that reads as occupied.

`work/p104/countsearch.py` and `work/p104/namebyte.py`.

### The measured half: the engine's own DROP

`PORSAVE-6char.D64` (MALCYON, LADY KATHERINE, ROLAND, SILAS, MAGNUS, BRUTUS)
booted on the instance pool, headless, disks copied into the slot's own
directory. `LOAD SAVED GAME`, then the party menu's `DROP CHARACTER`, then
`SAVE CURRENT GAME`. Diffed against the pristine image:

| address | before → after | what |
|---|---|---|
| `$5200` | `42` → `00` | **slot 5's record byte 0** — the `B` of BRUTUS |
| `$83A0` | `01` → `00` | **roster slot 5 +0x00** — `roster_in_use` |
| `$4BC0`, `$4BC2`, `$4BC3`, `$4BC5`, `$4BC8`, `$4BCB` | bit 7 set | the loaded-files cache's dirty bits, from the load-and-save cycle |

**One byte of slot 5's 256 changed.** BRUTUS's abilities, hit points, class
levels and items are all still there:

```
before  42 52 55 54 55 53 ...     BRUTUS
after   00 52 55 54 55 53 ...     \0RUTUS
```

Seven bytes changed as the party went from six to five and **not one of them is
a 6 becoming a 5**.

This also explains two saves this project has puzzled over: `PORSAVE-6char.D64`
and `PORSAVE11.D64` hold `00 52 55 54 55 53` in slots 6 and 7, which
`docs/30-savegame-layout.md` called remnants with a zeroed name-length byte.
There is no name-length byte in a C64 record — the name is 20 NUL-padded bytes
— and those are not remnants: **those saves were made by dropping BRUTUS**, and
that is byte for byte what it leaves.

`work/p104/drop2.py`, payloads in `work/p104/*.bin`.

### Two harness faults, both of which produce a run that looks fine and saves nothing

* **The drop list does not close itself.** The name disappears and the list
  stays up with `DROP (ERASE) WHO ?` on row 24, so a driver that goes straight
  for `SAVE CURRENT GAME` never finds it. `EXIT` in the list returns to the
  menu.
* **`SAVE CURRENT GAME` puts up `SAVE GAME: YES NO`** on the command bar, and
  `tools/session.py`'s `handle_prompt` does not answer it. The first run
  exited cleanly having written nothing and reported "0 bytes differ" as
  though the engine had made no change.

### What this leaves for somebody else

`docs/30-savegame-layout.md` and `docs/41-memory-regions.md` both still grade
`$49FC` as a party count — PROBABLE in one, GUESS in the other — and both
should now say refuted, with this measurement as the reason. **Flagged, not
edited**: those files belong to another lane.

## What a Sleep writes, and what it does not

**A Sleep that lands writes effect id 53 on each sleeper. It does not write
31.** The three codes `goldbox/traits.py` carries as 31 helpless, 52 held or
paralysed and 53 sleeping are genuinely three different things, and this is the
first time any of them has been watched being written.

The question mattered because the automapper's combat map had just been built
to draw an enemy's square gold when it carried **31**, on the reasoning that a
sleeping monster is helpless. The reasoning is sound in AD&D and wrong about
this engine.

### The measurement

A magic-user cast Sleep on the slums orc ambush, in a fight driven out of
`PORSAVE13.D64`. Reading the four effect arrays immediately afterwards:

| slot | id | owner | duration | magnitude |
|---|---|---|---|---|
| 56 | 53 | `$0D` = 13 | 4 | 1 |
| 57 | 53 | `$0B` = 11 | 4 | 1 |
| 58 | 53 | `$08` = 8 | 4 | 1 |
| 61 | 53 | `$03` = 3 | 5 | 1 |
| 62 | 53 | `$0A` = 10 | 4 | 1 |

**Five sleepers, five ids, all 53.** No slot anywhere in the 64 held 31. The
owner bytes are combat combatant indices, so 8, 10, 11 and 13 are four of the
eight orcs — and **3 is SILAS, one of the party's own**. Sleep is an area
effect and it caught a party member; that is the game working, not a fault, and
it is worth knowing before anything badges the party side.

Slots 59, 60 and 63 held owner bytes with a **zero id**, which is the expiry
behaviour `docs/133-active-effects.md` records: expiry clears only the id, so
the other three arrays keep whatever they had.

**This promotes 53 from PROBABLE to CONFIRMED.** 31 and 52 stay PROBABLE:
nothing has been seen to write either, and what does write 31 is still unknown.

### What it says about the drawing, which was separately proven

The gold square itself was verified in the same fight by writing id 31 onto one
orc's index with the machine paused, letting the poll run, and clearing it
again: the square went **red, gold, red** and the tooltip gained and lost its
line, without the program being restarted. So the path from the effect arrays
to the pixels is sound; only the set of ids it watched was wrong.

Donald's ruling, 2026-08-31: the square goes gold for **31, 52 and 53
together** — the states where a creature cannot defend itself — with the
tooltip naming which one it actually is rather than calling all three
"helpless". A party member keeps its green fill and says the condition in its
tooltip, because the fill's job is to say which side a square is on.

### What is still open

**What writes 31.** It is in the table as "helpless" and nothing observed has
ever set it. A Hold Person cast at a monster would settle 52 the same way this
settled 53, and is the obvious next measurement.

---

## The 68000 disassembler, and the `.pc` loader it was written to read (#148)

`work/amiga/m68dis.py` went with `work/`, and `docs/124-amiga-port.md` phase 1
had been stopped on it since: "read the `.pc` loader" needs a 68000
disassembler and there was not one in the tree. Donald's ruling on 2026-08-31
was to rebuild it and put it in `tools/`, which is where `CLAUDE.md` now says a
tool that regenerates an artefact belongs. `tools/m68dis.py` is the first one
written under that rule.

### The rule the tool is built around

**An encoding it does not recognise prints as `dc.w $xxxx`, never as the
nearest instruction that fits.** This is not fastidiousness. A 316 KB code hunk
has strings, jump tables and item data scattered through it, and a decoder that
rounds every word to the nearest legal instruction produces a listing that
looks exactly like code from the middle of a string table. The invented
instruction is then quoted in a document, and nothing about it says it was
invented.

So every field is checked before a mnemonic is emitted: an addressing mode the
opcode cannot take, a 68020 full-format index extension, a size field the
opcode does not define, a branch whose displacement lands on an odd address, a
word that runs off the end of the buffer. Each falls through to data.

### How it was verified, and what that caught

Plausible is not the same as correct, and a disassembler is unusually good at
looking correct. The check was an **independent decoder**: `capstone` 5.0.7,
which is in `.venv` and is not a dependency of `wish` and must not become one.
Both were walked over the whole 316 KB code hunk of the Amiga *Pools of
Darkness* executable, advancing by our own instruction lengths.

**The mode is part of the claim, so it is written down here:
`CS_MODE_BIG_ENDIAN | CS_MODE_M68K_000`.** It is not a detail. Run the same
comparison in `CS_MODE_M68K_020` and capstone decodes 616 more words —
42 `chk.l`, 205 `fbf.l`, `frestore`, `fsave` and the rest of the 68881 — none
of which exists on the CPU this binary runs on. The agreement numbers below
are identical in both modes; what changes is the refusal count, and only the
68000 mode accounts for it exactly.

| | |
|---|---|
| instructions both decoded | **100 385** |
| instruction lengths that disagreed | **0** |
| mnemonics that disagreed | **0** |
| operands that disagreed, after normalising the two syntaxes | **0** |
| we refused, capstone decoded | 2 288 — 1 943 branches to an odd address, 248 68020 scaled or memory-indirect index extensions, 97 index extensions with the 68020 format bit set. That is the whole 2 288 with nothing left over |
| capstone refused, we decoded | 0 |

Every one of the 2 288 is inside string data, and in each the refusal is the
stricter reading. **Two of the three are legal encodings that no assembler
would emit**, which is a narrower claim than "a 68000 cannot do this" and a
more useful one: real silicon ignores the reserved extension bits, and an odd
branch target is taken and then address-errors at run time rather than being
an illegal instruction. Refusing them is what separates code from string data
in a binary with both scattered through one hunk, and the comments in
`tools/m68dis.py` say so in those words. The 24 remaining textual differences
are capstone writing `lea.l` and `pea.l` where we write `lea` and `pea`.

**The cross-check earned its keep immediately.** The first draft read
NEGX/CLR/NEG/NOT/TST out of bits 11-9 of a line-4 opcode. They live in bits
11-8; bit 8 set is CHK, LEA, or nothing at all. So `$4552` — the letters `ER`
in the middle of `PICK A GENDER` — came out as `neg.w (a2)`, and 199 words of
string data across the binary decoded as instructions that do not exist. That
is precisely the failure the "never guess" rule exists to prevent, and reading
the listing would never have caught it: `neg.w (a2)` is a perfectly ordinary
line. `tests/test_m68dis.py::test_bit_eight_is_not_a_unary_operation` is the
regression, and it fails against the first draft.

The committed tests build their encodings by hand from the Motorola manual, so
the suite needs no game data and skips nothing. The comparison script needs
capstone and therefore cannot be one of them; it stays under `work/`, and the
two numbers that matter — the mode and the counts — are in this section so the
claim can be checked without it.

### Finding the routine, which is the other half of the job

`docs/124` §1.2 gives three file offsets for the literal `pc` and calls them a
load site and a save site. They are neither, and `--refs` says so: it walks the
range a word at a time and reports every instruction whose resolved target is
one address. Each literal is referenced exactly once in 316 KB:

* `0x255B2` from `pea $255b2(pc)` at `0x25568` — the **picker**, which builds
  the list of `*.pc` on the save disk;
* `0x25802` from `pea $25802(pc)` at `0x257DC` — **delete**;
* `0x265A2` from `lea $265a2(pc),a2` at `0x26476` — **save**.

The loader references none of them, because the picker hands it a name that is
already built. Getting to it needed one more step: the binary is an AmigaDOS
hunk file whose data hunk begins with a table of `jmp abs.l` stubs, and A4 is
set to `hunk1 + $7FFE` by a `lea $00007ffe,a4` with a relocation on it. So
`jsr -$7722(a4)` is a call to hunk 1 offset `$8DC`, and the longword in that
stub, relocated, is the real destination. Resolving the stubs by hand is what
turned a wall of `jsr -$nnnn(a4)` into a call graph.

### The answer phase 1 asked for

`pcload(char *name, character *dest)` at `0x25BAE` hands a callback at
`0x25806` to the engine's open-and-retry harness at `0x3F874`, which builds
`DF0:SAVE/<name>`, opens it with AmigaDOS `Open` and `MODE_OLDFILE` (`$3EE`),
and calls back with the handle. Every read reaches dos.library `Read` at
`-42(a6)`.

The callback reads **404 bytes** (`$194`) into the character record; then the
longword at record `+8` tells it how many **20-byte** item records follow, and
each item's own byte at `+$0C` how many 20-byte scroll records hang off it;
then, if the longword at record `+4` is non-zero, a chain of **10-byte**
effect records, each carrying the next one's pointer at its own `+6`.

It checks four things and no more: that each read returned the length it asked
for; that every item record begins with `$49`, ASCII `'I'`; that items plus
scrolls stay within `$78` (120), and prints `SCROLLS DROPPED!` when they do
not; and nothing else. **No file length is checked and the character record
carries no signature at all** — which is the mechanism behind §2.2's
experimental result that a 582-byte C64 export loads.

### The correction it produced

`docs/124` had "484 is the record with no appended item data". It is not: the
record is 404 bytes and 484 is 404 plus four items. The arithmetic accounts for
every size on disk 3 — 484, 504, 514, 524 are 404 + 4×20, 5×20, 5×20 + 10 and
6×20 — and for §1.5's reading of `4`, `5` or `6` at offset `0x08`, which is the
item count and not a mystery. The falsifiable part: the 514-byte file must hold
5 at `0x08` **and** a non-zero longword at `0x04`, and nobody has re-read the
files to check.

Nothing about `goldbox.amiga.PodWriter` moves: it leaves both counts zero, so
PoD reads 404 bytes and stops, and the 80 bytes after them are padding rather
than a length the game wants.
