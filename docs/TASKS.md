# Open tasks

Every task has a **stable code**. A code belongs to one task for life: when a
task closes its code retires with it, and new work takes the next free number.
That way "P44" means the same thing in a conversation three weeks apart.

Each row says what the task is and what it is waiting on. The plan behind a
task, where there is one, is the linked document.

**Keep this file current.** Close a task in the same commit that finishes it,
and add one when the work is agreed rather than when it starts.

**Run a task in a subagent.** The main window coordinates, answers questions
and makes the commits; the work itself goes out. The reason is context, which
is the scarce resource — a subagent's tool output never enters the main window.
See `CLAUDE.md`, "Delegating to subagents", for how to brief one: its own
files, the standing constraints in full, and no commits.

---

## Blocked on Donald

| | task | what is needed |
|---|---|---|
| **P1** | Read the ECL scripts | a person has to read them — [`115`](115-review-the-scripts.md) |
| **P12** | Cut the first `v*` tag | after the Windows run below. The tag also publishes to PyPI, and **PyPI never allows re-uploading a version** |
| **P62** | Run the Windows half of [`122`](122-release-testing.md) | the Linux half is done and passing; the Windows package builds from Actions → release → Run workflow |

## Ready to build

| | task | notes |
|---|---|---|
| **P46** | The VICE instance pool — [`123`](123-parallel-sessions.md) | `tools/instance.py`, and **remove the four `pkill -x` calls** that would kill a running game. Do it when nothing is driving the emulator |
| **P48** | `docs/117` obstacle 3 — the item record's binary tail | the DOSBox harness can now arrange the character that exposes it |
| **P50** | Implement the C64→Amiga port — [`124`](124-amiga-port.md) | unblocked: Pools of Darkness loads a C64 export with no checks at all |
| **P60** | `tools/genitems.py` and `tools/genmaps.py` carry stale prose | they regenerate `docs/85` and `docs/88`, so the docs cannot be fixed by hand |
| **P63** | Merge `wish` and `wish-cli` into one binary — [`129`](129-one-binary.md) | agreed; do it before the first tag |

## Needs an emulator

| | task | notes |
|---|---|---|
| **P8** | Curse tiers 3, 4, 5.2 — [`120`](120-curse-testing.md) | tier 3 is discovery: expect no resident address to transfer |
| **P9** | Silver Blades phases 3–5 — [`121`](121-silver-blades.md) | phase 4, the import diff, decides the field table by the game's own arithmetic |
| **P18** | Finish the high-level test party — [`119`](119-test-party.md) | one class-level diff taken; the rest remain |
| **P3** | Make the wanted saves ourselves | quickfight pair, the trainer ability-score pair, wilderness W1–W12, one taken mid-effect. **Was blocked on Donald playing to those states**; the warp and the trainer runs proved we can drive to them |
| **P19** | Combat log checklist item 7, the scroll | needs a fight with **long** messages, not a long fight |
| **P20** | The 15 areas with no harvested arrival square | do they land somewhere legal? |
| **P48b** | `docs/117` obstacle 7 — does the game accept a save we wrote? | one C64 load in VICE, at the point there is a first converted save |

---

## Retired

A code retires with its task and is never reused.

| | outcome |
|---|---|
| **P2** | citation length ruled on |
| **P4** | the code wheel settled by geometry, not by consulting one |
| **P5** | pushed |
| **P6** | the 1999 zips disregarded |
| **P7** | a Curse save opens, exports and re-imports |
| **P10** | one area table, keyed by title |
| **P11** | debug mode and the Warp row |
| **P13** | the hardcoded `DISKS` constants are gone |
| **P14** | the backend menu |
| **P15** | entering `NEWECL`'s tail is safe |
| **P16** | `$C04B` survives the overlay restart |
| **P17** | `turn_class` never moved from `0x0A3` |
| **P21** | `0x0D9` is `attack_forms` |
| **P22** | `0x0A0` promoted to CONFIRMED |
| **P23** | `capacity()`'s docstring corrected |
| **P24** | `AREA_NAMES` keyed by title |
| **P25** | `SPELLN64` is not a spell table in either game |
| **P26** | `curse_file()` follows the chain, not the block count |
| **P27** | `$6E12` is the disk number |
| **P28** | the Linux build ships `wish-cli` |
| **P29** | Windows output reaches a terminal |
| **P30** | the quest flags are identical across ports |
| **P31** | per-title race and class tables |
| **P32** | per-title item-name addresses |
| **P33** | the `POOL*.D64` globs are per-title |
| **P34** | `Session.prefer` |
| **P35** | the automapper is told which game it is |
| **P36** | the warp constants pinned |
| **P37** | the editor shows each title's own world |
| **P38** | the last hardcoded globs |
| **P40** | Curse's ceilings, racial limits and spell names |
| **P41** | the Sokol Keep bug reproduced in the game |
| **P42** | six D64 variants read |
| **P43** | `$49F2` survives the restart |
| **P44** | `spells_known` is seven bytes by usage |
| **P45** | spells and levels know Curse |
| **P47** | the DOSBox harness, and obstacle 2 |
| **P51** | Amiga Pools of Darkness loads a C64 export |
| **P52** | the protection spreadsheet routed to the private repo |
| **P53** | no duplication in Sokol Keep — the scroll is read, not taken |
| **P49** | the ceilings are the game's: `GEN $1E21` clamps against `$1E5C` |
| **P54** | `$6DD5` demoted to GUESS, and the answered questions dropped |
| **P55** | 49 of 129 names CONFIRMED; the other 77 codes have no C64 carrier |
| **P56** | roster `+0x15` is the die size, and `+0x10` stays the armour bonus |
| **P57** | `$1F` left unnamed |
| **P58** | `60 - (byte & 0x7F)` everywhere; AC 13 pinned |
| **P59** | the guide's rumours filed as `R40`-`R51` |
| **P61** | area 11 is the training hall, and the names are title-cased |
| **P64** | the skill says the square, not the clock |
| **P65** | the whole board folded into `docs/126` |
| **P66** | the game's own import routine read, 12 of our 15 bytes explained |
| **P67** | `STING` has no C64 counterpart — a clean negative |
| **P68** | the preferences dialog, and it reports what it found |
