"""Settings that survive closing the window.

Small and hand-editable on purpose: a JSON file you can look at and fix. An
unreadable or half-written file is treated as "no settings yet" rather than as
an error -- losing a preference is not worth refusing to start over.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields

from .paths import config_dir

FILE = "automap.json"


@dataclass
class Settings:
    """Everything the map remembers between runs."""

    # On by default -- discovering the map is the point -- but the choice is
    # remembered, so turning it off stays off.
    reveal: bool = True
    interval_ms: int = 200
    # Which live backend to prefer when more than one answers. Empty means
    # "whichever is there"; a name settles the tie for somebody with both a
    # running emulator and a device on the desk.
    backend: str = ""
    # Wide enough for the roster column beside the map: the map alone is
    # 596 px at the fixed cell size, and the cards are 270.
    window_width: int = 940
    window_height: int = 820
    sight: int = 4

    @classmethod
    def load(cls) -> "Settings":
        path = config_dir() / FILE
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in raw.items() if k in known})

    def save(self) -> None:
        path = config_dir() / FILE
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(asdict(self), indent=1) + "\n",
                            encoding="utf-8")
        except OSError:
            pass            # a read-only home should not take the window down
