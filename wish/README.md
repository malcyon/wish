# wish

The application that wraps the other two — the tabbed window, preferences, the
debug log, the backend session, the CLI entry point. The direction of the
imports is the point: `wish` may import both `editor/` and `automap/`, `editor`
imports neither, and `goldbox/` stays transport-free.

`wish/_version.py` is not listed below: it is written at build time by
hatch-vcs and is gitignored.

| file | purpose |
|---|---|
| `__init__.py` | The package docstring stating that rule, plus `__version__` — resolved from the build's `_version.py`, then the installed metadata for `wish-goldbox`, then `0.0.0+unknown` rather than an invented number. |
| `__main__.py` | The `wish` command: the window, and the `export` / `import` subcommands beside it. Never launches an emulator — start VICE with the usual wrapper and this attaches; with nothing running the map tab waits and the editor does not care. |
| `about.py` | Help > About — the version, so a bug report can name the build it came from. Built by hand rather than with `QMessageBox.about` so it can carry its own picture, and `box()` returns the dialog unshown so a test can read it. |
| `backends.py` | Which live backends exist and how to find one that is there, as data rather than a hard-coded probe of `127.0.0.1:6502`. A backend that cannot be probed is not offered, and `probe()` must be cheap and must never raise, because it runs on a timer with no emulator present most of the time. |
| `debuglog.py` | An opt-in debug log so a bug report can carry evidence — only our own process, only on request, only to a local file, with no telemetry of any kind. Kept checkable: a non-propagating logger, every line through `Scrubbed` (absolute paths reduced to their last component, because a path carries a username), and nothing written while it is off except an uncaught exception, which always goes to `CRASH`. |
| `debugmode.py` | A flag, off by default, carried by the debug log. `WISH_DEBUG=1` is the storage rather than a private attribute so a spawned subprocess inherits it and so one variable covers all three entry points; `--debug` is stripped into the same variable so the two spellings cannot disagree. |
| `nativewatch.py` | Logs the raw Windows message stream around the note popover that closes itself. Three fixes reasoned from Linux were all wrong and no Qt-level cause exists — the popover gets a bare `Close` while still visible and active — so this names the native message instead of narrowing suspects further. Windows only, and only while the debug log is on and a popover is open. |
| `preferences.py` | File > Preferences — the game disks, the live backend, and where a warp may go. Half of it is a *report* rather than a form, because the failure it exists to fix is silent: it says which folder is in use, who named it and which titles are in it, so a user who types nothing still learns what went wrong. One Close and no Cancel; every control applies at once. |
| `session.py` | The one live connection and the state machine around it. VICE accepts a second binary-monitor connection and then silently ignores it, so a window whose tabs each opened their own would hang; this owns a single `Target` and hands it to whichever tab is visible. Three ordinary states, none an error, and only the visible tab polls. |
| `ultimate.py` | A Commodore 64 Ultimate backend over its documented HTTP REST interface. **UNVERIFIED** — nobody on the project has the hardware, it has only been exercised against a stub implementing the vendor documentation, and `Backend.verified` is False so the interface says so too. |
| `window.py` | The tabbed window over the editor and the map, both used unchanged as `QMainWindow` pages. What the outer window adds is the three things a merged application owes you: one connection, one status bar and one title. The editor tab is never handed the target. |
