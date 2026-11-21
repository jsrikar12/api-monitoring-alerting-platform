# Interview guide

1. **What problem does the project solve?** It tracks whether HTTP endpoints are available and records outages and recoveries.
2. **Why FastAPI?** It validates request data, serializes typed responses, and produces interactive OpenAPI documentation.
3. **Why PostgreSQL?** It provides durable storage, transactions, row locks, foreign keys, and partial unique indexes.
4. **How are the data organized?** An endpoint has many check results and many alert episodes. Each child references its endpoint.
5. **How are checks scheduled?** APScheduler runs a one-second tick. PostgreSQL stores each endpoint's next due time.
6. **What counts as a success?** HTTP 200 through 299. Other responses and transport or destination errors count as failures.
7. **How do you measure latency?** A monotonic performance counter measures elapsed time in milliseconds from probe start through response-header receipt and stream close.
8. **Why require three consecutive failures?** It limits alerts from transient failures. A success clears the streak.
9. **How do you prevent duplicate open alerts?** A row lock serializes each endpoint's updates and a partial unique index permits one unresolved alert per endpoint.
10. **How is recovery stored?** The first subsequent successful check timestamps the open alert's resolution and records the reason.
11. **How do you reduce SSRF risk?** Validate URLs, reject dangerous DNS answers, connect to a vetted IP, preserve the original TLS identity, disable proxies, and decline redirects.
12. **How do you test without public internet?** Use FastAPI TestClient, HTTPX MockTransport, controlled DNS results, and isolated databases.
13. **What happens on a database failure?** API database exceptions return HTTP 503. The scheduler logs SQLAlchemy failures and a rolled-back check remains eligible for retry.
14. **What is the difference between current status and alert state?** Status reflects the latest check for an active endpoint. An alert opens only after three failures.
15. **What would you improve next?** Add migrations, expiration for old history, and bounded concurrent checks if the number of endpoints grows.
