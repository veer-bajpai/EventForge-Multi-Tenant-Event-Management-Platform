"""Attendee-facing endpoints (no login) + payment webhooks."""
import json
import logging
import secrets
import uuid
from datetime import timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request, status
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from .. import audit
from ..cache import cache, public_events_key
from ..config import settings
from ..database import get_db
from ..models import (Event, Organization, Payment, ProcessedWebhook, Registration,
                      TicketType, utcnow)
from ..schemas import RegisterAttendeeIn
from ..security import sign_webhook, verify_webhook

log = logging.getLogger("eventforge")
router = APIRouter(tags=["public"])

HOLD_MINUTES = 15  # unpaid reservations release their seats after this long
_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O/1/I


def _org(db: Session, slug: str) -> Organization:
    org = db.scalar(select(Organization).where(Organization.slug == slug))
    if not org:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organization not found")
    return org


def _public_event(ev: Event) -> dict:
    return {
        "id": ev.id, "title": ev.title, "description": ev.description, "venue": ev.venue,
        "starts_at": ev.starts_at.isoformat(), "ends_at": ev.ends_at.isoformat() if ev.ends_at else None,
        "ticket_types": [{"id": t.id, "name": t.name, "price_cents": t.price_cents,
                          "remaining": max(0, t.capacity - t.sold)} for t in ev.ticket_types],
    }


@router.get("/api/public/{slug}/events")
def public_events(slug: str, db: Session = Depends(get_db)):
    org = _org(db, slug)
    key = public_events_key(org.id)
    cached = cache.get(key)
    if cached is None:
        evs = db.scalars(select(Event).options(selectinload(Event.ticket_types))
                         .where(Event.org_id == org.id, Event.status == "published")
                         .order_by(Event.starts_at)).all()
        cached = [_public_event(e) for e in evs]
        cache.set(key, cached, settings.public_cache_ttl)
    return {"organization": {"name": org.name, "slug": org.slug}, "events": cached}


@router.get("/api/public/{slug}/events/{event_id}")
def public_event(slug: str, event_id: int, db: Session = Depends(get_db)):
    org = _org(db, slug)
    ev = db.scalar(select(Event).options(selectinload(Event.ticket_types))
                   .where(Event.id == event_id, Event.org_id == org.id, Event.status == "published"))
    if not ev:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Event not found")
    return _public_event(ev)


def _release_expired(db: Session, ticket_type_id: int) -> None:
    """Lazy reaper: cancel stale unpaid holds for this ticket type and give the seats back."""
    cutoff = utcnow() - timedelta(minutes=HOLD_MINUTES)
    stale = db.scalars(select(Registration).where(
        Registration.ticket_type_id == ticket_type_id, Registration.status == "pending",
        Registration.created_at < cutoff)).all()
    for r in stale:
        r.status = "cancelled"
        db.execute(update(TicketType).where(TicketType.id == r.ticket_type_id)
                   .values(sold=TicketType.sold - r.quantity))
        audit.record(db, r.org_id, "registration.expired", "registration", r.id, code=r.code)
    if stale:
        db.flush()


def _send_confirmation(email: str, code: str, title: str) -> None:
    # Swap for SendGrid/SES/etc. Runs after the response is sent.
    log.info("EMAIL to=%s subject='Your ticket for %s' code=%s", email, title, code)


@router.post("/api/public/{slug}/events/{event_id}/register", status_code=201)
def register_attendee(slug: str, event_id: int, body: RegisterAttendeeIn, bg: BackgroundTasks,
                      db: Session = Depends(get_db)):
    org = _org(db, slug)
    ev = db.scalar(select(Event).where(Event.id == event_id, Event.org_id == org.id,
                                       Event.status == "published"))
    if not ev:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Event not found")
    if ev.starts_at < utcnow():
        raise HTTPException(status.HTTP_409_CONFLICT, "This event has already started")
    tt = db.scalar(select(TicketType).where(TicketType.id == body.ticket_type_id,
                                            TicketType.event_id == ev.id, TicketType.org_id == org.id))
    if not tt:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ticket type not found")

    _release_expired(db, tt.id)
    # Atomic seat reservation: a single conditional UPDATE, so two concurrent buyers can never
    # oversell the last ticket (the DB serializes the row update).
    res = db.execute(update(TicketType)
                     .where(TicketType.id == tt.id, TicketType.sold + body.quantity <= TicketType.capacity)
                     .values(sold=TicketType.sold + body.quantity))
    if res.rowcount != 1:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Not enough tickets left for that ticket type")

    total = tt.price_cents * body.quantity
    reg = Registration(org_id=org.id, event_id=ev.id, ticket_type_id=tt.id,
                       code="EF-" + "".join(secrets.choice(_ALPHABET) for _ in range(8)),
                       attendee_name=body.attendee_name.strip(), attendee_email=body.attendee_email.lower(),
                       quantity=body.quantity, total_cents=total,
                       status="confirmed" if total == 0 else "pending")
    db.add(reg)
    db.flush()
    audit.record(db, org.id, "registration.created", "registration", reg.id, code=reg.code, qty=reg.quantity)
    db.commit()
    cache.delete(public_events_key(org.id))
    if reg.status == "confirmed":
        bg.add_task(_send_confirmation, reg.attendee_email, reg.code, ev.title)
    return _reg_view(reg, ev, tt)


def _reg_view(reg: Registration, ev: Event, tt: TicketType) -> dict:
    return {"code": reg.code, "status": reg.status, "attendee_name": reg.attendee_name,
            "attendee_email": reg.attendee_email, "quantity": reg.quantity, "total_cents": reg.total_cents,
            "event_title": ev.title, "event_starts_at": ev.starts_at.isoformat(), "venue": ev.venue,
            "ticket_name": tt.name, "checked_in": reg.checked_in_at is not None}


@router.get("/api/public/registrations/{code}")
def lookup(code: str, db: Session = Depends(get_db)):
    reg = db.scalar(select(Registration).where(Registration.code == code.strip().upper()))
    if not reg:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No registration with that code")
    return _reg_view(reg, db.get(Event, reg.event_id), db.get(TicketType, reg.ticket_type_id))


# ------------------------------------------------------------------ payments
@router.post("/api/public/registrations/{code}/pay")
def create_payment_intent(code: str, db: Session = Depends(get_db)):
    """Creates a payment intent. With a real provider (e.g. Stripe) you would call their API here
    and return the client secret; the provider then calls /api/webhooks/payments."""
    reg = db.scalar(select(Registration).where(Registration.code == code.strip().upper()))
    if not reg:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No registration with that code")
    if reg.status != "pending":
        raise HTTPException(status.HTTP_409_CONFLICT, f"Registration is {reg.status}; nothing to pay")
    pay = db.scalar(select(Payment).where(Payment.registration_id == reg.id, Payment.status == "requires_payment"))
    if not pay:
        pay = Payment(org_id=reg.org_id, registration_id=reg.id, provider_ref="pi_" + uuid.uuid4().hex[:20],
                      amount_cents=reg.total_cents)
        db.add(pay)
        db.commit()
    return {"payment_ref": pay.provider_ref, "amount_cents": pay.amount_cents,
            "demo_mode": settings.payment_mode == "demo"}


def process_payment_event(db: Session, event: dict) -> str:
    """Idempotent handler shared by the webhook and the demo confirm endpoint."""
    try:
        db.add(ProcessedWebhook(event_id=str(event["id"])))
        db.flush()
    except IntegrityError:
        db.rollback()
        return "duplicate"
    pay = db.scalar(select(Payment).where(Payment.provider_ref == event["data"]["payment_ref"]))
    if not pay:
        db.commit()
        return "ignored"
    reg = db.get(Registration, pay.registration_id)
    if event["type"] == "payment.succeeded" and pay.status != "succeeded":
        pay.status = "succeeded"
        if reg.status == "pending":
            reg.status = "confirmed"
        audit.record(db, pay.org_id, "payment.succeeded", "payment", pay.id, amount=pay.amount_cents)
    elif event["type"] == "payment.failed" and pay.status == "requires_payment":
        pay.status = "failed"
        audit.record(db, pay.org_id, "payment.failed", "payment", pay.id)
    db.commit()
    cache.delete(public_events_key(pay.org_id))
    return "processed"


@router.post("/api/webhooks/payments")
async def payment_webhook(request: Request, bg: BackgroundTasks, db: Session = Depends(get_db),
                          x_signature: str | None = Header(default=None)):
    body = await request.body()
    if not verify_webhook(body, x_signature):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid signature")
    try:
        event = json.loads(body)
        event["id"], event["type"], event["data"]["payment_ref"]
    except Exception:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Malformed event")
    result = process_payment_event(db, event)
    if result == "processed" and event["type"] == "payment.succeeded":
        pay = db.scalar(select(Payment).where(Payment.provider_ref == event["data"]["payment_ref"]))
        reg = db.get(Registration, pay.registration_id)
        bg.add_task(_send_confirmation, reg.attendee_email, reg.code, db.get(Event, reg.event_id).title)
    return {"result": result}


@router.post("/api/public/payments/{ref}/confirm-demo")
def confirm_demo(ref: str, bg: BackgroundTasks, db: Session = Depends(get_db)):
    """Demo-only stand-in for the payment provider: builds a signed event and feeds it through the
    exact same idempotent code path as the real webhook."""
    if settings.payment_mode != "demo":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    event = {"id": "evt_" + uuid.uuid4().hex[:16], "type": "payment.succeeded", "data": {"payment_ref": ref}}
    assert verify_webhook(json.dumps(event).encode(), sign_webhook(json.dumps(event).encode()))
    if not db.scalar(select(Payment).where(Payment.provider_ref == ref)):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown payment")
    result = process_payment_event(db, event)
    pay = db.scalar(select(Payment).where(Payment.provider_ref == ref))
    reg = db.get(Registration, pay.registration_id)
    if result == "processed":
        bg.add_task(_send_confirmation, reg.attendee_email, reg.code, db.get(Event, reg.event_id).title)
    return {"result": result, "registration_status": reg.status}
