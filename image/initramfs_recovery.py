"""Add a fail-closed recovery hook to the pinned Alpine diskless initramfs."""
import gzip
import stat
import sys
from pathlib import Path

MAGIC = b'070701'
BOOT_MEDIA = b'\t$repoopts -a "$ROOT"/tmp/apkovls\neend $?\n'
UNPACK = b'\tunpack_apkovl "$ovl" "$sysroot"\n\teend $? "$errstr" || ovlfiles=\n'
APK_FAILURE = b'\t\techo "WARNING: apkovl packages install completed with errors..." > "$ROOT"/dev/kmsg\n'
MARKER = b'# TravelRouter recovery hook v1\n'


def entries(data):
    offset = 0
    while offset < len(data):
        while offset < len(data) and data[offset] == 0:
            offset += 1
        if offset == len(data):
            break
        if data[offset:offset + 6] not in (MAGIC, b'070702') or offset + 110 > len(data):
            raise ValueError('Invalid initramfs cpio archive')
        try:
            fields = [int(data[offset + 6 + i * 8:offset + 14 + i * 8], 16) for i in range(13)]
        except ValueError as error:
            raise ValueError('Invalid initramfs cpio header') from error
        size, namesize = fields[6], fields[11]
        name_start = offset + 110
        name_end = name_start + namesize
        if not namesize or name_end > len(data) or data[name_end - 1] != 0:
            raise ValueError('Invalid initramfs cpio name')
        name = data[name_start:name_end - 1].decode('utf-8')
        start = (name_end + 3) & ~3
        end = start + size
        if end > len(data):
            raise ValueError('Truncated initramfs cpio entry')
        offset = (end + 3) & ~3
        if name != 'TRAILER!!!':
            yield name.removeprefix('./'), fields[1], data[start:end]


def archive(files):
    output = bytearray()
    for index, (name, mode, data) in enumerate([*files, ('TRAILER!!!', stat.S_IFREG, b'')], start=1):
        encoded = name.encode() + b'\0'
        fields = [index, mode, 0, 0, 1, 0, len(data), 0, 0, 0, 0, len(encoded), 0]
        output.extend(MAGIC + ''.join(f'{field:08x}' for field in fields).encode())
        output.extend(encoded)
        output.extend(b'\0' * (-len(output) % 4))
        output.extend(data)
        output.extend(b'\0' * (-len(output) % 4))
    return bytes(output)


def patch(compressed, recovery):
    init_files = [data for name, mode, data in entries(gzip.decompress(compressed))
                  if name == 'init' and stat.S_ISREG(mode)]
    if not init_files or not recovery.startswith(b'#!/bin/sh\n'):
        raise ValueError('Expected Alpine init and recovery shell script')
    init = init_files[-1]
    if MARKER in init or init.count(BOOT_MEDIA) != 1 or init.count(UNPACK) != 1 or init.count(APK_FAILURE) != 2:
        raise ValueError('Unknown or already modified Alpine initramfs')
    init = init.replace(BOOT_MEDIA, BOOT_MEDIA + MARKER +
                        b'/bin/sh /sbin/travelrouter-recovery early "$ROOT" || recovery_shell "Update recovery failed."\n')
    init = init.replace(UNPACK, b'\tunpack_apkovl "$ovl" "$sysroot"\n'
                        b'\ttr_unpack_status=$?\n'
                        b'\t[ "$tr_unpack_status" -eq 0 ] || /bin/sh /sbin/travelrouter-recovery failure "$ROOT" || :\n'
                        b'\teend "$tr_unpack_status" "$errstr" || ovlfiles=\n')
    init = init.replace(APK_FAILURE, b'\t\t/bin/sh /sbin/travelrouter-recovery failure "$ROOT" || :\n' + APK_FAILURE)
    extra = archive([('sbin/travelrouter-recovery', stat.S_IFREG | 0o755, recovery),
                     ('init', stat.S_IFREG | 0o755, init)])
    return compressed + gzip.compress(extra, mtime=0)


if __name__ == '__main__':
    image, script = map(Path, sys.argv[1:])
    result = patch(image.read_bytes(), script.read_bytes())
    temporary = image.with_name(image.name + '.recovery.tmp')
    temporary.write_bytes(result)
    temporary.replace(image)
