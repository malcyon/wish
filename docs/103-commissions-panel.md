# A commissions panel

**Status: built and wired.** A quest log on the Automapper tab: what the City
Council has asked the party to do, and what it has already paid for.
`por/commissions.py` decodes it, `automap/commissions.py` draws it, it sits in
the right-hand column of the map tab under the notes, and
`tests/test_commissions.py` holds the verification below.

The research is done and is in `work/reports/quest-flags.md`. Four lines are
CONFIRMED and buildable from 224 bytes that are already inside `SAVEDGAME0`, so
this needs no new decoding — only a panel.

---

## What can be shown, and how sure we are

| line | where | confidence |
|---|---|---|
| commissions completed | `$4AC1` | CONFIRMED |
| the ledger: not done / reward waiting / paid | `$4AA6 + i`, i = 0..25 | CONFIRMED |
| what the clerk would offer next | `ECL08 $A84D`, re-implemented | CONFIRMED |
| outstanding "summoned to X" appointments | `$4A97`-`$4A9B`, `$4A8C`, `$4A96`, `$4AC2` | CONFIRMED |
| graveyard undead killed, and paid for | `$4A39`-`$4A3F`, `$4A8F`-`$4A95` | PROBABLE |
| slum progress, N of 25 | `$4ABB` | PROBABLE |

The ledger index **is** the quest: each has the clerk's own speech in a 26-entry
jump table, so 1 is Sokal Keep, 11 the graveyard, 20 Tyranthraxus, 25 Cadorna.
Run against the shipped unplayed save the offer loop emits *slums, Sokal Keep,
books*, which is what the game really opens with.

**Not ready, and should not be shown:** per-area sub-bits outside the named
ones, and anything above `$4AFF` — no ECL operand reaches there, so
`docs/41-memory-regions.md`'s `$4A20`-`$4B7F` range is unverified above `$4AFF`.

---

## One byte, one row

`ECL08`'s board gates candidate 0 on `$4AA6 + 21 != 255`, and `$4AA6 + 21`
**is** the ledger entry the clerk pays for. The board and the ledger are the
same byte seen from two ends: the imperative on the way in, the clerk's payment
speech — *slums cleared* — on the way out.

The byte's four states, from `por/commissions.py`:

| value | what it means |
|---|---|
| 0 | untouched |
| 1-253 | an area script's own marker. For the slums it counted 3, and `$4ABB` — documented as "slum progress, N of 25" — read 3 at the same moment, so the two count the same thing |
| 254 | done; the reward is still at the City Hall |
| 255 | paid |

**So the panel draws one row per commission**, sorted by first ledger index,
which is roughly the plot's own order. `automap/commissions.py` builds the list
once, at import, in `COMMISSIONS`: every board candidate paired with the ledger
entries its gate settles, plus the six entries (0, 2, 11, 22, 24, 25) no
candidate offers. A row appears when the party has met the commission — any
non-zero ledger byte, or the clerk raising it on the next visit — and carries
one state word:

| word | when |
|---|---|
| offered | every entry untouched, and the clerk raises it next visit |
| in progress | a marker, or some of a many-entry commission settled |
| reward waiting | any entry at 254 — money sitting at the City Hall |
| paid | every entry at 255 |

Paid rows are drawn muted, so live work stands out of a late-game list.

### The name is the clerk's, and which of his two names depends on the state

Before it is done, the board's imperative: *clear the slums*. Once it is done,
his payment speech: *slums cleared*. The speech is the better name and is only
ever shown over a job that really is finished — the whole point being that
*slums cleared* must never sit above a slum the party is halfway through.

Six entries have no candidate, so there is no imperative to borrow and the
clerk's only words for them are the payment speech. Those get a neutral name in
`UNBOARDED` — *the graveyard menace*, *Cadorna's treachery* — and the speech
still arrives when the job is paid.

### Where the model is genuinely not one-to-one, the row says so

* **Six ledger entries, one commission.** Candidate 2, *bring back books, maps
  and tomes*, settles 4-9. One row, with a sub-line — *3 of 6 books recovered* —
  when some but not all are in. Its gate is `$4AC2`, the book bounty flag, and
  not the six entries at all; the tooltip says which byte.
* **A candidate that settles nothing.** Candidate 9 is withdrawn — an
  unconditional `GOTO $A890` past its own body — so it is never offered and
  settles no entry. It is not a commission and gets no row; a muted footnote at
  the bottom of the panel says it exists.
* **Gates that read more than their own entry.** Candidates 4, 5, 6, 12, 13, 14
  and 15 also test appointment flags. `GATE_NOTES` puts each in words in the
  tooltip, which is why a row can be finished and still on the board.
* **Three a visit.** The clerk offers at most three, so a commission whose gate
  is open but which is fourth in line gets no row. A shown row's tooltip says
  which of the three cases it is: raised next visit, gate open but queued
  behind others, or gate shut.

### What is on the face, and what is in the tooltip

The face carries only facts about the party's game: the name, the state word,
and the books' count. The raw marker value is not one — `marker 4` says a byte
reads 4, and what 4 means is script-specific and undecoded — so it goes in the
tooltip with everything else that is internal:

```
clean out Kovel Mansion
candidate 6 on ECL08's board at $A84D: the clerk raises it on the next visit
ledger 12 at $4AB2 = 4
  the clerk pays for it as "Kovel Mansion thieves"
  written by Kovel Mansion (ECL0E)
  counts towards commissions completed
```

**One row is an exception, and it is the Slums.** Its tooltip is one sentence:

```
Counts every fight won in the Slums: 10 set encounters and 15 wandering.
```

That number is the only thing the row has to settle — a PC walkthrough quotes
15 for the same job, which is `$4A80`'s separate cap on the wandering half
([`134-commissions.md`](134-commissions.md)) — and Donald asked in 2026-08 for
that sentence and nothing under it. `TOOLTIPS` in `automap/commissions.py` is
the override, keyed by ledger index.

### Place names are capitalised at display time

The board says *clear the slums* and the clerk pays for *slums cleared*; a
quest log should say **Clear the Slums**. `_sentence` does both the first
letter and the place names, beside each other and for the same reason: the
strings in `por/commissions.py` are the bytecode's own words and are cited as
such, so nothing there is edited. `PLACES` holds the one word that needs it —
every other place the board names (Sokal Keep, Kuto's Well, Podal Plaza, Kovel
Mansion, Valjevo Castle, Stojanow Gate) is already capitalised in the game's
text. **Sokal, not Sokol**: that is the game's spelling and it stands.

### The design this replaced

The panel first had two groups, *Available from the clerk* and *Working
towards*, on the reasoning that the board and the ledger are different
structures and collapsing them would lose the many-to-one cases. The slums then
appeared in both — once as the offer, once as ledger 21 — and the mitigations
(a heading that avoided the word "progress", an `on the board` suffix, a tooltip
saying outright that it was one commission in one state) did not stop readers
counting two commissions. Donald reported it more than once. The mapping really
is complicated; that is an argument for the model, not for making the player
carry it, so the join now happens in `COMMISSIONS` and the complications are
handled row by row above.

## Where the code is

`por/commissions.py`: the 26 ledger names and the script that finishes each, the
three states, `$4AC1`, the `ECL08 $A84D` offer loop, and the eight appointment
flags. `read(source)` returns the lot; `summary_lines(source)` is a plain-text
rendering for the CLI, which still groups by state. `source` is the 224 flags,
the `$4A00` page, a whole `SAVEDGAME0` payload or a `SaveGame0` — the lengths
are distinct, so no flag is needed. No Qt.

`automap/commissions.py` is the panel: `COMMISSIONS`, the joined list;
`commission_rows(flags)`, which turns a flag block into the drawn tuples and is
what the tests read; `CommissionsPanel()` with one entry point `update_from(source)`
taking exactly what the decoder takes, and `set_message(text)` for when there
are no bytes. It redraws only when the flag block changes, and holds nothing
that can be typed into. **Nothing here is editable** — making it writable would
mean writing plot flags, a much larger promise than reading them.

**Wired** in `automap/window.py`: `poll_live` reads the two blocks itself and
hands the panel the `SAVEDGAME0` bytes — `Snapshot` does not keep them — once
the snapshot has decoded. On a poll that yields nothing the panel is left
alone, because plot flags do not change while the game is in a menu and a quest
log that blanked every time somebody opened one would be a flicker.

## Verification — done, in `tests/test_commissions.py`

* **The slums is one row whatever its byte reads** — 0, a marker, 254, 255 —
  which is the regression this shape exists to prevent.
* No unfinished row is labelled with the clerk's completion speech, and both
  finished states are.
* The six books are one row, with the count when some are in and no count when
  all six are paid; every one of the six is named in its tooltip.
* The withdrawn candidate is a footnote and never a row; every board candidate
  that settles something and every one of the 26 entries appears in exactly one
  `COMMISSIONS` member.
* The marker value never reaches the state word; the Slums' tooltip is
  Donald's one sentence and every other row keeps its ledger line.
* The shipped unplayed `POOL1` save shows nothing done and offers exactly slums,
  Sokal Keep, and books. `work/fields/npc_party.d64` reads `$4AC1` = 6, fourteen
  entries paid — six of them the major ones, which is what `$4AC1` counts — and
  offers nomads, kobolds, lizardmen, and draws each commission once.
* Reading is pure: the decoder copies its input, and the specimen save's bytes
  are identical after the panel has drawn them.
