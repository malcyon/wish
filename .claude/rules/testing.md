---
paths:
  - "tests/**"
---

# Testing

**A green suite is the floor, not the finding.** Everything here is about the
gap between "the tests pass" and "we know this works".

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

Why these rules exist, and the incidents behind them:
`docs/160-why-these-rules.md`, "Testing".
