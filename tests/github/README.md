# github

Tests for the scripts that read and write the public issue tracker without letting a stranger's text into an agent's context.

| file | purpose |
|---|---|
| `test_ghtrust.py` | Checks `tools/github/ghtrust.py`: which authors count as trusted, and how flattening and the withheld wording behave, with no `gh` involved. |
| `test_issueread.py` | Checks `tools/github/issueread.py` prints a trusted author's text in full and never lets an outside author's text reach the output. |
| `test_wishagent.py` | Checks `tools/wishagent.py` builds its token, requests and refusals correctly, with `wishagent._request` replaced so nothing touches the network. |
