# Ansible

The playbooks that build the agent sandbox on your own desktop (an isolated libvirt network and its filter, the Ubuntu guest the coding agents run in, and the Windows guest that runs WinUAE and VICE), with the design and its reasons in `docs/219-the-agent-sandbox.md`.

```
                        the desktop
   ┌────────────────────────────────────────────────────────────┐
   │  virbr-sandbox  10.77.0.1   libvirt NAT, dnsmasq DNS/DHCP  │
   │     │                                                      │
   │     ├─ agent-vm  10.77.0.10  ── no-lan filter on its NIC   │
   │     └─ win11     10.77.0.11  ── no-lan filter on its NIC   │
   └────────────────────────────────────────────────────────────┘
                 │ NAT                     ╳ 192.168.0.0/16, 172.16.0.0/12,
                 ▼                           10.0.0.0/8, 100.64.0.0/10
             internet
```

| role | does | playbook |
|---|---|---|
| `sandbox-network` | libvirt, the `sandbox` network, the `no-lan` filter, the isolation test | `sandbox-network.yml`, `sandbox-isolation-test.yml` |
| `agent-vm` | builds and starts the Ubuntu guest on the host | `agent-vm.yml` (play 1), `agent-vm-teardown.yml` |
| `agent-vm-guest` | configures the inside of the Ubuntu guest over ssh | `agent-vm.yml` (play 2) |
| `windows-vm` | builds the Windows 11 guest and installs WinUAE and VICE in it | `windows-vm.yml`, `windows-vm-teardown.yml` |

| file | for |
|---|---|
| `inventory.yml.example` | The template for `inventory.yml`, the one file naming this machine's paths, accounts, MACs and LAN addresses; copy it and fill it in |
| `group_vars/all/vault.yml.example` | The template for `vault.yml`, which holds the Windows guest's administrator password |

`agent-vm` and `windows-vm` both depend on `sandbox-network`, so neither defines a network of its own. `agent-vm-guest` is a role of its own because a dependency runs wherever its role does, and `sandbox-network` has no business running inside the guest.

## Building it

Copy `inventory.yml.example` to `inventory.yml` and `group_vars/all/vault.yml.example` to `group_vars/all/vault.yml`, fill both in (the next section says what), then from the repository root:

```bash
ansible-playbook -i ansible/inventory.yml ansible/sandbox-network.yml   # the network and filter, on their own
ansible-playbook -i ansible/inventory.yml ansible/agent-vm.yml          # the Ubuntu guest; ends with the isolation test
ansible-playbook -i ansible/inventory.yml ansible/windows-vm.yml        # the Windows guest, which then needs installing
ansible-playbook -i ansible/inventory.yml ansible/sandbox-isolation-test.yml   # the proof, alone
```

Every playbook is idempotent. The first `agent-vm.yml` run downloads Canonical's cloud image (about 600 MB, once, checksum-verified), builds the guest from it with a cloud-init seed, boots it, then installs the toolchain over ssh; the DOSBox-X source build is the long part. Nothing is downloaded by hand and no installer is involved, except the Windows ISO below.

A section can be run alone by its tag: `boot`, `packages`, `gh`, `claude`, `vice`, `dosbox`, `wish`, `node`, `agenthud`, `herdr`, `codex`, `herdr_integrations`, `environment`, `credential`, `disks`, `exporter`, `login`, `codewheel`; or `agent_vm` for play 1, `agent_vm_guest` for play 2, `isolation` for the test, `agent_network` for the `sandbox-network` role in `sandbox-network.yml`, `winvm` for the `windows-vm` role.

`inventory.yml` and `group_vars/all/vault.yml` hold one machine's own values and are gitignored; `tests/suite/test_repository_contents.py` refuses a tracked file under `ansible/` that names a home directory, a LAN address or a credential.

## What `ansible/inventory.yml` must name

Each row is a variable `inventory.yml.example` has a placeholder for; everything not listed is a default inside its role.

| variable | what it is |
|---|---|
| `agent_vm_base_dir` | The directory the Ubuntu guest's image, keys and disks image live under; a path every user can traverse, on the disk with room for a 100 GB image |
| `agent_vm_disks_dir` | Where the game disks are; set under `all` so the host play and the guest play read one value, and it must be the prefix the paths in `gamedisks.yaml.example` start with |
| `agent_vm_keypair_path` | The Ubuntu guest's login keypair, both halves, outside the checkout; generated on the first run if absent, so move an existing pair here before running against a guest already built |
| `agent_vm_operator` | Your account on the desktop; the read-only sshfs mount of the guest's checkout runs as it |
| `agent_vm_timezone` | A tz database name for the Ubuntu guest's clock |
| `sandbox_net_leases` | Each guest's MAC, in libvirt's locally administered range; the addresses are `10.77.0.10` and `10.77.0.11` on every machine |
| `sandbox_net_pinholes` | The LAN hosts, each one bare address, the guests may reach, such as the C64 Ultimate; an empty list is no hole |
| `sandbox_net_lan_targets` | LAN machines the isolation test must fail to reach: a `name`, an `ip` and a `tcp_port` each, and each must answer a ping and accept that port from the desktop itself, or the test refuses to run |
| `winvm_user` | The desktop account added to the `libvirt` and `kvm` groups |
| `winvm_admin_user` | The Windows guest's local administrator, which `winvm ssh` logs in as and the isolation test probes |
| `winvm_iso_src` | The Windows installation ISO you downloaded |
| `winvm_kickstart_src` | A directory of Amiga Kickstart ROMs; empty skips them |
| `winvm_jiffydos_src` | A directory of JiffyDOS ROMs for VICE, outside every repository; empty skips them |
| `winvm_timezone` | Optional: a Windows time zone name for the guest's clock |
| `ansible_host`, `ansible_user`, `ansible_ssh_private_key_file` on the `agent-vm` host | The guest's `10.77.0.10` address, `agent`, the account the guest is built with (`agent_vm_user`), and `agent_vm_keypair_path` |
| `agent_guest_codewheel_slug` | The private repository holding the code-wheel arithmetic, which the guest clones; empty skips the clone |
| `agent_guest_private_repos` | Optional: further private repositories the guest clones with the same GitHub App; the list replaces the default, so keep the code-wheel entry |
| `vault_windows_admin_password` | In `group_vars/all/vault.yml`, not the inventory: the Windows administrator's password, at least 8 characters |

`sandbox_net_drops` is a default and needs naming only to change it. The commented lines at the end of the workstation's variables in the example (`winvm_memory_mb`, `winvm_disk_gb`, `winvm_graphics`, `winvm_forwarded_ports`, `winvm_disable_default_network`, `winvm_install_winuae`) are each the role's own default, for a machine that needs a different one. The guest's account is `agent_vm_user` (default `agent`); changing it breaks the isolation test unless the `user` in `sandbox_net_probe_guests` is changed to match.

## Using the Ubuntu guest

```bash
ssh agent-vm          # an ssh alias the role installs on this host
herdr                 # or tmux
```

Agents are started by hand, in `herdr` or a `tmux` session; the role installs the CLIs and does not daemonise them. `herdr` is the agent multiplexer: it shows at a glance which agents are working, blocked or done, and its hooks are installed for **Claude Code** and **Codex**. Both are logged in by hand, once per rebuild: `claude` prints a URL to open on the desktop, and `codex login` does the same. `gh` and `git` hold the `wish-agent` GitHub App and nothing of yours; see [The credential](#the-credential). Claude Code's status line script and its `statusLine`, `attribution`, `effortLevel`, `modelSettings`, `theme`, `outputStyle` and `remoteControlAtStartup` settings are set by the role on every run from the `agent_guest_claude_*` variables; everything else in `settings.json` is left as the login flow and herdr's integration put it. Agents never start, stop or revert either guest, and both autostart with the host.

| | |
|---|---|
| Sizing | 12 vCPU, 12 GB with a hard cap in the domain, 100 GB qcow2 |
| Image | `agent_vm_base_dir`, `agent-vm.qcow2` |
| Login | user `agent`, passwordless sudo, the key at `agent_vm_keypair_path`; an empty `~/.hushlogin` silences Ubuntu's welcome banner, system information, update counts and last-login line |
| Address | `10.77.0.10`, a fixed lease by MAC |
| `/tmp` | a 4 GB tmpfs; nothing in it survives a reboot |
| `wish` | `~/src/wish`, cloned over HTTPS as it is on `origin`, with `.venv`, installed with the `dev` and `gui` extras; `ruff` is also installed into `.venv` by name |
| Tools | `herdr` and `codex`, **not pinned**. `herdr-update` installs the newest checksum-verified GitHub release under `~/.local/share/herdr`; `codex-update` runs OpenAI's standalone installer so app-server and `/agents` have the managed package tree under `~/.codex/packages/standalone`. The playbook runs both and systemd user timers run them weekly. `claude` updates itself. `suite-timing` runs the suite and reports wall time and guest memory |
| VICE | a user flatpak (`net.sf.VICE`). Its own binaries fail outside the flatpak's sandbox with a missing-library error, so the role writes a thin wrapper into `~/.local/bin` for each one, running `flatpak run --command=<name> net.sf.VICE "$@"`; `VICE_PATH`, which `wish`'s `.mcp.json` reads for the VICE MCP server, points at `~/.local/bin` |
| Node | 20, through `nvm`, on `PATH` for every shell through the same profile drop-in as `WISH_SPECIMENS`; it runs Agent HUD, installed globally from npm, and the VICE MCP server, `~/src/mcp-vice-emu`, pinned at `agent_guest_mcp_vice_commit` with a local patch committed on top (`roles/agent-vm-guest/files/mcp-vice-emu-attach.patch`) and built so `dist/index.js` exists |
| Ansible | `ansible` and `ansible-lint` from apt, to syntax-check and lint the sandbox playbooks under `ansible/` |
| pytest | pinned to the guest's vCPU count through `PYTEST_ADDOPTS` in `/etc/profile.d/agent-vm.sh`, read by login shells and, through a `~/.bashrc` hook, by interactive non-login ones (every ssh login, tmux pane and herdr pane), but not by `ssh agent-vm cmd`; use `ssh agent-vm 'bash -lc ...'` or `bash -ic ...` |
| Specimens | `specimens/` under `agent_vm_disks_dir` on the host, shared read-write with virtiofs at `/mnt/specimens`; `WISH_SPECIMENS` points at it |
| Game disks | `agent_vm_disks_dir` on the host, packed into `disks.img` under `agent_vm_base_dir` and mounted read-only at `/mnt/disks`; the guest's `gamedisks.yaml` points there |

The specimen tree is the one thing shared into the guest and the one thing it can write. The guest's `agent` user is uid 1000 (`agent_vm_uid`) and virtiofs passthrough maps guest uids straight to host uids, so what it writes is owned by uid 1000 on the desktop. The role checks that the directory is owned by that uid and stops if it is not, and it never changes the ownership of an existing tree; a desktop account with another uid needs `agent_vm_uid` set to it.

## The game disks

The guest reads the player's game data from a read-only virtual disk and cannot write to it, as `agent` or as `root`. Nothing on the LAN is mounted into the guest; the data is copied into an image on this host.

**You fill `agent_vm_disks_dir`.** One directory per `gamedisks.yaml` entry, named for the entry (`pool-of-radiance`, `amiga`, `kickstarts` and so on, the names `gamedisks.yaml.example` uses). **`codewheel` is not one of them:** it is your private repository, the guest clones it, and the role refuses to build the image while `codewheel` exists in that directory. For each entry in this machine's `gamedisks.yaml`, copy the first path that holds data, and only what the entry needs (a save disk named among a folder of downloads is one file, not the folder; a whole ROM library is only the Gold Box titles):

```bash
rsync -a "<the entry's first path that holds data>/" <agent_vm_disks_dir>/pool-of-radiance/
```

An entry with no data gets no directory, so the guest reports it missing; the exception is `coab-source` and `game-icons`, two public datasets the role downloads into `agent_vm_disks_dir` itself, so you supply every directory but those. `specimens/` in the same directory is the writable share and is never part of the image; `cited/` is.

**The role builds the image.** `mkfs.ext4 -d` packs a directory and has no exclude, so the role hard-links everything except `specimens/` into a staging directory beside the image, stops if a GitHub token or a private key is in it, sizes an ext4 image to fit with 5% and 64 MB to spare, and puts it in place by rename. It is rebuilt when a file in the source is added, removed or changed, and otherwise left alone, so re-running the role costs a `find`. The domain attaches it as `vdb` with `<readonly/>`, which makes QEMU open the file read-only: `mount -o remount,rw` fails for root too.

**A running guest does not see a new image.** The domain change and the rebuilt file both apply at the next start, and a reboot from inside the guest is not one. The role says so when it happens:

```bash
virsh shutdown agent-vm      # wait for it to power off
virsh start agent-vm
ansible-playbook -i ansible/inventory.yml ansible/agent-vm.yml
```

**Inside the guest** the image is `/mnt/disks`, mounted by its label `agent-disks` through `fstab` (`ro,nodev,nosuid,nofail`), so a guest started without the disk still boots. The role also writes `~/src/wish/gamedisks.yaml` there from `gamedisks.yaml.example`, with every path under `/mnt/disks` except `codewheel`, and stops if any other path is not. `python -m automap.gamedisks` in the checkout prints what it finds.

## Looking at the guest's code

The guest's `wish` checkout is mounted on the desktop, **read-only**, at `~/agent-wish`. Open it in a local editor:

```bash
code ~/agent-wish
```

It is an sshfs mount made by a systemd user unit, `agent-wish.service`, which mounts when you log in and needs nothing typed. It is mounted by you and not by root, so nothing needs `allow_other`.

| situation | what happens |
|---|---|
| A write | The kernel refuses it ("Read-only file system") whatever the guest's permissions say; nothing you do there can reach the guest |
| The guest reboots | The mount reconnects by itself; `ls` works again a few seconds after the guest answers ssh |
| The guest is down when you log in | systemd retries every 10 seconds until it is up |
| The guest is down or dies | ssh notices within a few seconds and a request on the mount returns an error rather than hanging; a stale mount left by a crash is cleared before each start |

`systemctl --user status agent-wish` says what it is doing, `journalctl --user -u agent-wish` says why it is not, and `fusermount3 -u ~/agent-wish` unmounts it by hand. The path, the remote directory and the timings are role variables (`agent_vm_wish_mount`, `agent_vm_wish_remote`, `agent_vm_wish_mount_alive`, `agent_vm_wish_mount_retry`). Symlinks that point at absolute paths inside the guest point at this desktop's, so follow them in the guest. **VS Code Remote SSH into the guest is not used**: it forwards your GitHub sign-in into the guest; the design document has the finding.

## The credential

The `wish-agent` GitHub App is the only credential in the guest: no ssh key, no `gh` login, nothing of yours. `docs/218-the-wish-agent-bot.md` says how to create, rotate and revoke it. The role copies the App's private key and `config.json` from `agent_guest_wish_agent_src` (default `~/.config/wish-agent`) on this machine, so they never enter this repository, to the same path under `agent`, mode `0600` in a `0700` directory.

| in the guest | what it does |
|---|---|
| `git` | takes its credential from `tools/wishagent.py git-credential`, the only helper it has: it answers `github.com` over https with a token minted for that request, and stores nothing |
| `/usr/local/bin/gh` | a wrapper, ahead of the real `gh` on `PATH` in every shell, that runs it with a freshly minted token; issues are filed with `tools/wishagent.py` |
| commits | authored as `wish-agent[bot]` |
| `agent_guest_private_repos` | other private repositories, cloned over https and pulled (`git pull --ff-only`) on every run, which stops rather than merge or overwrite the guest's own work; each must be on the App's repository access, with Contents read and write to push. The code-wheel repository, `agent_guest_codewheel_slug`, is the first at `~/src/goldbox-codewheel`, and the guest's `gamedisks.yaml` points its `codewheel` entry at the clone |

The App needs Issues, Contents and Workflows, all read and write, on the installation. A request for a permission beyond what the installation has been granted is refused by GitHub's API, which answers the token request with `422 The permissions requested are not granted to this installation`.

## The filter, and proving it

The `no-lan` libvirt network filter is attached to each guest's NIC. Evaluated as a packet leaves the guest, it accepts the guest's own subnet and drops every private range, so a LAN renumber does not open it; anything else, the internet through libvirt's NAT, is allowed. `100.64.0.0/10` is dropped as well: that is Tailscale's range.

A wrong filter fails silently, so the test is a task, not a memory. `ansible-playbook -i ansible/inventory.yml ansible/sandbox-isolation-test.yml` runs these checks. The first three run inside every running guest; the last two run only in a guest whose entry in `sandbox_net_probe_guests` names mounts and directories to look in, which is the Ubuntu guest and not the Windows one:

| check | how |
|---|---|
| the internet answers, and the peer guest does | a request and a ping |
| no `sandbox_net_lan_targets` machine answers | a ping and a TCP connect |
| `ssh` to `10.77.0.1` is refused while DNS through it works | a connect and a lookup |
| the writable mount can be written and the read-only one cannot | a write as `agent` and as `root`, and the device's write protection |
| no GitHub token (`ghp_`, `gho_`, `ghu_`, `ghs_`, `ghr_`, `github_pat_`) is in a file or a process environment | a search of `/home /root /etc /opt /tmp /var/tmp` and the game disks, and every process's environment |

Two things stop it passing for the wrong reason: every LAN target must answer the *host* first, or a blocked probe means nothing; and every probe prints a verdict of its own, so an ssh that never connected is told from a probe that was blocked. A guest that is not running is reported as **not tested**, never as passing, and so is a read-only mount that is not mounted yet. It changes nothing that persists (its probes touch and remove a temporary file), so it runs under `--check`, and it never contacts a pinhole's address. Run it every time the filter changes; editing the rules and re-running `sandbox-network.yml` updates running guests in place.

### The one hole

The C64 Ultimate is on the home LAN and the agents keep it, through one accept rule ahead of the drops, **a single address, never a subnet**, set in `ansible/inventory.yml`:

```yaml
sandbox_net_pinholes:
  - "<the Ultimate's address>"
```

Give the Ultimate a DHCP reservation so the address does not move.

### What the filter does not cover

The filter is on the guest's NIC and screens what leaves the guest. On the bridge address, `10.77.0.1`, which is the host, it lets through DNS (udp and tcp 53) and DHCP (udp 67) to libvirt's dnsmasq and drops everything else the guest sends there, `sshd` included. Nothing filters what the host sends to the guest, and the host's own firewall is not touched: the filter is the whole enforcement.

## The Windows guest

A throwaway Windows 11 Enterprise (evaluation) guest with WinUAE and VICE, running under QEMU/KVM and libvirt on the desktop and driven from Ansible. It is its own playbook so that rebuilding it never touches the Ubuntu guest, and it targets the `winvm_hosts` group, which holds the workstation. It shares the `sandbox` network with the agent guest, and the `no-lan` filter on its NIC keeps it off the home LAN.

```
virt-manager (SPICE console, local)
        │
        ▼
   win11 guest ── 10.77.0.11 ── virbr-sandbox ──NAT──> internet
                       ▲          (no-lan filter: the home LAN is unreachable)
                  RDP :3389 direct, no forwarding needed
```

### Step 1: the ISO

Microsoft's Evaluation Center gates the download behind a registration form, so there is no stable URL Ansible can fetch. Download the **64-bit English ISO** from <https://www.microsoft.com/en-us/evalcenter/evaluate-windows-11-enterprise> and set `winvm_iso_src` to it in `inventory.yml`; the playbook copies it into place. The evaluation runs 90 days. When it expires, tear down and rebuild:

```bash
ansible-playbook -i ansible/inventory.yml ansible/windows-vm-teardown.yml
ansible-playbook -i ansible/inventory.yml ansible/windows-vm.yml
```

### Step 2: the guest's password

Set `vault_windows_admin_password` in `group_vars/all/vault.yml`, which is the file you copied from `vault.yml.example`. Windows rejects weak passwords during unattended setup: 8 or more characters with three of upper, lower, digit and symbol. The role refuses to run with it undefined or shorter than eight. The guest's key for `winvm ssh` is your public key, `winvm_ssh_pubkey_path` (default `~/.ssh/id_ed25519.pub`), which the role puts in the guest's `administrators_authorized_keys`.

### Step 3: run the playbook

`windows-vm.yml` installs QEMU, libvirt and swtpm, creates the domain, builds the `autounattend.xml` ISO, and installs the `winvm` command. It does **not** start the guest.

### Step 4: install Windows

```bash
sudo virsh start win11 && \
  for i in $(seq 1 15); do sudo virsh send-key win11 --codeset linux KEY_ENTER; sleep 1; done
```

The keypress loop is not optional on the **first** boot. The blank disk has no EFI boot entry, so the firmware falls through to the DVD, and Microsoft's `efisys.bin` then puts up *"Press any key to boot from CD or DVD"* and waits; with nobody at the console it lapses into the firmware boot manager. Fifteen Enters over fifteen seconds covers the window. **Stop pressing keys after that:** once WinPE loads, stray keypresses land on Setup's UI and click through screens that `autounattend.xml` is trying to answer, which looks exactly like the unattend being ignored. Later boots need none of this.

From there Setup runs unattended: partitioning, OOBE, your local account, RDP, the static IP and the firewall rules all come from `autounattend.xml`. The install itself takes 45 minutes or more, then another 30 or so before ssh answers: first logon installs OpenSSH through `Add-WindowsCapability` with Windows Update switched off, which is slow and shows only an "Operation Running" bar in a PowerShell window. The address answers first (ping, then RDP on 3389) and sshd last, so a guest that pings and has no ssh is not stuck. One install measured 83 minutes from `virsh start` to ssh. Watch without touching anything:

```bash
sudo virsh screenshot win11 /tmp/w.png && xdg-open /tmp/w.png
```

or open the SPICE console in `virt-manager`. Once Windows is installed, detach the unattend ISO so the plaintext password stops riding along with the guest:

```bash
sudo virsh change-media win11 sdd --eject --config
```

### Step 5: use it

**First time only:** the playbook adds `winvm_user` to the `libvirt` group, but Linux grants group membership at login, so a desktop session opened beforehand still lacks it. virt-manager then fails with *"Unable to connect to libvirt qemu:///system"*, which is misleading: the daemon is running and your session cannot open its socket. Log out and back in, or run `sg libvirt -c virt-manager` now. `groups | grep libvirt` empty means this is the problem.

| goal | command |
|---|---|
| Console, with audio, working before networking | `virt-manager`, then double-click `win11` |
| Console, straight to the guest | `virt-viewer --connect qemu:///system win11` |
| Full desktop, drive redirection | `xfreerdp /v:10.77.0.11 /u:<winvm_admin_user> /cert:ignore /sound` |
| Run one command in the guest | `winvm ssh 'Get-Date'` |
| Copy a file in | `scp game.adf <winvm_admin_user>@10.77.0.11:C:/Amiga/` |
| See the screen from a script | `winvm shot /tmp/win11.png` |
| Start or stop from an agent | `winvm acquire <tag>` and `winvm release <tag>` |

SPICE carries audio, which is why it is used instead of VNC: WinUAE is not much use mute. The guest has an ICH9 HD Audio device, which Windows drives with its in-box driver. For a resizable desktop with drive redirection over RDP, add `/dynamic-resolution /clipboard /drive:dev,$HOME/src` and leave `/p:` off so it prompts rather than putting the password in your shell history. The address is the guest directly; there is no port forwarding. Some distributions, Ubuntu 24.04 among them, ship FreeRDP 2 as `xfreerdp`, which is creaky against 25H2 (*Timeout waiting for activation* after a successful NLA handshake, especially with the console already logged in as the same user); `sudo apt install freerdp3-x11` gives `xfreerdp3`, and Remmina uses the FreeRDP 3 libraries. A bare `STATUS_LOGON_FAILURE` is a wrong password.

### What the guest gets

| thing | how |
|---|---|
| WinUAE | installed at first logon from the unattend ISO, so no download is needed in the guest, to `C:\Program Files\WinUAE`; excluded from Defender real-time scanning |
| Kickstart ROMs | WinUAE ships none. `winvm_kickstart_src` is staged into the unattend ISO and copied to `C:\Amiga\Kickstarts`; raw dumps are recognised by CRC, and Cloanto/Amiga Forever ROMs (they begin `AMIROMTYPE1`) need `rom.key` in the same directory |
| Defender exclusions | `winvm_defender_exclusions`, applied at first logon, so a change means a rebuild; add one to a running guest with `Add-MpPreference -ExclusionPath 'C:\Amiga'` in an elevated PowerShell |
| VICE | unpacked, not installed, to `C:\VICE`, binary at `C:\VICE\bin\x64sc.exe`; `winvm_install_vice: false` skips it, and the log at `C:\Windows\Temp\guest-setup.log` has the result under `install VICE` |
| VICE settings | `vice.ini.j2`, written to the guest's profile at first logon only if absent; the binary monitor is on at `127.0.0.1:6502` (`winvm_vice_binary_monitor`, `winvm_vice_binary_monitor_port`) |
| JiffyDOS | `winvm_jiffydos_src` into `C:\C64\JiffyDOS`; empty skips it, and VICE uses the stock kernal |
| QXL display driver | installed with `pnputil` from the virtio ISO (`winvm_install_qxl`); on a guest without the driver, run `pnputil /add-driver E:\qxldod\w10\amd64\qxldod.inf /install` from the attached virtio volume, then reboot |

### The `winvm` command

`/usr/local/bin/winvm` is installed by the playbook and is the intended way to drive the guest, by hand or from a script. Every state-changing command takes an `flock`, so concurrent callers serialise instead of racing.

| command | what it does |
|---|---|
| `winvm status` | State, golden base size, overlay size, and who holds leases |
| `winvm up` | Start (or restore a saved state) and block until ssh answers |
| `winvm down` | Graceful shutdown; force-off after 2 minutes if it hangs |
| `winvm save` | `managedsave`: suspend to disk; `up` then resumes in seconds |
| `winvm acquire <tag>` | Take a named lease and start the guest if it is not up |
| `winvm release <tag>` | Drop that lease; shuts down only when the last one goes |
| `winvm promote` | Flatten the current disk into the golden base (one-off, after install) |
| `winvm revert` | Throw away everything since golden, in about a second |
| `winvm shot [file]` | Framebuffer screenshot; works regardless of session state |
| `winvm ssh [cmd...]` | ssh into the guest as `winvm_admin_user` |
| `winvm guest-setup` | Re-run the first-logon install script (WinUAE, VICE, QXL, ROMs) on a running guest, so a role change reaches it without a rebuild; the static IP and Defender exclusions are set in autounattend.xml and still need a rebuild |
| `winvm scp ...` | `scp` with the guest's options |

### Leases, for several agents

`up` and `down` are fine for one caller. With several agents sharing the guest they race, so leases reference-count it:

```bash
winvm acquire re-session-1     # starts it if needed
winvm acquire fuzz-run-7       # no-op, already up
winvm release re-session-1     # still held by fuzz-run-7, stays up
winvm release fuzz-run-7       # last lease gone, shuts down
```

**A tag is an identity.** Taking a tag that is already held is refused, and the error says to pick one of your own (`winvm acquire re-session-1-$$`) or, if the lease is stale, to `winvm release` it. Leases are files in `leases` under `winvm_base_dir` (`/var/lib/libvirt/winvm/leases` by default); a lease cannot outlive the boot it was taken in, so `acquire` clears the directory when it finds the guest off. `winvm status` lists what is held.

### Reverting to a clean state

After the install finishes, freeze it once:

```bash
winvm down
winvm promote        # win11.qcow2 -> win11-golden.qcow2 + a fresh overlay
winvm revert         # from then on: delete the overlay, recreate it, restore the UEFI varstore
```

To adopt the current state as the new baseline, for instance after installing a debugger you want in every session, delete the golden file and re-promote:

```bash
winvm down && sudo rm /var/lib/libvirt/winvm/win11-golden.qcow2 && winvm promote
```

`virsh` works directly, and needs `sudo` without the `libvirt` group in your session: `virsh start|shutdown|destroy win11`, `virsh list --all`, `virsh domifaddr win11 --source agent` (needs the guest agent). Set `winvm_autostart: false` to start the guest by hand instead of with the host.

### Forwarding extra ports

The guest is reachable from the desktop directly. To reach a server inside it from another machine, add to `inventory.yml`:

```yaml
winvm_forwarded_ports:
  - { name: rdp,       port: 3389 }
  - { name: devserver, port: 5173 }
```

and re-run `windows-vm.yml`. Each entry gets a `socat` systemd unit on the host, listening on `winvm_forward_listen_address` (default all interfaces), and an inbound Windows Firewall rule in the guest. The guest rules are applied by `autounattend.xml`, so a port added later needs its rule added by hand inside Windows, or a rebuild.

### Troubleshooting

| symptom | cause and fix |
|---|---|
| Sitting at "Press any key to boot from CD or DVD", or at a boot-device menu | The keypress window was missed (Step 4). At the boot menu pick **UEFI QEMU DVD-ROM QM00003** (`sdb`, the Windows ISO; `QM00005` and `QM00007` are the virtio and unattend ISOs and are not bootable), then send Enter again for the "press any key" prompt |
| Setup shows its normal interactive screens | Almost always stray keypresses, which click whatever button has focus. Destroy the guest, recreate the disk, and retry hands-off: `sudo virsh destroy win11; sudo rm -f /var/lib/libvirt/winvm/win11.qcow2`, then run `windows-vm.yml` again. If the unattend really is ignored, Windows 11 24H2's new setup engine ("ConX", `SetupPrep.exe`) has reported unattend regressions, and the usual workaround is a `winpeshl.ini` in `boot.wim` calling `setup.exe /legacy`; build 26200.6584 (25H2) has not needed it |
| "Windows cannot be installed to this disk" | The ISO shipped more than one image. `sudo wiminfo` on the mounted ISO's `sources/install.wim` lists the indexes; set `winvm_image_index` |
| RDP refuses the connection | Check the guest is up and has its address: `sudo virsh domifaddr win11 --source agent; sudo virsh domstate win11` |
| No internet inside the guest | Almost always Docker's `FORWARD DROP`. `sandbox-network` pins libvirt to the iptables backend only when the `/etc/libvirt/network.conf` the package ships mentions `firewall_backend`. Check the pin is there and libvirt reloaded: `grep firewall_backend /etc/libvirt/network.conf; sudo iptables -S FORWARD \| head` |
| The guest has no address at all | It addresses itself from the first-logon script. `virsh net-list` should show `sandbox` active and `virbr-sandbox` holding `10.77.0.1`; inside Windows, `Get-NetIPAddress -AddressFamily IPv4` empty or showing a 169.254.x.x address means re-running the static configuration by hand, the command being in `unattend/autounattend.xml` under `winvm_state_dir` |
| Setup stops on a compatibility screen | `Shift+F10` for a console, and check `HKLM\SYSTEM\Setup\LabConfig` has the bypass values; if not, the unattend ISO was not attached |

## Removing it

```bash
ansible-playbook -i ansible/inventory.yml ansible/agent-vm-teardown.yml
ansible-playbook -i ansible/inventory.yml ansible/windows-vm-teardown.yml
```

The Ubuntu teardown force-stops and undefines the domain, stops the sshfs mount unit and deletes its file, and removes the guest's disk, the game disks image and its staging copy, the state directory (the seed ISO, the generated domain XML and the stamps), the ssh alias and the AppArmor override. It leaves `agent_vm_disks_dir` (yours, and where `coab-source` and `game-icons` were downloaded), the downloaded cloud image, the login key, and the empty mount point `agent_vm_wish_mount` (`~/agent-wish`). The Windows teardown force-stops the domain and undefines it (with `--nvram`, or libvirt refuses and orphans the UEFI varstore), removes the port-forward units, the whole `winvm_base_dir` tree and the AppArmor override.

Neither teardown removes the `sandbox` network, the `no-lan` filter or the libvirt firewall-backend pin, which both guests share, and neither removes the QEMU and libvirt packages, since pulling about 99 packages off a host is a bigger change than removing a guest; `sudo apt purge --autoremove qemu-system-x86 libvirt-daemon-system swtpm` finishes the job. libvirt's `default` network is left as it is: stopped and not autostarting only if `winvm_disable_default_network` was set when the guest was built.

## Monitoring

The Ubuntu guest runs `prometheus-node-exporter` on its sandbox address and `agent_guest_exporter_port` (default 9100), and nothing that ships metrics or holds a credential. Whatever scrapes it runs on the desktop and is set up outside this directory. If a metric is missing, `curl http://10.77.0.10:9100/metrics` from the desktop says whether the exporter answers.
