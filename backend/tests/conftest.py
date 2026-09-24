import os
import tempfile
from pathlib import Path

import pytest

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
    return {"Authorization": f"Bearer {_token(client, 'manager@intelliinventory.dev')}"}


@pytest.fixture(scope="session")
def viewer(client):
    return {"Authorization": f"Bearer {_token(client, 'viewer@intelliinventory.dev')}"}


@pytest.fixture
def session(client):
    from app.db import session_scope

    with session_scope() as s:
        yield s


MANAGER = {"email": "manager@intelliinventory.dev", "name": "Meera Manager", "role": "manager"}
VIEWER = {"email": "viewer@intelliinventory.dev", "name": "Vik Viewer", "role": "viewer"}
