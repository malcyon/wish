---
paths:
  - "automap/**"
  - "tools/session.py"
  - "tools/instance.py"
---

# Driving the emulator

**Emulator work goes through the instance pool.** VICE serves exactly one
binary-monitor connection *per process*, so running two things at once means two
emulators, not two connections.

**`tools/instance.py claim` hands back a slot** -- a binary-monitor port, a text-
monitor port, a command port, an X display, a work directory and a `vicerc` --
and holds the lease for as long as your process lives. `Session(disk,
slot=slot)` takes it from there. Two instances have been proven to coexist;
`docs/123-parallel-sessions.md` §0 has the measurement.

**Set `POR_HEADLESS=1`.** It keeps the window off Donald's desktop, and he works
at that desktop while agents run.

**The pool owns the lifecycle.** Allocate, launch, tear down. Do not attach to
an emulator you did not launch, and do not launch one outside the pool -- an
instance nobody leased cannot be told from a human's.

**Tear down only what your own slot launched**, with `Session.terminate()` or
`slot.teardown()`. Reclaim another slot only when `tools/instance.py reap` says
its lease is unheld; a slot whose lease is held is somebody's, however dead it
looks.

**Never point VICE at Donald's config.** Every pooled instance gets its own
`vicerc` seeded from his, with `SaveResourcesOnExit=0`, so nothing an agent runs
can write settings back. His file is read as a template and never opened for
writing.

**A new tool that needs the player's disks reads `$POR_DISKS`, then
`automap.paths.find_disks()`** -- not a fourth way, and never a hardcoded path.
`tools/geomap.py` is the one-liner.

Why these rules exist, and the incidents behind them:
`docs/160-why-these-rules.md`, "The machine".
