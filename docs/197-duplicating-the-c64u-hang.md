# Duplicating the C64 Ultimate hang

Reading the C64's memory over the Ultimate's REST interface **stops the 6510**.
If that stop lands inside a disk load, the load never finishes and the machine
hangs with interrupts off, needing a reset.

This page is how to make that happen on purpose, by hand, in a few minutes. It
exists so the fault can be shown to somebody else — an upstream maintainer, or
a second person with the hardware — without any of this project's code.

Measured on Donald's unit, **firmware 3.14**, 2026-09-07.
`#375 (Wish has to work around the Ultimate freezing the C64 mid-load, which
hangs the game while the automapper follows along)` is the ticket;
`#286 (Pool of Radiance on the C64 Ultimate sometimes hangs on a disk load)`
is how it was found and closes with the analysis.


## 1. The short version

**Two things have to be true at once: the drive is working, and something is
reading memory over the network.** That is the whole fault.

1. Start any disk activity on the Ultimate — load a game, load a file, it does
   not matter what.
2. While it loads, run this on another machine:

   ```sh
   while true; do
     curl -s -o /dev/null \
       'http://192.168.1.231/v1/machine:readmem?address=0400&length=32768'
     sleep 2
   done
   ```

3. Watch the jiffy clock — three bytes at `$00A0` that the KERNAL increments
   sixty times a second, and only while interrupts are being serviced:

   ```sh
   while true; do
     curl -s 'http://192.168.1.231/v1/machine:readmem?address=00A0&length=3' \
       | xxd -p
     sleep 5
   done
   ```

   While the machine lives, that number climbs. **When it stops climbing and
   never moves again, the machine has hung.**

Substitute the address of your own device. Ours hung in **5.6 minutes**.

**A single small load is over in a moment, and a read has to land inside one.**
So load something big, or keep loading things, for as long as the loop runs.
Section 2 makes that automatic.


## 2. The self-contained version

For a report to somebody who has no disk of ours — and for an unattended run —
`tools/c64uhang.py` builds a disk containing nothing but two generated files:

| file | what |
|---|---|
| `HANG` | one line of BASIC |
| `HANGDATA` | 4 KB of zeroes, loading to `$C000` |

```basic
10 LOAD"HANGDATA",8,1
```

That is the whole program. **A `LOAD` inside a running BASIC program restarts
the program**, so this reads the file over and over for ever with no `GOTO`,
keeping the serial bus busy at full KERNAL speed.

`$C000` matters. `LOAD"...",8,1` is a *non-relocating* load: it goes to the
address in the file's own first two bytes. Most files on a disk are BASIC
programs loading to `$0801`, **which is where the running program lives** — load
one of those and it overwrites the loop mid-flight. `$C000` is free RAM on a
bare C64, so nothing cares what lands there.

### If you want to use a file you already have

Use the reading form instead, which never puts the file anywhere:

```basic
10 OPEN2,8,2,"ANYFILE,P,R"
20 GET#2,A$:IF ST=0 THEN 20
30 CLOSE2:GOTO 10
```

This is the plainest possible serial read — the KERNAL's byte-in routine,
which is **exactly the loop both real hangs were sitting in** — and being
byte-at-a-time it keeps the drive busy longer than a block load does.

### The tool

```sh
tools/c64uhang.py build --out work/hang.d64
tools/c64uhang.py run --variant load --size 32768 --interval 2 --minutes 10
```


## 3. Telling a hang from a load

**A normal disk load also stops the jiffy clock**, because the KERNAL turns
interrupts off while it talks to the drive. During one load this project
measured the clock stopped for about eleven seconds out of fifteen.

So a single frozen reading proves nothing. **It has to stay at the same value
across several readings, ten seconds or more apart.** A load ends; a hang does
not.

Three other traps, each of which produced a wrong answer here before it was
caught:

* **`$DD00` says nothing on its own.** Six runs were scored on it containing
  `$C4`. That is the commonest *healthy* value on this machine — 76 of 164
  samples. All six verdicts were wrong.
* **Do not poll `$DC0D`.** Reading CIA 1's interrupt register *acknowledges*
  the interrupt, so watching it changes what you are watching. Read it once, in
  the end check, after the clock has already stopped.
* **An unreachable device is not a hung C64.** The Ultimate's own REST service
  stops answering under sustained polling
  (`#370 (The C64 Ultimate's REST service stops answering under sustained
  polling, ending every long hardware run before the measurement finishes)`),
  and a run that ends there has measured nothing. Wait for the service and take
  the end check anyway.

And one about the end check's own vocabulary, which nearly threw away three
good runs. A sweep on 2026-09-07 returned the verdict `basic` for 2048, 8192
and 16384 bytes, and `basic` reads as *"the program stopped, the drive was
idle, nothing was tested"*. **It was not that.** `basic` was only the label for
KERNAL-default registers, and **a running BASIC `LOAD` loop shows exactly the
registers an idle prompt does**. The samples underneath say the machine was
working the whole time:

* `$DD00` never once read `$97`, the idle-prompt value; it cycled the same
  seven bus states as the run that hung;
* the screen hash held one value across every sample, where a prompt's blinking
  cursor alternates two;
* the jiffy ran at 66 % of wall time, against 56 % in the hung run — the
  difference being how much of each run the KERNAL spent with interrupts off.

So those runs are **real negative results**, not artefacts. Check the bus and
the screen before believing a verdict either way, and do not name a verdict
after a register set that two different states share.


## 4. What it looks like when it goes

The machine stops mid-load, screen frozen, nothing responding, and only a reset
recovers it.

Resolving return addresses off the stack puts the processor in the KERNAL's
serial receive loop — an unbounded wait on `$DD00` with interrupts off, asking
the drive for a byte that never arrives. **Both real hangs are in that loop**:
the one caught under instrumentation on 2026-09-07, and Donald's own at
`ONWARD BOUND` in September. Graded PROBABLE rather than CONFIRMED, because
the stack pointer cannot be read over the device's interface and the position
has to be inferred.

They differ in one way, and it answers a question that had been open for days.
September's went through the game's own fastloader; the instrumented one went
through the KERNAL's plain loader, because the fastloader had been disabled.
**Disabling it changes which loop hangs, not whether a load can hang** — which
is why answering `Y` to `DISABLE FASTLOADER (Y/N)?` never helped.

Nothing is corrupted in either capture: the drive code and the screen are
byte-perfect. This is a machine stopped, not a machine fed rubbish.


## 5. How big a read it takes

**Not established, and it does not matter for a reproduction.** Donald,
2026-09-07: *"For a simple procedure to duplicate the hang, we do not really
care what the smallest possible read is. We just want to prove the issue
happens."*

What is measured, on this unit:

| read | processor frozen for | outcome |
|---|---|---|
| 1 byte | ~42 µs | shorter than one serial bit |
| 1000 bytes | ~1.1 ms | past the drive's own byte timeout |
| 2048 bytes | ~2.3 ms | ~380 reads, no hang |
| 7168 bytes | ~7.9 ms | ~240 reads over 18 min, no hang |
| 8192 bytes | ~9 ms | ~380 reads, no hang |
| 16384 bytes | ~18 ms | ~360 reads, no hang |
| 32768 bytes | ~36 ms | **hung in 5.6 min**, ~170 reads |
| 53248 bytes | ~57 ms | **hung in 23 min**, 98 reads |
| 65536 bytes | ~72 ms | 225 reads, **no hang** |

**Read size does not order the hazard, on this evidence.** Sixty-four kilobytes
— twice the size that hung — survived 225 reads, all of them verified
full-length. There have been **two hangs, ever**, against non-hangs at every
other size tried. Two events cannot separate "bigger is worse" from "it happens
occasionally and we were unlucky twice".

What the runs do support: **a hang occurs, and the per-read hazard during
loading is of order one in a thousand.** That is the claim to send upstream.

An earlier version of this page said *"the length of each halt decides it, not
how many you take"*, on one observation at each of two sizes. The 64 KB run
contradicts it and it is withdrawn. The mechanism in §4 stands — a halt inside
the serial wait breaks the transfer — but how the odds vary with halt length is
unmeasured.

The cost is about 42 µs fixed plus 1.1 µs a byte. A KERNAL serial bit is 60–70
µs wide and the drive waits about a millisecond for each byte to be
acknowledged, so a halt of milliseconds inside that exchange desynchronises it.

**So what the workaround should do, in this order** — revised once the 64 KB
run showed size does not order the hazard:

1. **an upstream `readmem` that waits for an idle bus.** Only the firmware
   knows when its own 1541 is on the wire, so only the firmware can close the
   window. This is the actual fix and it helps every tool, not only ours;
2. **a bus guard**, reading one byte of `$DD00` and skipping the rest of the
   tick when the drive is mid-conversation. It races — a load starting between
   the guard and the reads after it is still hit — but it addresses *when* a
   read lands, which is what the evidence points at;
3. **poll less**, which is linear help;
4. **a size ceiling**, as hygiene rather than as the fix it was first taken
   for.


## 6. What it is not

**Not the game.** It reproduces with plain BASIC and a generated disk, no Gold
Box code anywhere.

**Not the game's fastloader.** Refuted twice: by Donald playing with it
disabled, and by the two captures sitting in different loaders.

**Not a cracked release.** The disks are code-wheel protected originals.

**Not the save disk.** It is never mounted except while loading a save.

**One machine.** Donald, 2026-09-05: *"the cause could be anything. The game
software, the firmware, the 1541 software, or bad hardware. It is only one
machine."* Everything here says *this* unit on firmware 3.14 behaves this way.
A second Ultimate is the only clean way to tell a firmware fault from a fault
in this one, and nobody here has one.
