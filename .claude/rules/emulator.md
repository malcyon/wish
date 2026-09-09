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

**On the C64 Ultimate, turn the speaker off before you boot a game.** The
machine has an **internal speaker** and Donald has no physical way to turn it
down, so booting Pool of Radiance plays the intro music into the room he is
working in. He caught an agent doing it on 2026-09-05: *"That is going to
blast the intro song, and I'll have no way to turn it down."* A window on his
screen and a noise in his room are the same kind of mistake.

```sh
c64u --host <device> config export > work/c64u/config-backup-$(date +%F-%H%M).json
c64u --host <device> config set "Speaker Mixer" "Speaker Enable" "Disabled"
# ... drive the game ...
c64u --host <device> config set "Speaker Mixer" "Speaker Enable" "Enabled"
```

**Export the config before you change it, and put the speaker back when you
are done.** `config set` takes effect immediately and is **volatile** -- lost
on power-off -- so nothing here is permanent, which is exactly why
`save-to-flash`, `load-from-flash` and `reset-to-default` stay banned: those
are what would make a change to his machine outlive the session.

The music is `Vol UltiSid 1`/`2` in the same category and the drive noise is
`Vol Drive 1`/`2`, if something quieter than silence is wanted.

**Set `POR_HEADLESS=1`.** It keeps the window off Donald's desktop, and he works
at that desktop while agents run. `tools/porlaunch.sh` adds `+sound` in that
branch too, because he can hear a headless emulator through his speakers even
when it draws no window.

**Every emulator an agent starts is silent, and VICE is the only one this is
already true of.** The headless branch handles VICE and nothing handles the
others: on 2026-09-08 an agent booted FS-UAE offscreen on his own machine to
answer `#464 (Can the automapper follow a live FS-UAE game on Linux, so Wish
and the Amiga game run on one machine?)`, and two "Amiga Emulator" streams
turned up in PulseAudio while he was working. He asked what was making disk
noises, and it took a `pactl list sink-inputs` to say. He was mild about it --
*"I can turn the speakers down, so this is not a huge impact. But make sure to
silence it next time"* -- and mildness is not the point: a noise in his room is
the same kind of mistake as a window on his screen, and the brief that sent
that agent said "offscreen" and forgot to say "silent".

* **FS-UAE**: **`--volume=0` does not silence it** -- all three runs Donald
  heard on 2026-09-08 had it set, which is how this rule came to be measured
  rather than guessed. Use `SDL_AUDIODRIVER=dummy` for a build that links SDL
  audio, `flatpak run --nosocket=pulseaudio` for the stock Flatpak, and
  `ALSOFT_DRIVERS=null` for a native 3.x build with OpenAL.
* **WinUAE**: it runs on the Windows VM, whose audio reaches the host, and
  `sound_output=none` is **not** available -- it deadlocks Silver Blades on its
  second turn (`#331 (Amiga Silver Blades asks a journal word before it will
  adventure, so the title cannot be driven past its party menu)`), which is why
  `tools/goldbox-a500.uae` sets `sound_output=interrupts`. Mute the VM's own
  audio device rather than the emulator's.

**Check rather than assume.** `pactl list sink-inputs` names what is playing,
and a run that leaves nothing there is the only proof that a flag worked.

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
