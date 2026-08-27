# Working notes for Claude

## Conciseness

Say the thing once, in as few words as carry it. Length is not thoroughness.

Cut: preamble, restating the request, summarising what you just did in the same
breath as doing it, hedging, and "as you can see". Keep: offsets, byte values,
exact error strings, the reason a choice was made.

If a sentence would survive deletion without the reader losing anything, delete
it.

## Delegating to subagents

**The default is to delegate.** Reading a lot of files, running a long
experiment, disassembling, driving the emulator, writing something up -- all of
it goes to a subagent. The main window coordinates and answers questions.

The reason is context, and context is the scarce resource. A subagent's tool
output never enters the main window: a long grep out there costs nothing that a
long grep in here does.

**Give each agent its own files.** Several agents in one working tree will
collide. Assign non-overlapping areas, and say which in the brief.

**Subagents do not commit.** As things stand the main window makes the commits,
so nothing races the index.

**Commit a subagent's work before you review it, and push only after.** The
sequence is: the agent reports, the main window **commits locally**, the
`code-reviewer` runs, the findings are fixed or rejected with a reason, and
*then* it is pushed. Reviewing before committing is what this project used to
do, and on 2026-08-26 a reviewer ran `git checkout` on the file it was
reviewing and **destroyed 580 lines that existed nowhere else**. A local commit
costs nothing, is never pushed unreviewed, and turns that class of accident
into `git revert`.

If the review then rejects the work outright, the commit is reverted or the
branch reset -- deliberately, by the main window, which is a different thing
from losing it.

**Every subagent that wrote code gets reviewed.** Run the `code-reviewer`
subagent on what it changed, read the findings, and act on them -- or say why
not. The reason is not ceremony: an agent that has spent two hours inside a
problem is the worst possible judge of whether its own answer is right, and the
reviewer has already caught things the author could not see.

**Verify a finding before acting on it.** The reviewer is a reader, not an
oracle. It once reported a dead code path in `automap/actions.py` that turned
out to be a deliberate lever with a test and a docstring explaining it; the
guard was most of the way deleted before the test caught it. Check the claim,
then fix or reject it -- and rejecting it is a normal outcome, not a failure of
the review.

This does not apply to a subagent that only wrote documentation or only ran
experiments. It applies to code.

**The `reverse-engineering` subagent runs on Fable and is not to be used
unless the work genuinely cannot be done without it.** It is not the default
for anything technical, and "this is a reverse-engineering project" is not a
reason to reach for it. **Do not launch it without asking Donald first.**
It exhausted a monthly spend limit in one night on 2026-08-26, and what it had
produced by then a general-purpose agent went on to match.

**Reverse-engineering work goes to a general-purpose agent, and most of it
turns out to be ordinary work.** Diffing two files against a layout we already
have, flipping a byte and reloading, driving DOSBox or WinUAE through a
documented recipe, walking a save with a hex editor -- all of that is
general-purpose work, and it is how the DOS saved game's inherit list went
from 8016 bytes to 444 and how the Amiga Pool of Radiance record was read.

**The escape hatch, and use it rather than pressing on:** if a general-purpose
agent finds the task genuinely needs a disassembly -- reading 68000 or 6502
code rather than watching an address or diffing a file -- it should stop and
say so, and the work comes back to Donald to decide whether it is worth Fable.
That is a signal, not a failure. Stopping is cheap; an agent grinding at a
disassembly on the wrong model is not.

**Emulator work goes through the instance pool.** VICE serves exactly one
binary-monitor connection *per process*, so running two things at once means
two emulators, not two connections. `tools/instance.py claim` hands back a
binary-monitor port, a text-monitor port, a command port, an X display, a work
directory and a `vicerc`, and holds the lease for as long as your process
lives. `Session(disk, slot=slot)` takes it from there; `POR_HEADLESS=1` keeps
the window off Donald's desktop. Say in the brief which slot the agent has.
Two instances have been proven to coexist -- `docs/123-parallel-sessions.md` §0.

**Port 6502 is Donald's.** The pool allocates 6520 and upwards and never
touches 6502, 6510 or 6600. Anything on those is a game a human started from
the desktop menu -- do not attach to it, do not probe it, do not kill it.

**Never kill a process by name.** Not `pkill -x x64sc`, not `pkill -x Xephyr`.
Kill only the process group your own slot launched -- `Session.terminate()`, or
`slot.teardown()`. Reclaim another slot only when `tools/instance.py reap` says
its lease is unheld; a slot whose lease is held is somebody's, however dead it
looks. The one time this rule was broken, what died was Donald's own window.

**The pool owns the lifecycle.** Allocate, launch, tear down. Do not attach to
an emulator you did not launch, and do not launch one outside the pool -- an
instance nobody leased cannot be told from a human's.

**Nothing an agent runs may put a window on Donald's screen.** He works at
that desktop while agents run, and windows flashing open and closed are not a
cosmetic annoyance -- one of them was a modal dialog that sat over his editor
until he dismissed it.

`tests/conftest.py` forces `QT_QPA_PLATFORM=offscreen`, so `pytest` is safe.
**Everything else is not.** A measurement script, a screenshot script, anything
that builds a `QApplication` outside the suite inherits his live session unless
it is told otherwise:

```sh
env -u WAYLAND_DISPLAY -u XDG_SESSION_TYPE QT_QPA_PLATFORM=offscreen \
    GDK_BACKEND=x11 .venv/bin/python your_script.py
```

`QWidget.grab()` works under `offscreen`, so a screenshot never needs a visible
window. `tools/iconsheet.py` is the pattern.

**Unsetting `WAYLAND_DISPLAY` is the part that is easy to miss.** His desktop is
Wayland, and a GTK or Qt child prefers `WAYLAND_DISPLAY` over whatever you set
for X -- so a private `Xvfb` is not a sandbox. DOSBox-X's file chooser walked
straight out of one that way and drew on his screen. "Run it on your own X
display" is not sufficient advice on this machine.

**An agent's `ssh` must never be able to ask a human anything.** With no tty
and `DISPLAY` set, OpenSSH does not fail when authentication falls through --
it runs `SSH_ASKPASS`, and on this desktop that is `ksshaskpass`, which draws a
KDE credential dialog on Donald's screen. Three of them appeared in one night
that way. So:

```sh
SSH_ASKPASS_REQUIRE=never ssh -o BatchMode=yes ...
```

`BatchMode=yes` makes ssh fail instead of prompting; `SSH_ASKPASS_REQUIRE=never`
stops it reaching for a dialog even so. Set both, including for anything that
shells out to `ssh` or `scp` -- `winvm ssh` does not pass `BatchMode`, so it is
one of the things that needs wrapping rather than trusting.

A prompt an agent cannot answer is not a pause; it is a dialog on somebody
else's desktop, waiting on somebody who did not ask for it.

**Never point VICE at Donald's config.** Every pooled instance gets its own
`vicerc` seeded from his, with `SaveResourcesOnExit=0`, so nothing an agent
runs can write settings back. His file is read as a template and never opened
for writing.

**No agent runs `git checkout`, `git restore`, `git reset`, `git stash` or
`git clean` against a file in this repository.** Several agents share one
working tree, so a revert is never local to the agent doing it: it discards
whatever anybody else has uncommitted, silently and unrecoverably. That is how
580 lines of `por/amiga.py` went on 2026-08-26 -- a reviewer undoing a
throwaway edit of its own.

To test whether a change is load-bearing, **copy the file aside and copy it
back**, and `diff` to confirm the restore. Only the main window touches git's
history, and only deliberately.

**The brief carries the standing constraints**, because a subagent starts cold:
never write to `/home/donald/c64/Pool of Radiance Disks/`, never commit the
game's code, art or data ("What must never enter this repository"), never run
the git commands above, and leave the VICE configs alone.

Stays in the main window: Donald's questions, short edits, and anything where
writing the brief costs more than doing the work.

**Which agent, for what.** The definitions are in `.claude/agents/`; this is
the routing.

| agent | model | when |
|---|---|---|
| `reverse-engineering` | Fable | **Ask Donald before launching it.** Only when the work needs a disassembly read, not merely a measurement. Exhausted a monthly limit in one night |
| `quick-fix` | Sonnet | the issue's "What would fix it" names the **mechanism**: a port, a deduplication, narrowing a check. Never anything with a design decision left in it |
| `general-purpose` | inherits | everything else, including work that looks like reverse engineering and is not |
| `code-reviewer` | Sonnet | after **every** subagent that wrote code, on the local commit, before it is pushed. It runs in the shared tree, so scope it to the files it owns |
| `docs-reviewer` | Sonnet | when documentation may have drifted from the code -- after a run of findings lands. It runs in the shared tree, so scope it to the files it owns |
| `backlog-auditor` | Sonnet | before a refinement pass, or when the backlog has grown unwieldy |
| `changelog-writer` | Sonnet | after a batch of work lands, and before cutting a release |

**`quick-fix`'s filter is a property of the issue body** -- does it name the
mechanism, or only the goal? #71 looked like ordinary work and took nine
rounds and a `QTableView` subclass. #73 named the two candidate shapes and
said which was smaller, and that is what made it assignable.

**Every agent gets an escape hatch and it is a success, not a failure.** If the
work turns out to need something the agent is not for, it stops and says so and
the work is re-routed. An agent that presses on into a decision that was not
its own costs more than the re-route.

**Scope a reviewer explicitly when more than one agent is in the tree.** A
`code-reviewer` starts with `git diff`, and with three agents working that diff
is three people's work. Name the files it owns and name the ones it must
ignore, or it will report another agent's half-finished change as a finding
against the one you are reviewing.

## Prioritising the work list

Donald asks for a recommended order regularly, and this is what the
recommendation is made of. **It is a recommendation.** He recurates the
`Priority:` labels by hand, so a list that disagrees with a label says so
out loud and leaves the label alone.

**Lead with what you would do first and why, one line each.** Not an
exhaustive survey, not a table of everything open. Group by category when
there are more than a handful, because the categories are what make the shape
visible.

What moves an issue up:

* **A defect a user can actually hit**, over anything that is only untidy.
  What does the player see? If the honest answer is "nothing", it is not
  urgent, however wrong it is.
* **A guarantee that is asserted and never verified.** #70 was exactly this --
  the 1280x720 promise was believed by everyone and checked by nobody, and the
  first time it ran in CI it failed on both platforms. Worse than a missing
  test, because a missing test is not believed.
* **Work that unblocks several other issues.** #70's synthetic party unblocked
  #31, #33 and #34 at once. One issue that frees three beats three that free
  none.
* **The smallest thing that removes a blocker**, rather than the whole of what
  the blocker is in the way of.
* **A contradiction in the knowledge base.** Two documents disagreeing costs
  somebody a session, and the fix is usually an hour. #75 was a paragraph.

What moves it down:

* **`blocked` on Donald specifically** -- a choice only he can make, a machine
  only he has. Work blocked on a measurement we could take ourselves is not
  blocked and the label should come off.
* **Anything needing a design decision he has not made.** Do not schedule the
  building of something whose shape is still his to choose; schedule the
  question instead.
* **A `question` with no consequence attached.** If nothing changes when it is
  answered, it can wait for the session that stumbles over it.

**Say what each issue is waiting on, not just where it ranks.** "Blocked on
one DOS save made outdoors" is actionable; "medium priority" is not.

## Commits

**Keep a commit message to one sentence.** That is the whole rule, and it
exists to stop the assistant writing an essay in every message. Reasoning
belongs in `docs/50-experiments.md`, which exists for exactly that.

One commit per finding, where that is practical. Three findings in one commit
is worse for future archaeology than three commits, even when the files
overlap -- but do not spend longer splitting a commit than the split is worth.

```
Find the staging page at $5500
```

**The issue number goes at the end of that same line, in parentheses**, never
on a line of its own. GitHub hotlinks it inside parentheses; keeping it inline
keeps the message one line in `git log --oneline`. Use `closes #N` on the commit
that actually finishes the work -- that closes the issue when it reaches `main`
-- and a bare `#N` for a commit that only moves it along.

```
Land in the largest open part of the map (closes #14)
Read the trainer out of GEN (#10)
```

**The sentence still has to stand on its own.** It is read in `git blame`, in
`git log` and in a terminal, where `#14` is an opaque number -- and that is
where this project's archaeology actually happens. A message that needs GitHub
to be understood is worse than one that does not.

**Push once the code has been reviewed and the findings dealt with.** The
sequence is: a subagent reports, the `code-reviewer` runs on what it wrote, the
findings are fixed or explicitly rejected with a reason, and *then* it goes to
the remote. Donald has standing approval on that; he does not have to be asked
each time.

**Do not sit on commits.** A day's work was once held back and pushed in one
batch of forty-one, and a Windows regression that CI would have caught in
minutes went undetected for hours because no CI had seen any of it. Local
commits also silently break `closes #N`, so issues stay open while everything
looks finished. Push in the batches the reviews land in.

A documentation-only or `CLAUDE.md`-only commit needs no code review and can go
straight out.

**After a push, check that CI passed.** Not optional and not "later": a red
`main` is the state everything else is built on, and a failure found an hour
later has other people's work stacked on top of it.

**Check the run for the commit you pushed, not the newest run.** `--limit 1`
answers whichever run is at the top, which during a push is usually the
*previous* one, already green. That is how green has been reported off a stale
run three times here across two sessions. Match on `headSha`:

```sh
SHA=$(git rev-parse HEAD)
until [ "$(gh run list --limit 5 --json headSha,status \
           -q "[.[] | select(.headSha==\"$SHA\")] | map(.status) | unique | join(\",\")")" \
        = completed ]
do sleep 15; done
gh run list --limit 5 --json headSha,name,conclusion \
  -q ".[] | select(.headSha==\"$SHA\") | \"\(.name)\t\(.conclusion)\""
```

Both jobs, both named, both against that sha. A run whose `conclusion` is
empty has not finished, however `completed` the list looks.

Give it a minute or two -- the suite takes about 90 seconds on each of four
jobs. If it failed, `gh run view <id> --log-failed` says why, and **the fix goes
to a subagent**: the failure is usually platform-specific, the diagnosis is
reading, and neither belongs in the main window.

**Two failures happen here and neither reproduces on Linux**, so expect them:
something Windows cannot do (`chmod` does not make a directory unwritable
there, `fcntl` does not exist, paths are not split on `/`), and something that
is not byte-identical on another machine (a rendered image, anything with a
font or a timestamp in it).

## Testing

**A green suite is the floor, not the finding.** Everything below is about the
gap between "the tests pass" and "we know this works".

**Test what would actually break.** A test that restates the implementation
passes forever and catches nothing. Ask what a user would see go wrong, and
assert that. `tests/test_mapscale.py` pins a window minimum because a window
that does not fit the screen is what the user hits; it does not assert that a
function returns what the function returns.

**Prove a regression test fails without the fix.** Revert the fix, watch the test fail, put the
fix back. A test written against a bug that has already been fixed is a guess
until you have seen it red. This has gone wrong here twice: a test that filtered
on `not isWindow()` passed with the fix reverted, because the fault *was* a
parentless widget answering `isWindow() == True`; and a feature-flag test only
earned its place once forcing the flag on made it fail.

**A number measured on this machine is not a number.** It is a measurement of
this machine, and the moment it is written into an assertion it becomes a
claim about every machine. Three of one night's failures were this: 1270 here
against 1308 on CI's Linux and 1447 on Windows; five clipped fields here and
nine on another Linux box; a window width of `natural + 900` that was room to
spare here and twenty pixels short on Windows. Each time the fix was the same
-- **compute from what the thing asks for rather than from what you saw**, so
`natural + box.sizeHint().width() + 400` instead of a constant that happened
to work. Where a constant genuinely is the answer, say beside it what it was
measured on and what would move it.

**The trap has an inverse, and it caught #77 after the constant was right.**
A cap can be a perfectly good constant and the *assertion about it* still be a
measurement of this machine. #77 capped three widgets so the automapper page's
floor stops following the UI font, and asserted the floor was **the same at
every font**. True here -- 580 at +0 through +10 -- and red on both CI
platforms, because their base font is *smaller*: CI's Linux climbs 561, 578,
578, 578 and Windows 551, 569, 576, 576. The cap holds in all three. Only a
machine whose base font already reaches the cap sees no climb at all.

So when a constant bounds something, **assert that it is bounded, not that it
never moved**: non-decreasing, and flat by the largest font. And prefer the
assertion that states the outcome a user cares about -- "the window fits a
720-high screen at +6pt" survived both platforms untouched, while two
structural proxies for it did not.

**Say what the sample size was.** "24 of 24 records round-trip byte for byte" is
evidence. "It worked on my character" is not. Where a rule has exceptions, count
them and name them rather than rounding them away.

**A test that skips is not a test that passes.** `tests/gamedata.py` skips
cleanly with no disks, which is right -- but a suite that is green because
forty tests skipped has told you nothing. Say how many skipped and why when it
matters.

**Never weaken a test to make a change fit.** If a change makes a test fail, the
change is wrong until proven otherwise, and the proof is an argument about
behaviour, not a smaller assertion. `test_the_window_opens_inside_a_small_desktop`
encodes Donald's actual screen; a layout that fails it is a layout that does not
fit his screen.

**Failures found in the running program are worth more than any of it.** The
suite runs offscreen with no emulator. A screenshot, a save that loads and
walks, a party that reads right in the game -- those are the evidence, and the
tests are how you keep them true afterwards.

## Testing a conversion

**The standard is a perfect conversion.** Not "every loss is reported" -- that
is the old rule and it is too weak. Reporting a dropped field is the *minimum*;
it is not permission to drop it.

**Every field is carried, or it is on a short list with a tested reason.** Three
reasons are legitimate:

* the destination format **has no such field** -- and that has been established
  by reading its layout, not assumed;
* the destination **derives it** on load, so writing it is pointless -- and that
  has been *demonstrated in the running game*, not argued from plausibility;
* we **do not understand the bytes well enough to write them**, in which case
  the entry is a defect with a settling experiment, not a permanent exemption.

The third kind is a bug that has not been filed yet. Treat it that way.

**A template is not one of the three reasons, and "the template supplies it" is
not an answer.** Donald's ruling, 2026-08-26: *"We should not be using a
template at all. We should block on not understanding everything and go back and
understand what we need to. No more plugging in fake data to make it work."*

Building a converted save on top of a save the engine wrote means every byte
nobody has decoded silently keeps a value belonging to **a different party in a
different place**. That is not a neutral default -- it is wrong data that looks
right, and it is invisible because the file loads. It is how a converted party
arrived reading 21:15 when its own save said 10:15 (`#58`), and nothing about
the run said so; it took a person looking at the clock.

So **an undecoded field is a blocker, not a gap the template fills**. When the
conversion needs a byte nobody has attributed, the work is to go and measure
it, and the ticket says so. This is a tightening of the standard above rather
than a new rule: "we do not understand the bytes well enough to write them" was
already a defect with a settling experiment, and leaning on a template is what
let that entry sit.

**Zero written because the engine rebuilds the field is not plugged-in data and
does not fall under this.** Six of `WRITE_UNSOURCED`'s seven are live heap
pointers and combat state where the engine itself writes zero, measured both
with items and without. That is a known value with evidence. The distinction
that matters is **measured versus inherited**: a value we established is fine at
any number, and a value we inherited from somebody else's save is not.

**"Reported as dropped" is not a resting state.** Every entry in a drop list
carries the experiment that would remove it, and a drop list that has not
shrunk in months is a list of unfiled bugs.

**Test the empty and the extreme case, not only the typical one.** A drop list
measured survivable for a character carrying items said nothing about a
character carrying none -- and that is exactly where #62 was found, after the
conversion had been declared proven.

**Round-trip byte for byte, and mask by the declared list rather than by the
diff.** Masking by whatever happened to differ makes the test agree with the
code by construction. `tests/test_doswriter.py` masks by `WRITE_UNSOURCED`,
which is the list the writer declares, so a new difference fails.

**A conversion is not proven until it runs.** Bytes matching is necessary and
not sufficient: load it in the game, walk, and look at the sheet. Three separate
faults this project shipped -- an AC of 9 displayed as 51, a dropped combat
tail, and a garbage weapon line -- passed every byte-level check that existed.

## Art

**No AI-generated art, anywhere, ever.** Not icons, not logos, not textures, not
placeholders "until we find a real one". This is Donald's rule and it is not
negotiable by an agent that finds it inconvenient.

**Do not modify somebody else's art either.** An icon lifted from Font Awesome
is drawn the way Fonticons drew it. If it does not work at a size, the answer
is a different icon, or not using it at that size -- never nudging the artist's
geometry until it does. An assistant that moves a path point is making art, and
that is the thing it must not do.

Art comes from a set with a licence we can honour (Font Awesome Free, CC BY
4.0, attributed in the README and the About box) or from a human being.

## What must never enter this repository

This is a reverse-engineering project. It documents a game it does not ship.

**Never commit, in any form:**

* the game's **art, music, or sound** -- sprites, tilesets, portraits, SID
  tunes, sampled audio;
* the game's **manuals, cluebooks, maps or journal entries**, scanned,
  transcribed or retyped;
* the game's **executable code**, whole or in part -- overlays, PRG files, boot
  images, or any extract of them;
* **disassembly of that code** as a listing. Quoting as much of it as a finding
  actually needs -- an address, a handful of instructions, the shape of a
  handler with its operands left as placeholders -- is commentary and is fine.
  A dump of a routine is not.
* the game's **data files** -- maps, tables, scripts, character records -- as
  committed bytes, including as test fixtures.

Disk images are already ignored; keep them under `work/`, which is
`.gitignore`d, and read them at run time from wherever the player keeps theirs.

**Tests get their data from the player's own disks, not from the repository.**
`tests/gamedata.py` is how: `game_file("GEO04")` reads it off whichever `POOL*`
disk carries it and skips when there are none, and `synthetic_geo()` builds a
well-formed map from the format we documented for the cases that only need
*a* file rather than a specific one. A fixture that is a slice of a game file
is the same copy the rule forbids, merely renamed.

`tests/fixtures/` holds the player's own saved games and nothing else. Its
contents are on an allowlist in `tests/test_repository_contents.py`, which
fails the build if anything else appears there or if a disk image, executable,
image or audio file is committed anywhere. **Do not add to that allowlist** --
if a test needs game data, read it from the disks or generate it.

**Citing is not copying.** Quoting the code a finding rests on is exactly what
`docs/50-experiments.md` is for and is encouraged. It does not have to be two
or three instructions: Donald has ruled that a short block is fine, so do not
agonise over the length of a citation that carries evidence. A dump of a
routine is not.

Describe, cite, measure, and generate. Do not copy.

## Issues

**GitHub issues are the work list.** `gh issue list` is the register; `docs/` is
the knowledge base.

**`gh issue list` defaults to `--limit 30`, and says nothing when it truncates.**
Counting the backlog with it answered "30 open" against a real 44, and the
number looked plausible enough not to question. Pass `--limit` above the
backlog size for any count, any sweep, or anything an answer to Donald rests
on. The two are not the same thing and must not drift into
being the same thing: an issue tracks work and closes when the work is done, a
doc records what is known and outlives every issue that cited it.

**Open the description with one sentence restating the subject.** A body that
starts mid-argument reads like the second half of a conversation -- the title is
not the first line of the description, and nobody reads them as one. One
sentence, then the detail.

**Reply, never rewrite.** Progress goes in a comment (`gh issue comment N`).
The description is what the author asked for, and editing it destroys the
record of what was originally wanted. Edit the description only to correct a
factual error in it, and say in a comment that you did.

**Labels.** Exactly one priority on every issue -- `Priority: High`,
`Priority: Medium`, `Priority: Low`.

**Set it when you open the issue**, in the same `gh issue create` -- an issue
filed without one is not "unprioritised pending triage", it is an issue that
falls off the list, and #41 was opened that way. Guess if you have to and say
in the body that you guessed; Donald recurates priorities by hand, and a label
he has to correct costs him less than one he has to notice is missing. Then:

* **`bug`** -- a defect in *our* code, one a user can hit.
* **`enhancement`** -- build this. Plans are enhancements.
* **`question`** -- we do not know something. Nothing gets built when it is
  answered; we simply know. A defect in *the game* is research, not our bug,
  and is usually a `question` or an `enhancement`.
* **`blocked`** -- waiting on Donald specifically: a choice only he can make, a
  machine only he has, a save only he can play to. Work blocked on a
  measurement we could take ourselves is **not** blocked.

**Never undo a label or an edit somebody else made. This one has already gone
wrong.** An agent asked for `enhancement`, Donald had set `question`, the
mismatch was reported as a fault, and the assistant "fixed" it -- destroying his
work. He curates labels and priorities by hand and will keep doing so.

So: **an agent never removes or changes a label it did not itself just add**,
and never re-applies a label that has since been changed. A label that is not
what you expected is Donald's decision until proven otherwise. If it looks
wrong, say so in the reply and leave it alone. The same goes for a title,
a priority, a milestone, or an issue somebody closed.

**`blocked` is the one exception, and only in the one direction.** An agent may
**remove** `blocked` when it has established that the blocker is gone -- and
only then. It may not add it to somebody else's issue, may not change any other
label, and may not remove `blocked` because the work now looks doable or
important.

The reason for the exception is that `blocked` is the one label that is a claim
about the *world* rather than a judgement about the work, so it can be checked
and it can be wrong. #29 sat blocked on Curse and Silver Blades disks that were
on the machine the whole time -- an assistant wrote that they were missing
without looking. A label nobody may correct is a label that outlives the fact
it was recording.

**The bar is evidence, not inference**, and it is the same bar as any finding:
the disks are at this path, the measurement is in this commit, the question was
answered on this issue. "Probably fine now" is not it. **Say what you removed
and why in a comment on the issue**, in the same breath -- an issue whose label
changed with no explanation is exactly the silent edit the rule above exists to
prevent.

**Every issue follows one of three templates.** They are in
`.github/ISSUE_TEMPLATE/` so the forms appear when a human opens one; an agent
writing an issue with `gh` follows the same shape by hand.

**Bug** -- a defect in our code:

```
One sentence saying what goes wrong.

## What breaks
What a user sees, and when. Evidence.

## Root cause
The mechanism. Addresses and code paths belong here, not above.

## What would fix it
Not a patch -- the shape of the fix.

## Testing
What would fail today and pass after.
```

**Enhancement** -- build this:

```
One sentence saying what this builds.

## Why
What is impossible or awkward now.

## What is known
The measurements it rests on, graded CONFIRMED / PROBABLE / UNKNOWN.

## What has to be found out first
The blockers, each with the experiment that would settle it.

## Order of work
Smallest first.
```

**Question** -- we do not know something:

```
One sentence stating the question.

## Why it matters
What changes depending on the answer.

## What we know

## What would settle it
The specific experiment.
```

**"What would fix it", not "Fix".** An issue carrying a patch ages into a stale
patch that no longer applies; an issue carrying the *shape* of the fix stays
true. And every enhancement ends with a `Documentation:` line linking the doc it
rests on -- that link is what joins the work list to the knowledge base now the
P codes are gone.

**A bug you find and decide not to fix gets an issue, in the same session you
found it.** Out of scope is a fine reason not to fix something and not a reason
to leave it unrecorded -- a defect that exists only in a subagent's report is a
defect nobody will ever act on, because nobody re-reads reports. #65 sat in a
sentence of a #59 write-up until it was noticed by hand.

The bar is low on purpose: the issue does not need a diagnosis, only what you
saw, what you were doing, and why you did not chase it. "Not diagnosed" is a
legitimate Root cause section. Grade what you know and say what you would look
at next.

This applies to a bug in **our** code. A defect in the game is research and goes
where the Documentation section says.

**Name an issue when you cite it: `#59 (Map the DOS saved game, not just the
character record)`.** A bare `#59` is an opaque number in a commit message, in
`git blame`, in a terminal and in a reply -- and this project's archaeology
happens in all four. The title is what makes a reference readable a year later
without a browser.

This applies to replies, issue bodies, issue comments and documents. **The one
exception is a commit message**, where the Commits section already rules that
the number goes in parentheses at the end of the one line -- a title there would
break the sentence, and GitHub hotlinks the number anyway.

**Every finding goes in a comment on its issue, when it arrives.** Not at the
end of the work, not only in the reply, not only in `docs/` -- on the issue,
while the agent that found it is still the thing that knows it.

The reason is that a finding recorded nowhere is a finding somebody pays for
twice. A night's work can produce more than a person can read in one sitting;
what survives is what is attached to the thing being worked on. A reply
scrolls away, and a doc records what is *known* rather than what was *learnt
about this ticket*.

**This includes the findings that are not the answer.** A refuted hypothesis, a
measurement that came out unremarkable, a claim you checked and could not
confirm, the thing you could not reach and why -- those are the expensive ones
to rediscover, and they are the ones that get left out.

**And it includes findings that belong to a *different* issue.** File it or
comment on it, then say in your own issue that you did. Work that turns up a
defect in somebody else's area is the commonest way a fact gets lost.

**Comment before you close.** An issue that closes with nothing but a commit
reference makes the next reader open the diff to find out what happened. Say
what was actually done, what it now does instead, and anything that was
deliberately left undone -- a few sentences, in the issue, before or as it
closes. The commit message is one line; the comment is where the explanation
goes.

**`closes #N` fires when the commit reaches `main`, and not before.** While
work sits unpushed the issue is still open, however finished it is -- and this
project routinely carries dozens of unpushed commits, so that gap is the normal
state rather than a corner case.

So: **when the finishing commit is not pushed, close the issue by hand** with
`gh issue close`, and say in the closing note that the keyword will be a no-op
by the time the commit lands. And **never report an issue as closed without
checking `gh issue view N --json state`.** Saying "closed" of an issue that is
open has happened twice here, both times because a `closes #N` was written into
a commit that had gone nowhere. The keyword still belongs in the message; it is
simply not what does the closing today.

**Close an issue in the commit that finishes it**, and say which issue in the
commit message only when it needs saying -- one sentence is still the rule.

## Documentation

**A new file means a new row in that directory's `README.md`.** Every package
directory carries one -- a table of `file` and `purpose`, one line each -- and
`INDEX.md` at the top level says what each directory is for. Add the row in the
same change that adds the file, not afterwards: a table that is only mostly
true is worse than no table, because the gap is invisible.

The line says what the file is *for*, not what it is named. "Character record
layout" is worthless beside a file called `layout.py`; "the 580-byte character
record as a declarative table of fields, each with a confidence grade" earns
its place. If a file is generated, or generates something, the row says so --
that is what a reader needs to know before editing it.

The same goes for a file that moves or is deleted: the row moves or goes with
it.

`docs/50-experiments.md` is the only place that gets length, because the whole
project is the reasoning. Everything else is a lookup table: state the finding,
give the evidence in one clause, link the experiment by name.

Prune when a claim changes. A doc that accretes corrections without deleting the
superseded text is how the contradictions got in.

**Leave the top-level `README.md` alone** unless Donald asks for it by name. It
is the page a stranger reads first and it is his, not a scratchpad the assistant
tidies in passing. A finding goes in `docs/`; if it belongs in the README too,
say so and wait to be asked.

**The open work list is GitHub issues** -- see the Issues section above.
`docs/TASKS.md` and its `P` codes are retired; do not cite a P-code in new
work. A handful survive inside issue bodies as history and can stay there.

**A confirmed bug in the original game goes in `goldbox-bugs.md`** -- but only
if a player can run into it. That file is written for a human who wants to read
something interesting, not for completeness, and it is the shortest document in
the project on purpose.

The test is one question: **what does the player see?** If the honest answer is
"nothing", it is not going in the front-door file. Latent defects, cosmetic
faults, duplicated labels, flags written and never read -- all real, none
interesting -- go in `docs/125-bug-notes.md` instead, numbered `N1` upwards so
the two lists cannot be confused.

Four rules about the front-door file, all learned the hard way:

* **It is for bugs.** Not for unfinished features, not for cut content, not for
  spelling mistakes, and not for the record of our own errors. Those are
  interesting in their own way and they all live in `docs/125-bug-notes.md`.
* **Ours is not theirs.** Most things that looked like a game bug were our own
  misreading -- a wrong stride, an off-by-one dump, an array read half its
  width. They go in the notes file, as ours, never in the list.
* **Log it when it is CONFIRMED** -- reproduced in the running game, or proven
  from the bytecode beyond argument. A suspicion stays in
  `docs/50-experiments.md` until it earns promotion.
* **Describe the defect, not the bypass.** Copy-protection *research* stays in
  the separate private repository, but a protection routine that computes the
  wrong answer is a bug like any other and is logged. Say what the code does
  wrong and what a player sees; do not publish the tables, the arithmetic or
  anything else that amounts to defeating the protection.

**Name the consequence, not the mechanism.** A title and a summary line say
what goes wrong for the player; the mechanism is what the entry is *for*.
"Sokol Keep's dead elf comes back every time you return" is the bug. "The dead
elf is guarded on an address nothing writes" is the cause, and it means nothing
to somebody who has not read the entry yet. Call things by their ordinary
names, too: it is copy protection and a code wheel, not a verification check.

Each entry says what the game does, what it should do, the evidence, and what
the player sees. Keep the addresses to what carries the evidence -- the entry
has to make sense to somebody who has never read a disassembly.

**Two things every bug entry needs and most bug reports never have.**

**How a player ends up there.** Not the trigger in memory -- the situation. "You
save on the road within sight of a place you have not found yet, and reload"
is how somebody arrives at bug 10; "the paint runs on entry and not on load" is
why it happens. Both belong in the entry and they are not the same sentence.
Write the first one even when it is unflattering: **"no player can reach this"
is an answer**, and it is the answer that moves an entry out of
`goldbox-bugs.md` and into `125-bug-notes.md`. N18 is there for exactly that
reason.

**The steps, in the game's own terms.** A numbered path a person can follow with
a joystick, naming the menus and the commands the game shows -- `VIEW`, `ITEMS`,
`QUICK` -- and no addresses at all. If the only route is editing the files out
from under the engine, **say so in those words**, because that is the sentence
that tells the next reader it is not a bug a player hits.

The discipline is worth the lines because the failure it prevents is a real
one: an entry that is all mechanism reads as authoritative and cannot be
checked, argued with, or reproduced by the person most likely to care.

## Feature flags

**A major new feature ships behind a flag until it is proven stable, and a
feature with open bugs is not stable.** The DOS import is the first: it works,
it is proven in the emulator, and it still drops the portrait and the clock --
so `File > Import` is not built unless the flag says to build it.

**The name is always `WISH_EXPERIMENTAL_<FEATURE>`.** The prefix is doing work:
it separates a flag that exists to be *deleted* from `WISH_DEBUG` and
`WISH_NATIVE_LOG`, which are diagnostic switches and are permanent. Somebody
reading an environment variable should be able to tell those apart without
opening the file.

**Every flag names the condition that removes it, beside its definition.**
"Comes off when #57 and #58 close" is a condition; "when it is ready" is not.
A flag with no stated way out becomes a second code path maintained forever,
and the second path is the one nobody runs.

**Do not build the thing rather than disabling it.** A greyed-out menu item
invites the question of how to un-grey it, and the answer would be a sentence
in the interface -- which is the thing the GUI section below spends its length
preventing. `wish/window.py` builds the Import submenu inside the `if`.

**An environment variable, not a preference.** A checkbox needs a label, and a
label saying "experimental" needs a sentence saying what that means for the
user's save disk. That is Donald's wording to write and it is not worth
writing for something due to be deleted.

**One truthiness rule, shared: `1`, `true`, `yes`, `on`.** Anything else --
including an empty string, `0` and `off` -- is off. `wish/debugmode.py` has it
first; copy that tuple rather than inventing another. A variable somebody
exported once and forgot must not put an unfinished feature in front of them.

**Test both directions, and prove each test fails without the gate.** One test that the feature
is absent by default, one that a forgotten `0` or `off` does not turn it on,
one that it appears when asked for. Force the flag on and watch the first two
fail; a gate that cannot fail is not a gate.

## Help text in the GUI

**Every word a user reads in the interface is Donald's to approve.** Labels,
button text, tooltips, status messages, empty-state lines, dialog prose --
propose the wording, do not ship it. He has final say on how it is worded before
it goes in.

This exists because the interface kept growing sentences that explained itself.
An info icon whose tooltip ran four sentences, a footnote about a board slot no
player can reach, a line under the backup folder saying what an empty box means,
a note about how many backups are kept -- each looked reasonable alone, and
together they made a program that apologises for itself. Every one of them was
removed on request.

When in doubt, leave it out and say so in the reply. Removing a sentence is
cheap; a user reading a paragraph that should never have existed is not.

**"It matches the wording already there" is not approval, and it is the excuse
that got three strings shipped.** In 2026-08 an agent added one line to the
export report and two to Preferences, each closely modelled on a sibling
sentence in the same function, and that similarity is why nobody stopped to
ask. Donald's verdict on all three was *"they won't be understood by humans"* --
`#96`. The existing sentences read well **to somebody who already knows the
machinery**, which is everybody who has ever reviewed them and nobody who is
using the program.

**Look at the string in the running window before proposing it, not in the
source.** The export line reads `the file name 'LADYKATH.pc' is already used by
another character in this export; written instead as 'LADYKAT2.pc'` in the
code, and in the pane it is prefixed with the file it concerns -- so the same
filename appears twice in one sentence and half of it is repeating the prefix.
That was invisible in the diff and obvious in a screenshot. `QWidget.grab()`
under `offscreen` costs nothing; `work/reports/issue-96/` is the pattern.

## Code comments

Comment the *why*, and only when it is not obvious. A field note that carries
evidence — "10 for every player character; monsters carry their real AC here" —
earns its lines. Restating the code does not.

`goldbox/layout.py` is the exception: its notes are the field documentation and are
generated into `docs/20-character-record.md`. They can be long. Run
`python3 tools/gendocs.py` after touching them.

## Ending a session, and starting the next one

**The session is not the knowledge base and must never become it.** A fact
that exists only in a conversation is a fact somebody pays for twice, and
conversations end -- on a spend limit, on a `/clear`, on a context window.
Everything above about putting findings on issues when they arrive is what
makes a session disposable, which is the point.

**Long sessions accumulate stale facts, and that is a cost nobody counts.**
Twice in one night the assistant answered from something that had been true
earlier and was not any more: the Amiga disks were reported missing because an
old search had been too narrow, and #71 was reported closed off a local
measurement CI then contradicted. A fresh session reading the issue would have
got both right. Length is not context; it is also drift.

**Before clearing, say what is not written down yet.** Go through what the
session established and check each fact has a home: a comment on its issue, a
line in `docs/`, a row in a README. Name anything that does not, and write it
down before the session ends. Calibrations are the ones that get lost -- "+6pt
here measures like Windows' base font" is worth more than the fix it enabled,
and lived nowhere but a conversation until it was put on #71.

**A fresh session reads, in this order:** `CLAUDE.md`, `INDEX.md`, then
`gh issue list`. For any issue it is about to work, `gh issue view N --comments`
-- because the description is never rewritten here, so every correction lives
in the comments.

**The test of whether a session was recorded properly** is whether the next one
can answer "what should we work on" from the repository alone. If it cannot,
the gap is the thing to fix, and it is a documentation bug rather than a reason
to keep a session alive.

## Words to avoid

Plain words, and the ones a person would actually say. These four turn up
constantly in assistant prose and almost never in human speech:

| instead of | say |
|---|---|
| **load-bearing** | what holds it up, what depends on it, what breaks without it |
| **fair** ("that's fair") | agree or disagree in words: "you're right", "I don't think so, because" |
| **blast radius** | what else this touches, what it would break |
| **elide** | truncate, shorten, cut off with an ellipsis |
| **obviate** | say what actually happened: it cannot happen any more, the fix is no longer needed, that removes the reason for it |
| **retarget** | move the party to where it actually was, point the save at the right map |
| **"X follows Y"** | say what happens: "gets taller as Y grows", "is recomputed whenever Y changes" |
| **"the test bites"** | the test fails without the fix; it catches the bug; it goes red when the guard is removed |
| **a file "walks", "arrives", "stands"** | name who does it: *the party* walks, *the player* sees it, *the game* loads the save without crashing |

**Do not give a file the verb that belongs to the people in it.** "All three
saves walk" was written here and Donald could not read it: *"I don't know what
a save walking means."* He is right -- a save cannot walk, a **party** walks.
The shorthand collapses the actor, and the actor is the whole content of the
sentence: "the party in each of the three converted saves could be made to
move" says what was proven, where "the saves walk" could equally mean the file
loaded, the game did not crash, or somebody took a step.

**The sense that is fine is the one with no person in it** -- walking a range,
a loop or a structure. `docs/118-debug-mode.md`'s "walks `$9800` from 10 to 18"
is exactly right and should stay. The test is whether a person or a party is
the thing really doing it; if so, name them.

**"Follows" is the worst of these for a reader who was not there**, and it went
into two issue titles before Donald said so: *"I see this a lot, where you say
'X follows Y'. It doesn't make sense to me, and it results in me not
understanding what's going on."* It is doing the work of at least three
different sentences -- grows with, is derived from, is recomputed after -- and
the reader cannot tell which. Say the one you mean. "The window's minimum height
follows the UI font" is "the window gets taller as the UI font grows, so a large
font stops it fitting the screen", and the second version is the one somebody
can act on.

The list is examples of a habit rather than a blocklist to be satisfied.
The habit is reaching for a piece of jargon that sounds precise and carries
less than the plain phrase it replaced -- and "that's fair" is the worst of
them, because it agrees with nothing in particular and ends a conversation
that had somewhere to go.

**Code is the exception, and only where the API names it.** Qt's own methods
are `setTextElideMode` and `ElideRight`, so `elide` in `editor/rosterview.py`
is the framework's word and changing it would make the code harder to search,
not easier to read. Use the API's spelling in code and identifiers; use the
plain word when explaining it to a person.

## Replies

Lead with the answer. Findings before method. Tables over prose for anything
with more than three data points. No closing summary of a reply the user just
read.

Report failures with the shortest decisive line of output, not the whole log.

**Name every issue you cite, here as much as anywhere** -- `#59 (Map the DOS
saved game, not just the character record)`, never a bare `#59`. The rule is in
the Issues section and it says it applies to replies, but it is three hundred
lines away from here and that is exactly why it gets broken: a reply is written
fast, the number is what the assistant has in hand, and the title feels like
padding. It is not padding. Donald reads these replies without the browser
open, and a bare number carries nothing at all to him: *"when you only
reference a number, it never means anything to me."*

**This includes tables**, which is where it is dropped most often -- a column
of bare numbers is the least readable thing in a reply, not the most. Put the
title in the row.

**Every mention, not the first one.** The next failure after the tables was
putting titles in the table and then writing bare numbers in the prose around
it -- "#102 is solved", "#59's inherit list", "#50's proof now passes". A
number used as the subject of a sentence is the *least* readable place for it,
because that is where the reader most needs to know what is being talked
about. There is no "already introduced it above" exemption; a reply is skimmed,
not read in order.
