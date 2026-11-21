from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from database import get_db
from models import Alert, Check, Endpoint, utc_now
from monitoring import check_endpoint, close_alert, lock_endpoint
from schemas import (
    AlertOut, CheckOut, EndpointCreate, EndpointOut, EndpointStatus, EndpointUpdate, Summary,
)

router = APIRouter()
DB = Annotated[Session, Depends(get_db)]
Limit = Annotated[int, Query(ge=1, le=200)]


def require_endpoint(db, endpoint_id, *, lock=False):
    endpoint = lock_endpoint(db, endpoint_id) if lock else db.get(Endpoint, endpoint_id)
    if endpoint is None:
        raise HTTPException(404, "Endpoint not found")
    return endpoint


@router.get("/health", tags=["Service"])
def health(db: DB):
    db.execute(text("SELECT 1"))
    return {"status": "ok", "database": "connected"}


@router.get("/summary", tags=["Service"], response_model=Summary)
def summary(db: DB):
    total, healthy, unhealthy = db.execute(select(
        func.count(Endpoint.id),
        func.count(Endpoint.id).filter(Endpoint.active.is_(True), Endpoint.last_success.is_(True)),
        func.count(Endpoint.id).filter(Endpoint.active.is_(True), Endpoint.last_success.is_(False)),
    )).one()
    active_alerts = db.scalar(select(func.count(Alert.id)).where(Alert.resolved_at.is_(None)))
    return dict(total_endpoints=total, healthy_endpoints=healthy,
                unhealthy_endpoints=unhealthy, active_alerts=active_alerts)


@router.post("/endpoints", tags=["Endpoints"], response_model=EndpointOut, status_code=201)
def create_endpoint(body: EndpointCreate, db: DB):
    endpoint = Endpoint(**body.model_dump())
    db.add(endpoint)
    db.commit()
    return endpoint


@router.get("/endpoints", tags=["Endpoints"], response_model=list[EndpointOut])
def list_endpoints(db: DB, limit: Limit = 100, offset: Annotated[int, Query(ge=0)] = 0):
    return db.scalars(select(Endpoint).order_by(Endpoint.id).offset(offset).limit(limit)).all()


@router.get("/endpoints/{endpoint_id}", tags=["Endpoints"], response_model=EndpointOut)
def get_endpoint(endpoint_id: int, db: DB):
    return require_endpoint(db, endpoint_id)


@router.patch("/endpoints/{endpoint_id}", tags=["Endpoints"], response_model=EndpointOut)
def update_endpoint(endpoint_id: int, body: EndpointUpdate, db: DB):
    endpoint = require_endpoint(db, endpoint_id, lock=True)
    values = body.model_dump(exclude_unset=True)
    url_changed = values.get("url", endpoint.url) != endpoint.url
    active_changed = values.get("active", endpoint.active) != endpoint.active
    interval_changed = values.get("interval_seconds", endpoint.interval_seconds) != endpoint.interval_seconds
    for field, value in values.items():
        setattr(endpoint, field, value)

    now = utc_now()
    if url_changed or active_changed:
        reason = "configuration_changed" if endpoint.active else "disabled"
        close_alert(db, endpoint_id, now, reason)
        endpoint.last_checked_at = None
        endpoint.last_success = None
        endpoint.consecutive_failures = 0
    if url_changed or active_changed or interval_changed:
        endpoint.next_check_at = now
    if values:
        endpoint.updated_at = now
    db.commit()
    return endpoint


@router.delete("/endpoints/{endpoint_id}", tags=["Endpoints"], status_code=204)
def delete_endpoint(endpoint_id: int, db: DB):
    db.delete(require_endpoint(db, endpoint_id, lock=True))
    db.commit()
    return Response(status_code=204)


@router.post("/endpoints/{endpoint_id}/checks", tags=["Monitoring"],
             response_model=CheckOut, status_code=201)
def run_check(endpoint_id: int, request: Request, db: DB):
    endpoint = require_endpoint(db, endpoint_id, lock=True)
    if not endpoint.active:
        raise HTTPException(409, "Endpoint is inactive")
    return check_endpoint(db, endpoint, request.app.state.probe)


@router.get("/endpoints/{endpoint_id}/checks", tags=["Monitoring"], response_model=list[CheckOut])
def check_history(endpoint_id: int, db: DB, limit: Limit = 50):
    require_endpoint(db, endpoint_id)
    return db.scalars(select(Check).where(Check.endpoint_id == endpoint_id)
                      .order_by(Check.id.desc()).limit(limit)).all()


@router.get("/endpoints/{endpoint_id}/status", tags=["Monitoring"], response_model=EndpointStatus)
def endpoint_status(endpoint_id: int, db: DB):
    endpoint = require_endpoint(db, endpoint_id)
    status = {True: "healthy", False: "unhealthy", None: "pending"}[endpoint.last_success]
    return dict(endpoint_id=endpoint_id, status=status if endpoint.active else "inactive",
                last_checked_at=endpoint.last_checked_at,
                consecutive_failures=endpoint.consecutive_failures)


@router.get("/alerts", tags=["Alerts"], response_model=list[AlertOut])
def alerts(db: DB, endpoint_id: int | None = None, active_only: bool = False, limit: Limit = 50):
    query = select(Alert)
    if endpoint_id is not None:
        query = query.where(Alert.endpoint_id == endpoint_id)
    if active_only:
        query = query.where(Alert.resolved_at.is_(None))
    return db.scalars(query.order_by(Alert.id.desc()).limit(limit)).all()
