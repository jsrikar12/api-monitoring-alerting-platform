import logging
import socket
from dataclasses import dataclass
from datetime import timedelta
from time import perf_counter

import httpx
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from models import Alert, Check, Endpoint, as_utc, utc_now
from url_safety import parse_url, resolve_public_ip

logger = logging.getLogger(__name__)
FAILURE_THRESHOLD = 3


@dataclass
class ProbeResult:
    status_code: int | None
    response_time_ms: float
    success: bool
    error: str | None


def probe(url, *, transport=None):
    start = perf_counter()
    status = None
    error = None
    try:
        target = parse_url(url)
        address = resolve_public_ip(target)
        # Connect directly to the validated address while retaining Host and TLS identity.
        destination = target.copy_with(host=f"[{address}]" if ":" in address else address)
        hostname = target.raw_host.decode("ascii").strip("[]").rstrip(".")
        with httpx.Client(timeout=5, follow_redirects=False, trust_env=False,
                          transport=transport) as client:
            with client.stream("GET", destination, headers={"Host": target.netloc.decode("ascii")},
                               extensions={"sni_hostname": hostname}) as response:
                status = response.status_code
        if not 200 <= status < 300:
            error = f"HTTP {status}"
    except ValueError as exc:
        error = str(exc)
    except socket.gaierror:
        error = "DNS resolution failed"
    except httpx.TimeoutException:
        error = "HTTP request timed out"
    except httpx.RequestError as exc:
        error = f"HTTP request failed ({type(exc).__name__})"

    return ProbeResult(status, round((perf_counter() - start) * 1000, 3), error is None, error)


def close_alert(session, endpoint_id, timestamp, reason):
    alert = open_alert(session, endpoint_id)
    if alert:
        alert.resolved_at = timestamp
        alert.resolution = reason


def open_alert(session, endpoint_id):
    return session.scalar(select(Alert).where(
        Alert.endpoint_id == endpoint_id, Alert.resolved_at.is_(None),
    ))


def lock_endpoint(session, endpoint_id):
    return session.scalar(select(Endpoint).where(Endpoint.id == endpoint_id).with_for_update())


def check_endpoint(session, endpoint, probe_fn):
    started_at = utc_now()
    result = probe_fn(endpoint.url)
    check = Check(
        endpoint_id=endpoint.id, checked_at=started_at, status_code=result.status_code,
        response_time_ms=result.response_time_ms, success=result.success, error=result.error,
    )
    session.add(check)

    endpoint.last_checked_at = started_at
    endpoint.last_success = result.success
    endpoint.next_check_at = utc_now() + timedelta(seconds=endpoint.interval_seconds)
    if result.success:
        endpoint.consecutive_failures = 0
        close_alert(session, endpoint.id, started_at, "recovered")
    else:
        endpoint.consecutive_failures += 1
        if endpoint.consecutive_failures == FAILURE_THRESHOLD:
            session.add(Alert(endpoint_id=endpoint.id, opened_at=started_at))
    session.commit()
    return check


def run_due_checks(session_factory, probe_fn):
    try:
        with session_factory() as session:
            endpoint_ids = session.scalars(select(Endpoint.id).where(
                Endpoint.active.is_(True), Endpoint.next_check_at <= utc_now(),
            ).order_by(Endpoint.next_check_at)).all()
    except SQLAlchemyError:
        logger.exception("Could not read scheduled checks")
        return

    for endpoint_id in endpoint_ids:
        try:
            with session_factory() as session:
                endpoint = lock_endpoint(session, endpoint_id)
                if endpoint and endpoint.active and as_utc(endpoint.next_check_at) <= utc_now():
                    check_endpoint(session, endpoint, probe_fn)
        except SQLAlchemyError:
            logger.exception("Could not save scheduled check for endpoint %s", endpoint_id)
