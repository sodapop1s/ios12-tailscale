"""Mach-O fix-ups needed to run a Go darwin/arm64 binary on iOS 12.

Go's darwin/arm64 output links the macOS-style framework paths
(".../Foo.framework/Versions/A/Foo"). On iOS the frameworks live one level up
(".../Foo.framework/Foo"), so dyld reports "Library not loaded". Rewriting the
two load commands in place (the new path is shorter, so it is NUL-padded)
fixes it.

Do NOT relabel the binary's platform as iOS: in testing, a binary relabelled as
iOS spun at 100% CPU forever, while the unmodified macOS-platform binary ran.
"""
import struct
import sys

LC_LOAD_DYLIB = 0xC


def fix_framework_paths(path_in, path_out):
    data = bytearray(open(path_in, "rb").read())
    magic, = struct.unpack_from("<I", data, 0)
    if magic != 0xFEEDFACF:  # MH_MAGIC_64, little endian
        raise SystemExit(f"{path_in}: not a 64-bit little-endian Mach-O")
    ncmds, = struct.unpack_from("<I", data, 16)
    off, changed = 32, []
    for _ in range(ncmds):
        cmd, size = struct.unpack_from("<II", data, off)
        if cmd == LC_LOAD_DYLIB:
            name_off, = struct.unpack_from("<I", data, off + 8)
            raw = bytes(data[off + name_off: off + size])
            name = raw.split(b"\0")[0].decode()
            new = name.replace("/Versions/A", "")
            if new != name:
                data[off + name_off: off + size] = new.encode().ljust(size - name_off, b"\0")
                changed.append((name, new))
        off += size
    open(path_out, "wb").write(data)
    return changed


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: macho.py IN OUT")
    for old, new in fix_framework_paths(*sys.argv[1:]):
        print(f"  {old}\n    -> {new}")
