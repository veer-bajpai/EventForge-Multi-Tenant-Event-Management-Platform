import os
import sys
import tempfile
from pathlib import Path

_tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["LOGIN_RATE_LIMIT"] = "1000"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from fastapi.testclient import TestClient

from app.cache import cache
from app.database import Base, engine
from app.main import app


@pytest.fixture()
def client():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    cache.clear()
    with TestClient(app) as c:
        yield c


def signup(client, email, name="Test User", password="password123"):
    r = client.post("/api/auth/register", json={"email": email, "full_name": name, "password": password})
    assert r.status_code == 201, r.text
    tokens = r.json()
    return {"Authorization": f"Bearer {tokens['access_token']}"}, tokens


@pytest.fixture()
def alice(client):
    return signup(client, "alice@acme-events.com", "Alice")


@pytest.fixture()
def bob(client):
    return signup(client, "bob@globex-events.com", "Bob")
