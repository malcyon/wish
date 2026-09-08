# The DOS shopping trip

**Where New Phlan's shops are, how a party is driven into one, and what the
engine writes into the record when it buys something.** The training-hall half
of `#249 (Build a DOS party from creation and level it ourselves, so DOS
measurements rest on records we watched being written)` is
`docs/194-the-dos-training-ladder.md`; this is the shop half, and it is what
`#323 (The encumbrance identity does not survive the training fee, so failing
it is not evidence of an edited record)` was waiting on.

`tools/dosshop.py` is the tool. `tools/dosshop.py --map` re-derives every
square below from the player's own files with no emulator.

## The four shops

New Phlan is area 0 and its script is `ECL00`, which dispatches on the
square's own `GEO00` script id with `ONGOTO [$9800], 28, ...`. Four of those
twenty-eight arms end in the same five statements:

    TREASURE 0,0,0,0,0,0,0,<shop>
    SAVE 1, [$6E6C]        "a shop instead of a fight"
    SAVE 1, [$6EF6]
    SAVE 16, [$6E6D]
    COMBAT

`docs/128-guide-and-scripting.md` names `$6E6C` in `$24 COMBAT`'s side channel
as *shop instead*, so **a Pool of Radiance shop is the combat opcode entered
with that byte set and its stock preloaded by `TREASURE`**. Nothing else in
`ECL00` writes `$6E6C`.

| shop id | script id | squares in New Phlan | approach square |
|---|---|---|---|
| 52 | 21 | (8,10) | (9,10) facing west |
| 53 | 22 | (13,8) (8,11) (11,12) (8,13) (9,13) | (7,11) facing east |
| 54 | 19 | (15,8) (9,10) (12,10) (9,11) (11,11) | (9,12) facing north |
| 55 | 23 | (11,10) (10,13) | (11,9) facing south |

CONFIRMED, twice and independently, once per port. The C64 `ECL00` off
`POOL3.D64` decodes to those arms through `tools/eclwalk.py`. The DOS
`ECL00` -- block 0 of `ECL3.DAX`, 7,473 bytes against the C64's 7,468 --
carries the same four `TREASURE`/`$6E6C` sequences with the same shop ids and
its own 28-arm `ONGOTO` puts them at the same arm numbers. The two scripts
even name the same script-variable addresses.

**And the map is one file, not two.** DOS `GEO3.DAX` block 0 is
byte-identical to the C64's `GEO00`, 1024 of 1024 bytes, so a square table
read on the C64 is not being applied to DOS on faith. (`docs/194` says
`dosladder.check_hall` checks the hall "against the player's own DOS
`GEO00`"; it reads the C64 disks through `automap.maps`. The conclusion
survives, because the two files are the same bytes.)

**A save cannot be dropped on a shop square.** `ECL00` dispatches on the
*departing* square's attribute byte, the same as `ECL0B` does for the hall, so
the party is put down on the approach square and walks the last step.
Shop 52 is the awkward one: its only approach is (9,10), which is shop 54's
own shopfront.

## Driving the shop, screen by screen

Every screen was mapped in one boot with `--interactive`, which runs step
lines as they are appended to a command file.

| screen | bar | what to press |
|---|---|---|
| stepping onto the shop square | `YES NO`, under a line of the shopkeeper's offering to show his wares | `y` |
| the shop | `BUY VIEW POOL APPRAISE EXIT` | `b` |
| the stock list | `ITEMS: BUY NEXT PREV EXIT` | `b` buys the highlighted line, `n` pages |
| the sheet, from `VIEW` | `VIEW: ITEMS TRADE DROP EXIT` | `i` lists what the character owns |

**`BUY` gives no acknowledgement at all.** The stock list is redrawn
identically, so a run that presses `b` twice buys two of the thing and cannot
tell from the screen. The first run bought two hand axes that way. Count the
presses, or read the record afterwards.

## What the engine writes

### A purchase leaves stored encumbrance one debit behind

**CONFIRMED.** `docs/125-bug-notes.md` N19 records this for Curse of the Azure
Bonds, from the recovered overlays as well as from play: `shop_buy` adds the
item, recomputes the whole total, and *then* takes the coins, so the number
written out is the sum as it stood before the price was paid. **Pool of
Radiance does the same**, measured in
`WISH-SPEC-por-shop-encumbrance-spoiled`:

| | coins | Σ weight | stored | should be |
|---|---|---|---|---|
| staged before the boot | 140 gold | 0 | **999**, ours | 140 |
| after buying one hand axe listed at 1 gp | 27 platinum + 4 gold = 31 | 50 | **190** | 81 |

`190 = 140 + 50` -- his purse *before* it paid, plus the axe. The spoiled 999
is what makes this a measurement rather than a coincidence: the field was
overwritten wholesale rather than adjusted, so the engine computed 190 rather
than adding 50 to something.

**The excess is 109 rather than the 1 gp price, and that is Pool of Radiance's
purse arithmetic rather than a different bug.** Paying 1 gp out of 140 gold
coins leaves 27 platinum and 4 gold -- the engine consolidates the change into
the largest denomination it can -- so the *coin count* falls by 109 while the
value falls by 1. Encumbrance counts coins, not their value.

### Every screen that draws encumbrance recomputes it first

`WISH-SPEC-por-party-l1-shopped` balances exactly -- 30 coins, two axes at 50,
stored 130 -- because that run opened `VIEW` in the shop before it left.
N19 says the same of Curse. So **a record taken straight out of a shop with
nobody looking at the sheet is the one that fails the identity.**

### An in-town camp save rewrites the field

**CONFIRMED**, `WISH-SPEC-por-shop-encumbrance-control`: the same six records
staged at 999, loaded, encamped on the map and saved, with no shop and no
trainer. All six came back holding their own correct sum. So an ordinary save
does not preserve what was in the file.

### And that contradicts the training ladder, which is not resolved

The nine ladder rungs saved records whose stored encumbrance is 1000 per
training above the purse, and nine load-and-save cycles never corrected them
-- `WISH-SPEC-por-party-ladder-rung1` holds 21,000 against 19,000 gold. So
whatever rewrote the control's field did not happen on those boots.

**The two runs differ in the save path**: the ladder saved with
`SAVE CURRENT GAME` from the *training hall's party menu*, and the control
encamped from the map. They also differ in area, 11 against 0.

**The experiment that would settle it**, and it is one boot: stage 999 into a
save that loads back to the party menu -- any ladder rung does -- and take a
party-menu save immediately, training nobody. If it comes back holding 999,
the party-menu save preserves the field and camp rewrites it; if it comes back
correct, the difference is somewhere else and the next candidate is the area.

Until then, the honest form of the rule is narrow: **a stale stored
encumbrance is evidence about what the party did since the field was last
written, and not evidence that anybody edited the record.** That is what
`#323 (The encumbrance identity does not survive the training fee, so failing it is not evidence of an edited record)` needed and it is unaffected by which screen does the writing.

## What is in the specimen tree

| specimen | what it is |
|---|---|
| `WISH-SPEC-por-party-l1-shopped` | the six from creation, WISHFTR carrying two hand axes he bought with the 140 gp the engine rolled him. No character field was ever poked; the only byte this project wrote is the party's saved square |
| `WISH-SPEC-por-shop-encumbrance-spoiled` | the same party with stored encumbrance staged to 999, one hand axe bought, the buyer holding 190 and the five who bought nothing holding the right sum |
| `WISH-SPEC-por-shop-encumbrance-control` | the same spoiled input with no shop at all: all six correct |

## Running it

    tools/dosshop.py --map
    tools/dosshop.py --party $WISH_SPECIMENS/por-dos/WISH-SPEC-por-party-l1-intown \
        --shop 53 --slot E --interactive --cmd work/issue249/shop/cmd.txt
    tools/dosshop.py --party ... --shop 53 --encumbrance 999 \
        --steps Up '~5' y '~4' b '~4' b '~4' '@e' '~3' '@e' '~4' \
                '@e' '~4' '@s' '~3' g '~10' n '~4'

`--encumbrance` spoils the stored field before the boot, which is what makes a
right answer afterwards a recompute rather than our own staging surviving.
Output goes under `work/`, which is gitignored and has been lost twice: copy a
run you mean to keep into `$WISH_SPECIMENS` with `tools/specimens.py add` before
the slot goes down.
