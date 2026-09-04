# Feature flags

**A major new feature ships behind a flag until it is proven stable, and a
feature with open bugs is not stable.** The DOS import is the first: it works,
it is proven in the emulator, and it still drops the portrait and the clock --
so `File > Import` is not built unless the flag says to build it.

**The name is always `WISH_EXPERIMENTAL_<FEATURE>`.** The prefix separates a
flag that exists to be *deleted* from `WISH_DEBUG` and `WISH_NATIVE_LOG`, which
are diagnostic switches and are permanent. Somebody reading an environment
variable should be able to tell those apart without opening the file.

**Every flag names the condition that removes it, beside its definition.**
"Comes off when the two issues it is waiting on close", naming each by number
and title, is a condition; "when it is ready" is not. A flag with no stated way
out becomes a second code path maintained forever, and the second path is the
one nobody runs.

**Do not build the thing rather than disabling it.** A greyed-out menu item
invites the question of how to un-grey it, and the answer would be a sentence
in the interface -- which is the thing `.claude/rules/gui-text.md` spends its
length preventing. `wish/window.py` builds the Import submenu inside the `if`.

**An environment variable, not a preference.** A checkbox needs a label, and a
label saying "experimental" needs a sentence saying what that means for the
user's save disk. That is Donald's wording to write and it is not worth writing
for something due to be deleted.

**One truthiness rule, shared: `1`, `true`, `yes`, `on`.** Anything else --
including an empty string, `0` and `off` -- is off. `wish/debugmode.py` has it
first; copy that tuple rather than inventing another. A variable somebody
exported once and forgot must not put an unfinished feature in front of them.

**Test both directions, and prove each test fails without the gate.** One test
that the feature is absent by default, one that a forgotten `0` or `off` does
not turn it on, one that it appears when asked for. Force the flag on and watch
the first two fail; a gate that cannot fail is not a gate.

Why these rules exist, and the incidents behind them:
`docs/160-why-these-rules.md`, "Feature flags".
