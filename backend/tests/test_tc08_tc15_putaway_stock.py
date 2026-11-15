"""TC-08 Вибір і підтвердження комірки (FR-2.1, FR-2.2, FR-2.3); TC-15 Запит доступних залишків (FR-2.3)."""
from app.seed import gtin


def _labels(api, demo_asn):
    res = api.receive(demo_asn, [(gtin(1), 100, "LT1"), (gtin(5), 50, "MT1")])
    return {lb["product_code"]: lb["sscc"] for lb in res["labels"]}


def test_tc08_cell_choice_by_rules_and_confirmation(api, demo_asn):
    labels = _labels(api, demo_asn)
    sug = api.ok(api.post(f"/api/putaway/{labels['P-001']}/suggest", login="driver"))
    cell = sug["cell"]
    assert cell["zone"] == "STORAGE" and cell["abc_class"] == "A"  # P-001 клас A → комірка класу A
    # місткість дотримано: 100 × 1.05 кг ≤ вільне місце
    assert cell["capacity"] >= 105
    res = api.ok(api.post(f"/api/putaway/{labels['P-001']}/confirm", {"cell": cell["address"]}, login="driver"))
    assert res["status"] == "DONE"
    # FR-2.3: залишок «товар — партія — комірка»
    rows = [r for r in api.ok(api.get("/api/stock")) if r["cell"] == cell["address"] and r["batch"] == "LT1"]
    assert rows and rows[0]["quantity"] == 100 and rows[0]["product_code"] == "P-001"
    assert not [r for r in api.ok(api.get("/api/stock?zone=RECEIVING")) if r["batch"] == "LT1"]
    # повторне підтвердження неможливе
    assert api.post(f"/api/putaway/{labels['P-001']}/confirm", {"cell": cell["address"]},
                    login="driver").status_code == 409


def test_tc08_other_cell_requires_confirmation_and_capacity(api, demo_asn):
    labels = _labels(api, demo_asn)
    sscc = labels["P-005"]
    sug = api.ok(api.post(f"/api/putaway/(00){sscc}/suggest", login="driver"))
    other = "ST-04-06-2" if sug["cell"]["address"] != "ST-04-06-2" else "ST-04-05-2"
    r = api.post(f"/api/putaway/{sscc}/confirm", {"cell": other}, login="driver")
    assert r.status_code == 409 and r.json()["code"] == "confirm_replace"
    # не зона зберігання — відмова
    r = api.post(f"/api/putaway/{sscc}/confirm", {"cell": "SHP-01", "confirm_replace": True}, login="driver")
    assert r.status_code == 422 and r.json()["code"] == "cell_not_suitable"
    res = api.ok(api.post(f"/api/putaway/{sscc}/confirm", {"cell": other, "confirm_replace": True}, login="driver"))
    assert res["cell"] == other


def test_tc08_capacity_cannot_be_exceeded_and_escalation(api, demo_asn):
    labels = _labels(api, demo_asn)
    # зменшуємо місткість усіх комірок зберігання до 10 кг → вільної комірки немає (2а)
    for c in api.ok(api.get("/api/admin/directories/cells")):
        if c["zone"] == "STORAGE":
            api.ok(api.put(f"/api/admin/directories/cells/{c['id']}", {"capacity": 10}))
    r = api.post(f"/api/putaway/{labels['P-001']}/suggest", login="driver")
    assert r.status_code == 409 and r.json()["code"] == "no_free_cell"
    task = [t for t in api.ok(api.get("/api/putaway/tasks")) if t["label"] == labels["P-001"]][0]
    assert task["status"] == "ESCALATED" and task["assignee"] == "manager"
    r = api.post(f"/api/putaway/{labels['P-001']}/confirm", {"cell": "ST-04-06-2", "confirm_replace": True},
                 login="manager")
    assert r.status_code == 422 and "місткості" in r.json()["detail"]


def test_tc15_available_stock_by_batches(api):
    api.order("ORD-S1", [("P-001", 50)])
    r = api.ok(api.get("/api/stock/available?q=P-001", login="sales"))
    item = r["items"][0]
    # 530 всього; L2611A (60) з коротким терміном недоступна; резерв 50
    assert item["quantity"] == 530 and item["reserved"] == 50
    assert item["available"] == 530 - 60 - 50
    short = next(b for b in item["batches"] if b["batch"] == "L2611A")
    assert short["sellable"] is False and short["available"] == 0
    # пошук за назвою та GTIN
    assert api.ok(api.get("/api/stock/available?q=молоко", login="sales"))["items"][0]["product"]["code"] == "P-001"
    assert api.ok(api.get(f"/api/stock/available?q={gtin(1)}", login="sales"))["found"]


def test_tc15_not_found_suggests_similar(api):
    r = api.ok(api.get("/api/stock/available?q=малоко", login="sales"))
    assert r["found"] is False and any(s["code"] == "P-001" for s in r["suggestions"])
