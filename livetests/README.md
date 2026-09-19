# livetests

The tests that start an emulator or talk to hardware, kept apart because the normal pytest run never collects this directory.

| file | purpose |
|---|---|
| `conftest.py` | Puts the repository root on `sys.path` and forces `QT_QPA_PLATFORM=offscreen`, so no run puts a window on the desktop. |
| `needs.py` | Fails a test, naming the missing executable, registry, game folder or save specimen, when what it needs from the machine is not there. |
| `test_live_dosbox.py` | Boots DOSBox, takes one step in the game from save slot A and checks that only the party's square moved in the save. |
| `test_live_dosfight.py` | Boots DOSBox, drives one fight from save slot J and checks that experience rose in the saved records. |
| `test_live_dosboxx.py` | Boots DOSBox-X and re-runs the debugger worked example of `docs/142-dosbox-x-debugger.md`. |
| `test_live_c64u.py` | Reads the raster counter twice from a C64 Ultimate on the network and checks it moved; fails when the `c64u` command-line tool is missing or not executable, skips when the device does not answer. |

A test belongs here when it starts an emulator or talks to a device; being in this directory is the opt-in, so there is no environment variable to set. The weekly run in the agent VM and a run by hand are the same command:

```sh
.venv/bin/python -m pytest livetests -n0 -rs
```

`-n0` runs the tests one at a time, which the emulator pool's fixed display numbers need, and `-rs` prints why the C64 Ultimate test skipped.

A missing emulator or its helper tools, DOS game folder or archives, save specimen or `gamedisks.yaml` fails a test with the path in the message, and so does a missing or non-executable `c64u` command-line tool, because they are installed on the machine that runs these. Only the C64 Ultimate not answering skips: it is often switched off, and its skip reason says it did not answer.

Run `livetests/` on its own and never in the same `pytest` command as `tests/`: both directories carry a `conftest.py`, and a run over both fails to import `tests/` (33 collection errors with `pytest tests livetests`).
