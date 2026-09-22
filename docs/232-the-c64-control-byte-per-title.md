# The C64 control byte, title by title: control, morale and the trainer flag

Record byte `0x0B8` (`flags_0b8` in `goldbox/layout.py`) read out of all six
C64 titles' own code, so that the Character Editor can replace the raw number
with a control choice, a morale and an ability-altered flag without showing a
meaning a title does not have. It answers the research half of
#623 (Replace the Character Editor's raw Flags 0b8 field with control, morale and ability-altered fields).

**In one paragraph.** In every title bit 7 means the engine drives the
character, and for such a character the low seven bits are a morale the engine
doubles before use. The later five titles clamp the doubled value at 100;
Pool of Radiance does not. **Only Pool of Radiance has an ability-altered
flag in this byte**: its modify screen stores `$01` over the whole byte.
Curse, Silver Blades, Gateway and both Krynn titles have no instruction that
writes the byte for a player character except one that zeroes it, and no
instruction that reads bit 0. No title ever turns a companion back into a
player character. The one route back is Pool of Radiance's temple cure for a
berserk player character, and it keeps only bit 0.

The probe is [`tools/c64/flags0b8.py`](../tools/c64/flags0b8.py). It
classifies every absolute-mode reference to the record's `0x0B8` into the
idioms below, and
[`tests/records/test_flags0b8.py`](../tests/records/test_flags0b8.py) pins the
result against the player's disks. `tools/c64/recordsweep.py --indirect`
finds no `LDY #$B8` / `(zp),Y` access in Pool of Radiance, Curse or Silver
Blades (0 in 589, 412 and 349 files). Grades are `docs/50-experiments.md`'s.

## The census

Files are counted once per distinct content. A site is given as the file and
its payload offset. Where the run-time address is known, it is given as well.

| title | record | references | bit-7 tests | morale read | trainer flag written | control handed back | `CAN'T ADD NPCS` |
|---|---|---|---|---|---|---|---|
| Pool of Radiance | `$6B00` | 42 in 590 files | 22 | `COMBAT +0x191C` (`$211C`), **no clamp** | `GEN +0x0D5F`, `+0x0E23` (`$155F`, `$1623`) | `SQRPACI64 +0x01BE`, `& $01` | absent |
| Curse of the Azure Bonds | `$7C00` | 19 in 413 | 14 | `SECSET64 +0x0214`, clamped at 100 | none | none | `SPELLE20` |
| Secret of the Silver Blades | `$7C00` | 23 in 349 | 19 | `SECSET64 +0x0229`, clamped | none | none | `GEN` |
| Gateway to the Savage Frontier | `$7C00` | 24 in 405 | 17 | `SECSET64 +0x0214`, clamped | none | none | `SPELLE20` |
| Champions of Krynn | `$7C00` | 18 in 330 | 14 | `SECSET64 +0x0239`, clamped | none | none | `GEN` |
| Death Knights of Krynn | `$7C00` | 18 in 277 | 14 | `SECSET64 +0x022E`, clamped | none | none | `GEN` |

Pool of Radiance's 42 include `POOLBOOT`'s `POOLRB`, which holds a second
copy of `GEN`'s code at payload offsets 0x500 lower. It is counted apart and agrees with it
site for site. Gateway's one `read, other` is inside
`GATEWAY TO.. /GP`, where the bytes around it do not decode as a routine.
Every other read in all six titles is either a bit-7 test (`LDA`/`LDX`, then
`BPL`/`BMI`) or the modify screen saving the byte to a copy.

## Bit 7: who controls the character

CONFIRMED in all six titles. Every read of the byte tests bit 7 with
`BPL`/`BMI` except the four copies in Pool of Radiance's modify screen. The
same test gates the party-money pool, the treasure split, the six-character
limit and the ADD CHARACTER checks. `docs/195` has the DOS side, where
`0xB3` (a berserk player character) is also above `0x80`.

## The low seven bits of a companion: morale

**Encoding, CONFIRMED in all six.** The consumer is the same routine in every
title: `LDA 0x0B8 / BPL out / AND #$7F / ASL A`, so the value the engine uses
is **twice the stored seven bits**. The five later titles then run
`CMP #$64 / BCC / LDA #$64`, capping it at 100, before `EOR #$FF / SEC /
ADC #$64` turns it into `100 - morale`. That is compared against the
character's current hit points as a percentage of his maximum (`0x119`,
`0x076`). Pool of Radiance's `COMBAT $211C` has no cap. A stored value above
50 doubles past 100, and `100 - morale` wraps modulo 256: stored 127 gives 254,
and the check sees 102.

**So the decoded game value is `2 × (byte & 0x7F)`, in steps of 2**, and
the only values that mean the same thing in all six engines are 0 to 100,
stored `$80` to `$B2`. A byte of `$80` is morale 0. It is not "no morale".

**Producers.** Every title has the same two script commands in `DUNGEON`:

| command | Pool of Radiance | later titles | what happens to the low bits |
|---|---|---|---|
| join with a morale | `$2753`: fetch argument, `LSR A`, `ORA #$80`, `STA` | Curse `+0x211C`, Silver Blades `+0x2051`, Gateway `+0x20C6`, Champions `+0x2060` | **replaced** by the argument halved |
| join, morale untouched | `$1AF6`: `LDA #$80 / ORA 0x0B8 / STA` | Curse `+0x14A6`, Silver Blades `+0x13D6`, Gateway `+0x1633`, Champions `+0x13D2`, Death Knights `+0x11EA` | **kept**: whatever the loaded record held |

**Death Knights of Krynn does not halve.** Its "join with a morale" at
`DUNGEON +0x1BF9` is `JSR $1A76 / LSR $11FA / ORA #$80 / STA`, and `$11FA`
is the operand byte of a `JSR $1322` at `$11F9` in the same file. The shift
modifies code rather than the argument in `A`. So the script argument is
stored whole, and the cap at 100 turns any argument of 50 or more into 100.
PROBABLE, because the only Death Knights images here are a cracked release
(`[cr TRD][h DOHI]`). An original SSI image with the same bytes at that offset
would confirm it; `LSR A` (`4A`) followed by two filler bytes would refute it.

**What the monster files hold**, because the "morale untouched" command keeps
whatever the loaded `MON*` record holds (byte `0x0B8` of every distinct
`MON*` payload):

| title | files | values |
|---|---|---|
| Pool of Radiance | 135 | `$FF` x130, `$B2` x5 |
| Curse | 70 | `$80` x49, `$B2` x13, `$FF` x7, `$9E` x1 |
| Silver Blades | 71 | `$80` x60, `$B2` x11 |
| Gateway | 71 | `$99` x21, `$B1` x19, `$80` x12, `$9E` x7, `$A5` x7, `$94` x2, `$96`, `$97`, `$A8` |
| Champions of Krynn | 57 | `$80` x36, `$B2` x15, `$E4` x6 |
| Death Knights of Krynn | 63 | `$B2` x32, `$80` x26, `$A8` x2, `$94`, `$9E`, `$AD` |

Gateway's are graded (morale 40 to 98), which is the halved percentage used
as designed. Pool of Radiance's `$FF` is stored morale 127, which its
unclamped check reads as 102.
SPECULATIVE: `$FF` is a sentinel for "use the encounter's default", as DOS
Pool of Radiance treats a low-seven value of 0 or above `0x66` at
`GAME.OVR 0x00D976` (`docs/195`). No C64 site that reads `0x0B8` tests for it.
To settle it, load a Pool of Radiance encounter whose monster file holds `$FF`
under VICE with a watchpoint on the combatant's copy of the byte, and see
whether anything rewrites it before `COMBAT $211C` reads it. A rewrite
confirms the sentinel; the check reading `$FF` refutes it.

**The `$FE`/`$FF` hazard in Pool of Radiance, CONFIRMED from the code.**
`SQRPACI64` is the temple (`PAY FOR CURE`). Its routine at `+0x019A`
clears effect `$20` from the character's effect slots and then runs `LDA 0x0B8 / CMP #$FE / BCC / AND #$01 / STA`.
That turns any byte of `$FE` or `$FF` into `$00` or `$01`, which makes a
player character of whoever holds it. It is the counterpart of `SPELLE00 +0x0480`
and `SPELLE04 +0x0304`, which set a player character's byte to `old | $FE`
and a companion's to `$B2`. So in Pool of Radiance a companion stored at
morale 252 or 254 is indistinguishable from a berserk player character, and
the editor must not write `$FE` or `$FF` for one.

## Bit 0 of a player character: the trainer flag

**Pool of Radiance, CONFIRMED.** `GEN $1475` saves the ability array, the
byte (`$1480`, to `$2B46`) and the hit points before the modify screen runs.
`DEC 0x014,X` (`$14E0`) and `INC 0x014,X` (`$1526`) are the ability steps and
both reach `$155D: LDA #$01 / STA 0x0B8`. `INC`/`DEC` of `hp_max` (`$1618`,
`$1604`) reach `$1621: LDA #$01 / STA 0x0B8`. Leaving without keeping restores
the saved copy (`$157F`, `$15DD`). So the flag records **an ability score or
the hit points** changed and kept in MODIFY CHARACTER, not only an ability
score. It is a whole-byte store of `$01`, not an `ORA`, and nothing in the
title reads bit 0 back.

PROBABLE, from the code and not driven: the only gate in front of the modify
screen is `GEN $1AEE: LDA 0x0A0 / CMP #$02 / BCC` (level below 2). It does
not test bit 7, and Pool of Radiance's ADD CHARACTER lets a roster companion
join outside the six-player count (`GEN $193B: BMI` past `CMP #$06`). So a
level-1 companion on the roster could be modified, and a kept change would
store `$01` over his control byte, making him a player character. To settle
it, take a copy of `npc_party.d64`, give a companion level 1 and experience
0, open MODIFY CHARACTER on him in VICE, change a score, keep it and save. A
record reading `$01` confirms it; the screen refusing him refutes it.

**Curse, Silver Blades, Gateway, Champions and Death Knights: no such flag,
CONFIRMED.** Curse's modify screen (`GEN $1D35` asks "MODIFY WHICH CHARACTER?", `$1D78`
gates on experience, `$1D9B` runs the screen) and Silver Blades' (`GEN
$1D1A` onward) edit `abilities_second` at `0x065`, copy it into `0x014` at
`$1E9C` / `$1F0F`, and step the hit points through `hp_rolled` at `0x0ED`. Neither writes `0x0B8`. In the five titles
together, **the only writes to the byte** are the two join commands above
and one other: a routine in Curse's and Gateway's `SPELLE20` (`+0x0596`,
`+0x055C`). It clears the memorised spells (`0x020`), the inventory (`0x120`,
256 bytes), the money (`0x0BB`-`0x0C8`), the portrait bytes `0x0FE`-`0x0FF`
and `0x0D3`-`0x0D4`, copies `0x014` into `0x065`, and then stores `$00` into
`0x0B8` behind `LDX 0x0B8 / BMI`, so for a player character only. The same file holds the `GAME BEFORE HILLSFAR:`
prompt, and the routine runs only when `$2CE1` is 1. PROBABLE that it is the
import of a Pool of Radiance or Hillsfar character, which would mean **a
Pool of Radiance character imported into Curse arrives with the flag
cleared**. `INC 0x014,X` does occur in Curse's `COMBAT2`, `ECL65` and
`SPELLE65` (and Gateway's last two). Each is a capped one-point raise
(`CMP #$12 / BCS`) with no write to `0x0B8` beside it.

What the saves on this machine hold agrees: 85 of 85 Curse and 66 of 66
Silver Blades C64 records read `$00`, and Pool of Radiance's 16 `$01` records
are BRUTUS on the `PORSAVE*` disks and their specimen copies
(`tools/records/controlbyte.py`). Those saves have no chain of custody, so the
code is the evidence and the census corroborates.

**The other ports, from `docs/195` and a re-run of
`tools/dos/dosbyteimm.py`.** DOS keeps the flag in the share byte, not the
control byte. MODIFY CHARACTER's KEEP stores `1` there whether or not
anything changed: Pool of Radiance `0x085` at `GAME.OVR 0x01C263`, Curse
`0x0F8` at `0x023463`, Silver Blades `0x100` at `0x0208A9`. All three are
CONFIRMED, and the Pool of Radiance one was also watched in DOSBox. **Pools of
Darkness has no site at all** for `0x148` in `GAME.OVR` or `GAME.EXE` (0 of 2
images). The 4 of its 12 records reading 1 hold a value it inherited. Amiga
Pool of Radiance keeps the share at `0x086`: PROBABLE that KEEP writes it
there too, from the six game-written records that read `01`. UNKNOWN for the
other Amiga titles: no store site has been read.

## Changing control, and what happens to the low bits

| path | titles | player → engine | engine → player |
|---|---|---|---|
| script "join with a morale" | all six | low bits replaced by the argument halved (Death Knights: not halved) | -- |
| script "join, morale untouched" | all six | bit 7 set, low bits kept | -- |
| berserk spell `SPELLE00`/`SPELLE04` | Pool of Radiance | `old \| $FE`, so bit 0 survives in bit 0 | a companion is set to `$B2`, morale 100, and it is never restored |
| temple cure `SQRPACI64` | Pool of Radiance | -- | `& $01`, only when the byte is `$FE` or `$FF` |
| import reset `SPELLE20` | Curse, Gateway | -- | a player character's byte set to `$00`; a companion's untouched |
| ADD / REMOVE CHARACTER | all six | no write; the later five refuse a companion ("CAN'T ADD NPCS") | no write |

CONFIRMED for every row as code. The berserk and cure pair is the only
reversible transition in any title. **No instruction in any of the six turns
a companion into a player character.** The DOS engine's equality test at
`GAME.OVR 0x0251B7` (`docs/195`) wants a player character's DOS control byte
to be exactly `0x00`.

**So an editor switch that does what the engines do:**

* **Player → game-controlled:** write `0x80 | (morale / 2)` with a morale the
  user chooses, as the "join with a morale" command does. OR-ing `$80` into a
  Pool of Radiance player character's `$01` would turn his trainer flag into
  morale 2. That is what the "morale untouched" command would do, but that
  command runs on the record it has just loaded (`JSR $1219` in front of it),
  PROBABLY a monster file, not on a player character.
* **Game-controlled → player:** write `$00`. That is what every
  player-character writer produces except the Pool of Radiance modify screen
  and the berserk cure. A companion's bit 0 is the low bit of his morale, and
  keeping it would invent a trainer flag. DOS demands `0x00` for the same
  character.

## What the editor can show safely

| title, port | Control | Morale | Abilities altered |
|---|---|---|---|
| Pool of Radiance, C64 | yes: bit 7 | yes: `2 × (b & 0x7F)`, 0-100 step 2; refuse `$FE`/`$FF` | yes for a player: bit 0, meaning ability **or hit points** changed and kept |
| Curse, Silver Blades, Gateway, Champions, Death Knights, C64 | yes | yes, 0-100 step 2; the engine caps anything above at 100 | **no**: nothing writes or reads it; a set bit 0 is not the game's |
| Pool of Radiance, Curse, Silver Blades, DOS | yes: control byte (`docs/195`) | yes, same encoding (`docs/195`) | yes, but it is the share byte and means "left MODIFY by KEEP" |
| Pools of Darkness, DOS | yes | yes | **no**: the engine has no writer |
| Pool of Radiance, Amiga | yes | yes | PROBABLE only |
| other Amiga titles | yes | yes | UNKNOWN |

The morale and ability-altered fields never apply to the same record. A
companion's low bits are morale, a player character's bit 0 is the flag,
and bit 7 decides which, in every title.

**Values the editor may meet but the engines never produce as morale:** a
stored value of 51 to 127, which reads above 100 (130 of Pool of Radiance's
135 monster files hold 127, and Champions of Krynn has six at 100, reading
200). A display clamped to 100 matches the five later engines and not Pool
of Radiance. Showing the decoded value unclamped, read-only when it is above
100, is the reading every engine agrees with.

## What is not established

* Pool of Radiance's `$FF` monster morale as a sentinel: SPECULATIVE, with the
  experiment above.
* A level-1 roster companion modified in Pool of Radiance: PROBABLE, with the
  experiment above.
* Death Knights' unhalved producer on an uncracked image: PROBABLE.
* The consequence of failing the morale check: not read here. `docs/195`
  already grades the *name* morale PROBABLE for the same reason.
* The Amiga ports' modify flag, beyond Pool of Radiance's six records.
