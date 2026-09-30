"""Publish a conversion through the editor's Save As route, for the developer tools.

Opens `source` as the editor does, resolves the destination's game data, then
calls `saveplan.prepare_save_as` and `saveplan.publish`, so what the tool boots
is the rehearsed bytes Save As publishes and not what `File > Convert...`
writes. It does not call `refuse_alias`, flush edits or confirm a replacement:
the destination is always a new dated folder under `folder`, so it can neither
be the source nor replace a file. No dialog exists here, so a refusal is
returned as `report["refused"]` with the exception's own words. Imports of `editor` are lazy so a caller can point
`sys.path` at another checkout first.
"""
from __future__ import annotations

import datetime
import pathlib
from collections.abc import Collection, Mapping
from typing import Any

#: The file a Save As writes for a destination that is a single image.
IMAGE_NAMES = {"c64": "WISHSAVE.D64", "amiga": "POOLSAVE.ADF"}


def destination_path(port: str, folder: pathlib.Path) -> pathlib.Path:
    """Where a tool's Save As lands: a dated folder under `folder`, holding
    the image, or being the DOS save folder itself. A folder already there
    from an earlier run is left alone and the next free `-2`, `-3`... is used,
    so a re-run into the same `folder` never meets a non-empty target."""
    stem = f"wish-{datetime.date.today().isoformat()}"
    dated = pathlib.Path(folder) / stem
    n = 1
    while dated.exists():
        n += 1
        dated = pathlib.Path(folder) / f"{stem}-{n}"
    return dated if port == "dos" else dated / IMAGE_NAMES[port]


def save_as(window: Any, source: "str | pathlib.Path", port: str,
            folder: "str | pathlib.Path", *,
            c64_folder: "str | pathlib.Path | None" = None,
            dos_folder: "str | pathlib.Path | None" = None,
            amiga_disk: "str | pathlib.Path | None" = None,
            amiga_disk_one: "str | pathlib.Path | None" = None,
            source_slot: "str | None" = None,
            names: "Mapping[int, str] | None" = None,
            leave_effects: "Mapping[int, Collection[int]] | None" = None
            ) -> dict:
    """Open `source`, Save As it to `port` under `folder`, and say what landed.

    `window` is an `EditorBinding`, whose `game_files_for` finds the game data
    a route needs. The report carries `written` (paths), `slot`, `losses` and
    `dropped` from the conversion's accounting, or `refused` -- the exception's
    class and text -- when Save As refused or failed.

    `source_slot` names which of a DOS folder's or an Amiga disk's several
    saved games to read, the same letter `editor.convert.Source.detect`
    itself takes; `None` keeps its own default, the alphabetically first slot
    the source holds.

    `names` is the `{position: name}` a player would choose in the Shorten
    window, handed to `prepare_save_as`. A name too long for the destination
    with no choice for it is refused as `NamesDoNotFit`, and the report then
    also carries `unfit` (`[position, name]` for each) and `width`, so a caller
    can see which names needed a choice and not only that Save As refused.

    `leave_effects` is the `{member: running-effect indices}` a player would
    tick in the window that opens when the party's running effects need more
    rows than the C64's shared table holds. A party still over is refused as
    `EffectsDoNotFit`, and the report then also carries `effects_needed`,
    `effects_limit` and `effect_entries` (`[member, index, effect id,
    minutes]` for each effect that can be left out).
    """
    from editor import saveplan
    from editor.convert import Source
    from editor.roster import Party
    from goldbox import dos_codec

    report: dict = {"source": str(source), "to": port, "folder": str(folder)}
    path = destination_path(port, pathlib.Path(folder))
    report["destination"] = str(path)
    try:
        detected = Source.detect(source, slot=source_slot)
        party = Party(detected)
        assets = saveplan.resolve_assets(
            Source.of_snapshot(saveplan.prepare(party)), port,
            game_files=window.game_files_for, c64_folder=c64_folder,
            dos_folder=dos_folder, amiga_disk=amiga_disk,
            amiga_disk_one=amiga_disk_one)
        plan = saveplan.prepare_save_as(
            party, port, path, assets,
            **({"names": names} if names is not None else {}),
            **({"leave_effects": leave_effects} if leave_effects else {}))
        report["losses"] = saveplan.losses(plan.report) if plan.report else []
        report["dropped"] = list(getattr(plan.report, "dropped", []) or [])
        published = saveplan.publish(plan, party, assets=assets)
    except Exception as exc:
        if isinstance(exc, saveplan.NamesDoNotFit):
            report["unfit"] = [[position, name] for position, name in exc.unfit]
            report["width"] = exc.width
        if isinstance(exc, dos_codec.EffectsDoNotFit):
            over = exc.overflow
            report["effects_needed"] = over.needed
            report["effects_limit"] = over.limit
            report["effect_entries"] = [list(e) for e in over.entries]
        report["refused"] = [type(exc).__name__, str(exc)]
        report["error"] = f"{type(exc).__name__}: {exc}"
        return report
    report["slot"] = plan.destination.slot
    report["written"] = [str(p) for p in published.written]
    return report
