import json
from datetime import datetime, timedelta, timezone

from app.security import sign_webhook
from conftest import signup

FUTURE = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()


def make_org(client, headers, name="Acme Events"):
    r = client.post("/api/orgs", json={"name": name}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def make_event(client, headers, org_id, price=0, capacity=5, publish=True):
    e = client.post(f"/api/orgs/{org_id}/events", headers=headers,
                    json={"title": "Launch Party", "starts_at": FUTURE, "venue": "Hall A"}).json()
    tt = client.post(f"/api/orgs/{org_id}/events/{e['id']}/ticket-types", headers=headers,
                     json={"name": "General", "price_cents": price, "capacity": capacity}).json()
    if publish:
        r = client.patch(f"/api/orgs/{org_id}/events/{e['id']}", headers=headers, json={"status": "published"})
        assert r.status_code == 200, r.text
    return e, tt


# ------------------------------------------------------------------ auth
def test_register_login_me(client):
    headers, _ = signup(client, "a@example.com")
    assert client.get("/api/auth/me", headers=headers).json()["email"] == "a@example.com"
    assert client.post("/api/auth/login", json={"email": "a@example.com", "password": "password123"}).status_code == 200
    assert client.post("/api/auth/login", json={"email": "a@example.com", "password": "nope-nope"}).status_code == 401
    assert client.post("/api/auth/register", json={"email": "a@example.com", "full_name": "A", "password": "password123"}).status_code == 409


def test_unauthenticated_rejected(client):
    assert client.get("/api/orgs").status_code == 401


def test_refresh_rotation_and_reuse_detection(client, alice):
    _, tokens = alice
    r1 = client.post("/api/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert r1.status_code == 200
    new_refresh = r1.json()["refresh_token"]
    # replaying the old token = theft signal -> whole family revoked
    assert client.post("/api/auth/refresh", json={"refresh_token": tokens["refresh_token"]}).status_code == 401
    assert client.post("/api/auth/refresh", json={"refresh_token": new_refresh}).status_code == 401


def test_access_token_cannot_be_used_as_refresh(client, alice):
    headers, _ = alice
    token = headers["Authorization"].split()[1]
    assert client.post("/api/auth/refresh", json={"refresh_token": token}).status_code == 401


# ------------------------------------------------------------------ tenancy
def test_tenant_isolation(client, alice, bob):
    ha, hb = alice[0], bob[0]
    org_a, org_b = make_org(client, ha, "Acme"), make_org(client, hb, "Globex")
    ev_a, _ = make_event(client, ha, org_a["id"])

    # Bob cannot see or touch Acme's org or its event, through any path
    assert client.get(f"/api/orgs/{org_a['id']}", headers=hb).status_code == 404
    assert client.get(f"/api/orgs/{org_a['id']}/events", headers=hb).status_code == 404
    # ...even by smuggling Acme's event id into his own org's URL
    assert client.get(f"/api/orgs/{org_b['id']}/events/{ev_a['id']}", headers=hb).status_code == 404
    assert client.patch(f"/api/orgs/{org_b['id']}/events/{ev_a['id']}", headers=hb,
                        json={"title": "hacked"}).status_code == 404
    assert client.get(f"/api/orgs/{org_b['id']}/events", headers=hb).json() == []
    assert [o["name"] for o in client.get("/api/orgs", headers=hb).json()] == ["Globex"]


# ------------------------------------------------------------------ RBAC
def test_rbac_matrix(client, alice, bob):
    ha, hb = alice[0], bob[0]
    org = make_org(client, ha)
    oid = org["id"]
    ev, _ = make_event(client, ha, oid)

    # add bob as viewer
    assert client.post(f"/api/orgs/{oid}/members", headers=ha,
                       json={"email": "bob@globex-events.com", "role": "viewer"}).status_code == 201
    assert client.get(f"/api/orgs/{oid}/events", headers=hb).status_code == 200            # viewer can read
    assert client.post(f"/api/orgs/{oid}/events", headers=hb, json={"title": "x", "starts_at": FUTURE}).status_code == 403
    assert client.get(f"/api/orgs/{oid}/events/{ev['id']}/registrations", headers=hb).status_code == 403
    assert client.get(f"/api/orgs/{oid}/audit", headers=hb).status_code == 403

    # promote to staff: can list registrations + check-in, still cannot manage events
    bob_id = client.get("/api/auth/me", headers=hb).json()["id"]
    assert client.patch(f"/api/orgs/{oid}/members/{bob_id}", headers=ha, json={"role": "staff"}).status_code == 200
    assert client.get(f"/api/orgs/{oid}/events/{ev['id']}/registrations", headers=hb).status_code == 200
    assert client.patch(f"/api/orgs/{oid}/events/{ev['id']}", headers=hb, json={"title": "y"}).status_code == 403

    # admin cannot mint owners; last owner cannot be demoted
    assert client.patch(f"/api/orgs/{oid}/members/{bob_id}", headers=ha, json={"role": "admin"}).status_code == 200
    assert client.patch(f"/api/orgs/{oid}/members/{bob_id}", headers=hb, json={"role": "owner"}).status_code == 403
    alice_id = client.get("/api/auth/me", headers=ha).json()["id"]
    assert client.patch(f"/api/orgs/{oid}/members/{alice_id}", headers=ha, json={"role": "admin"}).status_code == 400


# ------------------------------------------------------------------ events + registration
def test_publish_requires_ticket_type(client, alice):
    h = alice[0]
    org = make_org(client, h)
    e = client.post(f"/api/orgs/{org['id']}/events", headers=h, json={"title": "T", "starts_at": FUTURE}).json()
    assert client.patch(f"/api/orgs/{org['id']}/events/{e['id']}", headers=h, json={"status": "published"}).status_code == 400


def test_free_registration_confirms_and_checks_in(client, alice):
    h = alice[0]
    org = make_org(client, h)
    ev, tt = make_event(client, h, org["id"], price=0, capacity=3)

    pub = client.get(f"/api/public/{org['slug']}/events").json()
    assert pub["events"][0]["ticket_types"][0]["remaining"] == 3

    r = client.post(f"/api/public/{org['slug']}/events/{ev['id']}/register",
                    json={"ticket_type_id": tt["id"], "attendee_name": "Zed", "attendee_email": "zed@example.com", "quantity": 2})
    assert r.status_code == 201, r.text
    reg = r.json()
    assert reg["status"] == "confirmed" and reg["total_cents"] == 0
    # cache was invalidated -> remaining is fresh
    assert client.get(f"/api/public/{org['slug']}/events").json()["events"][0]["ticket_types"][0]["remaining"] == 1

    ci = client.post(f"/api/orgs/{org['id']}/check-in", headers=h, json={"code": reg["code"].lower()})
    assert ci.status_code == 200 and ci.json()["checked_in_at"]
    assert client.post(f"/api/orgs/{org['id']}/check-in", headers=h, json={"code": reg["code"]}).status_code == 409  # double scan
    assert client.get(f"/api/orgs/{org['id']}/stats", headers=h).json()["checked_in"] == 2


def test_no_overselling(client, alice):
    h = alice[0]
    org = make_org(client, h)
    ev, tt = make_event(client, h, org["id"], capacity=2)
    url = f"/api/public/{org['slug']}/events/{ev['id']}/register"
    body = {"ticket_type_id": tt["id"], "attendee_name": "A", "attendee_email": "a@example.com"}
    assert client.post(url, json={**body, "quantity": 2}).status_code == 201
    assert client.post(url, json=body).status_code == 409


def test_draft_event_not_public(client, alice):
    h = alice[0]
    org = make_org(client, h)
    ev, tt = make_event(client, h, org["id"], publish=False)
    assert client.get(f"/api/public/{org['slug']}/events").json()["events"] == []
    r = client.post(f"/api/public/{org['slug']}/events/{ev['id']}/register",
                    json={"ticket_type_id": tt["id"], "attendee_name": "A", "attendee_email": "a@example.com"})
    assert r.status_code == 404


def test_cannot_check_in_other_tenants_code(client, alice, bob):
    ha, hb = alice[0], bob[0]
    org_a, org_b = make_org(client, ha, "Acme"), make_org(client, hb, "Globex")
    ev, tt = make_event(client, ha, org_a["id"])
    code = client.post(f"/api/public/{org_a['slug']}/events/{ev['id']}/register",
                       json={"ticket_type_id": tt["id"], "attendee_name": "A", "attendee_email": "a@example.com"}).json()["code"]
    assert client.post(f"/api/orgs/{org_b['id']}/check-in", headers=hb, json={"code": code}).status_code == 404


def test_cancel_releases_capacity(client, alice):
    h = alice[0]
    org = make_org(client, h)
    ev, tt = make_event(client, h, org["id"], capacity=1)
    url = f"/api/public/{org['slug']}/events/{ev['id']}/register"
    body = {"ticket_type_id": tt["id"], "attendee_name": "A", "attendee_email": "a@example.com"}
    assert client.post(url, json=body).status_code == 201
    reg = client.get(f"/api/orgs/{org['id']}/events/{ev['id']}/registrations", headers=h).json()[0]
    assert client.post(f"/api/orgs/{org['id']}/registrations/{reg['id']}/cancel", headers=h).status_code == 200
    assert client.post(url, json=body).status_code == 201


# ------------------------------------------------------------------ payments
def test_paid_flow_via_signed_webhook_is_idempotent(client, alice):
    h = alice[0]
    org = make_org(client, h)
    ev, tt = make_event(client, h, org["id"], price=2500, capacity=10)
    reg = client.post(f"/api/public/{org['slug']}/events/{ev['id']}/register",
                      json={"ticket_type_id": tt["id"], "attendee_name": "P", "attendee_email": "p@example.com", "quantity": 2}).json()
    assert reg["status"] == "pending" and reg["total_cents"] == 5000
    # cannot check in before paying
    assert client.post(f"/api/orgs/{org['id']}/check-in", headers=h, json={"code": reg["code"]}).status_code == 409

    intent = client.post(f"/api/public/registrations/{reg['code']}/pay").json()
    event = {"id": "evt_1", "type": "payment.succeeded", "data": {"payment_ref": intent["payment_ref"]}}
    body = json.dumps(event).encode()

    # bad / missing signature rejected
    assert client.post("/api/webhooks/payments", content=body, headers={"X-Signature": "bad"}).status_code == 401
    assert client.post("/api/webhooks/payments", content=body).status_code == 401

    sig = {"X-Signature": sign_webhook(body)}
    assert client.post("/api/webhooks/payments", content=body, headers=sig).json()["result"] == "processed"
    assert client.post("/api/webhooks/payments", content=body, headers=sig).json()["result"] == "duplicate"

    assert client.get(f"/api/public/registrations/{reg['code']}").json()["status"] == "confirmed"
    stats = client.get(f"/api/orgs/{org['id']}/stats", headers=h).json()
    assert stats["revenue_cents"] == 5000 and stats["tickets_sold"] == 2
    assert client.post(f"/api/orgs/{org['id']}/check-in", headers=h, json={"code": reg["code"]}).status_code == 200


def test_demo_confirm_endpoint(client, alice):
    h = alice[0]
    org = make_org(client, h)
    ev, tt = make_event(client, h, org["id"], price=1000)
    reg = client.post(f"/api/public/{org['slug']}/events/{ev['id']}/register",
                      json={"ticket_type_id": tt["id"], "attendee_name": "P", "attendee_email": "p@example.com"}).json()
    ref = client.post(f"/api/public/registrations/{reg['code']}/pay").json()["payment_ref"]
    r = client.post(f"/api/public/payments/{ref}/confirm-demo")
    assert r.status_code == 200 and r.json()["registration_status"] == "confirmed"


def test_audit_log_records_actions(client, alice):
    h = alice[0]
    org = make_org(client, h)
    make_event(client, h, org["id"])
    actions = [a["action"] for a in client.get(f"/api/orgs/{org['id']}/audit", headers=h).json()]
    assert "org.created" in actions and "event.created" in actions and "event.updated" in actions
