# Open tasks

Every task has a **stable code**. A code belongs to one task for life: when a
task closes its code retires with it, and new work takes the next free number.
That way "P44" means the same thing in a conversation three weeks apart.

Each row says what the task is and what it is waiting on. The plan behind a
task, where there is one, is the linked document.

**Keep this file current.** Close a task in the same commit that finishes it,
and add one when the work is agreed rather than when it starts.

---

## Blocked on Donald

| | task | what is needed |
|---|---|---|
| **P1** | Read the ECL scripts | a person has to read them — [`115`](docs/115-review-the-scripts.md) |
| **P3** | Saves still wanted | two quickfight saves, the trainer ability-score pair, wilderness W1–W12, one taken mid-effect |
| **P12** | Cut the first `v*` tag | after the Windows run below. The tag also publishes to PyPI, and **PyPI never allows re-uploading a version** |
| **P62** | Run the Windows half of [`122`](docs/122-release-testing.md) | the Linux half is done and passing; the Windows package builds from Actions → release → Run workflow |

## Ready to build

| | task | notes |
|---|---|---|
| **P46** | The VICE instance pool — [`123`](docs/123-parallel-sessions.md) | `tools/instance.py`, and **remove the four `pkill -x` calls** that would kill a running game. Do it when nothing is driving the emulator |
| **P48** | `docs/117` obstacle 3 — the item record's binary tail | the DOSBox harness can now arrange the character that exposes it |
| **P50** | Implement the C64→Amiga port — [`124`](docs/124-amiga-port.md) | unblocked: Pools of Darkness loads a C64 export with no checks at all |
| **P55** | Verify the trait and effect names against records | 129 named, 44 CONFIRMED and 84 PROBABLE |
| **P60** | `tools/genitems.py` and `tools/genmaps.py` carry stale prose | they regenerate `docs/85` and `docs/88`, so the docs cannot be fixed by hand |
| **P61** | `por/areas.py` still calls area 11 "the arena" | it is the training hall. Area 24's name is contested — leave it until the warp experiment runs |
| **P63** | Merge `wish` and `wish-cli` into one binary — [`129`](docs/129-one-binary.md) | agreed; do it before the first tag |

## Needs an emulator

| | task | notes |
|---|---|---|
| **P8** | Curse tiers 3, 4, 5.2 — [`120`](docs/120-curse-testing.md) | tier 3 is discovery: expect no resident address to transfer |
| **P9** | Silver Blades phases 3–5 — [`121`](docs/121-silver-blades.md) | phase 4, the import diff, decides the field table by the game's own arithmetic |
| **P18** | Finish the high-level test party — [`119`](docs/119-test-party.md) | one class-level diff taken; the rest remain |
| **P19** | Combat log checklist item 7, the scroll | needs a fight with **long** messages, not a long fight |
| **P20** | The 15 areas with no harvested arrival square | do they land somewhere legal? |
| **P48b** | `docs/117` obstacle 7 — does the game accept a save we wrote? | one C64 load in VICE, at the point there is a first converted save |

## Corrections outstanding

| | task |
|---|---|
| **P49** | `docs/119` calls the level ceiling PROBABLE; the routine is `GEN $1E20` |
| **P54** | `docs/118` open question 5 — `$6DD5` is demoted to GUESS |
| **P56** | `por/savegame.py`'s roster field names look wrong — `+0x15` is the primary attack die sides |
| **P57** | Demote `$1F` from `ADDRESSOF`; the guide says unimplemented and our sweep counts zero uses |
| **P58** | The armour rule is a special case of `60 - (byte & 0x7F)` and diverges at AC 13 |
| **P59** | File the guide's candidate rumours in [`125`](docs/125-bug-notes.md) |
| **P64** | `skills/goldbox/SKILL.md` asserts "a bump advances the clock" as fact; nobody has watched the clock during a bump |

## Waiting on the community sweep

| | task |
|---|---|
| **P65** | Fold `work/reports/forum-sweep.md` into [`126`](docs/126-forum-findings.md) — 296 threads read, 455 external URLs probed |
| **P66** | `github.com/simeonpilgrim/coab` is a primary source: the DOS record, and the import routine that sets money to 300 platinum and erases Animate Dead. Two candidates for our fifteen changed bytes |
| **P67** | The DOS builds ship a second cheat mode, `start.exe STING`. Grep the C64 overlays for the literal |

---

## Retired

**P2** citation length ruled on · **P4** the code wheel settled by geometry ·
**P5** pushed · **P6** old zips disregarded · **P7** a Curse save opens ·
**P10**/**P24** one area table, keyed by title · **P11**/**P14** debug mode and
the backend menu · **P13** hardcoded `DISKS` gone · **P15**/**P16** the warp
mechanism proven live · **P17** `turn_class` never moved · **P21** `0x0D9` is
`attack_forms` · **P22**/**P23**/**P25**/**P26**/**P27** field corrections ·
**P28**/**P29** packaging and Windows output · **P30** the quest flags are
identical across ports · **P31**/**P32** per-title tables · **P33**–**P35**
per-title paths · **P36** the warp constants · **P37**/**P38** the editor shows
each title's own world · **P40** Curse's ceilings and spell names ·
**P41** the Sokol Keep bug reproduced · **P42** six D64 variants ·
**P43** `$49F2` survives · **P44** `spells_known` is seven bytes ·
**P45** spells and levels know Curse · **P47** the DOSBox harness ·
**P51** the Amiga import assumption refuted · **P52** the protection
spreadsheet routed to the private repo · **P53** no duplication in Sokol Keep
