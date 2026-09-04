---
paths:
  - "**/*.ui"
  - "**/ui_*.py"
  - "tools/genui.py"
---

# Qt Designer

**Every widget layout that a human might rearrange must come from a `.ui`
file.** New windows, dialogs, panels and forms are designed in Qt Designer and
compiled with `tools/genui.py`; `tools/genui.py --check` is what CI runs and
catches a compiled file that is out of date. The Python code wires signals,
sets models and does anything dynamic; it does not call `addWidget`,
`setLayout`, or build a form in code.

**The only exceptions are custom-painted widgets** -- the map and combat
canvases, the HP/XP bars -- that have no layout to rearrange. Their containers
and placement still belong in the `.ui` that holds them, as promoted widgets.

**The pattern is `editor/character.ui`.** Widgets are found by `objectName` and
matched to the code that drives them, so the form can be rearranged in Designer
without a line of Python changing.

**`tools/genui.py` compiles every `.ui` in the project.** It discovers pairs
automatically -- `<dir>/<name>.ui` becomes `<dir>/ui_<name>.py` -- and
`ensure_current()` at startup regenerates anything stale. A `.ui` added in a new
directory needs a row in `genui.py`'s `UI_DIRS`.

Why these rules exist, and the incidents behind them:
`docs/160-why-these-rules.md`, "Qt Designer".
