from __future__ import annotations

import logging
import re
from typing import Dict, Iterable, Optional, Tuple

import goodwe
from prometheus_client.core import (
    CounterMetricFamily,
    GaugeMetricFamily,
    InfoMetricFamily,
)
from prometheus_client.registry import Collector

from . import __version__
from .client import InverterClient, Snapshot

log = logging.getLogger(__name__)

UNIT_SUFFIXES = {
    "V": "volts",
    "A": "amperes",
    "W": "watts",
    "VA": "volt_amperes",
    "var": "var",
    "Hz": "hertz",
    "C": "celsius",
    "%": "percent",
    "kWh": "kwh",
    "h": "hours",
}

# Names already used by the exporter's own metrics.
RESERVED = {
    "goodwe_up",
    "goodwe_info",
    "goodwe_scrape_duration_seconds",
    "goodwe_scrape_errors_total",
    "goodwe_scrape_errors",
    "goodwe_last_successful_scrape_timestamp_seconds",
    "goodwe_exporter_build_info",
}


def _sanitize(text: str) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", text.lower()).strip("_")


def metric_name(sensor_id: str, unit: str) -> str:
    name = "goodwe_" + _sanitize(sensor_id)
    suffix = UNIT_SUFFIXES.get(unit) if unit else None
    if suffix is None and unit:
        suffix = _sanitize(unit)
    if suffix and not name.endswith("_" + suffix):
        name += "_" + suffix
    return name


def is_counter(sensor_id: str, unit: str) -> bool:
    """Lifetime totals only ever increase; daily values reset at midnight, so stay gauges."""
    return sensor_id.lower().endswith("_total") and unit in ("kWh", "h")


def _numeric(value) -> Optional[float]:
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    return None


class GoodWeCollector(Collector):
    """Renders the client's latest snapshot. collect() does no I/O."""

    def __init__(self, client: InverterClient):
        self._client = client

    def collect(self) -> Iterable:
        snap = self._client.last_snapshot

        yield InfoMetricFamily(
            "goodwe_exporter_build",
            "Exporter build information",
            {"version": __version__, "goodwe_version": getattr(goodwe, "__version__", "") or _goodwe_version()},
        )

        up = GaugeMetricFamily("goodwe_up", "1 if the last inverter read succeeded")
        up.add_metric([], 1.0 if snap is not None and snap.ok else 0.0)
        yield up

        errors = CounterMetricFamily(
            "goodwe_scrape_errors", "Failed inverter reads by reason", labels=["reason"]
        )
        for reason, count in sorted(self._client.error_counts.items()):
            errors.add_metric([reason], float(count))
        yield errors

        if self._client.last_success is not None:
            last = GaugeMetricFamily(
                "goodwe_last_successful_scrape_timestamp_seconds",
                "Unix time of the last successful inverter read",
            )
            last.add_metric([], self._client.last_success)
            yield last

        if snap is None:
            return

        duration = GaugeMetricFamily(
            "goodwe_scrape_duration_seconds", "Duration of the last inverter read"
        )
        duration.add_metric([], snap.duration)
        yield duration

        if snap.ok:
            yield from self._sensor_metrics(snap)

    def _sensor_metrics(self, snap: Snapshot) -> Iterable:
        if snap.info:
            info = GaugeMetricFamily(
                "goodwe_info",
                "Inverter identity (value is always 1)",
                labels=list(snap.info.keys()),
            )
            info.add_metric(list(snap.info.values()), 1.0)
            yield info

        seen: Dict[str, str] = {}
        for sensor_id, doc, unit in snap.sensors:
            value = _numeric(snap.values.get(sensor_id))
            if value is None:
                continue
            counter = is_counter(sensor_id, unit)
            name = metric_name(sensor_id, unit)
            exposed = name + "_total" if counter else name
            if exposed in RESERVED or exposed in seen:
                log.warning(
                    "Skipping sensor %r: metric name %s clashes with %r",
                    sensor_id, exposed, seen.get(exposed, "an exporter metric"),
                )
                continue
            seen[exposed] = sensor_id
            family = (CounterMetricFamily if counter else GaugeMetricFamily)(name, doc or sensor_id)
            family.add_metric([], value)
            yield family


def _goodwe_version() -> str:
    try:
        from importlib.metadata import version

        return version("goodwe")
    except Exception:  # noqa: BLE001
        return ""
