# Experimental RTL8191SU driver

The CM5 image build uses the `r92su` mac80211 driver from
[chunkeey/rtl8192su](https://github.com/chunkeey/rtl8192su), pinned to the
commit recorded in `UPSTREAM_REVISION`. Its USB ID table includes the router's
RTL8191SU adapter (`0bda:8172`), and it requests Alpine's existing
`rtlwifi/rtl8712u.bin` firmware.

Upstream describes the driver as work in progress and only documents builds
against `wireless-testing`. The original `r8712u` driver was removed from the
kernel for maintenance and deprecated Wireless Extensions problems. This
patch series ports the candidate to the CM5 image's Alpine 6.18.58 kernel API.
It remains experimental: the source does not support WPA3, and a successful
module build or QEMU load does not prove that real radios scan, associate, or
remain stable under traffic.

## Updating the source

Review upstream changes, update `UPSTREAM_REVISION`, then rebuild against the
exact kernel package used by `image/build.sh`. Update the numbered patches as
needed and run the compatibility workflow. Keep the module out of a release
image until it passes the CM5 scan, WPA2 association, traffic, unplug/replug,
and reboot checks. The upstream source is GPL-2.0; preserve its license and
copyright notices when distributing the built module.

The build also compiles and runs a host-side check against the patched transmit
code. It checks station broadcast and unicast frames and AP broadcast frames for
the correct wireless receiver and key. Python 3 and a host C compiler are
required. This check does not replace testing radio traffic on hardware.
