# Scratch files, and what counts as a tool

* Game data comes from `gamedisks.yaml`, the registry, and is read-only.
* Anything that is kept is committed.
* Everything else is written under the temp directory (`tools/registry/scratch.py`), may vanish at any time, and its disappearance never needs a note.
* Anything an emulator must open goes under the cache (`cache_dir`) instead, because the flatpak VICE cannot see the temp directory.

Why these rules exist, and the incidents behind them:
`docs/160-why-these-rules.md`, "Temp files, tools and backups".
