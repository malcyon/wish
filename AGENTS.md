# Working notes for this repository

The rules that bind every task, wherever in the tree it lands. The rest is
thirteen files under `.claude/rules/`, reachable as `.agents/rules/` as well --
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
| Write a script, or leave a file in `work/` | `scratch.md` |

Seven cover one area of the tree each: `testing.md`, `conversions.md`,
`gui-text.md`, `qt-designer.md`, `documentation.md`, `art.md`, `emulator.md`.

## Name every issue you cite

**This is a rule about talking to Donald.** In a reply to him, in an issue
comment he will read, in a document: `#59 (Map the DOS saved game, not just the
character record)`, never a bare `#59`. **Every mention** -- there is no
"already introduced it above" exemption, because a reply is skimmed rather than
read in order. The title comes from `gh issue view N --json number,title`.

A bare number makes him do the lookup: fast for the assistant, which has the
number in hand, slow for him. *"When you only reference a number, it never means
anything to me."* As the **subject** of a sentence it is worst of all.

**It does not govern code.** Donald, 2026-09-09: *"I don't care about bare issue
numbers in code or docstrings. I care about it when you are communicating with
me."* A docstring is read by somebody already in that file, and
`tests/test_repository_contents.py`'s guard scans Markdown for that reason. Do
not sweep `.py` for bare numbers and do not file tickets about them.

Nor a **commit message**, where the number goes bare in parentheses at the end
of the line, nor the **body of an issue**, read on the web where the number
hovers into its title -- so do not go back and add titles to bare numbers in
existing bodies.

## Writing

Say the thing once, in as few words as carry it. Length is not thoroughness.
Cut preamble, restating the request, summarising what you just did in the same
breath as doing it, and hedging. Keep offsets, byte values, exact error strings,
and the reason a choice was made. **If a sentence would survive deletion without
the reader losing anything, delete it.** Lead with the answer, findings before
method, tables for more than three data points, no closing summary of a reply
the user just read. Report a failure with the shortest decisive line of output.

**Explain a bug by the situation a person is in when they hit it, before the
mechanism.** Not "`_flush` swallows a `ValueError`" -- *"you rename a
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

## Caveman lite is the default, in every session

Donald reads this project in **`/caveman lite`**. It is the standing setting
rather than something he asks for each time: **set it at the start of a session
and keep it until he says "stop caveman" or "normal mode".**

Lite is the gentlest level. **No filler and no hedging; articles and full
sentences stay.** It is not the telegraphic register -- do not drop articles,
do not write fragments, and never add a word to sound terse. Everything under
"Writing" above still binds, and where the two disagree, clarity wins.

**It governs the terminal and nothing else.** Anything that leaves the session
in normal prose: commit messages, issue bodies and comments, `docs/`, code and
its comments, README rows, and a brief written for a subagent.

## Words to avoid

| instead of | say |
|---|---|
| **load-bearing** | what holds it up, what depends on it, what breaks without it |
| **fair**, in any construction -- "fair", "fair enough", "fair point", "that's fair" | agree or disagree in words: "you're right", "I don't think so, because" |
| **blast radius** | what else this touches, what it would break |
| **elide** | truncate, shorten, cut off with an ellipsis |
| **obviate** | it cannot happen any more, the fix is no longer needed |
| **retarget** | move the party to where it actually was, point the save at the right map |
| **"X follows Y"** | say what happens: "gets taller as Y grows", "is recomputed whenever Y changes" |
| **"bites"** -- a test, a bug, a case | say what happens: the test fails without the fix; the conversion drops a figure |
| a file "walks", "arrives", "stands" | name who does it: *the party* walks, *the player* sees it |
| **worth** -- the whole word, in every construction. "worth saying", "worth knowing", "worth a look", "worth having", "worth the work", "it is worth noting", "for what it is worth" | say the thing, or say what it costs and what it gets. Donald, 2026-09-06: *"You've abused it past my point of tolerance. You are constantly telling me something is worth knowing, or worth saying, or worth this or that. I've had it."* The word rates a sentence instead of writing one, and a reader cannot argue with a rating |
| a sentence that rates itself by any other route: **"says so out loud"**, "the important thing here", "note that" | delete the rating and keep the sentence -- you would not have written it otherwise |
| **plainly** -- "say plainly", "state it plainly", "put it plainly", and the same promise without the adverb: "in plain terms", "put simply", "in plain English" | just say the thing. The word promises the sentence after it will be clear, which is not the same as writing one |
| **floor**, for anything but a story of a building -- "a floor under the window", "a green suite is the floor" | say the thing: "the window never gets narrower than this", "passing it proves nothing broke" |
| **carried**, of anything a conversion does not convert -- "not carried", "carries it across", "nowhere to carry it" | **converted**, and then say what a player loses: "the ring does not resist fire on the other side yet". The word is how an agent gives up and makes it sound like a finding -- Donald, 2026-09-04: *"The agents just give up and say 'oh well, we can't convert it'. But they call it carried instead, which confuses me."* |

**A row's examples are examples; the word is banned however it is phrased**,
and the table is not the whole rule -- the habit behind it is reaching for
jargon that sounds precise and carries less than the phrase it replaced.

**Do not give a file the verb that belongs to the people in it** -- *"I don't
know what a save walking means."* A save cannot walk; a **party** walks. Code
is the exception where the API names it: Qt's `setTextElideMode` keeps its
spelling. `embrassed-energy` is spelled **embraced** in prose, keeping the
typo only in the identifier, the
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

## Delegating

**The default is to delegate** -- reading a lot of files, a long experiment, a
disassembly, driving the emulator, writing something up. The reason is context:
a subagent's tool output never enters the main window. **Give each agent its own
files**, and say which in the brief along with the standing constraints above,
because a subagent starts cold. **Every agent gets an escape hatch, and using it
is a success**: work that needs something the agent is not for stops and says
so, because pressing on into a decision that was not its own costs more than the
re-route. Which agent for what, how to write the brief, and the
commit-review-push sequence: `.claude/rules/delegating.md`.

## Findings go on the issue, when they arrive

Not at the end of the work, not only in the reply, not only in `docs/` -- on the
issue, while the agent that found it is still the thing that knows it. **This
includes the findings that are not the answer**: a refuted hypothesis, an
unremarkable measurement, the thing you could not reach and why. Those are the
expensive ones to rediscover. **A bug you find and decide not to fix gets an
issue in the same session**; the bar is low.

## Before you commit

Run all three from the repository root. A green suite proves nothing broke.
It is not what you set out to learn.

1. `pytest` **on the files you touched**
2. `.venv/bin/ruff check .`
3. `.venv/bin/python3 tools/genui.py --check`

**The whole suite runs once, in a detached worktree, before the push.** Six
agents each running all 3,190 tests is six copies of Qt on one machine, and on
2026-09-04 that cost a reviewer its run. **One run, not six -- that is the
rule, and who starts it is not.** The main window either makes that run or
sends it to `test-runner`, whose whole job it is; never both, and never two at
once. The message, the push, the CI check, and where to run it:
`.claude/rules/commits.md`.
