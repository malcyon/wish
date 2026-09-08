# What the game says when a monster attacks

**One routine prints every melee attack, whoever swung.** There is no monster
path and no monster vocabulary: `COMBAT $0D63` builds the line for a character
and for an orc out of the same string table, into the same sixteen-column
panel, with the same delay and the same clear that
[`110-combat-log.md`](110-combat-log.md) documents.

Taken for `#350 (The Messages window logs the party's attacks and dice but
nothing a monster does)`, whose description said the message half had never
been measured. It has now, and the answer contradicts both halves of that
description.

## The routine — CONFIRMED, from the overlay

```
$0D63  JSR $12E6        ; the attacker resident at $6B00
$0D66  LDX #$29         ; message 41, ATTACKS
$0D68  JSR $2983        ;   clear the panel, print the name at $6B00, then it
$0D6B  JSR $2744        ; the *target* resident at $6B00
$0D76  JSR $34BD        ;   its name, on the next row
$0D79  LDX #$2A         ; message 42, AND MISSES...
$0D7B  LDA $A4FB        ; the hit flag
$0D7E  BNE $0D86        ;   ...or 43 AND HITS FOR, the damage, and 26
$0DA8  LDA $6C00        ; the target's status: $83 is DEAD
$0DB0  LDX #$2C         ; 44 GOES DOWN, 45 AND IS DYING, 46 IS KILLED
$0DD9  JSR $28C3        ; the delay, then the clear
```

Reached from `$11DF`, `$1214` and `$1242` — the attack resolution — and from
nowhere else. So the block a monster prints is the shape a character's is:

```
row 10   ORC
row 11   ATTACKS
row 12   BRUTUS
row 13   AND MISSES...
```

The name on row 10 is whichever record the engine has just made resident at
`$6B00`, and the one on row 12 is the target's, because `$2744` swaps the
resident record between the two prints. That is why a poll taken while the
block is showing reads `$6B00` as the **target**.

## The vocabulary — CONFIRMED

`SPELLN00` loads at `$AF00`: 128 pointers, lo at `$AF00` and hi at `$AF80`,
into strings from `$B000`. Entries 1-56 are the spell names. `COMBAT $29A2`
adds `#$39` to the index, so **its messages 0-63 are entries 57-120**, and
entries 121-127 are padding — `$FF00`, `$20FF`, addresses outside the file. A
scan that trusted the 128-entry table reads seven strings that are not there.

The eight the melee-attack routine uses:

| COMBAT # | table | text |
|---|---|---|
| 15 | 72 | `IS HIT FOR ` |
| 26 | 83 | `POINTS OF DAMAGE` |
| 41 | 98 | `ATTACKS` |
| 42 | 99 | `AND MISSES...` |
| 43 | 100 | `AND HITS FOR ` |
| 44 | 101 | `GOES DOWN` |
| 45 | 102 | `AND IS DYING` |
| 46 | 103 | `IS KILLED` |

**The three dots in `AND MISSES...` are the game's own** — screen codes
`2E 2E 2E` — the way `THE PARTY HAS LOST` has no full stop and
`THE PARTY HAS WON !` has a space before its exclamation mark. The other 56 are
the ones a monster or a spell earns, and they come out of the same table
through the same printer: `GAZES...`, `BREATHES...`, `SPITS ACID`,
`SUCKS SOME BLOOD`, `RAKES`, `SWEEPS`, `TURNS INTO GAS`, `SURRENDERS`,
`(HELPLESS)`. `tools/monstermsg.py table` prints all 64 off the player's own
disks; nothing here copies them.

`tools/monstermsg.py sites` finds the printers' callers. `$0D68` is the only
`JSR $2983` in COMBAT with a literal index; the other two, `$2936` and
`$29B1`, take theirs from `$2B38`, and **nothing in COMBAT stores to `$2B38`
with a direct instruction** — three mentions, two `LDX $2B38` and one byte
inside data. Where that variable is written is not established, and it is the
loose end here.

## Driven, and what came out — CONFIRMED

`tools/monstermsg.py fight` boots a pool slot, loads `PORSAVE13.D64`, walks
four steps into the slums ambush and polls the panel through
`automap/combatlog.py`'s own `CombatLog.poll` at the 200 ms `AutomapBinding`
ticks at, driving the party's turns in between.

| run | `$49FC` | polls | mean gap | messages | a monster's |
|---|---|---|---|---|---|
| `work/issue350/fight1.jsonl` | 2 | 448 | 0.67 s | 26 | 26 |
| `work/issue350/fight2.jsonl` | 2 | 412 | 0.58 s | 23 | 23 |
| `work/issue350/fight3.jsonl` | 2 | 410 | 0.58 s | 23 | 23 |

Every attack line came out whole, with the target named, whether it landed and
the damage; a killing blow added `ROLAND GOES DOWN AND IS DYING`, and one orc
`SURRENDERS`. **The nought in the party column is the harness, not the
reader**: the driver is inside `Session.melee_turn` at the moment the party's
own blow lands, which is what the 11-second worst gap is, and a player's
window never stops polling to take a turn.

## Two claims in `#350 (The Messages window logs the party's attacks and dice but nothing a monster does)`'s description, both refuted

**"A monster's index is past the end of the roster `_block` reads."** It is
not. `rolls.ROSTER_BLOCKS` is 64, covering `$8300`-`$8AFF`, and
`RosterBlock.occupied` is `any(self.raw)`, which a monster's block satisfies.
Measured: 22 of 23 monster messages in `work/issue350/fight3.jsonl` carry a
complete roll — `ORC rolled 17, needed 17, 1d8 = 2` — and the 23rd is the
`GOES DOWN` follow-up, which correctly has none. The needed numbers are the
orc's THAC0 19 less each defender's armour class: 17 against BRUTUS at AC 2,
13 against MALCYON at AC 6, 15 against ROLAND at AC 4.

**"The message never arrives."** It does. Two of them are in
`work/rolls/run1.jsonl`, a fight recorded on 2026-08-30 for the roll work,
and they replay through today's reader as
`ORC ATTACKS BRUTUS AND MISSES...` and `ORC ATTACKS MALCYON AND MISSES...`.
`tools/monstermsg.py replay` is that check, and it needs no emulator.

## The name a monster is given

`$2983` prints whatever is at `$6B00`, which for a monster is the `MON*`
record loaded into the character-record buffer — the same record
`automap/combat.py` reads for the combatant, so `Combatant.name` **is** the
string the engine prints. Measured on `work/issue350/fight2.jsonl`: on 22 of
23 messages the name printed on row 10 equals the backend's name for the
acting index, and the 23rd is the follow-up whose subject is the target
instead. The names in that fight were `ORC` for indices 8-15 against
`MALCYON`, `LADY KATHERINE`, `ROLAND`, `SILAS`, `MAGNUS`, `BRUTUS` for 0-5.

So `#345 (Draw a letter in each combat-map square saying what is standing
there, instead of the index the backend counts with)` and this have nothing to
reconcile: both name a monster from that record, and
`tools/monsterlabels.yaml` is an abbreviation of the same name. **The engine
cannot tell eight orcs apart either** — all eight print `ORC`.

## What silences the panel, and it is not the reader

`$49FC` is the player's own combat speed. `CAMP $0C91` is a three-item menu —
`SPEED:`, `SLOWER`, `FASTER`, `EXIT` — that prints the value as a digit and
greys `SLOWER` at 9 and `FASTER` at 0, so the range is **0 to 9 and both ends
are reachable**; `COMBAT $226A` is the same setting on the combat `DONE`
sub-bar; `INIT $09AC` starts it at 2. `COMBAT $28C3` is
`LDA $49FC / BEQ $28D9`, so **at zero the delay is skipped and the panel is
cleared with nothing in between**.

| `$49FC` | poll asked | polls | mean gap | messages | caught mid-block |
|---|---|---|---|---|---|
| 2 | 0.20 s | 410 | 0.58 s | 23 | 0 |
| 0 | 0.20 s | 199 | 0.90 s | 3 | 1 |
| 0 | 0.05 s | 354 | 0.50 s | 6 | 3 |

PROBABLE for the counts — one run each at zero, and the cadence came out
worse rather than better because a fight with no delays gets through more
turns in the same wall clock — and CONFIRMED for the mechanism, which is one
branch. `#425 (The Messages window logs a quarter of a fight when the player
turns the game's combat speed up)` carries it.

**It does not explain the asymmetry `#350 (The Messages window logs the party's attacks and dice but nothing a monster does)` was filed for**, because zero
silences a character's line as thoroughly as a monster's.

## Not established

* **Why Donald saw the party's lines and not the monsters'.** Every stage
  measures as working, including `AutomapBinding.log_combat` run directly on a
  monster's message, which produces `Orc attacks Brutus and misses...` and
  `Orc rolled 4, needed 17`. Two things would narrow it and only he can answer
  them: which machine — VICE at a 200 ms tick, or the C64 Ultimate at 500 ms
  with every read halting the 6510 — and what number `ENCAMP > SPEED` shows on
  the save he was playing.
* **The whole window against a live machine.** Everything here drives
  `CombatLog` from a harness. `AutomapBinding` on its own QTimer, with
  `combat.read_battle` gating `poll_combat_log`, has never been run against a
  fight; one VICE serves one binary-monitor connection, so it needs the window
  and the driver in one process.
* **Where `$2B38`, the general message index, is written.**
* **A monster with more than one attack a round**, which is where
  `docs/147-combat-rolls.md`'s unopened hole would open first. Eight orcs have
  one each.
