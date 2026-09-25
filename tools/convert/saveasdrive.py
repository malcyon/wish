"""Publish a conversion through the editor's Save As route, for the developer tools.

Opens `source` as the editor does, then calls `saveplan.prepare_save_as` and
`saveplan.publish` -- the two calls Save As makes -- so what the tool boots is
the rehearsed bytes Save As publishes and not what `File > Convert...` writes.
No dialog exists here, so a refusal is returned as `report["refused"]` with the
exception's own words. Imports of `editor` are lazy so a caller can point
`sys.path` at another checkout first.
"""
from __future__ import annotations

import datetime
import pathlib
from typing import Any

#: The file a Save As writes for a destination that is a single image.
IMAGE_NAMES = {"c64": "WISHSAVE.D64", "amiga": "POOLSAVE.ADF"}


def destination_path(port: str, folder: pathlib.Path) -> pathlib.Path:
    """Where a tool's Save As lands: a dated folder under `folder`, holding
    the image, or being the DOS save folder itself."""
    dated = pathlib.Path(folder) / f"wish-{datetime.date.today().isoformat()}"
    return dated if port == "dos" else dated / IMAGE_NAMES[port]


def save_as(window: Any, source: "str | pathlib.Path", port: str,
            folder: "str | pathlib.Path", *,
            c64_folder: "str | pathlib.Path | None" = None,
            dos_folder: "str | pathlib.Path | None" = None,
            amiga_disk: "str | pathlib.Path | None" = None) -> dict:
    """Open `source`, Save As it to `port` under `folder`, and say what landed.

    `window` is an `EditorBinding`, whose `game_files_for` finds the game data
    a route needs. The report carries `written` (paths), `slot`, `losses` and
    `dropped` from the conversion's accounting, or `refused` -- the exception's
    class and text -- when Save As refused or failed.
    """
    from editor import saveplan
    from editor.convert import Source
    from editor.roster import Party

    report: dict = {"source": str(source), "to": port, "folder": str(folder)}
    path = destination_path(port, pathlib.Path(folder))
    report["destination"] = str(path)
    try:
        detected = Source.detect(source)
        party = Party(detected)
        assets = saveplan.resolve_assets(
            Source.of_snapshot(saveplan.prepare(party)), port,
            game_files=window.game_files_for, c64_folder=c64_folder,
            dos_folder=dos_folder, amiga_disk=amiga_disk)
        plan = saveplan.prepare_save_as(party, port, path, assets)
        report["losses"] = saveplan.losses(plan.report) if plan.report else []
        report["dropped"] = list(getattr(plan.report, "dropped", []) or [])
        published = saveplan.publish(plan, party, assets=assets)
    except Exception as exc:
        report["refused"] = [type(exc).__name__, str(exc)]
        report["error"] = str(exc)
        return report
    report["slot"] = plan.destination.slot
    report["written"] = [str(p) for p in published.written]
    return report
