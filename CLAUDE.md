# Working notes for Claude

@AGENTS.md

## What is different for Claude Code

The rules are in `AGENTS.md`, imported above, because Google's tools read that
name and not this one. Everything there binds here. This file holds only what is
true of Claude Code and of nothing else, so `AGENTS.md` stays honest for both.

**Six of the thirteen rule files load at launch and seven load when you read a
file they cover**, so the routing table in `AGENTS.md` is mostly a formality
here. It is not one for a reader that has no such mechanism.

**A subagent inherits this file, `AGENTS.md`, and the same six unscoped rule
files, exactly as you do.** What it does not get until it touches a matching file is the seven
`paths:`-scoped ones -- so a brief only needs to name one of those, when the
agent's work will not itself touch a file that loads it.

## Documentation and comments carry no history

A README is a lookup table: one row per file saying what it is for, in one
sentence, under an intro of one sentence at most. A code comment or docstring
says what a thing does and, if needed, why, in a sentence. A rule file states
the rule. **None of them carries history:** no dates, no issue numbers, no
account of what an earlier version did or who decided what. History lives in
`docs/160-why-these-rules.md` or in the commit message, and any of them may
link there. In a `docs/` write-up, say why a claim changed; nowhere else.
`.claude/rules/documentation.md` has the rest.

## Banned Words

| instead of | say |
|---|---|
| **corpus** | say what it is: "the saves we have", "the specimens", "every save on this machine", "the files" |
| **load-bearing** | what holds it up, what depends on it, what breaks without it |
| **fair**, in any construction -- "fair", "fair enough", "fair point", "that's fair" | agree or disagree in words: "you're right", "I don't think so, because" |
| **blast radius** | what else this touches, what it would break |
| **elide** | truncate, shorten, cut off with an ellipsis |
| **obviate** | it cannot happen any more, the fix is no longer needed |
| **retarget** | move the party to where it actually was, point the save at the right map |
| **shape**, the whole word, in every construction -- "the payload shape", "the shape of the fix", "the shape of the work", "the same shape as", "it takes this shape" | say which one you mean: **structure**, **format**, **form**, **kind**, **design**, **what it must do**, **what it looks like**. **There is no exemption**, including for phrases that appear in the project's own documents. It reads as precise and says nothing, which is what this whole table is about. A class named `DosShape` keeps its spelling, like `setTextElideMode` -- the ban is on prose |
| **"X follows Y"** | say what happens: "gets taller as Y grows", "is recomputed whenever Y changes" |
| **"bites"** -- a test, a bug, a case | say what happens: the test fails without the fix; the conversion drops a figure |
| a file "walks", "arrives", "stands" | name who does it: *the party* walks, *the player* sees it |
| **worth** -- the whole word, in every construction. "worth saying", "worth knowing", "worth a look", "worth having", "worth the work", "it is worth noting", "for what it is worth" | say the thing, or say what it costs and what it gets. The word rates a sentence instead of writing one, and a reader cannot argue with a rating |
| a sentence that rates itself by any other route: **"says so out loud"**, "the important thing here", "note that", **"narrower than it looks"**, "worse than it looks", "worse than I said", "the interesting kind", "the thing to look at hardest", "this is the useful part", **"earned its keep"**, "paid for itself", "was the right call" | delete the rating and keep the sentence -- you would not have written it otherwise. The whole family is banned, not the three examples |
| **plain**, the whole word -- "plainly", "say plainly", "in plain terms", "in plain English" | **simple**, wherever an adjective is wanted. Where it is a preamble rather than an adjective, delete it: "say plainly" and "put simply" both promise the next sentence will be clear, which is not the same as writing one. Just say the thing |
| **floor**, for anything but a story of a building -- "a floor under the window", "a green suite is the floor" | say the thing: "the window never gets narrower than this", "passing it proves nothing broke" |
| **carried**, of anything a conversion does not convert -- "not carried", "carries it across", "nowhere to carry it" | **converted**, and then say what a player loses: "the ring does not resist fire on the other side yet". The word is how an agent gives up and makes it sound like a finding. |

**A row's examples are examples; the word is banned however it is phrased**,
and the table is not the whole rule -- the habit behind it is reaching for
jargon that sounds precise and carries less than the phrase it replaced.

**Do not give a file the verb that belongs to the people in it.** A save cannot
walk; a **party** walks. Code
is the exception where the API names it: Qt's `setTextElideMode` keeps its
spelling. `embrassed-energy` is spelled **embraced** in prose, keeping the
typo only in the identifier, the
archive filename and the URL.
