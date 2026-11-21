# Three-minute demo

Start the database and application using the README. Open http://127.0.0.1:8000/docs. Use a long interval such as 3600 seconds to make manual checks predictable. The scheduler may run the first check immediately.

1. **0:00–0:45** Run GET /health, then create an endpoint with POST /endpoints using `{"name":"Example","url":"https://example.com/","interval_seconds":3600}`. Keep the ID.
2. **0:45–1:20** Run POST /endpoints/{endpoint_id}/checks. Show the status code, response time, and success flag. Open GET /endpoints/{endpoint_id}/checks and GET /summary.
3. **1:20–2:20** Add a second endpoint with `{"name":"Intentional 404","url":"https://example.com/monitor-demo-missing","interval_seconds":3600}`. Confirm that the target returns a non-2xx response, use the manual check action until there are at least three consecutive failures, and open GET /alerts with `active_only=true`. Run another failed check and show that the active alert count stays the same.
4. **2:20–3:00** Explain that a 2xx response on the **same URL** resolves the alert. The automated lifecycle test demonstrates this transition deterministically. To demonstrate it live, monitor a public URL you control and change its response to 200. Editing a monitored URL closes the prior alert as a configuration change.

The sample targets require public DNS and internet access. A reachable public URL you control can replace either sample. Automated tests use mocked HTTP responses.
