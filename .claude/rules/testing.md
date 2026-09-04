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

**The largest font worth testing is +10, and 9pt is the base here**, so the
range is 9pt to 19pt, and `+6` matters most because it measures here about like
Windows' base font. There is no layout problem at any font a person uses;
somebody who needs text that large uses display scaling, which enlarges the
window too. A test that only holds above +10 proves an artefact and will be
true forever while catching nothing. If a claim is weak at a realistic font,
say it differently rather than at a bigger font --
`test_the_top_row_asks_for_more_than_the_page_makes_room_for` became true
everywhere once it compared a *rate* across two fonts instead of a gap at one.

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
outcome a user cares about: "the window fits a 720-high screen at +6pt"
survived both CI platforms where two structural proxies for it did not.

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
forty tests skipped has told you nothing. Say how many skipped and why.

**Never weaken a test to make a change fit.** If a change makes a test fail the
change is wrong until proven otherwise, and the proof is an argument about
behaviour rather than a smaller assertion.
`test_the_window_opens_inside_a_small_desktop` encodes Donald's actual screen;
a layout that fails it does not fit his screen.

**Failures found in the running program are worth more than any of it.** The
suite runs offscreen with no emulator. A screenshot, a save that loads, a party
a player can walk in the game -- those are the evidence, and the tests are how
you keep them true afterwards.

## Where a test gets its data

`CLAUDE.md` forbids the game's data entering this repository, and a fixture
that is a slice of a game file is the same copy under a new name. So:

* `tests/gamedata.py` reads it off the player's disks -- `game_file("GEO04")`
  finds whichever `POOL*` disk carries it, and skips when there are none.
* `synthetic_geo()` builds a well-formed map from the documented format, for
  the cases that need *a* file rather than a specific one.
* `tests/fixtures/` holds the player's own saved games and nothing else. Its
  contents are on an allowlist in `tests/test_repository_contents.py`. **Do not
  add to that allowlist** -- read from the disks, or generate it.

## A specimen is only evidence if we know who wrote it

**`/home/donald/dos_por_play/SAVE/` is Donald's own play directory and every
character record in it has been edited with Gold Box Companion's character
editor.** Assume all of them, not the ones that look wrong. Donald,
2026-09-04: *"Assume all character records in /home/donald/dos_por_play/SAVE/
were edited. Base your evidence and reasoning off saves you created
yourself."*

**And it is not only that directory.** Donald, 2026-09-04: *"any saves you got
off of any of the game disks might also have been edited."* His save disks are
a player's disks, played and tinkered with over years. So the boundary is not
a path -- it is **whether we watched it being written**.

**So a measurement rests on records we watched being written, and there is
essentially one source.**

**Saves an agent made by driving the game**, from character creation onward.
`tools/dosgnome.py` is the worked example: it rolls a character in the game's
own creation screens under DOSBox and reads back the bytes, and its five
same-boot racial controls are what make a single reading a measurement rather
than an anecdote. Donald, 2026-09-04: *"if we created our own characters and
level them up, then you can know it is safe."*

**A save found on a disk is not evidence, however official the disk looks.**
Donald, 2026-09-04: *"You shouldn't assume that saves you find on a game disk
are 'saves shipped with the game by the manufacturer'. Some random person on
the internet might have created those and edited them with GBC. You have no way
of knowing."* The archives here are a download -- `~/Downloads/fr-archives`,
"Forgotten Realms The Archives" -- so `Default files/Saves` has no chain of
custody either. It was listed as trustworthy in an earlier version of this
rule and that was wrong.

**A worked consequence:** six of the eighteen records in Pool of Radiance's
`Default files/Saves` fail the encumbrance identity, against two of eighteen in
the known-edited set. That was nearly filed as a question about the game. The
likelier answer is that it is a stranger's edited party, and no amount of
staring at it would have said which.

**Records this project's own writers produced** test the writer and are never
evidence about the game, since they carry what we already believe.

**The cost of getting this wrong is silent.** On 2026-09-04 a single edited
record -- SILAS, a *human* carrying two `.SPC` effect records where the engine
writes a human none -- refuted "an effect at duration zero is permanent",
stopped `#232 (An item-granted effect is dropped on the way through the
neutral record, with no report)`, and sent a `deep-research` agent after a
discriminator that may not exist. Nothing failed. The suite stayed green. It
surfaced only because Donald happened to mention he had used the editor.

**Two files can share a name and not each other's provenance.**
`CHRDATA6.SAV` exists both in the archives, shipped, and in the edited play
directory. A path finder resolves to one of them and the test cannot tell.
**So say in the test where its specimen came from**, and when a finding is
written up, give the corpus size *and* what the records are.

The same trap caught a census that was sweeping an emulator instance's staged
tree, where the sweeping tool's own tampered probe records sat -- our bytes
read back as the engine's. `tools/dostailcensus.py` excludes what this project
wrote, by name, and that exclusion is worth copying rather than reinventing.

**The way out, when no specimen can be trusted, is to read the code instead.**
A finding taken from the engine's own instructions cannot be poisoned by an
edited save. `#232 (An item-granted effect is dropped on the way through the
neutral record, with no report)` was settled that way on 2026-09-04 after
SILAS had misled it: the expiry routine at `GAME.OVR:0x23DCC` reads the 16-bit
duration at record bytes 1-2 and nothing else, so duration zero is permanence,
which is what the project had believed before an edited record refuted it.
Watching the routine run confirmed it, and readying a magical item in the
running game produced the engine-written specimen the corpus had never had.

**That is the order to prefer when provenance is in doubt: the code, then a
specimen we made, then a specimen we merely found.**

Why these rules exist, and the incidents behind them:
`docs/160-why-these-rules.md`, "Testing".
