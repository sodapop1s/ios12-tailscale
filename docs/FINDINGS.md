# Findings: every problem, its symptom, its cause, its fix

Environment for everything below: iPhone 6 (A8, `iPhone7,2`, board N61), iOS 12.0.1 (16A404), checkra1n
0.12.4, Procursus bootstrap from odysseyra1n, Linux host. "Verified" means it was observed on that phone;
"hypothesis" means it fits the evidence but was not isolated.

Unless noted, the phone-side commands are run over SSH as root.

---

## 1. Binary is killed instantly (`zsh: killed`, exit code 137)

**Symptom:** any binary you built or re-signed dies the moment it starts. Kernel log (`dmesg`):
`Sandbox: ... System Policy: deny(1) process-exec* ... process-exec denied while updating label`.
Even a *copy of the system's own* `/usr/bin/uname`, re-signed with `ldid -S`, died.

**Cause (verified):** `ldid`'s default signature has only a SHA-256 code directory and no entitlements. This
iOS 12 kernel (with checkra1n's patches) only accepted a signature carrying SHA-1 as well.

**Fix:** sign **on the phone** with both hashes, the ad-hoc flag, and entitlements copied from a system binary:

```sh
ldid -e /usr/bin/uname > ents.plist
ldid -Cadhoc -Hsha1 -Hsha256 -Sents.plist ./tailscaled
```

The `uname` entitlements are `platform-application`, `com.apple.private.security.no-container` and
`com.apple.private.skip-library-validation`. Signing with `-Hsha1 -Hsha256` alone made the re-signed `uname`
run; the Go binaries needed the entitlements as well (hypothesis: only the combination was tested for them).
Signing on the computer (an `ldid` built for another platform) was never confirmed to work.

## 2. `dyld: malformed mach-o image: segment load command __DWARF filesize ... is larger than vmsize`

**Cause (verified):** Go emits a `__DWARF` segment for debug info; iOS's dyld rejects it.
**Fix:** `go build -ldflags="-s -w"`.

## 3. `dyld: Library not loaded: .../CoreFoundation.framework/Versions/A/CoreFoundation`

**Cause (verified):** Go's darwin/arm64 build links the macOS framework layout. iOS has no `Versions/A`.
**Fix:** patch the two `LC_LOAD_DYLIB` paths (CoreFoundation, Security) in place; `scripts/macho.py` does it.

**Do not relabel the Mach-O platform as iOS.** A binary whose `LC_BUILD_VERSION` was changed to platform iOS
ran at 100% CPU and never produced output; the same program left as "macOS 12" ran fine. (Why is not known.)

## 4. `dyld: Symbol not found: _SecTrustCopyCertificateChain` (Go 1.25 only)

**Cause (verified):** Go 1.24+/1.25 uses a Security API added in iOS 15 for certificate verification.
**Fix:** use Go 1.22.12 (does not need it). With Go 1.25 it can be worked around by patching the standard library
with `-overlay` so `crypto/x509` uses `SecTrustGetCertificateCount`/`SecTrustGetCertificateAtIndex` (this was done
and the binary then loaded), but see #6 for what happened next.

## 5. DNS never resolves; `tailscale up` prints nothing; log shows `context deadline exceeded`

**Cause (verified):** a hello-world calling `net.LookupHost` hung forever with Go's default darwin resolver
(libresolv). With `GODEBUG=netdns=go` the same program resolved, dialed TCP/UDP and made HTTPS requests
immediately. `/etc/resolv.conf` on the phone is fine.
**Fix:** build in Go's own resolver: put `//go:debug netdns=go` + `package main` in a file in each `cmd/` package
(`build.py` does this temporarily).

Note: *setting `GODEBUG=netdns=go` as an environment variable* appeared to make `tailscaled` hang on startup. That
was probably #6 striking at random (hypothesis), but the compiled-in setting was used from then on.

## 6. `tailscaled` spins at 25-50% CPU, never creates its socket, stalls at a *different* place each run

**Symptoms:** `kernel: process tailscaled caught waking the CPU 45001 times over ~0 seconds, averaging
~100000 wakes/second`. `GODEBUG=inittrace=1` showed it stopping after 15, 38, 71 or 126 package initialisations
in different runs of the same binary. A watchdog goroutine never fired. SIGQUIT showed `goroutine 1 ...
running on other thread; stack unavailable`. A small Go test program (timers, goroutines, unix sockets,
net.Interfaces, AfterFunc) ran perfectly, so the runtime in general works.

**Fix (verified):** `GODEBUG=asyncpreemptoff=1`. Without it the same daemon came up only occasionally (a few early successes, then 0 of 6 in a row);
with it, 3 of 3 starts succeeded and the daemon then sat at 0% CPU, and it has started cleanly across a reboot since.
`GOMAXPROCS=1` alone: 1/3. **Hypothesis:** Go's signal-based (SIGURG) goroutine preemption does not work on this
kernel and the runtime spins waiting for a preempted thread. The Go 1.25/Tailscale 1.90 spin described in the
first test round was probably the same thing, but it was never retried with `asyncpreemptoff` (untested).

Use it for both `tailscaled` and the `tailscale` CLI (the CLI hung too); the launch job and the wrapper in
`device/` set it.

## 7. Under launchd the daemon dies after a second: `EXC_RESOURCE ... exceeded mem limit: InactiveHard 6 MB (fatal)`

`launchctl list` showed status -9. Started by hand over SSH the same binary was fine.

**Cause (verified):** limits for launchd jobs come from Apple's table
`/System/Library/LaunchDaemons/com.apple.jetsamproperties.N61.plist` (N61 = iPhone 6; other models have their own
file), under `Version4 > Daemon > Override > <job Label>` with `ActiveSoftMemoryLimit` / `InactiveHardMemoryLimit`
in MB. Unknown labels get the tiny default.

**Things that did not help (verified):** `JetsamProperties` (with `JetsamMemoryLimit`, `JetsamPriority`, and
`ActiveHardMemoryLimit`/`InactiveHardMemoryLimit`) inside the job's own plist; `POSIXSpawnType`/`ProcessType
Interactive`; `ExecuteAllowed`.

**Fix (verified):** add one entry for the job's label to that table (`scripts/jetsam_patch.py`, 300 MB) and reboot.
Edit a copy, validate it, keep a backup of the original on the phone. After the reboot, launchd ran the daemon
at ~0.4% CPU with no kills. This edits an Apple system file on a jailbroken phone: do it deliberately.

## 8. launchd job not loaded at boot

After rebooting, the launch job was **not** loaded. **Hypothesis (not isolated):** an earlier `launchctl unload -w <plist>` had marked the
job disabled in `/var/db/com.apple.xpc.launchd/disabled.plist` (after `load -w` that file listed the label as `false`), and the flag
survives deleting and re-adding the plist. After `launchctl load -w <plist>` the job loaded by itself on the next jailbroken boot
(observed once). Its first start reported exit status 78 (`LastExitStatus` 19968) and KeepAlive restarted it a moment later;
it healed itself.

## 9. `ssh` to the phone's tailnet address reaches its sshd

Verified: from another tailnet machine, a TCP connection to the phone's tailnet IP on port 22 returned the phone's
`OpenSSH` banner, although the node runs in userspace-networking mode. (Log in as `mobile` or `root`, not as
your local username.)

---

## checkra1n on Linux after the bootstrap

Context: the first checkra1n run on a stock phone worked. After running odysseyra1n and rebooting, **many**
runs showed `Exploiting ... Checkmate! ... Entered download mode ... Booting...` on the host, but the phone then
booted *stock*: only the plain Apple logo (no white pongoOS text), then the lock screen, and nothing listened on
SSH (checkra1n keeps logging `usbmux: Failed to connect (error code: -79)` because the agent on port 1337 isn't there).
The reboot reports on the phone (`ResetCounter-*.ips`, via `idevicecrashreport -k`) showed clean resets with no
boot fault and **no kernel panic**.

What *did* turn out to be an unrelated cause of failures: **two checkra1n processes running at once** (each
fights over the one USB device: `USB Error -77`, `Exploit Failed -21/-31`). Always check `pgrep -a checkra1n`.

What worked: `checkra1n -c -p` stops at the pongoOS shell ("Pongo shell requested, stopping here!") with the
kernel patcher module loaded. Talking to that shell over USB (`scripts/pongo.py`, protocol from PongoOS's
`pongoterm.c`: control transfer `0x21/3` sends a command, `0xa1/1` reads output, `0xa1/2` says whether output is
still in progress), then sending **`bootx`** produced a normal jailbroken boot (verbose checkra1n text on the
screen, SSH up ~30 s later). `scripts/rejailbreak.py` automates this and worked on the next reboot too.
**Why the automatic boot fails and the manual one works is not known** (hypothesis: timing; pongoOS needs a few seconds after
loading before `bootx`, and the script waits for the shell prompt plus a short settle).

Other notes: `usbmuxd` can stay running. The `-79` line at the end of a
shell-mode run is harmless: it is checkra1n's host side looking for the post-boot agent.

## Dead ends (so you don't repeat them)

* Tailscale 1.90.9 + Go 1.25.10: needed the x509 overlay (#4); then spun (#6, likely `asyncpreemptoff`, untested there).
* Relabelling the Mach-O as iOS (#3).
* Keys in the job plist for memory (#7).
* The official Tailscale app, `apt` packages: none exist for iOS 12 in the Procursus/Odyssey/Havoc/Chariz repos
  (searched for `tailscale`, `wireguard`).
* `GODEBUG=netdns=go` via environment variable (#5 note).
