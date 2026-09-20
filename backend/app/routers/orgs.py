import re

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit
from ..database import get_db
from ..deps import OrgContext, get_current_user, org_context, require_role
from ..models import (ROLE_RANK, AuditLog, Event, Membership, Organization,
                      Registration, Role, User)
from ..schemas import (AuditOut, MemberAdd, MemberOut, MemberUpdate, OrgCreate,
                       OrgOut, OrgWithRole)

router = APIRouter(prefix="/api/orgs", tags=["organizations"])


def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:50] or "org"


@router.post("", response_model=OrgOut, status_code=201)
def create_org(body: OrgCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    slug = body.slug or _slugify(body.name)
    base, n = slug, 1
    while db.scalar(select(Organization).where(Organization.slug == slug)):
        if body.slug:
            raise HTTPException(status.HTTP_409_CONFLICT, "That slug is already taken")
        n += 1
        slug = f"{base}-{n}"
    org = Organization(name=body.name.strip(), slug=slug)
    db.add(org)
    db.flush()
    db.add(Membership(user_id=user.id, org_id=org.id, role=Role.owner))
    audit.record(db, org.id, "org.created", "organization", org.id, actor=user)
    db.commit()
    return org


@router.get("", response_model=list[OrgWithRole])
def my_orgs(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.execute(select(Organization, Membership.role)
                      .join(Membership, Membership.org_id == Organization.id)
                      .where(Membership.user_id == user.id).order_by(Organization.name)).all()
    return [OrgWithRole(id=o.id, name=o.name, slug=o.slug, role=r) for o, r in rows]


@router.get("/{org_id}", response_model=OrgWithRole)
def get_org(ctx: OrgContext = Depends(org_context)):
    return OrgWithRole(id=ctx.org.id, name=ctx.org.name, slug=ctx.org.slug, role=ctx.role)


@router.get("/{org_id}/stats")
def stats(ctx: OrgContext = Depends(org_context), db: Session = Depends(get_db)):
    oid = ctx.org.id
    events = db.scalar(select(func.count()).select_from(Event).where(Event.org_id == oid)) or 0
    published = db.scalar(select(func.count()).select_from(Event)
                          .where(Event.org_id == oid, Event.status == "published")) or 0
    conf = (Registration.org_id == oid, Registration.status == "confirmed")
    tickets = db.scalar(select(func.coalesce(func.sum(Registration.quantity), 0)).where(*conf)) or 0
    revenue = db.scalar(select(func.coalesce(func.sum(Registration.total_cents), 0)).where(*conf)) or 0
    checked = db.scalar(select(func.coalesce(func.sum(Registration.quantity), 0))
                        .where(*conf, Registration.checked_in_at.is_not(None))) or 0
    pending = db.scalar(select(func.count()).select_from(Registration)
                        .where(Registration.org_id == oid, Registration.status == "pending")) or 0
    return {"events": events, "published_events": published, "tickets_sold": int(tickets),
            "revenue_cents": int(revenue), "checked_in": int(checked), "pending_registrations": pending}


@router.get("/{org_id}/members", response_model=list[MemberOut])
def members(ctx: OrgContext = Depends(org_context), db: Session = Depends(get_db)):
    rows = db.execute(select(Membership, User).join(User, User.id == Membership.user_id)
                      .where(Membership.org_id == ctx.org.id).order_by(User.full_name)).all()
    return [MemberOut(user_id=u.id, email=u.email, full_name=u.full_name, role=m.role) for m, u in rows]


@router.post("/{org_id}/members", response_model=MemberOut, status_code=201)
def add_member(body: MemberAdd, ctx: OrgContext = Depends(require_role(Role.admin)),
               db: Session = Depends(get_db)):
    if body.role == Role.owner and ctx.role != Role.owner:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only owners can add owners")
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No account with that email. Ask them to sign up first.")
    if db.scalar(select(Membership).where(Membership.user_id == user.id, Membership.org_id == ctx.org.id)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Already a member")
    db.add(Membership(user_id=user.id, org_id=ctx.org.id, role=body.role))
    audit.record(db, ctx.org.id, "member.added", "user", user.id, actor=ctx.user, role=body.role.value)
    db.commit()
    return MemberOut(user_id=user.id, email=user.email, full_name=user.full_name, role=body.role)


def _get_membership(db, org_id, user_id) -> Membership:
    m = db.scalar(select(Membership).where(Membership.org_id == org_id, Membership.user_id == user_id))
    if not m:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Member not found")
    return m


def _owner_count(db, org_id) -> int:
    return db.scalar(select(func.count()).select_from(Membership)
                     .where(Membership.org_id == org_id, Membership.role == Role.owner)) or 0


@router.patch("/{org_id}/members/{user_id}", response_model=MemberOut)
def update_member(user_id: int, body: MemberUpdate, ctx: OrgContext = Depends(require_role(Role.admin)),
                  db: Session = Depends(get_db)):
    m = _get_membership(db, ctx.org.id, user_id)
    # admins may not touch owners or grant owner
    if ctx.role != Role.owner and (m.role == Role.owner or body.role == Role.owner):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only owners can change owner roles")
    if m.role == Role.owner and body.role != Role.owner and _owner_count(db, ctx.org.id) <= 1:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "An organization needs at least one owner")
    old = m.role
    m.role = body.role
    audit.record(db, ctx.org.id, "member.role_changed", "user", user_id, actor=ctx.user,
                 old=old.value, new=body.role.value)
    db.commit()
    return MemberOut(user_id=m.user.id, email=m.user.email, full_name=m.user.full_name, role=m.role)


@router.delete("/{org_id}/members/{user_id}", status_code=204)
def remove_member(user_id: int, ctx: OrgContext = Depends(require_role(Role.admin)),
                  db: Session = Depends(get_db)):
    m = _get_membership(db, ctx.org.id, user_id)
    if m.role == Role.owner:
        if ctx.role != Role.owner:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Only owners can remove owners")
        if _owner_count(db, ctx.org.id) <= 1:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "An organization needs at least one owner")
    db.delete(m)
    audit.record(db, ctx.org.id, "member.removed", "user", user_id, actor=ctx.user)
    db.commit()


@router.get("/{org_id}/audit", response_model=list[AuditOut])
def audit_log(limit: int = Query(50, le=200), ctx: OrgContext = Depends(require_role(Role.admin)),
              db: Session = Depends(get_db)):
    return db.scalars(select(AuditLog).where(AuditLog.org_id == ctx.org.id)
                      .order_by(AuditLog.id.desc()).limit(limit)).all()
