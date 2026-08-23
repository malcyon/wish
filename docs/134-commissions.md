# The council's commissions

The City Hall's books, as `por/commissions.py` reads them. `ECL08` on disk 3 is
the authority for all of it; the working is in
`work/reports/commissions.md` (P80) and `work/reports/quest-flags.md` (P30).

## The ledger

26 bytes at `$4AA6`, one per commission, indexed by the clerk's own
`ONGOSUB [$6E79], 26` at `$9D55`. **0** untouched, **254** done, **255** paid.
The clerk pays on exactly 254 (`$9D1C COMPARE [$6E7A], 254`), so nothing else
is visible to her.

`$4AC1` counts commissions completed — bumped by the ten handlers that call a
job major: indices 0, 1, 10, 11, 12, 13, 15, 16, 17, 21.

## The four entries that keep a progress marker

Twenty-two of the twenty-six are only ever 0, 254 or 255. These are the rest.

| index | addr | value | meaning |
|---|---|---|---|
| 3 | `$4AA9` | 1 | the Bivant boy has been bought; still inside Buccaneer's Base. Becomes 254 on leaving |
| 3 | `$4AA9` | 128 | the party fled and left the boy. The clerk writes it off at 255, unpaid |
| 10 | `$4AB0` | 1 | the auction commission has been read out; it is what arms Podal Plaza |
| 14 | `$4AB4` | 1 | the Zhentil outpost commandant is dead; still inside the outpost |
| 14 | `$4AB4` | 253 | the outpost has been left; the ride home turns it into 254 |
| 21 | `$4ABB` | 1–24 | slum encounters cleared, of 25 |

All CONFIRMED, each from the instruction that writes it. `marker_text()` has
them.

**255 is not always "paid".** Index 3 at 128 and index 18 with Cadorna's seal
broken (`$4AC8` = 128) are both closed at 255 with no reward.

**Index 22 is dead.** `$4ABC` is named by no instruction in any script and its
handler is a bare `RETURN` — but its row in the clerk's payout tables is not
empty, so it was a commission once. `docs/125` N12.

## The offer board

`$A84D`: sixteen candidates in a fixed order, at most three shown per visit,
counted in `$4A05` — which lives in the scratch page the engine wipes on an
area change and is never reset inside the script. Candidate 9 is withdrawn: a
bare `GOTO $A890`.

A seventeenth offer, Valhingen Graveyard, runs *before* the sixteen at `$A584`
and outside the cap. Its gates are `$4AC1 >= 4`, the graveyard reward unpaid,
party strength ≥ 19, and `$4A96 != 255`. Above party strength 36 accepting
comes with an enchanted weapon.

Two side effects a predicate cannot show: being offered a job writes the
summons flags (`$4A97`, `$4A98`, `$4A99`, `$4A9A`, `$4A9B`, `$4A8C`, `$4AB0`),
and walking the whole list without filling three slots writes 254 into `$4ABE`
— "Cadorna exposed as a traitor".

## Appointments

`$4A96`-`$4A9B`, plus `$4A8C` and `$4AC2`. A summons runs 254 = go there, 255 =
the interview happened.

**`$4A9A` is shared with a wilderness animation and the collision is a bug in
the shipped game** — clearing Yarash's pyramid cancels the special council
meeting for good. `goldbox-bugs.md` #7.

## Ports

The ECL bytecode is one artefact shared by every port, absolute operands
included, so all of the above holds at the same addresses on Amiga and DOS.
`work/reports/quest-flags.md` §7.
