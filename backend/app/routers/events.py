from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from .. import audit
from ..cache import cache, public_events_key
from ..database import get_db
from ..deps import OrgContext, org_context, require_role
from ..models import Event, Registration, Role, TicketType
from ..schemas import (CheckInIn, EventIn, EventOut, EventUpdate, RegistrationOut,
                       TicketTypeIn, TicketTypeOut)
from ..models import utcnow

router = APIRouter(prefix="/api/orgs/{org_id}", tags=["events"])


def _event(db: Session, org_id: int, event_id: int) -> Event:
    # Tenant scoping: org_id is part of every lookup, so IDs from other tenants simply 404.
    ev = db.scalar(select(Event).options(selectinload(Event.ticket_types))
                   .where(Event.id == event_id, Event.org_id == org_id))
    if not ev:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Event not found")
    return ev


@router.get("/events", response_model=list[EventOut])
def list_events(ctx: OrgContext = Depends(org_context), db: Session = Depends(get_db)):
    return db.scalars(select(Event).options(selectinload(Event.ticket_types))
                      .where(Event.org_id == ctx.org.id).order_by(Event.starts_at.desc())).all()


@router.post("/events", response_model=EventOut, status_code=201)
def create_event(body: EventIn, ctx: OrgContext = Depends(require_role(Role.admin)),
                 db: Session = Depends(get_db)):
    if body.ends_at and body.ends_at <= body.starts_at:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "End time must be after start time")
    ev = Event(org_id=ctx.org.id, created_by=ctx.user.id, **body.model_dump())
    db.add(ev)
    db.flush()
    audit.record(db, ctx.org.id, "event.created", "event", ev.id, actor=ctx.user, title=ev.title)
    db.commit()
    db.refresh(ev)
    return ev


@router.get("/events/{event_id}", response_model=EventOut)
def get_event(event_id: int, ctx: OrgContext = Depends(org_context), db: Session = Depends(get_db)):
    return _event(db, ctx.org.id, event_id)


@router.patch("/events/{event_id}", response_model=EventOut)
def update_event(event_id: int, body: EventUpdate, ctx: OrgContext = Depends(require_role(Role.admin)),
                 db: Session = Depends(get_db)):
    ev = _event(db, ctx.org.id, event_id)
    changes = body.model_dump(exclude_unset=True)
    if changes.get("status") == "published" and not ev.ticket_types:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Add at least one ticket type before publishing")
    for k, v in changes.items():
        setattr(ev, k, v)
    if ev.ends_at and ev.ends_at <= ev.starts_at:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "End time must be after start time")
    audit.record(db, ctx.org.id, "event.updated", "event", ev.id, actor=ctx.user, fields=sorted(changes))
    db.commit()
    cache.delete(public_events_key(ctx.org.id))
    return ev


@router.delete("/events/{event_id}", status_code=204)
def delete_event(event_id: int, ctx: OrgContext = Depends(require_role(Role.admin)),
                 db: Session = Depends(get_db)):
    ev = _event(db, ctx.org.id, event_id)
    has_regs = db.scalar(select(func.count()).select_from(Registration)
                         .where(Registration.event_id == ev.id, Registration.status != "cancelled"))
    if has_regs:
        raise HTTPException(status.HTTP_409_CONFLICT, "Event has registrations. Cancel it instead of deleting.")
    audit.record(db, ctx.org.id, "event.deleted", "event", ev.id, actor=ctx.user, title=ev.title)
    db.delete(ev)
    db.commit()
    cache.delete(public_events_key(ctx.org.id))


@router.post("/events/{event_id}/ticket-types", response_model=TicketTypeOut, status_code=201)
def add_ticket_type(event_id: int, body: TicketTypeIn, ctx: OrgContext = Depends(require_role(Role.admin)),
                    db: Session = Depends(get_db)):
    ev = _event(db, ctx.org.id, event_id)
    tt = TicketType(org_id=ctx.org.id, event_id=ev.id, **body.model_dump())
    db.add(tt)
    db.flush()
    audit.record(db, ctx.org.id, "ticket_type.created", "ticket_type", tt.id, actor=ctx.user, name=tt.name)
    db.commit()
    cache.delete(public_events_key(ctx.org.id))
    return tt


@router.patch("/events/{event_id}/ticket-types/{tt_id}", response_model=TicketTypeOut)
def update_ticket_type(event_id: int, tt_id: int, body: TicketTypeIn,
                       ctx: OrgContext = Depends(require_role(Role.admin)), db: Session = Depends(get_db)):
    tt = db.scalar(select(TicketType).where(TicketType.id == tt_id, TicketType.event_id == event_id,
                                            TicketType.org_id == ctx.org.id))
    if not tt:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ticket type not found")
    if body.capacity < tt.sold:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Capacity cannot be lower than tickets already sold ({tt.sold})")
    tt.name, tt.price_cents, tt.capacity = body.name, body.price_cents, body.capacity
    audit.record(db, ctx.org.id, "ticket_type.updated", "ticket_type", tt.id, actor=ctx.user)
    db.commit()
    cache.delete(public_events_key(ctx.org.id))
    return tt


@router.get("/events/{event_id}/registrations", response_model=list[RegistrationOut])
def list_registrations(event_id: int, ctx: OrgContext = Depends(require_role(Role.staff)),
                       db: Session = Depends(get_db)):
    _event(db, ctx.org.id, event_id)
    return db.scalars(select(Registration).where(Registration.org_id == ctx.org.id,
                                                 Registration.event_id == event_id)
                      .order_by(Registration.id.desc())).all()


def _do_check_in(db: Session, ctx: OrgContext, reg: Registration) -> Registration:
    if reg.status != "confirmed":
        raise HTTPException(status.HTTP_409_CONFLICT, f"Registration is {reg.status}, not confirmed")
    if reg.checked_in_at:
        raise HTTPException(status.HTTP_409_CONFLICT, "Already checked in")
    reg.checked_in_at = utcnow()
    audit.record(db, ctx.org.id, "registration.checked_in", "registration", reg.id, actor=ctx.user, code=reg.code)
    db.commit()
    return reg


@router.post("/check-in", response_model=RegistrationOut)
def check_in_by_code(body: CheckInIn, ctx: OrgContext = Depends(require_role(Role.staff)),
                     db: Session = Depends(get_db)):
    reg = db.scalar(select(Registration).where(Registration.org_id == ctx.org.id,
                                               Registration.code == body.code.strip().upper()))
    if not reg:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No registration with that code in this organization")
    return _do_check_in(db, ctx, reg)


@router.post("/registrations/{reg_id}/check-in", response_model=RegistrationOut)
def check_in(reg_id: int, ctx: OrgContext = Depends(require_role(Role.staff)), db: Session = Depends(get_db)):
    reg = db.scalar(select(Registration).where(Registration.id == reg_id, Registration.org_id == ctx.org.id))
    if not reg:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Registration not found")
    return _do_check_in(db, ctx, reg)


@router.post("/registrations/{reg_id}/cancel", response_model=RegistrationOut)
def cancel_registration(reg_id: int, ctx: OrgContext = Depends(require_role(Role.admin)),
                        db: Session = Depends(get_db)):
    reg = db.scalar(select(Registration).where(Registration.id == reg_id, Registration.org_id == ctx.org.id))
    if not reg:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Registration not found")
    if reg.status == "cancelled":
        raise HTTPException(status.HTTP_409_CONFLICT, "Already cancelled")
    if reg.checked_in_at:
        raise HTTPException(status.HTTP_409_CONFLICT, "Cannot cancel after check-in")
    tt = db.get(TicketType, reg.ticket_type_id)
    tt.sold = max(0, tt.sold - reg.quantity)  # release capacity
    reg.status = "cancelled"
    audit.record(db, ctx.org.id, "registration.cancelled", "registration", reg.id, actor=ctx.user, code=reg.code)
    db.commit()
    cache.delete(public_events_key(ctx.org.id))
    return reg
