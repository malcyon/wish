---
paths:
  - "goldbox/**"
---

# Testing a conversion

**The standard is a perfect conversion.** Reporting a dropped field is the
minimum; it is not permission to drop it.

**And a drop is a bug.** Donald, 2026-09-04: *"We should not be dropping
anything when converting a save. Anything less is a bug, and the feature flag
cannot be lifted until that is true."* So the three reasons below explain why a
field is not carried **yet** -- they are not a licence, and a drop list is not
a state a conversion is allowed to rest in. **Every entry on every drop list
has an issue**, and `WISH_EXPERIMENTAL_DOS_IMPORT` does not come off while any
of them is open.

**Every field is carried, or it is on a short list with a tested reason.**
**And "the destination has no such field" is not an ending.** Donald,
2026-09-04, told the ring's effect could not reach the C64 and that the drop
was therefore legitimate: *"everything must work."* A converted character
wearing a Ring of Fire Resistance has to resist fire on the other side. So the
three reasons below say why a field is not converted **yet**, and the first of
them is a description of the destination as we currently understand it rather
than permission to stop -- if the destination has no home for something a
player would notice, finding it one is the work.

**Say "converted", not "carried".** Donald, 2026-09-04: *"When you say
'carried', you must mean 'converted'. I don't think carried means what you
think."* The word is in this file, in `field_disposition` prose and in drop
lines a player reads.

Three reasons are legitimate:

* the destination format **has no such field** -- and that has been established
  by reading its layout, not assumed;
* the destination **derives it** on load, so writing it is pointless -- and that
  has been *demonstrated in the running game*, not argued from plausibility;
* we **do not understand the bytes well enough to write them**, in which case
  the entry is a defect with a settling experiment, not a permanent exemption.

The third kind is a bug that has not been filed yet. Treat it that way.

**A template is not one of the three reasons, and "the template supplies it" is
not an answer.** Building a converted save on top of a save the engine wrote
means every byte nobody has decoded silently keeps a value belonging to a
different party in a different place -- wrong data that looks right, and
invisible because the file loads. Donald, 2026-08-26: *"We should not be using
a template at all. We should block on not understanding everything and go back
and understand what we need to. No more plugging in fake data to make it
work."*

So **an undecoded field is a blocker, not a gap the template fills.** When the
conversion needs a byte nobody has attributed, the work is to go and measure
it, and the ticket says so.

**Zero written because the engine rebuilds the field is not plugged-in data.**
Most of `WRITE_UNSOURCED` is live heap pointers and combat state where the
engine itself writes zero, measured both with items and without. The
distinction that matters is **measured versus inherited**: a value we
established is fine at any number, and a value we inherited from somebody
else's save is not.

**"Reported as dropped" is not a resting state.** Every entry in a drop list
carries the experiment that would remove it, and a drop list that has not
shrunk in months is a list of unfiled bugs.

**Test the empty and the extreme case, not only the typical one.** A drop list
measured survivable for a character carrying items said nothing about a
character carrying none, which is where
`#62 (A converted character who owns nothing gets a corrupt sheet, and DOS then
invents a garbage item)` was found -- after the conversion had been declared
proven.

**Round-trip byte for byte, and mask by the declared list rather than by the
diff.** Masking by whatever happened to differ makes the test agree with the
code by construction. `tests/test_doswriter.py` masks by `WRITE_UNSOURCED` and
`WRITE_DEFAULTS`, which are the lists the writer declares, so a new difference
fails.

**A conversion is not proven until it runs.** Bytes matching is necessary and
not sufficient: load it in the game, walk the party, and look at the sheet.
Three faults this project shipped -- an AC of 9 displayed as 51, a dropped
combat tail, and a garbage weapon line -- passed every byte-level check that
existed.

Why these rules exist, and the incidents behind them:
`docs/160-why-these-rules.md`, "Testing a conversion".
