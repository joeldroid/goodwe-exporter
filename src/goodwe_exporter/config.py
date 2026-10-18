from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping, Optional

# goodwe.connect() matches "NS" internally, while its docs call the family "D-NS".
FAMILIES = {"ET", "EH", "BT", "BH", "ES", "EM", "BP", "DT", "MS", "NS", "XS"}
FAMILY_ALIASES = {"D-NS": "NS"}


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Config:
    inverter_host: str
    inverter_port: int = 8899
    inverter_family: Optional[str] = None
    inverter_timeout: int = 1
    inverter_retries: int = 3
    cache_ttl_seconds: float = 5.0
    scrape_timeout_seconds: float = 8.0
    listen_address: str = "0.0.0.0"
    listen_port: int = 9877
    log_level: str = "INFO"

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None) -> "Config":
        env = os.environ if env is None else env

        def get(name: str, default: str = "") -> str:
            return (env.get(name) or default).strip()

        def number(name: str, default: str, kind=int, minimum=0):
            raw = get(name, default)
            try:
                value = kind(raw)
            except ValueError:
                raise ConfigError("%s must be a number, got %r" % (name, raw))
            if value < minimum:
                raise ConfigError("%s must be >= %s, got %r" % (name, minimum, raw))
            return value

        host = get("INVERTER_HOST")
        if not host:
            raise ConfigError("INVERTER_HOST is required")

        family = get("INVERTER_FAMILY").upper() or None
        family = FAMILY_ALIASES.get(family, family)
        if family is not None and family not in FAMILIES:
            raise ConfigError(
                "INVERTER_FAMILY must be one of %s (or D-NS), got %r"
                % (", ".join(sorted(FAMILIES)), family)
            )

        inverter_port = number("INVERTER_PORT", "8899", minimum=1)
        listen_port = number("LISTEN_PORT", "9877", minimum=1)
        for name, port in (("INVERTER_PORT", inverter_port), ("LISTEN_PORT", listen_port)):
            if port > 65535:
                raise ConfigError("%s must be <= 65535, got %r" % (name, port))

        log_level = get("LOG_LEVEL", "INFO").upper()
        if log_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ConfigError("LOG_LEVEL is invalid: %r" % log_level)

        return cls(
            inverter_host=host,
            inverter_port=inverter_port,
            inverter_family=family,
            inverter_timeout=number("INVERTER_TIMEOUT", "1", minimum=1),
            inverter_retries=number("INVERTER_RETRIES", "3", minimum=0),
            cache_ttl_seconds=number("CACHE_TTL_SECONDS", "5", kind=float),
            scrape_timeout_seconds=number("SCRAPE_TIMEOUT_SECONDS", "8", kind=float, minimum=0.1),
            listen_address=get("LISTEN_ADDRESS", "0.0.0.0"),
            listen_port=listen_port,
            log_level=log_level,
        )
