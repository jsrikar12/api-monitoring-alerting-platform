# API Monitoring & Alerting Platform

A Python backend that checks HTTP endpoints on a schedule, records availability and response time in PostgreSQL, and opens an alert after three consecutive failures. Explore the APIs through Swagger UI at `/docs`.

## Problem

An API can stop responding or start returning errors between manual checks. This platform records each observation so you can see when a failure streak began and when the service recovered.

## Features

- Create, list, update, pause, and delete endpoint configurations.
- Run scheduled checks at a per-endpoint interval or trigger a manual check in Swagger.
- Inspect HTTP status, elapsed time, timestamps, errors, current health, and alert history.
- Track a single active alert per endpoint and resolve it automatically after recovery.
- View aggregate counts for monitored endpoints, healthy endpoints, unhealthy endpoints, and open alerts.

## Stack

Python 3.11+, FastAPI, Pydantic, SQLAlchemy, psycopg, PostgreSQL, HTTPX, APScheduler, Uvicorn, pytest, and Docker Compose.

## Architecture

```mermaid
flowchart LR
    Swagger[Swagger UI] --> API[FastAPI routes]
    API --> Store[(PostgreSQL)]
    API -->|Manual check| Probe[Monitoring worker logic]
    Scheduler[APScheduler] -->|Due checks| Probe
    Probe -->|Validated HTTP GET| Target[Public API]
    Probe -->|Check and alert transaction| Store
```

| Path | Purpose |
| --- | --- |
| `main.py` | App and scheduler lifespan |
| `database.py`, `models.py` | Database setup and tables |
| `routes.py`, `schemas.py` | REST API and validation |
| `monitoring.py`, `url_safety.py` | HTTP checks, destination validation, and alert lifecycle |
| `requirements.txt`, `docker-compose.yml`, `.env.example` | Local setup |
| `tests/` | Offline HTTP tests with isolated storage |
| `docs/` | Architecture, interview guide, demo, and verification |

## Local setup

Install Python 3.11 or newer, Git, and Docker with the Compose plugin. Run the following in the project directory.

**PowerShell**

```powershell
Copy-Item .env.example .env
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
docker compose up -d --wait
.\.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000
```

**macOS or Linux**

```bash
cp .env.example .env
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
docker compose up -d --wait
.venv/bin/python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/docs`. GET `/health` should report `{"status":"ok","database":"connected"}`. The app creates tables on startup. For an existing PostgreSQL installation, create a database and a role with schema creation privileges, set `DATABASE_URL`, and skip Compose. Stop Compose with `docker compose down`. Its named volume preserves data across restarts.

| Variable | Default | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | `postgresql+psycopg://monitor:monitor-dev@127.0.0.1:5432/monitor` | SQLAlchemy database URL. URL-encode special characters in credentials. |
| `ENABLE_SCHEDULER` | `true` | Set to `false` for manual checks only. |
| `POSTGRES_USER` | `monitor` | Compose database role |
| `POSTGRES_PASSWORD` | `monitor-dev` | Compose development password |
| `POSTGRES_DB` | `monitor` | Compose database name |
| `POSTGRES_PORT` | `5432` | PostgreSQL host port bound to loopback |

When changing Compose parameters, update `DATABASE_URL` too. Use one Uvicorn worker. For reload-based editing, set `ENABLE_SCHEDULER=false` if you only need manual checks.

## REST API

| Method and path | Result |
| --- | --- |
| GET `/health` | Service and database health |
| GET `/docs` | Swagger UI |
| POST `/endpoints` | Create a configuration (201) |
| GET `/endpoints?limit=100&offset=0` | List configurations |
| GET `/endpoints/{id}` | Retrieve one configuration |
| PATCH `/endpoints/{id}` | Update provided configuration fields |
| DELETE `/endpoints/{id}` | Delete the endpoint, its checks, and its alerts (204) |
| POST `/endpoints/{id}/checks` | Run a check immediately (201, or 409 if inactive) |
| GET `/endpoints/{id}/checks?limit=50` | Check history, newest first |
| GET `/endpoints/{id}/status` | `pending`, `healthy`, `unhealthy`, or `inactive` |
| GET `/alerts?endpoint_id=1&active_only=true&limit=50` | Alert episodes, newest first. All filters are optional. |
| GET `/summary` | Total configurations, healthy and unhealthy active endpoints, and unresolved alerts |

Example POST `/endpoints` request, also usable in Swagger:

```json
{"name":"Example API","url":"https://example.com/","interval_seconds":60,"active":true}
```

The response includes `id`, the configuration, `created_at`, and `updated_at`. A PATCH body such as `{"active":false}` pauses scheduled and manual checks. Check history includes `id`, `endpoint_id`, `checked_at`, `status_code`, `response_time_ms`, `success`, and `error`. For example, a new endpoint's status and the summary for that single pending endpoint have these shapes:

```json
{"endpoint_id":1,"status":"pending","last_checked_at":null,"consecutive_failures":0}
```

```json
{"total_endpoints":1,"healthy_endpoints":0,"unhealthy_endpoints":0,"active_alerts":0}
```

Missing endpoints return 404, validation failures return 422, and database request errors return 503. Endpoint intervals range from 1 to 86,400 seconds. Check and alert history use a bounded `limit` of up to 200. The status and summary reflect the last observation for each active target. Pending and inactive configurations count toward the total only.

## Monitoring and alert rules

Active endpoints are due immediately on creation or reactivation. Each check schedules the next one after the configured interval. A 2xx marks success. Other status codes, unsafe destinations, and HTTP or DNS failures record failures. HTTPX uses a five-second network timeout and reads response headers without downloading the body. URL checks restrict the scheme and port and reject credentials, local hosts, private or reserved IPs, and unsafe DNS answers. Connections use the vetted IP and retain the original Host and TLS identity. The probe never follows redirects.

The third consecutive failure opens an alert. A subsequent success resolves it and clears the failure streak. Disabling an endpoint or changing its URL closes any active alert with the corresponding reason. Alerts are visible in the REST API.

## Testing

Run from the project directory using the virtual environment's Python:

```text
python -m pytest -q
```

The suite uses mocked HTTP responses and an isolated SQLite file for each test by default. To run against PostgreSQL, set `TEST_DATABASE_URL` to an SQLAlchemy psycopg URL for a PostgreSQL database where the user can create schemas. The suite creates and removes a uniquely named schema per test.

## Demo and documentation

Try `https://example.com/` and `https://example.com/monitor-demo-missing`. See the [demo walkthrough](docs/DEMO.md), [architecture notes](docs/ARCHITECTURE.md), [interview guide](docs/INTERVIEW_GUIDE.md), and [verification record](docs/VERIFICATION.md).

### Screenshots

![Swagger UI overview](docs/screenshots/swagger-overview.png)

![Creating an endpoint in Swagger](docs/screenshots/endpoint-creation.png)

![History showing a real public HTTPS check](docs/screenshots/monitoring-results.png)

![An active alert generated with a controlled upstream response](docs/screenshots/alerts.png)

## Limitations and future improvements

This is a single-worker, local project with no authentication. Keep it on loopback. Scheduled checks run sequentially, so a slow target can delay other checks. OS DNS resolution has its own timeout. The worker uses the first vetted address and does not retry alternate addresses. Swagger assets are loaded from a CDN. Checks and alerts are retained until the endpoint is deleted. Possible extensions include schema migrations, history retention, and bounded concurrency.
