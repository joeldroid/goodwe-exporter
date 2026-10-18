from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

import goodwe
from goodwe import InverterError

from .config import Config

log = logging.getLogger(__name__)

# (id, name, unit) captured at read time so the snapshot is self-contained.
SensorMeta = Tuple[str, str, str]

ERROR_REASONS = ("timeout", "connect", "inverter_error", "unexpected")


@dataclass(frozen=True)
class Snapshot:
    ok: bool
    timestamp: float
    duration: float
    values: Dict[str, Any] = field(default_factory=dict)
    sensors: Tuple[SensorMeta, ...] = ()
    info: Dict[str, str] = field(default_factory=dict)
    error_reason: Optional[str] = None


class InverterClient:
    """Reads the inverter on demand, with a TTL cache, a lock and a hard timeout."""

    def __init__(self, config: Config):
        self._config = config
        self._inverter: Optional[Any] = None
        self._lock = asyncio.Lock()
        self._snapshot: Optional[Snapshot] = None
        self._monotonic_read_at = 0.0
        self._pending: Optional[asyncio.Future] = None
        self.last_success: Optional[float] = None
        self.error_counts: Dict[str, int] = {reason: 0 for reason in ERROR_REASONS}

    @property
    def last_snapshot(self) -> Optional[Snapshot]:
        return self._snapshot

    def _fresh(self) -> bool:
        return (
            self._snapshot is not None
            and time.monotonic() - self._monotonic_read_at < self._config.cache_ttl_seconds
        )

    async def get_snapshot(self) -> Snapshot:
        if self._fresh():
            return self._snapshot
        async with self._lock:
            if self._fresh():
                return self._snapshot
            self._snapshot = await self._read()
            self._monotonic_read_at = time.monotonic()
            return self._snapshot

    async def _connect_and_read(self, stage: list) -> Tuple[Any, Dict[str, Any]]:
        if self._inverter is None:
            self._inverter = await goodwe.connect(
                host=self._config.inverter_host,
                port=self._config.inverter_port,
                family=self._config.inverter_family,
                timeout=self._config.inverter_timeout,
                retries=self._config.inverter_retries,
            )
        stage[0] = "read"
        return self._inverter, await self._inverter.read_runtime_data()

    async def _read(self) -> Snapshot:
        started = time.monotonic()
        if self._pending is not None and not self._pending.done():
            # An earlier read is still winding down inside goodwe; don't pile a second client onto the inverter.
            return self._failed(started, "timeout", "previous read is still running")

        stage = ["connect"]
        # goodwe uses CancelledError internally as its per-request timeout and retries on it, so
        # asyncio.wait_for() would block until the library gave up. Wait on the task instead and
        # abandon it (bounded by timeout x retries) if it overruns.
        task = asyncio.ensure_future(self._connect_and_read(stage))
        done, _ = await asyncio.wait({task}, timeout=self._config.scrape_timeout_seconds)
        if not done:
            self._pending = task
            task.add_done_callback(_consume_result)
            return self._failed(started, "timeout", "timed out after %ss" % self._config.scrape_timeout_seconds)

        try:
            inverter, values = task.result()
        except InverterError as exc:
            return self._failed(started, "connect" if stage[0] == "connect" else "inverter_error", repr(exc))
        except Exception as exc:  # noqa: BLE001 - never let a scrape crash the exporter
            log.error("Unexpected error reading inverter", exc_info=exc)
            return self._failed(started, "unexpected", repr(exc))

        now = time.time()
        self.last_success = now
        return Snapshot(
            ok=True,
            timestamp=now,
            duration=time.monotonic() - started,
            values=dict(values),
            sensors=tuple((s.id_, s.name, s.unit) for s in inverter.sensors()),
            info=_inverter_info(inverter),
        )

    async def close(self) -> None:
        if self._pending is not None and not self._pending.done():
            self._pending.cancel()

    def _failed(self, started: float, reason: str, detail: str) -> Snapshot:
        # Drop the connection so the next read re-establishes it (e.g. after night-time sleep).
        self._inverter = None
        self.error_counts[reason] += 1
        log.warning("Inverter read failed (%s): %s", reason, detail)
        return Snapshot(
            ok=False,
            timestamp=time.time(),
            duration=time.monotonic() - started,
            error_reason=reason,
        )


def _consume_result(task: "asyncio.Future") -> None:
    """Retrieve the outcome of an abandoned read so asyncio doesn't log it as never retrieved."""
    if not task.cancelled():
        task.exception()


def _inverter_info(inverter: Any) -> Dict[str, str]:
    return {
        "model": str(getattr(inverter, "model_name", None) or ""),
        "serial": str(getattr(inverter, "serial_number", None) or ""),
        "firmware": str(getattr(inverter, "firmware", None) or ""),
        "arm_firmware": str(getattr(inverter, "arm_firmware", None) or ""),
        "family": type(inverter).__name__,
        "rated_power_watts": str(getattr(inverter, "rated_power", 0) or 0),
    }

