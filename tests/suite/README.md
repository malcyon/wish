# suite

Tests for the suite's own tooling under `tools/suite/` and the guards that keep the repository itself in order.

| file | purpose |
|---|---|
| `test_conftest_state_guard.py` | Checks that `tests/conftest.py`'s guard against a module rebinding `automap.state._data_dir` at import time fails a real child `pytest` run and leaves a monkeypatched rebind alone. |
| `test_datatouch.py` | Checks that `tools/suite/datatouch.py` records every route by which a test file of a generated suite reaches the game data, names the route beside each file and selects nothing when its log is missing or unreadable. |
| `test_gamedata.py` | Checks that `tests/gamedata.py` finds Curse's disks through the registry alone, skips where there is no registry and fails where a machine's own registry cannot say where a title's disks are. |
| `test_gc_freeze.py` | Checks that an imported test module is out of the per-test garbage collection while an object built during a test is still in it. |
| `test_repository_contents.py` | Checks that the tracked files carry no game data, machine path, scratch-directory path, bare issue number or one machine's ansible values, and that the rule, agent and hook files agree with each other. |
| `test_staging_sweep.py` | Checks that no script under `tools/` stages a copy of a read-only specimen where the game has to write, against a reviewed allowlist. |
| `test_suiterun.py` | Checks that `tools/suite/suiterun.py` points the no-data pass at a path that does not exist, runs only the files that ask for data, cleans up its worktree and names a marker only for a green run. |
| `test_testparty.py` | Checks that `tools/suite/testparty.py` generates the same six-character party every time and that its level-one party matches the six the engine rolled. |
| `test_toolhelp.py` | Checks by reading each script under `tools/` that no call which claims a slot, boots an emulator or opens a window runs before `argparse` has handled `--help`. |
| `test_toolpaths.py` | Checks that every `tools/` path a tracked text file cites is a path that exists. |
| `test_toolreadmes.py` | Checks that every `tools/` directory has a README with one row per file in it and that `tools/README.md` lists every directory. |
| `test_toolshadowing.py` | Checks that neither a test file nor a tool can leave `tools/wish.py` shadowing the `wish` package. |
