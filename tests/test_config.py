import pytest

from goodwe_exporter.config import Config, ConfigError


def test_defaults():
    c = Config.from_env({"INVERTER_HOST": "10.0.0.5"})
    assert c.inverter_host == "10.0.0.5"
    assert c.inverter_port == 8899
    assert c.inverter_family is None
    assert c.listen_port == 9877
    assert c.cache_ttl_seconds == 5.0


def test_host_required():
    with pytest.raises(ConfigError, match="INVERTER_HOST"):
        Config.from_env({})


def test_family_uppercased_and_aliased():
    assert Config.from_env({"INVERTER_HOST": "h", "INVERTER_FAMILY": "et"}).inverter_family == "ET"
    assert Config.from_env({"INVERTER_HOST": "h", "INVERTER_FAMILY": "d-ns"}).inverter_family == "NS"


@pytest.mark.parametrize(
    "extra",
    [
        {"INVERTER_FAMILY": "nope"},
        {"INVERTER_PORT": "abc"},
        {"INVERTER_PORT": "70000"},
        {"LISTEN_PORT": "0"},
        {"LOG_LEVEL": "loud"},
        {"SCRAPE_TIMEOUT_SECONDS": "0"},
    ],
)
def test_invalid_values(extra):
    with pytest.raises(ConfigError):
        Config.from_env({"INVERTER_HOST": "h", **extra})
