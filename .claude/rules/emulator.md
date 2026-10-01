---
paths:
  - "automap/**"
  - "tools/c64/session.py"
  - "tools/registry/instance.py"
---

# Driving the emulator

**Emulator work goes through the instance pool.** VICE serves exactly one
binary-monitor connection *per process*, so running two things at once means two
emulators, not two connections.

**`tools/registry/instance.py claim` hands back a slot** -- a binary-monitor port, a text-
monitor port, a command port, an X display, a work directory and a `vicerc` --
and holds the lease for as long as your process lives. `Session(disk,
slot=slot)` takes it from there. Two instances have been proven to coexist;
`docs/123-parallel-sessions.md` §0 has the measurement.

**On the C64 Ultimate, turn the speaker off before you boot a game.** The
machine has an **internal speaker** and Donald has no physical way to turn it
down, so booting Pool of Radiance plays the intro music into the room he is
working in. A window on his screen and a noise in his room are the same kind of
mistake.

```sh
mkdir -p "${TMPDIR:-/tmp}/wish/c64u"
c64u --host <device> config export > "${TMPDIR:-/tmp}/wish/c64u/config-backup-$(date +%F-%H%M).json"
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
at that desktop while agents run. `tools/c64/launch.sh` adds `+sound` in that
branch too, because he can hear a headless emulator through his speakers even
when it draws no window.
Harness file names follow [Naming by responsibility](../../docs/236-requirements-for-adding-a-new-platform.md).

**Every emulator an agent starts is silent.** A brief for an emulator run
says "silent" as well as "offscreen". VICE's headless launcher disables
sound; the pooled DOSBox configuration disables its mixer, Sound Blaster and
PC speaker. Other launch paths must establish their own silence controls.

* **FS-UAE**: **`--volume=0` does not silence it.** Use
  `SDL_AUDIODRIVER=dummy` for a build that links SDL audio,
  `flatpak run --nosocket=pulseaudio` for the stock Flatpak, and
  `ALSOFT_DRIVERS=null` for a native 3.x build with OpenAL.
* **WinUAE**: it runs on the Windows VM, whose audio reaches the host, and
  `sound_output=none` is **not** available -- it deadlocks Silver Blades on its
  second turn, which is why `tools/amiga/goldbox-a500.uae` sets
  `sound_output=interrupts`. Mute the VM's own audio device rather than the
  emulator's.

**Verify the audio path on the machine that can reach the speakers.** A host
check of the running VM's configuration showing no virtual sound device and
an audio backend of `none`, with no audio forwarding or passthrough, is valid
silence evidence. Record that configuration evidence in the run brief and
retain the emulator's sound-disabled configuration. Recheck after a VM or
audio configuration change; a missing guest `pactl`, `wpctl` or audio socket
does not block a run with this evidence. Do not install an audio service to
verify a guest that has no audio path.

For a machine with an audio path, verify its actual output control: for
example, read back the Windows playback endpoint's mute state for WinUAE.
Record the endpoint and readback, and recheck if the endpoint, session or
mute state changes. Keep WinUAE's sound interrupts enabled. A check of
`pactl list sink-inputs` is useful on the host audio server while a stream is
active, but an empty list before launch alone does not prove silence.
One emulator's missing audio verification does not block experiments on
other machines whose silence is established.

**The pool owns the lifecycle.** Allocate, launch, tear down. Do not attach to
an emulator you did not launch, and do not launch one outside the pool -- an
instance nobody leased cannot be told from a human's.

**Tear down only what your own slot launched**, with `Session.terminate()` or
`slot.teardown()`. Reclaim another slot only when `tools/registry/instance.py reap` says
its lease is unheld; a slot whose lease is held is somebody's, however dead it
looks.

**Never point VICE at Donald's config.** Every pooled instance gets its own
`vicerc` seeded from his, with `SaveResourcesOnExit=0`, so nothing an agent runs
can write settings back. His file is read as a template and never opened for
writing.

**Snapshot before any risky leg, and roll back instead of fighting.** A risky
leg is a walk through an area with random encounters or a journey across a
world map. C64 drivers: `Session.snapshot(name)` saves the whole machine, the
1541 and its disk included, under the slot's `~/.cache/wish` folder;
`restore(name)` puts it back; `discard_snapshot(name)` deletes it;
`walk_with_retry(moves, retries=3)` does the snapshot, walk, restore and retry
for a leg and returns False, with the machine restored, when every attempt met
an encounter. After a restore `save_game` raises until a disk is attached on
purpose. Amiga: under WinUAE, `WinuaePipe.snapshot(name, holder)`, `restore(name, holder)` and `discard_snapshot(name, holder)`, or `tools/amiga/amigadrive.py --holder H snapshot|restore|discard_snapshot NAME`, save and put back the whole machine through the pipe, under `C:\Amiga\States\<holder>` on the guest; the state records each drive's image path, not its contents, so a save after a restore reaches the image and is allowed. FS-UAE has no usable machine-state save in this build, because its savestate crashes.

**Suppress random encounters with `Session.no_encounters = True`, unless the
run proves a conversion or must meet encounters.** C64 drivers: it writes the
running area's gate from `ENCOUNTER_GATES` before every move key, and
`skip_world_map_ambushes = True` skips Curse's fixed world-map fights. Both are
for automapper and driver testing only, never for conversion acceptance or for
a save that proves a conversion: the pokes are save-page bytes, so once any is
written `save_game` raises unless `allow_suppressed=True` is passed. An area
missing from the table is logged once as unsuppressed; add its gate to
`ENCOUNTER_GATES` to cover it. Amiga: in an FS-UAE `session`, `no_encounters on` for walks through encounter areas, and `no_encounters off` before any save. A save key is refused while it is on, but that net is incomplete, so `off` is the rule. It is never used for conversion proof, and the `wish` subcommand refuses it.

**Every emulator run that walks a party through areas with random encounters,
or travels a world map, uses snapshots, plus `no_encounters` unless it proves a
conversion or must meet encounters.** A brief for an `emulator-runner` says
which of the two it wants.

**A new tool that needs the player's disks reads `$POR_DISKS`, then
`automap.paths.find_disks()`** -- not a fourth way, and never a hardcoded path.
`tools/areas/geomap.py` is the one-liner.

Why these rules exist, and the incidents behind them:
`docs/160-why-these-rules.md`, "The machine".
