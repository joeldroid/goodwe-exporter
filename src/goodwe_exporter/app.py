from __future__ import annotations

import time
from typing import Optional

from aiohttp import web
from prometheus_client import CollectorRegistry
from prometheus_client.exposition import generate_latest

from .client import InverterClient
from .config import Config
from .metrics import GoodWeCollector

# generate_latest() emits the classic text format regardless of what CONTENT_TYPE_LATEST advertises.
CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"

INDEX = (
    "<html><head><title>GoodWe Exporter</title></head><body>"
    "<h1>GoodWe Exporter</h1><p><a href=\"/metrics\">Metrics</a></p></body></html>"
)


def create_app(config: Config, client: Optional[InverterClient] = None) -> web.Application:
    client = client or InverterClient(config)
    registry = CollectorRegistry(auto_describe=False)
    registry.register(GoodWeCollector(client))

    async def metrics(request: web.Request) -> web.Response:
        await client.get_snapshot()
        return web.Response(body=generate_latest(registry), headers={"Content-Type": CONTENT_TYPE})

    async def healthz(request: web.Request) -> web.Response:
        snap = client.last_snapshot
        return web.json_response(
            {
                "status": "ok",
                "inverter_up": bool(snap and snap.ok),
                "last_success": client.last_success,
                "time": time.time(),
            }
        )

    async def index(request: web.Request) -> web.Response:
        return web.Response(text=INDEX, content_type="text/html")

    async def close_client(app: web.Application) -> None:
        await client.close()

    app = web.Application()
    app["client"] = client
    app.on_cleanup.append(close_client)
    app.router.add_get("/", index)
    app.router.add_get("/metrics", metrics)
    app.router.add_get("/healthz", healthz)
    return app
