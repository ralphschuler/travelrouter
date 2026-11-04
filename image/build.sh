#!/bin/sh
# Run inside an Alpine aarch64 container. Output paths never refer to host disks.
set -eu
source_dir=$(CDPATH='' cd -- "$(dirname "$0")/.." && pwd)
build_dir="$source_dir/build"
media="$build_dir/media"
out="$source_dir/dist"
version=3.24.3
branch=v3.24
base=https://dl-cdn.alpinelinux.org/alpine
bundle="alpine-rpi-$version-aarch64.tar.gz"
bundle_sha=7bc2ac2ac3bd15667f651dc8d10c8423f1272730f028bc8962384c30e5317f62

[ "$(apk --print-arch)" = aarch64 ] || { echo 'Build requires native or emulated aarch64 Alpine'; exit 1; }
[ ! -e "$build_dir" ] || { echo 'Use a fresh checkout for each image build'; exit 1; }
apk add --no-cache curl tar gzip python3 py3-cryptography mtools dosfstools util-linux coreutils
mkdir -p "$media" "$out" "$build_dir/downloads"
curl --fail --location --retry 3 "$base/$branch/releases/aarch64/$bundle" -o "$build_dir/$bundle"
printf '%s  %s\n' "$bundle_sha" "$build_dir/$bundle" | sha256sum -c -
tar -xzf "$build_dir/$bundle" -C "$media"
python3 "$source_dir/image/initramfs_recovery.py" "$media/boot/initramfs-rpi" \
    "$source_dir/rootfs/etc/travelrouter/recovery.sh"
python3 "$source_dir/image/boot_config.py" cmdline "$media/cmdline.txt"

set --
while IFS= read -r package; do
    case "$package" in ''|'#'*) continue ;; esac
    set -- "$@" "$package"
done < "$source_dir/image/packages.txt"
# APK 3 --url also downloads and skips existing files; capture both in one pass.
apk fetch --recursive --url --output "$build_dir/downloads" "$@" > "$build_dir/package-urls.txt"
for repository in main community; do
    mkdir -p "$media/repositories/$repository/aarch64"
    touch "$media/repositories/$repository/.boot_repository"
    curl --fail --location --retry 3 "$base/$branch/$repository/aarch64/APKINDEX.tar.gz" \
        -o "$media/repositories/$repository/aarch64/APKINDEX.tar.gz"
done
while IFS= read -r url; do
    case "$url" in
        "$base/$branch/main/aarch64/"*) repository=main ;;
        "$base/$branch/community/aarch64/"*) repository=community ;;
        *) echo 'Unexpected package repository'; exit 1 ;;
    esac
    name=${url##*/}
    ln "$build_dir/downloads/$name" "$media/repositories/$repository/aarch64/$name"
done < "$build_dir/package-urls.txt"
python3 "$source_dir/image/overlay.py" "$source_dir" "$build_dir"
touch "$media/.travelrouter" "$media/.travelrouter-recovery-v1"
printf 'enable_uart=1\n[cm5]\ndtoverlay=dwc2,dr_mode=host\n[all]\n' > "$media/usercfg.txt"

# Verify all packages/signatures from the actual embedded repositories offline.
check="$build_dir/check"
mkdir -p "$check/etc/apk/keys" "$check/dev" "$check/proc" "$check/sys"
cp -a /etc/apk/keys/. "$check/etc/apk/keys/"
tar -xzf "$media/travelrouter.apkovl.tar.gz" -C "$check"
apk --root "$check" --initdb --no-network \
    --repository "$media/repositories/main" --repository "$media/repositories/community" \
    add "$@"
python3 "$source_dir/image/validate.py" "$check"

# Preserve exact package versions for audits and future rebuilds.
apk --root "$check" info -v | sort > "$out/packages.txt"
python3 "$source_dir/image/sbom.py" "$check" "$out" "$bundle_sha"

# FAT32 has enough reserve for several overlay generations. Size is adaptive.
used_kib=$(du -sk "$media" | cut -f1)
size_mib=$(( ((used_kib * 3 / 1024 + 1023) / 256) * 256 ))
[ "$size_mib" -ge 4096 ] || size_mib=4096
[ "$size_mib" -le 12000 ] || { echo 'Image exceeds the supported build budget'; exit 1; }
fat="$build_dir/boot.fat"
image="$out/travelrouter-cm5-aarch64.img"
truncate -s "${size_mib}M" "$fat"
mkfs.vfat -F 32 -n TRVROUTER "$fat"
for entry in "$media"/* "$media"/.[!.]*; do
    [ -e "$entry" ] || continue
    mcopy -s -i "$fat" "$entry" ::
done
truncate -s "$((size_mib + 1))M" "$image"
printf 'label: dos\nunit: sectors\n\nstart=2048, size=%s, type=c, bootable\n' "$((size_mib * 2048))" | sfdisk "$image"
dd if="$fat" of="$image" bs=1M seek=1 conv=notrunc status=none
gzip -6n "$image"
(cd "$out" && sha256sum travelrouter-cm5-aarch64.img.gz packages.txt sbom.cdx.json build-metadata.json > SHA256SUMS)
echo "Built $out/travelrouter-cm5-aarch64.img.gz"
