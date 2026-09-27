"""Temporary import shim: `tools/amiga/amigasecretsave.py` still imports this module name.

The staging code and its command line (`--source`, `--out`) live in
`tools/amiga/staging.py`; running this file no longer does anything. The change
that points `amigasecretsave.py` at `staging` deletes this file.
"""

from tools.amiga.staging import SOURCE_SHA256, stage_embedded_boot_disk  # noqa: F401
