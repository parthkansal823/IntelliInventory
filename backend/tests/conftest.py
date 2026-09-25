import os
import tempfile
from pathlib import Path

import pytest
from sqlmodel import select

# Isolated database + deterministic settings before the app is imported.
_tmp = Path(tempfile.mkdtemp(prefix="ii-tests-"))
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp / 'test.db'}"
os.environ["AI_PROVIDER"] = "offline"
os.environ["OLLAMA_AUTODETECT"] = "false"
os.environ["AUTOPILOT_ENABLED"] = "false"
os.environ.pop("HERMES_BASE_URL", None)

from fastapi.testclient import TestClient  # noqa: E402

from app.main import create_app  # noqa: E402


@pytest.fixture(scope="session")
def client():
    with TestClient(create_app(start_scheduler=False)) as c:
        yield c


def _token(client, email: str) -> str:
    res = client.post("/api/auth/token", json={"email": email, "password": "demo1234"})
    assert res.status_code == 200, res.text
    return res.json()["access_token"]


@pytest.fixture(scope="session")
def manager(client):
    return {"Authorization": f"Bearer {_token(client, 'ananya@intelliinventory.dev')}"}


@pytest.fixture(scope="session")
def viewer(client):
    """Read-only account created just for tests (the demo itself only has Parth and Ananya)."""
    from app.db import session_scope
    from app.models import Role, User
    from app.security import hash_password

    with session_scope() as s:
        if not s.exec(select(User).where(User.email == VIEWER["email"])).first():
            s.add(User(email=VIEWER["email"], name=VIEWER["name"], role=Role.VIEWER, password_hash=hash_password("demo1234")))
            s.commit()
    return {"Authorization": f"Bearer {_token(client, VIEWER['email'])}"}


@pytest.fixture
def session(client):
    from app.db import session_scope

    with session_scope() as s:
        yield s


MANAGER = {"email": "ananya@intelliinventory.dev", "name": "Ananya", "role": "manager"}
VIEWER = {"email": "viewer@test.local", "name": "Ananya", "role": "viewer"}
