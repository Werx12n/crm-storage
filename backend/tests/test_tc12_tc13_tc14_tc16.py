"""TC-12 Циклічна інвентаризація і коригування (FR-5.1, FR-5.2); TC-13 Звіти і KPI (FR-7.1, FR-7.2);
TC-14 Довідники, ролі і журнал (FR-6.1, FR-6.4); TC-16 Офлайн-режим ТЗД (NFR-2.3); штрихкоди (FR-1.2, FR-1.4)."""
import uuid

from app.seed import gtin
from app.services import gs1


def test_tc12_cycle_count_recount_and_approval(api):
    plan = api.ok(api.post("/api/inventory", {"cells": ["ST-04-01-1", "ST-04-02-1"], "threshold": 2}))
    inv = plan["number"]
    assert len(plan["tasks"]) == 2
    # сліпий підрахунок: ТЗД не бачить облікову кількість
    open_t = api.ok(api.get("/api/inventory/tasks/open", login="counter"))
    assert "book" not in str(open_t) and "expected" not in str(open_t)
    # FR-5.1: склад не заблоковано — під час інвентаризації можна відібрати товар з цієї комірки
    api.order("ORD-I1", [("P-008", 5)])
    api.pick_all()
    # ST-04-01-1: облік 195 (200 − 5), факт 194 → у межах порогу
    r = api.ok(api.post("/api/inventory/count", {"cell": "ST-04-01-1", "quantity": 194}, login="counter"))
    assert r["recount"] is False
    # ST-04-02-1: облік 100, факт 90 → понад поріг → повторний перерахунок (4а)
    r = api.ok(api.post("/api/inventory/count", {"cell": "ST-04-02-1", "quantity": 90}, login="counter"))
    assert r["recount"] is True
    assert api.post(f"/api/inventory/{inv}/approve").json()["code"] == "counting_not_finished"
    api.ok(api.post("/api/inventory/count", {"cell": "ST-04-02-1", "quantity": 92}, login="counter"))
    # FR-5.2 / BRL-02: до затвердження залишки не змінено; затверджує лише начальник складу
    assert [x["quantity"] for x in api.ok(api.get("/api/stock")) if x["cell"] == "ST-04-02-1"] == [100]
    assert api.post(f"/api/inventory/{inv}/approve", login="admin").status_code == 403
    assert api.post(f"/api/inventory/{inv}/approve", login="counter").status_code == 403
    st = api.ok(api.post(f"/api/inventory/{inv}/approve"))
    assert st["number"] == f"ВР-{inv}" and {(d["cell"], d["difference"]) for d in st["discrepancies"]} == {
        ("ST-04-01-1", -1), ("ST-04-02-1", -8)}
    stock = {x["cell"]: x["quantity"] for x in api.ok(api.get("/api/stock")) if x["cell"] in ("ST-04-01-1", "ST-04-02-1")}
    assert stock == {"ST-04-01-1": 194, "ST-04-02-1": 92}
    assert api.ok(api.get("/api/analytics/reports/inventory"))["rows"]


def test_tc13_reports_and_kpi(api, demo_asn):
    api.receive(demo_asn, [(gtin(1), 100, "LT1"), (gtin(5), 40, "MT1")])
    api.order("ORD-K1", [("P-006", 2)])
    task = api.ok(api.post("/api/picking/tasks/next", login="picker"))["task"]
    api.post(f"/api/picking/tasks/{task['number']}/confirm", {"cell": task["lines"][0]["from_cell"],
                                                               "product": gtin(9)}, login="picker")
    api.pick_all()
    api.ok(api.post("/api/shipping/orders/ORD-K1/check", {"code": gtin(6), "quantity": 2}, login="packer"))
    api.ok(api.post("/api/shipping/orders/ORD-K1/ship", login="packer"))
    reps = api.ok(api.get("/api/analytics/reports", login="accountant"))
    assert [r["code"] for r in reps] == [f"ВП-{i:02d}" for i in range(1, 11)] + ["FR-7.2"]
    for r in reps:
        rep = api.ok(api.get(f"/api/analytics/reports/{r['type']}", login="accountant"))
        assert rep["code"] == r["code"] and isinstance(rep["rows"], list)
    mv = api.ok(api.get("/api/analytics/reports/movement", login="accountant"))
    assert {"Приймання", "Відбір", "Відвантаження", "Помилка відбору"} <= {x["type"] for x in mv["rows"]}
    abc = api.ok(api.get("/api/analytics/reports/abc_xyz", login="accountant"))
    assert abc["rows"][0]["product_code"] == "P-006" and abc["rows"][0]["abc"] == "A"
    kpi = {k["code"]: k["value"] for k in api.ok(api.get("/api/analytics/kpi", login="accountant"))["kpi"]}
    # 1 рядок відбору, на ньому була помилка скану → безпомилкових 0 з 1
    assert kpi["picking_accuracy"] == 0.0
    assert kpi["otif"] == 100.0 and kpi["order_cycle_time"] is not None
    assert kpi["capacity_utilization"] > 0 and kpi["dock_to_stock"] is None  # розміщень ще не було
    assert kpi["inventory_turnover"] > 0 and kpi["labor_productivity"] > 0
    assert kpi["order_handling_cost"] is None  # витрати не введено → n/a
    # 2а: порожній період
    empty = api.ok(api.get("/api/analytics/reports/movement?date_from=2001-01-01&date_to=2001-01-31",
                           login="accountant"))
    assert empty["rows"] == [] and empty["message"]
    x = api.get("/api/analytics/reports/stock?format=xlsx", login="accountant")
    assert x.status_code == 200 and x.content[:2] == b"PK"
    p = api.get("/api/analytics/reports/stock?format=pdf", login="accountant")
    assert p.status_code in (200, 409)
    if p.status_code == 200:
        assert p.content[:4] == b"%PDF"


def test_tc14_directories_roles_journal(api):
    p = api.ok(api.post("/api/admin/directories/products", {"code": "P-100", "name": "Новий товар",
                                                            "gtin": gs1.make_gtin13("4820000", 100), "weight": 0.5}))
    assert p["gtin"].endswith(gs1.make_gtin13("4820000", 100))
    # 3а: дублікат
    r = api.post("/api/admin/directories/products", {"code": "P-100", "name": "x", "gtin": gtin(11)})
    assert r.status_code == 409
    r = api.post("/api/admin/directories/products", {"code": "P-101", "name": "x", "gtin": "4820000000001"})
    assert r.status_code == 422 and r.json()["code"] == "bad_gtin"
    api.ok(api.post("/api/admin/directories/cells", {"address": "st-05-01-1", "zone": "STORAGE", "capacity": 500}))
    assert api.post("/api/admin/directories/cells", {"address": "ST-05-01-1", "zone": "STORAGE"}).status_code == 409
    api.ok(api.post("/api/admin/directories/counterparties", {"code": "CL-9", "name": "Клієнт 9", "kind": "CLIENT"}))
    # користувачі й ролі — лише адміністратор
    assert api.post("/api/admin/directories/users", {"login": "u1", "full_name": "U", "password": "secret1"}
                    ).status_code == 403
    u = api.ok(api.post("/api/admin/directories/users", {"login": "u1", "full_name": "Новий працівник",
                                                         "password": "secret1"}, login="admin"))
    u = api.ok(api.post("/api/admin/users/u1/roles", {"role": "picker"}, login="admin"))
    assert u["roles"] == ["picker"]
    login = api.ok(api.c.post("/api/auth/login", json={"login": "u1", "password": "secret1"}))
    assert login["user"]["roles"] == ["picker"]
    journal = api.ok(api.get("/api/admin/journal", login="admin"))
    actions = [j["action"] for j in journal]
    assert "Роль призначено" in actions and any(a.startswith("Довідник products") for a in actions)
    assert any(j["path"] == "/api/admin/directories/products" and j["status"] == 409 for j in journal)


def test_tc16_offline_queue_replay_is_idempotent(api, demo_asn):
    """ТЗД зберігає скани в черзі офлайн і надсилає їх з Idempotency-Key; повторна відправка не дублює."""
    api.post(f"/api/receiving/shipments/{demo_asn}/start", login="receiver")
    keys = [str(uuid.uuid4()) for _ in range(3)]
    body = {"code": gtin(1), "quantity": 10, "batch_number": "LT1"}
    for _ in range(2):  # перша синхронізація обірвалась — черга надсилається повторно
        for k in keys:
            r = api.post(f"/api/receiving/shipments/{demo_asn}/scan", body, login="receiver",
                         headers={"Idempotency-Key": k})
            assert r.status_code == 200
    assert r.headers.get("Idempotent-Replay") == "true"
    sh = api.ok(api.get(f"/api/receiving/shipments/{demo_asn}", login="receiver"))
    assert next(ln for ln in sh["lines"] if ln["product_code"] == "P-001")["accepted"] == 30


def test_barcodes_generation_and_validation(api):
    for kind, value in [("ean13", gtin(1)), ("code128", "ST-01-02-1"), ("sscc", gs1.make_sscc("4820000", 1)),
                        ("qr", "PICK-000001"), ("gs1", f"(01){gtin(1)}(10)L1")]:
        for fmt in ("svg", "png"):
            r = api.c.get(f"/api/barcodes/{kind}/{value}.{fmt}")
            assert r.status_code == 200, (kind, fmt, r.text)
            assert r.headers["content-type"].startswith("image/")
    bad = gtin(1)[1:-1] + "0" if gtin(1)[-1] != "0" else gtin(1)[1:-1] + "1"
    assert api.c.get(f"/api/barcodes/ean13/{bad}.svg").status_code == 422
    assert api.c.get("/api/barcodes/sscc/123456789012345678.svg").status_code == 422
    v = api.ok(api.get(f"/api/barcodes/validate?code=(01){gtin(1)}(17)301231(10)ABC", login="receiver"))
    assert v["valid"] and v["batch"] == "ABC" and v["expiry"] == "2030-12-31"
    pdf = api.post("/api/barcodes/sheet", {"products": ["P-001", "P-002"], "cells": ["ST-01-01-1"], "new_sscc": 2},
                   login="manager")
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"
    prev = api.ok(api.post("/api/barcodes/sheet/preview", {"products": ["P-001"], "cells": ["PK-00-01"]}))
    assert [x["kind"] for x in prev] == ["ean13", "code128"]
