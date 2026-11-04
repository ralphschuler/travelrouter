"""Boot installer and installed runtime through real UEFI/GRUB in isolated VMs.

Only copied bootloader configs gain a serial console and a noninteractive CI init
shell. Installer payload, kernels, initramfs, packages and application are exact.
"""

import argparse
import hashlib
import json
import re
import secrets
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

from run import BOOT_ERRORS, BOOT_READY, HERE, REMOTE, Console, executable, expand_image, require


def checked(arguments):
    try:
        return subprocess.run(arguments, check=True, capture_output=True, text=True).stdout  # nosec B603
    except subprocess.CalledProcessError as error:
        raise RuntimeError(f'Host fixture preparation failed: {error.stderr[-2000:]}') from error


def digest(path, limit=None):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        remaining = path.stat().st_size if limit is None else limit
        while remaining:
            chunk = stream.read(min(remaining, 1024 * 1024))
            require(bool(chunk), 'File ended before the verified image length')
            result.update(chunk)
            remaining -= len(chunk)
    return result.hexdigest()


def instrument_grub(text, architecture):
    """Retain menu/kernel/initrd paths, changing only test console/init arguments."""
    console = 'ttyS0' if architecture == 'x86_64' else 'ttyAMA0'
    result = ['set timeout=0', 'terminal_input console', 'terminal_output console']
    entries = 0
    for line in text.splitlines():
        if re.match(r'\s*(?:set\s+timeout=|terminal_(?:input|output)\b)', line):
            continue
        if re.match(r'\s*linux(?:efi)?\s+', line):
            parts = line.split()
            parts = [part for part in parts if part != 'quiet' and not
                     part.startswith(('console=', 'init=', 'init_args=', 'rootflags='))]
            line = '    ' + ' '.join(parts + [f'console={console},115200', 'init=/bin/sh',
                                             'init_args=+i', 'rootflags=size=1536M'])
            entries += 1
        result.append(line)
    require(entries > 0, 'No Linux boot entry found in the shipped GRUB configuration')
    return '\n'.join(result) + '\n'


def machine_command(architecture, firmware_variables, disk, installer_iso=None):
    qemu = executable('qemu-system-' + architecture)
    firmware = Path('/usr/share/qemu')
    if architecture == 'x86_64':
        platform = ['-machine', 'q35', '-cpu', 'max', '-vga', 'none']
        code, variables = firmware / 'edk2-x86_64-code.fd', firmware / 'edk2-i386-vars.fd'
    else:
        platform = ['-machine', 'virt', '-cpu', 'cortex-a72']
        code, variables = firmware / 'edk2-aarch64-code.fd', firmware / 'edk2-arm-vars.fd'
    require(code.is_file() and variables.is_file(), 'Pinned QEMU UEFI firmware is missing')
    shutil.copyfile(variables, firmware_variables)
    command = [qemu, *platform, '-accel', 'tcg,thread=multi', '-m', '2G', '-smp', '2',
               '-display', 'none', '-monitor', 'none', '-serial', 'stdio', '-nic', 'none', '-no-reboot',
               '-drive', f'if=pflash,format=raw,readonly=on,file={code}',
               '-drive', f'if=pflash,format=raw,file={firmware_variables}',
               '-drive', f'if=none,id=target,format=qcow2,file={disk}',
               '-device', 'virtio-blk-pci,drive=target,bootindex=2']
    if installer_iso:
        command += ['-device', 'virtio-scsi-pci,id=scsi',
                    '-drive', f'if=none,id=installer,format=raw,readonly=on,file={installer_iso}',
                    '-device', 'scsi-cd,drive=installer,bootindex=1']
    return command, {'code_sha256': digest(code), 'variables_template_sha256': digest(variables)}


def install(args, architecture, image_bytes, image_hash, report):
    source = args.dist / f'travelrouter-installer-{architecture}.iso'
    require(source.is_file(), 'Expected built installer ISO')
    report['installer_iso_sha256'] = digest(source)
    grub = args.scratch / 'installer-grub.cfg'
    test_iso = args.scratch / 'installer-ci.iso'
    xorriso = executable('xorriso')
    checked([xorriso, '-osirrox', 'on', '-indev', str(source), '-extract', '/boot/grub/grub.cfg', str(grub)])
    grub.write_text(instrument_grub(grub.read_text(), architecture))
    # Replay the ISO's existing El Torito boot equipment and preserve its volume
    # label: upstream standalone EFI code searches that exact label.
    checked([xorriso, '-indev', str(source), '-outdev', str(test_iso), '-boot_image', 'any', 'replay',
             '-map', str(grub), '/boot/grub/grub.cfg', '-commit'])
    report['instrumented_installer_iso_sha256'] = digest(test_iso)
    disk = args.scratch / 'installed.qcow2'
    capacity = max(8 * 1024**3, 1 << (image_bytes - 1).bit_length())
    checked([executable('qemu-img'), 'create', '-f', 'qcow2', str(disk), str(capacity)])
    command, report['firmware'] = machine_command(architecture, args.scratch / 'installer-vars.fd', disk, test_iso)
    output = args.output / 'installer'
    output.mkdir()
    console = Console(command, output / 'console.log')
    try:
        report['stage'] = 'UEFI installer: restore stock Alpine environment'
        print(report['stage'], flush=True)
        console.expect(BOOT_READY, 900, error_patterns=BOOT_ERRORS)
        console.command("stty -echo; case $- in *i*) exit 1;; esac", timeout=30)
        console.ready = True
        console.command('openrc sysinit; openrc boot; test -b /dev/vda', timeout=180)
        result = console.command("set -- /media/*/travelrouter/install.sh; "
                                 "test \"$#\" -eq 1 && test -f \"$1\" && printf 'CI_INSTALLER:%s\\n' \"$1\"")
        path = re.search(r'^CI_INSTALLER:(/media/[^\r\n]+/travelrouter/install\.sh)\r?$', result, re.MULTILINE)
        require(path is not None, 'Could not uniquely locate the shipped installer payload')
        marker = 'CI_INSTALL_EXIT_' + secrets.token_hex(8)
        # The installer intentionally reads consent from /dev/tty. A CI PID1
        # shell has no controlling terminal, so give only its installer child
        # the same dedicated serial TTY a normal local login would provide.
        console.send(f"setsid -c sh {shlex.quote(path.group(1))}; result=$?; "
                     f"printf '\\n{marker}:%s\\n' \"$result\"\n")
        console.expect(rb'Type the whole target disk path, or press Enter to cancel:', 900,
                       error_patterns=(marker.encode(),))
        console.send('/dev/vda\n')
        console.expect(rb'Type exactly ERASE /dev/vda to continue:', 60, error_patterns=(marker.encode(),))
        console.send('ERASE /dev/vda\n')
        report['stage'] = 'UEFI installer: actual write and complete readback'
        output_text, status = console.expect((r'^' + marker + r':([0-9]+)\r?$').encode(), 900)
        require(int(status.group(1)) == 0, 'Shipped installer failed; see installer console')
        require(b'Installation and full readback verification succeeded: /dev/vda' in output_text,
                'Installer did not report complete image readback verification')
        console.command('sync', timeout=30)
    finally:
        if console.ready:
            try:
                (output / 'devices.txt').write_text(console.command('cat /proc/partitions; mount', check=False))
            except (OSError, RuntimeError, TimeoutError):
                pass
        console.close()
    raw = args.scratch / 'installed.raw'
    checked([executable('qemu-img'), 'convert', '-f', 'qcow2', '-O', 'raw', str(disk), str(raw)])
    written_hash = digest(raw, image_bytes)
    require(written_hash == image_hash, 'Installed disk bytes differ from the released runtime image')
    report['installed_prefix_sha256'] = written_hash
    report['installer_result'] = 'passed: real UEFI ISO boot, installer write and independent complete readback'
    return raw


def runtime(args, architecture, raw, report):
    mcopy, qemu_img = executable('mcopy'), executable('qemu-img')
    grub = args.scratch / 'runtime-grub.cfg'
    checked([mcopy, '-i', f'{raw}@@1048576', '::/boot/grub/grub.cfg', str(grub)])
    report['shipped_runtime_grub_sha256'] = digest(grub)
    grub.write_text(instrument_grub(grub.read_text(), architecture))
    checked([mcopy, '-o', '-i', f'{raw}@@1048576', str(grub), '::/boot/grub/grub.cfg'])
    report['instrumented_runtime_grub_sha256'] = digest(grub)
    disk = args.scratch / 'runtime.qcow2'
    checked([qemu_img, 'create', '-f', 'qcow2', '-F', 'raw', '-b', str(raw), str(disk)])
    for phase in ('initial', 'restored'):
        output = args.output / phase
        output.mkdir()
        command, _ = machine_command(architecture, args.scratch / f'{phase}-vars.fd', disk)
        console = Console(command, output / 'console.log')
        try:
            report['stage'] = phase + ': installed runtime UEFI boot'
            print(report['stage'], flush=True)
            console.boot()
            for fixture in ('prepare.sh', 'client.py', 'firewall.py'):
                console.upload(HERE / fixture)
            report['stage'] = phase + ': real OpenRC, WPA2 and DHCP'
            console.command(f'sh {REMOTE}/prepare.sh {phase}', timeout=240)
            report['stage'] = phase + ': measured firewall denial'
            result = console.command(f'python3 {REMOTE}/firewall.py', timeout=90)
            (output / 'firewall-results.txt').write_text(result)
            report['stage'] = phase + ': wireless HTTP, DNS and credentials'
            result = console.command(f'ip netns exec tr-client python3 {REMOTE}/client.py {phase}', timeout=120)
            (output / 'client-results.txt').write_text(result)
            console.command('sync', timeout=30)
            report.setdefault('runtime_passed', []).append(phase)
        finally:
            console.diagnostics(output)
            console.close()


def run(args, report):
    architecture = args.target.removeprefix('generic-')
    require(architecture in {'x86_64', 'aarch64'}, 'Unsupported generic test target')
    require(not args.scratch.exists(), 'Use a fresh generic E2E scratch directory')
    args.scratch.mkdir(parents=True)
    report['qemu'] = checked([executable('qemu-system-' + architecture), '--version']).splitlines()[0]
    image = args.dist / f'travelrouter-{args.target}.img.gz'
    require(image.is_file(), 'Expected built runtime .img.gz')
    raw = args.scratch / 'release.img'
    report['archive_sha256'], report['image_sha256'] = expand_image(image, raw)
    report['image_bytes'] = raw.stat().st_size
    report['boundary'] = ('Actual UEFI and GRUB boot of copied installer ISO and installed runtime. '
                          'Only copied GRUB configs gain serial/+i init-shell arguments; all bootloader code, '
                          'kernels, initramfs, APKs and installer/application payloads remain shipped bytes. '
                          'Runtime uses mac80211_hwsim radios, not physical hardware qualification.')
    installed = install(args, architecture, report['image_bytes'], report['image_sha256'], report)
    runtime(args, architecture, installed, report)
    report.update(result='passed', stage='complete')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', choices=['generic-x86_64', 'generic-aarch64'], required=True)
    parser.add_argument('--dist', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--scratch', type=Path, required=True)
    args = parser.parse_args()
    args.dist, args.output, args.scratch = (path.resolve() for path in (args.dist, args.output, args.scratch))
    args.output.mkdir(parents=True, exist_ok=True)
    report = {'target': args.target, 'result': 'failed', 'stage': 'host preparation'}
    started = time.monotonic()
    try:
        run(args, report)
    except (OSError, RuntimeError, ValueError, TimeoutError, subprocess.SubprocessError) as error:
        report['error'] = str(error)
        print('GENERIC IMAGE E2E FAILED:', error, file=sys.stderr, flush=True)
    finally:
        report['duration_seconds'] = round(time.monotonic() - started, 1)
        (args.output / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    if report['result'] != 'passed':
        return 1
    print('GENERIC IMAGE E2E PASSED: UEFI installer, exact installed image and real runtime services', flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
