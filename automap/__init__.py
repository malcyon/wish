"""Live automapper for Pool of Radiance (C64).

Separate from `goldbox/` and `editor/` on purpose. The shipped character editor is a
file tool with **zero emulator dependency** (`docs/README.md`) -- it opens a
.D64, edits it, writes it back, and never talks to VICE. Everything in
this package does the opposite: it reads a *running* machine. Keeping it here
is what lets both promises hold at once.
"""
