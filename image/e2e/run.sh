#!/bin/sh
# Run inside the pinned Alpine aarch64 builder, never against a host block device.
set -eu
[ "$(uname -s)" = Linux ] && [ "$(uname -m)" = aarch64 ] || {
    echo 'Image E2E requires an Alpine aarch64 Linux container' >&2
    exit 1
}
apk add --no-cache qemu-system-aarch64=11.0.3-r0 qemu-img=11.0.3-r0 mtools python3
source_dir=$(CDPATH='' cd -- "$(dirname "$0")/../.." && pwd)
exec python3 "$source_dir/image/e2e/run.py" \
    --image "${1:-$source_dir/dist/travelrouter-cm5-aarch64.img.gz}" \
    --output "$source_dir/build/e2e-results" --scratch "$source_dir/build/e2e-vm"
