#!/usr/bin/env python3
# minimal pongoOS shell helper (protocol from PongoOS scripts/pongoterm.c): sudo python3 pongo.py "<cmd>" ["<cmd2>" ...]
import sys, time, usb.core
dev = usb.core.find(idVendor=0x05ac, idProduct=0x4141)
if dev is None: sys.exit("pongoOS device not found")
try: dev.set_configuration()
except Exception as e: print("set_configuration:", e)
def drain(timeout=60):
    t0 = time.time(); buf = b""
    while time.time() - t0 < timeout:
        st = bytes(dev.ctrl_transfer(0xa1, 2, 0, 0, 1))
        data = bytes(dev.ctrl_transfer(0xa1, 1, 0, 0, 0x1000))
        if data: sys.stdout.write(data.decode("latin1")); sys.stdout.flush(); buf += data
        if st and st[0] == 0: break
        if not data: time.sleep(0.1)
    return buf
drain(5)                                   # flush whatever is pending
dev.ctrl_transfer(0x21, 4, 0xffff, 0, None)  # same init call pongoterm makes before a command
for cmd in sys.argv[1:]:
    print("\n>> " + cmd)
    dev.ctrl_transfer(0x21, 3, 0, 0, cmd.encode() + b"\n")
    drain(60)
print()
