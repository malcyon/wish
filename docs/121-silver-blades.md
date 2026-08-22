# Secret of the Silver Blades — running the Gold Box skill

**Status: phases 0, 1 and 2 are done, and phase 3's geometry with them.
Phases 3-5 need the emulator and have not started.** Everything done so far
was a cold read of the disks with `por/geo.py`, `por/record.py` and
`por/savegame.py` **unmodified**.

The title is *Secret* of the Silver Blades, singular, which is what the disks
say.

## 1. The disks

`SILVER-1.D64` ... `SILVER-6.D64` — three double-sided disks, sides 1 to 6,
with no gap and no error-byte rip among them. `por/d64.py` opens all six.
`work/reports/goldbox-inventory.md` has the full inventory.

**How the tests find them.** `tests/test_silverblades.py` looks behind an
`SSB_DISKS` environment variable and then at a candidate list, in the same
shape as `COAB_DISKS` in `tests/gamedata.py` — but *in the test module*, not in
`gamedata.py`, because that module was another agent's while this was written.
If a fourth title needs the same lookup it should move into `gamedata.py`
rather than be copied a second time.

Nothing about the disks may be committed. `tests/test_repository_contents.py`
enforces that and **its allowlist must not grow**.

**Still missing, and it is what phases 3-5 need:** a save disk written by the
game, with a real party on it, and best of all a Curse of the Azure Bonds party
imported into Silver Blades and exported again. `SAVEDBASH` on side 6 is the
shipped demo party, not a save disk. No exported character file exists on any
of the six sides, so the export load address and marker byte are still UNKNOWN.

### A note on the skill

`skills/goldbox/SKILL.md` did **not exist** when this was written. The phases
below are derived from `docs/60-goldbox-field-checklist.md` and
`docs/116-second-game.md`, which is what the skill was distilled from, so they
should align; whoever runs the rest should read the skill first and reorder to
match it rather than the other way round.

## 2. Ordering

Silver Blades is the direct sequel, shares the most with Pool of Radiance and
Curse, and **is the only remaining title that imports a Curse party** — the
lever that produced the 15-bytes-of-580 result in `docs/116-second-game.md`.
Gateway and the Krynn titles start fresh parties and cannot offer it. That
argument is why it was worth waiting for the disks, and they are here.

What remains, in order:

1. **Finish Curse** — `docs/120-curse-testing.md`. Tiers 1, 2 and 5.1 are done;
   what is left needs the emulator.
2. **Phases 3-5 here**, which all need the emulator and a save disk written by
   the game. Phase 4, the Curse-to-Silver-Blades import diff, is the single
   strongest experiment available in this project and nothing else on this
   machine can substitute for it.
3. Gateway to the Savage Frontier and the two Krynn titles are on disk and are
   read statically in `work/reports/goldbox-inventory.md`. They are a fourth
   target, not a third.

## 3. What was expected to transfer, and what did

Curse shares the 580-byte record with Pool of Radiance *at every offset*, and
that is not a diff of two specimens — it is the game's own import arithmetic.
The predictions below inherited their confidence from that. The outcome column
is the cold read of the disks (`tests/test_silverblades.py`,
`work/reports/goldbox-inventory.md`); rows still marked "not settled" need the
emulator.

| | Prediction | Outcome |
|---|---|---|
| character record size 580 bytes | same | **held** |
| every field in `por/layout.py`, same offset, same width | same | **held** — six shipped characters decode and round-trip byte-identically |
| save slot = first 256 bytes of the record, `$100` stride | same | **held** |
| roster block = record `0x100`–`0x11F`, last page of the payload | same | **held**, at `$6700` |
| `60 - value` encoding for THAC0, AC, damage bonus | same | **held** — `armour_class_base` decodes to 10 for all six |
| `GEO`: 1024 bytes, four 16×16 planes, `por/geo.py` unmodified | same | **held** — 17 files, barrier reciprocity mean 0.982, worst `GEO40` 0.923; wall-art reciprocity **1.000 on every file** |
| `ITEMS` 128 × 16; `ITEMNAMES` 256 low + 256 high + strings | same shape | **held** — `ITEMS` 2048 bytes |
| second ability array at `0x065`, fighting level at `0x098` | present, as in Curse | **held** |
| spell ids 1–56 unchanged, more added above | as Curse did | **held**, and it is the strongest new result — see below |
| save file **count and names** | assume neither game's | **name differs** (`SAVEDBASH`), count does not: one file, like every title after Pool of Radiance |
| save load address and header base | a third value expected | **contradicted, in our favour.** `$4B00`, slots `$4F00`, items `$5B00`, roster `$6700` — byte for byte Curse's |
| file stems (`GEO`, `ECL`, `ITEMS`, …) | may be renamed wholesale | **contradicted, in our favour.** 30 of 34 stems are Pool of Radiance's; the one real rename is `ITEMFILE` → `ITEM` |
| fewer `GEO` files, no wilderness | fewer expected | 17, against Curse's 16 and Pool of Radiance's 29. No `SQRDATA`/`SQRPACI`/`WALLS` on any side |
| export load address and marker byte | a third pair expected | **not settled** — no exported character file exists on any of the six sides |
| `ITEMNAMES` resident base | a third | **not settled** |
| `LIBRARY` `GEO` stem table address | a third | **not settled** |
| live party x/y/facing address | a third | **not settled** — needs the emulator |
| resident `GEO` left at `$0400` | must be re-verified | **not settled** |
| status-line row and format on screen | unverified anywhere else | **not settled** |

**The rule the table encodes still stands, with one correction:** *structure*
transfers, *addresses* do not — except that the **save container's** addresses
did, exactly. Silver Blades and Gateway both reuse Curse's `$4B00`; the two
Krynn titles moved the block down `$B00` to `$4000`. So the save geometry is a
per-title constant with only three values across six games, and `por/games.py`
is where they live. Every *other* absolute number is still a Pool of Radiance
constant that must be re-measured.

**A new regularity, worth more than any single address.** Silver Blades' `GEO`
ids are sparse — `$10` to `$62`, no `GEO00` — and **the high nibble is the disk
side the file sits on**, without exception: `GEO2x` on side 2, `GEO3x` on side
3. Champions and Death Knights do the same. That is a free area-to-side index,
and it is asserted in `tests/test_silverblades.py`.

### What being a sequel changed

| Difference | What came of it |
|---|---|
| **Party is imported from Curse, not rolled** | Still the experiment worth doing, and still undone: it needs the game running. Phase 4 |
| **Higher level range** | The shipped party is level 8-9 with 100000-200000 experience. `por/levels.py`'s caps are Pool of Radiance's and are still unmeasured for this title |
| **Higher spell levels than Curse** | **The gift arrived.** `docs/116` lists the spellbook bitmask's width at `0x078` as NOT FOUND because no Curse specimen writes past `0x07C`. MORGAINE sets `0x07D` and `0x07E`; DOMINIC sets all three, and `0x07F = 0x04` — bit 2, spell id 58. So `spells_known` is **at least eight bytes** in the later titles (PROBABLE), and `por/layout.py` records it. Nothing proves it stops at eight |
| **Dual- and multi-classed characters common at this level** | Weakly held: one of six, MALACHITE, thief 8 / fighter 7 |
| **No city-block/wilderness structure** | Held at the file level — no `SQRDATA`, `SQRPACI` or `WALLS` on any side, in this or any title after Pool of Radiance. Whether the save's wilderness travel bytes are dead is not answerable statically |
| **A different race table** | Not predicted at all, and real. Silver Blades drops half-orc and re-orders the rest, so **human is 6, not 7**. `por/games.py` now carries a per-title race table for exactly this |

## 4. The phases

| # | Phase | Emulator | State |
|---|---|---|---|
| 0 | **Obtain and place the disks** | no | **done** — six sides, all readable, found behind `SSB_DISKS` |
| 1 | **Cold read** — stem inventory, every `GEO` decoded, `ITEMS` shape | no | **done** — `tests/test_silverblades.py` |
| 2 | **A character record** | no | **done** — the shipped `SAVEDBASH` party, six characters, decoded and byte-identical on round trip |
| 3 | **Save geometry** | yes, for the header fields | **geometry done, header fields not.** File name, load address, slot, item and roster bases all measured from the shipped save. Party x/y/facing, the clock and the area byte need two saves one known step apart |
| 4 | **The import diff** | yes | not started. The strongest experiment available; needs a Curse party imported and exported |
| 5 | **Live addresses and the automapper run** | yes, exclusively | not started. §5 |
| 6 | **Tests** | no | **done** — `tests/test_silverblades.py`, with Pool of Radiance as the control in every check and a clean skip when the disks are absent |
| 7 | **Constants become a table** | no | **done** — `por/games.py`, all six titles, threaded through `por/savegame.py`, `por/yaml_io.py` and `editor/` |

Phase 7 was planned last on the argument that two games can share code by
accident and three cannot. That held: it was the six-title inventory that
showed the seam is the save container's base address and nothing else, and
`por/games.py` is three numbers wide because of it.

### What phase 2 corrected in its own pass criterion

Phase 2's criterion was "`class_bits` is exactly one bit per non-zero slot of
the array at `0x0C9`". `work/reports/goldbox-inventory.md` §3.3(a) reports it
**failing** on PAINE (`0x80`) and GUY DE VALOIS (`0x40`), and concludes the
criterion covers only the low four bits.

**That is wrong, and the criterion holds unchanged.** The report read the array
at `0x0C9` as four bytes. It is eight — `por/layout.py` names them
`level_magic_user`, `level_cleric`, `level_thief`, `level_fighter`,
`level_knight`, a gap, `level_paladin`, `level_ranger`. PAINE's level 8 sits in
slot 7 and GUY DE VALOIS's in slot 6, which is exactly what bits `0x80` and
`0x40` claim. Checked over every shipped party this machine holds, the
invariant `class_bits == sum(1 << i for non-zero slot i)` holds for **all six
titles**, the Krynn knights included: Champions' STRONGSWORD and Death Knights'
SIR DRYDEN carry `0x10` with slot 4 set. `tests/test_silverblades.py` asserts
it for Silver Blades and `tests/test_curse.py` for Curse.

### What is left, and what blocks it

| left | blocked on |
|---|---|
| the save header's fields — party x/y/facing, clock, area byte (phase 3) | two saves taken one known step apart, which needs the game running |
| the Curse → Silver Blades import diff (phase 4) | the game running, plus a Curse party to import |
| live addresses and the automapper run (phase 5) | the emulator, exclusively one agent, and the game's start-up check |
| export load address and marker byte | no exported character file exists on any of the six sides; one export settles it |
| `ITEMNAMES` and `LIBRARY` resident bases | fittable statically, not done here |
| whether `spells_known` stops at eight bytes | a caster with a spell id above 63; none of the 24 shipped characters in the four new titles has one |
| `por/levels.py`'s caps for this title | table data on the disks; no emulator needed |

Nothing in phases 1, 2 or 6 is blocked, and none of it needed the emulator —
which is the whole reason they were ordered first.

## 5. The automapper validation run

This is the phase the skill exists to make repeatable, and the one where "the
live data is not where we think it is" gets caught instead of quietly wrong.

**What is being asserted.** That `automap` can name the party's square, facing
and area in a game whose live addresses were found *by this run*, not assumed.
Three independent sources must agree:

| source | in Pool of Radiance | for Silver Blades |
|---|---|---|
| the on-screen status line | row 14, `RE_STATUS` = `([NESW]) +(\d+):(\d+) +(\d+),(\d+)` | **check this first — it needs no memory reads at all**. If the row or format differs, `party_fix` returns `None` everywhere and every later symptom is a red herring |
| the memory copy | `$49C0`/`$49C1`/`$49C2` — and it **lags a move** | address unknown; found by this run |
| the map itself | `ResidentGeo` at `$0400`, with `Fingerprint` as the contradiction check | `$0400` is a hypothesis, not a fact |

**Procedure.**

1. `ss -tnp | grep 6502` **before connecting.** A stray `wish` GUI holds the
   port and every `Monitor()` then times out, which looks exactly like a frozen
   game. Never kill a process holding the monitor — that has cost Donald his own
   window once.
2. Get into the world past the game's start-up check, with one binary-monitor
   connection held open.
3. Read the status line first, on its own. Confirm or correct the row and the
   regex before touching memory.
4. Walk a known route — four steps, turn, three steps, then **deliberately bump
   a wall**. At each step capture the status line and a full RAM snapshot.
5. Intersect: the set of addresses holding the observed `(x, y, facing)` triple
   at position A, intersected with the same at position B, is a handful of
   candidates. The bump adds a negative example — the clock advances, the square
   does not. Negative examples are what the earlier area-id search lacked.
6. Sweep both the `cpu` and the `ram` bank for a 1024-byte block matching a
   `GEO` read off the disks, with 480/480 reciprocity. Record where it lands
   whether or not it is `$0400`.

**Pass/fail.**

* position and facing from memory match the status line once the screen settles
  (allow one move of lag on the memory copy — that is documented behaviour, not
  a failure);
* the facing encoding matches Pool of Radiance's, or is written down as a
  difference;
* over twenty steps, `ResidentGeo` and `Fingerprint` never disagree; a refused
  step **narrows** the candidate set rather than raising a contradiction
  (`Fingerprint._narrow` refuses to narrow to zero and counts contradictions —
  a non-zero count is the failure signal);
* running the same route twice gives the same answer.

**Hazards, all of them already paid for once —
see `docs/70-driving-the-game.md`.**

| | |
|---|---|
| **Never leave a checkpoint armed when the socket closes** | VICE re-enters the monitor on a connection that is gone, freezes, and reads nothing new. Only a `pkill` recovers it. Delete every checkpoint at the end of every experiment |
| **One binary-monitor client at a time** | A second connection is accepted and then never answered. `automap` and `tools/session.py` cannot both be live |
| **Connecting stops the machine; resuming costs ~14.3 ms of extra emulated time** | Per `resume()`, not per byte. Batch a poll into one resume; the interval is a speed dial |
| **Match responses by request id** | VICE interleaves unsolicited `STOPPED` events; a naive reader silently returns the *previous* request's data |
| **RAM under I/O needs the `ram` bank** | Query `BANKS_AVAILABLE`; on this build `ram` is bank 1 |
| **Overlays make every address conditional** | Read and check bytes before every write. Patching blind has corrupted a live routine here before |
| **The game polls the CIA matrix directly** | Keydown / hold / keyup / gap, 0.10s/0.14s in menus and 0.15s/0.28s for text. The first burst after a screen change is usually swallowed — verify by effect |
| **Type names lowercase** | `xdotool key W` arrives as `$D7` and the name prompt silently re-prompts on any byte ≥ `$5B` |
| **Disk swapping goes through the text monitor** | Open the binary monitor first, open the text socket once and never close it, never send `x` on it |

One agent runs this phase, alone, and says so in its brief.

## 6. What the run feeds back into the skill

The point of running a skill against a new title is not the title. It is the
skill. **A finding is not closed until `skills/goldbox/SKILL.md` reads
differently, or has been deliberately left alone with a line in
`docs/50-experiments.md` saying why.**

| What the run showed | The edit |
|---|---|
| a prediction held | promote its confidence and name Silver Blades as the second corroboration. "Two games" becomes "three", which is the difference between a pattern and a coincidence |
| a prediction failed | the advice becomes *check, do not assume*, with the Silver Blades counterexample cited by offset. This is the most valuable outcome and should be treated as a success |
| a step cost far more or less than budgeted | reorder the phases. The order of attack is the skill's main claim; a phase that keeps running last should be documented last |
| a step needed something the skill does not mention | name the tool, the file and the invocation. A subagent starts cold; "you will need a save disk" belongs in the skill, not in someone's memory |
| a constant differed | it goes in the per-game constants table in `skills/goldbox/references/`, third column. That table is the skill's most reusable artefact and Silver Blades is what makes it a table rather than a pair |

`docs/116-second-game.md` §7 is the model: it ends by listing every place the
earlier plan was wrong, *including where it was wrong in our favour*. Do the same
here, against the skill.

**What the cold read has already fed back.** Three edits the skill and its
references now carry, all from phases 1 and 2:

* **Enumerate maps by directory scan, never by range.** Silver Blades,
  Champions and Death Knights have no `GEO00` and start at `$10` or `$20`.
  `por/areas.py` says so at the top of its module docstring.
* **The save container's geometry is a per-title constant with three values,
  not six.** `por/games.py` is the table.
* **`spells_known` is at least eight bytes in the later titles.** Recorded in
  `por/layout.py` against the field itself, where anyone reading the record
  will see it.

Still owed to the skill: the whole of phases 3-5, which is where its claims
about live memory and driving the game would actually be tested.

## 7. Out of scope

* **The game's start-up check.** Not discussed, not documented, not in this
  repository in any form.
* **Committing any part of Silver Blades** — code, art, music, manuals, maps,
  scripts, data files, disassembly listings, or a slice of any of them dressed
  as a test fixture. Disks live in `work/`; tests read the player's own.
* **A full `ECL` decode.** Pool of Radiance's took the whole project. Silver
  Blades needs it only if quest flags are ever wanted.
* **An editor UI for Silver Blades** until phases 2–4 have proven the record.
  `wish` opening a save it does not really understand is worse than not opening
  it.
* **Save conversion.** `docs/117-save-conversion.md` is DOS → C64 for Pool of
  Radiance, one direction, and stays that way.
* **The Krynn and Buck Rogers titles.** Different rules sets, separate work.
* **Any second binary-monitor client**, for any reason.
