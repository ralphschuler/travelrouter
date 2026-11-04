"""OpenRC entry points."""

import argparse
import logging
import threading

from .config import ConfigStore
from .policy import LAN_IP
from .system import System, initialize
from .web import make_server


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--bootstrap', action='store_true')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    store = ConfigStore()
    if args.bootstrap:
        initialize(store)
        return
    backend = System(store)
    server = make_server((LAN_IP, 80), store, backend)
    worker = threading.Thread(target=backend.loop, daemon=True)
    worker.start()
    try:
        server.serve_forever()
    finally:
        backend.stop.set()
        server.server_close()


if __name__ == '__main__':
    main()
