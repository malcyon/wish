# An opt-in debug log

**Status: built.** `wish/debuglog.py`, the menu items in `wish/window.py`, the
hooks in `wish/session.py`, and `tests/test_debuglog.py`, which tests the
privacy claims and not only the plumbing.

So a bug report can carry evidence, without the program collecting anything a
user did not ask it to.

---

## The rule this is built around

**Only our own process, only on request, only to a local file.** The log is off
by default, is turned on from a menu item, is written where the user can read it
before sending it, and is never transmitted anywhere by `wish`. There is no
telemetry, no upload, no "phone home", and no counting of anything.

That is not a nicety. A tool that reads a player's save disks has access to
their filesystem and their machine, and the only defensible default is to
record nothing.

Three things make the claim checkable rather than a promise:

* the handler hangs off the `wish` logger, which does not propagate, so nothing
  any other library logs can reach the file;
* every line is formatted through `Scrubbed`, which rewrites an absolute path
  to `.../basename` -- tracebacks included, since those are where paths hide;
* while the log is off there is no file at all, and nothing is written.

---

## What goes in

| Line | Written when |
| --- | --- |
| `logging on: wish 0.2.0, Python 3.12.3, PyQt 6.11.0 / Qt 6.11.0, Linux 6.18.7 x86_64` | the log is turned on |
| `session: …` | any session note changes -- waiting, connected, busy, gone |
| `Fake: monitor busy (…)` | `MonitorBusy`: something else holds the monitor |
| `attached to VICE, polling every 200 ms` | a backend attaches |
| `tab: Automapper, polling every 200 ms` | the visible tab changes |
| `save file: PORSAVE11.D64, 174848 bytes, 38 blocks, save disk, 6 characters, area GEO00` | a file is opened, or the log is turned on with one open |
| `map area: GEO00 (from resident, certain)` | the identified area or the confidence changes |
| `a poll took 410 ms (over 250 ms: the emulator stalled)` | a read takes longer than `SLOW_MS` |
| `the poll raised, and was swallowed` + traceback | `Session.poll` catches an exception to keep the window alive |

The last is the point of the feature. A poll that throws leaves the window up
and one line in the status bar; the traceback used to die there. It is written
once per distinct failure, because a poll that fails every tick would otherwise
write five tracebacks a second.

## What stays out

* **No file paths.** `scrub()` rewrites every absolute path to its last
  component, so a save disk appears as `PORSAVE11.D64` and a frame as
  `File ".../session.py"`.
* **No character names, and no save contents.** `save_shape()` reports size,
  blocks, kind, character count and area id, and reads no record.
* **No environment dump, no process list, no network state.**
* **Nothing about any process but ours.**

---

## Shape

* **View > Debug log**, a checkable menu item, off at every start. It is
  deliberately not remembered between runs: a logging setting that survives a
  restart is one a user forgets is on. Closing the window stops the log.
* Turning it on names the file in a dialog, along with what it does and does
  not record, and enables **View > Show log**, which opens it in whatever the
  desktop uses for a text file.
* One file per session, `wish-YYYYMMDD-HHMMSS.log` under
  `config_dir()/logs` -- beside the existing settings, on every platform
  `automap/paths.py` knows about. The last `KEEP` (5) are kept and the rest are
  deleted when a new one starts.
* A header on every file saying what is recorded and what is not, so the user
  can check the claim rather than trust it.
* A home that cannot be written to turns the menu item back off and says so.
  Nothing here may take the window down.

## Verification

`tests/test_debuglog.py`:

* with logging off, no directory and no file are created, and `note`, `warn`,
  `exception` and `timed` all write nothing;
* with it on, a real save opened in a real window leaves a log with no absolute
  path, no character name, and no twelve-byte run from the disk in it;
* an induced exception in a poll appears with its traceback, the traceback
  carries frames but no paths, and the window is still up afterwards;
* another library's logger, and the root logger, cannot reach the file;
* turning it off stops writing at once; the menu item is off again in a new
  window;
* only the last five session files survive.
