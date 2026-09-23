# A paladin's cure disease, from DOS to the C64

A converted paladin must be able to CURE as many times as he could in DOS, spend
a use the same way, and get his uses back at the same time. This page gives the
C64 record byte and effect-array row that does that for each state a DOS Curse
or Silver Blades paladin can be in, what the running C64 game did with each,
and the one state C64 Curse cannot hold. It serves
#600 (The neutral record has no field for an effect's remaining duration or a paladin's cure-disease uses, so a converted character loses both)
and
#626 (A paladin written into a C64 Curse or Silver Blades save, or renamed there in the editor, loses CURE and HEAL from his sheet, because the name field covers the two bytes that hold them).

The DOS side is read by `curedisease.dos_inspect` in
[`tools/c64/curedisease.py`](../tools/c64/curedisease.py), the C64 side by the
same file's `inspect` (the earlier read), and the running game was
driven with [`tools/c64/curedrive.py`](../tools/c64/curedrive.py).
[`tests/records/test_curedisease.py`](../tests/records/test_curedisease.py)
pins the reads, holds the per-case bytes a writer must produce, and runs them
through `dos_codec.convert_save` once the writer exists.

## The answer

Every row is a DOS Curse paladin at paladin level 6 (full count 2) or 11
(full 3), converted into C64 Curse. "Node" is his DOS cure node, id 141; the
driven saves held one with 4000 minutes left. The C64 column is what a
writer must put in record `0x012` and the save's effect arrays; "row" means
one row with id 141, owner his own save slot, magnitude `$C7`, and the
duration byte `goldbox.effects.closest_duration` gives for the node's minutes
at the save's clock (`$C3`, 4098 minutes, at 03:42). The last column is what
the running game did with exactly those bytes. Every driven claim is
**CONFIRMED** in the running game; each is one run.

| DOS source | what DOS lets him do | C64 write | what the C64 game did |
|---|---|---|---|
| full, no node | cure, then full again 10080 minutes after the cure | `0x012` = full, no row | level 11 and 6: CURE offered; the cure left 2 / 1 and added row 141 `$C7`/`$C7`, owner 0; full back at 00:00 on day 7, 9857 minutes after the 03:43 cure; CURE offered |
| 1 left, node | cure once; full when the node ends | `0x012` = 1, row | level 11 and 6: the cure left 0 and added no row; CURE gone from the sheet; full back at 00:00 on day 3, the row's 4098 minutes; CURE offered |
| 0 left, node | no CURE; full when the node ends | `0x012` = 0, row | the state the row above is in after its cure, byte for byte: no CURE, full back when the row ends |
| 0 left, no node | no CURE, ever | `0x012` = 0, no row | the state the row below is in after its cure: no CURE, and nothing back after eight days' rest |
| 1 left, no node | cure once; full 10080 minutes after that cure | **no C64 Curse state does this exactly -- see below**; written as `0x012` = 1, adjustment row 141 `$C7`/`$C7` | with `0x012` = 1 and no row (level 11 and 6): the cure left 0, added no row, and eight days' rest brought nothing back. With a `$C7` row as well (level 11 and 6): the cure left 0 and full came back at 00:00 on day 7 |
| full, node (no DOS play reaches this) | cure, no new node; full when the node ends | `0x012` = full, row | level 11: the cure left 2 and added a second row, `$C7`; full at the first row's end (day 3); the second row ended on day 7 and wrote full again |

For Silver Blades the same writes hold with id 110, and the partial state
has an answer; see "Silver Blades" below.

## What DOS does

**CONFIRMED from the player's `GAME.OVR`, both titles.** The two DOS engines
run the same rule on different bytes:

| | DOS Curse | DOS Silver Blades |
|---|---|---|
| uses byte | record `0x191` | record `0x06D` |
| cure | `0x2A959`: decrement only while above 0; then `find_affect(141)` and, only when it finds none, `add_affect(141, 10080 min, value 0, flag 1)` | `0x2B160`: the same with id 110 |
| gate | `0x2A6F1`: CURE is offered only while the byte is above 0 (after the class, `0x195` and a game-mode test) | `0x2AEDF`, the same with `0x1A6` |
| refresh | handler 141 at `0x127D6`, run on the node's removal: `(level - 1) / 5 + 1` | handler 110 at `0x1444F`, the same arithmetic |
| every other write | one: character creation writes 1 (`0x20DE5`) | three: creation (`0x1E38C`) and the Curse import (`0x256E9`, `0x25810`) write 1 |

Every instruction in either executable that names the byte is in that table:
`dos_inspect` sweeps every routine in `GAME.OVR` and the unpacked loader, and
finds five in Curse and seven in Silver Blades. **Training never touches the
byte.** So a DOS paladin's uses are 1 from creation, one less after each cure,
and the full count again only when a node ends -- and a paladin created at
level 1 and trained past 5 holds 1 with no node until his first cure. That is
why every DOS Curse paladin on this machine holds 1, at levels 5, 6 and 11.

What DOS lets him do next, by state:

| DOS state | next cure | recovery |
|---|---|---|
| uses = full, no node | spends one; starts a node | 10080 minutes after that cure |
| 0 < uses < full, no node | spends one; starts a node | 10080 minutes after that cure, to the full count |
| uses > 0, node with M minutes | spends one; no new node | when the node ends, M minutes from now, whatever he did |
| 0, node with M minutes | CURE not offered | M minutes from now |
| 0, no node | CURE not offered | never; no DOS route writes the byte again |

The DOS full count, `(level - 1) / 5 + 1`, is the C64's 1 / 2 / 3 at every
level from 1 to 15. At 16 DOS gives 4 and the C64 3.

## What the C64 does

The static read is in `tools/c64/curedisease.py`; the driven runs
below confirm it. The one difference from DOS is **when a cure starts a
timer**:

* **C64 Silver Blades** starts it when the paladin owns no row with id 110
  (`ECL65 $872E`-`$8733`) -- DOS's rule.
* **C64 Curse** starts it only when `0x012` equals the full count before the
  cure (`ECL65 $86F4 JSR $87EF / CPY $7C12 / BNE $870F`), and never
  otherwise.

A cure row's expiry in camp writes the full count (Curse `ECL65 $85BA`,
Silver Blades `$8657`). The row's owner byte is the paladin's **save slot**,
not his place on the panel: the driven cures wrote owner 0 for Curse's
PALADIN, in save slot 0 and sixth on the panel, and owner 5 for Silver
Blades' GUY DE VALOIS, in save slot 5 and first on the panel. **CONFIRMED**
on those two.

**A cure row lasts until the seventh midnight, not seven days.** The cure
writes duration `$C7`, which the camp ages by the day digit, so it runs out
after `10080 - (minutes since midnight)`: cured at 03:43, the driven paladin had
his three back at 00:00 seven days on, 9857 minutes later. A DOS node lasts
exactly 10080. This is the C64 engine's own rule for every cure made on the
C64, so it is not something a conversion changes.

**CURE is on the camp's `VIEW`, not the world's.** The world's `VIEW` builds
the sheet bar from `$7FF7` = `$41`, which leaves `EXIT` and `ITEMS` at most;
the camp's builds it from `$FF`, and only then do `0x012` and `0x013` decide
CURE and HEAL (`LIBRARY $4695`-`$46B5`). So a world `VIEW` that shows `EXIT`
alone says nothing about those two bytes. The DOS-to-C64 Silver Blades run
cited as in-game evidence on
#626 (A paladin written into a C64 Curse or Silver Blades save, or renamed there in the editor, loses CURE and HEAL from his sheet, because the name field covers the two bytes that hold them)
(`cited/52/walk-dostoc64-ssb/`) read the sheet straight after arriving, in
the world, so it cannot show the zeroed bytes hiding CURE; the static
reading of that issue stands without it. Silver Blades behaves the same
way: its first driven run here ended on a sheet outside camp showing
`EXIT` alone for GUY DE VALOIS with `0x012` and `0x013` both staged to 1.

## The state C64 Curse cannot hold

DOS Curse paladin 11 with 1 use and no node -- the state every DOS paladin
trained past level 5 or 10 is in -- can cure once, and gets 3 back seven days
after that cure, whenever it is. **No C64 Curse state does that.** The byte
has to be 1 for him to cure once and no more, and then:

* **with no row**, his cure starts no timer, because 1 is not his full 3.
  CURE is gone for good, until he is taken out of the party and added back
  (`ADD CHARACTER TO PARTY` seeds the full count). Driven at level 11
  and 6: the cure left 0 and wrote no row, and after eight days' rest he
  still had 0 and no CURE.
* **with a row**, his 3 come back when that row runs out, a time fixed when
  the save is written. If he cures on the day he arrives, that is exactly
  what the C64's own cure would have done; if he cures later, the uses come
  back early, and if he waits past the row, he has 3 before he has spent the
  1. Driven at level 11 and 6 with the row the C64's own cure writes, `$C7`:
  cured on the day he arrived, at 03:43, he had his full count back at 00:00
  on day 7 -- the moment a C64 cure from full would have given him.

## Donald's decision

Rather than refuse this state, `c64_cure_write` writes an adjustment: `0x012`
= 1 and a row 141, duration and magnitude both `$C7` -- the same byte the C64
cure itself writes, as if he had just cured from full on the day of
conversion. **This is not DOS parity.** It gives up on reproducing whenever
DOS would actually have brought his three back, in exchange for a recovery
that exists at all: with no row his first cure would start no timer and CURE
would never return.
`test_no_c64_curse_state_gives_one_use_of_three_its_dos_recovery` is the
measurement that shows no row length gets within two days of DOS's own
recovery for both of two cure times, which is why no row was a better match
than the adjustment picked here.

**The C64 game makes this state itself.** `GEN` seeds the count when a
character is created, added to the party, regains a class or changes class --
not when he trains. So on the C64, a paladin who trains from 5 to 6 or from 10
to 11 holds one less than his full count, and his next cure is his last until
he leaves and rejoins the party. That is a defect a C64 Curse player can hit
without any conversion; Silver Blades' guard does not have it.

## Silver Blades

C64 Silver Blades starts the cure timer when the paladin owns no row with id
110, which is DOS's rule, so every DOS Silver Blades state converts the same
way -- `0x012` = the DOS uses, and a row with id 110 for a DOS node -- and the
state C64 Curse cannot hold is no problem here: `0x012` = 1 and no row.

Driven on GUY DE VALOIS, paladin 11, `0x012` staged to 1 with no row, camp
clock 00:00: the camp sheet read `CURE HEAL EXIT`; the cure left 0 and the
game added row 110, `$C7`/`$C7`, owner 5 (checkpoint on the add: one hit);
the sheet then read `HEAL EXIT`; his 3 came back at 00:00 on day 7, 10079
minutes after the 00:01 cure, and the sheet read `CURE HEAL EXIT` again. **CONFIRMED**, one run.

## A former paladin

A human paladin who changes class (HUMAN CHANGE CLASSES) keeps his DOS uses
byte, and cannot CURE again until he regains the paladin. MATHEW in
`WISH-SPEC-curse-131-dualclassed-in-area-1` (magic-user 1, former paladin 5)
and DEMELTINA in `WISH-SPEC-curse-234-party-dualclassed` (cleric 1, former
paladin 5) both hold 1 at `0x191`, and MATHEW still holds 1 after regaining in
`WISH-SPEC-curse-408-regained-paladin`.

**DOS, CONFIRMED from `GAME.OVR`.** The gate at `0x2A6B2` passes the class test
when `char_class` (`0x075`) is 3, or when the former paladin level (`0x114`,
`former_class_levels[3]`) is above 0 **and** `0xFE:0x52` (`0x3C031`) is true:
a human whose current class level is above `former_level` (`0x0E6`), which
means he has regained. The refresh at `0x127D6` uses level = (regained ? former
paladin level : 0) + `class_levels[3]` (`0x10C`). Class change and regain never
write `0x191` (it has five writers, listed above). Silver Blades' gate at
`0x2AEA0` is the same test on `0x06C`, `0x11B` and `former_level` `0x0EF`.

**C64, CONFIRMED from the overlays, both titles.** A former paladin has no
cure count of his own. `0x012` is the only home the count has, and the engine
does not keep it across the class change:

* `GEN` seeds `0x012`/`0x013` from `level_paladin` (`0x0CF`) at the change
  (Curse `$23DE`, Silver Blades `$1FC6`). The level array has already been
  rewritten from the new mask by then, so the seed writes 0 and 0. The code
  is CONFIRMED. The value is PROBABLE, because no paladin record has been
  read between a change and a training.
* The regain (Curse `$20A3`-`$20BF`, Silver Blades `$154F`-`$156B`) puts
  `0x0CF` back and calls the same seed, so `0x012` becomes the full count
  for the old level, whatever it held before. This was observed:
  `WISH-SPEC-curse-409-regained-paladin` took MATHEW (paladin 6) and MARK
  (paladin 5) in with `0x012` = 0 and wrote 2 and 1.
* Nothing checks a class before CURE. The camp sheet's mask (`LIBRARY
  $4695`-`$46C0`) reads `$7CB8`, `$7E58`, `$7EF9`, `$7C12`, `$7C13` and
  `$7D00`, and no class byte. The cure (`ECL65 $86E6`) and its expiry reset
  (`JSR $87EF / STY $7C12`) take the full count from `0x0CF`, and that count
  is 1 when `0x0CF` is 0.

Only six instructions in Curse and five in Silver Blades name `$7C12`
(`tools/c64/absrefsweep.py`): seed, gate, cure and reset. Silver Blades has
no full-count compare, because its cure guard is the row. Nothing reads it
at load.

So `0x012` = 1 on a C64 character with no paladin level puts CURE on his camp
sheet. His first cure starts a cure row, because 1 equals the full count at
level 0, and the row's expiry writes 1 again. **A magic-user would cure disease
once a week for good.** This is read from the code and was not driven.

What each engine lets MATHEW do:

| | DOS | C64, `0x012` = 0 written |
|---|---|---|
| before regaining | no CURE: the gate's class test fails | no CURE: the sheet mask hides it at 0 |
| at the regain | `0x191` untouched: 1 | GEN seeds full for paladin 5: 1 |
| after that | cure once, then full again when the node ends | cure once from full, row 141, full at the seventh midnight |

**For MATHEW and DEMELTINA, writing 0 is DOS parity.** The regain gives him
the count DOS keeps for him, and that count equals the full count for the
level he left paladin at. **It is not parity** when the DOS count is below
that full count, for example a paladin trained to 6 without curing (1 of 2)
who then changed class, or when he carries a cure node. The C64 regain gives
him the full count whatever was written, and no state the C64 can hold before
the regain survives it. A cure row written for such a node would also end
before the regain and set `0x012` to 1 on a non-paladin.

A DOS character who was never a paladin holds 0 at `0x191`, and the C64 seed
gives him 0 at a class change and at a regain. The two cases differ only at
the regain.

## Evidence

Everything a run wrote -- the staged saves, one JSON line per reading with
`0x012`, the rows and the clock, a screenshot and screen text at every step,
and the game's own save after a cure -- is under
`~/.cache/wish/cited/600-curedrive/`, one directory per case under `runs/`
and the inputs under `stage/`. `tools/c64/curedrive.py summary DIR` prints a
run's readings. The inputs were staged into copies of
`WISH-SPEC-curse-551-paladin11-ranger11.D64` (PALADIN, save slot 0, level
set to 6 or 11) and `WISH-SPEC-ssb-89-train-input.D64` (GUY DE VALOIS, level
11, save slot 5).

Two things were changed in the running machine that are not the paladin's
state, both to let a rest run: Tilverton's streets set the rest-interruption
pair `$7ED2`/`$7ED3` to 1 and 100 when the party camps, so a rest there ends
after five minutes with `ROYAL GUARDS TELL YOU TO MOVE ALONG.`; the driver
zeroes `$7ED2` after `ENCAMP`, and writes the rest length straight into the
camp's rest-time field (Curse `$2C1B`, Silver Blades `$2A8E`, minutes, hours,
days). Neither touches a record byte or an effect row.

## What stays open

* A DOS Curse paladin at full uses with a node running is in the table but
  not reachable in DOS play: a node is added only by a cure, which leaves him
  below full, and only its end refills him. On C64 Curse a cure from full adds
  a second row beside the converted one. Driven at level 11: the cure left
  2 and added a `$C7` row; full came back when the converted row ended on day
  3, and the second row ended on day 7 and wrote full again. So a cure from
  full between those two days adds a third row, and the second refills him
  before seven days are up, where DOS would have waited the whole seven.
* Paladin level 16 and up: DOS counts 4, the C64 stops at 3, and
  `c64_cure_write` raises. Whether a Silver Blades party can reach 16 is not
  measured.
* The Amiga ports are not part of this page.
