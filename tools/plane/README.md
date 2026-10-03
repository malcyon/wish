# Plane

Apply Wish ticket policy to a single private Plane project.

| File | Purpose |
|---|---|
| `__init__.py` | Marks the private ticket integration package. |
| `client.py` | Wraps the pinned vendor transport with project restrictions, pagination, full private readback and write error classification. |
| `mcp.py` | Registers only project-scoped tools over local MCP stdio. |
| `planeagent.py` | Creates (in Backlog, Queue or In Progress), comments on, edits comments by the agent or the importer account on, and changes tickets. |
| `planeread.py` | Lists, searches, reads, cites and reports the state of tickets through the policy layer. |
| `policy.py` | Validates private project configuration, renders Markdown and defines the write error types. |
