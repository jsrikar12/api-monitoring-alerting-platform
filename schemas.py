from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, AfterValidator, model_validator

from models import as_utc
from url_safety import parse_url


def validate_url(value):
    parse_url(value)
    return value


Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
URL = Annotated[str, StringConstraints(strip_whitespace=True, max_length=2048),
                AfterValidator(validate_url)]
Interval = Annotated[int, Field(strict=True, ge=1, le=86400)]
Active = Annotated[bool, Field(strict=True)]
Timestamp = Annotated[datetime, AfterValidator(as_utc)]


class EndpointCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name
    url: URL
    interval_seconds: Interval = 60
    active: Active = True


class EndpointUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name | None = None
    url: URL | None = None
    interval_seconds: Interval | None = None
    active: Active | None = None

    @model_validator(mode="after")
    def reject_null_fields(self):
        if any(getattr(self, field) is None for field in self.model_fields_set):
            raise ValueError("Omit fields you do not want to change")
        return self


class EndpointOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    url: str
    interval_seconds: int
    active: bool
    created_at: Timestamp
    updated_at: Timestamp


class CheckOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    endpoint_id: int
    checked_at: Timestamp
    status_code: int | None
    response_time_ms: float
    success: bool
    error: str | None


class AlertOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    endpoint_id: int
    opened_at: Timestamp
    resolved_at: Timestamp | None
    resolution: str | None


class EndpointStatus(BaseModel):
    endpoint_id: int
    status: str
    last_checked_at: Timestamp | None
    consecutive_failures: int


class Summary(BaseModel):
    total_endpoints: int
    healthy_endpoints: int
    unhealthy_endpoints: int
    active_alerts: int
