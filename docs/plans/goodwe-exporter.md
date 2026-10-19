# GoodWe Prometheus Exporter: Implementation Plan

Library: [marcelblijleven/goodwe](https://github.com/marcelblijleven/goodwe) (PyPI `goodwe`, 0.4.10).

## 0. Findings

**Repo state.** Only `LICENSE`, `.gitignore` (Python template) and a stub `README.md`. Local machine has Python 3.9.6 and no `docker` binary, so unit tests run in a local venv (goodwe supports >=3.8; container uses 3.12) and Docker verification must happen elsewhere/CI.

**`goodwe` library.**
- Async-only. `await goodwe.connect(host, port=8899, family=None, comm_addr=0, timeout=1, retries=3, do_discover=True)` returns an `Inverter`. `family=None` auto-detects (ET, EH, BT, BH, ES, EM, BP, DT, MS, D-NS, XS). Port 8899 = UDP, 502 = Modbus/TCP (assumed; transport follows port). Raises `InverterError` if it cannot connect/recognise.
- `await inverter.read_runtime_data()` returns `dict[sensor_id, value]`. Worst case about `timeout x retries` seconds per request. Failures raise `RequestFailedException`, `RequestRejectedException`, `PartialResponseException` (all `InverterError`). Unparseable sensors come back as `None`.
- `inverter.sensors()` yields `Sensor(id_, offset, name, size_, unit, kind)`. Units: V, A, W, VA, var, Hz, kWh, h, %, C, "".
- Inverter attributes: `model_name`, `serial_number`, `firmware`, `arm_firmware`, `rated_power`, `modbus_version`.
- `search_inverters()` is a UDP broadcast and does not work from a bridged Docker network, so `INVERTER_HOST` is required and discovery is not supported.
- Quirks: the inverter's UDP endpoint serves roughly one client at a time (serialise reads behind an `asyncio.Lock`); many inverters are unresponsive at night, so `goodwe_up 0` is a normal state.

## 1. Key decisions

| Decision | Choice | Why |
|---|---|---|
| Read strategy | Scrape-time read behind TTL cache (default 5 s), lock and hard timeout; no background poller | No extra load on a fragile inverter, no stale-state handling, concurrent scrapers share one read |
| Web framework | `aiohttp` | goodwe is async; avoids thread/loop bridging |
| Prometheus approach | Custom `Collector` rendering an immutable snapshot, per-app `CollectorRegistry` | Async handler refreshes snapshot then calls `generate_latest`; `collect()` stays sync with no I/O |
| Connection | Keep one `Inverter`, reconnect after any failure | Avoids re-discovery, recovers from night outages |
| Stale data | On failed read emit `goodwe_up 0` and no sensor series | Never serve old values as fresh |
| Python | `python:3.12-slim` | Within supported range |
| Pinning | `goodwe==0.4.10`, compatible ranges elsewhere | Library is reverse-engineered; bump deliberately |

## 2. Project layout

```
pyproject.toml
requirements.txt / requirements-dev.txt
src/goodwe_exporter/{__init__,__main__,config,client,metrics,app}.py
tests/{conftest,test_config,test_metrics,test_client,test_app}.py
Dockerfile, docker-compose.yml, .dockerignore
prometheus/prometheus.yml.example
README.md
docs/plans/goodwe-exporter.md
```

## 3. Configuration (env vars, validated at startup)

| Var | Default | Notes |
|---|---|---|
| `INVERTER_HOST` | required | IP or hostname |
| `INVERTER_PORT` | `8899` | `502` for Modbus/TCP |
| `INVERTER_FAMILY` | auto | One of ET, EH, BT, BH, ES, EM, BP, DT, MS, D-NS, XS (uppercased, validated) |
| `INVERTER_TIMEOUT` | `1` | Per-request seconds |
| `INVERTER_RETRIES` | `3` | |
| `CACHE_TTL_SECONDS` | `5` | Minimum interval between real reads |
| `SCRAPE_TIMEOUT_SECONDS` | `8` | `wait_for` around connect+read; must be below Prometheus `scrape_timeout` |
| `LISTEN_ADDRESS` | `0.0.0.0` | |
| `LISTEN_PORT` | `9877` | |
| `LOG_LEVEL` | `INFO` | |

## 4. Metrics

Names are generated dynamically from `inverter.sensors()`: `goodwe_<sensor_id>_<unit_suffix>`, id lowercased and sanitised to `[a-z0-9_]`, HELP = sensor name.

Unit suffixes: V `_volts`, A `_amperes`, W `_watts`, VA `_volt_amperes`, var `_var`, Hz `_hertz`, C `_celsius`, % `_percent`, kWh `_kwh`, h `_hours`, none = no suffix. Do not double a suffix the id already ends with.

Typing:
- **Counter:** id ends in `_total` and unit is kWh or h (e.g. `goodwe_e_total_kwh_total`).
- **Gauge:** everything else (daily energy resets at midnight, so it is a gauge).
- **Skipped:** `None` and string values. Bools become 0/1.
- Name clash after sanitising: warn, keep first.

Labels: sensor series are label-free. Identity goes in `goodwe_info{model,serial,firmware,arm_firmware,rated_power_watts} 1`.

Self-metrics: `goodwe_up`, `goodwe_scrape_duration_seconds`, `goodwe_scrape_errors_total{reason=timeout|inverter_error|connect|unexpected}`, `goodwe_last_successful_scrape_timestamp_seconds`, `goodwe_exporter_build_info{version,goodwe_version}`.

## 5. HTTP behaviour

- `GET /metrics`: always 200, `text/plain; version=0.0.4`. Inverter failure is `goodwe_up 0`, not a 5xx.
- `GET /healthz`: 200 JSON while process is alive; does not touch the inverter (night-time sleep must not restart the container).
- `GET /`: small HTML page linking to `/metrics`.

`client.get_snapshot()`:
1. Return cached snapshot if younger than TTL.
2. Acquire lock, re-check cache (coalesces concurrent scrapes).
3. In `asyncio.wait_for(..., SCRAPE_TIMEOUT_SECONDS)`: connect if no inverter, then `read_runtime_data()`.
4. On any exception: drop the inverter (reconnect next time), count error, log WARNING, return failed snapshot (`up=0`), cached for TTL.
5. Snapshot is immutable: `{ok, values, sensor meta, inverter info, duration, ts}`.

## 6. Dockerfile

Multi-stage on `python:3.12-slim`: builder creates `/opt/venv` and installs requirements then the package; runtime copies the venv, runs as non-root uid 10001, `ENTRYPOINT ["python","-m","goodwe_exporter"]` (exec form), `EXPOSE 9877`, `HEALTHCHECK` using urllib against `/healthz` (no curl). OCI labels. `.dockerignore` excludes git, tests, docs, caches, venvs, `.env`.

`docker-compose.yml`: one service, `restart: unless-stopped`, port 9877, `INVERTER_HOST: ${INVERTER_HOST:?set INVERTER_HOST}`, `read_only: true`, `cap_drop: [ALL]`, `no-new-privileges`. Bridge networking is fine for unicast UDP replies.

## 7. Tests (pytest, `asyncio_mode = auto`, no network)

- `test_config`: defaults, missing host, bad family/port, family uppercasing.
- `test_metrics`: gauge vs counter naming, `None`/string skipped, clash handling, `goodwe_info`, output parses with `text_string_to_metric_families`.
- `test_client`: TTL caching, concurrent calls coalesce, timeout gives `up=0`, reconnect after failure, cached failure not retried in TTL.
- `test_app`: `/metrics` 200 with `goodwe_up 1`; failing inverter still 200 with `goodwe_up 0`; `/healthz` 200 in both.

## 8. Sample Prometheus config

```yaml
scrape_configs:
  - job_name: goodwe
    scrape_interval: 15s
    scrape_timeout: 10s
    static_configs:
      - targets: ["goodwe-exporter:9877"]
```

## 9. Implementation sequence

1. Scaffold pyproject, requirements, package skeleton, venv.
2. `config.py` + tests.
3. `metrics.py` + tests.
4. `client.py` + fake inverter fixture + tests.
5. `app.py`, `__main__.py` + tests.
6. Dockerfile, .dockerignore, docker-compose.yml.
7. README (usage, env table, metric naming, Prometheus config, night-time `goodwe_up 0`, UDP single-client caveat).

## 10. Verification

1. venv + `pytest -q` green.
2. Local run with unreachable inverter (`INVERTER_HOST=192.0.2.1`): `/metrics` shows `goodwe_up 0` within about `SCRAPE_TIMEOUT_SECONDS`; `/healthz` returns 200.
3. Docker (needs a machine with Docker): build, run, health `healthy`, `id` shows uid 10001, `docker compose up`.
4. Real inverter (manual): series appear, `e_total` matches SolarGo, recovery after power cycle/night.

## Risks and assumptions

- Sensor ids vary by family; counter/gauge rule is name-based. Verify on a real inverter and add an override map if needed.
- UDP contention with other clients (Home Assistant, SolarGo LAN mode) causes timeouts.
- Docker steps are untested locally (no `docker` binary).
- Transport-follows-port assumption should be confirmed in goodwe source.

## Implementation notes (deviations found while building)

- **`asyncio.wait_for` cannot enforce the scrape timeout.** goodwe's UDP protocol catches `CancelledError`
  (it uses cancellation as its own per-request timeout) and retries, so `wait_for` blocked for about 21 s
  against an unreachable host despite an 8 s limit. `client.py` instead runs the read as a task, waits with
  `asyncio.wait(timeout=...)`, abandons it on overrun, and fails fast while an abandoned read is still running.
- **Family name:** goodwe's code matches `NS`, not the documented `D-NS`; config accepts both and maps to `NS`.
- **Transport:** confirmed in `goodwe/inverter.py`: port 8899 selects UDP, any other port selects TCP.
- **Content type:** `prometheus_client` 0.26's `CONTENT_TYPE_LATEST` says `version=1.0.0`, but `generate_latest`
  emits the classic format, so the app sets `text/plain; version=0.0.4` explicitly.
- Docker was not available locally; image build and healthcheck are unverified here.
