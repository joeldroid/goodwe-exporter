from __future__ import annotations

import logging
import sys

from aiohttp import web

from .app import create_app
from .config import Config, ConfigError


def main() -> int:
    try:
        config = Config.from_env()
    except ConfigError as exc:
        print("configuration error: %s" % exc, file=sys.stderr)
        return 2

    logging.basicConfig(
        level=config.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger(__name__).info(
        "Starting exporter on %s:%s for inverter %s:%s",
        config.listen_address, config.listen_port, config.inverter_host, config.inverter_port,
    )
    web.run_app(
        create_app(config),
        host=config.listen_address,
        port=config.listen_port,
        print=None,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
