#!/usr/bin/env python3
"""Add a memory-limit entry for our launchd job to Apple's jetsam table.

Why: jobs started by launchd on iOS 12 get a tiny default memory budget
("InactiveHard 6 MB" in the kernel log) and Tailscale is killed immediately.
The limits come from /System/Library/LaunchDaemons/com.apple.jetsamproperties.<MODEL>.plist,
keyed by the job's Label. Keys inside the job's own plist (JetsamProperties,
ActiveHardMemoryLimit, ...) were tried and had no effect.

  python3 jetsam_patch.py IN.plist OUT.plist [--label com.local.tailscaled] [--mb 300]

IN is a copy of the phone's file (the model name is e.g. N61 for iPhone 6).
The tool only adds one entry and refuses to change anything else.
"""
import argparse, plistlib

ap = argparse.ArgumentParser()
ap.add_argument("src"); ap.add_argument("dst")
ap.add_argument("--label", default="com.local.tailscaled")
ap.add_argument("--mb", type=int, default=300)
a = ap.parse_args()

orig = plistlib.load(open(a.src, "rb"))
new = plistlib.loads(plistlib.dumps(orig))
override = new["Version4"]["Daemon"].setdefault("Override", {})
override[a.label] = {"ActiveSoftMemoryLimit": a.mb, "InactiveHardMemoryLimit": a.mb}
plistlib.dump(new, open(a.dst, "wb"), fmt=plistlib.FMT_BINARY)

check = plistlib.load(open(a.dst, "rb"))
del check["Version4"]["Daemon"]["Override"][a.label]
if a.label in orig["Version4"]["Daemon"]["Override"]:
    check["Version4"]["Daemon"]["Override"][a.label] = orig["Version4"]["Daemon"]["Override"][a.label]
assert check == orig, "unexpected difference from the original"
print(f"wrote {a.dst}: added Version4>Daemon>Override>{a.label} = {a.mb} MB (everything else identical)")
