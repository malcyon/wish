# Working notes for Claude

@AGENTS.md

## What is different for Claude Code

The rules are in `AGENTS.md`, imported above, because Google's tools read that
name and not this one. Everything there binds here. This file holds only what is
true of Claude Code and of nothing else, so `AGENTS.md` stays honest for both.

**Five of the twelve rule files load at launch and seven load when you read a
file they cover**, so the routing table in `AGENTS.md` is mostly a formality
here. It is not one for a reader that has no such mechanism.

**A subagent inherits this file and `AGENTS.md`, and does *not* inherit
`.claude/rules/`.** So a brief has to name the rule files its agent needs, and
an agent should read the ones its brief names rather than assuming they arrived.
