# Two test-harness faults — task

**Status: open. Neither affects `wish` itself; both affect anyone running the
suite.**

## 1. The suite opens real windows

Running `pytest` without `QT_QPA_PLATFORM=offscreen` puts real windows on
whoever is logged in. Many tests edit a character, so those windows are dirty,
and closing one asks **"Save before closing?"** — which is how Donald ended up
with a queue of dialogs he could not dismiss, one after another, on 2026-08-20.

**Fix:** set it in `tests/conftest.py` at import time, before anything imports
Qt:

```python
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
```

In `conftest.py` rather than a Makefile or a CI variable, so it protects every
way of invoking pytest, including a bare `pytest` typed by hand.

**Also:** never call `widget.close()` on a test's windows in a fixture. It runs
`closeEvent`, which is application logic — the save prompt is exactly that. A
teardown that wants widgets gone should drop references, not close them.

## 2. An intermittent segfault in `findChild`

About **one run in three to one in four** dumps core, always with the same
signature: `EditorWindow.__init__` calling `_child`, which calls `findChild`.
The suite passes 641 when it completes; nothing is wrong with the code under
test.

Measured, so nobody repeats the dead ends:

| approach | result |
|---|---|
| nothing | ~1 run in 3 crashes |
| `gc.collect()` after each test (**current**) | ~1 in 4 — better, not a cure |
| keep every top-level widget alive for the session | **6 runs of 6 crashed** |
| drain `DeferredDelete` in the teardown | no change (tried by the combat-view work) |

The third result is the informative one. If the fault were only about *when*
destruction happens, never destroying anything would fix it; instead it made it
certain. So the whole "just do not destroy" family is ruled out, and the cause
is something about the number of live Qt objects rather than the timing alone.

**Untried, in rough order of promise:**

1. Cut the number of windows the suite builds — `tests/test_editor.py` builds one
   per test, and a module-scoped window would remove most of them at a stroke.
2. Find what `findChild` is actually walking into: run under a debugger, or
   `PYTHONMALLOC=malloc` with valgrind, and get a real C-level trace instead of
   the Python frame.
3. Check whether it survives a newer PyQt6, and whether it reproduces on any
   machine but this one.
4. Stop `_child` using `findChild` at all — cache the lookups once per window.
   That is a change to `editor/window.py` rather than the tests, and it would be
   worth doing on its own merits if `findChild` turns out to be hot.

**Do not paper over it.** A retry wrapper or a `-p no:randomly` incantation
would hide a real memory fault, and the same fault could bite a user with a
long-lived window.
