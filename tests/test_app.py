from goodwe import InverterError

from goodwe_exporter.app import create_app


async def test_metrics_ok(aiohttp_client, config, fake_connect):
    client = await aiohttp_client(create_app(config))
    resp = await client.get("/metrics")
    assert resp.status == 200
    assert resp.headers["Content-Type"].startswith("text/plain; version=0.0.4")
    text = await resp.text()
    assert "goodwe_up 1.0" in text
    assert "goodwe_ppv_watts 1234.0" in text


async def test_metrics_with_failing_inverter_still_200(aiohttp_client, config, fake_connect):
    fake_connect.error = InverterError("asleep")
    client = await aiohttp_client(create_app(config))
    resp = await client.get("/metrics")
    assert resp.status == 200
    assert "goodwe_up 0.0" in await resp.text()


async def test_healthz(aiohttp_client, config, fake_connect):
    client = await aiohttp_client(create_app(config))
    resp = await client.get("/healthz")
    assert resp.status == 200
    assert (await resp.json())["inverter_up"] is False  # nothing scraped yet

    await client.get("/metrics")
    assert (await (await client.get("/healthz")).json())["inverter_up"] is True

    fake_connect.error = InverterError("asleep")
    fake_connect.inverter.error = InverterError("asleep")
    assert (await client.get("/healthz")).status == 200


async def test_index(aiohttp_client, config, fake_connect):
    client = await aiohttp_client(create_app(config))
    resp = await client.get("/")
    assert resp.status == 200
    assert "/metrics" in await resp.text()
