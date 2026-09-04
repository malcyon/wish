# Working notes for this repository

The rules that bind every task, wherever in the tree it lands. The rest is
twelve files under `.claude/rules/`, reachable as `.agents/rules/` as well --
the same files, by symlink. `docs/160-why-these-rules.md` has the incidents
behind all of it. **Read the one covering what you are about to do**, whether or
not it is already in front of you.

| Before you | Read (all under `.claude/rules/`) |
|---|---|
| Commit, push, or check CI | `commits.md` |
| File, label, prioritise or close an issue | `issues.md` |
| Write a brief for a subagent | `delegating.md` |
| End a turn, or end a session | `sessions.md` |
| Put a major feature behind a flag | `feature-flags.md` |

Seven cover one area of the tree each: `testing.md`, `conversions.md`,
`gui-text.md`, `qt-designer.md`, `documentation.md`, `art.md`, `emulator.md`.

## Name every issue you cite

`#59 (Map the DOS saved game, not just the character record)`, never a bare
`#59`. **Every mention** -- replies, comments, documents, tables, and the prose
around a table as much as the table. There is no "already introduced it above"
exemption; a reply is skimmed, not read in order.

A bare number makes Donald do the lookup: fast for the assistant, which has the
number in hand, slow for him. *"When you only reference a number, it never means
anything to me."* A number used as the **subject** of a sentence is the worst
place for it, because that is where the reader most needs to know the subject.

```sh
gh issue view N --json number,title -q '"#\(.number) (\(.title))"'
```

Two exceptions, both about where the reader is: a **commit message**, where the
number goes bare in parentheses at the end of the one line, and the **body of an
issue**, read on the web where the number hovers into its title. Do not go back
and add titles to bare numbers in existing bodies.

## Writing

Say the thing once, in as few words as carry it. Length is not thoroughness.
Cut preamble, restating the request, summarising what you just did in the same
breath as doing it, and hedging. Keep offsets, byte values, exact error strings,
and the reason a choice was made. **If a sentence would survive deletion without
the reader losing anything, delete it.** Lead with the answer, findings before
method, tables for more than three data points, no closing summary of a reply
the user just read. Report a failure with the shortest decisive line of output.

**Explain a bug by the situation a person is in when they hit it, before any of
the mechanism.** Not "`_flush` swallows a `ValueError`" -- *"you rename a
character to `Bel'ana`, the apostrophe is a curly one because you copied it off
a web page, you click Save, it says 'no changes', and the box still shows the name you
typed."* Then the cause. A reader who has not seen the code cannot tell from a
description of it whether the bug matters. Write the situation even when it is
unflattering: **"no user can reach this" is an answer.**

**Every line a person reads opens with a capital letter** -- your replies in the
terminal as much as anything in the window. **Never open a sentence with a
quotation that starts lowercase**; put words in front of it. Anything a user
reads *in the interface* is Donald's to approve and carries no memory address or
offset -- `.claude/rules/gui-text.md` has both rules and how to apply them.

## Words to avoid

| instead of | say |
|---|---|
| **load-bearing** | what holds it up, what depends on it, what breaks without it |
| **fair** ("that's fair") | agree or disagree in words: "you're right", "I don't think so, because" |
| **blast radius** | what else this touches, what it would break |
| **elide** | truncate, shorten, cut off with an ellipsis |
| **obviate** | it cannot happen any more, the fix is no longer needed |
| **retarget** | move the party to where it actually was, point the save at the right map |
| **"X follows Y"** | say what happens: "gets taller as Y grows", "is recomputed whenever Y changes" |
| **"the test bites"** | the test fails without the fix; it goes red when the guard is removed |
| a file "walks", "arrives", "stands" | name who does it: *the party* walks, *the player* sees it |
| **"saying so plainly"**, **"says so out loud"** | drop the announcement and say the thing: "the label is wrong, because" |

A habit rather than a blocklist: reaching for jargon that sounds precise and
carries less than the plain phrase it replaced. **Do not give a file the verb
that belongs to the people in it** -- *"I don't know what a save walking
means."* A save cannot walk; a **party** walks. Code is the exception where the
API names it: Qt's `setTextElideMode` keeps its spelling. `embrassed-energy` is
spelled **embraced** in prose, keeping the typo only in the identifier, the
archive filename and the URL.

## What must never enter this repository

This project documents a game it does not ship. **Never commit, in any form:**

* the game's **art, music or sound** -- sprites, tilesets, portraits, SID tunes;
* its **manuals, cluebooks, maps or journal entries**, scanned or retyped;
* its **executable code**, whole or in part -- overlays, PRG files, boot images;
* **a disassembly listing** of it. Quoting as much as a finding needs is
  commentary and encouraged; a short block is fine. A dump of a routine is not.
* its **data files** -- maps, tables, scripts, records -- as committed bytes,
  **including as test fixtures**. A fixture that is a slice of a game file is
  the same copy under a new name.

Disk images are gitignored; keep them under `work/` and read them at run time
from the player's own. **Describe, cite, measure and generate. Do not copy.**

## Git in a shared tree

**No agent runs `git checkout`, `git restore`, `git reset`, `git stash` or
`git clean` against a file in this repository.** Several agents share one tree,
so a revert is never local to the agent doing it: it discards whatever anybody
else has uncommitted, silently. That is how 580 lines of `por/amiga.py` went.

**Subagents do not `git add` and do not commit.** The main window commits, so
nothing races the index; an agent that stages is one `git commit` away from
putting half-finished work on `main`. **Do not edit a file you have assigned to
an agent** -- if you must, say so in a message to that agent, and prefer putting
back the one hunk you changed to restoring the whole file you remember.

To test whether a change matters, copy the file aside and copy it back, `diff`
to confirm, **and then delete `__pycache__`** -- a file put back at the same size
in the same second does not look changed to CPython's bytecode cache. Take that
copy immediately before the change you are testing, never at the run's start.

## The machine

Donald works at this desktop while agents run. **Nothing an agent runs may put a
window on his screen.** `tests/conftest.py` forces `QT_QPA_PLATFORM=offscreen`,
so `pytest` is safe; everything else is not. `QWidget.grab()` works offscreen.

```sh
env -u WAYLAND_DISPLAY -u XDG_SESSION_TYPE QT_QPA_PLATFORM=offscreen \
    GDK_BACKEND=x11 .venv/bin/python your_script.py
```

**Unsetting `WAYLAND_DISPLAY` is easy to miss**: his desktop is Wayland and a
GTK or Qt child prefers it over whatever you set for X, so a private `Xvfb` is
not a sandbox.

**An agent's `ssh` must never be able to ask a human anything.** With no tty and
`DISPLAY` set, OpenSSH runs `SSH_ASKPASS`, which here draws a KDE credential
dialog on his screen. Set both, in anything shelling out to `ssh`:

```sh
SSH_ASKPASS_REQUIRE=never ssh -o BatchMode=yes ...
```

**Ports 6502, 6510 and 6600 are Donald's** -- anything there is a game a human
started, so do not attach, probe or kill it. The pool allocates from 6520 up.

**Never kill a process by name** -- not `pkill -x x64sc`, not `pkill -x Xephyr`.
Kill only the process group your own slot launched. The one time this was broken,
what died was his own window.

## Scratch files

`work/` is for a **run's output** -- logs, dumps, screenshots, disk images -- and
is gitignored because most of it derives from the game's bytes. It is
snapshotted hourly to OneDrive here, and **that is not a reason to leave
anything valuable there**: it has been lost twice.

**A tool goes in `tools/`, committed, with a row in `tools/README.md`.** A
runner, a probe, a sweep, a one-off script that answered a question: every one is
a tool, however throwaway it felt. The test is whether somebody would otherwise
write it again. `ecl6.py` decoded all thirty ECL scripts and was lost.

## Delegating

**The default is to delegate** -- reading a lot of files, a long experiment, a
disassembly, driving the emulator, writing something up. The main window
coordinates and answers questions. The reason is context: a subagent's tool
output never enters the main window.

**Give each agent its own files** -- several in one tree collide. Say which in
the brief, along with the standing constraints above, because a subagent starts
cold. Which agent for what, the brief, and the commit-review-push sequence are
in `.claude/rules/delegating.md`.

**Every agent gets an escape hatch, and using it is a success.** If the work
needs something the agent is not for -- a general-purpose agent finding it needs
a real disassembly -- it stops and says so. Pressing on into a decision that was
not its own costs more than the re-route.

## Findings go on the issue, when they arrive

Not at the end of the work, not only in the reply, not only in `docs/` -- on the
issue, while the agent that found it is still the thing that knows it. **This
includes the findings that are not the answer**: a refuted hypothesis, an
unremarkable measurement, the thing you could not reach and why. Those are the
expensive ones to rediscover. **A bug you find and decide not to fix gets an
issue in the same session**; the bar is low.

## Before you commit

Run all three from the repository root. A green suite is the floor, not the
finding.

1. `pytest` -- the **whole** suite, not the files you touched
2. `.venv/bin/ruff check .`
3. `.venv/bin/python3 tools/genui.py --check`

The message, the push, the CI check, and running the suite somewhere the other
agents are not: `.claude/rules/commits.md`.
