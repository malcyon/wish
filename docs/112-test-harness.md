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

Two negative results worth keeping:

| probe | result |
|---|---|
| `pytest tests/test_editor.py` alone | 8 runs, 0 crashes -- the fault needs the modules that run before it |
| the whole suite under `gdb` | 6 runs, 0 crashes -- a debugger hides it, so no C-level trace was ever obtained, and none is needed now |

### Not done, and why

* **Cut the number of windows the suite builds.** Unnecessary: the count was
  never the mechanism, only a way of raising the odds. Reworking sixty tests
  onto a shared window would risk real coverage for no measured gain.
* **A newer PyQt6.** Already on 6.11.0, and it reproduced there.
* **Stop `_child` using `findChild`.** `findChild` was the messenger. Caching
  the lookups would have hidden the fault rather than fixed it, and with 55
  windows a run it is not hot enough to be worth doing on its own merits.
