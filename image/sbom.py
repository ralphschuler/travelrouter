"""Emit an inventory derived from the installed APK database, not a guessed list."""

import hashlib
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote


def generate(root, out, bundle_sha, architecture='aarch64', target='cm5'):
    targets = {'cm5': 'aarch64', 'generic-x86_64': 'x86_64', 'generic-aarch64': 'aarch64'}
    if targets.get(target) != architecture:
        raise ValueError('Image target and architecture do not match')
    root, out = Path(root), Path(out)
    database = root / 'lib/apk/db/installed'
    components = []
    for paragraph in database.read_text().split('\n\n'):
        fields = dict(line.split(':', 1) for line in paragraph.splitlines()
                      if len(line) >= 2 and line[1] == ':')
        if 'P' not in fields or 'V' not in fields:
            continue
        name, version = fields['P'], fields['V']
        package_architecture = fields.get('A', architecture)
        if package_architecture not in {architecture, 'noarch'}:
            raise ValueError('Installed package architecture does not match the image')
        purl = f'pkg:apk/alpine/{quote(name)}@{quote(version)}?arch={package_architecture}&distro=alpine-3.24.3'
        components.append({'type': 'library', 'name': name, 'version': version,
                           'purl': purl, 'bom-ref': purl})
    if not components:
        raise RuntimeError('Cannot produce SBOM: no installed packages found')
    sbom = {'bomFormat': 'CycloneDX', 'specVersion': '1.6', 'version': 1,
            'metadata': {'component': {'type': 'operating-system', 'name': 'TravelRouter',
                                       'version': os.environ.get('GITHUB_REF_NAME', 'development')}},
            'components': sorted(components, key=lambda item: item['name'])}
    (out / 'sbom.cdx.json').write_text(json.dumps(sbom, indent=2) + '\n')
    hashes = {}
    for package in sorted((root.parent / 'downloads').glob('*.apk')):
        hashes[package.name] = hashlib.sha256(package.read_bytes()).hexdigest()
    qualification = 'physical CM5 validation required' if target == 'cm5' else 'UEFI hardware validation required'
    metadata = {'alpine': '3.24.3', 'architecture': architecture, 'target': target, 'boot_bundle_sha256': bundle_sha,
                'source_commit': os.environ.get('GITHUB_SHA', 'local'),
                'built_at': datetime.now(UTC).isoformat(),
                'qualification': 'experimental: ' + qualification,
                'package_sha256': hashes}
    (out / 'build-metadata.json').write_text(json.dumps(metadata, indent=2) + '\n')


if __name__ == '__main__':
    generate(*sys.argv[1:])
