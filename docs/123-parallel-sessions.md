# Running more than one thing at once

**Status: §§1-3 are BUILT and verified (P46, 2026-08-22). §§4-8 are still the
costing they always were.** What changed when it was built is in §0; the rest
of this document is the design, corrected in place where building it proved a
claim wrong.

Donald asked whether Proxmox VMs, each with its own VICE and the game inside,
would let tests run in parallel, and separately asked for "Windows VMs for
DOSBox experiments". Those are three needs and they have three different
answers.

---

## The verdict

* **Parallelism wants processes, not VMs.** VICE's one-connection limit is per
  process. Eight `x64sc` on this box cost about 2.0 GB and no hypervisor; a VM
  per instance is isolation at the wrong layer and buys nothing the pool below
  does not.
* **A Windows VM earns its keep, for one job that is not this one.** It is the
  thing blocking the first `v*` tag: thirteen rows of
  [`122-release-testing.md`](122-release-testing.md) are marked unverified
  because nobody here has Windows. It has nothing to do with DOSBox.
* **DOSBox needs a game, not a hypervisor.** It runs natively on Linux — and the
  dependency this section was written around, "a DOS copy of Pool of Radiance and
  a DOS save, neither of which exists on this machine", **has since been
  satisfied**: see §7.

And one thing worth saying before any of it: **if "tests" meant `pytest`, none
of this applies.** `python3 -m pytest tests/ -q` is 1178 passing and 1 skipped in
about 65 s and touches no emulator at all — `tests/test_automap.py` is the only file that even
imports `ViceTarget`, and it stubs it. Making that faster is
`pip install pytest-xdist && pytest -n 12`, worth perhaps 40 seconds, and it is
not what the rest of this document is about. What is serialised here is the
**driven live sessions** — `tools/session.py`, `tools/walkrun.py`, the
automapper against a running game.

---

## 0. What was built, and what the building corrected

`tools/instance.py` is the pool; `tests/test_instance.py` is 26 tests of it and
none of them needs an emulator.  `tools/session.py` takes a `Slot` and is
otherwise unchanged, so `tools/walkrun.py` and `tools/porcmd` still work on the
human's numbers.  `pytest tests/ -q` is green.

**`x64sc -config <file>` works. CONFIRMED**, and it is the one claim in §2 that
was only PROBABLE.  Launched with `-config` and *no* monitor flags at all, VICE
bound 127.0.0.1:6527 and :6547 from the file alone.  `docs/131-fastloader.md`
reports it could not find the literal `-config` in the binary's option strings;
`x64sc -help` prints `-config <filename>` and the flag is honoured, so that
caveat can go.

**Two instances coexist.** Slots 0 and 1, launched through `porlaunch.sh`, each
answered its own greeting while the other ran, and a byte written at `$0340`
through 6520 was absent through 6521 — two machines, not two views of one.
Tearing down slot 0's process group left slot 1 answering.  Throughout, 6502
and 6510 were never bound and Donald's `vicerc` was byte-identical afterwards.

**A decoy `x64sc` the pool did not launch survived a full claim / launch /
teardown cycle**, which is the whole point of removing the four `pkill -x`
calls.

Three things the plan had wrong, found by building it:

1. **§3.4's reap table killed on the wrong condition.** It kills only on the two
   rows where the port answers.  But `porlaunch.sh` now passes
   `--die-with-parent`, so a crashed holder's *VICE* dies with it and the port
   falls silent — while the `Xvfb` or `Xephyr` it started has no such link and
   survives.  Under the table as written nothing ever collected it.  The port
   decides which row this is; the **lease** decides whether anything may be
   killed, and a free flock has already decided.  `_reap_held` therefore kills
   the recorded pgid on every row.
2. **`--die-with-parent` makes the orphan row rare**, which is a good outcome
   and not the one §3.4 expected.  It still happens — an emulator started
   outside the pool, or one whose parent `exec`d away — so the row stays, and it
   is proven on a real process.
3. **A reaped slot can still be unusable.** If the lease named no pgid, or the
   kill did not take, the port stays bound.  `claim()` steps over such a slot
   rather than launching into a port that is already in use — emphatically
   rather than going hunting for the process by name.

Still not done, because they are other agents' files: `wish/backends.py`'s
`setup_hint` and `automap/__main__.py`'s two message lines still name `6502` as
a literal.  They are strings in a message, not a probe, so nothing misbehaves —
but they will tell a pooled user the wrong port.

---

## 1. What is already there

Checked 2026-08-21, in this tree.

| claim | where | state |
|---|---|---|
| The monitor client takes a host and a port | `automap/vice.py:64` — `Monitor(host=MON_HOST, port=MON_PORT)` | already parameterised |
| `ViceTarget` passes them through | `automap/target.py:213` | already parameterised |
| "Which backend, where" is data | `wish/backends.py` — `Backend(probe=…, connect=…)` | already data |
| The launcher takes a display | `tools/porlaunch.sh` — `POR_DISPLAY`, default `:7` | already parameterised |
| The launcher takes monitor flags | `tools/porlaunch.sh` — `$MONFLAGS` | already parameterised |
| Everything is copied into `work/` before booting | `tools/session.py:113` asserts `path.startswith(HERE)` | already the practice |
| An env var is the project's idiom for "where is the thing" | `wish/ultimate.py:55`, `automap/paths.py:71` | pattern to copy |

**So the premise holds: what is missing is an override and a harness, not an
architecture.** Three things I found that the premise did not mention, and two
of them are the actual work:

1. **`monitor_listening()` and `who_holds_hint()` hard-code `6502`**
   (`automap/target.py:146`, `:187`) instead of importing `MON_PORT`. Harmless
   today because the values agree; the moment a port is overridable it means
   the probe tests one port and the connect uses another. Latent bug, two
   lines.
2. **The harness is actively hostile to parallelism.** `tools/session.py`
   lines 69–70 and 105–106, and `tools/porlaunch.sh` lines 8–9, run
   `pkill -x x64sc` and `pkill -x Xephyr` on **every launch and every close**.
   Under a pool that is not a bug, it is a massacre: one agent starting a run
   kills every other agent's emulator and Donald's game with it. This is the
   same failure mode as the incident behind the current `CLAUDE.md` rule,
   generalised. Removing those four calls is the single most important change
   in this plan.
3. **`SaveResourcesOnExit=1`.** `~/.var/app/net.sf.VICE/config/vice/vicerc`
   was last rewritten at 01:19 today and currently records
   `BinaryMonitorServerAddress="127.0.0.1:6502"` and
   `FliplistName=".../work/curse.vfl"`. Parallel instances would race that
   file, and the last one to exit would leave Donald's own configuration
   pointing at whatever port it happened to use. Per-instance config is
   mandatory, exactly as the premise said, and now with the byte to prove it.

---

## 2. The four things an instance owns

| # | resource | why per-instance | how |
|---|---|---|---|
| 1 | binary-monitor port | VICE serves **one** connection per process | `-binarymonitoraddress`, already a launch flag |
| 2 | text-monitor port | `tools/session.py` needs it for `attach`; one connection per run | `-remotemonitoraddress`, already a launch flag |
| 3 | command-server port | `tools/session.py:509 serve()` binds `CMD_PORT` | module constant → instance attribute |
| 4 | X display | `xdotool` XTEST goes to a display, not a window | `POR_DISPLAY`, already a launch flag |
| 5 | disk copies | the game **writes** to the disks it is given | `HERE` → `work/inst/<n>/` |
| 6 | `vicerc` | rewritten on exit; instances would race it | `-config <file>` |

`Slot.env()` is the whole interface: `POR_SLOT`, `POR_DISPLAY`, `POR_VICERC`,
`POR_MONITOR` and `MONFLAGS`, which `porlaunch.sh` reads and passes on.
`POR_HEADLESS=1` swaps `Xephyr` for `Xvfb`, which is what keeps eight game
windows off Donald's desktop.

Six, not four, because the text monitor and the command server are ports too
and neither is currently parameterised.

### The `vicerc` per instance

`x64sc` 3.10 carries `-config <filename>` "Specify config file", and it does
what it says: **CONFIRMED** 2026-08-22 by launching with `-config` and no
monitor flags and watching VICE bind the file's two monitor addresses.

Each slot gets `work/inst/<n>/vicerc`, **seeded by copying Donald's** and then
overriding four lines. Copying rather than writing from scratch is not
laziness: his rc carries

```
KernalName=".../JiffyDOS_C64_6.01.bin"
DosName1541ii=".../JiffyDOS_1541-II_6.00.bin"
```

and `Session.boot()` answers the fastloader prompt `Y` unconditionally
(`tools/session.py:300`). A stock kernal makes `Y` the wrong answer and the
symptom looks like a corrupt disk image — the trap
[`00-overview.md`](00-overview.md) records under "How a session runs".

The overrides:

```
SaveResourcesOnExit=0                      # instances never write settings back
BinaryMonitorServerAddress="127.0.0.1:<binary port>"
MonitorServerAddress="127.0.0.1:<text port>"
FliplistName=""                            # the pool attaches by path, not fliplist
```

The flatpak grants `filesystems=home` (`flatpak info --show-permissions
net.sf.VICE`), so a config under `/home/donald/src/wish/work/` is visible
inside the sandbox. `shared=network` is already granted too, so the
`--share=network` gotcha in the launch wrapper is history.

**Donald's own `~/.var/app/net.sf.VICE/config/vice/vicerc` is never opened for
writing by anything in this plan.** It is read once per slot creation, as a
template.

---

## 3. The pool

### 3.1 Port scheme — and why slot 0 is not 6502

| slot | binary | text | command | display | work dir |
|---|---|---|---|---|---|
| — | **6502** | **6510** | 6600 | `:7` | `work/drive/` |
| 0 | 6520 | 6540 | 6560 | `:10` | `work/inst/0/` |
| 1 | 6521 | 6541 | 6561 | `:11` | `work/inst/1/` |
| … | … | … | … | … | … |
| 7 | 6527 | 6547 | 6567 | `:17` | `work/inst/7/` |

**6502 and 6510 stay exactly what they are today and the pool never allocates
them.** That is the point of moving the pool off the legacy numbers: after this
change, *anything on 6502 is a human's game*, launched by
`~/.local/bin/pool-of-radiance` from the desktop menu. It restores the property
that made the old `ss -tnp | grep 6502` rule work, instead of destroying it.

### 3.2 Claiming and releasing

A new module, `tools/instance.py`.

```
slot = instance.claim(game="por")     # raises PoolFull if every slot is leased
slot.port, slot.text_port, slot.cmd_port, slot.display, slot.dir, slot.vicerc
slot.seed_vicerc(); instance.copy_disks(slot, [...])
Session(disk, slot=slot).launch()     # records the pgid in the lease
slot.release()                        # or just exit
```

`tools/instance.py status` prints every slot and which row of §3.4 it is on;
`tools/instance.py reap [n]` frees the ones that are nobody's;
`python3 tools/session.py --pool` claims a slot and serves on its command port.

**The lease is an `fcntl.flock` on `work/inst/<n>/lease`, held by the claiming
process.** Allocation is: try `LOCK_EX | LOCK_NB` on each slot in turn, first
success wins. The file's contents are informational JSON — slot, pid, game,
agent name, launch time, the x64sc pid once known.

The kernel releases a `flock` when the holding process dies, however it dies.
That is the whole reason to use one: **a crashed agent frees its slot with no
cleanup script, no timestamp heuristic and no stale-lock policy.** For a
long-running driven session the holder is the `tools/session.py serve` process
that already exists; for a one-shot `walkrun.py` it is the run itself.

### 3.3 Launching, and killing only your own

`porlaunch.sh` loses its two `pkill` lines and gains `--die-with-parent`
(`flatpak run -p`, present in this flatpak). Combined with the
`start_new_session=True` that `tools/session.py:74` already passes, teardown
becomes `os.killpg(pgid, SIGTERM)` on the group this slot started — Xephyr and
x64sc together, nothing else on the machine.

**No code in the pool may ever kill a process by name.** Not `pkill -x x64sc`,
not `pkill -f vice`, not `pkill -x Xephyr`.

### 3.4 Detecting and reclaiming a wedged instance

The two known ways an instance wedges:

| symptom | cause | recovery |
|---|---|---|
| monitor accepts the connection and never answers the greeting | another client attached, **or** a checkpoint was left armed when a socket closed — VICE re-enters the monitor on a connection that no longer exists | only a kill |
| monitor refuses the connection but the pid is alive | X gone, or VICE crashed into a dialog | kill |

`ViceTarget` already separates these: `NotConnected` on a failed connect,
`MonitorBusy` on a greeting that times out inside `GREETING = 1.0`. It cannot
tell "somebody else is attached" from "frozen" — from the socket the two are
identical, and `automap/target.py` says so in its own docstring.

**The lease is what tells them apart, and this is the rule that replaces
`ss -tnp | grep 6502`:**

| lease flock | port answers | greeting | conclusion |
|---|---|---|---|
| held | — | — | somebody's. **Do not touch it, ever.** |
| free | no | — | slot is clean; claim it |
| free | yes | yes | orphan — a healthy VICE nobody owns. Kill the pid in the lease file, then claim |
| free | yes | no | wreckage — frozen or half-attached. Same: kill the recorded pid |

`instance.reap()` does exactly that table, and it kills **the pgid recorded in
that slot's lease file** and nothing else. A slot whose flock is held is
somebody's however dead it looks; that is the whole discipline in one line.

**Corrected when built:** the port decides which row this is, but it must not
decide whether to kill. `--die-with-parent` means a crashed holder's VICE dies
with it and the port falls silent, while the `Xvfb` it started survives — so the
`clean` row has to kill the recorded pgid too, or nothing ever collects the X
server. A free flock is the only permission needed, and it is the only one used.

### 3.5 The code change

Small, as the premise claimed. Six existing files, one new one.

| file | change | size |
|---|---|---|
| `automap/vice.py` | `MON_HOST`/`MON_PORT` read once from `$POR_MONITOR` (`host:port`), defaulting to today's values — the `wish/ultimate.py:_env()` pattern | ~10 lines |
| `automap/target.py` | `monitor_listening()` and `who_holds_hint()` default from `MON_HOST`/`MON_PORT` instead of the literal `6502` | 3 lines |
| `wish/backends.py` | the `setup_hint` string interpolates the port | 1 line — **not done**, another agent's file |
| `automap/__main__.py` | two message lines, same | 2 lines — **not done**, same |
| `tools/session.py` | `HERE`, `TEXT_PORT`, `CMD_PORT`, `display`, `MONFLAGS` become instance attributes taken from a slot; the four `pkill` calls become a process-group kill | ~35 lines changed |
| `tools/porlaunch.sh` | drop the two `pkill` lines; take `POR_SLOT`; pass `-config` and `--die-with-parent` | ~8 lines |
| `tools/instance.py` | **new** — claim, release, reap, seed a `vicerc`, and a `main()` so a shell script can claim a slot too | ~150 lines |
| `tests/test_instance.py` | **new** — allocation, contention, reap's table, `vicerc` seeding. All of it is files and flocks, so none of it needs VICE | 26 tests |

Roughly **270 new lines and 50 changed**, and nothing in `goldbox/`, `editor/`,
`ui/` or `designer/` is touched. `wish/backends.py` needs no structural change
at all: `Backend.connect=ViceTarget` picks up the new default because
`ViceTarget` already forwards `port=None` to `Monitor`'s default.

**Deliberately not in scope:** a GUI port picker. `POR_MONITOR=127.0.0.1:6523
wish --tab map` is the whole interface, and it matches how `POR_DISKS`,
`POR_ULTIMATE` and `WISH_DEBUG` already work.

---

## 4. What it costs and what it buys

### 4.1 The ceiling is memory, and it is not close

Measured on this machine, 2026-08-21, against the instance running at the time:

| process | RSS |
|---|---|
| `x64sc` | 175 MB |
| `Xephyr` | 80 MB |
| **one instance** | **~255 MB** |

With 7.9 GB available, eight instances is about 2.0 GB. Twelve cores against
eight essentially-single-threaded emulators at `-speed 100` leaves headroom.
Disk I/O is 175 KB per D64 copy. **Nothing here is a reason to stop at fewer
than eight**, and the real limit is agent attention, not the box.

Headless (`Xvfb` instead of `Xephyr`) saves the 80 MB and, more usefully, keeps
eight game windows off Donald's desktop. XTEST works the same on either. Not
required for the first version; worth doing before the count goes past three.

### 4.2 The saving is across tasks, never within one

The per-step costs are unchanged by any of this, and they dominate:

| operation | cost | source |
|---|---|---|
| an area change | ~25 s | `50-experiments.md`, "There is no training-hall wedge" |
| a save-game cycle | ~22 s of settle | `tools/session.py:426-432` |
| a fasttravel, budgeted | 30 s | [`118-debug-mode.md`](118-debug-mode.md) §4 |
| a monitor resume | 14.3 ms | `70-driving-the-game.md` |

A 200-step walk run is about 83 minutes on one instance and about 83 minutes on
eight. **Parallelism here is `sum(tasks)` becoming `max(tasks)`, and nothing
else.**

### 4.3 The queue, and what it would actually save

The live-session work currently waiting, by which game has to be booted:

| task | doc | game | can share an instance with |
|---|---|---|---|
| FastTravel: is `$2034` safe to enter? (+6 more) | 118 §"Open questions" | PoR | the other PoR rows |
| `ResidentGeo` against all 29 maps | 118 §5 | PoR | ” |
| `Fingerprint.refused()`, first ever call | 118 §5 | PoR | ” |
| Overland map W1, the first step onto the travel grid | 113 | PoR | ” |
| Release testing L7 + M1–M6 | 122 | PoR | ” |
| Curse tier 3 — live addresses | 120 | **Curse** | tiers 4, 5.2 |
| Curse tier 4 — automapper | 120 | **Curse** | after tier 3 |
| Curse tier 5.2 — an edited field in game | 120 | **Curse** | ” |
| Silver Blades phases 3–5 | 121 | **Silver Blades** | each other — but blocked on a save disk the game wrote |

**Three games, therefore three instances, and that is the honest first number.**
Not eight. The PoR column is a queue of six that has to run in some order
anyway; splitting it across instances helps only once each item has its own
agent, and each agent costs a brief and a context.

The concrete win: Curse tier 3 and the PoR fasttravel experiments are genuinely
independent, need different disks in the drive, and today one of them waits for
the other to finish and tear down. Two instances turns two half-days into one.
Silver Blades makes it three the day its save disk exists. **PROBABLE** that
this is two to three hours of wall clock per working day, which is a real
saving and is not the tenfold one the word "parallel" suggests.

### 4.4 What it costs that is not code

* **Three agents driving three emulators is three briefs**, and the briefs are
  the expensive part.
* **A wedged instance is now a diagnosis rather than an observation.** With one
  instance, "the game is frozen" is the whole report. With three, the report has
  to name a slot, and an agent that names the wrong one kills the wrong game.
  §3.4 exists for that and it is the part most likely to be got wrong under
  pressure.
* **Screenshots and logs need slot-stamping**, or `work/drive/` becomes a pile
  of `boot-check.png` written by three agents. `work/inst/<n>/` fixes it by
  construction, which is why the disk copies move too.

---

## 5. The safety rules that replace the current one

`CLAUDE.md` today says at most one agent drives the emulator, that the agent
checks `ss -tnp | grep 6502` first, and that it never kills a process holding
the monitor. Under a pool the first is wrong, the second is no longer a complete
question, and the third is the one that must survive and get sharper.

**Recommended replacement for the "Emulator work is single-threaded" paragraph.
Reported here, not applied — three other agents are in this tree.**

> **Emulator work goes through the instance pool.** VICE serves exactly one
> binary-monitor connection *per process*, so running two things at once means
> two emulators, not two connections. Claim a slot with
> `tools/instance.py claim`; it hands back a port, a display, a work directory
> and a `vicerc`, and it holds the lease for as long as your process lives.
> Say in the brief which slot the agent has.
>
> **Port 6502 is Donald's.** The pool allocates 6520 and upwards and never
> touches 6502 or 6510. Anything on those is a game a human started from the
> desktop menu — do not attach to it, do not probe it, do not kill it.
>
> **Never kill a process by name.** Not `pkill -x x64sc`, not `pkill -x
> Xephyr`. Kill only the process group your own slot launched, and reclaim
> another slot only when `tools/instance.py reap` says its lease is unheld. A
> slot whose lease is held is somebody's, however dead it looks. The one time
> this rule was broken, what died was Donald's own window.
>
> **The pool owns the lifecycle.** Allocate, launch, tear down. Do not attach
> to an emulator you did not launch, and do not launch one outside the pool —
> an instance nobody leased cannot be told from a human's.
>
> **Never point VICE at Donald's config.** Every pooled instance gets its own
> `vicerc` seeded from his; `SaveResourcesOnExit=0` in every one of them, so
> nothing the pool runs can write settings back.

The existing lines about copying disks into `work/`, never writing to
`/home/donald/c64/Pool of Radiance Disks/`, and never committing game data are
unaffected and stay exactly as they are.

### Two things stay serial whatever the pool does

Neither is about the emulator, and no number of instances helps:

* **Differential experiments.** "Change exactly one thing, then diff" *is* the
  method. Two experiments running at once destroy the attribution that makes
  either result mean anything, however many emulators they have.
* **`goldbox/layout.py` has exactly one owner at a time.** It is the single source
  of truth for every field offset, and it asserts that all 580 bytes are
  accounted for; several agents appending to it independently fragment the
  schema and reintroduce the drift the table exists to prevent.

---

## 6. The Windows VM

**Donald has ruled against it, and the reasoning is sound.** Finding a Windows
ISO and standing the thing up costs more than the problem is worth when he has
a Windows laptop on the desk: he will run `122-release-testing.md` on it
himself. **Proxmox is retired for now** -- the fallback if running many VICE and
DOSBox processes on one host turns out to be unworkable, not the plan of
record. The rest of this section is kept as the argument for why, should that
day come.

The one thing that does *not* go away with the VM is the CI gap in §6.3: the
`AttachConsole` path has never run anywhere, on any machine, because
`release.yml` tests `--version` through a pipe. His laptop closes that, once.

**What it would have been for:** cutting the first release tag. Nothing else in
this document.

[`122-release-testing.md`](122-release-testing.md) ends with a table of
thirteen unverified claims. Every one of them is unverified for the same
reason — "nobody on the project has a Windows machine" — and they gate the
walkthrough that gates the tag.

**What CI already covers, and what it does not.** This is worth separating
before provisioning anything, because some of that list is cheaper than a VM:

| claim | already covered? |
|---|---|
| `wish.exe --version` prints the version | **partly.** `release.yml:82-90` asserts it on `windows-latest` — but under `shell: bash`, through a **pipe**. That exercises the *inherited-handle* link of `packaging/wish_main.py`'s chain and only that link |
| `AttachConsole(ATTACH_PARENT_PROCESS)` in a real cmd or PowerShell window | **no.** Never exercised anywhere. This is P29's actual claim and CI cannot reach it |
| the suite passes on Windows | **yes** — `test.yml` matrix includes `windows-latest` |
| the zip contains no `wish-cli.exe` | trivially CI-assertable; currently is not |
| SmartScreen's exact wording | **no**, and unreachable from CI — needs a desktop and a mark-of-the-web download |
| Defender quarantining the PyInstaller build | **no**, same |
| `%APPDATA%\vice\vice.ini` existing only after a first run | **no** — needs VICE installed and run interactively |
| double-click from Explorer swallowing every message | **no** — needs Explorer |
| the frozen zip on a machine with no Python | **no** — a CI runner has Python |

**So the VM's job is the interactive residue**, and it is a real job: roughly
half that table cannot be automated at any price. Two rows are worth a CI
ticket instead of a VM (the zip's contents; a `cmd /c` invocation of
`--version` alongside the piped one).

**What it would run:** Windows 11, no Python, no VICE, no game files at the
start — that emptiness *is* the test in `122` §5. Then VICE 3.10's Windows
GTK3 zip, the release `.zip`, and the game disks copied over.

**What makes a VM better than a spare laptop here:** snapshots. SmartScreen
warns *once*; Defender quarantines *once*; `vice.ini` does not exist *once*.
A "never seen this executable" snapshot turns each of those from a one-shot
observation into a repeatable check, and every future release re-runs it.

**What it is not for:**

* not for DOSBox — see §7;
* not for parallel VICE — a Windows VICE instance is one more instance and a
  much more expensive one;
* not for running the test suite — `test.yml` does that already, free.

---

## 7. DOSBox

**DOSBox does not need Windows.** It runs natively on Linux, and there is no
step below where a hypervisor helps.

What it needs, in order. **Steps 0, 1 and 3 have all landed since this was
written, and step 0 was the whole thing:**

| # | step | state |
|---|---|---|
| 0 | **A DOS copy of Pool of Radiance.** | **Found.** Donald's Steam *Forgotten Realms: The Archives*, unpacked read-only at `/home/donald/Downloads/fr-archives/` — the DOS game, plus the shipped pre-generated parties for six DOS Gold Box titles |
| 1 | A DOS save of a known party | **Found**, in the same tree: a real played DOS Pool of Radiance party in three slots (`A`, `B`, `J`), `A` and `B` being the same party at two moments. 24 specimens in all |
| 2 | `dosbox-staging` installed | still not installed here. One package. Recommending, not provisioning |
| 3 | Check the community record layout against a real file | **Done.** `work/reports/dos-saves.md`: **every prediction in `117` survived**, the record is 285 bytes, and the money block, spellbook, per-class array and class bitmask are all CONFIRMED against 24 specimens |
| 4 | `goldbox/dos_layout.py`, declarative, confidence per field | `117` order of work, step 2 |
| 5 | Stand on a known square in both ports, read `$4BC2` / `$49C0` and the DOS equivalents | `117` obstacle 2 — and this one really does want DOSBox |
| 6 | Item and spell numbering agreement | `117` obstacle 3. Partly answered statically: `ITEMS` is **126 of 128 records byte-identical** between the two ports, and spell ids 1–56 match — but DOS continues to 67 with item-invoked effects where the C64 continues with combat message fragments, so a DOS memorised-spell byte in 57–67 has no C64 id |

**Nothing in that list is unblocked by hardware**, and the file it was blocked
on has arrived. Only steps 4 and 5 are left, and only 5 wants a running DOSBox.

### The Amiga stand-in: where it is safe and where it is not

Another agent is working `work/amiga/` right now — the two `[cr SKR]` ADFs are
unpacked and `hunk10.asm`, `dax.py`, `ecl/` are today's files. `117` obstacle 1
proposes exactly this: the Amiga port is DOS-lineage (`ecl.dax`, `geo.dax`,
`DAxF` containers) so its scripts can be read to find the quest-flag base *by
shape*.

That is sound, and **it turned out better than this table expected.** Two rows
below were written as hard "no" and both have been refuted; they are kept as
written because the correction is the point.

| use of the Amiga rips | safe? | why |
|---|---|---|
| Which files exist, and the container scheme (`DAxF`, `POOLDATA`) | **yes** | shared lineage; this is what obstacle 1 wants |
| The *shape* of a structure — a 26-entry ledger, ten increment sites, an eight-entry lock table | **yes** | shape is portable; that is the whole fingerprint argument |
| Script semantics: which event sets which flag | **yes, and better than PROBABLE** | not "the same designers' data, recompiled" — **the same artefact.** The Amiga `ecl.dax` unpacks to the C64's own scripts, `$1388` load address and all |
| ~~**Any absolute address** — no~~ | **yes, inside the ECL bytecode** | **The ECL bytecode is one artefact shared by every port, absolute operands included.** 171 of the 172 referenced flag addresses appear unchanged in both ports, and DOS and C64 *Curse* differ only in a script's 2-byte header. The rule still holds for *engine* addresses — 68000 code, different loader, different bases — but a flag address named by a script is portable |
| **Byte order of any multi-byte field** | **no** | the Amiga is **big-endian**. `117` says "both little-endian, so multi-byte fields need no swapping" — that is true of DOS and C64 and false of the Amiga. A word read off an ADF says nothing about the DOS word |
| ~~**Record field offsets** — no~~ | **partly** | the Amiga record is **DOS-ordered**, so the DOS offset table does describe its field *sequence*. It is still big-endian, so no multi-byte value transfers. See [`124-amiga-port.md`](124-amiga-port.md) |
| Code-derived findings from disk 1 | **with care** | both rips are cracked (`[cr SKR]`). The loader is modified; the data files are presumably intact but that is an assumption, not a check |

The one-line rule, amended: **structure and script addresses transfer from the
Amiga; bytes and engine addresses do not.**

FS-UAE 3.1.66 is installed as a flatpak, so an Amiga *runtime* is available if
the static route stalls. It would be a second family of pooled instances and
everything in §3 applies unchanged — different launcher, same lease.

---

## 8. Where Proxmox fits

Taking it seriously, because it was asked seriously.

| use | verdict | reasoning |
|---|---|---|
| A VM per VICE instance | **no** | The limit is per process. A VM adds a kernel — call it 1–2 GB against the 255 MB an instance actually costs — to buy isolation the pool's leases already provide. It makes the memory ceiling strictly worse |
| Isolating a wedged instance's `pkill` | **no, once the pkill is gone** | This is the best argument for VMs and §3.3 removes the thing it defends against. Do not buy a hypervisor to contain a four-line bug |
| Hosting the Windows VM | **yes, if the hardware exists** | The snapshot argument in §6 is real and recurring: every release wants a machine that has never seen the executable. Proxmox does that better than anything else on the list |
| Running while Donald uses the desktop | **not the cheapest fix** | The complaint is eight Xephyr windows and audio. `Xvfb` plus `-sounddev dummy` solves it for the cost of one flag |
| Surviving a logout or a reboot | **not the cheapest fix** | `systemd-run --user --scope` or tmux; a VM is a large answer to a small question |
| Getting the load off his desktop entirely | **yes, if it is another box** | Twelve cores shared with Firefox, VS Code and this session is the actual contention. That is an argument about *whose machine*, not about virtualisation |

**What would change the answer for the VICE side:** a second physical machine.
If the pool ran somewhere that is not Donald's desktop, then `POR_MONITOR` taking
a *host* as well as a port — which it already does, `Monitor(host=…)` has always
been parameterised — makes the pool remote with no further code. That is the
one design decision worth taking now: **keep the host in the override, not just
the port**, so a move to another box is configuration rather than a rewrite.

Nothing here needs Proxmox installed on *this* machine, and this box has no
`qemu-system-x86_64`, no `virsh` and no `libvirt` today. Recommending, not
provisioning.

---

## 9. Verification

### 9.1 The harness works when all of these hold

None of the first four need a second instance, so they can be checked in an
ordinary session.

All eight passed on 2026-08-22.

| # | check | result |
|---|---|---|
| 1 | `pytest tests/ -q` still passes | green; 2 skipped |
| 2 | `tests/test_instance.py` passes with no emulator | 26 tests, ~5 s |
| 3 | `POR_MONITOR=127.0.0.1:6523` makes `monitor_listening()` probe 6523 | yes — and it is resolved *per call*, not at import, so a running window can be repointed |
| 4 | A seeded `vicerc` still carries the JiffyDOS kernal paths | yes; the diff against the template is exactly six lines |
| 5 | Donald's `vicerc` is byte-identical after a pooled run | yes, md5 unchanged across every run here. **The most important single check in the list** |
| 6 | Two instances on 6520 and 6521 each answer their own greeting | yes, and a byte written through one was absent through the other |
| 7 | Killing slot 0's process group leaves slot 1 running | yes |
| 8 | `instance.reap()` refuses a slot whose flock is held | yes, from a second process |
| 9 | a decoy `x64sc` the pool did not launch survives a full cycle | yes — the check the whole task was for |

### 9.2 The first parallel run

**Two instances, two different games, and one of them a task that is finished
whatever happens.**

* **Slot 0, Pool of Radiance:** the release walkthrough's automapper section —
  `122` M1 through M6. It is short, it has a written pass criterion, it is
  needed for the tag anyway, and it exercises the whole stack: launch, disks,
  monitor, the GUI attaching over `POR_MONITOR`, teardown.
* **Slot 1, Curse of the Azure Bonds:** `120` tier 3 — find the live save base
  by searching RAM for a run out of a Curse save. It is `120`'s own recipe, it
  needs a different disk in the drive, and it is the item most obviously
  blocked today by the single-instance rule.

Run them **from two agents at once, deliberately**, because a pool that is only
ever used by one agent has not been tested. The run passes if both tasks
produce their artefact, check 5 holds afterwards, and neither agent's log
mentions the other's slot.

Then, and only then, add a third for Silver Blades — which will still be
blocked on a save disk the game wrote, and that is a dependency no amount of
parallelism touches.
