"""Pinned generic-target inputs and artifacts derived from the real built image."""

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sbom import generate  # noqa: E402


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def target_spec(path, target):
    manifest = json.loads(Path(path).read_text())
    if manifest.get('schema') != 1 or target not in manifest['targets']:
        raise ValueError('Unknown target manifest or target')
    return {key: value for key, value in manifest.items() if key != 'targets'} | manifest['targets'][target]


def bootloader_build(build, spec):
    # These packages live in the builder, not in the runtime APK inventory.
    packages = {}
    for paragraph in Path('/lib/apk/db/installed').read_text().split('\n\n'):
        fields = dict(line.split(':', 1) for line in paragraph.splitlines()
                      if len(line) >= 2 and line[1] == ':')
        if fields.get('P') in {'grub', 'grub-efi'}:
            packages[fields['P']] = fields['V']
    if set(packages) != {'grub', 'grub-efi'}:
        raise ValueError('Cannot identify the installed GRUB builder packages')
    # Fixed builder executable and argument; no target or user data is executed.
    tool_version = subprocess.check_output(['/usr/bin/grub-mkimage', '--version'],  # nosec B603
                                           text=True, timeout=10).strip()
    if not tool_version:
        raise ValueError('Cannot identify the GRUB image builder version')
    efi_path = Path('efi/boot') / spec['efi_filename']
    return {'builder_packages': packages, 'grub_mkimage_version': tool_version,
            'platform': spec['grub_platform'], 'efi_path': str(efi_path),
            'efi_sha256': digest(Path(build) / 'media' / efi_path)}


def finish(manifest, target, build, out):
    spec = target_spec(manifest, target)
    build, out = Path(build), Path(out)
    prefix = 'travelrouter-' + target
    image = out / (prefix + '.img.gz')
    record = json.loads((build / 'image-record.json').read_text())
    installer = {'format': 'travelrouter-install-v1', 'architecture': spec['architecture'],
                 'image_filename': image.name, 'compressed_sha256': digest(image),
                 'compressed_bytes': image.stat().st_size, 'image_sha256': record['sha256'],
                 'image_bytes': record['bytes']}
    text = json.dumps(installer, indent=2) + '\n'
    (build / 'installer/install-manifest.json').write_text(text)
    (out / (prefix + '-install-manifest.json')).write_text(text)
    generate(build / 'check', out, spec['base_sha256'], architecture=spec['architecture'], target=target)
    metadata_path = out / 'build-metadata.json'
    metadata = json.loads(metadata_path.read_text())
    metadata.update(base_iso_url=spec['base_url'], base_iso_sha256=spec['base_sha256'],
                    installer_boot_modes=spec['installer_boot_modes'], runtime_boot_modes=spec['runtime_boot_modes'],
                    runtime_image=installer, runtime_bootloader='standalone GRUB ' + spec['grub_platform'],
                    installer_environment='Unmodified Alpine local root console; router overlay is only in runtime disk image')
    metadata['boot_file_sha256'] = {
        str(path.relative_to(build / 'media')): digest(path)
        for path in (build / 'media/boot').glob('*') if path.is_file()
    }
    metadata['runtime_bootloader_build'] = bootloader_build(build, spec)
    metadata['runtime_overlay_sha256'] = digest(build / 'media/travelrouter.apkovl.tar.gz')
    metadata['installer_validation_packages'] = (build / 'installer-packages.txt').read_text().splitlines()
    metadata['installer_package_sha256'] = {
        path.name: digest(path) for path in sorted((build / 'installer-downloads').glob('*.apk'))
    }
    metadata_path.write_text(json.dumps(metadata, indent=2) + '\n')
    for name in ('sbom.cdx.json', 'build-metadata.json'):
        (out / name).rename(out / (prefix + '-' + name))


def verify_iso(manifest, target, upstream_report, rebuilt_report):
    spec = target_spec(manifest, target)
    platforms = []
    for path in (upstream_report, rebuilt_report):
        text = Path(path).read_text()
        modes = re.findall(r'El Torito boot img\s*:\s*\d+\s+(BIOS|UEFI)\b', text)
        if not modes:
            raise ValueError('Cannot find El Torito boot entries in xorriso report')
        platforms.append(modes)
    if platforms[0] != platforms[1] or set(platforms[1]) != set(spec['installer_boot_modes']):
        raise ValueError('Rebuilt ISO did not preserve the expected boot platforms')
    print('ISO boot entries preserved:', ', '.join(platforms[1]), flush=True)


def main():
    operation, *arguments = sys.argv[1:]
    if operation == 'field':
        manifest, target, field = arguments
        value = target_spec(manifest, target)[field]
        if not isinstance(value, str) or '\n' in value:
            raise ValueError('Expected a single string manifest field')
        print(value)
    elif operation == 'record-image':
        image, record = map(Path, arguments)
        record.write_text(json.dumps({'bytes': image.stat().st_size, 'sha256': digest(image)}) + '\n')
    elif operation == 'finish':
        finish(*arguments)
    elif operation == 'verify-iso':
        verify_iso(*arguments)
    else:
        raise ValueError('Unknown metadata operation')


if __name__ == '__main__':
    main()
