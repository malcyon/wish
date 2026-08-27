### Which file do I want?

| you have | download |
|---|---|
| Windows, and you just want to run it | `wish-*-windows-x86_64.zip` |
| Linux, and you just want to run it | `wish-*-linux-x86_64.tar.gz` |
| Python 3.12+ and you would rather `pip install` | the `.whl` |

The two **Source code** archives are GitHub's own and are not
builds — you do not need them to run wish.

### Windows: the warning is expected

The executable is unsigned, so Windows will show **"Windows
protected your PC"**. Click **More info**, then **Run anyway**. A
code-signing certificate costs money and SmartScreen warns on new
signatures anyway, so this is not going away.

### One command

`wish` opens the window. `wish export SAVE.D64 -o party.yaml` and
`wish import party.yaml -o NEW.D64` are the save editor, in the
same executable. On Windows the build is windowed and never opens
a console, so the subcommands print only where a terminal
redirects them.

### Checksums

`SHA256SUMS` covers every file above. `sha256sum -c SHA256SUMS` on
Linux, `Get-FileHash` on Windows.
