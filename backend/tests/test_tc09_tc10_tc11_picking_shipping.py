"""TC-09 Резервування FEFO і хвилі відбору (FR-3.1, FR-3.2, FR-3.4); TC-10 Контроль комплектності
і відвантаження (FR-4.1, FR-4.2, FR-4.3); TC-11 Створення відправлення в службі доставки (FR-6.3)."""
from app.modules.integration import mock
from app.seed import gtin


def test_tc09_fefo_reservation_respects_min_shelf_life(api):
    api.order("ORD-F1", [("P-001", 250)])
    task = api.ok(api.post("/api/picking/tasks/next", login="picker"))["task"]
    by_batch = {}
    for ln in task["lines"]:
        by_batch[ln["batch"]] = by_batch.get(ln["batch"], 0) + ln["quantity"]
    # L2611A (20 днів < 30) не резервується; L2612B (230 = 200 + 30 у зоні відбору) першою, далі L2701C
    assert "L2611A" not in by_batch
    assert by_batch == {"L2612B": 230, "L2701C": 20}


def test_tc09_waves_group_orders(api):
    api.order("ORD-W1", [("P-005", 2)], create_task=False)
    api.order("ORD-W2", [("P-012", 3)], create_task=False)
    w = api.ok(api.post("/api/picking/waves", {"wave": True}))
    assert w["wave"].startswith("WAVE-") and set(w["orders"]) == {"ORD-W1", "ORD-W2"}
    assert len(w["tasks"]) == 1 and len(w["tasks"][0]["lines"]) == 2
    api.pick_all()
    for n in ("ORD-W1", "ORD-W2"):
        assert api.ok(api.get(f"/api/picking/orders/{n}"))["status"] == "PICKED"
    assert api.post("/api/picking/waves", {"wave": True}).status_code == 409


def test_tc09_wrong_product_blocked(api):
    api.order("ORD-X1", [("P-006", 2)])
    task = api.ok(api.post("/api/picking/tasks/next", login="picker"))["task"]
    ln = task["lines"][0]
    r = api.post(f"/api/picking/tasks/{task['number']}/confirm", {"cell": ln["from_cell"], "product": gtin(9)},
                 login="picker")
    assert r.status_code == 422 and r.json()["code"] == "wrong_product"
    r = api.post(f"/api/picking/tasks/{task['number']}/confirm", {"cell": "ST-04-06-2", "product": ln["gtin"]},
                 login="picker")
    assert r.json()["code"] == "wrong_cell"


def test_tc09_replenishment_by_min_level(api):
    # P-001: у зоні відбору 30, мінімум 20; відбір 25 → 5 < 20 → завдання на поповнення
    api.order("ORD-RP", [("P-001", 25)])
    task = api.pick_all()
    assert any(ln["from_cell"].startswith("PK-") for ln in task["lines"])
    repl = api.ok(api.get("/api/picking/tasks?type=REPLENISH"))
    assert len(repl) == 1
    ln = repl[0]["lines"][0]
    assert ln["to_cell"] == "PK-00-01" and ln["from_cell"].startswith("ST-") and ln["quantity"] == 35
    api.ok(api.post(f"/api/picking/replenishment/{repl[0]['number']}/confirm", {"cell": "PK-00-01"}, login="driver"))
    pk = [r for r in api.ok(api.get("/api/stock?zone=PICKING")) if r["product_code"] == "P-001"]
    assert sum(r["quantity"] for r in pk) == 40


def test_tc10_completeness_control_and_shipping(api):
    api.order("ORD-SH", [("P-006", 4), ("P-012", 2)])
    r = api.post("/api/shipping/orders/ORD-SH/ship", login="packer")
    assert r.status_code == 409  # ще не скомплектовано
    api.pick_all()
    api.ok(api.post("/api/shipping/orders/ORD-SH/check", {"code": gtin(6), "quantity": 4}, login="packer"))
    # 2а: бракує позиції — відвантаження заблоковано
    r = api.post("/api/shipping/orders/ORD-SH/ship", login="packer")
    assert r.status_code == 409 and r.json()["code"] == "incomplete"
    assert api.post("/api/shipping/orders/ORD-SH/check", {"code": gtin(12), "quantity": 5},
                    login="packer").json()["code"] == "over_check"
    # GS1 з AI 37 (кількість)
    c = api.ok(api.post("/api/shipping/orders/ORD-SH/check", {"code": f"(01){gtin(12)}(37)2"}, login="packer"))
    assert c["complete"]
    res = api.ok(api.post("/api/shipping/orders/ORD-SH/ship", login="packer"))
    pl = res["packing_list"]
    assert pl["number"] == "ПЛ-ORD-SH" and len(pl["lines"]) == 2 and pl["total_weight"] == 4 * 1.55 + 2 * 1.0
    assert res["dispatch"]["ramp"] in ("R1", "R2") and res["dispatch"]["slot_start"]
    # FR-4.2: залишки списано (нічого не лишилось у зоні відвантаження)
    assert not [x for x in api.ok(api.get("/api/stock?zone=SHIPPING")) if x["quantity"]]
    html = api.get(f"/api/shipping/dispatches/{res['dispatch']['id']}/packing-list")
    assert html.status_code == 200 and "Пакувальний лист" in html.text
    # FR-4.3: наступне відвантаження отримує інший слот/рампу
    api.order("ORD-SH2", [("P-006", 1)])
    api.pick_all()
    api.ok(api.post("/api/shipping/orders/ORD-SH2/check", {"code": gtin(6)}, login="packer"))
    res2 = api.ok(api.post("/api/shipping/orders/ORD-SH2/ship", login="packer"))
    assert (res2["dispatch"]["ramp"], res2["dispatch"]["slot_start"]) != (res["dispatch"]["ramp"],
                                                                          res["dispatch"]["slot_start"])


def test_tc11_delivery_shipment_created_with_ttn(api):
    api.order("ORD-D1", [("P-006", 1)])
    api.pick_all()
    api.ok(api.post("/api/shipping/orders/ORD-D1/check", {"code": gtin(6)}, login="packer"))
    res = api.ok(api.post("/api/shipping/orders/ORD-D1/ship", login="packer"))
    api.sync()
    created = mock.STATE["delivery_shipments"]
    assert len(created) == 1 and created[0]["data"]["sscc"] == res["sscc"]
    d = api.ok(api.get("/api/shipping/dispatches"))[0]
    assert d["ttn_number"] == created[0]["ttn"] and d["status"] == "SENT"
    # прийнятиСтатус від служби доставки
    st = api.ok(api.post("/api/integration/delivery/status", {"ttn": d["ttn_number"], "status": "delivered"},
                         login="erp"))
    assert st["status"] == "DELIVERED"
