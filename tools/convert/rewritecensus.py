#!/usr/bin/env python3
"""Which fields of a DOS or Amiga record the editor's own writer renders
differently from the bytes the engine wrote, over every specimen on this
machine.

`goldbox/rewrite.py` writes an edited character back by rendering it twice --
once as read, once as edited -- and copying only the spans the two renderings
disagree about.  A field whose *unedited* rendering already differs from the
engine's bytes is a field an edit to which would replace the engine's answer
with the writer's, so it is the one thing that rewrite cannot promise.  This
counts them.

Two modes:

* the default **census** reads every DOS save slot, every Amiga Pool of
  Radiance slot and every Amiga Curse or Silver Blades saved game it can
  find, converts each character to the C64 record the sheet edits, renders it
  straight back through the port's own writer, and reports per port and title
  the fields whose span differs -- with the count of characters that reached
  each one, whether the writer rendered more than one value for it across
  that title's characters, and what the writer's own `write_targets` says it
  sources the field from.  **A span the writer rendered one value for over
  every character of a title is one no edit can move**, whatever it differs
  by, because the two renderings a rewrite compares can never disagree about
  it; the rest are the read-only candidates;
* `--no-op` runs the real `goldbox.rewrite` entry point over the same
  characters with nothing edited, and counts the ones that came back byte for
  byte -- the claim the design rests on, measured rather than argued;
* `--read-only` adds one to each field of the C64 record in turn, rewrites,
  and lists per port and title the fields no such edit moves a byte of.  That
  is the list the editor marks read-only: a field here is one a player could
  type into and lose on the next read;
* `--unreachable` lists, per DOS title, the fields
  `goldbox.dos_codec.write_targets` declares it takes from a constant, a
  default, a zero or a derivation rather than from a neutral value.

Inputs come from `$WISH_SPECIMENS` (default `~/wish-specimens`,
`tools/registry/specimens.py`) and from the DOS archives
`automap/gamedisks.py` finds under the `dos-archives` key.  Nothing is
written and no specimen is opened for writing.

    tools/convert/rewritecensus.py
    tools/convert/rewritecensus.py --unreachable
    tools/convert/rewritecensus.py --per-specimen
"""

from __future__ import annotations

import argparse
import collections
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from automap import gamedisks  # noqa: E402
from goldbox import (  # noqa: E402
    amiga_later,
    amiga_por,
    amiga_savegame,
    c64_codec,
    c64_port,
    dos_codec,
    dos_port,
    layout,
    record,
    rewrite,
)
from goldbox.amiga_adf import AmigaDisk  # noqa: E402
from goldbox.iconparts import amiga_combat_icon  # noqa: E402

#: One character examined: where it came from, the fields whose round trip
#: changes bytes, and the fields the port's record has no span for at all.
Row = collections.namedtuple("Row", "port title deltas specimen name "
                                    "fields unplaced")


def specimen_root() -> pathlib.Path:
    return pathlib.Path(os.environ.get("WISH_SPECIMENS")
                        or pathlib.Path.home() / "wish-specimens")


def dos_folders() -> list[pathlib.Path]:
    """Every folder holding a DOS save slot: the specimen tree first, then
    whatever save directories the registered DOS archives hold."""
    out = [p for p in sorted(specimen_root().glob("*-dos/WISH-SPEC-*"))
           if p.is_dir()]
    try:
        roots = gamedisks.candidates("dos-archives")
    except Exception:
        roots = []
    for root in roots:
        try:
            if not root.is_dir():
                continue
            out.extend(sorted({p.parent for p in root.rglob("SAVGAM?.DAT")}))
        except OSError:
            continue
    return out


def amiga_disks() -> list[pathlib.Path]:
    return sorted(specimen_root().glob("*-amiga/WISH-SPEC-*/*.adf"))


def amiga_later_saves() -> list[pathlib.Path]:
    """The engine-written Curse and Silver Blades saved games in the tree,
    which are loose files rather than disk images."""
    return sorted(
        list(specimen_root().glob("coab-amiga/WISH-SPEC-*/savgam?.dat"))
        + list(specimen_root().glob("ssb-amiga/WISH-SPEC-*/savgam?.sav")))


# ---------------------------------------------------------------------------
# One character's round trip, per port
# ---------------------------------------------------------------------------
def _row(port, title, deltas, specimen, name, original, rendered,
         spans, unplaced) -> tuple[Row, dict[str, bytes]]:
    """One comparison, and what the writer put in each span.

    The second value is what :func:`census` accumulates into the evidence
    that a span is input-independent: a span whose rendered bytes are the
    same for every character of a title, however different those characters
    are, is one no edit on the sheet can move.
    """
    moved = rewrite.changed_spans(original, rendered, spans)
    row = Row(port, title, deltas, specimen, name,
              tuple(s.name for s in moved), tuple(unplaced))
    return row, {s.name: rendered[s.at:s.at + s.size] for s in spans}


def _dos_row(char, game, specimen: str) -> tuple[Row, dict[str, bytes]]:
    rec, _ = dos_codec.to_c64_record(char)
    neutral = c64_codec.read(rec, game=game)
    rendered, _itm, _spc, _rep = dos_codec.write(
        neutral, deltas=char.deltas, icon=amiga_combat_icon(char))
    spans, unplaced = rewrite.dos_spans(char.deltas)
    return _row("DOS", char.deltas.title, char.deltas, specimen, char.name,
                char.to_bytes(), rendered, spans, unplaced)


def _amiga_por_row(char, game, specimen: str) -> tuple[Row, dict[str, bytes]]:
    dos_char = amiga_por.to_dos_character(char)
    rec, _ = dos_codec.to_c64_record(dos_char)
    neutral = c64_codec.read(rec, game=game)
    rendered, _itm, _spc, _rep = amiga_por.write_por(
        neutral, icon=amiga_combat_icon(char))
    spans, unplaced = rewrite.amiga_por_spans()
    return _row("Amiga", "Pool of Radiance", dos_port.POOL_OF_RADIANCE,
                specimen, char.name, char.raw, rendered, spans, unplaced)


def _amiga_later_row(char, game, specimen: str
                     ) -> tuple[Row, dict[str, bytes]]:
    neutral = amiga_later.to_neutral_later(char)
    rec, _ = dos_codec.neutral_to_c64_record(neutral)
    back = c64_codec.read(rec, game=game)
    written, _rep = amiga_later.write_later(
        back, deltas=char.deltas, icon=amiga_combat_icon(char))
    spans, unplaced = rewrite.amiga_later_spans(char.deltas)
    return _row("Amiga", char.deltas.title, char.deltas.dos, specimen,
                char.name, char.raw, written.raw, spans, unplaced)


# ---------------------------------------------------------------------------
# The sweep
# ---------------------------------------------------------------------------
def census() -> tuple[list[Row], list[str], dict]:
    """Every character this machine can reach, the notes for what it could
    not, and how many distinct values each span was rendered as."""
    rows: list[Row] = []
    notes: list[str] = []
    seen: dict = collections.defaultdict(
        lambda: collections.defaultdict(set))

    def add(result) -> None:
        row, rendered = result
        rows.append(row)
        for name, value in rendered.items():
            values = seen[(row.port, row.title)][name]
            if len(values) < 2:
                values.add(value)

    for folder in dos_folders():
        try:
            slots = dos_codec.slots_available(folder)
        except Exception as e:                                # pragma: no cover
            notes.append(f"{folder}: {type(e).__name__}: {e}")
            continue
        for slot in slots:
            try:
                party = dos_codec.read_party(folder, slot)
                game = c64_port.by_key(party[0].deltas.key)
            except Exception as e:
                notes.append(f"{folder.name} slot {slot}: "
                             f"{type(e).__name__}: {e}")
                continue
            for char in party:
                try:
                    add(_dos_row(char, game, folder.name))
                except Exception as e:
                    notes.append(f"{folder.name} slot {slot} {char.name}: "
                                 f"{type(e).__name__}: {e}")

    pool = c64_port.by_key(c64_port.POOL_OF_RADIANCE.key)
    for image in amiga_disks():
        try:
            disk = AmigaDisk(bytearray(image.read_bytes()))
        except Exception as e:                                # pragma: no cover
            notes.append(f"{image.name}: {type(e).__name__}: {e}")
            continue
        for slot in amiga_savegame.por_slots_present(disk):
            try:
                drawer = amiga_savegame.por_save_drawer(disk)
                for index in range(1, amiga_savegame.PARTY_MAX + 1):
                    files = [amiga_savegame._por_file(disk, slot, index,
                                                      suffix, drawer)
                             for suffix in (".sav", ".itm", ".spc")]
                    if files[0] is None:
                        break
                    char = amiga_por.por_character(
                        files[0], files[1] or b"", files[2] or b"")
                    add(_amiga_por_row(
                        char, pool, f"{image.parent.name}/{slot}{index}"))
            except Exception as e:
                notes.append(f"{image.parent.name} slot {slot}: "
                             f"{type(e).__name__}: {e}")
        for slot in amiga_savegame.slots_present(disk):
            try:
                save = amiga_savegame.read_slot(disk, slot)
            except Exception as e:
                notes.append(f"{image.parent.name} slot {slot}: "
                             f"{type(e).__name__}: {e}")
                continue
            _later_rows(save, f"{image.parent.name}/{slot}",
                        notes, add)

    for path in amiga_later_saves():
        try:
            save = amiga_savegame.parse(path.read_bytes())
        except Exception as e:
            notes.append(f"{path.parent.name}/{path.name}: "
                         f"{type(e).__name__}: {e}")
            continue
        _later_rows(save, f"{path.parent.name}/{path.name}", notes, add)
    return rows, notes, seen


def _later_rows(save, specimen: str, notes: list[str], add) -> None:
    for char in save.characters:
        try:
            game = c64_port.by_key(char.deltas.key)
        except Exception as e:
            notes.append(f"{specimen} {char.name}: {type(e).__name__}: {e}")
            continue
        try:
            add(_amiga_later_row(char, game, specimen))
        except Exception as e:
            notes.append(f"{specimen} {char.name}: {type(e).__name__}: {e}")


def no_op() -> tuple[collections.Counter, list[str]]:
    """Rewrite every character with nothing edited, and count the ones that
    came back byte for byte.

    Every character is guarded on its own: one that cannot be read, or whose
    rewrite raises, is listed and the sweep goes on, because a count taken
    over whatever was reached before the first exception is not a count.
    """
    tally: collections.Counter = collections.Counter()
    bad: list[str] = []

    def check(label, port, title, record_ok, items_ok, effects_ok) -> None:
        tally[(port, title, "read")] += 1
        if record_ok and items_ok and effects_ok:
            tally[(port, title, "identical")] += 1
        else:
            bad.append(f"{label}: record {record_ok}, items {items_ok}, "
                       f"effects {effects_ok}")

    def nodes(char) -> bytes:
        return b"".join(rewrite.node_bytes(i) for i in char.items)

    for folder in dos_folders():
        try:
            slots = dos_codec.slots_available(folder)
        except Exception as e:
            bad.append(f"{folder}: {type(e).__name__}: {e}")
            continue
        for slot in slots:
            try:
                party = dos_codec.read_party(folder, slot)
                game = c64_port.by_key(party[0].deltas.key)
            except Exception as e:
                bad.append(f"{folder.name} {slot}: {type(e).__name__}: {e}")
                continue
            for char in party:
                label = f"{folder.name}/{slot} {char.name}"
                try:
                    rec, _ = dos_codec.to_c64_record(char)
                    out = rewrite.rewrite_dos(char, rec, rec, game)
                except Exception as e:
                    bad.append(f"{label}: {type(e).__name__}: {e}")
                    continue
                check(label, "DOS", char.deltas.title,
                      out.record == char.to_bytes(),
                      out.items == nodes(char),
                      out.effects == b"".join(bytes(e)
                                              for e in char.effects))

    pool = c64_port.by_key(dos_port.POOL_OF_RADIANCE.key)
    for image in amiga_disks():
        try:
            disk = AmigaDisk(bytearray(image.read_bytes()))
            drawer = amiga_savegame.por_save_drawer(disk)
            por_slots = amiga_savegame.por_slots_present(disk)
            later_slots = amiga_savegame.slots_present(disk)
        except Exception as e:
            bad.append(f"{image.parent.name}: {type(e).__name__}: {e}")
            continue
        for slot in por_slots:
            for index in range(1, amiga_savegame.PARTY_MAX + 1):
                label = f"{image.parent.name}/{slot}{index}"
                try:
                    files = [amiga_savegame._por_file(disk, slot, index,
                                                      suffix, drawer)
                             for suffix in (".sav", ".itm", ".spc")]
                    if files[0] is None:
                        break
                    char = amiga_por.por_character(files[0], files[1] or b"",
                                                   files[2] or b"")
                    rec, _ = dos_codec.to_c64_record(
                        amiga_por.to_dos_character(char))
                    out = rewrite.rewrite_amiga_por(char, rec, rec, pool)
                except Exception as e:
                    bad.append(f"{label}: {type(e).__name__}: {e}")
                    continue
                check(label, "Amiga", "Pool of Radiance",
                      out.record == char.raw, out.items == nodes(char),
                      out.effects == b"".join(bytes(e)
                                              for e in char.effects))
        for slot in later_slots:
            label = f"{image.parent.name}/{slot}"
            try:
                save = amiga_savegame.read_slot(disk, slot)
            except Exception as e:
                bad.append(f"{label}: {type(e).__name__}: {e}")
                continue
            _no_op_later(save, label, check, bad)

    for path in amiga_later_saves():
        label = f"{path.parent.name}/{path.name}"
        try:
            save = amiga_savegame.parse(path.read_bytes())
        except Exception as e:
            bad.append(f"{label}: {type(e).__name__}: {e}")
            continue
        _no_op_later(save, label, check, bad)
    return tally, bad


def _no_op_later(save, label: str, check, bad: list[str]) -> None:
    for char in save.characters:
        try:
            game = c64_port.by_key(char.deltas.key)
            rec, _ = dos_codec.neutral_to_c64_record(
                amiga_later.to_neutral_later(char))
            written = rewrite.rewrite_amiga_later(char, rec, rec,
                                                  game).character
        except Exception as e:
            bad.append(f"{label} {char.name}: {type(e).__name__}: {e}")
            continue
        check(f"{label} {char.name}", "Amiga", char.deltas.title,
              written.raw == char.raw,
              written.block_bytes() == char.block_bytes(),
              [bytes(e) for e in written.effects]
              == [bytes(e) for e in char.effects])


# ---------------------------------------------------------------------------
# What an edit cannot reach: the read-only fields, per port
# ---------------------------------------------------------------------------
#: How many characters of each port and title the read-only sweep fuzzes.
#: One character answers for the fields nothing writes at all; several are
#: what catch a field one character's class or race cannot move and another's
#: can.
READ_ONLY_SAMPLE = 12


def _fuzz(before, name: str, at: int):
    """The record with one added to byte `at` of the field called `name`."""
    after = record.CharacterRecord(before.to_bytes(), before.stored_size)
    raw = bytearray(after.get_raw(name))
    raw[at] = (raw[at] + 1) & 0xFF
    after.set_raw(name, bytes(raw))
    return after


def field_verdicts(before, do) -> dict[str, str]:
    """Per C64 record field, whether an edit to it reaches the port's save.

    Each field is fuzzed at its first byte and at its last, because a field
    whose padding was all that moved reads as read-only when it is not.  A
    fuzz the rewrite refuses with `RewriteError` *is* the read-only answer --
    that is the refusal it raises when an edit lands nowhere -- and one that
    raises anything else is an illegal value rather than a verdict.
    """
    baseline = do(before)
    out: dict[str, str] = {}
    for f in layout.LAYOUT:
        if not before.is_stored(f.name):
            continue
        verdict = "read-only"
        for at in sorted({0, f.size - 1}):
            after = _fuzz(before, f.name, at)
            if after.to_bytes() == before.to_bytes():
                continue
            try:
                if do(after) != baseline:
                    verdict = "writable"
                    break
            except rewrite.RewriteError:
                continue
            except Exception:
                if verdict == "read-only":
                    verdict = "refused"
        out[f.name] = verdict
    return out


def _sample(limit: int, notes: list[str]):
    """Up to `limit` characters of each port and title, each with the C64
    record the sheet would edit and a way to write an edited one back."""
    taken: collections.Counter = collections.Counter()

    def room(key) -> bool:
        return taken[key] < limit

    for folder in dos_folders():
        try:
            slots = dos_codec.slots_available(folder)
        except Exception as e:
            notes.append(f"{folder}: {type(e).__name__}: {e}")
            continue
        for slot in slots:
            try:
                party = dos_codec.read_party(folder, slot)
                game = c64_port.by_key(party[0].deltas.key)
            except Exception as e:
                notes.append(f"{folder.name} {slot}: {type(e).__name__}: {e}")
                continue
            for char in party:
                key = ("DOS", char.deltas.title)
                if not room(key):
                    continue
                rec, _ = dos_codec.to_c64_record(char)

                def do(after, char=char, before=rec, game=game):
                    out = rewrite.rewrite_dos(char, before, after, game)
                    return out.record + out.items

                taken[key] += 1
                yield key, f"{folder.name}/{slot} {char.name}", rec, do

    pool = c64_port.by_key(dos_port.POOL_OF_RADIANCE.key)
    for image in amiga_disks():
        try:
            disk = AmigaDisk(bytearray(image.read_bytes()))
            drawer = amiga_savegame.por_save_drawer(disk)
            por_slots = amiga_savegame.por_slots_present(disk)
            later_slots = amiga_savegame.slots_present(disk)
        except Exception as e:
            notes.append(f"{image.parent.name}: {type(e).__name__}: {e}")
            continue
        key = ("Amiga", "Pool of Radiance")
        for slot in por_slots:
            for index in range(1, amiga_savegame.PARTY_MAX + 1):
                if not room(key):
                    break
                try:
                    files = [amiga_savegame._por_file(disk, slot, index,
                                                      suffix, drawer)
                             for suffix in (".sav", ".itm", ".spc")]
                    if files[0] is None:
                        break
                    char = amiga_por.por_character(files[0], files[1] or b"",
                                                   files[2] or b"")
                    rec, _ = dos_codec.to_c64_record(
                        amiga_por.to_dos_character(char))
                except Exception as e:
                    notes.append(f"{image.parent.name}/{slot}{index}: "
                                 f"{type(e).__name__}: {e}")
                    continue

                def do(after, char=char, before=rec):
                    out = rewrite.rewrite_amiga_por(char, before, after, pool)
                    return out.record + out.items

                taken[key] += 1
                yield (key, f"{image.parent.name}/{slot}{index}", rec, do)
        for slot in later_slots:
            try:
                save = amiga_savegame.read_slot(disk, slot)
            except Exception as e:
                notes.append(f"{image.parent.name}/{slot}: "
                             f"{type(e).__name__}: {e}")
                continue
            yield from _sample_later(save, f"{image.parent.name}/{slot}",
                                     taken, limit, notes)

    for path in amiga_later_saves():
        try:
            save = amiga_savegame.parse(path.read_bytes())
        except Exception as e:
            notes.append(f"{path.parent.name}/{path.name}: "
                         f"{type(e).__name__}: {e}")
            continue
        yield from _sample_later(save, f"{path.parent.name}/{path.name}",
                                 taken, limit, notes)


def _sample_later(save, label: str, taken, limit: int, notes: list[str]):
    for char in save.characters:
        key = ("Amiga", char.deltas.title)
        if taken[key] >= limit:
            continue
        try:
            game = c64_port.by_key(char.deltas.key)
            rec, _ = dos_codec.neutral_to_c64_record(
                amiga_later.to_neutral_later(char))
        except Exception as e:
            notes.append(f"{label} {char.name}: {type(e).__name__}: {e}")
            continue

        def do(after, char=char, before=rec, game=game):
            return rewrite.rewrite_amiga_later(
                char, before, after, game).character.block_bytes()

        taken[key] += 1
        yield key, f"{label} {char.name}", rec, do


def read_only(limit: int = READ_ONLY_SAMPLE) -> tuple[dict, dict, list[str]]:
    """Per port and title, every field's verdict over the characters read."""
    verdicts: dict = collections.defaultdict(
        lambda: collections.defaultdict(set))
    counts: collections.Counter = collections.Counter()
    notes: list[str] = []
    for key, label, rec, do in _sample(limit, notes):
        try:
            found = field_verdicts(rec, do)
        except Exception as e:
            notes.append(f"{label}: {type(e).__name__}: {e}")
            continue
        counts[key] += 1
        for name, verdict in found.items():
            verdicts[key][name].add(verdict)
    return verdicts, counts, notes


def declared_unsourced(deltas) -> dict[str, str]:
    """This title's fields the writer declares it takes from something other
    than a neutral value -- a constant, a default, a zero or a derivation."""
    return {name: why for name, why in dos_codec.write_targets(deltas).items()
            if not why.startswith("from neutral")}


def unreachable() -> dict[str, list[tuple[str, str]]]:
    """Per DOS title, the fields the writer declares it does not source from
    a neutral value."""
    return {d.title: sorted(declared_unsourced(d).items())
            for d in dos_port.DELTAS}


# ---------------------------------------------------------------------------
# Printing
# ---------------------------------------------------------------------------
def _print_census(rows: list[Row], notes: list[str], seen: dict,
                  per_specimen: bool) -> None:
    by_title: dict[tuple[str, str], list[Row]] = collections.defaultdict(list)
    for row in rows:
        by_title[(row.port, row.title)].append(row)

    print(f"{len(rows)} characters examined\n")
    for (port, title), group in sorted(by_title.items()):
        tally: collections.Counter = collections.Counter()
        for row in group:
            tally.update(row.fields)
        clean = sum(1 for row in group if not row.fields)
        declared = declared_unsourced(group[0].deltas)
        varied = {n for n, values in seen[(port, title)].items()
                  if len(values) > 1}
        print(f"## {port} {title}  ({len(group)} characters, "
              f"{clean} with no field moved)\n")
        if group[0].unplaced:
            print(f"    no span at all, so never written: "
                  f"{', '.join(group[0].unplaced)}\n")
        if not tally:
            print("    every field round-trips byte for byte\n")
            continue
        print(f"    {'field':30s} {'chars':>6s}  {'rendered':10s} "
              f"{'writer says':12s}")
        for name, count in sorted(tally.items(),
                                  key=lambda kv: (-kv[1], kv[0])):
            says = declared.get(name, "from neutral").split(":")[0]
            print(f"    {name:30s} {count:6d}  "
                  f"{'varies' if name in varied else 'one value':10s} "
                  f"{says:12s}")
        reach = sorted(n for n in tally if n in varied)
        fixed = sorted(n for n in tally if n not in varied)
        print(f"\n    no edit can move these: the writer rendered one value "
              f"for all {len(group)} characters -- {', '.join(fixed) or '-'}")
        print(f"\n    read-only candidates ({len(reach)} of {len(tally)}): "
              f"{', '.join(reach)}\n")

    if per_specimen:
        print("## Per character\n")
        for row in rows:
            print(f"    {row.port:6s} {row.specimen:44s} {row.name:18s} "
                  f"{', '.join(row.fields) or '-'}")
        print()

    if notes:
        print(f"## {len(notes)} things not examined\n")
        for note in notes:
            print(f"    {note}")


def _print_read_only(verdicts: dict, counts: dict, notes: list[str]) -> None:
    print(f"{sum(counts.values())} characters fuzzed, up to "
          f"{READ_ONLY_SAMPLE} per port and title\n")
    for key in sorted(verdicts):
        port, title = key
        found = verdicts[key]
        stuck = sorted(n for n, v in found.items() if v == {"read-only"})
        mixed = sorted(n for n, v in found.items()
                       if "writable" in v and "read-only" in v)
        refused = sorted(n for n, v in found.items()
                         if "writable" not in v and "refused" in v)
        print(f"## {port} {title}  ({counts[key]} characters)\n")
        print(f"    read-only on all {counts[key]} ({len(stuck)}): "
              f"{', '.join(stuck) or '-'}\n")
        print(f"    read-only on some and not others ({len(mixed)}): "
              f"{', '.join(mixed) or '-'}\n")
        print(f"    no verdict, every fuzz was an illegal value "
              f"({len(refused)}): {', '.join(refused) or '-'}\n")
    if notes:
        print(f"## {len(notes)} things not examined\n")
        for note in notes:
            print(f"    {note}")


def main(argv: "list[str] | None" = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--no-op", action="store_true", dest="no_op",
                        help="rewrite everything with nothing edited")
    parser.add_argument("--read-only", action="store_true", dest="read_only",
                        help="fuzz every field and list what no edit moves")
    parser.add_argument("--sample", type=int, default=READ_ONLY_SAMPLE,
                        help="characters per port and title to fuzz")
    parser.add_argument("--unreachable", action="store_true",
                        help="list the fields no sheet edit can reach")
    parser.add_argument("--per-specimen", action="store_true",
                        help="also print one line per character")
    args = parser.parse_args(argv)

    if args.no_op:
        tally, bad = no_op()
        titles = sorted({(port, title) for port, title, _ in tally})
        for port, title in titles:
            print(f"    {port} {title:32s} "
                  f"{tally[(port, title, 'identical')]} of "
                  f"{tally[(port, title, 'read')]} byte for byte")
        read = sum(v for k, v in tally.items() if k[2] == "read")
        print(f"\n    {sum(v for k, v in tally.items() if k[2] == 'identical')}"
              f" of {read} characters in all")
        for line in bad:
            print(f"    {line}")
        if not read:
            print("    0 characters were readable: there is nothing here to "
                  "measure, which is not the same as nothing being wrong")
            return 1
        return 1 if bad else 0

    if args.read_only:
        verdicts, counts, notes = read_only(args.sample)
        _print_read_only(verdicts, counts, notes)
        return 0 if counts else 1

    if args.unreachable:
        for title, fields in unreachable().items():
            print(f"## {title}  ({len(fields)} fields)\n")
            for name, why in fields:
                print(f"    {name:28s} {why}")
            print()
        return 0

    rows, notes, seen = census()
    _print_census(rows, notes, seen, args.per_specimen)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
