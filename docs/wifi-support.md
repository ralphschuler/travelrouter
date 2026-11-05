# Wi-Fi driver support

## What ships

The CM5 image includes Alpine's full `linux-firmware` dependency set and the
separate signed `wireless-regdb` package. The build checks that the shipped
Raspberry Pi kernel's module loop contains the enabled upstream USB Wi-Fi
drivers below. A missing driver, firmware database or signature fails the
image build.

| Driver family | Kernel module |
| --- | --- |
| Atheros AR5523 | `ar5523` |
| Atheros AR600x USB | `ath6kl_usb` |
| Atheros AR9271 | `ath9k_htc` |
| Atheros AR9170 | `carl9170` |
| Atmel AT76C50x | `at76c50x_usb` |
| Broadcom FullMAC USB | `brcmfmac` |
| Marvell Libertas | `usb8xxx`, `libertas_tf_usb` |
| MediaTek | `mt7601u`, `mt76x0u`, `mt76x2u`, `mt7921u`, `mt7925u` |
| Prism54 | `p54usb` |
| Ralink | `rt2500usb`, `rt73usb`, `rt2800usb` |
| Realtek maintained in-tree drivers | `rtl8187`, `rtl8192cu`, `rtl8xxxu`, `rtw88_usb`, `rtw89_usb` |
| ZyDAS | `zd1211rw` |

The list is broad, but it cannot cover every USB ID, proprietary driver,
chip revision, or vendor-specific kernel. Confirm a dongle's USB ID and its
driver before treating it as supported; physical CM5 qualification is still
required.

## Known unsupported adapter

USB ID `0bda:8172` is a Realtek RTL8191SU. Linux sees it on the USB bus, but the
shipping 6.18 kernel has no matching driver. Its former `r8712u` driver was
removed upstream because it relied on deprecated Wireless Extensions, had
ongoing maintenance issues, and did not support WPA3. Firmware alone cannot
make it work. The replacement `rtl8192su` project is still marked work in
progress. Its [mac80211 source](https://github.com/chunkeey/rtl8192su) lists
USB ID `0bda:8172` and requests the firmware already shipped in Alpine. The
pinned source revision has not changed since 2017, and its README only claims
support for recent `wireless-testing` kernels. It is a candidate to port, not a
supported driver, so it is not included in the release image.

The `RTL8191SU driver compatibility` GitHub Actions workflow checks whether
this source compiles against Linux 6.18.58, applying the compatibility patches
kept under `image/drivers/rtl8192su`. Passing that build proves only API
compatibility. The adapter still needs real CM5 checks for scanning, encrypted
upstream connections, unplug/replug and reboot before the driver can ship.

Use a dongle whose USB ID is handled by one of the maintained in-tree modules
above. To request support for another chipset, record its USB ID, kernel
version, driver binding and firmware messages, then qualify it on the CM5.
