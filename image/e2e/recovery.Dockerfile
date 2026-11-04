# QEMU 11.1 treats a Raspberry Pi watchdog arm as an immediate reset. This
# pinned upstream commit includes the real BCM2835 watchdog timer emulation.
FROM alpine:edge@sha256:020dfcbaaf4cc1078bf2d9c7ba31a8466e334061dcd2f248001d68f79e52c000
RUN apk add --no-cache build-base meson ninja pkgconf glib-dev pixman-dev dtc-dev linux-headers git qemu-img mtools python3 dtc
WORKDIR /build
RUN git init && git remote add origin https://github.com/qemu/qemu.git && \
    git fetch --depth=1 origin 21fcfb6046082a06b82c17688634a1b769ee63a0 && git checkout --detach FETCH_HEAD
RUN mkdir output && cd output && ../configure --target-list=aarch64-softmmu --disable-werror --disable-docs \
    --disable-plugins --disable-tools --disable-guest-agent --disable-vnc --disable-sdl --disable-gtk \
    --disable-curses --disable-spice --disable-slirp && ninja -j4 qemu-system-aarch64 && \
    cp qemu-system-aarch64 /usr/bin/qemu-system-aarch64
WORKDIR /source
