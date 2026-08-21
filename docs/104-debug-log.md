# An opt-in debug log — plan

**Status: planned, not started.** So a bug report can carry evidence, without
the program collecting anything a user did not ask it to.

---

## The rule this is built around

**Only our own process, only on request, only to a local file.** The log is off
by default, is turned on from a menu item, is written where the user can read it
before sending it, and is never transmitted anywhere by `wish`. There is no
telemetry, no upload, no "phone home", and no counting of anything.

That is not a nicety. A tool that reads a player's save disks has access to
their filesystem and their machine, and the only defensible default is to
record nothing.

---

## What goes in

Useful when reading a GitHub issue, and cheap to justify:

* `wish` version, Python version, PyQt version, platform and OS release;
* which backend attached, and what it reported — including `MonitorBusy`;
* the tab in view, and the poll interval actually used;
* exceptions with tracebacks, including the ones `Session.poll` currently
  swallows to keep the window alive;
* for a save file: its **size and block count**, the number of characters, and
  the area id — the shape of the file, not its contents;
* for the map: the fingerprinted area and the confidence, since "it drew the
  wrong map" is the report we most expect;
* timings for anything that stalls the emulator, because that is the failure a
  user notices and cannot describe.

## What stays out

* **No file paths.** A path carries a username, and often a real name. Log the
  basename only, or better, nothing.
* **No character names, and no save contents.** A bug in the editor is
  reproducible from field names and offsets.
* **No environment dump, no process list, no network state.**
* **Nothing about any process but ours.** `ss -tnp | grep 6502` is a thing we
  tell a user to run; it is not a thing the program should run for them.

## Shape

* **View > Debug log**, a checkable menu item, off at every start. It is
  deliberately not remembered between runs: a logging setting that survives a
  restart is one a user forgets is on.
* Turning it on shows where the file is and opens the containing folder.
* One file per session under the platform config directory, alongside the
  existing settings; keep the last few and delete the rest.
* A line at the top of every log saying what is recorded and what is not, so
  the user can check the claim rather than trust it.
* **Show the log** opens it in the user's editor. Nobody should have to hunt
  for a file they are about to paste into an issue.

## Verification

* With logging off, the file is never created and nothing is written.
* With it on, the file contains no absolute path, no character name, and no
  bytes from a save.
* An induced exception in a map poll appears in the log with its traceback,
  and the window stays up.
* Turning it on and off during a session starts and stops writing at once.
