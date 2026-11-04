"""Set the shared production RAM-root limit in Pi and generic boot configuration."""

import re
import sys
from pathlib import Path


def configure_cmdline(text):
    arguments, options = [], []
    for argument in text.split():
        if argument.startswith('rootflags='):
            for option in argument.partition('=')[2].split(','):
                if option and not option.startswith('size=') and option not in options:
                    options.append(option)
        elif not argument.startswith('root_size='):
            arguments.append(argument)
    if not arguments:
        raise ValueError('Expected an existing kernel command line')
    # This is a ceiling, not a preallocation. The default 50% tmpfs ceiling left
    # less than 1 MiB free after the firmware/package restore on a 2 GiB VM.
    arguments.append('rootflags=' + ','.join([*options, 'size=75%']))
    return ' '.join(arguments) + '\n'


def configure_grub(text):
    lines, entries = [], 0
    for line in text.splitlines(keepends=True):
        match = re.match(r'^(\s*)(linux(?:efi)?\s+)(.*?)(?:\n)?$', line)
        if match:
            lines.append(match[1] + match[2] + configure_cmdline(match[3]))
            entries += 1
        else:
            lines.append(line)
    if not entries:
        raise ValueError('Expected at least one GRUB kernel command line')
    return ''.join(lines)


if __name__ == '__main__':
    kind, filename = sys.argv[1:]
    configure = {'cmdline': configure_cmdline, 'grub': configure_grub}[kind]
    path = Path(filename)
    path.write_text(configure(path.read_text()))
