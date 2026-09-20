---
paths:
  - "tests/**"
---

# Testing

**A green suite proves nothing broke. It is not what you set out to learn.**
Everything here is about the gap between "the tests pass" and "we know this
works".

**Test what would actually break.** A test that restates the implementation
passes forever and catches nothing. Ask what a user would see go wrong, and
assert that. `tests/test_mapscale.py` pins a window minimum because a window
that does not fit the screen is what the user hits.

**Prove a regression test fails without the fix.** Revert the fix, watch the
test go red, put the fix back. A test written against a bug that is already
fixed is a guess until you have seen it fail.

**Assert a width at `+0` only.** A `+N` font offset is not the same size on two
machines, and `+0` is the one offset that means the same thing everywhere --
whatever the machine running the test actually starts from. Assert a *height*
across the range: a taller font makes every machine's rows taller by the same
proportion, while how wide a button gets for the same text is the platform's
business.

**The largest font to test is +10, and 9pt is the base here**, so the
range is 9pt to 19pt, and `+6` matters most because it measures here about like
Windows' base font. There is no layout problem at any font a person uses;
somebody who needs text that large uses display scaling, which enlarges the
window too. A test that only holds above +10 proves an artefact and will be
true forever while catching nothing. If a claim is weak at a realistic font,
say it differently rather than at a bigger font --
`test_the_top_row_asks_for_more_than_the_page_makes_room_for` compares a *rate*
across two fonts instead of a gap at one.

**A number measured on this machine is not a number.** It is a measurement of
this machine, and the moment it goes into an assertion it becomes a claim about
every machine. Compute from what the thing asks for rather than from what you
saw: `natural + box.sizeHint().width() + 400`, never a constant that happened
to work here. Where a constant genuinely is the answer, say beside it what it
was measured on and what would move it.

**When a constant bounds something, assert that it is bounded, not that it
never moved** -- non-decreasing, and flat by the largest font. A machine whose
base font is smaller than ours still climbs towards the cap; only a machine
already at the cap sees no climb at all. Prefer the assertion that states the
outcome a user cares about: "the window fits a 720-high screen at +6pt".

**A timing measured on this machine is not a timing**, and it is worse than a
measured number because the test passes locally every time. A concurrency test
whose failure mode is "the other thread did not get a turn" will find that out
on somebody else's hardware. Drive the thing from what it actually does rather
than racing it: `settle_files` sleeps between reads, so the test stamps the
file forward with `os.utime` on every sleep, which is what a save in flight
looks like from outside and cannot be starved out.

Prefer, in order: no thread at all; a thread the code under test drives; a real
thread with a margin you can justify. Never a sleep chosen because it worked
once.

**Say what the sample size was.** "24 of 24 records round-trip byte for byte"
is evidence; "it worked on my character" is not. Where a rule has exceptions,
count them and name them rather than rounding them away.

**A test that skips is not a test that passes.** `tests/gamedata.py` skips
cleanly with no disks, which is right -- but a suite that is green because
forty tests skipped has told you nothing. Say how many skipped and why. On a
machine with its own `gamedisks.yaml`, an entry the registry cannot lead to
-- every entry of the example, the ones that are not titles included -- fails
`tests/suite/test_gamedata.py`'s per-entry guard, and the lookups that are not
reached at import raise `RegistryError` as well (`gamedata.curse_dir`,
`test_gametables.disks_for`), so a missing entry is not a silent skip.

**Never weaken a test to make a change fit.** If a change makes a test fail the
change is wrong until proven otherwise, and the proof is an argument about
behaviour rather than a smaller assertion.
`test_the_window_opens_inside_a_small_desktop` encodes Donald's actual screen;
a layout that fails it does not fit his screen.

**A failure found in the running program tells you more than any of it.** The
suite runs offscreen with no emulator. A screenshot, a save that loads, a party
a player can walk in the game -- those are the evidence, and the tests are how
you keep them true afterwards.

## Where a test gets its data

`AGENTS.md` forbids the game's data entering this repository, and a fixture
that is a slice of a game file is the same copy under a new name. So:

* `tests/gamedata.py` reads it off the player's disks -- `game_file("GEO04")`
  finds whichever `POOL*` disk carries it, and skips when there are none.
* `synthetic_geo()` builds a well-formed map from the documented format, for
  the cases that need *a* file rather than a specific one.
* `tests/fixtures/` holds the player's own saved games and nothing else. Its
  contents are on an allowlist in `tests/suite/test_repository_contents.py`. **Do not
  add to that allowlist** -- read from the disks, or generate it.

## A specimen is only evidence if we know who wrote it

**`/home/donald/dos_por_play/SAVE/` is Donald's own play directory and every
character record in it has been edited with Gold Box Companion's character
editor.** Assume all of them, not the ones that look wrong. Base evidence and
reasoning off saves you created yourself.

**And it is not only that directory.** Any save found on any of the game disks
might also have been edited: his save disks are a player's disks, played and
tinkered with over years. So the boundary is not a path -- it is **whether we
watched it being written**.

**So a measurement rests on records we watched being written, and there is
essentially one source.**

**Saves an agent made by driving the game**, from character creation onward.
`tools/dos/dosgnome.py` is the worked example: it rolls a character in the game's
own creation screens under DOSBox and reads back the bytes, and its five
same-boot racial controls are what make a single reading a measurement rather
than an anecdote.

**A save found on a disk is not evidence, however official the disk looks.**
Nobody can tell a save shipped with the game from one a stranger made and
edited with Gold Box Companion. The archives here are a download --
`~/Downloads/fr-archives`, "Forgotten Realms The Archives" -- so `Default
files/Saves` has no chain of custody either.

**The encumbrance identity is not a provenance test.** A record failing
`money + Σ(weight × quantity)` against the stored total is not evidence that
anybody edited it, and a record passing it is not evidence that nobody did. It
checks our reading of the money block, the item stride, the weight offset and
the byte order, in one sum, which is what it is for.

**Failing it is the normal state of a record we watched being written.** The
engine rewrites the field when it rebuilds a character's derived fields, and no
routine that moves coins does that, which is why the drift survives a save: one
boot leaves one fee of drift, and a training ladder's climb is mostly our own
restaging -- `tools/dos/dostrainprobe.install` moves stored encumbrance with
the gold it pokes, which is right for an input and is not the engine agreeing
with us. `tools/dos/dosencsave.py` is the tool.

**Poke a field before the boot, or the engine never sees it.** A value written
after `LOAD SAVED GAME` has already put the party in memory comes back as the
correct sum from every save, which reads exactly like a recompute and is the
engine writing its own untouched value over our poke. A staging that lands
after the load has measured nothing.

**The identity is the engine's own arithmetic, and the engine's own code says
when it stops being true.** Pool of Radiance rebuilds the field at
`START.EXE` image `0x1758` -- zero it, add each item's `weight × quantity`,
then add the seven purses -- and Curse and Silver Blades have the same routine
in `GAME.OVR`. So the *formula* is settled and a mismatch is one of two things:
the engine not having run that routine since something moved, or one of our
offsets being wrong. Telling those apart is the whole of what follows.

**No routine anywhere in the three engines writes a coin purse and calls that
recompute** -- 0 of 11, 0 of 12 and 0 of 10 in the three `GAME.OVR` files. The
trainer's fee and a shop's change are coin movements, so neither is repaired.
The one money-moving screen that does recompute is **appraising a gem or a
jewel**, which decrements the count and rebuilds the total on its way out.

**Four things are known to leave a record failing it, and the first three are
the engine's own work:**

| what happened | what the record looks like |
|---|---|
| a training fee | stored **above** the sum by an exact multiple of 1000 |
| a payment -- a purchase, an identify, a cure | stored above by the fall in the *coin count*, which after the engine consolidates change into a larger denomination can be far more than the price paid: 109 for a 1 gp axe |
| a readied bag of holding, Pool of Radiance only | stored **5000 below** the sum, or at the readied items' own weight when the sum is under 5000. Read from the code; no record on this machine carries one, so nothing has confirmed it in a file |
| a field we poked before a boot | whatever we poked |

**So the check is not weakened, it is narrowed: name the operation, or the
miss still means something.** A miss you can attribute to one of those four is
explained and says nothing about who wrote the record. A miss you cannot is
the signal the identity was built to be -- one of our offsets is wrong, or the
record was edited -- and it has to be chased rather than waved past. The two
records that fail it here for no named reason, GILES at −20 and ASTRID at −65,
are PROBABLY edited, and the argument for that is the *direction of a
disagreement* rather than the sign of the miss: the cached display line and the
stored total agree with each other while the quantity byte alone reads a round
50, where the engine keeps the quantity and the total in step and lets only the
line go stale (`docs/125-bug-notes.md` N19).

**A tolerance is not a reading.** `assert exact >= total - 2` says our sum may
be two-in-twenty-four wrong; it hides which two and why. Name the records, or
point the test at a set of records where the answer is exact.

**And the C64 cannot be checked this way at all.** Its record has no such
field: all three titles sum into a scratch word past the end of the record
(`$6DF6` in Pool of Radiance, `$7EF6` in the other two) every time `LIBRARY`
draws the sheet. `tests/test_enccensus.py::test_the_c64_record_has_no_
encumbrance_to_check` goes red if one is ever located.

The rule underneath all of this: a save found on a disk has no chain of
custody, and **staring at it does not say which**. The reason to distrust the
archives is that nobody watched them being written.

**And the archives' installed save directory is not an archive.**
`games/POOLRAD/GAME/POOLRAD/SAVE` is byte-identical to `~/dos_por_play/SAVE`,
and `SavesDir/76561197971030711/1882370/English` differs from it only by a
`GBC` subdirectory -- Gold Box Companion's own. Only `Default files/Saves`
holds what the download shipped. A sweep that walks the archives whole picks
the edited party up under an innocent-looking path, so grade a record by
**every** path its bytes were found at, not the first one walked.

**Records this project's own writers produced** test the writer and are never
evidence about the game, since they carry what we already believe. **Including
saves a person edited in Wish**: driving a party through the game does not keep
it clean afterwards.

**Editing an input and then watching the game compute from it is a valid
experiment** -- the engine does not care how a byte got there. Reading back a
**stored value that Wish wrote** and calling it the game's arithmetic is not.

So: raise a cleric's wisdom in Wish, drive the trainer, and what the trainer
offers is the game's answer for that wisdom. Raise the weight of an item in
Wish and read the stored encumbrance, and you have measured Wish.

**A specimen dies with the emulator slot that made it.** `Session.stage()` is a
`copytree` into the pool instance's own directory, and tearing the slot down
takes the instance with it. **Copy a specimen out before the slot goes**, and
put it in the tree below rather than anywhere in scratch.

**The tree is `$WISH_SPECIMENS`, default `~/wish-specimens/`**, outside the
repository because the game's data must never be committed. `tools/registry/specimens.py
add` copies a save in, records who made it and how, hashes every file and makes
it read-only; `check` re-hashes and reports anything that moved; `list` says
what is there. A file with no `provenance.toml` is not a specimen, and `check`
says so. It is where saves that exist only for tests are kept, so nobody
edits one by mistake.

`docs/125-bug-notes.md`'s N13 is the worked example of surviving this. Its
evidence is *"the table's bytes and the three compares"* -- `GEN $10AD`, read
out of the code -- with ROLAND at wisdom 16 as corroboration. The code half is
untouchable and the finding stands on it. Had it rested on ROLAND alone it
would now be worthless.

**The cost of getting this wrong is silent.** A single edited record can refute
a correct belief -- a *human* carrying two `.SPC` effect records where the
engine writes a human none is enough to make "an effect at duration zero is
permanent" look false -- and nothing fails. The suite stays green.

**Two files can share a name and not each other's provenance.**
`CHRDATA6.SAV` exists both in the archives, shipped, and in the edited play
directory. A path finder resolves to one of them and the test cannot tell.
**So say in the test where its specimen came from**, and when a finding is
written up, give how many records and what they are.

**A sweep must also exclude what this project wrote.** An emulator instance's
staged tree holds the sweeping tool's own tampered probe records, and they read
back as the engine's. `tools/dos/dostailcensus.py` excludes them by name; copy
that exclusion rather than reinventing it.

**The way out, when no specimen can be trusted, is to read the code instead.**
A finding taken from the engine's own instructions cannot be poisoned by an
edited save: the expiry routine at `GAME.OVR:0x23DCC` reads the 16-bit
duration at record bytes 1-2 and nothing else, so duration zero is permanence.

**That is the order to prefer when provenance is in doubt: the code, then a
specimen we made, then a specimen we merely found.**

Why these rules exist, and the incidents behind them:
`docs/160-why-these-rules.md`, "Testing".
