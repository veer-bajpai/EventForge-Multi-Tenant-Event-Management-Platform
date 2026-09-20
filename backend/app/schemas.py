import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from .models import Role


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---- auth ----
class RegisterIn(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=8, max_length=128)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class RefreshIn(BaseModel):
    refresh_token: str


class TokenOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class UserOut(ORM):
    id: int
    email: str
    full_name: str


# ---- orgs ----
class OrgCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    slug: str | None = Field(default=None, max_length=60)

    @field_validator("slug")
    @classmethod
    def _slug(cls, v):
        if v is None:
            return v
        v = v.lower().strip()
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", v):
            raise ValueError("Slug may contain lowercase letters, numbers and single hyphens")
        return v


class OrgOut(ORM):
    id: int
    name: str
    slug: str


class OrgWithRole(OrgOut):
    role: Role


class MemberOut(BaseModel):
    user_id: int
    email: str
    full_name: str
    role: Role


class MemberAdd(BaseModel):
    email: EmailStr
    role: Role = Role.staff


class MemberUpdate(BaseModel):
    role: Role


# ---- events ----
class TicketTypeIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    price_cents: int = Field(ge=0, le=10_000_000)
    capacity: int = Field(ge=1, le=1_000_000)


class TicketTypeOut(ORM):
    id: int
    name: str
    price_cents: int
    capacity: int
    sold: int


class EventIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = ""
    venue: str = ""
    starts_at: datetime
    ends_at: datetime | None = None


class EventUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    venue: str | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    status: str | None = Field(default=None, pattern="^(draft|published|cancelled)$")


class EventOut(ORM):
    id: int
    title: str
    description: str
    venue: str
    starts_at: datetime
    ends_at: datetime | None
    status: str
    ticket_types: list[TicketTypeOut] = []


# ---- registrations ----
class RegisterAttendeeIn(BaseModel):
    ticket_type_id: int
    attendee_name: str = Field(min_length=1, max_length=120)
    attendee_email: EmailStr
    quantity: int = Field(default=1, ge=1, le=10)


class RegistrationOut(ORM):
    id: int
    code: str
    event_id: int
    ticket_type_id: int
    attendee_name: str
    attendee_email: str
    quantity: int
    total_cents: int
    status: str
    checked_in_at: datetime | None
    created_at: datetime


class CheckInIn(BaseModel):
    code: str


class AuditOut(ORM):
    id: int
    actor_label: str
    action: str
    entity: str
    entity_id: int | None
    meta: dict
    created_at: datetime
