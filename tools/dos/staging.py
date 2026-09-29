"""Puts a saved game, and the inputs an acceptance run stages, into a DOS save folder.

`install` copies one slot of a Wish-written save into a staged `SAVE` tree, and
`stage_hall`, `stage_var`, `stage_xp`, `stage_record` and `stage_node` edit the installed records before the
game boots.
"""
from __future__ import annotations

import pathlib
import re

from goldbox import dos_codec, dos_savegame

#: `SAVGAM<slot>.DAT`'s training-hall word and the value `--hall` writes:
#: every class bit, so every character's school is open
#: (`tools/curse_of_the_azure_bonds/curseregain.py`, `EVERY_CLASS`).
HALL_WORD = 0xD51
HALL_OPEN = 0x00FF
#: The titles whose training hall word is documented at `HALL_WORD`
#: (`docs/194-the-dos-training-ladder.md`).
HALL_TITLES = frozenset({"pool", "curse", "ssb"})


def node_dict(node: bytes) -> dict:
    return {"id": node[0], "minutes": node[1] | node[2] << 8,
            "data": node[3], "flag": node[4], "raw": node[:5].hex()}


_SAVGAM = re.compile(r"SAVGAM([A-J])(\.DAT|\.PTY)")


def containers_in(save: pathlib.Path) -> dict[str, str]:
    """Slot letter -> saved-game suffix, `.DAT` or Pools of Darkness' `.PTY`,
    for every `SAVGAM?` file in `save`, whatever the case."""
    out: dict[str, str] = {}
    for p in save.iterdir():
        m = _SAVGAM.fullmatch(p.name.upper())
        if m:
            out[m.group(1)] = m.group(2)
    return out


def slots_in(save: pathlib.Path) -> list[str]:
    """The slot letters `save` holds a `SAVGAM?.DAT` or `.PTY` for."""
    return sorted(containers_in(save))


def source_slot(save: pathlib.Path, wanted: str | None = None) -> str:
    """The one slot of `save` to install: `wanted`, or the only one there is."""
    slots = slots_in(save)
    if wanted:
        if wanted.upper() not in slots:
            raise FileNotFoundError(f"{save} holds no SAVGAM{wanted.upper()} saved "
                                    f"game (it holds {', '.join(slots) or 'none'})")
        return wanted.upper()
    if len(slots) != 1:
        raise FileNotFoundError(
            f"{save} holds {len(slots)} SAVGAM?.DAT or .PTY files; one is wanted "
            "(name it with --from-slot)")
    return slots[0]


def install(save: pathlib.Path, save_dir: pathlib.Path, letter: str,
            source: str | None = None) -> dict:
    """Empty `save_dir` and put slot `source` of `save` into it as `letter`.

    The staged tree's own `SAVE` is the archives' copy, which is the edited
    play directory (`.claude/rules/testing.md`), so none of it is kept.
    A rename is refused: the saved game names its own `CHRDAT` files and the
    engine loads those, so a slot under another letter loads no party.  A
    Pools of Darkness slot is its `SAVGAM<slot>.PTY`, its `VAULT<slot>.DAT`
    and its `CHRDAT` files, which is what `dos_codec.new_pod_save_from` writes.
    """
    source = source_slot(save, source)
    suffix = containers_in(save)[source]
    letter = letter.upper()
    if source != letter:
        raise ValueError(f"the saved game names its own files and the engine "
                         f"loads those; install {source} as {source}, not {letter}")
    for old in save_dir.glob("*"):
        if old.is_file():
            old.unlink()
    took = {"from_slot": source, "as_slot": letter, "files": []}
    for p in sorted(save.iterdir()):
        name = p.name.upper()
        if name == f"SAVGAM{source}{suffix}":
            dest = f"SAVGAM{letter}{suffix}"
        elif suffix == ".PTY" and name == f"VAULT{source}.DAT":
            dest = f"VAULT{letter}.DAT"
        elif name.startswith(f"CHRDAT{source}"):
            dest = f"CHRDAT{letter}{name[7:]}"
        else:
            continue
        (save_dir / dest).write_bytes(p.read_bytes())
        took["files"].append(dest)
    return took


def stage_hall(save_dir: pathlib.Path, letter: str) -> dict:
    """Open every school: the word at `SAVGAM+0xD51` becomes `0x00FF`."""
    path = save_dir / f"SAVGAM{letter.upper()}.DAT"
    data = bytearray(path.read_bytes())
    if len(data) < HALL_WORD + 2:
        # A slice assignment past the end of a bytearray appends.
        raise ValueError(f"{path.name} is {len(data)} bytes, too short for the "
                         f"hall word at {HALL_WORD:#x}")
    before = bytes(data[HALL_WORD:HALL_WORD + 2])
    data[HALL_WORD:HALL_WORD + 2] = HALL_OPEN.to_bytes(2, "little")
    path.write_bytes(bytes(data))
    return {"stage": "hall", "file": path.name, "offset": hex(HALL_WORD),
            "before": before.hex(), "after": data[HALL_WORD:HALL_WORD + 2].hex()}


def stage_var(save_dir: pathlib.Path, letter: str, address: int, value: int) -> dict:
    """Write `value` into the script-variable word at `address` of `SAVGAM<letter>.DAT`.

    `address` is the title's own ECL address (`$4C2D` in Silver Blades), which
    `dos_savegame.pool_address` turns into the word index the file is laid out by.
    """
    path = save_dir / f"SAVGAM{letter.upper()}.DAT"
    data = bytearray(path.read_bytes())
    if not 0 <= value <= 0xFFFF:
        raise ValueError(f"value {value} is not one word")
    container = dos_savegame.container_for(len(data))
    index = dos_savegame.pool_address(address, container)
    offset = dos_savegame.word_offset(index, container)
    before = bytes(data[offset:offset + 2])
    dos_savegame.put_word(data, index, value, container)
    path.write_bytes(bytes(data))
    return {"stage": "var", "file": path.name, "address": f"{address:#06x}",
            "offset": hex(offset), "before": before.hex(),
            "after": bytes(data[offset:offset + 2]).hex()}


def stage_xp(save_dir: pathlib.Path, letter: str, line: int, xp: int) -> dict:
    """Write `xp` into roster line `line`'s `experience` field."""
    path = save_dir / f"CHRDAT{letter.upper()}{line}.SAV"
    c = dos_codec.read_character(path)
    f = c.fields["experience"]
    data = bytearray(path.read_bytes())
    before = bytes(data[f.offset:f.offset + f.size])
    data[f.offset:f.offset + f.size] = xp.to_bytes(f.size, "little")
    path.write_bytes(bytes(data))
    return {"stage": "xp", "file": path.name, "name": c.name,
            "offset": hex(f.offset), "before": before.hex(),
            "after": data[f.offset:f.offset + f.size].hex()}


def stage_control(save_dir: pathlib.Path, letter: str, line: int, control: int,
                   share: int | None = None) -> dict:
    """Write `control` into roster line `line`'s `field_83_87` control byte,
    and `share` into the byte after it when given, at the same index
    `goldbox.dos_codec.to_neutral` reads them from."""
    path = save_dir / f"CHRDAT{letter.upper()}{line}.SAV"
    c = dos_codec.read_character(path)
    f = c.fields["field_83_87"]
    control_index = 1 if f.size == 5 else 0
    offset = f.offset + control_index
    data = bytearray(path.read_bytes())
    result = {"stage": "control", "file": path.name, "name": c.name,
              "offset": hex(offset), "before": bytes(data[offset:offset + 1]).hex()}
    data[offset] = control & 0xFF
    result["after"] = bytes(data[offset:offset + 1]).hex()
    if share is not None:
        share_offset = offset + 1
        result["share_offset"] = hex(share_offset)
        result["share_before"] = bytes(data[share_offset:share_offset + 1]).hex()
        data[share_offset] = share & 0xFF
        result["share_after"] = bytes(data[share_offset:share_offset + 1]).hex()
    path.write_bytes(bytes(data))
    return result


def stage_record(save_dir: pathlib.Path, letter: str, line: int, offset: int,
                 value: int) -> dict:
    """Write `value` at `offset` of roster line `line`'s `CHRDAT` record.

    The offset must lie inside the file: a write past the end of a bytearray
    would grow the record, which no game wrote.
    """
    path = save_dir / f"CHRDAT{letter.upper()}{line}.SAV"
    data = bytearray(path.read_bytes())
    if not 0 <= offset < len(data):
        raise ValueError(f"offset {offset:#x} is outside {path.name}, "
                         f"which is {len(data)} bytes")
    if not 0 <= value <= 0xFF:
        raise ValueError(f"value {value} is not one byte")
    name = dos_codec.read_character(path).name
    before = data[offset]
    data[offset] = value
    path.write_bytes(bytes(data))
    return {"stage": "record", "file": path.name, "name": name,
            "offset": hex(offset), "before": f"{before:02x}",
            "after": f"{value:02x}"}


def stage_node(save_dir: pathlib.Path, letter: str, line: int, node: bytes) -> dict:
    """Append one effect node, its five bytes and a NULL next pointer, to line `line`."""
    record = save_dir / f"CHRDAT{letter.upper()}{line}.SAV"
    c = dos_codec.read_character(record)
    path = record.with_suffix(dos_codec.deltas_for(len(record.read_bytes()))
                              .effect_suffix)
    was = path.read_bytes() if path.is_file() else b""
    full = node[:5] + bytes(dos_codec.EFFECT_SIZE - 5)
    path.write_bytes(was + full)
    return {"stage": "node", "file": path.name, "name": c.name,
            "at": len(was), "bytes": full.hex(), "node": node_dict(full)}
