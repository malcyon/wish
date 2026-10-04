# The patches Wish applies to FS-UAE

Wish drives Amiga games in `grahambates/fs-uae`'s GDB-remote build. Two defects
in that build stop a driver from saving and loading a machine state, so Wish
patches the emulator in two ways:

- **Source patches**, which both fork build scripts apply before compiling.
- **Binary patches**, which `tools/amiga/installfsuae.py` writes into the
  binary that `uae-dap` 1.1.5 ships.

The binary needs patching because it is newer than any published source.
A build of the published branch tip, `remote_debugger_barto` at `b70b1180`,
has no `M` memory-write handler, so `poke` and Level up fail on it
([96-live-memory-automapper.md](96-live-memory-automapper.md), "What the fork
needs").

| Patch | What a driver sees without it | Source patch | Binary patch |
|---|---|---|---|
| NULL guard | the emulator segfaults on every state save, state load and reset | `tools/amiga/fsuae-inputcode-null.patch` | `installfsuae.NULL_GUARD` |
| Restore redraw | after a state load the picture stays black until the game draws each line again | `tools/amiga/fsuae-restore-redraw.patch` | `installfsuae.RESTORE_REDRAW` |

## The NULL guard

**Problem.** Every special input action is queued through
`inputdevice_add_inputcode(code, state, NULL)` (`src/inputdevice.cpp`); this
covers state save, state load and hard reset, whether picked from the F12
menu or sent by `--load_state`. The function stores `my_strdup(s)`. On Linux
`my_strdup` is `strdup` (`HAVE_STRDUP`, `src/include/sysdeps.h`), and
`strdup(NULL)` faults in glibc's `strlen` on the emulation thread. CONFIRMED:
three crashes, with a GDB client attached and without one, all at the same
libc instruction.

**Source patch.** In `inputdevice_add_inputcode`,
`inputcode_pending[i].s = my_strdup(s);` becomes
`inputcode_pending[i].s = s ? my_strdup(s) : NULL;`. Freeing a NULL entry
later is already safe.

**Binary patch.** In the shipped binary the `call strdup@plt` sits at the end
of the function at `0x56fe30`. The function is found by the
`"        inputcode %d state %d\n"` string it prints. Its third argument stays
in `r14`, and the call passes it unchecked. The call is pointed at a
13-byte wrapper written into the 14 bytes of alignment padding after the
function's `ret`.

| File offset | Address | Shipped bytes | Patched bytes | Instructions |
|---|---|---|---|---|
| `0x1700db` | `0x5700db` | `e8909fe9ff` | `e812000000` | `call strdup@plt` (`0x40a070`) → `call 0x5700f2` |
| `0x1700f2` | `0x5700f2` | `662e0f1f8400000000000f1f40` | `4885ff7405e9749fe9ff31c0c3` | padding → `test rdi,rdi; je +5; jmp strdup@plt; xor eax,eax; ret` |

- **Why it is safe:** a NULL argument returns NULL; anything else goes to
  `strdup` with the stack exactly as the original call left it.
- **Nothing else reaches the padding:** no instruction branches into it, and no
  4- or 8-byte value in the file points into it.

## The restore redraw

**Problem.** FS-UAE redraws only the display lines whose Amiga content changed
since the last frame. A state restore never marks the screen lost: the
fsemu video path's call to `notice_screen_contents_lost()` after posting a
frame is commented out (`src/od-fs/fsvideo.cpp`), and
`savestate_restore_finish()` (`src/savestate.cpp`) does not call it.

After a load the machine is restored exactly. Chip RAM is byte-identical to the
save, and the custom-chip state differs only in the refresh counter. The
picture, though, stays black until the game draws each line again, and some
lines stay stale even after a redraw (CONFIRMED, six of six loads). Neither
Alt+A nor pause brings it back.

**Source patch.** `notice_screen_contents_lost(0);` is added at the end of
`savestate_restore_finish()`, after `audio_activate();`. It sets
`frame_redraw_necessary`, which makes every line count as changed on the next
frames (`src/drawing.cpp`, `src/custom.cpp`). With it, the frame after a load
equals the pre-save frame pixel for pixel. CONFIRMED in one load on a source
build.

**Binary patch.** In the shipped binary:

- **`savestate_restore_finish()`** starts at `0x6b4f10`. It is found by its
  `puts("savestate_restore_finish")`, and its calls come in the source's order.
  The `call audio_activate` (`0x424d20`) is at `0x6b4f96`.
- **`notice_screen_contents_lost`** is at `0x4b44b0`: `movslq %edi,%rax;
  imul $0x1a8,%rax,%rax; movl $1,0x263c7f8(%rax); movl $2,0x263c800(%rax);
  ret`. It is matched by that body: the same struct stride (`0x1a8`) and the
  same field offsets (`adisplays+8`, `adisplays+0x10`) as the source build.
  These are the only direct references to those fields in either binary.

The `audio_activate` call is pointed at a 12-byte wrapper written into 15 bytes
of padding after a `ret` at `0x6b3440`.

| File offset | Address | Shipped bytes | Patched bytes | Instructions |
|---|---|---|---|---|
| `0x2b4f96` | `0x6b4f96` | `e885fdd6ff` | `e8a6e4ffff` | `call audio_activate` → `call 0x6b3441` |
| `0x2b3441` | `0x6b3441` | `662e0f1f8400000000000f1f` | `31ffe86810e0ffe9d318d7ff` | padding → `xor edi,edi; call 0x4b44b0; jmp 0x424d20` |

- **Why the stack is safe:** `notice_screen_contents_lost(0)` is a leaf that
  uses no stack, so calling it from the wrapper is harmless. The tail jump
  leaves `audio_activate` returning to `0x6b4f9b` exactly as before.
- **Order change:** the redraw request now comes before `audio_activate()`
  rather than after; neither reads what the other writes.
- **Nothing else reaches the padding:** no branch or stored pointer targets it.

**Measured on the patched binary.**

- **The picture comes back exactly.** The frame after a load equals the
  pre-save frame across the whole 754x576 Alt+S image (CONFIRMED, 22 loads in
  six boots, with a GDB client attached).
- **Some loads reboot the Amiga, on this binary only so far.** A soak of 20
  save-and-load cycles per binary was run: two boots of ten cycles each, a GDB
  client attached throughout, and a 512 KB chip-RAM read before every other
  save. On this binary 2 of 20 loads rebooted the Amiga into the Kickstart
  screen, and with the earlier runs it is 3 of 26. The NULL-guarded-only
  binary rebooted in 0 of 28 loads, all with the game still running after the
  load.
- **The reboots come from FS-UAE's CPU tracer.** All three reboots have the
  same cause (CONFIRMED, 3 of 3). The tracer restores the instruction the CPU
  was in when the state was saved. In every reboot that instruction was the
  `jsr` (`4EB9`) at `0x00fc9b18` in Kickstart. Playback fetched `0x00fced60`,
  which was not recorded, and the log says `CPU tracer invalid state during
  playback!`. The CPU then runs into `Illegal instruction 4e7b`, and the
  machine resets. In 23 other loads on this binary and 28 on the other, the
  tracer resumed elsewhere and the load worked.
- **Whether the redraw patch causes this is not known.** The tracer and the
  save path are code the patch does not touch. The patch could still change
  where the CPU stands when a later save is taken, because
  `custom_frame_redraw_necessary` also feeds the chipset's line decisions in
  `src/custom.cpp`. To settle it, save and load enough times on the
  NULL-guarded-only binary for a save to land on `0x00fc9b18`. If that binary
  then fails the same way, the fault is FS-UAE's and the patch only changes
  how often.
- **The picture comes back after every load that does not reboot.** Every
  one of the 17 such loads in the soak gave an Alt+S frame identical to the
  pre-save frame (CONFIRMED).
- **The binary exits cleanly on SIGTERM.** It ended with status 0 and no
  segfault in four of four boots, as the NULL-guarded-only binary did in four
  of four. The shutdown segfaults first recorded here came from the test script,
  which sent SIGTERM to the X server instead of the emulator. Ending the X
  server first makes the NULL-guarded-only binary segfault the same way (exit
  245; CONFIRMED, one boot), so they say nothing about either patch.
- **Nothing outside the call reaches the wrapper.** No unwind-table entry
  (`.eh_frame`) covers either patched padding range, and no initialiser or
  finaliser table entry points there.

## The SHA-256 chain

`installfsuae.REDRAW_CHAIN` lists the steps in order. Each step starts from
the digest the previous one ends at. The default install, `PATCH_CHAIN`, stops
after step 1: step 2 is opt-in with `--with-restore-redraw` because of the
reboots under "Measured on the patched binary", whose link to the patch is not
yet settled.

| Step | Binary | SHA-256 |
|---|---|---|
| 0 | `fs-uae-linux_x64` as `uae-dap` 1.1.5 ships it | `cee4e3c9f735168ce97e57fa846383fa8efcd718343ee53d212af2737e697d97` |
| 1 | + NULL guard | `3277775541ed8f65669b6beafc28dd647c4b0c030e845597b52ff1ffee29fe8b` |
| 2 | + restore redraw | `fbf6716089cac42bccd03eeede883d1184aa3eb00c9176aad568756eb484fbea` |

`patch_chain()` handles a binary at any step:

- **At an earlier step:** it checks the bytes at every remaining site, applies the
  remaining steps in memory, checks each result's digest and replaces the file
  by a rename. A running emulator keeps the file it started from.
- **At the last step of the chain it was given:** it does nothing. A default
  run on a binary at step 2 leaves it alone and says it holds the opt-in patch.
- **Anything else:** an unknown digest, or a site holding neither its shipped
  nor its patched bytes, stops the install with nothing written.

A fresh install patches the unpacked binary before it moves into place, to
step 1, or to step 2 with `--with-restore-redraw`.

## Verifying and rebuilding

- **Check an installed binary.** `sha256sum` it and compare with the table.
  `objdump -d --start-address=ADDR --stop-address=ADDR+N` on each address
  above shows the instructions listed.
- **Patch by hand.** `tools/amiga/installfsuae.py` run by default brings an
  installed binary to the NULL-guard step, and with `--with-restore-redraw` to
  the redraw step; a second run reports `Already installed`.
- **Build from source.** `tools/amiga/fsuaebuildcontainer.sh` (gcc) and
  `tools/amiga/fsuaebuildclang.sh` (clang) build `remote_debugger_barto` in a
  container, with the source at `/src` and the checkout's `tools/amiga` at
  `/patches`. Every `fsuae-*.patch` is applied before `./bootstrap`, a patch
  already present is skipped, and one that does not fit stops the build.
  `tests/amiga/test_fsuaebuild.py` runs that step against a tiny tree.
- **Build problems with gcc 13 on Ubuntu 24.04.** Two problems unrelated to
  the patches stop a gcc 13 build there:
  - `src/pcem/vid_voodoo_codegen_x86-64.h` does not compile (`'tmu' is not a
    constant expression`). Building the `vid_voodoo*.o` objects with
    `-U__amd64__` works around it; the Voodoo board is unused on an A500.
  - The default `./configure` links the built-in slirp without compiling it;
    `--disable-builtin-slirp` works around it.
- **A source build replaces only the patched code paths.** It has the published
  tip's older GDB server, so it cannot stand in for the shipped binary where a
  driver writes memory.
