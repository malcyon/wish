"""Live automapper for Pool of Radiance (C64).

Separate from `por/` and `editor/` on purpose. `docs/PLAN.md` decides that the
shipped character editor is a file tool with **zero emulator dependency** -- it
opens a .D64, edits it, writes it back, and never talks to VICE. Everything in
this package does the opposite: it reads a *running* machine. Keeping it here
is what lets both promises hold at once.
"""
