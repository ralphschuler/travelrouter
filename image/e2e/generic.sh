#!/bin/sh
# Boot only file-backed installer/runtime guests inside the native Alpine builder.
set -eu
case "${1:-}" in
    generic-x86_64) architecture=x86_64 ;;
    generic-aarch64) architecture=aarch64 ;;
    *) echo 'Expected generic-x86_64 or generic-aarch64' >&2; exit 2 ;;
esac
if [ "$(uname -s)" != Linux ] || [ "$(uname -m)" != "$architecture" ]; then
    echo 'Generic image E2E requires the matching native Alpine Linux container' >&2
    exit 1
fi
apk add --no-cache "qemu-system-$architecture=11.0.3-r0" qemu-img=11.0.3-r0 mtools python3 xorriso
source_dir=$(CDPATH='' cd -- "$(dirname "$0")/../.." && pwd)
exec python3 "$source_dir/image/e2e/generic.py" --target "$1" \
    --dist "$source_dir/dist/$1" --output "$source_dir/build/e2e-results-$1" \
    --scratch "$source_dir/build/e2e-vm-$1"
