"""The application: one window over the file editor and the live map.

`editor/` and `automap/` are libraries of widgets; this package owns the window,
the single live connection and the choice of backend. The direction of the
imports is the point -- `wish` may import both, `editor` imports neither, and
`por/` stays transport-free. That is `docs/PLAN.md`'s first decision: the
character editor is a file tool and never talks to a running machine.
"""
