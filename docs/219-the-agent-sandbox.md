# The agent sandbox

Why the coding agents run in two virtual machines that cannot reach the home network, how the network and its filter are built, what the guests are given and what they are refused, and what was found while building them. `ansible/README.md` is how to build and use it; this is the reasoning. Each figure below was read off a running machine unless it is labelled estimated or derived, and the commands that took them are at the end.

## Why

Run on the desktop, an agent holds whatever the account that started it holds: `gh` logged in with `repo` scope over every repository, the ssh key that pushes, the home directory, and a route to every machine on the home network. An agent that follows a malicious instruction, from an issue comment, a web page or a dependency, has all of it.

**The purpose is containment, not prevention.** Nothing here stops an agent being told something harmful. It changes what the agent can do afterwards from "everything the operator can do" to "one repository and two disposable virtual machines".

The four rules in `AGENTS.md` about sharing the desktop with agents (nothing an agent runs puts a window on the operator's screen, `ssh` never asks a human anything, the operator's emulator ports are not touched, no process is killed by name) stay true for anyone who runs agents on the desktop. An agent inside the guest cannot break any of them, since it shares no screen, ports or processes with the operator, but nothing here removes them.

## Where the guests run

**Both guests run on the operator's own desktop**, and not on a machine other people depend on: a guest that exhausts memory takes its host down with it. Both on one host means one set of filter rules in one place, and the two guests reach each other on a shared subnet with nothing crossing between machines.

What the Ubuntu guest was sized against, read off the desktop:

| | |
|---|---|
| CPU | Intel Core i7-8700, 6 cores, 12 threads |
| RAM | 46 GB usable |
| Desktop session in use | 8 GB (a browser, an editor, a chat client, the shell) |
| 13 agent processes | 1.45 GB in all, 112 MB each (measured) |
| One pytest worker, peak RSS | 563 MB |
| NVMe | 225 GB usable, 154 GB used, 60 GB free: the system, `~/src` and the Windows guest's images |
| Spinning disk | 1.8 TB, 1.3 TB free |
| Swap | 16 GB zram plus a 4 GB partition, both idle |

The firmware reports a 32 GB maximum for the board; it runs 48 GB, so that figure is a table value and not a limit. The agents are thin because the model runs elsewhere. The only heavy local thing is a suite run, and the repository's rules already cap that at one at a time.

## Where the disks live

**The Ubuntu guest's image goes on the spinning disk**, `agent_vm_base_dir` (default `/data/agent-vm`). The NVMe carries the desktop, `~/src` and the Windows guest's images, and at 60 GB free has no room for a second guest that will not have to be defended forever.

What the spinning disk costs is a slow first read: installing the system and packages, building the virtual environment, and the first suite run after a reboot. After that the guest's checkout, virtual environment and emulator files sit in the host's page cache, of which about 38 GB was spare, and a second run reads from RAM. Writes are small (pytest scratch, `.pyc`, coverage), and a tmpfs `/tmp` in the guest keeps them off the disk entirely. The image can be 100 GB; there is no reason to be tight.

The Windows guest stays under libvirt's own directory, `winvm_base_dir`, on the faster disk. WinUAE is the one thing here that notices disk latency.

## One isolated network, on one host

**No VLAN is needed.** A VLAN defends against a hypervisor escape, a guest breaking out onto the wire. The threat here is an agent misbehaving inside the guest, and such an agent cannot reach the host's firewall rules any more than it can reach the desktop. So enforcement belongs on the host.

The network is called `sandbox`. One role, `ansible/roles/sandbox-network`, defines it, the filter below and the isolation test, and both guest roles depend on it, so neither defines a network of its own and neither can quietly define it differently. It sits beside libvirt's `default` (192.168.122.0/24):

```xml
<network>
  <name>sandbox</name>
  <forward mode='nat'/>
  <bridge name='virbr-sandbox' stp='on' delay='0'/>
  <ip address='10.77.0.1' netmask='255.255.255.0'>
    <dhcp>
      <range start='10.77.0.10' end='10.77.0.99'/>
      <host mac='...' name='agent-vm' ip='10.77.0.10'/>
      <host mac='...' name='win11' ip='10.77.0.11'/>
    </dhcp>
  </ip>
</network>
```

The `<host>` lines are the address table (`sandbox_net_leases`): fixed leases by MAC, so the inventory and the isolation test can name each guest. The subnet is this project's own and the same on every machine; only the MACs are the operator's to choose.

The rule that makes it isolated is a libvirt network filter attached to each guest's virtual NIC, not a rule in the host's forwarding chain. A host that runs Docker and libvirt on the iptables backend has both insert their own accept rules at the top of the forwarding chain every time they start, so a drop placed there is only as good as its position. A filter on the NIC is evaluated as the packet leaves the guest, before any of that, and it persists with libvirt's configuration:

```xml
<filter name='no-lan' chain='ipv4'>
  <!-- One hole per address in sandbox_net_pinholes: one host, all ports. -->
  <rule action='accept' direction='out' priority='50'>
    <ip dstipaddr='the pinhole address' dstipmask='32'/>
  </rule>
  <!-- The gateway address is the host: DNS and DHCP out, anything from the
       host in, and nothing else out to it. Lower priority runs first. -->
  <rule action='accept' direction='out' priority='60'>
    <udp dstipaddr='10.77.0.1' dstipmask='32' dstportstart='53'/>
  </rule>
  <rule action='accept' direction='out' priority='61'>
    <tcp dstipaddr='10.77.0.1' dstipmask='32' dstportstart='53'/>
  </rule>
  <rule action='accept' direction='out' priority='62'>
    <udp dstipaddr='10.77.0.1' dstipmask='32' dstportstart='67'/>
  </rule>
  <rule action='accept' direction='in' priority='65'>
    <all srcipaddr='10.77.0.1' srcipmask='32'/>
  </rule>
  <rule action='drop' direction='out' priority='70'>
    <all dstipaddr='10.77.0.1' dstipmask='32'/>
  </rule>
  <!-- The rest of the guest's own subnet: the other guest. -->
  <rule action='accept' direction='out' priority='100'>
    <ip dstipaddr='10.77.0.0' dstipmask='24'/>
  </rule>
  <!-- Every private range, so a LAN renumber does not silently open it, and
       Tailscale's, since the host is a tailnet node and would otherwise carry
       a guest onto the tailnet. Anything not matched is allowed, which is how
       the internet keeps working. -->
  <rule action='drop' direction='out' priority='200'>
    <ip dstipaddr='192.168.0.0' dstipmask='16'/>
  </rule>
  <rule action='drop' direction='out' priority='201'>
    <ip dstipaddr='172.16.0.0' dstipmask='12'/>
  </rule>
  <rule action='drop' direction='out' priority='202'>
    <ip dstipaddr='10.0.0.0' dstipmask='8'/>
  </rule>
  <rule action='drop' direction='out' priority='203'>
    <ip dstipaddr='100.64.0.0' dstipmask='10'/>
  </rule>
</filter>
```

`virsh nwfilter-define` stores it under `/etc/libvirt/nwfilter/`, and each guest's interface references it:

```xml
<interface type='network'>
  <source network='sandbox'/>
  <filterref filter='no-lan'/>
</interface>
```

Everything else, the internet through libvirt's own NAT, keeps working, because a packet no rule matches is allowed. GitHub, package mirrors and the model APIs are untouched.

**The gateway address is the host, so the filter treats it as a door of its own.** The subnet accept would otherwise let a guest at every service the host runs on `10.77.0.1`, `sshd` included. So a guest reaches the gateway for DNS and DHCP renewals and nothing else. libvirt builds `<ip>` rules in ebtables, at the bridge, which cannot track connections, and `<tcp>`, `<udp>` and `<all>` rules in iptables, which can. The gateway rules are all iptables' for that reason: a stateless drop to `10.77.0.1` would also drop the guest's replies to the host's own ssh, and Ansible could no longer reach the guest. The `in` accept from the host is what makes libvirt let those replies out. The bridge has no IPv6 address, so there is no link-local route to the host to go round the rule.

**DNS has to come from the network's own gateway.** A guest pointed at a resolver on the LAN has its queries dropped by the filter and loses the internet with no other symptom. The `<dhcp>` block makes libvirt run dnsmasq for this network, with its DNS on by default; the guest queries `10.77.0.1`, and dnsmasq forwards to the host's resolver as the host's own traffic, which no guest filter sees. Names on the LAN still resolve; the addresses they give are unreachable, which is the point. The network needs a host where nothing else holds ports 53 and 67 on the bridge: libvirt's `default` network's dnsmasq already runs beside it on that network's own gateway address.

**The deny is one-directional, deliberately.** The operator reaches in from the desktop by ssh to the guest's `10.77.0.x` address, and the replies go back to `10.77.0.1`, which the `in` rule lets through. Reaching in from any other machine on the LAN would need the replies to cross the filter and is not supported; go through the desktop.

**The Windows guest is on this network too.** On a network of its own with libvirt's default NAT and no filter it could reach the home LAN, and a Windows guest on the LAN's side is a way in. It is built from scratch on `sandbox`: `win11` is at `10.77.0.11`, with gateway and DNS at `10.77.0.1` (`winvm_dns_server`), all written by `autounattend.xml`. Its golden image, promoted once after the install, is the baseline; `winvm promote` and `winvm revert` touch only the disk and the varstore, never the domain, so the network, the filter and the vCPU count survive both. Both guests autostart with the host, and the guest's own `winvm` refuses the commands that start, stop or revert Windows: they drive it over ssh once it is up. That refusal is `tools/amiga/winvmguest.py`'s own convenience, not a boundary the key enforces -- see "What the guest's `winvm` does, and what it refuses" below.

### Prove it, every time the filter changes

A wrong filter fails silently: the guest works and nobody notices it can reach a machine on the LAN. So the test is a task in `sandbox-network`, not somebody's memory (`ansible/sandbox-isolation-test.yml`). It runs in two phases: every guest's network and mount checks first, and only once every one of those has reported does a second phase audit for credentials. From inside every running guest the first phase checks that:

* the internet answers, and the other guest does if it is running;
* none of `sandbox_net_lan_targets` answers, by ping and by a TCP connect;
* `ssh` to `10.77.0.1` is refused while DNS through it works;
* the Windows guest's ssh port answers from the Ubuntu guest, the one endpoint the agents drive it through (`sandbox_net_peer_tcp`);
* inside the Ubuntu guest, whose entry in `sandbox_net_probe_guests` lists the mounts to look in: the writable share can be written, the read-only disks cannot, as `agent` or as `root`, and the disks' device is itself write-protected.

`ssh`'s own `ConnectTimeout` bounds connection setup only, not a command that has already connected, so every check above also runs under GNU `timeout` (`sandbox_net_probe_timeout_seconds`); a probe that hits that deadline prints no verdict and is never counted as a pass.

Once every running guest's first-phase checks have reported, the second phase audits every guest whose entry names `audit_dirs` -- the Ubuntu guest, not the Windows one -- for a GitHub token (`ghp_`, `gho_`, `ghu_`, `ghs_`, `ghr_`, `github_pat_`) in any process environment, then in any file under `/home /root /etc /opt /tmp /var/tmp`, one directory at a time, each under its own longer deadline (`sandbox_net_credential_root_timeout_seconds`). Kept out of the first phase's probe list on purpose: a scan across a whole filesystem does not finish in the second or two the network checks do, and mixing the two let a slow or stuck scan hold up the network assertions behind it (#644 (The sandbox isolation playbook hangs on an unbounded credential scan of home directories, Flatpak payloads and disk images)). The game disks are not rescanned here: the `agent-vm` role already refuses to build the image if a token or private key is in its source, and the read-only-mount check above proves the guest cannot have written to it since. Before opening anything, the scan skips `sandbox_net_credential_prune_globs` -- by default the whole of `~/.local/share/flatpak` -- because Flatpak hard-links the same object content into `repo/objects`, `runtime/…/files` and `app/…/files` once a package is deployed, so skipping `repo/objects` alone still leaves that content reachable through `runtime/`. Per-app state under `~/.var/app` is not a Flatpak payload and stays in scope.

It passes for the right reasons only. Every LAN target must answer the host first, or a blocked probe means nothing; every probe prints a verdict of its own, so an ssh that never connected is told from one that was blocked; and a guest that is not running, a read-only mount that is not mounted, or a credential scan that timed out or hit a file it could not read, is reported as **not tested**, never as passing. It changes nothing that persists (its probes touch and remove a temporary file), so it runs under `--check`, and it never contacts a pinhole's address.

## The Ubuntu guest

Two roles beside `windows-vm`, following its conventions. `ansible/roles/agent-vm` builds and starts the guest on the host, targeting the `agent_vm_hosts` group. `ansible/roles/agent-vm-guest` configures the inside of it over ssh, against the `agent_vms` group. They are separate because a role's dependency runs wherever the role does, and `agent-vm` depends on `sandbox-network`, which has no business running inside the guest.

Sizing: **12 vCPU, 12 GB, 100 GB disk.** The domain XML caps `memory` at 12 GB and the cgroup at 12 GB plus 1.5 GB for QEMU's own footprint, so the guest can never squeeze the host and QEMU is not killed for touching all it was given.

### Memory

| the 46 GB host | |
|---|---|
| desktop session | 8 GB |
| Windows guest | 6 GB, the `windows-vm` default |
| Ubuntu guest | 12 GB |
| page cache and headroom | about 20 GB (derived: 46 minus the three lines above) |

| inside the Ubuntu guest, suite run at `-n 6` | |
|---|---|
| guest system, idle | 0.44 GB (measured) |
| the suite | **peak 3.0 GB used in all, 2.6 GB above idle** (measured, two runs: 3042 and 3075 MB); at least 8.9 GB stayed available |
| the agents | about 1.5 GB: the 13 agent processes measured on the desktop, 112 MB each (eight would be about 0.9 GB) |
| two or three `Xvfb` and their emulators | about 0.5 GB (estimated) |
| `/tmp` tmpfs, only what is in it | up to 4 GB, usually far less |
| **peak, all of it** | **about 5 GB of 12, plus whatever scratch holds** (derived: 3.0 GB measured for the guest and the suite, 1.5 GB for the agents, 0.5 GB estimated) |

The suite was run with `suite-timing`, which the guest role installs: 5950 passed and 1809 skipped, the skips being the tests that need game disks, so the emulators were not part of it. The guest pins pytest to 12 workers (below) and the suite was measured at 6, so no 12-worker peak has been read. After the runs QEMU held 3.8 GB of the host's memory, the guest's page cache included.

### CPU

The host has 12 threads and they are what runs out. The desktop session, a Windows guest running WinUAE and an Ubuntu guest running a suite all draw on the same six cores.

* `win11` has 4 vCPU, the role's default: WinUAE needs far less than six.
* The Ubuntu guest has all 12 of the host's threads, and pytest is pinned to that count in the guest rather than `-n auto`, through `PYTEST_ADDOPTS` in the guest's profile (`agent_guest_pytest_workers`). The pin means a suite run takes the whole host for as long as it lasts (about four minutes, measured at 6 workers), and the guest is idle otherwise.

### Disk

A 100 GB qcow2 under `agent_vm_base_dir`, a standalone copy of the cloud image rather than an overlay on it, so nothing depends on the downloaded file afterwards. The read-only disks image goes beside it, and a tmpfs on `/tmp` inside the guest is capped at 4 GB, so scratch never reaches the spinning disk and never grows without bound.

The disk is attached `cache='writeback'`, not `none`. The design counts on the guest's checkout, virtual environment and emulator files sitting in the host's page cache after their first read, and `O_DIRECT` would bypass it. Measured at 6 workers, the cold-read cost of the spinning disk is **50 s on a 4-minute suite**: 245 s with the host's page cache dropped and the guest freshly booted, 195 s straight after.

### What it needs installed

Python 3.12 and the `wish` virtual environment, `git`, `gh`, VICE (from Flathub, as `tools/c64/porlaunch.sh` runs it), DOSBox-X (built from source, for its heavy debugger), FS-UAE, Ansible and `ansible-lint` (to syntax-check and lint the sandbox playbooks under `ansible/`), and the agent CLIs: Claude Code and Codex, run under `herdr`, the agent multiplexer, with its hooks installed for both. Agent HUD is installed globally through npm beside the VICE MCP server on Node 20. `herdr` and `codex` are not pinned. `herdr-update` asks GitHub for the newest release, checks GitHub's SHA-256, installs it under `~/.local/share/herdr`, and moves the command symlink. `codex-update` runs OpenAI's standalone installer, which verifies its package and maintains the app-server tree under `~/.codex/packages/standalone` that `/agents` requires. The playbook runs both updaters, and systemd user timers run them weekly. `claude` updates itself. Each agent CLI is logged in by hand once per rebuild.

**Emulators run in a virtual machine, but "headless" has to mean "no monitor" rather than "no display server".** VICE, DOSBox-X and FS-UAE are GUI programs and cannot start without an X server; what they do not need is a physical one. `wish` already solves this: `Xvfb` appears in many tools, `tools/registry/instance.py` allocates a display number per emulator slot from `:10` upwards (`DISPLAY_BASE`) and a port from 6520 (`BIN_BASE`), and `tools/dos/dosoutdoor.py` names `Xvfb` and `xdotool` beside `dosbox` as its requirements. So the guest needs `Xvfb`, `xdotool`, the X libraries, SDL, and Mesa for FS-UAE's OpenGL through llvmpipe. None of that needs a GPU. `QT_QPA_PLATFORM=offscreen` in `tests/conftest.py` is a separate mechanism: it covers the `wish` Qt windows during tests, not the emulators.

**The display-allocation rules stay.** Two emulators racing for one display is the failure `tools/registry/instance.py` exists to prevent, and virtualisation changes nothing about it.

### The game disks

**The guest is given the game disks on a read-only virtual disk and cannot write to it, as `agent` or as `root`.** The operator keeps the disks in an ordinary directory on the desktop, `agent_vm_disks_dir` (`/data/agent-disks`), one directory per `gamedisks.yaml` entry, and puts there whatever the guest is allowed to have: each entry's first path that holds data, and only what the entry names. An entry with no data gets no directory, except that the `agent-vm` role itself downloads two public datasets the suite reads, `coab-source` and `game-icons`, into that directory; the operator supplies every other one. The `agent-vm` role builds an ext4 image from that directory (`mkfs.ext4 -d`), and the domain XML attaches it with `<readonly/>`.

`mkfs.ext4 -d` packs whatever directory it is given and has no exclude, so the role first makes a staging directory beside the image with `cp -al`, leaving out `specimens/`, which is shared writable instead (below), so a file is never both read-only in one mount and writable in another. Hard links cost no space, and `cited/` is included. The role refuses to build if a GitHub token or a private key is anywhere in the staging copy, sizes the file to what the copy occupies plus 5% and 64 MB, and renames it into place. It records a fingerprint of the source (every file's path, size, mode and mtime, `specimens/` pruned) and rebuilds the image only when that changes, so a specimen the guest writes never triggers a rebuild:

```xml
<disk type='file' device='disk'>
  <driver name='qemu' type='raw' cache='writeback'/>
  <source file='/data/agent-vm/disks.img'/>
  <target dev='vdb' bus='virtio'/>
  <readonly/>
</disk>
```

QEMU opens the image read-only on the host, so the guest's block device is write-protected and nothing inside the guest can change it. A running guest keeps the file it started with: a new or rebuilt image applies at its next shutdown and start, which the role says when it happens. The guest mounts the image by its label, `agent-disks`, at `/mnt/disks` through `fstab` (`ro`, `nodev`, `nosuid`, `nofail`), and the role asserts that the mount is `ro` and that `blockdev --getro` on the device says `1`.

**The guest's `gamedisks.yaml` is written by the role.** In `wish`, `gamedisks.yaml` is gitignored and per machine, and the committed `gamedisks.yaml.example` is its structure: every game, its environment variable, its glob, and the paths to try, each under `/data/agent-disks/<game>`. The `agent-vm-guest` role writes the guest's copy from the example with every path under `/mnt/disks/<game>`, except `codewheel`, which is the guest's own clone (see the credential below), and stops if any other path is not. That prefix is why `agent_vm_disks_dir` is set once, in the inventory's `all` group: the host play that builds the image and the guest play that rewrites the paths read one value, and a mismatch with the example is caught by the assert. The operator's own `gamedisks.yaml` on the desktop is unchanged.

Nothing on the LAN is ever mounted into the guest. A mount to home storage is a route into the LAN wearing a different name.

**Scratch and specimens.** The guest's `/tmp` is a 4 GB tmpfs from `fstab`, so nothing persists across a reboot. The specimen tree is the one thing shared into the guest writable, and the one thing it can write. `tools/registry/specimens.py` keeps engine-written game records under `$WISH_SPECIMENS`, each with a provenance file and a hash manifest, and `specimens add` writes into it. Specimens are made by agents driving a game in an emulator and reading the record back, which is the guest's job, so the tree cannot be read-only there. It lives in `specimens/` under `agent_vm_disks_dir` on the desktop and is shared into the guest with virtiofs (`<filesystem type='mount' accessmode='passthrough'>` with `<driver type='virtiofs'/>`, which needs `<memoryBacking>` with a shared `memfd` source in the domain XML), mounted at `/mnt/specimens` with `$WISH_SPECIMENS` pointing there. virtiofs is host-local, not a network mount, so nothing on the LAN is reached, and there is one tree, written by the guest and read by the desktop directly, with no copy to reconcile. The tool's read-only files and hash checks apply inside the guest as they do on the desktop.

Passthrough maps guest uids straight to host uids, so the guest's `agent` user, uid 1000 (`agent_vm_uid`), writes files owned by uid 1000 on the desktop. The role asserts that the directory is owned by that uid and refuses to continue otherwise; it never changes the ownership of an existing tree.

### Browsing and editing the guest's files

Nothing of the operator's runs inside the guest, so its files are looked at and edited from outside it: the guest's whole filesystem is mounted on the desktop at `~/agent-wish` with sshfs, writable as the guest's `agent` account, so a local GUI can edit `/home/agent` and `/tmp`. A systemd user unit makes it as the operator, and neither `allow_other` nor `allow_root` is set, so only that desktop account can reach it. The guest is untrusted, so the mount uses `follow_symlinks`, which resolves a symlink the guest plants on the guest and keeps an editor from opening or saving a desktop file through it, and `noexec`, so nothing from the guest runs on the desktop. It mounts at login with nothing typed, reconnects when the guest reboots, and answers an error rather than hanging when the guest is down or killed: measured, `ls` fails in 3 seconds with the guest off, and after a kill it returns a listing up to 2 seconds old and then fails in 3. The guest's own permissions decide what a write may change, and a write under `~/src/wish` edits files the agents are using at that moment. The `agent-vm` role's `verify` task creates, appends to, reads back and deletes a file under the mount's `tmp/`.

**VS Code Remote SSH into the guest is not used.** It installs a server in the guest and forwards the person's GitHub sign-in into it, and a `gho_` token turned up in that server's logs, readable by every agent that runs as `agent`. The guest role removes such a server and what its Copilot extension cached, and the isolation test fails on a token in any file or process environment.

## The credential

Nothing of the operator's goes into the guest: no ssh key, no `gh` login, no token from their account. Agents use the `wish-agent` GitHub App for everything. `docs/218-the-wish-agent-bot.md` is the design, the permissions it needs, how to rotate or revoke its key and what to check when it stops working; this section is only what the guest does with it.

**The App's private key is the only GitHub secret in the guest**, with its `config.json`, two integers that are not secret. The only other secret is the guest's own ssh key for the Windows guest, which opens that guest and nothing else ([below](#the-agent-guest-drives-windows-over-ssh)). The role copies both from `agent_guest_wish_agent_src` (default `~/.config/wish-agent` on the desktop) to the same path under the `agent` user, mode `0600` in a `0700` directory, so they never enter this repository. Revoking the key on github.com ends everything the guest can do.

`tools/wishagent.py` mints a token per mode and each is as wide as its job; two commands are built on the push mode: `push-token`, and `git-credential`, a git credential helper. In the guest:

* The `wish` checkout's origin is `agent_guest_wish_repo`, and `credential.https://github.com.helper` is that helper, the only one: the list is reset first, because git offers what it was given to every helper it has and one that stores credentials would write the token. git asks for `github.com`, and the helper answers with the user `x-access-token` and a token minted for that request. It answers nothing else, no other host and no unencrypted `http`, and it splits git's request on newlines only, so no token is stored anywhere.
* `/usr/local/bin/gh` is a wrapper, ahead of the real `gh` on `PATH` in every shell, that mints a push token and runs the real `gh` with it in `GH_TOKEN`. Every `gh` call is the App's and there is no login to find. It is the push token, not the issues one: issues are filed with `wishagent.py`.
* Commits are authored as `wish-agent[bot]`, with the email `<id>+wish-agent[bot]@users.noreply.github.com`, the id being the bot user's, which the role asks GitHub for as the App.
* A push token is for one repository, `wish` unless `$WISH_AGENT_REPO` says otherwise, so anything else at `github.com` pushed through the helper is refused by GitHub.
* **Other private repositories are cloned, not copied** (`agent_guest_private_repos`). The code-wheel repository, named by `agent_guest_codewheel_slug`, is the first: it must be on the App's repository access with Contents read and write, and the role clones it and runs `git pull --ff-only` in it on every run, stopping if the pull would merge or overwrite the guest's own work. An empty slug skips the entry. Each checkout has a credential helper list of its own, reset first like the global one, that runs the same helper with `WISH_AGENT_REPO` set to that slug; without it the helper mints a token for `wish`, and GitHub answers "Repository not found". The guest's `gamedisks.yaml` points its `codewheel` entry at the clone, and `codewheel` is never a directory under `agent_vm_disks_dir`: the `agent-vm` role refuses to build the disks image while it exists, so the repository cannot be packed into the image as well.

What was proven from inside the guest: `git fetch` and `gh api /repos/<owner>/wish` work. An empty commit pushed to a throwaway branch is authored, on GitHub, by `wish-agent[bot]` (`gh api /repos/<owner>/wish/commits/<sha> --jq .author.login`); a file added under `.github/workflows/` and pushed to the same branch is accepted, which needs Workflows; then the branch was deleted. For a private repository, `git fetch` works, the same URL with no helper is refused (so the helper is what gets in), `git push --dry-run` authenticates to GitHub's push endpoint and changes nothing, and the checkout's config holds no token, with no `~/.git-credentials` and no `gh` login. The guest has no private key in `~/.ssh`, no `~/.config/gh`, a `gh` that reports it is not logged in, no credential store file, no `x-access-token` in any git config, and the App's key as the only PEM private key under `/home` and `/root`. The isolation test's token audit passes, and it was shown to fail on the two things it is for: a real leaked token in a file, and a fake one planted in a process environment. Those checks were taken before the guest had its Windows key, so `~/.ssh` now holds one private key, `winvm_ed25519`, which the guest generated itself and which Windows accepts only from `10.77.0.10`.

## What the isolation breaks

**The C64 Ultimate is physical hardware on the home network**, driven over HTTP and FTP by `tools/c64/c64urest.py`. Agents keep it, through one accept rule in the `no-lan` filter ahead of the drops, one entry of `sandbox_net_pinholes`:

```xml
<rule action='accept' direction='out' priority='50'>
  <ip dstipaddr='the pinhole address' dstipmask='32'/>
</rule>
```

That pinhole is the only hole in the isolation, so it is one address, never a subnet, and the Ultimate needs a fixed address for it: a DHCP reservation on whatever serves the LAN, so the rule does not go stale. It is one address on all ports rather than ports 80 and 21, because FTP negotiates its data connection on a port chosen at run time. The guest reaches it by that address, since names on the LAN resolve but nothing else on the LAN answers.

**The monitoring system needs no pinhole, and the guest holds no credential for it.** The guest runs only `prometheus-node-exporter` (Ubuntu's package), and the agent that scrapes it is on the desktop, across the `sandbox` network, which the filter allows in that direction.

## Monitoring

**The scraper runs on the desktop, and the guest holds only an exporter.** No credential for the monitoring system enters the guest, and nothing is installed in the Windows guest. The `agent-vm-guest` role installs `prometheus-node-exporter` from Ubuntu's archive and binds it to the guest's own sandbox address on `agent_guest_exporter_port` (default 9100) through `ARGS` in `/etc/default/prometheus-node-exporter`. The role asserts that this is the only listener on the port. A drop-in orders the unit after `network-online.target` and has it retry, because the address comes from DHCP and the packaged unit gives up after five quick failures. Loopback and the other interfaces refuse it, and so does the LAN: the exporter listens on an address the filter does not let the LAN reach.

The scrape itself, and the keys that ship it to the monitoring system, live in the operator's own Ansible, outside this repository.

## The Windows guest

The Windows 11 Enterprise (evaluation) guest runs WinUAE and VICE under QEMU/KVM and libvirt, on the desktop, and the Ubuntu guest's agents drive it over ssh. It is a peripheral of the agent guest, and it must not be a path out. What follows is why it is built as it is and what was found building it; `ansible/README.md` has how to run it.

**The shared `sandbox` network, not one of its own and not libvirt's `default`.** A Windows guest on its own unfiltered NAT network could reach the home LAN. So it sits on `sandbox`, whose `no-lan` filter is attached to the guest's NIC by the domain definition, and the `sandbox-network` role owns both. The `windows-vm` role defines no network. The guest still addresses itself statically from `autounattend.xml`: `10.77.0.11`, with DNS at the gateway, `10.77.0.1`, because a guest pointed at a resolver on the LAN would have every query dropped by the filter and would resolve nothing. libvirt's own `default` network is left alone unless `winvm_disable_default_network` is true, which stops it and turns off its autostart. The role also stops and undefines a libvirt network named by `winvm_legacy_network` (default `winvm`; set `""` to keep it) once no running guest is on it, because an unfiltered NAT network by that name is a route to the LAN.

**`socat` units, not DNAT rules, for forwarded ports.** Docker and Tailscale both rewrite iptables on the host. A userspace forwarder cannot be reordered out of existence by either. A forward is only needed to reach the guest from a machine other than the desktop.

**libvirt pinned to the iptables firewall backend.** Docker sets `iptables -P FORWARD DROP`. libvirt's default nftables backend writes ACCEPT rules into its own nft table, which cannot override that policy, and the guest ends up with no outbound network. `sandbox-network` writes the iptables pin into `/etc/libvirt/network.conf` so libvirt's rules land at the top of the same chain Docker uses, but only when the file the package ships mentions `firewall_backend`: older libvirt, such as the 10.x on Ubuntu 24.04, does not have the setting and always uses iptables. The pin is `sandbox-network`'s, since both guests depend on it, and it stays when either guest is removed.

**SATA disk and an e1000e NIC, not virtio.** Both have in-box Windows drivers, so nothing has to be injected into WinPE: driver paths in WinPE depend on unpredictable drive letters and are the most common cause of a failed unattended install on KVM. The virtio ISO is still attached, and the QEMU guest agent is installed from it on first logon. The disk can move to `virtio` in `winvm-domain.xml.j2` for the throughput.

**LabConfig bypasses in `autounattend.xml`.** The guest has a real emulated TPM 2.0 and Secure Boot, so those checks would pass, but Windows 11 Setup accepts only 8th-generation and newer processors. `BypassCPUCheck` is what gets Setup past that on an older host; the others are set alongside it so the install does not stall if firmware features come up differently.

**The guest agent needs two installers, not one.** The agent talks to the host over virtio-serial, for which Windows has no in-box driver, and this guest otherwise needs none, since it boots on SATA and e1000e. On the virtio-win ISO the pieces are split:

| installer | what it provides |
|---|---|
| `guest-agent\qemu-ga-x86_64.msi` | the `QEMU-GA` service, and nothing else |
| `virtio-win-gt-x64.msi` | 13 drivers including `vioser.sys`, and **no agent** |

Install the agent alone and you get a service with no channel; install the drivers alone and you get a channel with no service. Both fail identically from the host, `state='disconnected'`. First logon installs both.

**Display: the QXL driver.** `virtio-win-gt-x64.msi` installs the network, storage and balloon drivers but **not** the display one. Without the QXL driver the guest runs on *Microsoft Basic Display Adapter*: one fixed mode, no taller resolutions offered, and no SPICE auto-resize when the viewer window is resized. A dialog taller than the screen has its buttons off the bottom edge with nothing to drag them back with, which is how it was found, with VICE's disk-attach dialog at 1280x800. `guest-setup.ps1` installs the driver with `pnputil` from the virtio ISO (`winvm_install_qxl`, `winvm_qxl_inf`), and two things about that step are deliberate:

* It runs after the virtio MSI, which puts Red Hat's certificate in the TrustedPublisher store. Without that certificate `pnputil` waits for a human to confirm the publisher, on a machine with nobody at it.
* The path is the `w10` package: the ISO carries no `w11` build of `qxldod`, and `w10\amd64` is the Windows 11 one.

The check is `(Get-CimInstance Win32_VideoController).Name`, which says *Red Hat QXL controller* rather than *Microsoft Basic Display Adapter*.

**UTC hardware clock, pinned on both sides.** The domain sets `<clock offset='utc'/>` and first logon sets `RealTimeIsUniversal=1`. With `localtime` the guest clock slipped by exactly the timezone offset once Windows started syncing time, and `localtime` also misbehaves across DST transitions. Setting only one side reintroduces the same skew, so change both or neither.

**The static IP is set by adapter index, not adapter name.** `netsh` and PowerShell both address adapters as "Ethernet" by default, which is a localised string; `Get-NetAdapter -Physical | Select-Object -First 1` works whatever the image language is. If `winvm_ip`, `winvm_net_prefix`, `winvm_net_gateway` or `winvm_dns_server` change, the guest only picks the new values up on a rebuild: they are applied once, at first logon, and live in the guest's disk. `winvm revert` restores the golden image's copy of them, so a change made in the overlay is lost by a revert unless it is promoted first.

**libvirt snapshots do not work on this guest.** Windows 11 requires UEFI, and libvirt refuses internal snapshots of a guest with pflash firmware (*"internal snapshots of a VM with pflash based firmware are not supported"*). So the role uses a qcow2 overlay on an immutable golden base instead, and `winvm revert` deletes and recreates the overlay and restores the UEFI varstore from its golden copy. The varstore matters: reverting the disk without the NVRAM can leave a boot entry pointing at an ESP that no longer exists.

**VICE is unpacked, and its version is flattened out of the path.** VICE ships a zip and no installer, so `guest-setup.ps1` expands it. The archive holds one top-level directory named for the release, so unpacking it as it is would put the emulator at a path that moves with every release; the unpack step lifts that directory's contents up one level, so the binary is always `C:\VICE\bin\x64sc.exe`, and upgrading is two lines in the role's defaults and a rebuild.

**VICE's settings are seeded, and only if absent.** `vice.ini.j2` is rendered on the host and copied into the guest's profile at first logon, mirroring the workstation's own VICE settings minus its host paths, so a measurement taken in the guest is comparable with one taken on the desktop. VICE keeps `SaveResourcesOnExit=1`, so once somebody has opened the settings dialog the file on disk is theirs, and overwriting it on a later run would discard their work. Two settings in it are the point of seeding it: `VICIIFilter=0`, no rendering filter, which turns CRT emulation and its scan lines off; and `BinaryMonitorServer=1` on `127.0.0.1:6502`, the socket `wish`'s automapper attaches to, off in a stock VICE. **The resources are `BinaryMonitorServer` and `BinaryMonitorServerAddress`.** There is no `BinaryMonitor` resource, and setting that name does nothing at all, silently.

**The JiffyDOS and Kickstart ROMs are copyrighted**, so they stay outside every repository and ride the unattend ISO into `C:\C64\JiffyDOS` and `C:\Amiga\Kickstarts`, from `winvm_jiffydos_src` and `winvm_kickstart_src`. An empty value skips either. Without JiffyDOS VICE uses the stock kernal, which works and only has no fastloader, and Pool of Radiance asks to disable its own on boot.

**Leases: a tag is an identity.** `up` and `down` are fine for one caller; with several agents sharing the guest they race, and agent A's `down` lands while agent B is mid-test. Leases reference-count it: `winvm acquire <tag>` starts the guest if it is not up, `winvm release <tag>` shuts it down only when the last lease goes. Two holders of one tag is the failure the leases exist to prevent: they would share one lease file invisibly and the first to `release` would shut the guest down on top of the other's work. So taking a tag that is already held is refused, and the error tells the caller to pick a tag of their own. The create is a `noclobber` redirect in a subshell rather than a test followed by a write, so two acquires landing together cannot both win it: 20 simultaneous acquires of one tag were granted 1 and refused 19, where an unguarded create granted all 20; five different tags all succeed. A lease cannot outlive the boot it was taken in, since nobody is driving a guest that is switched off, so `acquire` clears the lease directory when it finds the guest off, and a crashed agent cannot lock its tag out forever.

## The agent guest drives Windows over ssh

**The agents run in the Ubuntu guest and WinUAE runs in the Windows guest, so the one needs a way into the other that does not pass through the desktop.** The desktop's `winvm` cannot run in the guest unchanged: its lifecycle commands, its leases and its screenshot are all `virsh` against the desktop's libvirt, which the guest has no access to and must not be given. What the guest gets is one ssh endpoint, `10.77.0.11:22`, and a `winvm` of its own, `tools/amiga/winvmguest.py`, that does over ssh the parts that can be done over ssh. `ansible/agent-winvm-access.yml` sets it up; it runs from the desktop, and its role is `ansible/roles/agent-winvm-access`.

**The identity is the guest's own.** The Ubuntu guest generates `~/.ssh/winvm_ed25519` with its own `ssh-keygen`, so the private half never exists on the desktop or anywhere else, and only the public half leaves the guest. The desktop writes that public half into the Windows guest's `administrators_authorized_keys`, logging in with the key Windows already trusts, the operator's, which never enters the guest. The line starts with `from="10.77.0.10"`, so the key works only from the Ubuntu guest's address, plus `no-agent-forwarding` and `no-X11-forwarding`, and ends with the comment `wish-agent-vm`, by which a later run finds and replaces it. It logs in as `winvm_admin_user`, the same administrator the operator uses, because `tools/amiga/winuae.ps1` registers its session 1 tasks for that account.

**The host key is read through the hypervisor, not the network.** The two guests share a bridge, and nothing stops the Ubuntu guest answering for `10.77.0.11`, so a key taken from whatever answers on port 22 could be the agent's own. The desktop reads `C:\ProgramData\ssh\ssh_host_ed25519_key.pub` off the Windows guest's disk with the QEMU guest agent's `guest-exec`, over virtio-serial, then runs `ssh-keyscan` against the address and stops unless the network presents the same key. The key is pinned in `/etc/ssh/wish-winvm_known_hosts` in the guest, owned by root, with `StrictHostKeyChecking yes`, so a different key is refused rather than learnt. If the guest agent refuses `guest-exec`, the run stops and asks for the key line to be read off the console and set as `agent_winvm_host_key`; it never falls back to trusting the scan.

**The ssh configuration is root's too**, `/etc/ssh/ssh_config.d/wish-winvm.conf`: host, account, identity, the pinned file and `BatchMode yes`. `winvm` passes it with `-F`, so nothing in the agent's own `~/.ssh/config` applies, and adds `BatchMode=yes` and `StrictHostKeyChecking=yes` on every command line whatever the file says. `ssh win11` on its own reads the same file through `/etc/ssh/ssh_config`.

**The network does not change.** The `no-lan` filter already accepts the guest's own subnet, `10.77.0.0/24`, on every port, and the Windows guest is inside it, so the endpoint needs no rule and no pinhole. The playbook does not include `sandbox-network` and cannot change the filter; it asserts that the Windows guest's address is on the sandbox subnet and not in `sandbox_net_pinholes`, so the endpoint cannot be a way onto the LAN. The isolation test proves the port answers from the Ubuntu guest, beside its proofs that the LAN does not.

**What the guest's `winvm` does, and what it refuses:**

| command | how |
|---|---|
| `ssh [cmd...]`, `scp ...` | ssh and scp with the pinned configuration; the same arguments as the desktop's, so `tools/amiga/amigadrive.py`, `winvmsettle.py` and the rest run unchanged |
| `ps SCRIPT` | PowerShell sent as `-EncodedCommand`, so no shell on either side re-quotes it |
| `put LOCAL... REMOTE`, `get REMOTE LOCAL` | scp in either direction, with a Windows path's backslashes turned into forward slashes |
| `shot [file]` | a one-off scheduled task with an Interactive principal captures the console session, session 1, since ssh lands in session 0 and cannot see the screen; the PNG comes back base64-encoded on the same ssh call and the task and file are removed before it returns |
| `status`, `lane` | the Windows guest's name, account and boot time, and `winuae.ps1 status`: who holds the WinUAE lane, and which `winuae64` is running for whom |
| `acquire`, `release`, `up`, `down`, `save`, `promote`, `revert`, `guest-setup` | refused with a one-line error, by the guest's own `winvm`, before anything runs |

**The refusal above is a convenience, not an access-control boundary.** The key that logs in carries no `command=` restriction, so `winvm ssh` and `winvm ps` already hand the agent guest a full Administrator PowerShell session on the Windows guest -- `Restart-Computer`, `Stop-Computer`, anything else an administrator can type reaches Windows exactly the same way `virsh` does from the desktop. What stops an agent calling those is that `tools/amiga/winvmguest.py`'s own `main()` refuses the eight names in the table above before running anything; a caller going around that file, over the same ssh identity, is refused nothing. Lane ownership is the same kind of thing: `winuae.ps1 claim` is a file two cooperating callers agree to check, not a lock Windows enforces, and an ssh session that skips it can start `winuae64` anyway.

**Lane ownership is `winuae.ps1 claim`, not the Linux instance pool and not a lease.** The pool in `tools/registry/instance.py` hands out ports and displays on the machine it runs on and knows nothing of Windows, and a `winvm` lease only counts who wants the domain running. Who may drive WinUAE is decided on Windows, where the driver is, by the claim file `winuae.ps1 claim` creates atomically, and `winvm lane --expect <holder>` reads it back through `winuae.ps1 status`.

**The screenshot is not the desktop's.** `virsh screenshot` reads the framebuffer, which works whatever the session state. The guest's `shot` needs somebody logged on at the console, like every `winuae.ps1` action, and says so when nobody is. It captures DPI-aware, so it has the framebuffer's pixel size.

**`winvm revert` undoes the authorization.** The key's line is written into the overlay, and a revert goes back to the golden image. Re-run the playbook after a revert, or promote once with the line in place. `winvm guest-setup` keeps it: the first-logon script rewrites `administrators_authorized_keys` with the operator's key and keeps any line ending in `winvm_agent_key_comment`. A rebuilt Windows guest has a new host key and a rebuilt Ubuntu guest a new identity; the playbook handles both.

**Audio.** The guest's audio device plays through SPICE, so it should reach the desktop's speakers only while a SPICE client (`virt-manager`, `virt-viewer`) has the Windows guest's console open; that follows from how SPICE delivers audio and has not been measured here, so check with `pactl list sink-inputs` on the desktop during a run. `.claude/rules/emulator.md` has why WinUAE's own sound cannot be turned off.

## Implementation defaults

Where this design is silent, these are the answers, chosen to match what `ansible/roles/windows-vm` does. Depart from them only with a reason written into the role.

| | |
|---|---|
| Guest OS | Ubuntu 24.04 server, from the official cloud image, so Python 3.12 is the system Python |
| Guest build | a cloud-init NoCloud seed ISO generated by the role, the Ubuntu counterpart of `autounattend.xml`, with the image directory, seed and domain XML all under `agent_vm_base_dir` |
| Guest user | `agent`, passwordless sudo, an ssh key generated by the role once and kept outside the checkout (`agent_vm_keypair_path`), and an empty `~/.hushlogin`, written by the guest role, so an ssh login prints no welcome banner, system information, update counts or last-login line |
| Guest address | DHCP from `sandbox`, with a fixed lease by MAC so the isolation test and the inventory can name it |
| Inventory | `agent_vm_hosts` and `winvm_hosts` groups that both contain `workstations`, an `agent_vms` group for the guest, and a host entry for it reached over ssh at its `10.77.0.x` address from the desktop |
| Agents inside | started by the operator in `herdr` or a `tmux` session over ssh; the role installs the CLIs and herdr's hooks for them and does not try to daemonise them |
| Autostart | both guests autostart with the host; the guest's own `winvm` refuses to start, stop or revert either, by convenience rather than by what the ssh key allows |
| Host firewall | untouched; the filter on the NIC is the whole enforcement |
| Filter and network | defined with `virsh` from templates in `sandbox-network`, which both guest roles depend on, checked for existence first so the role is idempotent |
| `wish` checkout | cloned over HTTPS during the build; a checkout that is a clean `main` is fast-forwarded on each run, and any other is left as it is; its origin stays `agent_guest_wish_repo`, and it pushes as the App through git's credential helper |
| Game disks | `agent_vm_disks_dir` on the desktop is the source, one directory per `gamedisks.yaml` entry; the role builds `disks.img` from a `cp -al` staging copy of it without `specimens/`, with `mkfs.ext4 -d`, refusing to if a token or private key is in it, and rebuilds only when a fingerprint of the source changes; the domain attaches it read-only as `vdb`; the guest mounts it by label at `/mnt/disks` via `fstab`, `ro`, and the role writes the guest's `gamedisks.yaml` from `gamedisks.yaml.example` with every path under `/mnt/disks` |
| Scratch | `/tmp` is a 4 GB tmpfs from `fstab`; nothing persists across a reboot |
| Specimens | `specimens/` under `agent_vm_disks_dir` shared with virtiofs, mounted read-write at `/mnt/specimens`; the guest's profile sets `WISH_SPECIMENS=/mnt/specimens`. The disks image never contains it |
| Browsing and editing the guest's files | sshfs, writable as `agent`, of the guest's `/` at `agent_vm_wish_mount` on the desktop, `follow_symlinks,noexec`, reachable only by the mounting user, by a systemd user unit that mounts at login and reconnects; no VS Code Remote SSH |
| App private key | copied into the guest by the role from `agent_guest_wish_agent_src` with `config.json`, mode `0600` in a `0700` directory, owned by `agent`; never in this repository |
| Windows access | `ansible/agent-winvm-access.yml`: a key generated in the guest, authorized on Windows only from `10.77.0.10`, the Windows host key read through the QEMU guest agent and pinned root-owned in the guest, and `tools/amiga/winvmguest.py` installed as `winvm`; no filter change |

## What this does not do

* It does not stop prompt injection. An agent in a guest still reads issues and can still be told things. What changes is what it can do next.
* It does not protect against a hypervisor escape. That is what a VLAN would be for, and it is a different threat from this one.
* It does not make the Windows guest trustworthy; it makes it contained. The agent driving WinUAE is in the Ubuntu guest, and the Windows guest is a peripheral that must not be a path out.

## Re-taking the measurements

The desktop's figures came from the desktop directly:

```sh
free -g
sudo dmidecode -t memory        # modules, slots, configured speed
ps -eo rss,comm                 # agent and pytest footprints
swapon --show
df -h /
sudo du -xh --max-depth=2 /var | sort -h | tail
sudo ls -lh /var/lib/libvirt/winvm/
virsh dumpxml win11 | grep -E '<memory|<vcpu'
```

The suite's memory and wall time in the guest come from `suite-timing`, which the guest role installs.
