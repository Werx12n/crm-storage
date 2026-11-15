"""TC-03 Тест обміну з обліковою системою (FR-6.2): REST API, outbox, ідемпотентність."""
from app.modules.integration import mock
from app.seed import gtin


def test_tc03_order_from_erp_and_status_back(api):
    o = api.order("ORD-E1", [("P-005", 10), ("P-009", 500)])  # P-009 лише 100 → частково
    assert o["partial"] and o["status"] == "IN_PICKING" and o["tasks"]
    res = api.sync()
    assert res["processed"] >= 1 and res["failed"] == 0
    statuses = [op for op in mock.STATE["erp_operations"] if op["type"] == "OrderStatus"]
    assert statuses[-1]["payload"]["order_number"] == "ORD-E1"
    assert statuses[-1]["payload"]["status"] == "частково" and statuses[-1]["payload"]["code"] == "PARTIAL"
    line = next(x for x in statuses[-1]["payload"]["lines"] if x["product_code"] == "P-009")
    assert line["reserved"] == 100


def test_tc03_receiving_and_shipping_reach_erp(api, demo_asn):
    api.receive(demo_asn, [(gtin(1), 100, "LT1"), (gtin(5), 50, "MT1")])
    api.order("ORD-E2", [("P-006", 3)])
    api.pick_all()
    api.ok(api.post("/api/shipping/orders/ORD-E2/check", {"code": gtin(6), "quantity": 3}, login="packer"))
    api.ok(api.post("/api/shipping/orders/ORD-E2/ship", login="packer"))
    api.sync()
    types = [op["type"] for op in mock.STATE["erp_operations"]]
    assert "ReceivingCompleted" in types and "Shipped" in types
    shipped = next(op for op in mock.STATE["erp_operations"] if op["type"] == "Shipped")
    assert shipped["payload"]["writeoffs"] == [{"product_code": "P-006", "batch": "W2801A", "quantity": 3.0}]
    rc = next(op for op in mock.STATE["erp_operations"] if op["type"] == "ReceivingCompleted")
    assert {ln["product_code"] for ln in rc["payload"]["lines"]} == {"P-001", "P-005"}
    # повторна синхронізація нічого не дублює
    n = len(mock.STATE["erp_operations"])
    api.sync()
    assert len(mock.STATE["erp_operations"]) == n


def test_tc03_stock_export_and_openapi(api):
    st = api.ok(api.get("/api/integration/erp/stock", login="erp"))
    p1 = [i for i in st["items"] if i["product_code"] == "P-001"]
    assert sum(i["quantity"] for i in p1) == 530
    spec = api.ok(api.c.get("/openapi.json"))
    assert spec["openapi"].startswith("3.")
    for path in ("/api/integration/erp/orders", "/api/integration/edi/asn", "/api/integration/erp/stock"):
        assert path in spec["paths"]


def test_tc03_validation_errors_are_reported(api):
    r = api.post("/api/integration/erp/orders", {"number": "X", "lines": [{"product_code": "NOPE", "quantity": 1}]},
                 login="erp")
    assert r.status_code == 422 and r.json()["code"] == "unknown_product"
    r = api.post("/api/integration/erp/orders", {"number": "X", "lines": [{"product_code": "P-001", "quantity": -1}]},
                 login="erp")
    assert r.status_code == 422
