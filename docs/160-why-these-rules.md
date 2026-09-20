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
"#102 (A minimally-cached save cannot walk into an area, and the party is stuck where it stands) is solved", "#59 (Map the DOS saved game, not just the character record)'s inherit list", "#50 (Lift the wilderness refusal from the DOS save converter)'s proof now passes". A number used
as the subject of a sentence is the worst place for it, because that is exactly
where the reader most needs to know what is being talked about. "The resizable
columns with #135 (The automapper's roster column does not scroll, so a full party puts a 944px floor under the window)" is the same shape. There is no "already introduced it above"
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

### What the rule files said before they dropped their history

The rule files state the rule and carry no history. These are the passages they held on this section's subject before that cut, verbatim.

#### AGENTS.md, "Name every issue you cite"

Original example (replaced by the placeholder `#123 (the issue's own title)`), lines 40-41:

> `#59 (Map the DOS saved game, not just the
> character record)`, never a bare number.

Cut quotation, lines 51-52 (end of the paragraph "A bare number makes him do the lookup"):

> number in hand, slow for him. *"When you only reference a number, it never means
> anything to me."* As the **subject** of a sentence it is worst of all.

Cut provenance, lines 54-56 ("It does not govern code"):

> **It does not govern code.** Donald, 2026-09-09: *"I don't care about bare issue
> numbers in code or docstrings. I care about it when you are communicating with
> me."* A docstring is read by somebody already in that file, and

### What tests and a hook said before they dropped their history

The passages below stood in code comments, a hook's docstring and an agent definition until the no-history rule removed them, verbatim.

#### tests/suite/test_repository_contents.py (comment above CITED_ISSUE_SCOPE)

```
#: Where this rule actually applies. Scoped to what
#: `.claude/rules/issues.md` and `#245 (tools/README.md cites issues by bare
#: number, which is the lookup AGENTS.md's first rule exists to prevent)`
#: swept, not every tracked `.md`:
#:
#: * `AGENTS.md` quotes a bare `#59` on purpose, as the example of what *not*
#:   to write -- fixing it would delete the example.
#: * `.claude/agents/*.md` do the same for `#59` and `#78`, and `junior-dev.md`
#:   cites issues in its own worked examples rather than in project prose.
#: * `CHANGELOG.md` uses a different, already-approved form -- a written-out
#:   markdown link, `[#78](https://github.com/.../issues/78)` -- because
#:   GitHub does not auto-link a bare number off the release page; see
#:   `.claude/agents/changelog-writer.md`.
```

Also, in the same file inside `test_no_bare_issue_number_where_a_citation_belongs`:

```
        # A generated page's citations come from the source it is built from --
        # `goldbox/layout.py`'s field notes, `goldbox/memory.py`'s regions --
        # so a bare number here means the source was never swept, not that
        # this page needs its own exemption.  #261 (A generated document's
        # issue citations come from source notes that still use bare numbers)
        # swept both sources; this guard now scans the pages they generate
        # like any other.
```

#### .claude/hooks/check-gh-issue-titles.py (module docstring)

```
The sibling `check-issue-titles.py` is a `Stop` hook: it reads what the
assistant said to Donald and refuses a bare `#59`. It never sees an issue
comment, because that leaves through Bash rather than through a reply -- and
`.claude/rules/issues.md` says the rule covers "replies, issue comments,
documents and tables", so half the rule had no guard at all.

Found on 2026-09-02, when Donald asked why the guard was not working: it was,
for replies, while six issue comments had gone out with bare numbers in them.

**It is not registered today**, along with its sibling -- `3ee1a3f "Disable
github issue hooks."` (2026-09-03) removed both from `.claude/settings.json`.

...

**The description of an issue is exempt, and that is Donald's ruling**, not an
oversight: *"Leave them alone. GitHub.com shows the ticket details on hover
and makes it a hotlink, so it will be fine."* An issue body is read on the
web.
```
(Also in the file's `CHECKED` comment: "which Donald has ruled is read on the web" -- and the block-message string says "issues.md says the rule covers replies, issue comments, documents and tables alike", the same misquote, in a user-facing stderr string.)

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

## Banned Words

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

### The later rows of the table

Each of these was added after Donald objected to the word in a reply.

**`shape`, 2026-09-11.** An earlier version of the row wrongly kept two phrases
that the rules themselves used, *"the shape of the fix"* and *"the shape of the
work"*; both were rewritten and the row now has no exemption. *"Just because
you read them in our docs somewhere doesn't mean I understand it. Every time you
use that word, I don't understand what you mean."*

**`worth`, 2026-09-06.** *"You've abused it past my point of tolerance. You are
constantly telling me something is worth knowing, or worth saying, or worth this
or that. I've had it."* The word rates a sentence instead of writing one.

**A sentence that rates itself, 2026-09-09.** After a reply that said a finding
"says so out loud": *"This is unnecessary filler. Shouldn't caveman lite prevent
you from saying things like this?"* It should, so the whole family of ratings is
banned and not only the examples.

**`plain`, 2026-09-09.** *"Anytime you ever, ever ever think you should use the
word plain, you should be using the word simple instead."*

**`carried`, 2026-09-04.** *"The agents just give up and say 'oh well, we can't
convert it'. But they call it carried instead, which confuses me."* The word
makes a refusal to convert sound like a finding.

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

### What the rule files said before they dropped their history

The rule files state the rule and carry no history. These are the passages they held on this section's subject before that cut, verbatim.

#### .claude/rules/gui-text.md -- "Help text in the GUI"

> The interface kept
> growing sentences that explained itself until it read as a program apologising
> for itself; every one of them was removed on request.

> Donald's verdict on three strings shipped that way --
> `#96 (Three interface strings shipped tonight without being approved)` -- was
> *"they won't be understood by humans"*.

#### .claude/rules/gui-text.md -- "Any decision about the interface comes with a screenshot"

> 2026-09-05: *"For the theming stuff, you need to
> show me a screenshot. You are just giving me straight numbers, and I am not a
> computer. We need a rule that any UI decision requires a screenshot."*
>
> He said it after being handed hex colours, file paths and line numbers as the
> evidence for a claim that Wish would be unreadable on a dark desktop -- a
> claim about **what something looks like**, argued entirely in things you
> cannot look at. When the screenshot was finally taken it did not support the
> claim.

> Reading
> `setStyleSheet` calls and reasoning about what they would do is how the
> wrong claim above got made.

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
between. The main window had given `goldbox/dos_codec.py` to an agent working
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

**`tools/gui/livestrip.py` reached `main` inside somebody else's commit,
2026-09-01.** `git add X && git commit` commits the whole index, not just `X`.
Several agents share this tree and they stage files, so a commit made after
naming your own paths sweeps in whatever anybody else had staged. Worse, the
file's `tools/README.md` row was still uncommitted, so it landed as a file the
table does not describe -- the exact "only mostly true" failure the
documentation rules are about. Reading `git diff --cached --name-only` before
every commit is the check; telling subagents not to `git add` at all is the
prevention.

### What the rule files said before they dropped their history

The rule files state the rule and carry no history. These are the passages they held on this section's subject before that cut, verbatim.

#### AGENTS.md, "Git in a shared tree"

Cut sentence, line 179:

> else has uncommitted, silently. That is how 580 lines of `por/amiga.py` went.

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

### Why four of these rules came off

Every rule above except the pool's own was there because an agent and Donald
shared one desktop: a window drawn on his screen, an ssh prompt on his KDE
session, a kill landing on the game he had started, the ports his own games
listened on. Agents now run in the sandbox VM, so none of it is on the machine
they run on and the four came out of `AGENTS.md`, the `test-runner`,
`emulator-runner` and `qt-ui-specialist` definitions and `gui-text.md`: the
`WAYLAND_DISPLAY` and `GDK_BACKEND` invocation, `SSH_ASKPASS_REQUIRE=never`,
the reservation of ports 6502, 6510 and 6600, and never killing a process by
name.

**The pool's display allocation stayed.** Two emulators started at once race
for one X display and one set of ports wherever they run, so
`.claude/rules/emulator.md` still has every agent claim a slot. The pool
still allocates from 6520 up.

### What the rule files said before they dropped their history

The rule files state the rule and carry no history. These are the passages they held on this section's subject before that cut, verbatim.

#### AGENTS.md, "The machine"

Cut sentences, lines 214-215:

> Kill only the process group your own slot launched. The one time this was broken,
> what died was his own window.

#### .claude/rules/emulator.md -- speaker section

> He caught an agent doing it on 2026-09-05: *"That is going to
> blast the intro song, and I'll have no way to turn it down."*

#### .claude/rules/emulator.md -- "Every emulator an agent starts is silent"

The FS-UAE incident (the rule keeps "The headless branch handles VICE and
nothing handles the others" and says a brief must say "silent" as well as
"offscreen"):

> on 2026-09-08 an agent booted FS-UAE offscreen on his own machine to
> answer `#464 (Can the automapper follow a live FS-UAE game on Linux, so Wish
> and the Amiga game run on one machine?)`, and two "Amiga Emulator" streams
> turned up in PulseAudio while he was working. He asked what was making disk
> noises, and it took a `pactl list sink-inputs` to say. He was mild about it --
> *"I can turn the speakers down, so this is not a huge impact. But make sure to
> silence it next time"* -- and mildness is not the point: a noise in his room is
> the same kind of mistake as a window on his screen, and the brief that sent
> that agent said "offscreen" and forgot to say "silent".

The FS-UAE volume measurement:

> all three runs Donald
> heard on 2026-09-08 had it set, which is how this rule came to be measured
> rather than guessed.

The WinUAE deadlock citation:

> (`#331 (Amiga Silver Blades asks a journal word before it will
> adventure, so the title cannot be driven past its party menu)`)

## Temp files, tools and backups

**`ecl6.py` is the expensive loss.** It decoded all thirty ECL scripts to 100%
of every byte, lived in the old scratch directory, and is gone. Losing it cost more than losing
any single report, and no rule about write-ups would have saved it -- which is
why a tool goes in `tools/`, committed, with a row in `tools/README.md`. Donald,
2026-09-01: *"If you develop tools, put them into tools/, not [the scratch directory]. That way,
you don't have to rebuild them."* The test is not whether a script looks
finished; it is whether somebody would otherwise write it again.

**A file in the scratch directory cannot be found either**, which is the cheaper half of
the same problem. `issue127/proto.py` (scratch, deleted) held the breadth-first
`step_towards` that walks round rock and round the party's own formation,
written for `#127 (A driven character stands next to an enemy and passes its
turn instead of attacking)`. On 2026-09-01 the main window reported it lost --
wrongly, off its own `ls | head` truncating the listing before the `.py` files
-- and wrote that into `CLAUDE.md` and into `#170 (A driven character walks into
rock, because step_towards never reads the terrain)` before a subagent that had
actually opened the directory corrected it. A tool in `tools/` has a row saying
what it is for; a tool in scratch is one entry among the logs and dumps of the
run that produced it, and nothing anywhere says it exists.

**The scratch directory was lost twice**, and Donald established the cause on 2026-09-02:
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
the guards, a stranger's machine would tar up their scratch directory and run
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

**And then the lesson was over-learnt, which is its own entry.** From that one
incident `.claude/rules/issues.md` grew a section saying priorities were "the
one place to hold back" and that an agent should recommend one and leave the
label. That is not what happened and not what he asked for. Donald,
2026-09-09: *"One time, I changed a priority label, and the AI immediately
changed it back. I asked it not to do that. Ever since then, the AI is
absolutely terrified to touch the priority label. That isn't the rule. It is
fine to change priorities. Just have a reason and post it in the comments.
Don't just flip it back because you think it was a mistake."*

So the incident above is about **reversing a person's decision**, and it says
nothing about labels an agent sets, corrects or updates as the world moves.
Writing it down as *never touch these* made a second invisible error out of
the first: an issue whose priority no longer matches what is known, left wrong
because nobody dared. The section is rewritten, and the general shape is worth
holding on to -- **a rule derived from a single incident tends to come out
wider than the incident**, and the width is what nobody notices afterwards.

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

### What the rule files said before they dropped their history

The rule files state the rule and carry no history. These are the passages they held on this section's subject before that cut, verbatim.

#### AGENTS.md, "The tracker is public..." hooks paragraph

Cut, lines 101-106 (the whole paragraph; the two hook paths stay, the reason and the date go):

> **The first two have hooks behind them**, because neither held as a rule alone:
> `.claude/hooks/check-issue-reads.py` refuses the unfiltered reads, and
> `.claude/hooks/check-issue-writes.py` refuses a `gh` write that would go out
> under Donald's name. The second was written on 2026-09-11 after a subagent
> posted its findings with `gh issue comment` hours after the rule was added --
> the rule had reached it, and every older document shows `gh`.

#### .claude/rules/issues.md -- "Citing an issue"

The example and the quotation in the opening paragraph (the rule now reads
`#123 (the issue's own title)` and gives the reason in its own words):

> **Name an issue when you cite it: `#59 (Map the DOS saved game, not just the
> character record)`.** A bare number is a lookup Donald has to go and do:
> *"when you only reference a number, it never means anything to me."*

The attribution on the code exemption:

> Donald, 2026-09-09: *"I don't care about bare issue numbers in code or
> docstrings. I care about it when you are communicating with me."*

The attribution on the issue-body exemption:

> Donald, 2026-09-01: *"Leave them alone. GitHub.com shows the
> ticket details on hover and makes it a hotlink, so it will be fine."*

#### .claude/rules/issues.md -- "Labels"

The incident and the attribution under "Do not reverse a change a person made":

> An agent asked for `enhancement`,
> Donald set `question`, and the agent set it back -- treating his decision as
> the defect.

> Donald, 2026-09-04: *"I
> just don't want it resetting labels back to what they were for no reason at
> all."*

The attribution under the priority rule:

> Donald, 2026-09-09: *"It is fine to change
> priorities. Just have a reason and post it in the comments. Don't just flip it
> back because you think it was a mistake."*

The account of the earlier version of the section (the rule now stands without
it):

> **An earlier version of this section said priorities were "the one place to
> hold back". That was wrong**, and `docs/160-why-these-rules.md` has how it got
> there.

#### .claude/rules/issues.md -- "An agent files and comments as the bot"

Dates and backfill history around the `AI` / `human` labels (the rule now says
"An issue with neither label predates that workflow."):

> **Nothing
> locks anything**: a GitHub App installation is refused a comment on a locked
> issue whatever permissions it holds, measured three ways on 2026-09-11, so
> locking would silence this project's own bot rather than the public. An issue opened before 2026-09-11 carries neither label; nothing was
> backfilled, because all three hundred of them were Donald's and a universal
> label means nothing.

#### .claude/rules/issues.md -- "Work you discover while working"

The attribution on the renaming ban:

> Donald, 2026-09-07, saying it as a standing instruction: *"Do not simply open
> new tickets for the same issue and close the original ticket. The issue must be
> resolved in the proper way."*

The "A" in the count paragraph was a leftover from an earlier version's option
list (A a comment on the ticket, B a separate issue); the rule now says what
the letter stood for:

> one that files twenty-three and closes ten was choosing A
> too often

### What an agent definition said before it dropped its history

The passages below stood in code comments, a hook's docstring and an agent definition until the no-history rule removed them, verbatim.

#### .claude/agents/backlog-auditor.md -- Check 7, closing paragraph (deleted)

This check exists because the words got into the backlog faster than into the documentation: `#97 (The character editor tab gets taller as the UI font grows, so a large font stops the window fitting a 720-high screen)` and `#102 (A minimally-cached save cannot walk into an area, and the party is stuck where it stands)` were both filed by agents carrying language `AGENTS.md` had already ruled out, and nobody noticed until Donald read them.

#### .claude/agents/backlog-auditor.md -- Check 8, first paragraph (the closing quotation)

Original: A bare `#59 (Map the DOS saved game, not just the character record)` is an opaque number to anyone reading without a browser open, and Donald reads it that way: *"when you only reference a number, it never means anything to me."*

#### .claude/agents/backlog-auditor.md -- Check 8, second paragraph (the ruling)

**Issue bodies are exempt and are not a finding.** Donald ruled on 2026-09-01: *"Leave them alone. GitHub.com shows the ticket details on hover and makes it a hotlink, so it will be fine."* An issue body is read on the web, where the number is its own title to anybody with a pointer.

#### .claude/agents/backlog-auditor.md -- Two rules of this repository, first bullet (the date)

Original: `.claude/rules/issues.md`, rewritten 2026-09-09: keeping a label right is part of doing the work, ...

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

### What the rule files said before they dropped their history

The rule files state the rule and carry no history. These are the passages they held on this section's subject before that cut, verbatim.

#### AGENTS.md, opening paragraph after the routing intro

Cut clause (end of the paragraph beginning "Each trigger below is a situation, not an action"):

> -- that
> gap cost a decision twice on 2026-09-10.

#### .claude/rules/delegating.md -- "Choosing the agent"

The cost paragraph's quotation and date:

> Donald,
> 2026-09-04, of Fable, Claude Code's name for the tier behind both (Codex runs
> the same two agents on its own top tier, `gpt-6-astra`): *"consider
> deep-research and architect as available options to use when necessary. I
> don't want to waste tokens where another agent could do the job. But I don't
> think using Fable will run us out of tokens anytime soon."*

The incident that defined `deep-research`'s test (the rule now states the test
without the case):

> On
> 2026-09-04 the project had been reading a `.SPC` effect's duration of zero as
> "permanent", and SILAS turned up carrying two running spells at duration zero
> -- so the discriminator is not in the bytes anybody has been reading, and no
> number of further specimens says what it is. Reading the engine's own expiry
> routine does.

The widening of the `deep-research` rule (the rule now says the UNKNOWN clause
without the date or quotation):

> **Widened on 2026-09-05: an issue whose remaining obstacle is an UNKNOWN goes
> here by default.** Donald: *"Honestly, just use the deep-research agent to
> figure out the unknowns. That should help a lot. You can't use it for
> everything, but you could use it for the hardest tickets."* So the broken
> assumption above is a **sufficient** reason to route here rather than the only
> one, and a ticket that has sat because nobody could say what some bytes hold is
> this agent's work now.

Why `senior-analyst` exists:

> Donald, 2026-09-14: an orchestrator
> that finds a bug and files it needs a higher model to turn the ticket into a
> plan, and `architect` on Fable was doing that for bugs that did not need an
> expert. So:

The two issues that illustrated `junior-dev`'s filter:

> `#71 (Character draws on top of itself when the header is squeezed to its floor)`
> looked like ordinary work and took nine rounds and a `QTableView` subclass.
> `#73 (The DOSBox-X harness refuses to start without DOSBox 0.74, which it never runs)` named the two candidate approaches and said
> which was smaller, and that is what made it assignable.

#### .claude/rules/delegating.md -- "Writing the brief"

> Six agents each running all
> 3,190 tests is six copies of Qt on one machine, and on 2026-09-04 that cost a
> reviewer its run.

> and five agents ended turns that day waiting on runs that never reported.

#### .claude/rules/delegating.md -- "Commit, then review, then push"

In the rule, reworded ("has reported" became "can report"):

> it has reported a deliberate lever with a test and a docstring as
> dead code.

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
`pytest tests/pool_of_radiance/test_combatdrive.py` was green and `main` went red on all four
jobs eight minutes later. A scoped run is for working; it is not the check.

**A worktree run without the scratch-directory symlink lies by omission.** That directory was
gitignored, so a bare detached worktree skipped every test that reads a specimen
out of it -- 204 skipped against the working tree's 103 on 2026-09-02, and the
hundred that vanished were exactly the ones with real game data behind them.
With the directory linked the numbers matched to the test: 2783 passed, 103 skipped,
both ways. That gap is also the useful fact about CI, which has no such directory
either: the bare run is the closest thing to what CI will do, and the in-tree
run is what covers the specimen-backed tests. Neither is the whole check alone.

**`tools/pool_of_radiance/fightrun.py` shipped a hardcoded path, 2026-09-01.** It carried
`DISKS = pathlib.Path("/home/donald/c64/...")` and went red on all four jobs
against a suite that had passed twice locally. The cause is that
`tests/suite/test_repository_contents.py` walks the files *git knows about* -- the
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

### What the rule files said before they dropped their history

The rule files state the rule and carry no history. These are the passages they held on this section's subject before that cut, verbatim.

#### AGENTS.md, "Before you commit"

Cut, lines 263-266 ("The whole suite runs once..." -- the reason stays as a fact without the count or the date):

> **The whole suite runs once, in a detached worktree, before the push.** Six
> agents each running all 3,190 tests is six copies of Qt on one machine, and on
> 2026-09-04 that cost a reviewer its run. **One run, not six -- that is the
> rule, and who starts it is not.** Whoever is about to push either makes that

#### .claude/rules/commits.md -- "Before every commit"

The red-`main` incident under "Run the whole suite":

> `pytest tests/pool_of_radiance/test_combatdrive.py` was green and
> `main` went red on all four jobs eight minutes later.

The subagent-run incident:

> on 2026-09-04
> a reviewer's run sat producing nothing under that load and was abandoned.

(The sentence also said "Six agents each running all 3,190 tests"; the count is
dropped from the rule because it goes stale.)

The `test-runner` quotation and its cost:

> Donald, 2026-09-09: *"Every
> time I want to ask you a question, I have to wait for you to finish running the
> tests. Your job as orchestrator is to coordinate subagents and answer my
> questions."* Four minutes of a blocked window, every push, was the cost.

The prose-only-commit quotation and the "habit" argument:

> Donald, 2026-09-03: *"Waiting on a full test suite when
> you've only changed a markdown file is a real bummer."* Six and a half minutes
> of suite to prove a sentence did not break a parser is not diligence, it is a
> habit that costs a person their evening.

The string-literal warning, before it was shortened:

> a
> comment change is the one that gets waved through and turns out to have been
> inside a string literal.

#### .claude/rules/commits.md -- "Pushing"

The incident behind the push hook:

> On 2026-09-16
> the rule alone let eighteen pushes out with one run, and the batch that
> closed `#89 (Silver Blades' trainer grants spells from a table, and goldbox/levelup.py offers them from a menu)` turned `main` red on a test nobody in scope had run.

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

### What the rule files said before they dropped their history

The rule files state the rule and carry no history. These are the passages they held on this section's subject before that cut, verbatim.

#### testing.md

Each block is the original paragraph, verbatim, whose provenance was cut. The rule in it stays in the file in a shorter form. Suggested homes in docs/160: the font and constant paragraphs under "Testing" ("The font calibration", "A number measured on this machine is not a number"); everything from the specimen section on has no section yet and wants a new one, "A specimen is only evidence if we know who wrote it", under "Testing".

##### The largest font to test is +10 (testing.md lines 28-36 of the original)

> **The largest font to test is +10, and 9pt is the base here**, so the
> range is 9pt to 19pt, and `+6` matters most because it measures here about like
> Windows' base font. There is no layout problem at any font a person uses;
> somebody who needs text that large uses display scaling, which enlarges the
> window too. A test that only holds above +10 proves an artefact and will be
> true forever while catching nothing. If a claim is weak at a realistic font,
> say it differently rather than at a bigger font --
> `test_the_top_row_asks_for_more_than_the_page_makes_room_for` became true
> everywhere once it compared a *rate* across two fonts instead of a gap at one.

##### When a constant bounds something (testing.md lines 45-50 of the original)

> **When a constant bounds something, assert that it is bounded, not that it
> never moved** -- non-decreasing, and flat by the largest font. A machine whose
> base font is smaller than ours still climbs towards the cap; only a machine
> already at the cap sees no climb at all. Prefer the assertion that states the
> outcome a user cares about: "the window fits a 720-high screen at +6pt"
> survived both CI platforms where two structural proxies for it did not.

##### Where a test gets its data (CLAUDE.md corrected to AGENTS.md in the retained text; no provenance cut) (testing.md lines 85-86 of the original)

> `CLAUDE.md` forbids the game's data entering this repository, and a fixture
> that is a slice of a game file is the same copy under a new name. So:

##### The play directory is edited (testing.md lines 98-118 of the original)

> **`/home/donald/dos_por_play/SAVE/` is Donald's own play directory and every
> character record in it has been edited with Gold Box Companion's character
> editor.** Assume all of them, not the ones that look wrong. Donald,
> 2026-09-04: *"Assume all character records in /home/donald/dos_por_play/SAVE/
> were edited. Base your evidence and reasoning off saves you created
> yourself."*
> 
> **And it is not only that directory.** Donald, 2026-09-04: *"any saves you got
> off of any of the game disks might also have been edited."* His save disks are
> a player's disks, played and tinkered with over years. So the boundary is not
> a path -- it is **whether we watched it being written**.
> 
> **So a measurement rests on records we watched being written, and there is
> essentially one source.**
> 
> **Saves an agent made by driving the game**, from character creation onward.
> `tools/dos/dosgnome.py` is the worked example: it rolls a character in the game's
> own creation screens under DOSBox and reads back the bytes, and its five
> same-boot racial controls are what make a single reading a measurement rather
> than an anecdote. Donald, 2026-09-04: *"if we created our own characters and
> level them up, then you can know it is safe."*

##### A save found on a disk is not evidence (testing.md lines 120-127 of the original)

> **A save found on a disk is not evidence, however official the disk looks.**
> Donald, 2026-09-04: *"You shouldn't assume that saves you find on a game disk
> are 'saves shipped with the game by the manufacturer'. Some random person on
> the internet might have created those and edited them with GBC. You have no way
> of knowing."* The archives here are a download -- `~/Downloads/fr-archives`,
> "Forgotten Realms The Archives" -- so `Default files/Saves` has no chain of
> custody either. It was listed as trustworthy in an earlier version of this
> rule and that was wrong.

##### The encumbrance identity is not a provenance test: earlier-version account and both sweeps (testing.md lines 129-191 of the original)

> **The encumbrance identity is not a provenance test, and this rule used to
> treat it as one.** It said six of the eighteen records in Pool of Radiance's
> `Default files/Saves` fail `money + Σ(weight × quantity)` against the stored
> total, two of eighteen in the known-edited set, and reasoned from that towards
> a stranger's edited party. Both halves of that are gone:
> 
> * **The six were never there.** `tools/records/enccensus.py` swept every DOS and Amiga
>   record on this machine on 2026-09-07: **54 of 54 records the archives ship
>   balance exactly**, across four titles, and so do **34 of 34 readable Amiga
>   records**. Those files have not been written since 2026-08-15, and the reader
>   as it stood at the commit that wrote the sentence gives the same 0 of 18, so
>   it was not a reader fix either.
> 
>   **The two figures do not come from the same place**, and an earlier version
>   of this passage read as though they did. `~/Downloads/fr-archives` holds no
>   `.adf` at all: the Amiga records come from the disk-image directories
>   `automap/gamedisks.py` lists as its `amiga` candidates. The DOS figure is
>   pinned by `tests/records/test_enccensus.py::test_every_record_the_archives_ship_
>   balances_exactly`, so a reader change that brings the six back turns it red.
>   **The Amiga figure has no test**, so treat it as a measurement taken once
>   rather than a guarantee, and re-take it before resting anything on it.
> * **Failing it is the normal state of a record we watched being written.** Of
>   the 114 records here that miss, on the 2026-09-08 sweep, **110 are ours**:
>   90 by an exact multiple of 1000 gp -- Pool of Radiance's training fee, on
>   the ladder of `#249 (Build a DOS party from creation and level it ourselves,
>   so DOS measurements rest on records we watched being written)` -- 3 by the
>   Curse shop bug in `docs/125-bug-notes.md` N19, one at +109 by the hand-axe
>   purchase in `docs/213-the-dos-shopping-trip.md`, four at +200 by one Curse
>   run's 200-coin payment, and twelve by a 999 this ticket staged itself.
>   **Nothing in the never-watched corpus misses at all**, 0 of 46. That leaves
>   **four records and two characters**: GILES at -20 and ASTRID at -65, each
>   found twice, once in the edited directory and once in a copy. They are
>   the only two nobody can name an operation for, and 90 + 3 + 1 + 4 + 12 + 4
>   is the 114.
> 
>   **The engine rewrites the field when it rebuilds a character's derived
>   fields, and no routine that moves coins does that**, which is why the drift
>   survives a save: 270 of 270 records the ladder saved held the
>   number they were loaded with, 87 of them after the trainer had taken 1000 gp
>   in that same boot, and a record spoiled to 999 *before* a boot came back 999
>   through both a party-menu `SAVE CURRENT GAME` and a camp save. Only the one
>   character whose sheet `VIEW` drew came back holding the right sum, with five
>   untouched characters in the same save still at 999. **So one boot leaves one
>   fee of drift, and the ladder's climb to +11,000 is mostly our own
>   restaging** -- `tools/dos/dostrainprobe.install` moves stored encumbrance with
>   the gold it pokes, which is right for an input and is not the engine
>   agreeing with us. `tools/dos/dosencsave.py` is the tool, and `#323 (The
>   encumbrance identity does not survive the training fee, so failing it is not
>   evidence of an edited record)` has the runs.
> 
>   **Poke a field before the boot, or the engine never sees it.** That same 999,
>   written after `LOAD SAVED GAME` had already put the party in memory, came
>   back as the correct sum from every save -- which reads exactly like a
>   recompute and is the engine writing its own untouched value over our poke. A
>   staging that lands after the load has measured nothing.
> 
> So **a record failing the identity is not evidence that anybody edited it**,
> and neither is a record passing it evidence that nobody did. It checks our
> reading of the money block, the item stride, the weight offset and the byte
> order, in one sum, which is what it was built for and what it is good at.
> `#323 (The encumbrance identity does not survive the training fee, so failing
> it is not evidence of an edited record)` has the counts and the two records
> that miss the other way.

##### A tolerance is not a reading (corpus reworded, nothing else) (testing.md lines 229-231 of the original)

> **A tolerance is not a reading.** `assert exact >= total - 2` says our sum may
> be two-in-twenty-four wrong; it hides which two and why. Name the records, or
> point the test at a corpus where the answer is exact.

##### What is left is the rule (testing.md lines 239-242 of the original)

> What is left is the rule rather than the example: a save found on a disk has no
> chain of custody, and **staring at it does not say which**. The reason to
> distrust the archives is that nobody watched them being written, not a count
> somebody took once.

##### Records this project's own writers produced (testing.md lines 252-268 of the original)

> **Records this project's own writers produced** test the writer and are never
> evidence about the game, since they carry what we already believe. **Including
> saves a person edited in Wish.** Donald, 2026-09-04, of the C64 party on
> `P18PARTY.D64` (scratch, deleted) that `#10 (Finish the high-level test party)` drove
> through the training hall: *"I edited the C64 characters you mentioned with
> WISH. I gave them gold. I increased their ability scores. I changed the weight
> of their items."* Driving a party through the game does not keep it clean
> afterwards.
> 
> **But there is a distinction to hold on to, because it rescues real
> work.** Editing an **input** and then watching the game compute from it is a
> valid experiment -- the engine does not care how a byte got there. Reading back
> a **stored value that Wish wrote** and calling it the game's arithmetic is not.
> 
> So: raise a cleric's wisdom in Wish, drive the trainer, and what the trainer
> offers is the game's answer for that wisdom. Raise the weight of an item in
> Wish and read the stored encumbrance, and you have measured Wish.

##### A specimen dies with the emulator slot (testing.md lines 270-287 of the original)

> **A specimen dies with the emulator slot that made it.** `Session.stage()` is a
> `copytree` into the pool instance's own directory, and tearing the slot down
> takes the instance with it. On 2026-09-04 the only engine-written DOS
> item-granted effect record this project has ever had -- `CHRDATD1.SPC`, made by
> readying a magical item in the running game -- was reported at
> `cited/232/ready4/` and was gone from the whole filesystem an hour later.
> Its nine bytes survive only because they were quoted in
> `docs/162-spc-permanence.md`. **Copy a specimen out before the slot goes**, and
> put it in the tree below rather than anywhere in scratch.
> 
> **The tree is `$WISH_SPECIMENS`, default `~/wish-specimens/`**, outside the
> repository because the game's data must never be committed. `tools/registry/specimens.py
> add` copies a save in, records who made it and how, hashes every file and makes
> it read-only; `check` re-hashes and reports anything that moved; `list` says
> what is there. A file with no `provenance.toml` is not a specimen, and `check`
> says so. Donald asked for it in those terms: *"We could have a process or naming
> convention for saves that are JUST for your tests, so I'll know not to touch
> them."*

##### The cost of getting this wrong is silent (testing.md lines 295-301 of the original)

> **The cost of getting this wrong is silent.** On 2026-09-04 a single edited
> record -- SILAS, a *human* carrying two `.SPC` effect records where the engine
> writes a human none -- refuted "an effect at duration zero is permanent",
> stopped `#232 (An item-granted effect is dropped on the way through the
> neutral record, with no report)`, and sent a `deep-research` agent after a
> discriminator that may not exist. Nothing failed. The suite stayed green. It
> surfaced only because Donald happened to mention he had used the editor.

##### Two files can share a name (testing.md lines 303-312 of the original)

> **Two files can share a name and not each other's provenance.**
> `CHRDATA6.SAV` exists both in the archives, shipped, and in the edited play
> directory. A path finder resolves to one of them and the test cannot tell.
> **So say in the test where its specimen came from**, and when a finding is
> written up, give the corpus size *and* what the records are.
> 
> The same trap caught a census that was sweeping an emulator instance's staged
> tree, where the sweeping tool's own tampered probe records sat -- our bytes
> read back as the engine's. `tools/dos/dostailcensus.py` excludes what this project
> wrote, by name; copy that exclusion rather than reinventing it.

##### The way out (testing.md lines 314-323 of the original)

> **The way out, when no specimen can be trusted, is to read the code instead.**
> A finding taken from the engine's own instructions cannot be poisoned by an
> edited save. `#232 (An item-granted effect is dropped on the way through the
> neutral record, with no report)` was settled that way on 2026-09-04 after
> SILAS had misled it: the expiry routine at `GAME.OVR:0x23DCC` reads the 16-bit
> duration at record bytes 1-2 and nothing else, so duration zero is permanence,
> which is what the project had believed before an edited record refuted it.
> Watching the routine run confirmed it, and readying a magical item in the
> running game produced the engine-written specimen the corpus had never had.
>

### What tests said before they dropped their history

The passages below stood in code comments, a hook's docstring and an agent definition until the no-history rule removed them, verbatim.

#### tests/records/test_enccensus.py (docstring of test_every_record_the_archives_ship_balances_exactly)

```
    """`.claude/rules/testing.md` used to say six of the eighteen Pool of
    Radiance records in `Default files/Saves` fail the identity.  They do
    not, and neither does anything else the archives ship: 54 distinct
    records over four titles, 0 misses, measured 2026-09-07 (Treasures of
    the Savage Frontier's fourteen are skipped, having no layout here).  A
    reader change that brings the six back turns this red, which is the
    point of pinning it.
    """
```

#### tests/gamedata.py (specimens comment block)

```
# `.claude/rules/testing.md`, "A specimen is only evidence if we know who wrote
# it". A record found in a save directory -- Donald's play folder, the
# archives' `Default files/Saves`, a rip off the internet -- has no chain of
# custody, and on 2026-09-04 one edited with Gold Box Companion refuted a
# correct belief and stopped `#232 (An item-granted effect is dropped on the
# way through the neutral record, with no report)` for a day. `#246 (Nothing
# tells an engine-written DOS record from one edited with Gold Box Companion,
# and conclusions already rest on edited ones)` is the fix, and this is how a
# test reaches the clean corpus.
```

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
construction**, which is why `tests/convert/test_doswriter.py` masks by
`WRITE_UNSOURCED` and `WRITE_DEFAULTS` -- the lists the writer declares -- so a
new difference fails.

### What the rule files said before they dropped their history

The rule files state the rule and carry no history. These are the passages they held on this section's subject before that cut, verbatim.

#### conversions.md

Each block is the original paragraph, verbatim, whose provenance was cut. The rule in it stays in the file in a shorter form.

##### A conversion is between two ports of the same title (conversions.md lines 8-14 of the original)

> **A conversion is between two ports of the same title, and never between
> titles.** Donald, 2026-09-05: *"the user should not be able to convert a Curse
> character into a Pool character. The conversion is meant to be for the same
> title."* **The title is fixed and the port is what changes**: a DOS Curse save
> converts to a C64 Curse save or to an Amiga Curse save, and to nothing else.
> Donald, 2026-09-05: *"A DOS Curse save would be able to be converted into a
> C64 Curse save or an Amiga Curse save."*

##### The six directions (conversions.md lines 16-19 of the original)

> So the six directions of
> `#51 (Every permutation of DOS, C64 and Amiga, in both directions)` are six
> pairs of *ports*, each carrying whichever titles both ends can read -- not a
> grid of every title against every other.

##### The player still gets from one title to the next (conversions.md lines 21-28 of the original)

> **The player still gets from one title to the next, and the game does it.**
> Donald, 2026-09-08, giving the path this rule exists to protect: *"A user plays
> Secrets of the Silver Blades on the C64. They beat the game. They then load
> their save into Wish and convert into an Amiga save. They now have an Amiga
> Secrets of the Silver Blades save. They then load that save into Amiga Pools of
> Darkness, and the game itself converts it into an Amiga Pools of Darkness save.
> This keeps us from running into a whole class of bugs that would come with
> converting saves from one game into another."*

##### editor/convert.py already builds it that way (conversions.md lines 37-44 of the original)

> `editor/convert.py` already builds it that way -- a direction's destination is
> `games.by_key(deltas.key)`, the same title on the other port -- so this rule is
> here to stop somebody adding the other thing rather than to describe a defect.
> It also settles a question that
> would otherwise keep coming back: **a character who cannot exist in the
> destination title is not a case the conversion has to handle**, because that
> conversion is never offered. Pool of Radiance has no druids, and no Curse
> druid is ever asked to become one.

##### The standard is a perfect conversion (conversions.md lines 46-50 of the original)

> **The standard is a perfect conversion, and the player is never told about a
> drop, because a route that drops something is not offered.** Donald,
> 2026-09-08, deciding it: *"I want perfect conversions. We should not have to
> tell the player that anything is dropped, because everything should just work.
> We should keep things behind feature flags until they are perfect."*

##### Never write a sentence to the player (conversions.md lines 52-61 of the original)

> **Never write a sentence to the player in place of fixing the thing it
> describes.** Finding a condition the conversion cannot handle and reporting it
> is how a defect turns into furniture: the sentence ships, the bug does not get
> fixed, and the next agent reads the sentence as the design. Donald, 2026-09-10,
> on being shown two such lines: *"Things like this are WHY we have to remove the
> Convert dialog. Because the agents find a bug, and instead of fixing it, they
> want to write an excuse to the player and then they never fix it. It's not
> okay. We need it to be correct."* If a condition cannot be fixed in the session
> that found it, **file it and send the line to the debug log** -- the evidence
> stays, the excuse does not.

##### The same game on two platforms is the same game (conversions.md lines 63-70 of the original)

> **And the same game on two platforms is the same game.** Both ports run the
> same rules on the same content, so a magic-user memorises the same number of
> spells on the C64 as in DOS, and a title's spellbook holds the same spells on
> both. **A difference between the platforms in what a character may hold is our
> table being wrong until the engine's own code says otherwise** -- read the
> code, do not reason from a record, and do not encode the difference as a limit
> to warn about. #508 (A converted magic-user loses memorised spells on the way to DOS, because our table says a title has fewer slots than the engine gives it) and #509 (A converted spellbook drops ids the destination title is said not to have, though both platforms are the same game) are both that mistake, each found as a sentence
> shown to a player.

##### Exactly two states (conversions.md lines 72-78 of the original)

> So there are exactly two states a conversion may be in. **Perfect and
> offered**: its drop list is empty, and there is nothing to say. **Imperfect
> and behind a flag**: `.claude/rules/feature-flags.md` governs, and the flag
> comes off when the list empties. There is no third state where a route ships
> and apologises, and the Convert dialog carries no log of what did not survive
> -- that pane is gone, and it is what had been sending a wording decision to
> Donald every time a field turned out to have no home.

##### Removing the pane gives nothing up (conversions.md lines 88-95 of the original)

> **Removing the pane gives nothing up.** It listed only fields already in the
> neutral vocabulary, and every writer must account for all of those: each has a
> `field_disposition()` naming every field as direct, transformed or dropped,
> and a test goes red the day a field exists in `goldbox/neutral.py` and a
> writer has never heard of it (`tests/amiga/test_amiga.py`, and
> `goldbox/c64_codec.py`'s own docstring: *"this catches a name the writer has
> never been taught, which is the failure that rots silently"*). That is what
> proves a conversion perfect, and the pane never contributed to it.

##### What the tables cannot see (conversions.md lines 97-101 of the original)

> **What the tables cannot see is a field nothing has named** -- something in a
> save that no reader was ever taught to read. It is in no vocabulary, no
> disposition table, and was in no pane either, so this is not a cost of dropping
> the pane; it is the standing reason decoding work continues. It shrinks only by
> reading the record.

##### The byte-coverage audit (conversions.md lines 106-122 of the original)

> **A full byte-coverage audit of every save file on every platform was proposed
> on 2026-09-08 and Donald declined it.** The reasoning that led there is sound
> and is kept because it explains what the problem is: an unnamed byte only
> costs anything when a writer has to produce a container it did not receive,
> which is cross-platform writing alone -- editing a save in place carries opaque
> regions through untouched, and reading simply shows what can be named. What
> the audit would have added is a measurement nobody has: what fraction of each
> container we can name, per platform.
> 
> He declined it on cost. It was estimated at ten to seventeen new tickets, most
> of them for the two containers nobody has counted, and it would have made the
> backlog larger before it made any conversion better. **That is a decision about
> a programme of work, not about the technique**: measuring the unnamed bytes of
> one region, when a ticket needs it, stays ordinary work -- `#446 (The Amiga
> saved game's zero argument rests on three of the game's twenty-nine areas)`
> took one such region from 4,072 bytes to 44 in a night. Do not propose the
> audit again without a reason he has not already heard.

##### Reporting a dropped field internally is the minimum (conversions.md lines 124-131 of the original)

> Reporting a dropped field internally is the
> minimum; it is not permission to drop it, and "the destination has no such
> field" is not an ending either. Donald, 2026-09-04: *"We should not be
> dropping anything when converting a save. Anything less is a bug, and the
> feature flag cannot be lifted until that is true."* Told separately that a
> ring's effect could not reach the C64 and that the drop was therefore
> legitimate: *"everything must work."* A converted character wearing a Ring of
> Fire Resistance has to resist fire on the other side.

##### So the three reasons below (conversions.md lines 133-140 of the original)

> So the three reasons below explain why a field is not converted **yet** --
> they are not a licence, and a drop list is not a state a conversion is allowed
> to rest in. The first of them, "the destination has no such field," is a
> description of the destination as we currently understand it rather than
> permission to stop: if the destination has no home for something a player
> would notice, finding it one is the work. **Every entry on every drop list has
> an issue.** (`WISH_EXPERIMENTAL_DOS_IMPORT` came off on 2026-09-06 once the
> import's lists were clear; the rule outlives the flag.)

##### The standard is every direction, not the import (conversions.md lines 142-155 of the original)

> **The standard is every direction, not the import.** Donald, 2026-09-05:
> *"We should not drop any fields for any conversion in any direction. Unless
> the platform we are converting to doesn't support that field."* And, on why:
> *"People will abandon it and call it bad and buggy when they notice things are
> missing from their characters. It's not a functional solution unless it
> converts everything. Why would someone want only half of their stats
> converted? It makes no sense. No shortcuts."*
> 
> This was asked because the two rulings above had only ever been made about the
> DOS-to-C64 import, and the program keeps six more lists of the same kind --
> `dos.WRITE_DROPPED`, `WRITE_UNSOURCED`, `WRITE_DEFAULTS`, `c64_codec.READ_DROPPED`,
> `amiga_pod.POD_WRITE_DROPPED` and `amiga_later.LATER_DROPPED`. **They are all covered.** A list is
> not exempt because its direction is the less travelled one, and the Amiga
> lists are not exempt because they are the longest.

##### The one carve-out is narrow (conversions.md lines 157-167 of the original)

> **The one carve-out is narrow, and it is not the same as "we have not decoded
> it yet".** A field is legitimately unconverted only when the destination
> *platform* has nothing that field could be -- not when we have not yet found
> its home, not when the home is inconvenient, and not when the value is one we
> guess a player would not miss. The identity byte is the worked example and it
> went the other way: Curse and Silver Blades on the C64 never write the pair
> and nothing reads it, which looked like the carve-out, and the ruling was to
> **write it anyway** because the bytes are there and a later conversion back to
> DOS then returns the player's own number instead of inventing one. Donald,
> 2026-09-05: *"Yes, write the identity byte. No, don't tell the user about
> it."*

##### Two things that are not drops (conversions.md lines 169-175 of the original)

> Two things that are **not** drops and must not be counted as though they were:
> a field the destination recomputes on load, and a constant of the format. Both
> have their own lists (`dos_codec.DERIVED`, `dos_codec.CONSTANTS`,
> `dos_codec.WRITE_DERIVED`, `dos_codec.WRITE_CONSTANTS`) and each row carries
> the run that demonstrated it. When
> a long drop list is read against this rule, sort it before costing it -- most
> of what sat on the import list was never a loss.

##### A small table of numbers is a measurement (conversions.md lines 177-196 of the original)

> **A small table of numbers read out of the game is a measurement, not a data
> file.** `AGENTS.md` forbids committing the game's data files -- maps, tables,
> scripts, records -- as committed bytes. That ban is about redistributing the
> game, and a handful of integers with a note saying where they were read from
> is the thing the sentence after it asks for: *describe, cite, measure and
> generate*. It is the same class of thing as the byte offsets, field addresses
> and constants committed all through `docs/`.
> 
> Donald, 2026-09-06, on storing the fourteen head and twelve body art ids the
> DOS-to-C64 portrait conversion needs, rather than reading them off the
> player's disks every time: *"A table of 26 numbers doesn't break any rules.
> It's not art, it's just two dozen numbers."* And on why to do it at
> all: *"They are 40 years old and they are not going to change."*
> 
> **The line is drawn by what the thing is, not by its size.** Numbers and their
> provenance are a measurement. A block of the game's own bytes is a copy
> however short, and a sprite, a map, a script or a record stays banned at any
> length -- including as a test fixture. If a table cannot be written as
> numbers a reader could check against the game, it is the wrong side of the
> line.

##### Say converted, not carried (conversions.md lines 198-201 of the original)

> **Say "converted", not "carried".** Donald, 2026-09-04: *"When you say
> 'carried', you must mean 'converted'. I don't think carried means what you
> think."* The word is in this file, in `field_disposition` prose and in drop
> lines a player reads.

##### SUPERSEDED BLOCK, cut whole -- the drop pane and its rulings

The next eight sections (lines 203-273) are rulings dated 2026-09-04 to 2026-09-06 about a report pane in the Convert dialog that listed dropped fields. The file's own later text (lines 72-95, the 2026-09-08 decision: "that pane is gone", "the player is never told about a drop") and `editor/convert.py` lines 79-82 ("The report pane this paragraph used to name is gone (2026-09-10)") supersede them. They are cut from `conversions.md` as superseded text rather than as provenance, and are kept here as they stood.

##### What a player would notice decides what a player is told ... Silent is about the pane ... A silent drop is still a drop (conversions.md lines 203-225 of the original)

> **What a player would notice decides what a player is told.** Two things are
> silent for two different reasons, and only one of them is a measurement.
> 
> * A field the destination **derives** on load needs no line, and that
>   derivation has to be *demonstrated in the running game* first.
> * A field a player **would not care about** needs no line either. Donald,
>   2026-09-04, of the quickfight setting: *"The player will not care if
>   Quickfight isn't converted. Don't bother alerting on that."*
> 
> The second is his judgement rather than anybody's finding, so **it is not a
> licence to silence anything else** -- propose and leave it in place. The same
> instinct applied to a character's status would have hidden a dead character
> arriving alive, which is what `#235 (Two unattributed DOS byte ranges in the combat tail are dropped converting to C64, and nobody knows what they hold)` turned out to be.
> 
> **Silent is about the pane, not about the work.** Asked whether quickfight
> should therefore come off `#131 (Lift WISH_EXPERIMENTAL_DOS_IMPORT, which needs the import working for all three C64 titles)`'s list, Donald, 2026-09-04: *"I agree, we
> should try to convert it. We just shouldn't tell the player about
> quickfight."* So a field nobody would miss still gets converted; it just does
> not get a line.
> 
> **And a silent drop is still a drop.** It stays in `field_disposition` and in
> the accounting; `#131 (Lift WISH_EXPERIMENTAL_DOS_IMPORT, which needs the import working for all three C64 titles)` is blocked on it either way. Only the line in the pane
> goes.

##### A player is shown a dropped field unless the destination derives it ... supersedes his ruling of 2026-09-05 ... UNREPORTED_DROPS (conversions.md lines 227-248 of the original)

> **A player is shown a dropped field unless the destination derives it.**
> Donald, 2026-09-06: *"do not show dropped fields if they are derived in the new
> game. Show others for now. I will refine them as we go."*
> 
> **This supersedes his ruling of 2026-09-05**, which was *"I don't want the
> player to EVER see a message saying any field was dropped. The conversion needs
> to be perfect."* That sentence was made when the list held fourteen entries,
> nine of which turned out not to be losses at all. With those nine moved to
> `goldbox.dos_codec.DERIVED` and `CONSTANTS`, what is left is short enough for him to
> read and rule on one at a time -- and hiding it put an agent's judgement
> between him and his own program.
> 
> So `DERIVED` and `CONSTANTS` are silent, and everything still on `DROPPED`
> reaches the pane. **No agent decides that a player would not care about an entry**; that
> is the judgement he took back. `UNREPORTED_DROPS` existed to make exactly that
> call and is gone.
> 
> What has not changed: **a dropped field is still a bug**, and the pane is a
> working state rather than a finished feature. *"I will refine them as we go"*
> is a plan for the sentences, not permission for the entries -- an entry is
> removed by converting the field, not by wording it better. An agent polishing a
> drop line is usually an agent working on the wrong half of the problem.

##### The pane itself stays, and becomes a smaller one ... An earlier version said it was temporary (conversions.md lines 250-273 of the original)

> **The pane itself stays, and becomes a smaller one that says what Wish did.**
> Donald, 2026-09-05: *"you could reduce the size of the drop pane and make it a
> messages pane. It could say things like, 'Fixing Ring of Fire Resistance
> bug.' If we discover that it truly isn't needed, we can remove it then. But
> let's not plan ahead so far. Let's wait and see what we might need it for."*
> 
> So it turns from a list of what did not convert into an account of what
> happened. **And it is not there to be as small as possible -- a player wants
> to know what the conversion did.** Donald, 2026-09-05: *"The user will want to
> know details about the conversion. A messages pane with details about what
> happened can have value."*
> 
> So the test of a line is whether it tells the player something true and useful
> about their own save -- a repair Wish applied, a thing that did not fit and
> which of them they kept, what was read and what was written. **The test it
> must not fail is the one above it**: never a field we failed to convert, and
> never a memory address, a record offset or a script filename, which
> `.claude/rules/gui-text.md` keeps out of anything a player reads.
> 
> **An earlier version of this rule said the pane was a temporary state that
> would end with the flag. That was my inference and it is wrong; do not plan
> its removal.** The example sentence above is Donald's wording rather than
> approved wording, and `.claude/rules/gui-text.md` governs every string that
> ends up in it.

##### The one exception -- destination holds fewer things (quote paragraph) (conversions.md lines 275-280 of the original)

> **The one exception, and it covers every field alike: a destination that
> genuinely holds fewer things than the source.** Donald, 2026-09-05: *"If a
> limit is truly part of the platform's design, inform the user during the
> convert about the limit. Offer them a choice on which to keep and which to
> discard. It would be a limit of the platform, not something we just didn't
> feel like fixing."*

##### Limits table row for trait slots (cited #84 (Roll a gnome in DOS and read the two innate effect ids nobody has seen)) and the #113 (Play DOS Curse far enough to save a party with items) sentence (conversions.md lines 306-310 of the original)

> | C64 trait slots | 10, shared between racial effects and item grants | racial ids are 0-4 by race, CONFIRMED (`#84 (Roll a gnome in DOS and read the two innate effect ids nobody has seen)`: human 0, elf 1, half-elf 1, halfling 2, dwarf 4, gnome 4), so it needs a dwarf or gnome with **seven or more effect-granting items readied at once** -- **UNMEASURED** |
> 
> Measure per title before designing anything: `#113 (Play DOS Curse far enough
> to save a party with items)` proved this family is not uniform, its items
> being 67 bytes where the others are 63.

##### Nobody has measured it is not it cannot be done (conversions.md lines 312-320 of the original)

> **"Nobody has measured it" is not "it cannot be done", and saying so is how an
> agent gives up in a sentence that sounds like a finding.** Donald, 2026-09-05,
> on the combat icon: *"We absolutely can figure out how to convert combat
> icons. They are not that complex. What is the problem, exactly? Are there
> differing amounts of colors? Are there differing amounts of pixels? We can
> figure it out. Don't give up so easily."* So an UNKNOWN in a conversion is a
> measurement somebody has to go and take, named in numbers -- how many colours
> each side stores, how many pixels, which file the art is in -- and never a
> reason to stop.

##### Never tell a player something untrue about their own game (conversions.md lines 322-330 of the original)

> **Never tell a player something untrue about their own game to make a drop
> line shorter.** Proposed for the combat-icon line on 2026-09-05 and rejected:
> *"DOS has no combat art"*. DOS has combat art. What it does not have is the
> C64's **encoding** of it -- 18 `CHARPIC00` screen codes plus 18 colours out of
> the C64's own character set -- and the converter has no route between the two
> yet, which is `#130 (A converted DOS party arrives with six identical combat
> figures, not its own)`. Donald, 2026-09-05: *"DOS absolutely does have combat
> art. What does that mean?"* Compressing "no equivalent encoding" into "none"
> reads as a claim about the game the player owns.

##### A template is not one of the three reasons (conversions.md lines 343-350 of the original)

> **A template is not one of the three reasons, and "the template supplies it" is
> not an answer.** Building a converted save on top of a save the engine wrote
> means every byte nobody has decoded silently keeps a value belonging to a
> different party in a different place -- wrong data that looks right, and
> invisible because the file loads. Donald, 2026-08-26: *"We should not be using
> a template at all. We should block on not understanding everything and go back
> and understand what we need to. No more plugging in fake data to make it
> work."*

##### Test the empty and the extreme case (conversions.md lines 367-372 of the original)

> **Test the empty and the extreme case, not only the typical one.** A drop list
> measured survivable for a character carrying items said nothing about a
> character carrying none, which is where
> `#62 (A converted character who owns nothing gets a corrupt sheet, and DOS then
> invents a garbage item)` was found -- after the conversion had been declared
> proven.

##### A conversion is not proven until it runs (conversions.md lines 380-384 of the original)

> **A conversion is not proven until it runs.** Bytes matching is necessary and
> not sufficient: load it in the game, walk the party, and look at the sheet.
> Three faults this project shipped -- an AC of 9 displayed as 51, a dropped
> combat tail, and a garbage weapon line -- passed every byte-level check that
> existed.

## Documentation

**Documentation carries no history, 2026-09-19.** The READMEs, the code comments
and the rule files had grown long and were full of the story of how each thing
came to be: issue numbers, dates, what an earlier version did, who decided
what. A reader looking a file up wanted one sentence and had to read a page.
The rule since then is that a README row, a comment and a rule say what is true
now, and this document and the commit messages hold the rest. What the
READMEs held that a reader still needs is under "What the READMEs used to say"
at the end of this section.

**Thirty-two write-ups gone.** The scratch directory's `reports/` held 32 of them and all 32 are
gone; nothing recovered them, and 80 citations across 29 documents had to be
rewritten to say so. That is `#136 (Thirty-two cited write-ups are gone, because
the knowledge base pointed into gitignored scratch)`. The scratch directory was gitignored on
purpose, because the game's own bytes may not be committed -- but the
*reasoning* about those bytes is not itself game data, so a write-up that argues
from evidence to a conclusion belongs in `docs/`, cited by a path that survives.
`tests/suite/test_repository_contents.py` fails the build on any `work/` path in a
tracked file, and the directory no longer exists (since 2026-09-18).

**A README table that is only mostly true is worse than no table**, because the
gap is invisible. `tools/gui/livestrip.py` landing on `main` without its row is the
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

### What the READMEs used to say

The README rows were cut to one sentence each. What they said beyond that, and
still helps somebody using or changing the tool, is here, grouped by the README
it came from.

#### The docs index (`docs/README.md`)

###### The two design decisions behind the package split
The editor is a file tool with zero emulator dependency: it opens a `.D64`, edits the save, writes it back and never talks to VICE, so `editor/` imports nothing from `automap/`, `goldbox/` stays transport-free, and the whole file path works on a machine with no emulator. `tests/test_wish.py` asserts both halves: the editor tab is never handed the live target, and no file under `editor/` mentions `automap`. Live memory is a discovery technique, not something the editor promises: a watchpoint on whatever stores to the strength byte beats reading disassembly, which grew into the automapper, a shipped feature that lives in `automap/` so the first decision survives it.

###### The package layout, split along the packaging boundary
`goldbox/` is the file formats (D64, the 580-byte record, save games, item and spell tables), transport-free. `editor/` is the PyQt6 character editor over `goldbox/` alone. `automap/` is everything that reads a running machine. `wish/` is the one window: two tabs, the single shared live connection, the backend registry and `File > Preferences…`. `ui/` is drawing code both GUIs need. `designer` launches Qt Designer on `wish/window.ui`. `packaging/` holds the PyInstaller entry points and the Windows console-stream repair. `tools/` is discovery scripts, but `tools.wish` (the `wish export`/`wish import` subcommands) and `tools.generate.genui` (run at window startup) ship. `INDEX.md` covers this per directory.

###### goldbox/layout.py is the single source of truth for the record
A declarative table with every field graded CONFIRMED, PROBABLE or GUESS, asserting at import that all 580 bytes belong to exactly one entry. `20-character-record.md` is generated from it so the documentation cannot drift, and it has exactly one owner at a time, because several agents appending independently would fragment the schema. The generated pages are rebuilt with `tools/generate/gendocs.py`, `genitems.py`, `genspells.py`, `gentemplates.py` and `genmaps.py`; the item, spell, template and map ones need a game disk. Every other page is hand-written.

###### What the save files hold (settled)
`SAVEDGAME0` is a verbatim image of `$4900`-`$64FF`: a party header, a combat-icon table at `$4BE0`, twelve character slots of `$100` at `$4D00`, and an item area from `$5900`. Slots 0-7 are the party and 8-11 are used only in combat; the roster and icon table count eight, and the game refuses a seventh player character, so the rule is at most six player characters and eight in total. `SAVEDGAME1` opens with eight 32-byte roster blocks filling `$8300`-`$83FF` exactly, holding the derived combat numbers the record does not (armour class, THAC0, current hit points, movement, damage bonus); base values live in the record and current ones in the roster. The party header carries x, y and facing with the previous square and the game clock. The page at `$5500` is slot 8, the first of the four combat slots; after a fight it holds the monster, byte-identical to its `MON*` file bar two derived bytes. The spellbook is at `0x078`-`0x07E` and the memorised list at `0x020`. Items are 16-byte records (three word indices for the name, a 16-bit cost, byte `+4` the magic bonus, byte `+0` indexing the `ITEMS` table of damage, armour class, hands, range and class usage, byte `+5` a signed saving-throw bonus). Combat icons are 18 screen codes plus 18 colours, independently editable. The game accepts externally edited saves: no checksum, no validation, and the roster blocks are writable (an edited armour class and hit-point total show on the sheet and survive a save, so the game reads that cache and does not recompute over it).

###### Fields closed in earlier passes
Character traits are `0x0AD`-`0x0B6`, ten slots holding codes from the same namespace as the save's active effects. `0x0A0` is the current level, with drain state in `0x0A1`/`0x0A2`; there is no highest level attained. `0x073` and `0x0EB` are different fields: `0x073` is what the sheet prints and `0x0EB` is what the game ANDs against an item's class-usage byte. Saving throws are derived by a known rule: the class table row for the character's level, best number per column across every class held, minus the constitution bonus for a dwarf, gnome or halfling; 78 of 79 records satisfy it exactly.

###### Fields still open when this list was cut
The level-drain pair `0x0A1`/`0x0A2` is read from the drain and restoration routines but no specimen has been drained in play. Roster `+0x03`-`+0x05` is unknown; per-level spell counts agree with two saves level by level and the contradicting page was a stale cache. How the C64 applies racial modifiers to thief skills is unknown (the progression table is the DOS one; a dwarf thief matches base plus the published row in all eight columns, a gnome, halfling and half-elf do not; the C64's own modifier table would settle it; see `127-community-formats.md`). Whether `0x100` is a status enum is unsettled and `roster_in_use` stays PROBABLE. The save path itself (`LOAD/SAVE` on the disk) has never been disassembled because diffing two saves answers more than the routine. `SAVEDGAME1` past its first page is resident code and a graphics buffer, not save data.

###### Techniques that were written off and work
VICE monitor watchpoints work if the connection is kept open and `resume()` is used rather than closing it, because VICE re-enters the monitor on the connection that was live when it stopped. Driving the game to create characters works if names are typed lowercase: the name prompt rejects any byte at or above `$5B` and `xdotool` sent capitals as Shift+letter, `$D7` for `W`. Disk swapping works through VICE's text monitor `attach` command. See `70-driving-the-game.md`.

###### Two outside sources
`npc_party.d64` is a save found online with three PCs and five NPCs at levels 4 to 8: five of its eight records are the game's own `MON*` files and the one value that cannot have come from play is MAD MAN's saturated `$FFFFFF` experience. It bounded the roster at one page, settled character level, and seven of its eight records satisfy the saving-throw rule derived without them (`90-specimens.md`). `poolce.d64` is a listable 1989 BASIC character editor: every offset it pokes matches ours, it carries the item name table and 162 complete item records, and what its author could not find corroborates our layout.

###### Detail dropped from the row of each write-up
Each row now states what its write-up settles in one sentence; the counted evidence, driving notes and per-run figures stay in the write-up itself. The rows for 175, 177, 197 and 198 named the C64 Ultimate hang's reproduction (three stops in three runs, six to ten minutes each; about one read in a thousand triggers it, so tens of minutes) and the firmware versions (3.14 / FPGA 121 / core 1.47 and 1.1.0 / FPGA 122 / core 1.49); those figures are in `177-a-load-that-goes-wrong.md` and `197-duplicating-the-c64u-hang.md`.

#### `INDEX.md` and the package READMEs: goldbox, editor, automap, wish, ui, packaging

###### goldbox/amiga_adf.py
Every OFS structure was checked against the player's own Amiga disks before the writer was trusted. `verify()` could not reach a drawer's own header block until `walk_dirs` existed, because every directory the module wrote was the root, so a drawer with a wrong checksum used to verify clean. `make_dir` exists only so tests can write a save slot onto a disk this module formatted, with no game data anywhere.

###### goldbox/amiga_later.py
The Silver Blades map was checked against its DOS twin, since both ports ship the same six characters. Silver Blades alone packs its spellbook into 15 bytes of bitmask where DOS spends 117. The three names taken from `amiga_por.py` (`PorWriteReport` and the pair that re-cuts a ten-byte effect node) are facts about the Amiga rather than about Curse and wear its spelling because Curse is where they were decoded.

###### goldbox/amiga_pod.py
Every offset was read off the game's screen by writing probe payloads onto a copy of disk 3. The `POD_WRITE_*` names replaced `DIRECT`, `TRANSFORMED`, `DROPPED` and `field_disposition`, which read as the whole Amiga port's and had put one title's count in front of a reader as another's.

###### goldbox/amiga_por.py
The slot-letter array in `SAVE/save` was established by making the game save to slot `D` and then `B` and reading back `"AB D      "`. Three of the twenty `.spc` specimens carry an item-granted effect the neutral record has no field for, so the writer emits no node for it and `to_neutral` reports which effect went and whether it had a duration.

###### goldbox/c64_port.py, c64_save.py
`live_position` and `mode_flag` were removed from the registry class and live on `automap/c64.py`'s `C64Machine`, with no alias left in `goldbox`, because an alias would import `automap` from `goldbox` and `tests/test_wish.py::test_goldbox_imports_no_transport` forbids it. `goldbox/games.py` was renamed to `c64_port.py` so the platform is the prefix and the role is the noun, alongside `dos_port.py`.

###### goldbox/d64.py
The BAM layout, the interleave and the track order were read off the player's own fifteen save disks. Writing a real save's two files onto a blank built by `blank()` reproduces the disk the drive wrote everywhere except the slack in each file's last sector.

###### goldbox/dos_port.py
Pool of Radiance's 285-byte record was checked against 24 real specimens.

###### goldbox/geo.py
Five earlier readings of the GEO format failed because they conflated wall art with passability; the two are independent fields.

###### goldbox/iconparts.py
The game's icon editor offers 63 weapons, each drawing a different fourteen cells, and 23 large heads, seven of which are another head with hair added in the two cells some weapons cover. An unconstrained 18-cell free choice would offer about 10^43 icons, against the few thousand the game can make.

###### goldbox/icons.py
The combat-icon layout (18 screen codes then 18 colours) was established by diffing in-game icon edits.

###### goldbox/portraits.py
The two table readers find the menu by the structure of the run of numbers and by checking every value names art that is actually there. The C64's `HEAD2D` file is DOS's block 45 of `HEAD3.DAX`.

###### goldbox/world.py
The addresses of the site and impassable-terrain tables in `ECL19`/`ECL1A`/`ECL1B` were once written up in a scratch report that no longer exists, so recovering them means reading the ECL scripts again.

###### editor/convert.py
Problems reach the player by three routes. A real refusal (`CANNOT_CONVERT` or a `DosRecordError`'s own message, meaning a source the player chose and Wish cannot convert) and a name too long for DOS's fifteen-character field reach a modal `QMessageBox` (`_maybe_warn`). `NO_DISKS`, `NO_DISK`, `NO_FOLDER` and `NO_GAME_FOLDER` name a row the player has not filled in yet and reach no modal (`_SILENT_BLOCKS`), because the disabled Convert button already says as much and a popup on the field after `From` told the player of a mistake they could not yet have made. A magic-user memorising more spells than the destination title has slots, and a spell id outside the destination's book, are bugs rather than platform limits and go to the debug log with the drop list. The dialog has no report pane and no `Convert Log` heading.

###### editor/dosimport.py
The module was once its own window, `File > Import > DOS Save Folder...`; it is now only the helper `ConvertDialog` calls, and its two-modal presentation lives in `ConvertDialog`'s `_maybe_warn`. It kept its name because several tools and test files import from it.

###### editor/rosterview.py
The minimum width is a constant because the header does not scroll, so the roster's minimum is a lower limit on the whole window, and a font-metric minimum made the window's minimum width vary between platforms.

###### editor/roster.py
The columns (name, armour class, current hit points) were established by disassembling all 64 call sites into the game's string printer.

###### editor/partspicker.py
It replaced a per-cell glyph picker that could build a figure with two heads and no legs.

###### editor/traitpicker.py
The picker offers the whole table rather than the cut at id 64 in `docs/107-roster-and-notes.md` section 8.

###### automap/amiga.py
A poll costs ten to twenty-two seconds, which is why the Amiga tab refreshes slowly.

###### automap/busguard.py
On hardware the fastloader's resting value on `$DD00` is `$10` (the drive holding DATA); a guard that believed a single byte would never tick again.

###### automap/render.py
Wall art is only 0.960 reciprocal, which is why every edge is drawn from both sides.

###### automap/target.py
Each `resume()` costs about 14.3 ms of extra emulated time, per resume and not per byte.

###### ui/icons.py
The path table costs about 72 KB of source against a 405 KB binary font the packaging would have to know about, and holds thirty-eight game-icons.net glyphs, sixteen of them map-note kinds. Font Awesome's canvas is kept though nothing is drawn in it now.

###### ui/appicon.py
The `pointy-hat` tile is a stand-in until an artist's logo replaces it.

###### packaging/geniconset.py
No macOS build reads `assets/wish.icns` yet, because `wish.spec` has no `BUNDLE` step; the file is committed for the day one exists.

#### `tools/amiga`, `tools/records`, `tools/areas`

Each heading is one tool or theme. Dates and ticket numbers are dropped on purpose.

###### tools/amiga

###### Code-wheel and journal answerers (amigacursewheel.py, amigabladesjournal.py)

The arithmetic behind both prompts is copy-protection research kept in a separate private repository, which the tools reach at run time through `$WISH_CODEWHEEL` or the `codewheel` entry in `gamedisks.yaml`. Curse's reader fits the game's font at 3.6 to 4.0 captured pixels per Amiga pixel, and `winvm shot` of WinUAE's 720-wide window gives exactly 2.0, so the capture is scaled up by a whole number with nearest neighbour. The Silver Blades journal reader was written against FS-UAE, where the 8x8 character cell is 30.64 captured pixels; `winvm shot` grabs a 1920x1080 desktop where the same cell is 16, so the grid is fitted from the challenge's own inked rows and the fitted origin is handed to the reader. A `6` used to read as an `8` because 30.64 is 3.83 pixels per Amiga pixel, so some pixels were replicated four times and others three, and the reader's normalise-to-8x8 lost the one-pixel gap. The tool now samples each Amiga pixel's centre and replicates it a whole number of times to a pitch of 32: the four real challenge captures read 3 of 4 correctly at 30.64 and 4 of 4 at 32, and over 55 captures of the running game 5 challenge screens were answered, 50 other screens refused, with no false positive. Amiga Pool of Radiance's wheel screen takes a bare RETURN and Silver Blades asks a journal word, so the Curse tool is a no-op on the other titles.

###### amigacontainercheck.py

The check is the independent evidence that `new_por_savegame` writes the source save's own square, facing, clock, area and resident map rather than the one SSI shipped. Its two ends share no reader: the C64 payload is read by hand at `address - $4900` and the built container at fixed offsets, big-endian, rather than through `goldbox.amiga_savegame.por_word` or `goldbox.world_state`, so a container that agreed with the writer and not with the save would show up; `tests/amiga/test_amigacontainercheck.py` asserts neither reader names a library accessor. Three fields the writer declines to write are reported as declared rather than mismatches; outdoors it writes `$49C5` = 0 because a travel window loads a `SQRDATA` rather than a `GEO`, and leaves the indoor square stale. Eight C64 specimens were checked, 8 of 8 matching. The container is 13,141 bytes.

###### amigadrive.py

`winuae.ps1 key` presses one virtual key per call and each call is an ssh round trip through a scheduled task, so the tool saves the name-to-VK table and the waiting. It takes no lane claim because the claim `winuae.ps1` enforces has to outlive any one call. `NP8` forward, `NP2` about face, `NP4` and `NP6` the two turns walk a party in Amiga Curse and Silver Blades, measured on the status line. `UP`, `DOWN`, `LEFT` and `RIGHT` go in with `KEYEVENTF_EXTENDEDKEY`: without it `keybd_event` hands `VK_UP` the unprefixed scancode `0x48`, which is `DIK_NUMPAD8`, so an unextended `UP` was keypad 8 under another name and the driver had no way to press a cursor key.

###### amigaenum.py

It settled that the later Amiga titles number the nine character states DOS's way.

###### amigaglobal.py

`amiga68k.py refs` searches for PC-relative references, which is the wrong search on the Curse and Silver Blades executables: a variable is `d16(a4)` and a far call is `jsr d16(a4)` through a table of `jmp abs.l` entries, so `refs` answers "no PC-relative reference" for both. A linear disassembly of the 300KB code hunk desyncs: taken that way the five Silver Blades square globals came back with 0 references between them where there are 191. Scanning for the displacement word first found the step routine from the party's x byte, and its one caller from the jump-table slot.

###### amigalaterproof.py and amigalaterwrite.py

`--first <name>` is what makes the run a test: the writer's riskiest choice is a boolean chain head where `write_por` writes NULL, and a wrong head does not spoil one character, because the loader reads the whole party off one file descriptor and everybody after the bad one is read out of the wrong bytes. Both C64 saves the run converted from keep their only item-carrying character last, where nothing is behind him to be corrupted. `diff` masks by the lists the writers declare (`goldbox.amiga_later`'s four and `goldbox.dos_codec`'s six, mapped through the title's shift map), never by whatever happened to differ. `LATER_WRITE_DERIVED`, one of the four, is Curse's `thac0_current` and one `roster_tail` byte, which the engine recomputes on load. `amigalaterwrite.py --compare` marked the six shipped Silver Blades twins: 150 field comparisons, 0 differing.

###### amigalaterslot.py

The party of Curse and Silver Blades lives inside the saved game rather than in `CHRDAT` files beside it, so `porslot.py` does not fit. The three edits are each one thing a screenshot can settle: `--rename` is the cheapest proof the engine read the bytes, `--keep n` moves the count word and every later block boundary, `--strip-items n` makes the loader's test on the chain head decide. It built the five slots measured in `docs/165-amiga-savegame.md`, "What the running game did with one".

###### amiganodefields.py

It settled that nothing in either executable reaches offset 1 of an effect node, so the byte DOS keeps there has no reader on the Amiga. `amigarecordrefs.py` cannot answer the question for a ten-byte node: its fields are `$1` to `$6`, and `$1(aN)` matches 81 instructions in `/Secret`, none of which is a node.

###### amigaportraitmenu.py and amigaportraitresolve.py

The Amiga's eighth body is a different picture, not the same one renumbered: its `body.dax` holds `0D`, `18` and `22` as one repeated block, so there are 19 distinct bodies over 21 ids against DOS's 20. `--palette` finds the thirty-two `0RGB` words by the pattern of the fetch, since three `DATA` hunks open with a run of small words and only one is read a word at a time. The resolver's answer is CONFIRMED off the engine: all four references point one byte in front of a table, which is one-based indexing, each followed by `adda.l dn, a0` and `move.b (a0), dn` with the record's own byte in `dn`, so the byte is a position and the table's output is the art id. Generation produces menu positions under either reading, which is why no set of records could answer it. The resolving routine tests for zero and applies no other check, so an out-of-range value fetches unrelated data: 24 fetches body art `0x03` and 33 fetches `0x18` off an unrelated table, and nothing may rely on either.

###### amigarecordrefs.py

It found the Amiga ICON menu's wraps, both shipped inter-title importers and `icon_dimension`'s combat test. A two-byte displacement also matches by luck, so a hit is a candidate until the listing is read.

###### amigarecords.py and amigasaves.py

`amigasaves.py` wants files of exactly 288 bytes in a lowercase `save/` drawer, which the Curse and Silver Blades specimens are not, hence `amigarecords.py`. The Pool of Radiance specimens had been extracted into scratch, which was lost, so `$AMIGA_POR_SAVES` pointed at nothing and thirty-one tests skipped on the machine that holds every byte of them; both tools exist so the specimens are never only in scratch. Four rips of Pool of Radiance disk 1 and two copies of the Curse save disk are on the machine and all 38 files are byte-identical across them.

###### amigasavecheck.py

`--sweep` measures how wide the argument "no Amiga saved game here holds anything there" is: 108 of 2560 words are non-zero over the nineteen saved games on the machine, standing in three of the game's 29 areas, where a set of New Phlan saves alone would have missed 13 of them.

###### amigashots.py

Driving a Gold Box menu by hand is three calls a keystroke (`amigadrive.py` to press, `winvmsettle.py` to wait, `winvm shot` to grab) and yields a 720x568 Amiga screen inside a 1920x1080 picture of a Windows desktop. The client area is found by WinUAE's status bar, a band of the Windows control grey exactly `gfx_width_windowed` wide, then walking up off the bar's own raised edge; the height comes from `goldbox-a500.uae` rather than from where the window sat.

###### amigazerowords.py

Of 4,066 bytes the converted saved game writes as zero, the sweep found 2,033 catch-all words, of which 49 are written by any script, 29 only by scripts of unvisited areas, and 25 after the engine's area-entry routine and the arriving area's own entry-4 prologue are taken off; fourteen of the twenty-five are in the Temple of Bane alone. Scripts are mapped through the VM's three heap blocks rather than the file's contiguous `$4900`-`$52FF` naming, which had hidden every reference to `$6B00`-`$6EFF`. With `--engine`, the 203 sites that load a block pointer name 52 array words at a constant displacement. `--dos` adds DOS containers, which run the same scripts at the same VM addresses and stand in two areas the Amiga set does not.

###### fromamigapor.py

`--to c64` writes all 9216 bytes of `SAVEDGAME0` and `SAVEDGAME1` from two zeroed buffers through `goldbox.dos_codec.new_save_from`; the combat icon tables and `ANIMATE00` come off the player's own C64 sides. `--to dos` writes through `new_dos_save_from`, needs no C64 disk, and each character's combat figure crosses as the number the Amiga record already stores at the DOS offsets. `--against` is the C64 run's only comparison: 63 of 63 numbers on the `VIEW` screens matched the Amiga record on both VICE runs; the two DOS runs were read off `tools/dos/dossheetread.py` screenshots. Before this tool the six characters crossed and the game around them did not, so a party saved in the Slums at 21:22 arrived somewhere else at a different time of day.

###### fsuae*.sh and fsuaegdb*.py

The five probe scripts and the two build scripts answered whether the automapper can follow a live FS-UAE game on Linux, so Wish and the Amiga game run on one machine. `fsuaegdb.py` is the shipped command line built on `automap/amiga.py`; `fsuaegdbprobe.py` was the first standalone client and probe.

###### goldbox-a500.uae

`joyport1=none` because WinUAE's default gives Amiga port 2 the numeric keypad as a joystick and the later titles move the party on that keypad. `sound_output=interrupts` rather than `none` because `none` turns Paula off altogether and Silver Blades deadlocks on the party's second turn. `use_debugger=true` cannot work on Windows, so the F11 binding is the only way in.

###### m68dis.py and m68discheck.py

The disassembler refuses to guess because a made-up instruction in a string table is what gets believed and written into a document. A 68020 index extension and a branch to an odd address are legal encodings on real silicon; refusing them is a judgement that no assembler emits them, so a word carrying one is data. `--refs ADDR` is how the code that opens a `.pc` was found from the string alone. The verification against capstone 5.0.7 in `CS_MODE_BIG_ENDIAN | CS_MODE_M68K_000` covered 100,385 instructions of the Amiga Pools of Darkness binary: no length disagreements, no operand disagreements, nothing capstone decoded that it refused, written up in `docs/50-experiments.md`, "The 68000 disassembler". The checker runs both modes because capstone in 020 mode decodes instructions the target CPU does not have, so a comparison that does not name its mode says very little.

###### podimportmap.py and podpcregions.py

The importer routine at file offset `0x026000` of `/Pools of Darkness` on disk 1 is a field-by-field copy of 77 fields from a Silver Blades record, and `goldbox.amiga_port.SILVER_BLADES_DELTAS` names every source offset. It is the engine's own account of its record and cannot be spoiled by an edited specimen; seven of the nineteen `.pc` files on the machine come off cracked rips and none has a chain of custody. It found the spellbook (a sixteen-byte mask at `0x159`, where no byte-per-spell array could fit) and the combat block (split between `0x5E`-`0x5F` and `0x184`-`0x185`, so no probe for four adjacent bytes could have found it), and caught two wrong constants: `HP_CURRENT` is the byte at `0x191`, not the word at `0x190`, and `PORTRAIT_BODY` was `0x0B8`, which is `hp_rolled`. Six disk-1 images hold an executable and they are not all the same file, so `--check` takes the build the most agree on and prints the counts. `podpcregions.py` settled that Pools of Darkness shares Curse's and Silver Blades' item and effect node layouts: 19 of 19 `.pc` files on the four Amiga disk images balance `money + sum(weight x quantity or 1)` against the word at record `0x056`, 93 items, all three insertion pads zero, and the eleven effect nodes read `<id> 00 00 FF 00`, the same `INNATE_PAYLOAD` the DOS `.EFX` files hold.

###### porboat.py

There is no walk to the harbour master's pier: every route from the shipped slot's square crosses an event square and one runs `NEWECL 8`, which teleports the party into Phlan City Hall. So the tool edits the input and lets the engine compute the output. Eight bytes change: the square becomes `(11, 2)` facing north, because `ECL00 $9C43` opens `COMPARE [$C04D], 0 / IF<> / EXIT` and the harbour master speaks only to a party arriving from the south, and `$4AA7` becomes 255, because `$9C5C` sends a party below 254 to the free Sokol Keep ferry instead of a coastal passage. It does not stage `$4AC4`, the destination: `$9AF2 SAVE 0, [$4AC4]` is the first statement of New Phlan's entry-4 prologue, so a staged value is gone before the first keystroke, and a run that tried it sailed to Sokol Keep. The square comes from `GEO00`, whose only script id 2 is `(11, 1)` and whose only id 1, the boat, is `(15, 1)`; the Amiga's `geo.dax` block 0 is that file byte for byte past its two-byte header. These were the first Amiga saved games ever made outdoors.

###### porslot.py, porslotdiff.py, toamigapor.py

`porslot.py` reads through `read_por_slot` with no temporary directory. It put a slot list written by our code in front of the game's picker. On the game disk, `porslotdiff.py` answers `item_chain`, `heap_104`, `effect_chain` and five thief skills and nothing else in 1728 bytes of record (`docs/124-amiga-port.md` section 1.12a); on a `POOLSAVE` save disk it answers the same 57 bytes, which says the two routes are one conversion (`docs/191-the-amiga-save-disk.md` section 5). The NUL item display lines count is how `docs/182-amiga-por-in-the-running-game.md` section 2 watched the engine compose one. `toamigapor.py` built the two disks `docs/182-amiga-por-in-the-running-game.md` was measured on: six C64 characters and one DOS character, each loaded and drawn in Amiga Pool of Radiance under WinUAE. Before it, `porslot.py` only copied an Amiga slot into another, so every party in front of the Amiga picker had come off an Amiga disk. A slot is six character files plus a `savgam<letter>.dat` carrying the map, square and clock, none of which a character record holds; that is why `--container` exists.

###### winuae.ps1 and winuae-lanecheck.ps1

An Interactive task started with nobody logged on at the console runs nothing and says nothing, and a task started while its own last instance is still alive is ignored and hands the caller that instance's receipt, which is how a whole run reported success and produced empty dumps; so each call stops the task before starting it and matches a token of its own in the receipt. `clean` refuses while an emulator runs because unregistering the task would strand it where the only way out is killing by name. The VM is single-tenant: with one task and one process name a second agent gets the first's emulator, and before the claim existed a second driver's `stop` ended somebody else's session three times in one night. The claim is an atomic file create plus a read-back of the caller's own token, because six claims arriving together used to grant the lane to all six. A holder re-asserting a lane writes nothing, because deleting the file first left it reading free long enough for somebody else to take it. `send` reads `send.log` through a handle that shares the file with the injector, because an unshared `Get-Content` poll collided with the injector's `Add-Content` and killed it. Every refusal carries the `-Override` line because a lane whose holder has died is otherwise a lock nothing tells you how to open. `roms` points WinUAE's ROM database at `C:\Amiga\Kickstarts` so a person who opens the emulator is not told there are no Kickstarts. The lane check watched the earlier version fail: a second driver's `stop` ended the first's emulator 3 of 3 rounds, its `key` pressed into the first's game 3 of 3, its `start` was handed the first's emulator as its own success 7 of 9, and six simultaneous `claim`s granted all six callers the lane; none of those after the fix. The hijack round needs two calls to overlap inside the second WinUAE takes to become a process, so it reports whether it actually raced and fails when no round did. The `reclaim` round storms a holder re-asserting its own lane while three others claim, callers jittered so they do not fall into lock-step, because the fault is a two-millisecond window that 198 unjittered attempts never hit; it asserts both that nobody else gets in and that the holder can still re-assert, because asking only the first passed four times against a build whose every re-claim failed.

###### winuae-send.ps1 and winuae-sendcheck.ps1

The read path a `WinuaeTarget` rests on is `S <file> <addr> <n>` here plus an `scp`. The `--- exit N token=...` line carries the caller's own token so the caller can tell "still working" from "died before it started" and cannot read an earlier call's log as this one's. Arguments are checked before a console is touched because an unguarded `-File` killed the process with no verdict. PowerShell's host keeps a `CONOUT$` handle that `AttachConsole` leaves dead, and the first error it had to print killed the injector half-way through a batch, 4 of 24. `winuae-sendcheck.ps1` sends twenty eight-line batches: against the pair before the fix 1 of 20 died, against the fixed pair 0 of 20.

###### winuaepipe.py and winvmsettle.py

The pipe `\\.\pipe\WinUAE` reaches the debugger's command parser with no F11, no console window and no halt; anything that could reach `activate_debugger()` is refused because that opens a console in front of the player. A key pressed into an Amiga game while a disk loads is swallowed with no sign, and the steps take no fixed time: on one Silver Blades boot the credits took 47 seconds, the party menu 9, and `BEGIN ADVENTURING` 56 the first time and 129 the second. Two seconds between grabs is the shortest interval that works; below about a second the emulator's frame rate hands back identical pairs in the middle of an animation.

###### tools/records

###### boundarychars.py

A real party rarely sits near a limit, so the records that exist can say whether a conversion is faithful and cannot say whether it is safe; these cases push each field to its limit.

###### carryceiling.py

Of 950 characters on the machine, exactly one carries more than sixteen items, and it is the specimen this project built to make that happen; nothing anywhere wants more than five of the ten trait slots. The measurement decides whether a chooser for a full inventory is needed.

###### classcodecensus.py

8 of 30 C64 Curse records disagree and every one is a character Curse's own engine trained or dual-classed; 0 of 162 DOS Curse and Silver Blades records do. The four Pool of Radiance disagreements in the archives are all SILAS, whose level array holds a thief 1 his mask and code do not know. A dual-classed character's mask names two classes while the code names the one he is, which is why the mask is derived from the level array.

###### classcombocheck.py

0 disagreements in 132 C64 records and 228 converted DOS records in the specimen tree, 12 of them dual-classed. The stored `class_bits` and the bitmask the level array implies are equal on the C64, which is why the two answers agree.

###### classlegality.py

The two ports agree on all 37 entries over the 7 races; the legality table is at C64 `$0E64` and the DOS lists at `START.EXE 0x00f44f`. It differs from the racial level limit: the racial row gives a dwarf a cleric limit of 8, and no dwarf is ever offered CLERIC. Only a half-elf may be a cleric/magic-user, so only a half-elf can hold both spell lists at once, which answered whether a Pool of Radiance character can memorise more than the 21 spells its DOS record allots.

###### controlbyte.py

The low seven bits are a morale percentage stored halved. Result: 5 engine-driven C64 records against 1 DOS one (OUGO, `$B2`), and 291 of 297 C64 and 457 of 458 DOS records at `$00` or `$01`; this settled whether the DOS record holds the NPC flag the conversion reports as having nowhere to go. The DOS offset is the fourth byte from the end of `field_83_87`, which reproduces the four offsets `dosbyteimm.py` finds the compares at.

###### enccensus.py

The encumbrance identity does not survive the training fee, so failing it is not evidence of an edited record.

###### fieldcensus.py

The `c64` sweep goes by filename prefix rather than by directory because `por-c64/` in the specimen tree holds six Curse and six Silver Blades disks, and globbing it whole adds six records of another game's layout. The `monsters` set is 116 `MON<hex>` files. Result for `attack_level` at `0x098`: it is the fighter's level in 26 of 26 C64 records that have one and in 22 of the 23 `MON*` templates that carry one (`8TH LVL FIGHTER` holds 8), while 220 of 238 DOS Pool of Radiance records hold the constant 1, a party taken to fighter 8 through the game's own schools included. Curse and Silver Blades do maintain the byte, which is why one set of records could not settle it. Mixing the record sets is how a census lies, so each is named in the header line.

###### geoplausible.py

Two traps: excluding maps by filename misses the Amiga's `/SAVE/spindisk`, which holds all sixteen Curse maps verbatim, and sweeping a raw disk image catches sector-shifted fragments that cannot be excluded at all. The margin of a threshold is stated only by the worst real map beside the best non-map that clears the other three clauses. The measurement came from a plausibility check that threw out five of Pool of Radiance's own maps.

###### geoports.py

A DOS block is 1026 bytes and the engine's `Load3DMap` copies four planes out of it from offset 2, so the reader takes any block of that size and trims two. `00 04` is there in four of the six titles because their maps came from the same source as a C64 release; Treasures of the Savage Frontier and Pools of Darkness carry `00 00` and `cc dd` instead, so a reader that keeps only blocks with a C64 load address hides two titles' maps. Three of Curse's sixteen maps differ between the C64 and the Amiga.

###### infravision.py

Pool of Radiance's table at `$0E5C` and Curse's at `$0C4B` both hold 6, 6, 6, 6, 3, 6, 0 for races 1-7, so the halfling's thirty feet is the game's own number and not the sixty AD&D would predict. Staging a value the race would have produced anyway proves nothing, which is why `stage` picks one it does not imply.

###### spellbookcensus.py

Result: 0 of 567 Pool of Radiance records set spell 56, `RESTORATION`, in the book or in the memorised list, and every one of their 141 clerics carries a book, so the field is not the magic-user's alone. `--control` re-asks of 2,891 DOS record files, 1,808 of them Pool of Radiance; all 160 hits are Pools of Darkness, whose id space is a different game's, which is what makes "nothing anywhere has it" safe. The container of an Amiga saved game is picked with `detect` rather than by trying each, because the record signature is identical in both later titles and the wrong container yields six plausible characters rather than an error. The parent of each registered disk directory is read too, so the three C64 titles with no `gamedisks.yaml` entry are not silently missed. Rows are graded `built`, `spec`, `edited`, `found` over all the paths a deduplicated record turned up at, since the specimen tree has the provenance.

###### thac0census.py

The two ports disagree about a low-level magic-user or thief because they ship different THAC0 tables, not because either clamps or caches. The DOS table is located by the class-bit run right after it, eight bytes `02 20 08 40 80 01 04 10` occurring exactly once, so the read cannot agree with `goldbox/levels.py` by construction. Pool of Radiance's four sites in `GAME.OVR` all read `mul 11` at `DS:0x3C7C`. 190 of 190 DOS records and 148 of 158 C64 records reproduce, and all ten C64 misses are on the five disks Wish itself converted from DOS.

###### thiefskillcensus.py

The C64 and DOS builds of Pool of Radiance ship different racial adjustment rows: the C64's is the DOS one a byte short from the gnome's hear-noise column on, so its gnome, half-elf, halfling and half-orc thieves each read a row displaced one column. The DOS tables are located by the C64's own 72 bytes of level table, which occurs exactly once in each image. Two structural checks say the geometry is right: the human racial row is zeros and the dexterity rows for 13, 14 and 15 adjust nothing. Rules: 59 of 63 DOS records reproduce as level + race + dexterity clamped at zero, and 27 of 27 engine-written C64 records as level + race with no dexterity at all, matching `GEN $1FEC`.

###### traitnames.py

Spell rows are not evidence until their name is their own (`docs/171-c64-trait-slots.md`): `COMBAT2` gives one string to a spell granted at two levels, so a shared name is ordinary, but a row whose name pointer was never set reads as the table's first string and writes an id that has nothing to do with it; Curse has fourteen such rows and Silver Blades twenty. The per-spell record is `ECL65 +0` at seven bytes a record in Pool of Radiance and `COMBAT2 +2732` and `+2937` at nine in the later two. Results for Curse: 47 codes are written by a spell, 43 by a row in a spell group, of which 32 agree with `NAMES`, 8 contradict it and 3 (136 Entangle, 142 Fear, 143 Fire Shield) have no name in it; its 70 `MON*` templates carry 52 distinct codes, none of them 68 or 69, with thirteen landing on the same creature in both titles, twelve on a creature the Pool of Radiance name cannot describe, and eight that `NAMES` does not name. The reader checks itself against the Pool of Radiance census (116 templates, the `$FF` fill in 38, 121 on AHNKHEG, 127 on BASILISK and MEDUSA) and gives Silver Blades the 71 templates the doc already carries. Neither route names a code that no spell writes and no creature carries; `tools/c64/traitquery.py --handlers` does, and is the tie-breaker when the two disagree.

###### turncensus.py

210 records, 187 agreeing, and all 23 disagreements are converted parties this project wrote; the clearest is `WISH-SPEC-curse-trained-party`, where the two characters Curse's own hall trained carry the trainer's 7 and 5 while the untrained paladin still holds the conversion's zero. So a converter may compute the byte rather than copy it. `--dos`: eleven monster records in Pool of Radiance carry something at `0x076`, every one undead, and no player character anywhere; it is the undead's row, not the caster's.

###### tools/areas

###### areatable.py

It produced `goldbox.areas.AREAS_SILVER_BLADES` and `AREAS_CURSE`. Nothing is copied from Pool of Radiance: the opcode tables come out of that title's own `DUNGEON` through `newecl.py`, and the script load address is derived from the scripts, since the five `GOTO`s at the head of every one name addresses inside it and exactly one page boundary puts all of them inside every script: `$9900` in Pool of Radiance, `$8000` in Silver Blades. A sweep in address order both invents a square (Silver Blades' `ECL30` hands its entry-4 square to a `NEWECL` no path reaches from there) and loses one (Pool of Radiance's `ECL1B` writes two, because the Kobold Caves have two entrances). The propagation also carries the indoors flag to each `LOADFILES`, because the first operand names a `SQRDATA` and not a `GEO` when the flag is zero: 5 of 5 such loads across the three titles are Pool of Radiance's three wilderness windows, and reading them as maps had `ECL19` claiming `GEO04`, a castle level on a side it never asks for. `--check`: Curse agreed 25 of 25 and Silver Blades 22 of 22 on id, side and maps; Pool of Radiance, the control whose squares were recorded from driven arrivals, agreed on 30 of 30 sides, 27 of 30 map columns and 10 of the 11 arrival squares the walk names at all.

###### eclcensus.py

21 of Curse's 25 scripts are byte-identical to the DOS `ECL<n>.DAX` blocks of the same id, so the two ports name one address set, `$4B00`-`$4DFF`, with nothing in `$4900`-`$4AFF`; the quest-flag page is `$4C20`-`$4CFF` in Curse and Silver Blades, not the `$4A20`-`$4AF8` that Pool of Radiance's labels had been copied across as. This was the first step of converting a Curse DOS save into a C64 one. `--loadfiles` runs the walk and the raw scan so the two can disagree.

###### eclexitkinds.py

Exit kinds: `edge` 14 (entry 0's `$6DD5` gate), `square` 43 (entry 1's `ONGOTO`), `edge+square` 11, `square-via-entry0` 6 (entry 0's `ONGOTO` with no gate), `entry1-unconditional` 4, and `entryN` for the one dispatched off camping or loading rather than any square or edge (`ECL0B`'s `$A20F`), out of 79. Three of the four `entry1-unconditional` exits name the square by masking `$C04F` into a variable and testing it with `COMPARE` and a conditional jump rather than an `ONGOTO` arm; the tool once missed those. It answers "which handler" for running an exit's own handler before Fast Travel warps out: thirteen script/target pairs are reached by more than one exit and all thirteen collapse once the exit is keyed by square and facing.

###### eclflags.py

It replaces `reports/quest-flags.md`, which was lost with the scratch directory. `SAVE 250, [$4A04]` counts as a write and `COMPARE [$4A04], 250` does not.

###### ecllist.py

Built for the session driver that could not fight in Curse or Silver Blades. The operand kind byte says whether a store touches one byte or two: `$00` immediate byte, `$01` byte variable, `$02` immediate word, `$03` word variable, `$80` string. `--handler` settles "does `SAVE` into a byte variable clobber its neighbour" from the engine. On every Silver Blades save specimen on the machine, arms 15 and 16 of `ECL10` reach `COMBAT` with no open decision.

###### eclnpc.py

It decided which joinable NPC a driven session can reach most cheaply. Of the 3,481 bytes across the thirty scripts that the walk never reaches, none decodes as an `ADDNPC`, so the twelve `census` found are all of them. `ECL0B $9FEB` takes both operands from an eight-byte table at `$A23F`, the Training Hall's eight hirelings. The second operand folds as `DUNGEON` `$273D`-`$2759` does, `(n >> 1) | $80`, the byte stored at record `0x0B8`.

###### ecltext.py

Encoding: six-bit groups, most significant bit first, read out of the title's own `DUNGEON` at the handler its operand fetch jumps to for operand kind `$80`; a group of `$01`-`$1F` is OR'd with `$40` to land on `A`-`Z`, `$20`-`$3F` stands as itself, `$00` terminates. Checked on all three C64 titles. `eclcensus.py` prints a string operand as its byte length and so cannot say which line a screen came from.

###### eclwalk.py

It reaches 98% of all 178,035 bytes of the thirty scripts; a linear sweep runs into the data tables opcode `$2A` indexes and turns them into nonsense. It was rebuilt for `docs/150-departing-prologues.md` after `analysis6/ecl6.py`, which decoded all thirty to 100%, was lost with the scratch directory.

###### exitreentry.py and reentrypoints.py

`exitreentry.py` re-enters `DUNGEON` where a step would have arrived, with the stack rebuilt from the depth `$03BF` records, so an exit's own handler runs before a fast travel warps out. `reentrypoints.py` checks the five addresses that depends on with no emulator, so a change to those constants can be gated on it.

###### exitroute.py

It showed that `ECL07 $A904` is the endgame battle with Tyranthraxus rather than six `SAVE`s and an exit.

###### fasttravelpcwait.py

Its purpose is that the wait's time limit rests on how long a miss lasts rather than how often one happens; the Fast Travel button greyed itself out for a second while the party stood still.

###### fasttravelrun.py

It drives the shipped `FastTravel().run()` and not `exitreentry.py`'s hand-rolled `reenter()`. Only the Kobold Caves case has a save that exercises it and has actually been run.

###### geomap.py

`--find` is the anchor problem; it narrowed 29 files to a handful.

###### georesident.py

It is the measurement the tolerance in `automap.area.NEAR_ENOUGH` never had. The load count is the positive control and the store count is the measurement.

###### geowalk.py

Routing off the map the game itself loaded made a Curse shopping trip one walk rather than a search.

###### loadfiles.py

It made the question of Warping from the Slums to New Phlan drawing New Phlan with the Slums' walls a measurement rather than a disassembly. It was first written into a scratch directory, where a tool cannot be found and does not survive.

###### newecl.py

Pool of Radiance's documented values are all reproduced, including the two windows measured from 400 program-counter samples of an idle party; Curse went from UNKNOWN to CONFIRMED and Silver Blades to PROBABLE in one command each. No address comes from a PRG header: `DUNGEON` runs at `$0800` and the three titles' headers claim `$1000`, `$3000` and `$4000`. Each `DUNGEON` has exactly two self-modifying `JSR`s; entry `$20` of the tables it builds is the handler.

###### wallpins.py

Confirms that warping out of Valhingen Graveyard or Valjevo Castle leaves two wall pieces unrelocated. The faulty run is driven by building the write list here and removing one entry, never by reverting `automap/actions.py`, which several agents share.

###### windowsquare.py

The address of each window's impassable-terrain table was in `reports/world-map.md`, lost with the scratch directory, so passability is measured by walking. Both boat landings re-open TAKE BOAT / STAY every time the party is put back on them, and the first run read seven of window 26's eight directions as impassable when what blocked them was its own unanswered dialogue. The seed of `$49C3`/`$49C4` to (0, 0) is what keeps a stale overland square from being mistaken for an arrival.

#### `tools/` top level, `tools/c64`, `tools/github`, `tools/registry`

###### tools/ top level, tools/c64, tools/github, tools/registry: what the README rows used to say

###### How tools/ was assembled from scratch

The old scratch directory held 95 Python files. Nine were judged likely to be written again and became six tools (`combatshot.py`, `d6502check.py`, `m68discheck.py`, `overlay.py`, `rostercard.py`, `whatis.py`), fewer than nine because several files in one directory were one tool between them. The other 86 were a run's output: an emulator driver edited into its own successor, one window's measurement, a copy of a package file taken before a change. A second read of those 86 promoted six more (`bigfont.py`, `combatdiag.py`, `libslots.py`, `menucheck.py`, `monitorchain.py`, `wallsmap.py`), because each one checks a tool that ships or reads what one writes. The sorting question that held up is what the script points at: a thing in `tools/` or in the packages makes it a tool, one row of one issue's evidence does not. The scratch directory was then deleted and scratch moved under the temp directory (`tools/registry/scratch.py`).

###### tools/__init__.py, wish.py, wishagent.py, installdesktop.py

`tools.wish` is named in `wish.spec`'s `hiddenimports` because it is the body of the `wish export` and `wish import` subcommands and no static scan sees the import that reaches it; `tools.generate.genui` is imported directly by `wish/__main__.py`. `__init__.py` exists so that `from tools import anything` cannot leave a process with `tools/wish.py` where the real `wish` package should be.

`wishagent.py` mints a short-lived JWT from the App's private key (`~/.config/wish-agent/private-key.pem` by default) and exchanges it for an installation token on this one repository. It calls the REST API with `urllib.request`, never GraphQL and never `gh issue`'s own subcommands, which resolve labels through GraphQL where an installation token is accepted unevenly. Subcommands: `whoami`, `token`, `create`, `comment`, `close`, `label`, `edit`, `edit-comment`. `push-token` mints the second kind of token (`contents: write` and `workflows: write`) and `git-credential` is a git credential helper built on it: it answers git's request for `github.com` over HTTPS with the user `x-access-token` and a token minted for that request, splitting the request on newlines only. A push token is minted per call and cached nowhere. The private key is refused when group- or world-readable (skipped on Windows), the ordinary token is cached in the process and never on disk, and every body comes from `--body-file`. `docs/218-the-wish-agent-bot.md` has the setup, including resetting git's helper list.

`installdesktop.py` exists because Wayland has no protocol for a client-supplied window icon: the desktop matches a window to a `.desktop` file by application id and looks the icon up by name, so `setWindowIcon` cannot help. A wheel ships both files into `<prefix>/share`, which is on the search path for `pip install --user` and not for a virtualenv or a `pipx` install; this covers those, and `wish --install-desktop` is the same code from the command line.

###### abilitypair.py

Every specimen anywhere holds the two ability arrays (`0x014` and `0x065`) byte for byte identical, so no save can say which one the engine uses. `stage` writes them apart (`--set PHILIPPE:str=9/18`) so a boot can, and `read` prints both beside the bytes the engine derives: the carrying allowance at `0x0E2`, the dexterity index at `0x0EC`, and the strength-drain counter at `0x0FF` that Pool of Radiance spends on a portrait. The `0x0E2` line discriminates: it reproduces `LIBRARY $19EE` and prints what each array would have predicted. `refs` is the static half, a per-file census of both windows. Write-up in `docs/201-the-two-ability-arrays.md`.

###### absrefsweep.py

Used for the Curse DOS-to-C64 conversion: a census of `$4B00`-`$4EFF` over Curse's 411 files found zero references to payload `+$EA` (Pool of Radiance's disk hint), against five in Pool of Radiance, and found `+$EE` instead, read by `GEN $2008` on load and written by `CAMP $0C8D` on save. A hit is a claim about bytes and not proof they are code: without separating art files and `ECL<id>` script bytecode from the overlays, the same sweep reports 597 references that are bitmap byte pairs and VM operands. It also settled, on the code side, the roster bytes with no established meaning (see `rosterspellcount.py`).

###### bamsweep.py

The 1541 User's Guide prints two byte ranges for the BAM disk header that cannot both be right. Over the 79 images on the machine the shifted spaces are bytes 167-170 on 73 and the nulls run from 171 on all 79; every exception is a cracked or hand-built image whose header was rewritten. A formatted disk carries `2A` at 165-166 and nine of the 79 do not, which separates a drive's own work from a build script's.

###### c64addchar.py, c64addprobe.py, c64nametable.py

`c64addchar.py` watched what reads record `0x0E6`-`0x0E7` in the running game: three non-stopping load watchpoints at `$6BE4`-`$6BE5` (referenced by nothing), `$6BE6`-`$6BE7` (the pair) and `$6BE8`-`$6BE9` (experience, the positive control), through LOAD SAVED GAME, two REMOVEs, the add list, VIEW, SAVE and a walk; a block copy reads all three alike, so a field read shows on one. The staged `PORSAVE.D64` carries BRUTUS's record under MALCYON's name and MALCYON's record under the name TWIN, so one boot also shows the add screen tests the name and nothing else. Screens are kept as text and PNG beside `addchar.jsonl`. Write-up: `docs/170-c64-identity-pair.md`.

`c64addprobe.py` staged a disk whose file name and stored name disagree (`\x02ARDXYZ` holding a record that still says `ARDEN`) and the game offered `ARDXYZ`, confirming that the add list is built from the directory. A parked character on a Curse or Silver Blades save disk is a whole 580-byte record in a file named for him. Completing an add does not delete the source file: `tools/c64/c64addprobe.py --save ... --remove NAME` showed `\x02NAME` still in the directory after the pick, after `EXIT` and after `SAVE CURRENT GAME`, as the tool's docstring records. An earlier version of this entry called the question open; the docstring answers it. It boots through `tools/curse_of_the_azure_bonds/curserun.py` and photographs each step.

`c64nametable.py` settled that the `+$C00` name table on Curse and Silver Blades is not read by anything a player sees: `GEN` clears the block and refills it from the save disk's directory before every read. `sites` finds the six `$5700` instructions in `GEN` and names each by its loop and reads the filename prefix byte off the `S0:` scratch template. `--remove NAME` takes a character out of the party so the game writes the character file the scan then finds; `--resave` takes SAVE CURRENT GAME at the end, which is how the buffer was caught being stored as though it were a record.

###### c64clock.py

Settled `c64_port.SHOWN_CLOCK_OFFSET = 0xC7` against `c64_save.Container.clock = 0xC6` as two fields rather than a contradiction.

###### c64outdoor.py

None of the player's twenty Pool of Radiance save disks stands on the overland travel grid (every one reads `$49E6` = 1), so there was nothing to test the DOS converter's outdoor branch against. The tool seeds from an indoor disk, points it at a travel window with `goldbox.dos_codec.apply_file_cache` and `apply_position`, lets the party walk so the saved square is one the engine moved it to, and has ENCAMP > SAVE write the disk. `--saves` takes more than one. It reads the live travel square, the frozen dungeon square, `$49E6`, the loaded-files cache and `$033D`, where the eight-way travel heading lives: outside the `$4900`-`$64FF` a save images, so an outdoor conversion cannot store a facing.

###### c64portraitprobe.py

Settled the portrait half of importing across ports. `--words 49FF=0x81` and `--portrait SLOT=HH/BB` patch the staged save; `--poke 49EB=0` writes RAM just before VIEW, the only way to test a saved-game word the arriving area's script overwrites on load; `--prompt-side 3` answers the disk prompt with the side that carries every portrait. Evidence: PORSAVE12 with `$49FF = $01` fetched nothing and drew a blank sheet; with `$81` it fetched `$08`/`$07` for BRUTUS and `$09`/`$02` for MALCYON and drew the faces; a converted party staged with the six ids the patch would write fetched all six of its own. The cache is at `$6E13`, slot 14 holding the resident `HEAD<xx>` and slot 13 the `BODY<xx>`.

###### c64recordoperandsweep.py, recordsweep.py

Both are byte scans that do not follow the code. `recordsweep.py`'s census over all six C64 titles' disks found zero references to `0x0B9` and `0x0BA` in Pool of Radiance against 42 in Curse of the Azure Bonds, which settled that those bytes are documented as both an NPC marker and the dual-class slot because every specimen held is Pool of Radiance's, not because they mean the same thing. `--indirect` censuses the other way a byte is reached, `LDY #$ll`/`LDX #$ll` followed within ten bytes by the matching `(pointer),Y` or `(pointer,X)` opcode; it reproduces two hits each for `0x0B9`/`0x0BA` on Pool of Radiance and Curse, both inside picture files. That indirect scan had been run once by a script nobody kept before this tool restored it.

###### c64restinterrupt.py

`code` reads the gate out of the disks: `CAMP $1E0F` skips the whole check when `$6DD2` is zero, and `DUNGEON $10A1` zeroes the pair and then runs the area script's entry 2. It walks every area script's entry 2 from entry 2, so a conditional pair is reported as the values each arm reaches: six of the thirty areas can never interrupt a rest and two always can. It walks both arms of every conditional through statements that leave no trace and reports arms arriving at the same single statement: two of two in `ECL14`, none in the other twenty-nine, which is what tells a mistake from a design. `drive` claims a pool slot, checks the resident script against the file before believing anything, and counts passes, checks and interruptions with non-stopping VICE checkpoints while the party rests in two-hour blocks (one check per block when the pair is (24, 24)) with the murder flag clear, set, and set with the chance held at zero. The rest duration is written into `CAMP`'s own `$2898`-`$289A` rather than driven with INCREASE, whose step grows while the key is held.

###### c64savescan.py, c64savespells.py, livelevel.py

`c64savescan.py` answered whether any party already had a cleric high enough for the spell whose party effect is computed every poll and shown nowhere, before `livelevel.py` raised one; `c64savespells.py` is its detail view (defaults `NEWSAVE6`, `NEWSAVE5`, `NEWSAVE3`, `PORSAVE13`, `PORSAVE14`). `livelevel.py` writes experience before every level because the trainer clamps it, which otherwise leaves a character one point short of the next threshold; what it leaves is doctored, since the levels are real and unpaid for.

###### c64sheet.py

The mirror of `tools/dos/dosdisk.py --sheet`, `tools/curse_of_the_azure_bonds/cursedisk.py --sheet` and `tools/secret_of_the_silver_blades/ssbdisk.py --sheet`, which read a DOS folder; checking a C64-to-DOS conversion the way `.claude/rules/conversions.md` asks (every field on the destination's own sheet against the source) needs a sheet for the C64 side. It works for all three titles because `goldbox.savegame.load_save` identifies the title from the disk's directory, and every field comes through `goldbox.c64_codec.read`, the reader `goldbox.dos_codec.new_dos_save` uses, so a difference from the DOS sheet is the writer or the engine and not a second reading of the bytes. Item names come off the player's disks through the registry and are skipped when none are present. The six Curse sheets it printed closed the C64-to-DOS row for that title and turned up the question whether the Curse engine reads `thac0_current` in a fight, since the training hall overwrites it with the base and loses the strength bonus.

###### c64splicechar.py

`goldbox.dos_codec.to_c64_record` builds the 580-byte record and its four per-slot regions go where `goldbox.dos_codec.convert_save` puts them: the record at `$4D00`, the roster block in `SAVEDGAME1`, the sixteen item slots at `$5900`, and the combat icon at `$4BE0`, left as the disk had it unless `--icon default`. It made the gnome that proved the four innate effect records a converted gnome needs.

###### c64strength.py

`LIBRARY $375C` gates the strength adjustment tables on record byte `0x0E3`. One boot puts the same converted character in five party slots that differ in that byte and nothing else that reaches the recompute, which says whether the flag is what a player sees.

###### c64todoswalk.py

Replaces `tools/convert/convertrun.py`'s automatic step count for the walled New Phlan start of the `C64ToDos` walk. It turns the party about and steps up to eight times recording each attempt's screen digest, then saves over slot D with the engine's own save and keeps the files.

###### c64u.py, c64ucompare.py, c64uhang.py, c64uload.py, c64uplay.py, c64urest.py

The C64 Ultimate is an FPGA recreation rather than an emulator, so a reading off it is independent of VICE; that is why it is driven at all. `c64u.py` wraps the `c64u` CLI, mounts a disk staged into the temp directory, reads memory over DMA, takes a paused dump with the bank state in a JSON sidecar (bank state cannot be measured there: `$01` reads as the RAM under the processor port), replays the automapper's own two poll blocks so a hardware reading is comparable with a VICE one byte for byte, times a hundred of those polls, and probes whether a stage drains the KERNAL keyboard buffer at `$00C6` or polls the matrix. It refuses `config save-to-flash`, `load-from-flash`, `reset-to-default`, `machine poweroff`, `streams` and `ui` before they reach the wire, and `paused()` resumes from a `finally` so a failed dump cannot leave the machine held. Exit 3 means no device, so a script can tell "no hardware" from "the hardware disagreed".

`c64uhang.py` reproduces the load hang with a generated disk holding one BASIC line (`10 LOAD"HANGDATA",8,1`, which restarts and loops) and a 4 KB zero-filled data file, both built in-tool so nothing copyrighted is committed. A hang is a jiffy at `$00A0` frozen across the end check, never a `$DD00` value. `sweep` raises the read size until a run hangs; on a hang it captures the screen, zero page and stack, both CIAs and the VIC and resolves the stack's return addresses against a KERNAL ROM (`--kernal`, capstone's MOS65xx backend). A `get` variant uses `OPEN`/`GET#`. It refuses to boot with the speaker on and resets to `READY.` after.

`c64uload.py` boots `POOL1.D64`, answers the fastloader prompt, applies a treatment (nothing, as the control; one `readmem` of a chosen size at a chosen interval; Wish's own tick as `tests/test_issue286a2.py` measures it; or a DMA-free route) and judges by the jiffy read twice ten seconds apart, since `$DD00 = $C4` is the commonest healthy value and decides nothing. It never samples `$DC0D` (a DMA read of it acknowledges CIA 1's interrupts), fits wall time to jiffies on a hang, captures ten regions plus the loaded-files cache, treats a lost request as a blip and quits only when the device stays silent. `stress` loads the HTTP service with no boot, for the REST service that stops answering under sustained polling.

`c64uplay.py` adds four things `c64urest.py` lacks: a key that is waited for (a `$00C6` returning to zero means the stage reads the KERNAL buffer and can be driven; a count that stays means it polls CIA 1's matrix and cannot), a screen polled until it matches or stops changing, a burst capture of every differing frame at about five a second over WiFi (too slow to see one frame of corruption, as its manifest says), and `hangwatch`. The ten regions dumped are the screen, colour RAM, zero page and stack, `GDRIVE` at `$C000`, the `DUNGEON` overlay, the character-record buffer at `$6B00`, the save image, `ITEMS`, the VIC and both CIAs, each identified in `docs/177-a-load-that-goes-wrong.md`. It writes nothing but `$0277`/`$00C6`.

`c64urest.py` exists because the C64 Ultimate tab in Wish needs `urllib` and `ftplib` only on a player's machine. It remounts an image already in the device's `/Temp` by path so the game's own writes come back instead of a stale local copy, boots a title by extracting its first PRG locally and POSTing it, fetches over anonymous FTP because no REST route returns a file, and sweeps `/Temp` to see what the firmware evicts. Reading screen RAM and writing `$0277`/`$00C6` (to watch a boot and answer `DISABLE FASTLOADER (Y/N)?`) are outside the tab's allowlist and live in the tool alone. It touches none of the routes `c64u.py` refuses.

###### coldread.py

Every table is found by the instruction that reads it rather than named by an address, so the same four questions can be asked of Champions of Krynn, Death Knights of Krynn or Gateway to the Savage Frontier and either answer or say they did not. It knows `GEN` and `CAMP` run at `$0800` while their PRG headers claim four different other addresses; `--base` is for a title where that stops holding.

###### combatdiag.py, stepcheck.py

`combatdiag.py` logs, for each turn, every candidate square `step_towards` looked at with its terrain byte, occupied bit, occupant and reach, beside the key chosen, plus the whole terrain grid, every bar waited for and how long it took, and every key sent. It diagnosed both a driven character passing its turn next to an enemy instead of attacking and a driven character walking into rock because `step_towards` never read the terrain. `stepcheck.py` asks the same question offline (which square would be picked); `combatdiag.py` records what the live machine did. `stepcheck.py` began as a prototype in a scratch directory, now deleted.

###### combatsigs.py, latercombat.py, laterbattle.py, laterfight.py, laterrolls.py

`combatsigs.py` re-derives each title's `COMBAT` addresses instead of carrying Pool of Radiance's across: the message printer by its `LDA #$0A / STA <window top>` skeleton, the four text-window bytes by the `STA $07 / STY $08 / JMP / LDA #lo / LDX #hi / JMP` thunk (in Curse and Silver Blades that thunk is not in `COMBAT` but in `ECL64`, resident at `$8000`), and the message-delay byte by its `LDA abs / BEQ <RTS>` gate. It prints every delay candidate because the gate's structure is not unique in a 9K overlay.

`latercombat.py`: `CombatMemory`, `BY_KEY`, `memory_for` and `read_battle` moved into `automap/combat.py` because `automap`'s combat window and log want the same table and a second copy would drift; the module keeps the derivation write-up and re-exports them so `session.py` and `laterbattle.py` need no change. Two of the six addresses are not per-title: the parameter block is `$0600` and the camera `$037E` in all three, because `GDRIVE00` names the same twenty addresses in every one of the three binaries. A title nobody has run under a monitor gets None rather than Pool of Radiance's addresses, since an unmeasured address reads as a plausible fight instead of an error. Derived from the titles' own files, then read off a running Curse.

`laterbattle.py` boots, loads through the game's own front end, walks Curse to Tilverton's tavern over the area's `GEO` and presses PUNCH BARKEEP; Silver Blades has no such square, so `--title ssb` walks and waits for a wandering monster. It then probes the mode byte, the `$0600` parameter block, the camera, the position page, the roster page and the initiative table, raw, plus what `Session.battle()` makes of them; the probe is taken in the world first as a control, because a page that reads plausibly outside a fight proves nothing inside one. `--accept` takes the YES half of a script's own YES NO bar. The walk is `tools/curse_of_the_azure_bonds/cursethac0.py`'s, subclassed rather than copied.

`laterfight.py` runs over a served session's command port because those two titles boot through `tools/curse_of_the_azure_bonds/curserun.py` and `tools/secret_of_the_silver_blades/ssbrun.py` and are already serving once a party is in the world. It handles four things `tools/pool_of_radiance/fightrun.py` does not know: `I J K M` arrive only through the KERNAL buffer; the status line is stale, so a step is judged by the live triple at `$C04B`; a step that goes nowhere is usually a script menu, and walking back into it spends the budget on one shopkeeper; Return on a combat bar is not read from XTEST either, so `press_bar` walks the highlight by colour RAM and presses `kernal 0D`. `--survey-bars` is how TURN on a converted paladin's bar became a measurement.

`laterrolls.py` reads both addresses before combat, on first reaching the combat map and after every `QUICK`-resolved turn, so a change is seen against a baseline.

###### d64census.py

Read to rule out the disk header as a title marker: `MAKE SAVE GAME DISK` sends `N0:SG,Q9` in all three C64 titles, so the header never names which one formatted the disk. `header` counts the name at track 18 sector 0 + `0x90` and the id at `+0xA2`; `files` parses every PRG as a `CharacterRecord`, keyed by its one-byte filename prefix (`$01` Pool of Radiance, `$02` Curse, `$05` Silver Blades; `docs/216-the-c64-name-table.md`). The trigger was a Curse or Silver Blades character disk read with Pool of Radiance's tables, so a paladin's class showed as 64 and a dual-classed character's former class disappeared.

###### d6502.py, d6502check.py

`d6502.py` was rescued from a scratch directory, where it supported the combat-rolls research (`docs/147-combat-rolls.md`) by turning `COMBAT` and `LIBRARY` into readable listings. `d6502check.py` has to be rerun whenever the hand-typed opcode table is touched, because a wrong mnemonic in a listing is what gets believed and written into a document. It catches real faults: an old copy of the table had `SBC` where `$F6` is `INC`, and the table sweep names it. `BRK` is excepted by declaration (`docs/148-d6502.md`).

###### diff.py

The workhorse of the discovery phase: save, change exactly one thing in game, save again, diff. The unknown-region hits are the ones that name new fields.

###### dualclassagain.py

`dos` installs one slot of a save tree whose character is already dual-classed, pokes the training hall's maximum level at `SAVGAM+0xD51` so the party menu carries HUMAN CHANGE CLASSES wherever the party stands, and either sweeps the roster highlight a character at a time (DOS Curse, where the item is enabled per selected character at `GAME.OVR 0x20243`: six characters, one save, the line missing for the one dual-classed human and the one elf) or presses the command itself (DOS Silver Blades, where the item is always drawn and the refusal is inside the routine at `0x3CDAF`). `--from-slot` is not cosmetic: Silver Blades will not load a save installed under a letter other than the one it was written as, twice out of two. `--burst` shoots as fast as `import` runs straight after a key, because a refusal that prints and times out is gone before a `settle` returns. `c64` boots Curse or Silver Blades on a pooled VICE slot and would do the same, but has never got a save loaded; its docstring lists what was tried and two settled facts about that front end: the party menu's highlight is the colour RAM at the label's own column rather than a row's dominant colour, and Return is read from the KERNAL buffer only. `--gate-off` writes `NOP NOP` over the branch that refuses (Curse `GEN $2396`, Silver Blades `GEN $1F8B`) so the refusal can be shown to be that instruction; it has not been run. Write-up: `docs/176-changing-class-twice.md`.

###### hallmenu.py

Used to show that the training hall's own TRAIN CHARACTER question comes back in a converted save made in the hall. `savecheck.py` could not: its walk loop re-sends a move until the status line changes, and the hall answers a step with a room description, a `PRESS <RETURN>`, a load and two YES NO questions, none of which is a status line, so six moves came back blocked at about 118 seconds each and read like a hang. This presses the key once and reads whatever screen is there, saving a `.png` and the twenty-five text rows for each distinct one and classifying row 24 as `world`, `yesno`, `press`, `movebar` or `bar`. `Session.handle_prompt` runs first, because `INSERT SIDE # 3` wants the side attached rather than a keypress. The game's own words go under the temp directory and never into the repository.

###### inventorycheck.py

Corresponds to `docs/139-per-title-validation.md` A13 (inventory edit, add and remove) for the two later titles. `stage` makes all three edits through `EditorBinding.delete_item`, `InventoryModel.setData` on the quantity column and `EditorBinding.add_item` with a record copied off the player's own disks, never a writer of this file's own, and reports the whole item block before and after straight out of the payload rather than back through `editor.inventory`. `run` claims a pooled VICE slot, reads the title off the save, boots through `tools/curse_of_the_azure_bonds/curserun.py` or `tools/secret_of_the_silver_blades/ssbwarp.py`, finds the character on the party panel and takes VIEW to the item list, writing one JSON line and a photograph per event. `as_drawn` shows what the C64 makes of a name with lower case in it (`Guy de Valois` draws as `G59 $% V!,/)3`, each lower-case letter being the glyph at its code minus `$40`); without it a save converted from DOS matches nobody on the panel.

###### laterthac0.py

`tools/records/thac0census.py` anchors on the eight class bits after Pool of Radiance's table (`02 20 08 40 80 01 04 10`); Curse and Silver Blades carry a different permutation, so it exits with "the class-bit anchor occurs 0 times". This tool locates a table without knowing a THAC0 number: the stride and DS offset come from the engine's own `mul`, the row count from the width of `class_levels` in `goldbox/dos_port.py` (7 for Silver Blades, which drops the monk), and the block is the one maximal run of bytes in 30..70 that long; then `block - DS offset` must be a paragraph boundary and the class-bit array must follow it. Pool of Radiance is the control, where it lands on the byte the class-bit anchor finds. `writers` prints every `GAME.OVR` instruction touching `thac0_base`, which showed that each engine stores a flat 40 from a block of new-character defaults, that Curse's importer copies the byte straight out of a Pool of Radiance record, and that nothing anywhere compares the field against a constant. Results: 202 of 202 Pool of Radiance records reproduce, 77 of 86 Curse and 72 of 74 Silver Blades, every miss a magic-user no rebuild has run over. `docs/210-the-later-titles-dos-thac0.md`.

###### libslots.py

Generates the table `docs/140-loaded-files-cache.md` carries, so it can be re-read rather than trusted; the stems come out of the file too, which is how the stem numbering turns out not to be the slot numbering.

###### livewatch.py

Named the disk-swap prompt at `$453B` and the byte it waits on while getting one Curse session to a party with items.

###### loadrace.py

Tested the suspicion that a stray keypress within 0.2 seconds of the picker loading collides with the LOAD SAVED GAME: YES bar. Refuted: the confirm screen carries no disk-prompt text, so `handle_prompt` cannot fire on it.

###### memorisedwidth.py

Reproduces the two widths measured by hand for Curse's conversion (Pool of Radiance 81 slots at `0x020`, Curse 69 at `0x020`), which makes the third believable: Secret of the Silver Blades is 74 at `0x01B`, the only measured title whose list does not start at `0x020`. It answers what a save disk could not, because no C64 party on the machine has more than three spells prepared.

###### menucheck.py

Nothing offline can ask these questions, since a bar's highlight is colour RAM on a live screen. The defect it guards was `select_bar` matching a word by where it started rather than by which word the highlight covered, so CAST reached VIEW. The proof that CAST opened is one keypress past the list, because the list itself looks the same either way.

###### outdoorsgrep.py

For Curse and Silver Blades the answer is not a yes: the word is in both `DUNGEON` overlays among unrelated message fragments, not proven to be a status line, and only a driven session settles it. Read a hit as somewhere to look, never as a measurement.

###### overlay.py

Every finding names a run-time address, so every check of one used to start with two chores: work out which of the eight sides carries the file, and subtract the base. `--base` defaults to `$0800`, where `LINKER` puts an overlay it calls, because a PRG header cannot be believed (`DUNGEON`'s says `$1000`). `refs` is the mode that turned finding the wall-art handlers into one command. Three scratch scripts that shared one file-finder became this one tool.

###### pursecheck.py

Corresponds to `docs/139-per-title-validation.md` A8 (the seven money fields). `stage` selects the character's row and types into the form's own `field_copper`...`field_jewelry` spin boxes so `EditorBinding._flush` is the writer, and predicts `ENCUMBRANCE` as `sum(purses) + sum(item weight x quantity)`, which the C64 stores nowhere and works out while drawing the sheet. `run` takes VIEW CHARACTER on the party-formation menu (no world entry needed, unlike the item list). `money_box` reads both layouts: Curse puts `PLATINUM 5555` beside `WIS 11`, Silver Blades gives the money a boxed column with the number right-aligned. The engine's loop is `LIBRARY $3D3E` in Curse and `$31F2` in Silver Blades and it skips any purse whose sixteen bits are zero, which is why earlier captures showed one line.

###### rosterbytecensus.py, rosterspellcount.py

`SAVEDGAME1` keeps 32 bytes per roster slot, several with no established meaning. `rosterbytecensus.py` needed roster byte `+0x0D` corroborated before `goldbox.c64_codec.read` could hand it over as the neutral `combat_figure`: 90 of 90 occupied slots on the 15 engine-written `PORSAVE*` disks agree with the slot index, and the 54 more on disks Wish itself wrote agree by construction and prove nothing. `rosterspellcount.py`: `COM.PREP $15ED` rebuilds the per-level counters from the record's list at the start of every fight and nothing else writes them, so they are a cache; what matters is how many hold a value the list cannot explain, which is 0 of 55 across 24 of the player's disks. That settled the roster bytes on the measurement side, after `absrefsweep.py` had settled them on the code side.

###### savecheck.py

Answers what no file can: whether the game's LOAD SAVED GAME accepts a disk Wish built. `--view` with no number walks the party panel's highlight and reads every character (it once stepped with a NEXT the sheet's bar does not carry, so every run read the first character only). `--icon` compares the 3x3 colour block, copied straight from the icon's second eighteen bytes, and every figure's glyphs against `CHARPIC00` for the codes the save holds; the engine copies each icon's glyph bitmaps into a combat character set and hands out sequential screen codes, so searching the map for the icon's own codes finds nothing. An earlier check comparing the cells whose codes are the ordinary space and the reversed space was refuted: `$A0` in `CHARPIC00` is the top of a figure's head rather than eight `$FF` bytes. `--route` answers the screens of a walked area change (a room description, a `PRESS <RETURN>` and two YES NO bars). `--walk` takes `I J K M` indoors and the compass digits `1-8` on the travel grid and reports the square out of memory beside the status line, which lags a step outdoors. In a fight it takes a roll call out of the engine's position table (every combatant's square, whether it is on the map, and the seven-square window drawn) when the fight opens and on every command bar, and complains when fewer figures are drawn than the table puts inside the window; counting the figures alone is how two of six party members missing from the combat map at one keep went unnoticed. `--resave` has the game's own ENCAMP > SAVE write the party back and copies that disk out: the only way to make an engine-written save of a converted party, the control every conversion finding wants. Output goes to the temp directory.

###### session.py

The disk swap is what makes automation possible: the fliplist is unreachable from automation, but the text monitor has `attach`, and both monitor servers can run at once; one long-lived process, because VICE serves one text-monitor connection per run and closing it deafens every monitor. `in_combat`, `combat_state`, `combat_bar` and `fight` drive a battle; `docs/70-driving-the-game.md` says what row 24 means. `indoors()` reads `$49E6`, and a party on the travel grid gets the compass digits its bar asks for, the live square out of `$49C3`/`$49C4`, and a `Status` whose facing is None, because the line out there prints the word `OUTDOORS` where the facing letter goes. The world's party panel is a menu: one name is drawn in the highlight colour, `select_party` walks that highlight with Up and Down, and `character_sheet` reaches characters two to six, since nothing on the sheet's own bar does.

###### sheetexit.py

Every bar in all three C64 titles goes through one interpreter (Pool of Radiance `LIBRARY $306D`, Curse `$31F1`, Silver Blades `$46F1`, byte for byte the same routine relocated) whose `CMP #imm / BEQ` chain answers the back-arrow key, PETSCII `$5F`, with `LDA #$FF / SEC / RTS`, a negative accumulator the sheet's own `BPL / RTS` loop reads as leave. `keys` finds it by structure rather than address, anchored on the sheet's menu string. `run` boots a title once and reads a second character's sheet in the same boot, photographing both and recording row 24's colour RAM, the highlight index and the drawn entries' command ids before leaving the first. Six boots established that EXIT has to be walked to (its column moves with what the character carries) while the cancel key is read wherever the highlight sits.

###### splatload.py

An image copied out of a pool slot before the emulated 1541 finished its write-back holds a directory entry the drive still believes is open for writing, and the game refuses it though every reader here gets the payload out. The measurement is `$03F1`, the drive's own error number, not the sentence on screen. It is the Pool twin of `tools/curse_of_the_azure_bonds/curseload.py`.

###### statusdrive.py

The only way record `0x100` has been seen holding anything but 1. It boots a pool slot, loads a save, walks into the ambush, wounds one character to 1 hit point and nothing else through the monitor so the status is written by the game's own damage code, samples `$8300`-`$83FF` every turn, then ENCAMP > SAVE and reads the roster off the disk the game wrote. `--sheets` drives no fight and reads every VIEW sheet, whose last boxed line is the `STATUS` word `LIBRARY $38BE` draws; `--stage SLOT=VALUE` puts a value into a copy first, which is how `GONE`, `DEAD`, `RUNNING` and `STONED` were each seen on screen. `--panel` adds the party panel's own colour per character, which separated bit 7 from the low three bits: `$81` drew `OK` in red and `$05` drew `UNCONSIOUS` in the ordinary colour, with an all-`$01` boot as the control against an alternating row colour. Result: `01` to `84` on the turn an orc reached 0 hit points, `84` to `85` when the party won, `85` on the save disk, bit 7 a flag of its own. Both modes print the roster slot beside the panel position, because the panel is drawn from slot 7 down to 0 and reading sheets back by position pairs each staged value with the wrong character.

###### trainerscan.py, trainerspells.py

`trainerscan.py` exists because none of Pool of Radiance's twenty-five trainer addresses means anything in Curse. `--refs` puts each routine within two instructions of its table; it knows where each title's overlays run and where the record sits (Pool of Radiance `$6B00`, Curse and Silver Blades `$7C00`), and `--base` is for an overlay like Curse's `ECL65`, which runs at `$8000` rather than the `$0800` of `GEN` and `CAMP`. It found every table for Curse's trainer with no emulator. A hit is a claim about bytes and not proof they are code: scanning all 411 Curse files for `spells_castable` returned two, both inside bitmaps. `trainerspells.py` asserts that every step is a `JSR` the title's own level-up sequence makes, so a routine that only looks like a trainer step is not reported.

###### traitask.py, traitcross.py, traitdrive.py, traitquery.py, traitsave.py

The ten trait slots at record `0x0AD` are the second of two backing stores for "has this character got effect N?". `LIBRARY $3FE4` searches the 64-entry active-effect array alone and `$4027` searches the array and then the slots, so a caller of the first never sees a trait and a caller of the second treats one exactly like a running spell.

`traitask.py` is the census `traitquery.py` cannot take by literal scan: the combat engine keeps twenty per-check id lists under the I/O area at `$DB7A` and walks them through `COMBAT $28A4`, so an id reaches a register from a table. The tracepoints (`tr exec`) at `LIBRARY $3FE4` (the ask, id in A), `$402D` (fell through to the ten slots) and `$403C` (a slot matched) print the registers on every hit without stopping the machine, so `session.py` can walk the party into the Slums ambush while 21,850 asks are logged. It stages a readied item template (`--item`), a trait id (`--stage`), roster hit points (`--hp`) or a memorised list (`--memorise`) into a copy of a save, reads the check lists and the 139 handler addresses out of RAM bank 1, drives ENCAMP > VIEW > ITEMS > READY by the character's name on the panel (the panel is in marching order; a magical item is refused with `NOT HERE` outside camp; the list takes the verb before the row and prints an unidentified item by its noun; ten boots found those out) and diffs the record and effect arrays around each press, and with `--cast` has a caster choose from `SPELLS: CAST EXIT` and a party member from `NEXT PREV MANUAL TARGET EXIT`. `--report DIR` prints asked / reached the trait scan / matched per id. Findings: 61 is on two lists, load never re-derives a slot from a readied item, READY changes exactly one byte, and a byte we wrote made ROLAND regenerate. `--repair` runs `goldbox.items.repair_ring_of_fire_resistance` over each staged item template so a run with the flag and a run without differ by the two bytes under test (the C64's Ring of Fire Resistance grants nothing).

`traitcross.py`: the block is filled from two neutral fields at once, `innate_effects` from slot 0 upward and `granted_effects` from slot 9 down, so whether a paladin's Protection from Evil crossed cannot be answered from either list alone. It runs the conversion for real (`goldbox.dos_codec.read_character`, `to_neutral`, `goldbox.c64_codec.write`) and prints the source `.SPC`/`.FX`/`.SFX` ids, both neutral lists, the filled slots and a LOST column for any permanent id reaching no slot; a running spell counting down is deliberately not converted and not counted. `--all` over `$WISH_SPECIMENS`: 236 records, 128 carrying a permanent id, 0 lost. `--c64` reads a `.d64`'s own ten bytes so the two halves of a disagreement can sit side by side. It measures our writer rather than the game.

`traitdrive.py` counts how often `LIBRARY $403C` executes, the `SEC` that only a trait slot's match falls through to (the array half returns at `$402C`, an exhausted scan at `$403B`). The checkpoints are armed not to stop, because a stopping breakpoint freezes the machine between `walk_one`'s screen polls and the party never moves. `--stage SLOT:INDEX=ID` takes several at once; the control is the same command with no `--stage`; `--save-game` reads the trait blocks back off the disk the engine wrote, which says whether the engine cleared a slot it acted on. Every event goes to `traits.jsonl` as it happens, so a killed run keeps its record.

`traitquery.py` finds the predicate without being told where the overlay runs: the trait scan's bytes give the scratch address, the entry's `JSR` operand gives the array routine's address, and that routine's opening `STA <scratch>` gives its offset, so address minus offset is the run base. Pool of Radiance comes out at `$2C48`, which agrees with `docs/40-memory-map.md`; the predicates are `$4027` (Pool of Radiance), Curse `$40E2`, Silver Blades `$387D`. `--lists` adds what a literal census cannot see: it traces the call chain out from the predicate (the `LDX <character> / JMP <predicate>` wrapper, the `STY / PHA / JSR <wrapper>` ask, the two handler tables it dispatches through, whose spacing is the size of the effect namespace: 139, 146 and 113 ids, then the walker and the file the block ships in) and reproduces `traitask.py`'s live reading of Pool of Radiance byte for byte (`SPELLE65 +0x0570`, 20 lists, 134 ids, 92 distinct). It established that Silver Blades honours 90 ids in a trait slot. `--compare TITLE` sets each id's check-list membership beside another title's; the walker takes a list number, so the same id in the same numbered list in two titles is asked the same question about the same thing, which is PROBABLE evidence a name transfers (46 of Silver Blades' 90 agree with Curse). `--spells` reads the per-spell record the engine copies when a spell is cast (`ECL65 +0` at seven bytes a record in Pool of Radiance, `COMBAT2 +2732` and `+2937` at nine in the later two) and prints the effect id each spell writes with the game's own message, which is the game's data naming the id and earns CONFIRMED; it grew `NAMES_SILVER_BLADES` from six entries to 59 and caught positional agreement getting 4, 27 and 35 wrong. `--handlers [ID...]` disassembles the routine each id dispatches through the table pair (`LDX <id> / LDA <low>,X / LDA <high>,X`, so the index is the id itself) until a return no forward branch reaches past; it named the last 35 Silver Blades ids and corrected 93 and 96. For Pool of Radiance it prints the four `$A700` overlays that could hold a handler rather than guessing. Anchors and every reading are in `docs/171-c64-trait-slots.md` (`$A904` the damage type, `$945F` the damage, `$A903` the saving-throw d20).

`traitsave.py` is measurement M3 for whether an item-granted trait works: `traitdrive.py` stages bytes by poking a `.d64`, which proves the engine reads a slot and says nothing about the editor's own write path. `write` builds the real `WishWindow`, clicks the real `button_trait_add`, picks the trait in the real `TraitPicker` and triggers the real File > Save, replacing only `TraitPicker.exec` (the modal wait for a person), and reports the byte diff of the whole disk image: one byte in 174,848 on `PORSAVE13.D64` and again on a synthetic save. `boot` reads the ten slots out of the live record at `$4D00 + slot * $100`, rests `--rest` hours through `CAMP`'s own rest-time field, and with `--save-game` has the game write its own save and reads the block back (run again on that disk, the answer is whether the trait survived a reload). The consequence half needs no new tool: `traitask.py --save <that disk> --cast ...` takes an absolute path and stages nothing without `--stage`. `QT_QPA_PLATFORM` is assigned before PyQt is imported and the XDG variables point at the run directory, so the player's settings are not touched.

###### turndrive.py

`COMBAT $09D9` reads `turn_power` and clears bit 5 of the bar's command mask when it is zero; bit 5 is the word TURN. The tool reads the acting character's name and `$6BA4` out of the working record at `$6B00` in one monitor stop, beside row 24 verbatim, so each line pairs the byte the engine read with the bar it drew. The two runs behind `docs/178-turning-undead.md` are `--stage 2=1` and `--stage 2=0` on `PORSAVE13.D64`: ROLAND gets `MOVE VIEW AIM USE CAST TURN QUICK DONE` with 1 and loses the word entirely with 0.

###### vicebankcheck.py

Measured on a pooled instance: `default` and `cpu` (both id 0) and `io` (3) answer the registers, `ram` (1) and `cart` (4) answer the RAM. `savecheck.py --icon` reads the combat character set at `$D000` through bank 0, so its "screen code `$20` is eight zero bytes" arm passes because the registers read zero, while its `$A0` arm cannot pass at all. `--address` takes several addresses and `--bytes` widens each reading to a whole glyph, because what the wrong bank answers instead decides whether a check fails loudly or passes quietly. It boots the emulator and leaves it at the title: the answer is VICE's, not the game's.

###### walkrun.py

Builds a set of saves unattended. A move that does not change the party position is a wall, which is the whole point. Tears everything down at the end and screenshots if anything goes wrong.

###### wallsmap.py, whatis.py

`wallsmap.py`: `$ED50` holds either the wall tables or three pieces unpacked over them and never both, so the question at an area change is which of the two is there and in which thirds; `cmp -l` cannot draw that. Used for the bug where warping out of Valhingen Graveyard or Valjevo Castle leaves two wall pieces unrelocated. `whatis.py` answers the first question about every region a driven session dumps, which cannot be answered by eye: the staging page holds whatever the last `LOADFILES` asked for and the loaded-files cache names a slot rather than the bytes. A byte-for-byte match is the answer outright and a block matching nothing is scratch; a partial match shows a mixed region, as with a region holding the arriving area's file for its first half and the departed area's for the rest (the Slums-to-New-Phlan warp drawing the Slums' walls). `--at-base` is for a region the loader relocates. Rescued from a scratch directory.

###### ghtrust.py, issueread.py

`gh issue view N --comments` prints every comment's body verbatim and the repository is public with issues enabled, so a comment's author can be anyone. `issueread.py N` prints the issue in full for a trusted author (`malcyon`, `wish-agent[bot]`) and withholds the rest through `ghtrust.py`'s `withheld(...)`, naming the author, the length and the exact command or URL that would show it, never the text. A summary line at the top says how many comments came from outside accounts and from whom, so an agent can still tell Donald there is something to read: withheld, not dropped. It uses `gh`, already authenticated as Donald, and fails loudly, unlike the session-start hook it shares `ghtrust.py` with.

###### gamedisks.py, instance.py, scratch.py, specimenbackup.py, specimens.py

`gamedisks.py` replaced seven searches in six files with one registry, turning "103 skipped" into a question anybody can answer in a second: with no `gamedisks.yaml` it stops with a one-line message saying to copy the example, which is the whole registry. `instance.py`: the lease is an `fcntl.flock`, so the kernel frees a crashed run's slot with no cleanup script; teardown is `os.killpg` on the group this slot started; `status` also reports whether a held slot is idle (how long since anything but the lease was written into it) and whether one process holds more than one slot, which is the actual leak, found by reading mtimes and asking for a process group, never by probing a monitor an agent is using; `claim -- <command>` catches `SIGTERM` so a shell `timeout` wrapped around it bounds the run instead of only killing the wrapper. `scratch.py`: one directory per tool and never one named for a ticket; `cache_dir` is for the few things that must survive a reboot, such as the marker a green suite run leaves for the push hook; `--help` and a refused argument leave the disk alone because `ensure` runs immediately before the first write; a tool puts the repository root, never `tools/`, on `sys.path`; `tests/registry/test_scratch.py` covers it. `specimenbackup.py` is step 5 ("somewhere durable to keep it") of building a DOS party from creation: `audit` reads `.tar.zst` through `zstd` (what the hourly snapshot of the deleted scratch directory was) and reports which recorded contents have a second copy by SHA-256, so a file edited since does not count; `archive` refuses a destination inside the repository, one that already exists, and a tree that does not match its own manifests; `verify` says whether an archive could put every specimen back. `specimens.py` `add` writes a `provenance.toml` naming who made the specimen, how and what was done to it, then makes every file and the specimen's directory read-only; it was seeded with the eight characters rolled from creation for the gnome innate-effect measurement; `amiga` is in `PLATFORMS` and directories are named `<title-slug>-<platform>` so more than one title can share a platform.

#### `tools/dos`, `tools/generate`, `tools/suite`, `tools/convert`

Each heading names a tool or theme. The facts are what the READMEs used to say about it; they are evidence for the tools' results, not part of how to use them.

###### Ability pairs (dosabilitypair.py)

For strength through charisma the lower byte of a DOS ability pair is the permanent score and the higher is the one in force; for the exceptional-strength percentile it is the other way round. `sites` matches six instruction signatures in the shipped `GAME.OVR`; they appear in all five DOS engines that keep pairs and in none of Pool of Radiance, which keeps one copy of each ability and is the negative control. All 406 pairs this project can reach hold equal bytes, so only a staged boot with unequal bytes could answer it.

###### Duplicate-character test (dosaddchar.py)

The engine's duplicate test on ADD CHARACTER TO PARTY compares the identity byte at `0x0AB` after the name: `--ident 0` is refused and `--ident 0x42` is let in, and `--writer` shows the fix works with our writer's value. In that menu the arrow keys do nothing; `Home` and `End` move the highlight, `N` and `P` turn the page and any other key picks. An entry is starred once its file has been read, so the star proves a refusal was a refusal and not a mis-driven menu.

###### Array widths (dosarraywidth.py, dosrecordloops.py)

`dosarraywidth.py` tallies `cmp byte [bp-n], imm` guards in the 90 bytes before an `es:[di+disp]` access and stops at a `retf` or `ret`. Its three controls (the titles whose widths were already known) must come out unchanged for a reading to be believable. It found that Pool of Radiance's memorised-spell list is 21 entries at `0x017`, four loops bounding the index at `0x14`, where `goldbox/dos_port.py` had declared 16 at `0x01C`; Curse, Silver Blades and Pools of Darkness read 84, 75 and 141, as declared. `spells_castable_cleric`, `attack_forms` and `field_83_87` are as declared. A big array is usually walked by adding the offset into a pointer first, which is why the spellbook gives no hits, and a 1-based loop carries the offset one lower, which that tool cannot see at all. `dosrecordloops.py` reads that case: it ties the bound to the stack slot genuinely added into `di`, reads the initialiser to tell 0-based from 1-based, and scales the span by any `shl ax, N`. Pool of Radiance's seven word-sized coin purses read as 7 entries across 12 bytes, and `spells_castable_cleric` comes out 8/6/8/8 against a declared 3/5/7/9 and is really 3/5/7/7-of-9.

###### Driving DOSBox (dosbox.py, dosboxx.py)

Input is XTEST through `xdotool` aimed at a window nobody else owns, because there is no window manager under a bare `Xvfb`, so `windowactivate` fails and the keystroke is lost. The window is chosen by `_NET_WM_PID` and then proved to have pixels in it, a display something already answers on is refused, and a one-colour screenshot is refused by name. The DOSBox-X harness hides four traps that cost an hour each: the 64K `MEMDUMPBIN` wrap, the spurious first `BPM` hit, the code breakpoint that logs nothing and the 254-character command truncation. It is the DOS counterpart of VICE's binary monitor.

###### Byte constants (dosbyteimm.py)

A byte the engine sets to `0Ah`, `0Ch` and `0FFh` is not a marching position; one it sets to `0B2h` and `0B3h` and compares against `80h` and `7Fh` is a bitfield with a flag in the top bit. Both readings came from this tool.

###### Disassembly windows (dosdis16.py)

The Silver Blades party-menu dispatcher was found through the string `Free training on`. `dualclassdos.py code` is the same disassembly at one fixed site.

###### Import from DOS (dosdisk.py, dosnewsave.py)

`goldbox.dos_codec.new_save` writes all 9216 bytes of `SAVEDGAME0` and `SAVEDGAME1` from two zeroed buffers and `save_disk` puts them on `D64.blank()`; the composed combat icon and `ANIMATE00` cannot come from a DOS save and are read off the player's own `POOL` sides, so the tool refuses without them. `--sheet` decodes `armour_class` and `thac0_current` through the family's `60 - value`. `goldbox.dos_codec.new_dos_save` writes all 13137 bytes of `SAVGAM<slot>.DAT` and every `CHRDAT<slot><n>` beside it from zeroes; the engine's own `ENCAMP > SAVE` rewrite is the oracle for which zeroed bytes it fills in for itself.

###### Drop census (dosdropcensus.py)

On Curse's 58 records, five of the six columns asked about are empty: 0 of 406 ability pairs differ, no druid slot and no fourth- or fifth-level slot is set anywhere, and the widest memorised list is 7 ids. Each of those fields therefore needs a specimen made rather than found. It reads the same records as `dostailcensus.py`.

###### Encumbrance (dosencrecompute.py, dosencsave.py, dosencumbrance.py, dosshop.py)

`dosencrecompute.py` answers from the shipped code when the engine rewrites the stored encumbrance, where `tools/records/enccensus.py` answers from records and `dosencsave.py` from a driven boot. `dosencumbrance.py --census` found 264 distinct records, 214 balancing exactly; the six that miss by +3 are all Curse characters straight from the Tilverton shop, and two Pool of Radiance dart-throwers are short by exactly the darts their cached name has not caught up with. Four purchases behind `docs/125-bug-notes.md` N19 were measured this way. `dosshop.py --encumbrance` once staged the spoiled value after the load, so the engine never read it and a later "recompute" conclusion for the shop control specimen does not hold; it now spoils before the boot, in the same order as `dosencsave.py`. `dosencsave.py` takes up to three saves off one spoiled load: a party-menu `SAVE CURRENT GAME`, a camp save, and a save after `VIEW` drew a sheet.

###### Shop map (dosshop.py)

`--map` reads `ECL00`'s twenty-eight-way `ONGOTO`, the four arms ending in `TREASURE` and the `$6E6C` shop side channel, and the `GEO00` squares those arms belong to, then checks the C64 reading against the DOS build's own `GEO3.DAX` and `ECL3.DAX`.

###### Instruction scans (dosfieldrefs.py)

For `hands_used`, eight sites address `0x100` and exactly two write it, both inside the inventory recount, the first an immediate zero, so the field is rebuilt before it is read and our zero cannot be believed as combat state. A displacement match does not prove the pointer is a record and one image is one set of overlays.

###### Fights (dosfightrun.py, dosfightwatch.py, dosquickprobe.py, dossideprobe.py)

`dosfightrun.py capture` produced the digests in `PoolOfRadiance.COMBAT_BARS`; experience rising in `CHRDAT<slot><n>.SAV` says monsters were slain and names the party as the killer, where hit points falling says only that the party was struck. Its run output is kept at `cited/dosbox/p114/`. `dosfightwatch.py` has no read watchpoint to use, so when the engine writes over our zero relative to the fight's phases is the measurement available; all but two of the player's save disks are in New Phlan, which has no wandering encounters. Its run is kept at `cited/69/`. `dosquickprobe.py` showed record `0x10F` is the quickfight flag: with 1 the engine fought the whole battle itself and the command bar never appeared; with 0 the same party stopped at `MOVE VIEW AIM USE QUICK DONE` and was still there 335 captures later. `q` is absent from its ladder because every fight in the earlier specimens was driven with it, so they could not separate "QUICK was pressed" from "a fight happened". `dossideprobe.py` read `0x10E` (0 the party's, 1 the enemy's) out of `GAME.OVR`; an earlier run is kept at `cited/235/`.

###### Gnome and innate effects (dosgnome.py, dosracialseed.py, innateids.py)

`dosgnome.py` read the two innate effect ids nobody had seen for a gnome. `dosracialseed.py` also reports the save-type gate, the constitution read, the band table and the roll accumulator of the handler, and was written to settle whether innate effect 97 is racial or the constitution bonus; `tests/dos/test_dosracialseed.py` pins `RACE_COMBAT_EFFECTS` and `constitution_save_bonus` to its reading. `innateids.py` found that Curse seeds the elf 107 and the ranger 134 (`GAME.OVR:0x20989`, `0x20D9E`), Silver Blades seeds the ranger 105 (`0x1E345`), and Pool of Radiance has no class switch at all, so its `INNATE_EFFECTS` needs no class ids. Both switches and `add_affect` are found by structure, so one run works on all three titles. `--ids` turns "the ranger branch adds 134" into "and nothing else in the overlay does". `census --by-id` prints one block per effect id with every carrier's race, class and levels, each graded so a set with no chain of custody cannot be read as evidence.

###### Item ceiling (dositemcap.py)

The specimen is `WISH-SPEC-por-party-l1-intown`; item lists use copies of the game's `Sling` template from `ITEM1.DAX` block 53 with `item_count` and `encumbrance` written to match. A sling weighs two tenths of a pound because the refusal routine shares one flag between the item count and `encumbrance + weight x quantity` against carrying capacity plus 1500, so a heavy inventory would prove nothing about the count. The refusal message is on screen for about a tenth of a second, so `@key` shoots with no settle. `--counts 2,15,16` shows the boundary (the same item accepted at fifteen, refused at sixteen), 16 alone shows `HALVE` missing from the item bar until one item is dropped, and 20 shows the ceiling is on acquisition only. A character carrying nothing gets no `.ITM` file rather than an empty one (`goldbox.dos_codec.ITM_OMITTED_WHEN_EMPTY`), because a zero-length one reproduces the phantom-item half of the empty-inventory corruption on a record the engine wrote.

###### Training (dosladder.py, dostrain.py, dostrainprobe.py)

The trainer clamps experience so hard that nobody can train twice on one staging, so `dosladder.py` re-stages experience and gold between rungs: those two are inputs it writes, and what the trainer writes back is the engine's.

###### Treasure-share byte (dosmodifyprobe.py, dostailprobe.py)

The byte at `0x085` stays 0 until KEEP. `dostailprobe.py`: twelve values across two boots came back byte for byte, so `0x10C` to `0x10F` are stored state rather than scratch; the same boots printed `STATUS OKAY` and `STATUS UNCONSCIOUS` for `0x10C` = 0 and 4 and greyed a name out of the party panel for `0x10D` = 0. `--field field_83_87` showed the sheet is pixel-identical whatever those five bytes hold.

###### Outdoor saves (dosoutdoor.py, dosoutdoorprobe.py)

All of the player's own saves are indoors, and the three made earlier for the wilderness work lived in scratch and are gone. Reaching the travel grid by playing means crossing New Phlan to the harbour master and taking a boat, so the tool seeds and resaves. A seed moves a copy of an indoor save onto a travel window and sets the four fields measured to differ outdoors: `$49C5` = 0, `$49E6` = 0, the travel square at `$49C3` and `$49C4`, and the outdoor tail state. Every byte of the specimen is then the engine's. `--wallset keep` (a triple no overland save has held) is what separated live from stale at `$4AFA` to `$4AFC`.

###### Overlays (dosovrmap.py, dosovrwindow.py, dosptrfields.py, unexepack.py)

DOS Pool of Radiance's `START.EXE` is EXEPACK-packed, which is why its overlay descriptors looked unaligned and its data segment could not be found in the file. Turbo Pascal compiles `p^.field` into `les di, [<global>]` then `es:[di+<disp>]`, so displacements after a load of one global are that structure's fields, and because the same block is what the save routine hands to `BlockWrite`, a displacement is a file offset. That read the first 1024 bytes of Pools of Darkness' `SAVGAM<slot>.PTY`. Its scan is linear over a file that is not all code, so a hit is a claim about bytes.

###### Pools of Darkness (dospod.py)

Its launcher is `START.BAT`; `to_main_menu` presses Escape because Return on the title menu walks into a stat roll. The eight engine-written containers behind the Pools of Darkness section of `docs/141-dos-savegame.md` came from it.

###### Race tables (dosraces.py)

The four titles do not share one race table. It anchors on `Lawful Good`, the alignment table's entry 0, and walks backwards while the bytes look like a padded slot, so a table naming a race nobody has heard of is still read; Silver Blades' entry 0 is `Tribble`. For Pool of Radiance and Curse it reproduces `RACE_NUMBERS`, which was established from 24 specimens and the C64, and that is what makes the same reading of the other two a measurement. The Gateway and Treasures readings in `goldbox/dos_port.py`'s docstrings were taken another way.

###### Record writer round trip (dosrecordwrite.py)

`roundtrip` over the whole specimen tree: 48 of 56 Curse records, 47 of 50 Silver Blades and 28 of 136 Pool of Radiance identical, every exception named. The eight Curse ones are `STALE_OUR_OUTPUT`, this project's own writer before the class-code repair, reported in their own paragraph; `field_83_87`'s treasure-share byte is a constant and 111 records disagree by design; the 62 Pool of Radiance encumbrance misses are the training fee. `WRITE_CONSTANTS` is deliberately not masked. `from-c64` reports that it wrote no `SAVGAM`, so a fault in the records can be seen without the container. `loop` puts the C64 engine inside the measurement, and every difference it finds is one of three named things, none of them the record writer.

###### Saved-game census and map (dossavcensus.py, dossavewritemap.py, dossavgam.py, neveradventured.py)

`dossavcensus.py` excludes hand-built seeds and parties saved before setting out by stated choice, since a census of world state should not count them; it re-takes the counts of `docs/141-dos-savegame.md` instead of quoting the ones eight lost specimens produced. `dossavewritemap.py` finds the save chain by structure: a save-side `BlockWrite` passes `NIL` for `var Result` and compiles to `xor ax, ax; push ax; push ax; lcall`, where the load side pushes `ss:di`; it takes the longest run whose widths add up to a known container size, and it settled that a Curse or Silver Blades party's square was read twelve bytes past where the engine writes it. `dossavgam.py --runs` is how the per-title region map in `goldbox/dos_savegame.py` was first read, `--scripts` compares the largest `ECL<n>.DAX` block per title with the 7680-byte staging buffer, and it deduplicates on bytes because the archives ship most save directories twice. In `neveradventured.py`, the area word is 0 in a never-adventured save on all three titles and is not the test: Pool of Radiance's area 0 is New Phlan, so keying on it would move thirteen containers out of the town the game starts in and reset their clocks. `--by word` reads `$4FE1`, which is 0 in 13 of 13 never-adventured containers and none of the 101 others; `--by buffer` reads the staged area script, which a party in the world always has and Silver Blades' container has no room for. They agree on all 107 containers where both can be taken.

###### Silver Blades scroll bundles (dosscrollbundle.py)

The four bytes are why a Silver Blades item is 67 bytes where the other five DOS engines' is 63. With the five 63-byte titles as controls, Silver Blades loads a far pointer from that displacement 41 times and none of the others loads one; every walk of the chain is gated on `type_index` `0x49`, and the only store of that type into an item is the JOIN routine that makes a bundle of two scrolls. `walk` is the engine's loop against `slice_naively`, which is what `goldbox.dos_codec.read_character` uses. The sweep of the specimen tree and archives found 140 item files and 0 bundles.

###### Converted-party sheets (dossheetread.py)

A `CHRDAT` in the container directory is deliberately not copied, so a stale effect or item file from the container's own party is never read as one of ours. `--save` installs a whole save this project wrote, container and records together, which proved the Curse and Silver Blades container writers. `LOAD SAVED GAME` leaves the party at `CHOOSE A FUNCTION` rather than on the map, so a walk needs `BEGIN ADVENTURING` first or it presses arrows at a menu that has none and reports blocked steps. DOS Silver Blades has a highlight-list party menu (`--sheet-open`, `--sheet-reopen`, `--pick-down`, `--pick-select`) where the other titles take a letter, and its map bar begins `MOVE` where theirs begin `AREA`; until `--move-mode` presses that key the arrows do nothing, so a walk reports six walls in an open corridor. Shots are copied from a `finally`, and a `save_game` that cannot find its way out of camp is reported rather than raised, because a specimen dies with the emulator slot that made it and one `TimeoutError` used to take six sheets and a walk with it.

###### Spell slots and expiry (dosslotwatch.py, dosspcexpiry.py, dosspellslots.py, dosvmwatch.py)

`dosslotwatch.py` watched the engine zero Silver Blades' fourth spell-slot array. `dosspellslots.py` found that array is spell class 2's and no spell in the title has that class; `tables` shows Curse's paladin gets cleric slots from level 9 written into the cleric array, and its ranger gets druid slots from 8 and magic-user slots from 9 out of one table split across two arrays; the same read reproduces the cleric and magic-user rows known from the C64, which makes the other two safe to take from DOS. The builder is picked out of the three fill sites by its class loop and `DS` off the System unit's start-up; `tests/curse_of_the_azure_bonds/test_cursespellslots.py` reads all four tables back off the player's own image. In `dosspcexpiry.py`, a `BLESS` at two minutes vanishes and every zero-duration node survives; `ready` reads the `id 00 00 0C 00` record the engine appends and writes to a `.SPC`. `dosvmwatch.py` ran two experiments back to back: a step with `$507A` (VM `$6E7A`) armed, then ENCAMP with `$4FD2` and `$4FD3` (VM `$6DD2`, `$6DD3`) armed.

###### Tail-field census (dostailcensus.py)

Three exclusions are the point. Records we wrote are out by default because `goldbox/dos_codec.py` writes the constants under test; an emulator instance's staged tree is skipped because a probe leaves its own tampering there; and a Gateway or Treasures record is skipped and counted because it has the same record size as Curse and Pools of Darkness. Before that exclusion 24 Gateway and 28 Treasures records were read as 12 and 14 extra Curse and Pools of Darkness ones after deduplication. The 24-specimen claim about the combat tail, re-taken on 223 records, found `field_10c_10f` holding three different values, and that count predates the exclusion and needs it applied before it is quoted again.

###### Experience award (dosxpaward.py)

The unattributed run is `gap_0b8` in Pool of Radiance, `gap_13c` in Curse and Gateway, `gap_14e` in Silver Blades; Pools of Darkness and Treasures keep the base alone at `0x198`. The end-of-combat routine accumulates `base + hp_rolled x per_hp`, and the script property dispatcher's ids are C64 record offsets, which names the field: 17 of 17 arms whose id is a named C64 field land on the DOS field of the same name, and the only two in a C64 gap are `0x0F7` and `0x0F9`, already confirmed in `docs/80-fields-wanted.md`. In `MON<n>CHA.DAX`, DOS Pool of Radiance's GOBLIN GUARD is 10 and 1 and its OGRE 90 and 5, the published AD&D values. The sweep found a non-zero award in 2 paths of 474, one record, in Treasures.

###### Dual-class old class (dualclassdos.py, dualclassregain.py)

In each of the six DOS engines exactly one of the three or four clear sites of `class_bits` goes on to read `former_class_levels` and compare it with `level`; Pool of Radiance has none, since it has no former array. The rule predicts the stored mask on 62 of 62 records in the archives and 11 of 11 dual-classed records across the archives and the specimen tree.

###### DAX images (daxls.py)

An image block is recognised by the one test every such block in the game passes: its length is exactly `17 + rows * width / 2`. The listing shows the nine unread header bytes.

###### Frame audit (dosframeaudit.py)

It takes several hundred unhalved captures, turning the party between batches so a capture caught mid-redraw is in the sample and not excluded from it, so that a uniformity check on `dosboxx.halve()` can be judged against how often a frame is really ragged.

###### Test flake tooling (tools/suite conftestflake_*)

The race in `tests/suite/test_conftest_state_guard.py` overlapped in 20 of 20 runs under `-n auto --dist loadgroup`, about 300 ms of each probe's 330 to 390 ms life. Forcing an `xdist_group` on both tests serialised them: 0 of 20 overlapped, but it needed `@pytest.hookimpl(tryfirst=True)` to run before xdist's own `pytest_collection_modifyitems`, a hazard specific to adding the marker through a hook, where a real fix's `pytestmark` binds before any hook runs. Resolving a single-file argument under `tests/` collects the whole directory first, and on `win32` `_pytest.pathlib.samefile_nofollow()` does an unguarded `.lstat()` on every sibling whose path does not string-equal the target's. Faking `sys.platform` to `win32` for the collection phase only, on Linux, 10 of 10 `force` runs failed collection naming the sibling and 10 of 10 `control` runs passed.

###### Path leaks and rules check (pathleak.py, rulescheck.py)

`pathleak.py` counted 34 of 119 tools leaving `tools/` on `sys.path`, and 7 capturing `wish`, at the commit it was written for; that census was what a cold-run failure of the `wish` package losing to `tools/wish.py` was about. `rulescheck.py` was written because splitting the 1595-line `CLAUDE.md` by hand across three agents could lose a paragraph and still look tidy.

###### Test party (testparty.py, testpartyrun.py)

Each character is a level-1 record through `goldbox.c64_codec.write`, then `goldbox.levelup.plan` once per level with experience granted before each training, so every derived byte above level 1 comes from the training hall reproduced, not from a table the tool reads. `--rolls max` gives the trainer an rng that always rolls the top of the die, which reaches the documented ceilings (BULWARK at THAC0 13, 112 hit points, 3/2 attacks) and makes the party byte-identical every run. `--records DIR` writes one 582-byte `.CHR` export per character. The one thing it cannot make is the combat icon, and the test file fails if a second gap appears. `tests/suite/test_testparty.py` rebuilds each of the six characters the engine rolled in `WISH-SPEC-por-party-l1-rolled` from its own inputs, which stops the generator validating its own tables. `testpartyrun.py` read six of six sheets in agreement, BULWARK included (LEVEL 8, EXP 130000, HITPOINTS 72, AC 8, THACO 11), which turned the fighter ceiling from our specification agreeing with itself into a measurement. The party panel is in marching order, so index 0 is the last save slot, and the sheet's portrait window reads back as a charset ramp through `Session.screen()` because the portrait is a bitmap over the text matrix.

###### Class diagrams (classdiagram.py, classedges.py)

`classdiagram.py` skips a module with no classes, since `pyreverse` writes it as a bare `classDiagram` line, which is a Mermaid parse error. It runs against a worktree at `HEAD` because `goldbox/` is renamed most nights. `pylint`, which ships `pyreverse`, is not in `.venv` and must not become a dependency. `classedges.py Title goldbox` answered 0 at stages 1 to 6 of the neutral-title work and 1 at stage 7; `Title | None` is visible as the weaker claim.

###### Generators (genexits.py, genicons.py, genimports.py, genitems.py)

`genexits.py`: a gated square (entry 0, the forward key) has to be one `Geo.is_passable` confirms open on the side that leaves the map, since `$10EC` never counts a step through a wall. `genicons.py` makes every size from the artist's own file rather than scaling one of ours, because Windows picks the nearest entry and scales it bilinearly, so a `.ico` holding only a 256 gives mush at the 16 px of the title bar and Alt-Tab. `genimports.py` exists because the edge it catches, a codec importing another codec, is one somebody adds without noticing. `genitems.py` reads names off the disk so they carry no transcription errors.

###### Convert measurement (convertbytes.py, convertdrops.py, convertrun.py, convertshots.py, convertdialog*.py, hallconvert.py)

`convertbytes.py` stands in for the emulator condition that every direction has been loaded and walked from a save the dialog's own code path wrote; that stays true only as long as the bytes it was taken on do, and nothing re-takes it when a writer changes. `--tree` puts a detached worktree's `goldbox/`, `editor/` and `tools/` in front on `sys.path`, so the measuring code is the same in both runs and the measured code is each tree's own. An Amiga destination is hashed by the files inside the built `POOLSAVE.ADF`, never by the image, because `AmigaDisk.write_file` stamps wall-clock timestamps and two builds of one input differ in about a dozen of 901,120 bytes. A colleague's uncommitted `goldbox/portraits.py` once made three of 118 conversions look nondeterministic in a working-tree run. `convertdrops.py`: a writer's `DROPPED` tuple is an upper bound, not a count; `goldbox.neutral.Writer.finish` composes a line only for a field the neutral record carries, so a declared entry no source can reach never fires. `WRITE_UNREPORTED_DROPS` used to silence `turn_power` and `infravision`, which a real C64 source reaches, so the count could look emptier than the conversion was; that list is deleted and those names, and `encumbrance`, go through `WRITE_NO_SUCH_FIELD` or `WRITE_DERIVED`. The default sweep includes the source title's own combat-icon tables and found the paladin's Protection from Evil on 5 of 10 C64 Curse specimens after a one-specimen run said the direction was clean. Later-title Amiga container specimens are wrapped in fresh temporary ADFs so their reader paths are measured, and each Amiga writer receives its own title's game-data disk. `convertrun.py`: `ConvertDialog.exec` is the one thing replaced, being the modal wait for a person to press Convert. A file copy has to clear the slot itself, because `goldbox.dos_codec.new_dos_save` deletes stale `CHRDAT<slot><n>.*` before it moves its own files in and a freshly staged archive tree carries the shipped party's records at slot A (thirteen of them, including `.ITM` files no conversion writes). It copies both slots' `CHRDAT<slot><n>` files beside the two containers, because the staged tree dies with the session and a `SAVGAM<slot>.DAT` without its party records is a saved game with no party. `convertshots.py`: six states (empty, the approved refusal, no C64 disks, no DOS game folder, only `From` filled in, an unreadable source) need only synthetic saves; the two "ready to write" states need a rehearsal to succeed; two more render the modal `QMessageBox` a refusal or a name-too-long-for-DOS warning shows in; a row still empty pops no modal at all. `hallconvert.py`: for an area that loads its own map the two words hold the same number and the disks are byte-identical; the training hall and Phlan City Hall load no map, so `$49C5` stays at New Phlan's 0 and the pair differ in `$49F2` and loaded-files cache slot 8. It reproduces the defect from the shipped code rather than a hand-edited file, which is what makes the booted comparison evidence.

#### `tools/gui`, `tools/icons`, `tools/pool_of_radiance`, `tools/curse_of_the_azure_bonds`, `tools/secret_of_the_silver_blades`

###### Windows base font and the offscreen proxy (gui)

Adding 6 points to the UI font offscreen (`shotwindow.py --font +6`) measured about like Windows' own base font, and +10 was the largest size the window is designed for. `winwish.py` and its guest scripts replace that proxy with a measurement on the real `windows` platform plugin and `windows11` style, at +0, +3, +6 and +10 points, for an ordinary six-character party and the widest party the record allows.

###### Screen reader banking (gui, screenblind.py and livecheck.py)

Pool of Radiance's loader spends part of every load with `$01 = $30`, the I/O chips banked out, so `$D018` and `$DD00` read off the monitor's default bank are bytes of RAM and the screen is computed somewhere nothing is displaying. Four polls of 1,035 disagreed on slot 0, all four putting the screen at `$C000` where the chips said `$DC00`. That rare a fault cannot be waited for, so `screenblind.py --stage` writes `$30` to `$01` with the machine stopped and reads the screen both ways; at the insert-a-side prompt the old reader answered `..@@@@....@@@@..` and the new one `INSERT SIDE # 3, AND PRESS ANY KEY.` The screen's registers must be read through `automap.vice.banked`, never through the processor's view.

###### Driving notes for livecheck.py (gui)

`$XDG_DATA_HOME` must not be reassigned to redirect the run's map notes: a Flatpak VICE installation lives under it, and moving it makes `tools/c64/porlaunch.sh` fail with `app/net.sf.VICE/x86_64/master not installed`. Every session has to be told which title it is driving, because `SSBSession` does not know. The five actions run before the walk, because a walk starts fights and every action is refused in one. Three checks stage a byte first (a wound for Heal party, roster `+0x0C` bit 7 for Quickfight off, an item's hidden-name bits for Identify, a memorised spell id for Save/Restore spells) because no save holds the situation; without the staged byte those checks report "nothing to do" and would pass by not looking.

###### Monster label draft rule (gui, monsterlabels.py)

The draft label `--propose` writes is the first letter of each word of the monster name, skipping ordinals, numbers and `LVL`, and the first and last letters when more than two remain. It is a guess to be corrected by hand and never rewrites a row already present. Colliding labels are expected and listed in the review document. The first run drafted 206 rows and none was approved.

###### Combat-label look (gui, combatbarsheet.py)

The combat map draws each square as a letter over a miniature health bar. The size below which a letter stops being readable is a measurement rather than a formula, which is why the tool sizes the letter in pixels to the room above the bar and prints what each label landed at.

###### Taskbar icon sheet (gui, taskbaricon.py)

Only whole delivered files were resized: an earlier sheet switched off elements and cropped in memory and was refused, and the test checked each cell equalled a fresh render of the whole file and that the delivery's hashes were unchanged. Row B was chosen, and `--shipped` drew what `ui.appicon.image` produces at the same sizes. `--measure` printed the SVG-versus-PNG gap that decided which PNG rows were kept. The tool was deleted once the choice was made, and `tests/test_taskbaricon.py` now holds one test, that the window's icon is the committed PNG scaled down.

###### Amiga body choice (gui, bodychoices.py)

Position 8 of the DOS and C64 creation menu draws a body that is in none of the Amiga's twenty-one body blocks, and writing 33 into an Amiga record reaches past the end of its menu table. An id present on both disks is not a picture present on both disks, which is why the sheet draws each panel from the art rather than comparing ids.

###### Amiga combat-icon art (icons, amigaicons.py)

The block ids in the Amiga `CHEAD.TLB` and `CBODY.TLB` libraries are DOS's own: 171,604 of 171,696 pixels match the same title's DOS `.DAX` through the sixteen-entry palette translation, and the 92 that differ are the hat-and-plume highlight. The libraries are `GLIB` containers of five-bitplane tiles, not the `.dax` format `goldbox/amiga_dax.py` reads.

###### Combat-icon numbering across the three DOS titles (icons, dosicontitles.py)

Curse's `CHEAD.DAX` and `CBODY.DAX` are 184 of 184 blocks byte-identical to Pool of Radiance's; Silver Blades has 182 identical, and the two it re-drew differ in how many 4-bit pixels moved and in which named parts each side uses. Each title's ICON menu wrap constants, read out of `GAME.OVR`, are 13 heads and 31 bodies in all three. The importer that reads the previous title's record copies `icon_head`, `icon_body`, `size` and the six `icon_colours` straight across with no table in between. Pools of Darkness blocks fail the 4-bit image test, so its art is a different encoding.

###### DOS and C64 combat-icon correspondence (icons, iconcorrespond.py)

DOS body `n` is not C64 weapon `n`. DOS offers 32 bodies and 14 heads in each of its two sizes, against the C64's 28 weapons and 14 heads small and 35 and 23 large. Scored over a small alignment window, the same index is the best match only once or twice per list, which is chance, and the highest overlap over all 1120 large pairings is 0.78, for the simple unarmed figure.

###### Mixed-size icons (icons, dosmixedicon.py)

Six weapon rows and three head rows of the DOS-to-C64 table land past the small lists of 28 and 14. A census of every `.SAV` and `.CHA` under the DOS specimens found 2 of 372 records on such a row, both the same Pools of Darkness character in two copies of one party, so no Pool of Radiance party available has one and it has to be staged. `--stage` rewrites `icon_head` `0x0BD` and `icon_body` `0x0BE` and leaves `size` `0x0C0` and the colours alone.

###### Staged DOS icons (icons, dosiconstage.py)

The one DOS party watched being written holds `icon_head` 0 and `icon_body` 0 for all six characters, so a conversion has nothing to say until the bytes are staged.

###### Colour nibbles (icons, dosnibbles.py)

A DOS `icon_colours` byte holds two 4-bit colours per part and the C64 keeps one, so a conversion picks a nibble; the conversion takes the low one as the main colour, and the pixel count is what says how often the choice makes a difference.

###### Reverse icon table (icons, iconreverse.py and iconreverse.yaml)

Of the 100 C64 rows (63 weapon and 37 head options), 54 are forced because exactly one DOS option becomes that C64 one in the forward table and reversing it is the only answer that returns a player their own figure on a round trip; 14 are a pick among DOS options the forward table merged, where any pick round-trips; 32 are a C64 figure DOS has none of, which is where a person's eye is needed. A census of 222 combat icons over the three titles' C64 disks read back into 35 distinct kinds, all named. The reverse YAML's key is a C64 option and its value a DOS one, and both size sections are complete lists because C64 large weapon 3 and small weapon 3 are different drawings out of different tables.

###### Per-title overrides (icons, iconproposal.yaml and iconredrawn.py)

Silver Blades redraws three of the 253 `CHARPIC00` glyphs, so C64 weapon 13 at either size and large heads 8 and 13 are different pictures on a `SILVER-*.D64`. The C64 half of `iconproposal.py` was once drawn off `POOL3.D64` whatever `--title` said, on the strength of `SPELLE64` being the identical 1882 bytes in all three titles; the option tables are identical but the glyphs they name are not. The first override chosen was Silver Blades' DOS head 10 to C64 head 2; the body of that pair is still open. The disk to draw from is found through `gamedisks.yaml` and then by looking for the side that carries `SPELLE64`, `SPELLN64` and `CHARPIC00` together: `POOL3.D64`, `CURSE_A.D64`, `SILVER-1.D64`. With none of a title's own disks, the document is written with the DOS side complete and no C64 figure, because a document that stands another game's art in is worse than one that shows none. There used to be a `--from-markdown` that read a hand-edited document back; the YAML replaced the round trip.

###### Icon row proof (icons, iconrowproof.py)

The table is merged from four levels and the merge takes a title and a size, so a caller that forgets either gets the base answer and a complete, plausible figure that is not the one the player made. Staging head 10 and body 11 onto an engine-written Silver Blades party (specimen `WISH-SPEC-ssb-299-engine-resave`, off `SILVER-1.D64`) and running `--home` showed every large character coming home as head 4 with no title and head 10 with one, and the one small character as body 0 with no title and body 11 with one.

###### Second-pose icon codes (icons, iconswing.py)

In a fight the second nine screen codes are fetched while a character takes its turn and gone before the game asks for the next command, so no reading at a command bar ever found them. Driving with `Session.melee_turn` makes the party strike (35 blows on 42 turns, against 0 on 80 for a passing run). The save's own codes at `$4BE0 + slot * 36` are read exactly nine times a window a fight; the bitmaps `COM.PREP $122C` expands them into at `$9BE8 + slot * 162` have their second-pose block read 72 bytes at a time, once a turn, for the character the camera is centred on. `docs/186-ready-and-action.md` and `docs/174-combat-figures-in-the-running-game.md` hold the findings.

###### Condition-badge grading (icons, inkcount.py and iconsheet.py)

The two numbers grading a badge are ink pixels (how much of the glyph survives; `invisible` was dropped at 55) and connected pieces (whether it survives as one thing; `hat-wizard`'s brim stopped touching its cone and it read as a shark's fin at 13 pixels). A table of icon names is how `hat-wizard` got chosen; `iconsheet.py` exists so icons are judged at the size they are seen.

###### Portrait reading (icons, portraitshot.py and dosportraitparty.py)

A conversion that wrote character 1's portrait into all six records passes a one-sheet check, so the check must be per character. Position 12 of the creation table draws `$39`, the twelfth entry, which fixed the menu positions as one-based. The DOS character sheet has no next-character key: sixteen keys were pressed and the art never changed, hence the `--first K` swap of two of the six 41-byte party entries at file offset 12809 of `SAVGAM<slot>.DAT`. The three handles that isolated a faceless converted party to one word of `SAVGAM<slot>.DAT` were `--rewrite`, `--template` and `--words 49FF=3`.

###### Portrait menu table (icons, portraitmenu.py)

The stored `POOL_OF_RADIANCE_MENU` matches what was read from the C64 `GEN` and DOS `START.EXE` on the machine it was made on; `--check` is the test for a release whose menu differs. Nothing but the ids leaves either file, so no game data is stored.

###### Defeat screen (pool_of_radiance, defeatdrive.py)

Losing a fight prints `THE PARTY HAS LOST`, sets `$6DC7` to `$80`, leaves all six characters `DYING` and the save disk untouched, and 66 of 66 program-counter readings sit at `$0957`, which is `POST.COM`'s `JMP $0957`.

###### Wilderness step refusals (pool_of_radiance, outdoorstep.py and outdoorwalk.py)

On the square an Amiga party sails to, selecting `MOVE` puts up `TAKE BOAT STAY` and a picture of the boat rather than `1-8, RETURN OR BUTTON`, so a driver that knows only those two prompts waits out its timeout in front of a game that is asking a question; `TAKE` sails the party back to New Phlan and destroys what a step measures, hence `--boat STAY` as the default. Outdoors the status line reads `OUTDOORS 22:02 7,28`, with the word where the facing letter goes, and it lags the step by about a second; an overland step is about twelve hours of game time, so the walker polls rather than sleeping. A title that reads keys from only one of XTEST and the KERNAL buffer looks exactly like a party hemmed in, so each digit is tried both ways.

###### Attract-loop stall (pool_of_radiance, porattract.py)

The same opening loop stopped three times in three runs on a C64 Ultimate; this is the control for it. A monitor connection held across the sample loop stops the emulator for as long as it is open, which on the tool's first run froze the machine and then reported it as stalled.

###### Ohlo's errand (pool_of_radiance, ohlowatch.py)

`Session.walk_one` cannot verify a step in the Slums, whose status line carries no coordinates, and `$4A80` has to be held at its own cap of 15 or a wandering fight arrives on the step into the booth. `$4A81` sampled every 0.4 s gave the 22 s and 49 s the two visits took. The menu options, prompt and booth word are 6-bit packed (four characters to three bytes) in `ECL14`.

###### Fight tools (pool_of_radiance, fightrun.py)

Three copies of this driver were written in scratch for the fight-driving investigations and thrown away with them; the tool is the kept one.

###### Curse area 0 (curse_of_the_azure_bonds, curseareazero.py)

A Curse save made at the party-formation menu holds area 0, map 0, disk hint 2, twenty-five zero cache slots and clock 00:00, the same numbers a DOS save made at the same menu holds. The file an area-0 save sends the loader after is `GEO00`, found by reading the KERNAL's `SETNAM` state when the game asks for a disk. `--patch-early` was suspected of killing the machine and cleared: the same disk crashed with no patch at all. Changing four header fields at once and crashing proves nothing about any of them, hence `--zero`.

###### Loading a Curse save (curse_of_the_azure_bonds, curseload.py)

`GEN $1F42`'s loader is `LIBRARY $3159`, a simple KERNAL `LOAD` whose name pointer is written into the operands of `$319F`; `$401E` turns the result into a number. With no fastloader installed (`$7E9F` = 0, the party menu's state) that number is the 1541's own error code at `$03F1`: 62 the save disk was never in the drive, 74 the load was taken inside the drive's settling time after the attach, 60 the image's `SAVEAZURE` is a file the drive never closed. `docs/179-loading-a-curse-save.md` has the three differentials.

###### Curse save-disk build (curse_of_the_azure_bonds, cursedisk.py)

The 25 area rows re-derived from the player's disks through `tools/areas/areatable.py` all agreed with the copy held in the tool. Curse's `SAVEAZURE` is one 7424-byte payload at `$4B00` holding eight slots, a name table, eight item pages, `ANIMATE00`'s picture buffer and the roster; Curse gives the memorised-spell list 69 slots.

###### Curse picture buffer (curse_of_the_azure_bonds, cursepic.py and cursepicrun.py)

The 1024 bytes at `+$1800` of a `SAVEAZURE` are `ANIMATE00`'s picture buffer at `$6300`, not map memory: the glyph bitmaps and colour bytes of the picture in the view window at whatever frame its animation had reached when `ENCAMP > SAVE` saved `$4B00`-`$67FF` in one KERNAL `SAVE`. On `ENCAMP` that picture is always `PIC1D`, the camp scene, so every engine-written Curse save carries one frame of a campfire, and a Wish-written save (zeroes there, never read back by the engine) reads 526 differing bytes against every frame. See `docs/181-curse-picture-buffer.md`.

###### Curse regained-class specimens (curse_of_the_azure_bonds, cursepaladin.py and curseregain.py)

`cursepaladin.py` made `WISH-SPEC-curse-409-regained-paladin`, the first C64 record anywhere whose `class_bits` is a pair `GEN $1951` has no class code for; the game's own answer on the `VIEW` sheet is `CLERIC/PALADIN` and `LEVEL 6/5`. `curseregain.py` made `WISH-SPEC-curse-408-regained-paladin`, the first DOS record past the regain threshold anybody here watched being written. Three things cost a C64 run each: `VIEW CHARACTER` puts up a picker and not a sheet, a training leaves the `TRAIN WHO` list up so the next menu lookup spends its whole timeout, and `SAVE CURRENT GAME` asks `SAVE GAME ? YES NO`, which like Curse's other bars answers only the KERNAL buffer. An ability goes into both of the record's two arrays because `GEN $1E9C` copies one into the other.

###### Curse disk-swap prompt (curse_of_the_azure_bonds, curserun.py)

The loop at `$453B` leaves only on a key read plus a command-channel answer of `00`, and the drive answers DOS error 62 continuously; three explanations were measured and all came back negative, so the prompt is patched instead. Curse's move handler answers only the KERNAL buffer, and Curse has no travel grid, so `Session.indoors()` must not read Pool of Radiance's `$49E6`. The first Curse save carrying items was made by shopping in Tilverton rather than fighting.

###### Curse save diff (curse_of_the_azure_bonds, cursesavediff.py)

The engine's own `ENCAMP > SAVE` is the oracle a conversion is checked against. On the first conversion run 538 differing bytes in 97 runs became four lines, all `engine`: `ANIMATE00`'s picture buffer (526), the loaded-files cache the arriving script refills (9), the two per-area constants `ECL01` writes at its head (2) and one clock digit.

###### Curse THAC0 test (curse_of_the_azure_bonds, cursethac0.py)

The staged `0x0A` is THAC0 50, twenty-six below anything `GEN $1F1F` can produce, so a fight that uses it is unmistakable. A greedy walk cannot leave Tilverton's start because the door north of `7,12` is locked, so the route is planned from the area's `GEO` passability; `PUNCH BARKEEP` is the cheapest fight in the title. Two counting checkpoints on `LIBRARY $3918` and `$394B` separate "nothing recomputed" from "recomputed to the same number".

###### Curse trainer lever (curse_of_the_azure_bonds, cursetrain.py)

`GEN $12AF` builds the party menu's item mask and clears bit 3, `TRAIN CHARACTER`, whenever `$7EA8` is zero. The area scripts write 127 there in a hall (`ECL01`, `ECL03`, `ECL50` and `ECL51` each issue `SAVE 127, =[$7EA8]`) and `GEN $2029` resets it to 0 on leaving, so poking one byte opens the hall wherever the party stands. Across five driven Curse level-ups, 75 of 75 derived fields matched `goldbox.levelup.plan`. Four things in the front end have to be watched, hence `run` serves rather than pressing keys (`docs/172-curse-trainer.md`).

###### Curse fast travel (curse_of_the_azure_bonds, cursewarp.py)

Curse can be fast-travelled. Warping out of the travel grid wedges the loader unrecoverably, on Pool of Radiance's precedent, so it needs `--force`. The Curse load bar reads `LOAD SAVED GAME ? YES NO` rather than Pool's `LOAD SAVED GAME: YES`, that `YES` answers only to the KERNAL buffer and not to an XTEST Return, and the game never prompts for the save disk: it reads `SAVEAZURE` off whatever is in unit 8 and says `UNABLE TO LOAD SAVED GAME.`

###### Curse code wheel (curse_of_the_azure_bonds, cursewheel.py)

A strict overlap ranks the right rune no better than the wrong one, so the glyph mask is matched as normalised grids with a cell of slack. A dash prompt marks only every other cell of its nine, so the path reader looks for a run of five or more marked cells with nothing but text between them, not five in a row; the first reader never matched a live capture. The command line prints nothing that identifies a challenge, an answer or a path.

###### DOS camp keys (curse_of_the_azure_bonds, doscurse.py)

In the party panel the highlight moves with `Home` and `End` in Curse and with the arrow keys in Silver Blades; eleven candidate keys were refuted per title, and the Archives' own `Controls.pdf` says `PgUp`/`PgDn`, which is wrong.

###### Silver Blades driving (secret_of_the_silver_blades, ssbwarp.py)

A cracker intro stands in front of the game and answers to none of its keys. The fastloader prompt comes after that intro, not before it, so a driver that waits for it up front waits forever. The loader letters its sides, `INSERT SIDE A` through `F` for sides 1 to 6. The party never reaches a command bar, so a trip leaves from the first moment the machine idles in `DUNGEON`'s key-wait loop or the `LIBRARY $4101` fetcher, and a landing is judged by the cache slot and the resident map, never by the program counter: an arrival on an encounter bar idles above `$6900` in neither key window. A boot costs five minutes and a hop thirty seconds, which is why `--to` takes a chain.

###### Silver Blades probes (secret_of_the_silver_blades, ssbarm16*.py, ssbload*.py, ssbstep1512.py, ssbtailprobe.py, ssbreturnprobe.py, ssbrevalidate.py, ssbarm2route.py, ssbstage.py)

These were written to make the session driver fight in Silver Blades. The wandering-encounter roll's fight-or-compliment gate is `$4C2D` (`SAVEDBASH`'s load address `$4B00` plus file offset `$12D`), off by default on every specimen driven. Block 28 of `ECL10` is `$9AC8`-`$9B64`. The `enter_world` Escape fix and the question of whether Escape aborts a KERNAL load (`ssbloadescape.py` against `ssbloadnoescape.py`) were the two variables. `ssbarm2route.py` finds a route to 15,12 that never enters the 14,11 shop.

###### Silver Blades trainer and rename (secret_of_the_silver_blades, ssbtrain.py, ssbedit.py and ssbtrainerinputs.py)

Silver Blades' party-menu builder is Curse's `$12AF` moved to `GEN $0991`, still `LDY $7EA8 / BNE / AND #$F7`, so poking `$7EA8` to 127 opens the training hall wherever the party stands. The `+$C00` name table runs in marching order in this title and in slot order in Curse, so a slot is found by the name inside the record. `ssbedit.py` writes through `EditorBinding` rather than poking a record so the shipped write path is what is measured.

###### Silver Blades twins (secret_of_the_silver_blades, ssbtwins.py)

Converting the six DOS characters SSI shipped and diffing them against the six C64 records found the ranger arriving as a paladin and the lower-case name, before either was watched in the game. Neither side has a chain of custody, so it is a consistency check and not proof.

### What the rule files said before they dropped their history

The rule files state the rule and carry no history. These are the passages they held on this section's subject before that cut, verbatim.

#### .claude/rules/documentation.md

> `docs/TASKS.md` and its `P` codes are
> retired

`docs/TASKS.md` does not exist, and the rule says so while still banning a citation of a P code.

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
and it is recorded under Banned Words: the licence credit for Lorc's
*Embraced energy* was written from the filename rather than from the title its
author gave it.

### What the rule files said before they dropped their history

The rule files state the rule and carry no history. These are the passages they held on this section's subject before that cut, verbatim.

#### art.md

Cut, lines 10-12 ("No AI-generated art" paragraph; the rule stays, the attribution to Donald goes):

> **No AI-generated art, anywhere, ever.** Not icons, not logos, not textures, not
> placeholders "until we find a real one". This is Donald's rule and it is not
> negotiable by an agent that finds it inconvenient.

## Qt Designer

No incident sits behind this one. Building layouts in `.ui` files and compiling
them with `tools/generate/genui.py` is a design decision taken at the start, so that a
human can rearrange a form in Designer without a line of Python changing;
`editor/character.ui` has worked that way since the character editor was
written, and `tools/generate/genui.py --check` catches drift in CI.

## Feature flags

The only history here is the feature that produced the rule. The DOS import was
the first flagged feature: it worked, it was proven in the emulator, and it
still dropped the portrait and the clock -- `#57 (Convert the character
portrait across ports)` and `#58 (Decode the DOS clock, so converted saves keep
the time of day)` -- so `File > Import` was not built unless the flag said to
build it, from 2026-08-24 until `#131 (Lift WISH_EXPERIMENTAL_DOS_IMPORT, which
needs the import working for all three C64 titles)` closed on 2026-09-06. That
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

### What the rule files said before they dropped their history

The rule files state the rule and carry no history. These are the passages they held on this section's subject before that cut, verbatim.

#### .claude/rules/feature-flags.md -- opening paragraph

> The DOS import was the first: it
> worked, it was proven in the emulator, and it still dropped the portrait and
> the clock -- so `File > Import` was not built unless the flag said to build
> it, until `#131 (Lift WISH_EXPERIMENTAL_DOS_IMPORT, which needs the import
> working for all three C64 titles)` closed on 2026-09-06.

The example sentence naming code that no longer has the `if`:

> `wish/window.py` builds the Export submenu inside the `if`.

`wish/window.py` no longer has an Export submenu or a flag around the convert
entry (`WISH_EXPERIMENTAL_CONVERT` was lifted; the menu is built for
everyone), so the sentence had become false. The rule now says "Build the menu
entry inside the `if` that reads the flag."

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

### What the rule files said before they dropped their history

The rule files state the rule and carry no history. These are the passages they held on this section's subject before that cut, verbatim.

#### .claude/rules/sessions.md -- "A turn that ends with nothing running"

> A backgrounded `pytest`
> has come back `killed` rather than with a result four times.

