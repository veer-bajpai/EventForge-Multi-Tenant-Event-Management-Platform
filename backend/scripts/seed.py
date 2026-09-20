"""Create a demo account, organization and events.   python -m scripts.seed"""
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.database import Base, SessionLocal, engine
from app.models import Event, Membership, Organization, Role, TicketType, User, utcnow
from app.security import hash_password

Base.metadata.create_all(bind=engine)
with SessionLocal() as db:
    if db.scalar(select(User).where(User.email == "demo@example.com")):
        print("Demo data already exists.")
        sys.exit(0)
    user = User(email="demo@example.com", full_name="Demo Organizer", password_hash=hash_password("demo12345"))
    org = Organization(name="Northside Collective", slug="northside")
    db.add_all([user, org])
    db.flush()
    db.add(Membership(user_id=user.id, org_id=org.id, role=Role.owner))
    now = utcnow()
    for i, (title, venue, days, tiers) in enumerate([
        ("Rooftop launch night", "Skyline Terrace", 21, [("General admission", 0, 120), ("VIP table", 4500, 12)]),
        ("Intro to synthesizers workshop", "Studio B", 35, [("Workshop seat", 2500, 24)]),
        ("Community open mic", "The Corner Room", 9, [("Free entry", 0, 60)]),
    ]):
        ev = Event(org_id=org.id, created_by=user.id, title=title, venue=venue, status="published",
                   description="Doors open 30 minutes before start.", starts_at=now + timedelta(days=days, hours=19))
        db.add(ev)
        db.flush()
        for name, price, cap in tiers:
            db.add(TicketType(org_id=org.id, event_id=ev.id, name=name, price_cents=price, capacity=cap))
    db.commit()
    print("Seeded. Log in with demo@example.com / demo12345  ->  public page: /events.html?org=northside")
