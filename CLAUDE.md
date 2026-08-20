# Working notes for Claude

## Conciseness

Say the thing once, in as few words as carry it. Length is not thoroughness.

Cut: preamble, restating the request, summarising what you just did in the same
breath as doing it, hedging, and "as you can see". Keep: offsets, byte values,
exact error strings, the reason a choice was made.

If a sentence would survive deletion without the reader losing anything, delete
it.

## Commits

**No essays.** Reasoning belongs in `docs/50-experiments.md`, which exists for
exactly that; the commit points at it.

* Subject: imperative, sentence case, no type prefix, ≤ 65 characters, no
  trailing period. Match the existing history's voice — "Find the size flag, and
  settle the party limit".
* Body: **usually none.** Add one only for a non-obvious *why*, a breaking
  change, or a correction of an earlier commit. Cap it at five lines, wrapped
  at 72.
* Never: "This commit does X", AI attribution, emoji, restating the diff.

One commit per finding. Three findings in one commit is worse for future
archaeology than three commits, even when the files overlap.

```
Find the staging page at $5500

It holds one record — the last one the game loaded there. Written up as
"the orc left behind at $5500".
```

## Documentation

`docs/50-experiments.md` is the only place that gets length, because the whole
project is the reasoning. Everything else is a lookup table: state the finding,
give the evidence in one clause, link the experiment by name.

Prune when a claim changes. A doc that accretes corrections without deleting the
superseded text is how the contradictions got in.

## Code comments

Comment the *why*, and only when it is not obvious. A field note that carries
evidence — "10 for every player character; monsters carry their real AC here" —
earns its lines. Restating the code does not.

`por/layout.py` is the exception: its notes are the field documentation and are
generated into `docs/20-character-record.md`. They can be long. Run
`python3 tools/gendocs.py` after touching them.

## Replies

Lead with the answer. Findings before method. Tables over prose for anything
with more than three data points. No closing summary of a reply the user just
read.

Report failures with the shortest decisive line of output, not the whole log.
