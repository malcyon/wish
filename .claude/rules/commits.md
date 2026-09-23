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

## The workflow

Work goes out in reviewed, coherent batches, and CI is the full-suite gate:

1. **Focused local tests** for the behaviour the change affects: the test
   files it touched, the tests of what it changed, and the relevant tests that
   read private game data, which CI cannot run because it has no specimens.
2. **`.venv/bin/ruff check .`** and
   **`.venv/bin/python3 tools/generate/genui.py --check`**.
3. **Commit locally**, then run the required code review
   (`.claude/rules/delegating.md`). Fix findings in a follow-up commit or
   reject them with a reason.
4. **Push** the reviewed batch.
5. **Check CI for the exact pushed SHA** before taking more tickets, and fix
   what actually failed.

**Nobody runs the whole suite locally in order to push.** CI runs it on every
pushed commit. A concrete CI failure is fixed with focused tests and a
corrected push, not with repeated local full-suite runs.

## Before every commit

1. `pytest` on the affected tests, including any that read game data (all
   selected tests pass)
2. `.venv/bin/ruff check .` (no unused imports or linting errors)
3. `.venv/bin/python3 tools/generate/genui.py --check` (every `.ui` compiled and current)

**Focused means chosen for the change, not only the files touched.** A change
to a shared helper runs the tests of what calls it. A change that touches no
code -- prose in `docs/`, a rule file, `AGENTS.md`, a README row -- runs
`tests/suite/test_repository_contents.py`, which is the only test that reads
those, and `ruff`. **"Touches no code" means no `.py`, no `.ui`, and no file a
test reads as data**; a docstring is code for this purpose.

**The tests that read game data are the ones CI cannot run.** `gamedisks.yaml`
is gitignored and CI has no registry, so every specimen- or disk-backed test
skips there. When a change touches code those tests cover, run them locally
as part of the focused check; they are a focused check, not a second full-suite
run.

**Use normal test parallelism.** `-n auto --dist loadgroup` lives in
`pyproject.toml`'s `addopts`. Keep `--dist loadgroup`: it keeps
`tests/registry/test_instance.py`, `tests/dos/test_dosbox.py`,
`tests/dos/test_dosboxx.py` and `tests/c64/test_walkrun.py` -- which claim a
synthetic emulator-pool slot by a fixed, shared display number -- in one
worker together, because two workers racing each other for the same number is
exactly the failure the pool itself exists to prevent between real agents.
`pytest -q -n0` drops back to one process, for a single flaky-looking failure
that needs to be seen in isolation.

**A subagent runs only the tests its change affects.** Several agents each
running the whole suite is several copies of Qt on one machine, and under that
load a run stalls and produces nothing. A `test-runner` can take a focused run
off the main window; `.claude/agents/test-runner.md` is the definition.

**`tools/suite/suiterun.py` is a diagnostic, run only when somebody asks for a
whole-suite run on this machine.** It is not a step before a push, and the
record it writes is not required by anything.

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
is the one case where a green local run says nothing about the checks that
govern it.

And when a new file needs a path to the player's disks, use what the other
tools use -- `$POR_DISKS`, then `automap.paths.find_disks()` -- rather than a
fourth way. `tools/areas/geomap.py` is the one-liner.

## Pushing

**Push once the locally committed batch is reviewed and its focused checks
pass.** A subagent reports, the root commits locally, the `code-reviewer`
reviews that commit, and the findings are fixed or explicitly rejected with a
reason before push. Donald has standing approval for the push; he does not
have to be asked each time.

A documentation-only or `CLAUDE.md`-only commit needs no code review and follows
the prose-only checks above.

**A batch is coherent**: work that is reviewed and ready goes out together, and
unfinished or unrelated work waits for the next one rather than holding a
ready batch back.

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

**Do not take the next ticket until that CI result is in.** If it failed,
`gh run view <id> --log-failed` says why, and **the fix goes to a subagent**:
the failure is usually platform-specific, the diagnosis is reading, and
neither belongs in the main window. The fix is checked with focused tests,
pushed, and its own SHA's CI checked in turn.

**Wind-down means finishing, not abandoning.** Stop taking new work; finish
focused validation, commit locally, review, push, and
check CI for the pushed SHA; then stop cleanly. Uncommitted or unpushed work is
left behind only when Donald explicitly asks to stop immediately and leave it,
and then the handoff names it, with any pending CI by SHA and run ID.

**Two failures happen here and neither reproduces on Linux**, so expect them:
something Windows cannot do (`chmod` does not make a directory unwritable
there, `fcntl` does not exist, paths are not split on `/`), and something that
is not byte-identical on another machine (a rendered image, anything with a
font or a timestamp in it).

Why these rules exist, and the incidents behind them:
`docs/160-why-these-rules.md`, "Commits and CI".
