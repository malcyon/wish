"""Debug mode: the controls that write to a running machine, off by default.

**An environment variable, `WISH_DEBUG=1`, and deliberately not a `Settings`
field.** `wish/window.py` already makes the argument for the debug log: *"Off
at every start, and deliberately not remembered: a logging setting that
survives a restart is one you forget is on."* A mode that pokes the running
game earns that rule twice over.

An environment variable rather than a menu item alone because the consumer is
an unattended harness that cannot click, and rather than a bare flag because
`wish`, `wish-editor` and `wish-automap` are three entry points and the
packaged build is launched from a desktop file -- one variable covers all of
them. `--debug` is an alias: `enable_from_argv` strips it and sets the
variable, so the two spellings cannot disagree.

**Nothing else in the application reads `os.environ` for this.** `enable()`
sets the variable rather than a private flag, so a debug session that spawns a
subprocess passes the mode on.

What it gates, and only this: the Warp row under the map
(`automap/actionbar.py:WarpBar`, `automap/actions.py:Warp`). The editor, the
save-file path and the log's privacy claims are untouched.
"""

from __future__ import annotations

import os

ENV = "WISH_DEBUG"
FLAG = "--debug"
NO_FLAG = "--no-debug"

#: Anything else -- including an empty string, `0` and `off` -- is off. A
#: variable somebody exported once and forgot should not turn the pokes on.
TRUE = ("1", "true", "yes", "on")


def enabled() -> bool:
    """Is debug mode on?"""
    return os.environ.get(ENV, "").strip().lower() in TRUE


def enable() -> None:
    """Turn it on for this process and anything it launches."""
    os.environ[ENV] = "1"


def disable() -> None:
    """Turn it off again. Used by `--no-debug` and by the tests."""
    os.environ.pop(ENV, None)


def enable_from_argv(argv: list[str] | None = None) -> bool:
    """Consume `--debug` / `--no-debug` from *argv* and set the variable.

    Removes the flag in place so an `argparse` that has never heard of it does
    not reject the command line. Call it before parsing; it returns whether
    debug mode is on afterwards.
    """
    if argv is None:
        import sys
        argv = sys.argv
    for flag, act in ((FLAG, enable), (NO_FLAG, disable)):
        while flag in argv:
            argv.remove(flag)
            act()
    return enabled()


def note() -> str:
    """One line for the debug log and the About box."""
    return f"debug mode is {'on' if enabled() else 'off'} ({ENV})"
