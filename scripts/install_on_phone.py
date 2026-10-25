#!/usr/bin/env python3
"""Sign and install the built binaries + launch job on a jailbroken iOS 12 phone over SSH.

  python3 scripts/install_on_phone.py --host 127.0.0.1 --port 2222 [--key KEY] [--model N61] [--dry-run]

Reach the phone over a USB tunnel (`iproxy 2222 22`) or Wi-Fi. You will be asked for the
phone's root password unless you pass --key. Requires `ldid` on the phone (apt install ldid).

What it does (each step is printed):
  1. copies out/tailscaled and out/tailscale to /var/root/ts/
  2. signs them ON THE PHONE with SHA-1+SHA-256 hashes, ad-hoc flag and the entitlements
     copied from /usr/bin/uname (a signature from a computer's ldid, or SHA-256 only, is killed)
  3. installs /usr/bin/tailscale (wrapper) and the launch job plist
  4. backs up and patches Apple's jetsam table (asks first; needs a reboot to take effect)
It does NOT start anything; see README for first start and `tailscale up`.
"""
import argparse, os, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", default="2222")
    ap.add_argument("--key")
    ap.add_argument("--model", default="N61", help="jetsam table suffix (N61 = iPhone 6)")
    ap.add_argument("--dry-run", action="store_true", help="print the steps, change nothing")
    ap.add_argument("--yes", action="store_true", help="do not ask before editing Apple's jetsam table")
    a = ap.parse_args()

    ssh_opts = ["-p", a.port, "-o", "UserKnownHostsFile=/dev/null", "-o", "StrictHostKeyChecking=no"]
    if a.key:
        ssh_opts += ["-i", a.key, "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes"]
    dest = f"root@{a.host}"
    scp_opts = ["-P" if o == "-p" else o for o in ssh_opts]

    def ssh(cmd):
        print("phone$", cmd)
        if not a.dry_run:
            subprocess.run(["ssh"] + ssh_opts + [dest, cmd], check=True)

    def scp_to(files, remote):
        print("scp", *[os.path.relpath(f, ROOT) for f in files], "->", remote)
        if not a.dry_run:
            subprocess.run(["scp"] + scp_opts + files + [f"{dest}:{remote}"], check=True)

    for f in ("out/tailscaled", "out/tailscale"):
        if not os.path.exists(os.path.join(ROOT, f)):
            sys.exit(f"{f} missing - run scripts/build.py first")

    jet = f"/System/Library/LaunchDaemons/com.apple.jetsamproperties.{a.model}.plist"
    if not a.dry_run and not a.yes:
        print(f"This will EDIT AN APPLE SYSTEM FILE on the phone:\n  {jet}\n"
              "It adds one entry raising the memory limit of the Tailscale launchd job (default ~6 MB -> 300 MB).\n"
              "A backup is kept at /var/root/ts/. Nothing else in the file changes.")
        if input("Type 'yes' to continue: ").strip().lower() != "yes":
            sys.exit("aborted; nothing was changed")
    ssh("which ldid >/dev/null || { echo 'ldid missing: apt install ldid'; exit 1; }")
    ssh("mkdir -p /var/root/ts")
    scp_to([os.path.join(ROOT, "out/tailscaled"), os.path.join(ROOT, "out/tailscale")], "/var/root/ts/")
    ssh("cd /var/root/ts && ldid -e /usr/bin/uname > ents.plist && chmod +x tailscaled tailscale "
        "&& for f in tailscaled tailscale; do ldid -Cadhoc -Hsha1 -Hsha256 -Sents.plist $f; done")
    scp_to([os.path.join(ROOT, "device/tailscale-wrapper.sh")], "/usr/bin/tailscale")
    ssh("chmod 755 /usr/bin/tailscale")
    scp_to([os.path.join(ROOT, "device/com.local.tailscaled.plist")], "/Library/LaunchDaemons/")
    ssh("chown root:wheel /Library/LaunchDaemons/com.local.tailscaled.plist "
        "&& chmod 644 /Library/LaunchDaemons/com.local.tailscaled.plist")

    # jetsam table: fetch, patch locally, verify, back up on the phone, install
    tmp = tempfile.mkdtemp()
    orig, patched = os.path.join(tmp, "orig.plist"), os.path.join(tmp, "patched.plist")
    if a.dry_run:
        print(f"(dry run) would copy {jet} here, run jetsam_patch.py, back it up to /var/root/ts/ and install the patched copy")
    else:
        subprocess.run(["scp"] + scp_opts + [f"{dest}:{jet}", orig], check=True)
        subprocess.run([sys.executable, os.path.join(HERE, "jetsam_patch.py"), orig, patched], check=True)
        ssh(f"[ -e /var/root/ts/jetsam.{a.model}.ORIGINAL.plist ] || cp -p {jet} /var/root/ts/jetsam.{a.model}.ORIGINAL.plist")
        scp_to([patched], f"/var/root/ts/jetsam.{a.model}.patched.plist")
        ssh(f"cat /var/root/ts/jetsam.{a.model}.patched.plist > {jet} && chown root:wheel {jet} && chmod 644 {jet}")
    shutil.rmtree(tmp, ignore_errors=True)
    print(("\n(dry run - nothing was changed)" if a.dry_run else "\nInstalled.") + " Reboot, re-jailbreak, then start with:\n"
          "  launchctl load -w /Library/LaunchDaemons/com.local.tailscaled.plist   (use -w; an earlier 'unload -w' leaves it disabled)\n"
          "  tailscale up --hostname=<name> --accept-dns=false   (open the printed login link yourself)")


if __name__ == "__main__":
    main()
