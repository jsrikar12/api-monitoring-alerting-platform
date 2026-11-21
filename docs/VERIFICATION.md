# Verification

Verified on 22 November 2026 in Windows using Python 3.12.4, PostgreSQL 17.10, and Playwright Chromium 159.

## Commands executed

The project was installed into a workspace virtual environment using `python -m pip --python work/venv/Scripts/python.exe install -r outputs/api-monitoring-alerting-platform/requirements.txt`. The commands below use the virtual environment's Python on PATH and omit workspace-specific absolute paths.

| Command | Result |
| --- | --- |
| `docker compose --env-file .env.example config --quiet` | Compose configuration passed validation. |
| `docker info --format '{{.ServerVersion}}'` | Docker Desktop's Linux engine pipe was unavailable. |
| `initdb -D work/pgdata -U monitor -A trust -E UTF8` | Initialized an isolated local-only PostgreSQL cluster. |
| `pg_ctl -D work/pgdata -l work/postgres.log -o "-p 55432 -h 127.0.0.1" -w start` | Started PostgreSQL 17.10 on loopback. |
| `createdb -h 127.0.0.1 -p 55432 -U monitor monitor` | Created the integration database. |
| `python -m pytest -q --basetemp=<workspace>/test-sqlite-final` | **32 passed**, 1 Starlette TestClient deprecation warning, 1.88 seconds. |
| `python -m pytest -q --basetemp=<workspace>/test-pg` with `TEST_DATABASE_URL=postgresql+psycopg://monitor@127.0.0.1:55432/monitor` | **32 passed**, 1 Starlette TestClient deprecation warning, 7.92 seconds. |
| `python -m playwright install chromium` | Installed Chromium for screenshot capture. |
| `python -m uvicorn live_demo:app_factory --factory --host 127.0.0.1 --port 58000` | Started the application through a temporary verification harness. Playwright exercised real Swagger operations. |
| `python -m uvicorn main:app --host 127.0.0.1 --port 58001` | Verified the documented app entry point and persistent data after restarting PostgreSQL. |
| `pg_ctl -D work/pgdata -m fast -w stop` | Stopped the temporary PostgreSQL instance after verification. |

The PostgreSQL run initially caught inconsistent timezone formatting between freshly written rows and rows read back from PostgreSQL. API timestamps are now normalized to UTC. The full suite passed after that correction.

## Live behavior observed

1. `GET /health` reported a connected database. Chromium rendered Swagger at `/docs`. Swagger returned HTTP 201 for endpoint creation and HTTP 200 for history and alerts.
2. The real scheduler sent an HTTPS GET to `https://example.com/`. PostgreSQL stored a 200 response and a measured elapsed time of **571.05 ms**.
3. A second endpoint used a temporary test transport producing consecutive 503 responses and then 204 on the same URL. Repeated failed checks left exactly one open alert. The next successful check resolved it with reason `recovered`.
4. After restarting Uvicorn, the created endpoint and the resolved alert were read back from PostgreSQL. The summary returned two healthy endpoints, zero unhealthy endpoints, and zero active alerts.
5. After stopping and restarting PostgreSQL, the standard `main:app` entry point returned the same summary. Three real 404 responses from `https://example.com/monitor-demo-missing` opened one alert.

The four PNGs in [screenshots](screenshots/) were captured from the running Swagger UI. The monitor results show the real public probe. The alert screenshot shows the alert persisted by the application using controlled upstream responses. The application source uses real HTTPX transport by default. Docker Compose runtime was unavailable, so the live verification used native PostgreSQL.
