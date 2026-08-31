# What the game rolls when somebody attacks

**Status: measured, and built.** `automap/rolls.py` reads these bytes and
`automap/combatlog.py` says the roll under each combat message (#139).
`docs/110-combat-log.md`'s Messages panel shows what the game *prints*; this is
what the game *rolled*, which is a different thing.

The question was Donald's: can we find out what the dice did, and could we print
them into the Messages console? Yes to both. There is one random number
generator, one dice roller, and the d20, the number it had to beat and the
damage all land in ordinary RAM that keeps its value until the next attack.
**Nothing lives only between two instructions**, which is the fact the whole
feature depends on.

Established from a static read of `COMBAT` (loads at `$0800`) and `LIBRARY`
(`$2C48`), plus two driven slums fights out of `PORSAVE13.D64` — 212 polls over
589 seconds, 21 driven turns, median poll gap 0.1 s.

---

## Where to read

| address | what | how established |
|---|---|---|
| `$2B10` | **the d20 to hit.** 20 is stored as **100**; **not written at all on a natural 1** | `COMBAT $1289` |
| `$A4F0` | **the number the roll must reach** — the target's `60 - AC`, plus modifiers | `$12DF`, `$11FB` |
| `$A4F8` | **the damage**, kept while it is applied | `$0D02` |
| `$A4FB` | **hit flag**, 0 or 1 | `$1275`, `$12AA` |
| `$A4F4` / `$A4F5` | acting combatant's index / target's index, 0–7 party and 8 upward monsters | `$12E3`, `$12C3` |
| `$A4F9` / `$A4FA` | attempts and landings so far in this action | `$1222`, `$122D` |
| `$6C0E` | the **resident** block's `60 - THAC0` — the attacker's *inside the routine*, and **not reliably the attacker's when polled**, for the same reason as `$6C13` below. Take THAC0 and AC from the battle roster instead | `$129F` |
| `$6DB9` | sides of the last die actually rolled | `$35CE` |
| `$03C2`–`$03C7` | the generator's state, advanced on every die | `$2D88` |

`$A4F7`–`$A4FC` are cleared once per **action** at `COMBAT $11AC`, not per roll.

**The resident roster block is a trap in both directions.** `$6C00`–`$6C1F` is
whichever combatant the engine last made resident, and `$2744` swaps it. Inside
the attack routine that is the attacker where the code reads it; from outside,
after a hit, `$0CFE` has made it the **target**. So nothing polled from
`$6C00`–`$6C1F` can be trusted to belong to the attacker — take what you need
from the battle roster at `$8300 + $A4F4 * 32`, which
`automap/combat.read_battle` already reads. `automap/rolls.py` computes the
number to beat as `THAC0(attacker) − AC(target)` from the two roster blocks for
exactly this reason, and reproduces both worked examples below.

## The generator — `LIBRARY $2D88` — CONFIRMED

Six bytes of state at `$03C2`–`$03C7`, a lagged-Fibonacci shift, result in
`$03C8`. `$2DBC` turns that into 0..Y by masking with the smallest `2^n - 1`
that covers Y — table at `$2DEC`, `01 03 07 0F 1F 3F 7F FF` — and **rejects and
re-rolls** until the value fits, so it is unbiased. `$2DE0` is the one-die
entry and returns 1..sides. `LIBRARY $35CB` rolls A dice of X sides and sums
them.

Nothing in `COMBAT` or `LIBRARY` writes the state; some other overlay seeds it.
The shift is why `$03C2` and `$03C3` are always equal when read from outside —
89 of 89 polls.

## The to-hit test closes on arithmetic we already decode — CONFIRMED

`COMBAT $1275` rolls 1d20, stores it at `$1289`, adds `$6C0E`, and compares
against `$A4F0`. `$6C0E` and `$6C0F` are the **resident roster block**'s THAC0
and AC, which `goldbox/savegame.py` carries as `ROSTER_THAC0 = 0x0E`,
`ROSTER_ARMOUR_CLASS = 0x0F` and `COMBAT_BIAS = 60`. `$12B1` runs after `$2744`
has made the *target* resident, so `$A4F0` is the target's `60 - AC`. The test
is therefore

```
d20 + (60 - THAC0 attacker)  >=  (60 - AC target)
```

which is `d20 >= THAC0 - AC`, the AD&D rule.

Checked against the running game: `$A4F0` read 58 in a poll whose panel showed
BRUTUS at AC 2, and 54 in polls showing the ORC at AC 6. An orc's `$6C0E` read
41 = 60 − 19, and the *Monster Manual* gives an orc THAC0 19.

## What the fight proved

* **The damage byte matches what the game prints.** `$A4F8` read 7 in **all 13**
  polls showing `BRUTUS ATTACKS ORC AND HITS FOR 7 POINTS OF DAMAGE`; 13 agree,
  0 disagree.
* **A natural 20 really is stored as 100.** Seen once — MALCYON, `$2B10` = 100.
* **The rolls outlive the game's own message.** A d20 value held between 0.8 s
  and 317.8 s, shortest run nine consecutive polls; the `ATTACKS` message held
  0.6–1.1 s. **Anything the combat log can catch, a roll read in the same poll
  catches too**, which is the answer to whether polling is enough.

## Refuted — four readings that do not work

Recorded because each is cheap to try again and expensive to re-disprove.

* **`$4C`/`$4D`, the dice accumulator, cannot be polled.** Thirty different
  values across 89 consecutive polls with no fighting: other code owns that
  zero page.
* **`$03C8` is not a reliable die result.** Every bare `JSR $2D88` overwrites
  it, including the initiative tie-break at `COMBAT $08E4`.
* **`$A4F7` is the wrong damage byte.** `$0D10 SBC $6C19 / STA $A4F7` writes
  the *overkill* back: on one kill it read 7 for a poll and then 2. `$A4F8` is
  the one that keeps the number.
* **`$A4EF`, the attack form, is unusable at poll time.** The loop counts it
  down to `$FF`, which is what 24 of 36 distinct states read.
* **`$6C13`/`$6C15`/`$6C17` are not the attacker's at poll time.** `$0CFE`
  makes the *target* resident. Take the dice from the battle roster at
  `$8300 + $A4F4 * 32`, which `automap/combat.read_battle` already reads.

## Two limits any feature must state rather than hide

**A natural 1 leaves `$2B10` holding the previous attack's roll.**
`$127F CMP #$01 / BEQ $12AF` returns before the store. PROBABLE rather than
CONFIRMED: it is plain in the code and no natural 1 came up in either fight.

**Polling cannot count rolls it did not see.** Two attacks resolved between two
polls collapse to the last one. `$A4F9` counts attempts and `$A4FA` landings
within an action, so a jump of more than one says rolls were missed — which is
enough to say so honestly rather than to pretend to recover them.

## Cost, if it is built

35 bytes: `$2B10`, `$A4E0`–`$A4FF` and `$6DB8`–`$6DB9`. The dice and the
attacker's name come from the battle roster and record slots `read_battle`
already fetches. Appended to a burst that already happens, this costs bytes and
**not a round trip** — and the round trip, ~14.3 ms under VICE, is the whole
cost of a read.

No disassembly beyond reading a few dozen instructions around known sites was
needed. `goldbox/monster.py`'s note that `COMBAT $0CAD` rolls damage is the
thread this was pulled from.
