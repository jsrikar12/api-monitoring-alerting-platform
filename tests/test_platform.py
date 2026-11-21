from datetime import timedelta
import socket

import httpx
import pytest

from models import Endpoint, utc_now
from monitoring import probe, run_due_checks

PUBLIC_URL = "https://8.8.8.8/"


def add(client, **changes):
    response = client.post("/endpoints", json={
        "name": "Example", "url": PUBLIC_URL, **changes,
    })
    assert response.status_code == 201, response.text
    return response.json()


def test_crud(api):
    client, outcomes, _, _ = api
    assert client.get("/health").json() == {"status": "ok", "database": "connected"}
    assert client.get("/docs").status_code == 200
    item = add(client)
    assert item["interval_seconds"] == 60 and item["active"] is True
    path = f"/endpoints/{item['id']}"
    assert client.get("/endpoints").json() == [item]
    assert client.get(path).json() == item
    assert client.get(f"{path}/status").json()["status"] == "pending"
    outcomes.append(200)
    assert client.post(f"{path}/checks").status_code == 201
    updated = client.patch(path, json={"name": "Renamed", "interval_seconds": 15, "active": False})
    assert updated.status_code == 200
    assert updated.json()["name"] == "Renamed"
    assert updated.json()["interval_seconds"] == 15
    assert client.get(f"{path}/status").json()["status"] == "inactive"
    assert client.post(f"{path}/checks").status_code == 409
    assert client.delete(path).status_code == 204
    assert client.get(path).status_code == 404
    assert client.get("/endpoints").json() == []


@pytest.mark.parametrize("url", [
    "file:///etc/passwd", "/relative", "http://localhost", "http://loop.internal",
    "http://127.0.0.1", "http://10.0.0.1", "http://169.254.169.254/",
    "http://100.100.100.200/", "http://168.63.129.16/", "http://[::1]", "http://[fd00::1]",
    "http://[::ffff:127.0.0.1]", "http://224.0.0.1/",
    "http://user:password@example.com", "https://example.com:8080/", "https://example.com/#anchor",
])
def test_unsafe_urls(api, url):
    client = api[0]
    assert client.post("/endpoints", json={"name": "Unsafe", "url": url}).status_code == 422


@pytest.mark.parametrize("field,value", [
    ("name", " "), ("url", None), ("interval_seconds", 0), ("interval_seconds", 86401),
    ("interval_seconds", "60"), ("interval_seconds", True), ("active", "false"), ("other", "field"),
])
def test_invalid_inputs(api, field, value):
    client = api[0]
    item = add(client)
    assert client.post("/endpoints", json={
        "name": "test", "url": PUBLIC_URL, field: value,
    }).status_code == 422
    assert client.patch(f"/endpoints/{item['id']}", json={field: value}).status_code == 422


def test_redirect_is_not_followed_and_duration_is_recorded(api, monkeypatch):
    client, outcomes, requests, _ = api
    times = iter([10.0, 10.125])
    monkeypatch.setattr("monitoring.perf_counter", lambda: next(times))
    outcomes.append(302)
    endpoint = add(client)
    path = f"/endpoints/{endpoint['id']}/checks"
    response = client.post(path)
    assert response.status_code == 201
    check = response.json()
    assert check["status_code"] == 302 and check["success"] is False
    assert check["error"] == "HTTP 302"
    assert check["response_time_ms"] == 125.0
    assert len(requests) == 1
    assert client.get(path).json() == [check]


@pytest.mark.parametrize("addresses", [["127.0.0.1"], ["8.8.8.8", "10.0.0.1"]])
def test_dns_rejects_unsafe_addresses(monkeypatch, addresses):
    def resolve(*args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443))
                for address in addresses]

    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    result = probe("https://example.com/")
    assert not result.success
    assert result.status_code is None
    assert "public IP" in result.error


@pytest.mark.parametrize("address", ["8.8.8.8", "2606:4700:4700::1111"])
def test_probe_uses_validated_ip_and_preserves_tls_identity(monkeypatch, address):
    monkeypatch.setattr("monitoring.resolve_public_ip", lambda url: address)

    def handler(request):
        assert request.url.host == address
        assert request.headers["Host"] == "example.com"
        assert request.extensions["sni_hostname"] == "example.com"
        return httpx.Response(204)

    assert probe("https://example.com/", transport=httpx.MockTransport(handler)).success


def test_alert_lifecycle_history_and_summary(api):
    client, outcomes, _, _ = api
    endpoint = add(client)
    add(client, name="Inactive", active=False)
    add(client, name="Pending")
    path = f"/endpoints/{endpoint['id']}"
    check_path = f"{path}/checks"
    outcomes.extend([500, 200, 503, httpx.ConnectError, httpx.ReadTimeout, 500, 204, 500, 500, 500])
    for success in (False, True, False, False):
        assert client.post(check_path).json()["success"] is success
    assert client.get("/alerts").json() == []
    timeout = client.post(check_path).json()
    assert timeout["status_code"] is None and timeout["error"] == "HTTP request timed out"
    client.post(check_path)
    alerts = client.get("/alerts?active_only=true").json()
    assert len(alerts) == 1
    assert alerts[0]["resolved_at"] is None
    assert client.get(f"{path}/status").json()["consecutive_failures"] == 4
    assert client.get("/summary").json() == dict(
        total_endpoints=3, healthy_endpoints=0, unhealthy_endpoints=1, active_alerts=1,
    )

    recovery = client.post(check_path).json()
    history = client.get(f"{check_path}?limit=2").json()
    assert history[0] == recovery
    assert [check["status_code"] for check in history] == [204, 500]
    assert client.get("/alerts?active_only=true").json() == []
    assert client.get("/alerts").json()[0]["resolution"] == "recovered"
    assert client.get("/summary").json() == dict(
        total_endpoints=3, healthy_endpoints=1, unhealthy_endpoints=0, active_alerts=0,
    )

    for _ in range(3):
        client.post(check_path)
    assert len(client.get("/alerts").json()) == 2
    client.patch(path, json={"url": "https://1.1.1.1/"})
    assert client.get(f"{path}/status").json()["status"] == "pending"
    assert client.get("/alerts").json()[0]["resolution"] == "configuration_changed"
    assert client.delete(path).status_code == 204
    assert client.get("/alerts").json() == []


def test_due_checks_respect_interval_and_inactive_flag(api):
    client, outcomes, requests, sessions = api
    selected = add(client, interval_seconds=300)
    add(client, name="Inactive", active=False)
    outcomes.extend([200, 200])

    run_due_checks(sessions, client.app.state.probe)
    run_due_checks(sessions, client.app.state.probe)
    assert len(requests) == 1
    with sessions.begin() as session:
        endpoint = session.get(Endpoint, selected["id"])
        assert endpoint.next_check_at.replace(tzinfo=None) > utc_now().replace(tzinfo=None)
        endpoint.next_check_at = utc_now() - timedelta(seconds=1)
    run_due_checks(sessions, client.app.state.probe)
    assert len(requests) == 2
    history = client.get(f"/endpoints/{selected['id']}/checks").json()
    assert len(history) == 2
