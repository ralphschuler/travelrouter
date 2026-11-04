"""Boot installer and installed runtime through real UEFI/GRUB in isolated VMs.

Only copied bootloader configs gain a serial console and a noninteractive CI init
shell. Installer payload, kernels, initramfs, packages and application are exact.
"""

import argparse
import hashlib
import json
import os
import re
import secrets
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from run import BOOT_ERRORS, BOOT_READY, HERE, REMOTE, Console, executable, expand_image, require, verify_console_protocol


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
                     part.startswith(('console=', 'init=', 'init_args='))]
            line = '    ' + ' '.join(parts + [f'console={console},115200', 'init=/bin/sh',
                                             'init_args=/proc/self/fd/0'])
            entries += 1
        result.append(line)
    require(entries > 0, 'No Linux boot entry found in the shipped GRUB configuration')
    return '\n'.join(result) + '\n'


def installer_session(path, marker):
    # Keep the controlling-terminal session leader alive after the installer
    # child exits. Otherwise its TTY hangup can kill the CI PID1 shell. The host
    # terminates this disposable VM after the synced status marker is received.
    script = (f'sh {shlex.quote(str(path))}; result=$?; sync; '
              f"printf '\\n{marker}:%s:%s\\n' \"$result\" \"$$\"; "
              'while :; do sleep 60; done')
    return 'setsid -c sh -c ' + shlex.quote(script) + '\n'


def verify_installer_session(output):
    """Check the exact session lifetime using native Alpine and a harmless child."""
    with tempfile.TemporaryDirectory(prefix='installer-preflight-', dir=output) as temporary:
        script = Path(temporary) / 'installer.sh'
        script.write_text('#!/bin/sh\nprintf "Native installer consent:" >/dev/tty\n'
                          'read -r confirmation </dev/tty\n'
                          '[ "$confirmation" = "CI harmless child" ] || exit 1\n'
                          'printf "Installer child completed\\n"\nexit 0\n')
        console = Console(['/bin/sh', '/proc/self/fd/0'], output / 'installer-protocol.log', terminal=True)
        child_pid = None
        try:
            console.command('stty -echo; case $- in *i*) exit 1;; esac', timeout=10)
            marker = 'CI_SESSION_' + secrets.token_hex(8)
            console.send(installer_session(script, marker))
            console.expect(rb'Native installer consent:', 10, error_patterns=(marker.encode(),))
            console.send('CI harmless child\n')
            _, match = console.expect((r'^' + marker + r':([0-9]+):([0-9]+)\r?$').encode(), 15)
            reported_pid = int(match.group(2))
            require(int(match.group(1)) == 0, 'Installer session preflight child failed')
            require(reported_pid > 1 and reported_pid != console.process.pid
                    and os.getsid(reported_pid) == reported_pid and os.getpgid(reported_pid) == reported_pid,
                    'Installer preflight did not establish its own controlling-terminal session')
            child_pid = reported_pid
            require(console.process.poll() is None, 'Installer exit terminated the parent serial shell')
        finally:
            if child_pid is not None:
                # This PID came from our fixed native dummy script, never a VM
                # or installer payload; kill only its newly owned session group.
                try:
                    os.killpg(child_pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
            console.close()
    print('Installer session preflight passed: child exit preserves the parent serial shell', flush=True)


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
        (output / 'devices-before-install.txt').write_text(console.command('cat /proc/partitions; mount'))
        marker = 'CI_INSTALL_EXIT_' + secrets.token_hex(8)
        console.send(installer_session(path.group(1), marker))
        console.expect(rb'Type the whole target disk path, or press Enter to cancel:', 900,
                       error_patterns=(marker.encode(),))
        console.send('/dev/vda\n')
        console.expect(rb'Type exactly ERASE /dev/vda to continue:', 60, error_patterns=(marker.encode(),))
        console.send('ERASE /dev/vda\n')
        report['stage'] = 'UEFI installer: actual write and complete readback'
        output_text, status = console.expect((r'^' + marker + r':([0-9]+):([0-9]+)\r?$').encode(), 900)
        require(int(status.group(1)) == 0, 'Shipped installer failed; see installer console')
        require(b'Installation and full readback verification succeeded: /dev/vda' in output_text,
                'Installer did not report complete image readback verification')
    finally:
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
            console.diagnostics(output, failed=phase not in report.get('runtime_passed', []))
            console.close()


def run(args, report):
    architecture = args.target.removeprefix('generic-')
    require(architecture in {'x86_64', 'aarch64'}, 'Unsupported generic test target')
    require(not args.scratch.exists(), 'Use a fresh generic E2E scratch directory')
    args.scratch.mkdir(parents=True)
    verify_console_protocol(args.output)
    verify_installer_session(args.output)
    report['qemu'] = checked([executable('qemu-system-' + architecture), '--version']).splitlines()[0]
    image = args.dist / f'travelrouter-{args.target}.img.gz'
    require(image.is_file(), 'Expected built runtime .img.gz')
    raw = args.scratch / 'release.img'
    report['archive_sha256'], report['image_sha256'] = expand_image(image, raw)
    report['image_bytes'] = raw.stat().st_size
    report['boundary'] = ('Actual UEFI and GRUB boot of copied installer ISO and installed runtime. '
                          'Only copied GRUB configs gain serial/script-mode init arguments; all bootloader code, '
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
