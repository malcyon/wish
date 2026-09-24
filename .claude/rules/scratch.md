# Scratch files, and what counts as a tool

* Game data comes from `gamedisks.yaml`, the registry, and is read-only.
* Durable project work is committed.
* Temporary scripts and other disposable work stay in `/tmp` on the machine that produces them; tool output uses `tools/registry/scratch.py`. They may vanish at any time, and their disappearance never needs a note.
* One-off screenshots and mockups shown to Donald go under the producing machine's `/tmp/wish/screens/<issue-or-topic>/`. Attach or embed them in the reply; a path alone does not deliver an image.
* Host and `agent-vm` paths refer to separate filesystems. Deliver an image made on another machine as an attachment or an accessible link.
* Anything an emulator must open, or any emulator artifact retained as run evidence, goes under the producing machine's `~/.cache/wish` (`cache_dir`) instead, because the flatpak VICE cannot see `/tmp`.

Why these rules exist, and the incidents behind them:
`docs/160-why-these-rules.md`, "Temp files, tools and backups".
