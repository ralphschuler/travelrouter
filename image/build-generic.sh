#!/bin/sh
# Build inside the matching Alpine container. Every disk operation targets a file.
set -eu
source_dir=$(CDPATH='' cd -- "$(dirname "$0")/.." && pwd)
case "${1:-}" in
    generic-x86_64|x86_64|amd64) target=generic-x86_64; arch=x86_64 ;;
    generic-aarch64|aarch64|arm64) target=generic-aarch64; arch=aarch64 ;;
    *) echo 'Usage: sh image/build-generic.sh generic-x86_64|generic-aarch64' >&2; exit 1 ;;
esac
[ "$(apk --print-arch)" = "$arch" ] || { echo "Build needs an Alpine $arch container" >&2; exit 1; }
build_dir="$source_dir/build/$target"
out="$source_dir/dist/$target"
if [ -e "$build_dir" ] || [ -e "$out" ]; then
    echo 'Use fresh target build/output directories' >&2
    exit 1
fi
apk add --no-cache curl tar gzip python3 py3-cryptography xorriso mtools dosfstools util-linux coreutils grub-efi
mkdir -p "$build_dir/downloads" "$build_dir/media" "$out"
manifest="$source_dir/image/targets/manifest.json"
field() { python3 "$source_dir/image/targets/metadata.py" field "$manifest" "$target" "$1"; }
branch=$(field alpine_branch)
version=$(field alpine_version)
base_url=$(field base_url)
base_sha=$(field base_sha256)
grub_platform=$(field grub_platform)
efi_filename=$(field efi_filename)
base=https://dl-cdn.alpinelinux.org/alpine
iso="$build_dir/alpine-standard-$version-$arch.iso"
curl --fail --location --retry 3 "$base_url" -o "$iso"
printf '%s  %s\n' "$base_sha" "$iso" | sha256sum -c -
xorriso -indev "$iso" -report_el_torito plain > "$build_dir/upstream-boot.txt" 2>&1
xorriso -osirrox on -indev "$iso" -extract / "$build_dir/upstream"

# Keep the official kernel, initramfs and signed module loop. ISO boot code is
# replayed for the installer; the writable runtime gets its own UEFI loader.
cp -a "$build_dir/upstream/boot" "$build_dir/media/boot"
cp "$build_dir/upstream/.alpine-release" "$build_dir/media/.alpine-release"
rm -rf "$build_dir/media/boot/syslinux"
rm -f "$build_dir/media/boot/grub/efi.img"
for file in vmlinuz-lts initramfs-lts modloop-lts; do
    test -s "$build_dir/media/boot/$file"
done
set --
while IFS= read -r package; do
    case "$package" in ''|'#'*) continue ;; esac
    set -- "$@" "$package"
done < "$source_dir/image/packages.txt"
# APK 3 --url still downloads; it omits URLs when the output file already exists.
# Capture URLs in the same fetch into this fresh directory, never a second pass.
apk --repositories-file /dev/null --repository "$base/$branch/main" --repository "$base/$branch/community" \
    fetch --recursive --url --output "$build_dir/downloads" "$@" > "$build_dir/package-urls.txt"
for repository in main community; do
    mkdir -p "$build_dir/media/repositories/$repository/$arch"
    touch "$build_dir/media/repositories/$repository/.boot_repository"
    curl --fail --location --retry 3 "$base/$branch/$repository/$arch/APKINDEX.tar.gz" \
        -o "$build_dir/media/repositories/$repository/$arch/APKINDEX.tar.gz"
done
while IFS= read -r url; do
    case "$url" in
        "$base/$branch/main/$arch/"*) repository=main ;;
        "$base/$branch/community/$arch/"*) repository=community ;;
        *) echo 'Unexpected package repository' >&2; exit 1 ;;
    esac
    name=${url##*/}
    ln "$build_dir/downloads/$name" "$build_dir/media/repositories/$repository/$arch/$name"
done < "$build_dir/package-urls.txt"
python3 "$source_dir/image/overlay.py" "$source_dir" "$build_dir"
touch "$build_dir/media/.travelrouter"

# No installer, unlocked account or test fixture enters this runtime overlay.
check="$build_dir/check"
mkdir -p "$check/etc/apk/keys" "$check/dev" "$check/proc" "$check/sys"
cp -a /etc/apk/keys/. "$check/etc/apk/keys/"
tar -xzf "$build_dir/media/travelrouter.apkovl.tar.gz" -C "$check"
apk --root "$check" --initdb --no-network --repositories-file /dev/null \
    --repository "$build_dir/media/repositories/main" --repository "$build_dir/media/repositories/community" add "$@"
python3 "$source_dir/image/validate.py" "$check"
apk --root "$check" info -v | sort > "$out/travelrouter-$target-packages.txt"

# Standalone UEFI boot code searches the writable runtime, not the upstream
# ISO's label (which was compiled into Alpine's own EFI executable).
mkdir -p "$build_dir/media/efi/boot" "$build_dir/media/boot/grub"
cat > "$build_dir/grub-early.cfg" <<'GRUB'
search --no-floppy --file --set=root /.travelrouter
set prefix=($root)/boot/grub
GRUB
cat > "$build_dir/media/boot/grub/grub.cfg" <<'GRUB'
set timeout=3
menuentry 'TravelRouter (UEFI)' {
    linux /boot/vmlinuz-lts modules=loop,squashfs,sd-mod,usb-storage quiet
    initrd /boot/initramfs-lts
}
GRUB
grub-mkimage --format="$grub_platform" --directory="/usr/lib/grub/$grub_platform" \
    --prefix=/boot/grub --config="$build_dir/grub-early.cfg" --compression=xz \
    --output="$build_dir/media/efi/boot/$efi_filename" \
    part_gpt part_msdos fat search search_fs_file normal configfile linux gzio all_video efi_gop

used_kib=$(du -sk "$build_dir/media" | cut -f1)
size_mib=$(( ((used_kib * 3 / 1024 + 1023) / 256) * 256 ))
[ "$size_mib" -ge 4096 ] || size_mib=4096
[ "$size_mib" -le 12000 ] || { echo 'Runtime image exceeds supported build budget' >&2; exit 1; }
fat="$build_dir/runtime.fat"
image="$out/travelrouter-$target.img"
truncate -s "${size_mib}M" "$fat"
mkfs.vfat -F 32 -n TRVROUTER "$fat"
for entry in "$build_dir/media"/* "$build_dir/media"/.[!.]*; do
    [ -e "$entry" ] || continue
    mcopy -s -i "$fat" "$entry" ::
done
truncate -s "$((size_mib + 2))M" "$image"
printf 'label: gpt\nunit: sectors\n\nstart=2048, size=%s, type=C12A7328-F81F-11D2-BA4B-00A0C93EC93B\n' \
    "$((size_mib * 2048))" | sfdisk "$image"
dd if="$fat" of="$image" bs=1M seek=1 conv=notrunc status=none
python3 "$source_dir/image/targets/metadata.py" record-image "$image" "$build_dir/image-record.json"
gzip -6n "$image"

# The ISO keeps Alpine's stock console/install environment. It deliberately has
# no router apkovl: ISO9660 cannot persist the mandatory credential rotation.
payload="$build_dir/installer"
mkdir -p "$payload"
cp "$source_dir/image/targets/install.sh" "$payload/install.sh"
cp "$source_dir/image/targets/INSTALLER.txt" "$payload/README.txt"
chmod 755 "$payload/install.sh"
# Only the installer tools belong here; the router's full package/firmware set
# is already inside the compressed runtime image. Keep its inventory separate.
mkdir -p "$build_dir/installer-downloads"
apk --repositories-file /dev/null --repository "$base/$branch/main" --repository "$base/$branch/community" \
    fetch --recursive --url --output "$build_dir/installer-downloads" python3 lsblk > "$build_dir/installer-package-urls.txt"
for repository in main community; do
    mkdir -p "$payload/repositories/$repository/$arch"
    cp "$build_dir/media/repositories/$repository/$arch/APKINDEX.tar.gz" \
        "$payload/repositories/$repository/$arch/APKINDEX.tar.gz"
done
while IFS= read -r url; do
    case "$url" in
        "$base/$branch/main/$arch/"*) repository=main ;;
        "$base/$branch/community/$arch/"*) repository=community ;;
        *) echo 'Unexpected installer package repository' >&2; exit 1 ;;
    esac
    name=${url##*/}
    ln "$build_dir/installer-downloads/$name" "$payload/repositories/$repository/$arch/$name"
done < "$build_dir/installer-package-urls.txt"
installer_check="$build_dir/installer-check"
mkdir -p "$installer_check/etc/apk/keys"
cp -a /etc/apk/keys/. "$installer_check/etc/apk/keys/"
# Match the stock ISO's existing Alpine base, then install tools using ONLY the
# minimal installer repositories. No installer dependency can leak from runtime.
apk --root "$installer_check" --initdb --no-network --repositories-file /dev/null \
    --repository "$build_dir/media/repositories/main" --repository "$build_dir/media/repositories/community" add alpine-base
apk --root "$installer_check" --no-network --repositories-file /dev/null \
    --repository "$payload/repositories/main" --repository "$payload/repositories/community" add python3 lsblk
chroot "$installer_check" /usr/bin/python3 -c 'import fcntl, gzip, hashlib, json, pathlib, platform, stat, struct, subprocess'
chroot "$installer_check" /bin/sh -c 'lsblk --version'
apk --root "$installer_check" info -v | sort > "$build_dir/installer-packages.txt"
ln "$image.gz" "$payload/$(basename "$image.gz")"
python3 "$source_dir/image/targets/metadata.py" finish "$manifest" "$target" "$build_dir" "$out"
installer="$out/travelrouter-installer-$arch.iso"
xorriso -indev "$iso" -outdev "$installer" -boot_image any replay \
    -map "$payload" /travelrouter -commit -end
xorriso -indev "$installer" -report_el_torito plain > "$out/travelrouter-$target-iso-boot.txt" 2>&1
python3 "$source_dir/image/targets/metadata.py" verify-iso "$manifest" "$target" \
    "$build_dir/upstream-boot.txt" "$out/travelrouter-$target-iso-boot.txt"
# Read the embedded payload manifest back from the actual final ISO.
xorriso -osirrox on -indev "$installer" -extract /travelrouter/install-manifest.json "$build_dir/embedded-manifest.json"
cmp "$payload/install-manifest.json" "$build_dir/embedded-manifest.json"
(cd "$out" && sha256sum ./*.img.gz ./*.iso ./*-packages.txt ./*-sbom.cdx.json ./*-build-metadata.json \
    ./*-install-manifest.json ./*-iso-boot.txt > "travelrouter-$target-SHA256SUMS")
echo "Built writable UEFI runtime and installer ISO in $out"
