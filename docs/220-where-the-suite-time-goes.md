# Where the suite's time goes

Half of the test suite's run time is one line in `tests/conftest.py`, and
almost none of it is the game data, the emulator-pool tests or worker
imbalance that `#579 (The test suite takes four minutes locally and ten
before a push, and nobody has measured where the time goes)` proposed as
candidates. This page has the measurement, then the order of work it argues
for.

## How it was measured, and how much to trust it

Two whole-suite runs on this machine, each in its own detached worktree,
twelve `-n auto` workers with `--dist loadgroup`, `pytest -q --durations=0`
with a JUnit XML alongside: one with `gamedisks.yaml` symlinked in, one with
it removed and every variable `gamedisks.yaml.example` names pointing at a
path that does not exist, which is what `tools/suite/suiterun.py` does and
what CI meets.

Two other agents were running small `pytest` jobs throughout. The one-minute
load average on this twelve-core machine went from 0.43 at the start of the
first run to 7.13 at the end of the second, so **every wall-clock figure
here is an upper bound, good to about ±20%.** The no-data run went second
and so ran under the heavier load; the 44.3 s by which it beat the with-data
run is therefore a *lower* bound on what hiding the data saves.

The proportions are much steadier than the wall figures, because contention
inflates the whole run together. The central one — mean teardown per test —
was re-measured separately, in a single process, on a differently loaded
machine, and came out higher rather than lower.

## The two passes

| pass | collected | skipped | wall | worker-seconds | effective workers |
|---|---|---|---|---|---|
| game data present | 8,234 | 0 | 262.0 s | 2,760.1 | 10.53 of 12 |
| no game data | 8,301 | 1,783 | 217.7 s | 2,208.1 | 10.14 of 12 |

"Worker-seconds" is the sum of every test's setup, call and teardown from
the JUnit XML. Perfectly balanced across twelve workers the first pass would
have taken 230.0 s against the 262.0 s it did take, and a worker's own
collection accounts for much of that difference: collecting all 8,301 tests
takes 3.39 s in one warm process, and each of the twelve does it.

Hiding the game data removes 1,783 tests and 552.0 worker-seconds — 20% of
the run for 22% of the tests. **Reading disks is not what the suite spends
its time on.**

## Half the run is the garbage collector

Splitting the first pass by phase, over the 10,136 durations of 0.05 s or
more that `--durations=0` prints (the phases below that add the remaining
134.7 worker-seconds):

| phase | worker-seconds | share of the run |
|---|---|---|
| teardown | 1,379.4 | 50.0% |
| call | 1,119.0 | 40.5% |
| setup | 126.9 | 4.6% |

The teardown total is spread almost perfectly evenly: 7,928 teardowns at a
mean of 0.174 s, and **the largest single teardown in the whole run is
0.68 s.** Nothing in the suite has an expensive fixture teardown. What it
has is a per-test cost paid 8,234 times, and `tests/conftest.py` has exactly
one candidate — the autouse `_collect_between_tests`, whose body after the
`yield` is `gc.collect()`.

Three probes settle it. Each runs one file's tests with the whole of
`tests/` collected first, so the interpreter holds the object graph a real
worker holds:

| probe, 168 tests of `tests/test_conditionbadges.py` | wall |
|---|---|
| as it stands | 32.82 s |
| `gc.collect` stubbed to a no-op | 9.45 s |
| `gc.freeze()` called once when collection finishes | 9.48 s |

That is 0.139 s a test, and freezing costs the same as removing the call
outright. The same file run with only its own
module collected goes 7.32 s to 1.83 s, and `tests/test_toolhelp.py` goes
16.07 s to 6.62 s — smaller savings from the same change, because the cost
is proportional to how much has been imported. A worker that has collected
the whole suite is the expensive case, and that is the only case that
happens in a real run.

**What to do about it is `gc.freeze()`, not deletion.** `gc.freeze()` moves
everything currently tracked into a permanent generation that later
collections never walk. After collection finishes, that is the imported
modules, their classes and their constants — objects which never become
garbage anyway. Every widget a test builds is created afterwards and is
still collected at the `yield`, so the deterministic collection point
`docs/112-test-harness.md` describes keeps doing its job at a fraction of
the price. A Qt-heavy file confirms it: 87 tests of
`tests/test_preferences.py` go 57.15 s to 49.97 s, all passing.

`_collect_between_tests`' own docstring says the collection point "costs
nothing measurable". It costs about half the suite, and the reason the claim
looked true is that it was checked on a single file rather than on a worker
carrying the whole tree.

## What the rest of the time is

Top files by worker-seconds with the per-test teardown subtracted, so the
column is what stays after the freeze:

| file | tests | total | teardown | setup | remainder |
|---|---|---|---|---|---|
| `tests/test_toolshadowing.py` | 711 | 331.4 | 138.2 | 0.0 | 193.2 |
| `tests/test_staging_sweep.py` | 25 | 88.8 | 3.3 | 0.0 | 85.5 |
| `tests/test_combatdrive.py` | 81 | 78.3 | 6.1 | 0.0 | 72.1 |
| `tests/test_iconproposal.py` | 67 | 70.6 | 8.0 | 0.0 | 62.6 |
| `tests/test_editor.py` | 182 | 80.3 | 25.2 | 10.6 | 55.1 |
| `tests/test_iconparts.py` | 39 | 57.5 | 5.0 | 46.4 | 52.5 |
| `tests/test_amiga.py` | 173 | 75.4 | 32.8 | 0.0 | 42.5 |
| `tests/test_mapscale.py` | 25 | 45.4 | 4.3 | 0.0 | 41.2 |
| `tests/test_preferences.py` | 83 | 49.7 | 11.9 | 0.0 | 37.7 |
| `tests/test_amigalaterwrite.py` | 17 | 39.2 | 2.3 | 0.0 | 36.9 |

`tests/test_toolshadowing.py` is the one item large enough to be attacked on
its own. Its 711 tests are two parametrised sweeps over every script in
`tools/` plus a handful of one-offs, and **each test spawns a fresh
interpreter** — 190.6 s of call time for 711 subprocesses, about 0.27 s
each, which is what starting CPython costs. The two sweeps import the same
module in two separate processes to assert two properties of that one
import: that `wish` is still the package, and that `tools/` is not left on
`sys.path`.

## Fixtures

The suite has **one** session-scoped fixture — `_one_qapplication` in
`tests/conftest.py` — and 59 module-scoped ones across 32 files. Setup is
4.6% of the run, so fixtures are not where the time is, with one exception.

`IconParts.legal_screen_codes()` takes about 14 s, and two files ask for it
from a module-scoped fixture of their own: `tests/test_iconparts.py` and
`tests/test_dosicon.py`. Under `--dist loadgroup` a file's tests scatter
across workers like any others, so a module fixture is built once *per
worker that gets any of that file's tests*. The durations show it: five
setups of 13.29 s to 15.55 s, three in one file and two in the other, for
what is one computation. That is 73.8 of the 126.9 setup seconds.

Session scope alone does not fix this, because an xdist "session" is one
worker. The two files' tests have to land on the same worker as well, which
is what an `xdist_group` does.

## The tests that name an emulator

None of them starts one.

| file | tests | seconds | what it actually runs |
|---|---|---|---|
| `tests/test_instance.py` | 72 | 16.7 | the pool, with `python -c "import time; time.sleep(120)"` standing in for a VICE run |
| `tests/test_dosbox.py` | 56 | 10.6 | a blank-window stub and captured output |
| `tests/test_dosboxx.py` | 35 | 5.3 | a fake debugger that wraps as the real one does |
| `tests/test_walkrun.py` | 9 | 1.5 | a `Session` replaced by a fake that never connects |
| `tests/test_combatdrive.py` | 81 | 78.3 | captured screens; its own docstring says it needs no emulator |
| `tests/test_fleedrive.py` | 11 | 32.3 | the same, over three fight outcomes |

The first four carry `xdist_group(name="emulator-pool")` and so share one
worker: **172 tests and 34.0 worker-seconds, 1.2% of the run.** The group
cannot be a tail. `livetests/`, which does drive real emulators, is in
`norecursedirs` and is never collected.

## Readings this data does not support

Three claims that look right and are not, each cheap to repeat:

* **A large per-file teardown total is not an expensive fixture.** It is the
  file's test count times 0.174 s. `tests/test_toolshadowing.py`'s 138.2 s
  is 711 tests, and `tests/test_toolhelp.py`'s 57.5 s is 345 tests whose
  calls together come to 0.1 s.
* **`--durations` attributes per test, not per fixture.** Summing a file's
  teardowns and calling the total one fixture's cost inverts what the
  numbers say.
* **Tightening `data_deciding_tests`' regex against prose saves nothing.**
  The selection is 230 of 308 files. Blanking every comment and docstring
  before matching drops it to 223 files and 1,866.3 worker-seconds against
  1,886.9 — 20.6 seconds. Every heavy file it picks is picked on real code:
  `tests/test_toolshadowing.py` on its `pytest.skip(` for a missing tool
  dependency, `tests/test_combatdrive.py` on importing `tests/gamedata.py`'s
  synthetic arena, `tests/test_staging_sweep.py` on the word `specimen` in
  code.

## What the pre-push run costs

`tools/suite/suiterun.py` does not run the suite twice. Its second pass is
already scoped, by `data_deciding_tests()`, to the files whose source
mentions skipping or game data. That selection is **230 of 308 files, 6,843
tests, 1,886.9 of the no-data run's 2,208.1 worker-seconds — 85% of it.**

Of those 230 files, **79 skip nothing at all without data: 2,568 tests and
948.9 worker-seconds, half the second pass.** `tests/test_toolshadowing.py`
alone is 322.6 of them. The 151 files that do skip at least one test come to
937.9 worker-seconds.

Estimating the parts at the measured parallelism, and marking each as
measured or derived:

| step | seconds | how |
|---|---|---|
| pass one, with data | 262.0 | measured |
| every `tools/` module imported in a fresh interpreter, 8 at a time | ~7 | 46 of the 364 took 0.8 s |
| pass two, no data, 230 files | ~186 | 1,886.9 worker-seconds at 10.14 |
| `ruff` and `genui.py --check` | ~10 | derived |

About 7:45, against the "roughly ten minutes" in `#579 (The test suite takes
four minutes locally and ten before a push, and nobody has measured where
the time goes)`; the load during the measurement and the worktree setup
cover the difference.

## What CI costs

CI already runs four `pytest` jobs in parallel — Ubuntu and Windows,
Python 3.12 and 3.13 — plus a fifth job for the generated files. On a recent
green run the Ubuntu 3.12 job spent **7:49 inside `pytest`** and 26 s on
everything before it, and the run's wall was set by Windows 3.13 at about
9:30 of `pytest`. A standard runner has four cores, so `-n auto` gives four
workers, and 2,208 worker-seconds over four of them is the right order.

`.claude/rules/commits.md` says the suite "takes about 90 seconds on each of
four jobs". It takes five times that, and the same file's "about 1:40 on
twelve cores" and `pyproject.toml`'s "about 7:00 sequential" were measured
on 3,303 tests where the suite now has 8,234. Those three sentences want
correcting alongside whatever else lands.

## The plan

### 1. Freeze the imported world after collection

**Do it, first, and on its own.** `tests/conftest.py` gains
`def pytest_collection_finish(session): gc.freeze()`, and
`_collect_between_tests` keeps its `gc.collect()` and loses the sentence in
its docstring saying the collection costs nothing measurable.

Expected saving, from the 0.139 s a test the probe measured against the
0.174 s mean the run measured: about **1,150 of the 2,760 worker-seconds in
pass one**, taking its wall from 262 s to roughly 150-165 s; about **890 of
the 1,887 in pass two**, taking it from ~186 s to ~95 s; and the pre-push
run as a whole from about 7:45 to about 4:30. CI's `pytest` step should fall
from 7:49 to somewhere near 3:30 for nothing.

The test: assert `gc.get_freeze_count() > 0` and that it is the imported
world rather than an accident, and watch it fail with the hook removed. The
risk to weigh is the segfault `docs/112-test-harness.md` records — freezing
does not change what is collected after each test, only how much is walked
looking for it, so the mechanism there is untouched, but the builder should
say how many whole-suite runs it saw stay green.

**Builder: `junior-dev`.** The file, the hook and the assertion are all
named.

### 2. One subprocess per tool instead of two

**Do it, second.** `tests/test_toolshadowing.py`'s
`test_importing_a_tool_leaves_the_wish_package_reachable` and
`test_no_tool_leaves_tools_on_sys_path_after_import` are two parametrised
sweeps that import the same module in two fresh interpreters and assert one
property each. Merge them into one sweep whose subprocess asserts both,
naming which property failed in the message, and keep the existing
`SKIP <module>` protocol for a tool whose dependency is not installed.

Expected saving: about **95 worker-seconds in each pass** — the file's call
time halves from 190.6 s — which is around 9 s of wall on each, 18 s across
the pre-push run.

The cost is that one failure now masks the other for the same tool, which is
the reason to keep the two assertion messages distinct rather than to keep
the two processes.

**Builder: `junior-dev`.**

### 3. Compute the reachable icon set once

**Do it, third.** Move the `parts` and `legal` fixtures out of
`tests/test_iconparts.py` and `tests/test_dosicon.py` into `tests/conftest.py`
at session scope, and mark both files
`pytestmark = pytest.mark.xdist_group(name="icon-tables")` so their tests
share a worker and the session fixture is built once rather than five times.

Expected saving: about **74 worker-seconds**, 7 s of wall, in pass one only —
these tests skip without data. The group it creates is about 13
worker-seconds after the saving, well short of anything that could be a tail.

**Builder: `junior-dev`.** This is the issue's candidate 1, and the number
is the whole of what candidate 1 is available to save: setup is 4.6% of the
run and three quarters of the interesting part is this one computation.

### 4. Whether pass two may shrink to the files that actually skip

**A question for Donald, not a verdict.** The second pass exists to prove
nothing breaks when the game data is absent. It selects by source regex, and
half of what it selects observes no difference at all.

*The question:* may the second pass run only the files that contain a test
which actually skips without data, rather than every file whose source
mentions skipping or data?

*What it saves:* 948.9 worker-seconds today, and about 615 after item 1 —
roughly **58 s of the pre-push run**, taking it under 3:30.

*What it risks:* the regex is a deliberate over-approximation. A file that
skips nothing today could acquire a data dependency tomorrow and would no
longer be re-run without data; CI would catch it, but a push later than the
pre-push run does. Any narrowing of this kind trades a local check for a
remote one, which is a policy choice and not an optimisation.

If the answer is yes, the mechanism is in `tools/suite/suiterun.py`,
function `data_deciding_tests`, and the builder is `junior-dev`.

### 5. Whether the local run before a push may be change-scoped

**The issue's candidate 3, and still a question for Donald.** Nothing in
this measurement makes it more or less attractive: it is a choice about
where a regression is caught, not about where the seconds go. What the
measurement does say is that items 1 to 3 take the pre-push run from about
7:45 to about 4:15 without touching what is checked, so the choice can be
made afterwards against a smaller prize.

### 6. Group balance under `--dist loadgroup`

**Reject.** The issue's candidate 2. There are two groups in the whole
suite. `emulator-pool` is 172 tests and 34.0 worker-seconds, 1.2% of the
run; `conftest-guard-probe` is two tests and 2.3 s. A perfectly balanced
twelve-worker run of pass one would take 230.0 s against the 262.0 s
measured, and a worker's own collection of all 8,301 tests — 3.39 s warm, in
one process, twelve of them at once — accounts for much of that. There is no
tail to shrink.

### 7. Splitting CI across more jobs

**Defer; do not do it now.** The issue's candidate 4. CI is already four
`pytest` jobs in parallel and the run's wall is set by the slowest, Windows
3.13 at about 9:30. Item 1 should take each job to somewhere near 3:30 for
no new jobs, no new checkouts and no new installs. Splitting a job in two
adds about 30 s of setup to each half and doubles the matrix; it is a
reasonable second move if 3:30 is still too long, and it does nothing at all for
the pre-push run, which is what the issue's target names.

## What could not be measured, and what would settle it

* **Per-worker busy time and finish time.** Neither run was made with `-v`,
  so no `[gwN]` tag appears in either log, and JUnit records no worker for a
  test. The bound above — 230.0 s balanced against 262.0 s actual, with only
  36.3 worker-seconds of grouped work in the suite — is as far as this data
  goes. A re-run with `-v` would give the real distribution.
* **Whether freezing changes the segfault rate.** `docs/112-test-harness.md`
  needed twelve runs to say the QApplication fix held. One run says nothing
  here either way.
* **Windows.** Every figure on this page is Linux. The CI step times are the
  only Windows evidence, and they measure a four-core runner rather than
  this machine.
* **The pre-push run end to end.** It was never run as a whole for this
  measurement — the two passes were separate whole-suite runs. Its second
  pass is derived by restricting the no-data run to the 230 files
  `data_deciding_tests()` picks, which is close but not identical to running
  only those files, because the scheduler sees a different set.
