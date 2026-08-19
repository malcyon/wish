# Optional future feature: live memory and an automapper

**Status: not started, and deliberately outside the character editor.** This is a
design note for a feature we might build, recorded so the thinking is not lost.
Nothing here is implemented.

## The idea

Read the party's map coordinates out of the running game and draw a live
automap, in the spirit of the Gold Box Companion. Optionally write memory too,
for things a save file cannot reach.

## Why it is cheap to add later

`por/` contains **no transport code at all** — no sockets, no disk knowledge
beyond the D64 module. `CharacterRecord.from_bytes()` does not care whether the
bytes came from a disk image, a TCP socket or an HTTP response. So a live layer
does not disturb any existing code; it only has to supply bytes.

## The whole interface

```python
class Target(Protocol):
    def read(self, addr: int, length: int) -> bytes: ...
    def write(self, addr: int, data: bytes) -> None: ...
```

Everything else builds on those two. Breakpoints, stepping and similar are
VICE-only luxuries; keeping them out of the contract stops every other backend
having to pretend it has them.

## Two backends, and only two

* **VICE**, over its binary monitor (`POR_DEBUG=1` already enables it).
* **Commodore 64 Ultimate**, over its network interface.

Deliberately not supporting other emulators or bare hardware. Most emulators
have no usable interface, and a real C64 would need a resident stub or a DMA
cartridge — a lot of fragility for very few users.

*(If a third is ever wanted, the cheapest by far is **watching the save file**:
poll its mtime and re-read on change. It needs no protocol, works on real
hardware with an SD2IEC, and fits the same interface with `writable=False`. It
is a fallback, not a priority.)*

## Backends differ in ways that change what you can build

Worth declaring rather than assuming:

| | VICE | Ultimate |
|---|---|---|
| writable | yes | expected, unverified |
| latency | ~1 ms, local TCP | higher; network |
| reading disturbs the machine | **yes** | expected no |

That last row is not a detail. **Connecting to VICE's binary monitor stops the
CPU** — during this project a perfectly healthy game was misdiagnosed as frozen
because of it ([the monitor-pause test](50-experiments.md)). A live map that opened a connection per poll would stutter
the game visibly. The VICE backend must hold one connection open and resume with
`EXIT`, not connect per read.

Two other VICE sharp edges already paid for: responses must be matched by
**request id**, because unsolicited events interleave and a naive reader
silently returns the *previous* request's data ([the desynchronised reads](50-experiments.md)); and reading RAM under I/O
needs the explicit `ram` bank.

## The two problems that are not about transport

**Overlays make addresses conditional.** The party lives at `$4D00` *while the
right overlay is resident*. Patching `$12D9` after the game had swapped a
different overlay into that space corrupted a live routine — see the warning in
[Getting past the copy protection](50-experiments.md). So a live backend needs **validate-before-trust**: read the region, check
it still decodes as a sane party, and refuse otherwise. For writes that check
should be mandatory.

**Batch aggressively.** Read `$4900`–`$64FF` in one call, not sixty small ones.
At network latency that is the difference between a usable map and an unusable
one.

## The actual first task is not the transport

**We do not know where the party's map coordinates are.** Nothing in the
character record looks like an x/y pair, and most of `SAVEDGAME1`
(`$8300`–`$8AFF`) is still unread — its first page is the party roster and
everything past `$83FF` is untouched, so it remains the obvious candidate, being
the other thing
the game saves.

Finding them is straightforward with the technique that has worked all along:
**take one step in the game, save, and diff.** Two or three saves a few squares
apart would isolate the coordinates without touching an emulator. That work is
worth doing regardless of whether a live map ever gets built, because it also
tells us what `SAVEDGAME1` is for.

## If it is ever built

1. Find the coordinates by diffing saves (no emulator needed).
2. Implement the `Target` protocol with the VICE backend only.
3. Draw the map from `Target`, so it never knows which backend it has.
4. Add the Ultimate backend, and see whether the interface survives contact with
   a second, slower transport. If it does not, better to learn that at two
   backends than at five.
