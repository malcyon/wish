"""What a save would write, in the form `wish --dry-run` already prints it.

Everything is compared against the bytes as they were read, never against a
dirty flag: the question a preview answers is "what will reach the disk", and
an edit typed and typed back has changed nothing.

    based on PORSAVE11.D64
      slot 0 MALCYON: gold 100 -> 1234
      slot 0 MALCYON: item 6 DART quantity 13 -> 9

    2 change(s) (nothing written yet)
"""

from __future__ import annotations

from por.layout import LAYOUT, Kind
from por.record import CharacterRecord

from .inventory import describe as describe_item

SLOT_BYTES = 0x100


def _shown(field, value) -> str:
    if field.kind is Kind.RAW:
        return bytes(value).hex()
    return repr(value)


def record_changes(member, *, in_save: bool) -> list[str]:
    """Field-by-field, against the record as it was read."""
    if member.record_original is None:
        return []
    was = CharacterRecord.from_bytes(member.record_original)
    now = member.record
    if was == now:
        return []
    limit = SLOT_BYTES if in_save else len(now)
    out = []
    for field in LAYOUT:
        if field.offset >= limit:
            continue        # a save slot holds 256 bytes; the rest is dropped
        old, new = was.get(field.name), now.get(field.name)
        if old != new:
            out.append(f"{field.name} {_shown(field, old)} -> "
                       f"{_shown(field, new)}")
    return out


def item_changes(member) -> list[str]:
    inv = member.inventory
    if inv is None or not inv.changed:
        return []
    out = []
    for n in range(len(inv)):
        old, new = inv.original[n], inv.raws[n]
        if old == new:
            continue
        was, is_ = inv.original_item(n), inv.item(n)
        if not any(old):
            out.append(f"item {n} added: {describe_item(is_, inv.names)}")
        elif not any(new):
            out.append(f"item {n} removed: {describe_item(was, inv.names)}")
        elif was.name != is_.name or was.raw[:4] != is_.raw[:4]:
            out.append(f"item {n} {describe_item(was, inv.names)} -> "
                       f"{describe_item(is_, inv.names)}")
        else:
            for what, a, b in (("quantity", was.quantity, is_.quantity),
                               ("readied", was.readied, is_.readied),
                               ("identified", was.is_identified,
                                is_.is_identified),
                               ("bonus", was.bonus, is_.bonus)):
                if a != b:
                    out.append(f"item {n} {describe_item(is_, inv.names)} "
                               f"{what} {a!r} -> {b!r}")
            if old[:4] == new[:4] and not out:
                out.append(f"item {n} {describe_item(is_, inv.names)} "
                           f"{old.hex()} -> {new.hex()}")
    return out


def icon_changes(member) -> list[str]:
    if member.icon is None or member.icon == member.icon_original:
        return []
    was, now = member.icon_original.raw, member.icon.raw
    cells = sum(1 for a, b in zip(was, now) if a != b)
    return [f"combat icon: {cells} of {len(was)} bytes changed"]


def changes(party) -> list[str]:
    """Every change the whole file would take, one line each."""
    out = []
    for member in party.members:
        who = f"slot {member.index} {member.record.name}"
        for line in (record_changes(member, in_save=party.in_save)
                     + item_changes(member) + icon_changes(member)):
            out.append(f"{who}: {line}")
    return out


def preview(party, path) -> str:
    """The whole report, in the shape `--dry-run` prints."""
    lines = changes(party)
    head = f"based on {path}"
    if not lines:
        return f"{head}\nno changes"
    body = "\n".join(f"  {line}" for line in lines)
    return (f"{head}\n{body}\n\n{len(lines)} change(s) "
            f"(nothing written yet)")
