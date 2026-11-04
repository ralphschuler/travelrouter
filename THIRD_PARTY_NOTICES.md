# Third-party components and data

TravelRouter is an aggregate system image; its MIT license applies to our own
Python, UI, configuration templates, and build scripts, not to third-party code.

- [Alpine Linux](https://www.alpinelinux.org/) supplies the base and packages.
  Exact package versions and hashes accompany each release. Package build recipes
  and source locations are in [Alpine aports](https://gitlab.alpinelinux.org/alpine/aports)
  and the [Alpine package database](https://pkgs.alpinelinux.org/). Consult each
  package's license and corresponding upstream sources.
- Linux, hostapd, dnsmasq, NetworkManager, WireGuard tooling and sing-box retain
  their respective copyleft licenses. Unbound, Python, cryptography and other
  dependencies retain their own licenses. Firmware has component-specific terms.
- [sing-box](https://github.com/SagerNet/sing-box) is an independently developed
  proxy platform distributed by Alpine. TravelRouter is not affiliated with it.
- [HaGeZi DNS blocklists](https://github.com/hagezi/dns-blocklists) are fetched at
  runtime over HTTPS. The default sources are Light and TIF Mini in plain-domain
  format. The upstream repository publishes GPL-3.0 terms and source attribution.
  These data files are not embedded in the original release build.
- [IPdeny country ranges](https://www.ipdeny.com/ipblocks/) are downloaded only for
  selected countries. The provider permits redistribution under its published
  copyright/usage policies. TravelRouter refreshes daily, not on every DNS request.
- [GNOME NetworkManager connectivity checking](http://nmcheck.gnome.org/)
  supplies the HTTP/HTTPS reachability endpoint. Cloudflare and Quad9 are the
  default DNS-over-TLS forwarders; they are separate third-party services.

The release source archive contains TravelRouter source and build instructions.
The package inventory, SBOM and metadata identify the separately distributed
upstream components. Preserve this notice when redistributing the image.
