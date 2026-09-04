# Why these rules

This page holds the incidents behind this project's working rules -- what was
done, what it cost, and what rule came out of it. It was split out of
`CLAUDE.md` under `#208 (Split CLAUDE.md into .claude/rules, so 21,800 tokens
do not load before every task)`, so that the rules themselves can be stated in
a few lines each without losing the reason anybody believes them. Nothing here
tells you what to do; the rules files do that. Read this when you have been
handed a rule and want the evidence.

Quotations from Donald are copied character for character. They are the
evidence, and most of the rules exist because he said something once and it
was written down.

## Citations

The rule that a cited issue carries its title is the one most often broken here
and the one that costs the most. The reason is that a bare number moves the
work from the writer to the reader: *"when you only reference a number, it
never means anything to me."*

`CLAUDE.md` used to explain this as a matter of whether a browser was open.
Donald corrected that on 2026-09-02: *"It should not matter if I have a web
browser open or not. You're forcing me to manually look up every number. That
is fast for you, but slow for me."*

The rule was stated twice in `CLAUDE.md` -- once in the Issues section and
again in Replies, three hundred lines later -- and went on being broken anyway,
five times in one session on 2026-08-31, in the middle of work that was
otherwise going well. A reply is written fast, the number is what the assistant
has in hand, and the title feels like padding. It is not padding; it is the
whole content of the reference.

The failures came in a sequence, each one a narrower version of the last.
First bare numbers everywhere. Then titles in the prose and bare numbers in
tables -- a column of bare numbers is the least readable thing in a reply, not
the most. Then titles in the table and bare numbers in the prose around it:
"#102 is solved", "#59's inherit list", "#50's proof now passes". A number used
as the subject of a sentence is the worst place for it, because that is exactly
where the reader most needs to know what is being talked about. "The resizable
columns with #135" is the same shape. There is no "already introduced it above"
exemption, because a reply is skimmed rather than read in order.

Two exceptions were settled deliberately, and both are about where the reader
is. A commit message keeps the number bare in parentheses at the end of its one
line, because a title there would break the sentence and GitHub hotlinks the
number anyway. And an issue *body* is exempt -- Donald, 2026-09-01: *"Leave
them alone. GitHub.com shows the ticket details on hover and makes it a
hotlink, so it will be fine."* On the web the hover does the lookup for him; in
a terminal nothing does, which is why the rule binds hardest there.

### The guard that disabled every subagent

`.claude/hooks/check-issue-titles.py` is a `Stop` hook, so it only sees a turn
once the turn has ended. Prose written mid-turn, with tool calls still to come,
reaches Donald before anything checks it.

A mid-turn `PreToolUse` guard was tried on 2026-09-02 to close that gap, and
withdrawn the same hour. It refused the next tool call whenever the turn's
prose so far carried a bare number. In the main window it worked. It also
disabled subagents completely: a subagent's `transcript_path` is the shared
one, so an agent was refused for citations the main window had written, could
not edit them, and had no way to clear the block -- `gh issue view`, the remedy
the message itself recommends, is a `Bash` call the guard refused. One agent
lost its whole task that way and reported that even `echo ok` was refused.

The lesson is the general one rather than the specific: a guard that blocks tool
use has to be clearable by whoever it blocks. This one was not, and its failure
mode -- no agent can do anything -- was worse than the fault it caught, which is
a sentence Donald has to read twice.

## Conciseness and replies

Conciseness carries no incident of its own; it is a standing preference, and
the shape of it is that length is not thoroughness.

Explaining a bug by its mechanism rather than by the situation does have one.
Donald read an explanation of a rename bug -- something to the effect of
"`_flush` swallows a `ValueError` from `encode_record_name`" -- and answered:
*"I don't understand. In what situation would a user be in when they run into
this?"* The situation was that you rename a character to `Bel'ana`, the
apostrophe is a curly one because you copied it off a web page, you click Save,
it says "no changes", and the box still shows the name you typed. A reader who
has not seen the code cannot tell from a description of the code whether the
bug matters, how often it happens, or whether they have ever hit it themselves
-- and those are the questions that decide what to do about it.

The same discipline applies when the honest situation is unflattering to the
bug. "No user can reach this" is an answer, and it is the answer that moves
something down the list.

## Words to avoid

Three separate corrections produced this list, and all three are about the same
habit: reaching for a piece of jargon that sounds precise and carries less than
the plain phrase it replaced.

**A file given a person's verb.** "All three saves walk" was written here and
Donald could not read it: *"I don't know what a save walking means."* He is
right -- a save cannot walk, a party walks. The shorthand collapses the actor,
and the actor is the whole content of the sentence. What was actually proven was
that the party in each of the three converted saves could be made to move;
"the saves walk" could equally have meant the file loaded, the game did not
crash, or somebody took a step.

The rule survived the sentence it was written about and was broken again on
2026-08-27, in a reply announcing that the DOS import no longer needs a
template: *"The template is gone, and it played."* Donald: *"I don't know what
'it played' means. A template cannot play a video game. It is a template, it
can't action anything on its own."* Two faults in five words -- a thing was
given a person's verb, and `it` pointed at the noun nearest to hand rather than
the one meant. Announcing a result is exactly where this slips, because the
result feels like the subject; it is not.

The sense that is fine is the one with no person in it: walking a range, a loop
or a structure. `docs/118-debug-mode.md`'s "walks `$9800` from 10 to 18" is
exactly right.

**"X follows Y".** It went into two issue titles before Donald said so: *"I see
this a lot, where you say 'X follows Y'. It doesn't make sense to me, and it
results in me not understanding what's going on."* It is doing the work of at
least three different sentences -- grows with, is derived from, is recomputed
after -- and the reader cannot tell which. "The window's minimum height follows
the UI font" means "the window gets taller as the UI font grows, so a large font
stops it fitting the screen", and only the second version is something somebody
can act on. `#77 (The window's minimum height follows the UI font, so a large
font stops it fitting a 720-high screen)` still carries the phrase in its title,
which is why the title is quoted rather than paraphrased.

**"That's fair"** is the worst of the list, because it agrees with nothing in
particular and ends a conversation that had somewhere to go.

**`elide` has a code exception**, and it is narrow. Qt's own methods are
`setTextElideMode` and `ElideRight`, so `elide` in `editor/rosterview.py` is the
framework's word; changing it would make the code harder to search rather than
easier to read.

### Embraced energy

Donald ruled on 2026-09-01: *"I think 'embrassed' is a typo from
game-icons.net. Let's refer to it as 'embraced' unless we are referring to the
url."* Only the URL slug and the archive filename carry the typo; the icon's
page on game-icons.net is titled *Embraced energy*.

The licence credit was then got backwards, and the reasoning is worth recording
because it was almost right. A credit should name a work as its author titled
it -- that part is correct. The mistake was taking the *filename* as the
author's spelling. Donald: *"It's called 'Embraced energy icon'. It says so on
the game-icons.net website."* `wish/licenses.py`'s `TITLES` is the one-entry
override that fixes it.

## Help text in the GUI

The rule that every word a user reads is Donald's to approve exists because the
interface kept growing sentences that explained itself. An info icon whose
tooltip ran four sentences; a footnote about a board slot no player can reach; a
line under the backup folder saying what an empty box means; a note about how
many backups are kept. Each looked reasonable alone, and together they made a
program that apologises for itself. Every one of them was removed on request.

**"It matches the wording already there" is the excuse that got three strings
shipped.** In 2026-08 an agent added one line to the export report and two to
Preferences, each closely modelled on a sibling sentence in the same function,
and that similarity is why nobody stopped to ask. Donald's verdict on all three
was *"they won't be understood by humans"* -- `#96 (Three interface strings
shipped tonight without being approved)`. The existing sentences read well to
somebody who already knows the machinery, which is everybody who has ever
reviewed them and nobody who is using the program.

**Capitalisation.** Donald, 2026-08-31, first of the Messages panel -- *"I want
us to start making sure we capitalize the phrases that are going into the
Messages panel. It looks more professional."* -- and then of everything:
*"There should be a rule that text we send to the user always has the first
letter capitalized. This has been a recurring problem in all AI text."*

He is right that it is a habit rather than an oversight. Assistant-written
strings start lowercase far more often than human-written ones, because they are
written as fragments -- `no party to read`, `waiting for the game` -- and nobody
looks at the finished line. Upper-casing each message constant was tried and
changes nothing a user sees, because the first word is usually the caller's:
`_report("fast travel", outcome)`, and `action.label.lower()` on the action bar.
The composed line is where it has to happen. And `str.capitalize()` is the wrong
tool, because it lower-cases the rest -- it would turn the combat log's
`MAGNUS MISSES.` into `Magnus misses.` and mangle `$6E11`.

The rule then got broken by somebody following it. Quoting a lowercase string is
correct; starting a sentence with that quotation makes the sentence lowercase
anyway. Donald caught it in the reply that cited the rule -- *"why isn't the
sentence capitalized?"* -- where a table cell began `counts towards commissions
completed names a label the window no longer shows`.

**Memory addresses in front of a player.** Donald, 2026-08-31, of a tooltip
reading `$4AC1, bumped by the clerk for the ten commissions that count as
major`: *"we shouldn't be presenting memory addresses to players."* It is an
easy fault to introduce here, because the address *is* the evidence and this
whole project is written in addresses. In a docstring, a comment, a `docs/` page
or an issue, the address is what makes a finding checkable; in a tooltip it is a
developer's note that escaped. `also needs $4A97 (Cadorna's chambers) unpaid`
became `also needs Cadorna's chambers unpaid`, and nothing was lost.

**Looking at the source instead of the running window** hid a duplicated word.
The export line reads `the file name 'LADYKATH.pc' is already used by another
character in this export; written instead as 'LADYKAT2.pc'` in the code, and in
the pane it is prefixed with the file it concerns -- so the same filename
appears twice in one sentence and half of it repeats the prefix. That was
invisible in the diff and obvious in a screenshot.

## What must never enter the repository

This has no failure behind it, which is the point: nothing forbidden has been
committed. The policy is that this is a reverse-engineering project which
documents a game it does not ship, and the boundary was drawn before it could
be crossed.

One ruling is worth recording because it went the permissive way. Quoting the
code a finding rests on is exactly what `docs/50-experiments.md` is for, and
Donald ruled that a short block is fine -- so nobody should agonise over the
length of a citation that carries evidence. A dump of a routine is still not a
citation.

The one thing that has to be argued each time is a test fixture. A fixture that
is a slice of a game file is the same copy the rule forbids, merely renamed,
which is why `tests/gamedata.py` reads from the player's own disks and
`synthetic_geo()` generates a well-formed map for the cases that only need *a*
file rather than a specific one.

## Git in a shared tree

**580 lines of `por/amiga.py`, 2026-08-26.** A `code-reviewer` ran `git
checkout` on the file it was reviewing, to undo a throwaway edit of its own, and
destroyed 580 lines that existed nowhere else. Several agents share one working
tree, so a revert is never local to the agent doing it: it discards whatever
anybody else has uncommitted, silently and unrecoverably. Two rules came out of
this. No agent runs `git checkout`, `git restore`, `git reset`, `git stash` or
`git clean` against a file in this repository; and a subagent's work is
committed locally *before* the review runs, which turns that class of accident
into `git revert`.

**A test red for twenty minutes against a correct file, 2026-08-27.** The
approved way to test whether a change matters is to copy the file aside and copy
it back. A file put back at the same size in the same second does not look
changed to CPython's bytecode cache, so the program went on running the broken
code while `inspect.getsource` showed the right source. Deleting `__pycache__`
after the restore is what closes it.

**A copy-back reverted an agent's fix, 2026-09-02.** A copy-back is a `git
checkout` with a different name, and the copy is a snapshot of the file at the
moment it was taken -- so putting it back deletes every edit anybody made in
between. The main window had given `goldbox/dos.py` to an agent working
`#191 (A converted dwarf loses his constitution bonus to saving throws)`, then
edited the same file itself for `#176 (A player importing a Curse of the Azure
Bonds save is shown an issue number)`, and its copy-back restore silently
reverted the agent's one-line fix after that agent had already seen the whole
suite green on it. Nothing failed loudly; the line simply went back to what it
had been.

The mistake was editing a file that had been assigned to an agent. The copy-back
was only how it landed. What came out of it: prefer a targeted edit to a
copy-back, take the copy immediately before the change being tested rather than
at the start of a run, and `diff` against the live file rather than against your
memory of it.

The same incident produced the technique for committing a shared file. The hunk
for `#176 (A player importing a Curse of the Azure Bonds save is shown an issue
number)` went in while the `#191 (A converted dwarf loses his constitution bonus
to saving throws)` work beside it stayed uncommitted and untouched, by building
the intended version in the scratchpad, `git hash-object -w`-ing it and
`git update-index --cacheinfo`-ing it into the index.

**`tools/livestrip.py` reached `main` inside somebody else's commit,
2026-09-01.** `git add X && git commit` commits the whole index, not just `X`.
Several agents share this tree and they stage files, so a commit made after
naming your own paths sweeps in whatever anybody else had staged. Worse, the
file's `tools/README.md` row was still uncommitted, so it landed as a file the
table does not describe -- the exact "only mostly true" failure the
documentation rules are about. Reading `git diff --cached --name-only` before
every commit is the check; telling subagents not to `git add` at all is the
prevention.

## The machine

Donald works at this desktop while agents run. Windows flashing open and closed
are not a cosmetic annoyance -- one of them was a modal dialog that sat over his
editor until he dismissed it.

**A private `Xvfb` is not a sandbox.** His desktop is Wayland, and a GTK or Qt
child prefers `WAYLAND_DISPLAY` over whatever you set for X. DOSBox-X's file
chooser walked straight out of an `Xvfb` that way and drew on his screen.
Unsetting `WAYLAND_DISPLAY` is the part that is easy to miss, and "run it on
your own X display" is not sufficient advice on this machine.

**Three KDE credential dialogs in one night.** With no tty and `DISPLAY` set,
OpenSSH does not fail when authentication falls through -- it runs
`SSH_ASKPASS`, which on this desktop is `ksshaskpass`. Setting both
`SSH_ASKPASS_REQUIRE=never` and `-o BatchMode=yes` is what stops it: the first
stops ssh reaching for a dialog, the second makes it fail instead of prompting.
A prompt an agent cannot answer is not a pause; it is a dialog on somebody
else's desktop, waiting on somebody who did not ask for it.

`CLAUDE.md` said for a while that `winvm` needed wrapping. That was true when it
was written -- `wait_ssh` had `BatchMode` and the `ssh` subcommand did not -- and
was checked against `/usr/local/bin/winvm` on 2026-09-01 and found fixed: it
exports `SSH_ASKPASS_REQUIRE=never`, and its one `SSH_OPTS` array carries
`-o BatchMode=yes` and is passed by the `ssh` and `scp` subcommands alike.
`winvm`'s own comment records the fix.

**Killing a process by name killed Donald's window.** The one time `pkill` was
used against an emulator by name, what died was the game a human had started
from the desktop menu. Port 6502 is his, along with 6510 and 6600; the instance
pool allocates 6520 and upwards and never touches them. An instance nobody
leased cannot be told from a human's, which is why the pool owns the whole
lifecycle -- allocate, launch, tear down -- and why a slot whose lease is held
belongs to somebody however dead it looks.

**VICE's config is read as a template and never opened for writing.** Every
pooled instance gets its own `vicerc` seeded from his with
`SaveResourcesOnExit=0`, so nothing an agent runs can write settings back into
his.

## Temp files, tools and backups

**`ecl6.py` is the expensive loss.** It decoded all thirty ECL scripts to 100%
of every byte, lived under `work/`, and is gone. Losing it cost more than losing
any single report, and no rule about write-ups would have saved it -- which is
why a tool goes in `tools/`, committed, with a row in `tools/README.md`. Donald,
2026-09-01: *"If you develop tools, put them into tools/, not work/. That way,
you don't have to rebuild them."* The test is not whether a script looks
finished; it is whether somebody would otherwise write it again.

**A file under `work/` cannot be found either**, which is the cheaper half of
the same problem. `work/issue127/proto.py` holds the breadth-first
`step_towards` that walks round rock and round the party's own formation,
written for `#127 (A driven character stands next to an enemy and passes its
turn instead of attacking)`. On 2026-09-01 the main window reported it lost --
wrongly, off its own `ls | head` truncating the listing before the `.py` files
-- and wrote that into `CLAUDE.md` and into `#170 (A driven character walks into
rock, because step_towards never reads the terrain)` before a subagent that had
actually opened the directory corrected it. A tool in `tools/` has a row saying
what it is for; a tool in `work/` is one entry among the logs and dumps of the
run that produced it, and nothing anywhere says it exists.

**`work/` has been lost twice**, and Donald established the cause on 2026-09-02:
he ran out of Claude quota, drove the project with Google Gemini for a while,
and it deleted the directory -- probably because it does not read `CLAUDE.md`.
The two losses are `#136 (Thirty-two cited write-ups are gone, because the
knowledge base pointed into gitignored scratch)` and `#148 (The Amiga port's
tools are gone, and phase 1 still needs the disassembler)`.

That cause is the whole reason the backup takes dated snapshots rather than
mirroring. An `rsync --delete` mirror would have replicated the deletion on its
next run and destroyed the backup as well; a dated tarball cannot be eaten by a
later `rm`.

**The retention scheme was nearly useless and nobody had noticed.** The first
version kept only the last fourteen snapshots, which at the ten-minute cadence
it then had was about two hours of history -- so a deletion nobody spotted for
an evening would have rolled the good copies off the end while the hook
faithfully snapshotted the empty directory. That is the exact failure the backup
exists to survive. Donald asked how often the hook fired, which is what turned it
up, and the same conversation produced the throttle: *"I don't think the backup
should run every 10 minutes. Once an hour is enough."* Retention now keeps the
last fourteen snapshots *and* the first snapshot of each of the last thirty
days.

**It is deliberately Donald's machine only.** He asked on 2026-09-02 what would
happen if another person cloned the repository and ran Claude Code on it: without
the guards, a stranger's machine would tar up their `work/` and run
`onedrive --sync` against *their* account. The hook is registered in
`.claude/settings.local.json`, which is gitignored, and refuses unless the
destination's parent directory exists.

A tarball nobody has opened does not tell the next session that a tool exists.
The backup is a restore of last resort, not a filing system.

## Issues

**`gh issue list` truncated a count and said nothing about it.** It defaults to
`--limit 30`, so counting the backlog with it answered "30 open" against a real
44, and the number looked plausible enough not to question.

**An agent destroyed Donald's curation by "fixing" it.** An agent had asked for
`enhancement`, Donald had set `question`, the mismatch was reported as a fault,
and the assistant changed the label back. He curates labels and priorities by
hand and will keep doing so. The thing that must never happen is a change with
no comment, because that is what left no record anybody could read or reverse.

**And the rule cut the other way, which cost a night.** `#69 (No
WRITE_UNSOURCED zero has been tested during combat)` carried `bug` for months
while its own body said *"Nothing observed. This is a gap in the evidence
rather than a seen fault."* On 2026-09-01 an assistant worked a whole bug queue
around it, put it in every list it gave Donald, and never asked whether the
label was right -- the label was doing its thinking. Donald caught it: *"You
were unable to explain convincingly how it would affect an end user."*

A mislabelled issue is an invisible error. It fails no test, turns no CI red,
and produces no symptom except work quietly going to the wrong place for as long
as nobody looks. The question already asked of a bug -- what does the player see?
-- turns out to be worth asking of the label, and "nothing, we do not know yet"
means `question`.

**`blocked` outlives the fact it recorded when nobody will touch it.**
`#29 (The live reader uses Pool of Radiance's addresses on every title)` sat
blocked on Curse and Silver Blades disks that were on the machine the whole
time -- an assistant had written that they were missing without looking.
`blocked` is a claim about the world rather than a judgement about the work, so
it can be checked and it can be wrong.

**Then the caution itself became the defect, which is why the rule reads the
way it does now.** Written as "never undo a label", with the permissions added
underneath as exceptions, it taught agents to leave every label alone: by
2026-09-04 an audit of all 46 open issues reported four labels it believed
wrong and changed none of them, including a `blocked`-shaped issue carrying no
`blocked` label. Donald: *"Now, it won't mark a ticket blocked, it won't remove
the blocked label on a ticket it knows isn't blocked anymore... I just don't
want it resetting labels back to what they were for no reason at all."* The
rule was rewritten to ban the two things that actually went wrong -- reversing
a person's decision, and changing anything with no comment -- and to say that
everything else is ordinary work. A prohibition stated first and in bold is
what a reader takes away, whatever the paragraphs after it permit.

**An issue filed without a priority falls off the list.**
`#41 (The window's minimum width is 1546px on Windows and 1071px on Linux)` was
opened that way. It is not "unprioritised pending triage"; it is invisible.

**A defect that exists only in a report is a defect nobody will act on.**
`#65 (dax_unpack raises IndexError on ECL2.DAX block 9)` sat in a sentence of a
`#59 (Map the DOS saved game, not just the character record)` write-up until it
was noticed by hand, because nobody re-reads reports.

**"Closed" has been reported of an open issue twice**, both times because a
`closes #N` had been written into a commit that had gone nowhere. The keyword
fires when the commit reaches `main` and not before, and this project routinely
carries dozens of unpushed commits, so that gap is the normal state rather than
a corner case.

**What the prioritising advice is made of.** Three of its lines come from real
issues. `#70 (The 1280x720 guarantee is never checked by CI, on any platform)`
was a guarantee asserted and never verified -- believed by everyone and checked
by nobody, and it failed on both platforms the first time CI ran it, which is
worse than a missing test because a missing test is not believed. The synthetic
party built for `#70 (The 1280x720 guarantee is never checked by CI, on any
platform)` then unblocked `#31 (Cold-read Curse and Silver Blades for the
fields the editor shows)`, `#33 (One Silver Blades session, for the whole editor
path)` and `#34 (Validate the live automapper tab per title)` at once. And
`#75 (docs/50-experiments.md still says the DOS saved game's ECL buffer is dead
on load)` was a contradiction in the knowledge base that took a paragraph to fix
and had already cost somebody a session.

## Delegating

**A reviewer's finding was nearly acted on and was wrong.** The `code-reviewer`
reported a dead code path in `automap/actions.py` that turned out to be a
deliberate lever with a test and a docstring explaining it; the guard was most
of the way deleted before the test caught it. The reviewer is a reader, not an
oracle, and rejecting a finding with a reason is a normal outcome.

**Two specialists were reached past on 2026-08-26.** A `general-purpose` agent
was sent to fix banned words in issues, which `backlog-auditor` names in its own
description; and a second one was sent to work out which fixed bugs a `v0.1.0`
user could have hit -- a question `changelog-writer` needed answered *before* it
wrote the entries, and which should have been asked in its own brief. The cost
is not only the model. A specialist has read its own domain's rules; a
general-purpose agent has to be told them in the brief, and whatever the brief
forgets is what goes wrong.

**The `reverse-engineering` agent's cost was wrong in `CLAUDE.md` for a week.**
The file said it ran on Fable, that it had exhausted a monthly spend limit in
one night on 2026-08-26, and that Donald had to be asked before it was launched.
All of that was true when it was written and none of it was true by 2026-09-01,
when `.claude/agents/reverse-engineering.md` was found carrying `model: opus`.
Donald: *"I think the reverse engineering agent used to use fable as the model,
but it has since been changed to Opus. Using the reverse-engineering agent is
fine and no more expensive than a general purpose agent."*

The routing table carried a second stale row at the same time: `junior-dev` was
called `quick-fix` there until 2026-09-01, because the agent was renamed and the
row was not.

**Most reverse-engineering work turned out to be ordinary work.** Diffing two
files against a layout we already have, flipping a byte and reloading, driving
DOSBox or WinUAE through a documented recipe, walking a save with a hex editor
-- general-purpose agents did all of it, and it is how the DOS saved game's
inherit list went from 8016 bytes to 444 and how the Amiga Pool of Radiance
record was read. The escape hatch exists for the other case: an agent that finds
it genuinely needs to read 68000 or 6502 code stops and says so, and stopping is
cheap where grinding at a disassembly it was not sent to read is not.

**What makes an issue assignable to `junior-dev` is a property of the issue
body.** `#71 (Character draws on top of itself when the header is squeezed to
its floor)` looked like ordinary work and took nine rounds and a `QTableView`
subclass. `#73 (The DOSBox-X harness refuses to start without DOSBox 0.74, which
it never runs)` named the two candidate shapes and said which was smaller, and
that is what made it assignable.

**A reviewer in a shared tree reviews everybody.** `code-reviewer` starts with
`git diff`, and with three agents working that diff is three people's work --
so it reports another agent's half-finished change as a finding against the one
you are reviewing unless it is told which files it owns.

## Commits and CI

**Forty-one commits in one batch.** A day's work was held back and pushed all at
once, and a Windows regression that CI would have caught in minutes went
undetected for hours because no CI had seen any of it. Sitting on commits also
silently breaks `closes #N`, so issues stay open while everything looks
finished.

**Green was reported off a stale run three times, across two sessions.**
`gh run list --limit 1` answers whichever run is at the top, which during a push
is usually the *previous* one, already green. Matching on `headSha` is what
fixes it, and a run whose `conclusion` is empty has not finished however
`completed` the list looks.

**A scoped test run cleared a push that turned `main` red.**
`pytest tests/test_combatdrive.py` was green and `main` went red on all four
jobs eight minutes later. A scoped run is for working; it is not the check.

**A worktree run without the `work/` symlink lies by omission.** `work/` is
gitignored, so a bare detached worktree skipped every test that reads a specimen
out of it -- 204 skipped against the working tree's 103 on 2026-09-02, and the
hundred that vanished were exactly the ones with real game data behind them.
With `work/` linked the numbers matched to the test: 2783 passed, 103 skipped,
both ways. That gap is also the useful fact about CI, which has no `work/`
either: the bare run is the closest thing to what CI will do, and the in-tree
run is what covers the specimen-backed tests. Neither is the whole check alone.

**`tools/fightrun.py` shipped a hardcoded path, 2026-09-01.** It carried
`DISKS = pathlib.Path("/home/donald/c64/...")` and went red on all four jobs
against a suite that had passed twice locally. The cause is that
`tests/test_repository_contents.py` walks the files *git knows about* -- the
`tests/fixtures/` allowlist, the ban on committed disk images and executables,
and `test_no_hardcoded_user_paths`. An untracked file is in none of those lists,
so every one of those checks passed by not looking, and the file became visible
to them at the moment it was committed, which is after the run that was supposed
to clear it. A new file is the one case where a green local suite says nothing
about the checks that govern it.

**Two classes of failure happen here and neither reproduces on Linux**, so they
are expected rather than surprising: something Windows cannot do (`chmod` does
not make a directory unwritable there, `fcntl` does not exist, paths are not
split on `/`), and something that is not byte-identical on another machine (a
rendered image, anything with a font or a timestamp in it).

## Testing

### A number measured on this machine is not a number

It is a measurement of this machine, and the moment it is written into an
assertion it becomes a claim about every machine. Three of one night's CI
failures were exactly this: 1270 here against 1308 on CI's Linux and 1447 on
Windows; five clipped fields here and nine on another Linux box; a window width
of `natural + 900` that was room to spare here and twenty pixels short on
Windows.

Each time the fix was the same shape -- compute from what the thing asks for
rather than from what you saw, so `natural + box.sizeHint().width() + 400`
instead of a constant that happened to work. Where a constant genuinely is the
answer, what it was measured on and what would move it belong beside it.

**The trap has an inverse, and it caught `#77 (The window's minimum height
follows the UI font, so a large font stops it fitting a 720-high screen)` after
the constant was already right.** A cap can be a perfectly good constant and the
*assertion about it* still be a measurement of this machine. That issue capped
three widgets so the automapper page's floor stops growing with the UI font, and
asserted the floor was the same at every font. True here -- 580 at +0 through
+10 -- and red on both CI platforms, because their base font is smaller: CI's
Linux climbs 561, 578, 578, 578 and Windows 551, 569, 576, 576. The cap holds in
all three. Only a machine whose base font already reaches the cap sees no climb
at all.

So when a constant bounds something, the assertion is that it is bounded --
non-decreasing, and flat by the largest font -- not that it never moved. The
assertion that stated the outcome a user cares about, "the window fits a
720-high screen at +6pt", survived both platforms untouched, while two
structural proxies for it did not.

### The font calibration

`+6` measures here about like Windows' base font. That single fact is worth more
than the fix it enabled, and it lived nowhere but a conversation until it was
written onto `#71 (Character draws on top of itself when the header is squeezed
to its floor)`.

It also explains how three pushes went red. A `+N` offset is not the same size on
two machines, and stacking it on a platform's own base compounds it: on a
Windows runner, whose base already *is* that font, `+6` is Windows' base plus six
more, so an assertion at `+6` on CI is an assertion about a size no Windows user
has. A width is asserted at `+0` only, because that is whatever the machine
running the test actually starts from. A height can be asserted across the range,
because a taller font makes every machine's rows taller by the same proportion,
while how wide a button gets for the same text is the platform's business.

**The largest font worth testing is +10**, and 9pt is the base here. Donald,
2026-09-01, after a test was found asserting things at +12, +16 and +20 -- 21,
25 and 29 point: *"I don't think we should ever have unit tests that force us to
make a 25 point font work. I think that's an extremely contrived situation that
wastes our time."* And: *"This whole 25 point font with a tiny resolution just
feels extremely contrived and a waste of our time."*

The measurements agree with him: at +10 the window's floor is 553px against a
720-high screen. There is no layout problem at any font a person uses -- somebody
who needs text that large uses display scaling, which enlarges the window too and
never produces the squeeze. A test that only holds above +10 is proving an
artefact, and it will be true forever while catching nothing. Where a claim is
weak at a realistic font, the answer is to say it differently:
`test_the_top_row_asks_for_more_than_the_page_makes_room_for` was false at +0 and
passed only because it was never asked, and became true everywhere once it
compared a *rate* across two fonts instead of a gap at one.

### A timing measured on this machine is not a timing

Same trap wearing a stopwatch, and worse, because the test passes locally every
time. `test_a_directory_being_written_to_is_not_called_quiet` ran a background
thread writing every 20 ms while `settle_files` waited for a 200 ms quiet
window. It passed here and went red on CI within the hour: on a loaded runner
the thread was not scheduled inside that window, so `settle_files` correctly saw
nothing change and answered "quiet". The test was measuring the runner.

A concurrency test whose failure mode is "the other thread did not get a turn"
will find that out on somebody else's hardware. The fix has the same shape as
for a measured constant -- drive the thing from what it actually does rather
than racing it. `settle_files` sleeps between reads, so every sleep now stamps
the file forward with `os.utime`: that is what a save in flight looks like from
outside, it cannot be starved out, and counted stamps mean no filesystem's mtime
granularity can make two writes look like one.

### Proving a regression test red

A test written against a bug that has already been fixed is a guess until you
have seen it fail. This has gone wrong here twice. A test that filtered on
`not isWindow()` passed with the fix reverted, because the fault *was* a
parentless widget answering `isWindow() == True`. And a feature-flag test only
earned its place once forcing the flag on made it fail.

### The rest

`test_the_window_opens_inside_a_small_desktop` encodes Donald's actual screen, so
a layout that fails it is a layout that does not fit his screen -- which is why a
failing test is treated as evidence that the change is wrong rather than as an
assertion to be weakened.

A suite that is green because forty tests skipped has told you nothing;
`tests/gamedata.py` skips cleanly with no disks, which is right, and the skip
count is part of the result. And "24 of 24 records round-trip byte for byte" is
evidence where "it worked on my character" is not.

## Testing a conversion

**The template ruling, 2026-08-26.** Donald: *"We should not be using a template
at all. We should block on not understanding everything and go back and
understand what we need to. No more plugging in fake data to make it work."*

Building a converted save on top of a save the engine wrote means every byte
nobody has decoded silently keeps a value belonging to a different party in a
different place. That is not a neutral default -- it is wrong data that looks
right, and it is invisible because the file loads.

**The clock is the proof.** A converted party arrived reading 21:15 when its own
save said 10:15. Nothing about the run said so; it took a person looking at the
clock. That is `#58 (Decode the DOS clock, so converted saves keep the time of
day)`.

The distinction that survives from this is **measured versus inherited**. A value
we established is fine at any number, including zero: most of `WRITE_UNSOURCED`
is live heap pointers and combat state where the engine itself writes zero, and
that was measured both with items and without. A value inherited from somebody
else's save is not fine at any number. An undecoded field is therefore a blocker
with a settling experiment behind it, not a gap a template fills -- and leaning
on a template is what let that entry sit for as long as it did.

**The empty case is where the conversion broke after it was declared proven.** A
drop list measured survivable for a character carrying items said nothing about a
character carrying none, and that is exactly where `#62 (A converted character
who owns nothing gets a corrupt sheet, and DOS then invents a garbage item)` was
found.

**Bytes matching is necessary and not sufficient.** Three separate faults this
project shipped -- an AC of 9 displayed as 51, a dropped combat tail, and a
garbage weapon line -- passed every byte-level check that existed. A conversion
is not proven until somebody loads it in the game, walks, and looks at the sheet.

**Masking a round-trip by the diff makes the test agree with the code by
construction**, which is why `tests/test_doswriter.py` masks by
`WRITE_UNSOURCED` and `WRITE_DEFAULTS` -- the lists the writer declares -- so a
new difference fails.

## Documentation

**Thirty-two write-ups gone.** `work/reports/` held 32 of them and all 32 are
gone; nothing recovered them, and 80 citations across 29 documents had to be
rewritten to say so. That is `#136 (Thirty-two cited write-ups are gone, because
the knowledge base pointed into gitignored scratch)`. `work/` is gitignored on
purpose, because the game's own bytes may not be committed -- but the
*reasoning* about those bytes is not itself game data, so a write-up that argues
from evidence to a conclusion belongs in `docs/`, cited by a path that survives.
`tests/test_repository_contents.py` now fails the build on a new one: a `work/`
path in `docs/` or in a package is either a file that exists, or is marked in its
own text as lost.

**A README table that is only mostly true is worse than no table**, because the
gap is invisible. `tools/livestrip.py` landing on `main` without its row is the
worked example, and it is recorded under Git in a shared tree.

**A wrong document is corrected, not escalated.** Donald, 2026-09-01: *"If you
find something wrong in a document, you can just update the document. You don't
need to block on me. Use your best judgement."* The cost of not doing so is
already known:
`#75 (docs/50-experiments.md still says the DOS saved game's ECL buffer is dead
on load)` was a paragraph and cost somebody a session. A correction that layers
on the superseded text rather than deleting it is how the contradictions got in
to begin with.

**The top-level `README.md` is Donald's**, and is not a scratchpad the assistant
tidies in passing.

### What `goldbox-bugs.md` learned the hard way

Four rules about the front-door bug file each came from something that went into
it and should not have.

**Ours is not theirs.** Most things that looked like a game bug were our own
misreading -- a wrong stride, an off-by-one dump, an array read half its width.
Those belong in `docs/125-bug-notes.md`, as ours.

**It is for bugs**, not unfinished features, not cut content, not spelling
mistakes, and not the record of our own errors.

**"No player can reach this" is an answer**, and it is the answer that moves an
entry out of `goldbox-bugs.md` and into `docs/125-bug-notes.md`. N18 is there
for exactly that reason.

**Name the consequence, not the mechanism.** "Sokol Keep's dead elf comes back
every time you return" is the bug; "the dead elf is guarded on an address
nothing writes" is the cause, and it means nothing to somebody who has not read
the entry yet. An entry that is all mechanism reads as authoritative and cannot
be checked, argued with, or reproduced by the person most likely to care -- which
is why every entry also needs the situation a player is in when they arrive, and
the steps in the game's own terms.

## Art

No incident sits behind this one. "No AI-generated art, anywhere, ever" is
Donald's standing rule, stated rather than learned, and it is not negotiable by
an agent that finds it inconvenient.

The extension of it -- do not modify somebody else's art either -- rests on the
same reasoning: an icon lifted from Font Awesome is drawn the way Fonticons drew
it, and an assistant that moves a path point to make an icon work at a size is
making art, which is the thing it must not do. The correct answer is a different
icon, or not using it at that size.

The one thing that has gone wrong here is an attribution rather than a drawing,
and it is recorded under Words to avoid: the licence credit for Lorc's
*Embraced energy* was written from the filename rather than from the title its
author gave it.

## Qt Designer

No incident sits behind this one. Building layouts in `.ui` files and compiling
them with `tools/genui.py` is a design decision taken at the start, so that a
human can rearrange a form in Designer without a line of Python changing;
`editor/character.ui` has worked that way since the character editor was
written, and `tools/genui.py --check` catches drift in CI.

## Feature flags

The only history here is the feature that produced the rule. The DOS import is
the first flagged feature: it works, it is proven in the emulator, and it still
drops the portrait and the clock -- `#57 (Carry the character portrait across
ports)` and `#58 (Decode the DOS clock, so converted saves keep the time of
day)` -- so `File > Import` is not built unless the flag says to build it. That
pair of open issues is what "names the condition that removes it" means; "when
it is ready" is not a condition, and a flag with no stated way out becomes a
second code path maintained forever, where the second path is the one nobody
runs.

Two of the choices around it were made to avoid writing prose for a user.
Greying out a menu item invites the question of how to un-grey it, and the
answer would be a sentence in the interface -- so `wish/window.py` builds the
Import submenu inside the `if` instead. And a preference checkbox would need a
label, and a label saying "experimental" would need a sentence saying what that
means for the user's save disk. That is Donald's wording to write, and it is not
worth writing for something due to be deleted.

The feature-flag test that only earned its place once forcing the flag on made
it fail is recorded under Testing.

## Sessions

**2026-09-03 lost its small hours.** The last turn said it was "running the
suite at `HEAD` before pushing" and never started it -- no agent running, no
background command pending -- so four reviewed commits sat unpushed for hours
while the session waited for an event that could not arrive. Donald:
*"Apparently that didn't happen this time."*

This session works by being re-invoked: a subagent finishing, a background
command exiting, a scheduled wake-up. An intention is not an event, and "I will
do X next" calls nothing back.

**A killed background command is not a finished one.** Twice on 2026-09-02 and
twice more on 2026-09-03 a backgrounded `pytest` came back `killed` rather than
with a result. The suite takes about six minutes; a foreground run with an
explicit timeout has a result, and a backgrounded one has to be checked for one
rather than assumed to have passed.

**Long sessions accumulate stale facts.** Twice in one night the assistant
answered from something that had been true earlier and was not any more: the
Amiga disks were reported missing because an old search had been too narrow, and
`#71 (Character draws on top of itself when the header is squeezed to its
floor)` was reported closed off a local measurement that CI then contradicted. A
fresh session reading the issue would have got both right. Length is not
context; it is also drift.

**The calibrations are what get lost.** "+6pt here measures like Windows' base
font" is worth more than the fix it enabled, and lived nowhere but a
conversation until it was written onto `#71 (Character draws on top of itself
when the header is squeezed to its floor)`. A fact that exists only in a
conversation is a fact somebody pays for twice, and conversations end -- on a
spend limit, on a `/clear`, on a context window.

The test of whether a session was recorded properly is whether the next one can
answer "what should we work on" from the repository alone. When it cannot, that
is a documentation bug rather than a reason to keep a session alive.
