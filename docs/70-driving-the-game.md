# Driving the game programmatically

Everything here was established the hard way. If you are automating Pool of
Radiance under VICE, read this before writing any input code.

## Run it in a nested X server

`tools/rungame.sh <experiment>` starts **Xephyr** and runs VICE inside it. This
is not cosmetic:

* Under Wayland there is no dependable way to give an XWayland window keyboard
  focus. `xdotool windowactivate` returns success, `xdotool getactivewindow`
  *and* `_NET_ACTIVE_WINDOW` both name the VICE window, and the keystrokes
  still do not arrive.
* It appears to work right after launch only because VICE grabs real focus
  then. It stops the moment focus moves — for instance when the window is
  dragged to another monitor.
* Worse, keys sent while VICE lacks focus land in **whatever window does have
  it**, potentially a terminal.

Inside Xephyr there is no window manager, so the single window holds input focus
permanently and XTEST always reaches it. `windowactivate` *errors* there — that
is expected and harmless; do not "fix" it.

**Both `DISPLAY` and `--env=DISPLAY` must be set** on the `flatpak run` line: the
outer one decides which X socket the sandbox is given, the `--env` one tells the
app which to connect to. Setting only `--env` silently puts the window on the
host display.

## Input timing — the single biggest source of lost time

The game polls the **CIA keyboard matrix** directly rather than using KERNAL
input. Consequences:

* Writing to the KERNAL keyboard buffer (`$0277`, count at `$C6`) does
  **nothing**.
* A press/release pair sent faster than the game's poll interval is missed
  entirely. `xdotool key` types `WYVERN` as `WRN`.

Send every key as **keydown, hold, keyup, gap**:

| context | hold | gap |
|---|---|---|
| menus (Up/Down/Return) | 0.10s | 0.14s |
| text entry generally | 0.15s | 0.28s |

When a screen has just changed, the first burst is often swallowed — the game is
not reading input yet. Verify by effect and retry rather than trusting a single
send.

## What does *not* work

| attempt | result |
|---|---|
| KERNAL buffer injection | game never reads it |
| `xdotool key --window <id>` | VICE ignores synthetic `XSendEvent` |
| `Alt+N` (fliplist next), plain or held | does not change the attached disk |
| `F10` | does not open the menu bar |
| synthetic mouse clicks on menus | do not register |

`Alt+N` genuinely *is* the right binding (VICE's own
`share/vice/hotkeys/hotkeys-fliplist.vhk` maps `fliplist-next-8` to `<Alt>n`).
The problem is that VICE's **GTK layer never sees synthetic modifiers or
clicks** — only the emulation canvas receives keys. So no disk swapping,
menu use, or hotkey beyond plain keypresses is available to automation.

**This blocks any experiment that needs the game to read a disk we constructed.**
Untried workarounds: build a boot disk that already carries the save files so no
swap is needed, or find a runtime attach route (the binary monitor has none).

## Reading the screen

The game runs in **text mode with its own character set**, so the screen is
readable as screen codes — no OCR, no image matching.

Compute the screen address from the VIC registers each time; it moves:

```python
d018 = peek(0xD018); dd00 = peek(0xDD00)
bank = (~dd00 & 3) * 0x4000
screen = bank + ((d018 >> 4) & 0xF) * 0x400      # $CC00 in-game, $0400 at boot
```

`$D011` bit 5 tells you whether the display is bitmap (title/credits) or text.
Bitmap screens cannot be read as text — use a screenshot.

**Menu selection is a colour, not a character.** The highlighted row is drawn in
white (colour 1), the rest green (colour 5). Colour RAM is always at `$D800`
regardless of VIC bank. `por`-side helpers read it to find the highlight, then
press Up/Down the right number of times and Return. That is far more robust than
counting rows.

## Screenshots

`import -window <id>` on the nested display takes ~0.25s. Going through the MCP's
`vice_screenshot` takes several seconds — enough to lose races against menus that
time out. Use `import` unless you need the MCP for another reason.

## The binary monitor

* **Connecting stops the machine.** Nothing advances while a socket is open.
  Use connect → read → **close**; closing resumes. Verified against the KERNAL
  jiffy clock at `$A0-$A2`, which advances at exactly real time between
  connections.
* Do **not** infer "stopped" from a constant `$D012`. Monitor reads with
  side-effects disabled do not return live VIC counter values.
* VICE interleaves **unsolicited events** into the stream (type `0x62` STOPPED,
  `rid=0xFFFFFFFF`). A client that reads one response per request silently
  desyncs and returns the *previous* request's data. Match responses by request
  id.
* `CHECKPOINT_SET` (`0x12`) answers with `CHECKPOINT_RESPONSE` (`0x11`), not
  with its own command type.
* **Always delete checkpoints when an experiment ends.** A stop-on-hit
  checkpoint left armed looks exactly like a hung game.
* Reading RAM under I/O (e.g. the charset at `$D000`) needs the `ram` bank —
  query `BANKS_AVAILABLE` (`0x82`); on this build `ram` is bank 1.

## Patching overlays

The game is heavily overlaid. An address holding the routine you patched is
**replaced wholesale** when another disk side loads. Patching the same address
blind a second time corrupted a live routine (`LDA #$01` → `NOP NOP`).

**Read and check the bytes before every write.**

## Snapshots

`DUMP` (`0x41`) / `UNDUMP` (`0x42`) over the binary monitor save and restore full
machine state. `work/E003-past-protection.vsf` is a snapshot taken at the
party-creation menu. Restoring proved unreliable in practice — the one attempt
left the machine at a fresh boot — so treat it as a convenience, not a
dependency.

## Character creation

Menus can be driven: **race → gender → roll stats → class → alignment → name**,
each a highlight-and-Return list. The class list offered depends on the race
(HUMAN offers only CLERIC / FIGHTER / MAGIC-USER / THIEF).

**Creation cannot currently be completed.** At the name prompt the name types
correctly — verified both on screen and in the input buffer at `$9700` — but
Return silently clears the field and re-prompts, and no record appears in
`$4D00`+. Ruled out: leftover patches, the disk in the drive, input timing, and
a hung CPU. Cause unknown. See [the two dead ends in driving VICE](50-experiments.md).

## Input buffer

Typed text lands at **`$9700`, in PETSCII** (`$C1` = `A`), not screen codes. It
is copied there when Return is pressed, so a memory scan taken *before* Return
will only find the text in screen RAM.
