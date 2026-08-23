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
| 21 | `$4ABB` | 1–24 | slum encounters cleared, of 25 — see below |

All CONFIRMED, each from the instruction that writes it. `marker_text()` has
them.

**255 is not always "paid".** Index 3 at 128 and index 18 with Cadorna's seal
broken (`$4AC8` = 128) are both closed at 255 with no reward.

**Index 22 is dead.** `$4ABC` is named by no instruction in any script and its
handler is a bare `RETURN` — but its row in the clerk's payout tables is not
empty, so it was a commission once. `docs/125` N12.

## The slums: why 25, and why a PC guide says 15

`$4ABB` is incremented by one subroutine, `ECL14 $B69C` — `COMPARE [$4ABB],
254 / IF>= / RETURN`, `ADD 1`, `COMPARE [$4ABB], 25 / IF< / RETURN`, `SAVE
254`. **Fourteen `GOSUB [$B69C]` sites call it and every one is the instruction
after a `COMBAT`**, which is what makes "encounters" the right word:

* **twelve after a set encounter** — `$9E73 $9F08 $A0BE $A3B2 $A514 $AA02
  $AA87 $AB91 $ABFE $AC4B $AF7A $B10D`. Each sits behind its own one-shot flag
  (`$4ACA`, `$4ACB`, `$4A85`, `$4ACD`, `$4ACE`, `$4ACF`, `$4AD0`, `$4AD8`,
  `$4AD9`, and `$4A04`/`$4A81` for the man who wants the potion, `$4A19` for
  the booth). `$A0BE` and `$A3B2` are the fight-him and serve-him outcomes of
  one encounter, so **ten** distinct set fights, eleven if the booth man is
  killed before the potion errand closes him out.
* **two in the wandering-monster outcome handler** at `$B118`, on the two
  winning results — `$6DC7 == 0`, and `$6DC7 == 1` with kills in `$6DC8`. A
  loss (128) and a flight (129) branch away without counting. **One won fight
  is exactly one increment**; nothing adds per monster group or per square.

The wandering half is capped by a *different* byte. `$4A80` counts won
wandering fights, and both spawn sites refuse to roll another once it reaches
15 — `ECL14 $9B32` and `$ADD6`, `COMPARE [$4A80], 15 / IF>= / EXIT`. Ten set
plus fifteen wandering is 25 exactly, and the two specimens that finished the
slums (`work/p20/CONV2.D64`, `work/fields/npc_party.d64`) show `$4A80` = 15
with all nine one-shot flags and `$4A81` at 255 — 10 + 15 = 25, arithmetic
closed against the data.

So **Ozzy_98's GameFAQs walkthrough is right about `$4A80` and describing a
different counter**: "the goal here is to clear out all the random encounters
(There are 15)". Its next sentence, "the set encounters do not need to be
cleared", does not hold — on the minimum path all ten are needed. This is not
a port difference: the Amiga `ECL14` is the same 7,679 bytes as the C64's and
differs in ten of them, none within the `$B69C` routine or either `$4A80`
gate; the 15, the 25 and the 75 sit at identical file offsets in both.

**`$4ABB` is never seeded.** `ADD 1` and `SAVE 254` in `ECL14` are its only
writes anywhere in the thirty scripts, plus the clerk's `SAVETABLE 255` when
she pays. Every specimen we hold has it equal to `$4A80`, at 0–5 or at 255.

**No lockout.** The only set encounter that can be closed without counting is
the booth man (leave, or give the wrong password), and that merely takes the
maximum from 26 to 25. Nothing else writes a one-shot flag except in the same
breath as the `GOSUB`, a lost or fled wandering fight consumes no slot, and
murdering the fortune teller resets `$4A80` to 0 (`$A749`), which hands the
party fifteen more.

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
