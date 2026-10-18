import asyncio
from types import SimpleNamespace

import pytest

from goodwe_exporter.config import Config

SENSORS = (
    SimpleNamespace(id_="ppv", name="PV Power", unit="W"),
    SimpleNamespace(id_="vpv1", name="PV1 Voltage", unit="V"),
    SimpleNamespace(id_="e_day", name="Today's PV Generation", unit="kWh"),
    SimpleNamespace(id_="e_total", name="Total PV Generation", unit="kWh"),
    SimpleNamespace(id_="h_total", name="Hours Total", unit="h"),
    SimpleNamespace(id_="temperature", name="Inverter Temperature", unit="C"),
    SimpleNamespace(id_="work_mode_label", name="Work Mode", unit=""),
    SimpleNamespace(id_="missing", name="Unreadable", unit="W"),
)

VALUES = {
    "ppv": 1234,
    "vpv1": 345.6,
    "e_day": 7.8,
    "e_total": 1000.5,
    "h_total": 4000,
    "temperature": 41.2,
    "work_mode_label": "Normal (On-Grid)",
    "missing": None,
}


class FakeInverter:
    model_name = "GW5000-DNS"
    serial_number = "ABC123"
    firmware = "fw1"
    arm_firmware = "arm1"
    rated_power = 5000

    def __init__(self, values=None, delay=0.0, error=None):
        self.values = dict(VALUES if values is None else values)
        self.delay = delay
        self.error = error
        self.reads = 0

    def sensors(self):
        return SENSORS

    async def read_runtime_data(self):
        self.reads += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error:
            raise self.error
        return dict(self.values)


class FakeConnect:
    """Stands in for goodwe.connect; records calls and can be told to fail."""

    def __init__(self, inverter=None, error=None):
        self.inverter = inverter or FakeInverter()
        self.error = error
        self.calls = 0

    async def __call__(self, **kwargs):
        self.calls += 1
        if self.error:
            raise self.error
        return self.inverter


@pytest.fixture
def config():
    return Config(
        inverter_host="192.0.2.1",
        cache_ttl_seconds=5.0,
        scrape_timeout_seconds=0.5,
    )


@pytest.fixture
def fake_connect(monkeypatch):
    fake = FakeConnect()
    monkeypatch.setattr("goodwe_exporter.client.goodwe.connect", fake)
    return fake
