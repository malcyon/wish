# Working notes for Claude

@AGENTS.md

## What is different for Claude Code

The rules are in `AGENTS.md`, imported above, because Google's tools read that
name and not this one. Everything there binds here. This file holds only what is
true of Claude Code and of nothing else, so `AGENTS.md` stays honest for both.

**Six of the thirteen rule files load at launch and seven load when you read a
file they cover**, so the routing table in `AGENTS.md` is mostly a formality
here. It is not one for a reader that has no such mechanism.

**A subagent inherits this file and `AGENTS.md`, and does *not* inherit
`.claude/rules/`.** So a brief has to name the rule files its agent needs, and
an agent should read the ones its brief names rather than assuming they arrived.

## Words to avoid

**This table is here rather than in `AGENTS.md` because it is a list of
*this model's* habits.** Donald, 2026-09-10: *"Codex doesn't say those words.
Claude does. It's a claude problem."* Every row was written down after Claude
reached for the same jargon again -- so it corrects one model's writing rather
than setting a house style, and a tool that does not have the habit does not
need the rule. The writing rules that bind **any** agent are in `AGENTS.md`
under "Writing"; this is the Claude-only appendix to them.

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
| a sentence that rates itself by any other route: **"says so out loud"**, "the important thing here", "note that", **"narrower than it looks"**, "worse than it looks", "worse than I said", "the interesting kind", "the thing to look at hardest", "this is the useful part", **"earned its keep"**, "paid for itself", "was the right call" | delete the rating and keep the sentence -- you would not have written it otherwise. Donald, 2026-09-09: *"This is unnecessary filler. Shouldn't caveman lite prevent you from saying things like this?"* It should; the whole family is banned, not the three examples |
| **plain**, the whole word -- "plainly", "say plainly", "in plain terms", "in plain English" | **simple**, wherever an adjective is wanted. Donald, 2026-09-09: *"Anytime you ever, ever ever think you should use the word plain, you should be using the word simple instead."* And where it is a preamble rather than an adjective, delete it: "say plainly" and "put simply" both promise the next sentence will be clear, which is not the same as writing one. Just say the thing |
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
