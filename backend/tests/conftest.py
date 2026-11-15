"""Спільні фікстури. За замовчуванням — тимчасова SQLite; TEST_DATABASE_URL=postgresql+psycopg://… — PostgreSQL."""
import os
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="wms-test-"))
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{(_tmp / 'test.db').as_posix()}"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import db  # noqa: E402
from app.config import settings  # noqa: E402
from app.main import app  # noqa: E402
from app.modules.integration import gateways, mock  # noqa: E402
from app.security import create_token  # noqa: E402
from app.seed import gtin, seed  # noqa: E402

settings.erp_url = "http://testserver/mock/erp"
settings.delivery_url = "http://testserver/mock/delivery"
gateways.client_factory = lambda: TestClient(app)


class Api:
    def __init__(self, client: TestClient):
        self.c = client

    @staticmethod
    def h(login: str, roles: list[str] | None = None) -> dict:
        from app.seed import USERS
        roles = roles or next(r for lg, _, r in USERS if lg == login)
        return {"Authorization": f"Bearer {create_token(login, roles)}"}

    def get(self, url, login="manager", **kw):
        return self.c.get(url, headers=self.h(login), **kw)

    def post(self, url, json=None, login="manager", headers=None, **kw):
        return self.c.post(url, json=json, headers={**self.h(login), **(headers or {})}, **kw)

    def put(self, url, json=None, login="manager", **kw):
        return self.c.put(url, json=json, headers=self.h(login), **kw)

    def ok(self, resp, code=200):
        assert resp.status_code == code, resp.text
        return resp.json()

    # --- сценарні помічники ---
    def receive(self, asn: str, lines: list[tuple], login="receiver") -> dict:
        """lines: (gtin, qty, batch)"""
        self.ok(self.post(f"/api/receiving/shipments/{asn}/start", login=login))
        for g, q, b in lines:
            self.ok(self.post(f"/api/receiving/shipments/{asn}/scan",
                              {"code": g, "quantity": q, "batch_number": b}, login=login))
        return self.ok(self.post(f"/api/receiving/shipments/{asn}/complete", login=login))

    def order(self, number: str, lines: list[tuple], create_task=True) -> dict:
        return self.ok(self.post("/api/integration/erp/orders", {
            "number": number, "client": "Тестовий клієнт", "create_task": create_task,
            "lines": [{"product_code": p, "quantity": q} for p, q in lines]}, login="erp"))

    def pick_all(self, login="picker") -> dict:
        task = self.ok(self.post("/api/picking/tasks/next", login=login))["task"]
        for ln in task["lines"]:
            self.ok(self.post(f"/api/picking/tasks/{task['number']}/confirm",
                              {"cell": ln["from_cell"], "product": ln["gtin"], "quantity": ln["quantity"]},
                              login=login))
        return task

    def sync(self) -> dict:
        return self.ok(self.post("/api/integration/sync", login="erp"))


@pytest.fixture()
def client():
    db.Base.metadata.drop_all(db.engine)
    db.Base.metadata.create_all(db.engine)
    mock.reset()
    with db.SessionLocal() as s:
        seed(s, with_documents=False)
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def api(client) -> Api:
    return Api(client)


@pytest.fixture()
def demo_asn(api) -> str:
    api.ok(api.post("/api/integration/edi/asn", {
        "asn_number": "ASN-T1", "supplier": "Постачальник", "lines": [
            {"gtin": gtin(1), "quantity": 100, "batch_number": "LT1", "expiry_date": "2030-01-31"},
            {"gtin": gtin(5), "quantity": 50, "batch_number": "MT1", "expiry_date": "2030-02-28"}]}, login="erp"))
    return "ASN-T1"
