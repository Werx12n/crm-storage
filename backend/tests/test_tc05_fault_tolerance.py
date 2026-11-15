"""TC-05 Тест відмовостійкості (NFR-2.1, NFR-2.2): черга і повтор при недоступності зовнішніх систем,
збереження подій між перезапусками воркера, атомарність операцій, health-check, резервне копіювання."""
from pathlib import Path

import pytest

from app import db
from app.modules.integration import mock
from app.modules.integration.manager import IntegrationManager
from app.seed import gtin

ROOT = Path(__file__).resolve().parents[2]


def _ship(api, number="ORD-F1"):
    api.order(number, [("P-006", 2)])
    api.pick_all()
    api.ok(api.post(f"/api/shipping/orders/{number}/check", {"code": gtin(6), "quantity": 2}, login="packer"))
    return api.ok(api.post(f"/api/shipping/orders/{number}/ship", login="packer"))


def test_tc05_delivery_unavailable_queue_and_retry(api):
    mock.STATE["delivery_available"] = False
    res = _ship(api)
    did = res["dispatch"]["id"]
    out = api.sync()
    assert out["failed"] == 1
    ev = [e for e in api.ok(api.get("/api/integration/events", login="erp")) if e["type"] == "DeliveryRequested"][0]
    assert ev["status"] == "PENDING" and ev["attempts"] == 1 and "503" in ev["last_error"]
    d = next(x for x in api.ok(api.get("/api/shipping/dispatches")) if x["id"] == did)
    assert d["status"] == "AWAITING_TTN" and d["ttn_number"] is None
    # «перезапуск воркера»: новий процес/сесія бачить ту саму чергу в БД
    mock.STATE["delivery_available"] = True
    with db.SessionLocal() as s:
        r = IntegrationManager(s).synchronize(force=True)
    assert r["processed"] >= 1
    d = next(x for x in api.ok(api.get("/api/shipping/dispatches")) if x["id"] == did)
    assert d["status"] == "SENT" and d["ttn_number"].startswith("2045")
    assert len(mock.STATE["delivery_shipments"]) == 1


def test_tc05_erp_outage_does_not_block_warehouse(api, demo_asn):
    mock.STATE["erp_available"] = False
    res = api.receive(demo_asn, [(gtin(1), 100, "LT1"), (gtin(5), 50, "MT1")])
    assert res["shipment"]["status"] == "COMPLETED"  # склад працює, подія чекає в outbox
    assert api.sync()["failed"] >= 1
    mock.STATE["erp_available"] = True
    api.sync()
    assert any(o["type"] == "ReceivingCompleted" for o in mock.STATE["erp_operations"])


def test_tc05_operation_is_atomic(api, demo_asn, monkeypatch):
    from app.services.events import EventPublisher
    api.post(f"/api/receiving/shipments/{demo_asn}/start", login="receiver")
    api.ok(api.post(f"/api/receiving/shipments/{demo_asn}/scan", {"code": gtin(1), "quantity": 10,
                                                                  "batch_number": "LT1"}, login="receiver"))

    def boom(*a, **k):
        raise RuntimeError("збій під час публікації події")
    monkeypatch.setattr(EventPublisher, "publish", boom)
    with pytest.raises(RuntimeError):
        api.post(f"/api/receiving/shipments/{demo_asn}/complete", login="receiver")
    monkeypatch.undo()
    sh = api.ok(api.get(f"/api/receiving/shipments/{demo_asn}", login="receiver"))
    assert sh["status"] == "IN_PROGRESS"
    assert api.ok(api.get("/api/stock?zone=RECEIVING")) == []  # залишки не змінились
    assert api.ok(api.get("/api/putaway/tasks")) == []


def test_tc05_health_and_backup_configuration(api):
    assert api.ok(api.c.get("/health"))["status"] == "ok"
    if not (ROOT / "docker-compose.yml").exists():
        pytest.skip("docker-compose.yml недоступний (тест запущено в контейнері)")
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "backup:" in compose and "BACKUP_INTERVAL_SECONDS: 900" in compose  # RPO ≤ 15 хв
    assert "restart: unless-stopped" in compose
    assert (ROOT / "scripts" / "restore.sh").exists() and (ROOT / "scripts" / "backup.sh").exists()
