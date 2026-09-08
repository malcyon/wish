# Scratch files, and what counts as a tool

## `work/` is a run's output, and it is not storage

`work/` holds what a run produced -- logs, dumps, screenshots, disk images --
and is gitignored, because most of it derives from the game's bytes and
`AGENTS.md` bans committing those.

It is snapshotted hourly to OneDrive from this machine, and **that is not a
reason to leave anything valuable there**. It has been lost twice. A snapshot
is a copy of whatever was there an hour ago, which is not the same as a place
a finding lives.

**So nothing important stops at `work/`.** A measurement goes in a comment on
its issue, a fact goes in `docs/`, a script goes in `tools/`. What stays
behind in `work/` should be only the bytes those three point at: the screenshot
a comment links, the dump a document cites.

Name a run's directory after the issue it belongs to -- `work/issue316/`,
`work/issue128/run3/` -- so a file found later can be traced to the work that
made it.

## A tool goes in `tools/`, committed, with a row in `tools/README.md`

**Every script is a tool**: a runner, a probe, a sweep, a one-off that answered
a question, the thing you wrote to check one number. However throwaway it felt
while you were writing it.

**The test is whether somebody would otherwise write it again.** They almost
always would. `ecl6.py` decoded all thirty ECL scripts, lived in a scratch
directory, and was lost; the next agent to want those scripts wrote it a second
time.

A tool that is committed is a tool the next session can find, run, and correct.
One that is not is a tool the next session rewrites from the same description,
usually slightly differently, and then the two disagree.

### The README row is part of the tool

`tools/README.md` is how anybody finds a tool without grepping. A tool without
a row is only reachable by whoever remembers it.

**Several agents edit `tools/README.md` at once**, and this is the file where
they collide. Do not rewrite it while somebody else is editing it. Either:

* write your rows to `work/reports/<issue>-rows.md` and say so in your report,
  and the main window lands them; or
* build the version you mean to commit in the scratchpad, `git hash-object -w`
  it and `git update-index --cacheinfo` it into the index, which lands your
  rows without touching the file somebody else is still editing.

`.claude/rules/commits.md` has the second one in full.

### A new tool needs a path to the player's disks

Use what the other tools use -- `$POR_DISKS`, then `automap.paths.find_disks()`
-- rather than inventing a fourth way. `tools/geomap.py` is the one-liner.

And `git add` a new file **before** the last local test run.
`tests/test_repository_contents.py` walks the files git knows about, so an
untracked tool is in none of its lists and every check on it passes by not
looking.

## Putting a file back, and the bytecode cache

To test whether a change matters, copy the file aside and copy it back, `diff`
to confirm, **and then delete `__pycache__`** -- a file put back at the same
size in the same second does not look changed to CPython's bytecode cache, so
the next run imports the version you thought you had removed.

**Take that copy immediately before the change you are testing, never at the
run's start.** A copy taken earlier restores whatever else happened in between,
and in a shared tree that is somebody else's work.

This is the only sanctioned way to revert anything here. `git checkout`,
`git restore`, `git reset`, `git stash` and `git clean` are banned outright --
`AGENTS.md`, "Git in a shared tree" -- because they discard what other agents
have uncommitted, silently.

## The scratchpad is not `work/`

A session's scratchpad directory is for intermediate junk that belongs to
neither: a throwaway script that composed a picture, a diff you took to compare
two files. Nothing there survives the session, and nothing there should need
to. If it turns out something does, it was a tool -- move it to `tools/`.

Why these rules exist, and the incidents behind them:
`docs/160-why-these-rules.md`, "Temp files, tools and backups".
