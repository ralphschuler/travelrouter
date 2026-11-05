#!/bin/sh
# Build the experimental RTL8191SU mac80211 port for the bundled CM5 kernel.
set -eu

if [ "$#" -ne 5 ]; then
    echo "Usage: $0 SOURCE_DIR BUILD_DIR KERNEL_RELEASE KERNEL_PACKAGE_VERSION OUTPUT_MODULE" >&2
    exit 2
fi

source_dir=$1
build_dir=$2
kernel_release=$3
kernel_package_version=$4
output_module=$5
driver_arch=${ARCH:-arm64}
cross_compile=${CROSS_COMPILE:-}
alpine_branch=${ALPINE_BRANCH:-v3.24}
apk_arch=${APK_ARCH:-aarch64}
kernel_dev_package=${KERNEL_DEV_PACKAGE:-linux-rpi-dev}
revision=${DRIVER_REVISION:-$(tr -d '\n' < "$source_dir/image/drivers/rtl8192su/UPSTREAM_REVISION")}
package="${kernel_dev_package}-${kernel_package_version}.apk"
package_url=${KERNEL_PACKAGE_URL:-"https://dl-cdn.alpinelinux.org/alpine/${alpine_branch}/main/${apk_arch}/${package}"}
package_path="$build_dir/driver-downloads/$package"
kernel_dir="/usr/src/linux-headers-${kernel_release}"
source_path="$build_dir/rtl8192su-src"

mkdir -p "$build_dir/driver-downloads"
if [ ! -s "$kernel_dir/Module.symvers" ]; then
    wget -q -O "$package_path" "$package_url"
    apk verify "$package_path"
    apk add --no-cache "$package_path"
fi

test -d "$kernel_dir" || { echo "Missing expected kernel headers: $kernel_dir" >&2; exit 1; }
test -s "$kernel_dir/Module.symvers" || { echo "Missing Module.symvers in $kernel_dir" >&2; exit 1; }

if [ -d "$source_path/.git" ]; then
    git -C "$source_path" fetch --depth=1 origin "$revision"
    git -C "$source_path" reset --hard "$revision"
    git -C "$source_path" clean -fdx
else
    git clone --filter=blob:none --no-checkout https://github.com/chunkeey/rtl8192su.git "$source_path"
    git -C "$source_path" checkout --detach "$revision"
fi
test "$(git -C "$source_path" rev-parse HEAD)" = "$revision"
for patch_file in "$source_dir"/image/drivers/rtl8192su/*.patch; do
    patch --batch --directory="$source_path/r92su" -p1 < "$patch_file"
done

make -C "$kernel_dir" M="$source_path/r92su" ARCH="$driver_arch" \
    CROSS_COMPILE="$cross_compile" CONFIG_R92SU=m modules
module="$source_path/r92su/r92su.ko"
test -s "$module"
vermagic=$(modinfo -F vermagic "$module")
case "$vermagic" in
    "$kernel_release "*) ;;
    *) echo "Unexpected module vermagic: $vermagic" >&2; exit 1 ;;
esac
modinfo -F alias "$module" | grep -F 'usb:v0BDAp8172' >/dev/null
test "$(modinfo -F firmware "$module")" = rtlwifi/rtl8712u.bin
mkdir -p "$(dirname "$output_module")"
cp "$module" "$output_module"
sha256sum "$output_module"
