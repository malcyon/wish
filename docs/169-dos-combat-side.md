# DOS record `0x10E` is the combat side, and the C64 keeps it in `0x10C`

The last unknown byte of `#235 (Two unattributed DOS byte ranges in the
combat tail are dropped converting to C64, and nobody knows what they
hold)`, settled from the code rather than from specimens, because no
player-character record can ever show it: every engine-written `CHRDAT`
holds 0 there. Read out of `GAME.OVR` (Pool of Radiance 1.3) and the
resident `START.EXE` with `tools/dosfieldrefs.py`, `tools/dosovrmap.py` and
`tools/dosdis16.py`; checked in the running game with
`tools/dostailprobe.py` and `tools/dossideprobe.py`. Listings and frames
are under `work/issue235/`. Grades are `docs/50-experiments.md`'s.

## The byte -- CONFIRMED

`0x10E` is the side a combatant fights on: **0 the party's, 1 the
enemy's.** It is stored, not scratch: staged 1 on one character, the
engine's own `ENCAMP > SAVE` wrote it back unchanged.

| evidence | what it shows |
|---|---|
| `MON1CHA.DAX`-`MON8CHA.DAX`, 172 records | `0x10E` = 1 in 171, 0 in one (EFREETI, `MON4CHA.DAX` block 70); 0 in every player record of the census |
| resident `0x2F7B` | zeroes `ds:0x6814`, `ds:0x6815`; for every active combatant (`0x10D` != 0) `inc [0x6814 + 0x10E]` -- a two-entry per-side count, so the value is 0 or 1 |
| resident `0x2E9A` | `dec [0x6814 + 0x10E]` when damage takes a combatant out |
| `GAME.OVR:0x98A2`, `0xA163`, `0xA178` | the fight ends when either count is 0; victory is `[0x6814] > 0 and [0x6815] == 0`, which is what makes 0 the party's side |
| resident `0x2F57` (`BA:23B7`) | returns `1 if 0x10E == 0 else 0`: the opposite side. Six `cmp al, es:[di+0x10E]` sites are the target picker walking one side or the other |
| `0x1638E` | the typed word `STING` ("The Gods intervene!") sets every `0x10E == 1` combatant to `0x10D` = 0, `0x10C` = 6 Dead |
| `0x15193` | `Attack Ally:` -- aiming at a combatant on the attacker's own side prompts, and `Y` turns every Okay combatant with `0x084 >= 0x80` to side 1: the joined-NPC betrayal rule |
| `0x2911D`-`0x29207` | Animate Dead: the corpse takes the caster's side, `0x10F` = 1, `0x10C` = 1 Animated |
| `0xF076`, `0xF0D3`, `0xF7B7` | combat setup writes it from the encounter's monster entry, with `0x10F` = 1 beside it |
| `0xD947` | a side-1 combatant's facing is turned by four at setup |
| resident `0x23B7` | name colour: `0x10D == 0` -> `0x0C` light red; `0x10E == 1` -> `0x0E` **yellow**; else `0x0B` light cyan |

Running game, one boot (`tools/dostailprobe.py --pattern
0:00010000,1:00010100`): MAGNUS staged `0x10E` = 1 in Donald's slot A was
drawn **yellow** on the party panel between BRUTUS in white and four names
in light cyan (`work/issue235/side-name/01-loaded.png`), and the resave
holds `00 01 01 00` for him and `00 01 00 00` for the other five.

## What a player would notice

A party member whose record says side 1 is, to the engine, a monster who
happens to be in the party list: his name is yellow on the main screen; in
a fight he is counted on the enemy side, faces the other way, is hunted by
the party's computer-run members and ignored by the monsters, gets
`Attack Ally:` when he aims at one, and **the fight cannot end while he
stands**, because `[0x6815]` never reaches zero.

Measured, one fight (`tools/dossideprobe.py`, `work/issue235/side-fight/`):
BAKSHI of Donald's slot J staged `00 01 01 01`, the other five `00 01 00
01` so the fight ran itself. His name was yellow at the encounter; the
combat log read `BAKSHI ATTACKS BROTHER SEAN HITTING FOR 7 POINTS OF
DAMAGE`; the fight ended with two of the party at 0 hit points; and the
engine's own `ENCAMP > SAVE` wrote **five** records -- BAKSHI was no
longer in the party.

## The DOS engine's own conversion table -- CONFIRMED

The ECL script interpreter addresses character fields by the **C64
record's offsets** and `GAME.OVR` translates each to the DOS layout. The
two entries that matter here:

| script field | read (`0x7DC9`-`0x7E25`) | write (`0x803F`-`0x80CB`) |
|---|---|---|
| `0x100` | `1` if `0x10D` != 0, else `0x80` | `>= 0x80` -> `0x10D` = 0; `0x87` also `0x10C` = 7 Stoned |
| `0x10C` | `0x81` if `0x10E == 1`; `0x80` if `0x10F` != 0; else `0` | `0` -> `0x10E` = 0, `0x10F` = 0; `0x80` -> `0`, `1`; `0x81` -> `1`, `1` |

That is `docs/128-guide-and-scripting.md`'s C64 `0x10C` -- 0 allied and
controlled, 128 allied and uncontrolled, 129 hostile -- so **C64 `0x10C`
bit 0 is DOS `0x10E` and bit 7 is DOS `0x10F`.** C64 saves agree: over 17
`.d64` images (`work/`, the player's disks, `~/wish-specimens/`), 104
occupied roster slots hold `0x10C` = `0x00` in 99 and `0x80` in 5, never
`0x81`.

## The conversion

| direction | rule |
|---|---|
| DOS -> C64 | record `0x10C` = `(0x80 if 0x10F else 0) \| (1 if 0x10E else 0)` |
| C64 -> DOS | `0x10E` = `0x10C & 1`; `0x10F` = `0x10C >> 7` |

Every engine-written player record on this machine converts to `0x00` or
`0x80`, so nothing a player owns changes value; what changes is that the
byte is converted rather than filled. The specification for
`goldbox/layout.py`, `goldbox/dos_layout.py` and the two codecs is on the
issue.

## Beside it: `0x084` -- PROBABLE

`Attack Ally` tests `0x084 >= 0x80`; combat setup writes it `0xB2`/`0xB3`
and clears a `0xB3`. Monster records hold `0x083`-`0x084` = `FF FF` (or
`FF B2`) where every player record holds `00 00`, and `0x085` varies (`00`
in 123, `FF` in 38, `01`, `03`, `84` in one or two each). So bit 7 of
`0x084` marks a creature that is not a player character, consistent with
the workbook's `Morale`. The settling specimen is a joined NPC's `CHRDAT`
record from a driven run.
