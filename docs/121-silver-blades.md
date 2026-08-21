# Secrets of the Silver Blades — plan for running the Gold Box skill

**Status: blocked at phase 0. The disks are not on this machine.** Everything
past phase 0 is written, costed and ready, and none of it can start.

## 1. The blocker

```
$ ls "/home/donald/c64/All Games" | grep -iE 'silver|secret|ssb'
```

Seventeen hits out of 6002 archives, and **not one is Secrets of the Silver
Blades**. They are the publisher Silverbird (`Scuba_Kidz`, `Combat_Crazy`),
Silverrock, `Legend_of_Blacksilver`, `Quicksilver`, `Black_Lamp` ("Secret
Society"), `marble_madness_secret_level`, `secret.zip`, `secretms.zip`, and
`ssbasebl` / `ssbsktbl` — Street Sports Baseball and Basketball. A wider sweep
of `/home/donald/c64`, `~/Downloads` and `work/` for `*silver*`, `*blades*` and
`*ssb*` returns nothing at all.

The title is simply not here. No amount of planning gets past that.

### What Donald has to supply

| | |
|---|---|
| **What** | A `.d64` set of the C64 release — every side. How many sides the C64 version shipped on is not known here; take whatever the rip has |
| **Also wanted, and nearly as important** | a **save disk written by the game**, with a real party on it. Phases 3–5 are all diffing saves, and a game disk alone cannot start them |
| **Best of all** | a Curse of the Azure Bonds party **imported into Silver Blades and exported again**. That single artefact is phase 4, and phase 4 is where the strongest evidence in this project has always come from |
| **Where** | `work/silverblades/` — `work/` is gitignored, which is where `CLAUDE.md` says disk images belong. `work/curse/` is the precedent |
| **How the tests find it** | a `SSB_DISKS` environment variable plus a candidate list, mirroring `COAB_DISKS` in `tests/gamedata.py:83` exactly. Skip when absent, never fail |

Nothing about the disks may be committed. `tests/test_repository_contents.py`
enforces that and **its allowlist must not grow**.

### A note on the skill

`skills/goldbox/SKILL.md` did **not exist** when this was written. The phases
below are derived from `docs/60-goldbox-field-checklist.md` and
`docs/116-second-game.md`, which is what the skill is being distilled from, so
they should align; whoever runs this should read the skill first and reorder to
match it rather than the other way round.

## 2. Ordering — do not wait for these disks

The argument for Silver Blades is real: it is the direct sequel, it shares the
most with Pool of Radiance and Curse, and **it is the only remaining title that
imports a Curse party**, which is the lever that produced the 15-bytes-of-580
result in `docs/116-second-game.md`. Gateway and the Krynn titles start fresh
parties and cannot offer it.

The counter-argument is that it costs an unbounded wait, and three Gold Box
titles are sitting on this machine already.

**Recommended order:**

1. **Finish Curse** — `docs/120-curse-testing.md`. On disk, partly done, and it
   still has named unknowns (the item area at `$5B00`, the spellbook bitmask
   width, the combat slots). Closing those makes every later title cheaper.
2. **Ask for the Silver Blades disks now**, in parallel. Phase 0 is latency, not
   work; it costs nothing to start it today.
3. **If the disks do not arrive, run the skill against Gateway to the Savage
   Frontier** (`Gateway_to_the_Savage_Frontier_with_docs.SSI.Mirage.zip`). Same
   rules set, same Forgotten Realms class list, on disk, untouched — the closest
   substitute available, and its failures improve the skill just as well.

Champions of Krynn, Death Knights of Krynn and Buck Rogers are all present and
are all further away: Dragonlance and 25th-century rules mean different classes,
different caps and a record that is expected to diverge more. They are a fourth
target, not a third.

## 3. What is expected to transfer, and what is not

Curse shares the 580-byte record with Pool of Radiance *at every offset*, and
that is not a diff of two specimens — it is the game's own import arithmetic.
Two of three titles holding a structure stable is real evidence the family does.
Everything below inherits its confidence from that.

| | Prediction for Silver Blades | Confidence |
|---|---|---|
| character record size 580 bytes | same | **LIKELY** |
| every field in `por/layout.py`, same offset, same width | same | **LIKELY** |
| save slot = first 256 bytes of the record, `$100` stride | same | **LIKELY** |
| roster block = record `0x100`–`0x11F` | same | **LIKELY** |
| `60 - value` encoding for THAC0, AC, damage bonus | same | **LIKELY** |
| `GEO`: 1024 bytes, four 16×16 planes, `por/geo.py` unmodified | same | **LIKELY** |
| `ITEMS` 128 × 16; `ITEMNAMES` 256 low + 256 high + strings | same shape | **LIKELY** |
| D64 container, PRG load address, `\x01`-style marker prefix on exports | same mechanism | **CONFIRMED** for the container; the marker *byte* differs |
| second ability array at `0x065`, fighting level at `0x098` | present, as in Curse | **PROBABLE** |
| spell ids 1–56 unchanged, more added above | as Curse did | **PROBABLE** |
| resident `GEO` left at `$0400` | plausible, **must be re-verified** — it holds only because the screen has moved to `$CC00` | **UNKNOWN** |
| save file **count and names** | Pool of Radiance has two (`SAVEDGAME0`/`SAVEDGAME1`), Curse one (`SAVEAZURE`). Assume neither | **EXPECTED TO DIFFER** |
| save load addresses and header base | `$4900` / `$4B00` respectively; a third value is expected | **EXPECTED TO DIFFER** |
| export load address and marker byte | `$6B00`/`$01`, `$7C00`/`$02`; a third pair expected | **EXPECTED TO DIFFER** |
| `ITEMNAMES` resident base | `$6F00`/`$9E00`; a third | **EXPECTED TO DIFFER** |
| `LIBRARY` `GEO` stem table address | `$24B4`/`$2714`; a third | **EXPECTED TO DIFFER** |
| live party x/y/facing address | `$49C0`–`$49C2` / `$4BC0`–`$4BC2`; a third | **EXPECTED TO DIFFER** |
| file stems (`GEO`, `ECL`, `ITEMS`, …) | may be renamed wholesale | **UNKNOWN** |
| status-line row and format on screen | row 14, `E 16:48 5,2` in Pool of Radiance. Unverified anywhere else | **UNKNOWN** |

**The rule the table encodes:** *structure* transfers, *addresses* do not. Every
absolute number in `por/` and `automap/` is a Pool of Radiance constant and must
be re-measured, not assumed.

### What being a sequel changes

| Difference | What it implies |
|---|---|
| **Party is imported from Curse, not rolled** | The import routine is the experiment. It writes the target record from a source we already decode byte for byte, so phase 4 gives a field-by-field answer with no disassembly at all — exactly how Curse was settled |
| **Higher level range** | `por/levels.py` is table data, not shape; caps rise, the eight-byte per-class array at `0x0C9` does not move. Watch the 24-bit experience field for saturation, and the two-byte max-HP field at `0x076` for headroom (the C64 already has two bytes; DOS has one) |
| **Higher spell levels than Curse** | This is a **gift**. `docs/116-second-game.md` lists "how wide the spellbook bitmask at `0x078` is" as NOT FOUND, because no Curse specimen writes past `0x07D`. A Silver Blades caster should, and the first one that does settles a question two games could not |
| **Dual- and multi-classed characters are common at this level** | The dual-class array is NOT FOUND in Curse. Silver Blades parties will carry real values in it |
| **No city-block/wilderness structure** | Fewer `GEO` files expected, and the wilderness travel bytes (`$49C3`/`$49C4` in Pool of Radiance) may be dead. Do not read their absence as a layout change |

## 4. The phases

| # | Phase | Produces | Cost | Emulator | Pass/fail |
|---|---|---|---|---|---|
| 0 | **Obtain and place the disks** | `work/silverblades/*.d64`, an `SSB_DISKS` hook in `tests/gamedata.py` | Donald's, not ours | no | `por/d64.py` opens every side and lists a directory. A 175531-byte rip with error bytes is refused, as one Curse side is — skip it, do not fail |
| 1 | **Cold read** | file-stem inventory across sides; every `GEO` decoded; `ITEMS`/`ITEMNAMES` shape; the constants table above filled in for load addresses | hours, offline | no | every `GEO` clears **92% reciprocity** through `por/geo.py` *unmodified* (Curse's worst is 93.5%); `ITEMS` length divisible by 16 |
| 2 | **A character record** | one 580-byte specimen — from a shipped pre-generated party if the disks carry one (Curse ships `SAVEAZURE` on two sides, at two different lengths, and a reader taking the first match gets the wrong one), otherwise from play | hours | only to produce a save | `CharacterRecord.from_bytes` decodes and round-trips **byte-identically**; `class_bits` is exactly one bit per non-zero slot of the array at `0x0C9` |
| 3 | **Save geometry** | file name(s), load address, header base, party x/y/facing, area byte, roster and item-area locations | a day | yes, to produce two saves | two saves taken one known step apart differ at **exactly** the position triple and the clock. Anything else moving means the header is not where we placed it |
| 4 | **The import diff** | the transferable/not table, decided by the game's own arithmetic | a day | yes | fewer than ~30 of 580 bytes differ, and **every** difference is named. Curse's answer was 15, all explained |
| 5 | **Live addresses and the automapper run** | live party triple, resident `GEO` location, a validated `Fix` | the expensive one | yes, exclusively | §5 |
| 6 | **Tests** | `tests/test_third_game.py` beside `test_second_game.py` — same invariants, third game | half a day | no | the Pool of Radiance control still passes; the Silver Blades half **skips** cleanly when the disks are absent, which is how CI will see it |
| 7 | **Constants become a table** | per-game constants in one place instead of a third set of module-level literals | half a day | no | `por/savegame.py`, `por/items.py`, `automap/target.py`, `automap/area.py` and `automap/paths.py` stop hardcoding Pool of Radiance and take a game parameter |

Phase 7 is deliberately last. Two games can share code by accident; three cannot,
and the third is the one that shows where the seams belong. Doing it earlier
means guessing at the seams from Curse alone.

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
