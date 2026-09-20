#!/usr/bin/env python3
"""Measure how DOS Curse's `MEMORIZE` list turns a page, one keypress at a time.

`#574 (Camp.memorize's page-turn landing is stateful and not proven for page >
0)` refuses `Camp.memorize(page>0)` because nothing here knows what a page turn
does to the highlight, how many pages a grimoire has, or whether the command
bar separates one page from another.  Nothing in the tree walks from the world
map to `ENCAMP > MAGIC > MEMORIZE` either: `Camp` starts at the grimoire and
assumes the caller arrived.  This walks there and presses a key list, writing a
screenshot and four values after **every** press:

| column | what it is |
|---|---|
| `row` | `Screen.highlight_row(Camp.GRIMOIRE_LIST)`, the physical band the highlight is on, or empty when no band is highlighted |
| `bar` | `Screen.glyphs(dosbox.BAR)`, the command bar by shape against its own paper |
| `digest` | `Screen.digest()`, the whole frame |
| `shot` | the PNG written for that press |

`glyphs` rather than `ink` for the bar: `Screen.glyphs`'s own docstring says
why a fixed threshold cannot be trusted on a screen whose paper is not black.

The party is staged from a specimen tree rather than the game's shipped slot,
and `Session.marching_first` brings one character to marching position 0 --
there is no key that changes which character a camp screen acts on:

    tools/curse_of_the_azure_bonds/cursememorize.py \
        --specimen $WISH_SPECIMENS/coab-dos/WISH-SPEC-curse-551-party-as-converted \
        --who 5                       # the PALADIN; 4 is the RANGER

Each `--trial` is one key list, pressed from a freshly entered `MEMORIZE`
screen; the default three are the lists `#574`'s plan names.  `--path` is the
keystroke route from the map to the grimoire, a flag because it is a reading of
the camp bar's words rather than a measurement.  `--after` presses a further
list once the trials are done and `--save-to` waits for that slot's
`SAVGAM<letter>.DAT` to change and prints each record's memorised spells, which
is how "did `Return` commit anything" is answered from the game's own writing.

A key list token is an X keysym (`End`, `Return`, `n`), `~N` to sleep N
seconds, or `KEY*N` for N presses of KEY.  Output goes to `--out`, by default a
scratch directory outside the repository; nothing here writes to the archives
or to the specimen.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import shutil
import sys
import time

REPO = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO))

from goldbox import dos_codec  # noqa: E402
from tools.dos import dosbox  # noqa: E402
from tools.registry import scratch  # noqa: E402

#: The three key lists `#574`'s plan asks for, each from a fresh `MEMORIZE`.
DEFAULT_TRIALS = (
    "n n n p p p",          # how many pages, and whether the bar separates them
    "n End*20",             # the reset case: where a turn with no End first lands
    "End n End*20",         # the preserved case, the one Camp.memorize assumes
)

#: `PALADIN'S SPELLS IN GRIMOIRE`, the list screen's own title row.  Measured
#: off this run's own shots: its `glyphs` digest is the same on the grimoire's
#: first page, its second, and its first reached again by `p` -- where the
#: whole-frame digest and the command bar are not, since the bar carries a
#: reverse-video cursor that the page keys move.  The map, the camp menu and
#: the magic menu all hash differently here, so it answers "is the list
#: showing" without reading a word.
GRIMOIRE_TITLE = (16, 8, 288, 8)

#: The three character cells of the bar that read `EXT` of `NEXT` on a page
#: with more after it and `REV` of `PREV` on the last one.  **Not the whole
#: word**: the cursor's reverse-video block starts at the word's own cell, and
#: `glyphs` is blind to reverse video only where the rectangle lies wholly
#: inside the block or wholly outside it -- a rectangle that straddles its edge
#: hashes differently with the cursor there and without it.
PAGE_WORD = (188, 192, 24, 7)


def describe(path: pathlib.Path) -> dict:
    """One character record, as the fields a memorisation moves."""
    c = dos_codec.read_character(path)
    out = {"file": path.name, "name": c.name,
           "class_levels": list(c.raw("class_levels"))}
    for field in ("spells_memorised", "spell_slots"):
        if field in c.fields:
            out[field] = [v for v in c.raw(field) if v]
    return out


def expand_keys(tokens) -> list[str]:
    """One flat key list from `--trial`/`--path` words.

    `End*20` is twenty presses, `~1.5` sleeps a second and a half, and a word
    with spaces in it is several tokens, so `--trial "n End*20"` and
    `--trial n --trial End*20` mean the same thing.
    """
    out: list[str] = []
    for token in tokens:
        for word in str(token).split():
            key, star, count = word.partition("*")
            if star:
                out.extend([key] * int(count))
            else:
                out.append(word)
    return out


def shot_name(tag: str, n: int, key: str) -> str:
    """A file name for one press: no keysym reaches the filesystem unfiltered."""
    return f"{tag}-{n:02d}-{re.sub(r'[^A-Za-z0-9]', '_', key)}"


def press_sequence(session, keys, record, *, tag: str,
                   rect=dosbox.Camp.GRIMOIRE_LIST, blank_stop: int = 2,
                   deadline: float | None = None, settle: float = 30.0) -> list[dict]:
    """Press `keys` one at a time, recording the four values after each.

    Stops early when `highlight_row` comes back `None` `blank_stop` times
    running -- the list is not showing, so further presses are going somewhere
    unknown -- or when `deadline` passes.  `blank_stop=0` turns that off, for
    the walk to the grimoire where the list is not up yet.

    Returns the rows it recorded, each of which was passed to `record` as it
    was taken, so a run that falls over has already written everything it
    measured.
    """
    rows: list[dict] = []
    blanks = 0
    for n, key in enumerate(keys):
        if key.startswith("~"):
            time.sleep(float(key[1:]))
        else:
            session.key(key)
        screen = session.settle(quiet=0.6, timeout=settle)
        row = {"tag": tag, "n": n, "key": key,
               "row": screen.highlight_row(rect),
               "bar": screen.glyphs(dosbox.BAR),
               "digest": screen.digest(),
               "page": screen.glyphs(PAGE_WORD),
               "title": screen.glyphs(GRIMOIRE_TITLE)}
        try:
            row["shot"] = session.shot(shot_name(tag, n, key),
                                       allow_blank=True).name
        except Exception as exc:                            # noqa: BLE001
            row["shot_error"] = repr(exc)
        record(row)
        rows.append(row)
        blanks = blanks + 1 if row["row"] is None else 0
        if blank_stop and blanks >= blank_stop:
            record({"tag": tag, "n": n, "key": "<stop>",
                    "why": f"no highlight {blanks} presses running"})
            break
        if deadline is not None and time.time() > deadline:
            record({"tag": tag, "n": n, "key": "<stop>", "why": "out of time"})
            break
    return rows


def sample(session, record, *, tag: str,
           rect=dosbox.Camp.GRIMOIRE_LIST) -> dict:
    """The same four values with no key pressed -- a screen's entry state."""
    screen = session.settle(quiet=0.6, timeout=30.0)
    row = {"tag": tag, "n": -1, "key": "",
           "row": screen.highlight_row(rect),
           "bar": screen.glyphs(dosbox.BAR),
           "digest": screen.digest(),
           "page": screen.glyphs(PAGE_WORD),
           "title": screen.glyphs(GRIMOIRE_TITLE)}
    try:
        row["shot"] = session.shot(f"{tag}-enter", allow_blank=True).name
    except Exception as exc:                                # noqa: BLE001
        row["shot_error"] = repr(exc)
    record(row)
    return row


def keep_run_files(session, out: pathlib.Path, note) -> None:
    """Copy this run's shots and save records into `out/shots` and `out/saves`.

    `--out` defaults to one fixed path, so both directories are emptied first:
    a record a longer earlier run left in `saves/` would otherwise be reported
    as this run's `after` state, and a shot would sit beside this run's under
    a name that only looks like it belongs.  The sources are this run's own
    slot files, written by `import` and by the game into a tree `stage` made
    writable, so the copy cannot carry a read-only mode.
    """
    shots = out / "shots"
    saves = out / "saves"
    for kept in (shots, saves):
        shutil.rmtree(kept, ignore_errors=True)
        kept.mkdir(parents=True)
    for png in sorted((session.dir / "shots").glob("*.png")):
        shutil.copy(png, shots / png.name)
    for f in sorted(session.save_dir.glob("*")):
        if f.name.upper().startswith(("CHRDAT", "SAVGAM")):
            shutil.copy(f, saves / f.name)
    for rec in sorted(saves.glob("CHRDAT*.SAV")):
        note(event="after", **describe(rec))
    note(event="kept", shots=str(shots), saves=str(saves))


def run(args: argparse.Namespace) -> int:
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    log = (out / "run.jsonl").open("a")
    tsv = (out / "keys.tsv").open("a")
    tsv.write("tag\tn\tkey\trow\tbar\tdigest\tpage\ttitle\tshot\n")

    def note(**kw) -> None:
        kw["t"] = round(time.time(), 2)
        log.write(json.dumps(kw, default=str) + "\n")
        log.flush()
        print(json.dumps(kw, default=str), flush=True)

    def record(row: dict) -> None:
        note(event="press", **row)
        tsv.write("\t".join(str(row.get(k, "")) for k in
                            ("tag", "n", "key", "row", "bar", "digest",
                             "page", "title", "shot")) + "\n")
        tsv.flush()

    specimen = pathlib.Path(args.specimen).expanduser()
    path_keys = expand_keys([args.path])
    trials = [expand_keys([t]) for t in (args.trial or DEFAULT_TRIALS)]
    deadline = time.time() + args.minutes * 60

    slot = dosbox.claim("issue574 curse memorize")
    session = dosbox.Session(slot, dosbox.find_game(args.game))
    try:
        session.stage(fresh=True)
        # The shipped tree carries its own slot A; the specimen is the party.
        for old in sorted(session.save_dir.iterdir()):
            if old.name.upper().startswith(("CHRDAT", "SAVGAM")):
                old.unlink()
        staged = []
        for src in sorted(specimen.iterdir()):
            if src.name == "provenance.toml":
                continue
            # `copyfile`, not `copy`: the specimen tree is r--r--r-- and the
            # game has to write `SAVGAM<slot>.DAT` back on a save.
            shutil.copyfile(src, session.save_dir / src.name)
            staged.append(src.name)
        note(event="staged", files=staged, save_dir=str(session.save_dir))
        for rec in sorted(session.save_dir.glob("CHRDAT*.SAV")):
            note(event="before", **describe(rec))

        session.boot(fresh=False)
        game = session.marching_first(args.slot, args.who)
        note(event="loaded", who=args.who, party_bar=game.world_bar,
             digest=session.capture().digest())
        press_sequence(session, expand_keys([args.begin]), record,
                       tag="begin", blank_stop=0)
        screen = session.settle()
        note(event="world", ink=screen.ink(dosbox.BAR),
             glyphs=screen.glyphs(dosbox.BAR))

        title = None
        for i, keys in enumerate(trials):
            if i:
                # **Not `PoolOfRadiance.leave_camp`**: it compares a whole-bar
                # `ink` digest against the one recorded on the map, and Curse's
                # map bar carries a cursor that its own alternation of `Escape`
                # and `n` moves -- so it walked the party back to the map,
                # failed to recognise it with the cursor on `CAST` rather than
                # `AREA`, and raised after twelve tries.  `--reenter` leaves the
                # list the short way instead, and the walk from the map is the
                # fallback when the title row says the list is not showing.
                back = press_sequence(session, expand_keys([args.reenter]),
                                      record, tag=f"t{i}-back", blank_stop=0)
                if title and (not back or back[-1].get("title") != title):
                    press_sequence(session, path_keys, record,
                                   tag=f"t{i}-path", blank_stop=0)
            else:
                press_sequence(session, path_keys, record, tag=f"t{i}-path",
                               blank_stop=0)
            entry = sample(session, record, tag=f"t{i}")
            title = title or entry.get("title")
            note(event="trial", trial=i, keys=keys)
            press_sequence(session, keys, record, tag=f"t{i}",
                           deadline=deadline)
            if time.time() > deadline:
                note(event="out-of-time", trial=i)
                break

        if args.after:
            path = session.save_file(args.save_to) if args.save_to else None
            was = path.read_bytes() if path and path.is_file() else None
            press_sequence(session, expand_keys(args.after), record,
                           tag="after", blank_stop=0)
            if path is not None:
                stop = time.time() + 90.0
                while time.time() < stop:
                    if path.is_file() and path.read_bytes() != was:
                        break
                    time.sleep(0.3)
                dosbox.settle_files(session.save_dir, timeout=60.0)
                note(event="saved", slot=args.save_to,
                     changed=path.is_file() and path.read_bytes() != was)
        note(event="done")
    finally:
        # Kept here rather than at the end of the try: a run that falls over
        # mid-trial still wrote shots and records, and the slot's directory
        # goes with the next run's `stage(fresh=True)`.
        try:
            keep_run_files(session, out, note)
        except Exception as exc:                            # noqa: BLE001
            note(event="keeping-failed", error=repr(exc))
        session.close()
        slot.release()
        tsv.close()
        log.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--specimen", required=False,
                    help="a save tree to stage: SAVGAM<slot>.DAT and CHRDAT*")
    ap.add_argument("--game", default="CURSE", help="the game directory stem")
    ap.add_argument("--slot", default="A", help="which save slot to load")
    ap.add_argument("--who", type=int, default=5,
                    help="party index to bring to marching position 0; "
                         "5 is the PALADIN of the #551 party, 4 the RANGER")
    ap.add_argument("--begin", default="b",
                    help="keys from the loaded party menu to the map")
    ap.add_argument("--path", default="e m m",
                    help="keys from the map to ENCAMP > MAGIC > MEMORIZE")
    ap.add_argument("--reenter", default="Escape m",
                    help="keys that leave the list and enter it again; the "
                         "--path walk is the fallback when they do not")
    ap.add_argument("--trial", action="append",
                    help="a key list to press from a fresh MEMORIZE screen; "
                         "repeatable, and each one re-enters the screen")
    ap.add_argument("--after", nargs="*",
                    help="keys pressed once the trials are done")
    ap.add_argument("--save-to", default=None,
                    help="wait for this slot's SAVGAM to change after --after")
    ap.add_argument("--minutes", type=float, default=20.0,
                    help="stop pressing after this long")
    ap.add_argument("--check", action="store_true",
                    help="print the tools and the game directory, and stop")
    ap.add_argument("--out",
                    default=str(scratch.scratch_dir("cursememorize", "run")))
    args = ap.parse_args(argv)
    if args.check:
        absent = dosbox.missing_tools()
        print("tools missing:", ", ".join(absent) if absent else "none")
        try:
            print("game:", dosbox.find_game(args.game))
        except FileNotFoundError as exc:
            print("game:", exc)
        print("trials:", [expand_keys([t]) for t in (args.trial or DEFAULT_TRIALS)])
        print("path:", expand_keys([args.path]))
        return 1 if absent else 0
    if not args.specimen:
        ap.error("--specimen is required unless --check")
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
