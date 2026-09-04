# Working unattended, and ending a session

## A turn that ends with nothing running is the end of the night

This session works by being re-invoked: a subagent finishing, a background
command exiting, a scheduled wake-up. When a turn ends with **no agent working
and no background command pending**, nothing ever calls back, and the session
sits idle until a human types something.

**The discipline, and it is the whole rule:** before ending a turn, check that
at least one of these is true.

* a subagent is running;
* a background command is pending (`run_in_background`, or a `Monitor`);
* a wake-up is scheduled.

**"I will do X next" is not one of them.** An intention is not an event. If the
next thing is a suite run, *start* it before the turn ends rather than
promising it -- the promise is what breaks the chain.

**The mechanism for an overnight run is `/loop`.** Invoked with no interval it
self-paces, scheduling its own next wake-up, so the chain does not depend on an
agent happening to be in flight. Without it, an overnight session is only as
long as its longest-running subagent. Ask Donald to start the night that way.

**A killed background command is not a finished one.** A backgrounded `pytest`
has come back `killed` rather than with a result four times. A long run belongs
in the foreground with an explicit timeout -- the suite takes about six minutes
and the tool allows ten -- or it has to be checked for a real result rather
than assumed to have passed.

## Ending a session, and starting the next one

**The session is not the knowledge base and must never become it.** A fact that
exists only in a conversation is a fact somebody pays for twice, and
conversations end -- on a spend limit, on a `/clear`, on a context window.
Putting findings on their issues when they arrive is what makes a session
disposable, which is the point.

**Long sessions accumulate stale facts.** The assistant answers from something
that was true earlier and is not any more; a fresh session reading the issue
would have got it right. Length is not context; it is also drift.

**Before clearing, say what is not written down yet.** Go through what the
session established and check each fact has a home: a comment on its issue, a
line in `docs/`, a row in a README. Name anything that does not, and write it
down before the session ends. Calibrations are the ones that get lost -- "+6pt
here measures like Windows' base font" is worth more than the fix it enabled.

**A fresh session reads, in this order:** `CLAUDE.md`, `INDEX.md`, then
`gh issue list`. For any issue it is about to work,
`gh issue view N --comments` -- because the description is never rewritten
here, so every correction lives in the comments.

**The test of whether a session was recorded properly** is whether the next one
can answer "what should we work on" from the repository alone. If it cannot,
the gap is the thing to fix, and it is a documentation bug rather than a reason
to keep a session alive.

Why these rules exist, and the incidents behind them:
`docs/160-why-these-rules.md`, "Sessions".
