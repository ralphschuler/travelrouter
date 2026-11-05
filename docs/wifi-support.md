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

## Experimental RTL8191SU adapter

USB ID `0bda:8172` is a Realtek RTL8191SU. Linux sees it on the USB bus, but the
shipping 6.18 kernel has no in-tree matching driver. Its former `r8712u` driver
was removed upstream because of deprecated Wireless Extensions and maintenance
problems; upstream also notes that this hardware cannot use WPA3. Firmware alone
cannot make it work. The replacement [mac80211 source](https://github.com/chunkeey/rtl8192su)
lists USB ID `0bda:8172` and requests the firmware already shipped in Alpine,
but the project still calls itself work in progress and only documents builds
against `wireless-testing`.

The pinned upstream revision is recorded in `image/drivers/rtl8192su/UPSTREAM_REVISION`;
the numbered compatibility patches and Makefile define how to update it. The
CM5 development image builds this module against the exact Alpine 6.18.58 kernel
headers, registers it after `modloop`, and checks that it loads in the QEMU image
test. Release and development builds include it by default; pass
`RTL8191SU=0` to `make image-cm5` to opt out. QEMU verifies module ABI and
dependency loading, not radio behavior. The module remains marked experimental
until the CM5 passes physical scan, WPA2 association, traffic, unplug/replug,
and reboot checks.

Use a dongle whose USB ID is handled by one of the maintained in-tree modules
above. To request support for another chipset, record its USB ID, kernel
version, driver binding and firmware messages, then qualify it on the CM5.
