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
| 1 left, no node | cure once; full 10080 minutes after that cure | **no C64 Curse state does this** -- see below | with `0x012` = 1 and no row (level 11 and 6): the cure left 0, added no row, and eight days' rest brought nothing back. With a `$C7` row as well (level 11 and 6): the cure left 0 and full came back at 00:00 on day 7 |
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

`c64_cure_write` raises `Unrepresentable` for this state rather than choosing,
and the converter test skips it, naming the choice.
`test_no_c64_curse_state_gives_one_use_of_three_its_dos_recovery` checks every
row length from 1 minute to 64 days against two cure times and finds each at
least two days from DOS's recovery for one of them.

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
