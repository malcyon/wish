# Driving the game, and validating the automapper against it

## Reading is not driving

Worth separating, because conflating them makes the mapper look far harder to
run than it is.

**Reading** a running game needs one thing: the emulator started with its binary
monitor listening. Nothing else on this page applies.

**Driving** a game — sending keys — needs the whole apparatus below.

## Run it in a nested X server

Start Xephyr and run the emulator inside it. This is not cosmetic:

* Under Wayland there is no dependable way to give an XWayland window keyboard
  focus. `xdotool windowactivate` returns success, the window is named as active
  by two different mechanisms, and the keystrokes still do not arrive.
* It appears to work right after launch only because the emulator grabs real
  focus then. It stops the moment focus moves.
* Keys sent while the emulator lacks focus land in **whatever window does have
  it** — potentially the operator's terminal.

Inside Xephyr there is no window manager, so the single window holds focus
permanently and XTEST always reaches it. `windowactivate` *errors* there; that
is expected and harmless.

Both `DISPLAY` and the sandbox's own `--env=DISPLAY` must be set if the emulator
is containerised: the outer one decides which X socket the sandbox is given, the
inner one tells the app which to connect to.

## Input timing is the single biggest source of lost time

The game polls the **CIA keyboard matrix** directly rather than using KERNAL
input:

* writing to the KERNAL keyboard buffer does nothing *for the menus*;
* a press/release pair sent faster than the game's poll interval is missed
  entirely — `xdotool key` types `WYVERN` as `WRN`.

Send every key as **keydown, hold, keyup, gap**:

| Context | Hold | Gap |
|---|---|---|
| menus | 0.10 s | 0.14 s |
| text entry | 0.15 s | 0.28 s |

**When a screen has just changed, the first burst is often swallowed.** Verify
by effect and retry rather than trusting a single send.

**The KERNAL buffer does work at text prompts.** The game's key fetcher reads it,
so writing the buffer and its count delivers a keystroke — and it is the only
reliable way to submit some prompts and to send `Return` anywhere. Treat XTEST
as the default and the buffer as the escape hatch.

**Type names in lowercase.** The name prompt rejects any byte at or above `$5B`,
and `xdotool key W` arrives as Shift+w, i.e. `$D7`. Every capital fails the
compare and the prompt silently restarts — which looks exactly like "Return
clears the field and re-prompts". This one blocked automated character creation
for a long time.

## What does not work

| Attempt | Result |
|---|---|
| `xdotool key --window <id>` | synthetic `XSendEvent` is ignored |
| the fliplist hotkey, plain or held | does not change the attached disk |
| the menu-bar key | does not open the menu bar |
| synthetic mouse clicks on menus | do not register |
| a single self-contained boot disk | impossible; the game demands other sides early |
| a second binary-monitor connection | accepted at TCP level, never answered |
| closing the text-monitor connection | wedges the binary monitor too |
| connecting to the text monitor first | it answers only while the machine is already stopped |
| a helper that assumes one highlight colour | some command bars use another; it finds nothing and reports success |

The emulator's GTK layer never sees synthetic modifiers or clicks — only the
emulation canvas receives keys. That is why hotkeys fail while ordinary
keystrokes work.

## Disk swapping, through the text monitor

Both monitor servers can be enabled at once, and the **text** monitor has an
`attach` command. That is the whole disk-swap mechanism. Three rules, each
learned by wedging the emulator:

1. **Open the binary monitor first.** The text monitor answers only while the
   machine is stopped, which is what connecting the binary monitor does.
2. **Open the text socket once and never close it.** One such connection is
   served per run; closing it kills the binary monitor as well.
3. **Never send the resume command on the text socket.** Resuming is the binary
   monitor's job.

Constrain `attach` to a working directory of disk copies, so no script can
attach — and therefore write to — the player's own disks.

## Driving a session end to end

| Step | What to do |
|---|---|
| fastloader prompt | answer per the emulator's own fast-loading setup |
| credits | take the play option at once — **left alone the screen starts a demo by itself** |
| disk prompts | there are several wordings on more than one row: **match the text, not the row** |
| main menu | load the saved game |
| party menu | begin adventuring |
| in the world | the status line carries facing, clock, x, y |
| movement | forward, turn left, turn right, and one key that steps *backward* without turning |
| saving | encamp → save, which writes to whatever disk is in the drive |

**Nothing here can be taken on trust.** The command bar is not always redrawn,
so finding a label on it is no evidence that the option was selected. Verify
every action by effect.

**Do not conclude "wedged" because a row lacks the label you wanted.** A
long-standing claim in this project that one square wedged the game was wrong
four times over: the square triggered an ordinary encounter, the load took ~25
seconds against a 5-second timeout, the status line legitimately keeps showing
the old square until the encounter resolves, and the key reader in that context
correctly discards movement keys. Sampling the program counter showed the
ordinary key-wait loop the whole time. Match the prompts that *are* on screen and
answer them.

## The walk corpus

Script a route in the game's own movement letters and record, for every step,
the square before and the square after. **A forward step whose square did not
change is a wall** — that is the whole point of the corpus.

Write one save disk per step plus a manifest naming the intended route, the
base save, whether the run completed, and per step: the move, before, after,
whether it was blocked, and the position read back out of the save that step
wrote. Take a screenshot on failure, and tear everything down — checkpoints
included — in a `finally`. An armed checkpoint or a stranded Xephyr looks
exactly like a hung game to whoever runs this next.

**A bump advances the clock**, so "the clock changed" is not evidence of
movement. The map fact is the square.

## What the automapper validation asserts

This is the test that catches "live data is not where we thought". A mapper
reading the wrong address does not error; it draws a party walking through walls.

Walk a known route in a known area and assert, at every step:

1. **Position and facing agree three ways** — the mapper's fix, the game's own
   status line, and the position bytes read back out of the save disk that step
   wrote. A mismatch between memory and disk is logged loudly rather than
   averaged away.
2. **Every square the party occupies is walkable** in the decoded map.
3. **Every completed step crossed a passable edge** in the decoded map.
4. **Every refused step corresponds to an impassable edge.** The strongest
   single observation available: impassable edges are rare, so **one refusal
   identifies the map** where positive evidence alone needs 111 steps.
5. **Area identification switches when the party crosses a boundary.** Build the
   boundary pair deliberately — one step through a doorway, a save either side —
   and assert the mapper's area changes on exactly that step, to the file that
   the independent map-matching identified for that area.

### Detecting a refused step without seeing key presses

The mapper cannot see the keyboard, and it does not need to. The status line
carries the clock, so **clock advanced by exactly one minute + square unchanged
+ facing unchanged** is a step the game refused.

Guard it three ways or it fires wrongly:

* both fixes must come from the **status line**, because the memory copy lags a
  move and a *successful* step read from memory looks identical to a refused one;
* the clock must have advanced by **exactly one minute** — longer is searching or
  camping, zero is standing still;
* the facing must not have changed.

Whether a bump costs a minute at all is worth confirming on each new title; if
it costs nothing this never fires, and if bashing a locked door costs a minute it
records a false blocked edge.

### Contradictions are counted, not obeyed

An observation that eliminates every candidate map is **not** evidence about
which map this is — it is evidence that the observation was wrong. A garbled
status line, a step across an area boundary, or a false refusal all produce one,
and obeying it throws away the true map for good.

Keep the last non-empty candidate set and count the contradiction. **A rising
contradiction count is the signal that an address is wrong**, and it is strictly
more informative than "0 candidates".

## Testing without an emulator

Everything above is developed and regression-tested offline:

* a **replay target** that walks a fixed list of fixes, so the model and the
  window can be exercised with no emulator;
* a **memory target** over a dictionary of `{address: bytes}`, which is enough
  to exercise the party fix, the screen decoder and the resident-map search,
  because those take `read` as a plain callable;
* a **synthetic map** generated from the documented format, for tests that need
  *a* well-formed file rather than a specific one.

Only the final validation needs a live machine. Everything else should fail in
CI, on a machine that has never seen the game.
