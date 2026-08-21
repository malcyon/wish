# A combat log — plan

**Status: planned, not started. Feasible, and probably the single most useful
thing left on the list.**

The game prints who hit whom for how much, and then paints over it. **How long
the text survives depends on the host's speed**, so on a fast emulator it can be
gone before it is read. The information is not saved anywhere; once it is
overwritten it is gone.

An automapper that watched for those lines and kept them would fix a real defect
in the game, not merely mirror it. And the Messages panel already exists.

---

## Is it possible?

**Yes, and the machinery is already here.** `automap/screen.py` reads the C64
screen, recomputing its address from `$D018`/`$DD00` every poll because it
moves. The combat view already polls while `$6E11` is 2.

So the loop is: poll the text region, decode screen codes to ASCII, and append
anything that is new.

**The one hard part is "anything that is new."** The screen is a rectangle that
gets overwritten, not a stream. Two lines in a row can be identical and both
real ("MAGNUS MISSES." twice). The approach that works:

* Poll fast enough that no message is missed. Combat is turn-based and messages
  persist for a beat; the current interval is a starting point, not an answer.
  **Measure it against the jiffy clock at `$A0`-`$A2`**, the technique
  `docs/70-driving-the-game.md` used to establish how much a poll stalls the
  game.
* Track the message region's contents; when it changes, diff against the last
  capture rather than against the whole history, and append the lines that
  scrolled in.
* Deduplicate only on *consecutive identical frames*, never on content, or the
  second "MAGNUS MISSES." is eaten.

## What has to be found first

1. **Where the message region is.** The screen is 40 x 25 at
   `$CC00`; combat prints its text in a band whose rows and height are not yet
   established. Find it by watching the screen while a fight runs.
2. **Whether it scrolls or overwrites.** Those need different diffing.
3. **Whether the game pauses for input** between messages, which would make the
   whole problem easier.

None of that needs disassembly — it is a fight and a screen capture per poll.

## What it should do

* Append to the **Messages panel**, tagged by round if the round is known
  (`$A380` reaching all-zero ends a round).
* **Keep the log after combat ends**, which is the entire point: the player
  wants to read what happened once the fight is over.
* Never invent structure. If a line cannot be parsed into attacker, target and
  damage, show it verbatim — a log of raw lines is still far better than what
  the game gives you.
* Parsing into structure (who dealt how much to whom, totals per character) is a
  second step, and worth doing only once raw capture is solid.

## Risks worth stating

* **Polling costs the game time.** Every read stops the machine briefly. A log
  that stutters the fight is worse than no log; this is why the interval must be
  measured rather than guessed.
* **Text mode is not guaranteed.** If the screen is a bitmap (`$D011` bit 5),
  there is nothing to read, and the reader must skip rather than capture noise.
* This is the first feature that would poll faster during combat than out of it.
  That is a real change to the session's rhythm and should be a setting.

## Verification

* A fight driven end to end produces a log whose lines match what the screen
  showed, in order, with nothing missed and nothing doubled.
* Two genuinely identical consecutive messages both appear.
* The log survives the end of combat and is still readable in the world.
* The measured stall with logging on is recorded in the docs, in jiffies.
