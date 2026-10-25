#!/bin/sh
# /usr/bin/tailscale on the phone: always use the right socket and Go runtime setting.
exec env GODEBUG=asyncpreemptoff=1 /var/root/ts/tailscale --socket=/var/root/ts/tailscaled.sock "$@"
