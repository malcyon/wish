# The council's commissions

The City Hall's books, as `goldbox/commissions.py` reads them. `ECL08` on disk 3 is
the authority for all of it; the working that established it, `work/reports/commissions.md`
(P80) and `work/reports/quest-flags.md` (P30), is lost.

**The quest-flag half of that working is back and is now generated.**
[`151-quest-flags.md`](151-quest-flags.md) is every reference the thirty
scripts make to `$4A00`-`$4AF8`, rebuilt by `tools/eclflags.py` rather than
written by hand, and it reproduces the lost report's counts exactly: 179 of
the 217 persistent bytes named, 1415 operand references, 38 gaps.

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

## A quest the council never hears about: Ohlo's potion

The Slums hold a side quest that is not a commission and touches no ledger
byte, so nothing in this document's structures can carry it and the panel draws
no row for it (#157 (Ohlo's potion errand does not appear in the Quest Log)). It is recorded here because it is the first evidence that
area scripts keep quests of their own.

A man in the Slums asks the party to fetch a potion his agent is holding in a
booth in the old rope guild, and gives his name, `OHLO`, as the password.
`ECL14` keeps the state in two bytes:

| byte | 0 | 250 | 255 |
|---|---|---|---|
| `$4A04` | not spoken to, or wiped by an area change | the errand has been accepted | the encounter is closed |
| `$4A81` | the potion is not in hand | Ohlo's potion collected. | Ohlo's quest completed. |

All CONFIRMED from `ECL14`'s own writes, re-derived on 2026-09-02 with
`tools/eclflags.py sites 4A04 4A81` and given here as **script addresses**,
which are unambiguous because an `ECL` loads at `$9900`:

| where | what |
|---|---|
| `$A251` | `SAVE 250, [$4A04]` — the accept path. A scan of the raw bytes for `09 00 FA 01 04 4A` finds exactly one occurrence in the script |
| `$B042`/`$B048` | `SAVE 255, [$4A19]` then `SAVE 250, [$4A81]` — the booth hands the potion over |
| `$A3A2`/`$A3A8` | `SAVE 255` into both, after the `TREASURE`/`COMBAT` pair that pays 150 platinum and one random magic item — the delivery |
| `$A084`/`$A0B8` | `SAVE 255, [$4A04]`, then the fight, then `SAVE 255, [$4A81]` — he was killed instead |
| `$9F13`, `$9F1B`, `$9F30`, `$9F3B` | the entry test: 255 in either byte exits, then `[$4A81] == 250` and `[$4A04] == 250` pick his three speeches apart |
| `$AE1E` | `COMPARE [$4A81], 250 / IF>= / EXIT` — the booth refuses a party that already has the potion or has finished with him |

**The file offsets quoted on `#157 (Ohlo's potion errand does not appear in the Quest Log)` and `#158 (Track the quests the game itself forgets, starting with Ohlo's potion)` do not all point where they
say.** They were `0x957`, `0x1748`, `0xaa4` and `0x7b8`, and they are not
measured from one base: `0xaa4` is an offset into the raw file, `0x7b8` an
offset into the body after the two-byte load address, `0x1748` the body offset
of the *second* of the two instructions quoted beside it, and `0x957` points
four bytes into the instruction it names, which begins at `0x953`. Nothing
about the claims is wrong — every instruction exists, exactly once each — but
cite the script address rather than any of those.

**`$4A04` is scratch and does not survive leaving the Slums.** It is inside
`$4A00`-`$4A1F`, which the engine zeroes on every area change
([`41-memory-regions.md`](41-memory-regions.md)), so the game keeps no durable
record that the errand was accepted; `$4A81` is the durable half. Four saves
show the whole run — `$4A04` = 250 with `$4A81` = 0 twice, then `$4A81` = 250
with the scratch back at 0 after a trip out of the area, then both at 255 with
`$4ABB` counting the delivery as one more encounter.

**`SIDE_QUESTS` in `goldbox/commissions.py` is the table**, one entry per
quest, each naming the accept flag, the finish flag, the values that mean each
and the instruction that writes them. `side_quests()` reads a save through it,
and `scratch()` is how the `$4A00`-`$4A1F` half is reached — deliberately a
separate call from `flags()`, because a scratch byte means nothing unless the
script that wrote it is still resident.

**Sixteen of the twenty saves on the machine cannot tell "never met him" from
"accepted and left".** `side_quests()` reports that as `ambiguous` rather than
guessing: a party that took the errand and walked out of the Slums leaves a
save that is byte for byte the same, in these two flags, as one that never
spoke to him.

**Donald's decision, 2026-09-04, settles what the panel does with that:** the
Quest Log shows the errand once the potion is in hand, never for having
merely talked to Ohlo, so all sixteen read *not done* — which is the right
answer under that decision rather than a gap. `SideQuestState.durable_state`
is that reading: it ignores `$4A04` altogether and is a pure function of the
durable half of `SAVEDGAME0`, `$4A81` alone for this quest. `state` and
`ambiguous` are unchanged and stay useful for the debug log and the tests;
`durable_state` is what `automap/questlog.py`'s `side_quest_rows()` draws.

## Appointments

`$4A96`-`$4A9B`, plus `$4A8C` and `$4AC2`. A summons runs 254 = go there, 255 =
the interview happened.

**`$4A9A` is shared with a wilderness animation and the collision is a bug in
the shipped game** — clearing Yarash's pyramid cancels the special council
meeting for good. `goldbox-bugs.md` #7 (Write a C64 party into Amiga Pools of Darkness).

## Ports

The ECL bytecode is one artefact shared by every port, absolute operands
included, so all of the above holds at the same addresses on Amiga and DOS
(write-up lost, `work/reports/quest-flags.md` §7).
