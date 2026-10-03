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
purpose. Amiga: under WinUAE, `tools/amiga/amigadrive.py` has `snapshot`,
`restore` and `discard_snapshot`, and `docs/70-driving-the-game.md` has the
calls. The state records each drive's image path, not its contents, so a game
save made between a snapshot and its restore stays on the disk image while
memory goes back; a run that saved in between treats that image as changed.
FS-UAE has no usable machine-state save in this build, because its savestate
crashes. DOS: the acceptance driver's `snapshot NAME` and `restore NAME` steps use
`tools/dos/dossnapshot.py`'s `SnapshotSession`, which works on DOSBox-X only,
because DOSBox 0.74 has no save states and the driver stops the run there; a
restore lists the `SAVE` files changed since the snapshot, since a game save
stays on disk. The DOS Curse console does the same by hand:
`tools/curse_of_the_azure_bonds/doscurse.py console --snapshots` boots
DOSBox-X, and its `snapshot NAME` and `restore NAME` commands save and restore
the machine, the restore logging the `SAVE` files changed since the snapshot,
which stay on disk.

**Suppress random encounters with `Session.no_encounters = True`, unless the
run must meet encounters.** C64 drivers: it writes the running area's gate
from `ENCOUNTER_GATES` before every move key, recording each address's
original value, and `skip_world_map_ambushes = True` skips Curse's fixed
world-map fights. Once any gate is written `save_game` raises until
`restore_encounter_gates()` has turned both off, written every original back
and read each one back equal; a gate that reads back wrong, or one the game
wrote itself while it was held, raises and the save stays blocked.
`allow_suppressed=True` saves anyway and is for automapper and driver testing
only. A walking conversion proof may switch encounters off only through
`tools/c64/acceptance.py --no-encounters`, which turns the switch on for each
`walk` step, clears the title's rest-interruption byte during each `rest` step
so a rest in a town runs to its end (without the switch a rest behaves as the
game does), and restores and verifies the gates at its end and before every
save, recording them in `summary.json`; such a run proves movement and saving,
not combat. An area missing from the table is logged once as unsuppressed; add
its gate to `ENCOUNTER_GATES` to cover it. Amiga: in an FS-UAE `session` or `wish` run, `no_encounters on` for walks through encounter areas, and `no_encounters off` before any save. Under `wish` it reads and writes through the window's connection helper. An interrupted run puts the bytes back as it ends, and after a `kill -9` the next run against that emulator repairs them from the journal in `~/.cache/wish/noencounters/`. A save key is refused while a change may be in the game, but that net is incomplete, so `off` is the rule. Under WinUAE, `tools/amiga/noencounters.py --holder H --title T on` turns it on, its `keys` replaces `amigadrive.py keys` while it is on, and its `off` comes before any save; it stays on across commands, writes through `WinuaePipe`, and records the originals in `~/.cache/wish/noencounters/winuae.json`, from which the next command takes over or repairs what a killed one left. It is never used for conversion proof. DOS: on DOSBox-X, `tools/dos/dosnoencounters.py`'s `NoEncounters(session, title, save)` writes the running area's gate from its `GATES` through the debugger before every move key once `on()` is called (`SuppressedPool` is `PoolOfRadiance` with that done), `off()` puts back each value the game has not changed since, and a save raises `SaveBlocked` while it is on or a value is outstanding; `tools/dos/acceptance.py --no-encounters` wires it in (`--speculative-encounters` for Silver Blades), stops its `save` step while it is on, records `no_encounters: true` in `summary.json`, and is never used for a run that proves a conversion; Silver Blades needs `speculative=True` and the save, because its offsets were not read in a running game; DOSBox 0.74 has no debugger and cannot use it. For Silver Blades, `play` waits for the PLAY bar and presses `p` before the attract demo starts, and `until load` or `until party` waits for a load instead of a fixed `wait`.

**Every emulator run that walks a party through areas with random encounters,
or travels a world map, uses snapshots, plus `no_encounters` unless it must
meet encounters or proves a conversion on a platform whose switch cannot
restore and verify its gates before a save.** A brief for an `emulator-runner` says
which of the two it wants.

**A new tool that needs the player's disks reads `$POR_DISKS`, then
`automap.paths.find_disks()`** -- not a fourth way, and never a hardcoded path.
`tools/areas/geomap.py` is the one-liner.

Why these rules exist, and the incidents behind them:
`docs/160-why-these-rules.md`, "The machine".
