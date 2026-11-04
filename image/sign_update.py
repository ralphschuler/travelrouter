"""Release-only signing. The private key is supplied by a GitHub Actions secret."""

import json
import os
import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from travelrouter import __version__  # noqa: E402
from travelrouter.updates import package_update  # noqa: E402

key = serialization.load_pem_private_key(os.environ['UPDATE_SIGNING_KEY'].encode(), password=None)
source = Path(__file__).resolve().parents[1] / 'src'
files = {str(path.relative_to(source)): path.read_bytes() for path in (source / 'travelrouter').rglob('*')
         if path.is_file() and path.suffix in {'.py', '.js', '.html', '.css', '.woff2', '.txt'}}
envelope = package_update(files, __version__, key)
Path('dist/travelrouter-update.tru').write_text(json.dumps(envelope) + '\n')
