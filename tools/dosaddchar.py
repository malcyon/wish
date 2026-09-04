#!/usr/bin/env python3
"""Drive DOS Pool of Radiance's ADD CHARACTER TO PARTY, and measure its
duplicate test.

The measurement `#216 (Every converted DOS character carries the same identity
byte at 0x0AB)` asked for.  `goldbox.dos.write` used to leave `unnamed_0ab`
zero in every record it made, and the engine uses that byte in one test:
adding a saved character to the party is refused when the candidate's **name
and `0x0AB` both** match a character already in the party.  Six converted
characters therefore carried the same value where the game's own carry a
random one each, and the question was whether a player can be refused an add
that the game would have allowed.  They can: the answer this tool measured is
that the second of two same-named converted characters is turned away in
silence, and `goldbox.dos.WRITE_DERIVED` is what the writer does instead now.

**One byte is the whole experiment.**  Two `.CHA` files are built by
`goldbox.dos.write` from two *different* shipped records, both renamed to the
same name, and offered to a party that already holds the first.  The variants
differ in one byte and nothing else:

| variant | the two files' `0x0AB` | expected |
|---|---|---|
| `--ident 0` | `0x00` and `0x00`, what the conversion used to write | refused, party of one |
| `--ident 0x42` | `0x00` and `0x42`, the second hand-set | accepted, party of two |
| `--writer` | whatever `goldbox.dos.write` writes today | accepted, party of two |

If both of the first two are accepted, the byte is not part of the test and
the issue is refuted.  If both are refused, the test is on the name alone and
the zero is irrelevant -- also a refutation, and the reason the control run is
not optional.  `--writer` is the third question and a different one: not what
the engine does, but whether what the writer produces now clears it.

Nothing is loaded from a saved game: the party starts empty, so the engine's
own six-character capacity check cannot be what refuses the second add.  The
staged `CHARLIST.TXT` is replaced with two names of our own, so the menu
offers nothing else, and the file the menu opens is `<entry>.CHA` -- the
*entry* names the file, and the *record inside* carries the name the duplicate
test compares, which is why one file can be called `ALPHA` and hold `DUPLICO`.

**How the screen is driven.**  `ADD A CHARACTER: ADD EXIT` is the game's
generic list menu, and **the arrow keys do nothing in it**: `Home` and `End`
move the highlight within the page, `N` and `P` (and `PgDn`/`PgUp`) turn the
page, and any other key picks whatever is highlighted -- which is how a run
that presses `Down` and then `Return` offers the engine the first entry twice
and measures nothing.  A successful *or* refused add rewrites the menu entry
in place as `* NAME`, and a starred entry is skipped before the file is even
read, so each entry can only be offered once per visit.  That star is also
this tool's proof that the record was read at all: `beta_was_read` in the
report is the screen changing when the second entry is picked.

Ground truth is the roster the main menu draws after `EXIT`, captured as a
screenshot, and the count of characters the engine writes when the run then
saves the party to a slot of its own.  Neither reads a word off the screen:
the file count is a host-filesystem fact.

    tools/dosaddchar.py --both
    tools/dosaddchar.py --writer
    tools/dosaddchar.py --ident 0x42 --keep

Output -- screenshots and a JSON report -- goes under `work/issue216/`, never
into the repository.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import shutil
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from goldbox import dos  # noqa: E402
from tools import dosbox  # noqa: E402

#: The name both test characters carry inside their records.  Deliberately not
#: a name any shipped character has, so a roster line naming it can only have
#: come from one of the two files this tool wrote.
NAME = "DUPLICO"

#: `CHARLIST.TXT` entry -> the shipped record the converted `.CHA` is built
#: from.  Two *different* characters, which is the point: a duplicate test
#: that lets the second one in has distinguished them, and one that does not
#: has decided on the name and the identity byte alone.
SOURCES = (("ALPHA", "CHRDATA1.SAV"), ("BETA", "CHRDATA2.SAV"))

#: Where the run's screenshots and report land.
OUT = REPO / "work" / "issue216"


def converted(src: Path, name: str, ident: int | None) -> tuple[bytes, bytes]:
    """A record `goldbox.dos.write` made from `src`, renamed, `0x0AB` forced.

    The rename is done on the neutral character rather than on the bytes, so
    the writer lays the name out itself -- one count byte and fifteen of
    ASCII -- and the record stays self-consistent.  `ident` is written over
    whatever the writer put at `0x0AB`, and that overwrite is the only byte
    the variants of this experiment differ in.  `ident=None` leaves the
    writer's own byte alone, which is how the run measures the writer rather
    than the engine.
    """
    neutral = dos.to_neutral(dos.read_character(src))
    neutral.fields["name"] = dataclasses.replace(
        neutral.fields["name"], value=name)
    record, itm, _spc, _report = dos.write(neutral)
    if ident is None:
        return record, itm
    record = bytearray(record)
    record[dos.FIELDS_BY_NAME["unnamed_0ab"].offset] = ident
    return bytes(record), itm


def stage_characters(save_dir: Path, ident: int | None) -> dict[str, str]:
    """Write the two `.CHA`/`.ITM` pairs and the `CHARLIST.TXT` that lists them.

    `ident` is forced on **both** files when it is `0`, which is the state
    `goldbox.dos.write` used to leave every converted character in, and on
    the second alone otherwise, so the pair differs in one byte.  `None`
    leaves both files carrying whatever the writer produces today, which is
    the run that says whether the fix works in the game.
    """
    made = {}
    for i, (entry, source) in enumerate(SOURCES):
        record, itm = converted(save_dir / source, NAME,
                                None if ident is None else (ident if i else 0))
        (save_dir / f"{entry}.CHA").write_bytes(record)
        if itm:
            (save_dir / f"{entry}.ITM").write_bytes(itm)
        made[entry] = (f"{source} as {NAME}, 0x0AB="
                       f"{record[dos.FIELDS_BY_NAME['unnamed_0ab'].offset]:#04x}")
    save_dir.joinpath("CHARLIST.TXT").write_bytes(
        b"".join(f"{entry}\r\n".encode() for entry, _ in SOURCES))
    return made


def run(ident: int | None, keep: bool = False) -> dict:
    """One variant, boot to report.  Returns what the run established."""
    label = ("writer" if ident is None
             else "same" if ident == 0 else f"differs-{ident:#04x}")
    shots = OUT / label
    shots.mkdir(parents=True, exist_ok=True)
    result: dict = {"ident": ident, "label": label}

    slot = dosbox.claim(f"issue216 {label}")
    session = dosbox.Session(slot, dosbox.find_game())
    try:
        session.stage(fresh=True)
        result["staged"] = stage_characters(session.save_dir, ident)
        # Slot C is this run's own and the archives use A, B and J, so a
        # CHRDATC file after the run can only be one the engine wrote here.
        for stale in session.save_dir.glob("CHRDATC*"):
            stale.unlink()
        for stale in session.save_dir.glob("SAVGAMC*"):
            stale.unlink()

        session.boot(fresh=False)
        game = dosbox.PoolOfRadiance(session)
        game.to_main_menu()
        session.shot("00-main-menu")

        session.key("a")
        session.settle()
        session.shot("01-list")

        session.key("Return")          # the highlighted entry: ALPHA
        after_alpha = session.settle()
        session.shot("02-after-alpha")

        # The list ignores the arrow keys and ignores N and P while it fits on
        # one page; End is what moves the highlight to the last entry, and a
        # run that skipped this step would offer the engine the *starred*
        # first entry again and measure nothing.
        session.key("End")
        moved = session.settle()
        if moved.px == after_alpha.px:
            raise RuntimeError("End did not move the highlight off ALPHA")

        session.key("Return")          # BETA, the character under test
        chosen = session.settle()
        session.shot("03-after-beta")
        # A candidate whose file was read is starred in the list before the
        # party is walked, whether it is then let in or turned away.  An
        # unchanged screen means the entry was never opened, and the run has
        # measured nothing rather than measured a refusal.
        result["beta_was_read"] = chosen.px != moved.px

        session.key("e")               # EXIT, back to the roster
        session.settle()
        result["roster_shot"] = str(session.shot("04-roster"))

        # Ground truth off the filesystem rather than off the screen: the
        # engine writes one CHRDAT<slot><n>.SAV per party member.  SAVE
        # CURRENT GAME from the party menu, into slot C.
        session.key("s")
        session.settle()
        session.key("c")
        deadline = time.time() + 30
        while time.time() < deadline:
            if list(session.save_dir.glob("CHRDATC*.SAV")):
                break
            time.sleep(0.5)
        session.settle()
        session.shot("05-saved", allow_blank=True)
        written = sorted(p.name for p in session.save_dir.glob("CHRDATC*.SAV"))
        result["party_files"] = written
        result["party"] = [
            dos.read_character(session.save_dir / n).name for n in written]
        result["party_idents"] = [
            (session.save_dir / n).read_bytes()[
                dos.FIELDS_BY_NAME["unnamed_0ab"].offset] for n in written]

        for png in sorted((session.dir / "shots").glob("*.png")):
            shutil.copy(png, shots / png.name)
    finally:
        session.close()
        if not keep:
            slot.release()
    result["added"] = len(result.get("party", []))
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ident", type=lambda s: int(s, 0), default=0,
                        help="the second character's 0x0AB (default 0, what "
                             "the conversion wrote before #216)")
    parser.add_argument("--both", action="store_true",
                        help="run 0x00 and 0x42 and print the comparison")
    parser.add_argument("--writer", action="store_true",
                        help="leave 0x0AB as goldbox.dos.write leaves it, "
                             "which is the run that tests the fix")
    parser.add_argument("--keep", action="store_true",
                        help="do not release the DOSBox slot afterwards")
    args = parser.parse_args(argv)

    idents: tuple[int | None, ...]
    if args.both:
        idents = (0x00, 0x42)
    elif args.writer:
        idents = (None,)
    else:
        idents = (args.ident,)
    results = []
    for ident in idents:
        result = run(ident, keep=args.keep)
        results.append(result)
        print(json.dumps(result, indent=2))
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "report.json").write_text(json.dumps(results, indent=2))
    if len(results) == 2:
        print(f"\n0x00 -> {results[0]['added']} in the party; "
              f"0x42 -> {results[1]['added']} in the party")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
