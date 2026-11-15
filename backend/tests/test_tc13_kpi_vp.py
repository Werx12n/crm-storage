"""TC-13 (доповнення): KPI за формулами табл. 1.1, звіти ВП-01…ВП-10, файл операцій для ERP (ВП-09),
кирилиця в PDF звітів і етикеток (вбудований TTF DejaVuSans)."""
import io
from datetime import datetime, timedelta

from pypdf import PdfReader

from app.modules.integration import mock
from app.seed import gtin


def _ship(api, number, lines, due_at=None):
    body = {"number": number, "client": "Клієнт", "lines": [{"product_code": p, "quantity": q} for p, q in lines]}
    if due_at:
        body["due_at"] = due_at
    api.ok(api.post("/api/integration/erp/orders", body, login="erp"))
    api.pick_all()
    for p, q in lines:
        api.ok(api.post(f"/api/shipping/orders/{number}/check", {"code": p, "quantity": q}, login="packer"))
    return api.ok(api.post(f"/api/shipping/orders/{number}/ship", login="packer"))


def _kpi(api, **params):
    q = "&".join(f"{k}={v}" for k, v in params.items())
    return {k["code"]: k for k in api.ok(api.get(f"/api/analytics/kpi?{q}", login="accountant"))["kpi"]}


def test_kpi_table_1_1_formulas(api, demo_asn):
    # приймання + розміщення → dock-to-stock
    res = api.receive(demo_asn, [(gtin(1), 100, "LT1")])
    sscc = res["labels"][0]["sscc"]
    cell = api.ok(api.post(f"/api/putaway/{sscc}/suggest", login="driver"))["cell"]["address"]
    api.ok(api.post(f"/api/putaway/{sscc}/confirm", {"cell": cell}, login="driver"))
    # два замовлення: одне вчасно і повністю, друге — прострочене (строк у минулому)
    _ship(api, "ORD-K1", [("P-006", 2), ("P-012", 1)])
    past = (datetime.utcnow() - timedelta(hours=1)).isoformat()
    _ship(api, "ORD-K2", [("P-005", 1)], due_at=past)
    # третє — частково зарезервоване і ще не відвантажене, строк не минув → не враховується в OTIF
    api.order("ORD-K3", [("P-009", 500)])

    k = _kpi(api)
    assert set(k) == {"picking_accuracy", "inventory_accuracy", "otif", "order_cycle_time", "dock_to_stock",
                      "labor_productivity", "capacity_utilization", "inventory_turnover", "order_handling_cost"}
    assert all(x["formula"] for x in k.values())
    assert k["picking_accuracy"]["value"] == 100.0           # 3 рядки, помилок немає
    assert k["otif"]["value"] == 50.0                        # 1 з 2 (ORD-K2 прострочено)
    assert k["dock_to_stock"]["value"] is not None and k["dock_to_stock"]["value"] >= 0
    occ = api.ok(api.get("/api/analytics/kpi", login="accountant"))["counters"]
    assert k["capacity_utilization"]["value"] == round(100 * occ["occupied_places"] / occ["places"], 1)
    assert k["inventory_turnover"]["value"] == round(occ["shipped_qty"] / occ["avg_stock"], 4)
    assert k["labor_productivity"]["value"] == round(occ["processed_lines"] / occ["man_hours"], 1)
    assert k["order_handling_cost"]["value"] is None         # n/a без витрат
    assert _kpi(api, costs=1000)["order_handling_cost"]["value"] == 500.0  # 1000 грн / 2 замовлення
    # витрати з довідника правил
    rid = next(r["id"] for r in api.ok(api.get("/api/admin/directories/rules")) if r["code"] == "handling_costs_period")
    api.ok(api.put(f"/api/admin/directories/rules/{rid}", {"value": "300"}))
    assert _kpi(api)["order_handling_cost"]["value"] == 150.0


def test_kpi_inventory_accuracy(api):
    inv = api.ok(api.post("/api/inventory", {"cells": ["ST-04-01-1", "ST-04-02-1"], "threshold": 50}))["number"]
    api.ok(api.post("/api/inventory/count", {"cell": "ST-04-01-1", "quantity": 200}, login="counter"))
    api.ok(api.post("/api/inventory/count", {"cell": "ST-04-02-1", "quantity": 99}, login="counter"))
    api.ok(api.post(f"/api/inventory/{inv}/approve"))
    assert _kpi(api)["inventory_accuracy"]["value"] == 50.0
    rep = api.ok(api.get("/api/analytics/reports/inventory", login="accountant"))
    assert rep["code"] == "ВП-04" and len(rep["rows"]) == 2  # опис: усі позиції, не лише розбіжності
    assert {r["result"] for r in rep["rows"]} == {"збіг", "нестача"}


def test_reports_vp07_to_vp10_and_erp_file(api, demo_asn):
    api.receive(demo_asn, [(gtin(1), 100, "LT1"), (gtin(5), 50, "MT1")])
    res = _ship(api, "ORD-V1", [("P-006", 2)])
    api.sync()
    tasks = api.ok(api.get("/api/analytics/reports/tasks", login="accountant"))
    assert tasks["code"] == "ВП-07" and {"Розміщення", "Відбір"} <= {r["type"] for r in tasks["rows"]}
    packing = api.ok(api.get("/api/analytics/reports/packing", login="accountant"))
    assert packing["code"] == "ВП-08" and packing["rows"][0]["sscc"] == res["sscc"]
    delivery = api.ok(api.get("/api/analytics/reports/delivery", login="accountant"))
    assert delivery["code"] == "ВП-10" and delivery["rows"][0]["ttn"].startswith("2045")
    kpi_rep = api.ok(api.get("/api/analytics/reports/kpi", login="accountant"))
    assert kpi_rep["code"] == "ВП-06" and len(kpi_rep["rows"]) == 9

    # ВП-09: файл підтверджених операцій → ERP; повторний виклик без нових операцій нічого не створює
    f = api.ok(api.post("/api/integration/erp/operations-file", login="erp"))
    assert f["count"] >= 4 and f["file_name"].startswith("WMS_WH1_OPS_")
    assert "message" in api.ok(api.post("/api/integration/erp/operations-file", login="erp"))
    api.sync()
    sent = [o for o in mock.STATE["erp_operations"] if o["type"] == "OperationsFile"]
    assert len(sent) == 1 and len(sent[0]["payload"]["operations"]) == f["count"]
    assert {o["type"] for o in sent[0]["payload"]["operations"]} >= {"RECEIPT", "PICK", "SHIPMENT"}
    files = api.ok(api.get("/api/analytics/reports/erp_files", login="accountant"))
    assert files["code"] == "ВП-09" and files["rows"][0]["status"] == "PROCESSED"
    content = api.ok(api.get(f"/api/integration/erp/operations-files/{files['rows'][0]['id']}", login="accountant"))
    assert content["count"] == f["count"]


def _pdf_text(content: bytes) -> tuple[str, set[str]]:
    reader = PdfReader(io.BytesIO(content))
    text = "".join(p.extract_text() for p in reader.pages)
    fonts = set()
    for page in reader.pages:
        for f in (page["/Resources"].get("/Font") or {}).values():
            f = f.get_object()
            fonts.add(str(f.get("/BaseFont")))
            for d in f.get("/DescendantFonts", []):
                fd = d.get_object().get("/FontDescriptor").get_object()
                assert "/FontFile2" in fd, "TTF-шрифт має бути вбудований у PDF"
    return text, fonts


def test_pdf_cyrillic_embedded_font(api):
    rep = api.get("/api/analytics/reports/stock?format=pdf", login="accountant")
    assert rep.status_code == 200
    text, fonts = _pdf_text(rep.content)
    assert "Звіт про залишки товарів" in text and "Молоко" in text
    assert any("DejaVu" in f for f in fonts)
    sheet = api.post("/api/barcodes/sheet", {"products": ["P-001"], "cells": ["ST-01-01-1"]})
    assert sheet.status_code == 200
    text, fonts = _pdf_text(sheet.content)
    assert "Молоко" in text and "Комірка ST-01-01-1" in text
    assert any("DejaVu" in f for f in fonts)
