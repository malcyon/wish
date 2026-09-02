# Working notes for Claude

## Name every issue you cite

`#59 (Map the DOS saved game, not just the character record)`, never a bare
`#59`. Every mention, in replies, issue bodies, comments, documents and
tables -- there is no "already introduced it above" exemption.

This is first in the file because it is the rule most often broken and the one
that costs Donald the most. **The reason is that a bare number makes him do
the lookup.** It is fast for the assistant, which has the number in hand, and
slow for him, who has to go and find out what it is before the sentence means
anything: *"when you only reference a number, it never means anything to me."*
It is not about whether he has a browser open -- this file used to say that,
and Donald corrected it on 2026-09-02: *"It should not matter if I have a web
browser open or not. You're forcing me to manually look up every number. That
is fast for you, but slow for me."* It was stated twice, in the Issues
section and again in Replies three hundred lines later, and went on being
broken anyway -- five times in one session on 2026-08-31, in the middle of
work that was otherwise going well. A reply is written fast, the number is
what the assistant has in hand, and the title feels like padding. It is not
padding; it is the whole content of the reference.

The number used as the subject of a sentence is the **worst** place for it,
because that is where the reader most needs to know what is being talked
about. "#102 is solved" and "the resizable columns with #135" are the shape
that keeps recurring.

```sh
gh issue view N --json number,title -q '"#\(.number) (\(.title))"'
```

`.claude/hooks/check-issue-titles.py` refuses a reply that breaks this, so it
is no longer a matter of remembering. It is a `Stop` hook, so it only sees a
turn once the turn has ended: prose written mid-turn, with tool calls still to
come, reaches Donald before anything checks it. `check-gh-issue-titles.py`
covers the other half, `gh issue comment` and `gh api .../issues/comments`,
which the `Stop` hook never sees at all.

**A mid-turn `PreToolUse` guard was tried on 2026-09-02 and withdrawn the same
hour. Do not rebuild it without solving this first.** It refused the next tool
call whenever the turn's prose so far carried a bare number, which worked in
the main window and **disabled subagents completely**: a subagent's
`transcript_path` is the shared one, so it was refused for citations the main
window had written, could not edit them, and had no way to clear the block --
`gh issue view`, the remedy the message recommends, is itself a `Bash` call it
refused. One agent lost its whole task that way and reported that even `echo
ok` was refused.

The lesson is the general one rather than the specific: **a guard that blocks
tool use has to be clearable by whoever it blocks.** This one was not, and its
failure mode -- no agent can do anything -- was worse than the fault it caught,
which is a sentence Donald has to read twice. **The one exception is a commit
message**, where the Commits section rules the number goes bare in
parentheses at the end of the one line -- a title there would break the
sentence, and GitHub hotlinks it anyway. The hook knows about that exception
and about code blocks; it does not know about anything else, so a false
positive is a bug in the hook and not a reason to work around it.

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

**The `reverse-engineering` subagent runs on Opus and costs no more than a
general-purpose one, so use it for what its definition describes.** This file
said the opposite until 2026-09-01 -- that it ran on Fable, that it had
exhausted a monthly spend limit in one night on 2026-08-26, and that Donald had
to be asked before it was launched. All of that was true when it was written and
none of it is true now: `.claude/agents/reverse-engineering.md` carries
`model: opus`. Donald: *"I think the reverse engineering agent used to use fable
as the model, but it has since been changed to Opus. Using the
reverse-engineering agent is fine and no more expensive than a general purpose
agent."*

**The two agents that still run on Fable are `architect` and `deep-research`,**
and the caution that used to sit here belongs to them. `deep-research` is for
the hardest problems by its own description; `architect` writes a plan for
somebody else to execute. Neither is the default for anything, and an overnight
run should think before spending on either.

**Reverse-engineering work goes to a general-purpose agent, and most of it
turns out to be ordinary work.** Diffing two files against a layout we already
have, flipping a byte and reloading, driving DOSBox or WinUAE through a
documented recipe, walking a save with a hex editor -- all of that is
general-purpose work, and it is how the DOS saved game's inherit list went
from 8016 bytes to 444 and how the Amiga Pool of Radiance record was read.

**The escape hatch, and use it rather than pressing on:** if a general-purpose
agent finds the task genuinely needs a disassembly -- reading 68000 or 6502
code rather than watching an address or diffing a file -- it should stop and
say so, and the work is re-routed to `reverse-engineering`, whose definition
already describes it. That is a signal, not a failure. Stopping is cheap; an
agent grinding at a disassembly it was not sent to read is not.

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
shells out to `ssh` or `scp`.

**`winvm` now sets both itself and does not need wrapping** -- checked against
`/usr/local/bin/winvm` on 2026-09-01: it exports `SSH_ASKPASS_REQUIRE=never`,
and its one `SSH_OPTS` array carries `-o BatchMode=yes` and is passed by the
`ssh` and `scp` subcommands alike. This file said the opposite until then,
which was true when it was written -- `wait_ssh` had `BatchMode` and the `ssh`
subcommand did not, and `winvm`'s own comment records the fix. The rule above
still holds for every `ssh` an agent writes itself.

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

To test whether a change matters, **copy the file aside and copy it back**,
`diff` to confirm the restore, **and then delete `__pycache__`**. A file put
back at the same size in the same second does not look changed to CPython's
bytecode cache, so the program goes on running the broken code while
`inspect.getsource` shows the right source -- a test stayed red for twenty
minutes against a correct file that way on 2026-08-27. Only the main window
touches git's history, and only deliberately.

**A copy-back is a `git checkout` with a different name, and it is only safe on
a file nobody else is in.** The rule above says copy aside and copy back, and it
is right for the ordinary case -- but the copy is a snapshot of the file at the
moment it was taken, so putting it back deletes every edit anybody made in
between. On 2026-09-02 the main window did exactly that: it had given
`goldbox/dos.py` to an agent working `#191 (A converted dwarf loses his
constitution bonus to saving throws)`, then edited the same file itself for
`#176 (A player importing a Curse of the Azure Bonds save is shown an issue
number)`, and its copy-back restore silently reverted the agent's one-line fix
after that agent had already seen the whole suite green on it. Nothing failed
loudly; the line simply went back to what it had been.

So, in order: **do not edit a file you have assigned to an agent** -- that is
the mistake, and the copy-back was only how it landed. If you must touch one,
say so in a message to the agent, and **prefer a targeted edit to a copy-back**:
put back the one hunk you changed rather than the whole file you remember. Take
the copy immediately before the change you are testing, never at the start of a
run, and `diff` against the *live* file rather than against your memory of it.

**And commit a shared file by staging the version you mean, not the file.**
Where a file holds your change and somebody else's half-finished one, build the
version you intend to commit in the scratchpad, `git hash-object -w` it and
`git update-index --cacheinfo` it into the index. That is how `#176`'s hunk went
in while the `#191` work beside it stayed uncommitted and untouched in the
working tree.

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
| `reverse-engineering` | Opus | byte layouts, checksums, encodings, and the parsers that prove they were read right -- including a disassembly read. No dearer than general-purpose; no permission needed |
| `deep-research` | **Fable** | the hardest reverse engineering only, where rigorous analysis is the whole job. The expensive one; think before spending on it |
| `architect` | **Fable** | a plan for another agent to execute, when the shape of the work is the hard part. Writes the plan, does not build it. Also Fable |
| `junior-dev` | Sonnet | the issue's "What would fix it" names the **mechanism**: a port, a deduplication, narrowing a check. Never anything with a design decision left in it. Called `quick-fix` in this table until 2026-09-01; the agent was renamed and the row was not |
| `general-purpose` | inherits | everything else, including work that looks like reverse engineering and is not |
| `code-reviewer` | Sonnet | after **every** subagent that wrote code, on the local commit, before it is pushed. It runs in the shared tree, so scope it to the files it owns |
| `docs-reviewer` | Sonnet | when documentation may have drifted from the code -- after a run of findings lands. It runs in the shared tree, so scope it to the files it owns |
| `backlog-auditor` | Sonnet | before a refinement pass, or when the backlog has grown unwieldy. **It owns the issues**: the banned-words sweep of titles, bodies and comments, and the fixing of them, are its work and not a `general-purpose` agent's |
| `changelog-writer` | Sonnet | after a batch of work lands, and before cutting a release |

**`junior-dev`'s filter is a property of the issue body** -- does it name the
mechanism, or only the goal? #71 looked like ordinary work and took nine
rounds and a `QTableView` subclass. #73 named the two candidate shapes and
said which was smaller, and that is what made it assignable.

**Send work to the agent whose definition already describes it.** Each
`.claude/agents/*.md` says what its agent is for, and that sentence is the
routing rule -- `backlog-auditor` names the "Words to avoid" sweep in its own
description, and `changelog-writer` names keeping `CHANGELOG.md` current. On
2026-08-26 both were reached past: a `general-purpose` agent was sent to fix
banned words in issues, and a second one to work out which fixed bugs a
`v0.1.0` user could have hit -- a question `changelog-writer` needed answered
*before* it wrote the entries and should have been asked in its own brief.

The cost is not only the model. A specialist has read its own domain's rules;
a general-purpose agent has to be told them in the brief, and whatever the
brief forgets is what goes wrong. **Before writing a brief, read the
definitions and ask which one already owns this.**

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

**A `+N` offset is not the same size on two machines, and stacking it on a
platform's own base is how three pushes went red.** `+6` measures here about
like Windows' base font -- so on a Windows runner, whose base already *is*
that font, `+6` is Windows' base **plus six more**. An assertion at `+6` on CI
is an assertion about a size no Windows user has.

So: **assert a width at `+0` only.** That is whatever the machine running the
test actually starts from, and it is the one offset that means the same thing
everywhere. Assert a *height* across the range, because the height promise is
platform-independent in a way the width one is not -- a taller font makes
every machine's rows taller by the same proportion, while how wide a button
gets for the same text is the platform's business.

**The largest font worth testing is +10, and 9pt is the base here.** So the
range is 9pt to 19pt, and `+6` is the one that matters most because
`CLAUDE.md` records it measuring about like Windows' base font.

Donald, 2026-09-01, after a test was found asserting things at +12, +16 and
+20 -- 21, 25 and 29 point: *"I don't think we should ever have unit tests
that force us to make a 25 point font work. I think that's an extremely
contrived situation that wastes our time."* And: *"This whole 25 point font
with a tiny resolution just feels extremely contrived and a waste of our
time."*

He is right, and the measurements agree with him: at +10 the window's floor is
553px against a 720-high screen. **There is no layout problem at any font a
person uses.** Somebody who needs text that large uses display scaling, which
enlarges the window too and never produces the squeeze.

A test that only holds above +10 is not proving a guarantee, it is proving an
artefact -- and it will be true forever while catching nothing. If a claim is
weak at a realistic font, **say it differently rather than at a bigger font**:
`test_the_top_row_asks_for_more_than_the_page_makes_room_for` was false at +0
and passed only because it was never asked, and became true everywhere once it
compared a *rate* across two fonts instead of a gap at one.

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

**A timing measured on this machine is not a timing.** The rule above is
about numbers; this is the same trap wearing a stopwatch, and it is worse
because the test passes locally every time.

`test_a_directory_being_written_to_is_not_called_quiet` ran a background thread
writing every 20 ms while `settle_files` waited for a 200 ms quiet window. It
passed here and went red on CI within the hour: on a loaded runner the thread
was not scheduled inside that window, so `settle_files` correctly saw nothing
change and answered "quiet". **The test was measuring the runner.**

**A concurrency test whose failure mode is "the other thread did not get a
turn" will find that out on somebody else's hardware.** The fix is the same
shape as for a measured constant -- drive the thing from what it actually
does, rather than racing it. `settle_files` sleeps between reads, so every
sleep now stamps the file forward with `os.utime`: that is what a save in
flight looks like from outside, it cannot be starved out, and counted stamps
mean no filesystem's mtime granularity can make two writes look like one.

Prefer, in order: no thread at all; a thread the code under test drives; a
real thread with a margin you have argued for out loud. Never a sleep chosen
because it worked once.

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
does not fall under this.** Most of `WRITE_UNSOURCED` is live heap pointers
and combat state where the engine itself writes zero, measured both with
items and without. That is a known value with evidence. The distinction
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
code by construction. `tests/test_doswriter.py` masks by `WRITE_UNSOURCED`
and `WRITE_DEFAULTS`, which are the lists the writer declares, so a new
difference fails.

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

So: **an agent never changes a label silently, and never on a judgement.**
A label that is not what you expected is Donald's decision until proven
otherwise.

**It may change one when it can state the evidence in a comment on the issue
in the same breath**, saying what it changed and why. The bar is a fact about
the world rather than an opinion about the work:

* *"The body says nothing is observed and nobody can name what a player sees,
  so it is a question rather than a bug"* -- a fact, checkable by reading the
  issue. Change it and say so.
* *"This feels more important now"*, *"this looks doable"* -- a judgement.
  Leave it alone and say so in the reply.

**The thing that must never happen is a change with no comment**, because
that is what destroyed his curation with no record anybody could read or
reverse.

**And the rule cuts the other way too, which cost a night.** `#69 (No
WRITE_UNSOURCED zero has been tested during combat)` carried `bug` for months
while its own body said *"Nothing observed. This is a gap in the evidence
rather than a seen fault."* On 2026-09-01 an assistant worked a whole bug
queue around it, put it in every list it gave Donald, and never asked whether
the label was right -- the label was doing its thinking. Donald caught it:
*"You were unable to explain convincingly how it would affect an end user."*

A mislabelled issue is an **invisible** error. It fails no test, turns no CI
red, and produces no symptom except work quietly going to the wrong place for
as long as nobody looks. So the question `CLAUDE.md` already asks of a bug --
**what does the player see?** -- is worth asking of the label as well as of
the work, and "nothing, we do not know yet" means `question`. The same goes for a title,
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
happens in all four. The title is what saves the reader a lookup, now and a
year later.

This applies to **replies, issue comments and documents** -- everywhere a
person reads the reference somewhere GitHub is not rendering it.

**Two exceptions, and both are about where the reader is.**

* **A commit message**, where the Commits section already rules the number goes
  in parentheses at the end of the one line -- a title there would break the
  sentence, and GitHub hotlinks the number anyway.
* **The body of an issue.** Donald, 2026-09-01: *"Leave them alone.
  GitHub.com shows the ticket details on hover and makes it a hotlink, so it
  will be fine."* An issue body is read on the web, where the number **is** the
  title to anybody with a pointer.

**So do not go back and add titles to bare numbers in existing issue bodies**,
and do not treat one as a defect in an audit. It is not a factual error, so
"Reply, never rewrite" governs and the answer is to leave it.

**The rule still binds hardest in a terminal**, which is where it keeps being
broken and where the cost is real: a bare number there is a lookup Donald has
to go and do -- *"when you only reference a number, it never means anything to
me."* That is also why an issue *body* is exempt and this is not: on the web
the hover does the lookup for him, and in a terminal nothing does. Write new
citations with their titles everywhere; simply do not rewrite old bodies to
match.

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

**A write-up's permanent home is `docs/`, never `work/`.** `work/` is for the
game's own bytes and anything derived byte-for-byte from them -- disk images,
raw disassembly listings, saved-game specimens -- and it is gitignored on
purpose, because none of that may be committed. The *reasoning* about those
bytes is not itself game data: quoting the handful of instructions a finding
rests on is explicitly permitted, so a write-up that argues from evidence to a
conclusion belongs in `docs/`, cited by a path that survives. **And a tool that
regenerates an artefact belongs in `tools/`** -- losing `ecl6.py`, which decoded
all thirty ECL scripts to 100% of every byte, cost more than losing any single
report, and no rule about write-ups would have saved it.

If a working file under `work/` would take more than a session to reproduce,
that is the signal to write its findings into a `docs/` page -- under
`docs/50-experiments.md`'s reasoning, or promoted to its own numbered doc --
**before** the working file is deleted, not after.

`work/reports/` held 32 such write-ups and all 32 are gone; nothing recovered
them, and 80 citations across 29 documents had to be rewritten to say so (#136).
`tests/test_repository_contents.py` fails the build on a new one: a `work/`
path in `docs/` or in a package is either a file that exists, or is marked in
its own text as lost.

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

**A wrong document gets corrected, not escalated.** Donald, 2026-09-01:
*"If you find something wrong in a document, you can just update the document.
You don't need to block on me. Use your best judgement."*

So a factual error found in `docs/` is fixed in the same session it is found,
by whoever finds it. Do not open an issue for it, do not ask, and do not leave
it for somebody else -- a correction nobody made is a claim the next reader
believes.

Two things a correction owes:

* **Delete the superseded text rather than layering on it.** A page that
  accretes corrections is how the contradictions got in, and pruning is
  already the rule above.
* **Say why it changed**, in a sentence, where the claim was. `#75` was a
  paragraph and cost somebody a session; a correction with no reason is the
  same trap with the values swapped.

And if the wrong claim held up a *conclusion* rather than a detail, say so
plainly rather than quietly fixing the line -- that is a different size of
thing and the reader has to be able to see it.

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

**Everything a person reads starts with a capital letter.** Donald,
2026-08-31, first of the Messages panel -- *"I want us to start making sure we
capitalize the phrases that are going into the Messages panel. It looks more
professional."* -- and then of everything: *"There should be a rule that text
we send to the user always has the first letter capitalized. This has been a
recurring problem in all AI text."*

He is right that it is a habit rather than an oversight. Assistant-written
strings start lowercase far more often than human-written ones, because they
are written as fragments -- `no party to read`, `waiting for the game` -- and
nobody looks at the finished line.

It covers **every line presented to a person**: the Messages panel, the status
bar, a dialog, a tooltip, a label, an empty-state line, the debug log, what the
CLI prints, and the assistant's own replies in the terminal. If a person reads
it, it opens with a capital.

**Capitalise the composed line, not the strings that go into it.** The first
word is usually the caller's -- `_report("fast travel", outcome)`, and
`action.label.lower()` on the action bar -- so upper-casing each message
constant leaves the prefix lowercase and changes nothing a user sees. Do it at
the point the final line is assembled: `FastTravelBar._report` and
`ActionBar._report` each do it in one place, and
`test_a_messages_panel_line_opens_with_a_capital` pins it.

**Only the first letter, never `str.capitalize()`**, which lower-cases the rest
-- it would turn the combat log's `MAGNUS MISSES.` into `Magnus misses.` and
mangle `$6E11`. `line[:1].upper() + line[1:]` is the whole of it, and it is
already correct for a line that starts with a proper noun, an address or the
game's own shouted text.

**A fragment stays a fragment.** A string that is only ever pasted into the
middle of a sentence is not a line a person reads, and capitalising it mid-line
is worse than leaving it. The test is where the string ends up, not what it
looks like in the source -- which is another reason to look at the running
window rather than the diff.

**No memory address, register or file offset in front of a player.** Donald,
2026-08-31, of a tooltip reading `$4AC1, bumped by the clerk for the ten
commissions that count as major`: *"we shouldn't be presenting memory addresses
to players."*

It is an easy fault to introduce here, because the address **is** the evidence
and this whole project is written in addresses. In a docstring, a code comment,
a `docs/` page or an issue, cite it -- that is what makes a finding checkable.
In a tooltip, a label, a panel column or a message, it is a developer's note
that escaped.

The same goes for anything else only a developer knows: a script filename like
`ECL08`, a record offset like `0x0A1`, a raw flag byte. `also needs $4A97
(Cadorna's chambers) unpaid` becomes `also needs Cadorna's chambers unpaid`,
and nothing is lost -- the address stays in `goldbox/commissions.py`, which is
where somebody reading the code looks for it.

`test_no_quest_log_tooltip_shows_a_memory_address` pins it for that panel.

**The debug log is the exception**, and `WISH_DEBUG` output generally: it is
read by whoever is debugging, and an address there is the point.

**Never open a sentence with a quotation that starts lowercase.** This is how
the rule gets broken by somebody who is following it: quoting a lowercase
string is correct, and starting a sentence with that quote makes the sentence
lowercase anyway. Donald caught it in the reply that cited the rule --
*"why isn't the sentence capitalized?"* -- where a table cell began
`counts towards commissions completed names a label the window no longer
shows`. Put words in front of the quotation: *The line reads `counts towards
commissions completed`, and it names a label the window no longer shows.*

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

## Qt Designer

**Every widget layout that a human might rearrange must come from a `.ui`
file.** New windows, dialogs, panels and forms are designed in Qt Designer and
compiled with `tools/genui.py`. The Python code wires signals, sets models, and
does anything dynamic; it does not call `addWidget`, `setLayout`, or build a
form in code. `tools/genui.py --check` catches drift in CI.

**The only exceptions are custom-painted widgets** -- the map and combat
canvases, the HP/XP bars -- that have no layout to rearrange. Their
*containers and placement* still belong in the `.ui` that holds them, as
promoted widgets.

**The pattern is `editor/character.ui`**, which the character editor has used
from the start. Widgets are found by `objectName` and matched to the code that
drives them, so the form can be rearranged in Designer without a line of Python
changing.

**`tools/genui.py` compiles every `.ui` in the project.** It discovers pairs
automatically -- `<dir>/<name>.ui` becomes `<dir>/ui_<name>.py` -- and
`ensure_current()` at startup regenerates anything stale. `--check` is what CI
runs. A `.ui` added in a new directory needs a row in `genui.py`'s `UI_DIRS`.

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

**The rule survived the sentence it was written about and was broken again on
2026-08-27**, in a reply announcing that the DOS import no longer needs a
template: *"The template is gone, and it played."* Donald: *"I don't know what
'it played' means. A template cannot play a video game. It is a template, it
can't action anything on its own."* Two faults in five words -- a thing was
given a person's verb, and `it` pointed at the noun nearest to hand rather than
the one meant. What was true is that **a party** converted onto a disk Wish
built could be played in the emulator, and that sentence has a person in it and
cannot be misread. Announcing a result is exactly where this slips, because the
result feels like the subject; it is not.

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

**`embrassed-energy` is spelled "embraced" in prose.** game-icons.net's own
filename carries the typo, and Donald ruled on 2026-09-01: *"I think
'embrassed' is a typo from game-icons.net. Let's refer to it as 'embraced'
unless we are referring to the url."*

**Only the URL slug carries the typo.** The icon's page on game-icons.net is
titled *Embraced energy*; it is the filename that misspells it. So:

* the **identifier and the archive filename** keep `embrassed-energy`, because
  the committed path data is diffed against that file;
* the **URL** keeps it, because that is the address that resolves;
* **the licence credit says "Embraced Energy"**, because attribution names a
  work as its author titled it -- and Lorc titled it that. `wish/licenses.py`'s
  `TITLES` is the one-entry override that does it.

Getting that last one backwards is easy and I did: I reasoned that a credit
should keep the author's spelling, which is right, and then used the filename
as the author's spelling, which is wrong. Donald: *"It's called 'Embraced
energy icon'. It says so on the game-icons.net website."*

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

**Explain a bug by the situation a person is in when they hit it, before any
of the mechanism.** Not "`_flush` swallows a `ValueError` from
`encode_record_name`" -- *"you rename a character to `Bel'ana`, the apostrophe
is a curly one because you copied it off a web page, you click Save, it says
'no changes', and the box still shows the name you typed."* Then the cause.

The mechanism is what the explanation is *for*; it is not the explanation. A
reader who has not seen the code cannot tell from a description of the code
whether the bug matters, how often it happens, or whether they have ever hit
it themselves -- and those are the questions that decide what to do about it.

**Write the situation even when it is unflattering to the bug.** "No user can
reach this" is an answer, and it is the answer that moves something down the
list. If the honest scenario is "only if you edit the files out from under the
program", say that in those words.

This is the same discipline `goldbox-bugs.md` demands of an entry about the
game -- "How a player ends up there" -- and it applies to our own defects, in
replies, in issue bodies and in comments. It was written down after Donald
read an explanation of a rename bug and answered: *"I don't understand. In
what situation would a user be in when they run into this?"*

**Name every issue you cite, here as much as anywhere** -- `#59 (Map the DOS
saved game, not just the character record)`, never a bare `#59`. The rule is in
the Issues section and it says it applies to replies, but it is three hundred
lines away from here and that is exactly why it gets broken: a reply is written
fast, the number is what the assistant has in hand, and the title feels like
padding. It is not padding. Leaving it out moves the work from the writer to
the reader: *"You're forcing me to manually look up every number. That is fast
for you, but slow for me."*

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

## Temp Files

Any temporary or scratch file created during development goes in `work/`, to
keep the project root clean. **`work/` is for a run's output, not for the thing
that produced it.** Logs, `.jsonl` traces, dumps, screenshots, disk images: all
of those, and they are gitignored because most of them are derived from the
game's own bytes.

**A tool goes in `tools/`, committed, with a row in `tools/README.md`.** Donald,
2026-09-01: *"If you develop tools, put them into tools/, not work/. That way,
you don't have to rebuild them."*

A runner, a probe, a sweep, a one-off script that drove an emulator and
answered a question -- every one of those is a tool, however throwaway it felt
while being written. The test is not whether it looks finished; it is whether
somebody would otherwise write it again.

The cost has already been paid: `ecl6.py` decoded all thirty ECL scripts to
100% of every byte and was lost.

And a file under `work/` cannot be *found* either, which is the cheaper half of
the same problem. `work/issue127/proto.py` holds the breadth-first
`step_towards` that walks round rock and round the party's own formation,
written for `#127 (A driven character stands next to an enemy and passes its
turn instead of attacking)`. On 2026-09-01 the main window reported it lost --
wrongly, off its own `ls | head` truncating the listing before the `.py` files
-- and wrote that into this file and into
`#170 (A driven character walks into rock, because step_towards never reads
the terrain)` before a subagent that had actually opened the directory
corrected it. A tool in `tools/` has a row in `tools/README.md` saying what it
is for; a tool in `work/` is one entry among the logs and dumps of the run that
produced it, and nothing anywhere says it exists.

## Pre-commit Checklist
Before committing and pushing any changes, you MUST always run the following checks locally to ensure CI will pass:
1. `pytest` (to ensure all tests pass)
2. `.venv/bin/ruff check .` (to ensure there are no unused imports or linting errors)
3. `.venv/bin/python3 tools/genui.py --check` (to ensure all `.ui` files are compiled and up to date)

**Run the whole suite, not the files you touched.** A scoped run is for working;
it is not the check. `pytest tests/test_combatdrive.py` was green and `main`
went red on all four jobs eight minutes later.

**`git add X && git commit` commits the whole index, not just `X`.** Several
agents share this tree and they stage files; a commit made after naming your
own paths sweeps in whatever anybody else had staged. That is how
`tools/livestrip.py` reached `main` on 2026-09-01 inside a commit about
something else -- and, because its `tools/README.md` row was still uncommitted,
it landed as a file the table does not describe, which is the exact "only
mostly true" failure the Documentation section is about.

**So run `git diff --cached --name-only` and read it before every commit.** If
somebody else's file is staged, `git reset` the index (that touches no working
file), stage yours again, and check once more. Where two agents have edited the
same file -- `tools/README.md`, always -- build the version you mean to commit
in the scratchpad, `git hash-object -w` it and `git update-index --cacheinfo`
it into the index: that lands your rows without ever rewriting the file
somebody else is still editing.

**And tell subagents not to `git add` at all.** The main window commits; an
agent that stages is an agent whose half-finished work is one `git commit`
away from `main`.

**`git add` a new file *before* the last local run.**
`tests/test_repository_contents.py` walks the files **git knows about** -- the
allowlist for `tests/fixtures/`, the ban on committed disk images and
executables, and `test_no_hardcoded_user_paths`. An untracked file is in none
of those lists, so every one of those checks passes by not looking, and the
file becomes visible to them at the moment it is committed -- which is after
the run that was supposed to clear it.

That is how `tools/fightrun.py` shipped `DISKS =
pathlib.Path("/home/donald/c64/...")` on 2026-09-01, red on all four jobs
against a suite that had passed twice locally. **A new file is the one case
where a green local suite says nothing about the checks that govern it.**

And when a new file needs a path to the player's disks, use what the other
tools use -- `$POR_DISKS`, then `automap.paths.find_disks()` -- rather than a
fourth way. `tools/geomap.py` is the one-liner.
