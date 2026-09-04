# Issues

**GitHub issues are the work list.** `gh issue list` is the register; `docs/`
is the knowledge base, and the two must not drift into being the same thing:
an issue tracks work and closes when the work is done, a doc records what is
known and outlives every issue that cited it.

**`gh issue list` defaults to `--limit 30`, and says nothing when it
truncates.** Pass `--limit` above the backlog size for any count, any sweep, or
anything an answer to Donald rests on.

**Open the description with one sentence restating the subject.** A body that
starts mid-argument reads like the second half of a conversation -- the title
is not the first line of the description, and nobody reads them as one.

**Reply, never rewrite.** Progress goes in a comment (`gh issue comment N`).
The description is what the author asked for, and editing it destroys the
record of what was originally wanted. Edit the description only to correct a
factual error in it, and say in a comment that you did.

## Citing an issue

**Name an issue when you cite it: `#59 (Map the DOS saved game, not just the
character record)`.** A bare number is a lookup Donald has to go and do:
*"when you only reference a number, it never means anything to me."*

```sh
gh issue view N --json number,title -q '"#\(.number) (\(.title))"'
```

It applies to replies, issue comments, documents and tables, every mention and
not just the first. **Two exceptions, both about where the reader is:**

* **A commit message**, where the number goes bare in parentheses at the end of
  the one line -- see `.claude/rules/commits.md`.
* **The body of an issue**, read on the web, where hovering the number shows
  the title. Donald, 2026-09-01: *"Leave them alone. GitHub.com shows the
  ticket details on hover and makes it a hotlink, so it will be fine."*

**So do not go back and add titles to bare numbers in existing issue bodies**,
and do not treat one as a defect in an audit. It is not a factual error, so
"Reply, never rewrite" governs.

**A screenshot of the game may go on an issue.** `AGENTS.md` governs what is
**committed**; the tracker is not the repository. Link one and move on.

## Labels

Exactly one priority on every issue -- `Priority: High`, `Priority: Medium`,
`Priority: Low`. **Set it when you open the issue**, in the same
`gh issue create`; an issue filed without one falls off the list. Guess if you
have to and say in the body that you guessed. Then:

* **`bug`** -- a defect in *our* code, one a user can hit.
* **`enhancement`** -- build this. Plans are enhancements.
* **`question`** -- we do not know something. Nothing gets built when it is
  answered; we simply know. A defect in *the game* is research, not our bug,
  and is usually a `question` or an `enhancement`.
* **`blocked`** -- waiting on Donald specifically: a choice only he can make, a
  machine only he has, a save only he can play to. Work blocked on a
  measurement we could take ourselves is **not** blocked.

**Keeping a label right is part of doing the work.** An issue you have just
worked is an issue you know more about than whoever filed it, and a label that
no longer matches what is known is an error like any other -- an *invisible*
one, because it fails no test, turns no CI red, and produces no symptom except
work quietly going to the wrong place. Set it, change it, add `blocked` or take
it off, the way you would fix a wrong sentence in a doc.

**Two things must never happen, and they are the whole of the caution.**

**Do not reverse a change a person made.** An agent asked for `enhancement`,
Donald set `question`, and the agent set it back -- treating his decision as
the defect. If you think a label a person chose is wrong, say why in a comment
and leave it as they left it. He reads the comments. Donald, 2026-09-04: *"I
just don't want it resetting labels back to what they were for no reason at
all."* Undoing your *own* earlier change is not this, and neither is a label
the world has since made wrong; what is banned is correcting a person.

**Do not change a label without a comment saying what you changed and why**, in
the same breath. That comment is the entire safety mechanism -- it is what
makes the change visible, arguable and reversible -- and a change without one
leaves no record anybody can read.

**Everything else is ordinary work, and not doing it is its own failure.** All
of these are yours, each with its comment:

* **Add `blocked`** when the work is waiting on Donald specifically, and
  **remove it** when the blocker is gone. `blocked` is a claim about the world
  rather than a judgement about the work, so it can be checked and it can be
  wrong, and a label nobody corrects outlives the fact it recorded. Name the
  evidence: the disks are at this path, the question was answered on this
  issue, the choice is still his to make.
* **Correct a type label** to what the body describes. Ask of the label what
  you ask of the work -- what does the player see? -- and "nothing, we do not
  know yet" means `question`, whatever it says now.
* **Set a priority on an issue that has none**, saying in the comment that you
  guessed. An issue without one falls off the list.

**Write the reason as a fact rather than an opinion**, because a fact is
something Donald can check and contradict:

* *"The body says nothing is observed and nobody can name what a player sees,
  so it is a question rather than a bug"* -- checkable by reading the issue.
* *"This feels more important now"*, *"this looks doable"* -- an opinion, and
  it belongs in your reply rather than in a label.

**Priorities are the one place to hold back.** Donald re-curates `Priority:` by
hand and reads the backlog through it, so changing one moves what he sees next
without telling him. Recommend it in your reply, leave the label, and say which
you would have set.

## The three templates

`.github/ISSUE_TEMPLATE/bug.md`, `enhancement.md` and `question.md` are the
templates, so the forms appear when a human opens an issue. **An agent writing
one with `gh` reads the file and follows the same headings by hand.** They are
not copied here: a second copy drifts out of step with the first, which is the
defect half the audit checks hunt for.

* **Bug** -- a defect in our code. What breaks, root cause, what would fix it,
  testing.
* **Enhancement** -- build this. Why, what is known, what has to be found out
  first, order of work.
* **Question** -- we do not know something. Why it matters, what we know, what
  would settle it.

**"What would fix it", not "Fix".** An issue carrying a patch ages into a stale
patch that no longer applies; an issue carrying the *shape* of the fix stays
true. Every enhancement ends with a `Documentation:` line linking the doc it
rests on -- that link is what joins the work list to the knowledge base.

## Findings, and closing

**A bug you find and decide not to fix gets an issue, in the same session you
found it.** Out of scope is a fine reason not to fix something and not a reason
to leave it unrecorded; a defect that exists only in a subagent's report is a
defect nobody will ever act on. The bar is low on purpose: what you saw, what
you were doing, and why you did not chase it. "Not diagnosed" is a legitimate
Root cause section. This applies to a bug in **our** code -- a defect in the
game is research and goes in the documentation.

**Every finding goes in a comment on its issue, when it arrives.** Not at the
end of the work, not only in the reply, not only in `docs/` -- on the issue,
while the agent that found it is still the thing that knows it. A reply scrolls
away, and a doc records what is *known* rather than what was *learnt about this
ticket*.

**This includes the findings that are not the answer**: a refuted hypothesis, a
measurement that came out unremarkable, a claim you could not confirm, the
thing you could not reach and why. Those are the expensive ones to rediscover.

**And it includes findings that belong to a *different* issue.** File it or
comment on it, then say in your own issue that you did.

**Comment before you close.** An issue that closes with nothing but a commit
reference makes the next reader open the diff. Say what was actually done, what
it now does instead, and anything deliberately left undone.

**`closes #N` fires when the commit reaches `main`, and not before.** This
project routinely carries dozens of unpushed commits, so that gap is the normal
state. **When the finishing commit is not pushed, close the issue by hand** with
`gh issue close`, and say in the closing note that the keyword will be a no-op
by the time the commit lands. And **never report an issue as closed without
checking `gh issue view N --json state`.**

## Prioritising the work list

Donald asks for a recommended order regularly. **It is a recommendation.** He
recurates the `Priority:` labels by hand, so a list that disagrees with a label
says so and leaves the label alone.

**Lead with what you would do first and why, one line each.** Not an exhaustive
survey, not a table of everything open. Group by category when there are more
than a handful, because the categories are what make the shape visible.

What moves an issue up:

* **A defect a user can actually hit**, over anything that is only untidy. What
  does the player see? If the honest answer is "nothing", it is not urgent,
  however wrong it is.
* **A guarantee that is asserted and never verified** -- worse than a missing
  test, because a missing test is not believed.
* **Work that unblocks several other issues.** One issue that frees three beats
  three that free none.
* **The smallest thing that removes a blocker**, rather than the whole of what
  the blocker is in the way of.
* **A contradiction in the knowledge base.** Two documents disagreeing costs
  somebody a session, and the fix is usually an hour.

What moves it down:

* **`blocked` on Donald specifically** -- a choice only he can make, a machine
  only he has. Work blocked on a measurement we could take ourselves is not
  blocked and the label should come off.
* **Anything needing a design decision he has not made.** Do not schedule the
  building of something whose shape is still his to choose; schedule the
  question instead.
* **A `question` with no consequence attached.** If nothing changes when it is
  answered, it can wait for the session that stumbles over it.

**Say what each issue is waiting on, not just where it ranks.** "Blocked on one
DOS save made outdoors" is actionable; "medium priority" is not.

Why these rules exist, and the incidents behind them:
`docs/160-why-these-rules.md`, "Issues".
