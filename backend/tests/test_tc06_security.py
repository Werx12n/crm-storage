"""TC-06 Тест безпеки (NFR-3.1): автентифікація JWT, розмежування за ролями, зберігання паролів, TLS-конфігурація."""
from pathlib import Path

import jwt
import pytest
from sqlalchemy import select

from app import db
from app.config import settings
from app.entities import JournalEntry, User
from app.main import app
from app.security import create_token

ROOT = Path(__file__).resolve().parents[2]
PUBLIC_PREFIXES = ("/api/auth/login", "/api/auth/token", "/api/barcodes/{kind}")


def _protected_routes():
    for r in app.routes:
        path = getattr(r, "path", "")
        if path.startswith("/api/") and not path.startswith(PUBLIC_PREFIXES):
            for m in r.methods - {"HEAD", "OPTIONS"}:
                yield m, path


def test_tc06_all_api_endpoints_require_token(client):
    checked = 0
    for method, path in _protected_routes():
        url = path.replace("{", "").replace("}", "")
        r = client.request(method, url, json={})
        assert r.status_code == 401, f"{method} {path} → {r.status_code}"
        checked += 1
    assert checked > 40


def test_tc06_invalid_forged_and_expired_tokens(client):
    url = "/api/picking/orders"
    assert client.get(url, headers={"Authorization": "Bearer abc.def.ghi"}).status_code == 401
    forged = jwt.encode({"sub": "admin", "roles": ["admin"]}, "wrong-secret", algorithm="HS256")
    assert client.get(url, headers={"Authorization": f"Bearer {forged}"}).status_code == 401
    expired = create_token("manager", ["warehouse_manager"], minutes=-1)
    r = client.get(url, headers={"Authorization": f"Bearer {expired}"})
    assert r.status_code == 401 and "Термін" in r.json()["detail"]
    ghost = create_token("ghost", ["admin"])
    assert client.get(url, headers={"Authorization": f"Bearer {ghost}"}).status_code == 401


def test_tc06_login_and_password_storage(api):
    r = api.c.post("/api/auth/login", json={"login": "manager", "password": "wrong"})
    assert r.status_code == 401
    r = api.ok(api.c.post("/api/auth/login", json={"login": "manager", "password": "demo123"}))
    payload = jwt.decode(r["access_token"], settings.jwt_secret, algorithms=["HS256"])
    assert payload["sub"] == "manager" and payload["roles"] == ["warehouse_manager"] and payload["exp"]
    with db.SessionLocal() as s:
        u = s.scalar(select(User).where(User.login == "manager"))
        assert u.password_hash.startswith("pbkdf2_sha256$") and "demo123" not in u.password_hash
        fails = s.scalars(select(JournalEntry).where(JournalEntry.action == "Невдала спроба входу")).all()
        assert fails and fails[0].user_login == "manager"


@pytest.mark.parametrize("login,method,url,body", [
    ("picker", "POST", "/api/inventory", {"zone": "STORAGE"}),
    ("sales", "POST", "/api/shipping/orders/X/ship", None),
    ("receiver", "GET", "/api/analytics/kpi", None),
    ("manager", "POST", "/api/admin/users/picker/roles", {"role": "admin"}),
    ("accountant", "POST", "/api/admin/directories/products", {"code": "Z"}),
    ("picker", "GET", "/api/admin/journal", None),
    ("sales", "POST", "/api/integration/erp/orders", {"number": "N", "lines": []}),
])
def test_tc06_role_based_access(api, login, method, url, body):
    r = api.c.request(method, url, json=body, headers=api.h(login))
    assert r.status_code == 403, r.text


def test_tc06_deactivated_user_rejected(api):
    uid = next(u["id"] for u in api.ok(api.get("/api/admin/directories/users", login="admin")) if u["login"] == "sales")
    api.ok(api.put(f"/api/admin/directories/users/{uid}", {"is_active": False}, login="admin"))
    assert api.get("/api/stock/available?q=P-001", login="sales").status_code == 401
    assert api.c.post("/api/auth/login", json={"login": "sales", "password": "demo123"}).status_code == 401


def test_tc06_tls_config():
    conf = ROOT / "frontend" / "nginx.conf"
    if not conf.exists():
        pytest.skip("frontend/nginx.conf недоступний")
    text = conf.read_text(encoding="utf-8")
    assert "listen 443 ssl" in text and "ssl_protocols TLSv1.2 TLSv1.3" in text
