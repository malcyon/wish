"""Debug mode: a flag, off by default, that the debug log carries with it.

**An environment variable, `WISH_DEBUG=1`, and the debug log turns it on.**
`debuglog.start()` calls `enable()` and `debuglog.stop()` calls `disable()`, so
a user who ticks Debug log for a bug report has debug mode too and is not asked
to export anything. The variable stays the storage because the other consumer
is an unattended harness that cannot click, and because `wish`, `wish-editor`
and `wish-automap` are three entry points launched from a desktop file -- one
variable covers all of them. `--debug` is an alias: `enable_from_argv` strips
it and sets the variable, so the two spellings cannot disagree.

**Nothing else in the application reads `os.environ` for this.** `enable()`
sets the variable rather than a private flag, so a debug session that spawns a
subprocess passes the mode on.

**It currently gates nothing.** The one control it ever gated was the FastTravel row
under the map, and that row is now Fast Travel and is shown to everybody: P20
fasttraveled into every area whose arrival square was unknown and measured where the
party landed, which is what the gate was waiting for
(write-up lost, `work/reports/p20-arrivals.md`; see `docs/118-debug-mode.md`).
What is left is the
flag itself -- `--debug`, the variable, and the line `note()` puts in the debug
log and the About box -- kept because the log turns it on and off and because
the next control that needs a gate will want one that is already wired.

Nothing else is affected either way: the editor, the save-file path and the
log's privacy claims never read this.
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
