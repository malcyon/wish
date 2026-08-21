# Content audit

Against the rule in `CLAUDE.md`: this project documents a game it does not
ship, and must not carry the game's art, music, manuals, executable code,
disassembly listings, or data files.

**All findings below are fixed.** Kept as the record of what was wrong and
how it was resolved; `tests/test_repository_contents.py` now enforces it.

Audited the tracked tree on 2026-08-20. **Disk images are clean** — no `.d64`
has ever been committed, in any commit, and `work/` has been `.gitignore`d from
the start. The findings are all in `tests/fixtures/`, plus one in the docs.

---

## Out of compliance

### 1. [FIXED] `tests/fixtures/SPELLN64.bin` — the game's executable code

1878 bytes lifted verbatim from disk 3. It is 6502 machine code: the first
instructions at `+$24` are `LDA $6B99 / AND #$01 / STA $B5F1`. This is the
plainest violation of the rule and should go first.

Used by `tests/test_iconparts.py`.

### 2. [FIXED] `tests/fixtures/SPELLE64.bin` — a game data file

1882 bytes, verbatim from disk 3. Tables, not code, but a data file copied
whole.

Used by `tests/test_iconparts.py` and `tests/test_editor.py`.

### 3. [FIXED] `tests/fixtures/GEO04.bin` — a game map file

1024 bytes, one map verbatim.

Used by `tests/test_geo.py`, `tests/test_automap.py`,
`tests/test_binary_roundtrip.py`.

### 4. [FIXED] `tests/fixtures/pool1_savedgame0.bin` — shipped game content

7170 bytes taken from the shipped `POOL1.D64`. Unlike the other saves below,
this is not a player's own data — it is the party SSI put on the disk.

Used by `tests/test_iconparts.py`.

### 5. `docs/70-driving-the-game.md` — not a finding

Five instructions transcribed with their opcode bytes, in the `$0C41` block.
The rule allows naming an address and the two or three instructions at it as
evidence; this is a short listing rather than a citation, and sits on the wrong
side of the line. The finding it supports can be stated without the bytes.

Elsewhere the docs cite instructions inline — `LDA $6D99 / AND $6BEB / BNE` and
similar. Those are commentary and are fine; there are no other listings.

---

## Grey, and lower priority

`savedgame0.bin`, `savedgame1.bin`, `party6_savedgame0.bin`,
`party6_after_combat.bin`, `combat-arena.bin`, and the three `.chr` exports are
**the player's own saved games**, produced by playing, not shipped by SSI. They
are the player's data in the game's format rather than the game's content.

**Most of them cannot be regenerated.** Checked against every disk: only
`party6_savedgame0.bin` and `malcyon.chr` still exist on one. The rest capture
states that were played past and overwritten. They stay, on the allowlist.

`combat-arena.bin` is a capture of live machine memory during a duel, so it also
contains whatever game code was resident at the time — that part is not the
player's data, and it should be reduced to the address ranges the test actually
reads.

---

## How it was fixed

`tests/gamedata.py`: `game_file(name)` reads a file off whichever `POOL*` disk
carries it and skips when there are none, and `synthetic_geo()` generates a
well-formed map from the format for the tests that only need *a* file.

`pool1_savedgame0.bin` was deleted rather than converted — the assertion it
supported already passes against the player's own saves.

Measured, both ways:

| | tests |
|---|---|
| with the disks present | **505 pass** (up 5: the generated map added coverage) |
| with no disks at all | **478 pass, 27 skip**, none fail |

The 27 that skip are the ones that need real game files. That is the fair cost
of not shipping them, and it is smaller than it looks: losslessness, the record
and save decoding, the automapper geometry and the whole combat view keep
running, because those use the player's own saves.

`tests/test_repository_contents.py` now enforces the rule — an allowlist for
`tests/fixtures/`, and a rejection of disk images, executables, images and
audio anywhere in the tree.

---

## Not findings

* **No art, music or sound of any kind** is tracked — no sprites, tilesets,
  portraits or SID data.
* **No manual, cluebook or journal text** is tracked, transcribed or otherwise.
* `work/analysis4/dis_*.txt` are full disassembly listings, and are correctly
  outside the repository — `work/` is ignored. They must stay there.
* The generated docs (`docs/20`, `docs/40`, `docs/85`–`89`) are tables *about*
  the format, produced by our own tools from field descriptions. They describe;
  they do not copy.
