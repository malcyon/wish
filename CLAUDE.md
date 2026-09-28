# Working notes for Claude

@AGENTS.md

## What is different for Claude Code

The rules are in `AGENTS.md`, imported above, because Google's tools read that
name and not this one. Everything there binds here. This file holds only what is
true of Claude Code and of nothing else, so `AGENTS.md` stays honest for both.

**Seven of the fourteen rule files load at launch and seven load when you read
a file they cover**, so the routing table in `AGENTS.md` is mostly a formality
here. It is not one for a reader that has no such mechanism.

**A subagent inherits this file, `AGENTS.md`, and the same seven unscoped rule
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

## Banned words

`.claude/rules/words.md` has the table and states which words are banned in
prose, and why.
