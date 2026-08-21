# Party strength: what makes a random encounter bigger

**Pool of Radiance sizes random encounters from the party.** The number is
computed by `PARTYSTRENGTH`, ECL opcode `$1D`, at **`DUNGEON $1BE8`**, and in
twelve of the thirty area scripts it becomes the **count operand of `LOADMON`**
— literally how many monsters are placed in the fight.

Nothing stores it. The routine walks the eight roster slots every time a script
asks, and writes only to the ECL variable its operand names. `por/strength.py`
recomputes it the same way, and the Automapper shows it live under the bottom
strip. Found in `work/reports/encounters.md`; the entry in
`docs/50-experiments.md` is "Does the game scale random encounters to the
party?".

## The formula

Per roster slot, summed as a 16-bit total and then divided **once**:

```
strength = floor( Σ_slots [ 5 · (THAC0 field − 39)
                          + hit points maximum
                          + 5 · (AC field − 60)     when the AC field ≥ 60
                          + 4 · level               when class bit 1 (cleric)
                          + 8 · level               when class bit 0 (magic-user)
                          ] / 10 )
```

| term | field | stored as | weight |
|---|---|---|---|
| THAC0 | roster `+0x0E` (record `0x10E`) | `60 − THAC0` | 5 a point better than 21 |
| hit points | record `0x076`, 16-bit LE | itself, the **maximum** | 1 a point |
| armour class | roster `+0x0F` (record `0x10F`) | `60 − AC` | 5 a point better than 0 |
| cleric | record `0x0A0` level, `0x0EB` bit 1 | itself | 4 a level |
| magic-user | record `0x0A0` level, `0x0EB` bit 0 | itself | 8 a level |

**The biased fields are used as stored.** The routine subtracts its own
constant from the byte — 39 from the THAC0 field, 60 from the armour field —
rather than decoding it first, which is why `−39` means "better than THAC0 21"
and `−60` means "better than AC 0". Both are the *current* values, after
armour, weapon and magic: the game recomputes them into the roster when
equipment changes.

Both are in the **roster block only** (`SAVEDGAME1 $8300 + N·$20`), so an editor
that reads `SAVEDGAME0` alone cannot compute this.

## What raises it

* **A better THAC0.** Five points of sum for each point, the heaviest term
  available and the one that actually moved on Donald's disks. Anything that
  improves current THAC0 does it: readying a weapon at all, a strength hit
  bonus, a dexterity missile bonus, a magic weapon.
* **More maximum hit points.** One for one, and it is the **maximum** — a
  wounded party meets exactly the same number of monsters as a healthy one.
  Curse of the Azure Bonds reads current hit points here; this game does not.
* **A better armour class — but only from 0 downwards.** `$1C16` subtracts 60
  from the field and branches away on the borrow, so AC 10 through AC 1 all
  score zero and only AC 0 and better pay, at five a point. This is *worn* AC,
  so armour does reach it — plate and a shield and a dexterity bonus — but a
  starting party is nowhere near. **In every one of Donald's save disks the term
  is zero for every character**: the best armour class anybody reaches is 2, a
  field of 58 against a floor of 60.
* **Levels in cleric or magic-user**, at 4 and 8. Fighter and thief levels are
  worth nothing. The routine reads the single `level` byte at `0x0A0` for both
  terms, so a cleric/magic-user scores `12 × level` rather than a per-class
  split — the one place where PoR and CoAB's version of this routine differ in
  kind rather than in constants.

## What does not

| | |
|---|---|
| experience | never read in the encounter path; the only ECL instruction touching the XP field *writes* a monster's award |
| ability scores | never read as bytes. The all-18 folklore is right through THAC0 and hit points, which is how 18s cash out, and not otherwise |
| the clock | gates *whether* a check happens, never *how big* |
| commissions completed | nothing in the size path reads them. `ECL08`'s `COMPARE 19` / `COMPARE 36` is on party strength itself, and chooses which speech the council gives |
| current hit points | see above: the maximum is what counts |
| party size | only as the number of terms in the sum. There is no head-count term and `$49FC` is not read |

**No party-strength byte is stored anywhere**, so there is nothing to poke and
nothing that can go stale. Change the party and the next script call sees it.

## What it changes

| script | what party strength does |
|---|---|
| `ECL14` slums | `(strength / 3) * 2` monsters, `$B1B0`. Leaders at 8+, a bugbear above 18 |
| `ECL14` old rope guild | the **raw** strength as the count — it skips the divide |
| `ECL19`/`1A`/`1B` wilderness | strength / a per-monster-type divisor, then a random further reduction |
| `ECL1D` Kuto's Well, `ECL08`, `ECL0A`, `ECL11`, `ECL12`, `ECL18` | the `LOADMON` count |
| `ECL00` New Phlan | the monster **type**, not the count: an index into a nastiness-ordered table, shifted at strength 24 and again at 50. Thirty-five monsters either way |
| the four dungeon-floor scripts | nothing — a fixed patrol, the same six monsters at level 1 as at level 8 |

`LOADMON` clamps at twelve monster groups and 64 combatant slots, so a huge
strength saturates rather than overflowing.

**Four scripts or six do not scale, and the two accounts disagree.** The
encounter survey finds four; the full ECL decode finds the per-square
`NO_ENCOUNTER` test in six, adding `ECL05` and `ECL0F`. Both can be true only
if those two honour the bit *and* scale. See the flagged disagreement in
`docs/50-experiments.md` before relying on either count.

## The consequence a player feels

Donald's six characters, from his own save disks, with no character gaining a
level or a point of experience anywhere in this sequence:

| disk | sum | strength | slums encounter |
|---|---|---|---|
| `PORSAVE` — nothing bought, nobody holding a weapon | 115 | 11 | **6 monsters** |
| `PORSAVE2` — after the shopping trip | 120 | 12 | **8 monsters** |
| `PORSAVE11` — after MALCYON's scores were edited to 18s | 130 | 13 | **8 monsters** |

**A shopping trip made every later random slums encounter half again as big.**
That is the point, and it is worth knowing before spending the party's gold.

**The mechanism is the weapons, not the armour.** The trip bought banded mail
and shields and took ROLAND from AC 10 to 4, SILAS 10 to 3, MAGNUS and BRUTUS 9
to 2 — and every one of those four contributed *exactly the same number*
before and after, because none of them crossed AC 0. All five points came from
MALCYON, who started with no weapon at all and ended with a dart readied:
THAC0 21 to 20, five points of sum, and the slums count from 6 to 8 across the
`/3 × 2` boundary. The later 120 → 130 is the same man again, his dexterity
edited to 18, taking the missile bonus and THAC0 to 18.

Per character in `PORSAVE11`:

| | contribution | |
|---|---|---|
| MALCYON | 27 | 15 THAC0 + 4 hp + 8 magic-user |
| LADY KATHERINE | 13 | 5 hp + 8 magic-user |
| ROLAND | 16 | 5 THAC0 + 7 hp + 4 cleric |
| SILAS | 24 | 15 THAC0 + 9 hp |
| MAGNUS | 24 | 15 THAC0 + 9 hp |
| BRUTUS | 26 | 15 THAC0 + 11 hp |

MALCYON is a level-1 magic-user with 4 hit points and he out-scores every
fighter in the party. The magic-user weight of 8 a level is the largest single
constant in the routine, and at low levels it dominates everything except
THAC0.

## Two edges

**A dead character stops counting.** `$1BF6` tests roster `+0x00` and skips the
slot when it is zero or has bit 7 set — the byte seen going `$01` → `$84` on
death. So a party that has lost somebody meets *smaller* random encounters
until it raises them, which is the opposite of what difficulty scaling usually
does.

**The THAC0 subtraction has no underflow guard.** `$1C01` is a plain `SBC #$27`
where the armour-class subtraction at `$1C16` carries a `BCC`. A current THAC0
worse than 21 therefore wraps to a byte near 255 and, times five, adds well over
a thousand to the sum — enough on its own to saturate `LOADMON`. A cursed
weapon is the plausible route to a THAC0 that bad. **GUESS**: this is read off
the instruction and reproduced in `por/strength.py`
(`Contribution.wrapped`), but no cursed weapon has been put on a character and
walked into the slums.

## Where the code is

`por/strength.py`. No Qt and no transport:

```python
strength.from_bytes(save0_bytes, roster_bytes)   # a save file, or a live read
strength.from_saves(save0, save1)                # decoded SaveGame0/SaveGame1
strength.read_live(target)                       # anything with .read(addr, n)
```

`PartyStrength.value` is the number, `.total` the sum before the divide,
`.slums_count` the `(s / 3) * 2` that `ECL14` places, and `.detail` the
per-character breakdown — which is the useful part, because a total of 130 says
nothing about what to change.

The Automapper computes it in `AutomapWindow.show_strength` from the two blocks
`poll_live` already reads, so it is **live data and never the save file**, and
shows it under the bottom strip with the breakdown as its tooltip. It belongs in
`BottomStrip` beside the clock, which is `automap/panel.py`: `show_state` would
need the two blocks, or a `PartyStrength` passed in beside the snapshot, and the
call site is the last line of `poll_live`.

Tested in `tests/test_strength.py`, including both save disks end to end.
