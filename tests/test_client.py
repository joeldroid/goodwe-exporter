import asyncio

from goodwe import InverterError

from goodwe_exporter.client import InverterClient

from .conftest import FakeInverter


async def test_cache_within_ttl(config, fake_connect):
    client = InverterClient(config)
    a = await client.get_snapshot()
    b = await client.get_snapshot()
    assert a is b
    assert fake_connect.inverter.reads == 1
    assert fake_connect.calls == 1


async def test_concurrent_calls_coalesce(config, fake_connect):
    fake_connect.inverter = FakeInverter(delay=0.05)
    client = InverterClient(config)
    snaps = await asyncio.gather(*(client.get_snapshot() for _ in range(10)))
    assert fake_connect.inverter.reads == 1
    assert all(s is snaps[0] for s in snaps)


async def test_ttl_expiry_rereads(config, fake_connect):
    client = InverterClient(config.__class__(**{**config.__dict__, "cache_ttl_seconds": 0.0}))
    await client.get_snapshot()
    await client.get_snapshot()
    assert fake_connect.inverter.reads == 2
    assert fake_connect.calls == 1  # connection is reused


async def test_timeout(config, fake_connect):
    fake_connect.inverter = FakeInverter(delay=5)
    client = InverterClient(config)
    snap = await client.get_snapshot()
    assert not snap.ok
    assert snap.error_reason == "timeout"
    assert client.error_counts["timeout"] == 1
    await client.close()


async def test_timeout_not_blocked_by_inverter_swallowing_cancellation(config, fake_connect):
    """goodwe catches CancelledError to retry; the scrape must still return on time."""

    class Stubborn(FakeInverter):
        async def read_runtime_data(self):
            self.reads += 1
            for _ in range(20):
                try:
                    await asyncio.sleep(0.1)
                except asyncio.CancelledError:
                    pass
            return {}

    fake_connect.inverter = Stubborn()
    client = InverterClient(config)  # scrape timeout 0.5s
    loop = asyncio.get_running_loop()
    start = loop.time()
    snap = await client.get_snapshot()
    assert loop.time() - start < 1.0
    assert snap.error_reason == "timeout"
    await client.close()


async def test_no_second_read_while_previous_still_running(config, fake_connect):
    cfg = config.__class__(**{**config.__dict__, "cache_ttl_seconds": 0.0, "scrape_timeout_seconds": 0.1})
    fake_connect.inverter = FakeInverter(delay=0.5)
    client = InverterClient(cfg)
    await client.get_snapshot()
    snap = await client.get_snapshot()
    assert snap.error_reason == "timeout"
    assert fake_connect.inverter.reads == 1
    await client.close()


async def test_connect_failure_classified(config, fake_connect):
    fake_connect.error = InverterError("no reply")
    client = InverterClient(config)
    snap = await client.get_snapshot()
    assert snap.error_reason == "connect"


async def test_read_failure_triggers_reconnect(config, fake_connect):
    cfg = config.__class__(**{**config.__dict__, "cache_ttl_seconds": 0.0})
    client = InverterClient(cfg)
    fake_connect.inverter = FakeInverter(error=InverterError("bad read"))
    snap = await client.get_snapshot()
    assert snap.error_reason == "inverter_error"
    assert fake_connect.calls == 1

    fake_connect.inverter = FakeInverter()
    snap = await client.get_snapshot()
    assert snap.ok
    assert fake_connect.calls == 2
    assert client.last_success is not None


async def test_failure_cached_for_ttl(config, fake_connect):
    fake_connect.error = InverterError("down")
    client = InverterClient(config)
    await client.get_snapshot()
    await client.get_snapshot()
    assert fake_connect.calls == 1
