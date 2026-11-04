#!/bin/sh
# Interactive installer only. Never included in the installed router overlay.
set -eu
[ "$(id -u)" -eq 0 ] || { echo 'Run this installer as root from the installer console.' >&2; exit 1; }
[ "$(uname -s)" = Linux ] || { echo 'This installer requires Linux.' >&2; exit 1; }
installer_dir=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
if ! command -v python3 >/dev/null 2>&1 || ! command -v lsblk >/dev/null 2>&1; then
    echo 'Installing installer tools from the signed, offline installation media.'
    apk --no-network --repositories-file /dev/null \
        --repository "$installer_dir/repositories/main" \
        --repository "$installer_dir/repositories/community" add python3 lsblk
fi
exec python3 - "$installer_dir" <<'PY'
"""Verify an image, require explicit target consent, write and read back Linux disk."""
import fcntl
import gzip
import hashlib
import json
import os
import platform
import re
import stat
import struct
import subprocess
import sys
from pathlib import Path

BLOCK = 1024 * 1024
BLKGETSIZE64 = 0x80081272
BLKFLSBUF = 0x1261


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def clean(value):
    return re.sub(r'[^\x20-\x7e]', '?', str(value or '')).strip()


def device_number(value):
    return f'{os.major(value)}:{os.minor(value)}'


def disk_snapshot():
    result = subprocess.run(['lsblk', '--json', '--bytes', '--paths', '--output',
                             'NAME,TYPE,SIZE,MODEL,SERIAL,WWN,MAJ:MIN,RO'],
                            check=True, capture_output=True, text=True, timeout=15)
    data = json.loads(result.stdout)
    disks = {}
    def visit(nodes):
        for node in nodes:
            if node.get('type') == 'disk':
                path = str(Path(node['name']).resolve())
                require(path.startswith('/dev/'), 'Invalid block-device path from lsblk')
                disks[path] = {
                    'path': path, 'number': str(node['maj:min']), 'size': int(node['size']),
                    'model': str(node.get('model') or ''), 'serial': str(node.get('serial') or ''),
                    'wwn': str(node.get('wwn') or ''), 'readonly': bool(int(node.get('ro', 0))),
                }
            visit(node.get('children', []))
    visit(data.get('blockdevices', []))
    return disks


def unescape_mount(value):
    return re.sub(r'\\([0-7]{3})', lambda match: chr(int(match[1], 8)), value)


def protected_devices(source_files):
    # Follow partition parents and device-mapper/RAID slave relationships, so a
    # mounted child protects every underlying physical disk, not just its node.
    protected = {line.split()[2] for line in Path('/proc/self/mountinfo').read_text().splitlines()}
    for line in Path('/proc/swaps').read_text().splitlines()[1:]:
        fields = line.split()
        require(bool(fields), 'Cannot parse active swap devices')
        info = os.stat(unescape_mount(fields[0]))
        protected.add(device_number(info.st_rdev if stat.S_ISBLK(info.st_mode) else info.st_dev))
    for source in source_files:
        protected.add(device_number(os.fstat(source.fileno()).st_dev))
    pending = list(protected)
    while pending:
        number = pending.pop()
        if number.startswith('0:'):
            continue
        link = Path('/sys/dev/block') / number
        require(link.exists(), f'Cannot establish ancestry of mounted device {number}')
        node = link.resolve()
        ancestors = []
        if (node / 'partition').exists():
            ancestors.append((node.parent / 'dev').read_text().strip())
        for slave in (node / 'slaves').glob('*'):
            ancestors.append((slave / 'dev').read_text().strip())
        backing = node / 'loop/backing_file'
        if backing.exists():
            value = unescape_mount(backing.read_text().strip())
            require(bool(value), 'Cannot establish backing file of mounted loop device')
            filename = '/' + value.lstrip('/')
            ancestors.append(device_number(os.stat(filename).st_dev))
        for ancestor in ancestors:
            if ancestor not in protected:
                protected.add(ancestor)
                pending.append(ancestor)
    return protected


def inspect_target(target, expected_bytes, sources):
    disks = disk_snapshot()
    require(target in disks, 'Target must be a whole disk listed by lsblk, not a partition')
    disk = disks[target]
    info = os.stat(target)
    require(stat.S_ISBLK(info.st_mode), 'Target is not a block device')
    require(device_number(info.st_rdev) == disk['number'], 'Target device identity changed')
    sequence = Path('/sys/dev/block') / disk['number'] / 'diskseq'
    require(sequence.is_file(), 'Cannot establish the target disk generation identity')
    disk['diskseq'] = sequence.read_text().strip()
    require(disk['diskseq'].isdigit(), 'Invalid target disk generation identity')
    require(not disk['readonly'], 'Target disk is read-only')
    require(disk['size'] >= expected_bytes, 'Target disk is smaller than the uncompressed image')
    require(disk['number'] not in protected_devices(sources),
            'Target is mounted, used for swap, or contains the running system/installation media')
    return disk


def verify_payload(archive, manifest):
    require(os.fstat(archive.fileno()).st_size == manifest['compressed_bytes'],
            'Compressed image size differs from the installation manifest')
    archive.seek(0)
    digest = hashlib.sha256()
    while chunk := archive.read(BLOCK):
        digest.update(chunk)
    require(digest.hexdigest() == manifest['compressed_sha256'], 'Compressed image SHA256 mismatch')
    archive.seek(0)
    digest = hashlib.sha256()
    size = 0
    with gzip.GzipFile(fileobj=archive, mode='rb') as image:
        while chunk := image.read(BLOCK):
            size += len(chunk)
            require(size <= manifest['image_bytes'], 'Expanded image exceeds the declared size')
            digest.update(chunk)
    require(size == manifest['image_bytes'], 'Expanded image size differs from the installation manifest')
    require(digest.hexdigest() == manifest['image_sha256'], 'Expanded image SHA256 mismatch')
    archive.seek(0)


def read_manifest(path):
    manifest = json.loads(path.read_text())
    require(isinstance(manifest, dict) and manifest.get('format') == 'travelrouter-install-v1',
            'Unsupported installation manifest')
    arch = manifest.get('architecture')
    require(arch in {'x86_64', 'aarch64'} and arch == platform.machine(),
            'Installer and image CPU architectures must match')
    require(manifest.get('image_filename') == f'travelrouter-generic-{arch}.img.gz',
            'Unexpected payload filename')
    for key in ('compressed_sha256', 'image_sha256'):
        require(isinstance(manifest.get(key), str) and re.fullmatch('[0-9a-f]{64}', manifest[key]),
                f'Invalid manifest field: {key}')
    for key in ('compressed_bytes', 'image_bytes'):
        require(type(manifest.get(key)) is int and 0 < manifest[key] <= 64 * 1024 ** 3,
                f'Invalid manifest field: {key}')
    require(manifest['image_bytes'] % 512 == 0, 'Disk image must contain complete sectors')
    return manifest


def source_identity(stream):
    info = os.fstat(stream.fileno())
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def write_and_verify(target, disk, archive, manifest, sources):
    # O_EXCL on Linux block devices rejects in-use media and holds an exclusive
    # claim while writing. Recheck both descriptor identity and mount ancestry.
    descriptor = os.open(target, os.O_RDWR | os.O_EXCL | os.O_CLOEXEC)
    try:
        info = os.fstat(descriptor)
        require(stat.S_ISBLK(info.st_mode) and device_number(info.st_rdev) == disk['number'],
                'Opened device does not match the confirmed target')
        actual_bytes = struct.unpack('Q', fcntl.ioctl(descriptor, BLKGETSIZE64, bytes(8)))[0]
        require(actual_bytes == disk['size'], 'Disk capacity changed after confirmation')
        require(inspect_target(target, manifest['image_bytes'], sources) == disk,
                'Disk identity or safety state changed after confirmation')
        archive.seek(0)
        written = 0
        last_report = -1
        digest = hashlib.sha256()
        with gzip.GzipFile(fileobj=archive, mode='rb') as image:
            while chunk := image.read(BLOCK):
                require(written + len(chunk) <= manifest['image_bytes'], 'Payload grew during installation')
                view = memoryview(chunk)
                while view:
                    count = os.write(descriptor, view)
                    require(count > 0, 'Disk write returned no progress')
                    view = view[count:]
                digest.update(chunk)
                written += len(chunk)
                progress = written * 100 // manifest['image_bytes']
                if progress // 10 != last_report:
                    last_report = progress // 10
                    print(f'Writing: {progress}%', flush=True)
        require(written == manifest['image_bytes'] and digest.hexdigest() == manifest['image_sha256'],
                'Payload changed while writing; installation is not verified')
        os.fsync(descriptor)
        # Flush block-device buffers before readback instead of trusting cached
        # pages from the write. Failure to flush means no success is reported.
        fcntl.ioctl(descriptor, BLKFLSBUF)
        os.lseek(descriptor, 0, os.SEEK_SET)
        digest = hashlib.sha256()
        remaining = written
        print('Reading back the installed image for full SHA256 verification...', flush=True)
        while remaining:
            chunk = os.read(descriptor, min(BLOCK, remaining))
            require(bool(chunk), 'Unexpected end of disk during verification')
            digest.update(chunk)
            remaining -= len(chunk)
        require(digest.hexdigest() == manifest['image_sha256'], 'Installed disk SHA256 mismatch')
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def main():
    require(os.geteuid() == 0, 'Root privileges are required')
    directory = Path(sys.argv[1]).resolve(strict=True)
    manifest = read_manifest(directory / 'install-manifest.json')
    filename = directory / manifest['image_filename']
    require(not filename.is_symlink(), 'Image payload must not be a symbolic link')
    with filename.open('rb') as archive, (directory / 'install.sh').open('rb') as script:
        require(stat.S_ISREG(os.fstat(archive.fileno()).st_mode), 'Image payload is not a regular file')
        sources = [archive, script]
        initial_source = source_identity(archive)
        print('Checking compressed SHA256, gzip integrity, image size and expanded SHA256...', flush=True)
        verify_payload(archive, manifest)
        print('Image verified. Installed router boots using UEFI; Secure Boot must be disabled.')
        print('The installer console is stock Alpine. The installed router has locked root login and no SSH.')
        print('\nDisks (mounted disks, swap and installation media cannot be selected):')
        for path, disk in sorted(disk_snapshot().items()):
            try:
                inspect_target(path, manifest['image_bytes'], sources)
                state = 'available'
            except (OSError, RuntimeError) as error:
                state = str(error)
            print(f'  {path}: {disk["size"]} bytes, model={clean(disk["model"]) or "unknown"}, '
                  f'serial={clean(disk["serial"]) or "unknown"} [{state}]')
        # Python code comes from stdin, so prompts must use the real terminal.
        with open('/dev/tty') as terminal, open('/dev/tty', 'w', buffering=1) as prompt:
            prompt.write('\nType the whole target disk path, or press Enter to cancel: ')
            target = terminal.readline().strip()
            if not target:
                print('Installation cancelled. No target disk was opened for writing.')
                return
            disk = inspect_target(target, manifest['image_bytes'], sources)
            prompt.write(f'\nALL DATA ON {target} WILL BE REPLACED.\n'
                           f'Model: {clean(disk["model"]) or "unknown"}\n'
                           f'Serial: {clean(disk["serial"]) or "unknown"}\n'
                           f'WWN: {clean(disk["wwn"]) or "unknown"}\n'
                           f'Capacity: {disk["size"]} bytes\n'
                           f'Image: {manifest["image_bytes"]} bytes\n'
                           f'Type exactly ERASE {target} to continue: ')
            require(terminal.readline().strip() == f'ERASE {target}', 'Confirmation did not match; cancelled')
        require(source_identity(archive) == initial_source, 'Image file changed after validation')
        require(inspect_target(target, manifest['image_bytes'], sources) == disk,
                'Target identity changed after confirmation')
        write_and_verify(target, disk, archive, manifest, sources)
        print(f'Installation and full readback verification succeeded: {target}', flush=True)
        print('Shut down, remove the installer media, then boot the target disk in UEFI mode.')
        print('The installed image starts the protected TravelRouter hotspot when a supported Wi-Fi radio is present.')


try:
    main()
except (OSError, EOFError, ValueError, RuntimeError, KeyError, subprocess.SubprocessError) as error:
    print(f'Installation stopped: {error}', file=sys.stderr, flush=True)
    print('Do not boot the target unless full readback verification was reported successful.', file=sys.stderr)
    sys.exit(1)
except KeyboardInterrupt:
    print('\nInstallation interrupted. A partially written target must be reinstalled before use.', file=sys.stderr)
    sys.exit(130)
PY
