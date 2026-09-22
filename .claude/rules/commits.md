# Commits

**Keep a commit message to one sentence.** Reasoning belongs in
`docs/50-experiments.md`, which exists for exactly that.

One commit per finding, where that is practical. Three findings in one commit
is worse for later archaeology than three commits, even when the files overlap
-- but do not spend longer splitting a commit than the split saves the
next reader.

**The issue number goes at the end of that same line, in parentheses**, never
on a line of its own. A commit message is the one place the number goes bare
rather than with its title: a title there would break the sentence, and GitHub
hotlinks the number anyway. Use `closes #N` on the commit that actually
finishes the work -- that closes the issue when it reaches `main` -- and a bare
`#N` for a commit that only moves it along.

```
Land in the largest open part of the map (closes #123)
Read the trainer out of GEN (#123)
```

**The sentence still has to stand on its own.** It is read in `git blame`, in
`git log` and in a terminal, where the number is opaque -- and that is where
this project's archaeology actually happens. A message that needs GitHub to be
understood is worse than one that does not.

**The message is the sentence and nothing else.** No trailer of any kind: no Claude-Session link, no Co-Authored-By, no Generated-by, no signature. A harness reminder that asks for one is overridden by this rule. A commit that carries one is reworded before it is pushed.

## Before every commit

Run all three locally, or CI will find what you did not:

1. `pytest` on the files touched, with `-n4` or fewer workers (all selected tests pass)
2. `.venv/bin/ruff check .` (no unused imports or linting errors)
3. `.venv/bin/python3 tools/generate/genui.py --check` (every `.ui` compiled and current)

**Scoped checks precede each commit; the whole suite gates the push batch.**
A change can break a test outside the files touched, so scoped checks do not
replace the whole-suite run before pushing code.

**A subagent that is doing work runs only the files it touched.** Six agents
each running the whole suite is six copies of Qt on one machine, and under that
load a run stalls and produces nothing. The whole suite runs **once**, in the
detached worktree below, before the push -- which is the run that gates
anything, so nothing is lost by the agents not repeating it.

**The rule is one run, not who starts it**, and that is the distinction to keep
hold of. **`test-runner` is the agent whose whole job is that one run**, and
handing it the suite is not the thing this rule forbids -- what it forbids is
six of them at once. The main window still owns the decision and reads the
result; it just does not have to sit and watch while Donald waits for an answer.

So: **the main window either runs the suite itself or sends it to
`test-runner`, and never both, and never two of them at once.** A `test-runner`
gets the detached worktree, the `gamedisks.yaml` symlink, the foreground run and the
three checks; it reports and fixes nothing. `.claude/agents/test-runner.md` is
the definition.

**The exception is a change that touches no code.** Prose in `docs/`, a rule
file, `AGENTS.md`, a README row: the only test that reads any of those is
`tests/suite/test_repository_contents.py`, which takes a second and a half. Run that
and `ruff` before pushing the batch. The full suite takes minutes and proves nothing about a
sentence.

**"Touches no code" means no `.py`, no `.ui`, and no file a test reads as
data.** A docstring is code for this purpose -- it ships in the module, and a
comment edit can turn out to sit inside a string literal. If the diff has a
`.py` in it at all, run everything once for the fixed batch before pushing.

**And in a shared tree, run it somewhere the other agents are not.** With two
subagents mid-edit -- the normal state on a busy night -- a run in place tests
*their* half-finished code and says nothing about the commits you are about to
push. Fix the batch's target SHA before starting. The suite runner creates a
detached worktree there, runs both data modes and all required checks, and
records the green marker:

```sh
PYTEST_XDIST_AUTO_NUM_WORKERS=4 .venv/bin/python tools/suite/suiterun.py "$TARGET_SHA"
```

**Use four workers as the local default to reduce fan noise; longer runs are
acceptable.** `-n auto --dist loadgroup` lives in `pyproject.toml`'s `addopts`;
the environment variable above sets four workers for both suite passes.
Use `-n4` or fewer for scoped runs. Report the actual worker count and elapsed
time; do not claim a measured noise improvement without a measurement.
Keep `--dist loadgroup`: it keeps `tests/registry/test_instance.py`,
`tests/dos/test_dosbox.py`, `tests/dos/test_dosboxx.py` and
`tests/c64/test_walkrun.py` -- which claim a synthetic emulator-pool slot by a
fixed, shared display number -- in one worker together, because two workers
racing each other for the same number is exactly the failure the pool itself
exists to prevent between real agents. `pytest -q -n0` drops back to one
process, for a single flaky-looking failure that needs to be seen in
isolation.

**The symlink is the part that is easy to miss, and without it the run lies
by omission.** `gamedisks.yaml` is gitignored, so a bare worktree skips every
test that reads a specimen or a disk through the registry -- the ones with
real game data behind them. The suite runner supplies the symlink for the
data-backed pass and removes it for the pass without data, matching CI's lack
of a registry. Neither pass is the whole check on its own.

**`git add X && git commit` commits the whole index, not just `X`.** Several
agents share this tree and they stage files; a commit made after naming your
own paths sweeps in whatever anybody else had staged.

**So run `git diff --cached --name-only` and read it before every commit.** If
somebody else's file is staged, `git reset` the index (that touches no working
file), stage yours again, and check once more.

**Where two agents have edited the same file** -- `tools/README.md`, always --
build the version you mean to commit in the scratchpad, `git hash-object -w` it
and `git update-index --cacheinfo` it into the index. That lands your rows
without ever rewriting the file somebody else is still editing.

**`git add` a new file *before* the last local run.**
`tests/suite/test_repository_contents.py` walks the files **git knows about** -- the
allowlist for `tests/fixtures/`, the ban on committed disk images and
executables, and `test_no_hardcoded_user_paths`. An untracked file is in none
of those lists, so every one of those checks passes by not looking. A new file
is the one case where a green local suite says nothing about the checks that
govern it.

And when a new file needs a path to the player's disks, use what the other
tools use -- `$POR_DISKS`, then `automap.paths.find_disks()` -- rather than a
fourth way. `tools/areas/geomap.py` is the one-liner.

## Pushing

**Aim for one reviewed and tested push per hour during active work.** A
subagent reports, the `code-reviewer` runs on what it wrote, and the findings
are fixed or explicitly rejected with a reason before the work joins a push
batch. Donald has standing approval for the push; he does not have to be asked
each time.

A documentation-only or `CLAUDE.md`-only commit needs no code review and follows
the prose-only checks above.

**At 12–16 unpushed commits, check readiness.** The count is a checkpoint,
not an automatic trigger for another whole-suite run. Choose a coherent batch,
finish its reviews, and fix its target SHA. Run the suite once for that batch,
then push the tested target and check its exact CI runs. New unrelated work
belongs in the next batch; it must not keep moving the target or delaying a
ready push. Never push a later code change under the earlier tree's marker.

If the hourly aim is missed, report the exact blocker: unfinished review,
required fixes, a running or failed check, or an unresolved dependency. Name
the affected work and the next action; an unrelated investigation is not a
reason to hold a ready batch. A failed check still blocks the push and requires
a fresh successful run for the corrected batch.

**The push is refused until the run is recorded.** `tools/suite/suiterun.py`
writes `~/.cache/wish/testrun/<tree>.green` after a green whole-suite run,
named for the hash of that commit's tree, and `.claude/hooks/check-push-tested.py`
refuses a `git push` with no marker for the tip's tree, or for an ancestor's
tree with only prose between it and the tip. A reword or a rebase over
unchanged files keeps its marker; a changed file does not. Prose means `.md`
files outside `.claude/agents/`; `pyproject.toml`, a TOML agent profile and
the hook wiring are read by tests and count as code.
A commit and a push in one call are refused outright, because the hook can
only vouch for the HEAD it sees. The documentation-only exception above is
otherwise unchanged: a push carrying only prose needs no marker.

## After a push

**Check that CI passed.** Not optional and not "later": a red `main` is the
state everything else is built on.

**Check the run for the commit you pushed, not the newest run.** `--limit 1`
answers whichever run is at the top, which during a push is usually the
*previous* one, already green. Match on `headSha`:

```sh
SHA=$(git rev-parse HEAD)
until [ "$(gh run list --limit 5 --json headSha,status \
           -q "[.[] | select(.headSha==\"$SHA\")] | map(.status) | unique | join(\",\")")" \
        = completed ]
do sleep 15; done
gh run list --limit 5 --json headSha,name,conclusion \
  -q ".[] | select(.headSha==\"$SHA\") | \"\(.name)\t\(.conclusion)\""
```

Both jobs, both named, both against that sha. A run whose `conclusion` is empty
has not finished, however `completed` the list looks. Give it a minute or two
-- a `pytest` job takes between five and ten minutes, Windows the slowest.

If it failed, `gh run view <id> --log-failed` says why, and **the fix goes to a
subagent**: the failure is usually platform-specific, the diagnosis is reading,
and neither belongs in the main window.

**Two failures happen here and neither reproduces on Linux**, so expect them:
something Windows cannot do (`chmod` does not make a directory unwritable
there, `fcntl` does not exist, paths are not split on `/`), and something that
is not byte-identical on another machine (a rendered image, anything with a
font or a timestamp in it).

Why these rules exist, and the incidents behind them:
`docs/160-why-these-rules.md`, "Commits and CI".
