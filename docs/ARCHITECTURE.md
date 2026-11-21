# Architecture

- `main.py` creates the FastAPI application, establishes the database schema at startup, handles SQLAlchemy errors, and starts/stops one APScheduler instance in the application lifespan.
- `database.py` loads configuration and creates the SQLAlchemy engine and sessions. `models.py` declares the endpoint, check, and alert tables. PostgreSQL enforces foreign keys and a partial unique index for each endpoint's unresolved alert.
- `schemas.py` validates request bodies and defines the response models. `routes.py` owns HTTP status codes, CRUD, status and summary queries, and the manual check entry point.
- `url_safety.py` validates destinations and checks all DNS answers before any connection. `monitoring.py` pins the connection to a validated IP, preserves the original Host and TLS identity, and performs a GET without following redirects.
- `tests/` drives the API through TestClient and injects HTTPX MockTransport. The suite can use SQLite files or isolated PostgreSQL schemas.

A scheduler tick finds active, due endpoint IDs. The scheduler and manual endpoint both lock the corresponding PostgreSQL endpoint row. The scheduler rechecks the due time and active flag after acquiring the lock. The transaction stores the probe result, latest status, next due time, failure streak, and any alert update together. A check is due again one configured interval after the previous check finishes. APScheduler coalesces missed ticks and skips overlapping runs. The endpoint row lock coordinates manual checks, edits, and scheduler checks, while the partial index provides an independent uniqueness safeguard.

A successful check resets the streak and closes an open alert. The third consecutive failure opens one. Later failures keep that alert open until recovery, disabling, or a target URL change. Disabling or changing the URL also clears the cached state. The service keeps historical rows until their parent endpoint is deleted.

A 2xx header marks success. Any other HTTP status, a refused destination, or a transport failure is recorded as a failed check. Latency covers DNS and the time to receive response headers and close the response stream. The worker uses a fresh HTTP client for each probe and leaves the response body unread.

This project runs in one Uvicorn worker. Endpoint checks run sequentially on a scheduler worker thread, with one transaction per endpoint. The resolver uses the OS DNS timeout, and HTTPX applies a five-second timeout to network operations. Alerts are stored and exposed through the API.
