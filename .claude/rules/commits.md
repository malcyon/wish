# Commits

**Keep a commit message to one sentence.** Reasoning belongs in
`docs/50-experiments.md`, which exists for exactly that.

One commit per finding, where that is practical. Three findings in one commit
is worse for later archaeology than three commits, even when the files overlap
-- but do not spend longer splitting a commit than the split is worth.

**The issue number goes at the end of that same line, in parentheses**, never
on a line of its own. A commit message is the one place the number goes bare
rather than with its title: a title there would break the sentence, and GitHub
hotlinks the number anyway. Use `closes #N` on the commit that actually
finishes the work -- that closes the issue when it reaches `main` -- and a bare
`#N` for a commit that only moves it along.

```
Land in the largest open part of the map (closes #14)
Read the trainer out of GEN (#10)
```

**The sentence still has to stand on its own.** It is read in `git blame`, in
`git log` and in a terminal, where the number is opaque -- and that is where
this project's archaeology actually happens. A message that needs GitHub to be
understood is worse than one that does not.

## Before every commit

Run all three locally, or CI will find what you did not:

1. `pytest` (all tests pass)
2. `.venv/bin/ruff check .` (no unused imports or linting errors)
3. `.venv/bin/python3 tools/genui.py --check` (every `.ui` compiled and current)

**Run the whole suite, not the files you touched.** A scoped run is for
working; it is not the check. `pytest tests/test_combatdrive.py` was green and
`main` went red on all four jobs eight minutes later.

**The exception is a change that touches no code.** Prose in `docs/`, a rule
file, `AGENTS.md`, a README row: the only test that reads any of those is
`tests/test_repository_contents.py`, which takes a second and a half. Run that
and `ruff`, and push. Donald, 2026-09-03: *"Waiting on a full test suite when
you've only changed a markdown file is a real bummer."* Six and a half minutes
of suite to prove a sentence did not break a parser is not diligence, it is a
habit that costs a person their evening.

**"Touches no code" means no `.py`, no `.ui`, and no file a test reads as
data.** A docstring is code for this purpose -- it ships in the module, and a
comment change is the one that gets waved through and turns out to have been
inside a string literal. If the diff has a `.py` in it at all, run everything.

**And in a shared tree, run it somewhere the other agents are not.** With two
subagents mid-edit -- the normal state on a busy night -- a run in place tests
*their* half-finished code and says nothing about the commits you are about to
push. A detached worktree at `HEAD` tests exactly what will land:

```sh
git worktree add -q --detach "$WT" HEAD
ln -sfn "$PWD/work" "$WT/work"          # gitignored, so a fresh checkout has none
(cd "$WT" && /path/to/.venv/bin/python -m pytest -q)
git worktree remove "$WT" --force
```

**The symlink is the part that is easy to miss, and without it the run lies by
omission.** `work/` is gitignored, so a bare worktree skips every test that
reads a specimen out of it -- the ones with real game data behind them. CI has
no `work/` either, so the bare run is the closest thing to what CI will do and
the in-tree run is what covers the specimen-backed tests. Neither is the whole
check on its own.

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
`tests/test_repository_contents.py` walks the files **git knows about** -- the
allowlist for `tests/fixtures/`, the ban on committed disk images and
executables, and `test_no_hardcoded_user_paths`. An untracked file is in none
of those lists, so every one of those checks passes by not looking. A new file
is the one case where a green local suite says nothing about the checks that
govern it.

And when a new file needs a path to the player's disks, use what the other
tools use -- `$POR_DISKS`, then `automap.paths.find_disks()` -- rather than a
fourth way. `tools/geomap.py` is the one-liner.

## Pushing

**Push once the code has been reviewed and the findings dealt with.** The
sequence is: a subagent reports, the `code-reviewer` runs on what it wrote, the
findings are fixed or explicitly rejected with a reason, and *then* it goes to
the remote. Donald has standing approval on that; he does not have to be asked
each time.

A documentation-only or `CLAUDE.md`-only commit needs no code review and can go
straight out.

**Do not sit on commits.** Unpushed work is work no CI has seen, and a local
`closes #N` leaves its issue open while everything looks finished. Push in the
batches the reviews land in.

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
-- the suite takes about 90 seconds on each of four jobs.

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
