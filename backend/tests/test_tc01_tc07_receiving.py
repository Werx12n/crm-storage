"""TC-01 Тест приймання за ASN (FR-1.1, FR-1.2); TC-07 Акт розбіжностей і етикетки SSCC (FR-1.3, FR-1.4)."""
from app.seed import gtin
from app.services import gs1


def test_tc01_asn_import_and_scan_receiving(api, demo_asn):
    # FR-1.1: ASN імпортовано, видно на ТЗД з очікуваними рядками
    sh = api.ok(api.post(f"/api/receiving/shipments/{demo_asn}/start", login="receiver"))
    assert sh["status"] == "IN_PROGRESS"
    assert [(ln["product_code"], ln["expected"]) for ln in sh["lines"]] == [("P-001", 100), ("P-005", 50)]

    # FR-1.2: скан GS1-128 з AI (01)(10)(17)(37) — партія, термін і кількість беруться зі штрихкоду
    code = f"(01){gtin(1)}(10)LT1(17)300131(37)60"
    r = api.ok(api.post(f"/api/receiving/shipments/{demo_asn}/scan", {"code": code}, login="receiver"))
    assert r["quantity"] == 60 and r["batch"] == "LT1" and not r["quarantine"]
    # той самий товар, GTIN-13 + ручне введення партії і кількості
    api.ok(api.post(f"/api/receiving/shipments/{demo_asn}/scan",
                    {"code": gtin(1)[1:], "quantity": 40, "batch_number": "LT1"}, login="receiver"))
    api.ok(api.post(f"/api/receiving/shipments/{demo_asn}/scan",
                    {"code": gtin(5), "quantity": 50, "batch_number": "MT1"}, login="receiver"))
    res = api.ok(api.post(f"/api/receiving/shipments/{demo_asn}/complete", login="receiver"))
    assert res["discrepancy_act"] is None
    assert {(ln["product_code"], ln["accepted"]) for ln in res["shipment"]["lines"]} == {("P-001", 100), ("P-005", 50)}

    # залишки збільшено в зоні приймання, створено завдання на розміщення
    stock = api.ok(api.get("/api/stock?zone=RECEIVING"))
    assert sum(x["quantity"] for x in stock if x["product_code"] == "P-001") == 100
    assert len(api.ok(api.get("/api/putaway/tasks"))) == 3
    # подія ПрийманняЗавершено в outbox
    ev = api.ok(api.get("/api/integration/events", login="erp"))
    assert any(e["type"] == "ReceivingCompleted" for e in ev)


def test_tc01_non_gs1_barcode_rejected(api, demo_asn):
    api.post(f"/api/receiving/shipments/{demo_asn}/start", login="receiver")
    bad = gtin(1)[:-1] + str((int(gtin(1)[-1]) + 1) % 10)  # зіпсована контрольна цифра
    for code in (bad, "ABC123", "12345"):
        r = api.post(f"/api/receiving/shipments/{demo_asn}/scan", {"code": code, "quantity": 1, "batch_number": "X"},
                     login="receiver")
        assert r.status_code == 422 and r.json()["code"] == "not_gs1"


def test_tc01_item_not_in_asn_goes_to_quarantine(api, demo_asn):
    api.post(f"/api/receiving/shipments/{demo_asn}/start", login="receiver")
    r = api.ok(api.post(f"/api/receiving/shipments/{demo_asn}/scan",
                        {"code": gtin(9), "quantity": 5, "batch_number": "F1"}, login="receiver"))
    assert r["quarantine"] is True and "карантин" in r["warning"]
    api.ok(api.post(f"/api/receiving/shipments/{demo_asn}/complete", login="receiver"))
    q = api.ok(api.get("/api/stock?zone=QUARANTINE"))
    assert q and q[0]["product_code"] == "P-009" and q[0]["quantity"] == 5
    # карантин не доступний для продажу
    av = api.ok(api.get("/api/stock/available?q=P-009", login="sales"))
    assert av["items"][0]["quarantine"] == 5 and av["items"][0]["available"] == 100


def test_tc01_duplicate_asn_rejected(api, demo_asn):
    r = api.post("/api/integration/edi/asn", {"asn_number": demo_asn, "lines": [{"gtin": gtin(1), "quantity": 1}]},
                 login="erp")
    assert r.status_code == 409


def test_tc07_discrepancy_act_and_sscc_labels(api, demo_asn):
    res = api.receive(demo_asn, [(gtin(1), 90, "LT1"), (gtin(5), 55, "MT1"), (gtin(9), 3, "F1")])
    act = res["discrepancy_act"]
    assert act["number"] == f"АР-{demo_asn}"
    kinds = {ln["product_code"]: (ln["difference"], ln["kind"]) for ln in act["lines"]}
    assert kinds["P-001"] == (-10, "Недостача")
    assert kinds["P-005"] == (5, "Надлишок")
    assert kinds["P-009"][0] == 3 and "карантин" in kinds["P-009"][1]
    # акт збережено і доступний у звіті ВП-03
    rep = api.ok(api.get("/api/analytics/reports/receiving"))
    assert len(rep["rows"]) == 3
    # FR-1.4: SSCC на кожну вантажну одиницю (окрім карантину), валідні за GS1
    labels = res["labels"]
    assert len(labels) == 2
    for lb in labels:
        assert gs1.is_valid_sscc(lb["sscc"]) and lb["gs1"] == f"(00){lb['sscc']}"
    assert len({lb["sscc"] for lb in labels}) == 2
    html = api.get(f"/api/receiving/labels/{labels[0]['sscc']}/print")
    assert html.status_code == 200 and "<svg" in html.text and labels[0]["sscc"] in html.text
