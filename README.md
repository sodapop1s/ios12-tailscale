# Tailscale on a jailbroken iPhone 6 (iOS 12.0.1, checkra1n)

> **Notice: AI-assisted ("vibe-coded") project.** The scripts, patches and documentation in this repo were
> written mostly by an AI coding assistant (Claude Code) working interactively with the phone's owner, who ran
> the hardware steps and tested everything on one phone. The code has **not** been audited or reviewed by a
> security professional, several results were observed only once, and the scripts run as root and edit
> system files on a jailbroken device. Read the code before you run it, and keep a backup.

Run a real `tailscaled` on an old, **checkra1n-jailbroken, A8-class iPhone on iOS 12** so it joins your
tailnet, using Tailscale's own open-source client built with an older Go toolchain. The official Tailscale
app needs a much newer iOS and can't be installed on this phone.

This repo is the notes, patches and scripts from getting that working. It was done on one phone, so read
[Status](#status) before trusting it.

## Status

Tested on: **iPhone 6 (iPhone7,2, A8), iOS 12.0.1, checkra1n 0.12.4, Procursus bootstrap via odysseyra1n,
Linux (NixOS) host.**

| Claim | Evidence |
|---|---|
| Tailscale **1.68.2** built with **Go 1.22.12** runs on the phone and joins a tailnet | works; phone showed online, pinged at 10-15 ms, direct (no relay) |
| Other tailnet machines can SSH to the phone's own `sshd` over the tailnet | observed (userspace mode forwards inbound connections to localhost) |
| launchd starts `tailscaled` at boot with no manual step | **verified once** (one full reboot cycle) |
| `scripts/rejailbreak.py` re-jailbreaks after a reboot | **worked once** end-to-end (took two DFU attempts; the first hit the usual exploit failure) |
| `scripts/build.py` produces binaries that run | yes: its output was copied to the phone, signed, and run |
| `scripts/install_on_phone.py` | the steps were each done by hand on the phone; the script itself was only **dry-run tested** |

**Not tested:** other iPhones / iOS versions, macOS or Windows hosts, Go or Tailscale versions other than the
pair above (newer ones failed, see `docs/FINDINGS.md`), long-term stability, Tailscale features other than
joining and routing.

This is an unofficial build. Tailscale does not support it. Use at your own risk, and never run any
restore/erase/update command on a phone with data you care about (see [Safety](#safety)).

## What you get

* The phone is a normal tailnet node (`tailscaled --tun=userspace-networking`; there is no TUN device).
* Other nodes can reach the phone's ports (for example SSH) over the tailnet.
* Programs *on the phone* reach the tailnet through a local SOCKS5 proxy on `localhost:1055`.

## The short version of what was hard

Every one of these cost hours; the details and evidence are in [`docs/FINDINGS.md`](docs/FINDINGS.md).

1. **Signing:** iOS 12 kills ad-hoc binaries signed with SHA-256 only. Sign **on the phone** with
   `ldid -Cadhoc -Hsha1 -Hsha256 -S<entitlements>` and copy entitlements from a system binary.
2. **Debug info:** strip it (`-ldflags="-s -w"`); Go's `__DWARF` segment makes `dyld` reject the file.
3. **Framework paths:** rewrite `.../Versions/A/CoreFoundation` to `.../CoreFoundation` (and `Security`).
   Do **not** relabel the platform as iOS (a relabelled binary spun forever).
4. **DNS:** Go's default darwin resolver hangs on iOS 12. Build with `//go:debug netdns=go`.
5. **Runtime hang:** run with `GODEBUG=asyncpreemptoff=1`. Without it the Go runtime wedges at random
   points during startup (and used 100k CPU wake-ups/second).
6. **launchd memory limit:** jobs get a ~6 MB limit and are killed. Add an entry for the job's label to
   Apple's `com.apple.jetsamproperties.<MODEL>.plist` (a reboot is needed). Keys in the job's own plist did nothing.
7. **Re-jailbreaking:** after bootstrapping, checkra1n's normal auto-boot kept producing a stock boot.
   Booting to the pongoOS shell (`checkra1n -p`) and then sending `bootx` worked. The cause is unknown.

## Quick start

You need the phone already jailbroken with checkra1n and bootstrapped (Procursus/Sileo via odysseyra1n),
`openssh` and `ldid` installed on it, SSH reachable (for example `iproxy 2222 22`), and **the default
`alpine` passwords changed**.

```sh
# 1. build (downloads Go 1.22.12 and verifies its published SHA-256; clones Tailscale v1.68.2)
python3 scripts/build.py

# 2. sign + install on the phone (see --help; use --dry-run first)
python3 scripts/install_on_phone.py --host 127.0.0.1 --port 2222 --dry-run
python3 scripts/install_on_phone.py --host 127.0.0.1 --port 2222

# 3. the jetsam change only applies after a reboot: reboot, re-jailbreak (below), then on the phone:
launchctl load -w /Library/LaunchDaemons/com.local.tailscaled.plist
tailscale up --hostname=my-iphone --accept-dns=false     # prints a login URL; open it yourself
```

After that, launchd should start Tailscale on every jailbroken boot.

## Re-jailbreaking after a reboot or power loss

The phone is semi-tethered: a reboot comes up stock until checkra1n runs again.

```sh
sudo -E env CHECKRA1N=/path/to/checkra1n IPROXY=$(command -v iproxy) python3 scripts/rejailbreak.py
```

It starts `checkra1n -c -p` (stop at the pongoOS shell), waits for pongoOS to finish loading, sends
`bootx`, then waits for SSH. **You** do the DFU buttons (Power+Home 8 s, release Power, hold Home 5 s).
The exploit step fails now and then (`error code -21`/`-31`); just re-enter DFU while it waits.
Needs `pyusb` and `libusb`. Run only **one** checkra1n at a time: two copies fight over the USB device
and look exactly like a flaky exploit. `scripts/pongo.py` sends a single command to the pongoOS shell.

## Safety

* **Never restore, erase, update or "revert rootfs"** a phone whose data you can't replace. Nothing here needs it.
* Back up first (`idevicebackup2 backup --full`). Photos that live only in iCloud are **not** in a local backup.
* `jetsam_patch.py` edits an Apple system file. It only adds one entry, verifies that, and the installer
  keeps a backup next to the binaries. To undo, copy the backup over the file and remove the launch job.
* Change the default `alpine` passwords before the phone sits on a shared network, and prefer key-only SSH.
  Anyone on your tailnet who can reach the phone's port 22 can try to log in.

## Credits

[checkra1n](https://checkra.in) and [pongoOS](https://github.com/checkra1n/PongoOS) (the `pongo.py` protocol is
from their `pongoterm.c`), [Tailscale](https://github.com/tailscale/tailscale), the Procursus/Odyssey bootstraps.
This repo contains none of their code except the tiny protocol re-implementation noted above.

## License

MIT, see `LICENSE`.
