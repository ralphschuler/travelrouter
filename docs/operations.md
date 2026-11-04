# Operations and recovery

## Radio support

The image bundles Alpine's complete `linux-firmware` dependency set. It relies
on the official Raspberry Pi kernel/module loop. Drivers outside that kernel
are not automatically downloaded. The integrated radio is preferred for the
hotspot; a detected USB radio is used for upstream Wi-Fi. A single detected
radio provides setup only. Adapter/carrier compatibility needs physical testing.

## Captive networks, DNS and privacy

No upstream: the local portal opens via DNS/plain-HTTP captive detection.
A detected upstream captive response: local interception stops so its legitimate
sign-in can load. Online: normal DNS uses Unbound. HTTPS is never intercepted.

Select Direct to complete an upstream captive login, then enable WireGuard or
your proxy. Protected modes have no direct client fallback. A WireGuard import
must contain exactly one Interface/Peer and a full IPv4 default route. Scripts,
PostUp/PostDown, custom tables and arbitrary commands are rejected. Imported DNS
settings are ignored in favor of the selected Unbound mode.

Domain filtering defaults to HaGeZi Light plus TIF Mini after first verified
Internet access. Lists update daily and remain cached across boots. Add your own
domains or exceptions in the panel. Country blocks use selected IPdeny IPv4 ranges;
no countries are blocked by default. Missing required country data keeps routing
offline until it is retrieved, rather than silently ignoring the restriction.

## Settings and backups

Mutations require administrator login and CSRF validation. Full backups use
scrypt and AES-256-GCM. A redacted export omits passwords and is for inspection;
use the encrypted backup for restoration. Imported backups have a strict schema
and can contain settings, normalized Wi-Fi profiles and tunnel configuration;
they cannot write arbitrary filesystem paths. Restoration replaces saved
settings and requires reconnecting with the restored credentials.

The panel and service credentials are not logged. Local service logs rotate;
DNS query history and packet captures are disabled. Metrics are aggregate
counters, current DHCP leases, resource load and Unbound cache statistics.

## Updates

Enable automatic stable-branch package updates in the panel, or stage them
manually. New signed packages and indexes are verified in a separate boot-medium
directory. They become active on reboot. The current RAM system is untouched.
This includes stable-branch fixes beyond strictly security-only releases.
Updates need free boot space and verified Internet connectivity. No reboot is
performed without an explicit user action.

Download an official `travelrouter-update.tru` for application-only updates and
upload it to the panel. Ed25519 signature, compatibility, version, archive paths
and sizes are checked before installation. Reboot to activate the staged code.
Use a complete release image for kernel/initramfs/boot-firmware updates. Flashing
a full image replaces the device; export your encrypted settings first.

## Recovery

Keep a verified full-device backup and an encrypted settings backup. If network
setup becomes unusable, shut down and expose the eMMC via your carrier's USB boot
mode. The FAT boot volume is readable from the host:

- `travelrouter.apkovl.tar.gz` contains the current persistent overlay.
- `travelrouter.previous.tar.gz.bak` is the preceding configuration generation.
- `.repositories.previous` contains the preceding package repository after a
  package update.

Recover by restoring the preceding overlay filename on the powered-off device,
or reflashing a known-good release and importing your encrypted backup. Do not
replace a live mounted boot medium while the router is running. The root account
is locked and SSH is disabled; this USB recovery path is deliberate.

The first release has not been qualified for unattended deployment. Validate the
hardware checklist, including reboot persistence and a VPN outage, before travel.
