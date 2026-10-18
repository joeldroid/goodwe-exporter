import logging

from prometheus_client import CollectorRegistry
from prometheus_client.exposition import generate_latest
from prometheus_client.parser import text_string_to_metric_families

from goodwe_exporter.client import InverterClient
from goodwe_exporter.metrics import GoodWeCollector, is_counter, metric_name

from .conftest import FakeInverter


def test_metric_name():
    assert metric_name("ppv", "W") == "goodwe_ppv_watts"
    assert metric_name("Temperature", "C") == "goodwe_temperature_celsius"
    assert metric_name("work_mode_label", "") == "goodwe_work_mode_label"
    assert metric_name("pv_watts", "W") == "goodwe_pv_watts"  # no doubled suffix
    assert metric_name("x", "kVA") == "goodwe_x_kva"


def test_is_counter():
    assert is_counter("e_total", "kWh")
    assert is_counter("h_total", "h")
    assert not is_counter("e_day", "kWh")
    assert not is_counter("pgrid_total", "W")


async def render(client):
    await client.get_snapshot()
    registry = CollectorRegistry(auto_describe=False)
    registry.register(GoodWeCollector(client))
    return generate_latest(registry).decode()


async def test_sensor_metrics(config, fake_connect):
    text = await render(InverterClient(config))
    families = {f.name: f for f in text_string_to_metric_families(text)}

    assert families["goodwe_up"].samples[0].value == 1
    assert families["goodwe_ppv_watts"].type == "gauge"
    assert families["goodwe_e_day_kwh"].type == "gauge"
    assert families["goodwe_e_total_kwh"].type == "counter"
    assert "goodwe_e_total_kwh_total 1000.5" in text
    assert "goodwe_h_total_hours_total 4000.0" in text
    # None and string values are skipped.
    assert "goodwe_missing" not in text
    assert "goodwe_work_mode_label" not in text

    info = families["goodwe_info"].samples[0]
    assert info.labels["model"] == "GW5000-DNS"
    assert info.labels["serial"] == "ABC123"
    assert info.labels["rated_power_watts"] == "5000"
    assert "goodwe_exporter_build_info" in text


async def test_failed_read_exposes_no_sensor_series(config, fake_connect):
    fake_connect.error = RuntimeError("boom")
    text = await render(InverterClient(config))
    assert "goodwe_up 0.0" in text
    assert 'goodwe_scrape_errors_total{reason="unexpected"} 1.0' in text
    assert "goodwe_ppv_watts" not in text
    assert "goodwe_info" not in text


async def test_name_clash_keeps_first(config, fake_connect, caplog):
    from types import SimpleNamespace

    class Clashing(FakeInverter):
        def sensors(self):
            return (
                SimpleNamespace(id_="ppv", name="A", unit="W"),
                SimpleNamespace(id_="PPV", name="B", unit="W"),
            )

    fake_connect.inverter = Clashing(values={"ppv": 1, "PPV": 2})
    with caplog.at_level(logging.WARNING):
        text = await render(InverterClient(config))
    assert "goodwe_ppv_watts 1.0" in text
    assert "goodwe_ppv_watts 2.0" not in text
    assert "clashes" in caplog.text
