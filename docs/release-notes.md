## Experimental CM5 image

This image is built for Raspberry Pi Compute Module 5 with a dedicated AP
radio and a second supported Wi-Fi adapter for the upstream network.

Download `travelrouter-cm5-aarch64.img.gz` and `SHA256SUMS`. Verify the checksum,
then select the compressed image in Raspberry Pi Imager using **Use custom**.
Writing an image erases the selected device. Keep a verified backup first.

The initial hotspot is `TravelRouter-XXXX`, using `TravelRouter-Setup!`.
Open `http://10.42.0.1/`. Sign in with `ChangeMe-TravelRouter!`, then replace
both the administrator and Wi-Fi passwords. Setup is mandatory before routing.

See README.md and docs/operations.md for configuration, security boundaries,
recovery and the physical hardware acceptance checklist. CI validation does
not establish that an untested USB adapter works on the CM5 kernel.
