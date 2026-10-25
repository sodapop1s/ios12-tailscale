#!/usr/bin/env python3
"""Build Tailscale (tailscaled + tailscale) that runs on iOS 12 (arm64, jailbroken).

Verified combination: Tailscale v1.68.2 + Go 1.22.12. Output goes to ./out/.

  python3 scripts/build.py            # download Go 1.22.12 (checksum-verified), clone, build, patch
  python3 scripts/build.py --go /path/to/go   # use an existing Go 1.22.x toolchain

Needs: python3, git, curl-less (uses urllib), a Linux/macOS x86_64/arm64 host.
"""
import argparse, hashlib, json, os, platform, shutil, subprocess, sys, tarfile, urllib.request

sys.path.insert(0, os.path.dirname(__file__))
import macho

TAILSCALE_TAG = "v1.68.2"
GO_VERSION = "go1.22.12"
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
WORK = os.path.join(ROOT, "work")
OUT = os.path.join(ROOT, "out")

# Setting this in the main package makes Go use its own DNS resolver. Go's default
# darwin resolver (libresolv) hangs on iOS 12, so no hostname ever resolves.
NETDNS = "//go:debug netdns=go\npackage main\n"


def run(cmd, **kw):
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True, **kw)


def fetch_go():
    goos = {"Linux": "linux", "Darwin": "darwin"}[platform.system()]
    arch = {"x86_64": "amd64", "aarch64": "arm64", "arm64": "arm64"}[platform.machine()]
    meta = json.load(urllib.request.urlopen("https://go.dev/dl/?mode=json&include=all"))
    f = next(f for r in meta if r["version"] == GO_VERSION for f in r["files"]
             if f["os"] == goos and f["arch"] == arch and f["kind"] == "archive")
    dest = os.path.join(WORK, "go")
    if os.path.exists(os.path.join(dest, "go", "bin", "go")):
        return os.path.join(dest, "go", "bin", "go")
    os.makedirs(dest, exist_ok=True)
    tgz = os.path.join(dest, f["filename"])
    print("downloading", f["filename"], f["size"], "bytes")
    urllib.request.urlretrieve("https://go.dev/dl/" + f["filename"], tgz)
    digest = hashlib.sha256(open(tgz, "rb").read()).hexdigest()
    if digest != f["sha256"]:
        raise SystemExit(f"checksum mismatch for {tgz}: {digest} != {f['sha256']}")
    print("sha256 ok:", digest)
    tarfile.open(tgz).extractall(dest)
    return os.path.join(dest, "go", "bin", "go")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--go", help="path to a Go 1.22.x binary (default: download)")
    args = ap.parse_args()
    os.makedirs(WORK, exist_ok=True)
    os.makedirs(OUT, exist_ok=True)
    go = args.go or fetch_go()
    ver = subprocess.run([go, "version"], capture_output=True, text=True, check=True).stdout.strip()
    print(ver)
    if "go1.22" not in ver:
        print("WARNING: only Go 1.22.x is verified. Newer Go needs extra patches (docs/FINDINGS.md).")

    src = os.path.join(WORK, "tailscale")
    if not os.path.isdir(src):
        run(["git", "clone", "--depth", "1", "--branch", TAILSCALE_TAG,
             "https://github.com/tailscale/tailscale", src])
    env = dict(os.environ, GOOS="darwin", GOARCH="arm64", CGO_ENABLED="0", GOTOOLCHAIN="local")
    for name in ("tailscaled", "tailscale"):
        pkg = os.path.join(src, "cmd", name)
        extra = os.path.join(pkg, "zz_netdns.go")
        open(extra, "w").write(NETDNS)
        try:
            raw = os.path.join(WORK, name + ".raw")
            # -s -w: strip debug info. Go's __DWARF segment makes iOS's dyld reject the file.
            run([go, "build", "-trimpath", "-ldflags=-s -w", "-o", raw, "./cmd/" + name], cwd=src, env=env)
        finally:
            os.remove(extra)
        for old, new in macho.fix_framework_paths(raw, os.path.join(OUT, name)):
            print(f"  patched {old.split('/')[-1]}")
        os.chmod(os.path.join(OUT, name), 0o755)
    for name in ("tailscaled", "tailscale"):
        data = open(os.path.join(OUT, name), "rb").read()
        print(f"{name}: {len(data)} bytes sha256={hashlib.sha256(data).hexdigest()}")
    print("\nDone. Next: sign and install on the phone (see README, 'Install on the phone').")


if __name__ == "__main__":
    main()
