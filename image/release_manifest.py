"""Require complete platform deliverables before creating the public checksum list."""

import hashlib
import sys
from pathlib import Path


def expected_files():
    names = {'travelrouter-cm5-aarch64.img.gz', 'packages.txt', 'sbom.cdx.json',
             'build-metadata.json', 'travelrouter-update.tru'}
    for architecture in ('x86_64', 'aarch64'):
        prefix = f'travelrouter-generic-{architecture}'
        names.update({prefix + '.img.gz', f'travelrouter-installer-{architecture}.iso',
                      prefix + '-packages.txt', prefix + '-sbom.cdx.json',
                      prefix + '-build-metadata.json', prefix + '-install-manifest.json',
                      prefix + '-iso-boot.txt', prefix + '-SHA256SUMS'})
    return names


def generate(directory):
    directory = Path(directory)
    expected = expected_files()
    actual = {path.name for path in directory.iterdir()} - {'SHA256SUMS'}
    if actual != expected:
        raise ValueError(f'Incomplete or unexpected release assets: missing={sorted(expected - actual)}, '
                         f'unexpected={sorted(actual - expected)}')
    lines = []
    for name in sorted(expected):
        path = directory / name
        if path.is_symlink() or not path.is_file() or path.stat().st_size == 0:
            raise ValueError(f'Release asset must be a nonempty regular file: {name}')
        with path.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        lines.append(f'{digest}  {name}\n')
    (directory / 'SHA256SUMS').write_text(''.join(lines))


if __name__ == '__main__':
    generate(sys.argv[1])
