#!/usr/bin/env python3
"""Re-jailbreak an iPhone 6 (A8, iOS 12.0.1) with checkra1n after a reboot.

Run as root (USB access): sudo -E python3 scripts/rejailbreak.py   (needs pyusb, libusb, iproxy)
Environment: CHECKRA1N=/path/to/checkra1n  IPROXY=/path/to/iproxy  REJAILBREAK_LOG=file
Steps:
  1. start `checkra1n -c -p` (stops at the pongoOS shell instead of auto-booting)
  2. you put the phone in DFU (Power+Home 8s, release Power, hold Home 5s)
  3. wait for pongoOS to finish loading, then send `bootx`
  4. wait for the phone to boot and for SSH (over a USB tunnel) to answer
"""
import os, socket, subprocess, sys, time
import usb.core

import shutil
CHECKRA1N = os.environ.get("CHECKRA1N") or shutil.which("checkra1n") or "./checkra1n"
LOG = os.environ.get("REJAILBREAK_LOG", "rejailbreak.log")
IPROXY = os.environ.get("IPROXY", "iproxy")
SETTLE = 6          # seconds to wait after pongoOS says it is ready
PORT = 2299         # local port for the SSH check tunnel


def say(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def find_pongo(timeout):
    t0 = time.time()
    while time.time() - t0 < timeout:
        dev = usb.core.find(idVendor=0x05AC, idProduct=0x4141)
        if dev is not None:
            return dev
        time.sleep(0.5)
    return None


def drain(dev, timeout):
    """Read pongoOS shell output until it reports nothing in progress."""
    t0, out = time.time(), b""
    while time.time() - t0 < timeout:
        st = bytes(dev.ctrl_transfer(0xA1, 2, 0, 0, 1))
        data = bytes(dev.ctrl_transfer(0xA1, 1, 0, 0, 0x1000))
        out += data
        if st and st[0] == 0 and not data:
            break
        if not data:
            time.sleep(0.1)
    return out.decode("latin1")


def wait_ssh(timeout):
    """True once the phone's sshd answers with a banner through a USB tunnel."""
    proc = subprocess.Popen([IPROXY, str(PORT), "22"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        t0 = time.time()
        while time.time() - t0 < timeout:
            try:
                with socket.create_connection(("127.0.0.1", PORT), timeout=4) as s:
                    s.settimeout(4)
                    if s.recv(16).startswith(b"SSH-"):
                        return True
            except OSError:
                pass
            time.sleep(3)
        return False
    finally:
        proc.terminate()


def main():
    if os.geteuid() != 0:
        sys.exit("run as root (needs USB access): sudo -E python3 scripts/rejailbreak.py")
    if subprocess.run(["pgrep", "-x", "checkra1n"], capture_output=True).returncode == 0:
        sys.exit("another checkra1n is already running - stop it first")
    say("starting checkra1n in pongo-shell mode (log: %s)" % LOG)
    log = open(LOG, "w")
    c1 = subprocess.Popen([CHECKRA1N, "-c", "-p", "-V", "-v", "-l", LOG + ".c1"], stdout=log, stderr=log)
    try:
        say("PUT THE PHONE IN DFU NOW: Power+Home 8s, release Power, hold Home 5s (screen stays black)")
        dev = find_pongo(240)
        if dev is None:
            sys.exit("pongoOS never appeared - DFU/exploit did not succeed; try again")
        say("pongoOS is up; waiting for it to finish loading")
        dev.set_configuration()
        seen, t0 = "", time.time()
        while "stopping here" not in seen and time.time() - t0 < 90:
            seen += drain(dev, 3)
        if "stopping here" not in seen:
            sys.exit("pongoOS did not reach its prompt; output was:\n" + seen[-600:])
        say("pongoOS is ready (kpf loaded); settling %ds" % SETTLE)
        time.sleep(SETTLE)
        say("sending bootx")
        try:
            dev.ctrl_transfer(0x21, 3, 0, 0, b"bootx\n")
        except usb.core.USBError:
            pass        # expected: the device resets as the kernel starts
        say("kernel is starting; waiting for the phone and its SSH server (up to 4 min)")
        if wait_ssh(240):
            say("SUCCESS: jailbreak is active, SSH answers")
            return 0
        say("FAILED: phone did not come up jailbroken (no SSH). Check the phone's screen and %s" % LOG)
        return 1
    finally:
        c1.terminate()
        try:
            c1.wait(10)
        except subprocess.TimeoutExpired:
            c1.kill()


if __name__ == "__main__":
    sys.exit(main())
