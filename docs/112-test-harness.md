# Two test-harness faults

**Status: both fixed, 2026-08-20.** Neither ever affected `wish` itself; both
affected anyone running the suite.

## 1. The suite opened real windows

Running `pytest` without `QT_QPA_PLATFORM=offscreen` put real windows on
whoever was logged in. Many tests edit a character, so those windows were
dirty, and closing one asks **"Save before closing?"** -- which is how Donald
ended up with a queue of dialogs he could not dismiss, one after another.

**Fixed** by setting it in `tests/conftest.py` at import time, before anything
imports Qt:

```python
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
```

In `conftest.py` rather than in a Makefile or a CI variable, so it protects
every way of invoking pytest, including a bare `pytest` typed by hand.

**The standing rule:** never call `widget.close()` on a test's windows in a
fixture. It runs `closeEvent`, which is application logic -- the save prompt is
exactly that. A teardown that wants widgets gone should drop references, not
close them.

## 2. The intermittent segfault in `findChild`

About one run in three dumped core, always with the same signature:
`EditorWindow.__init__` calling `_child`, which calls `findChild`.

**The cause was the QApplication, not `findChild`.** PyQt owns the
QApplication from Python: when the last Python reference to it goes, the C++
object is destroyed, and `~QApplication` deletes every widget still standing.
Every test module declares its own **function-scoped** `app` fixture returning
`QApplication.instance() or QApplication([])`, so the application was destroyed
at the end of whichever test held it last and the next test built a fresh one.

Reduced to a REPL:

```
>>> a = QApplication([]); w = QLabel("keep me")
>>> del a; gc.collect()
>>> QApplication.instance()
None
>>> w.text()
RuntimeError: wrapped C/C++ object of type QLabel has been deleted
```

A plugin logging `id(QApplication.instance())` at each test's teardown counted
**125 distinct QApplication objects in one session**, with stretches of `None`
between them. Every Qt object that outlived one of those teardowns -- anything
sitting in a reference cycle, anything a wider fixture held -- was pointing at
freed memory afterwards. `findChild` was simply the first thing to walk the
wreckage: it is the widest tree walk the suite performs, and `EditorWindow`
does it in its constructor.

That also explains the result nobody could account for. "Keep every top-level
widget alive for the session" crashed **6 runs out of 6** because those are
precisely the widgets `~QApplication` deletes underneath you: keeping the
Python wrappers alive guaranteed the dangling pointers instead of merely
risking them.

**Fixed** with a session-scoped autouse fixture in `tests/conftest.py` holding
one QApplication from the first test to the last. Each module's own `app`
fixture then gets that same object from `QApplication.instance()`, and nothing
destroys it. Re-probed after the fix: **1 distinct QApplication per session**.
The per-module `app` fixtures need no change -- they are harmless once
something else is holding the object.

### Measured

Full suite, this machine, Python 3.12.3, PyQt6 6.11.0 / Qt 6.11.1.

| approach | runs | crashes |
|---|---|---|
| nothing | -- | ~1 in 3 (reported) |
| drain `DeferredDelete` in the teardown | -- | no change (combat-view work) |
| keep every top-level widget alive for the session | 6 | **6** |
| `gc.collect()` after each test (the state before this) | 10 | 3 |
| one QApplication held for the session | 12 | **0** |

Two negative results to keep:

| probe | result |
|---|---|
| `pytest tests/editor/test_editor.py` alone | 8 runs, 0 crashes -- the fault needs the modules that run before it |
| the whole suite under `gdb` | 6 runs, 0 crashes -- a debugger hides it, so no C-level trace was ever obtained, and none is needed now |

### Not done, and why

* **Cut the number of windows the suite builds.** Unnecessary: the count was
  never the mechanism, only a way of raising the odds. Reworking sixty tests
  onto a shared window would risk real coverage for no measured gain.
* **A newer PyQt6.** Already on 6.11.0, and it reproduced there.
* **Stop `_child` using `findChild`.** `findChild` was the messenger. Caching
  the lookups would have hidden the fault rather than fixed it, and with 55
  windows a run it is not hot enough to justify doing on its own merits.

## Running the suite on the agent VM

Two local runs at once start two full sets of Qt-loading workers, and on the
agent VM (12 GiB, no swap) that was enough for the kernel to kill the
orchestrator session and every agent under it. A third fault of this kind is
not in the code under test; it is in how many test commands run together.

On a managed host (`/etc/wish/test-runner.json` exists with `enabled: true`)
`tests/conftest.py` stops a direct `pytest` before collection and prints the
launcher command. Local tests run only through `.venv/bin/python
tools/suite/testrun.py`:

* **One top-level test command at a time**, across every session and worktree,
  under one shared execution lock.
* **Each command in `wish-tests-run.service`** under `wish-tests.slice`, which
  caps test memory at 8 GiB with no swap. Agents, the runner and the launcher
  stay outside the slice, so a test that exceeds the cap ends its own service
  and nothing else.
* **Parallelism inside one command is unchanged**: `-n auto --dist loadgroup`,
  or the guest profile's `-n 12`.
* **A request is a record** under `~/.local/state/wish/test-requests/`:
  `submit` creates it, `run ID` runs it in the foreground (exit 0 only when
  every requested check passed), and `status`, `list`, `cancel` and `reconcile`
  read or settle it. It ends as passed, failed, timed_out, cancelled,
  interrupted, stale or infrastructure_failure.
* **Agents do not call the launcher's `run`.** The session's one `test-runner`
  does, taking requests in arrival order; see
  [Delegating](../.claude/rules/delegating.md).

CI, Windows, macOS and an unmanaged Linux run `pytest` as before.
