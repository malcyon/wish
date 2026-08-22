# An opt-in debug log

**Status: built.** `wish/debuglog.py`, the switch in `wish/preferences.py`, the
hooks in `wish/session.py`, and `tests/test_debuglog.py`, which tests the
privacy claims and not only the plumbing.

So a bug report can carry evidence, without the program collecting anything a
user did not ask it to.

---

## The rule this is built around

**Only our own process, only on request, only to a local file.** The log is off
until it is asked for, is written where the user can read it before sending it,
and is never transmitted anywhere by `wish`. There is no telemetry, no upload,
no "phone home", and no counting of anything.

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

* **A checkbox in File > Preferences**, remembered between runs, with
  `View > Debug log` still behind it as the model the checkbox is a view of.
  A log that survives a restart is one a user could forget is on, so the window
  says so while it is: `[logging]` in the title bar and a red marker in the
  status bar. Closing the window stops the log.
* Turning it on enables **View > Show log**, which opens the file in whatever
  the desktop uses for a text file.
* **Turning it on turns debug mode on, and turning it off turns it off** --
  `debuglog.start()` calls `debugmode.enable()`, `stop()` calls `disable()`.
  One switch, not two. What debug mode reaches, and why the Warp row still
  wants `--debug` at launch, is `docs/118-debug-mode.md` §1.
* One file per session, `wish-YYYYMMDD-HHMMSS.log` under
  `config_dir()/logs` -- beside the existing settings, on every platform
  `automap/paths.py` knows about. The last `KEEP` (5) are kept and the rest are
  deleted when a new one starts.
* **No header.** The file opens on the version line -- `wish`, Python, Qt and
  the platform -- which is the field a bug report needs and which two renames
  have broken. What is and is not recorded is this document's job; it was a
  comment block at the top of every log and nobody read it twice.
* A home that cannot be written to turns the switch back off and says so, and
  leaves debug mode off with it. Nothing here may take the window down.

## Verification

`tests/test_debuglog.py`:

* with logging off, no directory and no file are created, and `note`, `warn`,
  `exception` and `timed` all write nothing;
* the first line of the file is the version line, and no line starts with `#`;
* starting the log turns debug mode on and stopping it turns it off; a log that
  could not be opened leaves debug mode off;
* with it on, a real save opened in a real window leaves a log with no absolute
  path, no character name, and no twelve-byte run from the disk in it;
* an induced exception in a poll appears with its traceback, the traceback
  carries frames but no paths, and the window is still up afterwards;
* another library's logger, and the root logger, cannot reach the file;
* turning it off stops writing at once and disables **Show log**;
* only the last five session files survive.

Two tests were retired when the switch moved into `Settings`.
`test_the_menu_item_is_off_at_every_start` asserted no settings field carried
`log` in its name, which is the decision that was reversed -- and which is why
the field was called `diagnostics`. `test_turning_it_on_says_where_the_file_is`
asserted the wording of the dialog that named the file; the dialog belongs to
`wish/preferences.py` now, and what is asserted here is that there is a file to
show.
